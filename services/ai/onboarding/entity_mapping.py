from __future__ import annotations

from typing import Any

from services.ai.glossary import enrich_ontology_with_glossary


def map_entities(
    tables: list[dict[str, Any]],
    ontology: dict[str, Any],
    glossary: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    if glossary:
        ontology = enrich_ontology_with_glossary(ontology, glossary)
    entity_types = ontology.get("entity_types", {}) if ontology else {}
    candidates = []
    for table in tables:
        for col in table["columns"]:
            name = col["name"].lower()
            best = None
            confidence = 0.0
            for entity_id, body in entity_types.items():
                examples = [e.lower() for e in body.get("examples", [])]
                if name in examples:
                    best = entity_id
                    confidence = 0.9
                    break
                if any(example in name for example in examples):
                    best = entity_id
                    confidence = 0.7
                    break
            if best:
                candidates.append(
                    {
                        "table": table["table"],
                        "column": col["name"],
                        "mapped_entity_type": best,
                        "confidence": confidence,
                    }
                )
    return candidates
