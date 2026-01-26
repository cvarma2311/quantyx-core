from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def load_ontology(pack_path: str) -> dict[str, Any]:
    path = Path(pack_path) / "ontology.yml"
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text())
