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
          source_table,
          view_type,
          join_left_key,
          join_right_key,
          coverage_ratio
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
            "fact",
            None,
            None,
            None,
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
            SELECT view_name, schema_name, source_table, created_at, view_type, join_left_key, join_right_key, coverage_ratio
              FROM public.quantyx_fact_views_registry
             WHERE tenant_id = %s AND domain_id = %s
             ORDER BY created_at DESC
            """,
            [tenant_id, domain_id],
        )
    return run_query(
        settings,
        """
        SELECT view_name, schema_name, source_table, created_at, view_type, join_left_key, join_right_key, coverage_ratio
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


def create_joined_views(
    settings: Settings,
    tenant_id: str,
    domain_id: str,
    schema_name: str,
    join_edges: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    created: list[dict[str, Any]] = []
    for edge in join_edges[:5]:
        left = edge.get("left_table")
        right = edge.get("right_table")
        left_key = edge.get("left_key")
        right_key = edge.get("right_key")
        if not (left and right and left_key and right_key):
            continue
        view_name = f"view_{left}_{right}"
        sql = (
            f"CREATE OR REPLACE VIEW {schema_name}.{view_name} AS "
            f"SELECT l.*, r.* "
            f"FROM {schema_name}.{left} l "
            f"LEFT JOIN {schema_name}.{right} r "
            f"ON l.{left_key} = r.{right_key}"
        )
        try:
            execute_non_query(settings, sql, [])
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
                  source_table,
                  view_type,
                  join_left_key,
                  join_right_key,
                  coverage_ratio
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
                """,
                [
                    f"jview_{uuid.uuid4().hex[:10]}",
                    tenant_id,
                    domain_id,
                    "",
                    "",
                    schema_name,
                    view_name,
                    f"{left}__{right}",
                    "joined",
                    left_key,
                    right_key,
                    edge.get("coverage_ratio"),
                ],
            )
            created.append(
                {
                    "view_name": view_name,
                    "left_table": left,
                    "right_table": right,
                    "left_key": left_key,
                    "right_key": right_key,
                    "status": "created",
                }
            )
        except Exception:
            created.append(
                {
                    "view_name": view_name,
                    "left_table": left,
                    "right_table": right,
                    "left_key": left_key,
                    "right_key": right_key,
                    "status": "failed",
                }
            )
    return created
