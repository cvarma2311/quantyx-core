from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from hashlib import sha1
import json
from typing import Any

from services.ai.data_quality_trends import rule_logical_key, stage_logical_key


ISSUE_STATUS_VALUES = {"open", "in_progress", "deferred", "resolved", "accepted_risk"}
_ACTIVE_ISSUE_STATUSES = {"open", "in_progress", "deferred"}
_SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _severity_from_rule(rule: dict[str, Any]) -> str:
    raw = _normalize_text(rule.get("severity")).lower()
    if raw in {"critical", "error"}:
        return "critical"
    if raw in {"warning", "high"}:
        return "high"
    if raw in {"info", "low"}:
        return "low"
    return "medium"


def _severity_from_ratio(value: float | None, *, critical: float, high: float, medium: float) -> str:
    ratio = float(value or 0.0)
    if ratio >= critical:
        return "critical"
    if ratio >= high:
        return "high"
    if ratio >= medium:
        return "medium"
    return "low"


def _due_at_for_severity(severity: str) -> str | None:
    days_by_severity = {"critical": 2, "high": 5, "medium": 10, "low": 20}
    days = days_by_severity.get(str(severity or "").strip().lower())
    if not days:
        return None
    return (_utc_now() + timedelta(days=days)).isoformat()


def _owner_hint(issue_type: str) -> str:
    lowered = str(issue_type or "").strip().lower()
    if lowered in {"duplicate_risk", "failed_rule", "filter_loss_concentration"}:
        return "data_steward"
    if lowered in {"stale_dataset", "stability_change"}:
        return "source_system_owner"
    if lowered in {"join_exception", "publish_readiness_blocker", "trend_regression"}:
        return "domain_owner"
    return "data_steward"


def _issue_key(
    *,
    trend_scope_key: str | None,
    issue_type: str,
    object_type: str,
    object_key: str,
) -> str:
    payload = {
        "trend_scope_key": str(trend_scope_key or "").strip().lower(),
        "issue_type": str(issue_type or "").strip().lower(),
        "object_type": str(object_type or "").strip().lower(),
        "object_key": str(object_key or "").strip().lower(),
    }
    return f"dqissuekey_{sha1(json.dumps(payload, sort_keys=True).encode('utf-8')).hexdigest()[:20]}"


def _make_issue(
    *,
    trend_scope_key: str | None,
    issue_type: str,
    title: str,
    severity: str,
    object_type: str,
    object_key: str,
    table_name: str | None = None,
    column_name: str | None = None,
    stage_id: str | None = None,
    evidence_path: str | None = None,
    recommendation: str | None = None,
    summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    severity = str(severity or "medium").strip().lower() or "medium"
    return {
        "issue_key": _issue_key(
            trend_scope_key=trend_scope_key,
            issue_type=issue_type,
            object_type=object_type,
            object_key=object_key,
        ),
        "issue_type": issue_type,
        "title": title,
        "severity": severity,
        "object_type": object_type,
        "object_key": object_key,
        "table_name": table_name,
        "column_name": column_name,
        "stage_id": stage_id,
        "owner_id": _owner_hint(issue_type),
        "status": "open",
        "due_at": _due_at_for_severity(severity),
        "evidence_path": evidence_path,
        "recommendation_json": {"text": recommendation} if recommendation else {},
        "summary_json": summary or {},
    }


def derive_data_quality_issues(
    *,
    tenant_id: str,
    domain_id: str,
    run_id: str,
    trend_scope_key: str | None,
    quality_summary: dict[str, Any],
    rules: list[dict[str, Any]] | None = None,
    duplicate_candidates: list[dict[str, Any]] | None = None,
    freshness_results: list[dict[str, Any]] | None = None,
    dataset_stages: list[dict[str, Any]] | None = None,
    join_artifacts: list[dict[str, Any]] | None = None,
    final_dataset: dict[str, Any] | None = None,
    trends: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    rules = [row for row in (rules or []) if isinstance(row, dict)]
    duplicate_candidates = [row for row in (duplicate_candidates or []) if isinstance(row, dict)]
    freshness_results = [row for row in (freshness_results or []) if isinstance(row, dict)]
    dataset_stages = [row for row in (dataset_stages or []) if isinstance(row, dict)]
    join_artifacts = [row for row in (join_artifacts or []) if isinstance(row, dict)]
    final_dataset = dict(final_dataset or {})
    trends = [row for row in (trends or []) if isinstance(row, dict)]
    issues: list[dict[str, Any]] = []

    for rule in rules:
        status = _normalize_text(rule.get("result_status") or rule.get("status")).lower()
        if status != "failed":
            continue
        issue_rule_key = rule_logical_key(rule)
        violation_count = int(rule.get("violation_count") or 0)
        violation_pct = rule.get("violation_pct")
        issues.append(
            _make_issue(
                trend_scope_key=trend_scope_key,
                issue_type="failed_rule",
                title=_normalize_text(rule.get("rule_label")) or f"Failed {rule.get('rule_type')} rule",
                severity=_severity_from_rule(rule),
                object_type="rule",
                object_key=issue_rule_key,
                table_name=_normalize_text(rule.get("table_name")) or None,
                column_name=_normalize_text(rule.get("column_name")) or None,
                evidence_path=f"/data-quality/evidence/rules/{rule.get('rule_id')}?tenant_id={tenant_id}&domain_id={domain_id}",
                recommendation=f"Review and resolve {violation_count} failing records for this validation control before publication.",
                summary={
                    "run_id": run_id,
                    "rule_id": rule.get("rule_id"),
                    "rule_type": rule.get("rule_type"),
                    "violation_count": violation_count,
                    "violation_pct": violation_pct,
                },
            )
        )

    duplicate_counts = Counter(_normalize_text(item.get("table_name")) for item in duplicate_candidates if _normalize_text(item.get("table_name")))
    for table_name, count in duplicate_counts.items():
        severity = "high" if count >= 10 else "medium"
        first_candidate = next((item for item in duplicate_candidates if _normalize_text(item.get("table_name")) == table_name), {})
        issues.append(
            _make_issue(
                trend_scope_key=trend_scope_key,
                issue_type="duplicate_risk",
                title=f"Duplicate candidates detected in {table_name}",
                severity=severity,
                object_type="table",
                object_key=table_name,
                table_name=table_name,
                evidence_path=f"/data-quality/duplicates?tenant_id={tenant_id}&domain_id={domain_id}&run_id={run_id}",
                recommendation="Review duplicate candidates and standardize matching keys before downstream publication.",
                summary={
                    "run_id": run_id,
                    "duplicate_candidate_count": count,
                    "candidate_id": first_candidate.get("candidate_id"),
                },
            )
        )

    for row in freshness_results:
        table_name = _normalize_text(row.get("table_name"))
        if not table_name:
            continue
        freshness_status = _normalize_text(row.get("freshness_status")).lower()
        if freshness_status == "stale":
            lag = row.get("freshness_lag_days")
            issues.append(
                _make_issue(
                    trend_scope_key=trend_scope_key,
                    issue_type="stale_dataset",
                    title=f"Dataset freshness SLA breached for {table_name}",
                    severity="high",
                    object_type="table",
                    object_key=table_name,
                    table_name=table_name,
                    evidence_path=f"/data-quality/evidence/freshness/{table_name}?tenant_id={tenant_id}&domain_id={domain_id}",
                    recommendation="Check upstream refresh cadence, failed loads, and freshness SLA alignment.",
                    summary={
                        "run_id": run_id,
                        "freshness_lag_days": lag,
                        "freshness_column": row.get("freshness_column"),
                    },
                )
            )
        stability_status = _normalize_text(row.get("stability_status")).lower()
        if stability_status == "changed":
            issues.append(
                _make_issue(
                    trend_scope_key=trend_scope_key,
                    issue_type="stability_change",
                    title=f"Unexpected stability change in {table_name}",
                    severity="medium",
                    object_type="table",
                    object_key=f"{table_name}_stability",
                    table_name=table_name,
                    evidence_path=f"/data-quality/evidence/freshness/{table_name}?tenant_id={tenant_id}&domain_id={domain_id}",
                    recommendation="Investigate row-count or completeness drift against the prior baseline before publishing.",
                    summary={
                        "run_id": run_id,
                        "row_count_change_pct": row.get("row_count_change_pct"),
                        "completeness_score_change": row.get("completeness_score_change"),
                    },
                )
            )

    for join in join_artifacts:
        join_name = _normalize_text(join.get("join_name")) or f"{join.get('left_table')}->{join.get('right_table')}"
        unmatched_left = int(join.get("unmatched_left_row_count") or 0)
        unmatched_right = int(join.get("unmatched_right_row_count") or 0)
        duplicate_matches = int(join.get("duplicate_match_count") or 0)
        evidence_path = (
            f"/data-quality/evidence/joins/{join.get('join_artifact_id')}?tenant_id={tenant_id}&domain_id={domain_id}"
            if join.get("join_artifact_id")
            else None
        )
        if unmatched_left > 0 or unmatched_right > 0:
            impact = max(unmatched_left, unmatched_right)
            severity = "critical" if impact >= 100 else "high" if impact >= 25 else "medium"
            issues.append(
                _make_issue(
                    trend_scope_key=trend_scope_key,
                    issue_type="join_exception",
                    title=f"Join exceptions detected in {join_name}",
                    severity=severity,
                    object_type="join",
                    object_key=f"{join_name}_exceptions",
                    table_name=_normalize_text(join.get("left_table")) or None,
                    stage_id=_normalize_text(join.get("join_artifact_id")) or None,
                    evidence_path=evidence_path,
                    recommendation="Investigate key mismatches and reference-table completeness before trusting the reconciled output.",
                    summary={
                        "run_id": run_id,
                        "join_name": join_name,
                        "left_table": join.get("left_table"),
                        "right_table": join.get("right_table"),
                        "unmatched_left_row_count": unmatched_left,
                        "unmatched_right_row_count": unmatched_right,
                    },
                )
            )
        if duplicate_matches > 0:
            issues.append(
                _make_issue(
                    trend_scope_key=trend_scope_key,
                    issue_type="join_exception",
                    title=f"Ambiguous duplicate join matches in {join_name}",
                    severity="high" if duplicate_matches >= 10 else "medium",
                    object_type="join",
                    object_key=f"{join_name}_duplicate_matches",
                    table_name=_normalize_text(join.get("left_table")) or None,
                    stage_id=_normalize_text(join.get("join_artifact_id")) or None,
                    evidence_path=evidence_path,
                    recommendation="Review non-unique join keys and resolve duplicate-match ambiguity before publication.",
                    summary={
                        "run_id": run_id,
                        "join_name": join_name,
                        "duplicate_match_count": duplicate_matches,
                    },
                )
            )

    for stage in dataset_stages:
        if _normalize_text(stage.get("stage_type")) != "filter":
            continue
        input_rows = float(stage.get("input_row_count") or 0.0)
        rejected_rows = float(stage.get("rejected_row_count") or 0.0)
        if input_rows <= 0 or rejected_rows <= 0:
            continue
        rejected_pct = (rejected_rows / input_rows) * 100.0
        if rejected_pct < 20.0:
            continue
        severity = _severity_from_ratio(rejected_pct, critical=60.0, high=35.0, medium=20.0)
        stage_key = stage_logical_key(stage)
        issues.append(
            _make_issue(
                trend_scope_key=trend_scope_key,
                issue_type="filter_loss_concentration",
                title=f"High filter loss in {stage.get('stage_name')}",
                severity=severity,
                object_type="stage",
                object_key=stage_key,
                table_name=_normalize_text(stage.get("output_dataset")) or None,
                stage_id=_normalize_text(stage.get("stage_id")) or None,
                evidence_path=f"/data-quality/evidence/stages/{stage.get('stage_id')}?tenant_id={tenant_id}&domain_id={domain_id}",
                recommendation="Review whether this filter is too strict or should be downgraded from hard reject to warning.",
                summary={
                    "run_id": run_id,
                    "stage_name": stage.get("stage_name"),
                    "input_row_count": input_rows,
                    "rejected_row_count": rejected_rows,
                    "rejected_pct": round(rejected_pct, 2),
                    "expression_text": ((stage.get("expression") or {}).get("expression_text")),
                },
            )
        )

    readiness_status = _normalize_text(final_dataset.get("readiness_status")).lower()
    if readiness_status in {"blocked", "warning"}:
        severity = "critical" if readiness_status == "blocked" else "high"
        issues.append(
            _make_issue(
                trend_scope_key=trend_scope_key,
                issue_type="publish_readiness_blocker",
                title="Final dataset readiness is blocked" if readiness_status == "blocked" else "Final dataset readiness is warning",
                severity=severity,
                object_type="final_dataset",
                object_key="final_dataset",
                evidence_path=f"/data-quality/final-dataset?tenant_id={tenant_id}&domain_id={domain_id}&run_id={run_id}",
                recommendation="Resolve blocking quality issues before publishing the final dataset.",
                summary={
                    "run_id": run_id,
                    "readiness_status": readiness_status,
                    "final_row_count": final_dataset.get("final_row_count"),
                    "total_rejected_row_count": final_dataset.get("total_rejected_row_count"),
                },
            )
        )

    for trend in trends:
        if _normalize_text(trend.get("trend_status")).lower() != "worsened":
            continue
        metric_name = _normalize_text(trend.get("metric_name"))
        object_type = _normalize_text(trend.get("object_type")) or "run"
        object_key = _normalize_text(trend.get("object_key")) or "__run__"
        if object_type == "run" and metric_name == "overall_trust_score":
            issues.append(
                _make_issue(
                    trend_scope_key=trend_scope_key,
                    issue_type="trend_regression",
                    title="Overall trust score worsened versus baseline",
                    severity="high",
                    object_type="run",
                    object_key="overall_trust_score",
                    evidence_path=f"/data-quality/trends?tenant_id={tenant_id}&domain_id={domain_id}&run_id={run_id}",
                    recommendation="Review the worsened metrics and block publish if the degradation is operationally significant.",
                    summary={
                        "run_id": run_id,
                        "metric_name": metric_name,
                        "delta_value": trend.get("delta_value"),
                        "delta_pct": trend.get("delta_pct"),
                        "baseline_run_id": trend.get("baseline_run_id"),
                    },
                )
            )
        elif object_type == "final_dataset" and metric_name == "readiness_status":
            issues.append(
                _make_issue(
                    trend_scope_key=trend_scope_key,
                    issue_type="trend_regression",
                    title="Final dataset readiness worsened versus baseline",
                    severity="critical",
                    object_type="final_dataset",
                    object_key="readiness_status",
                    evidence_path=f"/data-quality/trends?tenant_id={tenant_id}&domain_id={domain_id}&run_id={run_id}",
                    recommendation="Compare the final dataset blockers against the previous baseline before publication.",
                    summary={
                        "run_id": run_id,
                        "metric_name": metric_name,
                        "previous_value_text": trend.get("previous_value_text"),
                        "current_value_text": trend.get("current_value_text"),
                        "baseline_run_id": trend.get("baseline_run_id"),
                    },
                )
            )

    deduped: dict[str, dict[str, Any]] = {}
    for issue in issues:
        key = str(issue.get("issue_key") or "")
        if not key:
            continue
        current = deduped.get(key)
        if current is None or _SEVERITY_ORDER.get(str(issue.get("severity")), 9) < _SEVERITY_ORDER.get(str(current.get("severity")), 9):
            deduped[key] = issue
    return sorted(
        deduped.values(),
        key=lambda row: (
            _SEVERITY_ORDER.get(str(row.get("severity") or ""), 9),
            str(row.get("issue_type") or ""),
            str(row.get("title") or ""),
        ),
    )


def _to_iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    text = str(value).strip()
    return text or None


def _age_days(first_seen_at: Any) -> int | None:
    if not first_seen_at:
        return None
    dt = first_seen_at if isinstance(first_seen_at, datetime) else None
    if dt is None:
        try:
            dt = datetime.fromisoformat(str(first_seen_at).replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return max(0, int((_utc_now() - dt).total_seconds() // 86400))


def build_quality_issue_payload(row: dict[str, Any]) -> dict[str, Any]:
    age_days = _age_days(row.get("first_seen_at"))
    due_text = _to_iso(row.get("due_at"))
    overdue = False
    if due_text:
        try:
            due_dt = datetime.fromisoformat(due_text.replace("Z", "+00:00"))
            if due_dt.tzinfo is None:
                due_dt = due_dt.replace(tzinfo=timezone.utc)
            overdue = due_dt < _utc_now() and str(row.get("status") or "").strip().lower() not in {"resolved", "accepted_risk"}
        except ValueError:
            overdue = False
    recommendation = row.get("recommendation_json") or {}
    summary = row.get("summary_json") or {}
    related_runs = row.get("related_run_ids_json") or []
    if not isinstance(related_runs, list):
        related_runs = []
    return {
        "issue_id": row.get("issue_id"),
        "issue_key": row.get("issue_key"),
        "tenant_id": row.get("tenant_id"),
        "domain_id": row.get("domain_id"),
        "trend_scope_key": row.get("trend_scope_key"),
        "run_id": row.get("run_id"),
        "quality_run_id": row.get("quality_run_id"),
        "first_seen_run_id": row.get("first_seen_run_id"),
        "last_seen_run_id": row.get("last_seen_run_id"),
        "issue_type": row.get("issue_type"),
        "title": row.get("title"),
        "severity": row.get("severity"),
        "object_type": row.get("object_type"),
        "object_key": row.get("object_key"),
        "table_name": row.get("table_name"),
        "column_name": row.get("column_name"),
        "stage_id": row.get("stage_id"),
        "owner_id": row.get("owner_id"),
        "status": row.get("status"),
        "due_at": due_text,
        "first_seen_at": _to_iso(row.get("first_seen_at")),
        "last_seen_at": _to_iso(row.get("last_seen_at")),
        "age_days": age_days,
        "overdue": overdue,
        "evidence_path": row.get("evidence_path"),
        "recommendation": recommendation.get("text"),
        "recommendation_json": recommendation,
        "summary": summary,
        "related_run_ids": related_runs,
    }


def summarize_quality_issues(rows: list[dict[str, Any]]) -> dict[str, Any]:
    payload_rows = [build_quality_issue_payload(row) for row in rows]
    open_rows = [row for row in payload_rows if str(row.get("status") or "") in _ACTIVE_ISSUE_STATUSES]
    overdue_rows = [row for row in open_rows if row.get("overdue")]
    severity_counts = Counter(str(row.get("severity") or "unknown") for row in open_rows)
    status_counts = Counter(str(row.get("status") or "unknown") for row in payload_rows)
    owner_workload = Counter(str(row.get("owner_id") or "unassigned") for row in open_rows)
    return {
        "issue_count": len(payload_rows),
        "open_issue_count": len(open_rows),
        "overdue_issue_count": len(overdue_rows),
        "critical_issue_count": severity_counts.get("critical", 0),
        "high_issue_count": severity_counts.get("high", 0),
        "medium_issue_count": severity_counts.get("medium", 0),
        "low_issue_count": severity_counts.get("low", 0),
        "severity_counts": dict(severity_counts),
        "status_counts": dict(status_counts),
        "owner_workload": dict(owner_workload),
    }


def build_quality_issue_list_payload(
    *,
    tenant_id: str,
    domain_id: str,
    run_id: str | None,
    issues: list[dict[str, Any]],
) -> dict[str, Any]:
    rows = [build_quality_issue_payload(row) for row in issues]
    rows.sort(
        key=lambda row: (
            _SEVERITY_ORDER.get(str(row.get("severity") or ""), 9),
            0 if row.get("overdue") else 1,
            -(int(row.get("age_days") or 0)),
            str(row.get("title") or ""),
        )
    )
    return {
        "tenant_id": tenant_id,
        "domain_id": domain_id,
        "run_id": run_id,
        "summary": summarize_quality_issues(issues),
        "issues": rows,
    }
