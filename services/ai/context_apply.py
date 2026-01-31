from __future__ import annotations

from typing import Any

from services.ai.config import Settings
from services.ai.db import execute_non_query


def _normalize_term(term: str) -> str:
    return term.strip().lower()


def apply_extractions(
    settings: Settings,
    tenant_id: str,
    domain_id: str,
    payload: dict[str, Any],
    apply_flags: dict[str, bool],
) -> dict[str, int]:
    updated: dict[str, int] = {"entities": 0, "hierarchies": 0, "glossary": 0, "metrics": 0}

    if apply_flags.get("entities"):
        for entity in payload.get("entities", []):
            entity_id = entity.get("entity_id")
            if not entity_id:
                continue
            sql = """
                INSERT INTO public.quantyx_entity_overrides (
                  tenant_id,
                  domain_id,
                  entity_id,
                  description,
                  join_key,
                  examples,
                  updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, now())
                ON CONFLICT (tenant_id, domain_id, entity_id)
                DO UPDATE SET
                  description = EXCLUDED.description,
                  join_key = EXCLUDED.join_key,
                  examples = EXCLUDED.examples,
                  updated_at = now()
            """
            execute_non_query(
                settings,
                sql,
                [
                    tenant_id,
                    domain_id,
                    entity_id,
                    entity.get("description"),
                    entity.get("join_key"),
                    entity.get("examples"),
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
                  hierarchy_name,
                  levels,
                  description,
                  updated_at
                )
                VALUES (%s, %s, %s, %s, %s, now())
                ON CONFLICT (tenant_id, domain_id, hierarchy_name)
                DO UPDATE SET
                  levels = EXCLUDED.levels,
                  description = EXCLUDED.description,
                  updated_at = now()
            """
            execute_non_query(
                settings,
                sql,
                [tenant_id, domain_id, name, levels, hierarchy.get("description")],
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
                    entry.get("source_context_id"),
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
                    entry.get("source_context_id"),
                ],
            )
            updated["glossary"] += 1

    if apply_flags.get("metrics"):
        for metric in payload.get("metric_candidates", []):
            metric_name = metric.get("metric_name")
            if not metric_name:
                continue
            metric_id = f"{domain_id}__{metric_name}"
            sql = """
                INSERT INTO public.quantyx_metrics_registry (
                  metric_id,
                  metric_name,
                  domain_id,
                  description,
                  type,
                  unit,
                  grain,
                  dimensions,
                  dataset_id,
                  source_model,
                  source_schema,
                  sql,
                  status,
                  created_at,
                  updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now(), now())
                ON CONFLICT (metric_id)
                DO UPDATE SET
                  description = EXCLUDED.description,
                  type = EXCLUDED.type,
                  unit = EXCLUDED.unit,
                  grain = EXCLUDED.grain,
                  dimensions = EXCLUDED.dimensions,
                  dataset_id = EXCLUDED.dataset_id,
                  source_model = EXCLUDED.source_model,
                  source_schema = EXCLUDED.source_schema,
                  sql = EXCLUDED.sql,
                  status = EXCLUDED.status,
                  updated_at = now()
            """
            execute_non_query(
                settings,
                sql,
                [
                    metric_id,
                    metric_name,
                    domain_id,
                    metric.get("description"),
                    metric.get("type"),
                    metric.get("unit"),
                    metric.get("grain"),
                    metric.get("dimensions"),
                    metric.get("table"),
                    metric.get("table"),
                    metric.get("schema"),
                    metric.get("sql"),
                    "suggested",
                ],
            )
            updated["metrics"] += 1

    return updated
