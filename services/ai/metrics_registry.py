from __future__ import annotations

import uuid
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
    filters = ["deprecated = false", "COALESCE(is_current, true) = true"]
    params: list[object] = []
    if not include_all_statuses:
        allowed = list(statuses) if statuses else ["certified", "active"]
        filters.append("lifecycle_status = ANY(%s)")
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
           domain_id, tenant_id, connection_id, database_name, schema_name, lifecycle_status,
           source_type, source_run_id, artifact_key, version_no, is_current, owner, version,
           dataset_id, source_model
    FROM public.quantyx_metrics_registry
    WHERE {where_clause}
    """
    try:
        return run_query(settings, sql, params)
    except psycopg2.errors.UndefinedTable:
        return []


def upsert_metric(settings: Settings, payload: dict[str, Any]) -> str:
    metric_name = payload["metric_name"]
    scope = (
        payload.get("tenant_id"),
        payload["domain_id"],
        payload.get("connection_id"),
        payload.get("database"),
        payload.get("schema"),
    )
    artifact_key = payload.get("artifact_key") or payload.get("metric_id") or f"{payload['domain_id']}__{metric_name}"
    current_rows = run_query(
        settings,
        """
        SELECT metric_id, version_no
          FROM public.quantyx_metrics_registry
         WHERE tenant_id = %s
           AND domain_id = %s
           AND connection_id = %s
           AND database_name = %s
           AND schema_name = %s
           AND artifact_key = %s
           AND COALESCE(is_current, true) = true
         ORDER BY COALESCE(version_no, 1) DESC, updated_at DESC
         LIMIT 1
        """,
        [scope[0], scope[1], scope[2], scope[3], scope[4], artifact_key],
    )
    if current_rows:
        previous = current_rows[0]
        prev_version = int(previous.get("version_no") or 1)
        version_no = prev_version + 1
        metric_id = f"{artifact_key}__v{version_no}_{uuid.uuid4().hex[:6]}"
        execute_non_query(
            settings,
            "UPDATE public.quantyx_metrics_registry SET is_current = false, updated_at = now() WHERE metric_id = %s",
            [previous.get("metric_id")],
        )
        supersedes_version_no = payload.get("supersedes_version_no", prev_version)
    else:
        version_no = int(payload.get("version_no") or 1)
        metric_id = payload.get("metric_id") or artifact_key
        supersedes_version_no = payload.get("supersedes_version_no")
    display_name = payload.get("display_name") or metric_name
    lifecycle_status = payload.get("lifecycle_status") or "suggested"
    sql = """
    INSERT INTO public.quantyx_metrics_registry
      (metric_id, metric_name, domain_id, tenant_id, connection_id, database_name, schema_name,
       display_name, description, type, unit, confidence, additive, grain, dimensions, dataset_id,
       source_model, source_schema, sql, lifecycle_status, source_type, source_run_id,
       artifact_key, version_no, is_current, change_reason, approved_by, approved_at,
       supersedes_version_no, created_by, updated_by, owner, version)
    VALUES
      (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
        lifecycle_status,
        payload.get("source_type", "system"),
        payload.get("source_run_id"),
        artifact_key,
        version_no,
        payload.get("is_current", True),
        payload.get("change_reason"),
        payload.get("approved_by"),
        payload.get("approved_at"),
        supersedes_version_no,
        payload.get("created_by"),
        payload.get("updated_by"),
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
        "lifecycle_status",
        "source_type",
        "source_run_id",
        "artifact_key",
        "version_no",
        "is_current",
        "change_reason",
        "approved_by",
        "approved_at",
        "supersedes_version_no",
        "created_by",
        "updated_by",
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
    rows = run_query(
        settings,
        """
        SELECT *
          FROM public.quantyx_metrics_registry
         WHERE (metric_id = %s OR artifact_key = %s)
           AND COALESCE(is_current, true) = true
         ORDER BY updated_at DESC
         LIMIT 1
        """,
        [metric_id, metric_id],
    )
    if not rows:
        return
    current = rows[0]
    merged = dict(current)
    merged.update(filtered)
    upsert_metric(
        settings,
        {
            "metric_name": merged.get("metric_name"),
            "metric_id": merged.get("artifact_key") or merged.get("metric_id"),
            "tenant_id": merged.get("tenant_id"),
            "domain_id": merged.get("domain_id"),
            "connection_id": merged.get("connection_id"),
            "database": merged.get("database_name"),
            "schema": merged.get("schema_name"),
            "display_name": merged.get("display_name"),
            "description": merged.get("description"),
            "type": merged.get("type"),
            "unit": merged.get("unit"),
            "confidence": merged.get("confidence"),
            "additive": merged.get("additive"),
            "grain": merged.get("grain"),
            "dimensions": merged.get("dimensions"),
            "dataset_id": merged.get("dataset_id"),
            "source_model": merged.get("source_model"),
            "source_schema": merged.get("source_schema"),
            "sql": merged.get("sql"),
            "lifecycle_status": merged.get("lifecycle_status", "suggested"),
            "source_type": merged.get("source_type", "user"),
            "source_run_id": merged.get("source_run_id"),
            "artifact_key": merged.get("artifact_key") or merged.get("metric_id"),
            "change_reason": merged.get("change_reason"),
            "approved_by": merged.get("approved_by"),
            "approved_at": merged.get("approved_at"),
            "created_by": merged.get("created_by"),
            "updated_by": merged.get("updated_by"),
            "owner": merged.get("owner"),
            "version": merged.get("version"),
        },
    )


def delete_metric(settings: Settings, metric_id: str) -> None:
    sql = "DELETE FROM public.quantyx_metrics_registry WHERE metric_id = %s OR artifact_key = %s"
    execute_non_query(settings, sql, [metric_id, metric_id])
