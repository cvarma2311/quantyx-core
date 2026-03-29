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


def _serialize_payload(payload: object) -> str | None:
    if payload is None:
        return None
    return json.dumps(payload, default=_json_fallback)


def create_chart_request(
    settings: Settings,
    tenant_id: str,
    domain_id: str | None,
    question: str | None,
    query_payload: dict | None,
    sql: str | None = None,
    params: list | None = None,
    rows_json: list | dict | None = None,
    run_id: str | None = None,
    chart_source: str | None = None,
    title: str | None = None,
    created_by: str | None = None,
) -> dict:
    chart_id = f"chart_{uuid.uuid4().hex[:10]}"
    insert_sql = """
        INSERT INTO public.quantyx_chart_requests
          (chart_id, tenant_id, domain_id, run_id, question, query_payload, sql, params, rows_json,
           chart_source, title, created_by, status)
        VALUES
          (%s, %s, %s, %s, %s, %s::jsonb, %s, %s::jsonb, %s::jsonb, %s, %s, %s, 'queued')
        RETURNING chart_id, status, created_at, updated_at
    """
    params = [
        chart_id,
        tenant_id,
        domain_id,
        run_id or None,
        question,
        _serialize_payload(query_payload),
        sql,
        _serialize_payload(params),
        _serialize_payload(rows_json),
        chart_source,
        title,
        created_by,
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
            cur.execute(insert_sql, params)
            row = cur.fetchone()
        conn.commit()
        return dict(row) if row else {"chart_id": chart_id, "status": "queued"}
    except (psycopg2.errors.UndefinedTable, psycopg2.errors.UndefinedColumn):
        return {"chart_id": chart_id, "status": "queued"}
    finally:
        conn.close()


def get_chart_request(settings: Settings, chart_id: str) -> dict | None:
    sql = """
        SELECT chart_id, tenant_id, domain_id, question, query_payload, sql, params,
               rows_json, chart_type, chart_payload, chart_data, status, error_message, timing_ms,
               insight_text, narrative_text, stats_json,
               created_at, updated_at
          FROM public.quantyx_chart_requests
         WHERE chart_id = %s
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
            cur.execute(sql, [chart_id])
            row = cur.fetchone()
        return dict(row) if row else None
    except psycopg2.errors.UndefinedTable:
        return None
    finally:
        conn.close()


def get_latest_chart_request_by_question(
    settings: Settings,
    tenant_id: str,
    question: str,
) -> dict | None:
    sql = """
        SELECT chart_id, tenant_id, domain_id, question, query_payload, status, created_at
          FROM public.quantyx_chart_requests
         WHERE tenant_id = %s
           AND lower(question) = lower(%s)
         ORDER BY created_at DESC
         LIMIT 1
    """
    params = [tenant_id, question]
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


def update_chart_request(
    settings: Settings,
    chart_id: str,
    *,
    status: str | None = None,
    query_payload: dict | None = None,
    sql: str | None = None,
    params: list | None = None,
    rows_json: list | dict | None = None,
    chart_type: str | None = None,
    chart_payload: dict | None = None,
    chart_data: list | dict | None = None,
    error_message: str | None = None,
    timing_ms: dict | None = None,
    insight_text: str | None = None,
    narrative_text: str | None = None,
    stats_json: dict | None = None,
) -> None:
    updates = []
    values: list[object] = []
    if status is not None:
        updates.append("status = %s")
        values.append(status)
    if query_payload is not None:
        updates.append("query_payload = %s::jsonb")
        values.append(_serialize_payload(query_payload))
    if sql is not None:
        updates.append("sql = %s")
        values.append(sql)
    if params is not None:
        updates.append("params = %s::jsonb")
        values.append(_serialize_payload(params))
    if rows_json is not None:
        updates.append("rows_json = %s::jsonb")
        values.append(_serialize_payload(rows_json))
    if chart_type is not None:
        updates.append("chart_type = %s")
        values.append(chart_type)
    if chart_payload is not None:
        updates.append("chart_payload = %s::jsonb")
        values.append(_serialize_payload(chart_payload))
    if chart_data is not None:
        updates.append("chart_data = %s::jsonb")
        values.append(_serialize_payload(chart_data))
    if error_message is not None:
        updates.append("error_message = %s")
        values.append(error_message)
    if timing_ms is not None:
        updates.append("timing_ms = %s::jsonb")
        values.append(_serialize_payload(timing_ms))
    if insight_text is not None:
        updates.append("insight_text = %s")
        values.append(insight_text)
    if narrative_text is not None:
        updates.append("narrative_text = %s")
        values.append(narrative_text)
    if stats_json is not None:
        updates.append("stats_json = %s::jsonb")
        values.append(_serialize_payload(stats_json))
    updates.append("updated_at = now()")
    if not updates:
        return

    sql_stmt = f"""
        UPDATE public.quantyx_chart_requests
           SET {", ".join(updates)}
         WHERE chart_id = %s
    """
    values.append(chart_id)

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


def create_chart_event(
    settings: Settings,
    chart_id: str,
    event_type: str,
    details: dict | None = None,
) -> None:
    sql = """
        INSERT INTO public.quantyx_chart_events
          (event_id, chart_id, event_type, details)
        VALUES
          (%s, %s, %s, %s::jsonb)
    """
    params = [
        f"evt_{uuid.uuid4().hex[:12]}",
        chart_id,
        event_type,
        _serialize_payload(details),
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
