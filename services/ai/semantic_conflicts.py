from __future__ import annotations

import json
import re
from collections import defaultdict
from typing import Any


def _normalize(value: Any) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", str(value or "").strip().lower()).strip("_")


def _payload(artifact: dict[str, Any]) -> dict[str, Any]:
    value = artifact.get("artifact_json") or {}
    return value if isinstance(value, dict) else {}


def _fingerprint(value: dict[str, Any]) -> str:
    return json.dumps(value or {}, sort_keys=True, default=str)


def semantic_conflict_key(artifact: dict[str, Any]) -> str | None:
    artifact_type = str(artifact.get("artifact_type") or "").strip()
    payload = _payload(artifact)
    if artifact_type == "metric_refinement":
        metric = _normalize(payload.get("metric_name") or payload.get("metric_id"))
        return f"metric_refinement:{metric}" if metric else None
    if artifact_type == "column_annotation":
        table = _normalize(payload.get("table"))
        column = _normalize(payload.get("column"))
        if not column:
            return None
        return f"column_annotation:{table}.{column}" if table else f"column_annotation:{column}"
    if artifact_type == "hierarchy_override":
        name = _normalize(payload.get("hierarchy_group") or payload.get("name") or payload.get("hierarchy_name") or "default")
        return f"hierarchy_override:{name}"
    if artifact_type == "join_rule":
        left = _normalize(payload.get("left_table"))
        right = _normalize(payload.get("right_table"))
        table = _normalize(payload.get("table"))
        rule_type = _normalize(payload.get("rule_type"))
        if left and right:
            ordered = sorted([left, right])
            return f"join_rule:{rule_type}:{ordered[0]}:{ordered[1]}"
        if table:
            return f"join_rule:{rule_type}:{table}"
        return f"join_rule:{rule_type}" if rule_type else None
    return None


def detect_semantic_conflicts(artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for artifact in artifacts:
        key = semantic_conflict_key(artifact)
        if key:
            grouped[key].append(artifact)

    conflicts: list[dict[str, Any]] = []
    for key, items in grouped.items():
        if len(items) < 2:
            continue
        fingerprints = {_fingerprint(_payload(item)) for item in items}
        if len(fingerprints) <= 1:
            continue
        artifact_type = str(items[0].get("artifact_type") or "")
        conflicts.append(
            {
                "conflict_key": key,
                "artifact_type": artifact_type,
                "severity": "high" if artifact_type in {"metric_refinement", "join_rule"} else "medium",
                "artifact_count": len(items),
                "artifact_ids": [item.get("artifact_id") for item in items if item.get("artifact_id")],
                "approval_statuses": sorted({str(item.get("approval_status") or "pending") for item in items}),
                "summary": f"Conflicting {artifact_type} artifacts for {key}",
                "artifacts": items,
            }
        )
    return conflicts
