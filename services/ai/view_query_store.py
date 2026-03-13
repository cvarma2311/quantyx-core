from __future__ import annotations

import json
import base64
from datetime import datetime, date, time as dt_time
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


def ensure_view_query_table(settings: Settings) -> None:
    execute_non_query(
        settings,
        """
        CREATE TABLE IF NOT EXISTS public.quantyx_view_query_runs (
          query_id text PRIMARY KEY,
          tenant_id text NOT NULL,
          domain_id text NOT NULL,
          sql_text text NOT NULL,
          limit_requested integer NOT NULL DEFAULT 200,
          status text NOT NULL DEFAULT 'running',
          chart_status text NOT NULL DEFAULT 'pending',
          inference_status text NOT NULL DEFAULT 'pending',
          data_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
          chart_payload jsonb,
          inference_payload jsonb,
          chart_error text,
          inference_error text,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now()
        )
        """,
        [],
    )
    execute_non_query(
        settings,
        """
        CREATE INDEX IF NOT EXISTS quantyx_view_query_runs_scope_idx
            ON public.quantyx_view_query_runs (tenant_id, domain_id, created_at DESC)
        """,
        [],
    )


def create_view_query_run(
    settings: Settings,
    *,
    query_id: str,
    tenant_id: str,
    domain_id: str,
    sql_text: str,
    limit_requested: int,
    data_payload: dict[str, Any],
) -> None:
    ensure_view_query_table(settings)
    execute_non_query(
        settings,
        """
        INSERT INTO public.quantyx_view_query_runs (
          query_id,
          tenant_id,
          domain_id,
          sql_text,
          limit_requested,
          status,
          chart_status,
          inference_status,
          data_payload,
          created_at,
          updated_at
        )
        VALUES (%s, %s, %s, %s, %s, 'running', 'pending', 'pending', %s, now(), now())
        """,
        [
            query_id,
            tenant_id,
            domain_id,
            sql_text,
            int(limit_requested),
            Json(data_payload, dumps=lambda v: json.dumps(v, default=_json_default)),
        ],
    )


def get_view_query_run(settings: Settings, query_id: str) -> dict[str, Any] | None:
    ensure_view_query_table(settings)
    rows = run_query(
        settings,
        """
        SELECT query_id,
               tenant_id,
               domain_id,
               sql_text,
               limit_requested,
               status,
               chart_status,
               inference_status,
               data_payload,
               chart_payload,
               inference_payload,
               chart_error,
               inference_error,
               created_at,
               updated_at
          FROM public.quantyx_view_query_runs
         WHERE query_id = %s
         LIMIT 1
        """,
        [query_id],
    )
    return rows[0] if rows else None


def mark_view_query_running(settings: Settings, query_id: str) -> None:
    ensure_view_query_table(settings)
    execute_non_query(
        settings,
        """
        UPDATE public.quantyx_view_query_runs
           SET status = 'running',
               updated_at = now()
         WHERE query_id = %s
        """,
        [query_id],
    )


def update_view_query_chart(
    settings: Settings,
    query_id: str,
    *,
    chart_status: str,
    chart_payload: dict[str, Any] | None = None,
    chart_error: str | None = None,
) -> None:
    ensure_view_query_table(settings)
    execute_non_query(
        settings,
        """
        UPDATE public.quantyx_view_query_runs
           SET chart_status = %s,
               chart_payload = %s,
               chart_error = %s,
               updated_at = now()
         WHERE query_id = %s
        """,
        [
            chart_status,
            Json(chart_payload, dumps=lambda v: json.dumps(v, default=_json_default))
            if chart_payload is not None
            else None,
            chart_error,
            query_id,
        ],
    )


def update_view_query_inference(
    settings: Settings,
    query_id: str,
    *,
    inference_status: str,
    inference_payload: dict[str, Any] | None = None,
    inference_error: str | None = None,
) -> None:
    ensure_view_query_table(settings)
    execute_non_query(
        settings,
        """
        UPDATE public.quantyx_view_query_runs
           SET inference_status = %s,
               inference_payload = %s,
               inference_error = %s,
               updated_at = now()
         WHERE query_id = %s
        """,
        [
            inference_status,
            Json(inference_payload, dumps=lambda v: json.dumps(v, default=_json_default))
            if inference_payload is not None
            else None,
            inference_error,
            query_id,
        ],
    )


def finalize_view_query(settings: Settings, query_id: str) -> None:
    ensure_view_query_table(settings)
    execute_non_query(
        settings,
        """
        UPDATE public.quantyx_view_query_runs
           SET status = CASE
                        WHEN chart_status IN ('ready', 'failed', 'skipped')
                         AND inference_status IN ('ready', 'failed', 'skipped')
                        THEN 'completed'
                        ELSE status
                        END,
               updated_at = now()
         WHERE query_id = %s
        """,
        [query_id],
    )


def _encode_cursor(created_at: Any, query_id: str) -> str | None:
    if not created_at or not query_id:
        return None
    try:
        payload = json.dumps({"created_at": str(created_at), "query_id": query_id}).encode("utf-8")
        return base64.urlsafe_b64encode(payload).decode("utf-8")
    except Exception:
        return None


def _decode_cursor(cursor: str | None) -> tuple[str | None, str | None]:
    if not cursor:
        return None, None
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("utf-8")).decode("utf-8")
        data = json.loads(raw)
        created_at = str(data.get("created_at") or "").strip() or None
        query_id = str(data.get("query_id") or "").strip() or None
        return created_at, query_id
    except Exception:
        return None, None


def list_view_query_runs(
    settings: Settings,
    *,
    tenant_id: str,
    domain_id: str | None = None,
    limit: int = 50,
    cursor: str | None = None,
) -> dict[str, Any]:
    ensure_view_query_table(settings)
    created_at_cursor, query_id_cursor = _decode_cursor(cursor)
    clauses = ["tenant_id = %s"]
    params: list[Any] = [tenant_id]
    if domain_id:
        clauses.append("domain_id = %s")
        params.append(domain_id)
    if created_at_cursor and query_id_cursor:
        clauses.append("(created_at < %s::timestamptz OR (created_at = %s::timestamptz AND query_id < %s))")
        params.extend([created_at_cursor, created_at_cursor, query_id_cursor])
    params.append(int(limit))
    rows = run_query(
        settings,
        f"""
        SELECT query_id,
               tenant_id,
               domain_id,
               sql_text,
               limit_requested,
               status,
               chart_status,
               inference_status,
               data_payload,
               chart_error,
               inference_error,
               created_at,
               updated_at
          FROM public.quantyx_view_query_runs
         WHERE {' AND '.join(clauses)}
         ORDER BY created_at DESC, query_id DESC
         LIMIT %s
        """,
        params,
    )
    items: list[dict[str, Any]] = []
    for row in rows:
        data_payload = row.get("data_payload") or {}
        row_count = int(data_payload.get("row_count") or 0)
        sql_text = str(row.get("sql_text") or "")
        items.append(
            {
                "query_id": str(row.get("query_id") or ""),
                "tenant_id": str(row.get("tenant_id") or ""),
                "domain_id": str(row.get("domain_id") or ""),
                "status": str(row.get("status") or "running"),
                "chart_status": str(row.get("chart_status") or "pending"),
                "inference_status": str(row.get("inference_status") or "pending"),
                "row_count": row_count,
                "limit": int(row.get("limit_requested") or 0),
                "sql_preview": (sql_text[:220] + "...") if len(sql_text) > 220 else sql_text,
                "created_at": str(row.get("created_at") or ""),
                "updated_at": str(row.get("updated_at") or ""),
                "chart_error": row.get("chart_error"),
                "inference_error": row.get("inference_error"),
            }
        )
    next_cursor = None
    if len(rows) == int(limit) and rows:
        last = rows[-1]
        next_cursor = _encode_cursor(last.get("created_at"), str(last.get("query_id") or ""))
    return {"items": items, "next_cursor": next_cursor}
