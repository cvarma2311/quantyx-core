from __future__ import annotations

import re
from typing import Any

from services.ai.anomalies import score_anomalies
from services.ai.config import Settings
from services.ai.db import run_query
from services.ai.join_graph import build_join_from


def _qident(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def _qualify_formula(formula: str, alias: str, table_profile: dict[str, Any]) -> str:
    text = str(formula or "").strip()
    if not text:
        return text
    columns = set(
        list(table_profile.get("eligible_numeric_columns") or [])
        + list(table_profile.get("numeric_columns") or [])
        + list(table_profile.get("categorical_columns") or [])
        + list(table_profile.get("time_columns") or [])
    )
    if not columns:
        return text

    def _replace(match: re.Match[str]) -> str:
        token = match.group(0)
        lower = token.lower()
        if lower in {
            "sum",
            "avg",
            "average",
            "count",
            "distinct",
            "round",
            "nullif",
            "coalesce",
            "case",
            "when",
            "then",
            "else",
            "end",
            "date",
            "date_trunc",
            "extract",
            "year",
            "month",
            "day",
            "from",
            "and",
            "or",
            "not",
            "null",
            "cast",
            "over",
            "partition",
            "by",
            "order",
            "desc",
            "asc",
            "current_date",
        }:
            return token
        if "." in token:
            return token
        if token in columns:
            return f"{alias}.{_qident(token)}"
        return token

    return re.sub(r"\b[a-zA-Z_][a-zA-Z0-9_]*\b", _replace, text)


def _time_grain(metric: dict[str, Any]) -> str:
    grain = str(metric.get("grain") or "day").strip().lower()
    if grain not in {"day", "week", "month", "quarter", "year"}:
        return "day"
    return grain


def _detect_series_anomaly(
    series: list[dict[str, Any]],
    *,
    window: int,
    threshold: float,
    recent_points: int = 5,
    min_percent_change: float = 0.12,
) -> dict[str, Any] | None:
    if not series or len(series) <= window:
        return None
    points = score_anomalies(series, window=window, threshold=threshold)
    if not points:
        return None
    recent = points[-max(int(recent_points), 1):]
    scored: list[tuple[float, TimeSeriesPoint, float]] = []
    for point in recent:
        if point.actual is None:
            continue
        baseline = float(point.baseline or 0.0)
        deviation = float(point.deviation or 0.0)
        severity = abs(deviation) / max(abs(baseline), 1.0)
        pct_change = abs(deviation) / max(abs(baseline), 1.0)
        if not point.is_anomaly and pct_change < float(min_percent_change):
            continue
        score = max(severity, abs(float(point.z_score or 0.0)) / max(threshold, 0.1))
        scored.append((score, point, severity))
    if not scored:
        return None
    scored.sort(key=lambda item: item[0], reverse=True)
    _, selected, severity = scored[0]
    baseline = selected.baseline or 0.0
    deviation = selected.deviation or 0.0
    confidence = min(
        0.99,
        0.5
        + min(abs(float(selected.z_score or 0.0)) / max(threshold, 0.1), 1.0) * 0.25
        + min(severity, 1.0) * 0.2,
    )
    return {
        "period": selected.period,
        "actual": selected.actual,
        "baseline": selected.baseline,
        "deviation": selected.deviation,
        "z_score": selected.z_score,
        "severity_score": round(severity, 4),
        "confidence_score": round(confidence, 4),
        "selection_reason": "recent_window_peak",
    }


def _signal_priority(name: str) -> tuple[int, str]:
    text = str(name or "").strip().lower()
    if not text:
        return (99, text)
    priority_tokens = [
        "production",
        "productivity",
        "output",
        "downtime",
        "hour",
        "net_hour",
        "rejection",
        "loss",
        "utilization",
        "fill",
        "throughput",
    ]
    for idx, token in enumerate(priority_tokens):
        if token in text:
            return (idx, text)
    return (50, text)


def _metric_series(
    settings: Settings,
    *,
    schema_name: str,
    metric: dict[str, Any],
    table_profile: dict[str, Any],
    periods_limit: int,
) -> list[dict[str, Any]]:
    table_name = str(metric.get("base_table") or "").strip()
    time_col = str(metric.get("preferred_time_column") or "").strip()
    formula = str(metric.get("formula") or "").strip()
    if not table_name or not time_col or not formula:
        return []
    q_schema = _qident(schema_name)
    q_table = _qident(table_name)
    alias = "t"
    grain = _time_grain(metric)
    metric_expr = _qualify_formula(formula, alias, table_profile)
    sql = (
        f"SELECT date_trunc('{grain}', {alias}.{_qident(time_col)}) AS period, "
        f"{metric_expr} AS value "
        f"FROM {q_schema}.{q_table} {alias} "
        f"WHERE {alias}.{_qident(time_col)} IS NOT NULL "
        "GROUP BY 1 "
        "ORDER BY 1 ASC "
        "LIMIT %s"
    )
    return run_query(settings, sql, [periods_limit])


def _raw_signal_series(
    settings: Settings,
    *,
    schema_name: str,
    table_name: str,
    time_col: str,
    signal_col: str,
    periods_limit: int,
) -> list[dict[str, Any]]:
    q_schema = _qident(schema_name)
    q_table = _qident(table_name)
    q_time = _qident(time_col)
    q_signal = _qident(signal_col)
    sql = (
        f"SELECT date_trunc('day', {q_time}) AS period, SUM({q_signal}) AS value "
        f"FROM {q_schema}.{q_table} "
        f"WHERE {q_time} IS NOT NULL "
        "GROUP BY 1 "
        "ORDER BY 1 ASC "
        "LIMIT %s"
    )
    return run_query(settings, sql, [periods_limit])


def _parse_period_literal(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    return text.split("+")[0].strip()


def _breakdown_sql(
    *,
    schema_name: str,
    table_name: str,
    time_col: str,
    category_col: str,
    period_literal: str,
    metric_expr: str,
    grain: str,
    limit: int,
) -> str:
    q_schema = _qident(schema_name)
    q_table = _qident(table_name)
    alias = "t"
    q_time = _qident(time_col)
    q_category = _qident(category_col)
    return (
        f"SELECT {alias}.{q_category} AS category_value, "
        f"{metric_expr} AS metric_value "
        f"FROM {q_schema}.{q_table} {alias} "
        f"WHERE {alias}.{q_time} IS NOT NULL "
        f"  AND date_trunc('{grain}', {alias}.{q_time}) = date_trunc('{grain}', %s::timestamp) "
        f"GROUP BY 1 "
        f"ORDER BY metric_value DESC NULLS LAST "
        f"LIMIT {int(limit)}"
    )


def rank_high_signal_investigative_areas(
    settings: Settings,
    *,
    schema_name: str,
    candidate: dict[str, Any],
    table_profile: dict[str, Any],
    max_dimensions: int = 3,
    max_values_per_dimension: int = 3,
) -> list[dict[str, Any]]:
    table_name = str(candidate.get("table_name") or "").strip()
    time_col = str(candidate.get("time_column") or "").strip()
    evidence = candidate.get("evidence") or {}
    period_literal = _parse_period_literal(evidence.get("period"))
    if not table_name or not time_col or not period_literal:
        return []
    cat_cols = [str(col) for col in (table_profile.get("categorical_columns") or []) if str(col or "").strip()]
    if not cat_cols:
        return []

    grain = str(candidate.get("grain") or "day").strip().lower()
    if grain not in {"day", "week", "month", "quarter", "year"}:
        grain = "day"

    metric_expr: str | None = None
    if candidate.get("candidate_type") == "metric":
        metric_expr = _qualify_formula(str(candidate.get("formula") or ""), "t", table_profile)
    elif candidate.get("candidate_type") == "raw_signal":
        raw_signal_name = str(candidate.get("raw_signal_name") or "").strip()
        if raw_signal_name:
            metric_expr = f"SUM(t.{_qident(raw_signal_name)})"
    if not metric_expr:
        return []

    ranked: list[dict[str, Any]] = []
    for category_col in cat_cols[:max_dimensions]:
        try:
            sql = _breakdown_sql(
                schema_name=schema_name,
                table_name=table_name,
                time_col=time_col,
                category_col=category_col,
                period_literal=period_literal,
                metric_expr=metric_expr,
                grain=grain,
                limit=max_values_per_dimension,
            )
            rows = run_query(settings, sql, [period_literal])
        except Exception:
            continue
        numeric_rows = []
        total_value = 0.0
        for row in rows:
            try:
                value = float(row.get("metric_value") or 0.0)
            except (TypeError, ValueError):
                continue
            total_value += value
            numeric_rows.append(
                {
                    "dimension": category_col,
                    "value": row.get("category_value"),
                    "metric_value": value,
                }
            )
        if not numeric_rows or total_value == 0.0:
            continue
        top_item = numeric_rows[0]
        top_share = abs(float(top_item["metric_value"])) / max(abs(total_value), 1.0)
        ranked.append(
            {
                "dimension": category_col,
                "top_value": top_item.get("value"),
                "top_metric_value": round(float(top_item["metric_value"]), 4),
                "top_share": round(top_share, 4),
                "concentration_score": round(top_share, 4),
                "rows": [
                    {
                        **item,
                        "share": round(abs(float(item["metric_value"])) / max(abs(total_value), 1.0), 4),
                    }
                    for item in numeric_rows
                ],
                "rationale": f"Top {category_col} value contributes {round(top_share * 100, 1)}% of the anomaly-period signal.",
            }
        )
    ranked.sort(key=lambda item: float(item.get("concentration_score") or 0.0), reverse=True)
    return ranked[:max_dimensions]


def detect_agentic_anomalies(
    settings: Settings,
    *,
    schema_name: str,
    profiling_stats: dict[str, Any],
    metric_defs: list[dict[str, Any]],
    dashboard_spec: dict[str, Any] | None = None,
    periods_limit: int = 45,
    window: int = 7,
    threshold: float = 1.5,
    min_severity_score: float = 0.0,
    max_metric_candidates: int = 12,
    max_raw_signal_candidates: int = 12,
    max_raw_signals_per_table: int = 6,
) -> dict[str, Any]:
    profiling_tables = {
        str(table.get("name") or "").strip(): table
        for table in (profiling_stats.get("tables") or [])
        if str(table.get("name") or "").strip()
    }
    metric_candidates: list[dict[str, Any]] = []
    for metric in metric_defs[:max_metric_candidates]:
        table_name = str(metric.get("base_table") or "").strip()
        table_profile = profiling_tables.get(table_name)
        if not table_profile:
            continue
        if not metric.get("preferred_time_column"):
            continue
        try:
            series = _metric_series(
                settings,
                schema_name=schema_name,
                metric=metric,
                table_profile=table_profile,
                periods_limit=periods_limit,
            )
        except Exception:
            continue
        detected = _detect_series_anomaly(series, window=window, threshold=threshold)
        if not detected:
            continue
        metric_candidates.append(
            {
                "candidate_type": "metric",
                "anomaly_type": "deviation",
                "metric_id": metric.get("metric_id"),
                "metric_name": metric.get("metric_name"),
                "formula": metric.get("formula"),
                "table_name": table_name,
                "time_column": metric.get("preferred_time_column"),
                "grain": _time_grain(metric),
                "metric_intent": metric.get("metric_intent"),
                "evidence": {
                    **detected,
                    "series_points": series[-min(len(series), 12):],
                },
            }
        )

    raw_signal_candidates: list[dict[str, Any]] = []
    for table_name, table in list(profiling_tables.items())[:max_raw_signal_candidates]:
        time_cols = table.get("time_columns") or []
        numeric_cols = table.get("eligible_numeric_columns") or []
        if not time_cols or not numeric_cols:
            continue
        time_col = str(time_cols[0])
        ranked_signal_cols = sorted(
            [str(col) for col in numeric_cols if str(col or "").strip()],
            key=_signal_priority,
        )
        for signal_col in ranked_signal_cols[:max_raw_signals_per_table]:
            try:
                series = _raw_signal_series(
                    settings,
                    schema_name=schema_name,
                    table_name=table_name,
                    time_col=time_col,
                    signal_col=str(signal_col),
                    periods_limit=periods_limit,
                )
            except Exception:
                continue
            detected = _detect_series_anomaly(series, window=window, threshold=threshold)
            if not detected:
                continue
            raw_signal_candidates.append(
                {
                    "candidate_type": "raw_signal",
                    "anomaly_type": "deviation",
                    "raw_signal_name": str(signal_col),
                    "table_name": table_name,
                    "time_column": time_col,
                    "evidence": {
                        **detected,
                        "series_points": series[-min(len(series), 12):],
                    },
                }
            )

    candidates = metric_candidates + raw_signal_candidates
    candidates.sort(
        key=lambda item: (
            float(((item.get("evidence") or {}).get("severity_score") or 0.0)),
            float(((item.get("evidence") or {}).get("confidence_score") or 0.0)),
        ),
        reverse=True,
    )
    min_severity_score = max(float(min_severity_score or 0.0), 0.0)
    filtered = [
        item
        for item in candidates
        if float(((item.get("evidence") or {}).get("severity_score") or 0.0)) >= min_severity_score
    ]
    top = filtered[:10]
    summary = {
        "candidate_count": len(candidates),
        "candidate_count_after_threshold": len(filtered),
        "metric_candidate_count": len(metric_candidates),
        "raw_signal_candidate_count": len(raw_signal_candidates),
        "top_anomalies": top[:3],
        "source_dashboard_title": (dashboard_spec or {}).get("dashboard_title") or (dashboard_spec or {}).get("title"),
        "min_severity_score": min_severity_score,
        "detection_threshold": threshold,
        "window": window,
    }
    return {
        "summary": summary,
        "candidates": top,
    }


def _preferred_numeric_signal(table_profile: dict[str, Any]) -> str | None:
    numeric_cols = [str(col) for col in (table_profile.get("eligible_numeric_columns") or []) if str(col or "").strip()]
    priority_tokens = [
        "sales",
        "volume",
        "amount",
        "revenue",
        "count",
        "qty",
        "quantity",
        "throughput",
        "production",
    ]
    for token in priority_tokens:
        for col in numeric_cols:
            if token in col.lower():
                return col
    return numeric_cols[0] if numeric_cols else None


def _preferred_dimensions(table_profile: dict[str, Any], limit: int = 3) -> list[str]:
    categorical_cols = [str(col) for col in (table_profile.get("categorical_columns") or []) if str(col or "").strip()]
    blocked = {"id", "created_at", "updated_at", "entity_id"}
    scored: list[tuple[int, str]] = []
    for col in categorical_cols:
        lower = col.lower()
        if lower in blocked:
            continue
        score = 10
        if any(token in lower for token in ("site", "zone", "region", "sales_area", "area", "product", "group", "location")):
            score = 0
        elif lower.endswith("_id"):
            score = 20
        scored.append((score, col))
    scored.sort(key=lambda item: (item[0], item[1]))
    return [col for _, col in scored[:limit]]


def _timeline_sql(
    *,
    schema_name: str,
    table_name: str,
    time_col: str,
    metric_expr: str,
    grain: str,
    periods_limit: int,
) -> str:
    return (
        f"SELECT date_trunc('{grain}', t.{_qident(time_col)}) AS period, {metric_expr} AS value "
        f"FROM {_qident(schema_name)}.{_qident(table_name)} t "
        f"WHERE t.{_qident(time_col)} IS NOT NULL "
        "GROUP BY 1 "
        "ORDER BY 1 ASC "
        f"LIMIT {int(periods_limit)}"
    )


def _category_timeline_sql(
    *,
    schema_name: str,
    table_name: str,
    time_col: str,
    category_col: str,
    metric_expr: str,
    grain: str,
    top_n: int,
    periods_limit: int,
) -> str:
    return (
        "WITH ranked_categories AS ("
        f"  SELECT t.{_qident(category_col)} AS category_value, {metric_expr} AS total_value "
        f"  FROM {_qident(schema_name)}.{_qident(table_name)} t "
        f"  WHERE t.{_qident(time_col)} IS NOT NULL AND t.{_qident(category_col)} IS NOT NULL "
        "  GROUP BY 1 "
        "  ORDER BY total_value DESC NULLS LAST "
        f"  LIMIT {int(top_n)}"
        "), series AS ("
        f"  SELECT date_trunc('{grain}', t.{_qident(time_col)}) AS period, "
        f"         t.{_qident(category_col)} AS category, "
        f"         {metric_expr} AS value "
        f"  FROM {_qident(schema_name)}.{_qident(table_name)} t "
        "  JOIN ranked_categories rc ON rc.category_value = t."
        f"{_qident(category_col)} "
        f"  WHERE t.{_qident(time_col)} IS NOT NULL "
        "  GROUP BY 1, 2 "
        ") "
        "SELECT period, category, value FROM series "
        "ORDER BY period ASC, value DESC NULLS LAST "
        f"LIMIT {int(periods_limit) * max(int(top_n), 1)}"
    )


def _movers_sql(
    *,
    schema_name: str,
    table_name: str,
    time_col: str,
    category_col: str,
    metric_expr: str,
    grain: str,
    limit: int,
) -> str:
    return (
        "WITH period_values AS ("
        f"  SELECT date_trunc('{grain}', t.{_qident(time_col)}) AS period, "
        f"         t.{_qident(category_col)} AS category, "
        f"         {metric_expr} AS value "
        f"  FROM {_qident(schema_name)}.{_qident(table_name)} t "
        f"  WHERE t.{_qident(time_col)} IS NOT NULL AND t.{_qident(category_col)} IS NOT NULL "
        "  GROUP BY 1, 2"
        "), ranked_periods AS ("
        "  SELECT DISTINCT period FROM period_values ORDER BY period DESC LIMIT 2"
        "), latest_period AS ("
        "  SELECT MAX(period) AS period FROM ranked_periods"
        "), previous_period AS ("
        "  SELECT MIN(period) AS period FROM ranked_periods"
        ") "
        "SELECT pv.category, "
        "       MAX(CASE WHEN pv.period = (SELECT period FROM latest_period) THEN pv.value END) AS latest_value, "
        "       MAX(CASE WHEN pv.period = (SELECT period FROM previous_period) THEN pv.value END) AS previous_value, "
        "       COALESCE(MAX(CASE WHEN pv.period = (SELECT period FROM latest_period) THEN pv.value END), 0) "
        "       - COALESCE(MAX(CASE WHEN pv.period = (SELECT period FROM previous_period) THEN pv.value END), 0) AS delta_value "
        "FROM period_values pv "
        "GROUP BY 1 "
        "ORDER BY ABS(delta_value) DESC NULLS LAST "
        f"LIMIT {int(limit)}"
    )


def _join_timeline_sql(
    *,
    schema_name: str,
    left_table: str,
    right_table: str,
    left_time_col: str,
    metric_expr: str,
    join_edges: list[dict[str, Any]],
    periods_limit: int,
) -> str | None:
    try:
        from_sql, alias_map = build_join_from([left_table, right_table], _qident(schema_name), joins=join_edges)
    except Exception:
        return None
    left_alias = alias_map.get(left_table) or "a"
    return (
        f"SELECT date_trunc('month', {left_alias}.{_qident(left_time_col)}) AS period, {metric_expr} AS value "
        f"{from_sql} "
        f"WHERE {left_alias}.{_qident(left_time_col)} IS NOT NULL "
        "GROUP BY 1 "
        "ORDER BY 1 ASC "
        f"LIMIT {int(periods_limit)}"
    )


def build_anomaly_fallback_exploration(
    settings: Settings,
    *,
    schema_name: str,
    profiling_stats: dict[str, Any],
    metric_defs: list[dict[str, Any]],
    dashboard_spec: dict[str, Any] | None = None,
    join_edges: list[dict[str, Any]] | None = None,
    scoped_conn: Any = None,
    periods_limit: int = 24,
    top_n_categories: int = 3,
) -> dict[str, Any]:
    profiling_tables = {
        str(table.get("name") or "").strip(): table
        for table in (profiling_stats.get("tables") or [])
        if str(table.get("name") or "").strip()
    }
    queries: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []
    seen_sql: set[str] = set()

    def _run(query_id: str, title: str, reason: str, sql: str) -> None:
        normalized_sql = " ".join(str(sql or "").split())
        if not normalized_sql or normalized_sql in seen_sql:
            return
        seen_sql.add(normalized_sql)
        try:
            rows = run_query(settings, sql, [], scoped_conn=scoped_conn)
        except Exception:
            return
        if not rows:
            return
        queries.append(
            {
                "query_id": query_id,
                "title": title,
                "reason": reason,
                "sql": sql,
                "row_count": len(rows),
                "rows": rows[: min(len(rows), 120)],
            }
        )

    prioritized_metrics = [metric for metric in metric_defs if str(metric.get("base_table") or "").strip()]
    prioritized_metrics = prioritized_metrics[:3]

    for metric in prioritized_metrics:
        table_name = str(metric.get("base_table") or "").strip()
        time_col = str(metric.get("preferred_time_column") or "").strip()
        table_profile = profiling_tables.get(table_name) or {}
        if not table_name or not time_col or not table_profile:
            continue
        grain = _time_grain(metric)
        metric_expr = _qualify_formula(str(metric.get("formula") or ""), "t", table_profile)
        metric_name = str(metric.get("metric_name") or metric.get("metric_id") or table_name)
        if metric_expr:
            timeline_sql = _timeline_sql(
                schema_name=schema_name,
                table_name=table_name,
                time_col=time_col,
                metric_expr=metric_expr,
                grain=grain,
                periods_limit=periods_limit,
            )
            _run(f"fallback_timeline_{metric_name}", f"{metric_name} over time", "timeline_overview", timeline_sql)
            dims = _preferred_dimensions(table_profile, limit=2)
            for category_col in dims:
                category_sql = _category_timeline_sql(
                    schema_name=schema_name,
                    table_name=table_name,
                    time_col=time_col,
                    category_col=category_col,
                    metric_expr=metric_expr,
                    grain=grain,
                    top_n=top_n_categories,
                    periods_limit=min(periods_limit, 18),
                )
                _run(
                    f"fallback_category_trend_{metric_name}_{category_col}",
                    f"{metric_name} by {category_col} over time",
                    "category_trend",
                    category_sql,
                )
                movers_sql = _movers_sql(
                    schema_name=schema_name,
                    table_name=table_name,
                    time_col=time_col,
                    category_col=category_col,
                    metric_expr=metric_expr,
                    grain=grain,
                    limit=10,
                )
                _run(
                    f"fallback_movers_{metric_name}_{category_col}",
                    f"{metric_name} movers by {category_col}",
                    "recent_movers",
                    movers_sql,
                )
            break

    if not queries:
        for table_name, table_profile in profiling_tables.items():
            time_cols = [str(col) for col in (table_profile.get("time_columns") or []) if str(col or "").strip()]
            signal_col = _preferred_numeric_signal(table_profile)
            if not time_cols or not signal_col:
                continue
            time_col = time_cols[0]
            metric_expr = f"SUM(t.{_qident(signal_col)})"
            timeline_sql = _timeline_sql(
                schema_name=schema_name,
                table_name=table_name,
                time_col=time_col,
                metric_expr=metric_expr,
                grain="month",
                periods_limit=periods_limit,
            )
            _run(
                f"fallback_raw_timeline_{table_name}_{signal_col}",
                f"{signal_col} over time",
                "timeline_overview",
                timeline_sql,
            )
            for category_col in _preferred_dimensions(table_profile, limit=2):
                category_sql = _category_timeline_sql(
                    schema_name=schema_name,
                    table_name=table_name,
                    time_col=time_col,
                    category_col=category_col,
                    metric_expr=metric_expr,
                    grain="month",
                    top_n=top_n_categories,
                    periods_limit=min(periods_limit, 18),
                )
                _run(
                    f"fallback_raw_category_{table_name}_{signal_col}_{category_col}",
                    f"{signal_col} by {category_col} over time",
                    "category_trend",
                    category_sql,
                )
            break

    if join_edges and len(profiling_tables) >= 2:
        metric = prioritized_metrics[0] if prioritized_metrics else None
        if metric:
            left_table = str(metric.get("base_table") or "").strip()
            left_time_col = str(metric.get("preferred_time_column") or "").strip()
            for edge in join_edges:
                left = str(edge.get("left_table") or edge.get("left") or "").split(".")[-1].strip()
                right = str(edge.get("right_table") or edge.get("right") or "").split(".")[-1].strip()
                if not left or not right or left_table not in {left, right}:
                    continue
                peer_table = right if left == left_table else left
                table_profile = profiling_tables.get(left_table) or {}
                metric_expr = _qualify_formula(str(metric.get("formula") or ""), "a", table_profile)
                if not left_time_col or not metric_expr:
                    continue
                join_sql = _join_timeline_sql(
                    schema_name=schema_name,
                    left_table=left_table,
                    right_table=peer_table,
                    left_time_col=left_time_col,
                    metric_expr=metric_expr,
                    join_edges=join_edges,
                    periods_limit=min(periods_limit, 18),
                )
                if join_sql:
                    _run(
                        f"fallback_join_{left_table}_{peer_table}",
                        f"{metric.get('metric_name') or left_table} joined timeline with {peer_table}",
                        "joined_timeline",
                        join_sql,
                    )
                break

    for item in queries:
        rows = [row for row in (item.get("rows") or []) if isinstance(row, dict)]
        if not rows:
            continue
        if {"period", "value"} <= set(rows[0].keys()):
            detected = _detect_series_anomaly(rows, window=5, threshold=1.0, recent_points=6, min_percent_change=0.05)
            if detected:
                observations.append(
                    {
                        "query_id": item.get("query_id"),
                        "title": item.get("title"),
                        "type": "soft_timeline_anomaly",
                        "detail": {
                            "period": detected.get("period"),
                            "actual": detected.get("actual"),
                            "baseline": detected.get("baseline"),
                            "deviation": detected.get("deviation"),
                            "severity_score": detected.get("severity_score"),
                        },
                    }
                )
        elif {"category", "value"} <= set(rows[0].keys()) or {"category", "latest_value", "delta_value"} & set(rows[0].keys()):
            top_row = rows[0]
            observations.append(
                {
                    "query_id": item.get("query_id"),
                    "title": item.get("title"),
                    "type": "category_shift",
                    "detail": top_row,
                }
            )

    return {
        "mode": "table_native_exploration",
        "queries": queries[:6],
        "observations": observations[:8],
        "source_dashboard_title": (dashboard_spec or {}).get("dashboard_title") or (dashboard_spec or {}).get("title"),
    }
