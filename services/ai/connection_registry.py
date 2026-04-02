from __future__ import annotations

import logging
import psycopg2
import time
from threading import Lock

from services.ai.config import Settings
from services.ai.crypto import decrypt_password
from services.ai.db import ScopedConnection, execute_non_query, run_query

logger = logging.getLogger(__name__)

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
    logger.info(
        "connection_registry.resolve | connection_id=%s schema=%s app_db_host=%s app_db_name=%s",
        connection_id, schema_name, settings.db_host, settings.db_name,
    )
    try:
        rows = run_query(settings, sql, [connection_id])
    except Exception as exc:
        logger.error(
            "connection_registry.resolve | FAILED querying public.databases | connection_id=%s error=%s",
            connection_id, exc, exc_info=True,
        )
        return None

    if not rows:
        logger.warning(
            "connection_registry.resolve | NO ROW in public.databases | connection_id=%s",
            connection_id,
        )
        return None

    row = rows[0]
    logger.info(
        "connection_registry.resolve | row found | connection_id=%s name=%r host=%r port=%s user_name=%r "
        "database_name=%r connection_type=%r password_prefix=%r",
        connection_id,
        row.get("name"),
        row.get("host"),
        row.get("port"),
        row.get("user_name"),
        row.get("database_name"),
        row.get("connection_type"),
        str(row.get("password") or "")[:10],   # only first 10 chars — never log full password
    )

    raw_password = str(row.get("password") or "")
    is_encrypted = raw_password.startswith("enc#_")
    logger.info(
        "connection_registry.resolve | password_encrypted=%s | connection_id=%s",
        is_encrypted, connection_id,
    )

    try:
        decrypted_password = decrypt_password(raw_password)
        logger.info(
            "connection_registry.resolve | password decrypted OK | connection_id=%s",
            connection_id,
        )
    except Exception as exc:
        logger.error(
            "connection_registry.resolve | PASSWORD DECRYPTION FAILED | connection_id=%s "
            "is_encrypted=%s error=%s — check PASSWORD_SALT env var matches the salt used by datafusion",
            connection_id, is_encrypted, exc, exc_info=True,
        )
        return None

    host = str(row.get("host") or "")
    user = str(row.get("user_name") or "")
    database_name = str(row.get("database_name") or "")

    if not host:
        logger.error(
            "connection_registry.resolve | host is EMPTY in public.databases | connection_id=%s",
            connection_id,
        )
        return None

    if not user:
        logger.error(
            "connection_registry.resolve | user_name is EMPTY in public.databases | connection_id=%s",
            connection_id,
        )
        return None

    if not database_name:
        logger.error(
            "connection_registry.resolve | database_name is EMPTY in public.databases | connection_id=%s",
            connection_id,
        )
        return None

    sc = ScopedConnection(
        connection_id=connection_id,
        host=host,
        port=int(row.get("port") or 5432),
        user=user,
        password=decrypted_password,
        database_name=database_name,
        schema_name=schema_name,
        connection_type=str(row.get("connection_type") or "postgresql"),
    )
    logger.info(
        "connection_registry.resolve | ScopedConnection built | connection_id=%s host=%r port=%s "
        "user=%r database_name=%r schema=%r",
        connection_id, sc.host, sc.port, sc.user, sc.database_name, sc.schema_name,
    )
    return sc


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
            age = time.monotonic() - ts
            if age < _CRED_CACHE_TTL:
                logger.info(
                    "connection_registry.cache | HIT | connection_id=%s schema=%s age_sec=%.1f",
                    connection_id, schema_name, age,
                )
                return cred
            else:
                logger.info(
                    "connection_registry.cache | EXPIRED | connection_id=%s schema=%s age_sec=%.1f",
                    connection_id, schema_name, age,
                )

    logger.info(
        "connection_registry.cache | MISS — fetching from public.databases | connection_id=%s schema=%s",
        connection_id, schema_name,
    )
    cred = resolve_database_credentials(settings, connection_id, schema_name)
    if cred:
        with _cred_cache_lock:
            _cred_cache[cache_key] = (cred, time.monotonic())
        logger.info(
            "connection_registry.cache | STORED | connection_id=%s schema=%s",
            connection_id, schema_name,
        )
    else:
        logger.warning(
            "connection_registry.cache | resolve returned None — NOT cached | connection_id=%s schema=%s",
            connection_id, schema_name,
        )
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
