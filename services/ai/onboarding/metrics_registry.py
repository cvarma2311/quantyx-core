from __future__ import annotations

from typing import Any

from services.ai.config import Settings
from services.ai.dbt_manifest import load_latest_manifest
from services.ai.metrics_registry import upsert_metric


def _load_dbt_model_map(settings: Settings, domain_id: str) -> dict[str, str]:
    payload = load_latest_manifest(settings, domain_id=domain_id)
    if not payload:
        return {}
    nodes = payload.get("nodes", {})
    model_map = {}
    for node in nodes.values():
        if node.get("resource_type") != "model":
            continue
        name = node.get("name")
        alias = node.get("alias")
        relation = node.get("relation_name") or ""
        if name:
            model_map[name.lower()] = name
        if alias:
            model_map[alias.lower()] = name
        if relation:
            model_map[relation.lower()] = name
    return model_map


def _resolve_model_for_table(table: str, model_map: dict[str, str]) -> str | None:
    key = table.lower()
    if key in model_map:
        return model_map[key]
    # Try to match relation suffix ".table"
    for relation, model_name in model_map.items():
        if relation.endswith(f".{key}"):
            return model_name
    return None


def persist_suggested_metrics(
    settings: Settings,
    tenant_id: str,
    domain_id: str,
    connection_id: str,
    database_name: str,
    schema_name: str,
    measures: list[dict[str, Any]],
    lifecycle_status: str = "suggested",
) -> None:
    model_map = _load_dbt_model_map(settings, domain_id)
    for measure in measures:
        metric_id = f"{domain_id}__{measure['table']}__{measure['column']}"
        artifact_key = metric_id
        model_name = _resolve_model_for_table(measure["table"], model_map)
        if model_name:
            dataset_id = model_name
            source_model = model_name
            source_schema = settings.db_schema
            sql_expr = f"SUM({{ ref('{model_name}') }}.{measure['column']})"
        else:
            dataset_id = measure["table"]
            source_model = None
            source_schema = settings.db_schema
            sql_expr = f"SUM({measure['table']}.{measure['column']})"
        unit = measure.get("unit") or measure.get("measure_type")
        upsert_metric(
            settings,
            {
                "metric_id": metric_id,
                "artifact_key": artifact_key,
                "metric_name": measure["column"],
                "domain_id": domain_id,
                "tenant_id": tenant_id,
                "connection_id": connection_id,
                "database": database_name,
                "schema": schema_name,
                "display_name": measure["column"],
                "description": f"Auto-detected metric from {measure['table']}.{measure['column']}",
                "type": "sum",
                "unit": unit,
                "confidence": measure.get("confidence"),
                "additive": measure.get("additive"),
                "grain": "unknown",
                "dimensions": None,
                "dataset_id": dataset_id,
                "source_model": source_model,
                "source_schema": source_schema,
                "sql": sql_expr,
                "lifecycle_status": lifecycle_status,
                "source_type": "rule",
                "is_current": True,
            },
        )
