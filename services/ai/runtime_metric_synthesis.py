"""
Runtime metric synthesis.

When a user asks for a metric that was never certified during the agentic
onboarding run, this module fills the gap at query time:

  1. Fetches the most recent profiling artifact for the scope
     (quantyx_table_profile_artifacts).
  2. For each unresolved metric candidate, scores all eligible numeric columns
     from the profiling data using token overlap between the candidate name and
     the column / table name.
  3. Builds an in-memory Metric object using a SUM aggregate over the best
     matching column.
  4. Optionally persists the new metric to quantyx_metrics_registry with
     lifecycle_status='suggested', so subsequent queries (and the next agentic
     run) find it without re-synthesis.

The synthesized Metric objects are injected into the MetricCatalog before
validate_workspace_query_plan runs, so bind_metric can resolve them just like
any certified metric.
"""

from __future__ import annotations

import logging
import re
from datetime import date
from typing import TYPE_CHECKING, Any

from services.ai.catalog import Metric, MetricCatalog

if TYPE_CHECKING:
    from services.ai.config import Settings

logger = logging.getLogger(__name__)

# Tokens that carry no discriminating signal for column matching.
_STOP_TOKENS: frozenset[str] = frozenset(
    {"sum", "avg", "count", "min", "max", "of", "the", "a", "an", "per", "by", "total"}
)

# Token sets that signal the temporal nature of a metric name
_PRIOR_FY_TOKENS: frozenset[str] = frozenset(
    {"history", "historical", "historic", "prior", "prev", "previous", "last"}
)
_TARGET_TOKENS: frozenset[str] = frozenset(
    {"target", "budget", "plan", "forecast"}
)
_ACTUAL_TOKENS: frozenset[str] = frozenset(
    {"actual", "current", "ytd"}
)

# Column name pattern that indicates a YYYYMMDD integer date (e.g. DAY_ID, DATE_ID)
_DAY_ID_COL_PATTERN = re.compile(r"(?i)^(day[_\s]?id|date[_\s]?id|day|date[_\s]?key)$")


def _tokens(name: str) -> set[str]:
    """Split a snake_case / space-separated name into a normalised token set."""
    return set(re.split(r"[_\s\-]+", name.lower())) - _STOP_TOKENS - {""}


def _detect_temporal_semantic(candidate: str) -> str | None:
    """
    Returns the fiscal-year intent of a metric name.
    - 'prior_fy'   → history / prior year (e.g. actual_history_tmt_sales)
    - 'current_fy' → current FY actuals or targets
    - None         → no strong temporal signal
    """
    toks = _tokens(candidate)
    if toks & _PRIOR_FY_TOKENS:
        return "prior_fy"
    if toks & (_ACTUAL_TOKENS | _TARGET_TOKENS):
        return "current_fy"
    return None


def _compute_fy_dates(*, prior: bool = False) -> tuple[str, str]:
    """
    Compute Indian fiscal year (April 1 – March 31) date bounds as YYYYMMDD strings.
    India FY runs April → March; month >= 4 means we are in the FY that started this year.
    """
    today = date.today()
    fy_start_year = today.year if today.month >= 4 else today.year - 1
    if prior:
        fy_start_year -= 1
    return f"{fy_start_year}0401", f"{fy_start_year + 1}0331"


def _compute_fy_dates_iso(*, prior: bool = False) -> tuple[str, str]:
    """Same as _compute_fy_dates but returns ISO YYYY-MM-DD strings."""
    start_yyyymmdd, end_yyyymmdd = _compute_fy_dates(prior=prior)
    def _fmt(s: str) -> str:
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    return _fmt(start_yyyymmdd), _fmt(end_yyyymmdd)


def _find_date_column(tbl: dict[str, Any]) -> tuple[str | None, str | None]:
    """
    Returns (column_name, format) for the best date/time column in a table.
    format is 'yyyymmdd' for integer date keys or 'iso_date' for real DATE columns.
    Checks time_columns first; falls back to searching numeric columns for DAY_ID patterns.
    """
    time_cols: list[str] = tbl.get("time_columns") or []
    if time_cols:
        return time_cols[0], "iso_date"
    for col in (tbl.get("numeric_columns") or []):
        if _DAY_ID_COL_PATTERN.match(col):
            return col, "yyyymmdd"
    return None, None


def _match_score(candidate: str, col_name: str, table_name: str) -> float:
    """
    Returns a [0, 1] token-overlap score between the requested metric name and
    a candidate (column_name, table_name) pair.

    Semantic adjustments:
    - "actual/history" metrics are penalised when the column name contains "target"
    - "target" metrics are penalised when the column name does not contain "target"
    This steers actual_tmt_sales → NETWEIGHT_TMT and target_tmt_sales → TARGET_QTY_TMT.
    """
    req = _tokens(candidate)
    if not req:
        return 0.0
    col_tokens = _tokens(col_name) | _tokens(table_name)
    base = len(req & col_tokens) / max(len(req), 1)
    if base == 0.0:
        return 0.0

    is_actual_like = bool(req & (_ACTUAL_TOKENS | _PRIOR_FY_TOKENS)) and not (req & _TARGET_TOKENS)
    is_target_like = bool(req & _TARGET_TOKENS) and not (req & (_ACTUAL_TOKENS | _PRIOR_FY_TOKENS))
    col_has_target = "target" in _tokens(col_name)

    if is_actual_like and col_has_target:
        base *= 0.2  # strongly penalise target columns for actual/history metrics
    if is_target_like and not col_has_target:
        base *= 0.5  # mildly penalise non-target columns for target metrics
    return base


def _build_date_aware_metric_sql(
    table_name: str,
    value_col: str,
    date_col: str,
    date_format: str,
    temporal: str,
) -> str:
    """
    Build a SUM(CASE WHEN <fy_filter> THEN col ELSE 0 END) expression so the
    metric only counts rows within the relevant fiscal year window.

    date_format: 'yyyymmdd' for integer date keys, 'iso_date' for real DATE cols.
    temporal: 'current_fy' or 'prior_fy'.
    """
    is_prior = temporal == "prior_fy"
    ref = f"{{{{ ref('{table_name}') }}}}"

    if date_format == "yyyymmdd":
        start, end = _compute_fy_dates(prior=is_prior)
        # Cast to varchar so integer DAY_ID can be compared as string YYYYMMDD
        date_cond = f'{ref}."{date_col}"::varchar BETWEEN \'{start}\' AND \'{end}\''
    else:
        start, end = _compute_fy_dates_iso(prior=is_prior)
        date_cond = f'{ref}."{date_col}"::date BETWEEN \'{start}\' AND \'{end}\''

    return f'SUM(CASE WHEN {date_cond} THEN {ref}."{value_col}" ELSE 0 END)'


def fetch_profiling_artifact(
    settings: "Settings",
    *,
    tenant_id: str,
    domain_id: str,
    connection_id: str,
    database_name: str,
    schema_name: str,
) -> dict[str, Any] | None:
    """
    Return the profiling_json from the most recent is_current profiling artifact
    for this scope. Returns None if none exists or the fetch fails.
    """
    from services.ai.db import run_query

    sql = """
        SELECT profiling_json
          FROM public.quantyx_table_profile_artifacts
         WHERE tenant_id     = %s
           AND domain_id     = %s
           AND connection_id = %s
           AND database_name = %s
           AND schema_name   = %s
           AND COALESCE(is_current, true) = true
         ORDER BY updated_at DESC
         LIMIT 1
    """
    try:
        rows = run_query(
            settings,
            sql,
            [tenant_id, domain_id, connection_id, database_name, schema_name],
        )
        if rows and rows[0].get("profiling_json"):
            return rows[0]["profiling_json"]
    except Exception as exc:
        logger.warning("[runtime_synthesis] profiling artifact fetch failed: %s", exc)
    return None


def synthesize_metrics(
    *,
    settings: "Settings",
    candidates: list[str],
    profiling: dict[str, Any],
    schema_name: str,
    tenant_id: str,
    domain_id: str,
    connection_id: str,
    database_name: str,
    source_run_id: str | None = None,
    persist: bool = True,
    min_score: float = 0.25,
) -> list[Metric]:
    """
    For each candidate name not already bound in the catalog, find the best
    matching eligible column from the profiling artifact and build a Metric.

    - persist=True (default): upserts to quantyx_metrics_registry as 'suggested'
      so the next query / agentic run finds it without re-synthesis.
    - min_score: minimum token-overlap score to accept a column match (0–1).
      Defaults to 0.25 — at least 1 token must match out of 4 candidate tokens.
    """
    from services.ai.metrics_registry import upsert_metric

    tables: list[dict[str, Any]] = profiling.get("tables") or []
    synthesized: list[Metric] = []

    for candidate in candidates:
        best_score = 0.0
        best_col: str | None = None
        best_table: str | None = None
        best_tbl_dict: dict[str, Any] | None = None

        for tbl in tables:
            tbl_name: str = tbl.get("name") or ""
            eligible: set[str] = set(tbl.get("eligible_numeric_columns") or [])
            numeric: set[str] = set(tbl.get("numeric_columns") or [])
            semantics: dict[str, dict] = {
                s["name"]: s for s in (tbl.get("column_semantics") or [])
            }

            for col in eligible | numeric:
                sem = semantics.get(col, {})
                # Skip if column is explicitly flagged as non-measure
                if not sem.get("eligible_measure", col in eligible):
                    continue
                score = _match_score(candidate, col, tbl_name)
                if score > best_score:
                    best_score = score
                    best_col = col
                    best_table = tbl_name
                    best_tbl_dict = tbl

        if not best_col or best_score < min_score:
            logger.info(
                "[runtime_synthesis] no column match for candidate=%s "
                "best_col=%s score=%.2f min=%.2f",
                candidate, best_col, best_score, min_score,
            )
            continue

        # Detect temporal semantic (current vs prior FY) and build a date-aware SQL
        # expression that scopes the SUM to the correct fiscal year window.
        # Indian FY: April 1 – March 31.
        temporal = _detect_temporal_semantic(candidate)
        date_col, date_fmt = _find_date_column(best_tbl_dict or {})

        if temporal and date_col and date_fmt:
            sql_expr = _build_date_aware_metric_sql(best_table, best_col, date_col, date_fmt, temporal)
            is_prior = temporal == "prior_fy"
            fy_start, fy_end = (
                _compute_fy_dates_iso(prior=is_prior)
                if date_fmt == "iso_date"
                else _compute_fy_dates(prior=is_prior)
            )
            description = (
                f"Runtime-synthesized from {best_table}.{best_col} "
                f"({'prior' if is_prior else 'current'} FY {fy_start} – {fy_end})"
            )
        else:
            # No temporal signal or no date column — plain SUM, no date scoping
            sql_expr = f'SUM({{{{ ref(\'{best_table}\') }}}}."{best_col}")'
            description = f"Runtime-synthesized from {best_table}.{best_col}"

        model_ref = f"fact_{best_table}"  # kept for registry metadata only

        metric = Metric(
            name=candidate,
            description=description,
            metric_type="sum",
            sql=sql_expr,
            grain="day",
            dimensions=[],
            status="suggested",
            semantic_metadata={"temporal": temporal, "date_col": date_col, "date_fmt": date_fmt},
        )
        synthesized.append(metric)
        logger.info(
            "[runtime_synthesis] synthesized metric=%s from col=%s table=%s score=%.2f temporal=%s date_col=%s",
            candidate, best_col, best_table, best_score, temporal, date_col,
        )

        if persist:
            try:
                upsert_metric(settings, {
                    "metric_name": candidate,
                    "display_name": candidate.replace("_", " ").title(),
                    "description": f"Runtime-synthesized from column {best_col} in {best_table}",
                    "type": "sum",
                    "sql": sql_expr,
                    "grain": "day",
                    "dimensions": [],
                    "dataset_id": f"fact_{best_table}",
                    "source_model": model_ref,
                    "source_schema": schema_name,
                    "tenant_id": tenant_id,
                    "domain_id": domain_id,
                    "connection_id": connection_id,
                    "database": database_name,
                    "schema": schema_name,
                    "lifecycle_status": "suggested",
                    "source_type": "runtime_synthesis",
                    "source_run_id": source_run_id or "",
                })
                logger.info(
                    "[runtime_synthesis] persisted metric=%s to registry as suggested", candidate
                )
            except Exception as exc:
                logger.warning(
                    "[runtime_synthesis] failed to persist metric=%s: %s", candidate, exc
                )

    return synthesized


def augment_catalog(
    catalog: MetricCatalog,
    synthesized: list[Metric],
) -> MetricCatalog:
    """
    Return a new MetricCatalog with the synthesized metrics added.
    The original catalog is not mutated (it is frozen).
    """
    if not synthesized:
        return catalog
    augmented_metrics = dict(catalog.metrics)
    for metric in synthesized:
        if metric.name not in augmented_metrics:
            augmented_metrics[metric.name] = metric
    return MetricCatalog(metrics=augmented_metrics, dimensions=catalog.dimensions)


def try_augment_catalog_from_profiling(
    *,
    settings: "Settings",
    metric_catalog: MetricCatalog,
    metric_candidates: list[str],
    tenant_id: str,
    domain_id: str,
    connection_id: str,
    database_name: str,
    schema_name: str,
    source_run_id: str | None = None,
) -> MetricCatalog:
    """
    High-level entry point called from the workspace query pipeline.

    Identifies which candidates are missing from the current catalog, fetches
    the profiling artifact, synthesizes Metric objects for the missing ones,
    persists them as 'suggested', and returns an augmented MetricCatalog.

    If profiling data is unavailable or no candidates match, the original
    catalog is returned unchanged.
    """
    if not metric_candidates:
        return metric_catalog

    # Only attempt synthesis for candidates not already in the catalog
    normalized_existing = {name.lower() for name in metric_catalog.metrics}
    missing = [
        c for c in metric_candidates
        if c.lower() not in normalized_existing
    ]
    if not missing:
        return metric_catalog

    logger.info(
        "[runtime_synthesis] %d candidate(s) missing from catalog, attempting synthesis: %s",
        len(missing), missing,
    )

    profiling = fetch_profiling_artifact(
        settings,
        tenant_id=tenant_id,
        domain_id=domain_id,
        connection_id=connection_id,
        database_name=database_name,
        schema_name=schema_name,
    )
    if not profiling:
        logger.warning(
            "[runtime_synthesis] no profiling artifact found for tenant=%s domain=%s — "
            "cannot synthesize metrics",
            tenant_id, domain_id,
        )
        return metric_catalog

    synthesized = synthesize_metrics(
        settings=settings,
        candidates=missing,
        profiling=profiling,
        schema_name=schema_name,
        tenant_id=tenant_id,
        domain_id=domain_id,
        connection_id=connection_id,
        database_name=database_name,
        source_run_id=source_run_id,
        persist=True,
    )

    if synthesized:
        logger.info(
            "[runtime_synthesis] augmenting catalog with %d synthesized metric(s): %s",
            len(synthesized), [m.name for m in synthesized],
        )
        return augment_catalog(metric_catalog, synthesized)

    return metric_catalog