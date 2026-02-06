from __future__ import annotations

import psycopg2

from services.ai.config import Settings
from services.ai.db import execute_non_query, run_query


def upsert_tenant_domain(settings: Settings, tenant_id: str, domain_id: str) -> None:
    sql = """
        INSERT INTO public.quantyx_tenant_domains (tenant_id, domain_id, status, updated_at)
        VALUES (%s, %s, 'active', now())
        ON CONFLICT (tenant_id)
        DO UPDATE SET
          domain_id = EXCLUDED.domain_id,
          status = 'active',
          updated_at = now()
    """
    execute_non_query(settings, sql, [tenant_id, domain_id])


def get_tenant_domain(settings: Settings, tenant_id: str) -> dict | None:
    sql = """
        SELECT tenant_id, domain_id, status, created_at, updated_at
          FROM public.quantyx_tenant_domains
         WHERE tenant_id = %s
    """
    try:
        rows = run_query(settings, sql, [tenant_id])
    except psycopg2.errors.UndefinedTable:
        return None
    return rows[0] if rows else None
