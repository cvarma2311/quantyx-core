from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from services.ai.catalog import Dimension, Metric, resolve_ref


_REF_PATTERN = re.compile(
    r"\b([a-zA-Z_][a-zA-Z0-9_]*)\.([a-zA-Z_][a-zA-Z0-9_]*)\.([a-zA-Z_][a-zA-Z0-9_]*)\b"
)
_TABLE_PATTERN = re.compile(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\.([a-zA-Z_][a-zA-Z0-9_]*)\b")
_ALLOWED_OPERATORS = {"=", "!=", ">", ">=", "<", "<=", "IN", "ILIKE"}


@dataclass(frozen=True)
class Filter:
    field: str
    operator: str
    value: object


@dataclass(frozen=True)
class BuiltQuery:
    sql: str
    params: list[object]


def _collect_tables(sql: str) -> set[str]:
    tables = {f"{m.group(1)}.{m.group(2)}" for m in _REF_PATTERN.finditer(sql)}
    if tables:
        return tables
    return {f"{m.group(1)}.{m.group(2)}" for m in _TABLE_PATTERN.finditer(sql)}


def _render_dimension_sql(dim: Dimension, schema: str) -> str:
    return resolve_ref(dim.sql, schema)


def _render_metric_sql(metric: Metric, schema: str) -> str:
    return resolve_ref(metric.sql, schema)


def _build_filters(filters: Iterable[Filter], dimensions: dict[str, Dimension], schema: str) -> tuple[str, list[object]]:
    clauses = []
    params: list[object] = []

    for flt in filters:
        if flt.operator not in _ALLOWED_OPERATORS:
            raise ValueError(f"Unsupported operator: {flt.operator}")
        if flt.field not in dimensions:
            raise ValueError(f"Unknown dimension: {flt.field}")
        dim_sql = _render_dimension_sql(dimensions[flt.field], schema)

        if flt.operator == "IN":
            if not isinstance(flt.value, (list, tuple)) or not flt.value:
                raise ValueError("IN operator requires a non-empty list")
            placeholders = ",".join(["%s"] * len(flt.value))
            clauses.append(f"{dim_sql} IN ({placeholders})")
            params.extend(list(flt.value))
        else:
            clauses.append(f"{dim_sql} {flt.operator} %s")
            params.append(flt.value)

    return (" AND ".join(clauses), params)


def _build_base_sql(metric: Metric, schema: str) -> tuple[str, str | None, str | None]:
    if metric.name == "sales_vs_target_achievement_pct":
        base_table = f"{schema}.fact_hpcl_sales_monthly_actuals"
        return (
            f"FROM {schema}.fact_hpcl_sales_monthly_actuals a "
            f"JOIN {schema}.fact_hpcl_sales_monthly_targets t "
            "ON a.month_name = t.month_name "
            "AND a.fiscal_year = t.fiscal_year "
            "AND a.sbu_name = t.sbu_name "
            "AND a.zone_name = t.zone_name "
            "AND a.region_name = t.region_name "
            "AND a.sales_area_name = t.sales_area_name "
            "AND a.product_name = t.product_name"
        ), base_table, "a"

    metric_sql = _render_metric_sql(metric, schema)
    tables = _collect_tables(metric_sql)
    if len(tables) != 1:
        raise ValueError("Multi-table metrics are not supported yet")
    table_name = sorted(tables)[0]
    return f"FROM {table_name}", table_name, None


def _rewrite_dimension_sql(dim_sql: str, base_table: str | None, base_alias: str | None) -> str:
    if not base_table:
        return dim_sql

    match = _REF_PATTERN.fullmatch(dim_sql)
    if not match:
        return dim_sql

    base_schema, base_name = base_table.split(".", 1)
    _, _, column = match.groups()
    if base_alias:
        return f"{base_alias}.{column}"
    return f"{base_schema}.{base_name}.{column}"


def _rewrite_metric_sql(metric: Metric, metric_sql: str, schema: str) -> str:
    if metric.name == "sales_vs_target_achievement_pct":
        actuals_prefix = f"{schema}.fact_hpcl_sales_monthly_actuals."
        targets_prefix = f"{schema}.fact_hpcl_sales_monthly_targets."
        metric_sql = metric_sql.replace(actuals_prefix, "a.")
        metric_sql = metric_sql.replace(targets_prefix, "t.")
    return metric_sql


def _normalize_group_dimensions(metrics: list[Metric], dimensions: list[Dimension]) -> list[Dimension]:
    metric_names = {metric.name for metric in metrics}
    if metric_names & {"hpcl_vs_company_sales_diff_tmt", "hpcl_vs_company_sales_ratio"}:
        return [dim for dim in dimensions if dim.name != "company_name"]
    return dimensions


def build_query(
    metrics: list[Metric],
    dimensions: list[Dimension],
    filter_dimensions: dict[str, Dimension],
    filters: list[Filter],
    schema: str,
    limit: int,
) -> BuiltQuery:
    if not metrics:
        raise ValueError("At least one metric is required")

    base_sql, base_table, base_alias = _build_base_sql(metrics[0], schema)
    dimensions = _normalize_group_dimensions(metrics, dimensions)

    for metric in metrics[1:]:
        metric_base_sql, _, _ = _build_base_sql(metric, schema)
        if metric_base_sql != base_sql:
            raise ValueError("All metrics must be from the same base table")

    metric_tables = set()
    select_parts = []

    for dim in dimensions:
        dim_sql = _rewrite_dimension_sql(_render_dimension_sql(dim, schema), base_table, base_alias)
        select_parts.append(dim_sql)
        metric_tables.update(_collect_tables(dim_sql))

    for metric in metrics:
        metric_sql = _render_metric_sql(metric, schema)
        if metric.metric_type == "sum":
            metric_sql = f"SUM({metric_sql})"
        elif metric.metric_type in {"average", "avg"}:
            metric_sql = f"AVG({metric_sql})"
        metric_sql = _rewrite_metric_sql(metric, metric_sql, schema)
        metric_sql = _rewrite_dimension_sql(metric_sql, base_table, base_alias)
        select_parts.append(f"{metric_sql} AS {metric.name}")
        metric_tables.update(_collect_tables(metric_sql))

    for flt in filters:
        if flt.field in filter_dimensions:
            dim_sql = _rewrite_dimension_sql(
                _render_dimension_sql(filter_dimensions[flt.field], schema),
                base_table,
                base_alias,
            )
            metric_tables.update(_collect_tables(dim_sql))

    rewritten_dimensions = dict(filter_dimensions)
    for flt in filters:
        dim = filter_dimensions[flt.field]
        dim_sql = _rewrite_dimension_sql(_render_dimension_sql(dim, schema), base_table, base_alias)
        rewritten_dimensions[dim.name] = Dimension(
            name=dim.name,
            description=dim.description,
            data_type=dim.data_type,
            sql=dim_sql,
        )

    where_sql, where_params = _build_filters(filters, rewritten_dimensions, schema)

    group_by = ""
    if dimensions:
        group_by = " GROUP BY " + ", ".join(
            _rewrite_dimension_sql(_render_dimension_sql(dim, schema), base_table, base_alias)
            for dim in dimensions
        )

    where_clause = f" WHERE {where_sql}" if where_sql else ""

    sql = f"SELECT {', '.join(select_parts)} {base_sql}{where_clause}{group_by} LIMIT {limit}"
    return BuiltQuery(sql=sql, params=where_params)
