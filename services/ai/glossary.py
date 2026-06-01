from __future__ import annotations

from copy import deepcopy
import json
from typing import Any

from psycopg2.extras import Json

from services.ai.config import Settings
from services.ai.db import execute_non_query, run_query


def _normalize_term(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def fetch_glossary_terms(settings: Settings, tenant_id: str, domain_id: str) -> list[dict[str, Any]]:
    sql = """
        SELECT term_id,
               term,
               normalized_term,
               definition,
               synonyms,
               abbreviations
          FROM public.quantyx_glossary_terms
         WHERE tenant_id = %s
           AND domain_id = %s
    """
    return run_query(settings, sql, [tenant_id, domain_id])


def upsert_glossary_terms(
    settings: Settings,
    *,
    tenant_id: str,
    domain_id: str,
    terms: list[dict[str, Any]] | None,
    lifecycle_status: str = "suggested",
    source_context_id: str | None = None,
) -> int:
    entries = [dict(item) for item in (terms or []) if isinstance(item, dict)]
    if not entries:
        return 0
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
          lifecycle_status,
          source_context_id,
          created_at,
          updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now(), now())
        ON CONFLICT (term_id)
        DO UPDATE SET
          term = EXCLUDED.term,
          definition = EXCLUDED.definition,
          synonyms = EXCLUDED.synonyms,
          abbreviations = EXCLUDED.abbreviations,
          lifecycle_status = EXCLUDED.lifecycle_status,
          source_context_id = COALESCE(EXCLUDED.source_context_id, public.quantyx_glossary_terms.source_context_id),
          updated_at = now()
    """
    updated = 0
    for entry in entries:
        term = str(entry.get("term") or "").strip()
        normalized = _normalize_term(entry.get("normalized_term") or term)
        if not term or not normalized:
            continue
        execute_non_query(
            settings,
            sql,
            [
                f"{tenant_id}__{domain_id}__{normalized.replace(' ', '_')}",
                tenant_id,
                domain_id,
                term,
                normalized,
                str(entry.get("definition") or "").strip() or None,
                Json([str(item).strip() for item in (entry.get("synonyms") or []) if str(item).strip()], dumps=json.dumps),
                Json([str(item).strip() for item in (entry.get("abbreviations") or []) if str(item).strip()], dumps=json.dumps),
                lifecycle_status,
                source_context_id,
            ],
        )
        updated += 1
    return updated


def _build_synonym_map(glossary: list[dict[str, Any]]) -> dict[str, list[str]]:
    mapping: dict[str, list[str]] = {}
    for entry in glossary:
        normalized = (entry.get("normalized_term") or "").strip().lower()
        if not normalized:
            continue
        synonyms = entry.get("synonyms") or []
        abbreviations = entry.get("abbreviations") or []
        terms = []
        if entry.get("term"):
            terms.append(entry["term"])
        if isinstance(synonyms, list):
            terms.extend(synonyms)
        if isinstance(abbreviations, list):
            terms.extend(abbreviations)
        mapping[normalized] = list({t for t in terms if t})
    return mapping


def enrich_ontology_with_glossary(
    ontology: dict[str, Any],
    glossary: list[dict[str, Any]],
) -> dict[str, Any]:
    if not glossary:
        return ontology
    enriched = deepcopy(ontology)
    entity_types = enriched.get("entity_types", {})
    synonym_map = _build_synonym_map(glossary)

    for entity_id, body in entity_types.items():
        examples = body.get("examples", [])
        expanded = set(examples)
        for example in examples:
            normalized = str(example).strip().lower()
            expanded.update(synonym_map.get(normalized, []))
        body["examples"] = list(expanded)
        entity_types[entity_id] = body

    enriched["entity_types"] = entity_types
    return enriched
