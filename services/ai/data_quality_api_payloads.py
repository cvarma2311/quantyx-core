from __future__ import annotations

from typing import Any


def build_data_quality_artifact_links(*, tenant_id: str, domain_id: str, run_id: str) -> dict[str, str]:
    return {
        "run_summary": f"/data-quality/runs/{run_id}",
        "dashboard": f"/data-quality/runs/{run_id}/dashboard",
        "excel_report": f"/data-quality/reports/{run_id}/excel?tenant_id={tenant_id}&domain_id={domain_id}",
        "stages": f"/data-quality/stages?tenant_id={tenant_id}&domain_id={domain_id}&run_id={run_id}",
        "joins": f"/data-quality/joins?tenant_id={tenant_id}&domain_id={domain_id}&run_id={run_id}",
        "rejected_records": f"/data-quality/rejected-records?tenant_id={tenant_id}&domain_id={domain_id}&run_id={run_id}",
        "final_dataset": f"/data-quality/final-dataset?tenant_id={tenant_id}&domain_id={domain_id}&run_id={run_id}",
        "final_dataset_rows": f"/data-quality/final-dataset/rows?tenant_id={tenant_id}&domain_id={domain_id}&run_id={run_id}",
        "lineage": f"/data-quality/lineage?tenant_id={tenant_id}&domain_id={domain_id}&run_id={run_id}",
        "lineage_base": f"/data-quality/lineage?tenant_id={tenant_id}&domain_id={domain_id}&run_id={run_id}",
        "tables": f"/data-quality/tables?tenant_id={tenant_id}&domain_id={domain_id}&run_id={run_id}",
        "rules": f"/data-quality/rules?tenant_id={tenant_id}&domain_id={domain_id}&run_id={run_id}",
        "rule_review_queue": f"/data-quality/rules/review-queue?tenant_id={tenant_id}&domain_id={domain_id}&run_id={run_id}",
        "resume_after_rule_review": f"/data-quality/runs/{run_id}/resume-after-rule-review",
        "duplicates": f"/data-quality/duplicates?tenant_id={tenant_id}&domain_id={domain_id}&run_id={run_id}",
        "remediation": f"/data-quality/remediation?tenant_id={tenant_id}&domain_id={domain_id}&run_id={run_id}",
        "enrichment_opportunities": f"/data-quality/enrichment/opportunities?tenant_id={tenant_id}&domain_id={domain_id}&run_id={run_id}",
        "enrichment_questions": f"/data-quality/enrichment/questions?tenant_id={tenant_id}&domain_id={domain_id}&run_id={run_id}",
    }


def build_data_quality_run_summary_payload(
    *,
    row: dict[str, Any],
    remediation_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    summary = dict(row.get("summary_json") or {})
    tenant_id = str(row.get("tenant_id") or "")
    domain_id = str(row.get("domain_id") or "data_quality_observability")
    run_id = str(row.get("run_id") or "")
    row_status = str(row.get("status") or "").strip().lower()
    if row_status in {"completed", "failed", "cancelled", "canceled"}:
        summary["workflow_status"] = row_status
    artifact_links = build_data_quality_artifact_links(
        tenant_id=tenant_id,
        domain_id=domain_id,
        run_id=run_id,
    )
    remediation_plan = remediation_plan or {"summary": {}, "actions": []}
    return {
        "quality_run_id": row.get("quality_run_id"),
        "run_id": row.get("run_id"),
        "tenant_id": row.get("tenant_id"),
        "domain_id": row.get("domain_id"),
        "connection_id": row.get("connection_id"),
        "database_name": row.get("database_name"),
        "schema_name": row.get("schema_name"),
        "status": row.get("status"),
        "overall_trust_score": row.get("overall_trust_score"),
        "critical_issue_count": summary.get("critical_issue_count", 0),
        "warning_issue_count": summary.get("warning_issue_count", 0),
        "dashboard_id": summary.get("dashboard_id"),
        "dashboard_title": summary.get("dashboard_title"),
        "dashboard_chart_count": summary.get("dashboard_chart_count"),
        "duplicate_candidate_count": summary.get("duplicate_candidate_count", 0),
        "exact_duplicate_candidate_count": summary.get("exact_duplicate_candidate_count", 0),
        "fuzzy_duplicate_candidate_count": summary.get("fuzzy_duplicate_candidate_count", 0),
        "active_rule_count": summary.get("active_rule_count", 0),
        "needs_review_rule_count": summary.get("needs_review_rule_count", 0),
        "unsupported_rule_count": summary.get("unsupported_rule_count", 0),
        "rejected_rule_count": summary.get("rejected_rule_count", 0),
        "rule_review_required": bool(summary.get("rule_review_required")),
        "review_queue_pending_count": summary.get("review_queue_pending_count", 0),
        "workflow_status": summary.get("workflow_status") or row.get("status"),
        "dataset_stage_count": summary.get("dataset_stage_count", 0),
        "join_stage_count": summary.get("join_stage_count", 0),
        "filter_stage_count": summary.get("filter_stage_count", 0),
        "total_rejected_row_count": summary.get("total_rejected_row_count", 0),
        "final_dataset_row_count": summary.get("final_dataset_row_count"),
        "final_dataset_readiness_status": summary.get("final_dataset_readiness_status"),
        "lineage_edge_count": summary.get("lineage_edge_count", 0),
        "stale_table_count": summary.get("stale_table_count", 0),
        "tables_without_freshness_column_count": summary.get("tables_without_freshness_column_count", 0),
        "stability_issue_count": summary.get("stability_issue_count", 0),
        "enrichment_opportunity_count": summary.get("enrichment_opportunity_count", 0),
        "external_lookup_opportunity_count": summary.get("external_lookup_opportunity_count", 0),
        "remediation_action_count": summary.get("remediation_action_count", 0),
        "critical_remediation_action_count": summary.get("critical_remediation_action_count", 0),
        "artifacts": artifact_links,
        "remediation_summary": remediation_plan.get("summary") or {},
        "recommended_actions": remediation_plan.get("actions") or [],
        "summary": summary,
        "created_at": row.get("created_at"),
        "completed_at": row.get("completed_at"),
    }


def _trim_rule_review_item(row: dict[str, Any]) -> dict[str, Any]:
    execution_plan = row.get("execution_plan_json") or {}
    return {
        "rule_id": row.get("rule_id"),
        "table_name": row.get("table_name"),
        "column_name": row.get("column_name"),
        "rule_type": row.get("rule_type"),
        "severity": row.get("severity"),
        "confidence": row.get("confidence"),
        "status": row.get("status"),
        "source_text": row.get("source_text") or (row.get("condition_json") or {}).get("source_text"),
        "sql_preview_status": execution_plan.get("sql_preview_status"),
        "sql_preview_source": execution_plan.get("sql_preview_source"),
    }


def build_data_quality_run_hydration_payload(
    *,
    row: dict[str, Any],
    remediation_plan: dict[str, Any] | None = None,
    rule_review_queue: dict[str, Any] | None = None,
    enrichment_question_queue: dict[str, Any] | None = None,
    lineage_overview: dict[str, Any] | None = None,
) -> dict[str, Any]:
    run_payload = build_data_quality_run_summary_payload(row=row, remediation_plan=remediation_plan)
    rule_review_queue = rule_review_queue or {"summary": {}, "rules": []}
    enrichment_question_queue = enrichment_question_queue or {"summary": {}, "questions": []}
    lineage_overview = lineage_overview or {"summary": {}, "rows": []}
    top_rule_review_items = [
        _trim_rule_review_item(item)
        for item in (rule_review_queue.get("rules") or [])[:5]
        if isinstance(item, dict)
    ]
    top_enrichment_questions = [
        item
        for item in (enrichment_question_queue.get("questions") or [])[:5]
        if isinstance(item, dict)
    ]
    return {
        "run": run_payload,
        "pending_tasks": {
            "workflow_status": run_payload.get("workflow_status"),
            "requires_attention": bool(
                run_payload.get("rule_review_required")
                or (enrichment_question_queue.get("summary") or {}).get("pending_answer_count")
                or (enrichment_question_queue.get("summary") or {}).get("proposal_ready_count")
            ),
            "rule_review": {
                **(rule_review_queue.get("summary") or {}),
                "top_items": top_rule_review_items,
            },
            "enrichment_questions": {
                **(enrichment_question_queue.get("summary") or {}),
                "top_items": top_enrichment_questions,
            },
            "lineage": {
                **(lineage_overview.get("summary") or {}),
                "top_items": [
                    item
                    for item in (lineage_overview.get("rows") or [])[:5]
                    if isinstance(item, dict)
                ],
            },
            "remediation": {
                "summary": (remediation_plan or {}).get("summary") or {},
                "top_actions": (remediation_plan or {}).get("actions") or [],
            },
        },
        "artifact_links": run_payload.get("artifacts") or {},
    }
