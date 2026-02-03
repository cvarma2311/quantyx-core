from __future__ import annotations

import json
import uuid
from datetime import date, datetime
from decimal import Decimal

import psycopg2

from services.ai.config import Settings
from services.ai.db import execute_non_query
from services.ai.db import run_query


def _mask_payload(payload: dict) -> dict:
    masked = json.loads(json.dumps(payload))
    for connection in masked.get("connections", []):
        if "password" in connection:
            connection["password"] = "******"
    return masked


def _json_fallback(value: object) -> str | float:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return str(value)


def persist_schema_scan(
    settings: Settings,
    request_payload: dict,
    result_payload: dict,
    tenant_id: str | None = None,
    domain_id: str | None = None,
    requested_by: str | None = None,
) -> None:
    sql = """
    INSERT INTO public.quantyx_schema_scans
      (scan_id, tenant_id, domain_id, requested_by, status, request_payload, result_payload)
    VALUES
      (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb)
    """
    params = [
        f"scan_{uuid.uuid4().hex[:8]}",
        tenant_id,
        domain_id,
        requested_by,
        "completed",
        json.dumps(_mask_payload(request_payload)),
        json.dumps(result_payload, default=_json_fallback),
    ]
    try:
        execute_non_query(settings, sql, params)
    except psycopg2.errors.UndefinedTable:
        return


def load_latest_scan_result(
    settings: Settings,
    tenant_id: str | None,
    domain_id: str | None,
) -> dict | None:
    filters = []
    params: list[object] = []
    if tenant_id:
        filters.append("tenant_id = %s")
        params.append(tenant_id)
    if domain_id:
        filters.append("domain_id = %s")
        params.append(domain_id)
    where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
    sql = f"""
        SELECT result_payload
          FROM public.quantyx_schema_scans
          {where_clause}
         ORDER BY created_at DESC
         LIMIT 1
    """
    try:
        rows = run_query(settings, sql, params)
    except psycopg2.errors.UndefinedTable:
        return None
    if not rows:
        return None
    return rows[0].get("result_payload")
