from __future__ import annotations

import psycopg2

from services.ai.config import Settings
from services.ai.db import execute_non_query, run_query


def register_connection(
    settings: Settings,
    connection_id: str,
    tenant_id: str | None = None,
    domain_id: str | None = None,
) -> None:
    sql = """
    INSERT INTO public.quantyx_connection_registry
      (connection_id, tenant_id, domain_id)
    VALUES
      (%s, %s, %s)
    ON CONFLICT (connection_id)
    DO UPDATE SET
      tenant_id = EXCLUDED.tenant_id,
      domain_id = EXCLUDED.domain_id,
      created_at = now()
    """
    params = [connection_id, tenant_id, domain_id]
    try:
        execute_non_query(settings, sql, params)
    except psycopg2.errors.UndefinedTable:
        return


def register_connection_scopes(
    settings: Settings,
    connection_id: str,
    scopes: list[tuple[str, str]],
) -> None:
    sql = """
    INSERT INTO public.quantyx_connection_scopes
      (connection_id, database_name, schema_name)
    VALUES
      (%s, %s, %s)
    ON CONFLICT (connection_id, database_name, schema_name)
    DO NOTHING
    """
    try:
        for database_name, schema_name in scopes:
            execute_non_query(settings, sql, [connection_id, database_name, schema_name])
    except psycopg2.errors.UndefinedTable:
        return


def resolve_connection_scope(settings: Settings, connection_id: str) -> list[dict] | None:
    sql = """
    SELECT connection_id, database_name, schema_name
    FROM public.quantyx_connection_scopes
    WHERE connection_id = %s
    ORDER BY database_name, schema_name
    """
    try:
        rows = run_query(settings, sql, [connection_id])
    except psycopg2.errors.UndefinedTable:
        return None
    return rows if rows else None
