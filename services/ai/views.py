from __future__ import annotations

import logging
import uuid
from typing import Any

import psycopg2

from services.ai.config import Settings
from services.ai.db import execute_non_query, run_query

logger = logging.getLogger(__name__)


def _registry_columns(settings: Settings) -> set[str]:
    rows = run_query(
        settings,
        """
        SELECT column_name
          FROM information_schema.columns
         WHERE table_schema = 'public'
           AND table_name = 'quantyx_fact_views_registry'
        """,
        [],
    )
    return {str(r.get("column_name")) for r in rows if r.get("column_name")}


def _insert_registry_row(settings: Settings, values: dict[str, Any]) -> None:
    cols = _registry_columns(settings)
    ordered = [k for k in values.keys() if k in cols]
    if not ordered:
        logger.warning("views.registry.insert_skipped | reason=no_compatible_columns")
        return
    placeholders = ", ".join(["%s"] * len(ordered))
    sql = (
        "INSERT INTO public.quantyx_fact_views_registry ("
        + ", ".join(ordered)
        + f") VALUES ({placeholders}) ON CONFLICT DO NOTHING"
    )
    execute_non_query(settings, sql, [values[k] for k in ordered])


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

    _insert_registry_row(
        settings,
        {
            "view_id": f"fview_{uuid.uuid4().hex[:10]}",
            "tenant_id": tenant_id,
            "domain_id": domain_id,
            "connection_id": connection_id,
            "database_name": database_name,
            "schema_name": schema_name,
            "view_name": fact_table,
            "source_table": source_table,
            "view_type": "fact",
            "join_left_key": None,
            "join_right_key": None,
            "coverage_ratio": None,
        },
    )
    return fact_table


def list_views(
    settings: Settings,
    tenant_id: str,
    domain_id: str | None,
) -> list[dict[str, Any]]:
    cols = _registry_columns(settings)
    view_type_expr = "view_type" if "view_type" in cols else "'fact' AS view_type"
    join_left_key_expr = "join_left_key" if "join_left_key" in cols else "NULL AS join_left_key"
    join_right_key_expr = "join_right_key" if "join_right_key" in cols else "NULL AS join_right_key"
    coverage_ratio_expr = "coverage_ratio" if "coverage_ratio" in cols else "NULL AS coverage_ratio"
    if domain_id:
        return run_query(
            settings,
            f"""
            SELECT view_name, schema_name, source_table, created_at,
                   {view_type_expr}, {join_left_key_expr}, {join_right_key_expr}, {coverage_ratio_expr}
              FROM public.quantyx_fact_views_registry
             WHERE tenant_id = %s AND domain_id = %s
             ORDER BY created_at DESC
            """,
            [tenant_id, domain_id],
        )
    return run_query(
        settings,
        f"""
        SELECT view_name, schema_name, source_table, created_at,
               {view_type_expr}, {join_left_key_expr}, {join_right_key_expr}, {coverage_ratio_expr}
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
    def _table_names(payload: dict[str, Any]) -> list[str]:
        names: list[str] = []
        if isinstance(payload.get("tables"), list):
            for item in payload.get("tables") or []:
                if isinstance(item, str):
                    names.append(item)
                elif isinstance(item, dict):
                    name = item.get("table") or item.get("name") or item.get("table_name")
                    if name:
                        names.append(str(name))
        for schema in payload.get("schemas", []) or []:
            if not isinstance(schema, dict):
                continue
            for item in schema.get("tables", []) or []:
                if isinstance(item, str):
                    names.append(item)
                elif isinstance(item, dict):
                    name = item.get("table") or item.get("name") or item.get("table_name")
                    if name:
                        names.append(str(name))
        for connection in payload.get("connections", []) or []:
            if not isinstance(connection, dict):
                continue
            for database in connection.get("databases", []) or []:
                if not isinstance(database, dict):
                    continue
                for schema in database.get("schemas", []) or []:
                    if not isinstance(schema, dict):
                        continue
                    for item in schema.get("tables", []) or []:
                        if isinstance(item, str):
                            names.append(item)
                        elif isinstance(item, dict):
                            name = item.get("table") or item.get("name") or item.get("table_name")
                            if name:
                                names.append(str(name))
        # preserve order while deduping
        return list(dict.fromkeys([n for n in names if n]))

    created: list[str] = []
    for name in _table_names(schema_payload):
        try:
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
        except Exception:
            logger.warning("views.create_fact_view_failed | schema=%s table=%s", schema_name, name, exc_info=True)
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
            _insert_registry_row(
                settings,
                {
                    "view_id": f"jview_{uuid.uuid4().hex[:10]}",
                    "tenant_id": tenant_id,
                    "domain_id": domain_id,
                    "connection_id": "",
                    "database_name": "",
                    "schema_name": schema_name,
                    "view_name": view_name,
                    "source_table": f"{left}__{right}",
                    "view_type": "joined",
                    "join_left_key": left_key,
                    "join_right_key": right_key,
                    "coverage_ratio": edge.get("coverage_ratio"),
                },
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
