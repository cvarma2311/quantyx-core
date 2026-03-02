from __future__ import annotations

import uuid
from typing import Any

import psycopg2

from services.ai.config import Settings
from services.ai.db import execute_non_query, run_query


def ensure_fact_view(
    settings: Settings,
    tenant_id: str,
    domain_id: str,
    connection_id: str,
    database_name: str,
    schema_name: str,
    source_table: str,
) -> str:
    fact_table = source_table if source_table.startswith("fact_") else f"fact_{source_table}"
    sql = f"""
        CREATE OR REPLACE VIEW {schema_name}.{fact_table} AS
        SELECT * FROM {schema_name}.{source_table}
    """
    conn = psycopg2.connect(
        host=settings.db_host,
        port=settings.db_port,
        dbname=settings.db_name,
        user=settings.db_user,
        password=settings.db_password,
    )
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()
    finally:
        conn.close()

    execute_non_query(
        settings,
        """
        INSERT INTO public.quantyx_fact_views_registry (
          view_id,
          tenant_id,
          domain_id,
          connection_id,
          database_name,
          schema_name,
          view_name,
          source_table
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT DO NOTHING
        """,
        [
            f"fview_{uuid.uuid4().hex[:10]}",
            tenant_id,
            domain_id,
            connection_id,
            database_name,
            schema_name,
            fact_table,
            source_table,
        ],
    )
    return fact_table


def list_views(
    settings: Settings,
    tenant_id: str,
    domain_id: str | None,
) -> list[dict[str, Any]]:
    if domain_id:
        return run_query(
            settings,
            """
            SELECT view_name, schema_name, source_table, created_at
              FROM public.quantyx_fact_views_registry
             WHERE tenant_id = %s AND domain_id = %s
             ORDER BY created_at DESC
            """,
            [tenant_id, domain_id],
        )
    return run_query(
        settings,
        """
        SELECT view_name, schema_name, source_table, created_at
          FROM public.quantyx_fact_views_registry
         WHERE tenant_id = %s
         ORDER BY created_at DESC
        """,
        [tenant_id],
    )


def get_view_schema(settings: Settings, schema_name: str, view_name: str) -> list[dict[str, Any]]:
    return run_query(
        settings,
        """
        SELECT column_name, data_type
          FROM information_schema.columns
         WHERE table_schema = %s
           AND table_name = %s
         ORDER BY ordinal_position
        """,
        [schema_name, view_name],
    )


def create_views_from_schema(
    settings: Settings,
    tenant_id: str,
    domain_id: str,
    connection_id: str,
    database_name: str,
    schema_name: str,
    schema_payload: dict[str, Any],
) -> list[str]:
    created: list[str] = []
    for table in schema_payload.get("tables", []) or []:
        name = table.get("table")
        if not name:
            continue
        created.append(
            ensure_fact_view(
                settings,
                tenant_id,
                domain_id,
                connection_id,
                database_name,
                schema_name,
                name,
            )
        )
    return created
