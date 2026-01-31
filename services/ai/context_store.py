from __future__ import annotations

from typing import Any
from uuid import uuid4

from services.ai.config import Settings
from services.ai.db import execute_non_query, run_query


def create_context(
    settings: Settings,
    tenant_id: str,
    domain_id: str,
    source_type: str,
    source_title: str | None,
    raw_text: str,
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
            raw_text,
            metadata,
        ],
    )
    return context_id


def list_context(
    settings: Settings,
    tenant_id: str,
    domain_id: str,
    source_type: str | None,
    status: str | None,
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
    if cursor:
        filters.append("created_at < %s")
        params.append(cursor)

    where_clause = " AND ".join(filters)
    sql = f"""
        SELECT context_id,
               tenant_id,
               domain_id,
               connection_id,
               database_name,
               schema_name,
               source_type,
               source_title,
               status,
               metadata,
               created_at
          FROM public.quantyx_business_context
         WHERE {where_clause}
         ORDER BY created_at DESC
         LIMIT %s
    """
    rows = run_query(settings, sql, params + [limit + 1])
    next_cursor = None
    if len(rows) > limit:
        next_cursor = rows[limit - 1]["created_at"].isoformat()
        rows = rows[:limit]
    return rows, next_cursor


def get_context(settings: Settings, context_id: str) -> dict | None:
    sql = """
        SELECT context_id,
               tenant_id,
               domain_id,
               raw_text,
               metadata,
               status
          FROM public.quantyx_business_context
         WHERE context_id = %s
    """
    rows = run_query(settings, sql, [context_id])
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
          confidence
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
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
            payload,
            llm_model,
            confidence,
        ],
    )
    return extraction_id


def get_extraction(settings: Settings, extraction_id: str) -> dict | None:
    sql = """
        SELECT extraction_id,
               context_id,
               tenant_id,
               domain_id,
               payload,
               llm_model
          FROM public.quantyx_context_extractions
         WHERE extraction_id = %s
    """
    rows = run_query(settings, sql, [extraction_id])
    return rows[0] if rows else None
