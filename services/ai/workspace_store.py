from __future__ import annotations

import json
import re
import uuid
from datetime import date, datetime, time as dt_time
from decimal import Decimal
from typing import Any

from psycopg2.extras import Json

from services.ai.config import Settings
from services.ai.db import execute_non_query, execute_returning_query, run_query


STATUS_ACTIVE = "active"
STATUS_ARCHIVED = "archived"
STATUS_DELETED = "deleted"


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


def _domain_display(domain_id: str) -> str:
    text = (domain_id or "workspace").strip().replace("_", " ").replace("-", " ")
    words = [w for w in text.split() if w]
    if not words:
        return "Workspace"
    return " ".join(w.capitalize() for w in words[:6])


def _short_title(text: str | None, fallback: str) -> str:
    if not text:
        return fallback
    cleaned = re.sub(r"\s+", " ", text).strip()
    if not cleaned:
        return fallback
    tokens = cleaned.split(" ")[:8]
    titled = " ".join(t.capitalize() for t in tokens)
    return titled[:120]


def _agent_runs_select_fields(settings: Settings) -> str:
    cols = _table_columns(settings, "quantyx_agent_runs")
    return ", ".join(
        [
            "run_id",
            "tenant_id",
            "domain_id",
            "status",
            "created_at",
            "updated_at",
            "is_canonical" if "is_canonical" in cols else "false AS is_canonical",
            "version_no" if "version_no" in cols else "1 AS version_no",
            "display_name" if "display_name" in cols else "NULL AS display_name",
            "superseded_by_run_id" if "superseded_by_run_id" in cols else "NULL AS superseded_by_run_id",
            "completed_at" if "completed_at" in cols else "NULL AS completed_at",
        ]
    )


def next_run_version(settings: Settings, tenant_id: str, domain_id: str) -> int:
    cols = _table_columns(settings, "quantyx_agent_runs")
    if "version_no" not in cols:
        return 1
    rows = run_query(
        settings,
        """
        SELECT COALESCE(MAX(version_no), 0) AS max_version
          FROM public.quantyx_agent_runs
         WHERE tenant_id = %s
           AND domain_id = %s
        """,
        [tenant_id, domain_id],
    )
    return int((rows[0].get("max_version") if rows else 0) or 0) + 1


def initialize_run_metadata(
    settings: Settings,
    run_id: str,
    *,
    tenant_id: str,
    domain_id: str,
    version_no: int,
    display_name: str,
    is_canonical: bool = False,
) -> None:
    cols = _table_columns(settings, "quantyx_agent_runs")
    updates: list[str] = []
    params: list[Any] = []
    if "version_no" in cols:
        updates.append("version_no = %s")
        params.append(version_no)
    if "display_name" in cols:
        updates.append("display_name = %s")
        params.append(display_name)
    if "is_canonical" in cols:
        updates.append("is_canonical = %s")
        params.append(is_canonical)
    if not updates:
        return
    updates.append("updated_at = now()")
    params.append(run_id)
    params.append(tenant_id)
    params.append(domain_id)
    execute_non_query(
        settings,
        f"""
        UPDATE public.quantyx_agent_runs
           SET {', '.join(updates)}
         WHERE run_id = %s
           AND tenant_id = %s
           AND domain_id = %s
        """,
        params,
    )


def list_deployments(
    settings: Settings,
    tenant_id: str,
    domain_id: str,
    limit: int = 50,
) -> list[dict[str, Any]]:
    fields = _agent_runs_select_fields(settings)
    return run_query(
        settings,
        f"""
        SELECT {fields}
          FROM public.quantyx_agent_runs
         WHERE tenant_id = %s
           AND domain_id = %s
         ORDER BY COALESCE(version_no, 1) DESC, updated_at DESC
         LIMIT %s
        """,
        [tenant_id, domain_id, limit],
    )


def get_current_deployment(settings: Settings, tenant_id: str, domain_id: str) -> dict[str, Any] | None:
    cols = _table_columns(settings, "quantyx_agent_runs")
    fields = _agent_runs_select_fields(settings)
    if "is_canonical" in cols:
        rows = run_query(
            settings,
            f"""
            SELECT {fields}
              FROM public.quantyx_agent_runs
             WHERE tenant_id = %s
               AND domain_id = %s
               AND is_canonical = true
             ORDER BY updated_at DESC
             LIMIT 1
            """,
            [tenant_id, domain_id],
        )
        if rows:
            return rows[0]
    rows = run_query(
        settings,
        f"""
        SELECT {fields}
          FROM public.quantyx_agent_runs
         WHERE tenant_id = %s
           AND domain_id = %s
           AND status = 'completed'
         ORDER BY COALESCE(version_no, 1) DESC, updated_at DESC
         LIMIT 1
        """,
        [tenant_id, domain_id],
    )
    return rows[0] if rows else None


def mark_run_status(settings: Settings, run_id: str, status: str) -> None:
    cols = _table_columns(settings, "quantyx_agent_runs")
    completed_expr = ""
    if "completed_at" in cols:
        completed_expr = ", completed_at = CASE WHEN %s IN ('completed','failed','superseded') THEN now() ELSE completed_at END"
    params: list[Any] = [status]
    if completed_expr:
        params.append(status)
    params.append(run_id)
    execute_non_query(
        settings,
        f"""
        UPDATE public.quantyx_agent_runs
           SET status = %s,
               updated_at = now()
               {completed_expr}
         WHERE run_id = %s
        """,
        params,
    )


def finalize_canonical_deployment(settings: Settings, run_id: str) -> dict[str, Any] | None:
    cols = _table_columns(settings, "quantyx_agent_runs")
    fields = _agent_runs_select_fields(settings)
    rows = run_query(
        settings,
        f"""
        SELECT {fields}
          FROM public.quantyx_agent_runs
         WHERE run_id = %s
         LIMIT 1
        """,
        [run_id],
    )
    if not rows:
        return None
    row = rows[0]
    tenant_id = row.get("tenant_id")
    domain_id = row.get("domain_id")

    if "is_canonical" in cols:
        execute_non_query(
            settings,
            """
            UPDATE public.quantyx_agent_runs
               SET is_canonical = false,
                   status = CASE WHEN status = 'completed' THEN 'superseded' ELSE status END,
                   updated_at = now()
             WHERE tenant_id = %s
               AND domain_id = %s
               AND is_canonical = true
               AND run_id <> %s
            """,
            [tenant_id, domain_id, run_id],
        )

        execute_non_query(
            settings,
            """
            UPDATE public.quantyx_agent_runs
               SET is_canonical = true,
                   status = 'completed',
                   updated_at = now(),
                   completed_at = CASE WHEN completed_at IS NULL THEN now() ELSE completed_at END
             WHERE run_id = %s
            """,
            [run_id],
        )

        if "superseded_by_run_id" in cols:
            execute_non_query(
                settings,
                """
                UPDATE public.quantyx_agent_runs
                   SET superseded_by_run_id = %s,
                       updated_at = now()
                 WHERE tenant_id = %s
                   AND domain_id = %s
                   AND run_id <> %s
                   AND status = 'superseded'
                   AND (superseded_by_run_id IS NULL OR superseded_by_run_id = '')
                """,
                [run_id, tenant_id, domain_id, run_id],
            )

    rows = run_query(
        settings,
        f"""
        SELECT {fields}
          FROM public.quantyx_agent_runs
         WHERE run_id = %s
         LIMIT 1
        """,
        [run_id],
    )
    return rows[0] if rows else None


def update_deployment(
    settings: Settings,
    run_id: str,
    *,
    display_name: str | None = None,
    make_canonical: bool = False,
) -> dict[str, Any] | None:
    cols = _table_columns(settings, "quantyx_agent_runs")
    updates: list[str] = []
    params: list[Any] = []
    if display_name is not None and "display_name" in cols:
        updates.append("display_name = %s")
        params.append(display_name)
    if make_canonical and "is_canonical" in cols:
        row = run_query(
            settings,
            "SELECT tenant_id, domain_id FROM public.quantyx_agent_runs WHERE run_id = %s LIMIT 1",
            [run_id],
        )
        if row:
            tenant_id = row[0].get("tenant_id")
            domain_id = row[0].get("domain_id")
            execute_non_query(
                settings,
                """
                UPDATE public.quantyx_agent_runs
                   SET is_canonical = false,
                       status = CASE WHEN status = 'completed' THEN 'superseded' ELSE status END,
                       updated_at = now()
                 WHERE tenant_id = %s
                   AND domain_id = %s
                   AND run_id <> %s
                   AND is_canonical = true
                """,
                [tenant_id, domain_id, run_id],
            )
            updates.append("is_canonical = true")
    if updates:
        updates.append("updated_at = now()")
        params.append(run_id)
        execute_non_query(
            settings,
            f"UPDATE public.quantyx_agent_runs SET {', '.join(updates)} WHERE run_id = %s",
            params,
        )
    fields = _agent_runs_select_fields(settings)
    rows = run_query(
        settings,
        f"SELECT {fields} FROM public.quantyx_agent_runs WHERE run_id = %s LIMIT 1",
        [run_id],
    )
    return rows[0] if rows else None


def generate_run_display_name(domain_id: str, version_no: int) -> str:
    return f"{_domain_display(domain_id)} Deployment v{max(1, int(version_no or 1))}"


def generate_conversation_title(question: str | None, domain_id: str) -> str:
    fallback = f"{_domain_display(domain_id)} Conversation"
    return _short_title(question, fallback)


def create_workspace_conversation(
    settings: Settings,
    *,
    tenant_id: str,
    domain_id: str,
    run_id: str,
    title: str,
    display_name: str | None = None,
    created_by: str | None = None,
    source_chart_id: str | None = None,
) -> dict[str, Any]:
    conversation_id = f"conv_{uuid.uuid4().hex[:12]}"
    rows = execute_returning_query(
        settings,
        """
        INSERT INTO public.quantyx_workspace_conversations (
          conversation_id, tenant_id, domain_id, run_id, title, display_name, status, created_by,
          source_chart_id, created_at, updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, now(), now())
        RETURNING conversation_id, tenant_id, domain_id, run_id, title, display_name, status, created_by,
                  source_chart_id, created_at, updated_at
        """,
        [conversation_id, tenant_id, domain_id, run_id, title, display_name or title, STATUS_ACTIVE, created_by, source_chart_id],
    )
    return rows[0]


def list_conversations_by_chart(
    settings: Settings,
    chart_id: str,
    tenant_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    filters = ["c.source_chart_id = %s"]
    params: list[Any] = [chart_id]
    if tenant_id is not None:
        filters.append("c.tenant_id = %s")
        params.append(tenant_id)
    params.extend([limit, offset])
    return run_query(
        settings,
        f"""
        SELECT c.conversation_id,
               c.tenant_id,
               c.domain_id,
               c.run_id,
               c.source_chart_id,
               c.title,
               c.display_name,
               c.status,
               c.created_at,
               c.updated_at,
               COALESCE(m.message_count, 0) AS message_count
          FROM public.quantyx_workspace_conversations c
          LEFT JOIN (
            SELECT conversation_id, COUNT(*)::int AS message_count
              FROM public.quantyx_workspace_messages
             GROUP BY conversation_id
          ) m ON m.conversation_id = c.conversation_id
         WHERE {' AND '.join(filters)}
         ORDER BY c.created_at DESC
         LIMIT %s OFFSET %s
        """,
        params,
    )


def list_workspace_conversations(
    settings: Settings,
    *,
    tenant_id: str,
    domain_id: str,
    status: str | None = STATUS_ACTIVE,
    limit: int = 50,
) -> list[dict[str, Any]]:
    filters = ["c.tenant_id = %s", "c.domain_id = %s"]
    params: list[Any] = [tenant_id, domain_id]
    if status:
        filters.append("c.status = %s")
        params.append(status)
    params.append(limit)
    return run_query(
        settings,
        f"""
        SELECT c.conversation_id,
               c.tenant_id,
               c.domain_id,
               c.run_id,
               c.title,
               c.display_name,
               c.status,
               c.created_by,
               c.created_at,
               c.updated_at,
               COALESCE(m.message_count, 0) AS message_count,
               m.last_message_at,
               m.last_message_preview,
               r.display_name AS run_display_name
          FROM public.quantyx_workspace_conversations c
          LEFT JOIN (
            SELECT conversation_id,
                   COUNT(*)::int AS message_count,
                   MAX(created_at) AS last_message_at,
                   (ARRAY_AGG(message_text ORDER BY created_at DESC))[1] AS last_message_preview
              FROM public.quantyx_workspace_messages
             GROUP BY conversation_id
          ) m
            ON m.conversation_id = c.conversation_id
          LEFT JOIN public.quantyx_agent_runs r
            ON r.run_id = c.run_id
         WHERE {' AND '.join(filters)}
         ORDER BY COALESCE(m.last_message_at, c.created_at) DESC
         LIMIT %s
        """,
        params,
    )


def list_workspace_conversations_for_tenant(
    settings: Settings,
    *,
    tenant_id: str,
    status: str | None = STATUS_ACTIVE,
    domain_id: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    filters = ["c.tenant_id = %s"]
    params: list[Any] = [tenant_id]
    if domain_id:
        filters.append("c.domain_id = %s")
        params.append(domain_id)
    if status:
        filters.append("c.status = %s")
        params.append(status)
    params.append(limit)
    return run_query(
        settings,
        f"""
        SELECT c.conversation_id,
               c.tenant_id,
               c.domain_id,
               c.run_id,
               c.title,
               c.display_name,
               c.status,
               c.created_by,
               c.created_at,
               c.updated_at,
               COALESCE(m.message_count, 0) AS message_count,
               m.last_message_at,
               m.last_message_preview,
               r.display_name AS run_display_name
          FROM public.quantyx_workspace_conversations c
          LEFT JOIN (
            SELECT conversation_id,
                   COUNT(*)::int AS message_count,
                   MAX(created_at) AS last_message_at,
                   (ARRAY_AGG(message_text ORDER BY created_at DESC))[1] AS last_message_preview
              FROM public.quantyx_workspace_messages
             GROUP BY conversation_id
          ) m
            ON m.conversation_id = c.conversation_id
          LEFT JOIN public.quantyx_agent_runs r
            ON r.run_id = c.run_id
         WHERE {' AND '.join(filters)}
         ORDER BY COALESCE(m.last_message_at, c.created_at) DESC
         LIMIT %s
        """,
        params,
    )


def get_workspace_conversation(settings: Settings, conversation_id: str) -> dict[str, Any] | None:
    rows = run_query(
        settings,
        """
        SELECT conversation_id, tenant_id, domain_id, run_id, title, display_name, status, created_by, created_at, updated_at
          FROM public.quantyx_workspace_conversations
         WHERE conversation_id = %s
         LIMIT 1
        """,
        [conversation_id],
    )
    return rows[0] if rows else None


def update_workspace_conversation(
    settings: Settings,
    conversation_id: str,
    *,
    title: str | None = None,
    display_name: str | None = None,
    status: str | None = None,
    run_id: str | None = None,
) -> dict[str, Any] | None:
    updates: list[str] = []
    params: list[Any] = []
    if title is not None:
        updates.append("title = %s")
        params.append(title)
    if display_name is not None:
        updates.append("display_name = %s")
        params.append(display_name)
    if status is not None:
        updates.append("status = %s")
        params.append(status)
    if run_id is not None:
        updates.append("run_id = %s")
        params.append(run_id)
    if not updates:
        return get_workspace_conversation(settings, conversation_id)
    updates.append("updated_at = now()")
    params.append(conversation_id)
    execute_returning_query(
        settings,
        f"UPDATE public.quantyx_workspace_conversations SET {', '.join(updates)} WHERE conversation_id = %s",
        params,
    )
    return get_workspace_conversation(settings, conversation_id)


def soft_delete_workspace_conversation(settings: Settings, conversation_id: str) -> None:
    execute_non_query(
        settings,
        """
        UPDATE public.quantyx_workspace_conversations
           SET status = %s,
               updated_at = now()
         WHERE conversation_id = %s
        """,
        [STATUS_DELETED, conversation_id],
    )


def create_workspace_message(
    settings: Settings,
    *,
    conversation_id: str,
    tenant_id: str,
    domain_id: str,
    run_id: str,
    sender: str,
    message_text: str,
    sql_text: str | None = None,
    data_json: dict[str, Any] | list[Any] | None = None,
    chart_json: dict[str, Any] | None = None,
    inference_json: dict[str, Any] | None = None,
    summary_json: dict[str, Any] | None = None,
) -> dict[str, Any]:
    message_id = f"wmsg_{uuid.uuid4().hex[:12]}"
    rows = execute_returning_query(
        settings,
        """
        INSERT INTO public.quantyx_workspace_messages (
          message_id, conversation_id, tenant_id, domain_id, run_id, sender, message_text,
          sql_text, data_json, chart_json, inference_json, summary_json, created_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, now())
        RETURNING message_id, conversation_id, tenant_id, domain_id, run_id, sender, message_text,
                  sql_text, data_json, chart_json, inference_json, summary_json, created_at
        """,
        [
            message_id,
            conversation_id,
            tenant_id,
            domain_id,
            run_id,
            sender,
            message_text,
            sql_text,
            Json(data_json, dumps=_json_dumps) if data_json is not None else None,
            Json(chart_json, dumps=_json_dumps) if chart_json is not None else None,
            Json(inference_json, dumps=_json_dumps) if inference_json is not None else None,
            Json(summary_json, dumps=_json_dumps) if summary_json is not None else None,
        ],
    )
    execute_non_query(
        settings,
        "UPDATE public.quantyx_workspace_conversations SET updated_at = now() WHERE conversation_id = %s",
        [conversation_id],
    )
    return rows[0]


def list_workspace_messages(settings: Settings, conversation_id: str, limit: int = 200) -> list[dict[str, Any]]:
    return run_query(
        settings,
        """
        SELECT message_id, conversation_id, tenant_id, domain_id, run_id, sender, message_text,
               sql_text, data_json, chart_json, inference_json, summary_json, created_at
          FROM public.quantyx_workspace_messages
         WHERE conversation_id = %s
         ORDER BY created_at ASC
         LIMIT %s
        """,
        [conversation_id, limit],
    )


def get_workspace_message(settings: Settings, conversation_id: str, message_id: str) -> dict[str, Any] | None:
    rows = run_query(
        settings,
        """
        SELECT message_id, conversation_id, tenant_id, domain_id, run_id, sender, message_text,
               sql_text, data_json, chart_json, inference_json, summary_json, created_at
          FROM public.quantyx_workspace_messages
         WHERE conversation_id = %s
           AND message_id = %s
         LIMIT 1
        """,
        [conversation_id, message_id],
    )
    return rows[0] if rows else None


def recent_workspace_messages(settings: Settings, conversation_id: str, limit: int = 12) -> list[dict[str, Any]]:
    rows = run_query(
        settings,
        """
        SELECT message_id, sender, message_text, created_at
          FROM public.quantyx_workspace_messages
         WHERE conversation_id = %s
         ORDER BY created_at DESC
         LIMIT %s
        """,
        [conversation_id, limit],
    )
    rows.reverse()
    return rows


def upsert_workspace_memory(
    settings: Settings,
    *,
    conversation_id: str,
    tenant_id: str,
    domain_id: str,
    run_id: str,
    summary_text: str,
    memory_json: dict[str, Any],
) -> dict[str, Any]:
    memory_id = f"mem_{uuid.uuid4().hex[:12]}"
    rows = execute_returning_query(
        settings,
        """
        INSERT INTO public.quantyx_workspace_conversation_memory (
          memory_id, conversation_id, tenant_id, domain_id, run_id,
          summary_text, memory_json, last_message_at, updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, now(), now())
        ON CONFLICT (conversation_id)
        DO UPDATE SET
          summary_text = EXCLUDED.summary_text,
          memory_json = EXCLUDED.memory_json,
          run_id = EXCLUDED.run_id,
          last_message_at = now(),
          updated_at = now()
        RETURNING memory_id, conversation_id, tenant_id, domain_id, run_id, summary_text, memory_json, last_message_at, updated_at
        """,
        [
            memory_id,
            conversation_id,
            tenant_id,
            domain_id,
            run_id,
            summary_text,
            Json(memory_json, dumps=_json_dumps),
        ],
    )
    return rows[0]


def get_workspace_memory(settings: Settings, conversation_id: str) -> dict[str, Any] | None:
    rows = run_query(
        settings,
        """
        SELECT memory_id, conversation_id, tenant_id, domain_id, run_id,
               summary_text, memory_json, last_message_at, updated_at
          FROM public.quantyx_workspace_conversation_memory
         WHERE conversation_id = %s
         LIMIT 1
        """,
        [conversation_id],
    )
    return rows[0] if rows else None
