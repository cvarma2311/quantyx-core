"""
Phase 43 — Persistence layer for correlation intelligence results.

Writes to (and reads from) the five Phase 43 tables:
  quantyx_correlation_runs
  quantyx_anomaly_results
  quantyx_correlation_pairs
  quantyx_investigation_threads
  quantyx_forward_projections

Follows the same psycopg2 / RealDictCursor pattern as charts_store.py.
All writes use INSERT ... ON CONFLICT DO UPDATE (upsert) so reruns are safe.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

import psycopg2
from psycopg2.extras import RealDictCursor, execute_values

from services.ai.config import Settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Connection helper
# ---------------------------------------------------------------------------

def _conn(settings: Settings):
    return psycopg2.connect(
        host=settings.db_host,
        port=settings.db_port,
        dbname=settings.db_name,
        user=settings.db_user,
        password=settings.db_password,
    )


def _j(value: Any) -> str | None:
    """Serialize to JSON string, or None if value is None."""
    if value is None:
        return None
    return json.dumps(value, default=str)


def _serialize_row(row: Any) -> dict:
    """Convert a psycopg2 RealDictRow to a plain dict, serializing
    datetime objects to ISO strings so that Pydantic Optional[str]
    fields in the API response model don't cause a 500."""
    result: dict = {}
    for k, v in dict(row).items():
        if isinstance(v, datetime):
            result[k] = v.isoformat()
        else:
            result[k] = v
    return result


# ---------------------------------------------------------------------------
# quantyx_correlation_runs
# ---------------------------------------------------------------------------

def _fallback_run_dict(
    correlation_run_id: str,
    tenant_id: str,
    domain_id: str,
    run_id: str,
    analysis_mode: str,
    forecast_periods: int,
) -> dict:
    """Minimal dict matching CorrelationRunResponse when the table doesn't exist yet."""
    return {
        "correlation_run_id": correlation_run_id,
        "tenant_id": tenant_id,
        "domain_id": domain_id,
        "run_id": run_id,
        "status": "running",
        "analysis_mode": analysis_mode,
        "forecast_periods": forecast_periods,
        "metric_count": None,
        "anomaly_count": None,
        "correlation_pair_count": None,
        "thread_count": None,
        "error_message": None,
        "triggered_by": None,
        "summary_text": None,
        "summary_html": None,
        "started_at": None,
        "completed_at": None,
        "created_at": None,
        "updated_at": None,
    }


def create_correlation_run(
    settings: Settings,
    *,
    correlation_run_id: str,
    tenant_id: str,
    domain_id: str,
    run_id: str,
    analysis_mode: str = "full",
    forecast_periods: int = 12,
    triggered_by: str | None = None,
) -> dict:
    """
    Insert a new correlation run record with status='running'.
    Returns the inserted row as a dict.
    Degrades gracefully if Phase 43 tables have not been created yet.
    """
    sql = """
        INSERT INTO public.quantyx_correlation_runs
          (correlation_run_id, tenant_id, domain_id, run_id,
           analysis_mode, status, forecast_periods, triggered_by,
           started_at, created_at, updated_at)
        VALUES
          (%s, %s, %s, %s, %s, 'running', %s, %s,
           now(), now(), now())
        ON CONFLICT (correlation_run_id) DO UPDATE
          SET status     = 'running',
              started_at = now(),
              updated_at = now()
        RETURNING *
    """
    c = _conn(settings)
    try:
        with c.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                sql,
                [
                    correlation_run_id, tenant_id, domain_id, run_id,
                    analysis_mode, forecast_periods, triggered_by,
                ],
            )
            row = cur.fetchone()
        c.commit()
        return _serialize_row(row) if row else _fallback_run_dict(
            correlation_run_id, tenant_id, domain_id, run_id, analysis_mode, forecast_periods
        )
    except psycopg2.errors.UndefinedTable:
        c.rollback()
        logger.warning(
            "[correlation.store] quantyx_correlation_runs table missing — "
            "run bash scripts/apply_agentic_tables.sh to create Phase 43 tables"
        )
        return _fallback_run_dict(
            correlation_run_id, tenant_id, domain_id, run_id, analysis_mode, forecast_periods
        )
    finally:
        c.close()


def update_correlation_run(
    settings: Settings,
    correlation_run_id: str,
    *,
    status: str,
    metric_count: int | None = None,
    anomaly_count: int | None = None,
    correlation_pair_count: int | None = None,
    thread_count: int | None = None,
    error_message: str | None = None,
    summary_text: str | None = None,
    summary_html: str | None = None,
) -> None:
    """Update status + counters on a correlation run (called at completion)."""
    fields = ["status = %s", "updated_at = now()"]
    values: list[Any] = [status]

    if metric_count is not None:
        fields.append("metric_count = %s"); values.append(metric_count)
    if anomaly_count is not None:
        fields.append("anomaly_count = %s"); values.append(anomaly_count)
    if correlation_pair_count is not None:
        fields.append("correlation_pair_count = %s"); values.append(correlation_pair_count)
    if thread_count is not None:
        fields.append("thread_count = %s"); values.append(thread_count)
    if error_message is not None:
        fields.append("error_message = %s"); values.append(error_message)
    if summary_text is not None:
        fields.append("summary_text = %s"); values.append(summary_text)
    if summary_html is not None:
        fields.append("summary_html = %s"); values.append(summary_html)
    if status in ("done", "failed"):
        fields.append("completed_at = now()")

    values.append(correlation_run_id)
    sql = f"""
        UPDATE public.quantyx_correlation_runs
           SET {", ".join(fields)}
         WHERE correlation_run_id = %s
    """
    c = _conn(settings)
    try:
        with c.cursor() as cur:
            cur.execute(sql, values)
        c.commit()
    except psycopg2.errors.UndefinedTable:
        c.rollback()
        logger.warning("[correlation.store] quantyx_correlation_runs table missing — update skipped")
    finally:
        c.close()


def get_correlation_run(
    settings: Settings,
    correlation_run_id: str,
) -> dict | None:
    sql = """
        SELECT * FROM public.quantyx_correlation_runs
         WHERE correlation_run_id = %s
    """
    c = _conn(settings)
    try:
        with c.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, [correlation_run_id])
            row = cur.fetchone()
        return _serialize_row(row) if row else None
    except psycopg2.errors.UndefinedTable:
        c.rollback()
        logger.warning("[correlation.store] quantyx_correlation_runs table missing — get skipped")
        return None
    finally:
        c.close()


def list_correlation_runs(
    settings: Settings,
    tenant_id: str,
    domain_id: str,
    limit: int = 20,
) -> list[dict]:
    sql = """
        SELECT * FROM public.quantyx_correlation_runs
         WHERE tenant_id = %s AND domain_id = %s
         ORDER BY created_at DESC
         LIMIT %s
    """
    c = _conn(settings)
    try:
        with c.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, [tenant_id, domain_id, limit])
            rows = cur.fetchall()
        return [_serialize_row(r) for r in rows]
    except psycopg2.errors.UndefinedTable:
        c.rollback()
        logger.warning("[correlation.store] quantyx_correlation_runs table missing — list skipped")
        return []
    finally:
        c.close()


def get_latest_correlation_run(
    settings: Settings,
    tenant_id: str,
    domain_id: str,
    run_id: str | None = None,
) -> dict | None:
    if run_id:
        sql = """
            SELECT * FROM public.quantyx_correlation_runs
             WHERE run_id = %s AND status = 'done'
             ORDER BY created_at DESC LIMIT 1
        """
        params = [run_id]
    else:
        sql = """
            SELECT * FROM public.quantyx_correlation_runs
             WHERE tenant_id = %s AND domain_id = %s AND status = 'done'
             ORDER BY created_at DESC LIMIT 1
        """
        params = [tenant_id, domain_id]

    c = _conn(settings)
    try:
        with c.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
        return dict(row) if row else None
    except psycopg2.errors.UndefinedTable:
        c.rollback()
        logger.warning("[correlation.store] quantyx_correlation_runs table missing — get_latest skipped")
        return None
    finally:
        c.close()


# ---------------------------------------------------------------------------
# quantyx_anomaly_results
# ---------------------------------------------------------------------------

def save_anomaly_results(
    settings: Settings,
    correlation_run_id: str,
    tenant_id: str,
    domain_id: str,
    anomaly_results: list[dict],
) -> int:
    """
    Bulk-insert anomaly results.  Returns count inserted.
    Uses execute_values for efficiency.
    """
    if not anomaly_results:
        return 0

    sql = """
        INSERT INTO public.quantyx_anomaly_results
          (anomaly_id, correlation_run_id, tenant_id, domain_id,
           metric_name, anomaly_class, anomaly_score, z_score,
           iqr_flag, cusum_signal, detected_at, period_label,
           baseline_value, observed_value, deviation_pct,
           top_dimension, top_dimension_value, dimension_pct,
           stats_json, created_at)
        VALUES %s
        ON CONFLICT (anomaly_id) DO NOTHING
    """
    rows = [
        (
            a["anomaly_id"],
            correlation_run_id,
            tenant_id,
            domain_id,
            a["metric_name"],
            a["anomaly_class"],
            a["anomaly_score"],
            a.get("z_score"),
            a.get("iqr_flag", False),
            a.get("cusum_signal", False),
            a["detected_at"],
            a.get("period_label"),
            a.get("baseline_value"),
            a["observed_value"],
            a.get("deviation_pct"),
            a.get("top_dimension"),
            a.get("top_dimension_value"),
            a.get("dimension_pct"),
            _j(a.get("stats_json")),
            datetime.now(timezone.utc),
        )
        for a in anomaly_results
    ]

    c = _conn(settings)
    try:
        with c.cursor() as cur:
            execute_values(cur, sql, rows)
        c.commit()
        return len(rows)
    except psycopg2.errors.UndefinedTable:
        c.rollback()
        logger.warning("[correlation.store] quantyx_anomaly_results table missing — save skipped")
        return 0
    finally:
        c.close()


def get_anomaly_results(
    settings: Settings,
    correlation_run_id: str,
    metric_name: str | None = None,
    min_score: float = 0.0,
    limit: int = 200,
) -> list[dict]:
    conditions = ["correlation_run_id = %s", "anomaly_score >= %s"]
    params: list[Any] = [correlation_run_id, min_score]
    if metric_name:
        conditions.append("metric_name = %s")
        params.append(metric_name)
    params.append(limit)

    sql = f"""
        SELECT * FROM public.quantyx_anomaly_results
         WHERE {" AND ".join(conditions)}
         ORDER BY anomaly_score DESC
         LIMIT %s
    """
    c = _conn(settings)
    try:
        with c.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
        return [dict(r) for r in rows]
    except psycopg2.errors.UndefinedTable:
        c.rollback()
        logger.warning("[correlation.store] quantyx_anomaly_results table missing — get skipped")
        return []
    finally:
        c.close()


# ---------------------------------------------------------------------------
# quantyx_correlation_pairs
# ---------------------------------------------------------------------------

def save_correlation_pairs(
    settings: Settings,
    correlation_run_id: str,
    tenant_id: str,
    domain_id: str,
    correlation_pairs: list[dict],
) -> int:
    """Bulk-insert correlation pairs.  Returns count inserted."""
    if not correlation_pairs:
        return 0

    sql = """
        INSERT INTO public.quantyx_correlation_pairs
          (pair_id, correlation_run_id, tenant_id, domain_id,
           metric_a, metric_b, pearson_r, spearman_rho,
           best_lag, lagged_r, lag_direction,
           strength_label, direction_label,
           sample_size, p_value, is_stable,
           rolling_r_json, created_at)
        VALUES %s
        ON CONFLICT (correlation_run_id, metric_a, metric_b) DO UPDATE
          SET pearson_r    = EXCLUDED.pearson_r,
              spearman_rho = EXCLUDED.spearman_rho,
              best_lag     = EXCLUDED.best_lag,
              lagged_r     = EXCLUDED.lagged_r,
              lag_direction= EXCLUDED.lag_direction,
              strength_label = EXCLUDED.strength_label,
              direction_label = EXCLUDED.direction_label,
              is_stable    = EXCLUDED.is_stable,
              rolling_r_json = EXCLUDED.rolling_r_json
    """
    rows = [
        (
            p["pair_id"],
            correlation_run_id,
            tenant_id,
            domain_id,
            p["metric_a"],
            p["metric_b"],
            p.get("pearson_r"),
            p.get("spearman_rho"),
            p.get("best_lag"),
            p.get("lagged_r"),
            p.get("lag_direction"),
            p.get("strength_label", "weak"),
            p.get("direction_label", "positive"),
            p.get("sample_size"),
            p.get("p_value"),
            p.get("is_stable", True),
            _j(p.get("rolling_r_json")),
            datetime.now(timezone.utc),
        )
        for p in correlation_pairs
    ]

    c = _conn(settings)
    try:
        with c.cursor() as cur:
            execute_values(cur, sql, rows)
        c.commit()
        return len(rows)
    except psycopg2.errors.UndefinedTable:
        c.rollback()
        logger.warning("[correlation.store] quantyx_correlation_pairs table missing — save skipped")
        return 0
    finally:
        c.close()


def get_correlation_pairs(
    settings: Settings,
    correlation_run_id: str,
    metric_name: str | None = None,
    min_abs_r: float = 0.0,
    limit: int = 100,
) -> list[dict]:
    params: list[Any] = [correlation_run_id, min_abs_r, limit]
    metric_filter = ""
    if metric_name:
        metric_filter = "AND (metric_a = %s OR metric_b = %s)"
        params = [correlation_run_id, min_abs_r, metric_name, metric_name, limit]

    sql = f"""
        SELECT * FROM public.quantyx_correlation_pairs
         WHERE correlation_run_id = %s
           AND ABS(COALESCE(pearson_r, 0)) >= %s
           {metric_filter}
         ORDER BY ABS(COALESCE(pearson_r, 0)) DESC
         LIMIT %s
    """
    c = _conn(settings)
    try:
        with c.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
        return [dict(r) for r in rows]
    except psycopg2.errors.UndefinedTable:
        c.rollback()
        logger.warning("[correlation.store] quantyx_correlation_pairs table missing — get skipped")
        return []
    finally:
        c.close()


# ---------------------------------------------------------------------------
# quantyx_investigation_threads
# ---------------------------------------------------------------------------

def save_investigation_threads(
    settings: Settings,
    correlation_run_id: str,
    tenant_id: str,
    domain_id: str,
    investigation_threads: list[dict],
) -> int:
    """Bulk-insert investigation threads.  Returns count inserted."""
    if not investigation_threads:
        return 0

    sql = """
        INSERT INTO public.quantyx_investigation_threads
          (thread_id, correlation_run_id, tenant_id, domain_id,
           trigger_metric, trigger_anomaly_id,
           evidence_chain, leading_dimension, leading_dim_value,
           confidence, suggested_focus,
           narrative_text, narrative_html, created_at)
        VALUES %s
        ON CONFLICT (thread_id) DO UPDATE
          SET evidence_chain   = EXCLUDED.evidence_chain,
              confidence       = EXCLUDED.confidence,
              narrative_text   = EXCLUDED.narrative_text,
              narrative_html   = EXCLUDED.narrative_html
    """
    rows = [
        (
            t["thread_id"],
            correlation_run_id,
            tenant_id,
            domain_id,
            t["trigger_metric"],
            t["trigger_anomaly_id"],
            _j(t.get("evidence_chain") or []),
            t.get("leading_dimension"),
            t.get("leading_dim_value"),
            t["confidence"],
            _j(t.get("suggested_focus") or []),
            t.get("narrative_text"),
            t.get("narrative_html"),
            datetime.now(timezone.utc),
        )
        for t in investigation_threads
    ]

    c = _conn(settings)
    try:
        with c.cursor() as cur:
            execute_values(cur, sql, rows)
        c.commit()
        return len(rows)
    except psycopg2.errors.UndefinedTable:
        c.rollback()
        logger.warning("[correlation.store] quantyx_investigation_threads table missing — save skipped")
        return 0
    finally:
        c.close()


def get_investigation_threads(
    settings: Settings,
    correlation_run_id: str,
    metric_name: str | None = None,
    min_confidence: float = 0.0,
    limit: int = 50,
) -> list[dict]:
    params: list[Any] = [correlation_run_id, min_confidence, limit]
    metric_filter = ""
    if metric_name:
        metric_filter = "AND trigger_metric = %s"
        params = [correlation_run_id, min_confidence, metric_name, limit]

    sql = f"""
        SELECT * FROM public.quantyx_investigation_threads
         WHERE correlation_run_id = %s
           AND confidence >= %s
           {metric_filter}
         ORDER BY confidence DESC
         LIMIT %s
    """
    c = _conn(settings)
    try:
        with c.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
        return [dict(r) for r in rows]
    except psycopg2.errors.UndefinedTable:
        c.rollback()
        logger.warning("[correlation.store] quantyx_investigation_threads table missing — get skipped")
        return []
    finally:
        c.close()


# ---------------------------------------------------------------------------
# quantyx_forward_projections
# ---------------------------------------------------------------------------

def save_forward_projections(
    settings: Settings,
    correlation_run_id: str,
    tenant_id: str,
    domain_id: str,
    forward_projections: list[dict],
) -> int:
    """Bulk-insert forward projections.  Returns count inserted."""
    if not forward_projections:
        return 0

    sql = """
        INSERT INTO public.quantyx_forward_projections
          (projection_id, correlation_run_id, tenant_id, domain_id,
           metric_name, forecast_periods, trend_direction, trend_slope,
           seasonality_present, inflection_signal, inflection_detail,
           projection_json, anomaly_density_trend, chart_spec, created_at)
        VALUES %s
        ON CONFLICT (projection_id) DO NOTHING
    """
    rows = [
        (
            f"proj_{p['metric_name'][:20].replace(' ', '_')}_{correlation_run_id[-8:]}",
            correlation_run_id,
            tenant_id,
            domain_id,
            p["metric_name"],
            p.get("forecast_periods", 12),
            p.get("trend_direction", "flat"),
            p.get("trend_slope"),
            p.get("seasonality_present", False),
            p.get("inflection_signal"),
            p.get("inflection_detail"),
            _j(p.get("projection_json") or []),
            p.get("anomaly_density_trend"),
            _j(p.get("chart_spec")),
            datetime.now(timezone.utc),
        )
        for p in forward_projections
    ]

    c = _conn(settings)
    try:
        with c.cursor() as cur:
            execute_values(cur, sql, rows)
        c.commit()
        return len(rows)
    except psycopg2.errors.UndefinedTable:
        c.rollback()
        logger.warning("[correlation.store] quantyx_forward_projections table missing — save skipped")
        return 0
    finally:
        c.close()


def get_forward_projections(
    settings: Settings,
    correlation_run_id: str,
    metric_name: str | None = None,
) -> list[dict]:
    params: list[Any] = [correlation_run_id]
    metric_filter = ""
    if metric_name:
        metric_filter = "AND metric_name = %s"
        params.append(metric_name)

    sql = f"""
        SELECT * FROM public.quantyx_forward_projections
         WHERE correlation_run_id = %s
           {metric_filter}
         ORDER BY metric_name
    """
    c = _conn(settings)
    try:
        with c.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
        return [dict(r) for r in rows]
    except psycopg2.errors.UndefinedTable:
        c.rollback()
        logger.warning("[correlation.store] quantyx_forward_projections table missing — get skipped")
        return []
    finally:
        c.close()


# ---------------------------------------------------------------------------
# Orchestrated save: write everything from one run result dict
# ---------------------------------------------------------------------------

def save_correlation_run_results(
    settings: Settings,
    *,
    correlation_run_id: str,
    tenant_id: str,
    domain_id: str,
    run_result: dict,
    summary_text: str = "",
    summary_html: str = "",
) -> dict:
    """
    Persist all outputs from run_correlation_intelligence() + narrate step.

    run_result keys expected:
      anomaly_results, correlation_pairs, investigation_threads,
      forward_projections, metric_count, anomaly_count,
      correlation_pair_count, thread_count, error_message

    Returns a summary dict with row counts.
    """
    anomaly_results       = run_result.get("anomaly_results") or []
    correlation_pairs     = run_result.get("correlation_pairs") or []
    investigation_threads = run_result.get("investigation_threads") or []
    forward_projections   = run_result.get("forward_projections") or []
    error_message         = run_result.get("error_message")

    counts: dict[str, int] = {}

    try:
        counts["anomalies"] = save_anomaly_results(
            settings, correlation_run_id, tenant_id, domain_id, anomaly_results
        )
        logger.info("[correlation.store] Saved %d anomalies", counts["anomalies"])
    except Exception:
        logger.exception("[correlation.store] Failed to save anomaly results")
        counts["anomalies"] = 0

    try:
        counts["pairs"] = save_correlation_pairs(
            settings, correlation_run_id, tenant_id, domain_id, correlation_pairs
        )
        logger.info("[correlation.store] Saved %d correlation pairs", counts["pairs"])
    except Exception:
        logger.exception("[correlation.store] Failed to save correlation pairs")
        counts["pairs"] = 0

    try:
        counts["threads"] = save_investigation_threads(
            settings, correlation_run_id, tenant_id, domain_id, investigation_threads
        )
        logger.info("[correlation.store] Saved %d investigation threads", counts["threads"])
    except Exception:
        logger.exception("[correlation.store] Failed to save investigation threads")
        counts["threads"] = 0

    try:
        counts["projections"] = save_forward_projections(
            settings, correlation_run_id, tenant_id, domain_id, forward_projections
        )
        logger.info("[correlation.store] Saved %d forward projections", counts["projections"])
    except Exception:
        logger.exception("[correlation.store] Failed to save forward projections")
        counts["projections"] = 0

    # Final status update on the run record
    final_status = "failed" if error_message else "done"
    try:
        update_correlation_run(
            settings,
            correlation_run_id,
            status=final_status,
            metric_count=run_result.get("metric_count"),
            anomaly_count=len(anomaly_results),
            correlation_pair_count=len(correlation_pairs),
            thread_count=len(investigation_threads),
            error_message=error_message,
            summary_text=summary_text or None,
            summary_html=summary_html or None,
        )
    except Exception:
        logger.exception("[correlation.store] Failed to update correlation run status")

    return {
        "correlation_run_id": correlation_run_id,
        "status": final_status,
        **counts,
    }