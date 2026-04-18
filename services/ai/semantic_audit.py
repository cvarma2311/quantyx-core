from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def _ts(value: Any) -> str | None:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if value is None:
        return None
    return str(value)


def _artifact_ids(artifacts: list[dict[str, Any]]) -> set[str]:
    return {str(item.get("artifact_id")) for item in artifacts if item.get("artifact_id")}


def _job_matches_artifacts(job: dict[str, Any], artifact_ids: set[str]) -> bool:
    scope = job.get("affected_scope_json") or {}
    if not isinstance(scope, dict):
        return False
    job_artifact_ids = {str(item) for item in scope.get("artifact_ids") or [] if str(item or "").strip()}
    return bool(artifact_ids & job_artifact_ids)


def build_semantic_audit(
    *,
    refinements: list[dict[str, Any]],
    artifacts_by_refinement: dict[str, list[dict[str, Any]]],
    semantic_states: list[dict[str, Any]],
    propagation_jobs: list[dict[str, Any]],
) -> dict[str, Any]:
    refinement_items: list[dict[str, Any]] = []
    timeline: list[dict[str, Any]] = []

    for refinement in refinements:
        refinement_id = str(refinement.get("refinement_input_id") or "")
        artifacts = artifacts_by_refinement.get(refinement_id) or []
        artifact_ids = _artifact_ids(artifacts)
        related_jobs = [job for job in propagation_jobs if _job_matches_artifacts(job, artifact_ids)]
        item = {
            "event_type": "refinement",
            "event_id": refinement_id,
            "created_at": _ts(refinement.get("created_at")),
            "tenant_id": refinement.get("tenant_id"),
            "domain_id": refinement.get("domain_id"),
            "source_type": refinement.get("source_type"),
            "refinement_kind": refinement.get("refinement_kind"),
            "status": refinement.get("status"),
            "submitted_by": refinement.get("submitted_by"),
            "conversation_id": refinement.get("conversation_id"),
            "source_run_id": refinement.get("source_run_id"),
            "source_text": refinement.get("source_text"),
            "artifact_count": len(artifacts),
            "artifacts": [_json_safe(artifact) for artifact in artifacts],
            "propagation_jobs": [_json_safe(job) for job in related_jobs],
        }
        refinement_items.append(item)
        timeline.append(
            {
                "event_type": "refinement",
                "event_id": refinement_id,
                "created_at": item["created_at"],
                "summary": f"{refinement.get('refinement_kind') or 'semantic'} refinement {refinement.get('status') or ''}".strip(),
                "details": item,
            }
        )

    state_items: list[dict[str, Any]] = []
    for state in semantic_states:
        item = {
            "event_type": "semantic_state",
            "event_id": state.get("semantic_state_id"),
            "created_at": _ts(state.get("created_at")),
            "tenant_id": state.get("tenant_id"),
            "domain_id": state.get("domain_id"),
            "version_no": state.get("version_no"),
            "trigger_type": state.get("trigger_type"),
            "is_active": state.get("is_active"),
            "created_from_artifact_ids": state.get("created_from_artifact_ids") or [],
        }
        state_items.append(item)
        timeline.append(
            {
                "event_type": "semantic_state",
                "event_id": item["event_id"],
                "created_at": item["created_at"],
                "summary": f"Semantic state v{item.get('version_no')} created",
                "details": item,
            }
        )

    propagation_items: list[dict[str, Any]] = []
    for job in propagation_jobs:
        scope = job.get("affected_scope_json") or {}
        if not isinstance(scope, dict):
            scope = {}
        item = {
            "event_type": "propagation_job",
            "event_id": job.get("job_id"),
            "created_at": _ts(job.get("created_at")),
            "completed_at": _ts(job.get("completed_at")),
            "tenant_id": job.get("tenant_id"),
            "domain_id": job.get("domain_id"),
            "trigger_type": job.get("trigger_type"),
            "status": job.get("status"),
            "affected_scope_json": _json_safe(scope),
        }
        propagation_items.append(item)
        timeline.append(
            {
                "event_type": "propagation_job",
                "event_id": item["event_id"],
                "created_at": item["created_at"],
                "summary": f"Propagation job {item.get('status') or 'queued'}",
                "details": item,
            }
        )

    timeline.sort(key=lambda item: item.get("created_at") or "", reverse=True)
    return {
        "refinements": refinement_items,
        "semantic_states": state_items,
        "propagation_jobs": propagation_items,
        "timeline": timeline,
    }
