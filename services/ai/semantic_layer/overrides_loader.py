from __future__ import annotations

import psycopg2
from psycopg2.extras import RealDictCursor

from services.ai.config import Settings


def load_entity_overrides(
    settings: Settings,
    tenant_id: str,
    domain_id: str,
    connection_id: str | None = None,
    database_name: str | None = None,
    schema_name: str | None = None,
) -> list[dict]:
    conn = psycopg2.connect(
        host=settings.db_host,
        port=settings.db_port,
        dbname=settings.db_name,
        user=settings.db_user,
        password=settings.db_password,
    )
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            filters = ["tenant_id = %s", "domain_id = %s"]
            params: list[object] = [tenant_id, domain_id]
            if connection_id:
                filters.append("connection_id = %s")
                params.append(connection_id)
            if database_name:
                filters.append("database_name = %s")
                params.append(database_name)
            if schema_name:
                filters.append("schema_name = %s")
                params.append(schema_name)
            where_clause = " AND ".join(filters)
            cur.execute(
                f"""
                SELECT entity_id, description, join_key, examples,
                       connection_id, database_name, schema_name,
                       lifecycle_status, source_type, source_run_id, artifact_key, version_no, is_current
                FROM public.quantyx_entity_overrides
                WHERE {where_clause}
                  AND COALESCE(is_current, true) = true
                """,
                params,
            )
            return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def load_entity_overrides_all(settings: Settings, tenant_id: str, domain_id: str) -> list[dict]:
    conn = psycopg2.connect(
        host=settings.db_host,
        port=settings.db_port,
        dbname=settings.db_name,
        user=settings.db_user,
        password=settings.db_password,
    )
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT entity_id, description, join_key, examples,
                       connection_id, database_name, schema_name,
                       lifecycle_status, source_type, source_run_id, artifact_key, version_no, is_current
                FROM public.quantyx_entity_overrides
                WHERE tenant_id = %s AND domain_id = %s
                  AND COALESCE(is_current, true) = true
                ORDER BY connection_id, database_name, schema_name, entity_id
                """,
                (tenant_id, domain_id),
            )
            return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def load_hierarchy_overrides(
    settings: Settings,
    tenant_id: str,
    domain_id: str,
    connection_id: str | None = None,
    database_name: str | None = None,
    schema_name: str | None = None,
) -> list[dict]:
    conn = psycopg2.connect(
        host=settings.db_host,
        port=settings.db_port,
        dbname=settings.db_name,
        user=settings.db_user,
        password=settings.db_password,
    )
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            filters = ["tenant_id = %s", "domain_id = %s"]
            params: list[object] = [tenant_id, domain_id]
            if connection_id:
                filters.append("connection_id = %s")
                params.append(connection_id)
            if database_name:
                filters.append("database_name = %s")
                params.append(database_name)
            if schema_name:
                filters.append("schema_name = %s")
                params.append(schema_name)
            where_clause = " AND ".join(filters)
            cur.execute(
                f"""
                SELECT hierarchy_name, levels, description,
                       connection_id, database_name, schema_name,
                       lifecycle_status, source_type, source_run_id, artifact_key, version_no, is_current
                FROM public.quantyx_hierarchy_overrides
                WHERE {where_clause}
                  AND COALESCE(is_current, true) = true
                """,
                params,
            )
            return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def load_hierarchy_overrides_all(settings: Settings, tenant_id: str, domain_id: str) -> list[dict]:
    conn = psycopg2.connect(
        host=settings.db_host,
        port=settings.db_port,
        dbname=settings.db_name,
        user=settings.db_user,
        password=settings.db_password,
    )
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT hierarchy_name, levels, description,
                       connection_id, database_name, schema_name,
                       lifecycle_status, source_type, source_run_id, artifact_key, version_no, is_current
                FROM public.quantyx_hierarchy_overrides
                WHERE tenant_id = %s AND domain_id = %s
                  AND COALESCE(is_current, true) = true
                ORDER BY connection_id, database_name, schema_name, hierarchy_name
                """,
                (tenant_id, domain_id),
            )
            return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()
