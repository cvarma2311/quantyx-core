from __future__ import annotations

from typing import Any


def derive_data_quality_rule_dimension(rule: dict[str, Any]) -> str:
    rule_type = str(rule.get("rule_type") or "").strip().lower()
    if rule_type in {"not_null", "not_blank", "null_pct_threshold"}:
        return "completeness"
    if rule_type in {"unique", "composite_unique"}:
        return "uniqueness"
    if rule_type in {"referential_integrity", "cross_column_consistency"}:
        return "consistency"
    if rule_type in {"email_pattern", "allowed_values", "regex_pattern", "date_range", "length"}:
        return "validity"
    if rule_type in {"numeric_min", "numeric_max", "numeric_range", "custom_sql"}:
        return "accuracy"
    return "other"


def build_data_quality_artifact_links(*, tenant_id: str, domain_id: str, run_id: str) -> dict[str, str]:
    return {
        "run_summary": f"/data-quality/runs/{run_id}",
        "dashboard": f"/data-quality/runs/{run_id}/dashboard",
        "excel_report": f"/data-quality/reports/{run_id}/excel?tenant_id={tenant_id}&domain_id={domain_id}",
        "csv_report": f"/data-quality/reports/{run_id}/csv?tenant_id={tenant_id}&domain_id={domain_id}",
        "trends": f"/data-quality/trends?tenant_id={tenant_id}&domain_id={domain_id}&run_id={run_id}",
        "business_term_trends": f"/data-quality/trends/business-terms?tenant_id={tenant_id}&domain_id={domain_id}&run_id={run_id}",
        "anomalies": f"/data-quality/anomalies?tenant_id={tenant_id}&domain_id={domain_id}&run_id={run_id}",
        "issues": f"/data-quality/issues?tenant_id={tenant_id}&domain_id={domain_id}&run_id={run_id}",
        "stages": f"/data-quality/stages?tenant_id={tenant_id}&domain_id={domain_id}&run_id={run_id}",
        "joins": f"/data-quality/joins?tenant_id={tenant_id}&domain_id={domain_id}&run_id={run_id}",
        "rejected_records": f"/data-quality/rejected-records?tenant_id={tenant_id}&domain_id={domain_id}&run_id={run_id}",
        "final_dataset": f"/data-quality/final-dataset?tenant_id={tenant_id}&domain_id={domain_id}&run_id={run_id}",
        "final_dataset_rows": f"/data-quality/final-dataset/rows?tenant_id={tenant_id}&domain_id={domain_id}&run_id={run_id}",
        "lineage": f"/data-quality/lineage?tenant_id={tenant_id}&domain_id={domain_id}&run_id={run_id}",
        "lineage_base": f"/data-quality/lineage?tenant_id={tenant_id}&domain_id={domain_id}&run_id={run_id}",
        "run_lineage": f"/agentic/runs/{run_id}/lineage",
        "tables": f"/data-quality/tables?tenant_id={tenant_id}&domain_id={domain_id}&run_id={run_id}",
        "rules": f"/data-quality/rules?tenant_id={tenant_id}&domain_id={domain_id}&run_id={run_id}",
        "rule_coverage": f"/data-quality/rule-coverage?tenant_id={tenant_id}&domain_id={domain_id}&run_id={run_id}",
        "rule_review_queue": f"/data-quality/rules/review-queue?tenant_id={tenant_id}&domain_id={domain_id}&run_id={run_id}",
        "resume_after_rule_review": f"/data-quality/runs/{run_id}/resume-after-rule-review",
        "duplicates": f"/data-quality/duplicates?tenant_id={tenant_id}&domain_id={domain_id}&run_id={run_id}",
        "remediation": f"/data-quality/remediation?tenant_id={tenant_id}&domain_id={domain_id}&run_id={run_id}",
        "enrichment_opportunities": f"/data-quality/enrichment/opportunities?tenant_id={tenant_id}&domain_id={domain_id}&run_id={run_id}",
        "enrichment_questions": f"/data-quality/enrichment/questions?tenant_id={tenant_id}&domain_id={domain_id}&run_id={run_id}",
    }


def build_data_quality_rule_evidence_links(
    *,
    tenant_id: str,
    domain_id: str,
    run_id: str,
    rule_id: str,
) -> dict[str, str]:
    base_q = f"tenant_id={tenant_id}&domain_id={domain_id}&run_id={run_id}"
    return {
        "review_detail": f"/data-quality/rules/{rule_id}/review?tenant_id={tenant_id}",
        "rule_evidence": f"/data-quality/evidence/rules/{rule_id}?tenant_id={tenant_id}&domain_id={domain_id}",
        "failed_records": f"/data-quality/runs/{run_id}/rules/{rule_id}/failed-records?{base_q}",
        "passed_records": f"/data-quality/runs/{run_id}/rules/{rule_id}/passed-records?{base_q}",
    }


def build_data_quality_rule_outcome_payload(
    *,
    row: dict[str, Any],
    tenant_id: str,
    domain_id: str,
) -> dict[str, Any]:
    run_id = str(row.get("run_id") or "")
    rule_id = str(row.get("rule_id") or "")
    checked_row_count = int(row.get("checked_row_count") or 0)
    failed_row_count = int(row.get("violation_count") or 0)
    passed_row_count = max(checked_row_count - failed_row_count, 0)
    try:
        pass_pct = round((passed_row_count / checked_row_count) * 100.0, 4) if checked_row_count else None
    except Exception:
        pass_pct = None
    evidence = build_data_quality_rule_evidence_links(
        tenant_id=tenant_id,
        domain_id=domain_id,
        run_id=run_id,
        rule_id=rule_id,
    )
    return {
        "rule_id": row.get("rule_id"),
        "quality_run_id": row.get("quality_run_id"),
        "run_id": row.get("run_id"),
        "rule_type": row.get("rule_type"),
        "rule_label": row.get("rule_label"),
        "dimension": derive_data_quality_rule_dimension(row),
        "severity": row.get("severity"),
        "table_name": row.get("table_name"),
        "column_name": row.get("column_name"),
        "reference_table": row.get("reference_table"),
        "reference_column": row.get("reference_column"),
        "source_text": row.get("source_text") or (row.get("condition_json") or {}).get("source_text"),
        "executor_kind": row.get("executor_kind"),
        "execution_plan": row.get("execution_plan_json") or {},
        "sql_preview": (row.get("execution_plan_json") or {}).get("sql_preview") or {},
        "sql_preview_status": (row.get("execution_plan_json") or {}).get("sql_preview_status"),
        "sql_preview_source": (row.get("execution_plan_json") or {}).get("sql_preview_source"),
        "condition_json": row.get("condition_json") or {},
        "source": row.get("source"),
        "confidence": row.get("confidence"),
        "rule_status": row.get("status"),
        "reviewed_by": row.get("reviewed_by"),
        "reviewed_at": row.get("reviewed_at"),
        "review_notes": row.get("review_notes"),
        "result": {
            "result_id": row.get("result_id"),
            "status": row.get("result_status"),
            "result_status": row.get("result_status"),
            "checked_row_count": checked_row_count,
            "failed_row_count": failed_row_count,
            "passed_row_count": passed_row_count,
            "violation_count": row.get("violation_count"),
            "violation_pct": row.get("violation_pct"),
            "pass_pct": pass_pct,
            "sample_rows_json": row.get("sample_rows_json") or [],
            "error_message": row.get("error_message"),
            "executed_at": row.get("executed_at"),
            "evidence": evidence,
        }
        if row.get("result_id")
        else None,
        "evidence": evidence,
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
        "rule_validation_planner_mode": summary.get("rule_validation_planner_mode"),
        "validation_control_count": summary.get("validation_control_count", 0),
        "compiled_validation_control_count": summary.get("compiled_validation_control_count", 0),
        "uncovered_validation_control_count": summary.get("uncovered_validation_control_count", 0),
        "workflow_status": summary.get("workflow_status") or row.get("status"),
        "trend_mode": row.get("trend_mode") or summary.get("trend_mode"),
        "trend_scope_key": row.get("trend_scope_key") or summary.get("trend_scope_key"),
        "trend_scope_label": row.get("trend_scope_label") or summary.get("trend_scope_label"),
        "baseline_run_id": row.get("baseline_run_id") or summary.get("baseline_run_id"),
        "trend_row_count": summary.get("trend_row_count", 0),
        "improved_metric_count": summary.get("improved_metric_count", 0),
        "worsened_metric_count": summary.get("worsened_metric_count", 0),
        "business_term_group_count": summary.get("business_term_group_count", 0),
        "worsened_business_term_count": summary.get("worsened_business_term_count", 0),
        "readiness_trend_status": summary.get("readiness_trend_status"),
        "baseline_readiness_status": summary.get("baseline_readiness_status"),
        "certification_blocker_count": summary.get("certification_blocker_count", 0),
        "residual_anomaly_count": summary.get("residual_anomaly_count", 0),
        "anomaly_count": summary.get("anomaly_count", 0),
        "critical_anomaly_count": summary.get("critical_anomaly_count", 0),
        "issue_count": summary.get("issue_count", 0),
        "open_issue_count": summary.get("open_issue_count", 0),
        "overdue_issue_count": summary.get("overdue_issue_count", 0),
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
        "rule_label": row.get("rule_label"),
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
    trend_overview: dict[str, Any] | None = None,
    business_term_overview: dict[str, Any] | None = None,
    anomaly_overview: dict[str, Any] | None = None,
    issue_overview: dict[str, Any] | None = None,
    readiness_overview: dict[str, Any] | None = None,
) -> dict[str, Any]:
    run_payload = build_data_quality_run_summary_payload(row=row, remediation_plan=remediation_plan)
    rule_review_queue = rule_review_queue or {"summary": {}, "rules": []}
    enrichment_question_queue = enrichment_question_queue or {"summary": {}, "questions": []}
    lineage_overview = lineage_overview or {"summary": {}, "rows": []}
    trend_overview = trend_overview or {"summary": {}, "trends": []}
    business_term_overview = business_term_overview or {
        "summary": {
            "business_term_group_count": 0,
            "worsened_business_term_count": 0,
            "improved_business_term_count": 0,
            "unmatched_trend_row_count": 0,
        },
        "rows": [],
    }
    anomaly_overview = anomaly_overview or {"summary": {}, "anomalies": []}
    issue_overview = issue_overview or {"summary": {}, "issues": []}
    readiness_overview = readiness_overview or {}
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
                or (issue_overview.get("summary") or {}).get("open_issue_count")
                or (issue_overview.get("summary") or {}).get("overdue_issue_count")
                or (anomaly_overview.get("summary") or {}).get("anomaly_count")
                or int(readiness_overview.get("certification_blocker_count") or 0) > 0
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
            "trends": {
                **(trend_overview.get("summary") or {}),
                "top_items": [
                    item
                    for item in (trend_overview.get("trends") or [])[:5]
                    if isinstance(item, dict)
                ],
            },
            "business_terms": {
                **(business_term_overview.get("summary") or {}),
                "top_items": [
                    item
                    for item in (business_term_overview.get("rows") or [])[:5]
                    if isinstance(item, dict)
                ],
            },
            "readiness": readiness_overview,
            "anomalies": {
                **(anomaly_overview.get("summary") or {}),
                "top_items": [
                    item
                    for item in (anomaly_overview.get("anomalies") or [])[:5]
                    if isinstance(item, dict)
                ],
            },
            "issues": {
                **(issue_overview.get("summary") or {}),
                "top_items": [
                    item
                    for item in (issue_overview.get("issues") or [])[:5]
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
