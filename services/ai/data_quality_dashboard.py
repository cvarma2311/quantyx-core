from __future__ import annotations

from collections import Counter
from typing import Any

from services.ai.config import Settings
from services.ai.data_quality_enrichment import canonical_column_alias
from services.ai.data_quality_remediation import derive_data_quality_remediation_plan
from services.ai.data_quality_stages import parse_lineage_id
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
    dataset_stages: list[dict[str, Any]] | None = None,
    join_artifacts: list[dict[str, Any]] | None = None,
    lineage_edges: list[dict[str, Any]] | None = None,
    row_outcomes: list[dict[str, Any]] | None = None,
    final_dataset: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tables = _table_rows(profiling)
    columns = _column_rows(profiling)
    quality_rules = [rule for rule in (quality_rules or []) if isinstance(rule, dict)]
    quality_rule_results = [result for result in (quality_rule_results or []) if isinstance(result, dict)]
    duplicate_candidates = [item for item in (duplicate_candidates or []) if isinstance(item, dict)]
    freshness_results = [item for item in (freshness_results or []) if isinstance(item, dict)]
    quality_tables = [item for item in (quality_tables or []) if isinstance(item, dict)]
    enrichment_opportunities = [item for item in (enrichment_opportunities or []) if isinstance(item, dict)]
    dataset_stages = [item for item in (dataset_stages or []) if isinstance(item, dict)]
    join_artifacts = [item for item in (join_artifacts or []) if isinstance(item, dict)]
    lineage_edges = [item for item in (lineage_edges or []) if isinstance(item, dict)]
    row_outcomes = [item for item in (row_outcomes or []) if isinstance(item, dict)]
    final_dataset = dict(final_dataset or {})
    evidence_base = f"/data-quality/evidence"
    remediation_plan = derive_data_quality_remediation_plan(
        tenant_id=tenant_id,
        domain_id=domain_id,
        run_id=run_id,
        tables=quality_tables,
        rules=quality_rules,
        duplicates=duplicate_candidates,
        opportunities=enrichment_opportunities,
        dataset_stages=dataset_stages,
        row_outcomes=row_outcomes,
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
    lineage_ids: set[str] = set()
    lineage_ids.update(str(row.get("row_lineage_id") or "").strip() for row in lineage_edges)
    lineage_ids.update(str(row.get("row_lineage_id") or "").strip() for row in row_outcomes)
    lineage_ids.discard("")
    duplicate_candidate_total = sum(int(row.get("duplicate_candidate_count") or 0) for row in duplicate_rows)
    remediation_summary = remediation_plan.get("summary") or {}
    rejected_record_count = len([row for row in row_outcomes if str(row.get("outcome_type") or "").strip() == "rejected"])
    join_exception_count = len([row for row in row_outcomes if str(row.get("outcome_type") or "").strip() == "join_exception"])
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
            "metric_key": "rejected_records",
            "label": "Rejected Records",
            "value": rejected_record_count,
            "note": f"{join_exception_count} join exceptions",
            "evidence_path": f"/data-quality/rejected-records?tenant_id={tenant_id}&domain_id={domain_id}&run_id={run_id}",
        },
        {
            "metric_key": "final_dataset_rows",
            "label": "Final Dataset Rows",
            "value": final_dataset.get("final_row_count"),
            "note": str(final_dataset.get("readiness_status") or "unknown"),
            "evidence_path": f"/data-quality/final-dataset?tenant_id={tenant_id}&domain_id={domain_id}&run_id={run_id}",
        },
        {
            "metric_key": "lineage_rows",
            "label": "Tracked Lineage Rows",
            "value": len(lineage_ids),
            "note": f"{len(lineage_edges)} lineage edges",
            "evidence_path": f"/data-quality/lineage?tenant_id={tenant_id}&domain_id={domain_id}&run_id={run_id}",
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
    filter_rows = [
        {
            "stage_id": row.get("stage_id"),
            "stage_name": row.get("stage_name"),
            "table_name": row.get("output_dataset"),
            "expression_text": ((row.get("expression") or {}).get("expression_text")),
            "input_row_count": row.get("input_row_count"),
            "output_row_count": row.get("output_row_count"),
            "rejected_row_count": row.get("rejected_row_count"),
            "rejected_pct": (
                round((float(row.get("rejected_row_count") or 0) / float(row.get("input_row_count") or 1)) * 100.0, 2)
                if row.get("input_row_count") not in (None, 0) and row.get("rejected_row_count") is not None
                else None
            ),
            "evidence_path": (
                f"{evidence_base}/stages/{row.get('stage_id')}?tenant_id={tenant_id}&domain_id={domain_id}"
                if row.get("stage_id")
                else None
            ),
        }
        for row in dataset_stages
        if str(row.get("stage_type") or "").strip() == "filter"
        and (row.get("rejected_row_count") is not None or row.get("output_row_count") is not None)
    ]
    stage_by_id = {str(row.get("stage_id") or ""): row for row in dataset_stages if str(row.get("stage_id") or "").strip()}
    final_basis_stage_name = str(final_dataset.get("final_stage_name") or "").strip()
    lineage_rows: list[dict[str, Any]] = []
    lineage_ids: set[str] = set()
    lineage_ids.update(str(row.get("row_lineage_id") or "").strip() for row in lineage_edges)
    lineage_ids.update(str(row.get("row_lineage_id") or "").strip() for row in row_outcomes)
    lineage_ids.discard("")
    final_stage_seq = None
    for stage in dataset_stages:
        if str(stage.get("stage_name") or "").strip() == final_basis_stage_name:
            final_stage_seq = stage.get("stage_seq")
            break
    for row_lineage_id in sorted(lineage_ids):
        decoded = row_lineage_id
        source_table = None
        source_row_ref = None
        if row_lineage_id.startswith("dqlin_"):
            try:
                parsed = parse_lineage_id(row_lineage_id)
            except Exception:
                parsed = None
            if parsed:
                parts = parsed.get("parts") or []
                decoded = " -> ".join(str(part) for part in parts if str(part).strip()) or row_lineage_id
                if len(parts) >= 2:
                    source_table = parts[0]
                    source_row_ref = parts[1]
        row_edge_items = [item for item in lineage_edges if str(item.get("row_lineage_id") or "") == row_lineage_id]
        row_outcome_items = [item for item in row_outcomes if str(item.get("row_lineage_id") or "") == row_lineage_id]
        stage_names: set[str] = set()
        latest_stage_name = None
        latest_stage_seq_local = -1
        for item in row_edge_items:
            for stage_id_key, stage_name_key in (("from_stage_id", "from_stage_name"), ("to_stage_id", "to_stage_name")):
                stage_id = str(item.get(stage_id_key) or "")
                if not stage_id:
                    continue
                stage = stage_by_id.get(stage_id) or {}
                stage_name = str(item.get(stage_name_key) or stage.get("stage_name") or "").strip()
                if stage_name:
                    stage_names.add(stage_name)
                stage_seq = int(stage.get("stage_seq") or -1)
                if stage_seq >= latest_stage_seq_local:
                    latest_stage_seq_local = stage_seq
                    latest_stage_name = stage_name or latest_stage_name
        for item in row_outcome_items:
            stage_id = str(item.get("stage_id") or "")
            stage = stage_by_id.get(stage_id) or {}
            stage_name = str(item.get("stage_name") or stage.get("stage_name") or "").strip()
            if stage_name:
                stage_names.add(stage_name)
            stage_seq = int(stage.get("stage_seq") or -1)
            if stage_seq >= latest_stage_seq_local:
                latest_stage_seq_local = stage_seq
                latest_stage_name = stage_name or latest_stage_name
        final_dataset_member = bool(final_basis_stage_name and latest_stage_name == final_basis_stage_name)
        if final_dataset_member and final_stage_seq is not None:
            latest_stage_seq_local = int(final_stage_seq or latest_stage_seq_local)
        reason_codes = [str(item.get("reason_code") or "").strip() for item in row_outcome_items if str(item.get("reason_code") or "").strip()]
        if final_dataset_member:
            final_state = "final_dataset_member"
        elif reason_codes:
            final_state = reason_codes[-1]
        elif row_edge_items:
            final_state = str(row_edge_items[-1].get("edge_type") or "transition")
        else:
            final_state = "tracked"
        lineage_rows.append(
            {
                "row_lineage_id": row_lineage_id,
                "source_table": source_table,
                "source_row_ref": source_row_ref,
                "decoded_lineage": decoded,
                "transition_count": len(row_edge_items),
                "stage_count": len(stage_names),
                "rejected_count": sum(1 for item in row_outcome_items if str(item.get("outcome_type") or "").strip() == "rejected"),
                "join_exception_count": sum(1 for item in row_outcome_items if str(item.get("outcome_type") or "").strip() == "join_exception"),
                "latest_stage_name": latest_stage_name,
                "final_state": final_state,
                "final_dataset_member": final_dataset_member,
                "evidence_path": f"/data-quality/lineage/{row_lineage_id}?tenant_id={tenant_id}&domain_id={domain_id}&run_id={run_id}",
            }
        )
    lineage_rows = sorted(
        lineage_rows,
        key=lambda row: (
            0 if row.get("final_dataset_member") else 1,
            -(int(row.get("rejected_count") or 0) + int(row.get("join_exception_count") or 0)),
            -(int(row.get("transition_count") or 0)),
            str(row.get("source_table") or ""),
            str(row.get("source_row_ref") or ""),
        ),
    )[:20]

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
            "chart_key": "filter_impact",
            "title": "Filter Impact",
            "chart_type": "table",
            "data_source": "quantyx_data_quality_dataset_stages",
            "display_columns": [
                _display_column("stage_name", "Filter Stage"),
                _display_column("table_name", "Table"),
                _display_column("expression_text", "Expression"),
                _display_column("input_row_count", "Input Rows"),
                _display_column("output_row_count", "Output Rows"),
                _display_column("rejected_row_count", "Rejected Rows"),
                _display_column("rejected_pct", "Rejected %"),
                _display_column("evidence_path", "Evidence Path"),
            ],
            "rows": sorted(filter_rows, key=lambda row: -(float(row.get("rejected_pct") or 0.0)))[:20],
            "summary": {
                "filter_stage_count": len(filter_rows),
                "total_rejected_row_count": sum(int(row.get("rejected_row_count") or 0) for row in filter_rows),
            },
        },
    )
    _append_chart_section(
        chart_plan,
        {
            "chart_key": "join_health",
            "title": "Join Health",
            "chart_type": "table",
            "data_source": "quantyx_data_quality_join_artifacts",
            "display_columns": [
                _display_column("join_name", "Join Name"),
                _display_column("left_table", "Left Table"),
                _display_column("right_table", "Right Table"),
                _display_column("matched_row_count", "Matched Rows"),
                _display_column("unmatched_left_row_count", "Unmatched Left"),
                _display_column("unmatched_right_row_count", "Unmatched Right"),
                _display_column("duplicate_match_count", "Duplicate Matches"),
                _display_column("evidence_path", "Evidence Path"),
            ],
            "rows": [
                {
                    "join_name": row.get("join_name"),
                    "left_table": row.get("left_table"),
                    "right_table": row.get("right_table"),
                    "matched_row_count": row.get("matched_row_count"),
                    "unmatched_left_row_count": row.get("unmatched_left_row_count"),
                    "unmatched_right_row_count": row.get("unmatched_right_row_count"),
                    "duplicate_match_count": row.get("duplicate_match_count"),
                    "evidence_path": (
                        f"{evidence_base}/joins/{row.get('join_artifact_id')}?tenant_id={tenant_id}&domain_id={domain_id}"
                        if row.get("join_artifact_id")
                        else None
                    ),
                }
                for row in join_artifacts
            ],
            "summary": {
                "join_count": len(join_artifacts),
                "total_unmatched_left": sum(int(row.get("unmatched_left_row_count") or 0) for row in join_artifacts),
                "total_unmatched_right": sum(int(row.get("unmatched_right_row_count") or 0) for row in join_artifacts),
            },
        },
    )
    _append_chart_section(
        chart_plan,
        {
            "chart_key": "stage_waterfall",
            "title": "Stage Waterfall",
            "chart_type": "waterfall",
            "data_source": "quantyx_data_quality_dataset_stages",
            "display_columns": [
                _display_column("stage_seq", "Stage Seq"),
                _display_column("stage_name", "Stage Name"),
                _display_column("stage_type", "Stage Type"),
                _display_column("input_row_count", "Input Rows"),
                _display_column("output_row_count", "Output Rows"),
                _display_column("rejected_row_count", "Rejected Rows"),
                _display_column("evidence_path", "Evidence Path"),
            ],
            "rows": [
                {
                    "stage_seq": row.get("stage_seq"),
                    "stage_name": row.get("stage_name"),
                    "stage_type": row.get("stage_type"),
                    "input_row_count": row.get("input_row_count"),
                    "output_row_count": row.get("output_row_count"),
                    "rejected_row_count": row.get("rejected_row_count"),
                    "evidence_path": (
                        f"{evidence_base}/stages/{row.get('stage_id')}?tenant_id={tenant_id}&domain_id={domain_id}"
                        if row.get("stage_id")
                        else None
                    ),
                }
                for row in dataset_stages
            ],
            "summary": {
                "stage_count": len(dataset_stages),
                "total_rejected_row_count": rejected_record_count,
            },
        },
    )
    _append_chart_section(
        chart_plan,
        {
            "chart_key": "final_dataset_quality",
            "title": "Final Dataset Quality",
            "chart_type": "summary_cards",
            "data_source": "quantyx_data_quality_final_dataset_artifacts",
            "display_columns": [
                _display_column("metric_key", "Metric Key"),
                _display_column("label", "Label"),
                _display_column("value", "Value"),
                _display_column("note", "Note"),
                _display_column("evidence_path", "Evidence Path"),
            ],
            "rows": [
                {
                    "metric_key": "final_row_count",
                    "label": "Final Row Count",
                    "value": final_dataset.get("final_row_count"),
                    "note": final_dataset.get("final_stage_name"),
                    "evidence_path": f"/data-quality/final-dataset?tenant_id={tenant_id}&domain_id={domain_id}&run_id={run_id}",
                },
                {
                    "metric_key": "total_rejected_row_count",
                    "label": "Rejected Rows",
                    "value": final_dataset.get("total_rejected_row_count"),
                    "note": "across measured stages",
                    "evidence_path": f"/data-quality/rejected-records?tenant_id={tenant_id}&domain_id={domain_id}&run_id={run_id}",
                },
                {
                    "metric_key": "readiness_status",
                    "label": "Readiness",
                    "value": final_dataset.get("readiness_status"),
                    "note": (final_dataset.get("summary_json") or {}).get("measurement_status"),
                    "evidence_path": f"/data-quality/final-dataset?tenant_id={tenant_id}&domain_id={domain_id}&run_id={run_id}",
                },
            ]
            if final_dataset
            else [],
            "summary": {
                "final_row_count": final_dataset.get("final_row_count"),
                "total_rejected_row_count": final_dataset.get("total_rejected_row_count"),
                "readiness_status": final_dataset.get("readiness_status"),
            },
        },
    )
    _append_chart_section(
        chart_plan,
        {
            "chart_key": "lineage_overview",
            "title": "Lineage Journey Overview",
            "chart_type": "table",
            "data_source": "quantyx_data_quality_lineage_edges",
            "display_columns": [
                _display_column("row_lineage_id", "Row Lineage ID"),
                _display_column("source_table", "Source Table"),
                _display_column("source_row_ref", "Source Row Ref"),
                _display_column("decoded_lineage", "Decoded Lineage"),
                _display_column("transition_count", "Transitions"),
                _display_column("stage_count", "Stages"),
                _display_column("rejected_count", "Rejected"),
                _display_column("join_exception_count", "Join Exceptions"),
                _display_column("latest_stage_name", "Latest Stage"),
                _display_column("final_state", "Final State"),
                _display_column("final_dataset_member", "Final Dataset Member"),
                _display_column("evidence_path", "Evidence Path"),
            ],
            "rows": lineage_rows,
            "summary": {
                "lineage_row_count": len(lineage_ids),
                "lineage_edge_count": len(lineage_edges),
                "final_dataset_member_count": len([row for row in lineage_rows if row.get("final_dataset_member")]),
            },
        },
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
                "rejected_record_count": rejected_record_count,
                "final_dataset_row_count": final_dataset.get("final_row_count"),
                "lineage_row_count": len(lineage_ids),
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
            "rejected_record_count": rejected_record_count,
            "final_dataset_row_count": final_dataset.get("final_row_count"),
            "lineage_row_count": len(lineage_ids),
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
    dataset_stages: list[dict[str, Any]] | None = None,
    join_artifacts: list[dict[str, Any]] | None = None,
    lineage_edges: list[dict[str, Any]] | None = None,
    row_outcomes: list[dict[str, Any]] | None = None,
    final_dataset: dict[str, Any] | None = None,
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
        dataset_stages=dataset_stages,
        join_artifacts=join_artifacts,
        lineage_edges=lineage_edges,
        row_outcomes=row_outcomes,
        final_dataset=final_dataset,
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
