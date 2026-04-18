from __future__ import annotations

from typing import Any

from services.ai.data_quality_enrichment import canonical_column_alias, canonical_column_aliases
from services.ai.data_quality_store import (
    get_latest_quality_enrichment_proposal_for_opportunity,
    list_quality_enrichment_opportunities,
)


def _question_status(opportunity_status: str | None, proposal: dict[str, Any] | None) -> str:
    status = str(opportunity_status or "").strip().lower()
    if status == "proposal_generated" or proposal:
        return "proposal_ready"
    if status in {"deferred_by_user", "deferred"}:
        return "deferred"
    if status in {"rejected_by_user", "rejected"}:
        return "rejected"
    if status in {"approved_for_staging"}:
        return "completed"
    return "pending_answer"


def _available_actions(question_status: str) -> list[str]:
    if question_status == "pending_answer":
        return ["approve", "defer", "reject"]
    if question_status == "proposal_ready":
        return ["review_proposal", "defer", "reject"]
    if question_status in {"deferred", "rejected"}:
        return ["reopen", "approve"]
    return []


def _question_payload(
    *,
    tenant_id: str,
    domain_id: str,
    run_id: str | None,
    opportunity: dict[str, Any],
    proposal: dict[str, Any] | None = None,
) -> dict[str, Any]:
    target_column = opportunity.get("target_column")
    source_columns = opportunity.get("source_columns_json") or []
    question_status = _question_status(opportunity.get("status"), proposal)
    return {
        "question_id": opportunity.get("opportunity_id"),
        "opportunity_id": opportunity.get("opportunity_id"),
        "run_id": opportunity.get("run_id") or run_id,
        "quality_run_id": opportunity.get("quality_run_id"),
        "table_name": opportunity.get("table_name"),
        "target_column": target_column,
        "target_column_alias": opportunity.get("target_column_alias") or canonical_column_alias(target_column),
        "source_columns_json": source_columns,
        "source_column_aliases_json": opportunity.get("source_column_aliases_json") or canonical_column_aliases(source_columns),
        "question": opportunity.get("question"),
        "missing_count": opportunity.get("missing_count"),
        "candidate_method": opportunity.get("candidate_method"),
        "confidence": opportunity.get("confidence"),
        "status": question_status,
        "available_actions": _available_actions(question_status),
        "proposal_id": (proposal or {}).get("proposal_id"),
        "proposal_status": (proposal or {}).get("status"),
        "proposal_summary": {
            "matched_count": (proposal or {}).get("matched_count"),
            "unmatched_count": (proposal or {}).get("unmatched_count"),
        }
        if proposal
        else None,
        "artifact_links": {
            "proposal": f"/data-quality/enrichment/proposals/{proposal.get('proposal_id')}"
            if proposal and proposal.get("proposal_id")
            else None,
            "answer": f"/data-quality/enrichment/questions/{opportunity.get('opportunity_id')}/answer",
        },
    }


def build_enrichment_question_queue(
    settings,
    *,
    tenant_id: str,
    domain_id: str,
    run_id: str | None = None,
    status: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    opportunities = list_quality_enrichment_opportunities(
        settings,
        tenant_id=tenant_id,
        domain_id=domain_id,
        run_id=run_id,
        status=status,
        limit=limit,
    )
    questions: list[dict[str, Any]] = []
    counts = {
        "pending_answer_count": 0,
        "proposal_ready_count": 0,
        "deferred_count": 0,
        "rejected_count": 0,
    }
    for opportunity in opportunities:
        proposal = get_latest_quality_enrichment_proposal_for_opportunity(
            settings,
            str(opportunity.get("opportunity_id") or ""),
            tenant_id=tenant_id,
        )
        payload = _question_payload(
            tenant_id=tenant_id,
            domain_id=domain_id,
            run_id=run_id,
            opportunity=opportunity,
            proposal=proposal,
        )
        questions.append(payload)
        counts_key = f"{payload['status']}_count"
        if counts_key in counts:
            counts[counts_key] += 1
    questions.sort(
        key=lambda item: (
            0 if item.get("status") == "pending_answer" else 1,
            -(float(item.get("missing_count") or 0.0)),
            -(float(item.get("confidence") or 0.0)),
            str(item.get("table_name") or ""),
            str(item.get("target_column_alias") or ""),
        )
    )
    return {
        "tenant_id": tenant_id,
        "domain_id": domain_id,
        "run_id": run_id,
        "summary": {
            "question_count": len(questions),
            **counts,
        },
        "questions": questions,
    }
