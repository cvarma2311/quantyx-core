from __future__ import annotations

from typing import Any

from services.ai.config import Settings
from services.ai.db import run_query
from services.ai.domain_refinement_store import (
    list_approved_refinement_artifacts,
    persist_semantic_state,
)


def _rows_or_empty(settings: Settings, sql: str, params: list[Any]) -> list[dict[str, Any]]:
    try:
        return [_json_safe(row) for row in run_query(settings, sql, params)]
    except Exception:
        return []


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _group_refinement_artifacts(artifacts: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped = {
        "business_context": [],
        "hierarchies": [],
        "column_annotations": [],
        "metric_overrides": [],
        "join_rules": [],
        "chart_guidance": [],
        "interpretation_rules": [],
        "context_question_answers": [],
        "other": [],
    }
    for artifact in artifacts:
        artifact_type = str(artifact.get("artifact_type") or "")
        artifact_json = artifact.get("artifact_json") or {}
        item = {
            "artifact_id": artifact.get("artifact_id"),
            "artifact_type": artifact_type,
            "artifact_json": artifact_json,
            "approval_status": artifact.get("approval_status"),
            "validation_status": artifact.get("validation_status"),
            "created_at": _json_safe(artifact.get("created_at")),
        }
        if artifact_type == "business_context":
            grouped["business_context"].append(item)
        elif artifact_type == "hierarchy_override":
            grouped["hierarchies"].append(item)
        elif artifact_type == "column_annotation":
            grouped["column_annotations"].append(item)
        elif artifact_type == "metric_refinement":
            grouped["metric_overrides"].append(item)
        elif artifact_type == "join_rule":
            grouped["join_rules"].append(item)
        elif artifact_type == "chart_guidance":
            grouped["chart_guidance"].append(item)
        elif artifact_type == "interpretation_rule":
            grouped["interpretation_rules"].append(item)
        elif artifact_type == "context_question_answer":
            grouped["context_question_answers"].append(item)
        else:
            grouped["other"].append(item)
    return grouped


def _load_existing_overrides(
    settings: Settings,
    *,
    tenant_id: str,
    domain_id: str,
    connection_id: str | None,
    database_name: str | None,
    schema_name: str | None,
) -> dict[str, list[dict[str, Any]]]:
    params = [tenant_id, domain_id, connection_id, database_name, schema_name]
    hierarchies = _rows_or_empty(
        settings,
        """
        SELECT hierarchy_name, hierarchy_group, levels, description, context_id,
               artifact_key, version_no, lifecycle_status, source_type, updated_at
          FROM public.quantyx_hierarchy_overrides
         WHERE tenant_id = %s
           AND domain_id = %s
           AND connection_id IS NOT DISTINCT FROM %s
           AND database_name IS NOT DISTINCT FROM %s
           AND schema_name IS NOT DISTINCT FROM %s
           AND COALESCE(is_current, true) = true
         ORDER BY updated_at DESC
        """,
        params,
    )
    entities = _rows_or_empty(
        settings,
        """
        SELECT entity_id, description, join_key, examples,
               artifact_key, version_no, lifecycle_status, source_type, updated_at
          FROM public.quantyx_entity_overrides
         WHERE tenant_id = %s
           AND domain_id = %s
           AND connection_id IS NOT DISTINCT FROM %s
           AND database_name IS NOT DISTINCT FROM %s
           AND schema_name IS NOT DISTINCT FROM %s
           AND COALESCE(is_current, true) = true
         ORDER BY updated_at DESC
        """,
        params,
    )
    metrics = _rows_or_empty(
        settings,
        """
        SELECT metric_id, metric_name, display_name, description, type, unit, grain,
               dimensions, dataset_id, source_model, source_schema, sql,
               artifact_key, version_no, lifecycle_status, source_type, updated_at
          FROM public.quantyx_metrics_registry
         WHERE tenant_id = %s
           AND domain_id = %s
           AND connection_id IS NOT DISTINCT FROM %s
           AND database_name IS NOT DISTINCT FROM %s
           AND schema_name IS NOT DISTINCT FROM %s
           AND COALESCE(is_current, true) = true
         ORDER BY updated_at DESC
        """,
        params,
    )
    glossary = _rows_or_empty(
        settings,
        """
        SELECT term_id, term, normalized_term, definition, synonyms, abbreviations,
               lifecycle_status, source_context_id, updated_at
          FROM public.quantyx_glossary_terms
         WHERE tenant_id = %s
           AND domain_id = %s
         ORDER BY updated_at DESC
        """,
        [tenant_id, domain_id],
    )
    return {
        "hierarchies": hierarchies,
        "entities": entities,
        "metrics": metrics,
        "glossary": glossary,
    }


def build_semantic_state(
    settings: Settings,
    *,
    tenant_id: str,
    domain_id: str,
    connection_id: str | None = None,
    database_name: str | None = None,
    schema_name: str | None = None,
) -> dict[str, Any]:
    artifacts = list_approved_refinement_artifacts(
        settings,
        tenant_id=tenant_id,
        domain_id=domain_id,
        connection_id=connection_id,
        database_name=database_name,
        schema_name=schema_name,
    )
    refinement_state = _group_refinement_artifacts(artifacts)
    existing = _load_existing_overrides(
        settings,
        tenant_id=tenant_id,
        domain_id=domain_id,
        connection_id=connection_id,
        database_name=database_name,
        schema_name=schema_name,
    )
    return {
        "scope": {
            "tenant_id": tenant_id,
            "domain_id": domain_id,
            "connection_id": connection_id,
            "database_name": database_name,
            "schema_name": schema_name,
        },
        "precedence": [
            "approved_refinement_artifacts",
            "approved_override_table_entries",
            "active_deployment_artifacts",
            "heuristic_fallback",
        ],
        "refinements": refinement_state,
        "existing_overrides": existing,
        "summary": {
            "approved_refinement_artifact_count": len(artifacts),
            "hierarchy_count": len(refinement_state["hierarchies"]) + len(existing["hierarchies"]),
            "metric_count": len(refinement_state["metric_overrides"]) + len(existing["metrics"]),
            "glossary_count": len(existing["glossary"]),
        },
    }


def rebuild_semantic_state(
    settings: Settings,
    *,
    tenant_id: str,
    domain_id: str,
    connection_id: str | None = None,
    database_name: str | None = None,
    schema_name: str | None = None,
    trigger_type: str = "manual",
) -> dict[str, Any]:
    artifacts = list_approved_refinement_artifacts(
        settings,
        tenant_id=tenant_id,
        domain_id=domain_id,
        connection_id=connection_id,
        database_name=database_name,
        schema_name=schema_name,
    )
    state_json = build_semantic_state(
        settings,
        tenant_id=tenant_id,
        domain_id=domain_id,
        connection_id=connection_id,
        database_name=database_name,
        schema_name=schema_name,
    )
    semantic_state_id = persist_semantic_state(
        settings,
        tenant_id=tenant_id,
        domain_id=domain_id,
        connection_id=connection_id,
        database_name=database_name,
        schema_name=schema_name,
        state_json=state_json,
        created_from_artifact_ids=[str(item.get("artifact_id")) for item in artifacts if item.get("artifact_id")],
        trigger_type=trigger_type,
    )
    return {"semantic_state_id": semantic_state_id, "state_json": state_json}
