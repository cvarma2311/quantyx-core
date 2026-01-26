from __future__ import annotations

from typing import Any

from services.ai.semantic_layer.overrides_loader import load_entity_overrides, load_hierarchy_overrides
from services.ai.config import Settings


def merge_entities(base: list[dict[str, Any]], overrides: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged = {item["entity_id"]: item for item in base}
    for override in overrides:
        entity_id = override["entity_id"]
        current = merged.get(entity_id, {"entity_id": entity_id})
        current.update({k: v for k, v in override.items() if v is not None})
        merged[entity_id] = current
    return list(merged.values())


def merge_hierarchies(base: list[dict[str, Any]], overrides: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged = {item["name"]: item for item in base}
    for override in overrides:
        name = override["hierarchy_name"]
        merged[name] = {
            "name": name,
            "levels": override.get("levels", []),
            "description": override.get("description"),
        }
    return list(merged.values())


def load_overrides(settings: Settings, tenant_id: str, domain_id: str) -> tuple[list[dict], list[dict]]:
    entity_overrides = load_entity_overrides(settings, tenant_id, domain_id)
    hierarchy_overrides = load_hierarchy_overrides(settings, tenant_id, domain_id)
    return entity_overrides, hierarchy_overrides
