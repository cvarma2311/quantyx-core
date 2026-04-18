from __future__ import annotations

from typing import Any

from services.ai.data_quality_api_payloads import build_data_quality_artifact_links
from services.ai.config import Settings
from services.ai.data_quality_enrichment import canonical_column_alias, canonical_column_aliases
from services.ai.data_quality_remediation import build_data_quality_remediation_plan
from services.ai.data_quality_store import (
    get_quality_run_by_run_id,
    get_quality_table_detail,
    list_quality_duplicate_candidates,
    list_quality_enrichment_opportunities,
    list_quality_rules,
    list_quality_tables,
)


def _clean(text: str | None) -> str:
    return str(text or "").strip().lower()


def _contains_any(text: str, phrases: list[str]) -> bool:
    return any(phrase in text for phrase in phrases)


def _extract_table_name(question: str, tables: list[dict[str, Any]]) -> str | None:
    lowered = _clean(question)
    for table in tables:
        table_name = str(table.get("table_name") or "").strip()
        if table_name and table_name.lower() in lowered:
            return table_name
    return None


def _issue_severity_rank(value: str | None) -> int:
    severity = _clean(value)
    if severity == "critical":
        return 0
    if severity == "warning":
        return 1
    if severity == "info":
        return 2
    return 3


def _classify_intent(question: str) -> str:
    lowered = _clean(question)
    if _contains_any(lowered, ["referential integrity", "foreign key", "orphan"]):
        return "referential_integrity"
    if _contains_any(lowered, ["freshness", "stale", "staleness", "stability", "drift", "row count change"]):
        return "freshness"
    if _contains_any(lowered, ["enrichment", "enrich", "fill missing", "missing values can be filled", "approval"]):
        return "enrichment"
    if _contains_any(lowered, ["remediation", "action plan", "fix plan", "what should we fix"]):
        return "remediation"
    if _contains_any(lowered, ["missing columns", "missing fields", "null columns", "nulls", "missingness"]):
        return "missingness"
    if "why" in lowered and "trust" in lowered:
        return "trust_explanation"
    if _contains_any(lowered, ["top issues", "critical issues", "summarize", "summary", "worst data quality", "worst issues"]):
        return "summary"
    return "summary"


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _build_top_issues(
    tables: list[dict[str, Any]],
    rules: list[dict[str, Any]],
    duplicates: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    duplicates = [item for item in (duplicates or []) if isinstance(item, dict)]
    for table in tables[:5]:
        trust = _safe_float(table.get("trust_score"))
        if trust is None:
            continue
        issues.append(
            {
                "issue_type": "table_trust",
                "severity": table.get("severity") or "warning",
                "table_name": table.get("table_name"),
                "summary": f"Trust score {trust:.1f}",
                "metric": trust,
                "recommended_action": "Review missingness, failed rules, duplicates, and freshness contributors for this table.",
            }
        )
    for rule in rules:
        if str(rule.get("result_status") or "").strip().lower() not in {"failed", "error"}:
            continue
        issues.append(
            {
                "issue_type": "rule_failure",
                "severity": rule.get("severity") or "warning",
                "table_name": rule.get("table_name"),
                "column_name": rule.get("column_name"),
                "rule_type": rule.get("rule_type"),
                "summary": f"{rule.get('rule_type')} failed with {int(rule.get('violation_count') or 0)} violating rows",
                "metric": _safe_float(rule.get("violation_pct")) or _safe_float(rule.get("violation_count")) or 0.0,
                "recommended_action": "Inspect failed rows, validate source mapping, and add remediation or enrichment flow if appropriate.",
            }
        )
    for item in duplicates[:5]:
        issues.append(
            {
                "issue_type": "duplicate_candidate",
                "severity": "warning",
                "table_name": item.get("table_name"),
                "summary": f"{item.get('duplicate_type')} with {int(item.get('candidate_record_count') or 0)} candidate records",
                "metric": _safe_float(item.get("candidate_record_count")) or 0.0,
                "recommended_action": "Review duplicate clusters before downstream matching, merge, or trust decisions.",
            }
        )
    for table in tables[:8]:
        summary_json = table.get("summary_json") or {}
        freshness = summary_json.get("freshness_analysis") or {}
        stability = summary_json.get("stability_analysis") or {}
        if freshness.get("freshness_status") == "stale":
            issues.append(
                {
                    "issue_type": "stale_table",
                    "severity": "warning",
                    "table_name": table.get("table_name"),
                    "summary": f"Freshness lag is {float(freshness.get('freshness_lag_days') or 0.0):.1f} days",
                    "metric": _safe_float(freshness.get("freshness_lag_days")) or 0.0,
                    "recommended_action": "Verify upstream feed schedules and freshness SLA expectations for this table.",
                }
            )
        if stability.get("stability_status") == "changed":
            issues.append(
                {
                    "issue_type": "stability_change",
                    "severity": "warning",
                    "table_name": table.get("table_name"),
                    "summary": f"Row count change {float(stability.get('row_count_change_pct') or 0.0):.1f}% and completeness change {float(stability.get('completeness_score_change') or 0.0):.1f}",
                    "metric": _safe_float(stability.get("row_count_change_pct")) or abs(_safe_float(stability.get("completeness_score_change")) or 0.0),
                    "recommended_action": "Compare this run to the previous quality baseline before trusting downstream movement.",
                }
            )
    issues.sort(
        key=lambda item: (
            _issue_severity_rank(str(item.get("severity"))),
            -(_safe_float(item.get("metric")) or 0.0),
            str(item.get("table_name") or ""),
        )
    )
    return issues[:8]


def _build_missingness_rows(table_detail: dict[str, Any]) -> list[dict[str, Any]]:
    columns = list(table_detail.get("columns") or [])
    columns.sort(
        key=lambda item: (
            -(_safe_float(item.get("null_pct")) or 0.0),
            -(_safe_float(item.get("blank_pct")) or 0.0),
            str(item.get("column_name") or ""),
        )
    )
    rows: list[dict[str, Any]] = []
    for column in columns:
        null_pct = _safe_float(column.get("null_pct")) or 0.0
        blank_pct = _safe_float(column.get("blank_pct")) or 0.0
        if null_pct <= 0 and blank_pct <= 0:
            continue
        rows.append(
            {
                "table_name": table_detail.get("table_name"),
                "column_name": column.get("column_name"),
                "null_count": column.get("null_count"),
                "null_pct": null_pct,
                "blank_count": column.get("blank_count"),
                "blank_pct": blank_pct,
                "completeness_score": column.get("completeness_score"),
                "recommended_action": "Backfill or enrich this column before downstream consumption if the field is business-critical.",
            }
        )
    return rows[:12]


def _build_referential_rows(rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = [
        {
            "rule_id": rule.get("rule_id"),
            "table_name": rule.get("table_name"),
            "column_name": rule.get("column_name"),
            "reference_table": rule.get("reference_table"),
            "reference_column": rule.get("reference_column"),
            "violation_count": rule.get("violation_count"),
            "violation_pct": rule.get("violation_pct"),
            "severity": rule.get("severity"),
            "sample_rows_json": rule.get("sample_rows_json") or [],
        }
        for rule in rules
        if str(rule.get("rule_type") or "").strip().lower() == "referential_integrity"
        and str(rule.get("result_status") or "").strip().lower() in {"failed", "error"}
    ]
    rows.sort(
        key=lambda item: (
            _issue_severity_rank(str(item.get("severity"))),
            -(_safe_float(item.get("violation_pct")) or 0.0),
            -(_safe_float(item.get("violation_count")) or 0.0),
        )
    )
    return rows[:10]


def _build_enrichment_rows(opportunities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = [
        {
            "opportunity_id": item.get("opportunity_id"),
            "table_name": item.get("table_name"),
            "target_column": item.get("target_column"),
            "target_column_alias": canonical_column_alias(item.get("target_column")),
            "source_columns": item.get("source_columns") or [],
            "source_column_aliases": canonical_column_aliases(item.get("source_columns") or []),
            "missing_count": item.get("missing_count"),
            "candidate_method": item.get("candidate_method"),
            "confidence": item.get("confidence"),
            "status": item.get("status"),
            "question": item.get("question"),
        }
        for item in opportunities
    ]
    rows.sort(
        key=lambda item: (
            -(_safe_float(item.get("missing_count")) or 0.0),
            -(_safe_float(item.get("confidence")) or 0.0),
        )
    )
    return rows[:10]


def _build_freshness_rows(tables: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for table in tables:
        summary_json = table.get("summary_json") or {}
        freshness = summary_json.get("freshness_analysis") or {}
        stability = summary_json.get("stability_analysis") or {}
        rows.append(
            {
                "table_name": table.get("table_name"),
                "freshness_column": freshness.get("freshness_column"),
                "freshness_lag_days": freshness.get("freshness_lag_days"),
                "freshness_status": freshness.get("freshness_status"),
                "row_count_change_pct": stability.get("row_count_change_pct"),
                "completeness_score_change": stability.get("completeness_score_change"),
                "stability_status": stability.get("stability_status"),
                "stability_issues": stability.get("stability_issues") or [],
            }
        )
    rows.sort(
        key=lambda item: (
            0 if item.get("freshness_status") == "stale" else 1,
            0 if item.get("stability_status") == "changed" else 1,
            -(_safe_float(item.get("freshness_lag_days")) or 0.0),
            -(_safe_float(item.get("row_count_change_pct")) or 0.0),
        )
    )
    return rows[:12]


def build_data_quality_workspace_response(
    settings: Settings,
    *,
    tenant_id: str,
    domain_id: str,
    run_id: str | None,
    question: str,
) -> tuple[dict[str, Any], str, dict[str, Any], dict[str, Any]] | None:
    if _clean(domain_id) != "data_quality_observability" or not str(run_id or "").strip():
        return None
    run = get_quality_run_by_run_id(settings, str(run_id))
    if not run:
        return None
    tables = list_quality_tables(
        settings,
        tenant_id=tenant_id,
        domain_id=domain_id,
        run_id=run_id,
        limit=12,
    )
    rules = list_quality_rules(
        settings,
        tenant_id=tenant_id,
        domain_id=domain_id,
        run_id=run_id,
        limit=50,
    )
    opportunities = list_quality_enrichment_opportunities(
        settings,
        tenant_id=tenant_id,
        domain_id=domain_id,
        run_id=run_id,
        limit=20,
    )
    duplicates = list_quality_duplicate_candidates(
        settings,
        tenant_id=tenant_id,
        domain_id=domain_id,
        run_id=run_id,
        limit=20,
    )
    intent = _classify_intent(question)
    referenced_table = _extract_table_name(question, tables)
    title = "Data Quality Summary"
    rows: list[dict[str, Any]] = []
    assistant_text = ""

    if intent == "missingness" and referenced_table:
        detail = get_quality_table_detail(
            settings,
            tenant_id=tenant_id,
            domain_id=domain_id,
            table_name=referenced_table,
            run_id=run_id,
        ) or {"table_name": referenced_table, "columns": []}
        rows = _build_missingness_rows(detail)
        title = f"Missingness - {referenced_table}"
        if rows:
            worst = rows[0]
            assistant_text = (
                f"{referenced_table} has {len(rows)} columns with missing data. "
                f"The worst is {worst.get('column_name')} at {float(worst.get('null_pct') or 0.0):.1f}% null."
            )
        else:
            assistant_text = f"{referenced_table} does not have material missingness in persisted column artifacts."
    elif intent == "trust_explanation" and referenced_table:
        detail = get_quality_table_detail(
            settings,
            tenant_id=tenant_id,
            domain_id=domain_id,
            table_name=referenced_table,
            run_id=run_id,
        ) or {}
        rows = _build_missingness_rows(detail)
        title = f"Trust Drivers - {referenced_table}"
        trust_score = _safe_float(detail.get("trust_score"))
        trust_components = (detail.get("summary") or {}).get("trust_components") or {}
        if rows:
            worst = rows[0]
            assistant_text = (
                f"{referenced_table} is at trust score {trust_score:.1f}."
                if trust_score is not None
                else f"{referenced_table} has the following trust drivers."
            )
            assistant_text += (
                f" The largest current completeness drag is {worst.get('column_name')} "
                f"with {float(worst.get('null_pct') or 0.0):.1f}% null."
            )
        else:
            assistant_text = (
                f"{referenced_table} is at trust score {trust_score:.1f}. Review failed rules, duplicates, and freshness contributors for the full breakdown."
                if trust_score is not None
                else f"{referenced_table} has no detailed missingness breakdown available yet."
            )
        if trust_components:
            rows = [
                {
                    "component": key,
                    "score": value,
                }
                for key, value in trust_components.items()
            ]
    elif intent == "referential_integrity":
        rows = _build_referential_rows(rules)
        title = "Referential Integrity Failures"
        assistant_text = (
            f"Found {len(rows)} failing referential integrity checks in the persisted rule results."
            if rows
            else "No failing referential integrity checks are currently persisted for this run."
        )
    elif intent == "freshness":
        rows = _build_freshness_rows(tables)
        title = "Freshness and Stability"
        stale_count = len([row for row in rows if row.get("freshness_status") == "stale"])
        changed_count = len([row for row in rows if row.get("stability_status") == "changed"])
        assistant_text = (
            f"I found {stale_count} stale tables and {changed_count} tables with stability changes against the previous quality baseline."
            if rows
            else "No freshness or stability rows are currently available for this run."
        )
    elif intent == "enrichment":
        rows = _build_enrichment_rows(opportunities)
        title = "Enrichment Opportunities"
        assistant_text = (
            f"There are {len(rows)} enrichment opportunities ready for review or proposal generation."
            if rows
            else "No enrichment opportunities are currently persisted for this run."
        )
    elif intent == "remediation":
        remediation_plan = build_data_quality_remediation_plan(
            settings,
            tenant_id=tenant_id,
            domain_id=domain_id,
            run_id=str(run_id),
            limit=12,
        )
        rows = remediation_plan.get("actions") or []
        title = "Data Quality Remediation Plan"
        assistant_text = (
            f"Built a remediation queue with {len(rows)} prioritized actions from trust, rule, and enrichment artifacts."
            if rows
            else "No remediation actions could be derived from the current persisted artifacts."
        )
    else:
        rows = _build_top_issues(tables, rules, duplicates)
        title = "Top Data Quality Issues"
        summary = run.get("summary_json") or {}
        overall = _safe_float(run.get("overall_trust_score"))
        assistant_text = (
            f"Overall trust score is {overall:.1f}. "
            if overall is not None
            else ""
        )
        assistant_text += (
            f"I found {summary.get('critical_issue_count', 0)} critical issues, "
            f"{summary.get('warning_issue_count', 0)} warnings, and "
            f"{summary.get('enrichment_opportunity_count', 0)} enrichment opportunities."
        )

    artifacts = build_data_quality_artifact_links(tenant_id=tenant_id, domain_id=domain_id, run_id=str(run_id))
    try:
        remediation_plan = build_data_quality_remediation_plan(
            settings,
            tenant_id=tenant_id,
            domain_id=domain_id,
            run_id=str(run_id),
            limit=5,
        )
    except Exception:
        remediation_plan = {"summary": {}, "actions": []}
    data_quality = {
        "intent": intent,
        "quality_run_id": run.get("quality_run_id"),
        "overall_trust_score": run.get("overall_trust_score"),
        "summary": run.get("summary_json") or {},
        "artifacts": artifacts,
        "rows": rows,
        "remediation_summary": remediation_plan.get("summary") or {},
        "recommended_actions": remediation_plan.get("actions") or [],
        "referenced_table": referenced_table,
    }
    response_payload = {
        "metrics": [],
        "dimensions": [],
        "chart_id": None,
        "chart_type": "table",
        "chart_title": title,
        "dashboard_title": "Data Quality Workspace",
        "chart_payload": None,
        "data": rows,
        "rows": rows,
        "sql": None,
        "lineage": None,
        "artifact_lineage": artifacts,
        "conversation_plan": {
            "sql_mode": "data_quality_artifacts",
            "intent": intent,
            "quality_run_id": run.get("quality_run_id"),
            "remediation_action_count": (remediation_plan.get("summary") or {}).get("action_count", 0),
        },
        "chart_followup": None,
        "data_quality": data_quality,
    }
    summary_json = {
        "text": assistant_text,
        "row_count": len(rows),
        "metrics": [],
        "dimensions": [],
        "lineage": None,
        "artifact_lineage": artifacts,
        "conversation_plan": response_payload["conversation_plan"],
        "data_quality": data_quality,
    }
    inference_json = {
        "text": "Use the data quality artifact links to inspect table detail, rules, dashboard, enrichment opportunities, or the Excel report.",
        "confidence": 0.9 if rows or data_quality.get("summary") else 0.5,
        "artifact_lineage": artifacts,
        "conversation_plan": response_payload["conversation_plan"],
        "data_quality": data_quality,
    }
    return response_payload, assistant_text, summary_json, inference_json
