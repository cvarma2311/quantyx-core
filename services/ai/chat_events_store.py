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


def create_chat_event(
    settings: Settings,
    chat_id: str,
    event_type: str,
    message: str,
    details: dict | None = None,
) -> str:
    event_id = f"cevt_{uuid.uuid4().hex[:12]}"
    sql = """
        INSERT INTO public.quantyx_chat_events
          (event_id, chat_id, event_type, message, details, created_at)
        VALUES
          (%s, %s, %s, %s, %s::jsonb, now())
    """
    params = [event_id, chat_id, event_type, message, _serialize(details)]
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
        return event_id
    finally:
        conn.close()
    return event_id


def list_chat_events(settings: Settings, chat_id: str, limit: int = 200) -> list[dict]:
    sql = """
        SELECT event_id, chat_id, event_type, message, details, created_at
          FROM public.quantyx_chat_events
         WHERE chat_id = %s
         ORDER BY created_at ASC
         LIMIT %s
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
            cur.execute(sql, [chat_id, limit])
            rows = cur.fetchall()
        return [dict(row) for row in rows]
    except psycopg2.errors.UndefinedTable:
        return []
    finally:
        conn.close()
