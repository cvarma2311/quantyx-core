from __future__ import annotations

from collections import Counter
from typing import Any
from urllib.parse import urlencode

from services.ai.config import Settings
from services.ai.data_quality_store import (
    get_quality_table_detail,
    list_quality_duplicate_candidates,
    list_quality_enrichment_opportunities,
    list_quality_dataset_stages,
    list_quality_rules,
    list_quality_stage_row_outcomes,
    list_quality_tables,
)


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _priority_rank(value: str | None) -> int:
    priority = str(value or "").strip().lower()
    if priority == "critical":
        return 0
    if priority == "warning":
        return 1
    if priority == "info":
        return 2
    return 3


def _build_evidence_path(
    path: str,
    *,
    tenant_id: str,
    domain_id: str,
    run_id: str | None = None,
    extra: dict[str, Any] | None = None,
) -> str:
    params: dict[str, Any] = {"tenant_id": tenant_id}
    if domain_id:
        params["domain_id"] = domain_id
    if run_id:
        params["run_id"] = run_id
    for key, value in (extra or {}).items():
        if value is None or value == "":
            continue
        params[key] = value
    return f"{path}?{urlencode(params)}"


def _recommended_rule_action(rule_type: str, table_name: str, column_name: str | None) -> str:
    column_ref = f"{table_name}.{column_name}" if column_name else table_name
    normalized = str(rule_type or "").strip().lower()
    if normalized == "referential_integrity":
        return f"Repair orphaned keys in {column_ref} or align the parent-child load order before downstream publishing."
    if normalized in {"not_null", "not_blank"}:
        return f"Backfill or enrich {column_ref} before the record is treated as production-ready."
    if normalized in {"allowed_values", "regex_pattern", "email_pattern"}:
        return f"Normalize invalid values in {column_ref} and tighten upstream input validation."
    if normalized in {"numeric_min", "numeric_max"}:
        return f"Review threshold logic for {column_ref} and correct out-of-range records."
    return f"Inspect the failing rows for {column_ref} and remediate the source mapping or source-system rule."


def _component_owner(component: str) -> str:
    normalized = str(component or "").strip().lower()
    if normalized in {"freshness", "stability"}:
        return "Data operations"
    if normalized in {"referential_integrity", "validity"}:
        return "Source system owner"
    if normalized in {"duplicate_risk", "uniqueness"}:
        return "Data steward"
    if normalized in {"completeness", "enrichment_readiness"}:
        return "Data steward"
    return "Domain owner"


def _action(
    *,
    key: str,
    priority: str,
    action_type: str,
    title: str,
    recommended_action: str,
    tenant_id: str,
    domain_id: str,
    run_id: str,
    table_name: str | None = None,
    column_name: str | None = None,
    issue_summary: str | None = None,
    metric_value: Any = None,
    metric_unit: str | None = None,
    evidence_type: str | None = None,
    evidence_path: str | None = None,
    trust_component: str | None = None,
    trust_score: Any = None,
    owner_hint: str | None = None,
    source_refs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "action_key": key,
        "priority": priority,
        "priority_rank": _priority_rank(priority),
        "action_type": action_type,
        "title": title,
        "recommended_action": recommended_action,
        "issue_summary": issue_summary,
        "tenant_id": tenant_id,
        "domain_id": domain_id,
        "run_id": run_id,
        "table_name": table_name,
        "column_name": column_name,
        "metric_value": metric_value,
        "metric_unit": metric_unit,
        "evidence_type": evidence_type,
        "evidence_path": evidence_path,
        "trust_component": trust_component,
        "trust_score": trust_score,
        "owner_hint": owner_hint,
        "source_refs": source_refs or {},
    }


def derive_data_quality_remediation_plan(
    *,
    tenant_id: str,
    domain_id: str,
    run_id: str,
    tables: list[dict[str, Any]] | None = None,
    table_details: list[dict[str, Any]] | None = None,
    rules: list[dict[str, Any]] | None = None,
    duplicates: list[dict[str, Any]] | None = None,
    opportunities: list[dict[str, Any]] | None = None,
    dataset_stages: list[dict[str, Any]] | None = None,
    row_outcomes: list[dict[str, Any]] | None = None,
    trends: list[dict[str, Any]] | None = None,
    limit: int = 25,
) -> dict[str, Any]:
    tables = [item for item in (tables or []) if isinstance(item, dict)]
    table_details = [item for item in (table_details or []) if isinstance(item, dict)]
    rules = [item for item in (rules or []) if isinstance(item, dict)]
    duplicates = [item for item in (duplicates or []) if isinstance(item, dict)]
    opportunities = [item for item in (opportunities or []) if isinstance(item, dict)]
    dataset_stages = [item for item in (dataset_stages or []) if isinstance(item, dict)]
    row_outcomes = [item for item in (row_outcomes or []) if isinstance(item, dict)]
    trends = [item for item in (trends or []) if isinstance(item, dict)]

    actions: list[dict[str, Any]] = []
    action_keys: set[str] = set()

    def add_action(payload: dict[str, Any]) -> None:
        key = str(payload.get("action_key") or "").strip()
        if not key or key in action_keys:
            return
        action_keys.add(key)
        actions.append(payload)

    for detail in table_details:
        table_name = str(detail.get("table_name") or "").strip()
        if not table_name:
            continue
        trust_score = _safe_float(detail.get("trust_score"))
        for column in detail.get("columns") or []:
            if not isinstance(column, dict):
                continue
            column_name = str(column.get("column_name") or "").strip()
            if not column_name:
                continue
            null_pct = _safe_float(column.get("null_pct")) or 0.0
            blank_pct = _safe_float(column.get("blank_pct")) or 0.0
            missing_pressure = max(null_pct, blank_pct)
            if missing_pressure < 10.0:
                continue
            priority = "critical" if missing_pressure >= 30.0 else "warning"
            add_action(
                _action(
                    key=f"missingness:{table_name}:{column_name}",
                    priority=priority,
                    action_type="missingness_backfill",
                    title=f"Backfill missing values in {table_name}.{column_name}",
                    recommended_action=(
                        f"Backfill or enrich {table_name}.{column_name} before publishing downstream records. "
                        f"If the field is derivable, generate an enrichment proposal first."
                    ),
                    tenant_id=tenant_id,
                    domain_id=domain_id,
                    run_id=run_id,
                    table_name=table_name,
                    column_name=column_name,
                    issue_summary=f"{column_name} is {null_pct:.1f}% null and {blank_pct:.1f}% blank.",
                    metric_value=missing_pressure,
                    metric_unit="missing_pct",
                    evidence_type="missingness",
                    evidence_path=_build_evidence_path(
                        "/data-quality/evidence/missingness",
                        tenant_id=tenant_id,
                        domain_id=domain_id,
                        run_id=run_id,
                        extra={"table_name": table_name, "column_name": column_name, "include_blank": "true"},
                    ),
                    trust_component="completeness",
                    trust_score=trust_score,
                    owner_hint="Data steward",
                    source_refs={"table_name": table_name, "column_name": column_name},
                )
            )

    for rule in rules:
        status = str(rule.get("result_status") or rule.get("status") or "").strip().lower()
        if status not in {"failed", "error"}:
            continue
        table_name = str(rule.get("table_name") or "").strip()
        column_name = str(rule.get("column_name") or "").strip() or None
        rule_id = str(rule.get("rule_id") or "").strip()
        rule_type = str(rule.get("rule_type") or "rule_failure").strip()
        violation_count = int(rule.get("violation_count") or 0)
        violation_pct = _safe_float(rule.get("violation_pct")) or 0.0
        priority = "critical" if str(rule.get("severity") or "").strip().lower() == "critical" or violation_pct >= 20.0 else "warning"
        trust_component = "referential_integrity" if rule_type == "referential_integrity" else "validity"
        add_action(
            _action(
                key=f"rule:{rule_id}",
                priority=priority,
                action_type=f"{rule_type}_remediation",
                title=f"Resolve {rule_type} failures in {table_name}",
                recommended_action=_recommended_rule_action(rule_type, table_name, column_name),
                tenant_id=tenant_id,
                domain_id=domain_id,
                run_id=run_id,
                table_name=table_name,
                column_name=column_name,
                issue_summary=f"{violation_count} violating rows ({violation_pct:.1f}%).",
                metric_value=violation_pct or violation_count,
                metric_unit="violation_pct" if violation_pct else "violation_count",
                evidence_type="rule_failure",
                evidence_path=_build_evidence_path(
                    f"/data-quality/evidence/rules/{rule_id}",
                    tenant_id=tenant_id,
                    domain_id=domain_id,
                ),
                trust_component=trust_component,
                owner_hint=_component_owner(trust_component),
                source_refs={"rule_id": rule_id, "rule_type": rule_type},
            )
        )

    for item in duplicates:
        candidate_id = str(item.get("candidate_id") or "").strip()
        table_name = str(item.get("table_name") or "").strip()
        candidate_record_count = int(item.get("candidate_record_count") or 0)
        confidence = _safe_float(item.get("confidence")) or 0.0
        priority = "critical" if candidate_record_count >= 25 or confidence >= 0.98 else "warning"
        add_action(
            _action(
                key=f"duplicate:{candidate_id}",
                priority=priority,
                action_type="duplicate_resolution",
                title=f"Review duplicate cluster in {table_name}",
                recommended_action="Review the duplicate cluster, choose survivorship rules, and prevent the duplicate pattern at the source.",
                tenant_id=tenant_id,
                domain_id=domain_id,
                run_id=run_id,
                table_name=table_name,
                issue_summary=f"{candidate_record_count} candidate records with confidence {confidence:.2f}.",
                metric_value=candidate_record_count,
                metric_unit="candidate_record_count",
                evidence_type="duplicates",
                evidence_path=_build_evidence_path(
                    f"/data-quality/evidence/duplicates/{candidate_id}",
                    tenant_id=tenant_id,
                    domain_id=domain_id,
                ),
                trust_component="duplicate_risk",
                owner_hint=_component_owner("duplicate_risk"),
                source_refs={"candidate_id": candidate_id, "duplicate_type": item.get("duplicate_type")},
            )
        )

    filter_rejected_counts: dict[str, int] = Counter(
        str(row.get("stage_id") or "")
        for row in row_outcomes
        if str(row.get("reason_code") or "").strip() == "filter_rejected"
    )
    for stage in dataset_stages:
        if str(stage.get("stage_type") or "").strip() != "filter":
            continue
        stage_id = str(stage.get("stage_id") or "").strip()
        rejected_row_count = int(stage.get("rejected_row_count") or filter_rejected_counts.get(stage_id) or 0)
        input_row_count = int(stage.get("input_row_count") or 0)
        if rejected_row_count <= 0:
            continue
        rejected_pct = (rejected_row_count / input_row_count * 100.0) if input_row_count > 0 else None
        priority = "critical" if (rejected_pct or 0.0) >= 30.0 else "warning"
        expression_text = str(((stage.get("expression") or {}).get("expression_text") or "")).strip()
        add_action(
            _action(
                key=f"filter:{stage_id}",
                priority=priority,
                action_type="filter_review",
                title=f"Review filter impact in {stage.get('stage_name')}",
                recommended_action=(
                    f"Review the filter `{expression_text}` and confirm whether this rejection rate is intentional. "
                    "If the filter is business-critical, document it as a gating rule; otherwise consider soft-fail handling or upstream normalization."
                ),
                tenant_id=tenant_id,
                domain_id=domain_id,
                run_id=run_id,
                table_name=str((stage.get("output_dataset") or "")).strip() or None,
                issue_summary=(
                    f"{rejected_row_count} rows were rejected"
                    + (f" ({rejected_pct:.1f}%)." if rejected_pct is not None else ".")
                ),
                metric_value=rejected_pct if rejected_pct is not None else rejected_row_count,
                metric_unit="rejected_pct" if rejected_pct is not None else "rejected_count",
                evidence_type="stage_filter_rejected",
                evidence_path=_build_evidence_path(
                    f"/data-quality/evidence/stages/{stage_id}",
                    tenant_id=tenant_id,
                    domain_id=domain_id,
                ),
                trust_component="validity",
                owner_hint="Domain owner",
                source_refs={"stage_id": stage_id, "stage_name": stage.get("stage_name"), "expression_text": expression_text},
            )
        )

    for table in tables:
        table_name = str(table.get("table_name") or "").strip()
        if not table_name:
            continue
        summary = table.get("summary_json") or {}
        freshness = summary.get("freshness_analysis") or {}
        stability = summary.get("stability_analysis") or {}
        trust_components = summary.get("trust_components") or {}
        trust_explanations = summary.get("trust_component_explanations") or {}
        trust_score = _safe_float(table.get("trust_score"))

        if freshness.get("freshness_status") == "stale":
            lag_days = _safe_float(freshness.get("freshness_lag_days")) or 0.0
            add_action(
                _action(
                    key=f"freshness:{table_name}",
                    priority="critical" if lag_days >= 7.0 else "warning",
                    action_type="freshness_recovery",
                    title=f"Restore freshness for {table_name}",
                    recommended_action="Check upstream refresh cadence, failed loads, and the freshness SLA before publishing this table.",
                    tenant_id=tenant_id,
                    domain_id=domain_id,
                    run_id=run_id,
                    table_name=table_name,
                    issue_summary=f"Freshness lag is {lag_days:.1f} days.",
                    metric_value=lag_days,
                    metric_unit="lag_days",
                    evidence_type="freshness",
                    evidence_path=_build_evidence_path(
                        f"/data-quality/evidence/freshness/{table_name}",
                        tenant_id=tenant_id,
                        domain_id=domain_id,
                        run_id=run_id,
                    ),
                    trust_component="freshness",
                    trust_score=trust_score,
                    owner_hint=_component_owner("freshness"),
                    source_refs={"table_name": table_name, "freshness_column": freshness.get("freshness_column")},
                )
            )
        if stability.get("stability_status") == "changed":
            row_count_change_pct = _safe_float(stability.get("row_count_change_pct")) or 0.0
            add_action(
                _action(
                    key=f"stability:{table_name}",
                    priority="warning",
                    action_type="stability_review",
                    title=f"Review baseline drift for {table_name}",
                    recommended_action="Compare this run with the previous baseline and confirm the volume and completeness movement is expected.",
                    tenant_id=tenant_id,
                    domain_id=domain_id,
                    run_id=run_id,
                    table_name=table_name,
                    issue_summary=(
                        f"Row count changed {row_count_change_pct:.1f}% and completeness changed "
                        f"{(_safe_float(stability.get('completeness_score_change')) or 0.0):.1f}."
                    ),
                    metric_value=row_count_change_pct,
                    metric_unit="row_count_change_pct",
                    evidence_type="freshness",
                    evidence_path=_build_evidence_path(
                        f"/data-quality/evidence/freshness/{table_name}",
                        tenant_id=tenant_id,
                        domain_id=domain_id,
                        run_id=run_id,
                    ),
                    trust_component="stability",
                    trust_score=trust_score,
                    owner_hint=_component_owner("stability"),
                    source_refs={"table_name": table_name, "baseline_quality_run_id": stability.get("baseline_quality_run_id")},
                )
            )

        weakest_component = None
        weakest_score = None
        for key, value in trust_components.items():
            score = _safe_float(value)
            if score is None:
                continue
            if weakest_score is None or score < weakest_score:
                weakest_score = score
                weakest_component = str(key)
        if weakest_component and weakest_score is not None and weakest_score < 80.0:
            add_action(
                _action(
                    key=f"trust:{table_name}:{weakest_component}",
                    priority="critical" if weakest_score < 60.0 else "warning",
                    action_type=f"{weakest_component}_trust_recovery",
                    title=f"Recover {weakest_component.replace('_', ' ')} trust in {table_name}",
                    recommended_action=(
                        str(trust_explanations.get(weakest_component) or "").strip()
                        or f"Resolve the lowest trust component for {table_name} before downstream release."
                    ),
                    tenant_id=tenant_id,
                    domain_id=domain_id,
                    run_id=run_id,
                    table_name=table_name,
                    issue_summary=f"Weakest trust component is {weakest_component} at {weakest_score:.1f}.",
                    metric_value=weakest_score,
                    metric_unit="trust_component_score",
                    evidence_type="table_summary",
                    evidence_path=_build_evidence_path(
                        f"/data-quality/tables/{table_name}",
                        tenant_id=tenant_id,
                        domain_id=domain_id,
                        run_id=run_id,
                    ),
                    trust_component=weakest_component,
                    trust_score=trust_score,
                    owner_hint=_component_owner(weakest_component),
                    source_refs={"table_name": table_name, "trust_component": weakest_component},
                )
        )

    for item in trends:
        trend_status = str(item.get("trend_status") or "").strip().lower()
        if trend_status != "worsened":
            continue
        object_type = str(item.get("object_type") or "").strip()
        object_name = str(item.get("object_name") or item.get("object_key") or "").strip()
        metric_name = str(item.get("metric_name") or "").strip()
        directionality = str(item.get("directionality") or "").strip()
        delta_value = item.get("delta_value")
        delta_pct = item.get("delta_pct")
        title = f"Investigate worsening {metric_name} for {object_name or object_type}"
        recommended_action = (
            f"Review why {metric_name} worsened for {object_name or object_type} compared with the prior monitoring run "
            f"and decide whether to remediate upstream data, tune rules, or reset the baseline."
        )
        evidence_path = _build_evidence_path(
            "/data-quality/trends",
            tenant_id=tenant_id,
            domain_id=domain_id,
            run_id=run_id,
        )
        if object_type == "table" and object_name:
            evidence_path = _build_evidence_path(
                f"/data-quality/trends/tables/{object_name}",
                tenant_id=tenant_id,
                domain_id=domain_id,
                run_id=run_id,
            )
        elif object_type == "rule" and str(item.get("object_key") or "").strip():
            evidence_path = _build_evidence_path(
                f"/data-quality/trends/rules/{item.get('object_key')}",
                tenant_id=tenant_id,
                domain_id=domain_id,
                run_id=run_id,
            )
        add_action(
            _action(
                key=f"trend:{object_type}:{item.get('object_key')}:{metric_name}",
                priority="warning" if directionality != "status_transition" else "critical",
                action_type="trend_regression_review",
                title=title,
                recommended_action=recommended_action,
                tenant_id=tenant_id,
                domain_id=domain_id,
                run_id=run_id,
                table_name=object_name if object_type == "table" else None,
                issue_summary=f"Delta={delta_value}; delta_pct={delta_pct}.",
                metric_value=delta_pct if delta_pct is not None else delta_value,
                metric_unit="delta_pct" if delta_pct is not None else "delta",
                evidence_type="trend_regression",
                evidence_path=evidence_path,
                owner_hint="Data steward",
                source_refs={"object_type": object_type, "object_key": item.get("object_key"), "metric_name": metric_name},
            )
        )

    for item in opportunities:
        opportunity_id = str(item.get("opportunity_id") or "").strip()
        table_name = str(item.get("table_name") or "").strip()
        target_column = str(item.get("target_column") or "").strip()
        if not opportunity_id or not table_name or not target_column:
            continue
        missing_count = int(item.get("missing_count") or 0)
        confidence = _safe_float(item.get("confidence")) or 0.0
        priority = "warning" if missing_count >= 25 or confidence >= 0.85 else "info"
        add_action(
            _action(
                key=f"enrichment:{opportunity_id}",
                priority=priority,
                action_type="enrichment_proposal",
                title=f"Generate enrichment proposal for {table_name}.{target_column}",
                recommended_action=(
                    f"Generate a staged enrichment proposal for {table_name}.{target_column} using "
                    f"{', '.join(item.get('source_columns_json') or item.get('source_columns') or []) or 'available row context'}."
                ),
                tenant_id=tenant_id,
                domain_id=domain_id,
                run_id=run_id,
                table_name=table_name,
                column_name=target_column,
                issue_summary=f"{missing_count} rows can potentially be completed through staged enrichment.",
                metric_value=missing_count,
                metric_unit="missing_count",
                evidence_type="enrichment_opportunity",
                evidence_path=_build_evidence_path(
                    "/data-quality/enrichment/opportunities",
                    tenant_id=tenant_id,
                    domain_id=domain_id,
                    run_id=run_id,
                ),
                trust_component="enrichment_readiness",
                owner_hint=_component_owner("enrichment_readiness"),
                source_refs={"opportunity_id": opportunity_id},
            )
        )

    actions.sort(
        key=lambda item: (
            int(item.get("priority_rank") or 99),
            -(_safe_float(item.get("metric_value")) or 0.0),
            str(item.get("table_name") or ""),
            str(item.get("column_name") or ""),
            str(item.get("action_type") or ""),
        )
    )
    limited_actions = actions[: max(1, min(int(limit or 25), 200))]
    priority_counts = Counter(str(item.get("priority") or "unknown") for item in actions)
    action_type_counts = Counter(str(item.get("action_type") or "unknown") for item in actions)
    return {
        "summary": {
            "action_count": len(actions),
            "critical_action_count": priority_counts.get("critical", 0),
            "warning_action_count": priority_counts.get("warning", 0),
            "info_action_count": priority_counts.get("info", 0),
            "priority_counts": dict(priority_counts),
            "action_type_counts": dict(action_type_counts),
        },
        "actions": limited_actions,
    }


def build_data_quality_remediation_plan(
    settings: Settings,
    *,
    tenant_id: str,
    domain_id: str,
    run_id: str,
    limit: int = 25,
) -> dict[str, Any]:
    tables = list_quality_tables(settings, tenant_id=tenant_id, domain_id=domain_id, run_id=run_id, limit=1200)
    table_details = [
        detail
        for table in tables
        if (detail := get_quality_table_detail(settings, tenant_id=tenant_id, domain_id=domain_id, table_name=table.get("table_name"), run_id=run_id))
    ]
    rules = list_quality_rules(settings, tenant_id=tenant_id, domain_id=domain_id, run_id=run_id, limit=1200)
    duplicates = list_quality_duplicate_candidates(settings, tenant_id=tenant_id, domain_id=domain_id, run_id=run_id, limit=1200)
    opportunities = list_quality_enrichment_opportunities(settings, tenant_id=tenant_id, domain_id=domain_id, run_id=run_id, limit=1200)
    dataset_stages = list_quality_dataset_stages(settings, tenant_id=tenant_id, domain_id=domain_id, run_id=run_id, limit=1200)
    row_outcomes = list_quality_stage_row_outcomes(settings, tenant_id=tenant_id, domain_id=domain_id, run_id=run_id, limit=1200)
    return derive_data_quality_remediation_plan(
        tenant_id=tenant_id,
        domain_id=domain_id,
        run_id=run_id,
        tables=tables,
        table_details=table_details,
        rules=rules,
        duplicates=duplicates,
        opportunities=opportunities,
        dataset_stages=dataset_stages,
        row_outcomes=row_outcomes,
        limit=limit,
    )
