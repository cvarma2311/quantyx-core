from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from services.ai.catalog import Dimension, Metric, resolve_ref
from services.ai.join_graph import build_join_from


_REF_PATTERN = re.compile(
    r"\b([a-zA-Z_][a-zA-Z0-9_]*)\.([a-zA-Z_][a-zA-Z0-9_]*)\.([a-zA-Z_][a-zA-Z0-9_]*)\b"
)
_TABLE_PATTERN = re.compile(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\.([a-zA-Z_][a-zA-Z0-9_]*)\b")
_ALLOWED_OPERATORS = {"=", "!=", ">", ">=", "<", "<=", "IN", "ILIKE"}
_AGGREGATE_SQL_PATTERN = re.compile(r"\b(SUM|AVG|COUNT|MIN|MAX)\s*\(", re.IGNORECASE)


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


def _is_already_aggregated(metric_sql: str) -> bool:
    return bool(_AGGREGATE_SQL_PATTERN.match(metric_sql or ""))


def _required_tables_for_metric(metric: Metric, schema: str) -> set[str]:
    metric_sql = _render_metric_sql(metric, schema)
    return _collect_tables(metric_sql)


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


def _rewrite_dimension_sql(
    dim_sql: str,
    base_table: str | None,
    base_alias: str | None,
    alias_map: dict[str, str] | None,
) -> str:
    if not base_table:
        if not alias_map:
            return dim_sql
        match = _REF_PATTERN.fullmatch(dim_sql)
        if not match:
            return dim_sql
        table = f"{match.group(1)}.{match.group(2)}"
        alias = alias_map.get(table) or alias_map.get(match.group(2))
        if alias:
            return f"{alias}.{match.group(3)}"
        return dim_sql

    match = _REF_PATTERN.fullmatch(dim_sql)
    if not match:
        return dim_sql

    base_schema, base_name = base_table.split(".", 1)
    _, _, column = match.groups()
    if base_alias:
        return f"{base_alias}.{column}"
    return f"{base_schema}.{base_name}.{column}"


def _rewrite_metric_sql(
    metric: Metric,
    metric_sql: str,
    schema: str,
    alias_map: dict[str, str] | None,
) -> str:
    if metric.name == "sales_vs_target_achievement_pct":
        actuals_prefix = f"{schema}.fact_hpcl_sales_monthly_actuals."
        targets_prefix = f"{schema}.fact_hpcl_sales_monthly_targets."
        actuals_alias = alias_map.get(f"{schema}.fact_hpcl_sales_monthly_actuals", "a") if alias_map else "a"
        targets_alias = alias_map.get(f"{schema}.fact_hpcl_sales_monthly_targets", "t") if alias_map else "t"
        metric_sql = metric_sql.replace(actuals_prefix, f"{actuals_alias}.")
        metric_sql = metric_sql.replace(targets_prefix, f"{targets_alias}.")
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
    order_by_metric: bool = True,
    order_desc: bool = True,
    join_edges: list[dict[str, object]] | None = None,
) -> BuiltQuery:
    if not metrics:
        raise ValueError("At least one metric is required")

    dimensions = _normalize_group_dimensions(metrics, dimensions)
    required_tables: set[str] = set()
    for metric in metrics:
        required_tables.update(_required_tables_for_metric(metric, schema))
    for dim in dimensions:
        required_tables.update(_collect_tables(_render_dimension_sql(dim, schema)))
    for flt in filters:
        if flt.field in filter_dimensions:
            required_tables.update(_collect_tables(_render_dimension_sql(filter_dimensions[flt.field], schema)))

    if not required_tables:
        raise ValueError("No tables resolved for query")
    if len(required_tables) == 1:
        table_name = sorted(required_tables)[0]
        base_sql = f"FROM {table_name}"
        base_table = table_name
        base_alias = None
        alias_map = None
    else:
        from_sql, alias_map = build_join_from(sorted(required_tables), schema, joins=join_edges)
        base_sql = from_sql
        base_table = None
        base_alias = None

    metric_tables = set()
    select_parts = []

    for dim in dimensions:
        dim_sql = _rewrite_dimension_sql(
            _render_dimension_sql(dim, schema),
            base_table,
            base_alias,
            alias_map,
        )
        dim_alias = dim.name.replace('"', '""')
        select_parts.append(f'{dim_sql} AS "{dim_alias}"')
        metric_tables.update(_collect_tables(dim_sql))

    for metric in metrics:
        metric_sql = _render_metric_sql(metric, schema)
        if metric.metric_type == "sum" and not _is_already_aggregated(metric_sql):
            metric_sql = f"SUM({metric_sql})"
        elif metric.metric_type in {"average", "avg"} and not _is_already_aggregated(metric_sql):
            metric_sql = f"AVG({metric_sql})"
        metric_sql = _rewrite_metric_sql(metric, metric_sql, schema, alias_map)
        metric_sql = _rewrite_dimension_sql(metric_sql, base_table, base_alias, alias_map)
        alias = metric.name.replace('"', '""')
        select_parts.append(f'{metric_sql} AS "{alias}"')
        metric_tables.update(_collect_tables(metric_sql))

    for flt in filters:
        if flt.field in filter_dimensions:
            dim_sql = _rewrite_dimension_sql(
                _render_dimension_sql(filter_dimensions[flt.field], schema),
                base_table,
                base_alias,
                alias_map,
            )
            metric_tables.update(_collect_tables(dim_sql))

    rewritten_dimensions = dict(filter_dimensions)
    for flt in filters:
        dim = filter_dimensions[flt.field]
        dim_sql = _rewrite_dimension_sql(
            _render_dimension_sql(dim, schema),
            base_table,
            base_alias,
            alias_map,
        )
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
            _rewrite_dimension_sql(
                _render_dimension_sql(dim, schema),
                base_table,
                base_alias,
                alias_map,
            )
            for dim in dimensions
        )

    where_clause = f" WHERE {where_sql}" if where_sql else ""

    order_clause = ""
    if order_by_metric and metrics:
        # When the leading dimension is time-based, order by it ASC for correct
        # chronological display rather than ordering by metric value.
        _time_tokens = {"date", "day", "week", "month", "quarter", "year", "period"}
        _first_dim_name = dimensions[0].name.lower() if dimensions else ""
        _first_dim_is_time = any(token in _first_dim_name for token in _time_tokens)
        if _first_dim_is_time and dimensions:
            time_alias = dimensions[0].name.replace('"', '""')
            order_clause = f' ORDER BY "{time_alias}" ASC'
        else:
            alias = metrics[0].name.replace('"', '""')
            direction = "DESC" if order_desc else "ASC"
            order_clause = f' ORDER BY "{alias}" {direction}'
    sql = f"SELECT {', '.join(select_parts)} {base_sql}{where_clause}{group_by}{order_clause} LIMIT {limit}"
    return BuiltQuery(sql=sql, params=where_params)
