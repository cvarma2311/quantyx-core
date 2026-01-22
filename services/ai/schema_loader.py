from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_manifest_models(path: str) -> list[dict[str, Any]]:
    manifest_path = Path(path)
    if not manifest_path.exists():
        return []

    payload = json.loads(manifest_path.read_text())
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
