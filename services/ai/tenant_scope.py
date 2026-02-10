from __future__ import annotations

import json
import uuid
from datetime import date, datetime
from decimal import Decimal

import psycopg2
from psycopg2.extras import RealDictCursor

from services.ai.config import Settings
from services.ai.db import execute_non_query, run_query


def _json_fallback(value: object) -> str | float:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return str(value)


def upsert_tenant_scope(
    settings: Settings,
    tenant_id: str,
    domain_id: str,
    connection_id: str,
    database_name: str,
    schema_name: str,
    tables: list[str] | None = None,
) -> None:
    sql = """
        INSERT INTO public.quantyx_tenant_scopes
          (tenant_id, domain_id, connection_id, database_name, schema_name, tables, status, updated_at)
        VALUES
          (%s, %s, %s, %s, %s, %s::jsonb, 'active', now())
        ON CONFLICT (tenant_id, domain_id)
        DO UPDATE SET
          connection_id = EXCLUDED.connection_id,
          database_name = EXCLUDED.database_name,
          schema_name = EXCLUDED.schema_name,
          tables = EXCLUDED.tables,
          status = 'active',
          updated_at = now()
    """
    params = [
        tenant_id,
        domain_id,
        connection_id,
        database_name,
        schema_name,
        json.dumps(tables or [], default=_json_fallback),
    ]
    try:
        execute_non_query(settings, sql, params)
    except psycopg2.errors.UndefinedTable:
        return


def get_tenant_scope(settings: Settings, tenant_id: str, domain_id: str) -> dict | None:
    sql = """
        SELECT tenant_id, domain_id, connection_id, database_name, schema_name, tables, status
          FROM public.quantyx_tenant_scopes
         WHERE tenant_id = %s
           AND domain_id = %s
         LIMIT 1
    """
    try:
        rows = run_query(settings, sql, [tenant_id, domain_id])
    except psycopg2.errors.UndefinedTable:
        return None
    if not rows:
        return None
    return rows[0]


def resolve_scope(settings: Settings, tenant_id: str, domain_id: str) -> dict | None:
    return get_tenant_scope(settings, tenant_id, domain_id)
