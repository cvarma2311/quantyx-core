from __future__ import annotations

from copy import deepcopy
from typing import Any

from services.ai.config import Settings
from services.ai.db import run_query


def fetch_glossary_terms(settings: Settings, tenant_id: str, domain_id: str) -> list[dict[str, Any]]:
    sql = """
        SELECT term,
               normalized_term,
               definition,
               synonyms,
               abbreviations
          FROM public.quantyx_glossary_terms
         WHERE tenant_id = %s
           AND domain_id = %s
    """
    return run_query(settings, sql, [tenant_id, domain_id])


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
