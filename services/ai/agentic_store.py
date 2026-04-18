from __future__ import annotations

import json
import uuid
from datetime import date, datetime, time as dt_time
from decimal import Decimal
from typing import Any

from psycopg2.extras import Json

from services.ai.config import Settings
from services.ai.db import run_query, execute_non_query


STAGE_SEQUENCE: dict[str, int] = {
    "queued": 1,
    "running": 2,
    "raw_json_ready": 3,
    "summary_ready": 4,
    "inference_ready": 5,
    "completed": 6,
}


def _json_default(value: Any) -> Any:
    if isinstance(value, (datetime, date, dt_time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return str(value)


def _json_dumps(value: Any) -> str:
    return json.dumps(value, default=_json_default)


def _table_columns(settings: Settings, table_name: str) -> set[str]:
    rows = run_query(
        settings,
        """
        SELECT column_name
          FROM information_schema.columns
         WHERE table_schema = 'public'
           AND table_name = %s
        """,
        [table_name],
    )
    return {str(row.get("column_name")) for row in rows if row.get("column_name")}


def create_agent_run(settings: Settings, tenant_id: str, domain_id: str, status: str = "queued") -> str:
    run_id = f"run_{uuid.uuid4().hex[:12]}"
    execute_non_query(
        settings,
        """
        INSERT INTO public.quantyx_agent_runs (run_id, tenant_id, domain_id, status, created_at, updated_at)
        VALUES (%s, %s, %s, %s, now(), now())
        """,
        [run_id, tenant_id, domain_id, status],
    )
    return run_id


def update_agent_run_status(settings: Settings, run_id: str, status: str) -> None:
    execute_non_query(
        settings,
        """
        UPDATE public.quantyx_agent_runs
           SET status = %s,
               updated_at = now()
         WHERE run_id = %s
        """,
        [status, run_id],
    )


def append_agent_run_event(
    settings: Settings,
    run_id: str,
    agent_name: str,
    status: str,
    message: str,
    artifacts: dict[str, Any] | None = None,
) -> str:
    event_id = f"event_{uuid.uuid4().hex[:12]}"
    execute_non_query(
        settings,
        """
        INSERT INTO public.quantyx_agent_run_events (
          event_id, run_id, agent_name, status, message, artifacts, created_at
        )
        VALUES (%s, %s, %s, %s, %s, %s::jsonb, now())
        """,
        [
            event_id,
            run_id,
            agent_name,
            status,
            message,
            Json(artifacts, dumps=_json_dumps) if artifacts is not None else None,
        ],
    )
    return event_id


def append_agent_run_stage_event(
    settings: Settings,
    run_id: str,
    agent_name: str,
    stage_name: str,
    message: str,
    *,
    logical_event_id: str | None = None,
    artifacts: dict[str, Any] | None = None,
    payload_compacted: bool = False,
) -> dict[str, str]:
    event_id = f"event_{uuid.uuid4().hex[:12]}"
    lifecycle_id = logical_event_id or f"le_{uuid.uuid4().hex[:12]}"
    stage_seq = STAGE_SEQUENCE.get(stage_name)
    status = stage_name
    execute_non_query(
        settings,
        """
        INSERT INTO public.quantyx_agent_run_events (
          event_id, run_id, agent_name, status, message, artifacts,
          stage_name, stage_seq, logical_event_id, payload_compacted, created_at
        )
        VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, now())
        """,
        [
            event_id,
            run_id,
            agent_name,
            status,
            message,
            Json(artifacts, dumps=_json_dumps) if artifacts is not None else None,
            stage_name,
            stage_seq,
            lifecycle_id,
            payload_compacted,
        ],
    )
    return {"event_id": event_id, "logical_event_id": lifecycle_id}


def upsert_agent_event_artifact(
    settings: Settings,
    *,
    event_id: str,
    run_id: str,
    agent_name: str,
    stage_name: str,
    logical_event_id: str,
    raw_json: dict[str, Any] | None = None,
    summary_raw_text: str | None = None,
    summary_html: str | None = None,
    inference_raw_text: str | None = None,
    inference_html: str | None = None,
    truncation: dict[str, Any] | None = None,
) -> str:
    artifact_id = f"artifact_{uuid.uuid4().hex[:12]}"
    execute_non_query(
        settings,
        """
        INSERT INTO public.quantyx_agent_event_artifacts (
          artifact_id, event_id, logical_event_id, run_id, agent_name, stage_name,
          raw_json, summary_raw_text, summary_html, inference_raw_text, inference_html, truncation,
          created_at, updated_at
        )
        VALUES (
          %s, %s, %s, %s, %s, %s,
          %s::jsonb, %s, %s, %s, %s, %s::jsonb,
          now(), now()
        )
        ON CONFLICT (logical_event_id, stage_name)
        DO UPDATE SET
          event_id = EXCLUDED.event_id,
          raw_json = COALESCE(EXCLUDED.raw_json, public.quantyx_agent_event_artifacts.raw_json),
          summary_raw_text = COALESCE(EXCLUDED.summary_raw_text, public.quantyx_agent_event_artifacts.summary_raw_text),
          summary_html = COALESCE(EXCLUDED.summary_html, public.quantyx_agent_event_artifacts.summary_html),
          inference_raw_text = COALESCE(EXCLUDED.inference_raw_text, public.quantyx_agent_event_artifacts.inference_raw_text),
          inference_html = COALESCE(EXCLUDED.inference_html, public.quantyx_agent_event_artifacts.inference_html),
          truncation = COALESCE(EXCLUDED.truncation, public.quantyx_agent_event_artifacts.truncation),
          updated_at = now()
        """,
        [
            artifact_id,
            event_id,
            logical_event_id,
            run_id,
            agent_name,
            stage_name,
            Json(raw_json, dumps=_json_dumps) if raw_json is not None else None,
            summary_raw_text,
            summary_html,
            inference_raw_text,
            inference_html,
            Json(truncation, dumps=_json_dumps) if truncation is not None else None,
        ],
    )
    return artifact_id


def get_agent_event_artifact(settings: Settings, run_id: str, event_id: str) -> dict[str, Any] | None:
    rows = run_query(
        settings,
        """
        SELECT artifact_id, event_id, logical_event_id, run_id, agent_name, stage_name,
               raw_json, summary_raw_text, summary_html, inference_raw_text, inference_html, truncation,
               created_at, updated_at
          FROM public.quantyx_agent_event_artifacts
         WHERE run_id = %s
           AND event_id = %s
         LIMIT 1
        """,
        [run_id, event_id],
    )
    return rows[0] if rows else None


def get_agent_event_artifact_by_logical_event_id(
    settings: Settings,
    run_id: str,
    logical_event_id: str,
    *,
    stage_name: str | None = None,
) -> dict[str, Any] | None:
    params: list[Any] = [run_id, logical_event_id]
    stage_filter = ""
    if stage_name:
        stage_filter = " AND stage_name = %s"
        params.append(stage_name)
    rows = run_query(
        settings,
        f"""
        SELECT artifact_id, event_id, logical_event_id, run_id, agent_name, stage_name,
               raw_json, summary_raw_text, summary_html, inference_raw_text, inference_html, truncation,
               created_at, updated_at
          FROM public.quantyx_agent_event_artifacts
         WHERE run_id = %s
           AND logical_event_id = %s
           {stage_filter}
         ORDER BY updated_at DESC
         LIMIT 1
        """,
        params,
    )
    return rows[0] if rows else None


def list_agent_event_artifacts_by_event_ids(
    settings: Settings,
    run_id: str,
    event_ids: list[str],
) -> dict[str, dict[str, Any]]:
    ids = [str(eid) for eid in event_ids if str(eid).strip()]
    if not ids:
        return {}
    rows = run_query(
        settings,
        """
        SELECT artifact_id, event_id, logical_event_id, run_id, agent_name, stage_name,
               raw_json, summary_raw_text, summary_html, inference_raw_text, inference_html, truncation,
               created_at, updated_at
          FROM public.quantyx_agent_event_artifacts
         WHERE run_id = %s
           AND event_id = ANY(%s)
        """,
        [run_id, ids],
    )
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        eid = row.get("event_id")
        if eid:
            out[str(eid)] = row
    return out


def append_agent_chat_log_stage(
    settings: Settings,
    run_id: str,
    sender: str,
    message: str,
    *,
    event_id: str | None = None,
    logical_event_id: str | None = None,
    stage_name: str | None = None,
) -> str:
    message_id = f"msg_{uuid.uuid4().hex[:12]}"
    execute_non_query(
        settings,
        """
        INSERT INTO public.quantyx_agent_chat_log (
          message_id, run_id, sender, message, event_id, stage_name, logical_event_id, created_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, now())
        """,
        [message_id, run_id, sender, message, event_id, stage_name, logical_event_id],
    )
    return message_id


def append_plan_summary(settings: Settings, run_id: str, steps: list[str]) -> str:
    message = "Plan created: " + "; ".join(steps)
    return append_agent_chat_log(
        settings,
        run_id,
        sender="system",
        message=message,
        artifacts={"steps": steps, "status": "ready"},
    )


def list_agent_run_events(settings: Settings, run_id: str, limit: int = 200) -> list[dict[str, Any]]:
    return run_query(
        settings,
        """
        SELECT event_id, run_id, agent_name, status, message, artifacts, created_at
          FROM public.quantyx_agent_run_events
         WHERE run_id = %s
         ORDER BY created_at ASC
         LIMIT %s
        """,
        [run_id, limit],
    )


def list_agent_run_events_stage_aware(settings: Settings, run_id: str, limit: int = 200) -> list[dict[str, Any]]:
    cols = _table_columns(settings, "quantyx_agent_run_events")
    stage_name_expr = "stage_name" if "stage_name" in cols else "NULL AS stage_name"
    stage_seq_expr = "stage_seq" if "stage_seq" in cols else "NULL AS stage_seq"
    logical_event_id_expr = "logical_event_id" if "logical_event_id" in cols else "NULL AS logical_event_id"
    payload_compacted_expr = "payload_compacted" if "payload_compacted" in cols else "false AS payload_compacted"
    return run_query(
        settings,
        f"""
        SELECT event_id, run_id, agent_name, status, message, artifacts,
               {stage_name_expr}, {stage_seq_expr}, {logical_event_id_expr}, {payload_compacted_expr}, created_at
          FROM public.quantyx_agent_run_events
         WHERE run_id = %s
         ORDER BY created_at ASC
         LIMIT %s
        """,
        [run_id, limit],
    )


def get_agent_run(settings: Settings, run_id: str) -> dict[str, Any] | None:
    rows = run_query(
        settings,
        """
        SELECT run_id, tenant_id, domain_id, status, created_at, updated_at
          FROM public.quantyx_agent_runs
         WHERE run_id = %s
         LIMIT 1
        """,
        [run_id],
    )
    return rows[0] if rows else None


def append_agent_chat_log(
    settings: Settings,
    run_id: str,
    sender: str,
    message: str,
    artifacts: dict[str, Any] | None = None,
) -> str:
    message_id = f"msg_{uuid.uuid4().hex[:12]}"
    execute_non_query(
        settings,
        """
        INSERT INTO public.quantyx_agent_chat_log (
          message_id, run_id, sender, message, created_at
        )
        VALUES (%s, %s, %s, %s, now())
        """,
        [message_id, run_id, sender, message],
    )
    if artifacts is not None:
        append_agent_run_event(
            settings,
            run_id,
            sender,
            "stream",
            message,
            artifacts,
        )
    return message_id


def list_agent_chat_log(settings: Settings, run_id: str, limit: int = 200) -> list[dict[str, Any]]:
    cols = _table_columns(settings, "quantyx_agent_chat_log")
    event_id_expr = "event_id" if "event_id" in cols else "NULL AS event_id"
    stage_name_expr = "stage_name" if "stage_name" in cols else "NULL AS stage_name"
    logical_event_id_expr = "logical_event_id" if "logical_event_id" in cols else "NULL AS logical_event_id"
    return run_query(
        settings,
        f"""
        SELECT message_id, run_id, sender, message, {event_id_expr}, {stage_name_expr}, {logical_event_id_expr}, created_at
          FROM public.quantyx_agent_chat_log
         WHERE run_id = %s
         ORDER BY created_at ASC
         LIMIT %s
        """,
        [run_id, limit],
    )
