from __future__ import annotations

from typing import Any

from services.ai.config import Settings
from services.ai.dbt_manifest import load_latest_manifest


def load_manifest_models(
    settings: Settings,
    domain_id: str | None = None,
    tenant_id: str | None = None,
) -> list[dict[str, Any]]:
    payload = load_latest_manifest(settings, domain_id=domain_id, tenant_id=tenant_id)
    if not payload:
        return []

    nodes = payload.get("nodes", {})
    models = []
    for node in nodes.values():
        if node.get("resource_type") != "model":
            continue
        models.append(
            {
                "name": node.get("name"),
                "database": node.get("database"),
                "schema": node.get("schema"),
                "description": node.get("description"),
                "columns": [
                    {"name": col_name, "description": col.get("description")}
                    for col_name, col in (node.get("columns") or {}).items()
                ],
            }
        )

    return sorted(models, key=lambda m: (m.get("schema") or "", m.get("name") or ""))
