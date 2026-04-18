from __future__ import annotations

import json
from typing import Any

from services.ai.semantic_propagation_store import plan_semantic_propagation_scope


_STATE_BUCKET_BY_ARTIFACT_TYPE = {
    "business_context": "business_context",
    "hierarchy_override": "hierarchies",
    "column_annotation": "column_annotations",
    "metric_refinement": "metric_overrides",
    "join_rule": "join_rules",
    "chart_guidance": "chart_guidance",
    "interpretation_rule": "interpretation_rules",
    "context_question_answer": "context_question_answers",
}


def _normalize(value: Any) -> str:
    return str(value or "").strip().lower()


def _artifact_payload(artifact: dict[str, Any]) -> dict[str, Any]:
    payload = artifact.get("artifact_json") or {}
    return payload if isinstance(payload, dict) else {}


def semantic_artifact_target(artifact: dict[str, Any]) -> str:
    artifact_type = str(artifact.get("artifact_type") or "").strip()
    payload = _artifact_payload(artifact)
    if artifact_type == "metric_refinement":
        return str(payload.get("metric_name") or payload.get("metric_id") or "metric_refinement")
    if artifact_type == "column_annotation":
        table = payload.get("table")
        column = payload.get("column")
        return ".".join(str(part) for part in (table, column) if part) or "column_annotation"
    if artifact_type == "hierarchy_override":
        return str(payload.get("name") or payload.get("hierarchy_name") or " > ".join(payload.get("levels") or []) or "hierarchy")
    if artifact_type == "join_rule":
        left = payload.get("left_table")
        right = payload.get("right_table")
        table = payload.get("table")
        if left and right:
            return f"{left}<->{right}"
        return str(table or payload.get("rule_type") or "join_rule")
    if artifact_type == "interpretation_rule":
        return str(payload.get("applies_to") or payload.get("rule") or payload.get("text") or "interpretation_rule")
    if artifact_type == "chart_guidance":
        return str(payload.get("chart_intent") or payload.get("preferred_time_grain") or payload.get("guidance") or "chart_guidance")
    if artifact_type == "context_question_answer":
        return str(payload.get("question_id") or "context_question_answer")
    return str(payload.get("text") or artifact_type or "artifact")


def semantic_artifact_summary(artifact: dict[str, Any]) -> str:
    artifact_type = str(artifact.get("artifact_type") or "").strip()
    payload = _artifact_payload(artifact)
    if artifact_type == "metric_refinement":
        metric = payload.get("metric_name") or payload.get("metric_id") or "metric"
        formula = payload.get("formula") or payload.get("description") or payload.get("source_text")
        return f"Refines {metric}" + (f": {formula}" if formula else "")
    if artifact_type == "column_annotation":
        label = payload.get("business_label") or payload.get("label") or payload.get("description")
        return f"Annotates {semantic_artifact_target(artifact)}" + (f" as {label}" if label else "")
    if artifact_type == "hierarchy_override":
        levels = payload.get("levels") or []
        return "Defines hierarchy" + (f" {' > '.join(str(level) for level in levels)}" if levels else "")
    if artifact_type == "join_rule":
        return str(payload.get("source_text") or payload.get("description") or f"Applies join rule {semantic_artifact_target(artifact)}")
    if artifact_type == "chart_guidance":
        return str(payload.get("guidance") or f"Applies chart guidance {semantic_artifact_target(artifact)}")
    if artifact_type == "interpretation_rule":
        return str(payload.get("rule") or payload.get("text") or f"Applies interpretation rule {semantic_artifact_target(artifact)}")
    return str(payload.get("source_text") or payload.get("text") or f"Applies {artifact_type}")


def _state_artifacts_for_type(active_state: dict[str, Any] | None, artifact_type: str) -> list[dict[str, Any]]:
    if not active_state:
        return []
    refinements = active_state.get("refinements") or {}
    bucket = refinements.get(_STATE_BUCKET_BY_ARTIFACT_TYPE.get(artifact_type, artifact_type)) or []
    return [item for item in bucket if isinstance(item, dict)]


def _json_equal(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return json.dumps(left or {}, sort_keys=True, default=str) == json.dumps(right or {}, sort_keys=True, default=str)


def _matching_active_artifact(active_state: dict[str, Any] | None, artifact: dict[str, Any]) -> dict[str, Any] | None:
    target = _normalize(semantic_artifact_target(artifact))
    artifact_type = str(artifact.get("artifact_type") or "").strip()
    for existing in _state_artifacts_for_type(active_state, artifact_type):
        if _normalize(semantic_artifact_target(existing)) == target:
            return existing
    return None


def build_semantic_impact_preview(
    artifacts: list[dict[str, Any]],
    *,
    active_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_artifacts = [artifact for artifact in artifacts if isinstance(artifact, dict) and artifact.get("artifact_type")]
    affected_scope = plan_semantic_propagation_scope(normalized_artifacts)
    diff_summary: list[dict[str, Any]] = []
    for artifact in normalized_artifacts:
        artifact_type = str(artifact.get("artifact_type") or "")
        payload = _artifact_payload(artifact)
        existing = _matching_active_artifact(active_state, artifact)
        if existing and _json_equal(_artifact_payload(existing), payload):
            change_type = "already_present"
        elif existing:
            change_type = "update_existing"
        else:
            change_type = "add_new"
        diff_summary.append(
            {
                "artifact_id": artifact.get("artifact_id"),
                "artifact_type": artifact_type,
                "change_type": change_type,
                "target": semantic_artifact_target(artifact),
                "summary": semantic_artifact_summary(artifact),
                "current_artifact_id": (existing or {}).get("artifact_id"),
                "artifact_json": payload,
            }
        )
    return {
        "impact_level": affected_scope.get("impact_level") or "none",
        "diff_summary": diff_summary,
        "affected_scope": affected_scope,
    }
