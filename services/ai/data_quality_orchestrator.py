from __future__ import annotations

from typing import Any, Callable
import logging

try:
    from langgraph.graph import END, StateGraph
except Exception:  # pragma: no cover
    END = None
    StateGraph = None

from services.ai.agentic_agents import build_schema_graph, enrich_schema_graph_columns, profile_tables
from services.ai.agentic_artifacts_registry import (
    get_table_profile_artifact,
    persist_schema_graph_artifact,
    persist_table_profile_artifact,
)
from services.ai.agentic_store import append_agent_chat_log, append_agent_run_event
from services.ai.data_quality_dashboard import create_data_quality_dashboard
from services.ai.data_quality_anomalies import derive_data_quality_anomalies, summarize_data_quality_anomalies
from services.ai.data_quality_duplicates import detect_duplicate_candidates
from services.ai.data_quality_freshness import analyze_freshness_and_stability
from services.ai.data_quality_enrichment import discover_enrichment_opportunities
from services.ai.data_quality_issues import derive_data_quality_issues
from services.ai.data_quality_trust import compute_data_quality_trust_scores
from services.ai.data_quality_store import (
    create_or_update_quality_run,
    get_quality_final_dataset_artifact,
    list_quality_anomalies,
    list_quality_issues,
    get_quality_run_by_run_id,
    get_previous_quality_run,
    list_quality_dataset_stages,
    list_quality_join_artifacts,
    list_quality_lineage_edges,
    list_quality_stage_row_outcomes,
    replace_quality_dataset_stages,
    replace_quality_join_artifacts,
    replace_quality_lineage_edges,
    replace_quality_stage_row_outcomes,
    list_quality_tables_by_quality_run,
    list_quality_duplicate_candidates,
    list_quality_rules,
    list_quality_run_metric_snapshots,
    list_quality_tables,
    list_quality_object_metric_snapshots,
    list_quality_trends,
    replace_quality_duplicate_candidates,
    replace_quality_enrichment_opportunities,
    replace_quality_anomalies,
    replace_quality_object_metric_snapshots,
    replace_quality_run_metric_snapshots,
    replace_quality_rules,
    replace_quality_trends,
    upsert_quality_final_dataset_artifact,
    upsert_quality_issues,
    update_quality_table_monitoring,
    update_quality_table_trust_scores,
    upsert_quality_artifacts_from_profiling,
)
from services.ai.data_quality_stages import compute_stage_plan_metrics_tool, infer_stage_plan_tool
from services.ai.data_quality_trends import (
    build_business_term_trend_payload,
    build_object_metric_snapshots,
    build_run_metric_snapshots,
    build_trend_rows,
    select_trend_baseline_run,
    summarize_trends,
)
from services.ai.glossary import fetch_glossary_terms
from services.ai.data_quality_rules import (
    build_validation_rule_coverage,
    classify_quality_rule_review_status,
    build_quality_rule_execution_plan,
    data_quality_rule_auto_approve_all_enabled,
    execute_quality_rules,
    extract_quality_rules_from_context,
    plan_quality_rules_from_context,
)
from services.ai.db import ScopedConnection
from services.ai.connection_registry import resolve_database_credentials_cached
from services.ai.semantic_layer.pack_loader import load_pack
from services.ai.workspace_store import get_deployment_run, list_runs_by_trend_scope


logger = logging.getLogger(__name__)


def _resolved_trend_metadata(
    settings,
    run_id: str,
    *,
    state: dict[str, Any] | None = None,
    run_row: dict[str, Any] | None = None,
) -> dict[str, Any]:
    state = state or {}
    run_row = run_row or {}
    deployment_row = get_deployment_run(settings, run_id) or {}

    trend_mode = (
        str(state.get("trend_mode") or run_row.get("trend_mode") or deployment_row.get("trend_mode") or "").strip().lower()
        or None
    )
    trend_scope_key = (
        str(
            state.get("trend_scope_key")
            or run_row.get("trend_scope_key")
            or ((run_row.get("summary_json") or {}) if isinstance(run_row.get("summary_json"), dict) else {}).get("trend_scope_key")
            or deployment_row.get("trend_scope_key")
            or ""
        ).strip()
        or None
    )
    trend_scope_label = (
        str(
            state.get("trend_scope_label")
            or run_row.get("trend_scope_label")
            or deployment_row.get("trend_scope_label")
            or ""
        ).strip()
        or None
    )
    baseline_run_id = (
        str(
            state.get("baseline_run_id")
            or run_row.get("baseline_run_id")
            or ((run_row.get("summary_json") or {}) if isinstance(run_row.get("summary_json"), dict) else {}).get("baseline_run_id")
            or deployment_row.get("baseline_run_id")
            or ""
        ).strip()
        or None
    )
    return {
        "trend_mode": trend_mode,
        "trend_scope_key": trend_scope_key,
        "trend_scope_label": trend_scope_label,
        "baseline_run_id": baseline_run_id,
    }


def is_data_quality_workflow(domain_id: str | None, initial_state: dict[str, Any] | None = None) -> bool:
    state = initial_state or {}
    if str(state.get("workflow_mode") or "").strip().lower() == "data_quality":
        return True
    normalized_domain = str(domain_id or state.get("domain_id") or "").strip().lower()
    if normalized_domain == "data_quality_observability":
        return True
    if not normalized_domain:
        return False
    try:
        pack = load_pack(f"packs/{normalized_domain}")
    except Exception:
        return False
    pack_type = str(pack.get("pack_type") or "").strip().lower()
    if pack_type == "data_quality":
        return True
    capabilities = {
        str(item).strip().lower()
        for item in (pack.get("capabilities") or [])
        if str(item).strip()
    }
    return bool(capabilities & {"data_quality", "validation", "profiling", "data_observability"})


def _scoped_conn_from_state(state: dict[str, Any]) -> ScopedConnection | None:
    raw = state.get("scoped_conn")
    if isinstance(raw, ScopedConnection):
        return raw
    if isinstance(raw, dict):
        try:
            return ScopedConnection.from_dict(raw)
        except Exception:
            logger.warning("data_quality.scoped_conn.invalid", exc_info=True)
    return None


def _emit(
    settings,
    run_id: str,
    agent_name: str,
    status: str,
    message: str,
    artifacts: dict[str, Any] | None = None,
    *,
    event_callback: Callable[[dict[str, Any]], None] | None = None,
) -> None:
    event_id = append_agent_run_event(settings, run_id, agent_name, status, message, artifacts or {})
    payload = {
        "event_id": event_id,
        "run_id": run_id,
        "agent_name": agent_name,
        "status": status,
        "message": message,
        "artifacts": artifacts or {},
    }
    if event_callback:
        try:
            event_callback(payload)
        except Exception:
            logger.warning("data_quality.event_callback_failed | run_id=%s agent=%s", run_id, agent_name, exc_info=True)


def _persist_trend_artifacts(settings, run_id: str, state: dict[str, Any]) -> dict[str, Any]:
    scope = _scope(state, run_id)
    quality_run_id = str(state.get("quality_run_id") or "").strip()
    if not quality_run_id:
        return {"baseline_run_id": None, "trends": [], "summary": {}}
    trend_meta = _resolved_trend_metadata(settings, run_id, state=state)
    trend_mode = trend_meta.get("trend_mode")
    trend_scope_key = trend_meta.get("trend_scope_key")
    current_summary = dict(state.get("quality_summary") or {})
    if not trend_scope_key:
        return {"baseline_run_id": None, "trends": [], "summary": {}}
    quality_tables = list_quality_tables(settings, tenant_id=scope["tenant_id"], domain_id=scope["domain_id"], run_id=run_id, limit=1200)
    quality_rules = list_quality_rules(settings, tenant_id=scope["tenant_id"], domain_id=scope["domain_id"], run_id=run_id, limit=1200)
    dataset_stages = list_quality_dataset_stages(settings, tenant_id=scope["tenant_id"], domain_id=scope["domain_id"], run_id=run_id, limit=1200)
    final_dataset = get_quality_final_dataset_artifact(settings, tenant_id=scope["tenant_id"], domain_id=scope["domain_id"], run_id=run_id) or {}
    current_run_row = {
        "run_id": run_id,
        "overall_trust_score": state.get("overall_trust_score") or current_summary.get("average_table_trust_score"),
        "summary_json": current_summary,
    }
    run_snapshots = build_run_metric_snapshots(
        run_row=current_run_row,
        tables=quality_tables,
        rules=quality_rules,
        stages=dataset_stages,
        final_dataset=final_dataset,
    )
    object_snapshots = build_object_metric_snapshots(
        tables=quality_tables,
        rules=quality_rules,
        stages=dataset_stages,
        final_dataset=final_dataset,
    )
    replace_quality_run_metric_snapshots(
        settings,
        quality_run_id=quality_run_id,
        run_id=run_id,
        tenant_id=scope["tenant_id"],
        domain_id=scope["domain_id"],
        trend_scope_key=trend_scope_key,
        snapshots=run_snapshots,
    )
    replace_quality_object_metric_snapshots(
        settings,
        quality_run_id=quality_run_id,
        run_id=run_id,
        tenant_id=scope["tenant_id"],
        domain_id=scope["domain_id"],
        trend_scope_key=trend_scope_key,
        snapshots=object_snapshots,
    )
    comparable_runs: list[dict[str, Any]] = []
    if trend_mode in {"monitor", "baseline_reset"}:
        comparable_runs = list_runs_by_trend_scope(
            settings,
            tenant_id=scope["tenant_id"],
            domain_id=scope["domain_id"],
            trend_scope_key=trend_scope_key,
            exclude_run_id=run_id,
            completed_only=True,
            limit=20,
        )
    baseline_run = select_trend_baseline_run(
        trend_mode=trend_mode,
        previous_runs=comparable_runs,
    )
    baseline_run_id = str((baseline_run or {}).get("run_id") or "").strip() or None
    previous_snapshots: list[dict[str, Any]] = []
    if baseline_run_id:
        previous_snapshots.extend(
            {
                "object_type": "run",
                "object_key": "__run__",
                "object_name": "Run Summary",
                "metric_name": item.get("metric_name"),
                "metric_value_num": item.get("metric_value_num"),
                "metric_value_text": item.get("metric_value_text"),
                "metric_unit": item.get("metric_unit"),
            }
            for item in list_quality_run_metric_snapshots(
                settings,
                tenant_id=scope["tenant_id"],
                domain_id=scope["domain_id"],
                run_id=baseline_run_id,
                limit=1200,
            )
        )
        previous_snapshots.extend(
            {
                "object_type": item.get("object_type"),
                "object_key": item.get("object_key"),
                "object_name": item.get("object_name"),
                "metric_name": item.get("metric_name"),
                "metric_value_num": item.get("metric_value_num"),
                "metric_value_text": item.get("metric_value_text"),
                "metric_unit": item.get("metric_unit"),
            }
            for item in list_quality_object_metric_snapshots(
                settings,
                tenant_id=scope["tenant_id"],
                domain_id=scope["domain_id"],
                trend_scope_key=trend_scope_key,
                run_id=baseline_run_id,
                limit=4000,
            )
        )
    current_snapshots = (
        [{"object_type": "run", "object_key": "__run__", "object_name": "Run Summary", **item} for item in run_snapshots]
        + object_snapshots
    )
    trends = build_trend_rows(
        current_run_id=run_id,
        baseline_run_id=baseline_run_id,
        current_snapshots=current_snapshots,
        previous_snapshots=previous_snapshots,
    )
    replace_quality_trends(
        settings,
        quality_run_id=quality_run_id,
        run_id=run_id,
        tenant_id=scope["tenant_id"],
        domain_id=scope["domain_id"],
        trend_scope_key=trend_scope_key,
        baseline_run_id=baseline_run_id,
        trends=trends,
    )
    summary = summarize_trends(trends)
    try:
        business_term_trends = build_business_term_trend_payload(
            tenant_id=scope["tenant_id"],
            domain_id=scope["domain_id"],
            run_id=run_id,
            trends=trends,
            glossary_terms=fetch_glossary_terms(settings, scope["tenant_id"], scope["domain_id"]),
        )
    except Exception:
        business_term_trends = {"summary": {}, "rows": []}
    summary["trend_mode"] = trend_mode
    summary["trend_scope_key"] = trend_scope_key
    summary["trend_scope_label"] = trend_meta.get("trend_scope_label")
    summary["baseline_run_id"] = baseline_run_id
    summary["business_term_group_count"] = (business_term_trends.get("summary") or {}).get("business_term_group_count", 0)
    summary["worsened_business_term_count"] = (business_term_trends.get("summary") or {}).get("worsened_business_term_count", 0)
    return {"baseline_run_id": baseline_run_id, "trends": trends, "summary": summary}


def _persist_issue_artifacts(settings, run_id: str, state: dict[str, Any]) -> dict[str, Any]:
    scope = _scope(state, run_id)
    quality_run_id = str(state.get("quality_run_id") or "").strip()
    if not quality_run_id:
        return {"issues": [], "summary": {}}
    issues = derive_data_quality_issues(
        tenant_id=scope["tenant_id"],
        domain_id=scope["domain_id"],
        run_id=run_id,
        trend_scope_key=str(state.get("trend_scope_key") or "").strip() or None,
        quality_summary=dict(state.get("quality_summary") or {}),
        rules=list_quality_rules(settings, tenant_id=scope["tenant_id"], domain_id=scope["domain_id"], run_id=run_id, limit=1200),
        duplicate_candidates=list_quality_duplicate_candidates(settings, tenant_id=scope["tenant_id"], domain_id=scope["domain_id"], run_id=run_id, limit=1200),
        freshness_results=state.get("freshness_results") or [],
        dataset_stages=list_quality_dataset_stages(settings, tenant_id=scope["tenant_id"], domain_id=scope["domain_id"], run_id=run_id, limit=1200),
        join_artifacts=list_quality_join_artifacts(settings, tenant_id=scope["tenant_id"], domain_id=scope["domain_id"], run_id=run_id, limit=1200),
        final_dataset=get_quality_final_dataset_artifact(settings, tenant_id=scope["tenant_id"], domain_id=scope["domain_id"], run_id=run_id) or {},
        trends=list_quality_trends(settings, tenant_id=scope["tenant_id"], domain_id=scope["domain_id"], run_id=run_id, limit=4000),
    )
    summary = upsert_quality_issues(
        settings,
        tenant_id=scope["tenant_id"],
        domain_id=scope["domain_id"],
        trend_scope_key=str(state.get("trend_scope_key") or "").strip() or None,
        run_id=run_id,
        quality_run_id=quality_run_id,
        issues=issues,
    )
    current_rows = list_quality_issues(
        settings,
        tenant_id=scope["tenant_id"],
        domain_id=scope["domain_id"],
        run_id=run_id,
        limit=1200,
    )
    summary.setdefault("issue_count", len(current_rows))
    return {"issues": current_rows, "summary": summary}


def _persist_anomaly_artifacts(settings, run_id: str, state: dict[str, Any]) -> dict[str, Any]:
    scope = _scope(state, run_id)
    quality_run_id = str(state.get("quality_run_id") or "").strip()
    if not quality_run_id:
        return {"anomalies": [], "summary": {}}
    anomalies = derive_data_quality_anomalies(
        tenant_id=scope["tenant_id"],
        domain_id=scope["domain_id"],
        run_id=run_id,
        quality_run_id=quality_run_id,
        trend_scope_key=str(state.get("trend_scope_key") or "").strip() or None,
        baseline_run_id=str(state.get("baseline_run_id") or "").strip() or None,
        trends=list_quality_trends(settings, tenant_id=scope["tenant_id"], domain_id=scope["domain_id"], run_id=run_id, limit=4000),
    )
    replace_quality_anomalies(
        settings,
        quality_run_id=quality_run_id,
        run_id=run_id,
        tenant_id=scope["tenant_id"],
        domain_id=scope["domain_id"],
        trend_scope_key=str(state.get("trend_scope_key") or "").strip() or None,
        anomalies=anomalies,
    )
    current_rows = list_quality_anomalies(
        settings,
        tenant_id=scope["tenant_id"],
        domain_id=scope["domain_id"],
        run_id=run_id,
        limit=1200,
    )
    summary = summarize_data_quality_anomalies(current_rows)
    return {"anomalies": current_rows, "summary": summary}


def _resolve_scoped_conn_from_scope(settings, scope: dict[str, str]) -> ScopedConnection | None:
    connection_id = str(scope.get("connection_id") or "").strip()
    schema_name = str(scope.get("schema_name") or "public").strip() or "public"
    if not connection_id:
        return None
    try:
        return resolve_database_credentials_cached(settings, connection_id, schema_name)
    except Exception:
        logger.warning("data_quality.scoped_conn.resolve_failed", exc_info=True)
        return None


def _scope(state: dict[str, Any], run_id: str) -> dict[str, str]:
    return {
        "tenant_id": str(state.get("tenant_id") or ""),
        "domain_id": str(state.get("domain_id") or "data_quality_observability"),
        "run_id": run_id,
        "connection_id": str(state.get("connection_id") or ""),
        "database_name": str(state.get("database_name") or ""),
        "schema_name": str(state.get("schema_name") or "public"),
    }


def _quality_summary(
    profiling: dict[str, Any],
    persisted: dict[str, int],
    rule_summary: dict[str, Any] | None = None,
    duplicate_summary: dict[str, Any] | None = None,
    freshness_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tables = profiling.get("tables") or []
    quality_overview = profiling.get("quality_overview") or {}
    critical = 0
    warning = 0
    for table in tables:
        score = (table.get("quality_summary") or {}).get("table_trust_score")
        try:
            numeric = float(score)
        except (TypeError, ValueError):
            continue
        if numeric < 50.0:
            critical += 1
        elif numeric < 75.0:
            warning += 1
    rule_summary = rule_summary or {}
    duplicate_summary = duplicate_summary or {}
    freshness_summary = freshness_summary or {}
    return {
        "profiled_tables": len(tables),
        "profiled_columns": sum(len(table.get("column_profiles") or []) for table in tables),
        "critical_issue_count": critical,
        "warning_issue_count": warning,
        "validation_rule_count": rule_summary.get("rule_count", 0),
        "failed_rule_count": rule_summary.get("failed_rules", 0),
        "passed_rule_count": rule_summary.get("passed_rules", 0),
        "rule_execution_error_count": rule_summary.get("error_rules", 0),
        "duplicate_candidate_count": duplicate_summary.get("duplicate_candidate_count", 0),
        "exact_duplicate_candidate_count": duplicate_summary.get("exact_duplicate_candidate_count", 0),
        "fuzzy_duplicate_candidate_count": duplicate_summary.get("fuzzy_duplicate_candidate_count", 0),
        "stale_table_count": freshness_summary.get("stale_table_count", 0),
        "tables_without_freshness_column_count": freshness_summary.get("tables_without_freshness_column_count", 0),
        "stability_issue_count": freshness_summary.get("stability_issue_count", 0),
        "average_table_trust_score": quality_overview.get("average_table_trust_score"),
        "low_trust_tables_count": quality_overview.get("low_trust_tables_count"),
        "persisted": persisted,
    }


_PHASE58_SUMMARY_KEYS = {
    "dataset_stage_plan",
    "dataset_stage_count",
    "join_stage_count",
    "filter_stage_count",
    "total_rejected_row_count",
    "lineage_edge_count",
    "final_dataset_row_count",
    "final_dataset_readiness_status",
    "rule_validation_planner_mode",
    "validation_control_count",
    "compiled_validation_control_count",
    "uncovered_validation_control_count",
    "validation_controls",
    "rule_coverage",
}


def _merge_phase58_summary(existing: dict[str, Any] | None, summary: dict[str, Any]) -> dict[str, Any]:
    merged = dict(summary or {})
    for key in _PHASE58_SUMMARY_KEYS:
        if key not in merged and existing and key in existing:
            merged[key] = existing.get(key)
    return merged


def _rule_status(rule: dict[str, Any]) -> str:
    return str(rule.get("status") or "").strip().lower()


def _rule_summary_from_rules(
    rules: list[dict[str, Any]],
    execution: dict[str, Any] | None = None,
) -> dict[str, Any]:
    execution = execution or {}
    return {
        "rule_count": len(rules),
        "active_rule_count": sum(1 for item in rules if _rule_status(item) == "active"),
        "needs_review_rule_count": sum(1 for item in rules if _rule_status(item) == "needs_review"),
        "unsupported_rule_count": sum(1 for item in rules if _rule_status(item) == "unsupported"),
        "rejected_rule_count": sum(1 for item in rules if _rule_status(item) == "rejected"),
        "rules_executed": execution.get("rules_executed", 0),
        "failed_rules": execution.get("failed_rules", 0),
        "passed_rules": execution.get("passed_rules", 0),
        "error_rules": execution.get("error_rules", 0),
        "review_required": False,
        "review_pending_count": 0,
    }


def _merge_rule_rows(
    rules: list[dict[str, Any]],
    results: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    results_by_rule_id = {
        str(item.get("rule_id") or "").strip(): item
        for item in (results or [])
        if isinstance(item, dict) and str(item.get("rule_id") or "").strip()
    }
    merged: list[dict[str, Any]] = []
    for rule in rules:
        rule_id = str(rule.get("rule_id") or "").strip()
        result = results_by_rule_id.get(rule_id, {})
        merged.append({**rule, **result})
    return merged


def _duplicate_summary_from_candidates(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "duplicate_candidate_count": len(candidates),
        "exact_duplicate_candidate_count": sum(
            1 for item in candidates if str(item.get("duplicate_type") or "").startswith("exact_")
        ),
        "fuzzy_duplicate_candidate_count": sum(
            1 for item in candidates if str(item.get("duplicate_type") or "").startswith("fuzzy_")
        ),
    }


def _freshness_results_from_quality_tables(quality_tables: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for table in quality_tables:
        table_name = str(table.get("table_name") or "").strip()
        if not table_name:
            continue
        summary = table.get("summary_json") or {}
        freshness = summary.get("freshness_analysis") or {}
        stability = summary.get("stability_analysis") or {}
        if not freshness and not stability:
            continue
        row = {"table_name": table_name}
        if isinstance(freshness, dict):
            row.update(freshness)
        if isinstance(stability, dict):
            row.update(stability)
        results.append(row)
    return results


def _freshness_summary_from_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "stale_table_count": sum(1 for item in results if str(item.get("freshness_status") or "").strip().lower() == "stale"),
        "tables_without_freshness_column_count": sum(
            1 for item in results if str(item.get("freshness_status") or "").strip().lower() == "no_freshness_column"
        ),
        "stability_issue_count": sum(1 for item in results if str(item.get("stability_status") or "").strip().lower() == "unstable"),
    }


def resume_data_quality_agentic_workflow_after_rule_review(
    settings,
    run_id: str,
    event_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    run_row = get_quality_run_by_run_id(settings, run_id)
    if not run_row:
        raise ValueError("Data quality run not found")
    tenant_id = str(run_row.get("tenant_id") or "").strip()
    domain_id = str(run_row.get("domain_id") or "data_quality_observability").strip() or "data_quality_observability"
    connection_id = str(run_row.get("connection_id") or "").strip()
    database_name = str(run_row.get("database_name") or "").strip()
    schema_name = str(run_row.get("schema_name") or "public").strip() or "public"
    quality_run_id = str(run_row.get("quality_run_id") or "").strip()
    profile_row = get_table_profile_artifact(
        settings,
        tenant_id=tenant_id,
        domain_id=domain_id,
        run_id=run_id,
        connection_id=connection_id,
        database_name=database_name,
        schema_name=schema_name,
    )
    profiling = (profile_row or {}).get("profiling_json") or {}
    rules = list_quality_rules(
        settings,
        tenant_id=tenant_id,
        domain_id=domain_id,
        run_id=run_id,
        limit=1200,
    )
    pending_review = [row for row in rules if _rule_status(row) in {"needs_review", "unsupported"}]
    if pending_review:
        raise ValueError("Rule review is still pending for this run")
    active_rules = [row for row in rules if _rule_status(row) == "active"]
    scope = {
        "tenant_id": tenant_id,
        "domain_id": domain_id,
        "run_id": run_id,
        "connection_id": connection_id,
        "database_name": database_name,
        "schema_name": schema_name,
    }
    summary = dict(run_row.get("summary_json") or {})
    create_or_update_quality_run(
        settings,
        **scope,
        status="running",
        overall_trust_score=summary.get("average_table_trust_score"),
        trend_mode=str(run_row.get("trend_mode") or "").strip() or None,
        trend_scope_key=str(run_row.get("trend_scope_key") or "").strip() or None,
        trend_scope_label=str(run_row.get("trend_scope_label") or "").strip() or None,
        baseline_run_id=run_row.get("baseline_run_id"),
        summary_json=summary,
    )
    _emit(
        settings,
        run_id,
        "DataQualityRuleAgent",
        "running",
        "Executing approved data quality rules after review",
        {"active_rule_count": len(active_rules)},
        event_callback=event_callback,
    )
    execution = execute_quality_rules(
        settings,
        rules=active_rules,
        schema_name=schema_name,
        scoped_conn=_resolve_scoped_conn_from_scope(settings, scope),
    )
    rule_summary = _rule_summary_from_rules(rules, execution)
    duplicate_candidates = list_quality_duplicate_candidates(
        settings,
        tenant_id=tenant_id,
        domain_id=domain_id,
        run_id=run_id,
        limit=1200,
    )
    quality_tables = list_quality_tables(
        settings,
        tenant_id=tenant_id,
        domain_id=domain_id,
        run_id=run_id,
        limit=1200,
    )
    freshness_results = _freshness_results_from_quality_tables(quality_tables)
    freshness_summary = _freshness_summary_from_results(freshness_results)
    updated_summary = _merge_phase58_summary(
        summary,
        _quality_summary(
            profiling,
            summary.get("persisted") or {"tables": len(quality_tables), "columns": 0},
            rule_summary,
            _duplicate_summary_from_candidates(duplicate_candidates),
            freshness_summary,
        ),
    )
    updated_summary.update(
        {
            "active_rule_count": rule_summary.get("active_rule_count", 0),
            "needs_review_rule_count": rule_summary.get("needs_review_rule_count", 0),
            "unsupported_rule_count": rule_summary.get("unsupported_rule_count", 0),
            "rejected_rule_count": rule_summary.get("rejected_rule_count", 0),
        }
    )
    updated_summary["rule_review_required"] = False
    updated_summary["review_queue_pending_count"] = 0
    updated_summary["workflow_status"] = "running"
    _emit(
        settings,
        run_id,
        "DataQualityRuleAgent",
        "completed",
        "Approved data quality rules executed after review",
        rule_summary,
        event_callback=event_callback,
    )
    _emit(
        settings,
        run_id,
        "DataEnrichmentOpportunityAgent",
        "running",
        "Discovering enrichment opportunities from quality artifacts",
        event_callback=event_callback,
    )
    opportunities = discover_enrichment_opportunities(
        profiling,
        quality_run_id=quality_run_id,
        run_id=run_id,
        tenant_id=tenant_id,
        domain_id=domain_id,
    ) if quality_run_id else []
    inserted = replace_quality_enrichment_opportunities(
        settings,
        quality_run_id=quality_run_id,
        run_id=run_id,
        tenant_id=tenant_id,
        domain_id=domain_id,
        opportunities=opportunities,
    ) if quality_run_id else 0
    updated_summary["enrichment_opportunity_count"] = inserted
    updated_summary["external_lookup_opportunity_count"] = sum(
        1 for item in opportunities if item.get("requires_external_lookup")
    )
    create_or_update_quality_run(
        settings,
        **scope,
        status="running",
        overall_trust_score=updated_summary.get("average_table_trust_score"),
        trend_mode=str(run_row.get("trend_mode") or "").strip() or None,
        trend_scope_key=str(run_row.get("trend_scope_key") or "").strip() or None,
        trend_scope_label=str(run_row.get("trend_scope_label") or "").strip() or None,
        baseline_run_id=run_row.get("baseline_run_id"),
        summary_json=updated_summary,
    )
    _emit(
        settings,
        run_id,
        "DataEnrichmentOpportunityAgent",
        "completed",
        "Enrichment opportunities identified",
        {
            "opportunity_count": inserted,
            "external_lookup_opportunity_count": updated_summary.get("external_lookup_opportunity_count", 0),
        },
        event_callback=event_callback,
    )
    rule_rows = _merge_rule_rows(active_rules, execution.get("results", []))
    _emit(
        settings,
        run_id,
        "DataTrustScoringAgent",
        "running",
        "Computing data trust from quality, duplicate, freshness, and enrichment signals",
        event_callback=event_callback,
    )
    trust = compute_data_quality_trust_scores(
        quality_tables=quality_tables,
        quality_rules=rule_rows,
        duplicate_candidates=duplicate_candidates,
        freshness_results=freshness_results,
        enrichment_opportunities=opportunities,
    )
    update_quality_table_trust_scores(
        settings,
        quality_run_id=quality_run_id,
        table_scores=trust.get("tables") or [],
    )
    quality_tables = list_quality_tables(
        settings,
        tenant_id=tenant_id,
        domain_id=domain_id,
        run_id=run_id,
        limit=1200,
    )
    updated_summary.update(trust.get("summary") or {})
    create_or_update_quality_run(
        settings,
        **scope,
        status="running",
        overall_trust_score=updated_summary.get("average_table_trust_score"),
        trend_mode=str(run_row.get("trend_mode") or "").strip() or None,
        trend_scope_key=str(run_row.get("trend_scope_key") or "").strip() or None,
        trend_scope_label=str(run_row.get("trend_scope_label") or "").strip() or None,
        baseline_run_id=run_row.get("baseline_run_id"),
        summary_json=updated_summary,
    )
    _emit(
        settings,
        run_id,
        "DataTrustScoringAgent",
        "completed",
        "Data trust summary completed",
        updated_summary,
        event_callback=event_callback,
    )
    _emit(
        settings,
        run_id,
        "TrendAnalysisAgent",
        "running",
        "Persisting trend snapshots and computing run-over-run deltas",
        event_callback=event_callback,
    )
    trend_result = _persist_trend_artifacts(
        settings,
        run_id,
        {
            "tenant_id": tenant_id,
            "domain_id": domain_id,
            "connection_id": connection_id,
            "database_name": database_name,
            "schema_name": schema_name,
            "quality_run_id": quality_run_id,
            "trend_mode": run_row.get("trend_mode"),
            "trend_scope_key": run_row.get("trend_scope_key"),
            "trend_scope_label": run_row.get("trend_scope_label"),
            "overall_trust_score": updated_summary.get("average_table_trust_score"),
            "quality_summary": updated_summary,
        },
    )
    updated_summary.update(trend_result.get("summary") or {})
    _emit(
        settings,
        run_id,
        "TrendAnalysisAgent",
        "completed",
        "Trend snapshots and deltas persisted",
        {
            "baseline_run_id": updated_summary.get("baseline_run_id"),
            "trend_row_count": updated_summary.get("trend_row_count", 0),
            "improved_metric_count": updated_summary.get("improved_metric_count", 0),
            "worsened_metric_count": updated_summary.get("worsened_metric_count", 0),
        },
        event_callback=event_callback,
    )
    _emit(
        settings,
        run_id,
        "AnomalyDetectionAgent",
        "running",
        "Deriving anomaly records from persisted quality trends and regressions",
        event_callback=event_callback,
    )
    anomaly_result = _persist_anomaly_artifacts(
        settings,
        run_id,
        {
            "tenant_id": tenant_id,
            "domain_id": domain_id,
            "connection_id": connection_id,
            "database_name": database_name,
            "schema_name": schema_name,
            "quality_run_id": quality_run_id,
            "trend_scope_key": run_row.get("trend_scope_key"),
            "baseline_run_id": updated_summary.get("baseline_run_id"),
            "quality_summary": updated_summary,
        },
    )
    updated_summary.update(anomaly_result.get("summary") or {})
    _emit(
        settings,
        run_id,
        "AnomalyDetectionAgent",
        "completed",
        "Anomaly records persisted",
        {
            "anomaly_count": updated_summary.get("anomaly_count", 0),
            "critical_anomaly_count": updated_summary.get("critical_anomaly_count", 0),
        },
        event_callback=event_callback,
    )
    _emit(
        settings,
        run_id,
        "IssueRegisterAgent",
        "running",
        "Deriving issue register from persisted quality, stage, and trend artifacts",
        event_callback=event_callback,
    )
    issue_result = _persist_issue_artifacts(
        settings,
        run_id,
        {
            "tenant_id": tenant_id,
            "domain_id": domain_id,
            "connection_id": connection_id,
            "database_name": database_name,
            "schema_name": schema_name,
            "quality_run_id": quality_run_id,
            "trend_mode": run_row.get("trend_mode"),
            "trend_scope_key": run_row.get("trend_scope_key"),
            "trend_scope_label": run_row.get("trend_scope_label"),
            "overall_trust_score": updated_summary.get("average_table_trust_score"),
            "quality_summary": updated_summary,
            "freshness_results": freshness_results,
        },
    )
    updated_summary.update(issue_result.get("summary") or {})
    _emit(
        settings,
        run_id,
        "IssueRegisterAgent",
        "completed",
        "Issue register updated",
        {
            "issue_count": updated_summary.get("issue_count", 0),
            "open_issue_count": updated_summary.get("open_issue_count", 0),
            "overdue_issue_count": updated_summary.get("overdue_issue_count", 0),
        },
        event_callback=event_callback,
    )
    _emit(
        settings,
        run_id,
        "DataQualityDashboardAgent",
        "running",
        "Building data quality dashboard from persisted artifacts",
        event_callback=event_callback,
    )
    dashboard = create_data_quality_dashboard(
        settings,
        tenant_id=tenant_id,
        domain_id=domain_id,
        run_id=run_id,
        profiling=profiling,
        quality_tables=quality_tables,
        quality_summary=updated_summary,
        quality_rules=active_rules,
        quality_rule_results=execution.get("results") or [],
        duplicate_candidates=duplicate_candidates,
        freshness_results=freshness_results,
        enrichment_opportunities=opportunities,
        dataset_stages=list_quality_dataset_stages(settings, tenant_id=tenant_id, domain_id=domain_id, run_id=run_id, limit=1200),
        join_artifacts=list_quality_join_artifacts(settings, tenant_id=tenant_id, domain_id=domain_id, run_id=run_id, limit=1200),
        lineage_edges=list_quality_lineage_edges(settings, tenant_id=tenant_id, domain_id=domain_id, run_id=run_id, limit=4000),
        row_outcomes=list_quality_stage_row_outcomes(settings, tenant_id=tenant_id, domain_id=domain_id, run_id=run_id, limit=4000),
        final_dataset=get_quality_final_dataset_artifact(settings, tenant_id=tenant_id, domain_id=domain_id, run_id=run_id) or {},
        trends=trend_result.get("trends") or [],
        anomalies=anomaly_result.get("anomalies") or [],
        issues=issue_result.get("issues") or [],
    )
    if dashboard.get("dashboard_id"):
        updated_summary["dashboard_id"] = dashboard.get("dashboard_id")
        updated_summary["dashboard_title"] = dashboard.get("dashboard_title")
        updated_summary["dashboard_chart_count"] = len(dashboard.get("chart_plan") or [])
        updated_summary["remediation_action_count"] = dashboard.get("remediation_action_count", 0)
        updated_summary["critical_remediation_action_count"] = dashboard.get("critical_remediation_action_count", 0)
        updated_summary["anomaly_count"] = dashboard.get("anomaly_count", 0)
        updated_summary["critical_anomaly_count"] = dashboard.get("critical_anomaly_count", 0)
        updated_summary["open_issue_count"] = dashboard.get("open_issue_count", 0)
        updated_summary["overdue_issue_count"] = dashboard.get("overdue_issue_count", 0)
    updated_summary["workflow_status"] = "completed"
    create_or_update_quality_run(
        settings,
        **scope,
        status="completed",
        overall_trust_score=updated_summary.get("average_table_trust_score"),
        trend_mode=str(run_row.get("trend_mode") or "").strip() or None,
        trend_scope_key=str(run_row.get("trend_scope_key") or "").strip() or None,
        trend_scope_label=str(run_row.get("trend_scope_label") or "").strip() or None,
        baseline_run_id=updated_summary.get("baseline_run_id"),
        summary_json=updated_summary,
        completed=True,
    )
    append_agent_chat_log(
        settings,
        run_id,
        "system",
        "Data quality workflow resumed after rule review and completed successfully.",
    )
    _emit(
        settings,
        run_id,
        "DataQualityDashboardAgent",
        "completed",
        "Data quality dashboard created",
        {
            "dashboard_id": dashboard.get("dashboard_id"),
            "dashboard_title": dashboard.get("dashboard_title"),
            "chart_count": len(dashboard.get("chart_plan") or []),
        },
        event_callback=event_callback,
    )
    return {
        "workflow_kind": "data_quality",
        "quality_run_id": quality_run_id,
        "profiling_stats": profiling,
        "quality_rules": rules,
        "quality_rule_summary": rule_summary,
        "quality_rule_results": execution.get("results", []),
        "quality_rule_rows": rule_rows,
        "duplicate_candidates": duplicate_candidates,
        "freshness_results": freshness_results,
        "quality_tables": quality_tables,
        "quality_summary": updated_summary,
        "enrichment_opportunities": opportunities,
        "dashboard_id": dashboard.get("dashboard_id"),
        "dashboard_title": dashboard.get("dashboard_title"),
        "run_status": "completed",
    }


def run_data_quality_agentic_workflow(
    settings,
    run_id: str,
    initial_state: dict[str, Any],
    event_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    if StateGraph is None or END is None:
        raise RuntimeError("LangGraph is not available. Install the 'langgraph' package in the active runtime environment.")

    graph = StateGraph(dict)

    def router_node(state: dict[str, Any]) -> dict[str, Any]:
        scope = _scope(state, run_id)
        quality_run_id = create_or_update_quality_run(
            settings,
            **scope,
            status="running",
            trend_mode=str(state.get("trend_mode") or "").strip() or None,
            trend_scope_key=str(state.get("trend_scope_key") or "").strip() or None,
            trend_scope_label=str(state.get("trend_scope_label") or "").strip() or None,
            summary_json={"workflow_kind": "data_quality"},
        )
        state["workflow_kind"] = "data_quality"
        state["quality_run_id"] = quality_run_id
        _emit(
            settings,
            run_id,
            "DataQualityWorkflowRouter",
            "completed",
            "Data quality workflow selected",
            {"workflow_kind": "data_quality", "quality_run_id": quality_run_id},
            event_callback=event_callback,
        )
        return state

    def schema_node(state: dict[str, Any]) -> dict[str, Any]:
        _emit(settings, run_id, "DataQualitySchemaAgent", "running", "Scanning schema for data quality analysis", event_callback=event_callback)
        scope = _scope(state, run_id)
        schema_payload = state.get("schema_payload") or {}
        schema_graph = enrich_schema_graph_columns(
            settings,
            build_schema_graph(schema_payload),
            scope["schema_name"],
            scoped_conn=_scoped_conn_from_state(state),
        )
        state["schema_graph"] = schema_graph
        try:
            persist_schema_graph_artifact(settings, schema_graph=schema_graph, **scope)
        except Exception:
            logger.exception("data_quality.schema.persist_failed | run_id=%s", run_id)
        tables = schema_graph.get("tables") or []
        _emit(
            settings,
            run_id,
            "DataQualitySchemaAgent",
            "completed",
            "Schema scan ready for data quality analysis",
            {"tables": len(tables), "table_names": [table.get("name") for table in tables]},
            event_callback=event_callback,
        )
        return state

    def _ensure_stage_plan(state: dict[str, Any]) -> dict[str, Any]:
        existing_plan = state.get("dataset_stage_plan")
        if isinstance(existing_plan, dict) and existing_plan.get("stages") is not None:
            return state
        _emit(
            settings,
            run_id,
            "DatasetStagePlannerAgent",
            "running",
            "Planning multi-table data quality stages from schema and context",
            event_callback=event_callback,
        )
        scope = _scope(state, run_id)
        quality_run_id = str(state.get("quality_run_id") or "").strip()
        stage_plan = infer_stage_plan_tool(
            schema_graph=state.get("schema_graph") or {},
            context_text=state.get("context_text"),
            settings=settings,
        )
        scoped_conn = _scoped_conn_from_state(state) or _resolve_scoped_conn_from_scope(settings, scope)
        if scoped_conn is not None:
            stage_plan = compute_stage_plan_metrics_tool(
                settings,
                scoped_conn=scoped_conn,
                schema_name=scope["schema_name"],
                tenant_id=scope["tenant_id"],
                domain_id=scope["domain_id"],
                stage_plan=stage_plan,
            )
        if quality_run_id:
            replace_quality_dataset_stages(
                settings,
                quality_run_id=quality_run_id,
                run_id=run_id,
                tenant_id=scope["tenant_id"],
                domain_id=scope["domain_id"],
                stages=stage_plan.get("stages") or [],
            )
            replace_quality_join_artifacts(
                settings,
                quality_run_id=quality_run_id,
                run_id=run_id,
                tenant_id=scope["tenant_id"],
                domain_id=scope["domain_id"],
                joins=stage_plan.get("joins") or [],
            )
            replace_quality_stage_row_outcomes(
                settings,
                quality_run_id=quality_run_id,
                run_id=run_id,
                tenant_id=scope["tenant_id"],
                domain_id=scope["domain_id"],
                row_outcomes=stage_plan.get("row_outcomes") or [],
            )
            replace_quality_lineage_edges(
                settings,
                quality_run_id=quality_run_id,
                run_id=run_id,
                tenant_id=scope["tenant_id"],
                domain_id=scope["domain_id"],
                edges=stage_plan.get("lineage_edges") or [],
            )
            upsert_quality_final_dataset_artifact(
                settings,
                quality_run_id=quality_run_id,
                run_id=run_id,
                tenant_id=scope["tenant_id"],
                domain_id=scope["domain_id"],
                artifact=stage_plan.get("final_dataset") or {},
            )
        state["dataset_stage_plan"] = stage_plan
        updated_summary = dict(state.get("quality_summary") or {})
        updated_summary["dataset_stage_plan"] = stage_plan
        updated_summary["dataset_stage_count"] = stage_plan.get("stage_count", 0)
        updated_summary["join_stage_count"] = stage_plan.get("join_stage_count", 0)
        updated_summary["filter_stage_count"] = stage_plan.get("filter_stage_count", 0)
        updated_summary["total_rejected_row_count"] = stage_plan.get("rejected_row_count", 0)
        updated_summary["lineage_edge_count"] = len(stage_plan.get("lineage_edges") or [])
        updated_summary["final_dataset_row_count"] = (stage_plan.get("final_dataset") or {}).get("final_row_count")
        updated_summary["final_dataset_readiness_status"] = (stage_plan.get("final_dataset") or {}).get("readiness_status")
        state["quality_summary"] = updated_summary
        create_or_update_quality_run(
            settings,
            **scope,
            status="running",
            overall_trust_score=updated_summary.get("average_table_trust_score"),
            trend_mode=str(state.get("trend_mode") or "").strip() or None,
            trend_scope_key=str(state.get("trend_scope_key") or "").strip() or None,
            trend_scope_label=str(state.get("trend_scope_label") or "").strip() or None,
            baseline_run_id=state.get("baseline_run_id"),
            summary_json=updated_summary,
        )
        _emit(
            settings,
            run_id,
            "DatasetStagePlannerAgent",
            "completed",
            "Multi-table data quality stage plan prepared",
            {
                "stage_count": stage_plan.get("stage_count", 0),
                "join_stage_count": stage_plan.get("join_stage_count", 0),
                "filter_stage_count": stage_plan.get("filter_stage_count", 0),
                "stage_names": [item.get("stage_name") for item in (stage_plan.get("stages") or [])],
                "measured_stage_count": sum(
                    1
                    for item in (stage_plan.get("stages") or [])
                    if str((item.get("summary_json") or {}).get("measurement_status") or "").strip() in {"measured", "derived"}
                ),
                "rejected_row_count": stage_plan.get("rejected_row_count", 0),
                "lineage_edge_count": len(stage_plan.get("lineage_edges") or []),
                "final_dataset_row_count": (stage_plan.get("final_dataset") or {}).get("final_row_count"),
            },
            event_callback=event_callback,
        )
        return state

    def profiling_node(state: dict[str, Any]) -> dict[str, Any]:
        state = _ensure_stage_plan(state)
        _emit(settings, run_id, "DataQualityProfilingAgent", "running", "Profiling tables for quality signals", event_callback=event_callback)
        scope = _scope(state, run_id)
        try:
            profiling = profile_tables(
                settings,
                state.get("schema_graph") or {},
                scope["schema_name"],
                scoped_conn=_scoped_conn_from_state(state),
            )
        except Exception:
            logger.exception("data_quality.profiling.failed | run_id=%s", run_id)
            profiling = {"tables": [], "quality_overview": {}, "errors": ["profiling_failed"]}
        state["profiling_stats"] = profiling
        try:
            persist_table_profile_artifact(settings, profiling_json=profiling, **scope)
        except Exception:
            logger.exception("data_quality.profile_artifact.persist_failed | run_id=%s", run_id)
        quality_run_id = state.get("quality_run_id")
        persisted = {"tables": 0, "columns": 0}
        if quality_run_id:
            persisted = upsert_quality_artifacts_from_profiling(
                settings,
                quality_run_id=str(quality_run_id),
                profiling_json=profiling,
                **scope,
            )
        summary = _merge_phase58_summary(state.get("quality_summary"), _quality_summary(profiling, persisted))
        state["quality_summary"] = summary
        create_or_update_quality_run(
            settings,
            **scope,
            status="running",
            overall_trust_score=summary.get("average_table_trust_score"),
            trend_mode=str(state.get("trend_mode") or "").strip() or None,
            trend_scope_key=str(state.get("trend_scope_key") or "").strip() or None,
            trend_scope_label=str(state.get("trend_scope_label") or "").strip() or None,
            baseline_run_id=state.get("baseline_run_id"),
            summary_json=summary,
        )
        _emit(
            settings,
            run_id,
            "DataQualityProfilingAgent",
            "completed",
            "Data quality profiling completed",
            summary,
            event_callback=event_callback,
        )
        return state

    def stage_planner_node(state: dict[str, Any]) -> dict[str, Any]:
        return _ensure_stage_plan(state)

    def rules_node(state: dict[str, Any]) -> dict[str, Any]:
        _emit(settings, run_id, "DataQualityRuleAgent", "running", "Extracting and classifying data quality rules", event_callback=event_callback)
        scope = _scope(state, run_id)
        quality_run_id = state.get("quality_run_id")
        pause_for_rule_review = bool(state.get("pause_for_rule_review", True))
        auto_approve_all = data_quality_rule_auto_approve_all_enabled()
        resume_after_rule_review = bool(state.get("resume_after_rule_review"))
        planned_rules = plan_quality_rules_from_context(
            context_text=state.get("context_text"),
            schema_graph=state.get("schema_graph") or {},
            settings=settings,
        )
        rules = list(planned_rules.get("rules") or [])
        rule_planner_mode = str(planned_rules.get("planner_mode") or "deterministic")
        validation_controls = list(planned_rules.get("validation_controls") or [])
        for rule in rules:
            source_text = str(
                rule.get("source_text")
                or (rule.get("condition_json") or {}).get("source_text")
                or state.get("context_text")
                or ""
            ).strip()
            if source_text:
                rule["source_text"] = source_text[:4000]
            execution_plan = build_quality_rule_execution_plan(
                rule,
                schema_name=scope["schema_name"],
                settings=settings,
            )
            rule["executor_kind"] = execution_plan.get("executor_kind")
            rule["execution_plan_json"] = execution_plan
            rule["status"] = classify_quality_rule_review_status(rule)
        rule_coverage = build_validation_rule_coverage(
            validation_controls=validation_controls,
            rules=rules,
            planner_mode=rule_planner_mode,
        )
        inserted = 0
        execution = {"rules_executed": 0, "failed_rules": 0, "passed_rules": 0, "error_rules": 0, "results": []}
        if quality_run_id and rules:
            inserted = replace_quality_rules(
                settings,
                quality_run_id=str(quality_run_id),
                rules=rules,
                source="context_text",
                **scope,
            )
        executable_rules = [item for item in rules if _rule_status(item) == "active"]
        rule_summary = _rule_summary_from_rules(rules, execution)
        rule_summary["rule_count"] = inserted
        review_pending_count = int(rule_summary.get("needs_review_rule_count", 0)) + int(rule_summary.get("unsupported_rule_count", 0))
        if auto_approve_all:
            rule_summary["review_required"] = False
            rule_summary["review_pending_count"] = 0
        if pause_for_rule_review and not auto_approve_all and not resume_after_rule_review and review_pending_count > 0:
            rule_summary["review_required"] = True
            rule_summary["review_pending_count"] = review_pending_count
            state["quality_rules"] = rules
            state["quality_rule_summary"] = rule_summary
            state["quality_rule_results"] = []
            state["quality_rule_rows"] = _merge_rule_rows(rules, [])
            state["awaiting_rule_review"] = True
            state["run_status"] = "awaiting_rule_review"
            updated_summary = _merge_phase58_summary(
                state.get("quality_summary"),
                _quality_summary(
                state.get("profiling_stats") or {},
                (state.get("quality_summary") or {}).get("persisted") or {"tables": 0, "columns": 0},
                rule_summary,
                state.get("duplicate_summary") or {},
                state.get("freshness_summary") or {},
                ),
            )
            updated_summary.update(
                {
                    "active_rule_count": rule_summary.get("active_rule_count", 0),
                    "needs_review_rule_count": rule_summary.get("needs_review_rule_count", 0),
                    "unsupported_rule_count": rule_summary.get("unsupported_rule_count", 0),
                    "rejected_rule_count": rule_summary.get("rejected_rule_count", 0),
                    "rule_validation_planner_mode": rule_planner_mode,
                    "validation_control_count": rule_coverage.get("validation_control_count", 0),
                    "compiled_validation_control_count": rule_coverage.get("compiled_validation_control_count", 0),
                    "uncovered_validation_control_count": rule_coverage.get("uncovered_validation_control_count", 0),
                    "validation_controls": validation_controls,
                    "rule_coverage": rule_coverage,
                }
            )
            updated_summary["rule_review_required"] = True
            updated_summary["review_queue_pending_count"] = review_pending_count
            updated_summary["workflow_status"] = "awaiting_rule_review"
            state["quality_summary"] = updated_summary
            create_or_update_quality_run(
                settings,
                **scope,
                status="awaiting_rule_review",
                overall_trust_score=updated_summary.get("average_table_trust_score"),
                trend_mode=str(state.get("trend_mode") or "").strip() or None,
                trend_scope_key=str(state.get("trend_scope_key") or "").strip() or None,
                trend_scope_label=str(state.get("trend_scope_label") or "").strip() or None,
                baseline_run_id=state.get("baseline_run_id"),
                summary_json=updated_summary,
            )
            _emit(
                settings,
                run_id,
                "DataQualityRuleAgent",
                "needs_review",
                "Rule interpretation review required before validation execution",
                rule_summary,
                event_callback=event_callback,
            )
            return state
        execution = execute_quality_rules(
            settings,
            rules=executable_rules,
            schema_name=scope["schema_name"],
            scoped_conn=_scoped_conn_from_state(state),
        )
        rule_summary = _rule_summary_from_rules(rules, execution)
        rule_summary["rule_count"] = inserted
        state["quality_rules"] = rules
        state["quality_rule_summary"] = rule_summary
        state["quality_rule_results"] = execution.get("results", [])
        state["quality_rule_rows"] = _merge_rule_rows(rules, execution.get("results", []))
        state["quality_summary"] = _merge_phase58_summary(
            state.get("quality_summary"),
            _quality_summary(
                state.get("profiling_stats") or {},
                (state.get("quality_summary") or {}).get("persisted") or {"tables": 0, "columns": 0},
                rule_summary,
                state.get("duplicate_summary") or {},
                state.get("freshness_summary") or {},
            ),
        )
        state["quality_summary"].update(
            {
                "active_rule_count": rule_summary.get("active_rule_count", 0),
                "needs_review_rule_count": rule_summary.get("needs_review_rule_count", 0),
                "unsupported_rule_count": rule_summary.get("unsupported_rule_count", 0),
                "rejected_rule_count": rule_summary.get("rejected_rule_count", 0),
                "rule_validation_planner_mode": rule_planner_mode,
                "validation_control_count": rule_coverage.get("validation_control_count", 0),
                "compiled_validation_control_count": rule_coverage.get("compiled_validation_control_count", 0),
                "uncovered_validation_control_count": rule_coverage.get("uncovered_validation_control_count", 0),
                "validation_controls": validation_controls,
                "rule_coverage": rule_coverage,
            }
        )
        state["quality_summary"]["rule_review_required"] = False
        state["quality_summary"]["review_queue_pending_count"] = 0
        state["quality_summary"]["workflow_status"] = "running"
        create_or_update_quality_run(
            settings,
            **scope,
            status="running",
            overall_trust_score=state["quality_summary"].get("average_table_trust_score"),
            trend_mode=str(state.get("trend_mode") or "").strip() or None,
            trend_scope_key=str(state.get("trend_scope_key") or "").strip() or None,
            trend_scope_label=str(state.get("trend_scope_label") or "").strip() or None,
            baseline_run_id=state.get("baseline_run_id"),
            summary_json=state["quality_summary"],
        )
        _emit(
            settings,
            run_id,
            "DataQualityRuleAgent",
            "completed",
            "Data quality rule execution completed",
            rule_summary,
            event_callback=event_callback,
        )
        return state

    def pause_review_node(state: dict[str, Any]) -> dict[str, Any]:
        append_agent_chat_log(
            settings,
            run_id,
            "system",
            "Data quality workflow paused for rule review before validation execution.",
        )
        _emit(
            settings,
            run_id,
            "DataQualityReviewGate",
            "awaiting_rule_review",
            "Review ambiguous or unsupported rules, then resume the data quality run.",
            {
                "review_queue_pending_count": (state.get("quality_summary") or {}).get("review_queue_pending_count", 0),
            },
            event_callback=event_callback,
        )
        return state

    def duplicate_node(state: dict[str, Any]) -> dict[str, Any]:
        _emit(
            settings,
            run_id,
            "DuplicateDetectionAgent",
            "running",
            "Detecting exact and likely duplicate candidates",
            event_callback=event_callback,
        )
        scope = _scope(state, run_id)
        quality_run_id = str(state.get("quality_run_id") or "").strip()
        candidates: list[dict[str, Any]] = []
        inserted = 0
        if quality_run_id:
            candidates = detect_duplicate_candidates(
                settings,
                profiling=state.get("profiling_stats") or {},
                schema_name=scope["schema_name"],
                scoped_conn=_scoped_conn_from_state(state),
                quality_run_id=quality_run_id,
                run_id=run_id,
                tenant_id=scope["tenant_id"],
                domain_id=scope["domain_id"],
            )
            inserted = replace_quality_duplicate_candidates(
                settings,
                quality_run_id=quality_run_id,
                run_id=run_id,
                tenant_id=scope["tenant_id"],
                domain_id=scope["domain_id"],
                candidates=candidates,
            )
        summary = {
            "duplicate_candidate_count": inserted,
            "exact_duplicate_candidate_count": sum(1 for item in candidates if str(item.get("duplicate_type") or "").startswith("exact_")),
            "fuzzy_duplicate_candidate_count": sum(1 for item in candidates if str(item.get("duplicate_type") or "").startswith("fuzzy_")),
        }
        state["duplicate_candidates"] = candidates
        state["duplicate_summary"] = summary
        updated_summary = dict(state.get("quality_summary") or {})
        updated_summary.update(summary)
        state["quality_summary"] = updated_summary
        create_or_update_quality_run(
            settings,
            **scope,
            status="running",
            overall_trust_score=updated_summary.get("average_table_trust_score"),
            trend_mode=str(state.get("trend_mode") or "").strip() or None,
            trend_scope_key=str(state.get("trend_scope_key") or "").strip() or None,
            trend_scope_label=str(state.get("trend_scope_label") or "").strip() or None,
            baseline_run_id=state.get("baseline_run_id"),
            summary_json=updated_summary,
        )
        _emit(
            settings,
            run_id,
            "DuplicateDetectionAgent",
            "completed",
            "Duplicate candidate detection completed",
            summary,
            event_callback=event_callback,
        )
        return state

    def freshness_node(state: dict[str, Any]) -> dict[str, Any]:
        _emit(
            settings,
            run_id,
            "FreshnessAndStabilityAgent",
            "running",
            "Evaluating freshness and stability against historical quality runs",
            event_callback=event_callback,
        )
        scope = _scope(state, run_id)
        quality_run_id = str(state.get("quality_run_id") or "").strip()
        previous_run = get_previous_quality_run(
            settings,
            tenant_id=scope["tenant_id"],
            domain_id=scope["domain_id"],
            current_run_id=run_id,
        )
        previous_tables_by_name: dict[str, dict[str, Any]] = {}
        if previous_run and previous_run.get("quality_run_id"):
            previous_tables_by_name = {
                str(item.get("table_name") or ""): item
                for item in list_quality_tables_by_quality_run(
                    settings,
                    quality_run_id=str(previous_run.get("quality_run_id")),
                )
                if str(item.get("table_name") or "")
            }
        analysis = analyze_freshness_and_stability(
            profiling=state.get("profiling_stats") or {},
            previous_tables_by_name=previous_tables_by_name,
        )
        results = analysis.get("results") or []
        if quality_run_id:
            for item in results:
                table_name = str(item.get("table_name") or "").strip()
                if not table_name:
                    continue
                update_quality_table_monitoring(
                    settings,
                    quality_run_id=quality_run_id,
                    table_name=table_name,
                    freshness_score=item.get("freshness_score"),
                    monitoring_json={
                        "freshness_analysis": item,
                        "stability_analysis": {
                            "baseline_quality_run_id": item.get("baseline_quality_run_id"),
                            "baseline_row_count": item.get("baseline_row_count"),
                            "row_count_change_pct": item.get("row_count_change_pct"),
                            "baseline_completeness_score": item.get("baseline_completeness_score"),
                            "completeness_score_change": item.get("completeness_score_change"),
                            "stability_status": item.get("stability_status"),
                            "stability_issues": item.get("stability_issues") or [],
                        },
                    },
                )
        summary = dict(analysis.get("summary") or {})
        summary["baseline_quality_run_id"] = previous_run.get("quality_run_id") if previous_run else None
        state["freshness_results"] = results
        state["freshness_summary"] = summary
        updated_summary = dict(state.get("quality_summary") or {})
        updated_summary.update(summary)
        state["quality_summary"] = updated_summary
        create_or_update_quality_run(
            settings,
            **scope,
            status="running",
            overall_trust_score=updated_summary.get("average_table_trust_score"),
            trend_mode=str(state.get("trend_mode") or "").strip() or None,
            trend_scope_key=str(state.get("trend_scope_key") or "").strip() or None,
            trend_scope_label=str(state.get("trend_scope_label") or "").strip() or None,
            baseline_run_id=state.get("baseline_run_id"),
            summary_json=updated_summary,
        )
        _emit(
            settings,
            run_id,
            "FreshnessAndStabilityAgent",
            "completed",
            "Freshness and stability analysis completed",
            summary,
            event_callback=event_callback,
        )
        return state

    def trust_node(state: dict[str, Any]) -> dict[str, Any]:
        scope = _scope(state, run_id)
        quality_tables = list_quality_tables(
            settings,
            tenant_id=scope["tenant_id"],
            domain_id=scope["domain_id"],
            run_id=run_id,
            limit=1200,
        )
        trust = compute_data_quality_trust_scores(
            quality_tables=quality_tables,
            quality_rules=state.get("quality_rule_rows") or [],
            duplicate_candidates=state.get("duplicate_candidates") or [],
            freshness_results=state.get("freshness_results") or [],
            enrichment_opportunities=state.get("enrichment_opportunities") or [],
        )
        update_quality_table_trust_scores(
            settings,
            quality_run_id=str(state.get("quality_run_id") or ""),
            table_scores=trust.get("tables") or [],
        )
        state["quality_tables"] = list_quality_tables(
            settings,
            tenant_id=scope["tenant_id"],
            domain_id=scope["domain_id"],
            run_id=run_id,
            limit=1200,
        )
        updated_summary = dict(state.get("quality_summary") or {})
        updated_summary.update(trust.get("summary") or {})
        state["quality_summary"] = updated_summary
        state["trust_results"] = trust.get("tables") or []
        create_or_update_quality_run(
            settings,
            **scope,
            status="running",
            overall_trust_score=updated_summary.get("average_table_trust_score"),
            trend_mode=str(state.get("trend_mode") or "").strip() or None,
            trend_scope_key=str(state.get("trend_scope_key") or "").strip() or None,
            trend_scope_label=str(state.get("trend_scope_label") or "").strip() or None,
            baseline_run_id=state.get("baseline_run_id"),
            summary_json=updated_summary,
        )
        _emit(
            settings,
            run_id,
            "DataTrustScoringAgent",
            "completed",
            "Data trust summary completed",
            updated_summary,
            event_callback=event_callback,
        )
        return state

    def dashboard_node(state: dict[str, Any]) -> dict[str, Any]:
        _emit(
            settings,
            run_id,
            "DataQualityDashboardAgent",
            "running",
            "Building data quality dashboard from persisted artifacts",
            event_callback=event_callback,
        )
        scope = _scope(state, run_id)
        dashboard = create_data_quality_dashboard(
            settings,
            tenant_id=scope["tenant_id"],
            domain_id=scope["domain_id"],
            run_id=run_id,
            profiling=state.get("profiling_stats") or {},
            quality_tables=state.get("quality_tables") or [],
            quality_summary=state.get("quality_summary") or {},
            quality_rules=state.get("quality_rules") or [],
            quality_rule_results=state.get("quality_rule_results") or [],
            duplicate_candidates=state.get("duplicate_candidates") or [],
            freshness_results=state.get("freshness_results") or [],
            enrichment_opportunities=state.get("enrichment_opportunities") or [],
            dataset_stages=list_quality_dataset_stages(settings, tenant_id=scope["tenant_id"], domain_id=scope["domain_id"], run_id=run_id, limit=1200),
            join_artifacts=list_quality_join_artifacts(settings, tenant_id=scope["tenant_id"], domain_id=scope["domain_id"], run_id=run_id, limit=1200),
            lineage_edges=list_quality_lineage_edges(settings, tenant_id=scope["tenant_id"], domain_id=scope["domain_id"], run_id=run_id, limit=4000),
            row_outcomes=list_quality_stage_row_outcomes(settings, tenant_id=scope["tenant_id"], domain_id=scope["domain_id"], run_id=run_id, limit=4000),
            final_dataset=get_quality_final_dataset_artifact(settings, tenant_id=scope["tenant_id"], domain_id=scope["domain_id"], run_id=run_id) or {},
            trends=list_quality_trends(settings, tenant_id=scope["tenant_id"], domain_id=scope["domain_id"], run_id=run_id, limit=4000),
            anomalies=list_quality_anomalies(settings, tenant_id=scope["tenant_id"], domain_id=scope["domain_id"], run_id=run_id, limit=1200),
            issues=list_quality_issues(settings, tenant_id=scope["tenant_id"], domain_id=scope["domain_id"], run_id=run_id, limit=1200),
        )
        state["dashboard_id"] = dashboard.get("dashboard_id")
        state["dashboard_title"] = dashboard.get("dashboard_title")
        updated_summary = dict(state.get("quality_summary") or {})
        if dashboard.get("dashboard_id"):
            updated_summary["dashboard_id"] = dashboard.get("dashboard_id")
            updated_summary["dashboard_title"] = dashboard.get("dashboard_title")
            updated_summary["dashboard_chart_count"] = len(dashboard.get("chart_plan") or [])
            updated_summary["remediation_action_count"] = dashboard.get("remediation_action_count", 0)
            updated_summary["critical_remediation_action_count"] = dashboard.get("critical_remediation_action_count", 0)
            updated_summary["anomaly_count"] = dashboard.get("anomaly_count", 0)
            updated_summary["critical_anomaly_count"] = dashboard.get("critical_anomaly_count", 0)
            updated_summary["open_issue_count"] = dashboard.get("open_issue_count", 0)
            updated_summary["overdue_issue_count"] = dashboard.get("overdue_issue_count", 0)
            state["quality_summary"] = updated_summary
            create_or_update_quality_run(
                settings,
                **scope,
                status="running",
                overall_trust_score=updated_summary.get("average_table_trust_score"),
                trend_mode=str(state.get("trend_mode") or "").strip() or None,
                trend_scope_key=str(state.get("trend_scope_key") or "").strip() or None,
                trend_scope_label=str(state.get("trend_scope_label") or "").strip() or None,
                baseline_run_id=updated_summary.get("baseline_run_id"),
                summary_json=updated_summary,
            )
        _emit(
            settings,
            run_id,
            "DataQualityDashboardAgent",
            "completed",
            "Data quality dashboard created",
            {
                "dashboard_id": dashboard.get("dashboard_id"),
                "dashboard_title": dashboard.get("dashboard_title"),
                "chart_count": len(dashboard.get("chart_plan") or []),
            },
            event_callback=event_callback,
        )
        return state

    def issues_node(state: dict[str, Any]) -> dict[str, Any]:
        _emit(
            settings,
            run_id,
            "IssueRegisterAgent",
            "running",
            "Deriving issue register from persisted quality, stage, and trend artifacts",
            event_callback=event_callback,
        )
        issue_result = _persist_issue_artifacts(settings, run_id, state)
        updated_summary = dict(state.get("quality_summary") or {})
        updated_summary.update(issue_result.get("summary") or {})
        state["quality_summary"] = updated_summary
        state["issues"] = issue_result.get("issues") or []
        scope = _scope(state, run_id)
        create_or_update_quality_run(
            settings,
            **scope,
            status="running",
            overall_trust_score=updated_summary.get("average_table_trust_score"),
            trend_mode=str(state.get("trend_mode") or "").strip() or None,
            trend_scope_key=str(state.get("trend_scope_key") or "").strip() or None,
            trend_scope_label=str(state.get("trend_scope_label") or "").strip() or None,
            baseline_run_id=updated_summary.get("baseline_run_id"),
            summary_json=updated_summary,
        )
        _emit(
            settings,
            run_id,
            "IssueRegisterAgent",
            "completed",
            "Issue register updated",
            {
                "issue_count": updated_summary.get("issue_count", 0),
                "open_issue_count": updated_summary.get("open_issue_count", 0),
                "overdue_issue_count": updated_summary.get("overdue_issue_count", 0),
            },
            event_callback=event_callback,
        )
        return state

    def anomalies_node(state: dict[str, Any]) -> dict[str, Any]:
        _emit(
            settings,
            run_id,
            "AnomalyDetectionAgent",
            "running",
            "Deriving anomaly records from persisted quality trends and regressions",
            event_callback=event_callback,
        )
        anomaly_result = _persist_anomaly_artifacts(settings, run_id, state)
        updated_summary = dict(state.get("quality_summary") or {})
        updated_summary.update(anomaly_result.get("summary") or {})
        state["quality_summary"] = updated_summary
        state["anomalies"] = anomaly_result.get("anomalies") or []
        scope = _scope(state, run_id)
        create_or_update_quality_run(
            settings,
            **scope,
            status="running",
            overall_trust_score=updated_summary.get("average_table_trust_score"),
            trend_mode=str(state.get("trend_mode") or "").strip() or None,
            trend_scope_key=str(state.get("trend_scope_key") or "").strip() or None,
            trend_scope_label=str(state.get("trend_scope_label") or "").strip() or None,
            baseline_run_id=updated_summary.get("baseline_run_id"),
            summary_json=updated_summary,
        )
        _emit(
            settings,
            run_id,
            "AnomalyDetectionAgent",
            "completed",
            "Anomaly records persisted",
            {
                "anomaly_count": updated_summary.get("anomaly_count", 0),
                "critical_anomaly_count": updated_summary.get("critical_anomaly_count", 0),
            },
            event_callback=event_callback,
        )
        return state

    def trends_node(state: dict[str, Any]) -> dict[str, Any]:
        _emit(
            settings,
            run_id,
            "TrendAnalysisAgent",
            "running",
            "Persisting trend snapshots and computing run-over-run deltas",
            event_callback=event_callback,
        )
        trend_result = _persist_trend_artifacts(settings, run_id, state)
        updated_summary = dict(state.get("quality_summary") or {})
        updated_summary.update(trend_result.get("summary") or {})
        state["quality_summary"] = updated_summary
        scope = _scope(state, run_id)
        create_or_update_quality_run(
            settings,
            **scope,
            status="running",
            overall_trust_score=updated_summary.get("average_table_trust_score"),
            trend_mode=str(state.get("trend_mode") or "").strip() or None,
            trend_scope_key=str(state.get("trend_scope_key") or "").strip() or None,
            trend_scope_label=str(state.get("trend_scope_label") or "").strip() or None,
            baseline_run_id=updated_summary.get("baseline_run_id"),
            summary_json=updated_summary,
        )
        _emit(
            settings,
            run_id,
            "TrendAnalysisAgent",
            "completed",
            "Trend snapshots and deltas persisted",
            {
                "baseline_run_id": updated_summary.get("baseline_run_id"),
                "trend_row_count": updated_summary.get("trend_row_count", 0),
                "improved_metric_count": updated_summary.get("improved_metric_count", 0),
                "worsened_metric_count": updated_summary.get("worsened_metric_count", 0),
            },
            event_callback=event_callback,
        )
        return state

    def finalize_node(state: dict[str, Any]) -> dict[str, Any]:
        summary = dict(state.get("quality_summary") or {})
        summary["workflow_status"] = "completed"
        state["quality_summary"] = summary
        scope = _scope(state, run_id)
        create_or_update_quality_run(
            settings,
            **scope,
            status="completed",
            overall_trust_score=summary.get("average_table_trust_score"),
            trend_mode=str(state.get("trend_mode") or "").strip() or None,
            trend_scope_key=str(state.get("trend_scope_key") or "").strip() or None,
            trend_scope_label=str(state.get("trend_scope_label") or "").strip() or None,
            baseline_run_id=summary.get("baseline_run_id"),
            summary_json=summary,
            completed=True,
        )
        append_agent_chat_log(
            settings,
            run_id,
            "system",
            "Data quality workflow completed with %s profiled tables."
            % summary.get("profiled_tables", 0),
        )
        return state

    def enrichment_node(state: dict[str, Any]) -> dict[str, Any]:
        _emit(
            settings,
            run_id,
            "DataEnrichmentOpportunityAgent",
            "running",
            "Discovering enrichment opportunities from quality artifacts",
            event_callback=event_callback,
        )
        scope = _scope(state, run_id)
        quality_run_id = str(state.get("quality_run_id") or "").strip()
        opportunities = []
        inserted = 0
        if quality_run_id:
            opportunities = discover_enrichment_opportunities(
                state.get("profiling_stats") or {},
                quality_run_id=quality_run_id,
                run_id=run_id,
                tenant_id=scope["tenant_id"],
                domain_id=scope["domain_id"],
            )
            inserted = replace_quality_enrichment_opportunities(
                settings,
                quality_run_id=quality_run_id,
                run_id=run_id,
                tenant_id=scope["tenant_id"],
                domain_id=scope["domain_id"],
                opportunities=opportunities,
            )
        state["enrichment_opportunities"] = opportunities
        updated_summary = dict(state.get("quality_summary") or {})
        updated_summary["enrichment_opportunity_count"] = inserted
        updated_summary["external_lookup_opportunity_count"] = sum(
            1 for item in opportunities if item.get("requires_external_lookup")
        )
        state["quality_summary"] = updated_summary
        create_or_update_quality_run(
            settings,
            **scope,
            status="running",
            overall_trust_score=updated_summary.get("average_table_trust_score"),
            trend_mode=str(state.get("trend_mode") or "").strip() or None,
            trend_scope_key=str(state.get("trend_scope_key") or "").strip() or None,
            trend_scope_label=str(state.get("trend_scope_label") or "").strip() or None,
            baseline_run_id=state.get("baseline_run_id"),
            summary_json=updated_summary,
        )
        _emit(
            settings,
            run_id,
            "DataEnrichmentOpportunityAgent",
            "completed",
            "Enrichment opportunities identified",
            {
                "opportunity_count": inserted,
                "external_lookup_opportunity_count": updated_summary.get("external_lookup_opportunity_count", 0),
            },
            event_callback=event_callback,
        )
        return state

    graph.add_node("router", router_node)
    graph.add_node("schema", schema_node)
    graph.add_node("stage_planner", stage_planner_node)
    graph.add_node("profiling", profiling_node)
    graph.add_node("duplicates", duplicate_node)
    graph.add_node("freshness", freshness_node)
    graph.add_node("rules", rules_node)
    graph.add_node("pause_review", pause_review_node)
    graph.add_node("enrichment", enrichment_node)
    graph.add_node("trust", trust_node)
    graph.add_node("dashboard", dashboard_node)
    graph.add_node("trends", trends_node)
    graph.add_node("anomalies", anomalies_node)
    graph.add_node("issues", issues_node)
    graph.add_node("finalize", finalize_node)
    graph.set_entry_point("router")
    graph.add_edge("router", "schema")
    graph.add_edge("schema", "stage_planner")
    graph.add_edge("stage_planner", "profiling")
    graph.add_edge("profiling", "duplicates")
    graph.add_edge("duplicates", "freshness")
    graph.add_edge("freshness", "rules")
    graph.add_conditional_edges(
        "rules",
        lambda state: "pause_review" if state.get("awaiting_rule_review") else "enrichment",
        {
            "pause_review": "pause_review",
            "enrichment": "enrichment",
        },
    )
    graph.add_edge("pause_review", END)
    graph.add_edge("enrichment", "trust")
    graph.add_edge("trust", "trends")
    graph.add_edge("trends", "anomalies")
    graph.add_edge("anomalies", "issues")
    graph.add_edge("issues", "dashboard")
    graph.add_edge("dashboard", "finalize")
    graph.add_edge("finalize", END)
    logger.info("data_quality.workflow.compiling | run_id=%s", run_id)
    app = graph.compile()
    result = app.invoke(initial_state)
    logger.info("data_quality.workflow.completed | run_id=%s", run_id)
    result.setdefault("run_status", "completed")
    return result
