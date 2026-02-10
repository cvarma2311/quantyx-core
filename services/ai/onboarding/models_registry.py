from __future__ import annotations

import uuid
from typing import Any

import psycopg2

from services.ai.config import Settings
from services.ai.db import execute_non_query, run_query


def _make_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def upsert_fact(settings: Settings, payload: dict[str, Any]) -> str:
    fact_id = payload.get("fact_id") or _make_id("fact")
    sql = """
        INSERT INTO public.quantyx_facts_registry (
          fact_id,
          tenant_id,
          domain_id,
          connection_id,
          database_name,
          schema_name,
          table_name,
          grain,
          time_column,
          measures,
          dimensions,
          description,
          status,
          created_at,
          updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now(), now())
        ON CONFLICT (fact_id)
        DO UPDATE SET
          table_name = EXCLUDED.table_name,
          grain = EXCLUDED.grain,
          time_column = EXCLUDED.time_column,
          measures = EXCLUDED.measures,
          dimensions = EXCLUDED.dimensions,
          description = EXCLUDED.description,
          status = EXCLUDED.status,
          updated_at = now()
    """
    params = [
        fact_id,
        payload["tenant_id"],
        payload["domain_id"],
        payload["connection_id"],
        payload["database_name"],
        payload["schema_name"],
        payload["table_name"],
        payload.get("grain"),
        payload.get("time_column"),
        payload.get("measures", []),
        payload.get("dimensions", []),
        payload.get("description"),
        payload.get("status", "draft"),
    ]
    execute_non_query(settings, sql, params)
    return fact_id


def list_facts(
    settings: Settings,
    tenant_id: str,
    domain_id: str,
    connection_id: str,
    database_name: str,
    schema_name: str,
) -> list[dict]:
    sql = """
        SELECT fact_id, tenant_id, domain_id, connection_id, database_name, schema_name,
               table_name, grain, time_column, measures, dimensions, description, status,
               created_at, updated_at
          FROM public.quantyx_facts_registry
         WHERE tenant_id = %s
           AND domain_id = %s
           AND connection_id = %s
           AND database_name = %s
           AND schema_name = %s
         ORDER BY created_at DESC
    """
    try:
        return run_query(settings, sql, [tenant_id, domain_id, connection_id, database_name, schema_name])
    except psycopg2.errors.UndefinedTable:
        return []


def list_facts_all(settings: Settings, tenant_id: str, domain_id: str) -> list[dict]:
    sql = """
        SELECT fact_id, tenant_id, domain_id, connection_id, database_name, schema_name,
               table_name, grain, time_column, measures, dimensions, description, status,
               created_at, updated_at
          FROM public.quantyx_facts_registry
         WHERE tenant_id = %s AND domain_id = %s
         ORDER BY connection_id, database_name, schema_name, created_at DESC
    """
    try:
        return run_query(settings, sql, [tenant_id, domain_id])
    except psycopg2.errors.UndefinedTable:
        return []


def update_fact(settings: Settings, fact_id: str, updates: dict[str, Any]) -> None:
    allowed_fields = {
        "table_name",
        "grain",
        "time_column",
        "measures",
        "dimensions",
        "description",
        "status",
    }
    filtered = {key: value for key, value in updates.items() if key in allowed_fields}
    if not filtered:
        return
    columns = []
    params: list[Any] = []
    for key, value in filtered.items():
        columns.append(f"{key} = %s")
        params.append(value)
    columns.append("updated_at = now()")
    params.append(fact_id)
    sql = f"UPDATE public.quantyx_facts_registry SET {', '.join(columns)} WHERE fact_id = %s"
    execute_non_query(settings, sql, params)


def delete_fact(settings: Settings, fact_id: str) -> None:
    sql = "DELETE FROM public.quantyx_facts_registry WHERE fact_id = %s"
    execute_non_query(settings, sql, [fact_id])


def upsert_dimension(settings: Settings, payload: dict[str, Any]) -> str:
    dimension_id = payload.get("dimension_id") or _make_id("dim")
    sql = """
        INSERT INTO public.quantyx_dimensions_registry (
          dimension_id,
          tenant_id,
          domain_id,
          connection_id,
          database_name,
          schema_name,
          name,
          keys,
          attributes,
          description,
          status,
          created_at,
          updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now(), now())
        ON CONFLICT (dimension_id)
        DO UPDATE SET
          name = EXCLUDED.name,
          keys = EXCLUDED.keys,
          attributes = EXCLUDED.attributes,
          description = EXCLUDED.description,
          status = EXCLUDED.status,
          updated_at = now()
    """
    params = [
        dimension_id,
        payload["tenant_id"],
        payload["domain_id"],
        payload["connection_id"],
        payload["database_name"],
        payload["schema_name"],
        payload["name"],
        payload.get("keys", []),
        payload.get("attributes", []),
        payload.get("description"),
        payload.get("status", "draft"),
    ]
    execute_non_query(settings, sql, params)
    return dimension_id


def list_dimensions(
    settings: Settings,
    tenant_id: str,
    domain_id: str,
    connection_id: str,
    database_name: str,
    schema_name: str,
) -> list[dict]:
    sql = """
        SELECT dimension_id, tenant_id, domain_id, connection_id, database_name, schema_name,
               name, keys, attributes, description, status,
               created_at, updated_at
          FROM public.quantyx_dimensions_registry
         WHERE tenant_id = %s
           AND domain_id = %s
           AND connection_id = %s
           AND database_name = %s
           AND schema_name = %s
         ORDER BY created_at DESC
    """
    try:
        return run_query(settings, sql, [tenant_id, domain_id, connection_id, database_name, schema_name])
    except psycopg2.errors.UndefinedTable:
        return []


def list_dimensions_all(settings: Settings, tenant_id: str, domain_id: str) -> list[dict]:
    sql = """
        SELECT dimension_id, tenant_id, domain_id, connection_id, database_name, schema_name,
               name, keys, attributes, description, status,
               created_at, updated_at
          FROM public.quantyx_dimensions_registry
         WHERE tenant_id = %s AND domain_id = %s
         ORDER BY connection_id, database_name, schema_name, created_at DESC
    """
    try:
        return run_query(settings, sql, [tenant_id, domain_id])
    except psycopg2.errors.UndefinedTable:
        return []


def update_dimension(settings: Settings, dimension_id: str, updates: dict[str, Any]) -> None:
    allowed_fields = {
        "name",
        "keys",
        "attributes",
        "description",
        "status",
    }
    filtered = {key: value for key, value in updates.items() if key in allowed_fields}
    if not filtered:
        return
    columns = []
    params: list[Any] = []
    for key, value in filtered.items():
        columns.append(f"{key} = %s")
        params.append(value)
    columns.append("updated_at = now()")
    params.append(dimension_id)
    sql = f"UPDATE public.quantyx_dimensions_registry SET {', '.join(columns)} WHERE dimension_id = %s"
    execute_non_query(settings, sql, params)


def delete_dimension(settings: Settings, dimension_id: str) -> None:
    sql = "DELETE FROM public.quantyx_dimensions_registry WHERE dimension_id = %s"
    execute_non_query(settings, sql, [dimension_id])
