from __future__ import annotations

import json
import uuid
from datetime import date, datetime, time as dt_time
from decimal import Decimal
from typing import Any

from psycopg2.extras import Json

from services.ai.config import Settings
from services.ai.db import execute_non_query, run_query


def _json_default(value: Any) -> Any:
    if isinstance(value, (datetime, date, dt_time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return str(value)


def _json_dumps(value: Any) -> str:
    return json.dumps(value, default=_json_default)


def create_dashboard_refresh_run(
    settings: Settings,
    *,
    dashboard_id: str,
    tenant_id: str,
    domain_id: str,
    trigger_source: str,
    requested_by: str | None,
    request_payload: dict[str, Any] | None = None,
) -> str:
    refresh_id = f"dref_{uuid.uuid4().hex[:12]}"
    execute_non_query(
        settings,
        """
        INSERT INTO public.quantyx_dashboard_refresh_runs (
          refresh_id, dashboard_id, tenant_id, domain_id, status, trigger_source, requested_by,
          request_payload, created_at, updated_at
        )
        VALUES (%s, %s, %s, %s, 'queued', %s, %s, %s::jsonb, now(), now())
        """,
        [
            refresh_id,
            dashboard_id,
            tenant_id,
            domain_id,
            trigger_source,
            requested_by,
            Json(request_payload or {}, dumps=_json_dumps),
        ],
    )
    return refresh_id


def update_dashboard_refresh_status(
    settings: Settings,
    refresh_id: str,
    status: str,
    *,
    error_message: str | None = None,
) -> None:
    execute_non_query(
        settings,
        """
        UPDATE public.quantyx_dashboard_refresh_runs
           SET status = %s,
               error_message = COALESCE(%s, error_message),
               started_at = CASE WHEN started_at IS NULL AND %s = 'running' THEN now() ELSE started_at END,
               completed_at = CASE WHEN %s IN ('completed', 'failed', 'partial_completed') THEN now() ELSE completed_at END,
               updated_at = now()
         WHERE refresh_id = %s
        """,
        [status, error_message, status, status, refresh_id],
    )


def get_dashboard_refresh_run(settings: Settings, dashboard_id: str, refresh_id: str) -> dict[str, Any] | None:
    rows = run_query(
        settings,
        """
        SELECT refresh_id, dashboard_id, tenant_id, domain_id, status, trigger_source, requested_by,
               request_payload, error_message, started_at, completed_at, created_at, updated_at
          FROM public.quantyx_dashboard_refresh_runs
         WHERE dashboard_id = %s
           AND refresh_id = %s
         LIMIT 1
        """,
        [dashboard_id, refresh_id],
    )
    return rows[0] if rows else None


def append_dashboard_refresh_event(
    settings: Settings,
    *,
    refresh_id: str,
    dashboard_id: str,
    stage_name: str,
    message: str,
    artifacts: dict[str, Any] | None = None,
) -> str:
    event_id = f"drevt_{uuid.uuid4().hex[:12]}"
    execute_non_query(
        settings,
        """
        INSERT INTO public.quantyx_dashboard_refresh_events (
          event_id, refresh_id, dashboard_id, stage_name, message, artifacts, created_at
        )
        VALUES (%s, %s, %s, %s, %s, %s::jsonb, now())
        """,
        [
            event_id,
            refresh_id,
            dashboard_id,
            stage_name,
            message,
            Json(artifacts or {}, dumps=_json_dumps),
        ],
    )
    return event_id


def list_dashboard_refresh_events(
    settings: Settings,
    *,
    dashboard_id: str,
    refresh_id: str,
    limit: int = 200,
) -> list[dict[str, Any]]:
    return run_query(
        settings,
        """
        SELECT event_id, refresh_id, dashboard_id, stage_name, message, artifacts, created_at
          FROM public.quantyx_dashboard_refresh_events
         WHERE dashboard_id = %s
           AND refresh_id = %s
         ORDER BY created_at ASC
         LIMIT %s
        """,
        [dashboard_id, refresh_id, limit],
    )


def get_dashboard_insights(
    settings: Settings,
    *,
    dashboard_id: str,
    refresh_id: str | None = None,
    as_of: str | None = None,
) -> dict[str, Any] | None:
    if refresh_id:
        rows = run_query(
            settings,
            """
            SELECT i.artifact_id, i.refresh_id, i.dashboard_id, i.summary_raw_text, i.summary_html,
                   i.inference_raw_text, i.inference_html, i.evidence_json, i.quality_json,
                   i.created_at, i.updated_at
              FROM public.quantyx_dashboard_insight_artifacts i
             WHERE i.dashboard_id = %s
               AND i.refresh_id = %s
             LIMIT 1
            """,
            [dashboard_id, refresh_id],
        )
        return rows[0] if rows else None
    if as_of:
        rows = run_query(
            settings,
            """
            SELECT i.artifact_id, i.refresh_id, i.dashboard_id, i.summary_raw_text, i.summary_html,
                   i.inference_raw_text, i.inference_html, i.evidence_json, i.quality_json,
                   i.created_at, i.updated_at
              FROM public.quantyx_dashboard_insight_artifacts i
              JOIN public.quantyx_dashboard_refresh_runs r
                ON r.refresh_id = i.refresh_id
             WHERE i.dashboard_id = %s
               AND r.completed_at IS NOT NULL
               AND r.completed_at <= %s::timestamptz
             ORDER BY r.completed_at DESC
             LIMIT 1
            """,
            [dashboard_id, as_of],
        )
        return rows[0] if rows else None
    rows = run_query(
        settings,
        """
        SELECT i.artifact_id, i.refresh_id, i.dashboard_id, i.summary_raw_text, i.summary_html,
               i.inference_raw_text, i.inference_html, i.evidence_json, i.quality_json,
               i.created_at, i.updated_at
          FROM public.quantyx_dashboard_insight_artifacts i
          JOIN public.quantyx_dashboard_refresh_runs r
            ON r.refresh_id = i.refresh_id
         WHERE i.dashboard_id = %s
           AND r.status IN ('completed', 'partial_completed')
         ORDER BY r.completed_at DESC NULLS LAST, r.updated_at DESC
         LIMIT 1
        """,
        [dashboard_id],
    )
    return rows[0] if rows else None


def upsert_dashboard_insights_artifact(
    settings: Settings,
    *,
    refresh_id: str,
    dashboard_id: str,
    summary_raw_text: str | None = None,
    summary_html: str | None = None,
    inference_raw_text: str | None = None,
    inference_html: str | None = None,
    evidence_json: dict[str, Any] | None = None,
    quality_json: dict[str, Any] | None = None,
) -> str:
    artifact_id = f"dins_{uuid.uuid4().hex[:12]}"
    execute_non_query(
        settings,
        """
        INSERT INTO public.quantyx_dashboard_insight_artifacts (
          artifact_id, refresh_id, dashboard_id, summary_raw_text, summary_html,
          inference_raw_text, inference_html, evidence_json, quality_json, created_at, updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, now(), now())
        ON CONFLICT (refresh_id)
        DO UPDATE SET
          summary_raw_text = COALESCE(EXCLUDED.summary_raw_text, public.quantyx_dashboard_insight_artifacts.summary_raw_text),
          summary_html = COALESCE(EXCLUDED.summary_html, public.quantyx_dashboard_insight_artifacts.summary_html),
          inference_raw_text = COALESCE(EXCLUDED.inference_raw_text, public.quantyx_dashboard_insight_artifacts.inference_raw_text),
          inference_html = COALESCE(EXCLUDED.inference_html, public.quantyx_dashboard_insight_artifacts.inference_html),
          evidence_json = COALESCE(EXCLUDED.evidence_json, public.quantyx_dashboard_insight_artifacts.evidence_json),
          quality_json = COALESCE(EXCLUDED.quality_json, public.quantyx_dashboard_insight_artifacts.quality_json),
          updated_at = now()
        """,
        [
            artifact_id,
            refresh_id,
            dashboard_id,
            summary_raw_text,
            summary_html,
            inference_raw_text,
            inference_html,
            Json(evidence_json or {}, dumps=_json_dumps),
            Json(quality_json or {}, dumps=_json_dumps),
        ],
    )
    return artifact_id


def create_dashboard_chart_snapshot(
    settings: Settings,
    *,
    refresh_id: str,
    dashboard_id: str,
    chart_id: str,
    chart_type: str,
    sql: str | None,
    params: list[Any] | None,
    data_json: list[dict[str, Any]],
    stats_json: dict[str, Any] | None = None,
    insight_json: dict[str, Any] | None = None,
) -> str:
    snapshot_id = f"dsnap_{uuid.uuid4().hex[:12]}"
    execute_non_query(
        settings,
        """
        INSERT INTO public.quantyx_dashboard_chart_snapshots (
          snapshot_id, refresh_id, dashboard_id, chart_id, chart_type, sql, params,
          row_count, data_json, stats_json, insight_json, created_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s::jsonb, %s::jsonb, %s::jsonb, now())
        """,
        [
            snapshot_id,
            refresh_id,
            dashboard_id,
            chart_id,
            chart_type,
            sql,
            Json(params or [], dumps=_json_dumps),
            len(data_json or []),
            Json(data_json or [], dumps=_json_dumps),
            Json(stats_json or {}, dumps=_json_dumps),
            Json(insight_json or {}, dumps=_json_dumps),
        ],
    )
    return snapshot_id
