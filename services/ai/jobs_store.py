from __future__ import annotations

import json
import uuid
from datetime import date, datetime
from decimal import Decimal

import psycopg2
from psycopg2.extras import RealDictCursor

from services.ai.config import Settings


def _json_fallback(value: object) -> str | float:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return str(value)


def _serialize_payload(payload: dict) -> str:
    return json.dumps(payload, default=_json_fallback)


def derive_scope(job_type: str, payload: dict) -> dict | None:
    if job_type == "scan_connection":
        connections = payload.get("connections") or []
        if len(connections) != 1:
            return None
        connection = connections[0]
        databases = connection.get("databases") or []
        if len(databases) != 1:
            return {"connection_id": connection.get("connection_id")}
        database = databases[0]
        schemas = database.get("schemas") or []
        if len(schemas) != 1:
            return {
                "connection_id": connection.get("connection_id"),
                "database_name": database.get("name"),
            }
        schema = schemas[0]
        return {
            "connection_id": connection.get("connection_id"),
            "database_name": database.get("name"),
            "schema_name": schema.get("name"),
            "tables": schema.get("tables"),
        }

    connection_id = payload.get("connection_id")
    database_name = payload.get("database")
    schema_name = payload.get("schema")
    if not schema_name and isinstance(payload.get("schemas"), list) and payload.get("schemas"):
        schema_name = payload["schemas"][0]
    tables = payload.get("tables")
    if not connection_id and not database_name and not schema_name:
        return None
    return {
        "connection_id": connection_id,
        "database_name": database_name,
        "schema_name": schema_name,
        "tables": tables,
    }


def create_job_scope(
    settings: Settings,
    tenant_id: str,
    domain_id: str | None,
    scope: dict | None,
) -> str | None:
    if not scope:
        return None
    scope_id = f"scope_{uuid.uuid4().hex[:10]}"
    sql = """
        INSERT INTO public.quantyx_job_scopes
          (scope_id, tenant_id, domain_id, connection_id, database_name, schema_name, tables)
        VALUES
          (%s, %s, %s, %s, %s, %s, %s::jsonb)
    """
    params = [
        scope_id,
        tenant_id,
        domain_id,
        scope.get("connection_id"),
        scope.get("database_name"),
        scope.get("schema_name"),
        _serialize_payload(scope.get("tables")) if scope.get("tables") is not None else None,
    ]
    conn = psycopg2.connect(
        host=settings.db_host,
        port=settings.db_port,
        dbname=settings.db_name,
        user=settings.db_user,
        password=settings.db_password,
    )
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
        conn.commit()
        return scope_id
    except psycopg2.errors.UndefinedTable:
        return None
    finally:
        conn.close()


def create_job(
    settings: Settings,
    tenant_id: str,
    domain_id: str | None,
    job_type: str,
    payload: dict,
    idempotency_key: str | None = None,
) -> dict:
    existing = None
    if idempotency_key:
        existing = find_job_by_idempotency(settings, tenant_id, job_type, idempotency_key)
        if existing:
            return existing

    scope = derive_scope(job_type, payload)
    scope_id = create_job_scope(settings, tenant_id, domain_id, scope)
    job_id = f"job_{uuid.uuid4().hex[:12]}"
    sql = """
        INSERT INTO public.quantyx_jobs
          (job_id, tenant_id, scope_id, job_type, status, request_payload, idempotency_key)
        VALUES
          (%s, %s, %s, %s, 'queued', %s::jsonb, %s)
        RETURNING job_id, job_type, status, scope_id, created_at, updated_at
    """
    params = [
        job_id,
        tenant_id,
        scope_id,
        job_type,
        _serialize_payload(payload),
        idempotency_key,
    ]
    conn = psycopg2.connect(
        host=settings.db_host,
        port=settings.db_port,
        dbname=settings.db_name,
        user=settings.db_user,
        password=settings.db_password,
    )
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
        conn.commit()
        return dict(row) if row else {"job_id": job_id, "job_type": job_type, "status": "queued"}
    except psycopg2.errors.UndefinedTable:
        return {"job_id": job_id, "job_type": job_type, "status": "queued"}
    finally:
        conn.close()


def find_job_by_idempotency(
    settings: Settings,
    tenant_id: str,
    job_type: str,
    idempotency_key: str,
) -> dict | None:
    sql = """
        SELECT job_id, job_type, status, scope_id, created_at, updated_at
          FROM public.quantyx_jobs
         WHERE tenant_id = %s
           AND job_type = %s
           AND idempotency_key = %s
         ORDER BY created_at DESC
         LIMIT 1
    """
    params = [tenant_id, job_type, idempotency_key]
    conn = psycopg2.connect(
        host=settings.db_host,
        port=settings.db_port,
        dbname=settings.db_name,
        user=settings.db_user,
        password=settings.db_password,
    )
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
        return dict(row) if row else None
    except psycopg2.errors.UndefinedTable:
        return None
    finally:
        conn.close()


def get_job(settings: Settings, job_id: str) -> dict | None:
    sql = """
        SELECT job_id, job_type, status, scope_id, progress_pct, progress_stage, error_message,
               created_at, updated_at
          FROM public.quantyx_jobs
         WHERE job_id = %s
    """
    params = [job_id]
    conn = psycopg2.connect(
        host=settings.db_host,
        port=settings.db_port,
        dbname=settings.db_name,
        user=settings.db_user,
        password=settings.db_password,
    )
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
        return dict(row) if row else None
    except psycopg2.errors.UndefinedTable:
        return None
    finally:
        conn.close()


def get_job_result(settings: Settings, job_id: str) -> dict | None:
    sql = """
        SELECT job_id, status, result_payload, error_message
          FROM public.quantyx_jobs
         WHERE job_id = %s
    """
    params = [job_id]
    conn = psycopg2.connect(
        host=settings.db_host,
        port=settings.db_port,
        dbname=settings.db_name,
        user=settings.db_user,
        password=settings.db_password,
    )
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
        return dict(row) if row else None
    except psycopg2.errors.UndefinedTable:
        return None
    finally:
        conn.close()


def list_jobs(
    settings: Settings,
    tenant_id: str,
    job_type: str | None = None,
    status: str | None = None,
    cursor: str | None = None,
    limit: int = 50,
) -> dict:
    filters = ["tenant_id = %s"]
    params: list[object] = [tenant_id]
    if job_type:
        filters.append("job_type = %s")
        params.append(job_type)
    if status:
        filters.append("status = %s")
        params.append(status)
    if cursor:
        filters.append("created_at < %s")
        params.append(cursor)
    where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
    sql = f"""
        SELECT job_id, job_type, status, scope_id, created_at, updated_at
          FROM public.quantyx_jobs
          {where_clause}
         ORDER BY created_at DESC
         LIMIT %s
    """
    params.append(limit)
    conn = psycopg2.connect(
        host=settings.db_host,
        port=settings.db_port,
        dbname=settings.db_name,
        user=settings.db_user,
        password=settings.db_password,
    )
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
        jobs = [dict(row) for row in rows]
        next_cursor = jobs[-1]["created_at"].isoformat() if jobs else None
        return {"jobs": jobs, "limit": limit, "cursor": cursor, "next_cursor": next_cursor}
    except psycopg2.errors.UndefinedTable:
        return {"jobs": [], "limit": limit, "cursor": cursor, "next_cursor": None}
    finally:
        conn.close()


def update_job_progress(
    settings: Settings,
    job_id: str,
    progress_pct: float | None = None,
    progress_stage: str | None = None,
) -> None:
    sql = """
        UPDATE public.quantyx_jobs
           SET progress_pct = COALESCE(%s, progress_pct),
               progress_stage = COALESCE(%s, progress_stage),
               updated_at = now()
         WHERE job_id = %s
    """
    params = [progress_pct, progress_stage, job_id]
    conn = psycopg2.connect(
        host=settings.db_host,
        port=settings.db_port,
        dbname=settings.db_name,
        user=settings.db_user,
        password=settings.db_password,
    )
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
        conn.commit()
    except psycopg2.errors.UndefinedTable:
        return
    finally:
        conn.close()


def update_job_status(
    settings: Settings,
    job_id: str,
    status: str,
    result_payload: dict | None = None,
    error_message: str | None = None,
) -> None:
    completed_at = "now()" if status in {"completed", "failed", "canceled"} else "completed_at"
    started_at = "COALESCE(started_at, now())" if status == "running" else "started_at"
    sql = f"""
        UPDATE public.quantyx_jobs
           SET status = %s,
               result_payload = COALESCE(%s::jsonb, result_payload),
               error_message = %s,
               started_at = {started_at},
               completed_at = {completed_at},
               updated_at = now()
         WHERE job_id = %s
    """
    params = [
        status,
        _serialize_payload(result_payload) if result_payload is not None else None,
        error_message,
        job_id,
    ]
    conn = psycopg2.connect(
        host=settings.db_host,
        port=settings.db_port,
        dbname=settings.db_name,
        user=settings.db_user,
        password=settings.db_password,
    )
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
        conn.commit()
    except psycopg2.errors.UndefinedTable:
        return
    finally:
        conn.close()


def claim_next_job(settings: Settings) -> dict | None:
    sql = """
        WITH next_job AS (
          SELECT job_id
            FROM public.quantyx_jobs
           WHERE status = 'queued'
           ORDER BY created_at ASC
           LIMIT 1
           FOR UPDATE SKIP LOCKED
        )
        UPDATE public.quantyx_jobs
           SET status = 'running',
               started_at = now(),
               updated_at = now()
         WHERE job_id IN (SELECT job_id FROM next_job)
        RETURNING job_id, job_type, request_payload, tenant_id, scope_id
    """
    conn = psycopg2.connect(
        host=settings.db_host,
        port=settings.db_port,
        dbname=settings.db_name,
        user=settings.db_user,
        password=settings.db_password,
    )
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, [])
            row = cur.fetchone()
        conn.commit()
        return dict(row) if row else None
    except psycopg2.errors.UndefinedTable:
        return None
    finally:
        conn.close()
