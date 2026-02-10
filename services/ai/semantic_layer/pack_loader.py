from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


PACK_FILES = {
    "pack": "pack.yml",
    "ontology": "ontology.yml",
    "datasets": "datasets.yml",
    "metric_templates": "metric_templates.yml",
    "policies": "policies.yml",
}


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text()) or {}


def load_pack(pack_path: str) -> dict[str, Any]:
    base = Path(pack_path)
    return {
        name: _load_yaml(base / filename)
        for name, filename in PACK_FILES.items()
    }


def list_packs(root: str = "packs") -> list[str]:
    base = Path(root)
    if not base.exists():
        return []
    return sorted([p.name for p in base.iterdir() if p.is_dir()])


def list_pack_metadata(root: str = "packs") -> list[dict[str, Any]]:
    base = Path(root)
    if not base.exists():
        return []
    packs = []
    for pack_dir in sorted([p for p in base.iterdir() if p.is_dir()], key=lambda p: p.name):
        metadata = _load_yaml(pack_dir / "pack.yml")
        packs.append(
            {
                "industry": pack_dir.name,
                "version": metadata.get("version"),
                "release_date": metadata.get("release_date"),
                "notes": metadata.get("notes"),
            }
        )
    return packs
