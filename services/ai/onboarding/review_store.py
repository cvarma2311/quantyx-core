from __future__ import annotations

import json
import uuid

import psycopg2

from services.ai.config import Settings
from services.ai.db import execute_non_query, run_query


def create_review_event(
    settings: Settings,
    tenant_id: str,
    domain_id: str,
    connection_id: str,
    database_name: str,
    schema_name: str,
    artifact_type: str,
    artifact_id: str,
    status: str,
    notes: str | None = None,
    payload: dict | None = None,
) -> str:
    review_id = f"review_{uuid.uuid4().hex[:10]}"
    sql = """
        INSERT INTO public.quantyx_review_events (
          review_id,
          tenant_id,
          domain_id,
          connection_id,
          database_name,
          schema_name,
          artifact_type,
          artifact_id,
          status,
          notes,
          payload,
          created_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, now())
    """
    params = [
        review_id,
        tenant_id,
        domain_id,
        connection_id,
        database_name,
        schema_name,
        artifact_type,
        artifact_id,
        status,
        notes,
        json.dumps(payload or {}),
    ]
    try:
        execute_non_query(settings, sql, params)
    except psycopg2.errors.UndefinedTable:
        return review_id
    return review_id


def list_review_events(
    settings: Settings,
    tenant_id: str,
    domain_id: str,
    connection_id: str,
    database_name: str,
    schema_name: str,
    artifact_type: str | None = None,
) -> list[dict]:
    filters = [
        "tenant_id = %s",
        "domain_id = %s",
        "connection_id = %s",
        "database_name = %s",
        "schema_name = %s",
    ]
    params: list[object] = [tenant_id, domain_id, connection_id, database_name, schema_name]
    if artifact_type:
        filters.append("artifact_type = %s")
        params.append(artifact_type)
    where_clause = " AND ".join(filters)
    sql = f"""
        SELECT review_id, tenant_id, domain_id, connection_id, database_name, schema_name,
               artifact_type, artifact_id, status, notes, payload, created_at
          FROM public.quantyx_review_events
         WHERE {where_clause}
         ORDER BY created_at DESC
    """
    try:
        return run_query(settings, sql, params)
    except psycopg2.errors.UndefinedTable:
        return []


def update_review_event(settings: Settings, review_id: str, status: str | None, notes: str | None) -> None:
    updates = []
    params = []
    if status is not None:
        updates.append("status = %s")
        params.append(status)
    if notes is not None:
        updates.append("notes = %s")
        params.append(notes)
    if not updates:
        return
    params.append(review_id)
    sql = f"UPDATE public.quantyx_review_events SET {', '.join(updates)} WHERE review_id = %s"
    execute_non_query(settings, sql, params)
