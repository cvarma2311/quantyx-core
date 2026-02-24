from __future__ import annotations

from typing import Any
from uuid import uuid4

from services.ai.config import Settings
from services.ai.db import execute_non_query, run_query
from psycopg2.extras import Json


def create_context(
    settings: Settings,
    tenant_id: str,
    domain_id: str,
    source_type: str,
    source_title: str | None,
    raw_text: str | None,
    metadata: dict[str, Any] | None,
) -> str:
    context_id = f"ctx_{uuid4().hex[:12]}"
    metadata = metadata or {}
    connection_id = metadata.get("connection_id")
    database_name = metadata.get("database")
    schema_name = metadata.get("schema")
    sql = """
        INSERT INTO public.quantyx_business_context (
          context_id,
          tenant_id,
          domain_id,
          connection_id,
          database_name,
          schema_name,
          source_type,
          source_title,
          raw_text,
          metadata,
          status
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'submitted')
    """
    execute_non_query(
        settings,
        sql,
        [
            context_id,
            tenant_id,
            domain_id,
            connection_id,
            database_name,
            schema_name,
            source_type,
            source_title,
            raw_text or "",
            Json(metadata),
        ],
    )
    return context_id


def create_context_file(
    settings: Settings,
    tenant_id: str,
    domain_id: str,
    filename: str,
    content_type: str | None,
    extracted_text: str,
    file_bytes: bytes,
    metadata: dict[str, Any] | None,
) -> str:
    file_id = f"file_{uuid4().hex[:12]}"
    sql = """
        INSERT INTO public.quantyx_context_files (
          file_id,
          tenant_id,
          domain_id,
          filename,
          content_type,
          extracted_text,
          raw_bytes,
          metadata
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    """
    execute_non_query(
        settings,
        sql,
        [
            file_id,
            tenant_id,
            domain_id,
            filename,
            content_type,
            extracted_text,
            file_bytes,
            Json(metadata or {}),
        ],
    )
    return file_id


def link_context_files(
    settings: Settings,
    context_id: str,
    file_ids: list[str],
) -> None:
    sql = """
        INSERT INTO public.quantyx_context_file_links (context_id, file_id)
        VALUES (%s, %s)
        ON CONFLICT DO NOTHING
    """
    for file_id in file_ids:
        execute_non_query(settings, sql, [context_id, file_id])


def list_context(
    settings: Settings,
    tenant_id: str,
    domain_id: str,
    source_type: str | None,
    status: str | None,
    connection_id: str | None,
    database: str | None,
    schema: str | None,
    limit: int,
    cursor: str | None,
) -> tuple[list[dict], str | None]:
    filters = ["tenant_id = %s", "domain_id = %s"]
    params: list[Any] = [tenant_id, domain_id]
    if source_type:
        filters.append("source_type = %s")
        params.append(source_type)
    if status:
        filters.append("status = %s")
        params.append(status)
    if connection_id:
        filters.append("connection_id = %s")
        params.append(connection_id)
    if database:
        filters.append("database_name = %s")
        params.append(database)
    if schema:
        filters.append("schema_name = %s")
        params.append(schema)
    if cursor:
        filters.append("created_at < %s")
        params.append(cursor)

    where_clause = " AND ".join(filters)
    sql = f"""
        SELECT c.context_id,
               c.tenant_id,
               c.domain_id,
               c.connection_id,
               c.database_name,
               c.schema_name,
               c.source_type,
               c.source_title,
               c.status,
               c.metadata,
               c.created_at,
               COALESCE(bool_or(a.is_active), false) AS is_active,
               COALESCE(
                 array_agg(DISTINCT e.extraction_type)
                   FILTER (WHERE e.extraction_type IS NOT NULL),
                 ARRAY[]::TEXT[]
               ) AS extraction_types
          FROM public.quantyx_business_context c
          LEFT JOIN public.quantyx_context_extractions e
            ON e.context_id = c.context_id
          LEFT JOIN public.quantyx_context_scope_active a
            ON a.context_id = c.context_id
           AND a.tenant_id = c.tenant_id
           AND a.domain_id = c.domain_id
           AND a.connection_id IS NOT DISTINCT FROM c.connection_id
           AND a.database_name IS NOT DISTINCT FROM c.database_name
           AND a.schema_name IS NOT DISTINCT FROM c.schema_name
         WHERE {where_clause}
         GROUP BY c.context_id,
                  c.tenant_id,
                  c.domain_id,
                  c.connection_id,
                  c.database_name,
                  c.schema_name,
                  c.source_type,
                  c.source_title,
                  c.status,
                  c.metadata,
                  c.created_at
         ORDER BY c.created_at DESC
         LIMIT %s
    """
    rows = run_query(settings, sql, params + [limit + 1])
    next_cursor = None
    if len(rows) > limit:
        next_cursor = rows[limit - 1]["created_at"].isoformat()
        rows = rows[:limit]
    return rows, next_cursor


def set_context_active(
    settings: Settings,
    tenant_id: str,
    domain_id: str,
    context_id: str,
    connection_id: str | None,
    database_name: str | None,
    schema_name: str | None,
    is_active: bool,
) -> None:
    sql = """
        INSERT INTO public.quantyx_context_scope_active (
          tenant_id,
          domain_id,
          connection_id,
          database_name,
          schema_name,
          context_id,
          is_active,
          created_at,
          updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, now(), now())
        ON CONFLICT (tenant_id, domain_id, connection_id, database_name, schema_name, context_id)
        DO UPDATE SET
          is_active = EXCLUDED.is_active,
          updated_at = now()
    """
    execute_non_query(
        settings,
        sql,
        [
            tenant_id,
            domain_id,
            connection_id,
            database_name,
            schema_name,
            context_id,
            is_active,
        ],
    )


def list_active_context_ids(
    settings: Settings,
    tenant_id: str,
    domain_id: str,
    connection_id: str | None,
    database_name: str | None,
    schema_name: str | None,
) -> list[str]:
    sql = """
        SELECT context_id
          FROM public.quantyx_context_scope_active
         WHERE tenant_id = %s
           AND domain_id = %s
           AND connection_id IS NOT DISTINCT FROM %s
           AND database_name IS NOT DISTINCT FROM %s
           AND schema_name IS NOT DISTINCT FROM %s
           AND is_active = true
         ORDER BY updated_at DESC
    """
    rows = run_query(
        settings,
        sql,
        [tenant_id, domain_id, connection_id, database_name, schema_name],
    )
    return [row["context_id"] for row in rows if row.get("context_id")]


def get_context(settings: Settings, context_id: str) -> dict | None:
    sql = """
        SELECT context_id,
               tenant_id,
               domain_id,
               connection_id,
               database_name,
               schema_name,
               source_title,
               raw_text,
               metadata,
               status
          FROM public.quantyx_business_context
         WHERE context_id = %s
    """
    rows = run_query(settings, sql, [context_id])
    return rows[0] if rows else None


def get_context_file_texts(settings: Settings, context_id: str) -> list[str]:
    sql = """
        SELECT f.extracted_text
          FROM public.quantyx_context_file_links l
          JOIN public.quantyx_context_files f
            ON f.file_id = l.file_id
         WHERE l.context_id = %s
         ORDER BY l.created_at ASC
    """
    rows = run_query(settings, sql, [context_id])
    return [row.get("extracted_text", "") for row in rows if row.get("extracted_text")]


def get_context_file(settings: Settings, file_id: str) -> dict | None:
    sql = """
        SELECT file_id,
               tenant_id,
               domain_id,
               metadata
          FROM public.quantyx_context_files
         WHERE file_id = %s
    """
    rows = run_query(settings, sql, [file_id])
    return rows[0] if rows else None


def get_context_file_bytes(settings: Settings, file_id: str) -> dict | None:
    sql = """
        SELECT file_id,
               tenant_id,
               domain_id,
               filename,
               content_type,
               raw_bytes
          FROM public.quantyx_context_files
         WHERE file_id = %s
    """
    rows = run_query(settings, sql, [file_id])
    return rows[0] if rows else None


def mark_context_processed(settings: Settings, context_id: str) -> None:
    sql = """
        UPDATE public.quantyx_business_context
           SET status = 'processed',
               updated_at = now()
         WHERE context_id = %s
    """
    execute_non_query(settings, sql, [context_id])


def persist_extraction(
    settings: Settings,
    context_id: str,
    tenant_id: str,
    domain_id: str,
    payload: dict[str, Any],
    llm_model: str | None,
    confidence: float | None = None,
    agent_name: str | None = None,
    parent_job_id: str | None = None,
) -> str:
    extraction_id = f"ext_{uuid4().hex[:12]}"
    sql = """
        INSERT INTO public.quantyx_context_extractions (
          extraction_id,
          context_id,
          tenant_id,
          domain_id,
          extraction_type,
          payload,
          llm_model,
          confidence,
          agent_name,
          parent_job_id
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    execute_non_query(
        settings,
        sql,
        [
            extraction_id,
            context_id,
            tenant_id,
            domain_id,
            "combined",
            Json(payload),
            llm_model,
            confidence,
            agent_name,
            parent_job_id,
        ],
    )
    return extraction_id


def persist_extraction_agent(
    settings: Settings,
    extraction_id: str,
    agent_name: str,
    payload: dict[str, Any],
    confidence: float | None = None,
) -> str:
    agent_run_id = f"agent_{uuid4().hex[:12]}"
    sql = """
        INSERT INTO public.quantyx_context_extraction_agents (
          agent_run_id,
          extraction_id,
          agent_name,
          payload,
          confidence
        )
        VALUES (%s, %s, %s, %s, %s)
    """
    execute_non_query(
        settings,
        sql,
        [
            agent_run_id,
            extraction_id,
            agent_name,
            Json(payload),
            confidence,
        ],
    )
    return agent_run_id


def update_context(settings: Settings, context_id: str, updates: dict[str, Any]) -> None:
    allowed = {"source_title", "raw_text", "metadata", "status"}
    filtered = {key: value for key, value in updates.items() if key in allowed}
    if not filtered:
        return
    columns = []
    params: list[Any] = []
    for key, value in filtered.items():
        columns.append(f"{key} = %s")
        if key == "metadata":
            params.append(Json(value))
        else:
            params.append(value)
    columns.append("updated_at = now()")
    params.append(context_id)
    sql = f"UPDATE public.quantyx_business_context SET {', '.join(columns)} WHERE context_id = %s"
    execute_non_query(settings, sql, params)


def update_context_file_metadata(settings: Settings, file_id: str, metadata: dict[str, Any]) -> None:
    sql = """
        UPDATE public.quantyx_context_files
           SET metadata = %s
         WHERE file_id = %s
    """
    execute_non_query(settings, sql, [Json(metadata), file_id])


def get_extraction(settings: Settings, extraction_id: str) -> dict | None:
    sql = """
        SELECT extraction_id,
               context_id,
               tenant_id,
               domain_id,
               extraction_type,
               payload,
               llm_model,
               agent_name,
               parent_job_id,
               status,
               notes,
               created_at
          FROM public.quantyx_context_extractions
         WHERE extraction_id = %s
    """
    rows = run_query(settings, sql, [extraction_id])
    return rows[0] if rows else None


def list_extractions(
    settings: Settings,
    tenant_id: str,
    domain_id: str | None,
    limit: int = 50,
) -> list[dict]:
    sql = """
        SELECT e.extraction_id,
               e.context_id,
               e.tenant_id,
               e.domain_id,
               e.extraction_type,
               e.payload,
               e.llm_model,
               e.agent_name,
               e.parent_job_id,
               e.status,
               e.notes,
               e.created_at,
               c.raw_text
          FROM public.quantyx_context_extractions
          AS e
          LEFT JOIN public.quantyx_business_context AS c
            ON c.context_id = e.context_id
         WHERE e.tenant_id = %s
           AND (%s IS NULL OR e.domain_id = %s)
         ORDER BY created_at DESC
         LIMIT %s
    """
    rows = run_query(settings, sql, [tenant_id, domain_id, domain_id, limit])
    return rows


def list_context_files_for_contexts(
    settings: Settings,
    context_ids: list[str],
) -> dict[str, list[dict]]:
    if not context_ids:
        return {}
    placeholders = ", ".join(["%s"] * len(context_ids))
    sql = f"""
        SELECT l.context_id,
               f.file_id,
               f.filename,
               f.content_type,
               f.metadata,
               f.created_at
          FROM public.quantyx_context_file_links AS l
          JOIN public.quantyx_context_files AS f
            ON f.file_id = l.file_id
         WHERE l.context_id IN ({placeholders})
         ORDER BY f.created_at DESC
    """
    rows = run_query(settings, sql, context_ids)
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(row.get("context_id"), []).append(
            {
                "file_id": row.get("file_id"),
                "filename": row.get("filename"),
                "content_type": row.get("content_type"),
                "metadata": row.get("metadata"),
                "created_at": row.get("created_at"),
            }
        )
    return grouped


def update_extraction(
    settings: Settings,
    extraction_id: str,
    status: str | None = None,
    notes: str | None = None,
) -> None:
    updates = {}
    if status is not None:
        updates["status"] = status
    if notes is not None:
        updates["notes"] = notes
    if not updates:
        return
    columns = []
    params: list[Any] = []
    for key, value in updates.items():
        columns.append(f"{key} = %s")
        params.append(value)
    params.append(extraction_id)
    sql = f"UPDATE public.quantyx_context_extractions SET {', '.join(columns)} WHERE extraction_id = %s"
    execute_non_query(settings, sql, params)
