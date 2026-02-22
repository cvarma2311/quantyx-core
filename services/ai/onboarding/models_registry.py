from __future__ import annotations

import uuid
from typing import Any

import psycopg2
from psycopg2.extras import Json

from services.ai.config import Settings
from services.ai.db import execute_non_query, run_query


def _make_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def upsert_fact(settings: Settings, payload: dict[str, Any]) -> str:
    fact_id = payload.get("fact_id") or _make_id("fact")
    lifecycle_status = payload.get("lifecycle_status", "draft")
    measures = payload.get("measures", [])
    dimensions = payload.get("dimensions", [])
    measures_value = Json(measures) if isinstance(measures, (list, dict)) else measures
    dimensions_value = Json(dimensions) if isinstance(dimensions, (list, dict)) else dimensions
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
          artifact_key,
          version_no,
          lifecycle_status,
          source_type,
          source_run_id,
          change_reason,
          approved_by,
          approved_at,
          supersedes_version_no,
          created_by,
          updated_by,
          is_current,
          created_at,
          updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now(), now())
        ON CONFLICT (fact_id)
        DO UPDATE SET
          table_name = EXCLUDED.table_name,
          grain = EXCLUDED.grain,
          time_column = EXCLUDED.time_column,
          measures = EXCLUDED.measures,
          dimensions = EXCLUDED.dimensions,
          description = EXCLUDED.description,
          artifact_key = EXCLUDED.artifact_key,
          version_no = EXCLUDED.version_no,
          lifecycle_status = EXCLUDED.lifecycle_status,
          source_type = EXCLUDED.source_type,
          source_run_id = EXCLUDED.source_run_id,
          change_reason = EXCLUDED.change_reason,
          approved_by = EXCLUDED.approved_by,
          approved_at = EXCLUDED.approved_at,
          supersedes_version_no = EXCLUDED.supersedes_version_no,
          created_by = EXCLUDED.created_by,
          updated_by = EXCLUDED.updated_by,
          is_current = EXCLUDED.is_current,
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
        measures_value,
        dimensions_value,
        payload.get("description"),
        payload.get("artifact_key") or fact_id,
        payload.get("version_no", 1),
        lifecycle_status,
        payload.get("source_type", "system"),
        payload.get("source_run_id"),
        payload.get("change_reason"),
        payload.get("approved_by"),
        payload.get("approved_at"),
        payload.get("supersedes_version_no"),
        payload.get("created_by"),
        payload.get("updated_by"),
        payload.get("is_current", True),
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
               table_name, grain, time_column, measures, dimensions, description,
               lifecycle_status, source_type, source_run_id, artifact_key, version_no, is_current,
               created_at, updated_at
          FROM public.quantyx_facts_registry
         WHERE tenant_id = %s
           AND domain_id = %s
           AND connection_id = %s
           AND database_name = %s
           AND schema_name = %s
           AND COALESCE(is_current, true) = true
         ORDER BY created_at DESC
    """
    try:
        return run_query(settings, sql, [tenant_id, domain_id, connection_id, database_name, schema_name])
    except psycopg2.errors.UndefinedTable:
        return []


def list_facts_all(settings: Settings, tenant_id: str, domain_id: str) -> list[dict]:
    sql = """
        SELECT fact_id, tenant_id, domain_id, connection_id, database_name, schema_name,
               table_name, grain, time_column, measures, dimensions, description,
               lifecycle_status, source_type, source_run_id, artifact_key, version_no, is_current,
               created_at, updated_at
          FROM public.quantyx_facts_registry
         WHERE tenant_id = %s AND domain_id = %s
           AND COALESCE(is_current, true) = true
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
        "lifecycle_status",
        "source_type",
        "source_run_id",
        "change_reason",
        "approved_by",
        "approved_at",
        "supersedes_version_no",
        "created_by",
        "updated_by",
        "is_current",
    }
    filtered = {key: value for key, value in updates.items() if key in allowed_fields}
    if not filtered:
        return
    rows = run_query(
        settings,
        """
        SELECT *
          FROM public.quantyx_facts_registry
         WHERE (fact_id = %s OR artifact_key = %s)
           AND COALESCE(is_current, true) = true
         ORDER BY updated_at DESC
         LIMIT 1
        """,
        [fact_id, fact_id],
    )
    if not rows:
        return
    current = rows[0]
    prev_version = int(current.get("version_no") or 1)
    artifact_key = current.get("artifact_key") or current.get("fact_id")
    execute_non_query(
        settings,
        "UPDATE public.quantyx_facts_registry SET is_current = false, updated_at = now() WHERE fact_id = %s",
        [current.get("fact_id")],
    )
    next_version = prev_version + 1
    next_fact_id = f"{artifact_key}__v{next_version}_{uuid.uuid4().hex[:6]}"
    merged = dict(current)
    merged.update(filtered)
    upsert_fact(
        settings,
        {
            "fact_id": next_fact_id,
            "tenant_id": merged.get("tenant_id"),
            "domain_id": merged.get("domain_id"),
            "connection_id": merged.get("connection_id"),
            "database_name": merged.get("database_name"),
            "schema_name": merged.get("schema_name"),
            "table_name": merged.get("table_name"),
            "grain": merged.get("grain"),
            "time_column": merged.get("time_column"),
            "measures": merged.get("measures", []),
            "dimensions": merged.get("dimensions", []),
            "description": merged.get("description"),
            "artifact_key": artifact_key,
            "version_no": next_version,
            "lifecycle_status": merged.get("lifecycle_status", "draft"),
            "source_type": merged.get("source_type", "user"),
            "source_run_id": merged.get("source_run_id"),
            "change_reason": merged.get("change_reason"),
            "approved_by": merged.get("approved_by"),
            "approved_at": merged.get("approved_at"),
            "supersedes_version_no": prev_version,
            "created_by": merged.get("created_by"),
            "updated_by": merged.get("updated_by"),
            "is_current": True,
        },
    )


def delete_fact(settings: Settings, fact_id: str) -> None:
    sql = "DELETE FROM public.quantyx_facts_registry WHERE fact_id = %s OR artifact_key = %s"
    execute_non_query(settings, sql, [fact_id, fact_id])


def upsert_dimension(settings: Settings, payload: dict[str, Any]) -> str:
    dimension_id = payload.get("dimension_id") or _make_id("dim")
    lifecycle_status = payload.get("lifecycle_status", "draft")
    keys = payload.get("keys", [])
    attributes = payload.get("attributes", [])
    keys_value = Json(keys) if isinstance(keys, (list, dict)) else keys
    attributes_value = Json(attributes) if isinstance(attributes, (list, dict)) else attributes
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
          artifact_key,
          version_no,
          lifecycle_status,
          source_type,
          source_run_id,
          change_reason,
          approved_by,
          approved_at,
          supersedes_version_no,
          created_by,
          updated_by,
          is_current,
          created_at,
          updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now(), now())
        ON CONFLICT (dimension_id)
        DO UPDATE SET
          name = EXCLUDED.name,
          keys = EXCLUDED.keys,
          attributes = EXCLUDED.attributes,
          description = EXCLUDED.description,
          artifact_key = EXCLUDED.artifact_key,
          version_no = EXCLUDED.version_no,
          lifecycle_status = EXCLUDED.lifecycle_status,
          source_type = EXCLUDED.source_type,
          source_run_id = EXCLUDED.source_run_id,
          change_reason = EXCLUDED.change_reason,
          approved_by = EXCLUDED.approved_by,
          approved_at = EXCLUDED.approved_at,
          supersedes_version_no = EXCLUDED.supersedes_version_no,
          created_by = EXCLUDED.created_by,
          updated_by = EXCLUDED.updated_by,
          is_current = EXCLUDED.is_current,
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
        keys_value,
        attributes_value,
        payload.get("description"),
        payload.get("artifact_key") or dimension_id,
        payload.get("version_no", 1),
        lifecycle_status,
        payload.get("source_type", "system"),
        payload.get("source_run_id"),
        payload.get("change_reason"),
        payload.get("approved_by"),
        payload.get("approved_at"),
        payload.get("supersedes_version_no"),
        payload.get("created_by"),
        payload.get("updated_by"),
        payload.get("is_current", True),
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
               name, keys, attributes, description,
               lifecycle_status, source_type, source_run_id, artifact_key, version_no, is_current,
               created_at, updated_at
          FROM public.quantyx_dimensions_registry
         WHERE tenant_id = %s
           AND domain_id = %s
           AND connection_id = %s
           AND database_name = %s
           AND schema_name = %s
           AND COALESCE(is_current, true) = true
         ORDER BY created_at DESC
    """
    try:
        return run_query(settings, sql, [tenant_id, domain_id, connection_id, database_name, schema_name])
    except psycopg2.errors.UndefinedTable:
        return []


def list_dimensions_all(settings: Settings, tenant_id: str, domain_id: str) -> list[dict]:
    sql = """
        SELECT dimension_id, tenant_id, domain_id, connection_id, database_name, schema_name,
               name, keys, attributes, description,
               lifecycle_status, source_type, source_run_id, artifact_key, version_no, is_current,
               created_at, updated_at
          FROM public.quantyx_dimensions_registry
         WHERE tenant_id = %s AND domain_id = %s
           AND COALESCE(is_current, true) = true
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
        "lifecycle_status",
        "source_type",
        "source_run_id",
        "change_reason",
        "approved_by",
        "approved_at",
        "supersedes_version_no",
        "created_by",
        "updated_by",
        "is_current",
    }
    filtered = {key: value for key, value in updates.items() if key in allowed_fields}
    if not filtered:
        return
    rows = run_query(
        settings,
        """
        SELECT *
          FROM public.quantyx_dimensions_registry
         WHERE (dimension_id = %s OR artifact_key = %s)
           AND COALESCE(is_current, true) = true
         ORDER BY updated_at DESC
         LIMIT 1
        """,
        [dimension_id, dimension_id],
    )
    if not rows:
        return
    current = rows[0]
    prev_version = int(current.get("version_no") or 1)
    artifact_key = current.get("artifact_key") or current.get("dimension_id")
    execute_non_query(
        settings,
        "UPDATE public.quantyx_dimensions_registry SET is_current = false, updated_at = now() WHERE dimension_id = %s",
        [current.get("dimension_id")],
    )
    next_version = prev_version + 1
    next_dimension_id = f"{artifact_key}__v{next_version}_{uuid.uuid4().hex[:6]}"
    merged = dict(current)
    merged.update(filtered)
    upsert_dimension(
        settings,
        {
            "dimension_id": next_dimension_id,
            "tenant_id": merged.get("tenant_id"),
            "domain_id": merged.get("domain_id"),
            "connection_id": merged.get("connection_id"),
            "database_name": merged.get("database_name"),
            "schema_name": merged.get("schema_name"),
            "name": merged.get("name"),
            "keys": merged.get("keys", []),
            "attributes": merged.get("attributes", []),
            "description": merged.get("description"),
            "artifact_key": artifact_key,
            "version_no": next_version,
            "lifecycle_status": merged.get("lifecycle_status", "draft"),
            "source_type": merged.get("source_type", "user"),
            "source_run_id": merged.get("source_run_id"),
            "change_reason": merged.get("change_reason"),
            "approved_by": merged.get("approved_by"),
            "approved_at": merged.get("approved_at"),
            "supersedes_version_no": prev_version,
            "created_by": merged.get("created_by"),
            "updated_by": merged.get("updated_by"),
            "is_current": True,
        },
    )


def delete_dimension(settings: Settings, dimension_id: str) -> None:
    sql = "DELETE FROM public.quantyx_dimensions_registry WHERE dimension_id = %s OR artifact_key = %s"
    execute_non_query(settings, sql, [dimension_id, dimension_id])
