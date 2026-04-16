"""
Phase 43 — Statistical Correlation, Anomaly, and Forward Pattern Agent.

This module is the pure statistical computation layer. It loads KPI snapshots
from quantyx_chart_requests (using rows_json + run_id scoping), runs anomaly
detection, cross-metric correlation, investigation threading, and forward
projections, then persists results via correlation_store.

No table-specific SQL is written here — all data comes from rows_json already
stored during the agentic deployment run.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import urllib.request
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

import numpy as np
import psycopg2
from psycopg2.extras import RealDictCursor

from services.ai.config import Settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PERIOD_KEY_WORDS = frozenset(
    {
        "period", "date", "month", "week", "year", "quarter", "day",
        "time", "timestamp", "dt", "ym", "yearmonth", "fiscal",
        "created", "updated", "at",
    }
)

_ISO_DATE_RE = re.compile(
    r"^\d{4}-\d{2}(-\d{2})?( \d{2}:\d{2}(:\d{2})?)?$"
)

_ANOMALY_ZSCORE_THRESHOLD = 2.5
_ANOMALY_IQR_MULTIPLIER = 1.5
_MIN_SERIES_LEN = 4          # below this, skip anomaly / correlation
_CORRELATION_MIN_R = 0.20    # prune weak pairs
_INVESTIGATION_MIN_CONF = 0.35
_FACT_SOURCE_MIN_SNAPSHOTS = 2
_DAY_ID_COL_PATTERN = re.compile(r"(?i)^(day[_\s]?id|date[_\s]?id|day|date[_\s]?key)$")
_SOURCE_RANK_MODEL_ENV = "CORRELATION_SOURCE_RANK_MODEL"
_SOURCE_RANK_TIMEOUT_ENV = "CORRELATION_SOURCE_RANK_TIMEOUT_SEC"


# ---------------------------------------------------------------------------
# Data loading helpers
# ---------------------------------------------------------------------------

def _detect_period_column(row: dict) -> str | None:
    """
    Auto-detect the period/date column in a single data row.

    Strategy:
    1. Prefer keys whose lower-case name contains a known time-dimension word.
    2. Among those, prefer keys whose value matches an ISO date pattern.
    3. Fall back to the first key whose *value* matches the ISO pattern.
    4. Return None if no period column can be found.
    """
    if not row:
        return None

    candidates_by_name: list[str] = []
    candidates_by_value: list[str] = []

    for key, value in row.items():
        lower_key = key.lower().replace("_", " ")
        if any(word in lower_key for word in _PERIOD_KEY_WORDS):
            candidates_by_name.append(key)
        if isinstance(value, str) and _ISO_DATE_RE.match(value.strip()):
            candidates_by_value.append(key)

    # Intersection first (name match + ISO value)
    for key in candidates_by_name:
        if key in candidates_by_value:
            return key

    if candidates_by_name:
        return candidates_by_name[0]
    if candidates_by_value:
        return candidates_by_value[0]
    return None


def _coerce_numeric(value: Any) -> float | None:
    """Safely cast a value to float, returning None on failure."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _qident(identifier: str) -> str:
    return '"' + str(identifier).replace('"', '""') + '"'


def _parse_temporal_value(value: Any) -> datetime | None:
    """Parse a supported temporal value into a datetime, else return None."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value

    text = str(value).strip()
    if not text or text.lower() in {"none", "null", "nan"}:
        return None

    normalized = text.replace("Z", "+00:00")
    for candidate in (
        normalized,
        f"{normalized}-01" if re.fullmatch(r"\d{4}-\d{2}", normalized) else None,
        f"{normalized}-01-01" if re.fullmatch(r"\d{4}", normalized) else None,
    ):
        if not candidate:
            continue
        try:
            return datetime.fromisoformat(candidate)
        except ValueError:
            continue
    return None


def _temporal_axis_quality(rows_json: list[dict], period_col: str | None) -> dict[str, Any]:
    """Return quality metadata for whether a snapshot has a real temporal axis."""
    if not period_col:
        return {
            "eligible": False,
            "reason": "missing_period_column",
            "period_col": None,
            "total_rows": len(rows_json),
            "parseable_rows": 0,
            "parse_ratio": 0.0,
            "unique_points": 0,
        }

    parsed_values: list[datetime] = []
    non_null_rows = 0
    for row in rows_json:
        raw = row.get(period_col)
        if raw in {None, ""}:
            continue
        non_null_rows += 1
        parsed = _parse_temporal_value(raw)
        if parsed is not None:
            parsed_values.append(parsed)

    parse_ratio = round((len(parsed_values) / non_null_rows), 4) if non_null_rows else 0.0
    unique_points = len({value.isoformat() for value in parsed_values})

    reason = None
    if not parsed_values:
        reason = "period_values_not_temporal"
    elif len(parsed_values) < _MIN_SERIES_LEN:
        reason = "too_few_temporal_points"
    elif parse_ratio < 0.8:
        reason = "insufficient_temporal_parse_ratio"
    elif unique_points < _MIN_SERIES_LEN:
        reason = "too_few_unique_temporal_points"

    return {
        "eligible": reason is None,
        "reason": reason or "eligible",
        "period_col": period_col,
        "total_rows": len(rows_json),
        "non_null_rows": non_null_rows,
        "parseable_rows": len(parsed_values),
        "parse_ratio": parse_ratio,
        "unique_points": unique_points,
    }


def _snapshot_metric_name(raw: dict[str, Any], fallback: str = "unknown") -> str:
    qp = raw.get("query_payload") or {}
    return str(
        qp.get("metric_name")
        or qp.get("metric")
        or raw.get("question")
        or fallback
    )


def _snapshot_exclusion_entry(
    raw: dict[str, Any],
    *,
    reason: str,
    period_col: str | None,
    value_col: str | None = None,
    parse_ratio: float | None = None,
    unique_points: int | None = None,
    total_rows: int | None = None,
    non_null_rows: int | None = None,
    parseable_rows: int | None = None,
) -> dict[str, Any]:
    return {
        "chart_id": raw.get("chart_id"),
        "metric_name": _snapshot_metric_name(raw),
        "reason": reason,
        "period_col": period_col,
        "value_col": value_col,
        "parse_ratio": parse_ratio,
        "unique_points": unique_points,
        "total_rows": total_rows,
        "non_null_rows": non_null_rows,
        "parseable_rows": parseable_rows,
    }


def _summarize_snapshot_eligibility(
    *,
    source_mode: str,
    rows_examined: int,
    snapshots: list[dict],
    exclusions: list[dict],
) -> dict[str, Any]:
    excluded_by_reason: dict[str, int] = defaultdict(int)
    for item in exclusions:
        excluded_by_reason[str(item.get("reason") or "unknown")] += 1
    return {
        "source_mode": source_mode,
        "rows_examined": rows_examined,
        "eligible_snapshot_count": len(snapshots),
        "excluded_chart_count": len(exclusions),
        "excluded_by_reason": dict(sorted(excluded_by_reason.items())),
    }


def _build_data_quality_warnings(
    snapshot_eligibility_summary: dict[str, Any],
    snapshot_exclusions: list[dict],
) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    excluded_count = int(snapshot_eligibility_summary.get("excluded_chart_count") or 0)
    if excluded_count:
        warnings.append(
            {
                "code": "non_temporal_or_ineligible_charts_excluded",
                "severity": "warning",
                "message": (
                    f"{excluded_count} chart snapshot(s) were excluded from correlation "
                    "because they were not eligible time series."
                ),
                "details": {
                    "excluded_by_reason": snapshot_eligibility_summary.get("excluded_by_reason") or {},
                    "preview": snapshot_exclusions[:5],
                },
            }
        )

    if snapshot_eligibility_summary.get("source_mode") in {"fact_bootstrap", "fact_preferred"}:
        warnings.append(
            {
                "code": "fact_native_sources_used",
                "severity": "info",
                "message": (
                    "Correlation snapshots were sourced from live fact tables using a real "
                    "temporal axis."
                ),
                "details": {
                    "source_mode": snapshot_eligibility_summary.get("source_mode"),
                    "bootstrap_snapshot_count": snapshot_eligibility_summary.get("bootstrap_snapshot_count") or 0,
                    "fact_snapshot_count": snapshot_eligibility_summary.get("fact_snapshot_count") or 0,
                    "category_snapshot_count": (
                        (snapshot_eligibility_summary.get("fact_source_summary") or {}).get("category_snapshot_count") or 0
                    ),
                },
            }
        )

    if int(snapshot_eligibility_summary.get("eligible_snapshot_count") or 0) < 2:
        warnings.append(
            {
                "code": "limited_temporal_coverage",
                "severity": "warning",
                "message": (
                    "Fewer than two eligible temporal series were available, so pairwise "
                    "correlation coverage is limited."
                ),
                "details": snapshot_eligibility_summary,
            }
        )
    return warnings


def _find_fact_time_column(table_info: dict[str, Any]) -> tuple[str | None, str | None]:
    time_cols = [str(col) for col in (table_info.get("time_columns") or []) if str(col or "").strip()]
    if time_cols:
        return time_cols[0], "iso_date"
    for col in (table_info.get("numeric_columns") or []):
        col_name = str(col or "").strip()
        if col_name and _DAY_ID_COL_PATTERN.match(col_name):
            return col_name, "yyyymmdd"
    return None, None


def _fact_time_expr(column_name: str, date_format: str) -> str:
    q_col = _qident(column_name)
    if date_format == "yyyymmdd":
        return f"TO_DATE({q_col}::varchar, 'YYYYMMDD')"
    return q_col


def _fact_table_quality(table_info: dict[str, Any]) -> dict[str, Any]:
    row_count = int(table_info.get("row_count") or 0)
    time_col, date_format = _find_fact_time_column(table_info)
    measure_cols = [
        str(c)
        for c in (table_info.get("eligible_numeric_columns") or table_info.get("numeric_columns") or [])
        if str(c or "").strip()
    ]
    category_cols = [
        str(c)
        for c in (table_info.get("categorical_columns") or [])
        if str(c or "").strip()
    ]
    score = 0.0
    if time_col:
        score += 3.0
    score += min(len(measure_cols), 5) * 0.6
    score += min(len(category_cols), 3) * 0.2
    if row_count > 0:
        score += min(math.log10(max(row_count, 1)), 4.0)
    return {
        "table_name": str(table_info.get("name") or ""),
        "row_count": row_count,
        "time_column": time_col,
        "date_format": date_format,
        "measure_count": len(measure_cols),
        "category_count": len(category_cols),
        "score": round(score, 3),
    }


def _llm_json_call(
    settings: Settings,
    *,
    system_prompt: str,
    user_payload: dict[str, Any],
    timeout: int | None = None,
) -> dict[str, Any] | None:
    api_key = getattr(settings, "openai_api_key", None)
    if not api_key:
        return None
    model = os.getenv(_SOURCE_RANK_MODEL_ENV, getattr(settings, "openai_model", "gpt-4o-mini"))
    timeout_sec = timeout or int(os.getenv(_SOURCE_RANK_TIMEOUT_ENV, "45"))
    body = json.dumps(
        {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_payload, default=str)},
            ],
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
        },
        default=str,
    ).encode("utf-8")
    request = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_sec) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
        return json.loads(raw["choices"][0]["message"]["content"])
    except Exception:
        logger.warning("[correlation.source_rank] LLM call failed", exc_info=True)
        return None


def _llm_rank_fact_sources(
    settings: Settings,
    table_quality: list[dict[str, Any]],
    profiling_stats: dict[str, Any],
) -> dict[str, Any] | None:
    candidates = []
    for quality in table_quality[:8]:
        table_name = str(quality.get("table_name") or "")
        table_info = next(
            (tbl for tbl in (profiling_stats.get("tables") or []) if str(tbl.get("name") or "") == table_name),
            {},
        )
        candidates.append(
            {
                "table_name": table_name,
                "row_count": quality.get("row_count"),
                "time_column": quality.get("time_column"),
                "date_format": quality.get("date_format"),
                "measure_count": quality.get("measure_count"),
                "category_count": quality.get("category_count"),
                "score": quality.get("score"),
                "description": table_info.get("description") or "",
                "sample_categories": list((table_info.get("categorical_columns") or [])[:3]),
                "sample_measures": list((table_info.get("eligible_numeric_columns") or table_info.get("numeric_columns") or [])[:5]),
            }
        )
    if not candidates:
        return None
    result = _llm_json_call(
        settings,
        system_prompt=(
            "You rank fact tables for correlation analysis. Prefer tables with meaningful temporal coverage, "
            "business-relevant additive measures, and useful category breakdowns. Return JSON with keys "
            "\"ranked_tables\" (list of table names best to worst) and \"rationales\" (object mapping table name to short reason)."
        ),
        user_payload={"candidates": candidates},
    )
    if not result:
        return None
    ranked_tables = [str(item).strip() for item in (result.get("ranked_tables") or []) if str(item).strip()]
    rationales = result.get("rationales") if isinstance(result.get("rationales"), dict) else {}
    valid_tables = {str(item.get("table_name") or "") for item in table_quality}
    ranked_tables = [name for name in ranked_tables if name in valid_tables]
    if not ranked_tables:
        return None
    return {
        "ranked_tables": ranked_tables,
        "rationales": {str(k): str(v) for k, v in rationales.items() if str(k) in valid_tables},
    }


def _series_period_sort_key(value: Any) -> tuple[int, str]:
    parsed = _parse_temporal_value(value)
    return (0, parsed.isoformat()) if parsed else (1, str(value))


def _category_label(value: Any) -> str:
    text = str(value or "").strip()
    return text if text else "UNKNOWN"


def _load_kpi_snapshot_bundle(
    settings: Settings,
    tenant_id: str,
    domain_id: str,
    run_id: str | None = None,
    scoped_conn=None,
    profiling_stats: dict | None = None,
) -> dict[str, Any]:
    """
    Load KPI snapshots plus eligibility metadata used by the correlation run.
    """
    bundle = {
        "kpi_snapshots": [],
        "snapshot_exclusions": [],
        "snapshot_eligibility_summary": {
            "source_mode": "none",
            "rows_examined": 0,
            "eligible_snapshot_count": 0,
            "excluded_chart_count": 0,
            "excluded_by_reason": {},
        },
    }
    conn = psycopg2.connect(
        host=settings.db_host,
        port=settings.db_port,
        dbname=settings.db_name,
        user=settings.db_user,
        password=settings.db_password,
    )
    rows: list[Any] = []
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if run_id:
                cur.execute(
                    """
                    SELECT chart_id, question, query_payload, rows_json
                      FROM public.quantyx_chart_requests
                     WHERE run_id = %s
                       AND status IN ('done', 'complete', 'success', 'ready')
                       AND rows_json IS NOT NULL
                     ORDER BY created_at ASC
                    """,
                    [run_id],
                )
                rows = cur.fetchall()

            if not rows:
                cur.execute(
                    """
                    SELECT chart_id, question, query_payload, rows_json
                      FROM public.quantyx_chart_requests
                     WHERE tenant_id = %s
                       AND domain_id  = %s
                       AND status IN ('done', 'complete', 'success', 'ready')
                       AND rows_json IS NOT NULL
                     ORDER BY created_at DESC
                     LIMIT 10
                    """,
                    [tenant_id, domain_id],
                )
                rows = cur.fetchall()
    except psycopg2.errors.UndefinedTable:
        logger.warning("quantyx_chart_requests table not found — returning empty snapshots")
        return bundle
    finally:
        conn.close()

    chart_snapshots, exclusions = _build_snapshots_from_rows(rows)
    fact_snapshots: list[dict] = []
    fact_source_summary: dict[str, Any] = {
        "candidate_table_count": 0,
        "qualified_table_count": 0,
        "snapshot_count": 0,
        "category_snapshot_count": 0,
        "llm_ranked": False,
        "llm_ranked_tables": [],
        "llm_rationales": {},
        "top_tables": [],
    }
    if scoped_conn and profiling_stats:
        logger.info(
            "[correlation] Evaluating fact-native KPI snapshots via scoped_conn host=%s db=%s",
            scoped_conn.host,
            scoped_conn.database_name,
        )
        fact_snapshots, fact_source_summary = _bootstrap_kpi_snapshots(settings, scoped_conn, profiling_stats)
        logger.info(
            "[correlation] Fact-native source evaluation complete | snapshots=%d qualified_tables=%d",
            len(fact_snapshots),
            fact_source_summary.get("qualified_table_count"),
        )

    selected_snapshots = chart_snapshots
    source_mode = "chart_rows" if chart_snapshots else ("none" if not rows else "chart_rows")
    if fact_snapshots and len(fact_snapshots) >= _FACT_SOURCE_MIN_SNAPSHOTS:
        selected_snapshots = fact_snapshots
        source_mode = "fact_preferred"
    elif not chart_snapshots and fact_snapshots:
        selected_snapshots = fact_snapshots
        source_mode = "fact_bootstrap"

    bundle["kpi_snapshots"] = selected_snapshots
    bundle["snapshot_exclusions"] = exclusions
    bundle["snapshot_eligibility_summary"] = {
        **_summarize_snapshot_eligibility(
            source_mode=source_mode,
            rows_examined=len(rows),
            snapshots=selected_snapshots,
            exclusions=exclusions,
        ),
        "chart_snapshot_count": len(chart_snapshots),
        "fact_snapshot_count": len(fact_snapshots),
        "selected_source_kind": "fact_metric" if source_mode.startswith("fact") else ("chart_fallback" if selected_snapshots else "none"),
        "fact_source_summary": fact_source_summary,
    }
    return bundle


def load_kpi_snapshots(
    settings: Settings,
    tenant_id: str,
    domain_id: str,
    run_id: str | None = None,
    scoped_conn=None,
    profiling_stats: dict | None = None,
) -> list[dict]:
    """
    Load KPI snapshots from quantyx_chart_requests.

    Scoping strategy:
    - Primary: WHERE run_id = %s (exact deployment run)
    - Fallback: WHERE tenant_id = %s AND domain_id = %s (latest 10 charts)
    - Bootstrap: when no chart rows_json data exists and scoped_conn + profiling_stats
      are provided, generate fresh time-series snapshots directly from the fact tables
      on the customer DB. This handles fresh deployments where no charts have been
      executed yet.

    Returns a list of snapshot dicts, each containing:
      {
        "chart_id": str,
        "question": str,
        "rows_json": list[dict],      # raw data rows
        "query_payload": dict | None,
        "metric_name": str,           # derived from question / query_payload
        "period_col": str | None,
        "value_col": str | None,
        "series": list[float],
        "timestamps": list[str],
      }
    """
    bundle = _load_kpi_snapshot_bundle(
        settings,
        tenant_id,
        domain_id,
        run_id=run_id,
        scoped_conn=scoped_conn,
        profiling_stats=profiling_stats,
    )
    return bundle.get("kpi_snapshots") or []


def _build_snapshots_from_rows(rows: list) -> tuple[list[dict], list[dict]]:
    """Convert raw quantyx_chart_requests rows into snapshot dicts."""
    snapshots: list[dict] = []
    category_snapshot_count = 0
    exclusions: list[dict] = []
    for raw in rows:
        rows_json: list[dict] = raw.get("rows_json") or []
        if not rows_json or not isinstance(rows_json, list):
            continue

        first_row = rows_json[0] if rows_json else {}
        period_col = _detect_period_column(first_row)
        temporal_quality = _temporal_axis_quality(rows_json, period_col)
        if not temporal_quality.get("eligible"):
            exclusions.append(
                _snapshot_exclusion_entry(
                    raw,
                    reason=str(temporal_quality.get("reason") or "ineligible_temporal_axis"),
                    period_col=temporal_quality.get("period_col"),
                    parse_ratio=temporal_quality.get("parse_ratio"),
                    unique_points=temporal_quality.get("unique_points"),
                    total_rows=temporal_quality.get("total_rows"),
                    non_null_rows=temporal_quality.get("non_null_rows"),
                    parseable_rows=temporal_quality.get("parseable_rows"),
                )
            )
            logger.info(
                "[correlation] Skipping chart_id=%s metric=%s reason=%s period_col=%s parse_ratio=%s unique_points=%s",
                raw.get("chart_id"),
                _snapshot_metric_name(raw),
                temporal_quality.get("reason"),
                temporal_quality.get("period_col"),
                temporal_quality.get("parse_ratio"),
                temporal_quality.get("unique_points"),
            )
            continue

        value_col: str | None = None
        for key, val in first_row.items():
            if key == period_col:
                continue
            if _coerce_numeric(val) is not None:
                value_col = key
                break

        if value_col is None:
            exclusions.append(
                _snapshot_exclusion_entry(
                    raw,
                    reason="missing_numeric_value_column",
                    period_col=period_col,
                    total_rows=len(rows_json),
                )
            )
            continue

        series: list[float] = []
        timestamps: list[str] = []
        for row in rows_json:
            v = _coerce_numeric(row.get(value_col))
            if v is None:
                continue
            series.append(v)
            ts = str(row.get(period_col, "")) if period_col else str(len(series))
            timestamps.append(ts)

        if len(series) < _MIN_SERIES_LEN:
            exclusions.append(
                _snapshot_exclusion_entry(
                    raw,
                    reason="too_few_numeric_points",
                    period_col=period_col,
                    value_col=value_col,
                    total_rows=len(rows_json),
                )
            )
            continue

        qp: dict = raw.get("query_payload") or {}
        metric_name: str = (
            qp.get("metric_name")
            or qp.get("metric")
            or (raw.get("question") or value_col or "unknown")
        )

        snapshots.append(
            {
                "chart_id": raw["chart_id"],
                "question": raw.get("question") or "",
                "rows_json": rows_json,
                "query_payload": qp,
                "metric_name": metric_name,
                "period_col": period_col,
                "value_col": value_col,
                "series": series,
                "timestamps": timestamps,
                "temporal_quality": temporal_quality,
                "source_kind": "chart_fallback",
                "source_quality": {
                    "source_kind": "chart_fallback",
                    "chart_id": raw.get("chart_id"),
                    "period_col": period_col,
                    "value_col": value_col,
                    "temporal_quality": temporal_quality,
                },
            }
        )
    return snapshots, exclusions


def _bootstrap_kpi_snapshots(settings: Settings, scoped_conn, profiling_stats: dict) -> tuple[list[dict], dict[str, Any]]:
    """
    Generate KPI snapshots by querying fact tables directly on the customer DB.

    This is the fact-native source path for correlation. It evaluates profiled
    tables, prefers tables with real temporal coverage and numeric measures, and
    produces monthly time-series snapshots from the live scoped customer DB.
    """
    snapshots: list[dict] = []
    category_snapshot_count: int = 0
    table_quality: list[dict[str, Any]] = []
    tables = profiling_stats.get("tables") or []
    for table_info in tables:
        quality = _fact_table_quality(table_info)
        if quality.get("time_column") and quality.get("measure_count"):
            table_quality.append(quality)

    table_quality.sort(key=lambda item: item.get("score") or 0.0, reverse=True)
    llm_ranking = _llm_rank_fact_sources(settings, table_quality, profiling_stats)
    if llm_ranking:
        rank_index = {
            table_name: idx
            for idx, table_name in enumerate(llm_ranking.get("ranked_tables") or [])
        }
        table_quality.sort(
            key=lambda item: (
                rank_index.get(str(item.get("table_name") or ""), len(rank_index) + 1000),
                -(float(item.get("score") or 0.0)),
            )
        )
    top_tables = table_quality[:5]
    if not top_tables:
        return [], {
            "candidate_table_count": len(tables),
            "qualified_table_count": 0,
            "snapshot_count": 0,
            "llm_ranked": bool(llm_ranking),
            "llm_ranked_tables": (llm_ranking or {}).get("ranked_tables") or [],
            "llm_rationales": (llm_ranking or {}).get("rationales") or {},
            "top_tables": [],
        }

    conn = psycopg2.connect(
        host=scoped_conn.host,
        port=scoped_conn.port,
        dbname=scoped_conn.database_name,
        user=scoped_conn.user,
        password=scoped_conn.password,
    )
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            for quality in top_tables:
                table_name = str(quality.get("table_name") or "").strip()
                time_col = str(quality.get("time_column") or "").strip()
                date_format = str(quality.get("date_format") or "iso_date")
                if not table_name or not time_col:
                    continue

                table_info = next(
                    (tbl for tbl in tables if str(tbl.get("name") or "").strip() == table_name),
                    {},
                )
                numeric_cols = [
                    str(c)
                    for c in (table_info.get("eligible_numeric_columns") or table_info.get("numeric_columns") or [])
                    if str(c or "").strip()
                ]
                category_cols = [
                    str(c)
                    for c in (table_info.get("categorical_columns") or [])
                    if str(c or "").strip()
                ]
                time_expr = _fact_time_expr(time_col, date_format)
                schema_name = scoped_conn.schema_name or "public"
                category_col = category_cols[0] if category_cols else None

                for measure_col in numeric_cols[:3]:
                    q_measure = _qident(measure_col)
                    sql = (
                        f"SELECT date_trunc('month', {time_expr}) AS period, "
                        f"SUM({q_measure}) AS {q_measure} "
                        f"FROM {_qident(schema_name)}.{_qident(table_name)} "
                        f"WHERE {time_expr} IS NOT NULL "
                        f"GROUP BY 1 ORDER BY 1"
                    )
                    try:
                        cur.execute(sql)
                        result_rows = [dict(r) for r in cur.fetchall()]
                    except Exception:
                        logger.warning(
                            "[correlation.fact] Query failed for %s.%s | sql=%s",
                            table_name,
                            measure_col,
                            sql,
                            exc_info=True,
                        )
                        continue

                    if not result_rows:
                        logger.info(
                            "[correlation.fact] No rows from %s.%s time_col=%s measure=%s",
                            table_name,
                            scoped_conn.database_name,
                            time_col,
                            measure_col,
                        )
                        continue

                    series: list[float] = []
                    timestamps: list[str] = []
                    for row in result_rows:
                        v = _coerce_numeric(row.get(measure_col))
                        if v is None:
                            continue
                        series.append(v)
                        timestamps.append(str(row.get("period", "")))

                    if len(series) < _MIN_SERIES_LEN:
                        logger.info(
                            "[correlation.fact] Series too short (%d < %d) for %s.%s",
                            len(series),
                            _MIN_SERIES_LEN,
                            table_name,
                            measure_col,
                        )
                        continue

                    metric_name = f"{measure_col}_by_month_{table_name}"
                    source_quality = {
                        **quality,
                        "measure_column": measure_col,
                        "source_kind": "fact_metric",
                    }
                    logger.info(
                        "[correlation.fact] OK | table=%s measure=%s points=%d score=%.2f",
                        table_name,
                        measure_col,
                        len(series),
                        float(quality.get("score") or 0.0),
                    )
                    snapshots.append(
                        {
                            "chart_id": f"fact_{table_name}_{measure_col}",
                            "question": f"{measure_col} over time from {table_name}",
                            "rows_json": result_rows,
                            "query_payload": {
                                "metric_name": metric_name,
                                "table": table_name,
                                "time_column": time_col,
                                "date_format": date_format,
                                "source_kind": "fact_metric",
                            },
                            "metric_name": metric_name,
                            "period_col": "period",
                            "value_col": measure_col,
                            "series": series,
                            "timestamps": timestamps,
                            "source_kind": "fact_metric",
                            "source_quality": source_quality,
                        }
                    )

                    if not category_col:
                        continue

                    q_category = _qident(category_col)
                    top_category_sql = (
                        f"SELECT {q_category} AS category_value, SUM({q_measure}) AS total_value "
                        f"FROM {_qident(schema_name)}.{_qident(table_name)} "
                        f"WHERE {time_expr} IS NOT NULL AND {q_category} IS NOT NULL "
                        f"GROUP BY 1 ORDER BY 2 DESC NULLS LAST LIMIT 3"
                    )
                    try:
                        cur.execute(top_category_sql)
                        top_category_rows = [dict(r) for r in cur.fetchall()]
                    except Exception:
                        logger.warning(
                            "[correlation.fact.category] Top category query failed for %s.%s | sql=%s",
                            table_name,
                            measure_col,
                            top_category_sql,
                            exc_info=True,
                        )
                        continue

                    top_categories = [
                        row.get("category_value")
                        for row in top_category_rows
                        if row.get("category_value") not in {None, ""}
                    ]
                    if not top_categories:
                        continue

                    category_series_sql = (
                        f"SELECT date_trunc('month', {time_expr}) AS period, "
                        f"{q_category} AS category_value, SUM({q_measure}) AS {q_measure} "
                        f"FROM {_qident(schema_name)}.{_qident(table_name)} "
                        f"WHERE {time_expr} IS NOT NULL AND {q_category} = ANY(%s) "
                        f"GROUP BY 1, 2 ORDER BY 1, 2"
                    )
                    try:
                        cur.execute(category_series_sql, [top_categories])
                        category_rows = [dict(r) for r in cur.fetchall()]
                    except Exception:
                        logger.warning(
                            "[correlation.fact.category] Category series query failed for %s.%s | sql=%s",
                            table_name,
                            measure_col,
                            category_series_sql,
                            exc_info=True,
                        )
                        continue

                    if not category_rows:
                        continue

                    periods = sorted(
                        {
                            str(row.get("period", ""))
                            for row in category_rows
                            if str(row.get("period", "")).strip()
                        },
                        key=_series_period_sort_key,
                    )
                    category_period_values: dict[str, dict[str, float]] = defaultdict(dict)
                    for row in category_rows:
                        period = str(row.get("period", "")).strip()
                        category_value = _category_label(row.get("category_value"))
                        value = _coerce_numeric(row.get(measure_col))
                        if not period or value is None:
                            continue
                        category_period_values[category_value][period] = value

                    for category_value, period_map in category_period_values.items():
                        series = [float(period_map.get(period, 0.0)) for period in periods]
                        if len(series) < _MIN_SERIES_LEN:
                            continue
                        category_metric_name = (
                            f"{measure_col}_by_month_{table_name}_{category_col}_{category_value}"
                        )
                        snapshots.append(
                            {
                                "chart_id": f"fact_{table_name}_{measure_col}_{category_col}_{uuid.uuid4().hex[:6]}",
                                "question": (
                                    f"{measure_col} over time from {table_name} "
                                    f"for {category_col}={category_value}"
                                ),
                                "rows_json": category_rows,
                                "query_payload": {
                                    "metric_name": category_metric_name,
                                    "table": table_name,
                                    "time_column": time_col,
                                    "date_format": date_format,
                                    "source_kind": "fact_category_metric",
                                    "category_column": category_col,
                                    "category_value": category_value,
                                },
                                "metric_name": category_metric_name,
                                "period_col": "period",
                                "value_col": measure_col,
                                "series": series,
                                "timestamps": periods,
                                "source_kind": "fact_category_metric",
                                "source_quality": {
                                    **source_quality,
                                    "source_kind": "fact_category_metric",
                                    "category_column": category_col,
                                    "category_value": category_value,
                                },
                            }
                        )
                        category_snapshot_count += 1
    finally:
        conn.close()

    return snapshots, {
        "candidate_table_count": len(tables),
        "qualified_table_count": len(table_quality),
        "snapshot_count": len(snapshots),
        "category_snapshot_count": category_snapshot_count,
        "llm_ranked": bool(llm_ranking),
        "llm_ranked_tables": (llm_ranking or {}).get("ranked_tables") or [],
        "llm_rationales": (llm_ranking or {}).get("rationales") or {},
        "top_tables": top_tables,
    }


def extract_dimension_breakdown(
    snapshot: dict,
    anomaly_period: str,
) -> dict | None:
    """
    Derive dimension concentration for an anomaly period from rows_json.

    Looks through all rows for those matching the anomaly_period, then finds
    the non-period, non-numeric column with the highest value concentration.

    Returns {"dimension": str, "value": str, "pct": float} or None.
    """
    rows_json: list[dict] = snapshot.get("rows_json") or []
    period_col: str | None = snapshot.get("period_col")
    value_col: str | None = snapshot.get("value_col")

    if not rows_json or not value_col:
        return None

    # Find rows for this period
    period_rows = [
        r for r in rows_json
        if period_col is None or str(r.get(period_col, "")).startswith(anomaly_period[:7])
    ]
    if not period_rows:
        period_rows = rows_json  # fall back to all rows

    # Find candidate dimension columns (non-period, non-numeric, non-id)
    dim_cols: list[str] = []
    for key, val in (period_rows[0] if period_rows else {}).items():
        if key in (period_col, value_col):
            continue
        if _coerce_numeric(val) is not None:
            continue
        dim_cols.append(key)

    if not dim_cols:
        return None

    best_dim = dim_cols[0]
    dim_col_to_use = best_dim

    # Sum values by dimension value
    totals: dict[str, float] = defaultdict(float)
    grand_total = 0.0
    for row in period_rows:
        v = _coerce_numeric(row.get(value_col, 0)) or 0.0
        dim_val = str(row.get(dim_col_to_use, "unknown"))
        totals[dim_val] += v
        grand_total += v

    if grand_total == 0:
        return None

    top_val = max(totals, key=lambda k: totals[k])
    pct = round(totals[top_val] / grand_total * 100, 1)

    return {
        "dimension": dim_col_to_use,
        "value": top_val,
        "pct": pct,
    }


# ---------------------------------------------------------------------------
# Anomaly detection
# ---------------------------------------------------------------------------

def score_anomalies(
    metric_name: str,
    series: list[float],
    timestamps: list[str],
    dimension_breakdown: dict | None = None,
) -> list[dict]:
    """
    Run Z-score + IQR + CUSUM anomaly detection on a numeric time series.

    Returns a list of AnomalyResult dicts (one per detected point) with keys:
      anomaly_id, metric_name, anomaly_class, anomaly_score, z_score,
      iqr_flag, cusum_signal, detected_at, period_label, baseline_value,
      observed_value, deviation_pct, top_dimension, top_dimension_value,
      dimension_pct, stats_json
    """
    if len(series) < _MIN_SERIES_LEN:
        return []

    arr = np.array(series, dtype=float)
    mean = float(np.mean(arr))
    std = float(np.std(arr, ddof=1)) if len(arr) > 1 else 0.0

    # IQR fences
    q1 = float(np.percentile(arr, 25))
    q3 = float(np.percentile(arr, 75))
    iqr = q3 - q1
    lower_fence = q1 - _ANOMALY_IQR_MULTIPLIER * iqr
    upper_fence = q3 + _ANOMALY_IQR_MULTIPLIER * iqr

    # CUSUM (cumulative sum of deviations from mean)
    cusum_pos = np.zeros(len(arr))
    cusum_neg = np.zeros(len(arr))
    slack = 0.5 * std if std > 0 else 0.01
    for i in range(1, len(arr)):
        cusum_pos[i] = max(0.0, cusum_pos[i - 1] + (arr[i] - mean) - slack)
        cusum_neg[i] = max(0.0, cusum_neg[i - 1] - (arr[i] - mean) - slack)
    cusum_threshold = 4 * std if std > 0 else 1.0

    results: list[dict] = []
    for i, (val, ts) in enumerate(zip(series, timestamps)):
        z = (val - mean) / std if std > 0 else 0.0
        abs_z = abs(z)

        iqr_flag = val < lower_fence or val > upper_fence
        cusum_signal = (cusum_pos[i] > cusum_threshold or cusum_neg[i] > cusum_threshold)

        # Composite anomaly score [0, 1]
        z_component = min(abs_z / (_ANOMALY_ZSCORE_THRESHOLD * 2), 1.0)
        iqr_component = 1.0 if iqr_flag else 0.0
        cusum_component = 1.0 if cusum_signal else 0.0
        anomaly_score = round(
            0.5 * z_component + 0.3 * iqr_component + 0.2 * cusum_component,
            4,
        )

        if anomaly_score < 0.3 and abs_z < _ANOMALY_ZSCORE_THRESHOLD:
            continue  # not anomalous enough

        # Classify anomaly
        if z > _ANOMALY_ZSCORE_THRESHOLD:
            anomaly_class = "spike"
        elif z < -_ANOMALY_ZSCORE_THRESHOLD:
            anomaly_class = "drop"
        elif cusum_signal and cusum_pos[i] > cusum_threshold:
            anomaly_class = "drift_up"
        elif cusum_signal and cusum_neg[i] > cusum_threshold:
            anomaly_class = "drift_down"
        elif iqr_flag:
            anomaly_class = "step_change"
        else:
            anomaly_class = "spike" if z > 0 else "drop"

        deviation_pct: float | None = None
        if mean != 0:
            deviation_pct = round((val - mean) / abs(mean) * 100, 2)

        top_dim = top_dim_val = dim_pct_val = None
        if dimension_breakdown:
            top_dim = dimension_breakdown.get("dimension")
            top_dim_val = dimension_breakdown.get("value")
            dim_pct_val = dimension_breakdown.get("pct")

        results.append(
            {
                "anomaly_id": f"anom_{uuid.uuid4().hex[:12]}",
                "metric_name": metric_name,
                "anomaly_class": anomaly_class,
                "anomaly_score": anomaly_score,
                "z_score": round(z, 4),
                "iqr_flag": iqr_flag,
                "cusum_signal": cusum_signal,
                "detected_at": ts,
                "period_label": ts,
                "baseline_value": round(mean, 6),
                "observed_value": val,
                "deviation_pct": deviation_pct,
                "top_dimension": top_dim,
                "top_dimension_value": top_dim_val,
                "dimension_pct": dim_pct_val,
                "stats_json": {
                    "mean": mean,
                    "std": std,
                    "q1": q1,
                    "q3": q3,
                    "iqr": iqr,
                    "cusum_pos": float(cusum_pos[i]),
                    "cusum_neg": float(cusum_neg[i]),
                    "series_len": len(series),
                },
            }
        )

    return results


# ---------------------------------------------------------------------------
# Correlation analysis
# ---------------------------------------------------------------------------

def lagged_correlation(
    series_a: list[float],
    series_b: list[float],
    max_lag: int = 6,
) -> dict:
    """
    Compute Pearson/Spearman correlations and find the best lag between two series.

    Returns:
      {
        "pearson_r": float | None,
        "spearman_rho": float | None,
        "best_lag": int,
        "lagged_r": float | None,
        "lag_direction": str,   # "a_leads_b" | "b_leads_a" | "concurrent"
        "sample_size": int,
        "p_value": float | None,
      }
    """
    from scipy import stats as scipy_stats

    n = min(len(series_a), len(series_b))
    if n < _MIN_SERIES_LEN:
        return {
            "pearson_r": None, "spearman_rho": None,
            "best_lag": 0, "lagged_r": None,
            "lag_direction": "concurrent", "sample_size": n, "p_value": None,
        }

    a = np.array(series_a[:n], dtype=float)
    b = np.array(series_b[:n], dtype=float)

    # Pearson at lag 0
    pearson_r = p_value = None
    try:
        pr, pv = scipy_stats.pearsonr(a, b)
        pearson_r = round(float(pr), 4)
        p_value = round(float(pv), 6)
    except Exception:
        pass

    # Spearman at lag 0
    spearman_rho = None
    try:
        sr, _ = scipy_stats.spearmanr(a, b)
        spearman_rho = round(float(sr), 4)
    except Exception:
        pass

    # Best lagged correlation
    best_lag = 0
    best_r = pearson_r or 0.0
    for lag in range(1, min(max_lag + 1, n // 2)):
        # A leads B by lag
        try:
            r_ab, _ = scipy_stats.pearsonr(a[:-lag], b[lag:])
            if abs(r_ab) > abs(best_r):
                best_r = round(float(r_ab), 4)
                best_lag = lag
        except Exception:
            pass

        # B leads A by lag
        try:
            r_ba, _ = scipy_stats.pearsonr(b[:-lag], a[lag:])
            if abs(r_ba) > abs(best_r):
                best_r = round(float(r_ba), 4)
                best_lag = -lag  # negative = B leads A
        except Exception:
            pass

    lag_direction = (
        "concurrent" if best_lag == 0
        else "a_leads_b" if best_lag > 0
        else "b_leads_a"
    )

    return {
        "pearson_r": pearson_r,
        "spearman_rho": spearman_rho,
        "best_lag": abs(best_lag),
        "lagged_r": round(best_r, 4) if best_r else None,
        "lag_direction": lag_direction,
        "sample_size": n,
        "p_value": p_value,
    }


def build_correlation_matrix(
    kpi_snapshots: list[dict],
    max_lag: int = 6,
) -> list[dict]:
    """
    Compute pairwise correlations for all KPI snapshot combinations.

    Returns a list of CorrelationPair dicts with keys:
      pair_id, metric_a, metric_b, pearson_r, spearman_rho, best_lag,
      lagged_r, lag_direction, strength_label, direction_label,
      sample_size, p_value, is_stable, rolling_r_json
    """
    pairs: list[dict] = []
    n = len(kpi_snapshots)

    for i in range(n):
        for j in range(i + 1, n):
            snap_a = kpi_snapshots[i]
            snap_b = kpi_snapshots[j]

            result = lagged_correlation(
                snap_a["series"], snap_b["series"], max_lag=max_lag
            )

            r = result.get("pearson_r") or 0.0
            if abs(r) < _CORRELATION_MIN_R:
                continue  # prune weak correlations

            abs_r = abs(r)
            if abs_r >= 0.7:
                strength_label = "strong"
            elif abs_r >= 0.4:
                strength_label = "moderate"
            else:
                strength_label = "weak"

            direction_label = "positive" if r >= 0 else "negative"

            # Rolling correlation stability (window = max 6 points)
            rolling_r_json: list[float] = []
            try:
                series_a = snap_a["series"]
                series_b = snap_b["series"]
                window = max(4, min(6, len(series_a) // 3))
                from scipy import stats as scipy_stats

                for w in range(window, len(series_a)):
                    try:
                        rr, _ = scipy_stats.pearsonr(
                            series_a[w - window: w],
                            series_b[w - window: w],
                        )
                        rolling_r_json.append(round(float(rr), 4))
                    except Exception:
                        rolling_r_json.append(0.0)
            except Exception:
                pass

            # Stability: std of rolling r < 0.25
            is_stable = True
            if rolling_r_json and len(rolling_r_json) >= 3:
                is_stable = float(np.std(rolling_r_json)) < 0.25

            pairs.append(
                {
                    "pair_id": f"pair_{uuid.uuid4().hex[:12]}",
                    "metric_a": snap_a["metric_name"],
                    "metric_b": snap_b["metric_name"],
                    "pearson_r": result["pearson_r"],
                    "spearman_rho": result["spearman_rho"],
                    "best_lag": result["best_lag"],
                    "lagged_r": result["lagged_r"],
                    "lag_direction": result["lag_direction"],
                    "strength_label": strength_label,
                    "direction_label": direction_label,
                    "sample_size": result["sample_size"],
                    "p_value": result["p_value"],
                    "is_stable": is_stable,
                    "rolling_r_json": rolling_r_json,
                }
            )

    return pairs


# ---------------------------------------------------------------------------
# Investigation threading
# ---------------------------------------------------------------------------

def build_investigation_threads(
    anomaly_results: list[dict],
    correlation_pairs: list[dict],
    min_confidence: float = _INVESTIGATION_MIN_CONF,
) -> list[dict]:
    """
    Link anomalies to correlated metrics, forming evidence chains.

    For each anomaly, find all correlation pairs that include its metric,
    then build an evidence chain of connected metrics. Confidence is the
    product of anomaly_score × |lagged_r|.

    Returns a list of InvestigationThread dicts with keys:
      thread_id, trigger_metric, trigger_anomaly_id, evidence_chain,
      leading_dimension, leading_dim_value, confidence, suggested_focus,
      narrative_text, narrative_html
    """
    # Index pairs by metric
    metric_to_pairs: dict[str, list[dict]] = defaultdict(list)
    for pair in correlation_pairs:
        metric_to_pairs[pair["metric_a"]].append(pair)
        metric_to_pairs[pair["metric_b"]].append(pair)

    threads: list[dict] = []

    for anomaly in anomaly_results:
        metric = anomaly["metric_name"]
        related_pairs = metric_to_pairs.get(metric, [])
        if not related_pairs:
            continue

        evidence_chain: list[dict] = []
        for pair in related_pairs:
            related_metric = (
                pair["metric_b"] if pair["metric_a"] == metric else pair["metric_a"]
            )
            r = pair.get("lagged_r") or pair.get("pearson_r") or 0.0
            evidence_chain.append(
                {
                    "related_metric": related_metric,
                    "pearson_r": pair.get("pearson_r"),
                    "lagged_r": pair.get("lagged_r"),
                    "best_lag": pair.get("best_lag"),
                    "lag_direction": pair.get("lag_direction"),
                    "strength_label": pair.get("strength_label"),
                    "direction_label": pair.get("direction_label"),
                    "abs_r": abs(r),
                }
            )

        if not evidence_chain:
            continue

        # Confidence: anomaly_score × mean(|r|) of evidence chain
        mean_abs_r = float(
            np.mean([e["abs_r"] for e in evidence_chain])
        )
        confidence = round(anomaly["anomaly_score"] * mean_abs_r, 4)

        if confidence < min_confidence:
            continue

        # Sort evidence by strength
        evidence_chain.sort(key=lambda e: e["abs_r"], reverse=True)

        # Suggested focus: top 3 related metrics
        suggested_focus = [e["related_metric"] for e in evidence_chain[:3]]

        threads.append(
            {
                "thread_id": f"thread_{uuid.uuid4().hex[:12]}",
                "trigger_metric": metric,
                "trigger_anomaly_id": anomaly["anomaly_id"],
                "evidence_chain": evidence_chain,
                "leading_dimension": anomaly.get("top_dimension"),
                "leading_dim_value": anomaly.get("top_dimension_value"),
                "confidence": confidence,
                "suggested_focus": suggested_focus,
                "narrative_text": None,  # filled by narrate step
                "narrative_html": None,
            }
        )

    # Deduplicate: keep highest-confidence thread per anomaly
    seen_anomaly_ids: set[str] = set()
    deduped: list[dict] = []
    threads.sort(key=lambda t: t["confidence"], reverse=True)
    for t in threads:
        if t["trigger_anomaly_id"] not in seen_anomaly_ids:
            deduped.append(t)
            seen_anomaly_ids.add(t["trigger_anomaly_id"])

    return deduped


# ---------------------------------------------------------------------------
# Forward projections
# ---------------------------------------------------------------------------

def project_forward(
    metric_name: str,
    series: list[float],
    timestamps: list[str],
    forecast_periods: int = 12,
    anomaly_results: list[dict] | None = None,
) -> dict:
    """
    Project a metric forward using STL decomposition (≥30 points) or
    linear extrapolation (fallback for shorter series).

    Returns a ProjectionResult dict with keys:
      metric_name, forecast_periods, trend_direction, trend_slope,
      seasonality_present, inflection_signal, inflection_detail,
      projection_json, anomaly_density_trend, chart_spec
    """
    n = len(series)
    arr = np.array(series, dtype=float)

    trend_direction = "flat"
    trend_slope: float | None = None
    seasonality_present = False
    inflection_signal: str | None = None
    inflection_detail: str | None = None
    projection_json: list[dict] = []
    anomaly_density_trend: str | None = None

    # --- Linear trend fit (always computed for slope/direction) ---
    x = np.arange(n, dtype=float)
    try:
        coeffs = np.polyfit(x, arr, 1)
        trend_slope = round(float(coeffs[0]), 6)
        rel_slope = trend_slope / (float(np.mean(arr)) or 1.0)
        if rel_slope > 0.02:
            trend_direction = "up"
        elif rel_slope < -0.02:
            trend_direction = "down"
        else:
            trend_direction = "flat"
    except Exception:
        coeffs = [0.0, float(np.mean(arr))]

    # --- STL decomposition (requires ≥30 points) ---
    residual_std: float = float(np.std(arr, ddof=1))
    trend_component: np.ndarray | None = None

    if n >= 30:
        try:
            from statsmodels.tsa.seasonal import STL

            stl = STL(arr, period=12, robust=True)
            res = stl.fit()
            trend_component = res.trend
            seasonal = res.seasonal
            residual_std = float(np.std(res.resid, ddof=1))
            seasonality_present = float(np.std(seasonal)) > 0.1 * float(np.std(arr))
        except Exception as exc:
            logger.debug("STL failed (%s), falling back to linear", exc)

    # --- Forecasting ---
    if trend_component is not None:
        # Extrapolate trend from STL
        tc = trend_component
        t_x = np.arange(len(tc), dtype=float)
        t_coeffs = np.polyfit(t_x, tc, 1)
    else:
        t_coeffs = coeffs

    sigma = residual_std if residual_std > 0 else (float(np.std(arr, ddof=1)) or 1.0)

    for k in range(1, forecast_periods + 1):
        fv = float(np.polyval(t_coeffs, n - 1 + k))
        projection_json.append(
            {
                "period_offset": k,
                "forecast": round(fv, 4),
                "lower_1sigma": round(fv - sigma, 4),
                "upper_1sigma": round(fv + sigma, 4),
                "lower_2sigma": round(fv - 2 * sigma, 4),
                "upper_2sigma": round(fv + 2 * sigma, 4),
            }
        )

    # --- Inflection detection ---
    if trend_component is not None and len(trend_component) >= 6:
        # Detect sign change in second derivative of trend
        second_diff = np.diff(np.diff(trend_component))
        recent = second_diff[-6:]
        if np.any(recent > 0.5 * sigma) and trend_direction == "down":
            inflection_signal = "potential_recovery"
            inflection_detail = "Trend curvature suggests deceleration of decline"
        elif np.any(recent < -0.5 * sigma) and trend_direction == "up":
            inflection_signal = "potential_plateau"
            inflection_detail = "Trend curvature suggests growth is slowing"

    # --- Anomaly density trend ---
    if anomaly_results:
        metric_anomalies = [
            a for a in anomaly_results if a["metric_name"] == metric_name
        ]
        if len(metric_anomalies) >= 3:
            anomaly_density_trend = "increasing"
        elif len(metric_anomalies) == 0:
            anomaly_density_trend = "none"
        else:
            anomaly_density_trend = "stable"

    return {
        "metric_name": metric_name,
        "forecast_periods": forecast_periods,
        "trend_direction": trend_direction,
        "trend_slope": trend_slope,
        "seasonality_present": seasonality_present,
        "inflection_signal": inflection_signal,
        "inflection_detail": inflection_detail,
        "projection_json": projection_json,
        "anomaly_density_trend": anomaly_density_trend,
        "chart_spec": None,  # filled by generate_correlation_charts step
    }


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

def run_correlation_intelligence(
    settings: Settings,
    correlation_run_id: str,
    tenant_id: str,
    domain_id: str,
    run_id: str | None = None,
    forecast_periods: int = 12,
    analysis_mode: str = "full",
    scoped_conn=None,
    profiling_stats: dict | None = None,
    semantic_context: dict | None = None,
) -> dict:
    """
    Entry point for the Phase 43 correlation intelligence run.

    Orchestrates:
      1. Load KPI snapshots
      2. Score anomalies per metric
      3. Build correlation matrix
      4. Build investigation threads
      5. Project each metric forward

    Returns a summary dict:
      {
        "correlation_run_id": str,
        "kpi_snapshots": list[dict],
        "anomaly_results": list[dict],
        "correlation_pairs": list[dict],
        "investigation_threads": list[dict],
        "forward_projections": list[dict],
        "metric_count": int,
        "anomaly_count": int,
        "correlation_pair_count": int,
        "thread_count": int,
        "error_message": str | None,
      }
    """
    logger.info(
        "[correlation] Starting run %s for tenant=%s domain=%s run_id=%s",
        correlation_run_id, tenant_id, domain_id, run_id,
    )

    error_message: str | None = None

    # --- Step 1: Load KPI snapshots ---
    kpi_snapshots: list[dict] = []
    snapshot_exclusions: list[dict] = []
    snapshot_eligibility_summary: dict[str, Any] = {
        "source_mode": "none",
        "rows_examined": 0,
        "eligible_snapshot_count": 0,
        "excluded_chart_count": 0,
        "excluded_by_reason": {},
    }
    try:
        snapshot_bundle = _load_kpi_snapshot_bundle(
            settings,
            tenant_id,
            domain_id,
            run_id=run_id,
            scoped_conn=scoped_conn, profiling_stats=profiling_stats,
        )
        kpi_snapshots = snapshot_bundle.get("kpi_snapshots") or []
        snapshot_exclusions = snapshot_bundle.get("snapshot_exclusions") or []
        snapshot_eligibility_summary = (
            snapshot_bundle.get("snapshot_eligibility_summary") or snapshot_eligibility_summary
        )
        logger.info("[correlation] Loaded %d KPI snapshots", len(kpi_snapshots))
        logger.info(
            "[correlation] Snapshot eligibility | source=%s examined=%s eligible=%s excluded=%s reasons=%s",
            snapshot_eligibility_summary.get("source_mode"),
            snapshot_eligibility_summary.get("rows_examined"),
            snapshot_eligibility_summary.get("eligible_snapshot_count"),
            snapshot_eligibility_summary.get("excluded_chart_count"),
            snapshot_eligibility_summary.get("excluded_by_reason"),
        )
    except Exception as exc:
        logger.exception("[correlation] Failed to load KPI snapshots")
        error_message = f"Snapshot load failed: {exc}"

    data_quality_warnings = _build_data_quality_warnings(
        snapshot_eligibility_summary,
        snapshot_exclusions,
    )

    if not kpi_snapshots:
        return {
            "correlation_run_id": correlation_run_id,
            "kpi_snapshots": [],
            "anomaly_results": [],
            "correlation_pairs": [],
            "investigation_threads": [],
            "forward_projections": [],
            "snapshot_exclusions": snapshot_exclusions,
            "snapshot_eligibility_summary": snapshot_eligibility_summary,
            "data_quality_warnings": data_quality_warnings,
            "semantic_context": semantic_context or {},
            "metric_count": 0,
            "anomaly_count": 0,
            "correlation_pair_count": 0,
            "thread_count": 0,
            "error_message": error_message or "No KPI snapshots found",
        }

    # --- Step 2: Score anomalies ---
    anomaly_results: list[dict] = []
    for snap in kpi_snapshots:
        # Extract dimension breakdown for the most anomalous period (if any)
        dim_breakdown: dict | None = None

        try:
            anoms = score_anomalies(
                snap["metric_name"],
                snap["series"],
                snap["timestamps"],
                dimension_breakdown=dim_breakdown,
            )
            # Now enrich with dimension breakdown for each anomaly
            for anom in anoms:
                db = extract_dimension_breakdown(snap, anom["detected_at"])
                if db:
                    anom["top_dimension"] = db.get("dimension")
                    anom["top_dimension_value"] = db.get("value")
                    anom["dimension_pct"] = db.get("pct")
            anomaly_results.extend(anoms)
        except Exception as exc:
            logger.warning(
                "[correlation] Anomaly scoring failed for %s: %s",
                snap["metric_name"], exc,
            )

    logger.info("[correlation] Detected %d anomalies", len(anomaly_results))

    # --- Step 3: Build correlation matrix ---
    correlation_pairs: list[dict] = []
    if len(kpi_snapshots) >= 2 and analysis_mode != "anomaly_only":
        try:
            correlation_pairs = build_correlation_matrix(kpi_snapshots)
            logger.info(
                "[correlation] Built %d correlation pairs", len(correlation_pairs)
            )
        except Exception as exc:
            logger.warning("[correlation] Correlation matrix failed: %s", exc)

    # --- Step 4: Build investigation threads ---
    investigation_threads: list[dict] = []
    if anomaly_results and correlation_pairs:
        try:
            investigation_threads = build_investigation_threads(
                anomaly_results, correlation_pairs
            )
            logger.info(
                "[correlation] Built %d investigation threads",
                len(investigation_threads),
            )
        except Exception as exc:
            logger.warning("[correlation] Investigation threading failed: %s", exc)

    # --- Step 5: Forward projections ---
    forward_projections: list[dict] = []
    if analysis_mode != "anomaly_only":
        for snap in kpi_snapshots:
            try:
                proj = project_forward(
                    snap["metric_name"],
                    snap["series"],
                    snap["timestamps"],
                    forecast_periods=forecast_periods,
                    anomaly_results=anomaly_results,
                )
                forward_projections.append(proj)
            except Exception as exc:
                logger.warning(
                    "[correlation] Projection failed for %s: %s",
                    snap["metric_name"], exc,
                )

    logger.info(
        "[correlation] Run %s complete — metrics=%d anomalies=%d pairs=%d threads=%d projections=%d",
        correlation_run_id,
        len(kpi_snapshots),
        len(anomaly_results),
        len(correlation_pairs),
        len(investigation_threads),
        len(forward_projections),
    )

    return {
        "correlation_run_id": correlation_run_id,
        "kpi_snapshots": kpi_snapshots,
        "anomaly_results": anomaly_results,
        "correlation_pairs": correlation_pairs,
        "investigation_threads": investigation_threads,
        "forward_projections": forward_projections,
        "snapshot_exclusions": snapshot_exclusions,
        "snapshot_eligibility_summary": snapshot_eligibility_summary,
        "data_quality_warnings": data_quality_warnings,
        "semantic_context": semantic_context or {},
        "metric_count": len(kpi_snapshots),
        "anomaly_count": len(anomaly_results),
        "correlation_pair_count": len(correlation_pairs),
        "thread_count": len(investigation_threads),
        "error_message": error_message,
    }
