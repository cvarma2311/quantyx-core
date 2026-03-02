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


def _serialize(payload: object) -> str | None:
    if payload is None:
        return None
    return json.dumps(payload, default=_json_fallback)


def create_chat_request(
    settings: Settings,
    tenant_id: str,
    domain_id: str | None,
    question: str | None,
    request_payload: dict,
) -> dict:
    chat_id = f"chat_{uuid.uuid4().hex[:10]}"
    sql = """
        INSERT INTO public.quantyx_chat_requests
          (chat_id, tenant_id, domain_id, question, request_payload, status)
        VALUES
          (%s, %s, %s, %s, %s::jsonb, 'queued')
        RETURNING chat_id, status, created_at, updated_at
    """
    params = [chat_id, tenant_id, domain_id, question, _serialize(request_payload)]
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
        return dict(row) if row else {"chat_id": chat_id, "status": "queued"}
    except psycopg2.errors.UndefinedTable:
        return {"chat_id": chat_id, "status": "queued"}
    finally:
        conn.close()


def get_chat_request(settings: Settings, chat_id: str) -> dict | None:
    sql = """
        SELECT chat_id, tenant_id, domain_id, question, request_payload, response_payload,
               status, error_message, timing_ms, created_at, updated_at
          FROM public.quantyx_chat_requests
         WHERE chat_id = %s
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
            cur.execute(sql, [chat_id])
            row = cur.fetchone()
        return dict(row) if row else None
    except psycopg2.errors.UndefinedTable:
        return None
    finally:
        conn.close()


def update_chat_request(
    settings: Settings,
    chat_id: str,
    *,
    status: str | None = None,
    response_payload: dict | None = None,
    error_message: str | None = None,
    timing_ms: dict | None = None,
) -> None:
    updates = []
    values: list[object] = []
    if status is not None:
        updates.append("status = %s")
        values.append(status)
    if response_payload is not None:
        updates.append("response_payload = %s::jsonb")
        values.append(_serialize(response_payload))
    if error_message is not None:
        updates.append("error_message = %s")
        values.append(error_message)
    if timing_ms is not None:
        updates.append("timing_ms = %s::jsonb")
        values.append(_serialize(timing_ms))
    updates.append("updated_at = now()")
    if not updates:
        return

    sql_stmt = f"""
        UPDATE public.quantyx_chat_requests
           SET {", ".join(updates)}
         WHERE chat_id = %s
    """
    values.append(chat_id)
    conn = psycopg2.connect(
        host=settings.db_host,
        port=settings.db_port,
        dbname=settings.db_name,
        user=settings.db_user,
        password=settings.db_password,
    )
    try:
        with conn.cursor() as cur:
            cur.execute(sql_stmt, values)
        conn.commit()
    except psycopg2.errors.UndefinedTable:
        return
    finally:
        conn.close()
