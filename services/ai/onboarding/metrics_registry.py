from __future__ import annotations

from typing import Any

from services.ai.config import Settings
from services.ai.db import execute_non_query
from services.ai.dbt_manifest import load_latest_manifest


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
    domain_id: str,
    measures: list[dict[str, Any]],
    status: str = "suggested",
) -> None:
    model_map = _load_dbt_model_map(settings, domain_id)
    for measure in measures:
        metric_id = f"{domain_id}__{measure['table']}__{measure['column']}"
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
        sql = """
        INSERT INTO public.quantyx_metrics_registry
          (metric_id, metric_name, domain_id, display_name, description, type, unit, confidence, additive, grain, dimensions, dataset_id, source_model, source_schema, sql, status)
        VALUES
          (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (metric_id)
        DO UPDATE SET
          metric_name = EXCLUDED.metric_name,
          status = EXCLUDED.status,
          unit = EXCLUDED.unit,
          confidence = EXCLUDED.confidence,
          additive = EXCLUDED.additive,
          source_model = EXCLUDED.source_model,
          source_schema = EXCLUDED.source_schema,
          updated_at = now()
        """
        unit = measure.get("unit") or measure.get("measure_type")
        params = (
            metric_id,
            measure["column"],
            domain_id,
            measure["column"],
            f"Auto-detected metric from {measure['table']}.{measure['column']}",
            "sum",
            unit,
            measure.get("confidence"),
            measure.get("additive"),
            "unknown",
            None,
            dataset_id,
            source_model,
            source_schema,
            sql_expr,
            status,
        )
        execute_non_query(settings, sql, list(params))
