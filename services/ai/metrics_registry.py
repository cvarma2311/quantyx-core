from __future__ import annotations

from typing import Any, Iterable

import psycopg2

from services.ai.config import Settings
from services.ai.db import execute_non_query, run_query


def fetch_registry_metrics(
    settings: Settings,
    tenant_id: str | None = None,
    domain_id: str | None = None,
    connection_id: str | None = None,
    database_name: str | None = None,
    schema_name: str | None = None,
    statuses: Iterable[str] | None = None,
    include_all_statuses: bool = False,
) -> list[dict[str, Any]]:
    filters = ["deprecated = false"]
    params: list[object] = []
    if not include_all_statuses:
        allowed = list(statuses) if statuses else ["certified", "active"]
        filters.append("status = ANY(%s)")
        params.append(allowed)
    if tenant_id:
        filters.append("tenant_id = %s")
        params.append(tenant_id)
    if domain_id:
        filters.append("domain_id = %s")
        params.append(domain_id)
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
    sql = f"""
    SELECT metric_id, metric_name, display_name, description, type, sql, grain, dimensions,
           domain_id, tenant_id, connection_id, database_name, schema_name, status, owner, version
    FROM public.quantyx_metrics_registry
    WHERE {where_clause}
    """
    try:
        return run_query(settings, sql, params)
    except psycopg2.errors.UndefinedTable:
        return []


def upsert_metric(settings: Settings, payload: dict[str, Any]) -> str:
    metric_name = payload["metric_name"]
    metric_id = payload.get("metric_id") or f"{payload['domain_id']}__{metric_name}"
    display_name = payload.get("display_name") or metric_name
    sql = """
    INSERT INTO public.quantyx_metrics_registry
      (metric_id, metric_name, domain_id, tenant_id, connection_id, database_name, schema_name,
       display_name, description, type, unit, confidence, additive, grain, dimensions, dataset_id,
       source_model, source_schema, sql, status, owner, version)
    VALUES
      (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (metric_id)
    DO UPDATE SET
      metric_name = EXCLUDED.metric_name,
      display_name = EXCLUDED.display_name,
      description = EXCLUDED.description,
      type = EXCLUDED.type,
      unit = EXCLUDED.unit,
      confidence = EXCLUDED.confidence,
      additive = EXCLUDED.additive,
      grain = EXCLUDED.grain,
      dimensions = EXCLUDED.dimensions,
      dataset_id = EXCLUDED.dataset_id,
      source_model = EXCLUDED.source_model,
      source_schema = EXCLUDED.source_schema,
      sql = EXCLUDED.sql,
      status = EXCLUDED.status,
      owner = EXCLUDED.owner,
      version = EXCLUDED.version,
      updated_at = now()
    """
    params = [
        metric_id,
        metric_name,
        payload["domain_id"],
        payload.get("tenant_id"),
        payload.get("connection_id"),
        payload.get("database"),
        payload.get("schema"),
        display_name,
        payload.get("description"),
        payload.get("type"),
        payload.get("unit"),
        payload.get("confidence"),
        payload.get("additive"),
        payload.get("grain"),
        payload.get("dimensions"),
        payload.get("dataset_id"),
        payload.get("source_model"),
        payload.get("source_schema"),
        payload.get("sql"),
        payload.get("status", "suggested"),
        payload.get("owner"),
        payload.get("version"),
    ]
    execute_non_query(settings, sql, params)
    return metric_id


def update_metric(settings: Settings, metric_id: str, updates: dict[str, Any]) -> None:
    key_map = {
        "database": "database_name",
        "schema": "schema_name",
    }
    allowed_fields = {
        "tenant_id",
        "domain_id",
        "connection_id",
        "database_name",
        "schema_name",
        "metric_name",
        "display_name",
        "description",
        "type",
        "unit",
        "confidence",
        "additive",
        "grain",
        "dimensions",
        "dataset_id",
        "source_model",
        "source_schema",
        "sql",
        "status",
        "owner",
        "version",
    }
    filtered = {}
    for key, value in updates.items():
        mapped_key = key_map.get(key, key)
        if mapped_key in allowed_fields:
            filtered[mapped_key] = value
    if not filtered:
        return
    columns = []
    params: list[Any] = []
    for key, value in filtered.items():
        columns.append(f"{key} = %s")
        params.append(value)
    columns.append("updated_at = now()")
    params.append(metric_id)
    sql = f"UPDATE public.quantyx_metrics_registry SET {', '.join(columns)} WHERE metric_id = %s"
    execute_non_query(settings, sql, params)


def delete_metric(settings: Settings, metric_id: str) -> None:
    sql = "DELETE FROM public.quantyx_metrics_registry WHERE metric_id = %s"
    execute_non_query(settings, sql, [metric_id])
