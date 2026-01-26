from __future__ import annotations

from typing import Any

from services.ai.semantic_layer.pack_loader import load_pack


def list_entities(pack_path: str) -> list[dict[str, Any]]:
    pack = load_pack(pack_path)
    ontology = pack.get("ontology", {})
    entities = []
    for entity_type, body in (ontology.get("entity_types") or {}).items():
        entities.append(
            {
                "entity_id": entity_type,
                "examples": body.get("examples", []),
                "description": body.get("description"),
                "join_key": body.get("join_key"),
            }
        )
    return entities


def list_hierarchies(pack_path: str) -> list[dict[str, Any]]:
    pack = load_pack(pack_path)
    ontology = pack.get("ontology", {})
    hierarchies = []
    for hierarchy in (ontology.get("hierarchies") or []):
        hierarchies.append(
            {
                "name": hierarchy.get("name"),
                "levels": hierarchy.get("levels", []),
                "description": hierarchy.get("description"),
            }
        )
    return hierarchies
