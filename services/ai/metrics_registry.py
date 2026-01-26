from __future__ import annotations

from typing import Any, Iterable

import psycopg2

from services.ai.config import Settings
from services.ai.db import execute_non_query, run_query


def fetch_registry_metrics(
    settings: Settings,
    statuses: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    allowed = list(statuses) if statuses else ["certified", "active"]
    sql = """
    SELECT metric_id, metric_name, display_name, description, type, sql, grain, dimensions
    FROM public.quantyx_metrics_registry
    WHERE deprecated = false AND status = ANY(%s)
    """
    try:
        return run_query(settings, sql, [allowed])
    except psycopg2.errors.UndefinedTable:
        return []


def upsert_metric(settings: Settings, payload: dict[str, Any]) -> str:
    metric_name = payload["metric_name"]
    metric_id = payload.get("metric_id") or f"{payload['domain_id']}__{metric_name}"
    display_name = payload.get("display_name") or metric_name
    sql = """
    INSERT INTO public.quantyx_metrics_registry
      (metric_id, metric_name, domain_id, display_name, description, type, unit, confidence, additive, grain, dimensions, dataset_id, source_model, source_schema, sql, status, owner, version)
    VALUES
      (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
    allowed_fields = {
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
    filtered = {key: value for key, value in updates.items() if key in allowed_fields}
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
