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


def create_anomaly_investigation(
    settings: Settings,
    *,
    tenant_id: str,
    domain_id: str,
    run_id: str,
    trigger_source: str,
    title: str | None = None,
    conversation_id: str | None = None,
    dashboard_id: str | None = None,
    source_dashboard_id: str | None = None,
    summary_text: str | None = None,
    severity_score: float | None = None,
    confidence_score: float | None = None,
    anomaly_summary_json: dict[str, Any] | None = None,
    quality_json: dict[str, Any] | None = None,
) -> str:
    investigation_id = f"inv_{uuid.uuid4().hex[:12]}"
    execute_non_query(
        settings,
        """
        INSERT INTO public.quantyx_anomaly_investigations (
          investigation_id, tenant_id, domain_id, run_id, conversation_id, dashboard_id, source_dashboard_id,
          trigger_source, status, title, summary_text, severity_score, confidence_score,
          anomaly_summary_json, quality_json, created_at, updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'queued', %s, %s, %s, %s, %s::jsonb, %s::jsonb, now(), now())
        """,
        [
            investigation_id,
            tenant_id,
            domain_id,
            run_id,
            conversation_id,
            dashboard_id,
            source_dashboard_id,
            trigger_source,
            title,
            summary_text,
            severity_score,
            confidence_score,
            Json(anomaly_summary_json or {}, dumps=_json_dumps),
            Json(quality_json or {}, dumps=_json_dumps),
        ],
    )
    return investigation_id


def update_anomaly_investigation(
    settings: Settings,
    investigation_id: str,
    *,
    status: str | None = None,
    dashboard_id: str | None = None,
    source_dashboard_id: str | None = None,
    title: str | None = None,
    summary_text: str | None = None,
    severity_score: float | None = None,
    confidence_score: float | None = None,
    anomaly_summary_json: dict[str, Any] | None = None,
    quality_json: dict[str, Any] | None = None,
    error_message: str | None = None,
) -> None:
    updates: list[str] = []
    params: list[Any] = []
    if status is not None:
        updates.append("status = %s")
        params.append(status)
    if dashboard_id is not None:
        updates.append("dashboard_id = %s")
        params.append(dashboard_id)
    if source_dashboard_id is not None:
        updates.append("source_dashboard_id = %s")
        params.append(source_dashboard_id)
    if title is not None:
        updates.append("title = %s")
        params.append(title)
    if summary_text is not None:
        updates.append("summary_text = %s")
        params.append(summary_text)
    if severity_score is not None:
        updates.append("severity_score = %s")
        params.append(severity_score)
    if confidence_score is not None:
        updates.append("confidence_score = %s")
        params.append(confidence_score)
    if anomaly_summary_json is not None:
        updates.append("anomaly_summary_json = %s::jsonb")
        params.append(Json(anomaly_summary_json, dumps=_json_dumps))
    if quality_json is not None:
        updates.append("quality_json = %s::jsonb")
        params.append(Json(quality_json, dumps=_json_dumps))
    if error_message is not None:
        updates.append("error_message = %s")
        params.append(error_message)
    if not updates:
        return
    updates.append("updated_at = now()")
    execute_non_query(
        settings,
        f"""
        UPDATE public.quantyx_anomaly_investigations
           SET {", ".join(updates)}
         WHERE investigation_id = %s
        """,
        [*params, investigation_id],
    )


def get_anomaly_investigation(settings: Settings, investigation_id: str) -> dict[str, Any] | None:
    rows = run_query(
        settings,
        """
        SELECT investigation_id, tenant_id, domain_id, run_id, conversation_id, dashboard_id, source_dashboard_id,
               trigger_source, status, title, summary_text, severity_score, confidence_score,
               anomaly_summary_json, quality_json, error_message, created_at, updated_at
          FROM public.quantyx_anomaly_investigations
         WHERE investigation_id = %s
         LIMIT 1
        """,
        [investigation_id],
    )
    return rows[0] if rows else None


def list_anomaly_investigations(
    settings: Settings,
    *,
    tenant_id: str,
    domain_id: str,
    run_id: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    if run_id:
        return run_query(
            settings,
            """
            SELECT investigation_id, tenant_id, domain_id, run_id, conversation_id, dashboard_id, source_dashboard_id,
                   trigger_source, status, title, summary_text, severity_score, confidence_score,
                   anomaly_summary_json, quality_json, error_message, created_at, updated_at
              FROM public.quantyx_anomaly_investigations
             WHERE tenant_id = %s
               AND domain_id = %s
               AND run_id = %s
             ORDER BY created_at DESC
             LIMIT %s
            """,
            [tenant_id, domain_id, run_id, limit],
        )
    return run_query(
        settings,
        """
        SELECT investigation_id, tenant_id, domain_id, run_id, conversation_id, dashboard_id, source_dashboard_id,
               trigger_source, status, title, summary_text, severity_score, confidence_score,
               anomaly_summary_json, quality_json, error_message, created_at, updated_at
          FROM public.quantyx_anomaly_investigations
         WHERE tenant_id = %s
           AND domain_id = %s
         ORDER BY created_at DESC
         LIMIT %s
        """,
        [tenant_id, domain_id, limit],
    )


def create_anomaly_record(
    settings: Settings,
    *,
    investigation_id: str,
    tenant_id: str,
    domain_id: str,
    anomaly_type: str,
    metric_id: str | None = None,
    raw_signal_name: str | None = None,
    entity_scope_json: dict[str, Any] | None = None,
    baseline_window_json: dict[str, Any] | None = None,
    comparison_window_json: dict[str, Any] | None = None,
    severity_score: float | None = None,
    confidence_score: float | None = None,
    evidence_json: dict[str, Any] | None = None,
) -> str:
    anomaly_id = f"an_{uuid.uuid4().hex[:12]}"
    execute_non_query(
        settings,
        """
        INSERT INTO public.quantyx_anomaly_records (
          anomaly_id, investigation_id, tenant_id, domain_id, metric_id, raw_signal_name, anomaly_type,
          entity_scope_json, baseline_window_json, comparison_window_json, severity_score, confidence_score,
          evidence_json, created_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s, %s, %s::jsonb, now())
        """,
        [
            anomaly_id,
            investigation_id,
            tenant_id,
            domain_id,
            metric_id,
            raw_signal_name,
            anomaly_type,
            Json(entity_scope_json or {}, dumps=_json_dumps),
            Json(baseline_window_json or {}, dumps=_json_dumps),
            Json(comparison_window_json or {}, dumps=_json_dumps),
            severity_score,
            confidence_score,
            Json(evidence_json or {}, dumps=_json_dumps),
        ],
    )
    return anomaly_id


def list_anomaly_records(
    settings: Settings,
    *,
    investigation_id: str,
) -> list[dict[str, Any]]:
    return run_query(
        settings,
        """
        SELECT anomaly_id, investigation_id, tenant_id, domain_id, metric_id, raw_signal_name, anomaly_type,
               entity_scope_json, baseline_window_json, comparison_window_json, severity_score, confidence_score,
               evidence_json, created_at
          FROM public.quantyx_anomaly_records
         WHERE investigation_id = %s
         ORDER BY severity_score DESC NULLS LAST, created_at DESC
        """,
        [investigation_id],
    )


def update_anomaly_record(
    settings: Settings,
    anomaly_id: str,
    *,
    entity_scope_json: dict[str, Any] | None = None,
    baseline_window_json: dict[str, Any] | None = None,
    comparison_window_json: dict[str, Any] | None = None,
    severity_score: float | None = None,
    confidence_score: float | None = None,
    evidence_json: dict[str, Any] | None = None,
) -> None:
    updates: list[str] = []
    params: list[Any] = []
    if entity_scope_json is not None:
        updates.append("entity_scope_json = %s::jsonb")
        params.append(Json(entity_scope_json, dumps=_json_dumps))
    if baseline_window_json is not None:
        updates.append("baseline_window_json = %s::jsonb")
        params.append(Json(baseline_window_json, dumps=_json_dumps))
    if comparison_window_json is not None:
        updates.append("comparison_window_json = %s::jsonb")
        params.append(Json(comparison_window_json, dumps=_json_dumps))
    if severity_score is not None:
        updates.append("severity_score = %s")
        params.append(severity_score)
    if confidence_score is not None:
        updates.append("confidence_score = %s")
        params.append(confidence_score)
    if evidence_json is not None:
        updates.append("evidence_json = %s::jsonb")
        params.append(Json(evidence_json, dumps=_json_dumps))
    if not updates:
        return
    execute_non_query(
        settings,
        f"""
        UPDATE public.quantyx_anomaly_records
           SET {", ".join(updates)}
         WHERE anomaly_id = %s
        """,
        [*params, anomaly_id],
    )


def create_anomaly_hypothesis(
    settings: Settings,
    *,
    investigation_id: str,
    title: str,
    explanation_text: str,
    rank_no: int = 1,
    anomaly_id: str | None = None,
    confidence_score: float | None = None,
    likely_drivers_json: dict[str, Any] | list[Any] | None = None,
    supporting_evidence_json: dict[str, Any] | list[Any] | None = None,
    validation_step_text: str | None = None,
    provenance_json: dict[str, Any] | None = None,
) -> str:
    hypothesis_id = f"hyp_{uuid.uuid4().hex[:12]}"
    execute_non_query(
        settings,
        """
        INSERT INTO public.quantyx_anomaly_hypotheses (
          hypothesis_id, investigation_id, anomaly_id, rank_no, title, explanation_text, confidence_score,
          likely_drivers_json, supporting_evidence_json, validation_step_text, provenance_json, created_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s::jsonb, now())
        """,
        [
            hypothesis_id,
            investigation_id,
            anomaly_id,
            rank_no,
            title,
            explanation_text,
            confidence_score,
            Json(likely_drivers_json or {}, dumps=_json_dumps),
            Json(supporting_evidence_json or {}, dumps=_json_dumps),
            validation_step_text,
            Json(provenance_json or {}, dumps=_json_dumps),
        ],
    )
    return hypothesis_id


def list_anomaly_hypotheses(
    settings: Settings,
    *,
    investigation_id: str,
) -> list[dict[str, Any]]:
    return run_query(
        settings,
        """
        SELECT hypothesis_id, investigation_id, anomaly_id, rank_no, title, explanation_text, confidence_score,
               likely_drivers_json, supporting_evidence_json, validation_step_text, provenance_json, created_at
          FROM public.quantyx_anomaly_hypotheses
         WHERE investigation_id = %s
         ORDER BY rank_no ASC, created_at ASC
        """,
        [investigation_id],
    )


def create_anomaly_action(
    settings: Settings,
    *,
    investigation_id: str,
    action_type: str,
    action_text: str,
    anomaly_id: str | None = None,
    hypothesis_id: str | None = None,
    priority: str | None = None,
    confidence_score: float | None = None,
    recommended_owner: str | None = None,
    metadata_json: dict[str, Any] | None = None,
) -> str:
    action_id = f"act_{uuid.uuid4().hex[:12]}"
    execute_non_query(
        settings,
        """
        INSERT INTO public.quantyx_anomaly_actions (
          action_id, investigation_id, anomaly_id, hypothesis_id, action_type, priority, confidence_score,
          recommended_owner, action_text, metadata_json, created_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, now())
        """,
        [
            action_id,
            investigation_id,
            anomaly_id,
            hypothesis_id,
            action_type,
            priority,
            confidence_score,
            recommended_owner,
            action_text,
            Json(metadata_json or {}, dumps=_json_dumps),
        ],
    )
    return action_id


def list_anomaly_actions(
    settings: Settings,
    *,
    investigation_id: str,
) -> list[dict[str, Any]]:
    return run_query(
        settings,
        """
        SELECT action_id, investigation_id, anomaly_id, hypothesis_id, action_type, priority, confidence_score,
               recommended_owner, action_text, metadata_json, created_at
          FROM public.quantyx_anomaly_actions
         WHERE investigation_id = %s
         ORDER BY created_at ASC
        """,
        [investigation_id],
    )


def create_anomaly_dashboard_link(
    settings: Settings,
    *,
    investigation_id: str,
    dashboard_id: str,
    role: str,
    source_dashboard_id: str | None = None,
) -> str:
    link_id = f"adlk_{uuid.uuid4().hex[:12]}"
    execute_non_query(
        settings,
        """
        INSERT INTO public.quantyx_anomaly_dashboard_links (
          link_id, investigation_id, dashboard_id, source_dashboard_id, role, created_at
        )
        VALUES (%s, %s, %s, %s, %s, now())
        ON CONFLICT DO NOTHING
        """,
        [link_id, investigation_id, dashboard_id, source_dashboard_id, role],
    )
    return link_id


def list_anomaly_dashboard_links(
    settings: Settings,
    *,
    investigation_id: str,
) -> list[dict[str, Any]]:
    return run_query(
        settings,
        """
        SELECT link_id, investigation_id, dashboard_id, source_dashboard_id, role, created_at
          FROM public.quantyx_anomaly_dashboard_links
         WHERE investigation_id = %s
         ORDER BY created_at ASC
        """,
        [investigation_id],
    )


def get_anomaly_dashboard_link(
    settings: Settings,
    *,
    investigation_id: str,
    role: str,
) -> dict[str, Any] | None:
    rows = run_query(
        settings,
        """
        SELECT link_id, investigation_id, dashboard_id, source_dashboard_id, role, created_at
          FROM public.quantyx_anomaly_dashboard_links
         WHERE investigation_id = %s
           AND role = %s
         ORDER BY created_at DESC
         LIMIT 1
        """,
        [investigation_id, role],
    )
    return rows[0] if rows else None
