from __future__ import annotations

import json
from typing import Any

from services.ai.db import execute_non_query, run_query
from services.ai.config import Settings


def upsert_tenant(
    settings: Settings,
    tenant_id: str,
    display_name: str | None = None,
    status: str = "active",
    metadata: dict[str, Any] | None = None,
) -> dict:
    metadata_json = json.dumps(metadata or {})
    sql = """
        INSERT INTO public.quantyx_tenants (
          tenant_id, display_name, status, metadata, created_at, updated_at
        )
        VALUES (%s, %s, %s, %s::jsonb, now(), now())
        ON CONFLICT (tenant_id)
        DO UPDATE SET
          display_name = EXCLUDED.display_name,
          status = EXCLUDED.status,
          metadata = EXCLUDED.metadata,
          updated_at = now()
        RETURNING tenant_id, display_name, status, metadata, created_at, updated_at
    """
    rows = run_query(settings, sql, [tenant_id, display_name, status, metadata_json])
    return rows[0] if rows else {}


def list_tenants(settings: Settings, limit: int = 200) -> list[dict]:
    sql = """
        SELECT t.tenant_id,
               t.display_name,
               t.status,
               t.metadata,
               t.created_at,
               t.updated_at,
               d.domain_id
          FROM public.quantyx_tenants t
          LEFT JOIN public.quantyx_tenant_domains d
            ON d.tenant_id = t.tenant_id
         ORDER BY t.created_at DESC
         LIMIT %s
    """
    return run_query(settings, sql, [limit])
