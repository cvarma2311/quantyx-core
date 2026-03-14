from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text()) or {}


def _normalize_table_name(table: str) -> str:
    return str(table or "").split(".")[-1].strip()


def _edge_join_sql(alias_left: str, alias_right: str, edge: dict[str, Any]) -> str:
    left_key = str(edge.get("left_key") or "").strip()
    right_key = str(edge.get("right_key") or "").strip()
    if not left_key or not right_key:
        raise ValueError("Join keys are required for multi-table queries")
    return f'{alias_left}."{left_key}" = {alias_right}."{right_key}"'


def _yaml_edge(left: str, right: str, join_type: str, condition: str) -> dict[str, Any]:
    return {
        "left": left,
        "right": right,
        "join_type": join_type,
        "condition": condition,
        "is_yaml": True,
    }


def build_join_from(
    tables: list[str],
    schema: str,
    joins_path: str = "contracts/joins.yml",
    joins: list[dict[str, Any]] | None = None,
) -> tuple[str, dict[str, str]]:
    """
    Build a FROM clause for a set of tables using join definitions.
    Returns (from_sql, alias_map).
    """
    if len(tables) < 2:
        raise ValueError("Join graph requires at least two tables")

    join_defs = _load_yaml(Path(joins_path)).get("joins", [])
    normalized = [_normalize_table_name(table) for table in tables]
    table_set = {table for table in normalized if table}

    registry_edges = joins or []
    graph: dict[str, list[tuple[str, dict[str, Any], bool]]] = {}

    def _add_edge(left: str, right: str, edge: dict[str, Any], forward: bool) -> None:
        graph.setdefault(left, []).append((right, edge, forward))

    for join in join_defs:
        left = _normalize_table_name(str(join.get("left") or ""))
        right = _normalize_table_name(str(join.get("right") or ""))
        if not left or not right:
            continue
        edge = _yaml_edge(left, right, str(join.get("join_type", "JOIN")), str(join.get("condition") or "").strip())
        _add_edge(left, right, edge, True)
        _add_edge(right, left, edge, False)

    for join in registry_edges:
        left = _normalize_table_name(str(join.get("left_table") or join.get("left") or ""))
        right = _normalize_table_name(str(join.get("right_table") or join.get("right") or ""))
        if not left or not right:
            continue
        edge = {
            "left": left,
            "right": right,
            "join_type": str(join.get("join_type") or "LEFT JOIN"),
            "left_key": join.get("left_key"),
            "right_key": join.get("right_key"),
            "metadata": join,
            "is_yaml": False,
        }
        _add_edge(left, right, edge, True)
        _add_edge(right, left, edge, False)

    root = normalized[0]
    if not root:
        raise ValueError("Join graph requires valid table names")

    aliases = "abcdefghijklmnopqrstuvwxyz"
    alias_map: dict[str, str] = {}
    visited = {root}
    alias_map[root] = aliases[0]
    alias_map[f"{schema}.{root}"] = aliases[0]
    from_sql = f"FROM {schema}.{root} {aliases[0]}"

    pending = [root]
    edges_used: list[tuple[str, str, dict[str, Any], bool]] = []
    while pending:
        current = pending.pop(0)
        for neighbor, edge, forward in graph.get(current, []):
            if neighbor not in table_set or neighbor in visited:
                continue
            visited.add(neighbor)
            pending.append(neighbor)
            edges_used.append((current, neighbor, edge, forward))

    if visited != table_set:
        missing = sorted(table_set - visited)
        raise ValueError(f"No join definition found for requested tables: {missing}")

    for idx, (parent, child, edge, forward) in enumerate(edges_used, start=1):
        alias = aliases[idx]
        alias_map[child] = alias
        alias_map[f"{schema}.{child}"] = alias
        join_type = str(edge.get("join_type") or "LEFT JOIN")
        if edge.get("is_yaml"):
            condition = str(edge.get("condition") or "").strip()
            if not condition:
                raise ValueError("Join condition is required for multi-table queries")
            parent_alias = alias_map[parent]
            child_alias = alias
            condition = condition.replace(f"{schema}.{parent}.", f"{parent_alias}.")
            condition = condition.replace(f"{schema}.{child}.", f"{child_alias}.")
            condition = condition.replace(f"{parent}.", f"{parent_alias}.")
            condition = condition.replace(f"{child}.", f"{child_alias}.")
        else:
            parent_alias = alias_map[parent]
            child_alias = alias
            if forward:
                condition = _edge_join_sql(parent_alias, child_alias, edge)
            else:
                flipped = {
                    "left_key": edge.get("right_key"),
                    "right_key": edge.get("left_key"),
                }
                condition = _edge_join_sql(parent_alias, child_alias, flipped)
        from_sql += f" {join_type} {schema}.{child} {alias} ON {condition}"

    return from_sql, alias_map
