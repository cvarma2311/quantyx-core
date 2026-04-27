from __future__ import annotations

from typing import Any, Callable


def build_run_lineage_graph_payload(
    *,
    run_id: str | None,
    edges: list[dict[str, Any]],
    fetch_run: Callable[[str], dict[str, Any] | None],
    tenant_id: str | None = None,
    domain_id: str | None = None,
) -> dict[str, Any]:
    run_ids: set[str] = set()
    trend_scope_keys: set[str] = set()
    for edge in edges:
        parent = str(edge.get("parent_run_id") or "").strip()
        child = str(edge.get("child_run_id") or "").strip()
        if parent:
            run_ids.add(parent)
        if child:
            run_ids.add(child)
        scope_key = str(edge.get("trend_scope_key") or "").strip()
        if scope_key:
            trend_scope_keys.add(scope_key)
    if run_id:
        run_ids.add(run_id)

    nodes: list[dict[str, Any]] = []
    parent_ids = {
        str(edge.get("parent_run_id") or "").strip()
        for edge in edges
        if str(edge.get("parent_run_id") or "").strip()
    }
    child_ids = {
        str(edge.get("child_run_id") or "").strip()
        for edge in edges
        if str(edge.get("child_run_id") or "").strip()
    }
    for node_run_id in sorted(run_ids):
        row = fetch_run(node_run_id) or {"run_id": node_run_id}
        node = {
            "run_id": node_run_id,
            "display_name": row.get("display_name"),
            "status": row.get("status"),
            "version_no": row.get("version_no"),
            "trend_mode": row.get("trend_mode"),
            "trend_scope_key": row.get("trend_scope_key"),
            "trend_scope_label": row.get("trend_scope_label"),
            "parent_run_id": row.get("parent_run_id"),
            "rerun_root_run_id": row.get("rerun_root_run_id") or node_run_id,
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
            "is_focus_run": bool(run_id and node_run_id == run_id),
            "is_root_run": node_run_id in parent_ids and node_run_id not in child_ids or not row.get("parent_run_id"),
        }
        nodes.append(node)
        scope_key = str(row.get("trend_scope_key") or "").strip()
        if scope_key:
            trend_scope_keys.add(scope_key)

    root_candidates = [node["run_id"] for node in nodes if node.get("is_root_run")]
    root_run_id = root_candidates[0] if root_candidates else (run_id or (nodes[0]["run_id"] if nodes else None))
    return {
        **({"run_id": run_id} if run_id else {"tenant_id": tenant_id, "domain_id": domain_id}),
        "graph": {
            "root_run_id": root_run_id,
            "focus_run_id": run_id,
            "node_count": len(nodes),
            "edge_count": len(edges),
            "trend_scope_keys": sorted(trend_scope_keys),
        },
        "nodes": nodes,
        "edges": edges,
    }
