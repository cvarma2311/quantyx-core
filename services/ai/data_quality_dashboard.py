from __future__ import annotations

from collections import Counter
from typing import Any

from services.ai.config import Settings
from services.ai.data_quality_enrichment import canonical_column_alias
from services.ai.data_quality_remediation import derive_data_quality_remediation_plan
from services.ai.dashboards_store import create_dashboard


def _as_number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _display_column(field: str, label: str) -> dict[str, str]:
    return {"field": field, "label": label}


def _append_chart_section(chart_plan: list[dict[str, Any]], section: dict[str, Any], *, include_when_empty: bool = False) -> None:
    rows = section.get("rows")
    if include_when_empty:
        chart_plan.append(section)
        return
    if isinstance(rows, list) and rows:
        chart_plan.append(section)


def _table_rows(profiling: dict[str, Any]) -> list[dict[str, Any]]:
    return [table for table in (profiling.get("tables") or []) if isinstance(table, dict)]


def _column_rows(profiling: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for table in _table_rows(profiling):
        table_name = str(table.get("name") or "").strip()
        for profile in table.get("column_profiles") or []:
            if not isinstance(profile, dict):
                continue
            row = dict(profile)
            row["table_name"] = table_name
            rows.append(row)
    return rows


def build_data_quality_dashboard_spec(
    *,
    tenant_id: str = "tenant",
    run_id: str,
    domain_id: str,
    profiling: dict[str, Any],
    quality_tables: list[dict[str, Any]] | None = None,
    quality_summary: dict[str, Any],
    quality_rules: list[dict[str, Any]] | None = None,
    quality_rule_results: list[dict[str, Any]] | None = None,
    duplicate_candidates: list[dict[str, Any]] | None = None,
    freshness_results: list[dict[str, Any]] | None = None,
    enrichment_opportunities: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    tables = _table_rows(profiling)
    columns = _column_rows(profiling)
    quality_rules = [rule for rule in (quality_rules or []) if isinstance(rule, dict)]
    quality_rule_results = [result for result in (quality_rule_results or []) if isinstance(result, dict)]
    duplicate_candidates = [item for item in (duplicate_candidates or []) if isinstance(item, dict)]
    freshness_results = [item for item in (freshness_results or []) if isinstance(item, dict)]
    quality_tables = [item for item in (quality_tables or []) if isinstance(item, dict)]
    enrichment_opportunities = [item for item in (enrichment_opportunities or []) if isinstance(item, dict)]
    evidence_base = f"/data-quality/evidence"
    remediation_plan = derive_data_quality_remediation_plan(
        tenant_id=tenant_id,
        domain_id=domain_id,
        run_id=run_id,
        tables=quality_tables,
        rules=quality_rules,
        duplicates=duplicate_candidates,
        opportunities=enrichment_opportunities,
        limit=15,
    )
    freshness_by_table = {
        str(item.get("table_name") or "").strip(): item
        for item in freshness_results
        if str(item.get("table_name") or "").strip()
    }

    trust_rows = []
    freshness_rows = []
    duplicate_rows = []
    persisted_tables_by_name = {
        str(item.get("table_name") or "").strip(): item
        for item in quality_tables
        if str(item.get("table_name") or "").strip()
    }
    duplicate_candidate_counts: dict[str, dict[str, Any]] = {}
    for candidate in duplicate_candidates:
        table_name = str(candidate.get("table_name") or "").strip()
        if not table_name:
            continue
        bucket = duplicate_candidate_counts.setdefault(
            table_name,
            {
                "candidate_id": None,
                "duplicate_candidate_count": 0,
                "exact_duplicate_candidate_count": 0,
                "fuzzy_duplicate_candidate_count": 0,
                "candidate_record_count": 0,
                "highest_confidence": None,
            },
        )
        bucket["candidate_id"] = bucket.get("candidate_id") or candidate.get("candidate_id")
        bucket["duplicate_candidate_count"] += 1
        if str(candidate.get("duplicate_type") or "").startswith("exact_"):
            bucket["exact_duplicate_candidate_count"] += 1
        if str(candidate.get("duplicate_type") or "").startswith("fuzzy_"):
            bucket["fuzzy_duplicate_candidate_count"] += 1
        bucket["candidate_record_count"] += int(candidate.get("candidate_record_count") or 0)
        confidence = _as_number(candidate.get("confidence"))
        if confidence is not None and (bucket["highest_confidence"] is None or confidence > bucket["highest_confidence"]):
            bucket["highest_confidence"] = confidence
    for table in tables:
        summary = table.get("quality_summary") or {}
        persisted_table = persisted_tables_by_name.get(str(table.get("name") or "").strip(), {})
        table_dupes = duplicate_candidate_counts.get(str(table.get("name") or "").strip(), {})
        trust_rows.append(
            {
                "table_name": table.get("name"),
                "trust_score": _as_number(persisted_table.get("trust_score")) if persisted_table else _as_number(summary.get("table_trust_score")),
                "completeness_score": _as_number(persisted_table.get("completeness_score")) if persisted_table else _as_number(summary.get("table_completeness_score")),
                "validity_score": _as_number(persisted_table.get("validity_score")),
                "referential_integrity_score": _as_number(persisted_table.get("referential_integrity_score")),
                "freshness_score": _as_number(persisted_table.get("freshness_score")),
                "duplicate_risk_score": _as_number(persisted_table.get("duplicate_risk_score")),
                "row_count": table.get("row_count") or summary.get("row_count"),
            }
        )
        freshness_rows.append(
            {
                "table_name": table.get("name"),
                "freshness_lag_days": _as_number(summary.get("freshness_lag_days")),
                "trust_score": _as_number(persisted_table.get("trust_score")) if persisted_table else _as_number(summary.get("table_trust_score")),
                "freshness_column": (freshness_by_table.get(str(table.get("name") or "").strip()) or {}).get("freshness_column"),
                "freshness_column_alias": canonical_column_alias(
                    (freshness_by_table.get(str(table.get("name") or "").strip()) or {}).get("freshness_column")
                ),
                "freshness_status": (freshness_by_table.get(str(table.get("name") or "").strip()) or {}).get("freshness_status"),
                "row_count_change_pct": (freshness_by_table.get(str(table.get("name") or "").strip()) or {}).get("row_count_change_pct"),
                "completeness_score_change": (freshness_by_table.get(str(table.get("name") or "").strip()) or {}).get("completeness_score_change"),
                "stability_status": (freshness_by_table.get(str(table.get("name") or "").strip()) or {}).get("stability_status"),
                "evidence_path": f"{evidence_base}/freshness/{table.get('name')}?tenant_id={tenant_id}&domain_id={domain_id}&run_id={run_id}",
            }
        )
        duplicate_rows.append(
            {
                "table_name": table.get("name"),
                "duplicate_risk_columns_count": int(summary.get("duplicate_risk_columns_count") or 0),
                "duplicate_risk_score": _as_number(persisted_table.get("duplicate_risk_score")) if persisted_table else _as_number(summary.get("duplicate_risk_score")),
                "duplicate_candidate_count": table_dupes.get("duplicate_candidate_count", 0),
                "exact_duplicate_candidate_count": table_dupes.get("exact_duplicate_candidate_count", 0),
                "fuzzy_duplicate_candidate_count": table_dupes.get("fuzzy_duplicate_candidate_count", 0),
                "candidate_record_count": table_dupes.get("candidate_record_count", 0),
                "highest_confidence": table_dupes.get("highest_confidence"),
                "candidate_id": table_dupes.get("candidate_id"),
            }
        )
    trust_rows = sorted(
        [row for row in trust_rows if row.get("table_name")],
        key=lambda row: (9999.0 if row.get("trust_score") is None else row["trust_score"], str(row.get("table_name"))),
    )[:15]
    freshness_rows = sorted(
        [row for row in freshness_rows if row.get("freshness_lag_days") is not None],
        key=lambda row: float(row.get("freshness_lag_days") or 0.0),
        reverse=True,
    )[:15]
    duplicate_rows = sorted(
        [
            row
            for row in duplicate_rows
            if row.get("table_name")
            and (
                int(row.get("duplicate_candidate_count") or 0) > 0
                or int(row.get("candidate_record_count") or 0) > 0
                or int(row.get("duplicate_risk_columns_count") or 0) > 0
            )
        ],
        key=lambda row: (
            -int(row.get("duplicate_candidate_count") or 0),
            -int(row.get("duplicate_risk_columns_count") or 0),
            9999.0 if row.get("duplicate_risk_score") is None else row["duplicate_risk_score"],
        ),
    )[:15]
    for row in duplicate_rows:
        candidate_id = row.get("candidate_id")
        row["evidence_path"] = (
            f"{evidence_base}/duplicates/{candidate_id}?tenant_id={tenant_id}&domain_id={domain_id}"
            if candidate_id
            else None
        )

    missingness_rows = sorted(
        [
            {
                "table_name": row.get("table_name"),
                "column_name": row.get("name"),
                "column_alias": canonical_column_alias(row.get("name")),
                "null_pct": _as_number(row.get("null_pct")),
                "blank_pct": _as_number(row.get("blank_pct")),
                "completeness_score": _as_number(row.get("completeness_score")),
                "evidence_path": (
                    f"{evidence_base}/missingness?tenant_id={tenant_id}&domain_id={domain_id}&run_id={run_id}"
                    f"&table_name={row.get('table_name')}&column_name={row.get('name')}"
                ),
            }
            for row in columns
            if row.get("name")
            and (
                float(row.get("null_pct") or 0.0) > 0.0
                or float(row.get("blank_pct") or 0.0) > 0.0
            )
        ],
        key=lambda row: (
            -(float(row["null_pct"]) if row.get("null_pct") is not None else -1.0),
            -(float(row["blank_pct"]) if row.get("blank_pct") is not None else -1.0),
        ),
    )[:20]
    top_missing_row = missingness_rows[0] if missingness_rows else None

    failed_rules = []
    referential_rows = []
    for idx, rule in enumerate(quality_rules):
        result = quality_rule_results[idx] if idx < len(quality_rule_results) and isinstance(quality_rule_results[idx], dict) else {}
        status = str(result.get("status") or result.get("result_status") or rule.get("result_status") or "").strip().lower()
        if status == "failed":
            failed_rules.append(
                {
                    "rule_id": rule.get("rule_id"),
                    "rule_type": rule.get("rule_type"),
                    "severity": rule.get("severity"),
                    "table_name": rule.get("table_name"),
                    "column_name": rule.get("column_name"),
                    "column_alias": canonical_column_alias(rule.get("column_name")),
                    "violation_count": result.get("violation_count"),
                    "violation_pct": result.get("violation_pct"),
                    "evidence_path": f"{evidence_base}/rules/{rule.get('rule_id')}?tenant_id={tenant_id}&domain_id={domain_id}",
                }
            )
            if str(rule.get("rule_type") or "").strip().lower() == "referential_integrity":
                referential_rows.append(
                    {
                        "table_name": rule.get("table_name"),
                        "column_name": rule.get("column_name"),
                        "column_alias": canonical_column_alias(rule.get("column_name")),
                        "reference_table": rule.get("reference_table"),
                        "reference_column": rule.get("reference_column"),
                        "reference_column_alias": canonical_column_alias(rule.get("reference_column")),
                        "violation_count": result.get("violation_count"),
                        "violation_pct": result.get("violation_pct"),
                        "evidence_path": f"{evidence_base}/rules/{rule.get('rule_id')}?tenant_id={tenant_id}&domain_id={domain_id}",
                    }
                )
    failed_rules = sorted(
        failed_rules,
        key=lambda row: (
            str(row.get("severity") or ""),
            -int(row.get("violation_count") or 0),
            str(row.get("rule_type") or ""),
        ),
    )[:20]
    referential_rows = sorted(
        referential_rows,
        key=lambda row: -int(row.get("violation_count") or 0),
    )[:20]

    rule_type_counts = Counter(str(rule.get("rule_type") or "unknown") for rule in quality_rules)
    failure_type_counts = Counter(str(row.get("rule_type") or "unknown") for row in failed_rules)
    failure_severity_counts = Counter(str(row.get("severity") or "unknown") for row in failed_rules)
    duplicate_candidate_total = sum(int(row.get("duplicate_candidate_count") or 0) for row in duplicate_rows)
    remediation_summary = remediation_plan.get("summary") or {}
    executive_summary_rows = [
        {
            "metric_key": "quality_score",
            "label": "Quality Score",
            "value": quality_summary.get("average_table_trust_score"),
            "note": "quality gate passed" if (quality_summary.get("critical_issue_count") or 0) == 0 else "quality gate failed",
            "evidence_path": None,
        },
        {
            "metric_key": "critical_issues",
            "label": "Critical Issues",
            "value": quality_summary.get("critical_issue_count", 0),
            "note": "from trust scorecard summary",
            "evidence_path": None,
        },
        {
            "metric_key": "failed_rules",
            "label": "Failed Rules",
            "value": quality_summary.get("failed_rule_count", 0),
            "note": "validation rules with violations",
            "evidence_path": f"/data-quality/rules?tenant_id={tenant_id}&domain_id={domain_id}&run_id={run_id}&status=failed",
        },
        {
            "metric_key": "top_missing_field",
            "label": "Top Missing Field",
            "value": top_missing_row.get("column_name") if top_missing_row else None,
            "note": (
                f"{top_missing_row.get('null_pct'):.1f}% nulls"
                if top_missing_row and top_missing_row.get("null_pct") is not None
                else "no missingness rows"
            ),
            "evidence_path": top_missing_row.get("evidence_path") if top_missing_row else None,
        },
        {
            "metric_key": "duplicate_candidates",
            "label": "Duplicate Candidates",
            "value": duplicate_candidate_total,
            "note": "across profiled tables",
            "evidence_path": f"/data-quality/duplicates?tenant_id={tenant_id}&domain_id={domain_id}&run_id={run_id}",
        },
        {
            "metric_key": "recommended_actions",
            "label": "Recommended Actions",
            "value": remediation_summary.get("action_count", 0),
            "note": f"{int(remediation_summary.get('critical_action_count', 0) or 0)} critical",
            "evidence_path": f"/data-quality/remediation?tenant_id={tenant_id}&domain_id={domain_id}&run_id={run_id}",
        },
        {
            "metric_key": "run_id",
            "label": "Run ID",
            "value": run_id,
            "note": None,
            "evidence_path": f"/data-quality/runs/{run_id}",
        },
        {
            "metric_key": "dashboard_type",
            "label": "Dashboard Type",
            "value": "data_quality",
            "note": "active",
            "evidence_path": f"/data-quality/runs/{run_id}/dashboard",
        },
    ]

    chart_plan: list[dict[str, Any]] = []
    _append_chart_section(
        chart_plan,
        {
            "chart_key": "executive_summary",
            "title": "Executive Summary",
            "chart_type": "summary_cards",
            "data_source": "quantyx_data_quality_run_summary",
            "display_columns": [
                _display_column("metric_key", "Metric Key"),
                _display_column("label", "Label"),
                _display_column("value", "Value"),
                _display_column("note", "Note"),
                _display_column("evidence_path", "Evidence Path"),
            ],
            "rows": executive_summary_rows,
            "summary": {
                "quality_score": quality_summary.get("average_table_trust_score"),
                "critical_issue_count": quality_summary.get("critical_issue_count", 0),
                "failed_rule_count": quality_summary.get("failed_rule_count", 0),
                "duplicate_candidate_count": duplicate_candidate_total,
                "recommended_action_count": remediation_summary.get("action_count", 0),
                "critical_recommended_action_count": remediation_summary.get("critical_action_count", 0),
                "run_id": run_id,
                "dashboard_type": "data_quality",
            },
        },
        include_when_empty=True,
    )
    _append_chart_section(
        chart_plan,
        {
            "chart_key": "data_trust_scorecard",
            "title": "Data Trust Score by Table",
            "chart_type": "horizontal_bar",
            "data_source": "quantyx_data_quality_table_artifacts",
            "x_field": "trust_score",
            "y_field": "table_name",
            "display_columns": [
                _display_column("table_name", "Table"),
                _display_column("trust_score", "Trust Score"),
                _display_column("completeness_score", "Completeness"),
                _display_column("validity_score", "Validity"),
                _display_column("referential_integrity_score", "Referential Integrity"),
                _display_column("freshness_score", "Freshness"),
                _display_column("duplicate_risk_score", "Duplicate Risk"),
                _display_column("row_count", "Row Count"),
            ],
            "rows": trust_rows,
            "summary": {
                "overall_trust_score": quality_summary.get("average_table_trust_score"),
                "critical_issue_count": quality_summary.get("critical_issue_count", 0),
                "warning_issue_count": quality_summary.get("warning_issue_count", 0),
            },
        },
    )
    _append_chart_section(
        chart_plan,
        {
            "chart_key": "missingness_heatmap",
            "title": "Columns with Highest Missingness",
            "chart_type": "table_heatmap",
            "data_source": "quantyx_data_quality_column_artifacts",
            "display_columns": [
                _display_column("table_name", "Table"),
                _display_column("column_name", "Physical Column"),
                _display_column("column_alias", "Semantic Alias"),
                _display_column("null_pct", "Null %"),
                _display_column("blank_pct", "Blank %"),
                _display_column("completeness_score", "Completeness"),
                _display_column("evidence_path", "Evidence Path"),
            ],
            "rows": missingness_rows,
            "summary": {"column_count": len(missingness_rows)},
        },
    )
    _append_chart_section(
        chart_plan,
        {
            "chart_key": "validation_rule_failures",
            "title": "Validation Rule Failures",
            "chart_type": "stacked_bar",
            "data_source": "quantyx_data_quality_rule_results",
            "display_columns": [
                _display_column("rule_id", "Rule ID"),
                _display_column("rule_type", "Rule Type"),
                _display_column("severity", "Severity"),
                _display_column("table_name", "Table"),
                _display_column("column_name", "Physical Column"),
                _display_column("column_alias", "Semantic Alias"),
                _display_column("violation_count", "Violations"),
                _display_column("violation_pct", "Violation %"),
                _display_column("evidence_path", "Evidence Path"),
            ],
            "rows": failed_rules,
            "summary": {
                "rule_count": len(quality_rules),
                "failed_rule_count": quality_summary.get("failed_rule_count", 0),
                "failure_type_counts": dict(failure_type_counts),
                "failure_severity_counts": dict(failure_severity_counts),
                "rule_type_counts": dict(rule_type_counts),
            },
        },
    )
    _append_chart_section(
        chart_plan,
        {
            "chart_key": "referential_integrity",
            "title": "Referential Integrity Violations",
            "chart_type": "table",
            "data_source": "quantyx_data_quality_rule_results",
            "display_columns": [
                _display_column("table_name", "Table"),
                _display_column("column_name", "Physical Column"),
                _display_column("column_alias", "Semantic Alias"),
                _display_column("reference_table", "Reference Table"),
                _display_column("reference_column", "Reference Column"),
                _display_column("reference_column_alias", "Reference Alias"),
                _display_column("violation_count", "Violations"),
                _display_column("violation_pct", "Violation %"),
                _display_column("evidence_path", "Evidence Path"),
            ],
            "rows": referential_rows,
            "summary": {"relationship_count": len(referential_rows)},
        },
    )
    _append_chart_section(
        chart_plan,
        {
            "chart_key": "duplicate_risk",
            "title": "Duplicate Risk by Table",
            "chart_type": "bar",
            "data_source": "quantyx_data_quality_table_artifacts",
            "display_columns": [
                _display_column("table_name", "Table"),
                _display_column("duplicate_candidate_count", "Duplicate Candidates"),
                _display_column("exact_duplicate_candidate_count", "Exact Candidates"),
                _display_column("fuzzy_duplicate_candidate_count", "Fuzzy Candidates"),
                _display_column("candidate_record_count", "Candidate Records"),
                _display_column("duplicate_risk_score", "Duplicate Risk"),
                _display_column("evidence_path", "Evidence Path"),
            ],
            "rows": duplicate_rows,
            "summary": {"table_count": len(duplicate_rows)},
        },
    )
    _append_chart_section(
        chart_plan,
        {
            "chart_key": "freshness_and_stability",
            "title": "Freshness Lag by Table",
            "chart_type": "bar",
            "data_source": "quantyx_data_quality_table_artifacts",
            "display_columns": [
                _display_column("table_name", "Table"),
                _display_column("freshness_column", "Physical Freshness Column"),
                _display_column("freshness_column_alias", "Semantic Freshness Alias"),
                _display_column("freshness_lag_days", "Freshness Lag Days"),
                _display_column("freshness_status", "Freshness Status"),
                _display_column("row_count_change_pct", "Row Count Change %"),
                _display_column("completeness_score_change", "Completeness Change"),
                _display_column("stability_status", "Stability Status"),
                _display_column("evidence_path", "Evidence Path"),
            ],
            "rows": freshness_rows,
            "summary": {
                "stale_table_count": quality_summary.get("stale_table_count", len([row for row in freshness_rows if row.get("freshness_status") == "stale"])),
                "stability_issue_count": quality_summary.get("stability_issue_count", len([row for row in freshness_rows if row.get("stability_status") == "changed"])),
            },
        },
    )
    _append_chart_section(
        chart_plan,
        {
            "chart_key": "recommended_actions",
            "title": "Recommended Actions",
            "chart_type": "table",
            "data_source": "quantyx_data_quality_remediation",
            "display_columns": [
                _display_column("priority", "Priority"),
                _display_column("action_type", "Action Type"),
                _display_column("title", "Title"),
                _display_column("table_name", "Table"),
                _display_column("column_name", "Column"),
                _display_column("recommended_action", "Recommended Action"),
                _display_column("evidence_path", "Evidence Path"),
            ],
            "rows": remediation_plan.get("actions") or [],
            "summary": remediation_plan.get("summary") or {},
        },
    )

    dashboard_title = f"{str(domain_id).replace('_', ' ').replace('-', ' ').title()} Data Quality Dashboard"
    return {
        "title": dashboard_title,
        "description": "System-generated dashboard summarizing trust, missingness, validation failures, referential integrity, duplicate risk, and freshness.",
        "summary_view": {
            "title": "Executive Summary",
            "rows": executive_summary_rows,
            "summary": {
                "quality_score": quality_summary.get("average_table_trust_score"),
                "critical_issue_count": quality_summary.get("critical_issue_count", 0),
                "failed_rule_count": quality_summary.get("failed_rule_count", 0),
                "duplicate_candidate_count": duplicate_candidate_total,
                "recommended_action_count": remediation_summary.get("action_count", 0),
                "critical_recommended_action_count": remediation_summary.get("critical_action_count", 0),
                "run_id": run_id,
                "dashboard_type": "data_quality",
            },
        },
        "chart_plan": chart_plan,
        "quality": {
            "quality_score": quality_summary.get("average_table_trust_score"),
            "gate_passed": (quality_summary.get("critical_issue_count") or 0) == 0,
        },
        "summary": {
            "run_id": run_id,
            "profiled_tables": quality_summary.get("profiled_tables", 0),
            "profiled_columns": quality_summary.get("profiled_columns", 0),
            "failed_rule_count": quality_summary.get("failed_rule_count", 0),
            "duplicate_candidate_count": quality_summary.get("duplicate_candidate_count", 0),
            "remediation_action_count": (remediation_plan.get("summary") or {}).get("action_count", 0),
            "executive_summary": executive_summary_rows,
        },
    }


def create_data_quality_dashboard(
    settings: Settings,
    *,
    tenant_id: str,
    domain_id: str,
    run_id: str,
    profiling: dict[str, Any],
    quality_tables: list[dict[str, Any]] | None = None,
    quality_summary: dict[str, Any],
    quality_rules: list[dict[str, Any]] | None = None,
    quality_rule_results: list[dict[str, Any]] | None = None,
    duplicate_candidates: list[dict[str, Any]] | None = None,
    freshness_results: list[dict[str, Any]] | None = None,
    enrichment_opportunities: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    spec = build_data_quality_dashboard_spec(
        tenant_id=tenant_id,
        run_id=run_id,
        domain_id=domain_id,
        profiling=profiling,
        quality_tables=quality_tables,
        quality_summary=quality_summary,
        quality_rules=quality_rules,
        quality_rule_results=quality_rule_results,
        duplicate_candidates=duplicate_candidates,
        freshness_results=freshness_results,
        enrichment_opportunities=enrichment_opportunities,
    )
    dashboard = create_dashboard(
        settings,
        tenant_id=tenant_id,
        domain_id=domain_id,
        name=spec.get("title") or "Data Quality Dashboard",
        description=spec.get("description"),
        dashboard_type="data_quality",
        run_id=run_id,
        chart_plan=spec.get("chart_plan") or [],
        quality_score=spec.get("quality", {}).get("quality_score"),
        quality_gate_passed=spec.get("quality", {}).get("gate_passed"),
        created_by="DataQualityDashboardAgent",
    )
    return {
        "dashboard_id": dashboard.get("dashboard_id"),
        "dashboard_title": spec.get("title"),
        "summary_view": spec.get("summary_view") or {},
        "chart_plan": spec.get("chart_plan") or [],
        "quality_score": spec.get("quality", {}).get("quality_score"),
        "quality_gate_passed": spec.get("quality", {}).get("gate_passed"),
        "remediation_action_count": (spec.get("summary") or {}).get("remediation_action_count", 0),
        "critical_remediation_action_count": ((spec.get("summary_view") or {}).get("summary") or {}).get("critical_recommended_action_count", 0),
    }
