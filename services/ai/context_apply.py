from __future__ import annotations

from typing import Any

from services.ai.config import Settings
from services.ai.db import execute_non_query
from services.ai.metrics_registry import upsert_metric


def _normalize_term(term: str) -> str:
    return term.strip().lower()


def apply_extractions(
    settings: Settings,
    tenant_id: str,
    domain_id: str,
    payload: dict[str, Any],
    apply_flags: dict[str, bool],
    source_context_id: str | None = None,
    connection_id: str | None = None,
    database_name: str | None = None,
    schema_name: str | None = None,
) -> dict[str, int]:
    updated: dict[str, int] = {"entities": 0, "hierarchies": 0, "glossary": 0, "metrics": 0}
    connection_id = connection_id or "global"
    database_name = database_name or "global"
    schema_name = schema_name or "global"

    if apply_flags.get("entities"):
        for entity in payload.get("entities", []):
            entity_id = entity.get("entity_id")
            if not entity_id:
                continue
            sql = """
                INSERT INTO public.quantyx_entity_overrides (
                  tenant_id,
                  domain_id,
                  connection_id,
                  database_name,
                  schema_name,
                  entity_id,
                  description,
                  join_key,
                  examples,
                  artifact_key,
                  lifecycle_status,
                  source_type,
                  source_run_id,
                  source_context_id,
                  is_current,
                  created_at,
                  updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now(), now())
                ON CONFLICT (tenant_id, domain_id, connection_id, database_name, schema_name, entity_id)
                DO UPDATE SET
                  description = EXCLUDED.description,
                  join_key = EXCLUDED.join_key,
                  examples = EXCLUDED.examples,
                  artifact_key = EXCLUDED.artifact_key,
                  lifecycle_status = EXCLUDED.lifecycle_status,
                  source_type = EXCLUDED.source_type,
                  source_run_id = EXCLUDED.source_run_id,
                  source_context_id = EXCLUDED.source_context_id,
                  is_current = EXCLUDED.is_current,
                  updated_at = now()
            """
            execute_non_query(
                settings,
                sql,
                [
                    tenant_id,
                    domain_id,
                    connection_id,
                    database_name,
                    schema_name,
                    entity_id,
                    entity.get("description"),
                    entity.get("join_key"),
                    entity.get("examples"),
                    entity_id,
                    "draft",
                    "llm",
                    source_context_id,
                    source_context_id,
                    True,
                ],
            )
            updated["entities"] += 1

    if apply_flags.get("hierarchies"):
        for hierarchy in payload.get("hierarchies", []):
            name = hierarchy.get("name")
            levels = hierarchy.get("levels")
            if not name or not levels:
                continue
            sql = """
                INSERT INTO public.quantyx_hierarchy_overrides (
                  tenant_id,
                  domain_id,
                  connection_id,
                  database_name,
                  schema_name,
                  hierarchy_name,
                  levels,
                  description,
                  artifact_key,
                  lifecycle_status,
                  source_type,
                  source_run_id,
                  source_context_id,
                  is_current,
                  created_at,
                  updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now(), now())
                ON CONFLICT (tenant_id, domain_id, connection_id, database_name, schema_name, hierarchy_name)
                DO UPDATE SET
                  levels = EXCLUDED.levels,
                  description = EXCLUDED.description,
                  artifact_key = EXCLUDED.artifact_key,
                  lifecycle_status = EXCLUDED.lifecycle_status,
                  source_type = EXCLUDED.source_type,
                  source_run_id = EXCLUDED.source_run_id,
                  source_context_id = EXCLUDED.source_context_id,
                  is_current = EXCLUDED.is_current,
                  updated_at = now()
            """
            execute_non_query(
                settings,
                sql,
                [
                    tenant_id,
                    domain_id,
                    connection_id,
                    database_name,
                    schema_name,
                    name,
                    levels,
                    hierarchy.get("description"),
                    name,
                    "draft",
                    "llm",
                    source_context_id,
                    source_context_id,
                    True,
                ],
            )
            updated["hierarchies"] += 1

    if apply_flags.get("glossary"):
        for entry in payload.get("synonyms", []):
            term = entry.get("term")
            if not term:
                continue
            normalized = _normalize_term(term)
            term_id = f"{tenant_id}__{domain_id}__{normalized}"
            sql = """
                INSERT INTO public.quantyx_glossary_terms (
                  term_id,
                  tenant_id,
                  domain_id,
                  term,
                  normalized_term,
                  definition,
                  synonyms,
                  abbreviations,
                  source_context_id,
                  created_at,
                  updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, now(), now())
                ON CONFLICT (term_id)
                DO UPDATE SET
                  definition = EXCLUDED.definition,
                  synonyms = EXCLUDED.synonyms,
                  abbreviations = EXCLUDED.abbreviations,
                  source_context_id = EXCLUDED.source_context_id,
                  updated_at = now()
            """
            execute_non_query(
                settings,
                sql,
                [
                    term_id,
                    tenant_id,
                    domain_id,
                    term,
                    normalized,
                    entry.get("definition"),
                    entry.get("synonyms", []),
                    entry.get("abbreviations", []),
                    source_context_id,
                ],
            )
            updated["glossary"] += 1

        for entry in payload.get("abbreviations", []):
            abbr = entry.get("abbr")
            definition = entry.get("definition")
            if not abbr:
                continue
            normalized = _normalize_term(abbr)
            term_id = f"{tenant_id}__{domain_id}__{normalized}"
            sql = """
                INSERT INTO public.quantyx_glossary_terms (
                  term_id,
                  tenant_id,
                  domain_id,
                  term,
                  normalized_term,
                  definition,
                  synonyms,
                  abbreviations,
                  source_context_id,
                  created_at,
                  updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, now(), now())
                ON CONFLICT (term_id)
                DO UPDATE SET
                  definition = EXCLUDED.definition,
                  abbreviations = EXCLUDED.abbreviations,
                  source_context_id = EXCLUDED.source_context_id,
                  updated_at = now()
            """
            execute_non_query(
                settings,
                sql,
                [
                    term_id,
                    tenant_id,
                    domain_id,
                    abbr,
                    normalized,
                    definition,
                    [],
                    [abbr],
                    source_context_id,
                ],
            )
            updated["glossary"] += 1

    if apply_flags.get("metrics"):
        for metric in payload.get("metric_candidates", []):
            metric_name = metric.get("metric_name")
            if not metric_name:
                continue
            metric_id = f"{domain_id}__{metric_name}"
            upsert_metric(
                settings,
                {
                    "metric_id": metric_id,
                    "artifact_key": metric_id,
                    "metric_name": metric_name,
                    "domain_id": domain_id,
                    "tenant_id": tenant_id,
                    "connection_id": connection_id,
                    "database": database_name,
                    "schema": schema_name,
                    "description": metric.get("description"),
                    "type": metric.get("type"),
                    "unit": metric.get("unit"),
                    "grain": metric.get("grain"),
                    "dimensions": metric.get("dimensions"),
                    "dataset_id": metric.get("table"),
                    "source_model": metric.get("table"),
                    "source_schema": metric.get("schema"),
                    "sql": metric.get("sql"),
                    "lifecycle_status": "suggested",
                    "source_type": "llm",
                    "source_run_id": source_context_id,
                    "is_current": True,
                },
            )
            updated["metrics"] += 1

    return updated
