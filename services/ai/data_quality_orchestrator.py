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
from services.ai.data_quality_duplicates import detect_duplicate_candidates
from services.ai.data_quality_freshness import analyze_freshness_and_stability
from services.ai.data_quality_enrichment import discover_enrichment_opportunities
from services.ai.data_quality_trust import compute_data_quality_trust_scores
from services.ai.data_quality_store import (
    create_or_update_quality_run,
    get_quality_run_by_run_id,
    get_previous_quality_run,
    list_quality_tables_by_quality_run,
    list_quality_duplicate_candidates,
    list_quality_rules,
    list_quality_tables,
    replace_quality_duplicate_candidates,
    replace_quality_enrichment_opportunities,
    replace_quality_rules,
    update_quality_table_monitoring,
    update_quality_table_trust_scores,
    upsert_quality_artifacts_from_profiling,
)
from services.ai.data_quality_rules import (
    classify_quality_rule_review_status,
    build_quality_rule_execution_plan,
    execute_quality_rules,
    extract_quality_rules_from_context,
)
from services.ai.db import ScopedConnection
from services.ai.connection_registry import resolve_database_credentials_cached
from services.ai.semantic_layer.pack_loader import load_pack


logger = logging.getLogger(__name__)


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
        limit=500,
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
        limit=500,
    )
    quality_tables = list_quality_tables(
        settings,
        tenant_id=tenant_id,
        domain_id=domain_id,
        run_id=run_id,
        limit=500,
    )
    freshness_results = _freshness_results_from_quality_tables(quality_tables)
    freshness_summary = _freshness_summary_from_results(freshness_results)
    updated_summary = _quality_summary(
        profiling,
        summary.get("persisted") or {"tables": len(quality_tables), "columns": 0},
        rule_summary,
        _duplicate_summary_from_candidates(duplicate_candidates),
        freshness_summary,
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
        limit=500,
    )
    updated_summary.update(trust.get("summary") or {})
    create_or_update_quality_run(
        settings,
        **scope,
        status="running",
        overall_trust_score=updated_summary.get("average_table_trust_score"),
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
    )
    if dashboard.get("dashboard_id"):
        updated_summary["dashboard_id"] = dashboard.get("dashboard_id")
        updated_summary["dashboard_title"] = dashboard.get("dashboard_title")
        updated_summary["dashboard_chart_count"] = len(dashboard.get("chart_plan") or [])
        updated_summary["remediation_action_count"] = dashboard.get("remediation_action_count", 0)
        updated_summary["critical_remediation_action_count"] = dashboard.get("critical_remediation_action_count", 0)
    create_or_update_quality_run(
        settings,
        **scope,
        status="completed",
        overall_trust_score=updated_summary.get("average_table_trust_score"),
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
        raise RuntimeError("LangGraph is not available")

    graph = StateGraph(dict)

    def router_node(state: dict[str, Any]) -> dict[str, Any]:
        scope = _scope(state, run_id)
        quality_run_id = create_or_update_quality_run(
            settings,
            **scope,
            status="running",
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

    def profiling_node(state: dict[str, Any]) -> dict[str, Any]:
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
        summary = _quality_summary(profiling, persisted)
        state["quality_summary"] = summary
        create_or_update_quality_run(
            settings,
            **scope,
            status="running",
            overall_trust_score=summary.get("average_table_trust_score"),
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

    def rules_node(state: dict[str, Any]) -> dict[str, Any]:
        _emit(settings, run_id, "DataQualityRuleAgent", "running", "Extracting and classifying data quality rules", event_callback=event_callback)
        scope = _scope(state, run_id)
        quality_run_id = state.get("quality_run_id")
        pause_for_rule_review = bool(state.get("pause_for_rule_review", True))
        resume_after_rule_review = bool(state.get("resume_after_rule_review"))
        rules = extract_quality_rules_from_context(
            state.get("context_text"),
            state.get("schema_graph") or {},
            settings=settings,
        )
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
        if pause_for_rule_review and not resume_after_rule_review and review_pending_count > 0:
            rule_summary["review_required"] = True
            rule_summary["review_pending_count"] = review_pending_count
            state["quality_rules"] = rules
            state["quality_rule_summary"] = rule_summary
            state["quality_rule_results"] = []
            state["quality_rule_rows"] = _merge_rule_rows(rules, [])
            state["awaiting_rule_review"] = True
            state["run_status"] = "awaiting_rule_review"
            updated_summary = _quality_summary(
                state.get("profiling_stats") or {},
                (state.get("quality_summary") or {}).get("persisted") or {"tables": 0, "columns": 0},
                rule_summary,
                state.get("duplicate_summary") or {},
                state.get("freshness_summary") or {},
            )
            updated_summary.update(
                {
                    "active_rule_count": rule_summary.get("active_rule_count", 0),
                    "needs_review_rule_count": rule_summary.get("needs_review_rule_count", 0),
                    "unsupported_rule_count": rule_summary.get("unsupported_rule_count", 0),
                    "rejected_rule_count": rule_summary.get("rejected_rule_count", 0),
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
        state["quality_summary"] = _quality_summary(
            state.get("profiling_stats") or {},
            (state.get("quality_summary") or {}).get("persisted") or {"tables": 0, "columns": 0},
            rule_summary,
            state.get("duplicate_summary") or {},
            state.get("freshness_summary") or {},
        )
        state["quality_summary"].update(
            {
                "active_rule_count": rule_summary.get("active_rule_count", 0),
                "needs_review_rule_count": rule_summary.get("needs_review_rule_count", 0),
                "unsupported_rule_count": rule_summary.get("unsupported_rule_count", 0),
                "rejected_rule_count": rule_summary.get("rejected_rule_count", 0),
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
            limit=500,
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
            limit=500,
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
            state["quality_summary"] = updated_summary
            create_or_update_quality_run(
                settings,
                **scope,
                status="running",
                overall_trust_score=updated_summary.get("average_table_trust_score"),
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

    def finalize_node(state: dict[str, Any]) -> dict[str, Any]:
        summary = state.get("quality_summary") or {}
        scope = _scope(state, run_id)
        create_or_update_quality_run(
            settings,
            **scope,
            status="completed",
            overall_trust_score=summary.get("average_table_trust_score"),
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
    graph.add_node("profiling", profiling_node)
    graph.add_node("duplicates", duplicate_node)
    graph.add_node("freshness", freshness_node)
    graph.add_node("rules", rules_node)
    graph.add_node("pause_review", pause_review_node)
    graph.add_node("enrichment", enrichment_node)
    graph.add_node("trust", trust_node)
    graph.add_node("dashboard", dashboard_node)
    graph.add_node("finalize", finalize_node)
    graph.set_entry_point("router")
    graph.add_edge("router", "schema")
    graph.add_edge("schema", "profiling")
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
    graph.add_edge("trust", "dashboard")
    graph.add_edge("dashboard", "finalize")
    graph.add_edge("finalize", END)
    logger.info("data_quality.workflow.compiling | run_id=%s", run_id)
    app = graph.compile()
    result = app.invoke(initial_state)
    logger.info("data_quality.workflow.completed | run_id=%s", run_id)
    result.setdefault("run_status", "completed")
    return result
