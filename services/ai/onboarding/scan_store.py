from __future__ import annotations

import json
import uuid

import psycopg2

from services.ai.config import Settings
from services.ai.db import execute_non_query


def _mask_payload(payload: dict) -> dict:
    masked = json.loads(json.dumps(payload))
    for connection in masked.get("connections", []):
        if "password" in connection:
            connection["password"] = "******"
    return masked


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
        json.dumps(result_payload),
    ]
    try:
        execute_non_query(settings, sql, params)
    except psycopg2.errors.UndefinedTable:
        return
