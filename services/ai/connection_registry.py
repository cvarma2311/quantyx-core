from __future__ import annotations

import psycopg2
import time
from threading import Lock

from services.ai.config import Settings
from services.ai.crypto import decrypt_password
from services.ai.db import ScopedConnection, execute_non_query, run_query


# ---------------------------------------------------------------------------
# In-process credential cache — avoids a DB round-trip on every customer query
# ---------------------------------------------------------------------------
_cred_cache: dict[str, tuple[ScopedConnection, float]] = {}
_cred_cache_lock = Lock()
_CRED_CACHE_TTL = 300  # seconds


def resolve_database_credentials(
    settings: Settings,
    connection_id: str,
    schema_name: str,
) -> ScopedConnection | None:
    """Fetch full connection credentials from `public.databases` using connection_id as the row id.

    This query always runs against the App DB (settings) — `databases` lives in datafusion.
    """
    sql = """
        SELECT name, host, port, user_name, password, connection_type, database_name
        FROM public.databases
        WHERE id = %s
    """
    try:
        rows = run_query(settings, sql, [connection_id])
    except Exception:
        return None
    if not rows:
        return None
    row = rows[0]
    raw_password = str(row.get("password") or "")
    return ScopedConnection(
        connection_id=connection_id,
        host=str(row.get("host") or ""),
        port=int(row.get("port") or 5432),
        user=str(row.get("user_name") or ""),
        password=decrypt_password(raw_password),
        database_name=str(row.get("database_name") or ""),
        schema_name=schema_name,
        connection_type=str(row.get("connection_type") or "postgresql"),
    )


def resolve_database_credentials_cached(
    settings: Settings,
    connection_id: str,
    schema_name: str,
) -> ScopedConnection | None:
    """Cached wrapper around `resolve_database_credentials` (5-minute TTL)."""
    cache_key = f"{connection_id}:{schema_name}"
    with _cred_cache_lock:
        if cache_key in _cred_cache:
            cred, ts = _cred_cache[cache_key]
            if time.monotonic() - ts < _CRED_CACHE_TTL:
                return cred
    cred = resolve_database_credentials(settings, connection_id, schema_name)
    if cred:
        with _cred_cache_lock:
            _cred_cache[cache_key] = (cred, time.monotonic())
    return cred


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


def count_connections(
    settings: Settings,
    tenant_id: str | None = None,
    domain_id: str | None = None,
) -> int:
    filters = []
    params: list[object] = []
    if tenant_id:
        filters.append("tenant_id = %s")
        params.append(tenant_id)
    if domain_id:
        filters.append("domain_id = %s")
        params.append(domain_id)
    where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
    sql = f"SELECT COUNT(*) AS count FROM public.quantyx_connection_registry {where_clause}"
    try:
        rows = run_query(settings, sql, params)
    except psycopg2.errors.UndefinedTable:
        return 0
    if not rows:
        return 0
    return int(rows[0].get("count", 0) or 0)
