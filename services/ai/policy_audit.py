from __future__ import annotations

import uuid

import psycopg2

from services.ai.config import Settings
from services.ai.db import execute_non_query


def log_policy_audit(
    settings: Settings,
    tenant_id: str,
    query_id: str | None,
    policy_name: str,
    action: str,
    details: dict | None = None,
) -> None:
    sql = """
        INSERT INTO public.quantyx_policy_audit
          (policy_audit_id, tenant_id, query_id, policy_name, action, details)
        VALUES
          (%s, %s, %s, %s, %s, %s::jsonb)
    """
    params = [
        f"pa_{uuid.uuid4().hex[:10]}",
        tenant_id,
        query_id,
        policy_name,
        action,
        (details or {}),
    ]
    try:
        execute_non_query(settings, sql, params)
    except psycopg2.errors.UndefinedTable:
        return
