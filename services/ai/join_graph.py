from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text()) or {}


def build_join_from(tables: list[str], schema: str, joins_path: str = "contracts/joins.yml") -> tuple[str, dict[str, str]]:
    """
    Build a FROM clause for a set of tables using join definitions.
    Returns (from_sql, alias_map).
    """
    if len(tables) < 2:
        raise ValueError("Join graph requires at least two tables")

    join_defs = _load_yaml(Path(joins_path)).get("joins", [])
    normalized = [table.split(".")[-1] for table in tables]
    table_set = set(normalized)

    for join in join_defs:
        left = join.get("left")
        right = join.get("right")
        if not left or not right:
            continue
        if table_set == {left, right}:
            left_full = f"{schema}.{left}"
            right_full = f"{schema}.{right}"
            join_type = join.get("join_type", "JOIN")
            condition = join.get("condition", "")
            if not condition:
                raise ValueError("Join condition is required for multi-table queries")
            alias_map = {
                left: "a",
                right: "b",
                left_full: "a",
                right_full: "b",
            }
            from_sql = f"FROM {left_full} a {join_type} {right_full} b ON {condition}"
            return from_sql, alias_map

    raise ValueError("No join definition found for requested tables")
