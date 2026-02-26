from __future__ import annotations

import json
from typing import Any

from services.ai.db import execute_non_query, run_query
from services.ai.config import Settings
from services.ai.tenant_domain import upsert_tenant_domain


def upsert_tenant(
    settings: Settings,
    tenant_id: str,
    display_name: str | None = None,
    status: str = "active",
    metadata: dict[str, Any] | None = None,
    domain_id: str | None = None,
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
    if domain_id:
        upsert_tenant_domain(settings, tenant_id, domain_id)
    return rows[0] if rows else {}


def delete_tenant(settings: Settings, tenant_id: str) -> None:
    execute_non_query(
        settings,
        "DELETE FROM public.quantyx_tenant_domains WHERE tenant_id = %s",
        [tenant_id],
    )
    execute_non_query(
        settings,
        "DELETE FROM public.quantyx_tenants WHERE tenant_id = %s",
        [tenant_id],
    )


def update_tenant(
    settings: Settings,
    tenant_id: str,
    display_name: str | None = None,
    status: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict:
    updates = {}
    if display_name is not None:
        updates["display_name"] = display_name
    if status is not None:
        updates["status"] = status
    if metadata is not None:
        updates["metadata"] = json.dumps(metadata)
    if not updates:
        rows = run_query(
            settings,
            """
            SELECT tenant_id, display_name, status, metadata, created_at, updated_at
              FROM public.quantyx_tenants
             WHERE tenant_id = %s
            """,
            [tenant_id],
        )
        return rows[0] if rows else {}
    columns = []
    params: list[Any] = []
    for key, value in updates.items():
        if key == "metadata":
            columns.append("metadata = %s::jsonb")
        else:
            columns.append(f"{key} = %s")
        params.append(value)
    columns.append("updated_at = now()")
    params.append(tenant_id)
    sql = f"""
        UPDATE public.quantyx_tenants
           SET {", ".join(columns)}
         WHERE tenant_id = %s
        RETURNING tenant_id, display_name, status, metadata, created_at, updated_at
    """
    rows = run_query(settings, sql, params)
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
