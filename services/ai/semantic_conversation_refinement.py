from __future__ import annotations

import logging
import re
from typing import Any

from services.ai.config import Settings
from services.ai.domain_refinement_extractor import process_refinement_input
from services.ai.domain_refinement_store import create_refinement_input, get_refinement_input
from services.ai.domain_semantic_state_builder import rebuild_semantic_state
from services.ai.semantic_propagation_store import enqueue_semantic_propagation_for_artifacts

logger = logging.getLogger(__name__)

_CORRECTION_MARKERS = (
    "actually",
    "correction",
    "correct this",
    "wrong",
    "incorrect",
    "should be",
    "should use",
    "should mean",
    "means",
    "represents",
    "instead of",
    "do not",
    "don't",
    "never",
    "exclude",
    "ignore",
    "filter out",
    "treat",
    "prefer",
)


def infer_refinement_kind(text: str | None = None, payload: dict[str, Any] | None = None) -> str:
    if isinstance(payload, dict) and payload:
        if payload.get("question_id") or payload.get("answer_text") or payload.get("maps_to"):
            return "context_question_answer"
        if payload.get("levels") or payload.get("hierarchy_name"):
            return "hierarchy"
        if payload.get("metric_name") or payload.get("metric_id") or payload.get("formula"):
            return "metric_refinement"
        if payload.get("left_table") or payload.get("right_table") or payload.get("rule_type") in {
            "join_restriction",
            "reference_table_usage",
            "table_restriction",
            "exclusion_filter",
        }:
            return "join_rule"
        if payload.get("column") or payload.get("business_label"):
            return "column_annotation"
        if payload.get("rule") or payload.get("applies_to"):
            return "interpretation_rule"
        if payload.get("guidance") or payload.get("chart_intent") or payload.get("preferred_time_grain"):
            return "chart_guidance"

    cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
    lowered = cleaned.lower()
    if not lowered:
        return "business_context"
    if any(token in lowered for token in ("hierarchy", "drill path", "roll up", "rollup", "grain path")):
        return "hierarchy"
    if any(token in lowered for token in ("do not join", "don't join", "never join", "join ", "joined", "exclude", "filter out", "do not include")):
        return "join_rule"
    if any(token in lowered for token in ("metric", "kpi", "formula", "growth rate", "month over month", "prior month", "previous month", "year over year")):
        return "metric_refinement"
    if any(token in lowered for token in ("column", "field", "means", "represents", "label", "show as", "shown as", "business identifier")):
        return "column_annotation"
    if any(token in lowered for token in ("anomaly", "correlation", "significant", "alert", "expected", "ignore", "shutdown")):
        return "interpretation_rule"
    if any(token in lowered for token in ("chart", "dashboard", "trend", "forecast", "ranking", "visual")):
        return "chart_guidance"
    return "business_context"


def infer_conversation_refinement_kind(text: str | None) -> str | None:
    cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(cleaned) < 12:
        return None
    lowered = cleaned.lower()
    if not any(marker in lowered for marker in _CORRECTION_MARKERS):
        return None

    return infer_refinement_kind(cleaned)


def maybe_writeback_conversation_refinement(
    settings: Settings,
    *,
    tenant_id: str,
    domain_id: str,
    source_text: str,
    connection_id: str | None = None,
    database_name: str | None = None,
    schema_name: str | None = None,
    source_run_id: str | None = None,
    conversation_id: str | None = None,
    submitted_by: str | None = "system:conversation_auto_writeback",
) -> dict[str, Any] | None:
    refinement_kind = infer_conversation_refinement_kind(source_text)
    if not refinement_kind:
        return None

    refinement_input_id = create_refinement_input(
        settings,
        tenant_id=tenant_id,
        domain_id=domain_id,
        connection_id=connection_id,
        database_name=database_name,
        schema_name=schema_name,
        source_run_id=source_run_id,
        source_type="conversation",
        refinement_kind=refinement_kind,
        source_text=source_text,
        source_payload_json={},
        source_context_id=conversation_id,
        conversation_id=conversation_id,
        submitted_by=submitted_by,
    )
    row = get_refinement_input(settings, refinement_input_id)
    if not row:
        return {
            "refinement_input_id": refinement_input_id,
            "refinement_kind": refinement_kind,
            "status": "created",
            "artifact_count": 0,
        }

    artifacts = process_refinement_input(
        settings,
        row,
        auto_approve=True,
        approved_by=submitted_by or "system:conversation_auto_writeback",
    )
    semantic_state_id = None
    valid_artifacts = [
        artifact
        for artifact in artifacts
        if artifact.get("validation_status") == "valid" and artifact.get("approval_status") in {"approved", "auto_approved"}
    ]
    if valid_artifacts:
        state_result = rebuild_semantic_state(
            settings,
            tenant_id=tenant_id,
            domain_id=domain_id,
            connection_id=connection_id,
            database_name=database_name,
            schema_name=schema_name,
            trigger_type="conversation_auto_writeback",
        )
        semantic_state_id = state_result.get("semantic_state_id")
        enqueue_semantic_propagation_for_artifacts(
            settings,
            tenant_id=tenant_id,
            domain_id=domain_id,
            connection_id=connection_id,
            database_name=database_name,
            schema_name=schema_name,
            artifacts=valid_artifacts,
            trigger_type="conversation_auto_writeback",
            semantic_state_id=semantic_state_id,
        )

    logger.info(
        "semantic_conversation.writeback | tenant=%s domain=%s conversation_id=%s kind=%s artifacts=%s semantic_state_id=%s",
        tenant_id,
        domain_id,
        conversation_id,
        refinement_kind,
        len(valid_artifacts),
        semantic_state_id,
    )
    return {
        "refinement_input_id": refinement_input_id,
        "refinement_kind": refinement_kind,
        "status": "processed",
        "artifact_count": len(artifacts),
        "valid_artifact_count": len(valid_artifacts),
        "semantic_state_id": semantic_state_id,
    }
