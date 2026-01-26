from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from services.ai.catalog import MetricCatalog, resolve_ref
from services.ai.config import Settings
from services.ai.db import run_query
from services.ai.join_graph import build_join_from


_TABLE_PATTERN = r"\b([a-zA-Z_][a-zA-Z0-9_]*)\.([a-zA-Z_][a-zA-Z0-9_]*)\.([a-zA-Z_][a-zA-Z0-9_]*)\b"


@dataclass(frozen=True)
class TimeSeriesPoint:
    period: str
    actual: float | None
    baseline: float | None
    deviation: float | None
    z_score: float | None
    is_anomaly: bool


def _collect_tables(sql: str) -> set[str]:
    import re

    return {f"{m.group(1)}.{m.group(2)}" for m in re.finditer(_TABLE_PATTERN, sql)}


def _rewrite_with_alias(sql: str, alias_map: dict[str, str] | None) -> str:
    if not alias_map:
        return sql
    import re

    def _replace(match: re.Match) -> str:
        schema, table, column = match.groups()
        alias = alias_map.get(f"{schema}.{table}") or alias_map.get(table)
        if alias:
            return f"{alias}.{column}"
        return match.group(0)

    return re.sub(_TABLE_PATTERN, _replace, sql)


def _build_filters(filters: list[dict], dimensions: dict[str, Any], schema: str, alias_map: dict[str, str] | None) -> tuple[str, list[object]]:
    clauses = []
    params: list[object] = []
    for flt in filters:
        field = flt["field"]
        operator = flt["operator"]
        value = flt["value"]
        if field not in dimensions:
            continue
        dim_sql = resolve_ref(dimensions[field].sql, schema)
        dim_sql = _rewrite_with_alias(dim_sql, alias_map)
        if operator == "IN":
            placeholders = ",".join(["%s"] * len(value))
            clauses.append(f"{dim_sql} IN ({placeholders})")
            params.extend(list(value))
        else:
            clauses.append(f"{dim_sql} {operator} %s")
            params.append(value)
    return (" AND ".join(clauses), params)


def build_timeseries(
    settings: Settings,
    catalog: MetricCatalog,
    metric_name: str,
    grain: str,
    filters: list[dict],
    limit: int,
) -> list[dict[str, Any]]:
    if metric_name not in catalog.metrics:
        raise ValueError(f"Unknown metric: {metric_name}")
    metric = catalog.metrics[metric_name]
    if "date_day" not in metric.dimensions:
        raise ValueError("Metric does not support date_day for time-series")
    date_dim = catalog.dimensions["date_day"]
    period_sql = f"date_trunc('{grain}', {resolve_ref(date_dim.sql, settings.db_schema)})"

    metric_sql = resolve_ref(metric.sql, settings.db_schema)
    tables = _collect_tables(metric_sql)
    alias_map = None
    if len(tables) > 1:
        from_sql, alias_map = build_join_from(sorted(tables), settings.db_schema)
    else:
        table = sorted(tables)[0]
        from_sql = f"FROM {table}"

    period_sql = _rewrite_with_alias(period_sql, alias_map)
    metric_sql = _rewrite_with_alias(metric_sql, alias_map)

    if metric.metric_type == "sum":
        metric_expr = f"SUM({metric_sql})"
    elif metric.metric_type in {"average", "avg"}:
        metric_expr = f"AVG({metric_sql})"
    else:
        metric_expr = metric_sql

    where_sql, params = _build_filters(filters, catalog.dimensions, settings.db_schema, alias_map)
    where_clause = f" WHERE {where_sql}" if where_sql else ""
    sql = (
        f"SELECT {period_sql} AS period, {metric_expr} AS value "
        f"{from_sql}{where_clause} "
        f"GROUP BY period ORDER BY period ASC LIMIT %s"
    )
    params.append(limit)
    return run_query(settings, sql, params)


def normalize_period(value: str | None) -> str | None:
    if not value:
        return None
    return value.split(" ")[0]


def compute_driver_breakdown(
    settings: Settings,
    catalog: MetricCatalog,
    metric_name: str,
    grain: str,
    period: str,
    dimensions: list[str],
    filters: list[dict],
    top_n: int = 5,
) -> list[dict[str, Any]]:
    if metric_name not in catalog.metrics:
        return []
    metric = catalog.metrics[metric_name]
    if "date_day" not in metric.dimensions:
        return []
    if grain not in {"day", "month", "quarter", "year"}:
        raise ValueError("Unsupported grain")

    date_dim = catalog.dimensions["date_day"]
    period_sql = f"date_trunc('{grain}', {resolve_ref(date_dim.sql, settings.db_schema)})"
    metric_sql = resolve_ref(metric.sql, settings.db_schema)
    tables = _collect_tables(metric_sql)
    alias_map = None
    if len(tables) > 1:
        from_sql, alias_map = build_join_from(sorted(tables), settings.db_schema)
    else:
        table = sorted(tables)[0]
        from_sql = f"FROM {table}"

    period_sql = _rewrite_with_alias(period_sql, alias_map)
    metric_sql = _rewrite_with_alias(metric_sql, alias_map)

    if metric.metric_type == "sum":
        metric_expr = f"SUM({metric_sql})"
    elif metric.metric_type in {"average", "avg"}:
        metric_expr = f"AVG({metric_sql})"
    else:
        return []

    allowed_dims = [dim for dim in dimensions if dim in metric.dimensions]
    if not allowed_dims:
        return []

    dim_sql = resolve_ref(catalog.dimensions[allowed_dims[0]].sql, settings.db_schema)
    dim_sql = _rewrite_with_alias(dim_sql, alias_map)

    where_clauses = [f"{period_sql} = date_trunc('{grain}', %s::date)"]
    params: list[object] = [period]
    filter_sql, filter_params = _build_filters(filters, catalog.dimensions, settings.db_schema, alias_map)
    if filter_sql:
        where_clauses.append(filter_sql)
        params.extend(filter_params)

    where_clause = " AND ".join(where_clauses)
    sql = (
        f"SELECT {dim_sql} AS dimension_value, {metric_expr} AS metric_value "
        f"{from_sql} WHERE {where_clause} "
        f"GROUP BY {dim_sql} ORDER BY metric_value DESC LIMIT %s"
    )
    params.append(top_n)
    rows = run_query(settings, sql, params)
    return [
        {
            "dimension": allowed_dims[0],
            "dimension_value": row.get("dimension_value"),
            "metric_value": row.get("metric_value"),
        }
        for row in rows
    ]


def compute_correlations(
    settings: Settings,
    catalog: MetricCatalog,
    period: str,
    grain: str,
    filters: list[dict],
    related_metrics: list[str],
    window: int,
    threshold: float,
) -> list[dict[str, Any]]:
    correlations: list[dict[str, Any]] = []
    for metric_name in related_metrics:
        if metric_name not in catalog.metrics:
            continue
        series = build_timeseries(
            settings,
            catalog,
            metric_name=metric_name,
            grain=grain,
            filters=filters,
            limit=36,
        )
        points = score_anomalies(series, window=window, threshold=threshold)
        match = None
        for point in points:
            if normalize_period(point.period) == period:
                match = point
                break
        if not match:
            continue
        correlations.append(
            {
                "metric_name": metric_name,
                "actual": match.actual,
                "baseline": match.baseline,
                "deviation": match.deviation,
                "z_score": match.z_score,
                "is_anomaly": match.is_anomaly,
            }
        )
    return correlations


def score_anomalies(
    series: list[dict[str, Any]],
    window: int,
    threshold: float,
) -> list[TimeSeriesPoint]:
    points: list[TimeSeriesPoint] = []
    values: list[float] = []

    for row in series:
        value = row.get("value")
        try:
            value_f = float(value) if value is not None else None
        except (TypeError, ValueError):
            value_f = None

        baseline = None
        deviation = None
        z_score = None
        is_anomaly = False

        if value_f is not None and len(values) >= window:
            window_values = values[-window:]
            mean = sum(window_values) / len(window_values)
            variance = sum((v - mean) ** 2 for v in window_values) / len(window_values)
            std = math.sqrt(variance)
            baseline = mean
            deviation = value_f - mean
            if std > 0:
                z_score = abs(deviation) / std
                is_anomaly = z_score >= threshold

        if value_f is not None:
            values.append(value_f)

        points.append(
            TimeSeriesPoint(
                period=str(row.get("period")),
                actual=value_f,
                baseline=baseline,
                deviation=deviation,
                z_score=z_score,
                is_anomaly=is_anomaly,
            )
        )

    return points
