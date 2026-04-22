from __future__ import annotations

from typing import Callable, Iterator, List, Optional, TypeVar

import base64
import contextlib
import io
import json
import logging
import os
import time
import re
import threading
import traceback
import uuid
import zipfile
import xml.etree.ElementTree as ElementTree
import urllib.request
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Response, Query
from fastapi.middleware.cors import CORSMiddleware

from services.ai.catalog import Dimension, Metric, MetricCatalog, load_catalog_with_registry, resolve_ref
from datetime import date as _date, datetime as _datetime, timedelta as _timedelta
from services.ai.config import load_settings
from services.ai.db import execute_non_query, run_query
from services.ai.metrics_registry import (
    delete_metric,
    fetch_registry_metrics,
    upsert_metric,
    update_metric,
)
from services.ai.audit import log_query_audit
from services.ai.connection_registry import (
    register_connection,
    register_connection_scopes,
    resolve_connection_scope,
    resolve_database_credentials_cached,
)
from services.ai.crypto import decrypt_password
from services.ai.db import ScopedConnection
from services.ai.onboarding.scan_store import persist_schema_scan
from services.ai.onboarding.scan_store import load_latest_scan_result, load_latest_scan_for_scope
from services.ai.resolver import resolve_question
from services.ai.semantic_graph_resolver import resolve_question_semantic, log_semantic_usage
from services.ai.charts import build_chart_payload, infer_chart_type, infer_chart_type_with_llm, build_chart_inference
from services.ai.workspace_query_planner import (
    build_workspace_chart,
    compile_workspace_query_plan,
    conversation_plan_diagnostics,
    interpret_workspace_query,
    validate_workspace_query_plan,
    workspace_chart_title,
)
from services.ai.rollups import (
    create_rollup,
    list_rollups,
    get_rollup,
    build_rollup_table,
    find_matching_rollup,
    update_rollup_status,
)
from services.ai.views import list_views as list_registered_views, get_view_schema as load_view_schema
from services.ai.charts_store import (
    create_chart_request,
    create_chart_event,
    get_chart_request,
    get_latest_chart_request_by_question,
    update_chart_request,
    append_chart_conversation_id,
)
from services.ai.chart_interactions import (
    build_chart_interaction_context,
    build_chart_interaction_context_for_creation,
    build_chart_interaction_response,
    create_chart_interaction,
    execute_chart_compilation,
    ensure_chart_interaction_metadata,
)
from services.ai.hierarchy_store import list_business_hierarchies
from services.ai.dashboards_store import (
    create_dashboard as _ds_create_dashboard,
    list_dashboards as _ds_list_dashboards,
    get_dashboard as _ds_get_dashboard,
    get_dashboard_with_charts as _ds_get_with_charts,
    update_dashboard as _ds_update_dashboard,
    delete_dashboard as _ds_delete_dashboard,
    add_chart as _ds_add_chart,
    remove_chart as _ds_remove_chart,
    reorder_charts as _ds_reorder_charts,
)
from services.ai.schema_loader import load_manifest_models
from services.ai.dbt_manifest import (
    run_dbt_compile,
    store_manifest,
    load_latest_manifest_row,
    resolve_dbt_project_dir,
    upsert_tenant_project_dir,
    upsert_dbt_config,
    get_latest_dbt_config,
    resolve_dbt_config,
    ensure_tenant_dbt_project,
    create_temp_profiles_dir,
    normalize_profile_name,
)
from services.ai.dbt_scaffold import (
    build_scaffold_payload,
    write_scaffold_files,
    persist_scaffold,
    list_scaffolds,
    get_scaffold,
    update_scaffold,
)
from services.ai.semantic_layer.pack_loader import list_packs, load_pack
from services.ai.semantic_layer.pack_loader import list_pack_metadata
from services.ai.semantic_contracts import (
    get_active_semantic_contract,
    get_semantic_contract,
    list_pack_versions,
    register_pack_version,
    store_semantic_contract,
    update_contract_status,
    validate_semantic_payload,
)
from services.ai.context_extraction import extract_context
from services.ai.semantic_extraction import extract_semantic_contract
from services.ai.governance import build_lineage
from services.ai.insights import generate_variance_insight, get_insight, list_insights, persist_insight
from services.ai.actions import create_action, create_feedback, get_action, list_actions, update_action
from services.ai.scenarios import (
    compare_scenarios,
    create_scenario,
    get_scenario,
    list_scenarios,
    run_scenario,
    update_scenario,
)
from services.ai.anomalies import (
    build_timeseries,
    compute_correlations,
    compute_driver_breakdown,
    normalize_period,
    score_anomalies,
)
from services.api.overrides import load_overrides, load_overrides_all
from services.api.overrides_endpoints import upsert_entity_override, upsert_hierarchy_override
from services.ai.onboarding.schema_scan import scan_schema
from services.ai.onboarding.connection_scan import scan_connection
from services.ai.onboarding.measure_detection import detect_measures, detect_time_columns
from services.ai.onboarding.entity_mapping import map_entities
from services.ai.onboarding.entity_mappings_store import (
    get_entity_mapping,
    list_entity_mappings,
    persist_entity_mapping,
    update_entity_mapping_status,
)
from services.ai.onboarding.entity_mapping_agents import (
    attach_mapping_id_to_agents,
    list_entity_mapping_agents,
)
from services.ai.agentic_store import (
    create_agent_run,
    update_agent_run_status,
    append_agent_run_event,
    append_agent_run_stage_event,
    append_agent_chat_log,
    list_agent_run_events,
    list_agent_run_events_stage_aware,
    get_agent_run,
    list_agent_chat_log,
    get_agent_event_artifact,
    get_agent_event_artifact_by_logical_event_id,
    list_agent_event_artifacts_by_event_ids,
    append_plan_summary,
    upsert_agent_event_artifact,
)
from services.ai.agentic_orchestrator import run_agentic_workflow
from services.ai.agentic_artifacts_registry import (
    get_schema_graph_artifact,
    get_table_profile_artifact,
    list_join_registry,
    list_model_registry,
)
from services.ai.data_quality_enrichment import (
    build_staged_enrichment_overlay_artifact,
    build_enrichment_proposal,
    canonical_column_alias,
    canonical_column_aliases,
    select_enrichment_rows_for_application,
    summarize_enrichment_proposal,
)
from services.ai.data_quality_enrichment_questions import build_enrichment_question_queue
from services.ai.data_quality_api_payloads import (
    build_data_quality_run_hydration_payload,
    build_data_quality_run_summary_payload,
)
from services.ai.data_quality_orchestrator import resume_data_quality_agentic_workflow_after_rule_review
from services.ai.data_quality_evidence import (
    fetch_duplicate_evidence,
    fetch_enrichment_evidence,
    fetch_freshness_evidence,
    fetch_missingness_evidence,
    fetch_rule_evidence,
    load_quality_run,
)
from services.ai.data_quality_rule_review import (
    apply_quality_rule_review_action,
    get_quality_rule_for_review,
    get_quality_rule_review_queue,
)
from services.ai.data_quality_remediation import build_data_quality_remediation_plan
from services.ai.data_quality_store import (
    get_quality_rule,
    create_quality_enrichment_proposal,
    list_quality_duplicate_candidates,
    get_quality_enrichment_opportunity,
    get_quality_enrichment_proposal,
    get_latest_quality_enrichment_proposal_for_opportunity,
    list_quality_enrichment_opportunities,
    get_quality_run_by_run_id,
    get_quality_table_detail,
    list_quality_rules,
    list_quality_tables,
    update_quality_enrichment_opportunity_status,
    update_quality_enrichment_proposal,
)
from services.ai.data_quality_report import EXCEL_MIME_TYPE, build_data_quality_excel_report
from services.ai.data_quality_workspace import build_data_quality_workspace_response
from services.ai.langsmith_forwarder import LangSmithEventForwarder
from services.ai.ontology_mapper import llm_map_entities
from services.ai.onboarding.metrics_registry import persist_suggested_metrics
from services.ai.semantic_suggest import build_lineage_edges, build_schema_summary, suggest_semantic_model
from services.ai.onboarding.models_registry import (
    delete_dimension,
    delete_fact,
    list_dimensions,
    list_dimensions_all,
    list_dimensions_by_run,
    list_facts,
    list_facts_all,
    list_facts_by_run,
    update_dimension,
    update_fact,
    upsert_dimension,
    upsert_fact,
)
from services.ai.onboarding.review_store import (
    create_review_event,
    list_review_events,
    update_review_event,
)
from services.ai.context_store import (
    create_context,
    create_context_file,
    get_context,
    get_context_file,
    get_context_file_bytes,
    get_extraction,
    list_extractions,
    list_context_files_for_contexts,
    list_applied_context_artifacts,
    list_context,
    list_active_context_ids,
    link_context_files,
    mark_context_processed,
    persist_extraction,
    persist_extraction_agent,
    get_context_file_texts,
    set_context_active,
    update_context,
    update_context_file_metadata,
    update_enriched_context,
    update_extraction,
)
from services.ai.context_enrichment import enrich_context_text
from services.ai.context_extraction import extract_context
from services.ai.context_merge import merge_extractions
from services.ai.context_apply import apply_extractions
from services.ai.glossary import fetch_glossary_terms
from services.ai.sql_builder import Filter, build_query
from services.ai.tenant_domain import get_tenant_domain, upsert_tenant_domain
from services.ai.tenant_registry import delete_tenant, list_tenants, upsert_tenant, update_tenant
from services.ai.tenant_scope import get_tenant_scope, upsert_tenant_scope
from services.ai.tenant_purge import purge_tenant_data
from services.ai.policy_audit import log_policy_audit
from services.ai.jobs_store import (
    claim_next_job,
    create_job,
    get_job,
    get_job_result as fetch_job_result,
    list_jobs as fetch_jobs,
    update_job_progress,
    update_job_status,
)
from services.ai.chat_store import create_chat_request, get_chat_request, update_chat_request
from services.ai.chat_events_store import create_chat_event, list_chat_events
from services.ai.semantic_feedback_store import (
    create_semantic_feedback,
    list_semantic_feedback,
    apply_semantic_feedback,
)
from services.ai.domain_refinement_extractor import (
    validate_refinement_input_payload,
    process_refinement_input,
    extract_refinement_artifacts_with_llm,
)
from services.ai.domain_refinement_store import (
    activate_semantic_state,
    create_refinement_input,
    get_refinement_artifact,
    get_current_semantic_state,
    get_refinement_input,
    get_semantic_state,
    list_refinement_artifacts,
    list_refinement_inputs,
    list_semantic_states,
    update_refinement_artifact_approval,
)
from services.ai.domain_semantic_state_builder import rebuild_semantic_state
from services.ai.semantic_propagation_store import (
    create_semantic_propagation_job,
    enqueue_semantic_propagation_for_artifacts,
    list_semantic_propagation_jobs,
)
from services.ai.semantic_propagation_runner import run_semantic_propagation_job
from services.ai.semantic_runtime import (
    apply_join_constraints_to_edges,
    load_active_semantic_state,
    merge_semantic_glossary,
    semantic_interpretation_context,
    semantic_join_constraints,
)
from services.ai.semantic_conversation_refinement import (
    infer_refinement_kind,
    maybe_writeback_conversation_refinement,
)
from services.ai.semantic_impact_preview import build_semantic_impact_preview
from services.ai.semantic_audit import build_semantic_audit
from services.ai.semantic_conflicts import detect_semantic_conflicts
from services.ai.semantic_graph_store import list_dashboard_specs, get_dashboard_spec, update_dashboard_spec  # noqa: F401 — delegating shims kept for call sites below during Phase 44 cutover
from services.ai.dashboard_refresh_store import (
    create_dashboard_refresh_run,
    update_dashboard_refresh_status,
    get_dashboard_refresh_run,
    append_dashboard_refresh_event,
    list_dashboard_refresh_events,
    get_dashboard_insights,
    upsert_dashboard_insights_artifact,
    create_dashboard_chart_snapshot,
)
from services.ai.dashboard_insights import (
    chart_stats as dashboard_chart_stats,
    chart_insight as dashboard_chart_insight,
    build_dashboard_evidence,
    deterministic_dashboard_summary,
    deterministic_dashboard_inference,
    llm_rewrite_text,
    render_summary_html,
    render_inference_html,
)
from services.ai.anomaly_store import (
    get_anomaly_dashboard_link,
    get_anomaly_investigation,
    list_anomaly_actions,
    list_anomaly_dashboard_links,
    list_anomaly_hypotheses,
    list_anomaly_investigations,
    list_anomaly_records,
)
from services.ai.workspace_store import (
    STATUS_ACTIVE as WORKSPACE_STATUS_ACTIVE,
    STATUS_ARCHIVED as WORKSPACE_STATUS_ARCHIVED,
    STATUS_DELETED as WORKSPACE_STATUS_DELETED,
    create_workspace_conversation,
    create_workspace_message,
    finalize_canonical_deployment,
    generate_conversation_title,
    generate_run_display_name,
    get_current_deployment,
    get_workspace_conversation,
    get_workspace_memory,
    get_workspace_message,
    initialize_run_metadata,
    list_deployments,
    list_workspace_conversations,
    list_workspace_conversations_for_tenant,
    list_workspace_messages,
    mark_run_status,
    next_run_version,
    recent_workspace_messages,
    soft_delete_workspace_conversation,
    update_deployment,
    update_workspace_conversation,
    upsert_workspace_memory,
    list_conversations_by_chart,
)
from services.ai.correlation_store import (
    create_correlation_run,
    get_correlation_run,
    list_correlation_runs,
    get_anomaly_results,
    get_correlation_pairs,
    get_investigation_threads,
    get_forward_projections,
    save_correlation_run_results,
)
from services.ai.correlation_agent import run_correlation_intelligence
from services.ai.correlation_charts import generate_correlation_charts
from services.ai.correlation_narrate import narrate_correlation_results
from services.ai.user_dashboards_store import (  # noqa: F401 — delegating shims; kept during Phase 44 cutover
    create_user_dashboard,
    get_user_dashboard,
    list_user_dashboards,
    update_user_dashboard,
    delete_user_dashboard,
    add_chart_to_dashboard,
    remove_chart_from_dashboard,
    reorder_dashboard_charts,
    get_dashboard_with_charts,
)
from services.ai.view_query_store import (
    create_view_query_run,
    finalize_view_query,
    get_view_query_run,
    list_view_query_runs,
    mark_view_query_running,
    update_view_query_chart,
    update_view_query_inference,
)
from services.api.schemas import (
    EntitiesResponse,
    EntitiesAllResponse,
    EntityOverrideRequest,
    HierarchyOverrideRequest,
    HierarchyUpdateRequest,
    MetricsResponse,
    MetricPatchRequest,
    MetricUpsertRequest,
    MetricUpsertResponse,
    DatasetsResponse,
    DimensionsResponse,
    TenantCreateRequest,
    TenantUpdateRequest,
    TenantResponse,
    TenantsResponse,
    DimensionValuesResponse,
    OnboardScanRequest,
    OnboardScanResponse,
    OnboardMapResponse,
    OnboardMapApplyRequest,
    OnboardMapApplyResponse,
    OnboardMapRunResponse,
    FactsResponse,
    FactsAllResponse,
    FactsUpsertRequest,
    FactsPatchRequest,
    DimensionsUpsertRequest,
    DimensionsPatchRequest,
    DimensionsAllResponse,
    ReviewCreateRequest,
    ReviewPatchRequest,
    ReviewResponse,
    ReviewListResponse,
    ReviewSummaryResponse,
    ContextIngestRequest,
    ContextIngestResponse,
    ContextFileIngestResponse,
    ContextListResponse,
    ContextExtractRequest,
    ContextExtractResponse,
    ContextExtractionResponse,
    ContextExtractionListResponse,
    ContextApplyRequest,
    ContextApplyResponse,
    ContextPatchRequest,
    ContextFilePatchRequest,
    ContextExtractionPatchRequest,
    OnboardScanConnectionResponse,
    OnboardScanMultiConnectionRequest,
    InferModelsRequest,
    InferModelsResponse,
    QueryRequest,
    QueryResult,
    ChatRequest,
    ChatResponse,
    SchemaResponse,
    SuggestedMetricsResponse,
    ContractValidateRequest,
    ContractValidateResponse,
    DbtManifestGenerateRequest,
    DbtManifestGenerateResponse,
    DbtManifestLatestResponse,
    DbtConfigUpsertRequest,
    DbtConfigResponse,
    DbtScaffoldRequest,
    DbtScaffoldResponse,
    DbtScaffoldListResponse,
    DbtScaffoldPatchRequest,
    PoliciesResponse,
    LineageResponse,
    InsightsResponse,
    InsightDetailResponse,
    ActionCreateRequest,
    ActionUpdateRequest,
    ActionFeedbackRequest,
    ActionsResponse,
    ActionDetailResponse,
    ActionCreateResponse,
    ChartRequest,
    ChartFilterRequest,
    ChartNavigationRequest,
    ChartStatusResponse,
    RollupCreateRequest,
    RollupResponse,
    RollupRefreshResponse,
    SemanticFeedbackRequest,
    SemanticFeedbackResponse,
    SemanticRefinementCreateRequest,
    SemanticRefinementResponse,
    SemanticRefinementListResponse,
    SemanticRefinementProcessResponse,
    SemanticRefinementArtifactResponse,
    SemanticIntakeRequest,
    SemanticIntakeResponse,
    SemanticIntakeArtifactSummary,
    SemanticIntakePropagationSummary,
    SemanticImpactPreviewRequest,
    SemanticImpactPreviewResponse,
    SemanticAuditResponse,
    SemanticConflictResponse,
    SemanticStateActivateRequest,
    SemanticRefinementApprovalRequest,
    SemanticStateRebuildRequest,
    SemanticStateResponse,
    SemanticPropagationRequest,
    SemanticPropagationJobResponse,
    SemanticPropagationListResponse,
    ContextQuestionsResponse,
    ViewListResponse,
    ViewSchemaResponse,
    ViewQueryRequest,
    ViewQueryResponse,
    ViewQueryHistoryResponse,
    ViewQueryStatusResponse,
    DashboardListResponse,
    DashboardResponse,
    DashboardUpdateRequest,
    ScenariosResponse,
    ScenarioCreateRequest,
    ScenarioUpdateRequest,
    ScenarioRunRequest,
    ScenarioCompareRequest,
    ScenarioRunResponse,
    ScenarioCompareResponse,
    TimeSeriesRequest,
    TimeSeriesResponse,
    InsightDetailWithContextResponse,
    JobCancelResponse,
    JobCreateRequest,
    JobCreateResponse,
    JobListResponse,
    JobResultResponse,
    JobStatusResponse,
    PackApplyRequest,
    PackApplyResponse,
    PackListResponse,
    SemanticContractResponse,
    SemanticContractListResponse,
    SemanticContractValidateResponse,
    SemanticExtractRequest,
    SemanticExtractResponse,
    SemanticApplyRequest,
    SemanticApplyResponse,
    SemanticSuggestRequest,
    SemanticSuggestResponse,
    SemanticSuggestApplyRequest,
    SemanticSuggestApplyResponse,
    TenantScopeUpsertRequest,
    TenantScopeResponse,
    CanvasSaveRequest,
    CanvasSaveResponse,
    CanvasListResponse,
    CanvasDetailResponse,
    CanvasTreeResponse,
    CreateConversationRequest,
    CreateDashboardRequest,
    UpdateDashboardRequest,
    AddChartToDashboardRequest,
    ReorderDashboardChartsRequest,
    CorrelationRunRequest,
    CorrelationRunResponse,
    CorrelationRunListResponse,
    CorrelationAnomalyListResponse,
    CorrelationPairListResponse,
    CorrelationThreadListResponse,
    CorrelationProjectionListResponse,
)
from services.api.validators import (
    generate_source_title,
)


load_dotenv()

_log_level = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=getattr(logging, _log_level, logging.INFO))
logger = logging.getLogger("quantyx.api")
PHASE52_BUILD_VERSION = "2026-04-04-phase52-v1"

# Bump this manually after each significant edit to confirm the latest code is running.
BUILD_VERSION = "2026.03.29.007"

app = FastAPI(
    title="quantyx-core-services API",
    version="0.1.0",
    openapi_tags=[
        {"name": "certify", "description": "Certification endpoints for glossary, entities, hierarchies, facts, dimensions, and metrics."},
        {"name": "rollups", "description": "Rollup registry and refresh endpoints."},
        {"name": "chat", "description": "Chat-style query endpoints."},
        {"name": "governance", "description": "Semantic feedback and governance endpoints."},
        {"name": "views", "description": "View explorer and SQL editor endpoints."},
        {"name": "dashboards", "description": "Dashboard listing and retrieval endpoints."},
        {"name": "workspace", "description": "Deployment-scoped conversational workspace APIs."},
    ],
)

settings = load_settings()
_cors_allow_origins = [
    origin.strip()
    for origin in str(settings.cors_allow_origins or "").split(",")
    if origin.strip()
]
_cors_allow_origin_regex = (
    str(settings.cors_allow_origin_regex).strip()
    if settings.cors_allow_origin_regex
    else r"https?://(localhost|127\.0\.0\.1)(:\d+)?$"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_allow_origins,
    allow_origin_regex=_cors_allow_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

catalog = load_catalog_with_registry(settings, settings.metrics_catalog_path)
_CHART_FOLLOWUP_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "ai" / "prompts" / "chart_followup"
LOW_CONFIDENCE_THRESHOLD = 0.7
JOB_TYPES = {
    "scan_connection",
    "map_entities",
    "infer_models",
    "metrics_suggested",
    "context_extract",
    "context_apply",
    "agentic_run",
    "rollup_build",
    "rollup_refresh",
    "chat_build",
}


@contextlib.contextmanager
def _langsmith_project_env(tenant_id: str | None):
    tenant = str(tenant_id or "").strip()
    prefix = str(os.getenv("LANGCHAIN_PROJECT_PREFIX") or os.getenv("LANGSMITH_PROJECT_PREFIX") or "").strip()
    project = (f"{prefix}{tenant}" if tenant and prefix else tenant) or None
    old_langchain_project = os.environ.get("LANGCHAIN_PROJECT")
    old_langsmith_project = os.environ.get("LANGSMITH_PROJECT")
    try:
        if project:
            os.environ["LANGCHAIN_PROJECT"] = project
            os.environ["LANGSMITH_PROJECT"] = project
            logger.info("langsmith.project.selected | tenant=%s project=%s", tenant, project)
        yield project
    finally:
        if old_langchain_project is None:
            os.environ.pop("LANGCHAIN_PROJECT", None)
        else:
            os.environ["LANGCHAIN_PROJECT"] = old_langchain_project
        if old_langsmith_project is None:
            os.environ.pop("LANGSMITH_PROJECT", None)
        else:
            os.environ["LANGSMITH_PROJECT"] = old_langsmith_project


@contextlib.contextmanager
def _langsmith_project_context(tenant_id: str | None):
    with _langsmith_project_env(tenant_id) as project:
        if not project:
            yield project
            return
        tracing_cm = None
        try:
            from langsmith.run_helpers import tracing_context  # type: ignore

            _extra_tags = [f"build:{BUILD_VERSION}"]
            env_tags = [t.strip() for t in os.getenv("LANGCHAIN_TAGS", "").split(",") if t.strip()]
            tracing_cm = tracing_context(
                project_name=project,
                tags=env_tags + _extra_tags,
                metadata={"build_version": BUILD_VERSION},
            )
        except Exception:
            tracing_cm = None
        if tracing_cm is None:
            yield project
            return
        with tracing_cm:
            yield project
_job_worker_stop = threading.Event()
_job_worker_thread: threading.Thread | None = None
_REF_PATTERN = re.compile(r"\{\{\s*ref\('(?P<name>[^']+)'\)\s*\}\}")


def _resolve_scope_values(
    tenant_id: str,
    domain_id: str,
) -> tuple[str, str, str, list[str] | None]:
    registry = get_tenant_scope(settings, tenant_id, domain_id)
    connection_id = (registry or {}).get("connection_id")
    if not connection_id:
        raise HTTPException(status_code=400, detail="tenant scope not configured")

    # Prefer database_name/schema_name stored on the tenant scope itself — these are
    # the exact values written to facts/dimensions/metrics during the agentic run.
    # Fall back to the connection's registered scope only if the tenant scope lacks them.
    database_name = (registry or {}).get("database_name")
    schema_name = (registry or {}).get("schema_name")
    if not database_name or not schema_name:
        scopes = resolve_connection_scope(settings, connection_id)
        if not scopes:
            raise HTTPException(status_code=404, detail="tenant scope connection not registered")
        database_name = database_name or scopes[0].get("database_name")
        schema_name = schema_name or scopes[0].get("schema_name")
    if not database_name or not schema_name:
        raise HTTPException(status_code=400, detail="tenant scope not configured")
    return (connection_id, database_name, schema_name, registry.get("tables") if registry else None)


def _resolve_scoped_conn(tenant_id: str, domain_id: str) -> ScopedConnection | None:
    """Resolve full connection credentials for a tenant/domain scope.

    Two-tier resolution:
    1. Full credentials from public.databases (supports different server/user)
    2. Same-server fallback: App DB host/port/user + database_name from scope
       (covers the common case where customer DB is on the same PostgreSQL server)

    Never raises; safe to call speculatively.
    """
    try:
        registry = get_tenant_scope(settings, tenant_id, domain_id)
        connection_id = (registry or {}).get("connection_id")
        if not connection_id:
            logger.warning("_resolve_scoped_conn: no connection_id for tenant=%s domain=%s", tenant_id, domain_id)
            return None
        # Get schema/database from quantyx_connection_scopes (populated after schema scan).
        # Fall back to quantyx_tenant_scopes fields — these are available from the very first
        # deployment call, before the schema scan agent has run register_connection_scopes.
        scopes = resolve_connection_scope(settings, connection_id)
        if scopes:
            schema_name = scopes[0].get("schema_name") or "public"
            database_name = scopes[0].get("database_name") or ""
        else:
            logger.info(
                "_resolve_scoped_conn: no connection_scopes for connection_id=%s — "
                "using tenant_scope fields (schema_name=%s database_name=%s)",
                connection_id,
                (registry or {}).get("schema_name"),
                (registry or {}).get("database_name"),
            )
            schema_name = str((registry or {}).get("schema_name") or "public")
            database_name = str((registry or {}).get("database_name") or "")

        # Tier 1: full credentials from public.databases
        cred = resolve_database_credentials_cached(settings, connection_id, schema_name)
        if cred:
            logger.info("_resolve_scoped_conn: tier-1 resolved conn=%r", cred)
            return cred

        # Tier 2: same server as App DB, just a different database name
        if database_name:
            sc = ScopedConnection(
                connection_id=connection_id,
                host=settings.db_host,
                port=int(settings.db_port or 5432),
                user=settings.db_user,
                password=settings.db_password,
                database_name=database_name,
                schema_name=schema_name,
            )
            logger.info("_resolve_scoped_conn: tier-2 fallback conn=%r", sc)
            return sc
        logger.warning("_resolve_scoped_conn: no database_name in scope for connection_id=%s", connection_id)
        return None
    except Exception:
        logger.exception("_resolve_scoped_conn: unexpected error for tenant=%s domain=%s", tenant_id, domain_id)
        return None


def _load_job_payload(payload: dict | str | None) -> dict:
    if payload is None:
        return {}
    if isinstance(payload, str):
        return json.loads(payload)
    return payload


def _build_semantic_validation(metrics: list, contract: dict | None) -> dict | None:
    if not contract:
        return None
    payload = contract.get("payload") or {}
    definitions = []
    definition_map = {}
    for item in payload.get("metric_definitions", []) or []:
        name = item.get("metric_name")
        if name:
            definition_map[name] = item.get("definition")
    for metric in metrics:
        if metric.name in definition_map:
            definitions.append(metric.name)
    assumptions = []
    grains = {metric.grain for metric in metrics if metric.grain}
    if grains:
        assumptions.append(f"default grain={sorted(grains)[0]}")
    return {"definitions": definitions, "assumptions": assumptions, "policy_applied": []}


def _build_lineage(metrics: list) -> dict | None:
    models = set()
    tables = set()
    for metric in metrics:
        for match in _REF_PATTERN.finditer(metric.sql or ""):
            model = match.group("name")
            models.add(model)
            tables.add(f"{settings.db_schema}.{model}")
    if not models and not tables:
        return None
    return {"models": sorted(models), "tables": sorted(tables)}


def _extract_metric_sources(metric: dict) -> set[str]:
    sources: set[str] = set()
    sql = metric.get("sql") or ""
    for match in _REF_PATTERN.finditer(sql):
        sources.add(match.group("name"))
    for key in ("dataset_id", "source_model"):
        if metric.get(key):
            sources.add(metric[key])
    return sources


def _build_canvas_lineage(
    facts: list[dict],
    dimensions: list[dict],
    metrics: list[dict],
) -> dict:
    nodes = []
    edges = []

    dimension_keys: dict[str, set[str]] = {}
    for dim in dimensions:
        dim_name = dim.get("name")
        if not dim_name:
            continue
        keys = set((dim.get("keys") or []) + (dim.get("attributes") or []))
        dimension_keys[dim_name] = keys
        nodes.append({"id": dim_name, "type": "dimension"})

    for fact in facts:
        fact_name = fact.get("table_name")
        if not fact_name:
            continue
        nodes.append({"id": fact_name, "type": "fact"})
        fact_dims = set(fact.get("dimensions") or [])
        for dim_name, keys in dimension_keys.items():
            if fact_dims & keys:
                edges.append({"from": dim_name, "to": fact_name, "edge_type": "dimension_to_fact"})

    for metric in metrics:
        metric_name = metric.get("metric_name")
        if not metric_name:
            continue
        nodes.append({"id": metric_name, "type": "metric"})
        for source in _extract_metric_sources(metric):
            edges.append({"from": source, "to": metric_name, "edge_type": "fact_to_metric"})

    return {"nodes": nodes, "edges": edges}


def _normalize_grain(grain: str | None) -> str | None:
    if not grain:
        return None
    return grain.strip().lower()


def _validate_fact_payload(payload: dict) -> None:
    measures = payload.get("measures") or []
    if not isinstance(measures, list) or not measures:
        raise HTTPException(status_code=400, detail="Fact must include at least one measure")


def _validate_dimension_payload(payload: dict) -> None:
    keys = payload.get("keys") or []
    if not isinstance(keys, list) or not keys:
        raise HTTPException(status_code=400, detail="Dimension must include at least one key")


def _fact_grain_map(
    tenant_id: str,
    domain_id: str,
    connection_id: str,
    database_name: str,
    schema_name: str,
) -> dict[str, str | None]:
    rows = list_facts(settings, tenant_id, domain_id, connection_id, database_name, schema_name)
    return {row.get("table_name"): row.get("grain") for row in rows if row.get("table_name")}


def _validate_metric_payload(
    payload: dict,
    fact_grains: dict[str, str | None],
) -> None:
    metric_type = str(payload.get("type") or "").strip().lower()
    if not metric_type:
        raise HTTPException(status_code=400, detail="Metric type is required")
    if metric_type not in ALLOWED_METRIC_TYPES:
        raise HTTPException(status_code=400, detail=f"Unsupported metric type: {payload.get('type')}")

    sql = payload.get("sql")
    if not sql or not isinstance(sql, str):
        raise HTTPException(status_code=400, detail="Metric sql is required")

    grain = _normalize_grain(payload.get("grain"))
    if not grain:
        raise HTTPException(status_code=400, detail="Metric grain is required")

    refs = [match.group("name") for match in _REF_PATTERN.finditer(sql)]
    fact_refs = [ref for ref in refs if ref.startswith("fact_")]
    if not fact_refs:
        raise HTTPException(status_code=400, detail="Metric sql must reference a fact model via ref('fact_*')")

    if metric_type == "ratio" and "/" not in sql:
        raise HTTPException(status_code=400, detail="Ratio metrics must include numerator/denominator expression")

    metric_rank = GRAIN_ORDER.get(grain)
    for fact_ref in fact_refs:
        fact_grain = _normalize_grain(fact_grains.get(fact_ref))
        if not fact_grain:
            continue
        fact_rank = GRAIN_ORDER.get(fact_grain)
        if metric_rank is not None and fact_rank is not None and metric_rank < fact_rank:
            raise HTTPException(
                status_code=400,
                detail=f"Metric grain '{grain}' cannot be finer than fact grain '{fact_grain}' for {fact_ref}",
            )


def _get_canvas_nodes_and_edges(tenant_id: str, domain_id: str) -> tuple[list[dict], list[dict]]:
    nodes_rows = run_query(
        settings,
        """
        SELECT n.node_id AS id, n.node_type AS type
          FROM public.quantyx_canvas_nodes n
          JOIN public.quantyx_canvases c ON c.canvas_id = n.canvas_id
         WHERE c.tenant_id = %s AND c.domain_id = %s
        """,
        [tenant_id, domain_id],
    )
    edges_rows = run_query(
        settings,
        """
        SELECT e.from_id AS "from", e.to_id AS "to", e.edge_type, e.source, e.confidence, e.from_type, e.to_type
          FROM public.quantyx_canvas_edges e
          JOIN public.quantyx_canvases c ON c.canvas_id = e.canvas_id
         WHERE c.tenant_id = %s AND c.domain_id = %s
        """,
        [tenant_id, domain_id],
    )

    seen_nodes: set[tuple[str, str]] = set()
    nodes: list[dict] = []
    for row in nodes_rows:
        node_id = row.get("id")
        node_type = row.get("type")
        if not node_id or not node_type:
            continue
        key = (node_id, node_type)
        if key in seen_nodes:
            continue
        seen_nodes.add(key)
        nodes.append({"id": node_id, "type": node_type})

    seen_edges: set[tuple[str, str, str]] = set()
    edges: list[dict] = []
    for row in edges_rows:
        from_id = row.get("from")
        to_id = row.get("to")
        edge_type = row.get("edge_type")
        if not from_id or not to_id or not edge_type:
            continue
        key = (from_id, to_id, edge_type)
        if key in seen_edges:
            continue
        seen_edges.add(key)
        edges.append(
            {
                "from": from_id,
                "to": to_id,
                "edge_type": edge_type,
                "source": row.get("source"),
                "confidence": row.get("confidence"),
                "from_type": row.get("from_type"),
                "to_type": row.get("to_type"),
            }
        )

    return nodes, edges


def _ensure_canvas_owned(canvas_id: str, tenant_id: str, domain_id: str) -> None:
    rows = run_query(
        settings,
        "SELECT tenant_id, domain_id FROM public.quantyx_canvases WHERE canvas_id = %s LIMIT 1",
        [canvas_id],
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Canvas not found")
    row = rows[0]
    if row.get("tenant_id") != tenant_id or row.get("domain_id") != domain_id:
        raise HTTPException(status_code=404, detail="Canvas not found")


def _load_context_text(context_id: str) -> tuple[dict, str, list[str]]:
    context_row = get_context(settings, context_id)
    if not context_row:
        raise HTTPException(status_code=404, detail="Context not found")
    file_texts = get_context_file_texts(settings, context_id)
    effective_text = context_row.get("enriched_context") or context_row.get("raw_text")
    combined_parts = [effective_text] if effective_text else []
    combined_parts.extend(file_texts)
    combined_text = "\n\n".join([part for part in combined_parts if part])
    return context_row, combined_text, file_texts


def _merge_context_inputs(
    tenant_id: str,
    domain_id: str,
    context_text: str | None,
    context_ids: list[str] | None,
) -> tuple[str | None, list[str]]:
    merged_parts: list[str] = []
    resolved_ids: list[str] = []
    seen_ids: set[str] = set()
    for raw_id in context_ids or []:
        context_id = str(raw_id or "").strip()
        if not context_id or context_id in seen_ids:
            continue
        seen_ids.add(context_id)
        context_row, combined_text, _ = _load_context_text(context_id)
        if context_row.get("tenant_id") != tenant_id or context_row.get("domain_id") != domain_id:
            raise HTTPException(status_code=400, detail=f"Context {context_id} tenant/domain mismatch")
        resolved_ids.append(context_id)
        if combined_text:
            merged_parts.append(combined_text)
    inline_text = str(context_text or "").strip()
    if inline_text:
        merged_parts.append(inline_text)
    merged_text = "\n\n".join([part for part in merged_parts if part]).strip() or None
    return merged_text, resolved_ids


def _execute_chart_job(payload: dict) -> dict:
    chart_id = payload.get("chart_id")
    if not chart_id:
        raise ValueError("chart_id is required for chart_build job")
    update_chart_request(settings, chart_id, status="running")
    create_chart_event(settings, chart_id, "running")

    timing: dict[str, float] = {}
    start_time = time.perf_counter()
    last_step = start_time

    def _mark(step: str) -> None:
        nonlocal last_step
        now = time.perf_counter()
        timing[f"{step}_ms"] = (now - last_step) * 1000
        last_step = now

    try:
        chart_row = get_chart_request(settings, chart_id)
        if not chart_row:
            raise ValueError("Chart request not found")
        rows = chart_row.get("rows_json") or []
        if not isinstance(rows, list):
            raise ValueError("Chart rows_json must be a list")
        query_payload = chart_row.get("query_payload") or {}
        metric_names = query_payload.get("metrics") or []
        dimensions = query_payload.get("dimensions") or []
        _mark("load_rows")

        chart_type = infer_chart_type(dimensions, rows, metric_names)
        if not chart_type:
            chart_type = infer_chart_type_with_llm(
                query_payload.get("question"),
                metric_names,
                dimensions,
                rows,
                settings,
            )
        _mark("chart_infer")

        chart_payload = None
        chart_data = None
        metric_name = metric_names[0] if metric_names else ""
        dim_key = dimensions[0] if dimensions else None
        if chart_type and metric_name:
            chart = build_chart_payload(chart_type, rows, metric_name, dimensions)
            chart_payload = chart.get("chart_payload")
            chart_data = chart.get("data")
        interaction_context = build_chart_interaction_context_for_creation(
            settings,
            chart_row={
                **chart_row,
                "query_payload": query_payload,
                "rows_json": rows,
                "chart_type": chart_type,
            },
            tenant_id=str(chart_row.get("tenant_id") or ""),
            domain_id=str(chart_row.get("domain_id") or "").strip() or None,
        )
        inference = build_chart_inference(
            settings,
            chart_type=chart_type or "bar",
            rows=rows,
            metric_name=metric_name,
            dim_key=dim_key,
            chart_title=chart_row.get("title") or query_payload.get("question"),
        )
        update_chart_request(
            settings,
            chart_id,
            status="ready",
            sql=chart_row.get("sql"),
            params=chart_row.get("params"),
            rows_json=rows,
            chart_type=chart_type,
            chart_payload=chart_payload,
            chart_data=chart_data,
            timing_ms=timing,
            insight_text=inference["insight_text"],
            narrative_text=inference["narrative_text"],
            stats_json=inference["stats_json"],
            interaction_context_json=interaction_context,
            root_chart_id=chart_row.get("root_chart_id") or chart_id,
        )
        create_chart_event(
            settings,
            chart_id,
            "ready",
            details={"chart_type": chart_type},
        )
        return {"chart_id": chart_id, "status": "ready"}
    except Exception as exc:  # noqa: BLE001
        update_chart_request(
            settings,
            chart_id,
            status="failed",
            error_message=str(exc),
            timing_ms=timing,
        )
        create_chart_event(
            settings,
            chart_id,
            "failed",
            details={"error_message": str(exc)},
        )
        raise


def _execute_job(job: dict) -> dict:
    job_type = job.get("job_type")
    payload = _load_job_payload(job.get("request_payload"))
    if job_type == "scan_connection":
        generate_dbt = payload.pop("generate_dbt", True)
        request = OnboardScanMultiConnectionRequest(**payload)
        response = _run_scan_connection(
            request,
            generate_dbt,
            progress_cb=lambda pct, stage: update_job_progress(settings, job.get("job_id"), pct, stage),
        )
        return response.model_dump()
    if job_type == "map_entities":
        use_llm = payload.pop("use_llm", True)
        request = OnboardScanRequest(**payload)
        response = _run_onboard_map(request, use_llm=use_llm, job_id=job.get("job_id"))
        return response.model_dump()
    if job_type == "infer_models":
        request = InferModelsRequest(**payload)
        response = infer_models(request)
        return response.model_dump()
    if job_type == "metrics_suggested":
        persist = payload.pop("persist", True)
        request = OnboardScanRequest(**payload)
        response = _suggested_metrics_impl(
            request,
            persist=persist,
            progress_cb=lambda pct, stage: update_job_progress(settings, job.get("job_id"), pct, stage),
        )
        return response.model_dump()
    if job_type == "context_extract":
        request = ContextExtractRequest(**payload)
        if (request.mode or "").lower() == "parallel":
            domain_id = _resolve_domain_id(request.tenant_id, request.domain_id)
            context_row, combined_text, _ = _load_context_text(request.context_id)
            if context_row["tenant_id"] != request.tenant_id or context_row["domain_id"] != domain_id:
                raise HTTPException(status_code=400, detail="Context tenant/domain mismatch")

            requested = set(request.extraction_types or [])
            agent_map = {
                "context_glossary": ["abbreviations", "synonyms"],
                "context_hierarchies": ["hierarchies"],
                "context_metrics": ["metric_candidates"],
                "context_questions": ["question_intents"],
            }
            agent_payloads: list[dict] = []
            for agent_name, types in agent_map.items():
                if requested and not requested.intersection(types):
                    continue
                extracted = extract_context(
                    settings,
                    raw_text=combined_text,
                    extraction_types=types,
                )
                agent_payloads.append(
                    {
                        "agent_name": agent_name,
                        "payload": extracted,
                    }
                )
            merged = merge_extractions(agent_payloads)
            extraction_id = persist_extraction(
                settings,
                context_id=request.context_id,
                tenant_id=request.tenant_id,
                domain_id=domain_id,
                payload=merged,
                llm_model=settings.openai_model,
                agent_name="context_extract_merged",
                parent_job_id=job.get("job_id"),
            )
            for agent in agent_payloads:
                persist_extraction_agent(
                    settings,
                    extraction_id=extraction_id,
                    agent_name=agent.get("agent_name") or "unknown",
                    payload=agent.get("payload") or {},
                )
            mark_context_processed(settings, request.context_id)
            return ContextExtractResponse(
                extraction_id=extraction_id,
                context_id=request.context_id,
                extractions=merged,
            ).model_dump()

        response = extract_context_payload(request)
        return response.model_dump()
    if job_type in {"context_glossary", "context_hierarchies", "context_metrics", "context_questions"}:
        request = ContextExtractRequest(**payload)
        extraction_type = {
            "context_glossary": ["abbreviations", "synonyms"],
            "context_hierarchies": ["hierarchies"],
            "context_metrics": ["metric_candidates"],
            "context_questions": ["question_intents"],
        }[job_type]
        response = extract_context_payload(
            ContextExtractRequest(
                tenant_id=request.tenant_id,
                domain_id=request.domain_id,
                context_id=request.context_id,
                extraction_types=extraction_type,
                model=request.model,
            )
        )
        return response.model_dump()
    if job_type == "context_apply":
        request = ContextApplyRequest(**payload)
        domain_id = _resolve_domain_id(request.tenant_id, request.domain_id)
        extraction_row = get_extraction(settings, request.extraction_id)
        if not extraction_row:
            raise HTTPException(status_code=404, detail="Extraction not found")
        if extraction_row["tenant_id"] != request.tenant_id or extraction_row["domain_id"] != domain_id:
            raise HTTPException(status_code=400, detail="Extraction tenant/domain mismatch")
        connection_id, database_name, schema_name, _ = _resolve_scope_values(
            request.tenant_id,
            domain_id,
        )
        updated = apply_extractions(
            settings,
            tenant_id=request.tenant_id,
            domain_id=domain_id,
            payload=extraction_row["payload"],
            apply_flags=request.apply,
            hierarchy_selection=request.hierarchy_selection,
            source_context_id=extraction_row.get("context_id"),
            connection_id=connection_id,
            database_name=database_name,
            schema_name=schema_name,
        )
        if extraction_row.get("context_id"):
            set_context_active(
                settings,
                tenant_id=request.tenant_id,
                domain_id=domain_id,
                context_id=extraction_row["context_id"],
                connection_id=connection_id,
                database_name=database_name,
                schema_name=schema_name,
                is_active=True,
            )
        return ContextApplyResponse(status="applied", updated=updated).model_dump()
    if job_type == "chart_build":
        return _execute_chart_job(payload)
    if job_type in {"rollup_build", "rollup_refresh"}:
        rollup_id = payload.get("rollup_id")
        if not rollup_id:
            raise HTTPException(status_code=400, detail="rollup_id is required")
        rollup = get_rollup(settings, rollup_id)
        if not rollup:
            raise HTTPException(status_code=404, detail="Rollup not found")
        update_rollup_status(settings, rollup_id, "building" if job_type == "rollup_build" else "refreshing")
        build_rollup_table(settings, rollup, schema_name=settings.db_schema)
        update_rollup_status(settings, rollup_id, "active")
        return {"rollup_id": rollup_id, "status": "active"}
    if job_type == "chat_build":
        chat_id = payload.get("chat_id")
        if not chat_id:
            raise HTTPException(status_code=400, detail="chat_id is required")
        chat_row = get_chat_request(settings, chat_id)
        if not chat_row:
            raise HTTPException(status_code=404, detail="Chat request not found")
        create_chat_event(settings, chat_id, "running", "Chat request started")
        update_chat_request(settings, chat_id, status="running")
        request_payload = chat_row.get("request_payload") or {}
        try:
            create_chat_event(settings, chat_id, "resolve", "Resolving metrics and dimensions")
            query_request = QueryRequest(**request_payload)
            query_result = query(query_request)
            create_chat_event(settings, chat_id, "query", "Executing SQL")
            chart_payload = None
            chart_type = None
            if query_result.rows and query_result.metrics:
                create_chat_event(settings, chat_id, "chart", "Building chart payload")
                chart_type = infer_chart_type(query_result.dimensions, query_result.rows, query_result.metrics)
                if chart_type:
                    chart_payload = build_chart_payload(
                        chart_type,
                        query_result.rows,
                        query_result.metrics[0],
                        query_result.dimensions,
                    )
            response_payload = {
                "metrics": query_result.metrics,
                "dimensions": query_result.dimensions,
                "chart_id": query_result.chart_id,
                "chart_type": chart_type,
                "chart_payload": chart_payload.get("chart_payload") if chart_payload else None,
                "data": chart_payload.get("data") if chart_payload else None,
                "sql": query_result.sql,
                "rows": query_result.rows,
            }
            update_chat_request(settings, chat_id, status="complete", response_payload=response_payload)
            create_chat_event(settings, chat_id, "complete", "Chat response ready")
            return {"chat_id": chat_id, "status": "complete"}
        except Exception as exc:  # noqa: BLE001
            update_chat_request(settings, chat_id, status="failed", error_message=str(exc))
            create_chat_event(settings, chat_id, "failed", "Chat request failed", {"error": str(exc)})
            raise
    if job_type == "dashboard_refresh":
        refresh_id = payload.get("refresh_id")
        dashboard_id = payload.get("dashboard_id")
        if not refresh_id or not dashboard_id:
            raise HTTPException(status_code=400, detail="refresh_id and dashboard_id are required")
        refresh_row = get_dashboard_refresh_run(settings, dashboard_id, refresh_id)
        if not refresh_row:
            raise HTTPException(status_code=404, detail="Dashboard refresh run not found")
        dashboard_row = get_dashboard_spec(settings, dashboard_id)
        if not dashboard_row:
            update_dashboard_refresh_status(settings, refresh_id, "failed", error_message="Dashboard not found")
            raise HTTPException(status_code=404, detail="Dashboard not found")
        update_dashboard_refresh_status(settings, refresh_id, "running")
        append_dashboard_refresh_event(
            settings,
            refresh_id=refresh_id,
            dashboard_id=dashboard_id,
            stage_name="running",
            message="Dashboard refresh started",
            artifacts={},
        )
        request_payload = (refresh_row.get("request_payload") or {}) if isinstance(refresh_row, dict) else {}
        regenerate_titles = bool((request_payload or {}).get("regenerate_titles"))
        spec = dashboard_row.get("spec") or {}
        charts = spec.get("charts") or []
        chart_results: list[dict] = []
        failed_charts: list[dict] = []
        charts_spec_out: list[dict] = []
        for idx, chart in enumerate(charts):
            chart_obj = chart if isinstance(chart, dict) else {}
            chart_id = chart_obj.get("chart_id") or f"dash_chart_{idx+1}"
            chart_type = chart_obj.get("chart_type") or chart_obj.get("type") or "bar"
            metric_name = chart_obj.get("metric_name") or chart_obj.get("metric")
            dimensions = chart_obj.get("dimensions") or []
            sql = chart_obj.get("sql")
            params = chart_obj.get("params") or []
            if chart_obj.get("chart_id"):
                chart_row = get_chart_request(settings, chart_obj.get("chart_id"))
                if chart_row:
                    sql = sql or chart_row.get("sql")
                    params = params or chart_row.get("params") or []
                    if not metric_name:
                        qp = chart_row.get("query_payload") or {}
                        metrics_from_qp = qp.get("metrics") or []
                        if metrics_from_qp:
                            metric_name = metrics_from_qp[0]
                        dimensions = dimensions or qp.get("dimensions") or []
                    chart_type = chart_type or chart_row.get("chart_type") or "bar"
            rows: list[dict] = []
            status = "ok"
            error_message = None
            _dash_chart_scoped_conn = None
            if chart_row:
                _dc_tenant = chart_row.get("tenant_id")
                _dc_domain = chart_row.get("domain_id")
                if _dc_tenant and _dc_domain:
                    _dash_chart_scoped_conn = _resolve_scoped_conn(_dc_tenant, _dc_domain)
            try:
                if sql:
                    rows = run_query(settings, sql, params if isinstance(params, list) else [], scoped_conn=_dash_chart_scoped_conn)
                elif chart_obj.get("chart_data") and isinstance(chart_obj.get("chart_data"), list):
                    rows = chart_obj.get("chart_data") or []
                elif chart_obj.get("rows") and isinstance(chart_obj.get("rows"), list):
                    rows = chart_obj.get("rows") or []
                else:
                    status = "failed"
                    error_message = "No SQL or chart data available for refresh"
            except Exception as exc:  # noqa: BLE001
                status = "failed"
                error_message = str(exc)
            metric_key = metric_name
            if rows and not metric_key:
                for key in rows[0].keys():
                    if key not in {"category", "date", "period"}:
                        try:
                            float(rows[0].get(key))
                            metric_key = key
                            break
                        except (TypeError, ValueError):
                            continue
            stats = dashboard_chart_stats(rows, metric_key)
            insight = dashboard_chart_insight(rows, metric_key, chart_type)
            if not dimensions:
                if chart_type in {"bar", "pie"}:
                    dimensions = ["category"]
                elif chart_type == "line":
                    dimensions = ["date"]
            payload_obj = build_chart_payload(chart_type, rows, metric_key or "value", dimensions or ["category"])
            if chart_obj.get("chart_id") and status == "ok":
                update_chart_request(
                    settings,
                    chart_obj.get("chart_id"),
                    status="ready",
                    sql=sql,
                    params=params if isinstance(params, list) else [],
                    rows_json=rows,
                    chart_type=chart_type,
                    chart_payload=payload_obj.get("chart_payload"),
                    chart_data=payload_obj.get("data"),
                )
            create_dashboard_chart_snapshot(
                settings,
                refresh_id=refresh_id,
                dashboard_id=dashboard_id,
                chart_id=chart_id,
                chart_type=chart_type,
                sql=sql,
                params=params if isinstance(params, list) else [],
                data_json=rows,
                stats_json=stats,
                insight_json={**insight, "status": status, "error_message": error_message},
            )
            result_item = {
                "chart_id": chart_id,
                "chart_type": chart_type,
                "metric_name": metric_key,
                "table": chart_obj.get("table"),
                "rows_count": len(rows),
                "stats": stats,
                "insight": insight,
                "status": status,
            }
            chart_results.append(result_item)
            if status != "ok":
                failed_charts.append(
                    {"chart_id": chart_id, "error_message": error_message or "unknown_error"}
                )

            merged = dict(chart_obj)
            if status == "ok":
                merged["chart_data"] = payload_obj.get("data")
                merged["rows"] = rows
                cp = payload_obj.get("chart_payload")
                if cp is not None:
                    merged["chart_payload"] = cp
                merged["chart_type"] = chart_type
                if sql is not None:
                    merged["sql"] = sql
                merged["params"] = params if isinstance(params, list) else []
            charts_spec_out.append(merged)

        regenerated_count = 0
        if regenerate_titles:
            regenerated_dashboard_title = _regenerated_dashboard_title(
                dashboard_row.get("domain_id"), charts_spec_out
            )
            for chart_obj in charts_spec_out:
                chart_obj["title"] = _regenerated_chart_title(chart_obj)
                chart_obj["chart_title"] = chart_obj["title"]
                chart_obj["dashboard_title"] = regenerated_dashboard_title
            spec["charts"] = charts_spec_out
            spec["title"] = regenerated_dashboard_title
            spec["dashboard_title"] = regenerated_dashboard_title
            update_dashboard_spec(
                settings,
                dashboard_id,
                spec=spec,
                title=regenerated_dashboard_title,
            )
            regenerated_count = len(charts_spec_out)
            append_dashboard_refresh_event(
                settings,
                refresh_id=refresh_id,
                dashboard_id=dashboard_id,
                stage_name="titles_regenerated",
                message=f"Dashboard/chart titles regenerated: {regenerated_count}",
                artifacts={
                    "regenerate_titles": True,
                    "dashboard_title": regenerated_dashboard_title,
                    "chart_titles": [c.get("title") for c in charts_spec_out if isinstance(c, dict)],
                },
            )
        else:
            spec["charts"] = charts_spec_out
            update_dashboard_spec(settings, dashboard_id, spec=spec)

        append_dashboard_refresh_event(
            settings,
            refresh_id=refresh_id,
            dashboard_id=dashboard_id,
            stage_name="charts_refreshed",
            message=f"Dashboard charts refreshed: {len(chart_results) - len(failed_charts)}/{len(chart_results)}",
            artifacts={
                "chart_count": len(chart_results),
                "failed_charts": failed_charts,
                "regenerate_titles": regenerate_titles,
                "regenerated_chart_titles": regenerated_count,
            },
        )
        update_dashboard_refresh_status(settings, refresh_id, "charts_refreshed")

        evidence = build_dashboard_evidence(chart_results)
        quality_confidence = 1.0 if evidence.get("total_charts", 0) == 0 else max(
            0.0,
            min(
                1.0,
                (evidence.get("refreshed_charts", 0) / max(1, evidence.get("total_charts", 0))),
            ),
        )
        warnings = []
        if failed_charts:
            warnings.append("some_chart_refreshes_failed")
        if evidence.get("refreshed_charts", 0) == 0:
            warnings.append("no_refreshed_charts")
        quality = {"confidence": round(quality_confidence, 3), "warnings": warnings}

        summary_base = deterministic_dashboard_summary(evidence)
        inference_base = deterministic_dashboard_inference(evidence)
        summary_raw_text = llm_rewrite_text(
            settings,
            kind="summary",
            base_text=summary_base,
            evidence=evidence,
        )
        inference_raw_text = llm_rewrite_text(
            settings,
            kind="inference",
            base_text=inference_base,
            evidence=evidence,
        )
        summary_html = render_summary_html(summary_raw_text, evidence)
        inference_html = render_inference_html(inference_raw_text, evidence)

        upsert_dashboard_insights_artifact(
            settings,
            refresh_id=refresh_id,
            dashboard_id=dashboard_id,
            summary_raw_text=summary_raw_text,
            summary_html=summary_html,
            inference_raw_text=inference_raw_text,
            inference_html=inference_html,
            evidence_json=evidence,
            quality_json=quality,
        )
        append_dashboard_refresh_event(
            settings,
            refresh_id=refresh_id,
            dashboard_id=dashboard_id,
            stage_name="summary_ready",
            message="Dashboard summary ready",
            artifacts={"confidence": quality.get("confidence"), "warnings": warnings},
        )
        update_dashboard_refresh_status(settings, refresh_id, "summary_ready")
        append_dashboard_refresh_event(
            settings,
            refresh_id=refresh_id,
            dashboard_id=dashboard_id,
            stage_name="inference_ready",
            message="Dashboard inference ready",
            artifacts={"confidence": quality.get("confidence"), "warnings": warnings},
        )
        update_dashboard_refresh_status(settings, refresh_id, "inference_ready")
        final_status = "partial_completed" if failed_charts else "completed"
        append_dashboard_refresh_event(
            settings,
            refresh_id=refresh_id,
            dashboard_id=dashboard_id,
            stage_name=final_status,
            message="Dashboard refresh completed" if not failed_charts else "Dashboard refresh partially completed",
            artifacts={"failed_charts": failed_charts, "confidence": quality.get("confidence")},
        )
        update_dashboard_refresh_status(settings, refresh_id, final_status)
        return {"refresh_id": refresh_id, "dashboard_id": dashboard_id, "status": final_status}
    if job_type == "agentic_run":
        run_id = payload.get("run_id")
        if not run_id:
            raise HTTPException(status_code=400, detail="run_id is required")
        run = get_agent_run(settings, run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        mark_run_status(settings, run_id, "running")
        initial_state = payload.get("initial_state") or {}
        tenant_id = str(initial_state.get("tenant_id") or run.get("tenant_id") or "").strip() or None
        canonicalize_on_success = bool(payload.get("canonicalize_on_success"))
        logger.info(
            "agentic.job.start | run_id=%s tenant=%s domain=%s initial_state_keys=%s workflow=%s",
            run_id,
            tenant_id,
            initial_state.get("domain_id") or run.get("domain_id"),
            sorted(initial_state.keys()) if isinstance(initial_state, dict) else [],
            "services.ai.agentic_orchestrator.run_agentic_workflow",
        )
        with _langsmith_project_context(tenant_id):
            forwarder = LangSmithEventForwarder(run_id, tenant_id=tenant_id)
            try:
                result = run_agentic_workflow(settings, run_id, initial_state, event_callback=forwarder.on_event)
                final_status = str(result.get("run_status") or "completed")
                mark_run_status(settings, run_id, final_status)
                if canonicalize_on_success and final_status == "completed":
                    finalize_canonical_deployment(settings, run_id)
                forwarder.close(status=final_status)
                return {"run_id": run_id, "status": final_status}
            except Exception as exc:  # noqa: BLE001
                mark_run_status(settings, run_id, "failed")
                error_artifacts = {
                    "error_message": str(exc),
                    "error_type": exc.__class__.__name__,
                    "traceback": traceback.format_exc(limit=20),
                }
                try:
                    stage = append_agent_run_stage_event(
                        settings,
                        run_id,
                        "WorkflowAgent",
                        "failed",
                        "Agentic workflow failed",
                        artifacts=error_artifacts,
                    )
                    append_agent_chat_log(
                        settings,
                        run_id,
                        sender="system",
                        message=f"Run failed: {exc}",
                        artifacts=error_artifacts,
                    )
                    logger.error(
                        "agentic.run.failed | run_id=%s event_id=%s error_type=%s error=%s",
                        run_id,
                        stage.get("event_id"),
                        exc.__class__.__name__,
                        str(exc),
                    )
                except Exception:  # noqa: BLE001
                    logger.exception("agentic.run.failed_event_emit_failed | run_id=%s", run_id)
                    append_agent_run_event(
                        settings,
                        run_id,
                        "WorkflowAgent",
                        "failed",
                        "Agentic workflow failed",
                        error_artifacts,
                    )
                forwarder.close(status="failed", error=str(exc))
                raise
    if job_type == "data_quality_resume_after_rule_review":
        run_id = payload.get("run_id")
        if not run_id:
            raise HTTPException(status_code=400, detail="run_id is required")
        run = get_quality_run_by_run_id(settings, run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Data quality run not found")
        mark_run_status(settings, run_id, "running")
        tenant_id = str(run.get("tenant_id") or "").strip() or None
        with _langsmith_project_context(tenant_id):
            forwarder = LangSmithEventForwarder(run_id, tenant_id=tenant_id)
            try:
                result = resume_data_quality_agentic_workflow_after_rule_review(
                    settings,
                    run_id,
                    event_callback=forwarder.on_event,
                )
                final_status = str(result.get("run_status") or "completed")
                mark_run_status(settings, run_id, final_status)
                forwarder.close(status=final_status)
                return {"run_id": run_id, "status": final_status}
            except Exception as exc:  # noqa: BLE001
                mark_run_status(settings, run_id, "failed")
                forwarder.close(status="failed", error=str(exc))
                raise
    raise ValueError(f"Unsupported job_type: {job_type}")


def _job_worker_loop() -> None:
    poll_seconds = float(os.getenv("JOB_WORKER_POLL_SEC", "2"))
    logger.info("Job worker started (poll=%ss)", poll_seconds)
    while not _job_worker_stop.is_set():
        job = claim_next_job(settings)
        if not job:
            logger.debug("Job worker idle (no queued jobs)")
            _job_worker_stop.wait(poll_seconds)
            continue
        job_id = job.get("job_id")
        job_type = job.get("job_type")
        logger.info("Job claimed | job_id=%s job_type=%s", job_id, job_type)
        try:
            current = get_job(settings, job_id)
            if current and current.get("status") == "canceled":
                logger.info("Job canceled before start | job_id=%s", job_id)
                continue
            update_job_progress(settings, job_id, progress_pct=0, progress_stage="started")
            logger.info("Job started | job_id=%s job_type=%s", job_id, job_type)
            result = _execute_job(job)
            current = get_job(settings, job_id)
            if current and current.get("status") == "canceled":
                update_job_status(
                    settings,
                    job_id,
                    "canceled",
                    result_payload=None,
                    error_message=current.get("error_message") or "Canceled by user request",
                )
                continue
            update_job_progress(settings, job_id, progress_pct=100, progress_stage="completed")
            update_job_status(settings, job_id, "completed", result_payload=result, error_message=None)
            logger.info("Job completed | job_id=%s job_type=%s", job_id, job_type)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Job failed: %s", job_id)
            update_job_status(settings, job_id, "failed", result_payload=None, error_message=str(exc))
    logger.info("Job worker stopped")


@app.on_event("startup")
def _start_job_worker() -> None:
    logger.info(
        "quantyx.api.build_loaded | build_version=%s phase52_enabled=%s correlation_flow_version=%s anomaly_flow_version=%s",
        PHASE52_BUILD_VERSION,
        True,
        "2026-04-03-correlation-debug-v1",
        "2026-04-03-anomaly-fallback-debug-v1",
    )
    enabled = os.getenv("JOB_WORKER_ENABLED", "true").lower() not in {"0", "false", "no"}
    global _job_worker_thread
    if not enabled:
        logger.info("Job worker disabled via JOB_WORKER_ENABLED")
        return
    if _job_worker_thread and _job_worker_thread.is_alive():
        return
    _job_worker_thread = threading.Thread(target=_job_worker_loop, name="job-worker", daemon=True)
    _job_worker_thread.start()


@app.on_event("shutdown")
def _stop_job_worker() -> None:
    _job_worker_stop.set()
ALLOWED_METRIC_TYPES = {
    "sum",
    "average",
    "avg",
    "min",
    "max",
    "count",
    "count_distinct",
    "ratio",
    "rate",
    "derived",
}
GRAIN_ORDER = {
    "transaction": 0,
    "hour": 1,
    "day": 2,
    "week": 3,
    "month": 4,
    "quarter": 5,
    "year": 6,
}
T = TypeVar("T")


def _decode_cursor(cursor: str) -> str:
    try:
        return base64.b64decode(cursor).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid cursor") from exc


def _encode_cursor(value: str) -> str:
    return base64.b64encode(value.encode("utf-8")).decode("utf-8")


def _paginate_list(
    items: list[T],
    cursor: str | None,
    limit: int,
    key_fn: Callable[[T], str],
) -> tuple[list[T], str | None]:
    if limit < 1:
        raise HTTPException(status_code=400, detail="limit must be >= 1")
    sorted_items = sorted(items, key=key_fn)
    if cursor:
        cursor_value = _decode_cursor(cursor)
        sorted_items = [item for item in sorted_items if key_fn(item) > cursor_value]
    page = sorted_items[:limit]
    next_cursor = None
    if page:
        next_cursor = _encode_cursor(key_fn(page[-1]))
    return page, next_cursor


def _resolve_domain_id(tenant_id: str, request_domain_id: str | None = None) -> str:
    row = get_tenant_domain(settings, tenant_id)
    if row and row.get("domain_id"):
        return row["domain_id"]
    if request_domain_id:
        logger.warning(
            "domain_id fallback used for tenant %s; configure /tenant/domain", tenant_id
        )
        return request_domain_id
    raise HTTPException(status_code=400, detail="domain_id not configured for tenant")


def _latest_run_for_scope(tenant_id: str, domain_id: str) -> dict | None:
    rows = run_query(
        settings,
        """
        SELECT run_id, tenant_id, domain_id, status, created_at, updated_at
          FROM public.quantyx_agent_runs
         WHERE tenant_id = %s
           AND domain_id = %s
         ORDER BY created_at DESC
         LIMIT 1
        """,
        [tenant_id, domain_id],
    )
    return rows[0] if rows else None


def _inflight_run_for_scope(tenant_id: str, domain_id: str) -> dict | None:
    rows = run_query(
        settings,
        """
        SELECT run_id, tenant_id, domain_id, status, created_at, updated_at
          FROM public.quantyx_agent_runs
         WHERE tenant_id = %s
           AND domain_id = %s
           AND status IN ('queued', 'running')
         ORDER BY created_at DESC
         LIMIT 1
        """,
        [tenant_id, domain_id],
    )
    return rows[0] if rows else None


def _model_schema_map() -> dict[str, str]:
    models = load_manifest_models(settings)
    return {model["name"]: model.get("schema") or "" for model in models}


def _model_database_map() -> dict[str, str]:
    models = load_manifest_models(settings)
    return {model["name"]: model.get("database") or "" for model in models}


def _extract_tables_from_scan(
    scan_result: dict,
    connection_id: str,
    database: str,
    schema: str,
    tables: list[str],
) -> list[dict]:
    for connection in scan_result.get("connections", []):
        if connection.get("connection_id") != connection_id:
            continue
        for db in connection.get("databases", []):
            if db.get("name") != database:
                continue
            for sch in db.get("schemas", []):
                if sch.get("name") != schema:
                    continue
                if not tables:
                    return sch.get("tables", [])
                return [t for t in sch.get("tables", []) if t.get("table") in tables]
    return []


def _filter_by_model_attr(items: list[dict], value: str | None, key: str, attr: str) -> list[dict]:
    if not value:
        return items
    model_map = _model_schema_map() if attr == "schema" else _model_database_map()
    filtered = []
    for item in items:
        model_name = item.get(key)
        if not model_name:
            filtered.append(item)
            continue
        model_value = model_map.get(model_name, "")
        if model_value == value:
            filtered.append(item)
    return filtered


def _log_scan_step(step: str, details: dict | None = None) -> None:
    payload = details or {}
    logger.info("scan-connection: %s | %s", step, payload)


@app.get(
    "/health",
    tags=["system"],
    summary="Health check",
    description="Simple health check for the API process.",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "ok": {"summary": "Healthy", "value": {"status": "ok"}}
                        }
                    }
                }
            }
        }
    },
)
def health() -> dict:
    return {"status": "ok", "build_version": BUILD_VERSION}


@app.get(
    "/packs",
    response_model=PackListResponse,
    tags=["admin"],
    summary="List available packs",
)
def list_available_packs() -> PackListResponse:
    packs = list_pack_metadata()
    if not packs:
        packs = [{"industry": pack} for pack in list_packs()]
    return PackListResponse(packs=packs)


@app.post(
    "/packs/apply",
    response_model=PackApplyResponse,
    tags=["admin"],
    summary="Apply a pack version to a tenant",
)
def apply_pack(request: PackApplyRequest) -> PackApplyResponse:
    pack = load_pack(f"packs/{request.industry}")
    pack_meta = pack.get("pack") or {}
    version = request.version or pack_meta.get("version") or "1.0.0"
    register_pack_version(
        settings,
        industry=request.industry,
        version=version,
        release_date=pack_meta.get("release_date"),
        breaking_changes=pack_meta.get("breaking_changes"),
        notes=pack_meta.get("notes"),
    )
    payload = {
        "pack": pack_meta,
        "ontology": pack.get("ontology", {}),
        "datasets": pack.get("datasets", {}),
        "metric_templates": pack.get("metric_templates", {}),
        "policies": pack.get("policies", {}),
    }
    contract_id = store_semantic_contract(
        settings,
        tenant_id=request.tenant_id,
        industry=request.industry,
        version=version,
        payload=payload,
        status="active",
    )
    return PackApplyResponse(ok=True, contract_id=contract_id)


@app.get(
    "/contracts/semantic",
    response_model=SemanticContractResponse,
    tags=["admin"],
    summary="Get active semantic contract",
)
def get_semantic_contract(
    tenant_id: str,
    industry: str,
) -> SemanticContractResponse:
    contract = get_active_semantic_contract(settings, tenant_id, industry)
    if not contract:
        raise HTTPException(status_code=404, detail="No active contract found")
    return SemanticContractResponse(**contract)


@app.post(
    "/contracts/semantic/validate",
    response_model=SemanticContractValidateResponse,
    tags=["admin"],
    summary="Validate semantic contract payload",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "validate": {
                            "summary": "Validate contract payload",
                            "value": {
                                "ontology": {"entity_types": {}},
                                "datasets": {"datasets": []},
                                "metric_definitions": [],
                                "dataset_definitions": [],
                            },
                        }
                    }
                }
            }
        },
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "ok": {"value": {"ok": True, "errors": []}},
                            "error": {"value": {"ok": False, "errors": [{"field": "ontology", "issue": "missing"}]}},
                        }
                    }
                }
            }
        },
    },
)
def validate_semantic_contract(payload: dict) -> SemanticContractValidateResponse:
    errors = []
    if "ontology" not in payload:
        errors.append({"field": "ontology", "issue": "missing"})
    if "datasets" not in payload:
        errors.append({"field": "datasets", "issue": "missing"})
    errors.extend(validate_semantic_payload(payload))
    if errors:
        return SemanticContractValidateResponse(ok=False, errors=errors)
    return SemanticContractValidateResponse(ok=True, errors=[])


@app.post(
    "/contracts/semantic/extract",
    response_model=SemanticExtractResponse,
    tags=["admin"],
    summary="Extract semantic contract elements with LLM",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "extract": {
                            "summary": "Extract glossary terms",
                            "value": {
                                "tenant_id": "VC_101",
                                "industry": "lpg_production_distribution",
                                "inputs": {
                                    "raw_text": "Plant = LPG filling facility. SAP ID identifies plant.",
                                    "tables_and_columns": "lpg_plant_operations: [process_date, sap_id, region, production_19kg]",
                                    "entity_types": ["organizational_unit", "plant", "product"],
                                    "metric_candidate": "metric_name=production_mt, columns=[production_14_2kg, production_19kg]",
                                },
                                "model": "gpt-4o-mini",
                            },
                        }
                    }
                }
            }
        },
        "responses": {
            "200": {
                "content": {
                    "application/json": {"examples": {"extracted": {"value": {"contract_id": "contract_123", "status": "extracted"}}}}
                }
            }
        },
    },
)
def extract_semantic_contract(request: SemanticExtractRequest) -> SemanticExtractResponse:
    raw_text = (request.inputs or {}).get("raw_text", "")
    tables_and_columns = (request.inputs or {}).get("tables_and_columns")
    entity_types = (request.inputs or {}).get("entity_types")
    metric_candidate_payload = (request.inputs or {}).get("metric_candidate")
    extraction = extract_semantic_contract(
        settings,
        raw_text=raw_text,
        tables_and_columns=tables_and_columns,
        entity_types=entity_types,
        metric_candidate_payload=metric_candidate_payload,
    )
    payload = {
        "business_terms": extraction.get("business_terms", []),
        "entity_mappings": extraction.get("entity_mappings", []),
        "metric_definitions": extraction.get("metric_definitions", []),
    }
    contract_id = store_semantic_contract(
        settings,
        tenant_id=request.tenant_id,
        industry=request.industry,
        version="live",
        payload=payload,
        status="live",
    )
    return SemanticExtractResponse(contract_id=contract_id, status="extracted")


@app.post(
    "/contracts/semantic/apply",
    response_model=SemanticApplyResponse,
    tags=["admin"],
    summary="Apply a semantic contract (set active)",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "apply": {
                            "summary": "Apply contract",
                            "value": {"tenant_id": "VC_101", "contract_id": "contract_123"},
                        }
                    }
                }
            }
        },
        "responses": {
            "200": {
                "content": {
                    "application/json": {"examples": {"ok": {"value": {"ok": True}}}}
                }
            }
        },
    },
)
def apply_semantic_contract(request: SemanticApplyRequest) -> SemanticApplyResponse:
    contract = get_semantic_contract(settings, request.contract_id)
    if not contract or contract.get("tenant_id") != request.tenant_id:
        raise HTTPException(status_code=404, detail="Contract not found")
    update_contract_status(settings, request.contract_id, "active")
    return SemanticApplyResponse(ok=True)


@app.post(
    "/semantic/suggest",
    response_model=SemanticSuggestResponse,
    tags=["semantic"],
    summary="Suggest semantic models",
    description="Generate generic facts, dimensions, metrics, and lineage from schema and question types.",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "suggest": {
                            "summary": "Suggest semantic model",
                            "value": {
                                "tenant_id": "VC_101",
                                "domain_id": "lpg_production_distribution",
                                "inputs": {
                                    "schema_summary": "lpg_plant_operations: [process_date, sap_id, region, production_19kg]",
                                    "questions": [
                                        "Top 5 plants by LPG production last week",
                                        "Which regions are trending down YoY?",
                                    ],
                                    "glossary": "Plant = LPG filling facility; SAP ID identifies plant",
                                },
                                "model": "gpt-4o-mini",
                            },
                        }
                    }
                }
            }
        }
    },
)
def semantic_suggest(request: SemanticSuggestRequest) -> SemanticSuggestResponse:
    if not request.tenant_id:
        raise HTTPException(status_code=400, detail="tenant_id is required")
    domain_id = _resolve_domain_id(request.tenant_id, request.domain_id)
    inputs = request.inputs
    schema_summary = inputs.schema_summary
    tables = inputs.tables
    if not schema_summary:
        connection_id, database_name, schema_name, _ = _resolve_scope_values(request.tenant_id, domain_id)
        schema_payload = load_latest_scan_for_scope(
            settings,
            request.tenant_id,
            domain_id,
            connection_id,
            database_name,
            schema_name,
        )
        if not schema_payload:
            raise HTTPException(status_code=400, detail="No scan results found for scope")
        tables = schema_payload.get("tables", [])
        schema_summary = build_schema_summary(tables)

    suggestions = suggest_semantic_model(
        settings,
        schema_summary=schema_summary,
        questions=inputs.questions,
        glossary=inputs.glossary,
        domain_id=domain_id,
        model_override=request.model,
        tables=tables,
    )
    return SemanticSuggestResponse(**suggestions)


def _infer_edge_type(from_type: str | None, to_type: str | None) -> str | None:
    if from_type == "dimension" and to_type == "fact":
        return "dimension_to_fact"
    if from_type == "fact" and to_type == "metric":
        return "fact_to_metric"
    return None


@app.post(
    "/semantic/suggest/apply",
    response_model=SemanticSuggestApplyResponse,
    tags=["semantic"],
    summary="Persist suggested semantic models",
    description="Persist facts, dimensions, metrics, and lineage to registries and canvas.",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "apply": {
                            "summary": "Apply semantic suggestions",
                            "value": {
                                "tenant_id": "VC_101",
                                "domain_id": "lpg_production_distribution",
                                "facts": [
                                    {
                                        "table_name": "fact_lpg_plant_operations",
                                        "grain": "day",
                                        "time_column": "process_date",
                                        "measures": ["production_14_2kg", "production_19kg"],
                                        "dimensions": ["sap_id", "region"],
                                        "description": "Daily LPG production fact",
                                        "status": "live",
                                    }
                                ],
                                "dimensions": [
                                    {
                                        "name": "dim_plant",
                                        "keys": ["sap_id"],
                                        "attributes": ["plant_name", "region"],
                                        "description": "Plant dimension",
                                        "status": "live",
                                    }
                                ],
                                "metrics": [
                                    {
                                        "metric_name": "production_mt",
                                        "type": "sum",
                                        "sql": "({{ ref('fact_lpg_plant_operations') }}.production_14_2kg * 14.2 + {{ ref('fact_lpg_plant_operations') }}.production_19kg * 19) / 1000",
                                        "grain": "day",
                                        "dimensions": ["sap_id", "region"],
                                        "description": "Total LPG production in MT",
                                        "status": "suggested",
                                    }
                                ],
                                "lineage": {
                                    "edges": [
                                        {"from": "dim_plant", "to": "fact_lpg_plant_operations"},
                                        {"from": "fact_lpg_plant_operations", "to": "production_mt"},
                                    ]
                                },
                            },
                        }
                    }
                }
            }
        }
    },
)
def semantic_suggest_apply(request: SemanticSuggestApplyRequest) -> SemanticSuggestApplyResponse:
    if not request.tenant_id:
        raise HTTPException(status_code=400, detail="tenant_id is required")
    domain_id = _resolve_domain_id(request.tenant_id, request.domain_id)
    connection_id, database_name, schema_name, _ = _resolve_scope_values(request.tenant_id, domain_id)

    facts = request.facts or []
    dimensions = request.dimensions or []
    metrics = request.metrics or []
    fact_grains = _fact_grain_map(request.tenant_id, domain_id, connection_id, database_name, schema_name)
    node_alias_to_id: dict[str, str] = {}
    nodes: list[dict] = []

    for fact in facts:
        table_name = fact.get("table_name") or fact.get("name")
        if not table_name:
            continue
        fact_payload = {
            "fact_id": fact.get("fact_id"),
            "tenant_id": request.tenant_id,
            "domain_id": domain_id,
            "connection_id": connection_id,
            "database_name": database_name,
            "schema_name": schema_name,
            "table_name": table_name,
            "grain": fact.get("grain"),
            "time_column": fact.get("time_column"),
            "measures": fact.get("measures", []),
            "dimensions": fact.get("dimensions", []),
            "description": fact.get("description"),
            "status": fact.get("status", "live"),
        }
        _validate_fact_payload(fact_payload)
        fact_id = upsert_fact(
            settings,
            fact_payload,
        )
        for alias in (table_name, fact.get("fact_id"), fact_id):
            if alias:
                node_alias_to_id[str(alias)] = fact_id
        if table_name:
            fact_grains[str(table_name)] = fact.get("grain")
        nodes.append({"id": fact_id, "type": "fact", "label": table_name})

    for dim in dimensions:
        name = dim.get("name")
        if not name:
            continue
        dim_payload = {
            "dimension_id": dim.get("dimension_id"),
            "tenant_id": request.tenant_id,
            "domain_id": domain_id,
            "connection_id": connection_id,
            "database_name": database_name,
            "schema_name": schema_name,
            "name": name,
            "keys": dim.get("keys", []),
            "attributes": dim.get("attributes", []),
            "description": dim.get("description"),
            "status": dim.get("status", "live"),
        }
        _validate_dimension_payload(dim_payload)
        dimension_id = upsert_dimension(
            settings,
            dim_payload,
        )
        for alias in (name, dim.get("dimension_id"), dimension_id):
            if alias:
                node_alias_to_id[str(alias)] = dimension_id
        nodes.append({"id": dimension_id, "type": "dimension", "label": name})

    for metric in metrics:
        metric_name = metric.get("metric_name")
        if not metric_name:
            continue
        metric_payload = {
            "metric_id": metric.get("metric_id"),
            "tenant_id": request.tenant_id,
            "domain_id": domain_id,
            "connection_id": connection_id,
            "database": database_name,
            "schema": schema_name,
            "metric_name": metric_name,
            "display_name": metric.get("display_name"),
            "description": metric.get("description"),
            "type": metric.get("type"),
            "sql": metric.get("sql"),
            "grain": metric.get("grain"),
            "dimensions": metric.get("dimensions", []),
            "unit": metric.get("unit"),
            "status": metric.get("status", "suggested"),
            "dataset_id": metric.get("dataset_id"),
            "source_model": metric.get("source_model"),
            "source_schema": metric.get("source_schema"),
            "owner": metric.get("owner"),
            "version": metric.get("version"),
        }
        _validate_metric_payload(metric_payload, fact_grains)
        metric_id = upsert_metric(
            settings,
            metric_payload,
        )
        for alias in (metric_name, metric.get("metric_id"), metric_id):
            if alias:
                node_alias_to_id[str(alias)] = metric_id
        nodes.append({"id": metric_id, "type": "metric", "label": metric_name})

    node_types = {node["id"]: node["type"] for node in nodes}

    edges = []
    lineage_edges = (request.lineage or {}).get("edges", []) if isinstance(request.lineage, dict) else []
    if not isinstance(lineage_edges, list) or not lineage_edges:
        lineage_edges = build_lineage_edges(facts, dimensions, metrics)
    for edge in lineage_edges:
        from_id = node_alias_to_id.get(str(edge.get("from")), edge.get("from"))
        to_id = node_alias_to_id.get(str(edge.get("to")), edge.get("to"))
        if not from_id or not to_id:
            continue
        if from_id not in node_types or to_id not in node_types:
            continue
        edge_type = edge.get("edge_type") or _infer_edge_type(node_types.get(from_id), node_types.get(to_id))
        if not edge_type:
            continue
        edges.append(
            {
                "from": from_id,
                "to": to_id,
                "edge_type": edge_type,
                "source": edge.get("source", "llm"),
                "confidence": edge.get("confidence"),
                "from_type": node_types.get(from_id),
                "to_type": node_types.get(to_id),
            }
        )

    canvas_id: str | None = request.canvas_id
    if nodes or edges:
        if canvas_id:
            _ensure_canvas_owned(canvas_id, request.tenant_id, domain_id)
        if edges:
            _validate_canvas_edges(nodes, edges)
        if request.idempotency_key:
            rows = run_query(
                settings,
                """
                SELECT canvas_id
                  FROM public.quantyx_canvases
                 WHERE tenant_id = %s AND domain_id = %s AND idempotency_key = %s
                 LIMIT 1
                """,
                [request.tenant_id, domain_id, request.idempotency_key],
            )
            if rows:
                canvas_id = rows[0]["canvas_id"]
        if not canvas_id:
            canvas_id = f"canvas_{uuid.uuid4().hex[:10]}"
        _persist_canvas_graph(
            tenant_id=request.tenant_id,
            domain_id=domain_id,
            canvas_id=canvas_id,
            name="AI Suggested Canvas",
            description="Auto-generated semantic model",
            root_node_id=None,
            status="live",
            idempotency_key=request.idempotency_key,
            nodes=nodes,
            edges=edges,
        )

    return SemanticSuggestApplyResponse(
        ok=True,
        canvas_id=canvas_id,
        facts=len(facts),
        dimensions=len(dimensions),
        metrics=len(metrics),
    )

@app.post(
    "/jobs",
    response_model=JobCreateResponse,
    status_code=202,
    tags=["jobs"],
    summary="Submit async job",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "scan_job": {
                            "summary": "Scan connection job",
                            "value": {
                                "tenant_id": "VC_101",
                                "domain_id": "lpg_production_distribution",
                                "job_type": "scan_connection",
                                "payload": {
                                    "tenant_id": "VC_101",
                                    "connections": [
                                        {
                                            "connection_id": "conn_lpg",
                                            "db_type": "postgres",
                                            "host": "db.company.com",
                                            "port": 5432,
                                            "user": "readonly_user",
                                            "password": "******",
                                            "sample_rows": 100,
                                            "databases": [
                                                {
                                                    "name": "hpcl_ceg",
                                                    "schemas": [
                                                        {"name": "public", "tables": ["lpg_plant_operations"]}
                                                    ],
                                                }
                                            ],
                                        }
                                    ],
                                },
                                "idempotency_key": "client-123",
                            },
                        }
                    }
                }
            }
        },
        "responses": {
            "202": {
                "content": {
                    "application/json": {"examples": {"queued": {"value": {"job_id": "job_123", "status": "queued"}}}}
                }
            }
        },
    },
)
def submit_job(request: JobCreateRequest) -> JobCreateResponse:
    if request.job_type not in JOB_TYPES:
        raise HTTPException(status_code=400, detail="Unsupported job_type")
    payload = dict(request.payload or {})
    if payload.get("tenant_id") and payload["tenant_id"] != request.tenant_id:
        raise HTTPException(status_code=400, detail="tenant_id mismatch in payload")
    payload.setdefault("tenant_id", request.tenant_id)
    domain_id = _resolve_domain_id(request.tenant_id, request.domain_id)
    if request.job_type == "scan_connection":
        payload.setdefault("domain_id", domain_id)
    if request.job_type in {"map_entities", "infer_models", "metrics_suggested"}:
        connection_id, database_name, schema_name, tables = _resolve_scope_values(
            request.tenant_id,
            domain_id,
        )
        payload["connection_id"] = connection_id
        payload["database"] = database_name
        payload["schema"] = schema_name
        if tables is not None:
            payload["tables"] = tables
    job = create_job(
        settings,
        tenant_id=request.tenant_id,
        domain_id=domain_id,
        job_type=request.job_type,
        payload=payload,
        idempotency_key=request.idempotency_key,
    )
    return JobCreateResponse(job_id=job["job_id"], status=job["status"])


@app.get(
    "/jobs/{job_id}",
    response_model=JobStatusResponse,
    tags=["jobs"],
    summary="Get job status",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "running": {
                                "value": {
                                    "job_id": "job_123",
                                    "job_type": "scan_connection",
                                    "status": "running",
                                    "progress_pct": 35,
                                    "progress_stage": "scan.schema:public",
                                    "error_message": None,
                                }
                            }
                        }
                    }
                }
            }
        }
    },
)
def get_job_status(job_id: str) -> JobStatusResponse:
    job = get_job(settings, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    job.pop("scope_id", None)
    created_at = job.get("created_at")
    if created_at is not None and hasattr(created_at, "isoformat"):
        job["created_at"] = created_at.isoformat()
    updated_at = job.get("updated_at")
    if updated_at is not None and hasattr(updated_at, "isoformat"):
        job["updated_at"] = updated_at.isoformat()
    return JobStatusResponse(**job)


@app.get(
    "/jobs/{job_id}/result",
    response_model=JobResultResponse,
    tags=["jobs"],
    summary="Get job result",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "completed": {
                                "value": {
                                    "job_id": "job_123",
                                    "status": "completed",
                                    "result": {"connections": []},
                                }
                            },
                            "failed": {
                                "value": {
                                    "job_id": "job_123",
                                    "status": "failed",
                                    "error_message": "Connection timeout",
                                    "result": None,
                                }
                            },
                        }
                    }
                }
            },
            "202": {
                "content": {
                    "application/json": {
                        "examples": {
                            "pending": {"value": {"job_id": "job_123", "status": "running", "result": None}}
                        }
                    }
                }
            },
        }
    },
)
def get_job_result(job_id: str, response: Response) -> JobResultResponse:
    job = fetch_job_result(settings, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    status_value = job.get("status")
    if status_value in {"queued", "running"}:
        response.status_code = 202
        return JobResultResponse(job_id=job_id, status=status_value, result=None, error_message=None)
    if status_value in {"failed", "canceled"}:
        return JobResultResponse(
            job_id=job_id,
            status=status_value,
            result=None,
            error_message=job.get("error_message"),
        )
    return JobResultResponse(
        job_id=job_id,
        status=status_value,
        result=job.get("result_payload"),
        error_message=None,
    )


@app.get(
    "/jobs",
    response_model=JobListResponse,
    tags=["jobs"],
    summary="List jobs",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "jobs": {
                                "value": {
                                    "jobs": [
                                        {
                                            "job_id": "job_123",
                                            "job_type": "scan_connection",
                                            "status": "running",
                                            "created_at": "2025-02-14T10:00:00Z",
                                            "updated_at": "2025-02-14T10:01:00Z",
                                        }
                                    ],
                                    "limit": 50,
                                    "cursor": None,
                                    "next_cursor": None,
                                }
                            }
                        }
                    }
                }
            }
        }
    },
)
def list_jobs(
    tenant_id: str,
    job_type: str | None = None,
    status: str | None = None,
    limit: int = 50,
    cursor: str | None = None,
    offset: int | None = None,
) -> JobListResponse:
    payload = fetch_jobs(
        settings,
        tenant_id=tenant_id,
        job_type=job_type,
        status=status,
        limit=limit,
        cursor=cursor,
        offset=offset
    )
    for item in payload.get("jobs", []):
        item.pop("scope_id", None)
    return JobListResponse(**payload)


@app.post(
    "/jobs/{job_id}/cancel",
    response_model=JobCancelResponse,
    tags=["jobs"],
    summary="Cancel job",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {"canceled": {"value": {"job_id": "job_123", "status": "canceled"}}}
                    }
                }
            }
        }
    },
)
def cancel_job(job_id: str) -> JobCancelResponse:
    job = get_job(settings, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    status_value = job.get("status")
    if status_value in {"queued", "running"}:
        update_job_status(settings, job_id, "canceled", result_payload=None, error_message="Canceled by user request")
        status_value = "canceled"
    return JobCancelResponse(job_id=job_id, status=status_value)


@app.post(
    "/tenants",
    response_model=TenantResponse,
    tags=["admin"],
    summary="Create or update a tenant",
    description="Register a tenant for UI switching and metadata storage.",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "create_tenant": {
                            "summary": "Create tenant",
                            "value": {
                                "tenant_id": "VC_101",
                                "display_name": "HPCL LPG",
                                "domain_id": "lpg_production_distribution",
                                "status": "active",
                                "metadata": {"region": "IN"},
                            },
                        }
                    }
                }
            }
        },
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "created": {
                                "summary": "Tenant created",
                                "value": {
                                    "tenant_id": "VC_101",
                                    "display_name": "HPCL LPG",
                                    "status": "active",
                                    "domain_id": "lpg_production_distribution",
                                },
                            }
                        }
                    }
                }
            }
        },
    },
)
def create_tenant(payload: TenantCreateRequest) -> TenantResponse:
    if not payload.domain_id:
        raise HTTPException(status_code=400, detail="domain_id is required")
    row = upsert_tenant(
        settings,
        tenant_id=payload.tenant_id,
        display_name=payload.display_name,
        status=payload.status,
        metadata=payload.metadata,
        domain_id=payload.domain_id,
    )
    domain_row = get_tenant_domain(settings, payload.tenant_id)
    return TenantResponse(
        tenant_id=row.get("tenant_id") or payload.tenant_id,
        display_name=row.get("display_name"),
        status=row.get("status") or payload.status,
        domain_id=domain_row.get("domain_id") if domain_row else None,
        metadata=row.get("metadata"),
        created_at=row.get("created_at").isoformat() if row.get("created_at") else None,
        updated_at=row.get("updated_at").isoformat() if row.get("updated_at") else None,
    )


@app.get(
    "/tenants",
    response_model=TenantsResponse,
    tags=["admin"],
    summary="List tenants",
    description="List tenants available for UI switching.",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "tenants": {
                                "summary": "Tenant list",
                                "value": {
                                    "tenants": [
                                        {
                                            "tenant_id": "VC_101",
                                            "display_name": "HPCL LPG",
                                            "status": "active",
                                            "domain_id": "lpg_production_distribution",
                                        },
                                        {
                                            "tenant_id": "BT_01",
                                            "display_name": "Bharat Petroleum",
                                            "status": "active",
                                            "domain_id": "lpg_production_distribution",
                                        },
                                    ],
                                    "limit": 200,
                                },
                            }
                        }
                    }
                }
            }
        }
    },
)
def list_tenants_api(limit: int = 200) -> TenantsResponse:
    rows = list_tenants(settings, limit=limit)
    payload = []
    for row in rows:
        payload.append(
            {
                "tenant_id": row.get("tenant_id"),
                "display_name": row.get("display_name"),
                "status": row.get("status"),
                "domain_id": row.get("domain_id"),
                "metadata": row.get("metadata"),
                "created_at": row.get("created_at").isoformat() if row.get("created_at") else None,
                "updated_at": row.get("updated_at").isoformat() if row.get("updated_at") else None,
            }
        )
    return TenantsResponse(tenants=payload, limit=limit)


@app.patch(
    "/tenants/{tenant_id}",
    response_model=TenantResponse,
    tags=["admin"],
    summary="Update a tenant",
    description="Update tenant display_name, status, or metadata.",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "rename": {
                            "summary": "Update display name",
                            "value": {"display_name": "HPCL LPG - South"},
                        }
                        ,
                        "domain_only": {
                            "summary": "Update domain only",
                            "value": {"domain_id": "lpg_production_distribution"},
                        }
                    }
                }
            }
        },
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "updated": {
                                "summary": "Tenant updated",
                                "value": {
                                    "tenant_id": "VC_101",
                                    "display_name": "HPCL LPG - South",
                                    "status": "active",
                                    "domain_id": "lpg_production_distribution",
                                },
                            }
                        }
                    }
                }
            }
        },
    },
)
def update_tenant_api(tenant_id: str, payload: TenantUpdateRequest) -> TenantResponse:
    row = update_tenant(
        settings,
        tenant_id=tenant_id,
        display_name=payload.display_name,
        status=payload.status,
        metadata=payload.metadata,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Tenant not found")
    if payload.domain_id:
        upsert_tenant_domain(settings, tenant_id, payload.domain_id)
    domain_row = get_tenant_domain(settings, tenant_id)
    return TenantResponse(
        tenant_id=row.get("tenant_id") or tenant_id,
        display_name=row.get("display_name"),
        status=row.get("status") or "active",
        domain_id=domain_row.get("domain_id") if domain_row else None,
        metadata=row.get("metadata"),
        created_at=row.get("created_at").isoformat() if row.get("created_at") else None,
        updated_at=row.get("updated_at").isoformat() if row.get("updated_at") else None,
    )


@app.delete(
    "/tenants/{tenant_id}",
    tags=["admin"],
    summary="Delete a tenant",
    description="Delete tenant registry entry and default domain mapping. Optionally purge tenant data.",
    openapi_extra={
        "parameters": [
            {
                "name": "purge",
                "in": "query",
                "required": False,
                "schema": {"type": "boolean", "default": False},
                "description": "When true, purge all tenant data across tables.",
            }
        ],
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "deleted": {
                                "summary": "Tenant deleted",
                                "value": {"ok": True, "tenant_id": "VC_101", "purged": False},
                            }
                        }
                    }
                }
            }
        }
    },
)
def delete_tenant_api(tenant_id: str, purge: bool = False) -> dict:
    purged_tables = None
    if purge:
        purged_tables = purge_tenant_data(settings, tenant_id, dry_run=False)
    delete_tenant(settings, tenant_id)
    return {"ok": True, "tenant_id": tenant_id, "purged": purge, "tables": purged_tables}


@app.post(
    "/tenant/domain",
    tags=["admin"],
    summary="Set tenant domain",
    description="Persist the active domain for a tenant.",
)
def set_tenant_domain(payload: dict) -> dict:
    tenant_id = payload.get("tenant_id")
    domain_id = payload.get("domain_id")
    if not tenant_id or not domain_id:
        raise HTTPException(status_code=400, detail="tenant_id and domain_id are required")
    upsert_tenant_domain(settings, tenant_id, domain_id)
    return {"ok": True}


@app.get(
    "/tenant/domain",
    tags=["admin"],
    summary="Get tenant domain",
    description="Fetch the active domain for a tenant.",
)
def get_tenant_domain_api(tenant_id: str) -> dict:
    row = get_tenant_domain(settings, tenant_id)
    if not row:
        raise HTTPException(status_code=404, detail="Tenant domain not found")
    return row


@app.post(
    "/tenant/purge",
    tags=["admin"],
    summary="Purge tenant data",
    description="Delete all rows in public tables that contain tenant_id.",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "dry_run": {
                            "summary": "Preview rows that would be deleted",
                            "value": {"tenant_id": "DEBUG_LPG_001", "dry_run": True},
                        },
                        "purge_confirmed": {
                            "summary": "Purge tenant data",
                            "value": {"tenant_id": "DEBUG_LPG_001", "confirm": True, "dry_run": False},
                        },
                    }
                }
            }
        },
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "result": {
                                "summary": "Purge results by table",
                                "value": {
                                    "ok": True,
                                    "dry_run": False,
                                    "tenant_id": "DEBUG_LPG_001",
                                    "tables": [
                                        {"table": "quantyx_agent_runs", "rows": 1},
                                        {"table": "quantyx_agent_run_events", "rows": 120},
                                        {"table": "quantyx_workspace_messages", "rows": 42},
                                    ],
                                },
                            }
                        }
                    }
                }
            }
        },
    },
)
def purge_tenant(payload: dict) -> dict:
    tenant_id = payload.get("tenant_id")
    confirm = payload.get("confirm")
    dry_run = bool(payload.get("dry_run"))
    if not tenant_id:
        raise HTTPException(status_code=400, detail="tenant_id is required")
    if not dry_run and confirm is not True:
        raise HTTPException(status_code=400, detail="confirm=true is required to purge")
    results = purge_tenant_data(settings, tenant_id, dry_run=dry_run)
    return {"ok": True, "dry_run": dry_run, "tenant_id": tenant_id, "tables": results}


@app.post(
    "/tenant/scope",
    response_model=dict,
    tags=["admin"],
    summary="Set tenant scope",
    description="Persist the active connection scope for a tenant.",
)
def set_tenant_scope(payload: TenantScopeUpsertRequest) -> dict:
    domain_id = _resolve_domain_id(payload.tenant_id, payload.domain_id)
    upsert_tenant_scope(
        settings,
        tenant_id=payload.tenant_id,
        domain_id=domain_id,
        connection_id=payload.connection_id,
        database_name=payload.database,
        schema_name=payload.schema_name,
        tables=payload.tables,
    )
    return {"ok": True}


@app.get(
    "/tenant/scope",
    response_model=TenantScopeResponse,
    tags=["admin"],
    summary="Get tenant scope",
    description="Fetch the active connection scope for a tenant.",
)
def get_tenant_scope_api(tenant_id: str, domain_id: str | None = None) -> TenantScopeResponse:
    resolved_domain = _resolve_domain_id(tenant_id, domain_id)
    row = get_tenant_scope(settings, tenant_id, resolved_domain)
    if not row:
        raise HTTPException(status_code=404, detail="Tenant scope not found")
    return TenantScopeResponse(
        tenant_id=row.get("tenant_id"),
        domain_id=row.get("domain_id"),
        connection_id=row.get("connection_id"),
        database=row.get("database_name"),
        schema_name=row.get("schema_name"),
        tables=row.get("tables"),
        status=row.get("status"),
    )


@app.get(
    "/metrics",
    response_model=MetricsResponse,
    tags=["explore"],
    summary="List metrics",
    description="Return tenant-scoped metrics from the registry.",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "metrics_list": {
                                "summary": "Metric list",
                                "value": {
                                    "metrics": [
                                        {
                                            "metric_name": "production_mt",
                                            "description": "Total LPG production in metric tonnes",
                                            "type": "sum",
                                            "sql": "{{ ref('fact_lpg_plant_operations') }}.production_19kg",
                                            "grain": "day",
                                            "dimensions": ["region", "sap_id"],
                                            "tables": ["fact_lpg_plant_operations"],
                                            "status": "certified",
                                            "owner": "analytics@company.com",
                                            "version": "v1",
                                            "semantic_metadata": {
                                                "family_name": "total",
                                                "family_role": "production",
                                                "derivation_method": "direct_column",
                                            },
                                        }
                                    ],
                                    "limit": 200,
                                    "cursor": None,
                                    "next_cursor": "c2FsZXNfdnNfdGFyZ2V0X2FjaGlldmVtZW50X3BjdA==",
                                },
                            }
                        }
                    }
                }
            }
        }
    },
)
def metrics(
    tenant_id: str,
    limit: int = 200,
    cursor: str | None = None,
) -> MetricsResponse:
    domain_id = _resolve_domain_id(tenant_id, None)
    connection_id, database, schema, _ = _resolve_scope_values(
        tenant_id,
        domain_id,
    )
    contract = get_active_semantic_contract(settings, tenant_id, domain_id)
    contract_metrics = {}
    if contract:
        payload = contract.get("payload") or {}
        for item in payload.get("metric_definitions", []) or []:
            name = item.get("metric_name")
            if name:
                contract_metrics[name] = item
    payload = []
    metrics_rows = fetch_registry_metrics(
        settings,
        tenant_id=tenant_id,
        domain_id=domain_id,
        connection_id=connection_id,
        database_name=database,
        schema_name=schema,
        include_all_statuses=True,
    )
    for row in metrics_rows:
        table_name = row.get("dataset_id") or row.get("source_model")
        tables = [table_name] if table_name else []
        payload.append(
            {
                "metric_id": row.get("metric_id"),
                "metric_name": row.get("metric_name"),
                "description": row.get("description"),
                "type": row.get("type"),
                "sql": row.get("sql"),
                "grain": row.get("grain"),
                "dimensions": row.get("dimensions"),
                "tables": tables,
                "status": row.get("lifecycle_status"),
                "lifecycle_status": row.get("lifecycle_status"),
                "source_type": row.get("source_type"),
                "source_run_id": row.get("source_run_id"),
                "artifact_key": row.get("artifact_key"),
                "version_no": row.get("version_no"),
                "is_current": row.get("is_current"),
                "owner": row.get("owner"),
                "version": row.get("version"),
                "semantic_metadata": row.get("semantic_metadata"),
                "definition": contract_metrics.get(row.get("metric_name"), {}).get("definition"),
                "freshness": contract_metrics.get(row.get("metric_name"), {}).get("freshness"),
            }
        )
    page, next_cursor = _paginate_list(payload, cursor, limit, key_fn=lambda item: item["metric_name"])
    return MetricsResponse(metrics=page, limit=limit, cursor=cursor, next_cursor=next_cursor)


@app.get(
    "/metrics/all",
    response_model=dict,
    tags=["explore"],
    summary="List metrics across tenant scope",
    description="Return all tenant-scoped metrics grouped by resolved scope.",
)
def metrics_all(tenant_id: str) -> dict:
    domain_id = _resolve_domain_id(tenant_id, None)
    metrics_rows = fetch_registry_metrics(
        settings,
        tenant_id=tenant_id,
        domain_id=domain_id,
        include_all_statuses=True,
    )
    grouped: dict[tuple[str, str, str], dict] = {}
    for row in metrics_rows:
        key = (row.get("connection_id"), row.get("database_name"), row.get("schema_name"))
        grouped.setdefault(
            key,
            {
                "metrics": [],
            },
        )
        table_name = row.get("dataset_id") or row.get("source_model")
        tables = [table_name] if table_name else []
        grouped[key]["metrics"].append(
            {
                "metric_id": row.get("metric_id"),
                "metric_name": row.get("metric_name"),
                "description": row.get("description"),
                "type": row.get("type"),
                "sql": row.get("sql"),
                "grain": row.get("grain"),
                "dimensions": row.get("dimensions"),
                "tables": tables,
                "status": row.get("lifecycle_status"),
                "lifecycle_status": row.get("lifecycle_status"),
                "source_type": row.get("source_type"),
                "source_run_id": row.get("source_run_id"),
                "artifact_key": row.get("artifact_key"),
                "version_no": row.get("version_no"),
                "is_current": row.get("is_current"),
                "semantic_metadata": row.get("semantic_metadata"),
            }
        )
    return {"connections": list(grouped.values())}


@app.get(
    "/datasets",
    response_model=DatasetsResponse,
    tags=["explore"],
    summary="List datasets",
    description="Return datasets defined in the selected domain pack, scoped by tenant scope.",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "datasets": {
                                "summary": "Dataset list",
                                "value": {
                                    "datasets": [
                                        {
                                            "name": "lpg_plant_operations",
                                            "source_model": "fact_lpg_plant_operations",
                                            "description": "LPG plant operations with production and process metrics",
                                        }
                                    ],
                                    "limit": 200,
                                    "cursor": None,
                                    "next_cursor": "aW5kdXN0cnlfcGVyZm9ybWFuY2U=",
                                },
                            }
                        }
                    }
                }
            }
        },
    },
)
def datasets(
    tenant_id: str,
    limit: int = 200,
    cursor: str | None = None,
) -> DatasetsResponse:
    domain_id = _resolve_domain_id(tenant_id, None)
    connection_id, database, schema, _ = _resolve_scope_values(
        tenant_id,
        domain_id,
    )
    contract = get_active_semantic_contract(settings, tenant_id, domain_id)
    contract_datasets = {}
    if contract:
        payload = contract.get("payload") or {}
        for item in payload.get("dataset_definitions", []) or []:
            name = item.get("name")
            if name:
                contract_datasets[name] = item
    pack = load_pack(f"packs/{domain_id}")
    datasets_list = pack.get("datasets", {}).get("datasets", []) or []
    datasets_list = _filter_by_model_attr(datasets_list, schema, key="source_model", attr="schema")
    datasets_list = _filter_by_model_attr(datasets_list, database, key="source_model", attr="database")
    enriched = []
    for item in datasets_list:
        overlay = contract_datasets.get(item.get("name"), {})
        enriched.append(
            {
                **item,
                "owner": overlay.get("owner"),
                "refresh_frequency": overlay.get("refresh_frequency"),
                "definition": overlay.get("definition") or overlay.get("description"),
            }
        )
    page, next_cursor = _paginate_list(enriched, cursor, limit, key_fn=lambda item: item["name"])
    return DatasetsResponse(datasets=page, limit=limit, cursor=cursor, next_cursor=next_cursor)


@app.get(
    "/dimensions",
    response_model=DimensionsResponse,
    tags=["explore"],
    summary="List dimensions",
    description="Return dimensions from the metric catalog, scoped by tenant scope.",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "dimensions": {
                                "summary": "Dimension list",
                                "value": {
                                    "dimensions": [
                                        {
                                            "name": "region",
                                            "description": "Sales region",
                                            "data_type": "string",
                                            "sql": "{{ ref('fact_lpg_plant_operations') }}.region",
                                        }
                                    ]
                                },
                            }
                        }
                    }
                }
            }
        }
    },
)
def dimensions(tenant_id: str) -> DimensionsResponse:
    domain_id = _resolve_domain_id(tenant_id, None)
    _, database, schema, _ = _resolve_scope_values(
        tenant_id,
        domain_id,
    )
    payload = [
        {
            "name": dim.name,
            "description": dim.description,
            "data_type": dim.data_type,
            "sql": dim.sql,
        }
        for dim in catalog.dimensions.values()
    ]
    if schema or database:
        schema_map = _model_schema_map()
        database_map = _model_database_map()
        filtered = []
        for item in payload:
            match = re.search(r"\{\{\s*ref\('(?P<name>[^']+)'\)\s*\}\}", item["sql"])
            if not match:
                filtered.append(item)
                continue
            model_name = match.group("name")
            if schema and schema_map.get(model_name) != schema:
                continue
            if database and database_map.get(model_name) != database:
                continue
            filtered.append(item)
        payload = filtered
    return DimensionsResponse(dimensions=payload)


@app.get(
    "/policies",
    response_model=PoliciesResponse,
    tags=["governance"],
    summary="List policies",
    description="Return policy rules from the domain pack.",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "policies": {
                                "summary": "Policy list",
                                "value": {
                                    "policies": [
                                        {
                                            "policy_id": "lpg_region_filter",
                                            "description": "Restrict LPG production queries to tenant regions",
                                        }
                                    ]
                                },
                            }
                        }
                    }
                }
            }
        },
    },
)
def policies(tenant_id: str) -> PoliciesResponse:
    domain_id = _resolve_domain_id(tenant_id, None)
    pack = load_pack(f"packs/{domain_id}")
    policies_list = pack.get("policies", {}).get("policies", []) or []
    return PoliciesResponse(policies=policies_list)


@app.get(
    "/governance/lineage",
    response_model=LineageResponse,
    tags=["governance"],
    summary="Metric lineage",
    description="Return metric to dataset and dbt model lineage.",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "lineage": {
                                "summary": "Lineage list",
                                "value": {
                                    "lineage": [
                                        {
                                            "metric_name": "production_mt",
                                            "dataset": "fact_lpg_plant_operations",
                                            "dbt_model": "fact_lpg_plant_operations",
                                        }
                                    ]
                                },
                            }
                        }
                    }
                }
            }
        },
    },
)
def governance_lineage(metric_name: str | None = None) -> LineageResponse:
    lineage = build_lineage(catalog, settings)
    if metric_name:
        lineage = [entry for entry in lineage if entry.get("metric_name") == metric_name]
    return LineageResponse(lineage=lineage)


def _canvas_node_id(node_type: str, payload: dict) -> str | None:
    if node_type == "dimension":
        return payload.get("name") or payload.get("dimension_id")
    if node_type == "fact":
        return payload.get("table_name") or payload.get("fact_id")
    if node_type == "metric":
        return payload.get("metric_name") or payload.get("metric_id")
    if node_type == "root":
        return payload.get("id") or payload.get("root_node_id")
    return None


def _persist_canvas_graph(
    tenant_id: str,
    domain_id: str,
    canvas_id: str,
    name: str,
    description: str | None,
    root_node_id: str | None,
    status: str,
    idempotency_key: str | None,
    nodes: list[dict],
    edges: list[dict],
) -> None:
    graph_json = {"nodes": nodes, "edges": edges}
    sql_canvas = """
        INSERT INTO public.quantyx_canvases (
          canvas_id, tenant_id, domain_id, name, description, graph_json, root_node_id, status, idempotency_key, created_at, updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, now(), now())
        ON CONFLICT (canvas_id)
        DO UPDATE SET
          name = EXCLUDED.name,
          description = EXCLUDED.description,
          graph_json = EXCLUDED.graph_json,
          root_node_id = EXCLUDED.root_node_id,
          status = EXCLUDED.status,
          idempotency_key = EXCLUDED.idempotency_key,
          updated_at = now()
    """
    execute_non_query(
        settings,
        sql_canvas,
        [
            canvas_id,
            tenant_id,
            domain_id,
            name,
            description,
            json.dumps(graph_json),
            root_node_id,
            status,
            idempotency_key,
        ],
    )

    execute_non_query(settings, "DELETE FROM public.quantyx_canvas_nodes WHERE canvas_id = %s", [canvas_id])
    execute_non_query(settings, "DELETE FROM public.quantyx_canvas_edges WHERE canvas_id = %s", [canvas_id])

    for node in nodes:
        node_type = node.get("type")
        node_id = node.get("id")
        if not node_type or not node_id:
            continue
        execute_non_query(
            settings,
            """
            INSERT INTO public.quantyx_canvas_nodes (canvas_id, node_type, node_id, created_at)
            VALUES (%s, %s, %s, now())
            ON CONFLICT DO NOTHING
            """,
            [canvas_id, node_type, node_id],
        )

    for edge in edges:
        execute_non_query(
            settings,
            """
            INSERT INTO public.quantyx_canvas_edges (
              canvas_id, from_type, from_id, to_type, to_id, edge_type, source, confidence, created_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now())
            ON CONFLICT DO NOTHING
            """,
            [
                canvas_id,
                edge.get("from_type"),
                edge.get("from"),
                edge.get("to_type"),
                edge.get("to"),
                edge.get("edge_type"),
                edge.get("source", "manual"),
                edge.get("confidence"),
            ],
        )

@app.get(
    "/lineage",
    tags=["explore"],
    summary="Semantic canvas lineage",
    description="Return nodes and edges for the semantic canvas, derived from registries.",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "canvas": {
                                "summary": "Canvas lineage",
                                "value": {
                                    "nodes": [
                                        {"id": "dim_plant", "type": "dimension"},
                                        {"id": "fact_lpg_plant_operations", "type": "fact"},
                                        {"id": "production_mt", "type": "metric"},
                                    ],
                                    "edges": [
                                        {"from": "dim_plant", "to": "fact_lpg_plant_operations", "edge_type": "dimension_to_fact"},
                                        {"from": "fact_lpg_plant_operations", "to": "production_mt", "edge_type": "fact_to_metric"},
                                    ],
                                },
                            }
                        }
                    }
                }
            }
        }
    },
)
def semantic_lineage(tenant_id: str) -> dict:
    domain_id = _resolve_domain_id(tenant_id, None)
    canvas_nodes, canvas_edges = _get_canvas_nodes_and_edges(tenant_id, domain_id)
    if canvas_nodes or canvas_edges:
        return {"nodes": canvas_nodes, "edges": canvas_edges}
    connection_id, database, schema, _ = _resolve_scope_values(tenant_id, domain_id)
    facts = list_facts(settings, tenant_id, domain_id, connection_id, database, schema)
    dimensions = list_dimensions(settings, tenant_id, domain_id, connection_id, database, schema)
    metrics_rows = fetch_registry_metrics(
        settings,
        tenant_id=tenant_id,
        domain_id=domain_id,
        connection_id=connection_id,
        database_name=database,
        schema_name=schema,
        include_all_statuses=True,
    )
    return _build_canvas_lineage(facts, dimensions, metrics_rows)


def _validate_canvas_edges(nodes: list[dict], edges: list[dict]) -> None:
    node_types = {node.get("id"): node.get("type") for node in nodes if node.get("id")}
    node_ids = set(node_types.keys())
    valid_types = {"dimension_to_fact", "fact_to_metric", "root_to_dimension"}
    for edge in edges:
        edge_type = edge.get("edge_type")
        from_id = edge.get("from")
        to_id = edge.get("to")
        if edge_type not in valid_types:
            raise HTTPException(status_code=400, detail=f"Invalid edge_type: {edge_type}")
        if from_id not in node_ids or to_id not in node_ids:
            raise HTTPException(status_code=400, detail="Edge references unknown node id")
        from_type = node_types.get(from_id)
        to_type = node_types.get(to_id)
        if edge_type == "dimension_to_fact" and (from_type != "dimension" or to_type != "fact"):
            raise HTTPException(status_code=400, detail="dimension_to_fact edge must connect dimension to fact")
        if edge_type == "fact_to_metric" and (from_type != "fact" or to_type != "metric"):
            raise HTTPException(status_code=400, detail="fact_to_metric edge must connect fact to metric")
        if edge_type == "root_to_dimension" and (from_type != "root" or to_type != "dimension"):
            raise HTTPException(status_code=400, detail="root_to_dimension edge must connect root to dimension")


@app.post(
    "/canvas/save",
    response_model=CanvasSaveResponse,
    tags=["canvas"],
    summary="Save semantic canvas",
    description="Persist canvas nodes/edges and upsert semantic objects.",
)
def save_canvas(payload: CanvasSaveRequest) -> CanvasSaveResponse:
    domain_id = _resolve_domain_id(payload.tenant_id, payload.domain_id)
    connection_id, database_name, schema_name, _ = _resolve_scope_values(payload.tenant_id, domain_id)

    if payload.idempotency_key:
        rows = run_query(
            settings,
            """
            SELECT canvas_id
              FROM public.quantyx_canvases
             WHERE tenant_id = %s AND domain_id = %s AND idempotency_key = %s
             LIMIT 1
            """,
            [payload.tenant_id, domain_id, payload.idempotency_key],
        )
        if rows:
            return CanvasSaveResponse(canvas_id=rows[0]["canvas_id"], status="saved")

    nodes = []
    node_alias_to_id: dict[str, str] = {}
    fact_grains = _fact_grain_map(payload.tenant_id, domain_id, connection_id, database_name, schema_name)
    for node in payload.nodes:
        node_type = node.type
        node_payload = dict(node.payload or {})
        node_id = _canvas_node_id(node_type, node_payload)
        if node_type == "dimension":
            if not node_payload.get("name") and node_id:
                node_payload["name"] = node_id
            _validate_dimension_payload(node_payload)
            dimension_id = upsert_dimension(
                settings,
                {
                    "dimension_id": node_payload.get("dimension_id"),
                    "tenant_id": payload.tenant_id,
                    "domain_id": domain_id,
                    "connection_id": connection_id,
                    "database_name": database_name,
                    "schema_name": schema_name,
                    "name": node_payload.get("name"),
                    "keys": node_payload.get("keys", []),
                    "attributes": node_payload.get("attributes", []),
                    "description": node_payload.get("description"),
                    "status": node_payload.get("status", "live"),
                },
            )
            for alias in (node_payload.get("name"), node_payload.get("dimension_id"), dimension_id):
                if alias:
                    node_alias_to_id[str(alias)] = dimension_id
            nodes.append({"id": dimension_id, "type": "dimension", "label": node_payload.get("name")})
        elif node_type == "fact":
            if not node_payload.get("table_name") and node_id:
                node_payload["table_name"] = node_id
            _validate_fact_payload(node_payload)
            fact_id = upsert_fact(
                settings,
                {
                    "fact_id": node_payload.get("fact_id"),
                    "tenant_id": payload.tenant_id,
                    "domain_id": domain_id,
                    "connection_id": connection_id,
                    "database_name": database_name,
                    "schema_name": schema_name,
                    "table_name": node_payload.get("table_name"),
                    "grain": node_payload.get("grain"),
                    "time_column": node_payload.get("time_column"),
                    "measures": node_payload.get("measures", []),
                    "dimensions": node_payload.get("dimensions", []),
                    "description": node_payload.get("description"),
                    "status": node_payload.get("status", "live"),
                },
            )
            for alias in (node_payload.get("table_name"), node_payload.get("fact_id"), fact_id):
                if alias:
                    node_alias_to_id[str(alias)] = fact_id
            if node_payload.get("table_name"):
                fact_grains[str(node_payload.get("table_name"))] = node_payload.get("grain")
            nodes.append({"id": fact_id, "type": "fact", "label": node_payload.get("table_name")})
        elif node_type == "metric":
            if not node_payload.get("metric_name") and node_id:
                node_payload["metric_name"] = node_id
            _validate_metric_payload(node_payload, fact_grains)
            metric_id = upsert_metric(
                settings,
                {
                    "metric_id": node_payload.get("metric_id"),
                    "tenant_id": payload.tenant_id,
                    "domain_id": domain_id,
                    "connection_id": connection_id,
                    "database": database_name,
                    "schema": schema_name,
                    "metric_name": node_payload.get("metric_name"),
                    "display_name": node_payload.get("display_name"),
                    "description": node_payload.get("description"),
                    "type": node_payload.get("type"),
                    "sql": node_payload.get("sql"),
                    "grain": node_payload.get("grain"),
                    "dimensions": node_payload.get("dimensions", []),
                    "unit": node_payload.get("unit"),
                    "status": node_payload.get("status", "suggested"),
                    "dataset_id": node_payload.get("dataset_id"),
                    "source_model": node_payload.get("source_model"),
                    "source_schema": node_payload.get("source_schema"),
                    "owner": node_payload.get("owner"),
                    "version": node_payload.get("version"),
                },
            )
            for alias in (node_payload.get("metric_name"), node_payload.get("metric_id"), metric_id):
                if alias:
                    node_alias_to_id[str(alias)] = metric_id
            nodes.append({"id": metric_id, "type": "metric", "label": node_payload.get("metric_name")})
        elif node_type == "root":
            root_id = node_payload.get("id") or node_payload.get("root_node_id") or node_id
            if not root_id:
                continue
            node_alias_to_id[str(root_id)] = str(root_id)
            nodes.append({"id": str(root_id), "type": "root"})
        else:
            continue

    edges = []
    for edge in payload.edges:
        from_id = node_alias_to_id.get(edge.from_id, edge.from_id)
        to_id = node_alias_to_id.get(edge.to_id, edge.to_id)
        edge_type = edge.edge_type
        if not from_id or not to_id or not edge_type:
            continue
        if edge_type == "dimension_to_fact":
            from_type = "dimension"
            to_type = "fact"
        elif edge_type == "fact_to_metric":
            from_type = "fact"
            to_type = "metric"
        elif edge_type == "root_to_dimension":
            from_type = "root"
            to_type = "dimension"
            if from_id not in {node.get("id") for node in nodes}:
                nodes.append({"id": from_id, "type": "root"})
        else:
            continue
        edges.append(
            {
                "from": from_id,
                "to": to_id,
                "edge_type": edge_type,
                "source": edge.source or "manual",
                "confidence": edge.confidence,
                "from_type": from_type,
                "to_type": to_type,
            }
        )

    canvas_id = f"canvas_{uuid.uuid4().hex[:10]}"
    _validate_canvas_edges(nodes, edges)
    _persist_canvas_graph(
        tenant_id=payload.tenant_id,
        domain_id=domain_id,
        canvas_id=canvas_id,
        name=payload.name,
        description=payload.description,
        root_node_id=payload.root_node_id,
        status=payload.status or "live",
        idempotency_key=payload.idempotency_key,
        nodes=nodes,
        edges=edges,
    )
    return CanvasSaveResponse(canvas_id=canvas_id, status="saved")


@app.put(
    "/canvas/{canvas_id}",
    response_model=CanvasSaveResponse,
    tags=["canvas"],
    summary="Update semantic canvas",
    description="Replace canvas graph and resync nodes/edges.",
)
def update_canvas(canvas_id: str, payload: CanvasSaveRequest) -> CanvasSaveResponse:
    domain_id = _resolve_domain_id(payload.tenant_id, payload.domain_id)
    _ensure_canvas_owned(canvas_id, payload.tenant_id, domain_id)
    connection_id, database_name, schema_name, _ = _resolve_scope_values(payload.tenant_id, domain_id)

    nodes = []
    node_alias_to_id: dict[str, str] = {}
    fact_grains = _fact_grain_map(payload.tenant_id, domain_id, connection_id, database_name, schema_name)
    for node in payload.nodes:
        node_type = node.type
        node_payload = dict(node.payload or {})
        node_id = _canvas_node_id(node_type, node_payload)
        if node_type == "dimension":
            if not node_payload.get("name") and node_id:
                node_payload["name"] = node_id
            _validate_dimension_payload(node_payload)
            dimension_id = upsert_dimension(
                settings,
                {
                    "dimension_id": node_payload.get("dimension_id"),
                    "tenant_id": payload.tenant_id,
                    "domain_id": domain_id,
                    "connection_id": connection_id,
                    "database_name": database_name,
                    "schema_name": schema_name,
                    "name": node_payload.get("name"),
                    "keys": node_payload.get("keys", []),
                    "attributes": node_payload.get("attributes", []),
                    "description": node_payload.get("description"),
                    "status": node_payload.get("status", "live"),
                },
            )
            for alias in (node_payload.get("name"), node_payload.get("dimension_id"), dimension_id):
                if alias:
                    node_alias_to_id[str(alias)] = dimension_id
            nodes.append({"id": dimension_id, "type": "dimension", "label": node_payload.get("name")})
        elif node_type == "fact":
            if not node_payload.get("table_name") and node_id:
                node_payload["table_name"] = node_id
            _validate_fact_payload(node_payload)
            fact_id = upsert_fact(
                settings,
                {
                    "fact_id": node_payload.get("fact_id"),
                    "tenant_id": payload.tenant_id,
                    "domain_id": domain_id,
                    "connection_id": connection_id,
                    "database_name": database_name,
                    "schema_name": schema_name,
                    "table_name": node_payload.get("table_name"),
                    "grain": node_payload.get("grain"),
                    "time_column": node_payload.get("time_column"),
                    "measures": node_payload.get("measures", []),
                    "dimensions": node_payload.get("dimensions", []),
                    "description": node_payload.get("description"),
                    "status": node_payload.get("status", "live"),
                },
            )
            for alias in (node_payload.get("table_name"), node_payload.get("fact_id"), fact_id):
                if alias:
                    node_alias_to_id[str(alias)] = fact_id
            if node_payload.get("table_name"):
                fact_grains[str(node_payload.get("table_name"))] = node_payload.get("grain")
            nodes.append({"id": fact_id, "type": "fact", "label": node_payload.get("table_name")})
        elif node_type == "metric":
            if not node_payload.get("metric_name") and node_id:
                node_payload["metric_name"] = node_id
            _validate_metric_payload(node_payload, fact_grains)
            metric_id = upsert_metric(
                settings,
                {
                    "metric_id": node_payload.get("metric_id"),
                    "tenant_id": payload.tenant_id,
                    "domain_id": domain_id,
                    "connection_id": connection_id,
                    "database": database_name,
                    "schema": schema_name,
                    "metric_name": node_payload.get("metric_name"),
                    "display_name": node_payload.get("display_name"),
                    "description": node_payload.get("description"),
                    "type": node_payload.get("type"),
                    "sql": node_payload.get("sql"),
                    "grain": node_payload.get("grain"),
                    "dimensions": node_payload.get("dimensions", []),
                    "unit": node_payload.get("unit"),
                    "status": node_payload.get("status", "suggested"),
                    "dataset_id": node_payload.get("dataset_id"),
                    "source_model": node_payload.get("source_model"),
                    "source_schema": node_payload.get("source_schema"),
                    "owner": node_payload.get("owner"),
                    "version": node_payload.get("version"),
                },
            )
            for alias in (node_payload.get("metric_name"), node_payload.get("metric_id"), metric_id):
                if alias:
                    node_alias_to_id[str(alias)] = metric_id
            nodes.append({"id": metric_id, "type": "metric", "label": node_payload.get("metric_name")})
        elif node_type == "root":
            root_id = node_payload.get("id") or node_payload.get("root_node_id") or node_id
            if not root_id:
                continue
            node_alias_to_id[str(root_id)] = str(root_id)
            nodes.append({"id": str(root_id), "type": "root"})
        else:
            continue

    edges = []
    for edge in payload.edges:
        from_id = node_alias_to_id.get(edge.from_id, edge.from_id)
        to_id = node_alias_to_id.get(edge.to_id, edge.to_id)
        edge_type = edge.edge_type
        if not from_id or not to_id or not edge_type:
            continue
        if edge_type == "dimension_to_fact":
            from_type = "dimension"
            to_type = "fact"
        elif edge_type == "fact_to_metric":
            from_type = "fact"
            to_type = "metric"
        elif edge_type == "root_to_dimension":
            from_type = "root"
            to_type = "dimension"
            if from_id not in {node.get("id") for node in nodes}:
                nodes.append({"id": from_id, "type": "root"})
        else:
            continue
        edges.append(
            {
                "from": from_id,
                "to": to_id,
                "edge_type": edge_type,
                "source": edge.source or "manual",
                "confidence": edge.confidence,
                "from_type": from_type,
                "to_type": to_type,
            }
        )

    _validate_canvas_edges(nodes, edges)
    _persist_canvas_graph(
        tenant_id=payload.tenant_id,
        domain_id=domain_id,
        canvas_id=canvas_id,
        name=payload.name,
        description=payload.description,
        root_node_id=payload.root_node_id,
        status=payload.status or "live",
        idempotency_key=payload.idempotency_key,
        nodes=nodes,
        edges=edges,
    )
    return CanvasSaveResponse(canvas_id=canvas_id, status="updated")


@app.get(
    "/canvas",
    response_model=CanvasListResponse,
    tags=["canvas"],
    summary="List canvases",
)
def list_canvases(tenant_id: str) -> CanvasListResponse:
    domain_id = _resolve_domain_id(tenant_id, None)
    sql = """
        SELECT canvas_id, tenant_id, domain_id, name, description, root_node_id, status, created_at, updated_at
          FROM public.quantyx_canvases
         WHERE tenant_id = %s AND domain_id = %s
         ORDER BY created_at DESC
    """
    rows = run_query(settings, sql, [tenant_id, domain_id])
    return CanvasListResponse(canvases=rows)


@app.get(
    "/canvas/{canvas_id}",
    response_model=CanvasDetailResponse,
    tags=["canvas"],
    summary="Get canvas",
)
def get_canvas(canvas_id: str, tenant_id: str) -> CanvasDetailResponse:
    domain_id = _resolve_domain_id(tenant_id, None)
    sql = """
        SELECT canvas_id, tenant_id, domain_id, name, description, graph_json, root_node_id, status, created_at, updated_at
          FROM public.quantyx_canvases
         WHERE canvas_id = %s AND tenant_id = %s AND domain_id = %s
         LIMIT 1
    """
    rows = run_query(settings, sql, [canvas_id, tenant_id, domain_id])
    if not rows:
        raise HTTPException(status_code=404, detail="Canvas not found")
    return CanvasDetailResponse(**rows[0])


@app.get(
    "/canvas/tree",
    response_model=CanvasTreeResponse,
    tags=["canvas"],
    summary="Tenant rooted canvas tree",
)
def get_canvas_tree(tenant_id: str) -> CanvasTreeResponse:
    domain_id = _resolve_domain_id(tenant_id, None)
    root_id = "tenant_root"
    nodes, edges = _get_canvas_nodes_and_edges(tenant_id, domain_id)
    if not nodes and not edges:
        connection_id, database, schema, _ = _resolve_scope_values(tenant_id, domain_id)
        facts = list_facts(settings, tenant_id, domain_id, connection_id, database, schema)
        dimensions = list_dimensions(settings, tenant_id, domain_id, connection_id, database, schema)
        metrics_rows = fetch_registry_metrics(
            settings,
            tenant_id=tenant_id,
            domain_id=domain_id,
            connection_id=connection_id,
            database_name=database,
            schema_name=schema,
            include_all_statuses=True,
        )
        lineage = _build_canvas_lineage(facts, dimensions, metrics_rows)
        nodes = lineage.get("nodes", [])
        edges = lineage.get("edges", [])

    if root_id not in {node.get("id") for node in nodes}:
        nodes = [{"id": root_id, "type": "root"}] + nodes

    edge_keys = {(edge.get("from"), edge.get("to"), edge.get("edge_type")) for edge in edges}
    for node in nodes:
        if node.get("type") != "dimension":
            continue
        root_edge = (root_id, node.get("id"), "root_to_dimension")
        if root_edge in edge_keys:
            continue
        edges.append({"from": root_id, "to": node.get("id"), "edge_type": "root_to_dimension"})
        edge_keys.add(root_edge)
    return CanvasTreeResponse(nodes=nodes, edges=edges)



@app.post(
    "/dbt/manifest/generate",
    response_model=DbtManifestGenerateResponse,
    tags=["admin"],
    summary="Generate dbt manifest",
    description="Run dbt compile and store manifest.json in the database.",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "stored": {
                                "summary": "Manifest stored",
                                "value": {"manifest_id": "manifest_123", "status": "stored"},
                            }
                        }
                    }
                }
            }
        }
    },
)
def generate_dbt_manifest(payload: DbtManifestGenerateRequest) -> DbtManifestGenerateResponse:
    if not payload.tenant_id:
        raise HTTPException(status_code=400, detail="tenant_id is required")
    tenant_id = payload.tenant_id
    domain_id = _resolve_domain_id(tenant_id, payload.domain_id)
    connection_id, _, _, _ = _resolve_scope_values(
        tenant_id,
        domain_id,
    )
    dbt_project_path = payload.dbt_project_path or resolve_dbt_project_dir(tenant_id)
    upsert_tenant_project_dir(settings, tenant_id, domain_id, dbt_project_path)
    try:
        manifest_json = run_dbt_compile(
            settings,
            dbt_project_path=dbt_project_path,
            profile_name=normalize_profile_name(payload.profile_name),
            target_name=payload.target_name,
            profiles_dir=payload.profiles_dir,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    manifest_id = store_manifest(
        settings,
        tenant_id=tenant_id,
        domain_id=domain_id,
        connection_id=connection_id,
        dbt_project_path=dbt_project_path,
        profile_name=payload.profile_name,
        target_name=payload.target_name,
        manifest_json=manifest_json,
    )
    return DbtManifestGenerateResponse(
        manifest_id=manifest_id,
        status="stored",
        tenant_id=tenant_id,
        dbt_project_path=dbt_project_path,
    )


@app.get(
    "/dbt/manifest/latest",
    response_model=DbtManifestLatestResponse,
    tags=["admin"],
    summary="Fetch latest dbt manifest",
    description="Return the latest stored dbt manifest from the database.",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "latest": {
                                "summary": "Latest manifest",
                                "value": {
                                    "manifest_id": "manifest_123",
                                    "tenant_id": "VC_101",
                                    "dbt_project_path": "dbt",
                                    "profile_name": "default",
                                    "target_name": "dev",
                                    "created_at": "2025-02-14T10:00:00Z",
                                    "manifest_json": {"metadata": {"dbt_version": "1.7.0"}},
                                },
                            }
                        }
                    }
                }
            }
        }
    },
)
def get_latest_dbt_manifest(
    tenant_id: str,
) -> DbtManifestLatestResponse:
    domain_id = _resolve_domain_id(tenant_id, None)
    row = load_latest_manifest_row(settings, domain_id=domain_id, tenant_id=tenant_id)
    if not row:
        raise HTTPException(status_code=404, detail="Manifest not found")
    return DbtManifestLatestResponse(
        manifest_id=row["manifest_id"],
        tenant_id=row["tenant_id"],
        domain_id=row["domain_id"],
        dbt_project_path=row["dbt_project_path"],
        profile_name=row["profile_name"],
        target_name=row["target_name"],
        created_at=row["created_at"].isoformat(),
        manifest_json=row["manifest_json"],
    )


@app.post(
    "/dbt/config",
    response_model=DbtConfigResponse,
    tags=["admin"],
    summary="Upsert dbt config",
    description="Store dbt config for a tenant/domain (admin use only).",
)
def upsert_dbt_config_endpoint(payload: DbtConfigUpsertRequest) -> DbtConfigResponse:
    domain_id = _resolve_domain_id(payload.tenant_id, payload.domain_id)
    connection_id, _, _, _ = _resolve_scope_values(
        payload.tenant_id,
        domain_id,
    )
    dbt_project_path = payload.dbt_project_path or resolve_dbt_project_dir(payload.tenant_id)
    profile_name = normalize_profile_name(payload.tenant_id)
    target_name = payload.target_name or settings.dbt_target_name
    profiles_dir = payload.profiles_dir or settings.dbt_profiles_dir
    config_id = upsert_dbt_config(
        settings,
        tenant_id=payload.tenant_id,
        domain_id=domain_id,
        connection_id=connection_id,
        dbt_project_path=dbt_project_path,
        profile_name=profile_name,
        target_name=target_name,
        profiles_dir=profiles_dir,
    )
    return DbtConfigResponse(
        config_id=config_id,
        tenant_id=payload.tenant_id,
        domain_id=domain_id,
        dbt_project_path=dbt_project_path,
        profile_name=profile_name,
        target_name=target_name,
        profiles_dir=profiles_dir,
    )


@app.get(
    "/dbt/config/latest",
    response_model=DbtConfigResponse,
    tags=["admin"],
    summary="Fetch latest dbt config",
    description="Return the latest dbt config for a tenant/domain (admin use only).",
)
def get_latest_dbt_config_endpoint(
    tenant_id: str,
) -> DbtConfigResponse:
    domain_id = _resolve_domain_id(tenant_id, None)
    connection_id, _, _, _ = _resolve_scope_values(
        tenant_id,
        domain_id,
    )
    config = get_latest_dbt_config(settings, tenant_id, domain_id, connection_id)
    if not config:
        raise HTTPException(status_code=404, detail="dbt config not found")
    return DbtConfigResponse(
        config_id=config.get("config_id"),
        tenant_id=config["tenant_id"],
        domain_id=config["domain_id"],
        dbt_project_path=config["dbt_project_path"],
        profile_name=config["profile_name"],
        target_name=config["target_name"],
        profiles_dir=config.get("profiles_dir"),
        created_at=config.get("created_at").isoformat() if config.get("created_at") else None,
        updated_at=config.get("updated_at").isoformat() if config.get("updated_at") else None,
    )


@app.post(
    "/dbt/scaffold",
    response_model=DbtScaffoldResponse,
    tags=["admin"],
    summary="Generate dbt scaffold",
    description="Generate draft dbt models from latest scan results (admin use only).",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "generate_scaffold": {
                            "summary": "Generate scaffold",
                            "value": {
                                "tenant_id": "VC_101",
                                "domain_id": "lpg_production_distribution",
                                "context_id": "ctx_123",
                                "host": "db.company.com",
                                "port": 5432,
                                "user": "readonly_user",
                                "password": "******",
                            },
                        }
                    }
                }
            }
        }
    },
)
def generate_dbt_scaffold(payload: DbtScaffoldRequest) -> DbtScaffoldResponse:
    domain_id = _resolve_domain_id(payload.tenant_id, payload.domain_id)
    connection_id, database, schema, tables = _resolve_scope_values(
        payload.tenant_id,
        domain_id,
    )
    tables = tables or []
    scan_result = load_latest_scan_result(settings, payload.tenant_id, domain_id)
    if not scan_result:
        raise HTTPException(status_code=404, detail="No scan results found for tenant/domain")
    tables = _extract_tables_from_scan(
        scan_result,
        connection_id=connection_id,
        database=database,
        schema=schema,
        tables=tables,
    )
    if not tables:
        raise HTTPException(status_code=400, detail="No matching tables found in latest scan")
    dbt_project_path = ensure_tenant_dbt_project(
        payload.tenant_id,
        template_dir=settings.dbt_project_template,
    )
    context_text = None
    if payload.context_id:
        context_row = get_context(settings, payload.context_id)
        if context_row and context_row.get("raw_text"):
            context_text = context_row.get("raw_text")
    scaffold_payload = build_scaffold_payload(
        settings,
        database=database,
        schema=schema,
        tables=tables,
        context_text=context_text,
        use_llm=True,
    )
    if payload.host and payload.user:
        scaffold_payload["connection"] = {
            "host": payload.host,
            "port": payload.port or 5432,
            "user": payload.user,
            "password": decrypt_password(payload.password or ""),
        }
    write_scaffold_files(dbt_project_path, scaffold_payload)
    scaffold_id = persist_scaffold(
        settings,
        tenant_id=payload.tenant_id,
        domain_id=domain_id,
        connection_id=connection_id,
        database=database,
        schema=schema,
        tables=[t.get("table") for t in tables if t.get("table")],
        context_id=payload.context_id,
        payload=scaffold_payload,
    )
    models = [
        {"name": model["name"], "path": f"models/auto/{model['name']}.sql", "status": model["status"]}
        for model in scaffold_payload.get("models", [])
    ]
    return DbtScaffoldResponse(status="generated", scaffold_id=scaffold_id, models=models)


@app.get(
    "/dbt/scaffold",
    response_model=DbtScaffoldListResponse,
    tags=["admin"],
    summary="List dbt scaffolds",
    description="List generated dbt scaffolds for a tenant/domain (admin use only).",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "scaffolds": {
                                "summary": "Scaffold list",
                                "value": {
                                    "scaffolds": [
                                        {
                                            "scaffold_id": "scaffold_123",
                                            "tables": ["lpg_plant_operations", "lpg_plant_operations_masters"],
                                            "status": "live",
                                            "created_at": "2025-02-14T10:00:00Z",
                                        }
                                    ]
                                },
                            }
                        }
                    }
                }
            }
        }
    },
)
def list_dbt_scaffolds(
    tenant_id: str,
) -> DbtScaffoldListResponse:
    domain_id = _resolve_domain_id(tenant_id, None)
    connection_id, _, _, _ = _resolve_scope_values(
        tenant_id,
        domain_id,
    )
    scaffolds = list_scaffolds(settings, tenant_id, domain_id, connection_id)
    payload = [
        {
            key: value
            for key, value in item.items()
            if key not in {"connection_id", "database_name", "schema_name"}
        }
        for item in scaffolds
    ]
    return DbtScaffoldListResponse(scaffolds=payload)


@app.patch(
    "/dbt/scaffold/{scaffold_id}",
    tags=["admin"],
    summary="Update scaffold",
    description="Update scaffold payload or status (admin use only).",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "reviewed": {
                            "summary": "Mark as reviewed",
                            "value": {"status": "reviewed", "notes": "Reviewed by analyst"},
                        }
                    }
                }
            }
        }
    },
)
def patch_dbt_scaffold(
    scaffold_id: str,
    tenant_id: str,
    payload: DbtScaffoldPatchRequest,
) -> dict:
    domain_id = _resolve_domain_id(tenant_id, None)
    scaffold = get_scaffold(settings, scaffold_id)
    if not scaffold:
        raise HTTPException(status_code=404, detail="Scaffold not found")
    if scaffold["tenant_id"] != tenant_id or scaffold["domain_id"] != domain_id:
        raise HTTPException(status_code=400, detail="Scaffold tenant/domain mismatch")
    update_scaffold(
        settings,
        scaffold_id=scaffold_id,
        status=payload.status,
        payload=payload.payload,
        notes=payload.notes,
    )
    return {"ok": True}


@app.post(
    "/dbt/scaffold/{scaffold_id}/apply",
    tags=["admin"],
    summary="Apply scaffold",
    description="Write reviewed scaffold into dbt project and compile (admin use only).",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "applied": {
                                "summary": "Applied scaffold",
                                "value": {"ok": True, "status": "applied"},
                            }
                        }
                    }
                }
            }
        }
    },
)
def apply_dbt_scaffold(
    scaffold_id: str,
    tenant_id: str,
) -> dict:
    domain_id = _resolve_domain_id(tenant_id, None)
    scaffold = get_scaffold(settings, scaffold_id)
    if not scaffold:
        raise HTTPException(status_code=404, detail="Scaffold not found")
    if scaffold["tenant_id"] != tenant_id or scaffold["domain_id"] != domain_id:
        raise HTTPException(status_code=400, detail="Scaffold tenant/domain mismatch")
    payload = scaffold.get("payload") or {}
    dbt_project_path = ensure_tenant_dbt_project(
        tenant_id,
        template_dir=settings.dbt_project_template,
    )
    write_scaffold_files(dbt_project_path, payload)
    connection = payload.get("connection") or {}
    profiles_dir = None
    if connection.get("host") and connection.get("user"):
        profiles_dir = create_temp_profiles_dir(
            tenant_id=tenant_id,
            target_name=settings.dbt_target_name,
            connection=connection,
            database=scaffold.get("database_name") or settings.db_name,
            schema=scaffold.get("schema_name") or settings.db_schema,
        )
    elif settings.dbt_profiles_dir:
        profiles_dir = settings.dbt_profiles_dir
    else:
        raise HTTPException(status_code=400, detail="No dbt profiles available for compile")
    manifest_json = run_dbt_compile(
        settings,
        dbt_project_path=dbt_project_path,
        profile_name=normalize_profile_name(tenant_id),
        target_name=settings.dbt_target_name,
        profiles_dir=profiles_dir,
    )
    store_manifest(
        settings,
        tenant_id=tenant_id,
        domain_id=domain_id,
        connection_id=scaffold.get("connection_id"),
        dbt_project_path=dbt_project_path,
        profile_name=normalize_profile_name(tenant_id),
        target_name=settings.dbt_target_name,
        manifest_json=manifest_json,
    )
    update_scaffold(settings, scaffold_id=scaffold_id, status="applied")
    return {"ok": True, "status": "applied"}


@app.get(
    "/insights",
    response_model=InsightsResponse,
    tags=["insights"],
    summary="List insights",
    description="Return recent insights for a domain.",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "insights": {
                                "summary": "Insights feed",
                                "value": {
                                    "insights": [
                                        {
                                            "insight_id": "ins_123",
                                            "insight_type": "variance",
                                            "headline": "LPG production decreased 4.2% vs last month",
                                            "severity": "medium",
                                            "confidence": 0.8,
                                        }
                                    ],
                                    "limit": 200,
                                    "cursor": None,
                                    "next_cursor": "aW5zXzEyNA==",
                                },
                            }
                        }
                    }
                }
            }
        },
    },
)
def insights(tenant_id: str, limit: int = 200, cursor: str | None = None) -> InsightsResponse:
    domain_id = _resolve_domain_id(tenant_id, None)
    items = list_insights(settings, domain_id)
    page, next_cursor = _paginate_list(items, cursor, limit, key_fn=lambda item: item["insight_id"])
    return InsightsResponse(insights=page, limit=limit, cursor=cursor, next_cursor=next_cursor)


@app.get(
    "/insights/{insight_id}",
    response_model=InsightDetailResponse,
    tags=["insights"],
    summary="Get an insight",
    description="Return the full insight record.",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "insight_detail": {
                                "summary": "Insight detail",
                                "value": {
                                    "insight": {
                                        "insight_id": "ins_123",
                                        "insight_type": "variance",
                                        "headline": "LPG production decreased 4.2% vs last month",
                                        "severity": "medium",
                                        "confidence": 0.8,
                                        "entity_scope": {"region": "BANGALORE LPG RO"},
                                    }
                                },
                            }
                        }
                    }
                }
            }
        }
    },
)
def insight_detail(insight_id: str) -> InsightDetailResponse:
    insight = get_insight(settings, insight_id)
    if not insight:
        raise HTTPException(status_code=404, detail="Insight not found")
    return InsightDetailResponse(insight=insight)


@app.get(
    "/insights/{insight_id}/details",
    response_model=InsightDetailWithContextResponse,
    tags=["insights"],
    summary="Get insight details",
    description="Return drivers and correlated facts for the selected insight.",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "details": {
                                "summary": "Insight drilldown",
                                "value": {
                                    "insight": {
                                        "insight_id": "ins_123",
                                        "insight_type": "anomaly",
                                        "headline": "production_mt anomaly detected at 2026-02-01",
                                    },
                                    "drivers": [
                                        {
                                            "period": "2026-02-01",
                                            "actual": 1200.5,
                                            "baseline": 1100.2,
                                            "deviation": 100.3,
                                            "z_score": 2.8,
                                        }
                                    ],
                                    "correlations": [],
                                },
                            }
                        }
                    }
                }
            }
        }
    },
)
def insight_detail_with_context(insight_id: str) -> InsightDetailWithContextResponse:
    insight = get_insight(settings, insight_id)
    if not insight:
        raise HTTPException(status_code=404, detail="Insight not found")
    drivers_payload = []
    correlations_payload = []
    drivers = insight.get("drivers")
    if isinstance(drivers, list):
        drivers_payload = drivers
    elif isinstance(drivers, dict):
        drivers_payload = [drivers]

    if insight.get("insight_type") == "anomaly" and isinstance(drivers, dict):
        period = drivers.get("period")
        grain = drivers.get("grain", "month")
        metric_name = drivers.get("metric_name") or (insight.get("metric_refs") or [None])[0]
        if period and metric_name:
            driver_dims = ["sales_area_name", "product_name", "region_name", "zone_name"]
            try:
                driver_rows = compute_driver_breakdown(
                    settings,
                    catalog,
                    metric_name=metric_name,
                    grain=grain,
                    period=period,
                    dimensions=driver_dims,
                    filters=[],
                    top_n=5,
                )
                if driver_rows:
                    drivers_payload = driver_rows
            except Exception:
                pass
            try:
                correlations_payload = compute_correlations(
                    settings,
                    catalog,
                    period=period,
                    grain=grain,
                    filters=[],
                    related_metrics=[
                        "target_sales_tmt",
                        "required_run_rate_mmt",
                        "current_run_rate_mmt",
                    ],
                    window=6,
                    threshold=2.5,
                )
            except Exception:
                correlations_payload = []

    return InsightDetailWithContextResponse(
        insight=insight,
        drivers=drivers_payload,
        correlations=correlations_payload,
    )


@app.post(
    "/insights/generate",
    response_model=InsightDetailResponse,
    tags=["insights"],
    summary="Generate insights",
    description="Generate and persist a variance or anomaly insight for the domain.",
    openapi_extra={
    },
)
def generate_insights(
    tenant_id: str,
    scenario_id: str | None = None,
    type: str = "variance",
    metric_name: str | None = None,
) -> InsightDetailResponse:
    domain_id = _resolve_domain_id(tenant_id, None)
    _resolve_scope_values(tenant_id, domain_id)
    if type == "anomaly":
        if not metric_name:
            raise HTTPException(status_code=400, detail="metric_name is required for anomaly generation")
        series = build_timeseries(
            settings,
            catalog,
            metric_name=metric_name,
            grain="month",
            filters=[],
            limit=24,
        )
        points = score_anomalies(series, window=6, threshold=2.5)
        anomalies = [point for point in points if point.is_anomaly]
        if not anomalies:
            raise HTTPException(status_code=404, detail="No anomaly detected")
        latest = anomalies[-1]
        period = normalize_period(latest.period)
        insight = {
            "insight_id": f"ins_{uuid.uuid4().hex[:8]}",
            "domain_id": domain_id,
            "scenario_id": scenario_id,
            "insight_type": "anomaly",
            "headline": f"{metric_name} anomaly detected at {period}",
            "severity": "medium",
            "confidence": 0.7,
            "entity_scope": None,
            "metric_refs": [metric_name],
            "drivers": {
                "period": period,
                "grain": "month",
                "metric_name": metric_name,
                "actual": latest.actual,
                "baseline": latest.baseline,
                "deviation": latest.deviation,
                "z_score": latest.z_score,
            },
            "recommended_actions": None,
            "supporting_query_ids": None,
        }
        persist_insight(settings, insight)
        return InsightDetailResponse(insight=insight)

    insight = generate_variance_insight(settings, domain_id, scenario_id)
    if not insight:
        raise HTTPException(status_code=404, detail="No insight generated")
    persist_insight(settings, insight)
    return InsightDetailResponse(insight=insight)


@app.post(
    "/timeseries",
    response_model=TimeSeriesResponse,
    tags=["insights"],
    summary="Time-series with anomaly overlay",
    description="Return time-series points with baseline and anomaly flags.",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "timeseries": {
                            "summary": "Monthly time series",
                            "value": {
                                "metric_name": "production_mt",
                                "grain": "month",
                                "filters": [{"field": "region", "operator": "=", "value": "BANGALORE LPG RO"}],
                                "limit": 24,
                                "window": 6,
                                "threshold": 2.5,
                            },
                        }
                    }
                }
            }
        }
    },
)
def timeseries(request: TimeSeriesRequest) -> TimeSeriesResponse:
    filters = [flt.model_dump() for flt in request.filters]
    series = build_timeseries(
        settings,
        catalog,
        metric_name=request.metric_name,
        grain=request.grain,
        filters=filters,
        limit=request.limit,
    )
    points = score_anomalies(series, window=request.window, threshold=request.threshold)
    payload = [
        {
            "period": point.period,
            "actual": point.actual,
            "baseline": point.baseline,
            "deviation": point.deviation,
            "z_score": point.z_score,
            "is_anomaly": point.is_anomaly,
        }
        for point in points
    ]
    return TimeSeriesResponse(metric_name=request.metric_name, grain=request.grain, series=payload)


@app.get(
    "/actions",
    response_model=ActionsResponse,
    tags=["actions"],
    summary="List actions",
    description="Return actions with optional filters.",
    openapi_extra={
    },
)
def actions(
    tenant_id: str,
    status: str | None = None,
    limit: int = 200,
    cursor: str | None = None,
) -> ActionsResponse:
    domain_id = _resolve_domain_id(tenant_id, None)
    items = list_actions(settings, domain_id, status)
    page, next_cursor = _paginate_list(items, cursor, limit, key_fn=lambda item: item["action_id"])
    return ActionsResponse(actions=page, limit=limit, cursor=cursor, next_cursor=next_cursor)


@app.get(
    "/actions/{action_id}",
    response_model=ActionDetailResponse,
    tags=["actions"],
    summary="Get an action",
    description="Return an action record.",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "action_detail": {
                                "summary": "Action detail",
                                "value": {
                                    "action": {
                                        "action_id": "act_123",
                                        "headline": "Investigate sales drop in Tenali",
                                        "status": "open",
                                        "severity": "medium",
                                    }
                                },
                            }
                        }
                    }
                }
            }
        }
    },
)
def action_detail(action_id: str) -> ActionDetailResponse:
    action = get_action(settings, action_id)
    if not action:
        raise HTTPException(status_code=404, detail="Action not found")
    return ActionDetailResponse(action=action)


@app.post(
    "/actions",
    response_model=ActionCreateResponse,
    tags=["actions"],
    summary="Create an action",
    description="Create a new action from an insight or manual input.",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "create_action": {
                            "summary": "Create action",
                            "value": {
                                "tenant_id": "VC_101",
                                "headline": "Investigate LPG production drop in Bangalore",
                                "severity": "medium",
                                "status": "open",
                                "assigned_to": "ops_manager@company.com",
                                "source_insight_id": "ins_123",
                            },
                        }
                    }
                }
            }
        }
    },
)
def create_action_endpoint(payload: ActionCreateRequest) -> ActionCreateResponse:
    domain_id = _resolve_domain_id(payload.tenant_id, payload.domain_id)
    payload_dict = payload.model_dump()
    payload_dict["domain_id"] = domain_id
    action_id = create_action(settings, payload_dict)
    return ActionCreateResponse(action_id=action_id, status=payload.status or "open")


@app.patch(
    "/actions/{action_id}",
    response_model=ActionCreateResponse,
    tags=["actions"],
    summary="Update an action",
    description="Update action status or ownership.",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "update_status": {
                            "summary": "Update status",
                            "value": {"status": "in_progress"},
                        },
                        "reassign": {
                            "summary": "Reassign action",
                            "value": {"assigned_to": "ops_manager@company.com"},
                        },
                    }
                }
            }
        },
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "updated": {
                                "summary": "Updated action",
                                "value": {"action_id": "act_123", "status": "in_progress"},
                            }
                        }
                    }
                }
            }
        },
    },
)
def update_action_endpoint(action_id: str, payload: ActionUpdateRequest) -> ActionCreateResponse:
    update_action(settings, action_id, payload.model_dump())
    return ActionCreateResponse(action_id=action_id, status=payload.status or "updated")


@app.post(
    "/actions/{action_id}/feedback",
    tags=["actions"],
    summary="Add action feedback",
    description="Capture action outcome and impact window.",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "feedback": {
                            "summary": "Action feedback",
                            "value": {
                                "status": "resolved",
                                "outcome": "Distributor restocked",
                                "notes": "Resolved after 2 days",
                                "impact_window": {"start": "2025-02-01", "end": "2025-02-28"},
                            },
                        }
                    }
                }
            }
        },
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "ok": {"summary": "Feedback stored", "value": {"ok": True}}
                        }
                    }
                }
            }
        },
    },
)
def action_feedback(action_id: str, payload: ActionFeedbackRequest) -> dict:
    create_feedback(settings, action_id, payload.model_dump())
    return {"ok": True}


@app.get(
    "/scenarios",
    response_model=ScenariosResponse,
    tags=["scenarios"],
    summary="List scenarios",
    description="Return scenarios with optional filters.",
    openapi_extra={
    },
)
def scenarios(tenant_id: str, limit: int = 200, cursor: str | None = None) -> ScenariosResponse:
    domain_id = _resolve_domain_id(tenant_id, None)
    items = list_scenarios(settings, domain_id)
    page, next_cursor = _paginate_list(items, cursor, limit, key_fn=lambda item: item["scenario_id"])
    return ScenariosResponse(scenarios=page, limit=limit, cursor=cursor, next_cursor=next_cursor)


@app.get(
    "/scenarios/{scenario_id}",
    tags=["scenarios"],
    summary="Get a scenario",
    description="Return a single scenario record.",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "scenario_detail": {
                                "summary": "Scenario detail",
                                "value": {
                                    "scenario": {
                                        "scenario_id": "scenario_001",
                                        "domain_id": "lpg_production_distribution",
                                        "name": "Plant Outage Simulation",
                                        "status": "live",
                                    }
                                },
                            }
                        }
                    }
                }
            }
        }
    },
)
def scenario_detail(scenario_id: str) -> dict:
    scenario = get_scenario(settings, scenario_id)
    if not scenario:
        raise HTTPException(status_code=404, detail="Scenario not found")
    return {"scenario": scenario}


@app.post(
    "/scenarios",
    tags=["scenarios"],
    summary="Create a scenario",
    description="Create a new planning scenario.",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "create_scenario": {
                            "summary": "Create scenario",
                            "value": {
                                "tenant_id": "VC_101",
                                "name": "Plant Outage Simulation",
                                "description": "Simulate loss of production in a region",
                                "status": "live",
                            },
                        }
                    }
                }
            }
        },
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "created": {
                                "summary": "Scenario created",
                                "value": {"scenario_id": "scenario_001", "status": "live"},
                            }
                        }
                    }
                }
            }
        },
    },
)
def create_scenario_endpoint(payload: ScenarioCreateRequest) -> dict:
    domain_id = _resolve_domain_id(payload.tenant_id, payload.domain_id)
    payload_dict = payload.model_dump()
    payload_dict["domain_id"] = domain_id
    scenario_id = create_scenario(settings, payload_dict)
    return {"scenario_id": scenario_id, "status": payload.status or "live"}


@app.patch(
    "/scenarios/{scenario_id}",
    tags=["scenarios"],
    summary="Update a scenario",
    description="Update scenario metadata or status.",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "mark_ready": {
                            "summary": "Mark ready",
                            "value": {"status": "ready"},
                        }
                    }
                }
            }
        },
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "updated": {
                                "summary": "Scenario updated",
                                "value": {"scenario_id": "scenario_001", "status": "ready"},
                            }
                        }
                    }
                }
            }
        },
    },
)
def update_scenario_endpoint(scenario_id: str, payload: ScenarioUpdateRequest) -> dict:
    update_scenario(settings, scenario_id, payload.model_dump())
    return {"scenario_id": scenario_id, "status": payload.status or "updated"}


@app.post(
    "/scenarios/{scenario_id}/run",
    response_model=ScenarioRunResponse,
    tags=["scenarios"],
    summary="Run a scenario",
    description="Persist scenario parameters for downstream computation.",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "run": {
                            "summary": "Run scenario",
                            "value": {"parameters": {"uplift_pct": 3}},
                        }
                    }
                }
            }
        },
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "completed": {
                                "summary": "Scenario run completed",
                                "value": {"scenario_id": "scenario_001", "status": "completed"},
                            }
                        }
                    }
                }
            }
        },
    },
)
def run_scenario_endpoint(scenario_id: str, payload: ScenarioRunRequest) -> ScenarioRunResponse:
    run_scenario(settings, scenario_id, payload.parameters)
    return ScenarioRunResponse(scenario_id=scenario_id, status="completed")


@app.post(
    "/scenarios/compare",
    response_model=ScenarioCompareResponse,
    tags=["scenarios"],
    summary="Compare scenarios",
    description="Compare outputs between two scenarios for a metric.",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "compare": {
                            "summary": "Compare scenarios",
                            "value": {
                                "base_scenario_id": "baseline",
                                "compare_scenario_id": "scenario_001",
                                "metric_name": "production_mt",
                            },
                        }
                    }
                }
            }
        },
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "delta": {
                                "summary": "Scenario delta",
                                "value": {
                                    "base_scenario_id": "baseline",
                                    "compare_scenario_id": "scenario_001",
                                    "metric_name": "production_mt",
                                    "delta": 12.3,
                                },
                            }
                        }
                    }
                }
            }
        },
    },
)
def compare_scenarios_endpoint(payload: ScenarioCompareRequest) -> ScenarioCompareResponse:
    delta = compare_scenarios(
        settings,
        payload.base_scenario_id,
        payload.compare_scenario_id,
        payload.metric_name,
    )
    return ScenarioCompareResponse(
        base_scenario_id=payload.base_scenario_id,
        compare_scenario_id=payload.compare_scenario_id,
        metric_name=payload.metric_name,
        delta=delta,
    )


@app.get(
    "/dimension-values",
    response_model=DimensionValuesResponse,
    tags=["explore"],
    summary="List dimension values",
    description="Return distinct values for a dimension.",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "values": {
                                "summary": "Dimension values",
                                "value": {
                                    "dimension": "region",
                                    "values": [{"value": "BANGALORE LPG RO"}, {"value": "HYDERABAD LPG RO"}],
                                },
                            }
                        }
                    }
                }
            }
        },
    },
)
def dimension_values(
    dimension: str,
    limit: int = 100,
    search: str | None = None,
    starts_with: str | None = None,
    exclude_nulls: bool = True,
    order: str = "asc",
    cursor: str | None = None,
) -> DimensionValuesResponse:
    if dimension not in catalog.dimensions:
        raise HTTPException(status_code=400, detail=f"Unknown dimension: {dimension}")
    if order.lower() not in {"asc", "desc"}:
        raise HTTPException(status_code=400, detail="order must be 'asc' or 'desc'")
    if limit < 1:
        raise HTTPException(status_code=400, detail="limit must be >= 1")
    dim = catalog.dimensions[dimension]
    dim_sql = resolve_ref(dim.sql, settings.db_schema)
    match = re.search(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\.([a-zA-Z_][a-zA-Z0-9_]*)\b", dim_sql)
    if not match:
        raise HTTPException(status_code=400, detail=f"Could not resolve table for dimension: {dimension}")
    table_name = f"{match.group(1)}.{match.group(2)}"
    where_clauses = []
    params: list[object] = []
    if search:
        where_clauses.append(f"CAST({dim_sql} AS TEXT) ILIKE %s")
        params.append(f"%{search}%")
    if starts_with:
        where_clauses.append(f"CAST({dim_sql} AS TEXT) ILIKE %s")
        params.append(f"{starts_with}%")
    if exclude_nulls:
        where_clauses.append(f"{dim_sql} IS NOT NULL")
    cursor_value: str | None = None
    order_dir = "ASC" if order.lower() == "asc" else "DESC"
    if cursor:
        try:
            cursor_value = base64.b64decode(cursor).decode("utf-8")
        except (ValueError, UnicodeDecodeError) as exc:
            raise HTTPException(status_code=400, detail="Invalid cursor") from exc
        operator = ">" if order_dir == "ASC" else "<"
        where_clauses.append(f"CAST({dim_sql} AS TEXT) {operator} %s")
        params.append(cursor_value)
    where_sql = f" WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
    sql = (
        f"SELECT DISTINCT {dim_sql} AS value FROM {table_name}"
        f"{where_sql} ORDER BY {dim_sql} {order_dir} LIMIT %s"
    )
    params.append(limit)
    rows = run_query(settings, sql, params)
    next_cursor = None
    if rows:
        last_value = rows[-1].get("value")
        if last_value is not None:
            next_cursor = base64.b64encode(str(last_value).encode("utf-8")).decode("utf-8")
    return DimensionValuesResponse(
        dimension=dimension,
        values=rows,
        limit=limit,
        cursor=cursor,
        next_cursor=next_cursor,
    )


@app.post(
    "/metrics",
    response_model=MetricUpsertResponse,
    tags=["admin"],
    summary="Create or upsert a metric",
    description="Create a new metric in the registry, or update if the metric_id already exists.",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "create_metric": {
                            "summary": "Create metric",
                            "value": {
                                "tenant_id": "VC_101",
                                "domain_id": "lpg_production_distribution",
                                "metric_name": "production_mt",
                                "description": "Total LPG production in MT",
                                "type": "sum",
                                "sql": "({{ ref('fact_lpg_plant_operations') }}.production_14_2kg * 14.2 + {{ ref('fact_lpg_plant_operations') }}.production_19kg * 19) / 1000",
                                "grain": "day",
                                "dimensions": ["region", "sap_id"],
                                "unit": "mt",
                                "status": "certified",
                            },
                        }
                    }
                }
            }
        }
    },
)
def create_metric(payload: MetricUpsertRequest) -> MetricUpsertResponse:
    if not payload.tenant_id:
        raise HTTPException(status_code=400, detail="tenant_id is required")
    domain_id = _resolve_domain_id(payload.tenant_id, payload.domain_id)
    connection_id, database, schema, tables = _resolve_scope_values(
        payload.tenant_id,
        domain_id,
    )
    payload_dict = payload.model_dump()
    payload_dict["domain_id"] = domain_id
    payload_dict["connection_id"] = connection_id
    payload_dict["database"] = database
    payload_dict["schema"] = schema
    payload_dict["tables"] = tables
    payload_dict["lifecycle_status"] = payload.status or "suggested"
    payload_dict["source_type"] = "user"
    fact_grains = _fact_grain_map(payload.tenant_id, domain_id, connection_id, database, schema)
    _validate_metric_payload(payload_dict, fact_grains)
    metric_id = upsert_metric(settings, payload_dict)
    return MetricUpsertResponse(metric_id=metric_id, status=payload.status or "suggested")


@app.patch(
    "/metrics/{metric_id}",
    response_model=MetricUpsertResponse,
    tags=["admin"],
    summary="Update a metric",
    description="Patch a metric in the registry. Only provided fields are updated.",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "promote_metric": {
                            "summary": "Promote to certified",
                            "value": {"status": "certified"},
                        },
                        "fix_sql": {
                            "summary": "Update SQL",
                            "value": {"sql": "{{ ref('fact_lpg_plant_operations') }}.production_19kg"},
                        },
                    }
                }
            }
        }
    },
)
def patch_metric(metric_id: str, payload: MetricPatchRequest) -> MetricUpsertResponse:
    if not payload.tenant_id:
        raise HTTPException(status_code=400, detail="tenant_id is required")
    domain_id = _resolve_domain_id(payload.tenant_id, payload.domain_id)
    connection_id, database, schema, tables = _resolve_scope_values(
        payload.tenant_id,
        domain_id,
    )
    updates = {key: value for key, value in payload.model_dump().items() if value is not None}
    updates["domain_id"] = domain_id
    updates["connection_id"] = connection_id
    updates["database"] = database
    updates["schema"] = schema
    updates["tables"] = tables
    if updates.get("status") is not None and updates.get("lifecycle_status") is None:
        updates["lifecycle_status"] = updates.get("status")
    updates.pop("status", None)
    updates.setdefault("source_type", "user")
    current_rows = run_query(
        settings,
        """
        SELECT metric_id, metric_name, type, sql, grain
          FROM public.quantyx_metrics_registry
         WHERE (metric_id = %s OR artifact_key = %s)
           AND tenant_id = %s
           AND domain_id = %s
           AND connection_id = %s
           AND database_name = %s
           AND schema_name = %s
           AND COALESCE(is_current, true) = true
         LIMIT 1
        """,
        [metric_id, metric_id, payload.tenant_id, domain_id, connection_id, database, schema],
    )
    if not current_rows:
        raise HTTPException(status_code=404, detail="Metric not found")
    current = current_rows[0]
    merged_metric = {
        "metric_name": updates.get("metric_name", current.get("metric_name")),
        "type": updates.get("type", current.get("type")),
        "sql": updates.get("sql", current.get("sql")),
        "grain": updates.get("grain", current.get("grain")),
    }
    fact_grains = _fact_grain_map(payload.tenant_id, domain_id, connection_id, database, schema)
    _validate_metric_payload(merged_metric, fact_grains)
    update_metric(settings, metric_id, updates)
    status = updates.get("lifecycle_status", "updated")
    return MetricUpsertResponse(metric_id=metric_id, status=status)


@app.delete(
    "/metrics/{metric_id}",
    tags=["admin"],
    summary="Delete a metric",
    description="Delete a metric from the registry.",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {"deleted": {"value": {"ok": True}}}
                    }
                }
            }
        }
    },
)
def delete_metric_endpoint(metric_id: str) -> dict:
    delete_metric(settings, metric_id)
    return {"ok": True}

@app.get(
    "/context/domains",
    tags=["context"],
    summary="List industry packs",
    description="Return available domain packs from the packs/ folder.",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "domains": {
                                "summary": "Domain packs",
                                "value": {
                                    "domains": [
                                        {"domain_id": "lpg_production_distribution", "display_name": "lpg_production_distribution"},
                                        {"domain_id": "manufacturing", "display_name": "manufacturing"},
                                    ]
                                },
                            }
                        }
                    }
                }
            }
        }
    },
)
def domains() -> dict:
    packs = list_packs()
    return {"domains": [{"domain_id": name, "display_name": name} for name in packs]}


def _default_context_questions(domain_id: str) -> list[dict]:
    return [
        {
            "group_id": "dashboard_objectives",
            "title": "Dashboard Objectives",
            "questions": [
                {
                    "question_id": "primary_kpis",
                    "prompt": "What are the most important KPIs this dashboard should track?",
                    "answer_type": "text",
                    "required": True,
                    "maps_to": ["metric_refinement", "chart_guidance"],
                },
                {
                    "question_id": "dashboard_audience",
                    "prompt": "Who is the main audience for this dashboard?",
                    "answer_type": "single_select",
                    "options": ["operations", "management", "finance", "planning", "quality"],
                    "required": False,
                    "maps_to": ["chart_guidance"],
                },
            ],
        },
        {
            "group_id": "hierarchy_and_grain",
            "title": "Hierarchy and Grain",
            "questions": [
                {
                    "question_id": "preferred_drill_path",
                    "prompt": "What is the preferred business drill path from broad to detailed levels?",
                    "answer_type": "text",
                    "required": False,
                    "maps_to": ["hierarchy_override"],
                },
                {
                    "question_id": "preferred_time_grain",
                    "prompt": "Which time grain is most important for decision-making?",
                    "answer_type": "single_select",
                    "options": ["day", "week", "month", "quarter"],
                    "required": False,
                    "maps_to": ["chart_guidance", "metric_refinement"],
                },
            ],
        },
        {
            "group_id": "rules_and_trust",
            "title": "Rules and Data Trust",
            "questions": [
                {
                    "question_id": "mandatory_exclusions",
                    "prompt": "Which records should always be excluded?",
                    "answer_type": "text",
                    "required": False,
                    "maps_to": ["metric_refinement", "join_rule"],
                },
                {
                    "question_id": "unreliable_fields",
                    "prompt": "Which fields or tables are known to be unreliable?",
                    "answer_type": "text",
                    "required": False,
                    "maps_to": ["business_context", "interpretation_rule"],
                },
            ],
        },
    ]


def _load_context_questions_for_domain(domain_id: str) -> list[dict]:
    pack = load_pack(f"packs/{domain_id}")
    groups = ((pack.get("context_questions") or {}).get("question_groups") or [])
    return groups if groups else _default_context_questions(domain_id)


@app.get(
    "/packs/{pack_id}/context-questions",
    response_model=ContextQuestionsResponse,
    tags=["context"],
    summary="Get pack context questions",
    description="Return pack-defined semantic discovery questions, with a generic fallback when the pack has no context_questions.yml.",
)
def get_pack_context_questions(pack_id: str) -> ContextQuestionsResponse:
    if pack_id not in list_packs():
        raise HTTPException(status_code=404, detail="Pack not found")
    return ContextQuestionsResponse(domain_id=pack_id, question_groups=_load_context_questions_for_domain(pack_id))


@app.get(
    "/semantic/context-questions",
    response_model=ContextQuestionsResponse,
    tags=["semantic"],
    summary="Get semantic context questions",
    description="Return semantic discovery questions for the selected tenant/domain.",
)
def get_semantic_context_questions(tenant_id: str, domain_id: str | None = None) -> ContextQuestionsResponse:
    resolved_domain_id = _resolve_domain_id(tenant_id, domain_id)
    return ContextQuestionsResponse(
        domain_id=resolved_domain_id,
        question_groups=_load_context_questions_for_domain(resolved_domain_id),
    )


@app.post(
    "/context/ingest",
    response_model=ContextIngestResponse,
    tags=["context"],
    summary="Ingest business context",
    description="Persist customer-provided business context text for ontology, hierarchy, and metric enrichment.",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "business_context": {
                            "summary": "Glossary and hierarchy notes",
                            "value": {
                                "tenant_id": "VC_101",
                                "domain_id": "lpg_production_distribution",
                                "source_type": "business_context",
                                "source_title": "Operations glossary and hierarchy notes",
                                "raw_text": "Plant = LPG filling facility. Sales org is Zone > Region > Sales Area...",
                                "file_ids": ["file_123", "file_456"],
                                "metadata": {
                                    "columns": ["plant_name", "region"],
                                },
                            },
                        }
                    }
                }
            }
        },
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "submitted": {
                                "summary": "Context stored",
                                "value": {"context_id": "ctx_123", "status": "submitted"},
                            }
                        }
                    }
                }
            }
        },
    },
)
def ingest_context(payload: ContextIngestRequest) -> ContextIngestResponse:
    logger.info(
        "context.ingest: start | %s",
        {
            "tenant_id": payload.tenant_id,
            "domain_id": payload.domain_id,
            "source_type": payload.source_type,
            "has_text": bool(payload.raw_text),
            "file_ids": len(payload.file_ids or []),
        },
    )
    domain_id = _resolve_domain_id(payload.tenant_id, payload.domain_id)
    source_title = payload.source_title or generate_source_title(payload.raw_text, payload.metadata)
    logger.info("context.ingest: source_title.resolved | %s", {"source_title": source_title})
    context_id = create_context(
        settings,
        tenant_id=payload.tenant_id,
        domain_id=domain_id,
        source_type=payload.source_type,
        source_title=source_title,
        raw_text=payload.raw_text,
        metadata=payload.metadata,
    )
    logger.info("context.ingest: stored | %s", {"context_id": context_id})
    if payload.file_ids:
        logger.info(
            "context.ingest: link.files.begin | %s",
            {"context_id": context_id, "file_ids": len(payload.file_ids)},
        )
        link_context_files(settings, context_id, payload.file_ids)
        logger.info("context.ingest: link.files.complete | %s", {"context_id": context_id})
    logger.info("context.ingest: complete | %s", {"context_id": context_id})
    enrich_status = "no_text"
    if payload.raw_text and payload.raw_text.strip():
        logger.info(
            "context.enrich.start | context_id=%s raw_len=%s",
            context_id,
            len(payload.raw_text),
        )
        enriched = enrich_context_text(settings, payload.raw_text)
        if enriched:
            update_enriched_context(settings, context_id, enriched)
            enrich_status = "enriched"
            logger.info(
                "context.enrich.complete | context_id=%s enriched_len=%s",
                context_id,
                len(enriched),
            )
        else:
            enrich_status = "skipped"
            logger.warning("context.enrich.skipped | context_id=%s", context_id)
    return ContextIngestResponse(context_id=context_id, status=enrich_status)


@app.post(
    "/context/ingest-file",
    response_model=ContextFileIngestResponse,
    tags=["context"],
    summary="Ingest business context file",
    description="Upload a text file and persist its contents as business context.",
    openapi_extra={
        "requestBody": {
            "content": {
                "multipart/form-data": {
                    "examples": {
                        "upload_context": {
                            "summary": "Upload business context (.txt or .docx)",
                            "value": {
                                "tenant_id": "VC_101",
                                "domain_id": "lpg_production_distribution",
                                "source_type": "business_context",
                                "source_title": "Operations glossary",
                                "metadata": "{\"columns\":[\"plant_name\",\"region\"]}",
                                "file": "@context.txt",
                            },
                        }
                    }
                }
            }
        }
    },
)
def ingest_context_file(
    tenant_id: str = Form(...),
    domain_id: str | None = Form(None),
    source_type: str = Form(...),
    source_title: str | None = Form(None),
    metadata: str | None = Form(None),
    file: UploadFile = File(...),
) -> ContextFileIngestResponse:
    logger.info(
        "context.ingest-file: start | %s",
        {
            "tenant_id": tenant_id,
            "domain_id": domain_id,
            "source_type": source_type,
            "filename": file.filename,
        },
    )
    filename = (file.filename or "").lower()
    if filename.endswith(".doc"):
        raise HTTPException(status_code=400, detail="Unsupported file type: .doc")
    if not (filename.endswith(".txt") or filename.endswith(".docx")):
        raise HTTPException(status_code=400, detail="Unsupported file type: use .txt or .docx")
    try:
        raw_bytes = file.file.read()
    finally:
        file.file.close()
    logger.info("context.ingest-file: file.read | %s", {"bytes": len(raw_bytes)})
    if filename.endswith(".docx"):
        try:
            with zipfile.ZipFile(io.BytesIO(raw_bytes)) as docx:
                xml_data = docx.read("word/document.xml")
            root = ElementTree.fromstring(xml_data)
            text_nodes = [node.text for node in root.iter() if node.tag.endswith("}t") and node.text]
            raw_text = "\n".join(text_nodes).strip()
            logger.info(
                "context.ingest-file: docx.parsed | %s",
                {"text_chars": len(raw_text)},
            )
        except (KeyError, zipfile.BadZipFile, ElementTree.ParseError) as exc:
            raise HTTPException(status_code=400, detail="Invalid .docx file") from exc
    else:
        raw_text = raw_bytes.decode("utf-8", errors="replace")
        logger.info(
            "context.ingest-file: text.decoded | %s",
            {"text_chars": len(raw_text)},
        )
    parsed_metadata = None
    if metadata:
        try:
            parsed_metadata = json.loads(metadata)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail="metadata must be valid JSON") from exc
    if not parsed_metadata:
        parsed_metadata = {}
    resolved_domain = _resolve_domain_id(tenant_id, domain_id)
    file_id = create_context_file(
        settings,
        tenant_id=tenant_id,
        domain_id=resolved_domain,
        filename=filename,
        content_type=file.content_type,
        extracted_text=raw_text,
        file_bytes=raw_bytes,
        metadata={
            "source_type": source_type,
            "source_title": source_title,
            **(parsed_metadata or {}),
        },
    )
    logger.info("context.ingest-file: stored | %s", {"file_id": file_id})
    logger.info("context.ingest-file: complete | %s", {"file_id": file_id})
    return ContextFileIngestResponse(file_id=file_id, status="stored")


@app.get(
    "/context",
    response_model=ContextListResponse,
    tags=["context"],
    summary="List business context entries",
    description="List stored business context entries with cursor pagination.",
    openapi_extra={
    },
)
def list_context_entries(
    tenant_id: str,
    source_type: str | None = None,
    status: str | None = None,
    limit: int = 200,
    cursor: str | None = None,
) -> ContextListResponse:
    domain_id = _resolve_domain_id(tenant_id, None)
    decoded_cursor = _decode_cursor(cursor) if cursor else None
    entries, next_cursor = list_context(
        settings,
        tenant_id=tenant_id,
        domain_id=domain_id,
        source_type=source_type,
        status=status,
        connection_id=None,
        database=None,
        schema=None,
        limit=limit,
        cursor=decoded_cursor,
    )
    encoded_next = _encode_cursor(next_cursor) if next_cursor else None
    return ContextListResponse(entries=entries, limit=limit, cursor=cursor, next_cursor=encoded_next)


@app.post(
    "/context/extract",
    response_model=ContextExtractResponse,
    tags=["context"],
    summary="Extract structured context",
    description="Run LLM-assisted extraction to derive abbreviations, synonyms, hierarchies, and metric candidates.",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "extract_context": {
                            "summary": "Extract from stored context",
                            "value": {
                                "tenant_id": "VC_101",
                                "domain_id": "lpg_production_distribution",
                                "context_id": "ctx_123",
                                "extraction_types": [
                                    "abbreviations",
                                    "synonyms",
                                    "hierarchies",
                                    "metric_candidates",
                                    "question_intents",
                                ],
                            },
                        }
                    }
                }
            }
        },
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "extracted": {
                                "summary": "Extraction results",
                                "value": {
                                    "extraction_id": "ext_123",
                                    "context_id": "ctx_123",
                                    "extractions": {
                                        "abbreviations": [
                                            {"abbr": "SAP", "definition": "Systems, Applications, and Products"}
                                        ],
                                        "synonyms": [{"term": "plant", "synonyms": ["sap_id", "plant_id"]}],
                                        "hierarchies": [
                                            {"name": "sales_org", "levels": ["zone", "region", "sales_area"]}
                                        ],
                                        "metric_candidates": [
                                            {"metric_name": "production_mt", "table": "fact_lpg_plant_operations"}
                                        ],
                                        "question_intents": [
                                            {
                                                "question": "Which plants are underperforming?",
                                                "metrics": ["production_mt"],
                                            }
                                        ],
                                    },
                                },
                            }
                        }
                    }
                }
            }
        },
    },
)
def extract_context_payload(payload: ContextExtractRequest) -> ContextExtractResponse:
    domain_id = _resolve_domain_id(payload.tenant_id, payload.domain_id)
    logger.info(
        "context.extract: start | %s",
        {
            "tenant_id": payload.tenant_id,
            "domain_id": payload.domain_id,
            "context_id": payload.context_id,
            "extraction_types": payload.extraction_types,
        },
    )
    context_row = get_context(settings, payload.context_id)
    if not context_row:
        raise HTTPException(status_code=404, detail="Context not found")
    if context_row["tenant_id"] != payload.tenant_id or context_row["domain_id"] != domain_id:
        raise HTTPException(status_code=400, detail="Context tenant/domain mismatch")

    file_texts = get_context_file_texts(settings, payload.context_id)
    logger.info(
        "context.extract: files.loaded | %s",
        {"context_id": payload.context_id, "files": len(file_texts)},
    )
    if file_texts:
        total_file_chars = sum(len(text) for text in file_texts if text)
        logger.info(
            "context.extract: files.summary | %s",
            {"context_id": payload.context_id, "file_text_chars": total_file_chars},
        )
    combined_parts = [context_row["raw_text"]] if context_row["raw_text"] else []
    combined_parts.extend(file_texts)
    combined_text = "\n\n".join([part for part in combined_parts if part])
    logger.info(
        "context.extract: text.prepared | %s",
        {"context_id": payload.context_id, "chars": len(combined_text)},
    )
    logger.info(
        "context.extract: llm.request | %s",
        {
            "context_id": payload.context_id,
            "extraction_types": payload.extraction_types,
            "raw_text_chars": len(context_row["raw_text"] or ""),
            "file_text_chars": sum(len(text) for text in file_texts if text),
            "total_chars": len(combined_text),
        },
    )
    extracted = extract_context(
        settings,
        raw_text=combined_text,
        extraction_types=payload.extraction_types,
    )
    logger.info(
        "context.extract: llm.complete | %s",
        {
            "context_id": payload.context_id,
            "extraction_types": list((extracted or {}).keys()),
        },
    )
    extraction_id = persist_extraction(
        settings,
        context_id=payload.context_id,
        tenant_id=payload.tenant_id,
        domain_id=domain_id,
        payload=extracted,
        llm_model=settings.openai_model,
    )
    logger.info(
        "context.extract: stored | %s",
        {"context_id": payload.context_id, "extraction_id": extraction_id},
    )
    mark_context_processed(settings, payload.context_id)
    logger.info("context.extract: context.marked | %s", {"context_id": payload.context_id})
    logger.info("context.extract: complete | %s", {"extraction_id": extraction_id})
    return ContextExtractResponse(
        extraction_id=extraction_id,
        context_id=payload.context_id,
        extractions=extracted,
    )


@app.post(
    "/context/extract/async",
    response_model=JobCreateResponse,
    tags=["context"],
    summary="Extract structured context (async)",
    description="Queue LLM-assisted extraction as a background job.",
)
def extract_context_async(payload: ContextExtractRequest) -> JobCreateResponse:
    domain_id = _resolve_domain_id(payload.tenant_id, payload.domain_id)
    job = create_job(
        settings,
        tenant_id=payload.tenant_id,
        domain_id=domain_id,
        job_type="context_extract",
        payload=payload.model_dump(),
        idempotency_key=None,
    )
    return JobCreateResponse(job_id=job.get("job_id"), status=job.get("status", "queued"))


@app.get(
    "/context/extractions",
    response_model=ContextExtractionListResponse,
    tags=["context"],
    summary="List extractions for tenant",
    description="Return recent extractions for all contexts in a tenant (optional domain filter).",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "list": {
                                "summary": "Extraction list",
                                "value": {
                                    "extractions": [
                                        {
                                            "extraction_id": "ext_123",
                                            "context_id": "ctx_abc",
                                            "extraction_type": "combined",
                                            "payload": {"hierarchies": []},
                                            "raw_text": "Source notes...",
                                            "files": [
                                                {
                                                    "file_id": "file_1",
                                                    "filename": "notes.txt",
                                                    "content_type": "text/plain",
                                                }
                                            ],
                                            "applied_glossary": [
                                                {
                                                    "term": "plant",
                                                    "definition": "LPG filling facility",
                                                    "synonyms": ["sap_id", "plant_id"],
                                                }
                                            ],
                                            "applied_entities": [
                                                {
                                                    "entity_id": "plant",
                                                    "join_key": "sap_id",
                                                    "lifecycle_status": "certified",
                                                }
                                            ],
                                            "applied_hierarchies": [
                                                {"name": "sales_org", "levels": ["zone", "region", "sales_area"]}
                                            ],
                                            "status": "reviewed",
                                            "created_at": "2026-02-20T10:05:12Z",
                                        }
                                    ]
                                },
                            }
                        }
                    }
                }
            }
        }
    },
)
def list_context_extractions(
    tenant_id: str,
    domain_id: str | None = None,
    limit: int = 50,
    include_applied: bool = True,
) -> ContextExtractionListResponse:
    resolved_domain_id = _resolve_domain_id(tenant_id, domain_id) if tenant_id else domain_id
    rows = list_extractions(settings, tenant_id, resolved_domain_id if domain_id else None, limit=limit)
    context_ids = [row.get("context_id") for row in rows if row.get("context_id")]
    files_by_context = list_context_files_for_contexts(settings, context_ids)
    applied_by_context = list_applied_context_artifacts(settings, context_ids) if include_applied else {}
    extractions = []
    for row in rows:
        applied = applied_by_context.get(row.get("context_id"), {})
        extractions.append(
            ContextExtractionResponse(
                extraction_id=row.get("extraction_id"),
                context_id=row.get("context_id"),
                extraction_type=row.get("extraction_type"),
                payload=row.get("payload") or {},
                raw_text=row.get("raw_text"),
                files=files_by_context.get(row.get("context_id"), []),
                applied_glossary=applied.get("glossary", []),
                applied_entities=applied.get("entities", []),
                applied_hierarchies=applied.get("hierarchies", []),
                status=row.get("status"),
                notes=row.get("notes"),
                created_at=row.get("created_at").isoformat() if row.get("created_at") else None,
            )
        )
    return ContextExtractionListResponse(extractions=extractions)


@app.get(
    "/context/extractions/{extraction_id}",
    response_model=ContextExtractionResponse,
    tags=["context"],
    summary="Fetch an extraction",
    description="Return a stored extraction payload for review.",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "extraction": {
                                "summary": "Stored extraction",
                                "value": {
                                    "extraction_id": "ext_123",
                                    "context_id": "ctx_123",
                                    "extraction_type": "combined",
                                    "payload": {
                                        "hierarchies": [
                                            {"name": "sales_org", "levels": ["zone", "region", "sales_area"]}
                                        ]
                                    },
                                    "applied_glossary": [
                                        {
                                            "term": "plant",
                                            "definition": "LPG filling facility",
                                            "synonyms": ["sap_id", "plant_id"],
                                        }
                                    ],
                                    "applied_entities": [
                                        {
                                            "entity_id": "plant",
                                            "join_key": "sap_id",
                                            "lifecycle_status": "certified",
                                        }
                                    ],
                                    "applied_hierarchies": [
                                        {"name": "sales_org", "levels": ["zone", "region", "sales_area"]}
                                    ],
                                    "status": "reviewed",
                                    "notes": "Reviewed by analyst",
                                },
                            }
                        }
                    }
                }
            }
        }
    },
)
def get_context_extraction(
    extraction_id: str,
    tenant_id: str,
    include_applied: bool = True,
) -> ContextExtractionResponse:
    domain_id = _resolve_domain_id(tenant_id, None)
    extraction_row = get_extraction(settings, extraction_id)
    if not extraction_row:
        raise HTTPException(status_code=404, detail="Extraction not found")
    if extraction_row["tenant_id"] != tenant_id or extraction_row["domain_id"] != domain_id:
        raise HTTPException(status_code=400, detail="Extraction tenant/domain mismatch")
    created_at = extraction_row.get("created_at")
    applied = {}
    if include_applied and extraction_row.get("context_id"):
        applied = list_applied_context_artifacts(settings, [extraction_row.get("context_id")]).get(
            extraction_row.get("context_id"),
            {},
        )
    return ContextExtractionResponse(
        extraction_id=extraction_row["extraction_id"],
        context_id=extraction_row["context_id"],
        extraction_type=extraction_row.get("extraction_type"),
        payload=extraction_row.get("payload") or {},
        applied_glossary=applied.get("glossary", []),
        applied_entities=applied.get("entities", []),
        applied_hierarchies=applied.get("hierarchies", []),
        status=extraction_row.get("status"),
        notes=extraction_row.get("notes"),
        created_at=created_at.isoformat() if created_at else None,
    )


@app.get(
    "/context/files/{file_id}/download",
    tags=["context"],
    summary="Download a context file",
    description="Download the original file bytes for a context file.",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/octet-stream": {
                        "examples": {
                            "file": {
                                "summary": "Binary file download",
                                "description": "Binary response with Content-Disposition header",
                                "value": "..."
                            }
                        }
                    }
                }
            }
        }
    },
)
def download_context_file(file_id: str, tenant_id: str) -> Response:
    domain_id = _resolve_domain_id(tenant_id, None)
    row = get_context_file_bytes(settings, file_id)
    if not row:
        raise HTTPException(status_code=404, detail="File not found")
    if row.get("tenant_id") != tenant_id or row.get("domain_id") != domain_id:
        raise HTTPException(status_code=404, detail="File not found")
    raw_bytes = row.get("raw_bytes") or b""
    if isinstance(raw_bytes, memoryview):
        raw_bytes = raw_bytes.tobytes()
    filename = row.get("filename") or file_id
    content_type = row.get("content_type") or "application/octet-stream"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return Response(content=raw_bytes, media_type=content_type, headers=headers)


@app.post(
    "/context/apply",
    response_model=ContextApplyResponse,
    tags=["context"],
    summary="Apply extracted context",
    description="Apply extracted context to glossary, hierarchy overrides, entity overrides, and metrics registry.",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "apply_context": {
                            "summary": "Apply all extracted signals",
                            "value": {
                                "tenant_id": "VC_101",
                                "domain_id": "lpg_production_distribution",
                                "extraction_id": "ext_123",
                                "apply": {
                                    "entities": True,
                                    "hierarchies": True,
                                    "glossary": True,
                                    "metrics": True,
                                },
                            },
                        }
                        ,
                        "apply_selected_hierarchies": {
                            "summary": "Apply only selected hierarchies",
                            "value": {
                                "tenant_id": "VC_101",
                                "domain_id": "lpg_production_distribution",
                                "extraction_id": "ext_123",
                                "apply": {
                                    "entities": True,
                                    "hierarchies": True,
                                    "glossary": True,
                                    "metrics": True,
                                },
                                "hierarchy_selection": {"names": ["geography"], "apply_all": False},
                            },
                        }
                    }
                }
            }
        },
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "applied": {
                                "summary": "Applied results",
                                "value": {
                                    "status": "applied",
                                    "updated": {"entities": 4, "hierarchies": 1, "metrics": 8},
                                },
                            }
                        }
                    }
                }
            }
        },
    },
)
def apply_context(payload: ContextApplyRequest) -> ContextApplyResponse:
    logger.info(
        "context.apply: start | %s",
        {
            "tenant_id": payload.tenant_id,
            "domain_id": payload.domain_id,
            "extraction_id": payload.extraction_id,
            "apply": payload.apply,
        },
    )
    domain_id = _resolve_domain_id(payload.tenant_id, payload.domain_id)
    extraction_row = get_extraction(settings, payload.extraction_id)
    if not extraction_row:
        raise HTTPException(status_code=404, detail="Extraction not found")
    if extraction_row["tenant_id"] != payload.tenant_id or extraction_row["domain_id"] != domain_id:
        raise HTTPException(status_code=400, detail="Extraction tenant/domain mismatch")

    connection_id, database_name, schema_name, _ = _resolve_scope_values(
        payload.tenant_id,
        domain_id,
    )
    context_row = get_context(settings, extraction_row.get("context_id"))
    logger.info(
        "context.apply: scope.resolved | %s",
        {
            "context_id": extraction_row.get("context_id"),
            "connection_id": connection_id,
            "database": database_name,
            "schema": schema_name,
        },
    )
    updated = apply_extractions(
        settings,
        tenant_id=payload.tenant_id,
        domain_id=domain_id,
        payload=extraction_row["payload"],
        apply_flags=payload.apply,
        hierarchy_selection=payload.hierarchy_selection,
        source_context_id=extraction_row.get("context_id"),
        connection_id=connection_id,
        database_name=database_name,
        schema_name=schema_name,
    )
    if extraction_row.get("context_id"):
        set_context_active(
            settings,
            tenant_id=payload.tenant_id,
            domain_id=domain_id,
            context_id=extraction_row["context_id"],
            connection_id=connection_id,
            database_name=database_name,
            schema_name=schema_name,
            is_active=True,
        )
    logger.info(
        "context.apply: complete | %s",
        {"extraction_id": payload.extraction_id, "updated": updated},
    )
    return ContextApplyResponse(status="applied", updated=updated)


@app.post(
    "/context/apply/async",
    response_model=JobCreateResponse,
    tags=["context"],
    summary="Apply extracted context (async)",
    description="Queue context apply as a background job.",
)
def apply_context_async(payload: ContextApplyRequest) -> JobCreateResponse:
    domain_id = _resolve_domain_id(payload.tenant_id, payload.domain_id)
    job = create_job(
        settings,
        tenant_id=payload.tenant_id,
        domain_id=domain_id,
        job_type="context_apply",
        payload=payload.model_dump(),
        idempotency_key=None,
    )
    return JobCreateResponse(job_id=job.get("job_id"), status=job.get("status", "queued"))


@app.patch(
    "/context/{context_id}",
    tags=["context"],
    summary="Update a context entry",
    description="Update context metadata or status; scope fields cannot change.",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "update_title": {
                            "summary": "Update title and status",
                            "value": {"source_title": "Ops glossary v2", "status": "processed"},
                        },
                        "activate_context": {
                            "summary": "Activate context",
                            "value": {"status": "active"},
                        },
                        "deactivate_context": {
                            "summary": "Deactivate context",
                            "value": {"status": "inactive"},
                        },
                        "update_metadata": {
                            "summary": "Update metadata",
                            "value": {"metadata": {"columns": ["plant_name", "region_name"]}},
                        },
                    }
                }
            }
        }
    },
)
def patch_context(
    context_id: str,
    tenant_id: str,
    payload: ContextPatchRequest,
) -> dict:
    domain_id = _resolve_domain_id(tenant_id, None)
    context_row = get_context(settings, context_id)
    if not context_row:
        raise HTTPException(status_code=404, detail="Context not found")
    if context_row["tenant_id"] != tenant_id or context_row["domain_id"] != domain_id:
        raise HTTPException(status_code=400, detail="Context tenant/domain mismatch")

    updates = {key: value for key, value in payload.model_dump().items() if value is not None}
    if not updates:
        return {"ok": True}
    status = updates.get("status")
    if status in {"active", "inactive"}:
        set_context_active(
            settings,
            tenant_id=tenant_id,
            domain_id=domain_id,
            context_id=context_id,
            connection_id=context_row.get("connection_id"),
            database_name=context_row.get("database_name"),
            schema_name=context_row.get("schema_name"),
            is_active=status == "active",
        )
    update_context(settings, context_id, updates)
    return {"ok": True}


@app.patch(
    "/context/files/{file_id}",
    tags=["context"],
    summary="Update a context file",
    description="Update context file metadata; scope fields cannot change.",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "update_file_metadata": {
                            "summary": "Update file metadata",
                            "value": {"metadata": {"columns": ["plant_name", "region_name"]}},
                        }
                    }
                }
            }
        }
    },
)
def patch_context_file(
    file_id: str,
    tenant_id: str,
    payload: ContextFilePatchRequest,
) -> dict:
    domain_id = _resolve_domain_id(tenant_id, None)
    if payload.metadata is None:
        raise HTTPException(status_code=400, detail="metadata is required")
    file_row = get_context_file(settings, file_id)
    if not file_row:
        raise HTTPException(status_code=404, detail="Context file not found")
    if file_row["tenant_id"] != tenant_id or file_row["domain_id"] != domain_id:
        raise HTTPException(status_code=400, detail="Context file tenant/domain mismatch")
    update_context_file_metadata(settings, file_id, payload.metadata)
    return {"ok": True}


@app.patch(
    "/context/extractions/{extraction_id}",
    tags=["context"],
    summary="Update a context extraction",
    description="Update extraction status or notes; payload is immutable.",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "reviewed": {
                            "summary": "Mark as reviewed",
                            "value": {"status": "reviewed", "notes": "Reviewed by analyst"},
                        }
                    }
                }
            }
        }
    },
)
def patch_context_extraction(
    extraction_id: str,
    tenant_id: str,
    payload: ContextExtractionPatchRequest,
) -> dict:
    domain_id = _resolve_domain_id(tenant_id, None)
    extraction_row = get_extraction(settings, extraction_id)
    if not extraction_row:
        raise HTTPException(status_code=404, detail="Extraction not found")
    if extraction_row["tenant_id"] != tenant_id or extraction_row["domain_id"] != domain_id:
        raise HTTPException(status_code=400, detail="Extraction tenant/domain mismatch")
    update_extraction(settings, extraction_id, status=payload.status, notes=payload.notes)
    return {"ok": True}


@app.get(
    "/entities",
    response_model=EntitiesResponse,
    tags=["explore"],
    summary="List entities and hierarchies",
    description="Return tenant-scoped entities and hierarchies for a connection.",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "entities": {
                                "summary": "Entities and hierarchies",
                                "value": {
                                    "entities": [
                                        {
                                            "entity_id": "organizational_unit",
                                            "description": "Sales organization",
                                            "join_key": "sap_id",
                                        }
                                    ],
                                    "hierarchies": [
                                        {
                                            "name": "sales_org",
                                            "levels": ["zone", "region", "sales_area"],
                                        }
                                    ],
                                },
                            }
                        }
                    }
                }
            }
        },
    },
)
def entities(
    tenant_id: str,
) -> EntitiesResponse:
    domain_id = _resolve_domain_id(tenant_id, None)
    connection_id, database, schema, _ = _resolve_scope_values(
        tenant_id,
        domain_id,
    )
    active_context_ids = list_active_context_ids(
        settings,
        tenant_id,
        domain_id,
        connection_id,
        database,
        schema,
    )
    entity_overrides, hierarchy_overrides = load_overrides(
        settings,
        tenant_id,
        domain_id,
        connection_id=connection_id,
        database_name=database,
        schema_name=schema,
        context_ids=active_context_ids or None,
    )
    entity_page = [
        {
            "entity_id": item.get("entity_id"),
            "description": item.get("description"),
            "join_key": item.get("join_key"),
            "examples": item.get("examples"),
            "lifecycle_status": item.get("lifecycle_status"),
            "source_type": item.get("source_type"),
            "source_run_id": item.get("source_run_id"),
            "artifact_key": item.get("artifact_key"),
            "version_no": item.get("version_no"),
            "is_current": item.get("is_current"),
        }
        for item in sorted(entity_overrides, key=lambda item: item.get("entity_id", ""))
    ]
    hierarchy_page = [
        {
            "name": item.get("hierarchy_name"),
            "levels": item.get("levels", []),
            "description": item.get("description"),
            "context_id": item.get("context_id"),
            "hierarchy_group": item.get("hierarchy_group"),
            "lifecycle_status": item.get("lifecycle_status"),
            "source_type": item.get("source_type"),
            "source_run_id": item.get("source_run_id"),
            "artifact_key": item.get("artifact_key"),
            "version_no": item.get("version_no"),
            "is_current": item.get("is_current"),
        }
        for item in sorted(hierarchy_overrides, key=lambda item: item.get("hierarchy_name", ""))
    ]
    return EntitiesResponse(
        entities=entity_page,
        hierarchies=hierarchy_page,
    )


@app.get(
    "/entities/mappings",
    tags=["explore"],
    summary="List entity mapping runs",
    description="Return all entity mapping runs for the active tenant scope.",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "runs": {
                                "summary": "Mapping runs",
                                "value": {
                                    "runs": [
                                        {
                                            "mapping_id": "map_ab12cd34",
                                            "tenant_id": "VC_101",
                                            "domain_id": "lpg_production_distribution",
                                            "connection_id": "conn_lpg",
                                            "database_name": "hpcl_ceg",
                                            "schema_name": "public",
                                            "tables": ["lpg_plant_operations"],
                                            "candidates": [
                                                {
                                                    "table": "lpg_plant_operations",
                                                    "column": "sap_id",
                                                    "mapped_entity_type": "plant",
                                                    "confidence": 0.93,
                                                    "source": "llm",
                                                }
                                            ],
                                            "low_confidence_candidates": [],
                                            "low_confidence_threshold": 0.7,
                                            "status": "live",
                                        }
                                    ]
                                },
                            }
                        }
                    }
                }
            }
        }
    },
)
def entities_mappings(tenant_id: str, limit: int = 50) -> dict:
    domain_id = _resolve_domain_id(tenant_id, None)
    connection_id, database, schema, _ = _resolve_scope_values(
        tenant_id,
        domain_id,
    )
    runs = list_entity_mappings(
        settings,
        tenant_id,
        domain_id,
        connection_id,
        database,
        schema,
        limit=limit,
    )
    return {"runs": runs}


@app.post(
    "/agentic/runs",
    tags=["agentic"],
    summary="Start agentic run",
    description="Start a multi-agent semantic build run. Customer-facing flow enforces one deployment run per tenant/domain; use /workspace/deployments for first build or versioned redeployments.",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "start_minimal": {
                            "summary": "Start run (minimal)",
                            "value": {
                                "tenant_id": "VC_101",
                                "domain_id": "lpg_production_distribution",
                                "mode": "full",
                            },
                        },
                        "start_with_context_and_schema": {
                            "summary": "Start run with context and schema payload",
                            "value": {
                                "tenant_id": "VC_101",
                                "domain_id": "lpg_production_distribution",
                                "schema_ids": ["schema_public"],
                                "context_text": "Plant hierarchy is Zone > Region > Plant. SAP ID is unique per plant.",
                                "schema_name": "public",
                                "schema_payload": {
                                    "tables": [
                                        {
                                            "table": "lpg_plant_operations",
                                            "columns": [
                                                {"name": "sap_id", "data_type": "text"},
                                                {"name": "process_date", "data_type": "date"},
                                                {"name": "production_19kg", "data_type": "numeric"},
                                            ],
                                        }
                                    ]
                                },
                                "mode": "full",
                            },
                        },
                        "start_with_context_ids": {
                            "summary": "Start run with stored context references",
                            "value": {
                                "tenant_id": "VC_101",
                                "domain_id": "lpg_production_distribution",
                                "context_ids": ["ctx_ops_glossary", "ctx_kpi_formulas"],
                                "mode": "full",
                            },
                        },
                        "start_with_runtime_tuning": {
                            "summary": "Start run with performance tuning (single full run)",
                            "value": {
                                "tenant_id": "VC_101",
                                "domain_id": "lpg_production_distribution",
                                "mode": "full",
                                "runtime_tuning": {
                                    "chart_max_charts": 5,
                                    "chart_line_multi_limit": 250,
                                    "join_coverage_max_joins": 3,
                                    "join_coverage_left_sample_limit": 100000,
                                    "join_coverage_right_sample_limit": 100000
                                }
                            }
                        }
                    }
                }
            }
        },
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "queued": {
                                "summary": "Run queued",
                                "value": {"run_id": "run_123", "status": "queued", "job_id": "job_abc"},
                            },
                            "accepted": {
                                "summary": "Run accepted for async processing",
                                "value": {"run_id": "run_9f2d1a8c45e1", "status": "queued", "job_id": "job_2b4d87a1c9d0"},
                            }
                        }
                    }
                }
            },
            "409": {
                "content": {
                    "application/json": {
                        "examples": {
                            "single_run_guardrail": {
                                "summary": "Single deployment run guardrail",
                                "value": {
                                        "detail": {
                                        "message": "Customer flow allows a single deployment run per tenant/domain. Use /workspace/deployments for first build or a new version.",
                                        "tenant_id": "VC_101",
                                        "domain_id": "lpg_production_distribution",
                                        "existing_run_id": "run_1a0f427c86ec",
                                        "existing_status": "completed"
                                    }
                                }
                            }
                        }
                    }
                }
            },
            "400": {
                "content": {
                    "application/json": {
                        "examples": {
                            "schema_required": {
                                "summary": "Scoped schema payload unavailable",
                                "value": {"detail": "schema_payload is required"},
                            }
                        }
                    }
                }
            }
        },
    },
)
def start_agentic_run(payload: dict) -> dict:
    tenant_id = payload.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=400, detail="tenant_id is required")
    domain_id = _resolve_domain_id(tenant_id, payload.get("domain_id"))
    existing = _latest_run_for_scope(tenant_id, domain_id)
    if existing:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Customer flow allows a single deployment run per tenant/domain. Use /workspace/deployments for first build or a new version.",
                "tenant_id": tenant_id,
                "domain_id": domain_id,
                "existing_run_id": existing.get("run_id"),
                "existing_status": existing.get("status"),
            },
        )
    logger.info("agentic.start | tenant=%s domain=%s", tenant_id, domain_id)
    connection_id = payload.get("connection_id")
    database = payload.get("database")
    schema = payload.get("schema_name") or "public"
    if not payload.get("schema_payload"):
        connection_id, database, schema, _ = _resolve_scope_values(tenant_id, domain_id)
        logger.info(
            "agentic.start | loading schema_payload tenant=%s domain=%s connection=%s db=%s schema=%s",
            tenant_id,
            domain_id,
            connection_id,
            database,
            schema,
        )
        schema_payload = load_latest_scan_for_scope(
            settings, tenant_id, domain_id, connection_id, database, schema
        )
        if not schema_payload:
            raise HTTPException(status_code=400, detail="schema_payload is required")
        payload["schema_payload"] = schema_payload
        payload["schema_name"] = schema
    if not connection_id or not database:
        connection_id, database, schema, _ = _resolve_scope_values(tenant_id, domain_id)
    merged_context_text, resolved_context_ids = _merge_context_inputs(
        tenant_id,
        domain_id,
        payload.get("context_text"),
        payload.get("context_ids") or [],
    )
    logger.info(
        "agentic.start | context_present=%s context_ids=%s",
        bool(merged_context_text),
        len(resolved_context_ids),
    )
    # Activate each resolved context for this scope so subsequent conversation
    # messages can find it via list_active_context_ids → business_context_text.
    _run_connection_id = payload.get("connection_id") or connection_id
    _run_database = payload.get("database") or database
    _run_schema = payload.get("schema_name") or schema
    for _ctx_id in resolved_context_ids:
        try:
            set_context_active(
                settings,
                tenant_id=tenant_id,
                domain_id=domain_id,
                context_id=_ctx_id,
                connection_id=_run_connection_id,
                database_name=_run_database,
                schema_name=_run_schema,
                is_active=True,
            )
        except Exception:
            logger.exception(
                "agentic.start.context_activate_failed | tenant_id=%s domain_id=%s context_id=%s",
                tenant_id, domain_id, _ctx_id,
            )
    run_id = create_agent_run(settings, tenant_id, domain_id, status="queued")
    append_agent_run_event(
        settings,
        run_id,
        "PlanningAgent",
        "completed",
        "Plan created",
        {"steps": ["Scan schema", "Build semantics", "Create dashboards"]},
    )
    append_plan_summary(
        settings,
        run_id,
        ["Scan schema", "Build semantics", "Create dashboards"],
    )
    initial_state = {
        "tenant_id": tenant_id,
        "domain_id": domain_id,
        "workflow_mode": payload.get("workflow_mode"),
        "schema_ids": payload.get("schema_ids") or [],
        "context_text": merged_context_text,
        "context_ids": resolved_context_ids,
        "schema_payload": payload.get("schema_payload") or {},
        "schema_name": payload.get("schema_name") or "public",
        "connection_id": payload.get("connection_id") or connection_id,
        "database_name": payload.get("database") or database,
        "runtime_tuning": payload.get("runtime_tuning") or {},
        "scoped_conn": (_sc := _resolve_scoped_conn(tenant_id, domain_id)) and _sc.to_dict(),
    }
    job = create_job(
        settings,
        tenant_id=tenant_id,
        domain_id=domain_id,
        job_type="agentic_run",
        payload={"run_id": run_id, "initial_state": initial_state},
        idempotency_key=None,
    )
    update_agent_run_status(settings, run_id, "queued")
    return {"run_id": run_id, "status": job.get("status", "queued"), "job_id": job.get("job_id")}


def _split_select_items(select_body: str) -> list[str]:
    """Split a SQL SELECT body by top-level commas (respecting parentheses)."""
    items: list[str] = []
    depth = 0
    current: list[str] = []
    for ch in select_body:
        if ch == "(":
            depth += 1
            current.append(ch)
        elif ch == ")":
            depth -= 1
            current.append(ch)
        elif ch == "," and depth == 0:
            items.append("".join(current))
            current = []
        else:
            current.append(ch)
    if current:
        items.append("".join(current))
    return items


def _extract_metric_expr_from_sql(source_sql: str, metric_name: str) -> str | None:
    """
    Extract the aggregate expression for `metric_name` from the SELECT clause of
    `source_sql`.  Returns the expression without the AS alias, with table aliases
    stripped, so it can be dropped into a new query against a different table.

    Example:
        source_sql has:  CASE WHEN SUM(t."total_net_hours") > 0 THEN ...  AS "productivity"
        Returns:         CASE WHEN SUM("total_net_hours") > 0 THEN SUM("total_production") / SUM("total_net_hours") ELSE 0 END
    """
    m = re.search(r"\bSELECT\b(.*?)\bFROM\b", source_sql, re.IGNORECASE | re.DOTALL)
    if not m:
        return None
    select_body = m.group(1)

    _sql_kw = frozenset(
        "CASE WHEN THEN ELSE END SUM AVG MIN MAX COUNT AND OR NOT IF "
        "NULLIF COALESCE ROUND CAST OVER PARTITION BY NULL AS SELECT "
        "FROM WHERE GROUP ORDER HAVING LIMIT DISTINCT IS IN BETWEEN "
        "LIKE DATE_TRUNC DATE_PART EXTRACT ILIKE SIMILAR TO".split()
    )

    def _strip_alias(match: re.Match) -> str:  # type: ignore[type-arg]
        alias = match.group(1)
        if alias.upper() in _sql_kw:
            return match.group(0)
        return match.group(2)

    metric_lower = metric_name.lower()
    for item in _split_select_items(select_body):
        item = item.strip()
        alias_m = re.search(r'\bAS\s+["`]?(\w+)["`]?\s*$', item, re.IGNORECASE)
        if alias_m and alias_m.group(1).lower() == metric_lower:
            expr = item[: alias_m.start()].strip()
            # Strip table alias prefix: t."col" → "col"
            expr = re.sub(r'\b[A-Za-z_]\w*\."(\w+)"', r'"\1"', expr)
            # Strip unquoted alias.col → col (preserving SQL keywords)
            expr = re.sub(r'\b([A-Za-z_]\w*)\.([A-Za-z_]\w*)\b', _strip_alias, expr)
            return expr
    return None


def _execute_passthrough_workspace_query(
    *,
    metric_name: str,
    dimensions: list[str],
    filters: list[dict],
    intelligence_bundle: dict,
    schema_name: str,
    limit: int,
    chart_context: dict | None = None,
    scoped_conn: ScopedConnection | None = None,
) -> "QueryResult":
    """
    Build and execute a direct aggregate SQL query for a raw-column metric
    (metric_raw_column_passthrough mode).  Used when the metric registry is
    empty but scanned model data gives us the table + column information.

    When chart_context is supplied and contains a source SQL, the metric
    expression is extracted from that SQL (preserving the original business
    formula) rather than defaulting to SUM(column).

    Handles the virtual `process_month` dimension by deriving it from the
    table's time_column via DATE_TRUNC.
    """
    model_map = _build_model_intelligence_map(intelligence_bundle)

    # Find the fact table that contains the metric column.
    # Use exact match first, then substring match (e.g. "productivity" → "total_productivity").
    target_table: str | None = None
    target_model: dict = {}
    metric_lower = metric_name.lower()

    for tbl, model in model_map.items():
        numeric_cols = [str(c).lower() for c in (model.get("numeric_columns") or [])]
        if metric_lower in numeric_cols:
            target_table = tbl
            target_model = model
            break
        if any(metric_lower in col or col in metric_lower for col in numeric_cols):
            target_table = tbl
            target_model = model
            break

    # Fallback: first fact table
    if not target_table:
        for tbl, model in model_map.items():
            if str(model.get("model_type") or "").lower() == "fact":
                target_table = tbl
                target_model = model
                break

    if not target_table:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "No fact table found for passthrough metric query",
                "metric": metric_name,
            },
        )

    # Resolve the actual column name: exact → prefix/suffix → first numeric
    numeric_cols_actual = [str(c) for c in (target_model.get("numeric_columns") or [])]
    numeric_cols_lower = [c.lower() for c in numeric_cols_actual]
    actual_metric_col = metric_name  # default — may not exist in table

    if metric_lower in numeric_cols_lower:
        actual_metric_col = numeric_cols_actual[numeric_cols_lower.index(metric_lower)]
    else:
        # Prefer columns that contain the metric name (e.g. "total_productivity")
        # scored: "total_" prefix < exact suffix < contains
        candidates = [
            (col, col_l)
            for col, col_l in zip(numeric_cols_actual, numeric_cols_lower)
            if metric_lower in col_l or col_l in metric_lower
        ]
        if candidates:
            # Prefer the column whose name ends with the metric name (most specific)
            candidates.sort(key=lambda x: (not x[1].endswith(metric_lower), len(x[1])))
            actual_metric_col = candidates[0][0]

    time_col = str(target_model.get("time_column") or "")
    qualified_table = f"{schema_name}.{target_table}" if schema_name else target_table

    # Build SELECT / GROUP BY
    select_parts: list[str] = []
    group_parts: list[str] = []
    out_dims: list[str] = []

    for dim in dimensions:
        if dim == "process_month" and time_col:
            select_parts.append(f"DATE_TRUNC('month', {time_col})::DATE AS process_month")
            group_parts.append(f"DATE_TRUNC('month', {time_col})::DATE")
            out_dims.append("process_month")
        else:
            select_parts.append(dim)
            group_parts.append(dim)
            out_dims.append(dim)

    # Prefer the formula from the source chart SQL (preserves business logic like CASE WHEN).
    # Fall back to naive SUM(column) only when no chart context is available.
    source_metric_expr: str | None = None
    if chart_context:
        source_sql = (chart_context.get("sql") or "").strip()
        if source_sql:
            source_metric_expr = _extract_metric_expr_from_sql(source_sql, metric_name)

    if source_metric_expr:
        logger.info(
            "passthrough_query | using source chart formula for %s: %s",
            metric_name, source_metric_expr[:120],
        )
        select_parts.append(f"{source_metric_expr} AS {metric_name}")
    else:
        logger.info(
            "passthrough_query | no source formula found for %s, falling back to SUM(%s)",
            metric_name, actual_metric_col,
        )
        select_parts.append(f"SUM({actual_metric_col}) AS {metric_name}")

    # WHERE clause
    where_clauses: list[str] = []
    params: list[Any] = []
    for flt in filters:
        field = flt.get("field")
        op = str(flt.get("operator") or "=")
        value = flt.get("value")
        if field and value is not None and op in {"=", "!=", ">", ">=", "<", "<=", "ILIKE"}:
            where_clauses.append(f"{field} {op} %s")
            params.append(value)

    sql_parts = [f"SELECT {', '.join(select_parts)}", f"FROM {qualified_table}"]
    if where_clauses:
        sql_parts.append("WHERE " + " AND ".join(where_clauses))
    if group_parts:
        sql_parts.append("GROUP BY " + ", ".join(group_parts))
    sql_parts.append("ORDER BY " + (group_parts[0] if group_parts else "1"))
    sql_parts.append(f"LIMIT {limit}")
    sql_text = "\n".join(sql_parts)

    rows = run_query(settings, sql_text, params or None, scoped_conn=scoped_conn)
    return QueryResult(
        metrics=[metric_name],
        dimensions=out_dims,
        sql=sql_text,
        rows=[dict(r) for r in (rows or [])],
    )


def _workspace_query_response(
    *,
    tenant_id: str,
    domain_id: str,
    run_id: str | None,
    question: str,
    conversation_id: str | None = None,
    chart_context: dict | None = None,
    chart_followup_context: dict | None = None,
    raw_user_query: str | None = None,
    conversation_memory_text: str | None = None,
    business_context_text: str | None = None,
    metrics: list[str] | None = None,
    dimensions: list[str] | None = None,
    limit: int = 200,
) -> tuple[dict, str, dict, dict]:
    connection_id, database_name, schema_name, _ = _resolve_scope_values(tenant_id, domain_id)
    intelligence_bundle = _load_run_scoped_intelligence(
        tenant_id=tenant_id,
        domain_id=domain_id,
        run_id=run_id,
        connection_id=connection_id,
        database_name=database_name,
        schema_name=schema_name,
    )
    # ── LLM-first SQL agent path ─────────────────────────────────────────────
    # When CONVERSATION_LLM_SQL_MODE=true the LLM writes complete SQL from
    # business context + table schemas + source chart SQL.  Falls back silently
    # to the deterministic pipeline on any failure.
    from services.ai.llm_sql_direct import is_llm_sql_mode_enabled, llm_direct_sql
    if is_llm_sql_mode_enabled():
        _eff_schema = schema_name or settings.db_schema
        _llm_result = llm_direct_sql(
            user_query=raw_user_query or question,
            conversation_memory=conversation_memory_text,
            business_context=business_context_text,
            intelligence_bundle=intelligence_bundle or {},
            chart_context=chart_context,
            chart_followup_context=chart_followup_context,
            schema_name=_eff_schema,
            settings=settings,
            scoped_conn=_resolve_scoped_conn(tenant_id, domain_id),
        )
        if _llm_result:
            try:
                _llm_metrics: list[str] = list(_llm_result.get("metrics") or [])
                _llm_dims: list[str] = list(_llm_result.get("dimensions") or [])
                from decimal import Decimal as _Decimal
                import os as _os
                _sq_timeout_ms = int(_os.getenv("LLM_SQL_QUERY_TIMEOUT_MS", "15000"))
                _llm_raw_rows = [
                    {k: float(v) if isinstance(v, _Decimal) else v for k, v in dict(r).items()}
                    for r in (run_query(
                        settings,
                        _llm_result["sql"],
                        [],
                        scoped_conn=_resolve_scoped_conn(tenant_id, domain_id),
                        statement_timeout_ms=_sq_timeout_ms,
                    ) or [])
                ]
                _llm_qr = QueryResult(
                    metrics=_llm_metrics,
                    dimensions=_llm_dims,
                    sql=_llm_result["sql"],
                    rows=_llm_raw_rows,
                )
                _llm_metric_name = _llm_metrics[0] if _llm_metrics else None
                _llm_chart_type, _llm_chart_payload, _ = build_workspace_chart(
                    rows=_llm_qr.rows,
                    metric_name=_llm_metric_name,
                    metric_names=_llm_metrics,
                    dimensions=_llm_dims,
                    preferred_chart_type=_llm_result.get("chart_type"),
                )
                _llm_title = str(
                    _llm_result.get("title")
                    or workspace_chart_title(_llm_metric_name, _llm_dims)
                )
                _llm_dashboard_title = (
                    f"{str(domain_id).replace('_', ' ').replace('-', ' ').title()} Dashboard"
                )
                _llm_conv_plan = {
                    "sql_mode": "llm_agent",
                    "reasoning": _llm_result.get("reasoning"),
                    "model": os.getenv("CONVERSATION_LLM_SQL_MODEL") or settings.openai_model,
                }
                _llm_followup: dict | None = None
                if chart_context:
                    _llm_followup = {
                        "source_chart_id": chart_context.get("source_chart_id"),
                        "follow_up_intent": "llm_agent",
                        "selected_context": {
                            k: v for k, v in (chart_followup_context or {}).items()
                            if k != "chart_id" and v not in (None, "", [])
                        },
                    }
                _llm_response_payload: dict[str, Any] = {
                    "metrics":          _llm_qr.metrics,
                    "dimensions":       _llm_qr.dimensions,
                    "chart_id":         None,
                    "chart_type":       _llm_chart_type,
                    "chart_title":      _llm_title,
                    "dashboard_title":  _llm_dashboard_title,
                    "chart_payload":    _llm_chart_payload.get("chart_payload") if _llm_chart_payload else None,
                    "data":             _llm_chart_payload.get("data") if _llm_chart_payload else _llm_qr.rows,
                    "sql":              _llm_qr.sql,
                    "rows":             _llm_qr.rows,
                    "lineage":          None,
                    "artifact_lineage": None,
                    "conversation_plan": _llm_conv_plan,
                    "chart_followup":   _llm_followup,
                }
                _persisted_llm_id = _persist_workspace_chart_artifact(
                    tenant_id=tenant_id,
                    domain_id=domain_id,
                    question=question,
                    compiled_request={"dimensions": _llm_dims, "filters": [], "limit": limit},
                    response_payload=_llm_response_payload,
                    conversation_id=conversation_id,
                )
                if _persisted_llm_id:
                    _llm_response_payload["chart_id"] = _persisted_llm_id
                    if isinstance(_llm_followup, dict):
                        _llm_followup["derived_chart_id"] = _persisted_llm_id
                        _llm_response_payload["chart_followup"] = _llm_followup
                _llm_label = ", ".join(_llm_metrics[:2]) if _llm_metrics else "requested metrics"
                _llm_assistant_text = f"Returned {len(_llm_qr.rows)} rows for {_llm_label}."
                _llm_summary = {
                    "text": _llm_assistant_text,
                    "row_count": len(_llm_qr.rows),
                    "metrics": _llm_metrics,
                    "dimensions": _llm_dims,
                    "lineage": None,
                    "artifact_lineage": None,
                    "conversation_plan": _llm_conv_plan,
                    "chart_followup": _llm_response_payload.get("chart_followup"),
                }
                _llm_inference = {
                    "text": "Use filters or follow-up prompts to drill deeper.",
                    "confidence": 0.8 if _llm_qr.rows else 0.4,
                    "artifact_lineage": None,
                    "conversation_plan": _llm_conv_plan,
                    "chart_followup": _llm_response_payload.get("chart_followup"),
                }
                logger.info(
                    "[llm_sql] pipeline bypassed | rows=%d metrics=%s dims=%s",
                    len(_llm_qr.rows), _llm_metrics, _llm_dims,
                )
                return _llm_response_payload, _llm_assistant_text, _llm_summary, _llm_inference
            except Exception as _llm_exc:
                logger.warning("[llm_sql] execution/build failed, falling back: %s", _llm_exc)
        else:
            logger.info("[llm_sql] LLM returned no result — falling back to pipeline")
            # When LLM mode is enabled and LLM returned None, raise immediately
            # rather than letting the semantic pipeline attempt cross-table joins
            # it cannot resolve (e.g. m60_level_metadata has no join definition).
            raise HTTPException(
                status_code=400,
                detail={
                    "message": "Could not generate SQL for this question. The query may span multiple tables that cannot be joined automatically.",
                    "hint": "Try rephrasing the question, or ensure the LLM SQL mode is properly configured (CONVERSATION_LLM_SQL_MODE=true).",
                },
            )
    # ── end LLM-first path ───────────────────────────────────────────────────

    scoped_metric_rows = (intelligence_bundle or {}).get("metrics") or []
    metric_catalog = _catalog_from_registry_rows(scoped_metric_rows, catalog.dimensions)
    allowed_dimensions = (intelligence_bundle or {}).get("dimension_candidates") or _dimension_candidates_for_scope(
        tenant_id,
        domain_id,
        connection_id,
        database_name,
        schema_name,
    )
    glossary = (intelligence_bundle or {}).get("glossary") or fetch_glossary_terms(settings, tenant_id, domain_id)
    effective_metrics = list(metrics or [])
    effective_dimensions = list(dimensions or [])
    chart_followup_meta: dict[str, Any] | None = None
    chart_followup_plan_patch: dict[str, Any] | None = None
    if chart_context:
        effective_metrics, effective_dimensions, chart_followup_plan_patch, chart_followup_meta = _chart_context_explicit_overrides(
            question=question,
            chart_context=chart_context,
            glossary=glossary,
            hierarchies=(intelligence_bundle or {}).get("hierarchies") or [],
            allowed_dimensions=allowed_dimensions,
            explicit_metrics=metrics,
            explicit_dimensions=dimensions,
        )
    active_semantic_state = load_active_semantic_state(
        settings,
        tenant_id=tenant_id,
        domain_id=domain_id,
        connection_id=connection_id,
        database_name=database_name,
        schema_name=schema_name,
    )
    if active_semantic_state:
        glossary = merge_semantic_glossary(glossary, active_semantic_state)
        join_constraints = semantic_join_constraints(active_semantic_state)
        constrained_joins, removed_joins = apply_join_constraints_to_edges(
            (intelligence_bundle or {}).get("joins") or [],
            join_constraints,
        )
        if removed_joins and intelligence_bundle is not None:
            intelligence_bundle["joins"] = constrained_joins
            logger.info(
                "workspace.semantic_constraints | removed_joins=%s constraints=%s",
                len(removed_joins),
                join_constraints,
            )
    raw_llm_plan = interpret_workspace_query(
        question=question,
        metric_catalog=metric_catalog,
        allowed_dimensions=allowed_dimensions,
        glossary=glossary,
        settings=settings,
    )
    if chart_followup_plan_patch:
        raw_llm_plan.update(chart_followup_plan_patch)

    # Runtime metric synthesis — if the LLM proposed metric names that are not
    # in the current catalog (missed during onboarding or not yet certified),
    # attempt to synthesize them from the profiling artifact and inject into
    # the catalog before validation runs. Synthesized metrics are persisted as
    # 'suggested' so future queries find them without re-synthesis.
    _raw_candidates: list[str] = list(
        (raw_llm_plan.get("metric_candidates") or [])
        + (raw_llm_plan.get("metrics") or [])
        + list(effective_metrics or [])
    )
    if _raw_candidates:
        from services.ai.runtime_metric_synthesis import try_augment_catalog_from_profiling
        metric_catalog = try_augment_catalog_from_profiling(
            settings=settings,
            metric_catalog=metric_catalog,
            metric_candidates=_raw_candidates,
            tenant_id=tenant_id,
            domain_id=domain_id,
            connection_id=connection_id or "",
            database_name=database_name or "",
            schema_name=schema_name or settings.db_schema,
            source_run_id=run_id,
        )

    validated_plan = validate_workspace_query_plan(
        question=question,
        raw_plan=raw_llm_plan,
        metric_catalog=metric_catalog,
        allowed_dimensions=allowed_dimensions,
        explicit_metrics=effective_metrics,
        explicit_dimensions=effective_dimensions,
    )
    # When the user said "instead of date/time", strip any auto-injected time dimensions
    # (the planner may re-add process_month via time_grain logic even if we excluded it above).
    _instead_of_time = bool(re.search(
        r"\binstead\s+of\s+(date|time|month|day|week|period|process_month|process_date|the\s+date|the\s+time)\b",
        question.lower(),
    ))
    if _instead_of_time and chart_context:
        plan_dims = validated_plan.get("dimensions") or []
        plan_dims = [d for d in plan_dims if not _is_time_dimension_name(d)]
        validated_plan["dimensions"] = plan_dims
    if chart_followup_meta:
        merged_filters = list(validated_plan.get("filters") or [])
        for flt in chart_followup_meta.get("filter_hints") or []:
            if not any(
                str(existing.get("field")) == str(flt.get("field"))
                and str(existing.get("operator")) == str(flt.get("operator"))
                and str(existing.get("value")) == str(flt.get("value"))
                for existing in merged_filters
                if isinstance(existing, dict)
            ):
                merged_filters.append(flt)
        validated_plan["filters"] = merged_filters
        validation_warnings = list(validated_plan.get("validation_warnings") or [])
        validation_warnings.extend(chart_followup_meta.get("warnings") or [])
        validated_plan["validation_warnings"] = list(dict.fromkeys(validation_warnings))
        validated_plan["chart_followup"] = {
            "follow_up_intent": chart_followup_meta.get("follow_up_intent"),
            "accepted_transformations": chart_followup_meta.get("accepted_transformations") or [],
            "rejected_transformations": chart_followup_meta.get("rejected_transformations") or [],
        }
    if not validated_plan.get("metric_name"):
        raise HTTPException(
            status_code=400,
            detail={
                "message": "No metrics resolved for workspace conversation",
                "question": question,
                "conversation_plan": conversation_plan_diagnostics(
                    raw_llm_plan=raw_llm_plan,
                    validated_plan=validated_plan,
                ),
            },
        )
    compiled_request = compile_workspace_query_plan(
        tenant_id=tenant_id,
        domain_id=domain_id,
        run_id=run_id,
        validated_plan=validated_plan,
        limit=limit,
    )
    _is_passthrough = any(
        str(w).startswith("metric_raw_column_passthrough:")
        for w in (validated_plan.get("validation_warnings") or [])
    )
    if _is_passthrough:
        _, _, schema_name, _ = _resolve_scope_values(tenant_id, domain_id)
        query_result = _execute_passthrough_workspace_query(
            metric_name=validated_plan["metric_name"],
            dimensions=validated_plan.get("dimensions") or [],
            filters=validated_plan.get("filters") or [],
            intelligence_bundle=intelligence_bundle,
            schema_name=schema_name or "",
            limit=limit,
            chart_context=chart_context,
            scoped_conn=_resolve_scoped_conn(tenant_id, domain_id),
        )
    else:
        try:
            query_result = query(
                QueryRequest(**compiled_request)
            )
        except (ValueError, HTTPException) as _qe:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": str(_qe),
                    "hint": "The semantic pipeline could not resolve a join path for the requested tables. "
                            "Try rephrasing your question or ensure tables are connected via join definitions.",
                    "question": question,
                },
            ) from _qe
    metric_name = (query_result.metrics or [None])[0]
    chart_type, chart_payload, chart_warnings = build_workspace_chart(
        rows=query_result.rows,
        metric_name=metric_name,
        metric_names=query_result.metrics or [],
        dimensions=query_result.dimensions,
        response_mode=validated_plan.get("response_mode"),
        preferred_chart_type=(chart_followup_meta or {}).get("requested_chart_type") or validated_plan.get("chart_type"),
    )
    if chart_warnings:
        validated_plan["validation_warnings"] = list(dict.fromkeys((validated_plan.get("validation_warnings") or []) + chart_warnings))
        if chart_type == "table":
            validated_plan["chart_type"] = "table"
    chart_title = workspace_chart_title(metric_name, query_result.dimensions)
    dashboard_title = f"{str(domain_id).replace('_', ' ').replace('-', ' ').title()} Dashboard"
    conversation_plan = conversation_plan_diagnostics(
        raw_llm_plan=raw_llm_plan,
        validated_plan=validated_plan,
        compiled_sql_preview=query_result.sql,
    )
    conversation_plan["sql_mode"] = "pipeline"
    if chart_followup_meta:
        conversation_plan["chart_followup"] = {
            "source_chart_id": chart_followup_meta.get("source_chart_id"),
            "follow_up_intent": chart_followup_meta.get("follow_up_intent"),
            "selected_context": chart_followup_meta.get("selected_context") or {},
            "filter_hints": chart_followup_meta.get("filter_hints") or [],
            "accepted_transformations": chart_followup_meta.get("accepted_transformations") or [],
            "rejected_transformations": chart_followup_meta.get("rejected_transformations") or [],
            "warnings": chart_followup_meta.get("warnings") or [],
        }
    transformation_summary = _build_chart_followup_transformation_summary(
        validated_plan=validated_plan,
        chart_followup_meta=chart_followup_meta,
    )
    if chart_followup_meta:
        conversation_plan["chart_followup"]["transformation_summary"] = transformation_summary
    llm_followup_advisory = _llm_review_chart_followup(
        question=question,
        chart_context=chart_context,
        chart_followup_meta=chart_followup_meta,
        validated_plan=validated_plan,
        query_result=query_result,
    )
    if chart_followup_meta and isinstance(llm_followup_advisory, dict) and llm_followup_advisory:
        conversation_plan["chart_followup"]["llm_advisory"] = llm_followup_advisory

    merged_chart_followup = {
        **(chart_context or {}),
        **(chart_followup_meta or {}),
    } if chart_context or chart_followup_meta else None
    if merged_chart_followup is not None:
        merged_chart_followup["transformation_summary"] = transformation_summary
        merged_chart_followup["derived_chart_id"] = query_result.chart_id
        if isinstance(llm_followup_advisory, dict) and llm_followup_advisory:
            merged_chart_followup["llm_advisory"] = llm_followup_advisory

    response_payload = {
        "metrics": query_result.metrics,
        "dimensions": query_result.dimensions,
        "chart_id": query_result.chart_id,
        "chart_type": chart_type,
        "chart_title": chart_title,
        "dashboard_title": dashboard_title,
        "chart_payload": chart_payload.get("chart_payload") if chart_payload else None,
        "data": chart_payload.get("data") if chart_payload else query_result.rows,
        "sql": query_result.sql,
        "rows": query_result.rows,
        "lineage": query_result.lineage,
        "artifact_lineage": query_result.artifact_lineage,
        "conversation_plan": conversation_plan,
        "chart_followup": merged_chart_followup,
    }
    persisted_chart_id = _persist_workspace_chart_artifact(
        tenant_id=tenant_id,
        domain_id=domain_id,
        question=question,
        compiled_request=compiled_request,
        response_payload=response_payload,
        conversation_id=conversation_id,
    )
    if persisted_chart_id:
        response_payload["chart_id"] = persisted_chart_id
        if isinstance(response_payload.get("conversation_plan"), dict):
            response_payload["conversation_plan"]["chart_id"] = persisted_chart_id
        if isinstance(response_payload.get("chart_followup"), dict):
            response_payload["chart_followup"]["derived_chart_id"] = persisted_chart_id
    metric_label = ", ".join(query_result.metrics[:2]) if query_result.metrics else "requested metrics"
    assistant_text = f"Returned {len(query_result.rows)} rows for {metric_label}."
    summary_json = {
        "text": assistant_text,
        "row_count": len(query_result.rows),
        "metrics": query_result.metrics,
        "dimensions": query_result.dimensions,
        "lineage": query_result.lineage,
        "artifact_lineage": query_result.artifact_lineage,
        "conversation_plan": conversation_plan,
        "chart_followup": response_payload.get("chart_followup"),
    }
    inference_json = {
        "text": "Use filters or follow-up prompts to drill deeper by region, plant, or time period.",
        "confidence": 0.75 if query_result.rows else 0.4,
        "artifact_lineage": query_result.artifact_lineage,
        "conversation_plan": conversation_plan,
        "chart_followup": response_payload.get("chart_followup"),
    }
    return response_payload, assistant_text, summary_json, inference_json


def _workspace_llm_stream_enabled() -> bool:
    return bool(getattr(settings, "openai_api_key", None))


def _build_client_response(response_payload: dict) -> dict:
    """
    Slim response returned to the UI — only keys the client actually needs.
    Internal fields (conversation_plan, lineage, summary_json, data duplicate,
    dashboard_title) are kept in response_payload for persistence but not sent
    over the wire.
    """
    followup = response_payload.get("chart_followup")
    slim_followup: dict | None = None
    if isinstance(followup, dict):
        slim_followup = {
            k: followup[k]
            for k in ("source_chart_id", "derived_chart_id", "follow_up_intent", "selected_context")
            if k in followup
        }
    return {
        "chart_id":      response_payload.get("chart_id"),
        "chart_type":    response_payload.get("chart_type"),
        "chart_title":   response_payload.get("chart_title"),
        "chart_payload": response_payload.get("chart_payload"),
        "sql":           response_payload.get("sql"),
        "metrics":       response_payload.get("metrics"),
        "dimensions":    response_payload.get("dimensions"),
        "rows":          response_payload.get("rows"),
        "chart_followup": slim_followup,
        "data_quality":  response_payload.get("data_quality"),
    }


def _load_chart_followup_prompt(name: str) -> str:
    return (_CHART_FOLLOWUP_PROMPTS_DIR / name).read_text(encoding="utf-8")


def _workspace_llm_json_response(
    *,
    system_prompt: str,
    user_payload: dict[str, Any],
    model_env_key: str,
    timeout_env_key: str,
) -> dict[str, Any] | None:
    if not getattr(settings, "openai_api_key", None):
        return None
    model = os.getenv(model_env_key, getattr(settings, "openai_model", "gpt-4o-mini"))
    timeout_sec = int(os.getenv(timeout_env_key, "30"))
    request = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(
            {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": json.dumps(user_payload, default=str)},
                ],
                "temperature": 0.1,
                "response_format": {"type": "json_object"},
            },
            default=str,
        ).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {settings.openai_api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_sec) as response:
            body = json.loads(response.read().decode("utf-8"))
        return json.loads(body["choices"][0]["message"]["content"])
    except Exception:
        logger.warning("workspace.chart_followup_llm_failed", exc_info=True)
        return None


def _llm_review_chart_followup(
    *,
    question: str,
    chart_context: dict[str, Any] | None,
    chart_followup_meta: dict[str, Any] | None,
    validated_plan: dict[str, Any],
    query_result: Any,
) -> dict[str, Any] | None:
    if not chart_followup_meta:
        return None
    return _workspace_llm_json_response(
        system_prompt=_load_chart_followup_prompt("review.md"),
        user_payload={
            "question": question,
            "source_chart": {
                "source_chart_id": (chart_context or {}).get("source_chart_id"),
                "chart_title": (chart_context or {}).get("chart_title"),
                "chart_type": (chart_context or {}).get("chart_type"),
                "metrics": (chart_context or {}).get("metrics") or [],
                "dimensions": (chart_context or {}).get("dimensions") or [],
            },
            "chart_followup": {
                "follow_up_intent": chart_followup_meta.get("follow_up_intent"),
                "accepted_transformations": chart_followup_meta.get("accepted_transformations") or [],
                "rejected_transformations": chart_followup_meta.get("rejected_transformations") or [],
                "warnings": chart_followup_meta.get("warnings") or [],
                "requested_chart_type": chart_followup_meta.get("requested_chart_type"),
            },
            "validated_plan": {
                "metric_name": validated_plan.get("metric_name"),
                "dimensions": validated_plan.get("dimensions") or [],
                "chart_type": validated_plan.get("chart_type"),
                "time_grain": validated_plan.get("time_grain"),
                "validation_warnings": validated_plan.get("validation_warnings") or [],
            },
            "result_shape": {
                "chart_id": getattr(query_result, "chart_id", None),
                "metrics": getattr(query_result, "metrics", None) or [],
                "dimensions": getattr(query_result, "dimensions", None) or [],
                "row_count": len(getattr(query_result, "rows", None) or []),
            },
        },
        model_env_key="WORKSPACE_CHART_FOLLOWUP_REVIEW_MODEL",
        timeout_env_key="WORKSPACE_CHART_FOLLOWUP_REVIEW_TIMEOUT_SEC",
    )


def _workspace_narration_prompt(question: str, response_payload: dict, summary_json: dict) -> tuple[str, str]:
    safe_rows = (response_payload.get("rows") or [])[:5]
    payload = {
        "question": question,
        "metrics": response_payload.get("metrics") or [],
        "dimensions": response_payload.get("dimensions") or [],
        "row_count": len(response_payload.get("rows") or []),
        "sample_rows": safe_rows,
        "base_summary": summary_json.get("text"),
        "chart_followup": response_payload.get("chart_followup"),
    }
    system_prompt = (
        "You are an analytics assistant. "
        "Respond with concise factual analysis based only on provided data. "
        "Do not invent numbers."
    )
    user_prompt = (
        "Write a concise answer for the user query using the analytics payload below.\n"
        f"{json.dumps(payload, default=str)}"
    )
    return system_prompt, user_prompt


def _extract_chart_followup_context(payload: dict | None) -> dict[str, Any]:
    data = payload or {}
    chart_id = str(data.get("chart_id") or "").strip()
    context: dict[str, Any] = {}
    if chart_id:
        context["chart_id"] = chart_id
    for key in ("selected_point", "selected_series", "selected_category", "selected_time_value"):
        value = data.get(key)
        if value not in (None, "", []):
            context[key] = value
    return context


def _resolve_chart_conversation_context(
    *,
    tenant_id: str,
    domain_id: str,
    chart_id: str | None,
    conversation_id: str | None = None,
) -> dict[str, Any] | None:
    resolved_chart_id = str(chart_id or "").strip()
    if not resolved_chart_id:
        return None
    chart_row = get_chart_request(settings, resolved_chart_id)
    if not chart_row:
        raise HTTPException(status_code=404, detail=f"Chart not found: {resolved_chart_id}")
    if str(chart_row.get("tenant_id") or "").strip() != str(tenant_id or "").strip():
        raise HTTPException(status_code=400, detail="chart_id does not belong to the current tenant")
    row_domain = str(chart_row.get("domain_id") or "").strip()
    if row_domain and row_domain != str(domain_id or "").strip():
        raise HTTPException(status_code=400, detail="chart_id does not belong to the current domain")
    if conversation_id:
        try:
            append_chart_conversation_id(settings, resolved_chart_id, conversation_id)
        except Exception:
            logger.exception("chart.append_conversation_id_failed | chart_id=%s conversation_id=%s", resolved_chart_id, conversation_id)
    query_payload = dict(chart_row.get("query_payload") or {})
    # Prefer source_dimensions (real SQL columns) over dimensions (may contain chart aliases
    # like "category" which are not actual column names and will be dropped as non-dimension filters).
    raw_dims = query_payload.get("source_dimensions") or query_payload.get("dimensions") or []
    dimensions = raw_dims if isinstance(raw_dims, list) else []
    # For old charts that only stored generic aliases (e.g. ["category"]), resolve the real
    # column name from the chart SQL. Two passes:
    # 1. Explicit alias: `zone AS "category"` → replace "category" with "zone".
    # 2. GROUP BY columns: if a dimension is still unresolved (generic alias like "category"),
    #    replace it in order with GROUP BY columns from the SQL.
    chart_sql = str(chart_row.get("sql") or "")
    if chart_sql and dimensions:
        _alias_re = re.compile(
            r'\b([a-zA-Z_][a-zA-Z0-9_]*)\s+AS\s+"?([a-zA-Z_][a-zA-Z0-9_]*)"?',
            re.IGNORECASE,
        )
        sql_alias_map = {alias.lower(): col for col, alias in _alias_re.findall(chart_sql)}
        dimensions = [sql_alias_map.get(d.lower(), d) for d in dimensions]
        # Pass 2: still-unresolved generic aliases → replace with GROUP BY columns in order
        _generic_aliases = {"category", "dimension", "label", "name", "group", "series"}
        unresolved = [i for i, d in enumerate(dimensions) if d.lower() in _generic_aliases]
        if unresolved:
            _groupby_re = re.compile(r'GROUP\s+BY\s+(.*?)(?:ORDER\s+BY|LIMIT|$)', re.IGNORECASE | re.DOTALL)
            gb_match = _groupby_re.search(chart_sql)
            if gb_match:
                gb_cols = [
                    c.strip().split(".")[-1].strip('"').strip()
                    for c in gb_match.group(1).split(",")
                    if c.strip()
                ]
                for idx, pos in enumerate(unresolved):
                    if idx < len(gb_cols):
                        dimensions[pos] = gb_cols[idx]
    metrics = query_payload.get("metrics") if isinstance(query_payload.get("metrics"), list) else []
    return {
        "mode": "chart_scoped",
        "source_chart_id": resolved_chart_id,
        "chart_title": query_payload.get("chart_title") or chart_row.get("question"),
        "dashboard_title": query_payload.get("dashboard_title"),
        "chart_type": chart_row.get("chart_type"),
        "metrics": metrics,
        "dimensions": dimensions,
        "sql": chart_row.get("sql"),
        "query_payload": query_payload,
        "status": chart_row.get("status"),
    }


def _chart_context_question_suffix(
    question: str,
    chart_context: dict[str, Any] | None,
    selected_context: dict[str, Any] | None,
) -> str:
    if not chart_context:
        return question
    suffix_payload = {
        "mode": "chart_followup",
        "source_chart_id": chart_context.get("source_chart_id"),
        "chart_title": chart_context.get("chart_title"),
        "dashboard_title": chart_context.get("dashboard_title"),
        "chart_type": chart_context.get("chart_type"),
        "metrics": chart_context.get("metrics") or [],
        "dimensions": chart_context.get("dimensions") or [],
        "selected_context": selected_context or {},
    }
    return f"{question}\n\nChart context: {json.dumps(suffix_payload, default=str)}"


def _classify_chart_followup_intent(question: str, chart_context: dict[str, Any] | None) -> str:
    del chart_context
    lowered = str(question or "").lower()
    if any(token in lowered for token in ("why ", "why is", "why did", "explain", "driver", "spike", "drop")):
        return "explain_point_or_segment"
    if "roll up" in lowered or "summary by" in lowered:
        return "roll_up"
    # "instead of" means replace a dimension — not a hierarchical drill-down
    if "instead of" in lowered:
        return "regenerate_with_adjustment"
    if "drill" in lowered or "break this by" in lowered or re.search(r"\bby\s+[a-z]", lowered):
        return "drill_down"
    if any(token in lowered for token in ("exclude ", "without ", "remove ", "except ")):
        return "remove_filter"
    if any(token in lowered for token in ("only ", "for ", "where ", "filter ", "include ")):
        return "add_filter"
    if any(token in lowered for token in ("top ", "bottom ", "rank ", "highest ", "lowest ")):
        return "rank_or_top_n"
    if any(token in lowered for token in ("daily", "by day", "monthly", "by month", "weekly", "by week")):
        return "change_grain"
    if any(token in lowered for token in ("bar chart", "line chart", "pie chart", "split by", "share instead")):
        return "change_chart_type"
    return "regenerate_with_adjustment"


def _requested_time_grain_from_question(question: str) -> str | None:
    lowered = str(question or "").lower()
    if "by day" in lowered or "daily" in lowered:
        return "day"
    if "by week" in lowered or "weekly" in lowered:
        return "week"
    if "by month" in lowered or "monthly" in lowered:
        return "month"
    return None


def _requested_chart_type_from_question(question: str) -> tuple[str | None, str | None]:
    lowered = str(question or "").lower()
    if "stacked area" in lowered:
        return "stacked_area", "show as stacked area chart"
    if "area chart" in lowered or "area instead" in lowered:
        return "area", "show as area chart"
    if "donut chart" in lowered or "doughnut chart" in lowered or "donut instead" in lowered:
        return "donut", "convert to donut chart"
    if "horizontal bar" in lowered or "horizontal chart" in lowered:
        return "horizontal_bar", "show as horizontal bar chart"
    if "share instead" in lowered or "share chart" in lowered or "pie chart" in lowered or "pie instead" in lowered:
        return "pie", "convert to share view"
    if "stacked" in lowered:
        return "stacked_bar", "show as stacked comparison"
    if "grouped bar" in lowered or "clustered bar" in lowered or "clustered column" in lowered:
        return "grouped_bar", "show as grouped comparison"
    if "bar chart" in lowered or "bar instead" in lowered or "column chart" in lowered:
        return "bar", "show as bar chart"
    if "line chart" in lowered or "line instead" in lowered or "trend line" in lowered:
        return "line", "show as line chart"
    return None, None


def _norm_followup_name(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")


def _is_time_dimension_name(value: str | None) -> bool:
    normalized = _norm_followup_name(value)
    if not normalized:
        return False
    if normalized in {"date", "day", "week", "month", "quarter", "year", "period"}:
        return True
    return any(token in normalized for token in ("date", "day", "week", "month", "quarter", "year", "period"))


def _hierarchy_level_sequences(hierarchies: list[dict[str, Any]] | None) -> list[list[str]]:
    sequences: list[list[str]] = []
    for item in hierarchies or []:
        if not isinstance(item, dict):
            continue
        levels = [str(level).strip() for level in (item.get("levels") or []) if str(level).strip()]
        if levels:
            sequences.append(levels)
    return sequences


def _resolve_hierarchy_transition(
    *,
    current_dimensions: list[str],
    requested_dimensions: list[str],
    hierarchies: list[dict[str, Any]] | None,
    allowed_dimensions: list[str],
    direction: str,
) -> tuple[list[str] | None, str | None]:
    allowed_lookup = {_norm_followup_name(name): str(name) for name in (allowed_dimensions or []) if str(name).strip()}
    time_dimensions = [str(name) for name in current_dimensions if _is_time_dimension_name(name)]
    business_dimensions = [str(name) for name in current_dimensions if not _is_time_dimension_name(name)]
    normalized_current = [_norm_followup_name(name) for name in business_dimensions if _norm_followup_name(name)]
    normalized_requested = [_norm_followup_name(name) for name in requested_dimensions if _norm_followup_name(name)]
    hierarchy_sequences = _hierarchy_level_sequences(hierarchies)
    if not normalized_current:
        return None, "invalid_chart_followup_dimension"

    # First honor an explicitly requested valid hierarchy level.
    for sequence in hierarchy_sequences:
        norm_sequence = [_norm_followup_name(level) for level in sequence]
        current_idx = next((idx for idx, name in enumerate(norm_sequence) if name in normalized_current), None)
        if current_idx is None:
            continue
        for requested_name in normalized_requested:
            if requested_name not in norm_sequence:
                continue
            requested_idx = norm_sequence.index(requested_name)
            if direction == "down" and requested_idx > current_idx:
                resolved = allowed_lookup.get(requested_name)
                return (time_dimensions + [resolved] if resolved else None), None if resolved else "invalid_chart_followup_dimension"
            if direction == "up" and requested_idx < current_idx:
                resolved = allowed_lookup.get(requested_name)
                return (time_dimensions + [resolved] if resolved else None), None if resolved else "invalid_chart_followup_dimension"
            return None, "invalid_chart_followup_dimension"

    # Otherwise move one level along a known hierarchy.
    for sequence in hierarchy_sequences:
        norm_sequence = [_norm_followup_name(level) for level in sequence]
        current_idx = next((idx for idx, name in enumerate(norm_sequence) if name in normalized_current), None)
        if current_idx is None:
            continue
        target_idx = current_idx + 1 if direction == "down" else current_idx - 1
        if 0 <= target_idx < len(norm_sequence):
            resolved = allowed_lookup.get(norm_sequence[target_idx])
            if resolved:
                return time_dimensions + [resolved], None
        return None, "invalid_chart_followup_dimension"
    return None, "invalid_chart_followup_dimension"


def _chart_context_explicit_overrides(
    *,
    question: str,
    chart_context: dict[str, Any] | None,
    glossary: list[dict] | None,
    hierarchies: list[dict[str, Any]] | None,
    allowed_dimensions: list[str],
    explicit_metrics: list[str] | None,
    explicit_dimensions: list[str] | None,
) -> tuple[list[str], list[str], dict[str, Any], dict[str, Any]]:
    chart_context = chart_context or {}
    selected_context = chart_context.get("selected_context") or {}
    source_metrics = [str(item).strip() for item in (chart_context.get("metrics") or []) if str(item).strip()]
    source_dimensions = [str(item).strip() for item in (chart_context.get("dimensions") or []) if str(item).strip()]
    allowed_lookup = {_norm_followup_name(name): str(name) for name in (allowed_dimensions or []) if str(name).strip()}
    metrics_out = [str(item).strip() for item in (explicit_metrics or []) if str(item).strip()] or source_metrics[:1]
    dimensions_out = [str(item).strip() for item in (explicit_dimensions or []) if str(item).strip()] or list(source_dimensions)
    intent = _classify_chart_followup_intent(question, chart_context)
    warnings: list[str] = []
    accepted: list[str] = []
    rejected: list[str] = []
    raw_plan_patch: dict[str, Any] = {}
    requested_dims = _deterministic_dimensions_from_question(question, glossary, allowed_dimensions)
    requested_grain = _requested_time_grain_from_question(question)
    requested_chart_type, requested_chart_reason = _requested_chart_type_from_question(question)

    # Detect "instead of [date/time/month/...]" — user wants to DROP the time dimension
    _replacing_time_dim = bool(re.search(
        r"\binstead\s+of\s+(date|time|month|day|week|period|process_month|process_date|the\s+date|the\s+time)\b",
        question.lower(),
    ))

    if intent in {"drill_down", "roll_up"}:
        transition_dims, transition_error = _resolve_hierarchy_transition(
            current_dimensions=source_dimensions or dimensions_out,
            requested_dimensions=requested_dims,
            hierarchies=hierarchies,
            allowed_dimensions=allowed_dimensions,
            direction="down" if intent == "drill_down" else "up",
        )
        if transition_dims:
            dimensions_out = transition_dims
            if source_dimensions and transition_dims != source_dimensions:
                action = "drilled down" if intent == "drill_down" else "rolled up"
                accepted.append(f"{action} to {', '.join(transition_dims[:2])}")
            else:
                accepted.append(f"carried forward dimensions {', '.join(transition_dims[:2])}")
        elif requested_dims:
            # Hierarchy transition failed — use the user's explicitly requested dimensions
            # without inheriting time dimensions from the source chart. This handles cases
            # like "by Zone" on a time-series chart where the user wants a categorical breakdown.
            resolved_requested = [allowed_lookup.get(_norm_followup_name(name)) for name in requested_dims]
            resolved_requested = [name for name in resolved_requested if name]
            if resolved_requested:
                dimensions_out = resolved_requested
                accepted.append(f"applied requested dimensions {', '.join(resolved_requested[:2])}")
            else:
                rejected.append(transition_error or "invalid_chart_followup_dimension")
        else:
            rejected.append(transition_error or "invalid_chart_followup_dimension")
    elif intent == "regenerate_with_adjustment":
        resolved_requested_dims = [allowed_lookup.get(_norm_followup_name(name)) for name in requested_dims]
        resolved_requested_dims = [name for name in resolved_requested_dims if name]
        if resolved_requested_dims:
            dimensions_out = resolved_requested_dims
            if source_dimensions and resolved_requested_dims != source_dimensions:
                accepted.append(f"replaced dimensions with {', '.join(resolved_requested_dims[:2])}")
            else:
                accepted.append(f"carried forward dimensions {', '.join(resolved_requested_dims[:2])}")
        else:
            # No explicit dims resolved — strip time if user said "instead of date"
            if _replacing_time_dim:
                dimensions_out = [d for d in dimensions_out if not _is_time_dimension_name(d)]
                if not dimensions_out and source_dimensions:
                    non_time = [d for d in source_dimensions if not _is_time_dimension_name(d)]
                    dimensions_out = non_time or []
                accepted.append("removed time dimension per 'instead of date' request")
            elif not dimensions_out and source_dimensions:
                dimensions_out = source_dimensions[:1]
                accepted.append(f"carried forward dimension {source_dimensions[0]}")
    elif requested_dims and intent not in {"change_grain", "explain_point_or_segment", "change_chart_type"}:
        resolved_requested_dims = [allowed_lookup.get(_norm_followup_name(name)) for name in requested_dims]
        resolved_requested_dims = [name for name in resolved_requested_dims if name]
        if resolved_requested_dims:
            # Preserve time dimension unless user said "instead of date/time"
            time_dimensions = [] if _replacing_time_dim else [str(name) for name in source_dimensions if _is_time_dimension_name(name)]
            business_dimensions = [str(name) for name in resolved_requested_dims if not _is_time_dimension_name(name)]
            dimensions_out = list(dict.fromkeys(time_dimensions + business_dimensions)) or dimensions_out
            if source_dimensions and dimensions_out != source_dimensions:
                accepted.append(f"replaced dimensions with {', '.join(dimensions_out[:2])}")
            else:
                accepted.append(f"carried forward dimensions {', '.join(dimensions_out[:2])}")
        else:
            rejected.append("invalid_chart_followup_dimension")
    elif not dimensions_out and source_dimensions:
        dimensions_out = list(source_dimensions)
        accepted.append(f"carried forward dimensions {', '.join(source_dimensions[:2])}")

    if intent == "change_grain":
        if requested_grain:
            raw_plan_patch["time_grain"] = requested_grain
            accepted.append(f"changed time grain to {requested_grain}")
        else:
            rejected.append("invalid_chart_followup_grain")

    if intent == "change_chart_type":
        if requested_chart_type:
            raw_plan_patch["chart_intent"] = requested_chart_type
            accepted.append(requested_chart_reason or f"requested chart type {requested_chart_type}")
        else:
            rejected.append("invalid_chart_followup_chart_type")

    filter_hints: list[dict[str, Any]] = []
    selected_category = selected_context.get("selected_category")
    if selected_category and source_dimensions:
        filter_hints.append(
            {
                "field": source_dimensions[-1],
                "operator": "=",
                "value": selected_category,
                "value_type": "text",
            }
        )
        accepted.append(f"added filter hint {source_dimensions[-1]} = {selected_category}")

    selected_series = selected_context.get("selected_series")
    if selected_series and len(source_dimensions) >= 2:
        filter_hints.append(
            {
                "field": source_dimensions[-2],
                "operator": "=",
                "value": selected_series,
                "value_type": "text",
            }
        )
        accepted.append(f"added series filter hint {source_dimensions[-2]} = {selected_series}")

    if selected_context.get("selected_time_value"):
        time_field = next((dim for dim in source_dimensions if str(dim).lower() in {"process_date", "date", "period", "month", "process_month"}), None)
        if time_field:
            filter_hints.append(
                {
                    "field": time_field,
                    "operator": "=",
                    "value": selected_context.get("selected_time_value"),
                    "value_type": "text",
                }
            )
            accepted.append(f"added time filter hint {time_field} = {selected_context.get('selected_time_value')}")

    if not source_metrics:
        warnings.append("chart_followup_missing_source_metric")
    if chart_context and not source_dimensions:
        warnings.append("chart_followup_missing_source_dimensions")
    if metrics_out and source_metrics and metrics_out[0] == source_metrics[0]:
        accepted.insert(0, f"carried forward metric {source_metrics[0]}")
    elif metrics_out:
        accepted.insert(0, f"resolved metric {metrics_out[0]}")

    if intent in {"explain_point_or_segment", "change_chart_type", "regenerate_with_adjustment"} or (not accepted and rejected):
        warnings.append("chart_followup_replanned_from_scratch")
    if rejected:
        warnings.extend(rejected)

    return metrics_out, dimensions_out, raw_plan_patch, {
        "follow_up_intent": intent,
        "source_chart_id": chart_context.get("source_chart_id"),
        "selected_context": selected_context,
        "filter_hints": filter_hints,
        "source_metrics": source_metrics,
        "source_dimensions": source_dimensions,
        "requested_dimensions": dimensions_out,
        "requested_chart_type": requested_chart_type,
        "accepted_transformations": accepted,
        "rejected_transformations": rejected,
        "warnings": warnings,
    }


def _build_chart_followup_transformation_summary(
    *,
    validated_plan: dict[str, Any],
    chart_followup_meta: dict[str, Any] | None,
) -> list[str]:
    meta = chart_followup_meta or {}
    accepted = [str(item) for item in (meta.get("accepted_transformations") or []) if str(item).strip()]
    if accepted:
        return accepted
    summary: list[str] = []
    source_metrics = [str(item) for item in (meta.get("source_metrics") or []) if str(item).strip()]
    source_dimensions = [str(item) for item in (meta.get("source_dimensions") or []) if str(item).strip()]
    metric_name = str(validated_plan.get("metric_name") or "").strip()
    dimensions = [str(item) for item in (validated_plan.get("dimensions") or []) if str(item).strip()]
    if metric_name:
        if source_metrics and metric_name == source_metrics[0]:
            summary.append(f"carried forward metric {metric_name}")
        elif source_metrics:
            summary.append(f"replaced metric {source_metrics[0]} with {metric_name}")
        else:
            summary.append(f"resolved metric {metric_name}")
    if source_dimensions and dimensions:
        if dimensions == source_dimensions:
            summary.append(f"carried forward dimensions {', '.join(dimensions[:2])}")
        elif len(dimensions) == 1 and len(source_dimensions) == 1 and dimensions[0] != source_dimensions[0]:
            summary.append(f"replaced dimension {source_dimensions[0]} with {dimensions[0]}")
        else:
            summary.append(f"resolved dimensions {', '.join(dimensions[:2])}")
    elif dimensions:
        summary.append(f"resolved dimensions {', '.join(dimensions[:2])}")
    for flt in meta.get("filter_hints") or []:
        if isinstance(flt, dict) and flt.get("field") and flt.get("value") not in (None, ""):
            summary.append(f"added filter hint {flt.get('field')} {flt.get('operator') or '='} {flt.get('value')}")
    return summary


def _persist_chart_followup_lineage(
    *,
    chart_id: str | None,
    response_payload: dict[str, Any],
) -> None:
    resolved_chart_id = str(chart_id or "").strip()
    if not resolved_chart_id:
        return
    chart_followup = response_payload.get("chart_followup") or {}
    source_chart_id = str(chart_followup.get("source_chart_id") or "").strip()
    if not source_chart_id:
        return
    existing = get_chart_request(settings, resolved_chart_id) or {}
    existing_query_payload = dict(existing.get("query_payload") or {})
    followup_payload = {
        "source_chart_id": source_chart_id,
        "parent_chart_id": source_chart_id,
        "derived_chart_id": resolved_chart_id,
        "follow_up_intent": chart_followup.get("follow_up_intent"),
        "selected_context": chart_followup.get("selected_context") or {},
        "accepted_transformations": chart_followup.get("accepted_transformations") or [],
        "rejected_transformations": chart_followup.get("rejected_transformations") or [],
        "transformation_summary": chart_followup.get("transformation_summary") or [],
        "warnings": chart_followup.get("warnings") or [],
    }
    merged_query_payload = {
        **existing_query_payload,
        "chart_followup": followup_payload,
    }
    update_chart_request(
        settings,
        resolved_chart_id,
        query_payload=merged_query_payload,
    )
    create_chart_event(
        settings,
        resolved_chart_id,
        "chart_followup_linked",
        details=followup_payload,
    )


def _persist_workspace_chart_artifact(
    *,
    tenant_id: str,
    domain_id: str | None,
    question: str,
    compiled_request: dict[str, Any],
    response_payload: dict[str, Any],
    conversation_id: str | None = None,
) -> str | None:
    try:
        query_payload = {
            "tenant_id": tenant_id,
            "domain_id": domain_id,
            "question": question,
            "metrics": response_payload.get("metrics") or [],
            "dimensions": response_payload.get("dimensions") or [],
            # Real SQL column names — used to resolve selected_category/selected_series
            # filters on follow-up, where chart aliases like "category" are not real columns.
            "source_dimensions": compiled_request.get("dimensions") or [],
            "filters": compiled_request.get("filters") or [],
            "limit": compiled_request.get("limit"),
            "conversation_plan": response_payload.get("conversation_plan"),
            "chart_followup": response_payload.get("chart_followup"),
        }
        _metric_names = response_payload.get("metrics") or []
        _dims = response_payload.get("dimensions") or []
        _clean_title = workspace_chart_title(_metric_names[0] if _metric_names else None, _dims)
        chart_row = create_chart_request(
            settings,
            tenant_id=tenant_id,
            domain_id=domain_id,
            question=question,
            query_payload=query_payload,
            sql=response_payload.get("sql"),
            params=[],
            rows_json=response_payload.get("rows"),
            chart_source="workspace",
            title=_clean_title,
            conversation_id=conversation_id,
        )
        chart_id = chart_row.get("chart_id")
        if not chart_id:
            return None
        create_chart_event(
            settings,
            chart_id,
            "queued",
            details={"question": question, "source": "workspace_conversation"},
        )
        _ws_rows = response_payload.get("rows") or []
        _ws_chart_type = response_payload.get("chart_type") or "bar"
        _ws_metric = (_metric_names[0] if _metric_names else None) or ""
        _ws_dim_key = (_dims[0] if _dims else None)
        inference = build_chart_inference(
            settings,
            chart_type=_ws_chart_type,
            rows=_ws_rows,
            metric_name=_ws_metric,
            dim_key=_ws_dim_key,
            chart_title=_clean_title or question,
        )
        interaction_context = build_chart_interaction_context_for_creation(
            settings,
            chart_row={
                "chart_id": chart_id,
                "tenant_id": tenant_id,
                "domain_id": domain_id,
                "query_payload": {
                    **query_payload,
                    "table": (compiled_request.get("tables") or [None])[0] if isinstance(compiled_request.get("tables"), list) else compiled_request.get("table"),
                    "time_grain": compiled_request.get("time_grain"),
                },
                "rows_json": _ws_rows,
            },
            tenant_id=tenant_id,
            domain_id=domain_id,
        )
        update_chart_request(
            settings,
            chart_id,
            status="ready",
            query_payload=query_payload,
            sql=response_payload.get("sql"),
            params=[],
            rows_json=_ws_rows,
            chart_type=_ws_chart_type,
            chart_payload=response_payload.get("chart_payload"),
            chart_data=response_payload.get("data"),
            insight_text=inference["insight_text"],
            narrative_text=inference["narrative_text"],
            stats_json=inference["stats_json"],
            interaction_context_json=interaction_context,
            root_chart_id=chart_id,
        )
        create_chart_event(
            settings,
            chart_id,
            "ready",
            details={
                "chart_type": _ws_chart_type,
                "source": "workspace_conversation",
            },
        )
        return chart_id
    except Exception:  # noqa: BLE001
        logger.exception("workspace.chart_persist_failed")
        return None


def _stream_openai_tokens(system_prompt: str, user_prompt: str) -> Iterator[str]:
    if not _workspace_llm_stream_enabled():
        return iter(())
    payload = {
        "model": settings.openai_model,
        "stream": True,
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {settings.openai_api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    def _iter() -> Iterator[str]:
        with urllib.request.urlopen(req, timeout=60) as resp:
            while True:
                line = resp.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="ignore").strip()
                if not text.startswith("data: "):
                    continue
                data = text[6:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                delta = ((chunk.get("choices") or [{}])[0].get("delta") or {}).get("content")
                if delta:
                    yield str(delta)

    return _iter()


def _workspace_scan_table_count(result_payload: dict | None) -> int:
    if not isinstance(result_payload, dict):
        return 0
    count = 0
    for connection in result_payload.get("connections", []) or []:
        for database in connection.get("databases", []) or []:
            for schema in database.get("schemas", []) or []:
                tables = schema.get("tables") or []
                if isinstance(tables, list):
                    count += len(tables)
    return count


def _configured_table_count(scope: dict | None) -> int:
    tables = (scope or {}).get("tables")
    if isinstance(tables, list):
        return len(tables)
    return 0


def _workspace_schema_scan_payload(
    connection_id: str | None,
    database_name: str | None,
    schema_payload: dict | None,
) -> dict | None:
    if not isinstance(schema_payload, dict):
        return None
    schemas = schema_payload.get("schemas")
    if not isinstance(schemas, list) or not schemas:
        return None
    resolved_connection_id = str(schema_payload.get("connection_id") or connection_id or "")
    resolved_database = str(schema_payload.get("database") or database_name or "")
    if not resolved_connection_id or not resolved_database:
        return None
    normalized_schemas: list[dict[str, object]] = []
    for schema in schemas:
        if not isinstance(schema, dict):
            continue
        schema_name = str(schema.get("name") or "").strip()
        if not schema_name:
            continue
        tables = schema.get("tables")
        normalized_tables = [str(table).strip() for table in (tables or []) if str(table).strip()]
        normalized_schemas.append({"name": schema_name, "tables": normalized_tables})
    if not normalized_schemas:
        return None
    return {
        "connections": [
            {
                "connection_id": resolved_connection_id,
                "databases": [
                    {
                        "name": resolved_database,
                        "schemas": normalized_schemas,
                    }
                ],
            }
        ]
    }


def _extract_user_query(payload: dict | None, *, required: bool = False) -> str | None:
    data = payload or {}
    for key in ("user_query", "query", "message_text", "first_question"):
        value = data.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    if required:
        raise HTTPException(
            status_code=400,
            detail="user_query is required (aliases accepted: query, message_text, first_question)",
        )
    return None


@app.get(
    "/workspace/tenants",
    tags=["workspace"],
    summary="List workspace tenants",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "tenants": {
                                "summary": "Workspace tenants",
                                "value": {
                                    "tenants": [
                                        {
                                            "tenant_id": "VC_101",
                                            "tenant_name": "HPCL VC 101",
                                            "status": "active",
                                            "domain_id": "lpg_production_distribution",
                                            "metadata": {},
                                        }
                                    ]
                                },
                            }
                        }
                    }
                }
            }
        }
    },
)
def workspace_list_tenants(limit: int = 200) -> dict:
    rows = list_tenants(settings, limit=limit)
    items: list[dict] = []
    seen: set[str] = set()
    for row in rows:
        tenant_id = row.get("tenant_id")
        if not tenant_id or tenant_id in seen:
            continue
        seen.add(tenant_id)
        items.append(
            {
                "tenant_id": tenant_id,
                "tenant_name": row.get("display_name") or tenant_id,
                "status": row.get("status") or "active",
                "domain_id": row.get("domain_id"),
                "metadata": row.get("metadata") or {},
            }
        )
    return {"tenants": items}


@app.get(
    "/workspace/tenants/{tenant_id}/domains",
    tags=["workspace"],
    summary="List tenant domains with readiness",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "domains": {
                                "summary": "Tenant domains",
                                "value": {
                                    "tenant_id": "VC_101",
                                    "domains": [
                                        {
                                            "domain_id": "lpg_production_distribution",
                                            "display_name": "Lpg Production Distribution",
                                            "scan_status": "completed",
                                            "deployment_status": "completed",
                                            "current_run_id": "run_1a0f427c86ec",
                                            "current_run_display_name": "Lpg Production Distribution Deployment v4",
                                            "last_scan_id": "scan_2233e9a1",
                                            "last_scanned_at": "2026-02-23T05:31:07.901Z",
                                            "tables_detected": 9,
                                        }
                                    ],
                                },
                            }
                        }
                    }
                }
            }
        }
    },
)
def workspace_list_domains_for_tenant(tenant_id: str) -> dict:
    domains: set[str] = set()
    domain_row = get_tenant_domain(settings, tenant_id)
    if domain_row and domain_row.get("domain_id"):
        domains.add(domain_row["domain_id"])
    run_rows = run_query(
        settings,
        """
        SELECT DISTINCT domain_id
          FROM public.quantyx_agent_runs
         WHERE tenant_id = %s
        """,
        [tenant_id],
    )
    for row in run_rows:
        if row.get("domain_id"):
            domains.add(row["domain_id"])
    convo_rows = run_query(
        settings,
        """
        SELECT DISTINCT domain_id
          FROM public.quantyx_workspace_conversations
         WHERE tenant_id = %s
        """,
        [tenant_id],
    )
    for row in convo_rows:
        if row.get("domain_id"):
            domains.add(row["domain_id"])

    domain_items: list[dict] = []
    for domain_id in sorted(domains):
        scope = get_tenant_scope(settings, tenant_id, domain_id)
        scan_rows = run_query(
            settings,
            """
            SELECT scan_id, status, created_at, result_payload
              FROM public.quantyx_schema_scans
             WHERE tenant_id = %s
               AND domain_id = %s
             ORDER BY created_at DESC
             LIMIT 1
            """,
            [tenant_id, domain_id],
        )
        scan = scan_rows[0] if scan_rows else None
        deployment = get_current_deployment(settings, tenant_id, domain_id)
        scan_status = (scan or {}).get("status") or ("configured" if scope else "not_started")
        deployment_status = (deployment or {}).get("status") or ("configured" if scope else "not_started")
        domain_items.append(
            {
                "domain_id": domain_id,
                "display_name": domain_id.replace("_", " ").replace("-", " ").title(),
                "scan_status": scan_status,
                "deployment_status": deployment_status,
                "current_run_id": (deployment or {}).get("run_id"),
                "current_run_display_name": (deployment or {}).get("display_name"),
                "last_scan_id": (scan or {}).get("scan_id"),
                "last_scanned_at": (scan or {}).get("created_at"),
                "tables_detected": _workspace_scan_table_count((scan or {}).get("result_payload")) or _configured_table_count(scope),
            }
        )
    return {"tenant_id": tenant_id, "domains": domain_items}


@app.get(
    "/workspace/tenants/{tenant_id}/domains/{domain_id}/scan-status",
    tags=["workspace"],
    summary="Get scan status for tenant/domain",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "scan_status": {
                                "summary": "Latest scan status",
                                "value": {
                                    "tenant_id": "VC_101",
                                    "domain_id": "lpg_production_distribution",
                                    "scan_status": "completed",
                                    "last_scan_id": "scan_2233e9a1",
                                    "last_scanned_at": "2026-02-23T05:31:07.901Z",
                                    "tables_detected": 9,
                                },
                            }
                        }
                    }
                }
            }
        }
    },
)
def workspace_scan_status(tenant_id: str, domain_id: str) -> dict:
    rows = run_query(
        settings,
        """
        SELECT scan_id, status, created_at, result_payload
          FROM public.quantyx_schema_scans
         WHERE tenant_id = %s
           AND domain_id = %s
         ORDER BY created_at DESC
         LIMIT 1
        """,
        [tenant_id, domain_id],
    )
    if not rows:
        scope = get_tenant_scope(settings, tenant_id, domain_id)
        return {
            "tenant_id": tenant_id,
            "domain_id": domain_id,
            "scan_status": "configured" if scope else "not_started",
            "last_scan_id": None,
            "last_scanned_at": None,
            "tables_detected": _configured_table_count(scope),
        }
    row = rows[0]
    return {
        "tenant_id": tenant_id,
        "domain_id": domain_id,
        "scan_status": row.get("status") or "unknown",
        "last_scan_id": row.get("scan_id"),
        "last_scanned_at": row.get("created_at"),
        "tables_detected": _workspace_scan_table_count(row.get("result_payload")),
    }


@app.get(
    "/workspace/tenants/{tenant_id}/domains/{domain_id}/deployment-status",
    tags=["workspace"],
    summary="Get deployment status for tenant/domain",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "deployment_status": {
                                "summary": "Deployment status",
                                "value": {
                                    "tenant_id": "VC_101",
                                    "domain_id": "lpg_production_distribution",
                                    "status": "completed",
                                    "run_id": "run_1a0f427c86ec",
                                    "display_name": "Lpg Production Distribution Deployment v4",
                                    "version_no": 4,
                                    "completed_at": "2026-03-06T21:54:18.326901Z",
                                },
                            }
                        }
                    }
                }
            }
        }
    },
)
def workspace_deployment_status(tenant_id: str, domain_id: str) -> dict:
    deployment = get_current_deployment(settings, tenant_id, domain_id)
    if deployment:
        return {
            "tenant_id": tenant_id,
            "domain_id": domain_id,
            "status": deployment.get("status"),
            "run_id": deployment.get("run_id"),
            "display_name": deployment.get("display_name"),
            "version_no": deployment.get("version_no"),
            "completed_at": deployment.get("completed_at"),
        }
    latest = list_deployments(settings, tenant_id, domain_id, limit=1)
    if latest:
        row = latest[0]
        return {
            "tenant_id": tenant_id,
            "domain_id": domain_id,
            "status": row.get("status"),
            "run_id": row.get("run_id"),
            "display_name": row.get("display_name"),
            "version_no": row.get("version_no"),
            "completed_at": row.get("completed_at"),
        }
    scope = get_tenant_scope(settings, tenant_id, domain_id)
    return {
        "tenant_id": tenant_id,
        "domain_id": domain_id,
        "status": "configured" if scope else "not_started",
        "run_id": None,
        "display_name": None,
        "version_no": None,
        "completed_at": None,
    }


@app.get(
    "/workspace/deployments/current",
    tags=["workspace"],
    summary="Get current canonical deployment",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "current": {
                                "summary": "Current deployment",
                                "value": {
                                    "run_id": "run_1a0f427c86ec",
                                    "tenant_id": "VC_101",
                                    "domain_id": "lpg_production_distribution",
                                    "status": "completed",
                                    "is_canonical": True,
                                    "version_no": 4,
                                    "display_name": "Lpg Production Distribution Deployment v4",
                                },
                            }
                        }
                    }
                }
            }
        }
    },
)
def workspace_current_deployment(tenant_id: str, domain_id: str | None = None) -> dict:
    resolved_domain = _resolve_domain_id(tenant_id, domain_id)
    current = get_current_deployment(settings, tenant_id, resolved_domain)
    if not current:
        raise HTTPException(status_code=404, detail="No completed deployment found for tenant/domain")
    return current


@app.get(
    "/workspace/deployments",
    tags=["workspace"],
    summary="List deployment history",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "history": {
                                "summary": "Deployment history",
                                "value": {
                                    "tenant_id": "VC_101",
                                    "domain_id": "lpg_production_distribution",
                                    "deployments": [
                                        {
                                            "run_id": "run_1a0f427c86ec",
                                            "status": "completed",
                                            "version_no": 4,
                                            "display_name": "Lpg Production Distribution Deployment v4",
                                        }
                                    ],
                                },
                            }
                        }
                    }
                }
            }
        }
    },
)
def workspace_list_deployments(tenant_id: str, domain_id: str | None = None, limit: int = 50) -> dict:
    resolved_domain = _resolve_domain_id(tenant_id, domain_id)
    rows = list_deployments(settings, tenant_id, resolved_domain, limit=limit)
    return {"tenant_id": tenant_id, "domain_id": resolved_domain, "deployments": rows}


def _start_workspace_deployment(payload: dict) -> dict:
    tenant_id = payload.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=400, detail="tenant_id is required")
    domain_id = _resolve_domain_id(tenant_id, payload.get("domain_id"))
    inflight = _inflight_run_for_scope(tenant_id, domain_id)
    if inflight:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "A deployment run is already in progress for this tenant/domain.",
                "tenant_id": tenant_id,
                "domain_id": domain_id,
                "run_id": inflight.get("run_id"),
                "status": inflight.get("status"),
            },
        )
    connection_id, database, schema, _ = _resolve_scope_values(tenant_id, domain_id)
    schema_payload = payload.get("schema_payload")
    if not schema_payload:
        schema_payload = load_latest_scan_for_scope(settings, tenant_id, domain_id, connection_id, database, schema)
    if not schema_payload:
        raise HTTPException(status_code=400, detail="schema_payload is required")
    scan_payload = _workspace_schema_scan_payload(
        payload.get("connection_id") or connection_id,
        payload.get("database") or database,
        schema_payload,
    )
    if scan_payload:
        try:
            persist_schema_scan(
                settings,
                request_payload={
                    "source": "workspace_deployments",
                    "tenant_id": tenant_id,
                    "domain_id": domain_id,
                    "schema_payload": schema_payload,
                },
                result_payload=scan_payload,
                tenant_id=tenant_id,
                domain_id=domain_id,
                requested_by="workspace_deployments",
            )
        except Exception:
            logger.exception(
                "workspace.deployment.scan_snapshot_failed | tenant_id=%s domain_id=%s",
                tenant_id,
                domain_id,
            )
    merged_context_text, resolved_context_ids = _merge_context_inputs(
        tenant_id,
        domain_id,
        payload.get("context_text"),
        payload.get("context_ids") or [],
    )
    # Activate each resolved context for this scope so subsequent conversation
    # messages can find it via list_active_context_ids → business_context_text.
    _deploy_connection_id = payload.get("connection_id") or connection_id
    _deploy_database = payload.get("database") or database
    _deploy_schema = payload.get("schema_name") or schema
    for _ctx_id in resolved_context_ids:
        try:
            set_context_active(
                settings,
                tenant_id=tenant_id,
                domain_id=domain_id,
                context_id=_ctx_id,
                connection_id=_deploy_connection_id,
                database_name=_deploy_database,
                schema_name=_deploy_schema,
                is_active=True,
            )
        except Exception:
            logger.exception(
                "workspace.deployment.context_activate_failed | tenant_id=%s domain_id=%s context_id=%s",
                tenant_id, domain_id, _ctx_id,
            )
    run_id = create_agent_run(settings, tenant_id, domain_id, status="queued")
    version_no = next_run_version(settings, tenant_id, domain_id)
    display_name = payload.get("display_name") or generate_run_display_name(domain_id, version_no)
    initialize_run_metadata(
        settings,
        run_id,
        tenant_id=tenant_id,
        domain_id=domain_id,
        version_no=version_no,
        display_name=display_name,
        is_canonical=False,
    )
    append_agent_run_event(
        settings,
        run_id,
        "PlanningAgent",
        "completed",
        "Plan created",
        {"steps": ["Scan schema", "Build semantics", "Create dashboards"]},
    )
    append_plan_summary(settings, run_id, ["Scan schema", "Build semantics", "Create dashboards"])
    initial_state = {
        "tenant_id": tenant_id,
        "domain_id": domain_id,
        "schema_ids": payload.get("schema_ids") or [],
        "context_text": merged_context_text,
        "context_ids": resolved_context_ids,
        "schema_payload": schema_payload or {},
        "schema_name": payload.get("schema_name") or schema,
        "connection_id": payload.get("connection_id") or connection_id,
        "database_name": payload.get("database") or database,
        "runtime_tuning": payload.get("runtime_tuning") or {},
        "pause_for_rule_review": bool(payload.get("pause_for_rule_review", True)),
        "scoped_conn": (_sc2 := _resolve_scoped_conn(tenant_id, domain_id)) and _sc2.to_dict(),
    }
    job = create_job(
        settings,
        tenant_id=tenant_id,
        domain_id=domain_id,
        job_type="agentic_run",
        payload={
            "run_id": run_id,
            "initial_state": initial_state,
            "canonicalize_on_success": True,
        },
        idempotency_key=None,
    )
    mark_run_status(settings, run_id, "queued")
    return {
        "tenant_id": tenant_id,
        "domain_id": domain_id,
        "run_id": run_id,
        "display_name": display_name,
        "version_no": version_no,
        "status": "queued",
        "workflow_kind": "data_quality"
        if str(domain_id or "").strip().lower() == "data_quality_observability"
        or str(payload.get("workflow_mode") or "").strip().lower() == "data_quality"
        else "standard",
        "job_id": job.get("job_id"),
    }


DQ_RUN_SUMMARY_EXAMPLE = {
    "quality_run_id": "dqrun_001",
    "run_id": "run_dq_001",
    "tenant_id": "VC_101",
    "domain_id": "data_quality_observability",
    "connection_id": "conn_001",
    "database_name": "analytics",
    "schema_name": "public",
    "status": "completed",
    "overall_trust_score": 82.4,
    "critical_issue_count": 7,
    "warning_issue_count": 18,
    "dashboard_id": "dash_001",
    "dashboard_title": "Data Quality Observability Data Quality Dashboard",
    "dashboard_chart_count": 7,
    "duplicate_candidate_count": 18,
    "exact_duplicate_candidate_count": 12,
    "fuzzy_duplicate_candidate_count": 6,
    "active_rule_count": 25,
    "needs_review_rule_count": 0,
    "unsupported_rule_count": 0,
    "rejected_rule_count": 0,
    "rule_review_required": False,
    "review_queue_pending_count": 0,
    "workflow_status": "completed",
    "stale_table_count": 1,
    "tables_without_freshness_column_count": 0,
    "stability_issue_count": 1,
    "enrichment_opportunity_count": 4,
    "external_lookup_opportunity_count": 0,
    "remediation_action_count": 9,
    "critical_remediation_action_count": 3,
    "artifacts": {
        "run_summary": "/data-quality/runs/run_dq_001",
        "dashboard": "/data-quality/runs/run_dq_001/dashboard",
        "excel_report": "/data-quality/reports/run_dq_001/excel?tenant_id=VC_101&domain_id=data_quality_observability",
        "tables": "/data-quality/tables?tenant_id=VC_101&domain_id=data_quality_observability&run_id=run_dq_001",
        "rules": "/data-quality/rules?tenant_id=VC_101&domain_id=data_quality_observability&run_id=run_dq_001",
        "rule_review_queue": "/data-quality/rules/review-queue?tenant_id=VC_101&domain_id=data_quality_observability&run_id=run_dq_001",
        "resume_after_rule_review": "/data-quality/runs/run_dq_001/resume-after-rule-review",
        "duplicates": "/data-quality/duplicates?tenant_id=VC_101&domain_id=data_quality_observability&run_id=run_dq_001",
        "remediation": "/data-quality/remediation?tenant_id=VC_101&domain_id=data_quality_observability&run_id=run_dq_001",
        "enrichment_opportunities": "/data-quality/enrichment/opportunities?tenant_id=VC_101&domain_id=data_quality_observability&run_id=run_dq_001",
        "enrichment_questions": "/data-quality/enrichment/questions?tenant_id=VC_101&domain_id=data_quality_observability&run_id=run_dq_001",
    },
    "remediation_summary": {"action_count": 9, "critical_action_count": 3},
    "recommended_actions": [
        {
            "priority": "critical",
            "action_type": "freshness_recovery",
            "title": "Restore freshness for customer",
        }
    ],
    "summary": {
        "profiled_tables": 18,
        "profiled_columns": 243,
        "failed_rules": 5,
        "referential_violations": 2,
        "enrichment_opportunities": 4,
        "workflow_status": "completed",
    },
    "created_at": "2026-04-22T09:00:00Z",
    "completed_at": "2026-04-22T09:05:00Z",
}

DQ_RUN_HYDRATION_EXAMPLE = {
    "run": {
        "quality_run_id": "dqrun_001",
        "run_id": "run_dq_001",
        "tenant_id": "VC_101",
        "domain_id": "data_quality_observability",
        "connection_id": "conn_001",
        "database_name": "analytics",
        "schema_name": "public",
        "status": "awaiting_rule_review",
        "overall_trust_score": 82.4,
        "critical_issue_count": 2,
        "warning_issue_count": 5,
        "active_rule_count": 3,
        "needs_review_rule_count": 2,
        "unsupported_rule_count": 0,
        "rejected_rule_count": 0,
        "rule_review_required": True,
        "review_queue_pending_count": 2,
        "workflow_status": "awaiting_rule_review",
        "stale_table_count": 0,
        "tables_without_freshness_column_count": 0,
        "stability_issue_count": 0,
        "enrichment_opportunity_count": 4,
        "external_lookup_opportunity_count": 0,
        "remediation_action_count": 5,
        "critical_remediation_action_count": 2,
        "artifacts": {
            "run_summary": "/data-quality/runs/run_dq_001",
            "rule_review_queue": "/data-quality/rules/review-queue?tenant_id=VC_101&domain_id=data_quality_observability&run_id=run_dq_001",
            "resume_after_rule_review": "/data-quality/runs/run_dq_001/resume-after-rule-review",
            "enrichment_questions": "/data-quality/enrichment/questions?tenant_id=VC_101&domain_id=data_quality_observability&run_id=run_dq_001",
        },
        "remediation_summary": {"action_count": 5, "critical_action_count": 2},
        "recommended_actions": [{"priority": "critical", "title": "Backfill missing values in customer.email"}],
        "summary": {"workflow_status": "awaiting_rule_review"},
        "created_at": "2026-04-22T09:00:00Z",
        "completed_at": None,
    },
    "pending_tasks": {
        "workflow_status": "awaiting_rule_review",
        "requires_attention": True,
        "rule_review": {
            "rule_count": 2,
            "needs_review_count": 2,
            "unsupported_count": 0,
            "top_items": [
                {
                    "rule_id": "dq_rule_101",
                    "table_name": "orders",
                    "column_name": "status",
                    "rule_type": "allowed_values",
                    "severity": "warning",
                    "confidence": 0.62,
                    "status": "needs_review",
                    "source_text": "Order status should be valid",
                    "sql_preview_status": "ready",
                    "sql_preview_source": "llm",
                }
            ],
        },
        "enrichment_questions": {
            "question_count": 4,
            "pending_answer_count": 2,
            "proposal_ready_count": 1,
            "deferred_count": 1,
            "rejected_count": 0,
            "top_items": [],
        },
        "remediation": {
            "summary": {"action_count": 5, "critical_action_count": 2},
            "top_actions": [{"priority": "critical", "title": "Backfill missing values in customer.email"}],
        },
    },
    "artifact_links": {
        "run_summary": "/data-quality/runs/run_dq_001",
        "dashboard": "/data-quality/runs/run_dq_001/dashboard",
    },
}

DQ_TABLES_EXAMPLE = {
    "tenant_id": "VC_101",
    "domain_id": "data_quality_observability",
    "run_id": "run_dq_001",
    "tables": [
        {
            "table_name": "customer",
            "row_count": 100000,
            "trust_score": 71.2,
            "severity": "warning",
            "duplicate_candidate_count": 18,
            "enrichment_opportunity_count": 2,
        }
    ],
}

DQ_RULES_EXAMPLE = {
    "tenant_id": "VC_101",
    "domain_id": "data_quality_observability",
    "run_id": "run_dq_001",
    "rules": [
        {
            "rule_id": "dq_rule_201",
            "rule_type": "referential_integrity",
            "source_text": "orders.customer_id must exist in customer.customer_id",
            "executor_kind": "deterministic_sql",
            "execution_plan": {"validation_sql": "SELECT ...", "sample_sql": "SELECT ..."},
            "severity": "critical",
            "table_name": "orders",
            "column_name": "customer_id",
            "reference_table": "customer",
            "reference_column": "customer_id",
            "rule_status": "active",
            "result": {
                "status": "failed",
                "violation_count": 842,
                "violation_pct": 0.84,
            },
        }
    ],
}

DQ_RULE_REVIEW_QUEUE_EXAMPLE = {
    "tenant_id": "VC_101",
    "domain_id": "data_quality_observability",
    "run_id": "run_dq_001",
    "summary": {"rule_count": 2, "needs_review_count": 2, "unsupported_count": 0},
    "rules": [
        {
            "rule_id": "dq_rule_101",
            "table_name": "orders",
            "column_name": "status",
            "rule_type": "allowed_values",
            "severity": "warning",
            "confidence": 0.62,
            "status": "needs_review",
            "source_text": "Order status should be valid",
            "execution_plan_json": {"sql_preview_status": "ready", "sql_preview_source": "llm"},
        }
    ],
}

DQ_RULE_REVIEW_DETAIL_EXAMPLE = {
    "rule_id": "dq_rule_101",
    "run_id": "run_dq_001",
    "tenant_id": "VC_101",
    "domain_id": "data_quality_observability",
    "rule_type": "allowed_values",
    "severity": "warning",
    "table_name": "orders",
    "column_name": "status",
    "source_text": "Order status should be valid",
    "condition_json": {"allowed_values": [], "ambiguity_reason": "Allowed values were not stated"},
    "executor_kind": "deterministic_sql",
    "sql_preview": {"validation_sql": "SELECT status FROM orders WHERE status IS NOT NULL"},
    "sql_preview_status": "ready",
    "sql_preview_source": "llm",
    "confidence": 0.62,
    "rule_status": "needs_review",
    "result": None,
}

DQ_TABLE_DETAIL_EXAMPLE = {
    "quality_run_id": "dqrun_001",
    "run_id": "run_dq_001",
    "tenant_id": "VC_101",
    "domain_id": "data_quality_observability",
    "table_name": "customer",
    "row_count": 100000,
    "trust_score": 71.2,
    "completeness_score": 78.5,
    "freshness_score": 100.0,
    "duplicate_risk_score": 54.0,
    "severity": "warning",
    "components": {
        "completeness": 78.5,
        "validity": 91.0,
        "referential_integrity": 88.0,
        "duplicate_risk": 54.0,
        "freshness": 100.0,
    },
    "trust_component_explanations": {
        "duplicate_risk": "High duplicate candidate volume is pulling down trust for this table."
    },
    "summary": {
        "trust_components": {
            "completeness": 78.5,
            "validity": 91.0,
            "referential_integrity": 88.0,
            "duplicate_risk": 54.0,
            "freshness": 100.0,
        }
    },
    "columns": [
        {
            "column_name": "email",
            "column_alias": "email",
            "null_pct": 17.4,
            "completeness_score": 82.6,
        }
    ],
    "failed_rules": [
        {
            "rule_id": "dqr_001",
            "rule_type": "email_pattern",
            "table_name": "customer",
            "column_name": "email",
            "severity": "warning",
        }
    ],
    "duplicate_candidates": [
        {
            "candidate_id": "dqdup_001",
            "table_name": "customer",
            "duplicate_type": "exact_key_duplicate",
            "confidence": 0.99,
            "candidate_record_count": 4,
        }
    ],
    "enrichment_opportunities": [
        {
            "opportunity_id": "dq_enrich_001",
            "table_name": "customer",
            "target_column": "state",
            "confidence": 0.87,
        }
    ],
}

DQ_FRESHNESS_EXAMPLE = {
    "tenant_id": "VC_101",
    "domain_id": "data_quality_observability",
    "run_id": "run_dq_001",
    "freshness": [
        {
            "table_name": "customer",
            "freshness_column": "updated_at",
            "latest_timestamp": "2026-04-18T10:00:00Z",
            "freshness_lag_days": 9.0,
            "freshness_score": 55.0,
            "freshness_status": "stale",
            "baseline_quality_run_id": "dqrun_prev",
            "baseline_row_count": 90000,
            "row_count_change_pct": 33.33,
            "baseline_completeness_score": 95.0,
            "completeness_score_change": -15.0,
            "stability_status": "changed",
            "stability_issues": ["row_count_change_pct>20", "completeness_score_change>10"],
        }
    ],
}

DQ_DUPLICATES_EXAMPLE = {
    "tenant_id": "VC_101",
    "domain_id": "data_quality_observability",
    "run_id": "run_dq_001",
    "duplicates": [
        {
            "candidate_id": "dqdup_001",
            "table_name": "customer",
            "duplicate_type": "exact_key_duplicate",
            "match_columns_json": ["customer_id"],
            "confidence": 0.99,
            "candidate_record_count": 4,
            "review_status": "needs_review",
        }
    ],
}

DQ_REMEDIATION_EXAMPLE = {
    "tenant_id": "VC_101",
    "domain_id": "data_quality_observability",
    "run_id": "run_dq_001",
    "summary": {
        "action_count": 9,
        "critical_action_count": 3,
        "warning_action_count": 5,
        "info_action_count": 1,
    },
    "actions": [
        {
            "priority": "critical",
            "action_type": "missingness_backfill",
            "title": "Backfill missing values in customer.email",
            "table_name": "customer",
            "column_name": "email",
            "issue_summary": "email is 35.0% null and 0.0% blank.",
            "recommended_action": "Backfill or enrich customer.email before publishing downstream records.",
            "owner_hint": "Data steward",
            "evidence_type": "missingness",
            "evidence_path": "/data-quality/evidence/missingness?tenant_id=VC_101&run_id=run_dq_001&table_name=customer&column_name=email",
            "trust_component": "completeness",
        }
    ],
}

DQ_MISSINGNESS_EVIDENCE_EXAMPLE = {
    "tenant_id": "VC_101",
    "run_id": "run_dq_001",
    "table_name": "customer",
    "column_name": "email",
    "column_alias": "email",
    "issue_type": "missingness",
    "row_count": 290,
    "rows": [{"customer_id": "C101", "email": None, "country": "US"}],
}

DQ_RULE_EVIDENCE_EXAMPLE = {
    "rule_id": "dq_rule_201",
    "table_name": "orders",
    "column_name": "customer_id",
    "column_alias": "customer_id",
    "reference_table": "customer",
    "reference_column": "customer_id",
    "reference_column_alias": "customer_id",
    "sample_rows": [{"order_id": "O101", "customer_id": "C999"}],
}

DQ_DUPLICATE_EVIDENCE_EXAMPLE = {
    "candidate_id": "dqdup_001",
    "table_name": "customer",
    "match_columns": ["customer_id"],
    "match_column_aliases": ["customer_id"],
    "rows": [{"customer_id": "C101", "email": "x@example.com"}],
}

DQ_FRESHNESS_EVIDENCE_EXAMPLE = {
    "table_name": "customer",
    "freshness_column": "updated_at",
    "freshness_column_alias": "updated_at",
    "latest_timestamp": "2026-04-18T10:00:00Z",
    "baseline_quality_run_id": "dqrun_prev",
    "stability_status": "changed",
}

DQ_ENRICHMENT_EVIDENCE_EXAMPLE = {
    "proposal_id": "dq_enrich_prop_001",
    "table_name": "customer",
    "target_column": "state",
    "target_column_alias": "state",
    "source_columns_json": ["pincode", "country"],
    "source_column_aliases": ["postal_code", "country"],
    "rows": [
        {
            "row_ref": {"customer_id": "C101"},
            "proposed_value": "Karnataka",
            "confidence": 0.91,
            "method": "llm",
        }
    ],
}

DQ_DASHBOARD_EXAMPLE = {
    "run_id": "run_dq_001",
    "dashboard_id": "dash_001",
    "dashboard_type": "data_quality",
    "title": "Data Quality Observability Data Quality Dashboard",
    "name": "Data Quality Observability Data Quality Dashboard",
    "description": "System-generated dashboard summarizing trust, missingness, validation failures, referential integrity, duplicate risk, and freshness.",
    "status": "active",
    "quality_score": 82.4,
    "quality_gate_passed": False,
    "chart_plan": [
        {
            "title": "Columns with Highest Missingness",
            "chart_key": "missingness_heatmap",
            "chart_type": "table_heatmap",
            "data_source": "quantyx_data_quality_column_artifacts",
            "summary": {"column_count": 3},
            "display_columns": [
                {"field": "column_name", "label": "Physical Column"},
                {"field": "column_alias", "label": "Semantic Alias"},
                {"field": "evidence_path", "label": "Evidence Path"},
            ],
            "rows": [
                {
                    "table_name": "customer",
                    "column_name": "email",
                    "column_alias": "email",
                    "null_pct": 17.4,
                    "completeness_score": 82.6,
                    "evidence_path": "/data-quality/evidence/missingness?tenant_id=VC_101&domain_id=data_quality_observability&run_id=run_dq_001&table_name=customer&column_name=email",
                }
            ],
        }
    ],
    "charts": [],
    "created_at": "2026-04-22T09:05:00Z",
    "updated_at": "2026-04-22T09:05:00Z",
}

DQ_OPPORTUNITIES_EXAMPLE = {
    "tenant_id": "VC_101",
    "domain_id": "data_quality_observability",
    "run_id": "run_dq_001",
    "opportunities": [
        {
            "opportunity_id": "dq_enrich_001",
            "table_name": "customer",
            "target_column": "state",
            "target_column_alias": "state",
            "source_columns_json": ["pincode", "country"],
            "source_column_aliases_json": ["postal_code", "country"],
            "missing_count": 1240,
            "candidate_method": "postal_context_inference",
            "confidence": 0.87,
            "question": "Can we use existing row context to propose missing customer.state values from pincode and country?",
            "status": "needs_user_approval",
        }
    ],
}

DQ_QUESTIONS_EXAMPLE = {
    "tenant_id": "VC_101",
    "domain_id": "data_quality_observability",
    "run_id": "run_dq_001",
    "summary": {
        "question_count": 4,
        "pending_answer_count": 2,
        "proposal_ready_count": 1,
        "deferred_count": 1,
        "rejected_count": 0,
    },
    "questions": [
        {
            "question_id": "dq_enrich_001",
            "opportunity_id": "dq_enrich_001",
            "table_name": "customer",
            "target_column": "state",
            "target_column_alias": "state",
            "source_columns_json": ["pincode", "country"],
            "source_column_aliases_json": ["postal_code", "country"],
            "question": "Can we use existing row context to propose missing customer.state values from pincode and country?",
            "missing_count": 1240,
            "candidate_method": "postal_context_inference",
            "confidence": 0.87,
            "status": "pending_answer",
            "available_actions": ["approve", "defer", "reject"],
            "proposal_id": None,
        }
    ],
}

DQ_QUESTION_ANSWER_REQUEST_EXAMPLE = {"tenant_id": "VC_101", "answer": "approve", "approved_by": "ui:user", "max_records": 500}
DQ_QUESTION_ANSWER_RESPONSE_EXAMPLE = {
    "opportunity_id": "dq_enrich_001",
    "status": "proposal_generated",
    "proposal_id": "dq_enrich_prop_001",
    "matched_count": 480,
    "unmatched_count": 20,
}

DQ_APPROVE_RESEARCH_REQUEST_EXAMPLE = {"tenant_id": "VC_101", "approved_by": "ui:user", "max_records": 500}
DQ_APPROVE_RESEARCH_RESPONSE_EXAMPLE = {
    "opportunity_id": "dq_enrich_001",
    "status": "proposal_generated",
    "proposal_id": "dq_enrich_prop_001",
    "target_column": "state",
    "target_column_alias": "state",
    "source_columns_json": ["pincode", "country"],
    "source_column_aliases_json": ["postal_code", "country"],
    "matched_count": 480,
    "unmatched_count": 20,
}

DQ_PROPOSAL_EXAMPLE = {
    "proposal_id": "dq_enrich_prop_001",
    "opportunity_id": "dq_enrich_001",
    "status": "proposed",
    "table_name": "customer",
    "target_column": "state",
    "target_column_alias": "state",
    "source_columns_json": ["pincode", "country"],
    "source_column_aliases_json": ["postal_code", "country"],
    "candidate_method": "postal_context_inference",
    "matched_count": 480,
    "unmatched_count": 20,
    "source_references": [],
    "sample_proposed_values": [],
    "summary": {
        "total_candidate_rows": 500,
        "confidence_buckets": {"auto_approve": 220, "high_confidence": 180, "needs_review": 80},
        "grouped_values": [{"proposed_value": "Karnataka", "row_count": 140}],
    },
}

DQ_APPROVE_APPLICATION_REQUEST_EXAMPLE = {
    "tenant_id": "VC_101",
    "approved_by": "data_steward:user",
    "application_mode": "staged_overlay",
    "approval_scope": "high_confidence",
    "min_confidence": 0.85,
    "reason": "Reviewed postal reference matches",
}

DQ_APPROVE_APPLICATION_RESPONSE_EXAMPLE = {
    "proposal_id": "dq_enrich_prop_001",
    "status": "approved_for_staging",
    "application_mode": "staged_overlay",
    "approval_scope": "high_confidence",
    "confidence_threshold": 0.85,
    "approved_row_count": 400,
    "deferred_row_count": 80,
    "staged_artifact_id": "artifact_stage_001",
}

DQ_STAGED_ARTIFACT_EXAMPLE = {
    "artifact_id": "artifact_stage_001",
    "event_id": "evt_stage_001",
    "logical_event_id": "dq_stage::dq_enrich_prop_001",
    "run_id": "run_dq_001",
    "proposal_id": "dq_enrich_prop_001",
    "status": "approved_for_staging",
    "approved_row_count": 400,
    "deferred_row_count": 80,
    "approval_scope": "high_confidence",
    "confidence_threshold": 0.85,
    "raw_json": {"approved_rows": [], "deferred_rows": []},
}

DQ_RESUME_REQUEST_EXAMPLE = {"requested_by": "ui:user"}
DQ_RESUME_RESPONSE_EXAMPLE = {
    "run_id": "run_dq_001",
    "status": "queued",
    "job_id": "job_resume_001",
    "resume_mode": "after_rule_review",
}


@app.get(
    "/data-quality/runs/{run_id}",
    tags=["data-quality"],
    summary="Get data quality run summary",
    description="Return the data-quality workflow summary produced by a data_quality_observability deployment run.",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "completed_run": {
                                "summary": "Completed data quality run summary",
                                "value": DQ_RUN_SUMMARY_EXAMPLE,
                            }
                        }
                    }
                }
            }
        }
    },
)
def get_data_quality_run_summary(run_id: str) -> dict:
    row = get_quality_run_by_run_id(settings, run_id)
    if not row:
        raise HTTPException(status_code=404, detail="Data quality run not found")
    try:
        remediation_plan = build_data_quality_remediation_plan(
            settings,
            tenant_id=str(row.get("tenant_id") or ""),
            domain_id=str(row.get("domain_id") or "data_quality_observability"),
            run_id=run_id,
            limit=5,
        )
    except Exception:
        remediation_plan = {"summary": {}, "actions": []}
    return build_data_quality_run_summary_payload(row=row, remediation_plan=remediation_plan)


@app.get(
    "/data-quality/runs/{run_id}/hydration",
    tags=["data-quality"],
    summary="Get data quality run hydration payload",
    description="Return the consolidated data-quality state needed to rehydrate a deployment run UI, including summary, pending rule review, enrichment questions, and remediation.",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "hydration": {
                                "summary": "Hydration payload for run reload",
                                "value": DQ_RUN_HYDRATION_EXAMPLE,
                            }
                        }
                    }
                }
            }
        }
    },
)
def get_data_quality_run_hydration(run_id: str) -> dict:
    row = get_quality_run_by_run_id(settings, run_id)
    if not row:
        raise HTTPException(status_code=404, detail="Data quality run not found")
    tenant_id = str(row.get("tenant_id") or "")
    domain_id = str(row.get("domain_id") or "data_quality_observability")
    try:
        remediation_plan = build_data_quality_remediation_plan(
            settings,
            tenant_id=tenant_id,
            domain_id=domain_id,
            run_id=run_id,
            limit=5,
        )
    except Exception:
        remediation_plan = {"summary": {}, "actions": []}
    try:
        rule_review_queue = get_quality_rule_review_queue(
            settings,
            tenant_id=tenant_id,
            domain_id=domain_id,
            run_id=run_id,
        )
    except Exception:
        rule_review_queue = {"summary": {}, "rules": []}
    try:
        enrichment_question_queue = build_enrichment_question_queue(
            settings,
            tenant_id=tenant_id,
            domain_id=domain_id,
            run_id=run_id,
            limit=10,
        )
    except Exception:
        enrichment_question_queue = {"summary": {}, "questions": []}
    return build_data_quality_run_hydration_payload(
        row=row,
        remediation_plan=remediation_plan,
        rule_review_queue=rule_review_queue,
        enrichment_question_queue=enrichment_question_queue,
    )


@app.post(
    "/data-quality/runs/{run_id}/resume-after-rule-review",
    tags=["data-quality"],
    summary="Resume a paused data quality run after rule review",
    description="Queue continuation of a data-quality run that is waiting for rule review so approved rules execute and the workflow can finish.",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "resume": {
                            "summary": "Resume after rule review",
                            "value": DQ_RESUME_REQUEST_EXAMPLE,
                        }
                    }
                }
            }
        },
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "queued": {
                                "summary": "Resume queued",
                                "value": DQ_RESUME_RESPONSE_EXAMPLE,
                            }
                        }
                    }
                }
            }
        },
    },
)
def resume_data_quality_run_after_rule_review(run_id: str, payload: dict | None = None) -> dict:
    run = get_quality_run_by_run_id(settings, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Data quality run not found")
    pending = list_quality_rules(
        settings,
        tenant_id=str(run.get("tenant_id") or ""),
        domain_id=str(run.get("domain_id") or "data_quality_observability"),
        run_id=run_id,
        limit=500,
    )
    unresolved = [row for row in pending if str(row.get("status") or "").strip().lower() in {"needs_review", "unsupported"}]
    if unresolved:
        raise HTTPException(status_code=409, detail="Rule review is still pending for this run")
    if str(run.get("status") or "").strip().lower() == "completed":
        raise HTTPException(status_code=409, detail="Data quality run is already completed")
    job = create_job(
        settings,
        tenant_id=str(run.get("tenant_id") or ""),
        domain_id=str(run.get("domain_id") or "data_quality_observability"),
        job_type="data_quality_resume_after_rule_review",
        payload={"run_id": run_id, **(payload or {})},
        idempotency_key=None,
    )
    mark_run_status(settings, run_id, "queued")
    return {
        "run_id": run_id,
        "status": "queued",
        "job_id": job.get("job_id"),
        "resume_mode": "after_rule_review",
    }


@app.get(
    "/data-quality/tables",
    tags=["data-quality"],
    summary="List data quality table summaries",
    description="Return table-level quality artifacts for a data quality deployment run.",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "tables": {
                                "summary": "Table quality list",
                                "value": DQ_TABLES_EXAMPLE,
                            }
                        }
                    }
                }
            }
        }
    },
)
def list_data_quality_table_summaries(
    tenant_id: str,
    domain_id: str = "data_quality_observability",
    run_id: str | None = None,
    limit: int = 100,
) -> dict:
    duplicate_candidates = list_quality_duplicate_candidates(
        settings,
        tenant_id=tenant_id,
        domain_id=domain_id,
        run_id=run_id,
        limit=500,
    )
    enrichment_opportunities = list_quality_enrichment_opportunities(
        settings,
        tenant_id=tenant_id,
        domain_id=domain_id,
        run_id=run_id,
        limit=500,
    )
    duplicate_counts: dict[str, int] = {}
    for item in duplicate_candidates:
        table_name = str(item.get("table_name") or "").strip()
        if table_name:
            duplicate_counts[table_name] = duplicate_counts.get(table_name, 0) + 1
    enrichment_counts: dict[str, int] = {}
    for item in enrichment_opportunities:
        table_name = str(item.get("table_name") or "").strip()
        if table_name:
            enrichment_counts[table_name] = enrichment_counts.get(table_name, 0) + 1
    rows = list_quality_tables(
        settings,
        tenant_id=tenant_id,
        domain_id=domain_id,
        run_id=run_id,
        limit=limit,
    )
    return {
        "tenant_id": tenant_id,
        "domain_id": domain_id,
        "run_id": run_id,
        "tables": [
            {
                "quality_run_id": row.get("quality_run_id"),
                "run_id": row.get("run_id"),
                "table_name": row.get("table_name"),
                "row_count": row.get("row_count"),
                "trust_score": row.get("trust_score"),
                "completeness_score": row.get("completeness_score"),
                "freshness_score": row.get("freshness_score"),
                "duplicate_risk_score": row.get("duplicate_risk_score"),
                "severity": row.get("severity"),
                "duplicate_candidate_count": duplicate_counts.get(str(row.get("table_name") or ""), 0),
                "enrichment_opportunity_count": enrichment_counts.get(str(row.get("table_name") or ""), 0),
                "summary": row.get("summary_json") or {},
            }
            for row in rows
        ],
    }


@app.get(
    "/data-quality/rules",
    tags=["data-quality"],
    summary="List data quality rules and latest results",
    description="Return validation rules extracted for a data quality deployment run with latest execution status.",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "rules": {
                                "summary": "Rule list with latest results",
                                "value": DQ_RULES_EXAMPLE,
                            }
                        }
                    }
                }
            }
        }
    },
)
def list_data_quality_rules(
    tenant_id: str,
    domain_id: str = "data_quality_observability",
    run_id: str | None = None,
    status: str | None = None,
    rule_status: str | None = None,
    limit: int = 100,
) -> dict:
    rows = list_quality_rules(
        settings,
        tenant_id=tenant_id,
        domain_id=domain_id,
        run_id=run_id,
        status=status,
        rule_status=rule_status,
        limit=limit,
    )
    return {
        "tenant_id": tenant_id,
        "domain_id": domain_id,
        "run_id": run_id,
        "rules": [
            {
                "rule_id": row.get("rule_id"),
                "quality_run_id": row.get("quality_run_id"),
                "run_id": row.get("run_id"),
                "rule_type": row.get("rule_type"),
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
                    "checked_row_count": row.get("checked_row_count"),
                    "violation_count": row.get("violation_count"),
                    "violation_pct": row.get("violation_pct"),
                    "sample_rows_json": row.get("sample_rows_json") or [],
                    "error_message": row.get("error_message"),
                    "executed_at": row.get("executed_at"),
                }
                if row.get("result_id")
                else None,
            }
            for row in rows
        ],
    }


@app.get(
    "/data-quality/rules/review-queue",
    tags=["data-quality"],
    summary="Get data quality rule review queue",
    description="Return reviewable low-confidence or unsupported rules before they are approved for execution.",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "queue": {
                                "summary": "Review queue",
                                "value": DQ_RULE_REVIEW_QUEUE_EXAMPLE,
                            }
                        }
                    }
                }
            }
        }
    },
)
def get_data_quality_rule_review_queue(
    tenant_id: str,
    run_id: str,
    domain_id: str = "data_quality_observability",
) -> dict:
    return get_quality_rule_review_queue(
        settings,
        tenant_id=tenant_id,
        domain_id=domain_id,
        run_id=run_id,
    )


@app.get(
    "/data-quality/rules/{rule_id}/review",
    tags=["data-quality"],
    summary="Get one data quality rule for review",
    description="Return the stored interpretation, SQL preview, and latest result metadata for one rule review item.",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "detail": {
                                "summary": "Review detail for one rule",
                                "value": DQ_RULE_REVIEW_DETAIL_EXAMPLE,
                            }
                        }
                    }
                }
            }
        }
    },
)
def get_data_quality_rule_review_detail(
    rule_id: str,
    tenant_id: str | None = None,
) -> dict:
    row = get_quality_rule_for_review(
        settings,
        rule_id=rule_id,
        tenant_id=tenant_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Data quality rule not found")
    return {
        "rule_id": row.get("rule_id"),
        "quality_run_id": row.get("quality_run_id"),
        "run_id": row.get("run_id"),
        "tenant_id": row.get("tenant_id"),
        "domain_id": row.get("domain_id"),
        "rule_type": row.get("rule_type"),
        "severity": row.get("severity"),
        "table_name": row.get("table_name"),
        "column_name": row.get("column_name"),
        "reference_table": row.get("reference_table"),
        "reference_column": row.get("reference_column"),
        "source_text": row.get("source_text") or (row.get("condition_json") or {}).get("source_text"),
        "condition_json": row.get("condition_json") or {},
        "executor_kind": row.get("executor_kind"),
        "execution_plan": row.get("execution_plan_json") or {},
        "sql_preview": (row.get("execution_plan_json") or {}).get("sql_preview") or {},
        "sql_preview_status": (row.get("execution_plan_json") or {}).get("sql_preview_status"),
        "sql_preview_source": (row.get("execution_plan_json") or {}).get("sql_preview_source"),
        "confidence": row.get("confidence"),
        "rule_status": row.get("status"),
        "reviewed_by": row.get("reviewed_by"),
        "reviewed_at": row.get("reviewed_at"),
        "review_notes": row.get("review_notes"),
        "result": {
            "result_id": row.get("result_id"),
            "status": row.get("result_status"),
            "checked_row_count": row.get("checked_row_count"),
            "violation_count": row.get("violation_count"),
            "violation_pct": row.get("violation_pct"),
            "sample_rows_json": row.get("sample_rows_json") or [],
            "error_message": row.get("error_message"),
            "executed_at": row.get("executed_at"),
        }
        if row.get("result_id")
        else None,
    }


@app.post(
    "/data-quality/rules/{rule_id}/review",
    tags=["data-quality"],
    summary="Review and optionally execute one data quality rule",
    description="Approve, reject, or edit a reviewable data quality rule and optionally execute it after approval.",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "approve_rule": {
                            "summary": "Approve with condition patch",
                            "value": {
                                "tenant_id": "VC_101",
                                "reviewed_by": "ui:user",
                                "action": "approve",
                                "review_notes": "Allowed values confirmed by steward",
                                "condition_json": {
                                    "allowed_values": ["CREATED", "SHIPPED", "CANCELLED"],
                                },
                            },
                        },
                        "reject_rule": {
                            "summary": "Reject rule",
                            "value": {
                                "tenant_id": "VC_101",
                                "reviewed_by": "ui:user",
                                "action": "reject",
                                "review_notes": "This rule is out of scope",
                            },
                        },
                    }
                }
            }
        },
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "approved": {
                                "summary": "Rule review applied",
                                "value": {
                                    "rule_id": "dq_rule_101",
                                    "status": "approved",
                                    "stored_rule": {"rule_id": "dq_rule_101", "status": "active"},
                                    "execution": None,
                                },
                            }
                        }
                    }
                }
            }
        },
    },
)
def review_data_quality_rule(rule_id: str, payload: dict) -> dict:
    tenant_id = str(payload.get("tenant_id") or "").strip() or None
    row = get_quality_rule(settings, rule_id, tenant_id=tenant_id)
    if not row:
        raise HTTPException(status_code=404, detail="Data quality rule not found")
    run_row = get_quality_run_by_run_id(settings, str(row.get("run_id") or ""))
    reviewed_by = str(payload.get("reviewed_by") or "").strip() or "system:manual_review"
    action = str(payload.get("action") or "").strip().lower()
    rule_patch = {
        key: payload.get(key)
        for key in ["source_text", "severity", "table_name", "column_name", "reference_table", "reference_column", "condition_json"]
        if key in payload
    }
    try:
        execute_default = str((run_row or {}).get("status") or "").strip().lower() not in {"awaiting_rule_review"}
        result = apply_quality_rule_review_action(
            settings,
            rule_row=row,
            action=action,
            reviewed_by=reviewed_by,
            review_notes=str(payload.get("review_notes") or "").strip() or None,
            rule_patch=rule_patch or None,
            execute_after_approval=bool(payload.get("execute_after_approval", execute_default)),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "rule_id": result.get("rule_id"),
        "status": result.get("status"),
        "stored_rule": result.get("stored_rule"),
        "execution": result.get("execution"),
    }


@app.get(
    "/data-quality/tables/{table_name}",
    tags=["data-quality"],
    summary="Get data quality table detail",
    description="Return table and column quality artifacts for one table.",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "detail": {
                                "summary": "One table detail",
                                "value": DQ_TABLE_DETAIL_EXAMPLE,
                            }
                        }
                    }
                }
            }
        }
    },
)
def get_data_quality_table_summary(
    table_name: str,
    tenant_id: str,
    domain_id: str = "data_quality_observability",
    run_id: str | None = None,
) -> dict:
    failed_rules = [
        item
        for item in list_quality_rules(
            settings,
            tenant_id=tenant_id,
            domain_id=domain_id,
            run_id=run_id,
            status="failed",
            limit=200,
        )
        if str(item.get("table_name") or "") == str(table_name)
    ]
    duplicate_candidates = list_quality_duplicate_candidates(
        settings,
        tenant_id=tenant_id,
        domain_id=domain_id,
        run_id=run_id,
        table_name=table_name,
        limit=100,
    )
    enrichment_opportunities = [
        item
        for item in list_quality_enrichment_opportunities(
            settings,
            tenant_id=tenant_id,
            domain_id=domain_id,
            run_id=run_id,
            limit=100,
        )
        if str(item.get("table_name") or "") == str(table_name)
    ]
    row = get_quality_table_detail(
        settings,
        tenant_id=tenant_id,
        domain_id=domain_id,
        table_name=table_name,
        run_id=run_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Data quality table not found")
    return {
        "quality_run_id": row.get("quality_run_id"),
        "run_id": row.get("run_id"),
        "tenant_id": row.get("tenant_id"),
        "domain_id": row.get("domain_id"),
        "table_name": row.get("table_name"),
        "row_count": row.get("row_count"),
        "trust_score": row.get("trust_score"),
        "completeness_score": row.get("completeness_score"),
        "freshness_score": row.get("freshness_score"),
        "duplicate_risk_score": row.get("duplicate_risk_score"),
        "severity": row.get("severity"),
        "components": {
            **(((row.get("summary_json") or {}).get("trust_components") or {})),
            **{
                "completeness": ((row.get("summary_json") or {}).get("trust_components") or {}).get("completeness", row.get("completeness_score")),
                "validity": ((row.get("summary_json") or {}).get("trust_components") or {}).get("validity", row.get("validity_score")),
                "referential_integrity": ((row.get("summary_json") or {}).get("trust_components") or {}).get("referential_integrity", row.get("referential_integrity_score")),
                "duplicate_risk": ((row.get("summary_json") or {}).get("trust_components") or {}).get("duplicate_risk", row.get("duplicate_risk_score")),
                "freshness": ((row.get("summary_json") or {}).get("trust_components") or {}).get("freshness", row.get("freshness_score")),
            },
        },
        "trust_component_explanations": (row.get("summary_json") or {}).get("trust_component_explanations") or {},
        "summary": row.get("summary_json") or {},
        "columns": row.get("columns") or [],
        "failed_rules": failed_rules,
        "duplicate_candidates": duplicate_candidates,
        "enrichment_opportunities": enrichment_opportunities,
    }


@app.get(
    "/data-quality/freshness",
    tags=["data-quality"],
    summary="List freshness and stability results",
    description="Return freshness and stability rows derived for a data quality deployment run.",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "freshness": {
                                "summary": "Freshness and stability rows",
                                "value": DQ_FRESHNESS_EXAMPLE,
                            }
                        }
                    }
                }
            }
        }
    },
)
def list_data_quality_freshness_results(
    tenant_id: str,
    domain_id: str = "data_quality_observability",
    run_id: str | None = None,
    limit: int = 100,
) -> dict:
    tables = list_quality_tables(
        settings,
        tenant_id=tenant_id,
        domain_id=domain_id,
        run_id=run_id,
        limit=limit,
    )
    rows = []
    for table in tables:
        summary = table.get("summary_json") or {}
        freshness = summary.get("freshness_analysis") or {}
        stability = summary.get("stability_analysis") or {}
        rows.append(
            {
                "table_name": table.get("table_name"),
                "freshness_column": freshness.get("freshness_column"),
                "latest_timestamp": freshness.get("latest_timestamp"),
                "freshness_lag_days": freshness.get("freshness_lag_days"),
                "freshness_score": freshness.get("freshness_score") or table.get("freshness_score"),
                "freshness_status": freshness.get("freshness_status"),
                "baseline_quality_run_id": stability.get("baseline_quality_run_id"),
                "baseline_row_count": stability.get("baseline_row_count"),
                "row_count_change_pct": stability.get("row_count_change_pct"),
                "baseline_completeness_score": stability.get("baseline_completeness_score"),
                "completeness_score_change": stability.get("completeness_score_change"),
                "stability_status": stability.get("stability_status"),
                "stability_issues": stability.get("stability_issues") or [],
            }
        )
    return {
        "tenant_id": tenant_id,
        "domain_id": domain_id,
        "run_id": run_id,
        "freshness": rows,
    }


@app.get(
    "/data-quality/duplicates",
    tags=["data-quality"],
    summary="List duplicate candidates",
    description="Return persisted duplicate candidates for a data quality deployment run.",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "duplicates": {
                                "summary": "Duplicate candidates",
                                "value": DQ_DUPLICATES_EXAMPLE,
                            }
                        }
                    }
                }
            }
        }
    },
)
def list_data_quality_duplicate_candidates(
    tenant_id: str,
    domain_id: str = "data_quality_observability",
    run_id: str | None = None,
    table_name: str | None = None,
    review_status: str | None = None,
    limit: int = 100,
) -> dict:
    rows = list_quality_duplicate_candidates(
        settings,
        tenant_id=tenant_id,
        domain_id=domain_id,
        run_id=run_id,
        table_name=table_name,
        review_status=review_status,
        limit=limit,
    )
    return {
        "tenant_id": tenant_id,
        "domain_id": domain_id,
        "run_id": run_id,
        "table_name": table_name,
        "review_status": review_status,
        "duplicates": rows,
    }


@app.get(
    "/data-quality/remediation",
    tags=["data-quality"],
    summary="Get recommended remediation actions",
    description="Return prioritized remediation actions derived from persisted trust, rule, duplicate, freshness, and enrichment artifacts.",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "remediation": {
                                "summary": "Recommended actions",
                                "value": DQ_REMEDIATION_EXAMPLE,
                            }
                        }
                    }
                }
            }
        }
    },
)
def get_data_quality_remediation(
    tenant_id: str,
    run_id: str,
    domain_id: str = "data_quality_observability",
    limit: int = 25,
) -> dict:
    plan = build_data_quality_remediation_plan(
        settings,
        tenant_id=tenant_id,
        domain_id=domain_id,
        run_id=run_id,
        limit=limit,
    )
    return {
        "tenant_id": tenant_id,
        "domain_id": domain_id,
        "run_id": run_id,
        "summary": plan.get("summary") or {},
        "actions": plan.get("actions") or [],
    }


@app.get(
    "/data-quality/evidence/missingness",
    tags=["data-quality"],
    summary="Get missingness evidence rows",
    description="Return underlying source rows for a missing/null/blank column issue.",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "missingness": {
                                "summary": "Missingness drill-through",
                                "value": DQ_MISSINGNESS_EVIDENCE_EXAMPLE,
                            }
                        }
                    }
                }
            }
        }
    },
)
def get_data_quality_missingness_evidence(
    tenant_id: str,
    run_id: str,
    table_name: str,
    column_name: str,
    domain_id: str = "data_quality_observability",
    include_blank: bool = True,
    limit: int = 100,
    offset: int = 0,
) -> dict:
    run_row = load_quality_run(settings, run_id=run_id, tenant_id=tenant_id, domain_id=domain_id)
    return fetch_missingness_evidence(
        settings,
        run_row=run_row,
        table_name=table_name,
        column_name=column_name,
        include_blank=include_blank,
        limit=limit,
        offset=offset,
    )


@app.get(
    "/data-quality/evidence/rules/{rule_id}",
    tags=["data-quality"],
    summary="Get rule evidence rows",
    description="Return persisted and, when possible, source evidence rows for a data quality rule.",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "rule_evidence": {
                                "summary": "Rule drill-through",
                                "value": DQ_RULE_EVIDENCE_EXAMPLE,
                            }
                        }
                    }
                }
            }
        }
    },
)
def get_data_quality_rule_evidence(
    rule_id: str,
    tenant_id: str,
    domain_id: str = "data_quality_observability",
    limit: int = 100,
) -> dict:
    return fetch_rule_evidence(
        settings,
        tenant_id=tenant_id,
        domain_id=domain_id,
        rule_id=rule_id,
        limit=limit,
    )


@app.get(
    "/data-quality/evidence/duplicates/{candidate_id}",
    tags=["data-quality"],
    summary="Get duplicate evidence rows",
    description="Return backing rows for a duplicate candidate or cluster.",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "duplicate_evidence": {
                                "summary": "Duplicate drill-through",
                                "value": DQ_DUPLICATE_EVIDENCE_EXAMPLE,
                            }
                        }
                    }
                }
            }
        }
    },
)
def get_data_quality_duplicate_evidence(
    candidate_id: str,
    tenant_id: str,
    domain_id: str = "data_quality_observability",
    limit: int = 100,
) -> dict:
    return fetch_duplicate_evidence(
        settings,
        tenant_id=tenant_id,
        domain_id=domain_id,
        candidate_id=candidate_id,
        limit=limit,
    )


@app.get(
    "/data-quality/evidence/freshness/{table_name}",
    tags=["data-quality"],
    summary="Get freshness and stability evidence",
    description="Return baseline/current comparison details for freshness and stability of a table.",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "freshness_evidence": {
                                "summary": "Freshness drill-through",
                                "value": DQ_FRESHNESS_EVIDENCE_EXAMPLE,
                            }
                        }
                    }
                }
            }
        }
    },
)
def get_data_quality_freshness_evidence(
    table_name: str,
    tenant_id: str,
    run_id: str,
    domain_id: str = "data_quality_observability",
) -> dict:
    return fetch_freshness_evidence(
        settings,
        tenant_id=tenant_id,
        domain_id=domain_id,
        run_id=run_id,
        table_name=table_name,
    )


@app.get(
    "/data-quality/evidence/enrichment/{proposal_id}",
    tags=["data-quality"],
    summary="Get enrichment proposal evidence",
    description="Return proposed enrichment rows and source references for a proposal.",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "enrichment_evidence": {
                                "summary": "Enrichment drill-through",
                                "value": DQ_ENRICHMENT_EVIDENCE_EXAMPLE,
                            }
                        }
                    }
                }
            }
        }
    },
)
def get_data_quality_enrichment_evidence(
    proposal_id: str,
    tenant_id: str,
    limit: int = 100,
) -> dict:
    return fetch_enrichment_evidence(
        settings,
        proposal_id=proposal_id,
        tenant_id=tenant_id,
        limit=limit,
    )


@app.get(
    "/data-quality/reports/{run_id}/excel",
    tags=["data-quality"],
    summary="Download data quality Excel report",
    description="Generate an Excel workbook from persisted data-quality artifacts for a completed deployment run.",
    openapi_extra={
        "responses": {
            "200": {
                "description": "Excel workbook download",
                "content": {
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": {
                        "schema": {"type": "string", "format": "binary"}
                    }
                },
                "headers": {
                    "Content-Disposition": {
                        "description": "Attachment file name",
                        "schema": {"type": "string"},
                        "example": 'attachment; filename="data_quality_run_dq_001.xlsx"',
                    }
                },
            }
        }
    },
)
def download_data_quality_excel_report(
    run_id: str,
    tenant_id: str,
    domain_id: str = "data_quality_observability",
) -> Response:
    try:
        workbook, file_name, _summary = build_data_quality_excel_report(
            settings,
            tenant_id=tenant_id,
            domain_id=domain_id,
            run_id=run_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(
        content=workbook,
        media_type=EXCEL_MIME_TYPE,
        headers={"Content-Disposition": f'attachment; filename="{file_name}"'},
    )


@app.get(
    "/data-quality/runs/{run_id}/dashboard",
    tags=["data-quality"],
    summary="Get data quality dashboard for a run",
    description="Resolve the generated data quality dashboard for a deployment run and return its persisted dashboard metadata.",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "dashboard": {
                                "summary": "Data quality dashboard",
                                "value": DQ_DASHBOARD_EXAMPLE,
                            }
                        }
                    }
                }
            }
        }
    },
)
def get_data_quality_dashboard(run_id: str) -> dict:
    row = get_quality_run_by_run_id(settings, run_id)
    if not row:
        raise HTTPException(status_code=404, detail="Data quality run not found")
    summary = row.get("summary_json") or {}
    dashboard_id = summary.get("dashboard_id")
    if not dashboard_id:
        raise HTTPException(status_code=404, detail="Data quality dashboard not found")
    dashboard = get_dashboard_spec(settings, dashboard_id)
    if not dashboard:
        raise HTTPException(status_code=404, detail="Data quality dashboard not found")
    return {
        "run_id": run_id,
        "dashboard_id": dashboard.get("dashboard_id"),
        "dashboard_type": dashboard.get("dashboard_type"),
        "title": dashboard.get("title") or dashboard.get("name"),
        "name": dashboard.get("name"),
        "description": dashboard.get("description"),
        "status": dashboard.get("status"),
        "quality_score": dashboard.get("quality_score"),
        "quality_gate_passed": dashboard.get("quality_gate_passed"),
        "chart_plan": dashboard.get("chart_plan") or [],
        "charts": dashboard.get("charts") or [],
    }


@app.get(
    "/data-quality/enrichment/opportunities",
    tags=["data-quality"],
    summary="List data quality enrichment opportunities",
    description="Return user-reviewable enrichment opportunities discovered from data quality profiling artifacts.",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "opportunities": {
                                "summary": "Enrichment opportunities",
                                "value": DQ_OPPORTUNITIES_EXAMPLE,
                            }
                        }
                    }
                }
            }
        }
    },
)
def list_data_quality_enrichment_opportunities(
    tenant_id: str,
    domain_id: str = "data_quality_observability",
    run_id: str | None = None,
    status: str | None = None,
    limit: int = 100,
) -> dict:
    rows = list_quality_enrichment_opportunities(
        settings,
        tenant_id=tenant_id,
        domain_id=domain_id,
        run_id=run_id,
        status=status,
        limit=limit,
    )
    return {
        "tenant_id": tenant_id,
        "domain_id": domain_id,
        "run_id": run_id,
        "opportunities": [
            {
                "opportunity_id": row.get("opportunity_id"),
                "quality_run_id": row.get("quality_run_id"),
                "run_id": row.get("run_id"),
                "table_name": row.get("table_name"),
                "target_column": row.get("target_column"),
                "target_column_alias": canonical_column_alias(row.get("target_column")),
                "source_columns_json": row.get("source_columns_json") or [],
                "source_column_aliases_json": canonical_column_aliases(row.get("source_columns_json") or []),
                "missing_count": row.get("missing_count"),
                "candidate_method": row.get("candidate_method"),
                "requires_external_lookup": row.get("requires_external_lookup"),
                "requires_user_approval": row.get("requires_user_approval"),
                "confidence": row.get("confidence"),
                "question": row.get("question"),
                "status": row.get("status"),
                "created_at": row.get("created_at"),
                "updated_at": row.get("updated_at"),
            }
            for row in rows
        ],
    }


@app.get(
    "/data-quality/enrichment/questions",
    tags=["data-quality"],
    summary="List question-centric enrichment review items",
    description="Return enrichment opportunities as user-facing questions with answer actions and proposal links.",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "questions": {
                                "summary": "Question-centric enrichment queue",
                                "value": DQ_QUESTIONS_EXAMPLE,
                            }
                        }
                    }
                }
            }
        }
    },
)
def list_data_quality_enrichment_questions(
    tenant_id: str,
    domain_id: str = "data_quality_observability",
    run_id: str | None = None,
    status: str | None = None,
    limit: int = 100,
) -> dict:
    return build_enrichment_question_queue(
        settings,
        tenant_id=tenant_id,
        domain_id=domain_id,
        run_id=run_id,
        status=status,
        limit=limit,
    )


@app.post(
    "/data-quality/enrichment/questions/{opportunity_id}/answer",
    tags=["data-quality"],
    summary="Answer an enrichment review question",
    description="Approve, defer, reject, or reopen a question-centric enrichment item. Approval generates a proposal using the existing staged enrichment flow.",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "approve": {
                            "summary": "Approve question and generate proposal",
                            "value": DQ_QUESTION_ANSWER_REQUEST_EXAMPLE,
                        },
                        "defer": {
                            "summary": "Defer question",
                            "value": {"tenant_id": "VC_101", "answer": "defer"},
                        },
                    }
                }
            }
        },
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "proposal_generated": {
                                "summary": "Question answered with proposal generation",
                                "value": DQ_QUESTION_ANSWER_RESPONSE_EXAMPLE,
                            }
                        }
                    }
                }
            }
        },
    },
)
def answer_data_quality_enrichment_question(opportunity_id: str, payload: dict) -> dict:
    tenant_id = str(payload.get("tenant_id") or "").strip()
    if not tenant_id:
        raise HTTPException(status_code=400, detail="tenant_id is required")
    answer = str(payload.get("answer") or "").strip().lower()
    if answer not in {"approve", "defer", "reject", "reopen"}:
        raise HTTPException(status_code=400, detail="answer must be one of approve, defer, reject, reopen")
    opportunity = get_quality_enrichment_opportunity(settings, opportunity_id, tenant_id=tenant_id)
    if not opportunity:
        raise HTTPException(status_code=404, detail="Enrichment opportunity not found")
    if answer == "defer":
        updated = update_quality_enrichment_opportunity_status(
            settings,
            opportunity_id,
            tenant_id=tenant_id,
            status="deferred_by_user",
        )
        queue_item = build_enrichment_question_queue(
            settings,
            tenant_id=tenant_id,
            domain_id=str(updated.get("domain_id") or opportunity.get("domain_id") or "data_quality_observability"),
            run_id=str(updated.get("run_id") or opportunity.get("run_id") or ""),
            limit=500,
        )
        question = next((item for item in (queue_item.get("questions") or []) if item.get("opportunity_id") == opportunity_id), None)
        return {"opportunity_id": opportunity_id, "status": "deferred", "question": question}
    if answer == "reject":
        updated = update_quality_enrichment_opportunity_status(
            settings,
            opportunity_id,
            tenant_id=tenant_id,
            status="rejected_by_user",
        )
        queue_item = build_enrichment_question_queue(
            settings,
            tenant_id=tenant_id,
            domain_id=str(updated.get("domain_id") or opportunity.get("domain_id") or "data_quality_observability"),
            run_id=str(updated.get("run_id") or opportunity.get("run_id") or ""),
            limit=500,
        )
        question = next((item for item in (queue_item.get("questions") or []) if item.get("opportunity_id") == opportunity_id), None)
        return {"opportunity_id": opportunity_id, "status": "rejected", "question": question}
    if answer == "reopen":
        updated = update_quality_enrichment_opportunity_status(
            settings,
            opportunity_id,
            tenant_id=tenant_id,
            status="needs_user_approval",
        )
        queue_item = build_enrichment_question_queue(
            settings,
            tenant_id=tenant_id,
            domain_id=str(updated.get("domain_id") or opportunity.get("domain_id") or "data_quality_observability"),
            run_id=str(updated.get("run_id") or opportunity.get("run_id") or ""),
            limit=500,
        )
        question = next((item for item in (queue_item.get("questions") or []) if item.get("opportunity_id") == opportunity_id), None)
        return {"opportunity_id": opportunity_id, "status": "pending_answer", "question": question}
    tenant_payload = dict(payload)
    tenant_payload["tenant_id"] = tenant_id
    result = approve_data_quality_enrichment_research(opportunity_id, tenant_payload)
    proposal = get_latest_quality_enrichment_proposal_for_opportunity(settings, opportunity_id, tenant_id=tenant_id)
    queue_item = build_enrichment_question_queue(
        settings,
        tenant_id=tenant_id,
        domain_id=str(opportunity.get("domain_id") or "data_quality_observability"),
        run_id=str(opportunity.get("run_id") or ""),
        limit=500,
    )
    question = next((item for item in (queue_item.get("questions") or []) if item.get("opportunity_id") == opportunity_id), None)
    return {
        "opportunity_id": opportunity_id,
        "status": "proposal_generated",
        "proposal_id": (proposal or {}).get("proposal_id") or result.get("proposal_id"),
        "question": question,
        "matched_count": result.get("matched_count"),
        "unmatched_count": result.get("unmatched_count"),
    }


@app.post(
    "/data-quality/enrichment/opportunities/{opportunity_id}/approve-research",
    tags=["data-quality"],
    summary="Approve enrichment research",
    description="Approve a discovered enrichment opportunity for research/proposal generation.",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "approve_research": {
                            "summary": "Generate enrichment proposal",
                            "value": DQ_APPROVE_RESEARCH_REQUEST_EXAMPLE,
                        }
                    }
                }
            }
        },
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "proposal_generated": {
                                "summary": "Proposal generated",
                                "value": DQ_APPROVE_RESEARCH_RESPONSE_EXAMPLE,
                            }
                        }
                    }
                }
            }
        },
    },
)
def approve_data_quality_enrichment_research(opportunity_id: str, payload: dict) -> dict:
    tenant_id = str(payload.get("tenant_id") or "").strip()
    if not tenant_id:
        raise HTTPException(status_code=400, detail="tenant_id is required")
    opportunity = get_quality_enrichment_opportunity(settings, opportunity_id, tenant_id=tenant_id)
    if not opportunity:
        raise HTTPException(status_code=404, detail="Enrichment opportunity not found")
    run_row = get_quality_run_by_run_id(settings, str(opportunity.get("run_id") or ""))
    if not run_row:
        raise HTTPException(status_code=404, detail="Data quality run not found for enrichment opportunity")
    connection_id = str(run_row.get("connection_id") or "").strip()
    schema_name = str(run_row.get("schema_name") or "public").strip() or "public"
    scoped_conn = None
    if connection_id:
        scoped_conn = resolve_database_credentials_cached(settings, connection_id, schema_name)
    if connection_id and not scoped_conn:
        raise HTTPException(status_code=500, detail="Failed to resolve source connection for enrichment proposal generation")
    max_records = payload.get("max_records")
    proposal = build_enrichment_proposal(
        settings,
        opportunity,
        scoped_conn=scoped_conn,
        schema_name=schema_name,
        max_records=max_records,
    )
    created = create_quality_enrichment_proposal(settings, proposal=proposal)
    if not created:
        raise HTTPException(status_code=500, detail="Failed to create enrichment proposal")
    update_quality_enrichment_opportunity_status(
        settings,
        opportunity_id,
        tenant_id=tenant_id,
        status="proposal_generated",
    )
    return {
        "opportunity_id": opportunity_id,
        "status": "proposal_generated",
        "proposal_id": created.get("proposal_id"),
        "target_column": proposal.get("target_column"),
        "target_column_alias": proposal.get("target_column_alias"),
        "source_columns_json": proposal.get("source_columns_json") or [],
        "source_column_aliases_json": proposal.get("source_column_aliases_json") or [],
        "matched_count": created.get("matched_count"),
        "unmatched_count": created.get("unmatched_count"),
    }


@app.get(
    "/data-quality/enrichment/proposals/{proposal_id}",
    tags=["data-quality"],
    summary="Get enrichment proposal",
    description="Return a persisted enrichment proposal for UI review.",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "proposal": {
                                "summary": "Proposal detail",
                                "value": DQ_PROPOSAL_EXAMPLE,
                            }
                        }
                    }
                }
            }
        }
    },
)
def get_data_quality_enrichment_proposal(proposal_id: str, tenant_id: str | None = None) -> dict:
    proposal = get_quality_enrichment_proposal(settings, proposal_id, tenant_id=tenant_id)
    if not proposal:
        raise HTTPException(status_code=404, detail="Enrichment proposal not found")
    opportunity = get_quality_enrichment_opportunity(
        settings,
        str(proposal.get("opportunity_id") or ""),
        tenant_id=tenant_id,
    ) or {}
    target_column = proposal.get("target_column") or opportunity.get("target_column")
    source_columns = proposal.get("source_columns_json") or opportunity.get("source_columns_json") or []
    summary = summarize_enrichment_proposal(proposal)
    return {
        "proposal_id": proposal.get("proposal_id"),
        "opportunity_id": proposal.get("opportunity_id"),
        "quality_run_id": proposal.get("quality_run_id"),
        "run_id": proposal.get("run_id"),
        "tenant_id": proposal.get("tenant_id"),
        "domain_id": proposal.get("domain_id"),
        "status": proposal.get("status"),
        "table_name": proposal.get("table_name") or opportunity.get("table_name"),
        "target_column": target_column,
        "target_column_alias": proposal.get("target_column_alias") or canonical_column_alias(target_column),
        "source_columns_json": source_columns,
        "source_column_aliases_json": proposal.get("source_column_aliases_json") or canonical_column_aliases(source_columns),
        "candidate_method": proposal.get("candidate_method") or opportunity.get("candidate_method"),
        "matched_count": proposal.get("matched_count"),
        "unmatched_count": proposal.get("unmatched_count"),
        "source_references": proposal.get("source_references_json") or [],
        "sample_proposed_values": summary.get("sample_proposed_values") or [],
        "summary": {
            "total_candidate_rows": summary.get("total_candidate_rows"),
            "confidence_buckets": summary.get("confidence_buckets") or {},
            "method_counts": summary.get("method_counts") or {},
            "grouped_values": summary.get("grouped_values") or [],
        },
        "approved_by": proposal.get("approved_by"),
        "approved_at": proposal.get("approved_at"),
        "created_at": proposal.get("created_at"),
        "updated_at": proposal.get("updated_at"),
    }


@app.post(
    "/data-quality/enrichment/proposals/{proposal_id}/approve-application",
    tags=["data-quality"],
    summary="Approve enrichment proposal application",
    description="Approve a proposal for non-destructive staging. This does not write back to source tables.",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "staged_overlay": {
                            "summary": "Approve for staged overlay",
                            "value": DQ_APPROVE_APPLICATION_REQUEST_EXAMPLE,
                        }
                    }
                }
            }
        },
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "approved_for_staging": {
                                "summary": "Staged overlay created",
                                "value": DQ_APPROVE_APPLICATION_RESPONSE_EXAMPLE,
                            }
                        }
                    }
                }
            }
        },
    },
)
def approve_data_quality_enrichment_application(proposal_id: str, payload: dict) -> dict:
    tenant_id = str(payload.get("tenant_id") or "").strip()
    if not tenant_id:
        raise HTTPException(status_code=400, detail="tenant_id is required")
    approved_by = str(payload.get("approved_by") or "").strip() or "system"
    application_mode = str(payload.get("application_mode") or "staged_overlay").strip() or "staged_overlay"
    approval_scope = str(payload.get("approval_scope") or "high_confidence").strip() or "high_confidence"
    min_confidence = payload.get("min_confidence")
    proposal = get_quality_enrichment_proposal(settings, proposal_id, tenant_id=tenant_id)
    if not proposal:
        raise HTTPException(status_code=404, detail="Enrichment proposal not found")
    opportunity = get_quality_enrichment_opportunity(
        settings,
        str(proposal.get("opportunity_id") or ""),
        tenant_id=tenant_id,
    ) or {}
    proposal_with_context = dict(proposal)
    if opportunity:
        proposal_with_context.setdefault("table_name", opportunity.get("table_name"))
        proposal_with_context.setdefault("target_column", opportunity.get("target_column"))
    selection = select_enrichment_rows_for_application(
        proposal_with_context,
        approval_scope=approval_scope,
        min_confidence=min_confidence,
    )
    updated = update_quality_enrichment_proposal(
        settings,
        proposal_id,
        tenant_id=tenant_id,
        status="approved_for_staging",
        approved_by=approved_by,
    )
    if not updated:
        raise HTTPException(status_code=500, detail="Failed to update enrichment proposal")
    run_id = str(proposal.get("run_id") or "")
    event_id = append_agent_run_event(
        settings,
        run_id,
        "DataEnrichmentApplicationAgent",
        "completed",
        "Staged enrichment overlay artifact created",
        {
            "proposal_id": proposal_id,
            "approved_row_count": len(selection.get("approved_rows") or []),
            "deferred_row_count": len(selection.get("deferred_rows") or []),
            "approval_scope": selection.get("approval_scope"),
        },
    )
    staged_artifact = build_staged_enrichment_overlay_artifact(
        proposal_with_context,
        selection=selection,
        approved_by=approved_by,
        application_mode=application_mode,
        reason=str(payload.get("reason") or "").strip() or None,
    )
    staged_artifact_id = upsert_agent_event_artifact(
        settings,
        event_id=event_id,
        run_id=run_id,
        agent_name="DataEnrichmentApplicationAgent",
        stage_name="staged_overlay",
        logical_event_id=f"dq_stage::{proposal_id}",
        raw_json=staged_artifact,
        summary_raw_text=(
            f"Approved {len(selection.get('approved_rows') or [])} rows for staged overlay; "
            f"deferred {len(selection.get('deferred_rows') or [])} rows."
        ),
        inference_raw_text=json.dumps(
            {
                "approval_scope": selection.get("approval_scope"),
                "confidence_threshold": selection.get("confidence_threshold"),
                "approved_row_count": len(selection.get("approved_rows") or []),
                "deferred_row_count": len(selection.get("deferred_rows") or []),
            }
        ),
    )
    return {
        "proposal_id": proposal_id,
        "status": "approved_for_staging",
        "application_mode": application_mode,
        "approval_scope": selection.get("approval_scope"),
        "confidence_threshold": selection.get("confidence_threshold"),
        "approved_row_count": len(selection.get("approved_rows") or []),
        "deferred_row_count": len(selection.get("deferred_rows") or []),
        "sample_approved_values": (selection.get("approved_rows") or [])[:20],
        "event_id": event_id,
        "staged_artifact_id": staged_artifact_id,
    }


@app.get(
    "/data-quality/enrichment/proposals/{proposal_id}/staged-artifact",
    tags=["data-quality"],
    summary="Get staged enrichment overlay artifact",
    description="Return the persisted staged overlay artifact created when an enrichment proposal was approved for staging.",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "artifact": {
                                "summary": "Staged overlay artifact",
                                "value": DQ_STAGED_ARTIFACT_EXAMPLE,
                            }
                        }
                    }
                }
            }
        }
    },
)
def get_data_quality_enrichment_staged_artifact(proposal_id: str, tenant_id: str | None = None) -> dict:
    proposal = get_quality_enrichment_proposal(settings, proposal_id, tenant_id=tenant_id)
    if not proposal:
        raise HTTPException(status_code=404, detail="Enrichment proposal not found")
    run_id = str(proposal.get("run_id") or "").strip()
    artifact = get_agent_event_artifact_by_logical_event_id(
        settings,
        run_id,
        f"dq_stage::{proposal_id}",
        stage_name="staged_overlay",
    )
    if not artifact:
        raise HTTPException(status_code=404, detail="Staged enrichment artifact not found")
    raw = artifact.get("raw_json") or {}
    return {
        "artifact_id": artifact.get("artifact_id"),
        "event_id": artifact.get("event_id"),
        "logical_event_id": artifact.get("logical_event_id"),
        "run_id": artifact.get("run_id"),
        "proposal_id": proposal_id,
        "status": proposal.get("status"),
        "summary_raw_text": artifact.get("summary_raw_text"),
        "inference_raw_text": artifact.get("inference_raw_text"),
        "raw_json": raw,
        "approved_row_count": raw.get("approved_row_count"),
        "deferred_row_count": raw.get("deferred_row_count"),
        "approval_scope": raw.get("approval_scope"),
        "confidence_threshold": raw.get("confidence_threshold"),
        "created_at": artifact.get("created_at"),
        "updated_at": artifact.get("updated_at"),
    }


@app.post(
    "/workspace/deployments",
    tags=["workspace"],
    summary="Create deployment (first build or new version)",
    description="Canonical deployment entry point. Creates first deployment if none exists, or a new version when one exists. Fails with 409 if another deployment run is already queued/running for the same scope.",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "create_or_redeploy": {
                            "summary": "Create deployment or next version",
                            "value": {
                                "tenant_id": "VC_101",
                                "domain_id": "lpg_production_distribution",
                                "mode": "full",
                            },
                        },
                        "create_with_context_text": {
                            "summary": "Create deployment with inline business context",
                            "value": {
                                "tenant_id": "VC_101",
                                "domain_id": "lpg_production_distribution",
                                "context_text": (
                                    "Total production is the sum of production_14_2kg and production_19kg. "
                                    "Use process_date as the canonical operational date. "
                                    "Zone > Region > Plant is the business hierarchy."
                                ),
                                "mode": "full",
                            },
                        },
                        "create_data_quality_deployment": {
                            "summary": "Create data quality deployment",
                            "value": {
                                "tenant_id": "VC_101",
                                "domain_id": "data_quality_observability",
                                "connection_id": "conn_lpg",
                                "database": "analytics",
                                "schema_name": "public",
                                "mode": "full",
                                "pause_for_rule_review": True,
                                "context_text": (
                                    "Validate orders.customer_id against customer.customer_id. "
                                    "Customer email must be present and valid."
                                ),
                            },
                        },
                        "create_with_context_ids": {
                            "summary": "Create deployment with stored context references",
                            "value": {
                                "tenant_id": "VC_101",
                                "domain_id": "lpg_production_distribution",
                                "context_ids": ["ctx_ops_glossary", "ctx_kpi_formulas"],
                                "mode": "full",
                            },
                        },
                        "create_with_text_and_context_ids": {
                            "summary": "Create deployment with both stored and inline context",
                            "value": {
                                "tenant_id": "VC_101",
                                "domain_id": "lpg_production_distribution",
                                "context_ids": ["ctx_ops_glossary"],
                                "context_text": (
                                    "Total production is total_production. "
                                    "Prefer day and month charts for total productivity and total production."
                                ),
                                "mode": "full",
                            },
                        }
                    }
                }
            }
        },
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "queued": {
                                "summary": "Deployment queued",
                                "value": {
                                    "tenant_id": "VC_101",
                                    "domain_id": "lpg_production_distribution",
                                    "run_id": "run_abc123",
                                    "display_name": "Lpg Production Distribution Deployment v5",
                                    "version_no": 5,
                                    "status": "queued",
                                    "job_id": "job_123",
                                },
                            }
                            ,
                            "dq_queued": {
                                "summary": "Data quality deployment queued",
                                "value": {
                                    "tenant_id": "VC_101",
                                    "domain_id": "data_quality_observability",
                                    "run_id": "run_dq_001",
                                    "display_name": "Data Quality Observability Deployment v3",
                                    "version_no": 3,
                                    "status": "queued",
                                    "workflow_kind": "data_quality",
                                    "job_id": "job_001",
                                },
                            },
                        }
                    }
                }
            },
            "409": {
                "content": {
                    "application/json": {
                        "examples": {
                            "inflight_blocked": {
                                "summary": "Deployment already in progress",
                                "value": {
                                    "detail": {
                                        "message": "A deployment run is already in progress for this tenant/domain.",
                                        "tenant_id": "VC_101",
                                        "domain_id": "lpg_production_distribution",
                                        "run_id": "run_9f2d1a8c45e1",
                                        "status": "running"
                                    }
                                }
                            }
                        }
                    }
                }
            }
        },
    },
)
def workspace_create_deployment(payload: dict) -> dict:
    return _start_workspace_deployment(payload)


@app.put(
    "/workspace/deployments/{run_id}",
    tags=["workspace"],
    summary="Update deployment metadata",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "rename": {
                            "summary": "Rename deployment",
                            "value": {"display_name": "LPG Ops Deployment v5", "make_canonical": False},
                        }
                    }
                }
            }
        },
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "updated": {
                                "summary": "Deployment metadata updated",
                                "value": {
                                    "run_id": "run_1a0f427c86ec",
                                    "tenant_id": "VC_101",
                                    "domain_id": "lpg_production_distribution",
                                    "display_name": "LPG Ops Deployment v5",
                                    "is_canonical": True,
                                    "version_no": 5
                                },
                            }
                        }
                    }
                }
            }
        },
    },
)
def workspace_update_deployment(run_id: str, payload: dict) -> dict:
    updated = update_deployment(
        settings,
        run_id,
        display_name=payload.get("display_name"),
        make_canonical=bool(payload.get("make_canonical")),
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Deployment run not found")
    return updated


@app.get(
    "/workspace/anomalies",
    tags=["workspace"],
    summary="List anomaly investigations",
)
def workspace_list_anomaly_investigations(
    tenant_id: str,
    domain_id: str | None = None,
    run_id: str | None = None,
    limit: int = 50,
) -> dict:
    resolved_domain = _resolve_domain_id(tenant_id, domain_id)
    rows = list_anomaly_investigations(
        settings,
        tenant_id=tenant_id,
        domain_id=resolved_domain,
        run_id=run_id,
        limit=limit,
    )
    return {
        "tenant_id": tenant_id,
        "domain_id": resolved_domain,
        "run_id": run_id,
        "investigations": rows,
    }


@app.get(
    "/workspace/anomalies/{investigation_id}",
    tags=["workspace"],
    summary="Get anomaly investigation",
)
def workspace_get_anomaly_investigation(investigation_id: str) -> dict:
    investigation = get_anomaly_investigation(settings, investigation_id)
    if not investigation:
        raise HTTPException(status_code=404, detail="Anomaly investigation not found")
    anomalies = list_anomaly_records(settings, investigation_id=investigation_id)
    hypotheses = list_anomaly_hypotheses(settings, investigation_id=investigation_id)
    actions = list_anomaly_actions(settings, investigation_id=investigation_id)
    dashboard_links = list_anomaly_dashboard_links(settings, investigation_id=investigation_id)
    return {
        "investigation": investigation,
        "anomalies": anomalies,
        "hypotheses": hypotheses,
        "actions": actions,
        "dashboard_links": dashboard_links,
    }


@app.get(
    "/workspace/anomalies/{investigation_id}/dashboard",
    tags=["workspace"],
    summary="Get linked anomaly dashboard",
)
def workspace_get_anomaly_dashboard(investigation_id: str) -> dict:
    investigation = get_anomaly_investigation(settings, investigation_id)
    if not investigation:
        raise HTTPException(status_code=404, detail="Anomaly investigation not found")
    link = get_anomaly_dashboard_link(settings, investigation_id=investigation_id, role="anomaly_dashboard")
    if not link:
        raise HTTPException(status_code=404, detail="Anomaly dashboard not found")
    dashboard = get_dashboard_spec(settings, link.get("dashboard_id"))
    if not dashboard:
        raise HTTPException(status_code=404, detail="Linked dashboard spec not found")
    return {
        "investigation_id": investigation_id,
        "dashboard_link": link,
        "dashboard": dashboard,
    }


@app.post(
    "/workspace/conversations",
    tags=["workspace"],
    summary="Create a new conversation",
    description=(
        "Create a conversation shell. Three usage patterns:\n\n"
        "1. **Blank** — just `title`, no chart context.\n"
        "2. **Chart-anchored** — provide `chart_id`; title is auto-derived from the chart's original question and the new `conversation_id` is appended to `quantyx_chart_requests.conversation_ids`.\n"
        "3. **Chart-anchored with override** — provide both `chart_id` and `title`; explicit title wins but linkage still happens.\n\n"
        "Use `display_name` for a human-friendly label shown in the UI (defaults to `title`). "
        "Use `created_by` to track the initiating user."
    ),
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "blank_minimal": {
                            "summary": "Blank — minimal",
                            "description": "Start a new conversation with no chart context. Title is explicit.",
                            "value": {
                                "tenant_id": "VC_101",
                                "domain_id": "lpg_production_distribution",
                                "title": "North zone pending trend analysis",
                            },
                        },
                        "blank_with_display_name": {
                            "summary": "Blank — with display name and creator",
                            "description": "Blank conversation with a separate UI display name and created_by tracking.",
                            "value": {
                                "tenant_id": "VC_101",
                                "domain_id": "lpg_production_distribution",
                                "title": "north_zone_pending_trend",
                                "display_name": "North Zone — Pending Trend",
                                "created_by": "user_789",
                            },
                        },
                        "chart_anchored_auto_title": {
                            "summary": "Chart-anchored — title auto-derived from chart",
                            "description": "Conversation seeded from an existing chart. Title comes from the chart's original question. conversation_id is appended to chart's conversation_ids.",
                            "value": {
                                "tenant_id": "VC_101",
                                "domain_id": "lpg_production_distribution",
                                "chart_id": "chart_abc123",
                            },
                        },
                        "chart_anchored_explicit_title": {
                            "summary": "Chart-anchored — explicit title override",
                            "description": "Chart context is linked but the title is overridden explicitly instead of auto-derived.",
                            "value": {
                                "tenant_id": "VC_101",
                                "domain_id": "lpg_production_distribution",
                                "chart_id": "chart_abc123",
                                "title": "Deep dive on North zone bottleneck",
                            },
                        },
                        "chart_anchored_with_creator": {
                            "summary": "Chart-anchored — with creator",
                            "description": "Chart-anchored conversation with created_by for audit trail.",
                            "value": {
                                "tenant_id": "VC_101",
                                "domain_id": "lpg_production_distribution",
                                "chart_id": "chart_abc123",
                                "created_by": "user_789",
                            },
                        },
                    }
                }
            }
        }
    },
)
def workspace_create_conversation(payload: dict) -> dict:
    tenant_id = payload.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=400, detail="tenant_id is required")
    domain_id = _resolve_domain_id(tenant_id, payload.get("domain_id"))
    deployment = get_current_deployment(settings, tenant_id, domain_id)
    if not deployment or deployment.get("status") != "completed":
        raise HTTPException(status_code=409, detail="No completed deployment available for tenant/domain")
    connection_id, database_name, schema_name, _ = _resolve_scope_values(tenant_id, domain_id)
    bundle = _load_run_scoped_intelligence(
        tenant_id=tenant_id,
        domain_id=domain_id,
        run_id=deployment.get("run_id"),
        connection_id=connection_id,
        database_name=database_name,
        schema_name=schema_name,
    )
    missing = _missing_required_intelligence(bundle)
    if missing:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Deployment intelligence is incomplete for conversation use",
                "tenant_id": tenant_id,
                "domain_id": domain_id,
                "run_id": deployment.get("run_id"),
                "missing_artifacts": missing,
            },
        )
    # Resolve chart_id — accept both `chart_id` (canonical) and legacy `source_chart_id`
    chart_id = str(payload.get("chart_id") or payload.get("source_chart_id") or "").strip() or None
    # Derive title: explicit > chart question > domain fallback
    title = payload.get("title")
    if not title and chart_id:
        chart_row = get_chart_request(settings, chart_id)
        if chart_row:
            title = chart_row.get("question") or chart_row.get("title")
    if not title:
        title = generate_conversation_title(None, domain_id)
    conversation = create_workspace_conversation(
        settings,
        tenant_id=tenant_id,
        domain_id=domain_id,
        run_id=deployment.get("run_id"),
        title=title,
        display_name=payload.get("display_name") or title,
        created_by=payload.get("created_by"),
        source_chart_id=chart_id,
    )
    # Link this new conversation back to the chart's conversation_ids list
    if chart_id:
        try:
            append_chart_conversation_id(settings, chart_id, conversation["conversation_id"])
        except Exception:
            logger.exception("conversation.create.append_chart_conversation_id_failed | chart_id=%s", chart_id)
    return {
        **conversation,
        "run_display_name": deployment.get("display_name"),
    }


@app.post(
    "/workspace/tenants/{tenant_id}/domains/{domain_id}/conversations",
    tags=["workspace"],
    summary="Create a new conversation for tenant/domain",
    description=(
        "Scoped variant of `POST /workspace/conversations` — `tenant_id` and `domain_id` come from the URL path. "
        "Same three patterns apply:\n\n"
        "1. **Blank** — just `title`.\n"
        "2. **Chart-anchored** — `chart_id` only; title auto-derived from chart question.\n"
        "3. **Chart-anchored with title override** — both `chart_id` and `title`.\n\n"
        "The new `conversation_id` is always appended to `quantyx_chart_requests.conversation_ids` when `chart_id` is supplied."
    ),
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "blank_minimal": {
                            "summary": "Blank — minimal",
                            "description": "Start a new conversation with no chart context.",
                            "value": {
                                "title": "Show production by plant",
                            },
                        },
                        "blank_with_display_name": {
                            "summary": "Blank — with display name and creator",
                            "description": "Blank conversation with a separate UI display name and created_by tracking.",
                            "value": {
                                "title": "production_by_plant",
                                "display_name": "Production by Plant",
                                "created_by": "user_789",
                            },
                        },
                        "chart_anchored_auto_title": {
                            "summary": "Chart-anchored — title auto-derived",
                            "description": "Conversation seeded from an existing chart. Title comes from the chart's original question.",
                            "value": {
                                "chart_id": "chart_abc123",
                            },
                        },
                        "chart_anchored_explicit_title": {
                            "summary": "Chart-anchored — explicit title override",
                            "description": "Chart context linked but title overridden.",
                            "value": {
                                "chart_id": "chart_abc123",
                                "title": "Deep dive on North zone bottleneck",
                            },
                        },
                        "chart_anchored_with_creator": {
                            "summary": "Chart-anchored — with creator",
                            "description": "Chart-anchored conversation with created_by for audit trail.",
                            "value": {
                                "chart_id": "chart_abc123",
                                "created_by": "user_789",
                            },
                        },
                    }
                }
            }
        }
    },
)
def workspace_create_conversation_for_scope(tenant_id: str, domain_id: str, payload: dict | None = None) -> dict:
    data = payload or {}
    return workspace_create_conversation(
        {
            "tenant_id": tenant_id,
            "domain_id": domain_id,
            "title": data.get("title"),
            "display_name": data.get("display_name"),
            "chart_id": data.get("chart_id"),
            "created_by": data.get("created_by"),
        }
    )


@app.get(
    "/workspace/conversations",
    tags=["workspace"],
    summary="List conversations",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "conversations": {
                                "summary": "Conversation list",
                                "value": {
                                    "tenant_id": "VC_101",
                                    "domain_id": "lpg_production_distribution",
                                    "conversations": [
                                        {
                                            "conversation_id": "conv_6f0f0f",
                                            "title": "North Zone Bottleneck Analysis",
                                            "display_name": "North Zone Bottleneck Analysis",
                                            "run_display_name": "Lpg Production Distribution Deployment v4",
                                            "message_count": 24,
                                        }
                                    ],
                                },
                            }
                        }
                    }
                }
            }
        }
    },
)
def workspace_list_conversations(
    tenant_id: str,
    domain_id: str | None = None,
    status: str = WORKSPACE_STATUS_ACTIVE,
    limit: int = 50,
) -> dict:
    resolved_domain = _resolve_domain_id(tenant_id, domain_id)
    rows = list_workspace_conversations(
        settings,
        tenant_id=tenant_id,
        domain_id=resolved_domain,
        status=status,
        limit=limit,
    )
    return {"tenant_id": tenant_id, "domain_id": resolved_domain, "conversations": rows}


@app.get(
    "/workspace/tenants/{tenant_id}/domains/{domain_id}/conversations",
    tags=["workspace"],
    summary="List conversations for tenant/domain",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "scope_conversations": {
                                "summary": "Scope conversation list",
                                "value": {
                                    "tenant_id": "VC_101",
                                    "domain_id": "lpg_production_distribution",
                                    "conversations": [
                                        {"conversation_id": "conv_6f0f0f", "title": "North Zone Bottleneck Analysis"}
                                    ],
                                },
                            }
                        }
                    }
                }
            }
        }
    },
)
def workspace_list_conversations_for_scope(
    tenant_id: str,
    domain_id: str,
    status: str = WORKSPACE_STATUS_ACTIVE,
    limit: int = 50,
) -> dict:
    rows = list_workspace_conversations(
        settings,
        tenant_id=tenant_id,
        domain_id=domain_id,
        status=status,
        limit=limit,
    )
    return {"tenant_id": tenant_id, "domain_id": domain_id, "conversations": rows}


@app.get(
    "/workspace/tenants/{tenant_id}/conversations",
    tags=["workspace"],
    summary="List tenant-wide conversation history (all domains)",
    description="Returns all conversations for a tenant across domains. Optionally filter by domain_id or status.",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "tenant_history": {
                                "summary": "Tenant-wide conversation history",
                                "value": {
                                    "tenant_id": "VC_101",
                                    "domain_id": None,
                                    "status": "active",
                                    "conversations": [
                                        {
                                            "conversation_id": "conv_6f0f0f",
                                            "domain_id": "lpg_production_distribution",
                                            "title": "North Zone Bottleneck Analysis",
                                            "run_id": "run_1a0f427c86ec",
                                            "run_display_name": "Lpg Production Distribution Deployment v4",
                                            "message_count": 24,
                                        },
                                        {
                                            "conversation_id": "conv_8a7b6c",
                                            "domain_id": "retail_sales",
                                            "title": "Retail Throughput Trend",
                                            "run_id": "run_4b6d9a0e1122",
                                            "run_display_name": "Retail Sales Deployment v2",
                                            "message_count": 11,
                                        },
                                    ],
                                },
                            }
                        }
                    }
                }
            }
        }
    },
)
def workspace_list_conversations_for_tenant(
    tenant_id: str,
    status: str = WORKSPACE_STATUS_ACTIVE,
    domain_id: str | None = None,
    limit: int = 100,
) -> dict:
    rows = list_workspace_conversations_for_tenant(
        settings,
        tenant_id=tenant_id,
        status=status,
        domain_id=domain_id,
        limit=limit,
    )
    return {
        "tenant_id": tenant_id,
        "domain_id": domain_id,
        "status": status,
        "conversations": rows,
    }


@app.get(
    "/workspace/tenants/{tenant_id}/domains/{domain_id}/runs/{run_id}/conversations",
    tags=["workspace"],
    summary="List conversations for a specific deployment run",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "run_history": {
                                "summary": "Run-scoped conversation list",
                                "value": {
                                    "tenant_id": "VC_101",
                                    "domain_id": "lpg_production_distribution",
                                    "run_id": "run_1a0f427c86ec",
                                    "conversations": [
                                        {"conversation_id": "conv_6f0f0f", "title": "North Zone Bottleneck Analysis"}
                                    ],
                                },
                            }
                        }
                    }
                }
            }
        }
    },
)
def workspace_list_conversations_for_run(
    tenant_id: str,
    domain_id: str,
    run_id: str,
    status: str = WORKSPACE_STATUS_ACTIVE,
    limit: int = 50,
) -> dict:
    rows = list_workspace_conversations(
        settings,
        tenant_id=tenant_id,
        domain_id=domain_id,
        status=status,
        limit=limit,
    )
    rows = [item for item in rows if item.get("run_id") == run_id]
    return {"tenant_id": tenant_id, "domain_id": domain_id, "run_id": run_id, "conversations": rows}


@app.get(
    "/workspace/conversations/{conversation_id}",
    tags=["workspace"],
    summary="Get conversation",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "conversation": {
                                "summary": "Conversation metadata",
                                "value": {
                                    "conversation_id": "conv_6f0f0f",
                                    "tenant_id": "VC_101",
                                    "domain_id": "lpg_production_distribution",
                                    "run_id": "run_1a0f427c86ec",
                                    "title": "North Zone Bottleneck Analysis",
                                    "status": "active",
                                },
                            }
                        }
                    }
                }
            }
        }
    },
)
def workspace_get_conversation(conversation_id: str) -> dict:
    conversation = get_workspace_conversation(settings, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


@app.put(
    "/workspace/conversations/{conversation_id}",
    tags=["workspace"],
    summary="Update conversation",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "update": {
                            "summary": "Rename/archive/switch",
                            "value": {
                                "title": "Updated Conversation Title",
                                "status": "archived",
                                "switch_to_latest_run": False,
                            },
                        }
                    }
                }
            }
        }
    },
)
def workspace_update_conversation(conversation_id: str, payload: dict) -> dict:
    conversation = get_workspace_conversation(settings, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    run_id = None
    if payload.get("switch_to_latest_run"):
        latest = get_current_deployment(settings, conversation["tenant_id"], conversation["domain_id"])
        if latest:
            run_id = latest.get("run_id")
    status = payload.get("status")
    if status and status not in {WORKSPACE_STATUS_ACTIVE, WORKSPACE_STATUS_ARCHIVED, WORKSPACE_STATUS_DELETED}:
        raise HTTPException(status_code=400, detail="Invalid status")
    updated = update_workspace_conversation(
        settings,
        conversation_id,
        title=payload.get("title"),
        display_name=payload.get("display_name"),
        status=status,
        run_id=run_id,
    )
    return updated or {}


@app.delete(
    "/workspace/conversations/{conversation_id}",
    tags=["workspace"],
    summary="Soft delete conversation",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "deleted": {
                                "summary": "Conversation soft deleted",
                                "value": {"conversation_id": "conv_6f0f0f", "status": "deleted"},
                            }
                        }
                    }
                }
            }
        }
    },
)
def workspace_delete_conversation(conversation_id: str) -> dict:
    conversation = get_workspace_conversation(settings, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    soft_delete_workspace_conversation(settings, conversation_id)
    return {"conversation_id": conversation_id, "status": WORKSPACE_STATUS_DELETED}


@app.get(
    "/workspace/conversations/{conversation_id}/messages",
    tags=["workspace"],
    summary="List conversation messages",
    openapi_extra={
        "parameters": [
            {
                "name": "limit",
                "in": "query",
                "required": False,
                "schema": {"type": "integer", "default": 200, "minimum": 1, "maximum": 2000},
                "description": "Maximum number of messages to return.",
            },
            {
                "name": "cursor",
                "in": "query",
                "required": False,
                "schema": {"type": "string"},
                "description": "Opaque cursor for pagination. Use `paging.next_cursor` from previous response.",
            },
        ],
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "first_page": {
                                "summary": "First page",
                                "value": {
                                    "conversation_id": "conv_6f0f0f",
                                    "messages": [
                                        {"sender": "user", "message_text": "Show production trend"},
                                        {"sender": "assistant", "message_text": "Returned 120 rows for production_mt."},
                                    ],
                                    "paging": {
                                        "limit": 50,
                                        "cursor": None,
                                        "returned": 50,
                                        "has_more": True,
                                        "next_cursor": "NTA="
                                    }
                                },
                            },
                            "next_page": {
                                "summary": "Next page",
                                "value": {
                                    "conversation_id": "conv_6f0f0f",
                                    "messages": [
                                        {"sender": "user", "message_text": "Show pending by region"},
                                        {"sender": "assistant", "message_text": "North leads pending backlog."}
                                    ],
                                    "paging": {
                                        "limit": 50,
                                        "cursor": "NTA=",
                                        "returned": 50,
                                        "has_more": True,
                                        "next_cursor": "MTAw"
                                    }
                                },
                            },
                            "last_page": {
                                "summary": "Last page",
                                "value": {
                                    "conversation_id": "conv_6f0f0f",
                                    "messages": [
                                        {"sender": "assistant", "message_text": "Conversation complete."}
                                    ],
                                    "paging": {
                                        "limit": 50,
                                        "cursor": "MTAw",
                                        "returned": 8,
                                        "has_more": False,
                                        "next_cursor": None
                                    }
                                },
                            }
                        }
                    }
                }
            }
        }
    },
)
def workspace_list_conversation_messages(conversation_id: str, limit: int = 200, cursor: str | None = None) -> dict:
    conversation = get_workspace_conversation(settings, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    bounded_limit = max(1, min(int(limit), 2000))
    if cursor:
        try:
            cursor_value = _decode_cursor(cursor)
            start_offset = max(0, int(cursor_value))
        except Exception as exc:
            raise HTTPException(status_code=400, detail="Invalid cursor") from exc
    else:
        start_offset = 0
    fetch_window = min(5000, start_offset + bounded_limit + 1)
    rows = list_workspace_messages(settings, conversation_id, limit=fetch_window)
    page = rows[start_offset : start_offset + bounded_limit + 1]
    has_more = len(page) > bounded_limit
    messages = page[:bounded_limit]
    next_cursor = _encode_cursor(str(start_offset + bounded_limit)) if has_more else None
    return {
        "conversation_id": conversation_id,
        "messages": messages,
        "paging": {
            "limit": bounded_limit,
            "cursor": cursor,
            "returned": len(messages),
            "has_more": has_more,
            "next_cursor": next_cursor,
        },
    }


@app.get(
    "/workspace/conversations/{conversation_id}/messages/{message_id}",
    tags=["workspace"],
    summary="Get conversation message",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "message": {
                                "summary": "Single message with artifacts",
                                "value": {
                                    "message_id": "wmsg_abc123",
                                    "sender": "assistant",
                                    "message_text": "Returned 120 rows for production_mt.",
                                    "sql_text": "SELECT ...",
                                    "chart_json": {"chart_type": "line"},
                                },
                            }
                        }
                    }
                }
            }
        }
    },
)
def workspace_get_conversation_message(conversation_id: str, message_id: str) -> dict:
    conversation = get_workspace_conversation(settings, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    row = get_workspace_message(settings, conversation_id, message_id)
    if not row:
        raise HTTPException(status_code=404, detail="Message not found")
    return row


@app.get(
    "/workspace/conversations/{conversation_id}/messages/{message_id}/plan",
    tags=["workspace"],
    summary="Get interpreted and validated conversation plan for a message",
)
def workspace_get_conversation_message_plan(conversation_id: str, message_id: str) -> dict:
    conversation = get_workspace_conversation(settings, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    row = get_workspace_message(settings, conversation_id, message_id)
    if not row:
        raise HTTPException(status_code=404, detail="Message not found")
    conversation_plan = (
        (row.get("chart_json") or {}).get("conversation_plan")
        or (row.get("summary_json") or {}).get("conversation_plan")
        or (row.get("inference_json") or {}).get("conversation_plan")
        or {}
    )
    return {
        "conversation_id": conversation_id,
        "message_id": message_id,
        "raw_llm_plan": conversation_plan.get("raw_llm_plan") or {},
        "validated_plan": conversation_plan.get("validated_plan") or {},
        "validation_warnings": conversation_plan.get("validation_warnings") or [],
        "rejected_candidates": conversation_plan.get("rejected_candidates") or {},
        "compiled_sql_preview": conversation_plan.get("compiled_sql_preview") or row.get("sql_text"),
        "chart_followup": conversation_plan.get("chart_followup") or ((row.get("chart_json") or {}).get("chart_followup") or {}),
    }


@app.get(
    "/workspace/conversations/{conversation_id}/memory",
    tags=["workspace"],
    summary="Get conversation memory",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "memory": {
                                "summary": "Persisted memory",
                                "value": {
                                    "conversation_id": "conv_6f0f0f",
                                    "memory": {
                                        "summary_text": "Latest topic: pending trend in North zone",
                                        "memory_json": {"last_user_question": "Show pending trend"},
                                    },
                                },
                            }
                        }
                    }
                }
            }
        }
    },
)
def workspace_get_memory(conversation_id: str) -> dict:
    conversation = get_workspace_conversation(settings, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    memory = get_workspace_memory(settings, conversation_id)
    return {"conversation_id": conversation_id, "memory": memory}


@app.get(
    "/workspace/conversations/{conversation_id}/context",
    tags=["workspace"],
    summary="Get context package",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "context": {
                                "summary": "Context package",
                                "value": {
                                    "conversation_id": "conv_6f0f0f",
                                    "run_id": "run_1a0f427c86ec",
                                    "recent_turns": [{"sender": "user", "message_text": "Show pending trend"}],
                                    "memory": {"summary_text": "Latest topic: pending trend"},
                                },
                            }
                        }
                    }
                }
            }
        }
    },
)
def workspace_get_context(conversation_id: str, last_turns: int = 12) -> dict:
    conversation = get_workspace_conversation(settings, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    memory = get_workspace_memory(settings, conversation_id)
    turns = recent_workspace_messages(settings, conversation_id, limit=last_turns)
    return {
        "conversation_id": conversation_id,
        "run_id": conversation.get("run_id"),
        "recent_turns": turns,
        "memory": memory,
    }


@app.put(
    "/workspace/conversations/{conversation_id}/context/rebuild",
    tags=["workspace"],
    summary="Rebuild context memory",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "rebuilt": {
                                "summary": "Memory rebuilt",
                                "value": {
                                    "conversation_id": "conv_6f0f0f",
                                    "memory": {"summary_text": "Latest topic: production trend"},
                                },
                            }
                        }
                    }
                }
            }
        }
    },
)
def workspace_rebuild_context(conversation_id: str) -> dict:
    conversation = get_workspace_conversation(settings, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    turns = recent_workspace_messages(settings, conversation_id, limit=12)
    last_user = next((t for t in reversed(turns) if t.get("sender") == "user"), None)
    summary = f"Latest topic: {(last_user or {}).get('message_text') or 'conversation context'}"
    memory = upsert_workspace_memory(
        settings,
        conversation_id=conversation_id,
        tenant_id=conversation["tenant_id"],
        domain_id=conversation["domain_id"],
        run_id=conversation["run_id"],
        summary_text=summary,
        memory_json={
            "last_user_question": (last_user or {}).get("message_text"),
            "turn_count": len(turns),
        },
    )
    return {"conversation_id": conversation_id, "memory": memory}


@app.put(
    "/workspace/conversations/{conversation_id}/memory",
    tags=["workspace"],
    summary="Override conversation memory",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "override": {
                            "summary": "Override memory",
                            "value": {
                                "summary_text": "North zone pending analysis",
                                "memory_json": {"active_filters": ["zone=North"]},
                            },
                        }
                    }
                }
            }
        }
    },
)
def workspace_override_memory(conversation_id: str, payload: dict) -> dict:
    conversation = get_workspace_conversation(settings, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    memory = upsert_workspace_memory(
        settings,
        conversation_id=conversation_id,
        tenant_id=conversation["tenant_id"],
        domain_id=conversation["domain_id"],
        run_id=conversation["run_id"],
        summary_text=payload.get("summary_text") or "",
        memory_json=payload.get("memory_json") or {},
    )
    return {"conversation_id": conversation_id, "memory": memory}


@app.post(
    "/workspace/conversations/{conversation_id}/messages",
    tags=["workspace"],
    summary="Send conversation message",
    description="Canonical request field is `user_query`. Backward-compatible aliases accepted: `query`, `message_text`, `first_question`. Optional chart-scoped follow-up fields such as `chart_id`, `selected_category`, and `selected_time_value` can be supplied to continue the same conversation in chart-followup mode.",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "stream_default": {
                            "summary": "Stream response by default",
                            "value": {
                                "user_query": "Show production trend by plant for last 30 days",
                                "resume_context": True,
                                "stream": True,
                            },
                        },
                        "sync": {
                            "summary": "Synchronous response",
                            "value": {
                                "user_query": "Show production trend by plant for last 30 days",
                                "resume_context": True,
                                "stream": False,
                            },
                        },
                        "chart_followup_carry_metric": {
                            "summary": "Carry forward source metric from chart",
                            "value": {
                                "user_query": "Drill this into region",
                                "chart_id": "chart_daily_sales_zone_01",
                                "resume_context": True,
                                "stream": False,
                            },
                        },
                        "chart_followup_carry_dimension": {
                            "summary": "Carry forward existing dimension context",
                            "value": {
                                "user_query": "Show the latest 6 months for this",
                                "chart_id": "chart_monthly_target_sbu_01",
                                "resume_context": True,
                                "stream": False,
                            },
                        },
                        "chart_followup_replace_dimension": {
                            "summary": "Replace source dimension with requested one",
                            "value": {
                                "user_query": "Show this by region instead",
                                "chart_id": "chart_monthly_target_sbu_01",
                                "resume_context": True,
                                "stream": False,
                            },
                        },
                        "chart_followup_selected_category": {
                            "summary": "Add selected-category filter before drill-down",
                            "value": {
                                "user_query": "Break this by plant",
                                "chart_id": "chart_daily_sales_zone_01",
                                "selected_category": "West Zone",
                                "resume_context": True,
                                "stream": False,
                            },
                        },
                        "chart_followup_selected_time": {
                            "summary": "Add selected-time filter before refinement",
                            "value": {
                                "user_query": "Break this by region",
                                "chart_id": "chart_daily_sales_trend_01",
                                "selected_time_value": "2026-02-01",
                                "resume_context": True,
                                "stream": False,
                            },
                        },
                        "chart_followup_combined": {
                            "summary": "Use both selected category and selected time",
                            "value": {
                                "user_query": "Drill this into plant and exclude Common",
                                "chart_id": "chart_sales_region_month_01",
                                "selected_category": "West Zone",
                                "selected_time_value": "2026-02-01",
                                "resume_context": True,
                                "stream": False,
                            },
                        },
                    }
                }
            }
        },
        "responses": {
            "200": {
                "content": {
                    "text/event-stream": {
                        "examples": {
                            "sse_token": {
                                "summary": "Token event",
                                "value": "data: {\"event\":\"token\",\"text\":\"Returned \"}\n\n",
                            },
                            "sse_done": {
                                "summary": "Done event",
                                "value": "data: {\"event\":\"done\"}\n\n",
                            },
                        }
                    },
                    "application/json": {
                        "examples": {
                            "sync_response": {
                                "summary": "Non-stream response",
                                "value": {
                                    "conversation_id": "conv_6f0f0f",
                                    "response": {
                                        "chart_type": "line",
                                        "chart_title": "Total Production Trend by Plant",
                                        "dashboard_title": "Lpg Production Distribution Dashboard",
                                        "sql": "SELECT ..."
                                    },
                                    "context_used": {"resume_context": True, "run_id": "run_1a0f427c86ec"},
                                },
                            },
                            "sync_chart_followup_response": {
                                "summary": "Chart-scoped follow-up response",
                                "value": {
                                    "conversation_id": "conv_6f0f0f",
                                    "response": {
                                        "chart_type": "bar",
                                        "chart_title": "Daily Sales by Region",
                                        "dashboard_title": "Market Performance Dashboard",
                                        "sql": "SELECT ...",
                                        "chart_followup": {
                                            "mode": "chart_scoped",
                                            "source_chart_id": "chart_daily_sales_zone_01",
                                            "derived_chart_id": "chart_derived_region_01",
                                            "follow_up_intent": "drill_down",
                                            "selected_context": {
                                                "selected_category": "West Zone"
                                            },
                                            "filter_hints": [
                                                {
                                                    "field": "Zone_Name",
                                                    "operator": "=",
                                                    "value": "West Zone",
                                                    "value_type": "text"
                                                }
                                            ],
                                            "accepted_transformations": [
                                                "carried forward metric daily_sales",
                                                "replaced dimensions with Region_Name",
                                                "added filter hint Zone_Name = West Zone"
                                            ],
                                            "rejected_transformations": [],
                                            "transformation_summary": [
                                                "carried forward metric daily_sales",
                                                "replaced dimensions with Region_Name",
                                                "added filter hint Zone_Name = West Zone"
                                            ]
                                        }
                                    },
                                    "context_used": {
                                        "resume_context": True,
                                        "run_id": "run_1a0f427c86ec",
                                        "chart_followup": {
                                            "mode": "chart_scoped",
                                            "source_chart_id": "chart_daily_sales_zone_01"
                                        }
                                    }
                                },
                            },
                        }
                    },
                }
            }
        },
    },
)
def workspace_send_message(conversation_id: str, payload: dict):
    from fastapi.responses import StreamingResponse

    conversation = get_workspace_conversation(settings, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if conversation.get("status") == WORKSPACE_STATUS_DELETED:
        raise HTTPException(status_code=400, detail="Conversation is deleted")
    user_query = _extract_user_query(payload, required=True) or ""
    stream = payload.get("stream")
    if stream is None:
        stream = True
    resume_context = payload.get("resume_context")
    if resume_context is None:
        resume_context = True
    chart_followup_context = _extract_chart_followup_context(payload)
    chart_context = _resolve_chart_conversation_context(
        tenant_id=conversation["tenant_id"],
        domain_id=conversation["domain_id"],
        chart_id=chart_followup_context.get("chart_id"),
        conversation_id=conversation_id,
    )
    if chart_context and chart_followup_context:
        chart_context = {
            **chart_context,
            "selected_context": {
                key: value for key, value in chart_followup_context.items() if key != "chart_id"
            },
        }

    user_msg = create_workspace_message(
        settings,
        conversation_id=conversation_id,
        tenant_id=conversation["tenant_id"],
        domain_id=conversation["domain_id"],
        run_id=conversation["run_id"],
        sender="user",
        message_text=user_query,
        chart_json=chart_followup_context or None,
    )
    memory = get_workspace_memory(settings, conversation_id)
    effective_question = _chart_context_question_suffix(user_query, chart_context, chart_followup_context)

    # Load the active enriched business context for this tenant/domain scope.
    # This is always injected as baseline domain knowledge so the query planner
    # has mandatory filters, FY conventions, and metric definitions available.
    # When resume_context=True the rolling conversation memory is appended on top.
    _conv_tenant = conversation["tenant_id"]
    _conv_domain = conversation["domain_id"]
    _conv_connection_id, _conv_db, _conv_schema, _ = _resolve_scope_values(_conv_tenant, _conv_domain)
    try:
        writeback = maybe_writeback_conversation_refinement(
            settings,
            tenant_id=_conv_tenant,
            domain_id=_conv_domain,
            connection_id=_conv_connection_id,
            database_name=_conv_db,
            schema_name=_conv_schema,
            source_run_id=conversation.get("run_id"),
            conversation_id=conversation_id,
            source_text=user_query,
        )
        if writeback:
            logger.info(
                "workspace.message.semantic_writeback | conversation_id=%s refinement_input_id=%s kind=%s valid_artifacts=%s",
                conversation_id,
                writeback.get("refinement_input_id"),
                writeback.get("refinement_kind"),
                writeback.get("valid_artifact_count"),
            )
    except Exception:
        logger.warning("workspace.message.semantic_writeback_failed | conversation_id=%s", conversation_id, exc_info=True)
    _active_ctx_ids = list_active_context_ids(
        settings, _conv_tenant, _conv_domain, _conv_connection_id, _conv_db, _conv_schema
    )
    _business_context_text: str | None = None
    if _active_ctx_ids:
        _ctx_row = get_context(settings, _active_ctx_ids[0])
        if _ctx_row:
            _business_context_text = (
                _ctx_row.get("enriched_context") or _ctx_row.get("raw_text") or ""
            ).strip() or None

    if _business_context_text:
        effective_question = f"{user_query}\n\nBusiness context:\n{_business_context_text}"
        effective_question = _chart_context_question_suffix(effective_question, chart_context, chart_followup_context)

    if resume_context and memory and memory.get("summary_text"):
        effective_question = f"{user_query}\n\nConversation context: {memory.get('summary_text')}"
        if _business_context_text:
            effective_question = f"{effective_question}\n\nBusiness context:\n{_business_context_text}"
        effective_question = _chart_context_question_suffix(effective_question, chart_context, chart_followup_context)
    logger.info(
        "workspace.message.start | conversation_id=%s tenant=%s domain=%s run_id=%s stream=%s resume_context=%s memory_present=%s business_context_present=%s chart_id=%s user_query=%s",
        conversation_id,
        conversation["tenant_id"],
        conversation["domain_id"],
        conversation["run_id"],
        bool(stream),
        bool(resume_context),
        bool(memory),
        bool(_business_context_text),
        (chart_context or {}).get("source_chart_id"),
        user_query,
    )

    def _persist_assistant(
        *,
        response_payload: dict,
        assistant_text: str,
        summary_json: dict,
        inference_json: dict,
    ) -> dict:
        assistant_msg = create_workspace_message(
            settings,
            conversation_id=conversation_id,
            tenant_id=conversation["tenant_id"],
            domain_id=conversation["domain_id"],
            run_id=conversation["run_id"],
            sender="assistant",
            message_text=assistant_text,
            sql_text=response_payload.get("sql"),
            data_json={"rows": response_payload.get("rows")},
            chart_json={
                "chart_id": response_payload.get("chart_id"),
                "chart_type": response_payload.get("chart_type"),
                "chart_title": response_payload.get("chart_title"),
                "dashboard_title": response_payload.get("dashboard_title"),
                "chart_payload": response_payload.get("chart_payload"),
                "data": response_payload.get("data"),
                "conversation_plan": response_payload.get("conversation_plan"),
                "chart_followup": response_payload.get("chart_followup"),
                "data_quality": response_payload.get("data_quality"),
            },
            summary_json=summary_json,
            inference_json=inference_json,
        )
        new_memory = upsert_workspace_memory(
            settings,
            conversation_id=conversation_id,
            tenant_id=conversation["tenant_id"],
            domain_id=conversation["domain_id"],
            run_id=conversation["run_id"],
            summary_text=summary_json.get("text") or assistant_text,
            memory_json={
                "last_user_question": user_query,
                "last_assistant_summary": summary_json.get("text"),
                "metrics": response_payload.get("metrics") or [],
                "dimensions": response_payload.get("dimensions") or [],
                "sql_present": bool(response_payload.get("sql")),
                "conversation_plan": response_payload.get("conversation_plan"),
                "last_chart_followup": response_payload.get("chart_followup"),
                "data_quality_context": response_payload.get("data_quality"),
            },
        )
        return {"assistant_message": assistant_msg, "memory": new_memory}

    def _compute_workspace_response() -> tuple[dict, str, dict, dict]:
        dq_response = build_data_quality_workspace_response(
            settings,
            tenant_id=conversation["tenant_id"],
            domain_id=conversation["domain_id"],
            run_id=conversation["run_id"],
            question=user_query,
        )
        if dq_response is not None:
            return dq_response
        return _workspace_query_response(
            tenant_id=conversation["tenant_id"],
            domain_id=conversation["domain_id"],
            run_id=conversation["run_id"],
            question=effective_question,
            conversation_id=conversation_id,
            chart_context=chart_context,
            chart_followup_context=chart_followup_context,
            raw_user_query=user_query,
            conversation_memory_text=(memory or {}).get("summary_text"),
            business_context_text=_business_context_text,
            metrics=payload.get("metrics") or [],
            dimensions=payload.get("dimensions") or [],
            limit=int(payload.get("limit") or 200),
        )

    def _compute_sync_result() -> dict:
        response_payload, assistant_text_base, summary_json, inference_json = _compute_workspace_response()
        assistant_text = assistant_text_base
        if _workspace_llm_stream_enabled() and str((response_payload.get("conversation_plan") or {}).get("sql_mode")) in {"pipeline", "llm_agent"}:
            try:
                sys_prompt, usr_prompt = _workspace_narration_prompt(user_query, response_payload, summary_json)
                collected = "".join(_stream_openai_tokens(sys_prompt, usr_prompt)).strip()
                if collected:
                    assistant_text = collected
            except Exception:
                logger.exception("workspace.message.llm_stream_failed")
        _persist_chart_followup_lineage(
            chart_id=response_payload.get("chart_id"),
            response_payload=response_payload,
        )
        persisted = _persist_assistant(
            response_payload=response_payload,
            assistant_text=assistant_text,
            summary_json=summary_json,
            inference_json=inference_json,
        )
        _conv_plan = response_payload.get("conversation_plan") or {}
        return {
            "conversation_id": conversation_id,
            "message_id": (persisted.get("assistant_message") or {}).get("message_id"),
            "response": _build_client_response(response_payload),
            "context_used": {
                "resume_context": bool(resume_context and memory),
                "run_id": conversation["run_id"],
                "sql_mode": _conv_plan.get("sql_mode", "pipeline"),
                "llm_sql_fallback": _conv_plan.get("sql_mode") != "llm_agent" and os.getenv("CONVERSATION_LLM_SQL_MODE", "").lower() in ("true", "1", "yes"),
            },
        }

    if not stream:
        return _compute_sync_result()

    def _event_stream():
        try:
            yield f"data: {json.dumps({'event': 'message_start', 'conversation_id': conversation_id})}\n\n"
            yield f"data: {json.dumps({'event': 'status', 'stage': 'query_started'})}\n\n"
            response_payload, assistant_text_base, summary_json, inference_json = _compute_workspace_response()
            yield f"data: {json.dumps({'event': 'status', 'stage': 'query_completed', 'row_count': len(response_payload.get('rows') or [])})}\n\n"
            assistant_text = assistant_text_base
            streamed = False
            if _workspace_llm_stream_enabled() and str((response_payload.get("conversation_plan") or {}).get("sql_mode")) in {"pipeline", "llm_agent"}:
                yield f"data: {json.dumps({'event': 'status', 'stage': 'narration_started'})}\n\n"
                try:
                    sys_prompt, usr_prompt = _workspace_narration_prompt(user_query, response_payload, summary_json)
                    assistant_text = ""
                    for token in _stream_openai_tokens(sys_prompt, usr_prompt):
                        streamed = True
                        assistant_text += token
                        yield f"data: {json.dumps({'event': 'token', 'text': token})}\n\n"
                except Exception:
                    logger.exception("workspace.message.llm_stream_failed")
            if not streamed:
                for token in assistant_text.split(" "):
                    if not token:
                        continue
                    yield f"data: {json.dumps({'event': 'token', 'text': token + ' '})}\n\n"
            _persist_chart_followup_lineage(
                chart_id=response_payload.get("chart_id"),
                response_payload=response_payload,
            )
            persisted = _persist_assistant(
                response_payload=response_payload,
                assistant_text=assistant_text.strip(),
                summary_json=summary_json,
                inference_json=inference_json,
            )
            _s_conv_plan = response_payload.get("conversation_plan") or {}
            _s_sql_mode = _s_conv_plan.get("sql_mode", "pipeline")
            _s_llm_fallback = _s_sql_mode != "llm_agent" and os.getenv("CONVERSATION_LLM_SQL_MODE", "").lower() in ("true", "1", "yes")
            yield f"data: {json.dumps({'event': 'artifact', 'name': 'response', 'payload': _build_client_response(response_payload)}, default=str)}\n\n"
            yield (
                f"data: "
                f"{json.dumps({'event': 'message_end', 'assistant_message_id': (persisted.get('assistant_message') or {}).get('message_id'), 'sql_mode': _s_sql_mode, 'llm_sql_fallback': _s_llm_fallback})}\n\n"
            )
            yield f"data: {json.dumps({'event': 'done'})}\n\n"
        except Exception as exc:  # noqa: BLE001
            yield f"data: {json.dumps({'event': 'error', 'error': str(exc)})}\n\n"

    return StreamingResponse(_event_stream(), media_type="text/event-stream")


@app.get(
    "/agentic/runs/{run_id}",
    tags=["agentic"],
    summary="Get agentic run",
    description="Return agentic run status.",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "running": {
                                "summary": "Run in progress",
                                "value": {
                                    "run_id": "run_123",
                                    "tenant_id": "VC_101",
                                    "domain_id": "lpg_production_distribution",
                                    "status": "running",
                                },
                            },
                            "completed": {
                                "summary": "Run completed",
                                "value": {
                                    "run_id": "run_123",
                                    "tenant_id": "VC_101",
                                    "domain_id": "lpg_production_distribution",
                                    "status": "completed",
                                },
                            }
                        }
                    }
                }
            }
        }
    },
)
def get_agentic_run(run_id: str) -> dict:
    run = get_agent_run(settings, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@app.get(
    "/agentic/runs/{run_id}/events",
    tags=["agentic"],
    summary="List agentic run events",
    description="Return agentic run progress events.",
    openapi_extra={
        "parameters": [
            {
                "name": "limit",
                "in": "query",
                "required": False,
                "schema": {"type": "integer", "default": 200, "minimum": 1, "maximum": 2000},
                "description": "Maximum number of events to return in ascending chronological order.",
            }
        ],
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "events": {
                                "summary": "Run events",
                                "value": {
                                    "events": [
                                        {
                                            "agent_name": "SchemaAgent",
                                            "status": "running",
                                            "message": "Schema Agent started",
                                        },
                                        {
                                            "agent_name": "SchemaAgent",
                                            "status": "completed",
                                            "message": "Schema Agent completed",
                                            "artifacts": {"tables": 12},
                                        },
                                        {
                                            "agent_name": "DashboardAgent",
                                            "status": "completed",
                                            "stage_name": "completed",
                                            "message": "Dashboard Agent completed",
                                            "dashboard_id": "dash_123",
                                            "dashboard_title": "Lpg Production Distribution Dashboard",
                                            "chart_ids": ["chart_a1b2c3", "chart_d4e5f6"],
                                            "chart_titles": [
                                                "Total Production Trend Over Process Date",
                                                "Total Production by Plant Name"
                                            ],
                                            "artifacts": {
                                                "raw_json": {
                                                    "quality_report": {
                                                        "gate_passed": True,
                                                        "quality_score": 0.9,
                                                        "warnings": [],
                                                        "blocked_patterns": [],
                                                        "kpi_mix": {
                                                            "trend": 2,
                                                            "breakdown_or_share": 2,
                                                            "quality_or_rate": 1
                                                        }
                                                    },
                                                    "chart_details": [
                                                        {
                                                            "chart_id": "chart_a1b2c3",
                                                            "metric_intent": "volume",
                                                            "semantic_validation": {
                                                                "status": "passed",
                                                                "reason": "eligible_metric"
                                                            }
                                                        }
                                                    ]
                                                }
                                            },
                                        }
                                    ]
                                },
                            }
                        }
                    }
                }
            }
        }
    },
)
def get_agentic_run_events(
    run_id: str,
    limit: int = 200,
    include: str | None = None,
    compact: bool = True,
    stage_name: str | None = None,
    agent_name: str | None = None,
) -> dict:
    del compact  # reserved for store-side compaction behavior
    events = _list_events_v2(
        run_id=run_id,
        limit=limit,
        include=include,
        stage_name=stage_name,
        agent_name=agent_name,
    )
    return {"events": events, "paging": {"limit": limit, "returned": len(events)}}


def _parse_include_tokens(include: str | None, default_tokens: set[str] | None = None) -> set[str]:
    default = default_tokens or {"raw_json", "summary", "inference", "html"}
    if not include:
        return default
    tokens = {token.strip().lower() for token in include.split(",") if token.strip()}
    return tokens or default


def _filter_artifact_payload(artifact: dict | None, include_tokens: set[str]) -> dict:
    if not artifact:
        return {}
    reserved_keys = {
        "raw_json",
        "summary_raw_text",
        "summary_html",
        "inference_raw_text",
        "inference_html",
        "truncation",
    }
    if not any(key in artifact for key in reserved_keys):
        return dict(artifact)
    filtered: dict = {}
    if "raw_json" in include_tokens and artifact.get("raw_json") is not None:
        filtered["raw_json"] = artifact.get("raw_json")
    if "summary" in include_tokens:
        if artifact.get("summary_raw_text") is not None:
            filtered["summary_raw_text"] = artifact.get("summary_raw_text")
        if "html" in include_tokens and artifact.get("summary_html") is not None:
            filtered["summary_html"] = artifact.get("summary_html")
    if "inference" in include_tokens:
        if artifact.get("inference_raw_text") is not None:
            filtered["inference_raw_text"] = artifact.get("inference_raw_text")
        if "html" in include_tokens and artifact.get("inference_html") is not None:
            filtered["inference_html"] = artifact.get("inference_html")
    if artifact.get("truncation") is not None:
        filtered["truncation"] = artifact.get("truncation")
    for key, value in artifact.items():
        if key not in reserved_keys and value is not None:
            filtered[key] = value
    return filtered


def _list_events_v2(
    run_id: str,
    limit: int,
    include: str | None,
    stage_name: str | None,
    agent_name: str | None,
) -> list[dict]:
    include_tokens = _parse_include_tokens(include, default_tokens={"raw_json", "summary", "inference", "html"})
    rows = list_agent_run_events_stage_aware(settings, run_id, limit=limit)
    event_ids = [str(row.get("event_id")) for row in rows if row.get("event_id")]
    artifact_by_event_id: dict[str, dict] = {}
    if event_ids:
        try:
            artifact_by_event_id = list_agent_event_artifacts_by_event_ids(settings, run_id, event_ids)
        except Exception:
            artifact_by_event_id = {}
    events: list[dict] = []
    for row in rows:
        if stage_name and row.get("stage_name") != stage_name:
            continue
        if agent_name and row.get("agent_name") != agent_name:
            continue
        item = dict(row)
        event_id = item.get("event_id")
        direct_artifacts = item.get("artifacts")
        artifact_payload = direct_artifacts
        if event_id and str(event_id) in artifact_by_event_id:
            stored_artifacts = _filter_artifact_payload(artifact_by_event_id[str(event_id)], include_tokens)
            direct_filtered = _filter_artifact_payload(direct_artifacts, include_tokens)
            artifact_payload = {**direct_filtered, **stored_artifacts}
        item["artifacts"] = _filter_artifact_payload(artifact_payload, include_tokens)
        events.append(item)
    return events


def _events_as_chat_messages(
    *,
    run_id: str,
    limit: int,
    include: str | None,
    stage_name: str | None = None,
    agent_name: str | None = None,
) -> list[dict]:
    events = _list_events_v2(
        run_id=run_id,
        limit=limit,
        include=include,
        stage_name=stage_name,
        agent_name=agent_name,
    )
    messages: list[dict] = []
    for event in events:
        artifacts = event.get("artifacts") or {}
        raw_json = artifacts.get("raw_json") if isinstance(artifacts, dict) else None
        dashboard_id = None
        dashboard_title = None
        chart_ids: list[str] = []
        chart_titles: list[str] = []
        if isinstance(artifacts, dict):
            dashboard_id = artifacts.get("dashboard_id") or dashboard_id
            dashboard_title = artifacts.get("dashboard_title") or dashboard_title
            for value in artifacts.get("chart_ids") or []:
                if value:
                    chart_ids.append(str(value))
            for value in artifacts.get("chart_titles") or []:
                if value:
                    chart_titles.append(str(value))
            if isinstance(artifacts.get("chart_details"), list):
                for chart in artifacts.get("chart_details") or []:
                    if isinstance(chart, dict):
                        title = chart.get("title") or chart.get("chart_title")
                        if title:
                            chart_titles.append(str(title))
        if isinstance(raw_json, dict):
            dashboard_id = dashboard_id or raw_json.get("dashboard_id")
            dashboard_title = dashboard_title or raw_json.get("title") or raw_json.get("dashboard_title")
            charts = raw_json.get("charts")
            if isinstance(charts, list):
                for chart in charts:
                    if isinstance(chart, dict):
                        cid = chart.get("chart_id")
                        if cid:
                            chart_ids.append(str(cid))
                        title = chart.get("title") or chart.get("chart_title")
                        if title:
                            chart_titles.append(str(title))
        chart_ids = list(dict.fromkeys(chart_ids))
        chart_titles = list(dict.fromkeys(chart_titles))
        messages.append(
            {
                "message_id": f"evtmsg_{event.get('event_id')}",
                "run_id": run_id,
                "sender": "agent",
                "agent_name": event.get("agent_name"),
                "status": event.get("status"),
                "message": event.get("message"),
                "event_id": event.get("event_id"),
                "logical_event_id": event.get("logical_event_id"),
                "stage_name": event.get("stage_name"),
                "stage_seq": event.get("stage_seq"),
                "payload_compacted": event.get("payload_compacted"),
                "artifacts": artifacts,
                "dashboard_id": dashboard_id,
                "dashboard_title": dashboard_title,
                "chart_ids": chart_ids,
                "chart_titles": chart_titles,
                "created_at": event.get("created_at"),
            }
        )
    return messages


def _latest_agent_event(run_id: str, agent_name: str, status: str = "completed") -> dict | None:
    events = list_agent_run_events(settings, run_id, limit=2000)
    for event in reversed(events):
        if event.get("agent_name") == agent_name and event.get("status") == status:
            return event
    return None


@app.get(
    "/agentic/runs/{run_id}/events/{event_id}/artifacts",
    tags=["agentic"],
    summary="Get artifacts for an event stage",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "dashboard_completed_artifacts": {
                                "summary": "Dashboard stage artifacts",
                                "value": {
                                    "event_id": "evt_123",
                                    "run_id": "run_1a0f427c86ec",
                                    "agent_name": "DashboardAgent",
                                    "stage_name": "completed",
                                    "raw_json": {
                                        "dashboard_id": "dash_123",
                                        "dashboard_title": "Lpg Production Distribution Dashboard",
                                        "chart_ids": ["chart_a1b2c3", "chart_d4e5f6"],
                                        "chart_titles": [
                                            "Total Production Trend Over Process Date",
                                            "Total Production by Plant Name"
                                        ],
                                        "quality_report": {
                                            "gate_passed": True,
                                            "quality_score": 0.9,
                                            "warnings": [],
                                            "blocked_patterns": [],
                                            "kpi_mix": {
                                                "trend": 2,
                                                "breakdown_or_share": 2,
                                                "quality_or_rate": 1
                                            }
                                        },
                                        "chart_details": [
                                            {
                                                "chart_id": "chart_a1b2c3",
                                                "title": "Total Production Trend Over Process Date",
                                                "metric_intent": "volume",
                                                "semantic_validation": {
                                                    "status": "passed",
                                                    "reason": "eligible_metric"
                                                }
                                            },
                                            {
                                                "title": "sum_PaymentErrorCode Trend",
                                                "skipped": True,
                                                "reason": "invalid_metric",
                                                "semantic_validation": {
                                                    "status": "rejected",
                                                    "reason": "invalid_metric_role_or_expression"
                                                }
                                            }
                                        ]
                                    },
                                    "summary_raw_text": "Dashboard and charts were generated successfully.",
                                    "inference_raw_text": "The dashboard emphasizes production trend and plant-wise distribution.",
                                    "truncation": {"applied": False, "sample_limit": 50, "fields_truncated": []}
                                },
                            }
                        }
                    }
                }
            }
        }
    },
)
def get_agentic_run_event_artifacts(run_id: str, event_id: str, include: str | None = None) -> dict:
    include_tokens = _parse_include_tokens(include)
    try:
        artifact = get_agent_event_artifact(settings, run_id, event_id)
    except Exception:
        artifact = None
    if not artifact:
        raise HTTPException(status_code=404, detail=f"Artifacts not found for event_id={event_id}")
    payload = dict(artifact)
    payload_filtered = _filter_artifact_payload(payload, include_tokens)
    payload["raw_json"] = payload_filtered.get("raw_json")
    payload["summary_raw_text"] = payload_filtered.get("summary_raw_text")
    payload["summary_html"] = payload_filtered.get("summary_html")
    payload["inference_raw_text"] = payload_filtered.get("inference_raw_text")
    payload["inference_html"] = payload_filtered.get("inference_html")
    payload["truncation"] = payload_filtered.get("truncation")
    return payload


@app.get(
    "/agentic/debug/schema",
    tags=["agentic"],
    summary="Debug: latest schema payload",
    description="Return the latest stored schema payload for the tenant/domain scope.",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "schema_payload": {
                                "summary": "Latest scoped schema payload",
                                "value": {
                                    "tenant_id": "VC_101",
                                    "domain_id": "lpg_production_distribution",
                                    "connection_id": "conn_lpg",
                                    "database": "hpcl_ceg",
                                    "schema": "public",
                                    "schema_payload": {
                                        "tables": [
                                            {
                                                "table": "lpg_plant_operations",
                                                "columns": [
                                                    {"name": "sap_id", "data_type": "text"},
                                                    {"name": "process_date", "data_type": "date"},
                                                ],
                                            }
                                        ]
                                    },
                                },
                            }
                        }
                    }
                }
            }
        }
    },
)
def agentic_debug_schema(tenant_id: str, domain_id: str | None = None) -> dict:
    domain_id = _resolve_domain_id(tenant_id, domain_id)
    connection_id, database, schema, _ = _resolve_scope_values(tenant_id, domain_id)
    schema_payload = load_latest_scan_for_scope(
        settings, tenant_id, domain_id, connection_id, database, schema
    )
    if not schema_payload:
        raise HTTPException(status_code=404, detail="No schema payload found for scope")
    return {
        "tenant_id": tenant_id,
        "domain_id": domain_id,
        "connection_id": connection_id,
        "database": database,
        "schema": schema,
        "schema_payload": schema_payload,
    }


@app.get(
    "/agentic/debug/profiling",
    tags=["agentic"],
    summary="Debug: profiling stats for run",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "profiling_stats": {
                                "summary": "Profiling artifacts for run",
                                "value": {
                                    "run_id": "run_123",
                                    "profiling_stats": {
                                        "tables": 4,
                                        "profiles": [
                                            {
                                                "name": "lpg_plant_operations",
                                                "row_count": 12000,
                                                "numeric_columns": ["production_19kg"],
                                            }
                                        ],
                                    },
                                },
                            }
                        }
                    }
                }
            }
        }
    },
)
def agentic_debug_profiling(run_id: str) -> dict:
    event = _latest_agent_event(run_id, "ProfilingAgent")
    if not event:
        raise HTTPException(status_code=404, detail="Profiling event not found")
    return {"run_id": run_id, "profiling_stats": event.get("artifacts")}


@app.get(
    "/agentic/debug/glossary",
    tags=["agentic"],
    summary="Debug: glossary terms after context",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "glossary_terms": {
                                "summary": "Glossary artifacts for run",
                                "value": {
                                    "run_id": "run_123",
                                    "glossary_terms": {
                                        "entities": 8,
                                        "sample_entities": ["plant", "region", "sap id"],
                                    },
                                },
                            }
                        }
                    }
                }
            }
        }
    },
)
def agentic_debug_glossary(run_id: str) -> dict:
    event = _latest_agent_event(run_id, "ContextAgent")
    if not event:
        event = _latest_agent_event(run_id, "GlossaryAgent")
    if not event:
        raise HTTPException(status_code=404, detail="Glossary event not found")
    return {"run_id": run_id, "glossary_terms": event.get("artifacts")}


@app.get(
    "/agentic/debug/intelligence",
    tags=["agentic"],
    summary="Debug: run-scoped conversation intelligence bundle",
)
def agentic_debug_intelligence(tenant_id: str, domain_id: str | None = None, run_id: str | None = None) -> dict:
    resolved_domain = _resolve_domain_id(tenant_id, domain_id)
    if not run_id:
        deployment = get_current_deployment(settings, tenant_id, resolved_domain)
        if deployment:
            run_id = deployment.get("run_id")
    connection_id, database_name, schema_name, _ = _resolve_scope_values(tenant_id, resolved_domain)
    bundle = _load_run_scoped_intelligence(
        tenant_id=tenant_id,
        domain_id=resolved_domain,
        run_id=run_id,
        connection_id=connection_id,
        database_name=database_name,
        schema_name=schema_name,
    )
    return {
        "tenant_id": tenant_id,
        "domain_id": resolved_domain,
        "run_id": run_id,
        "connection_id": connection_id,
        "database_name": database_name,
        "schema_name": schema_name,
        "counts": {
            "metrics": len(bundle.get("metrics") or []),
            "facts": len(bundle.get("facts") or []),
            "dimensions": len(bundle.get("dimensions") or []),
            "glossary": len(bundle.get("glossary") or []),
            "hierarchies": len(bundle.get("hierarchies") or []),
            "joins": len(bundle.get("joins") or []),
            "models": len(bundle.get("models") or []),
            "dimension_candidates": len(bundle.get("dimension_candidates") or []),
        },
        "artifact_agents": sorted(list((bundle.get("agent_artifacts") or {}).keys())),
        "metrics_sample": [
            {
                "metric_name": row.get("metric_name"),
                "dataset_id": row.get("dataset_id"),
                "source_model": row.get("source_model"),
                "source_run_id": row.get("source_run_id"),
            }
            for row in (bundle.get("metrics") or [])[:10]
        ],
        "facts_sample": [
            {
                "table_name": row.get("table_name"),
                "grain": row.get("grain"),
                "time_column": row.get("time_column"),
                "source_run_id": row.get("source_run_id"),
            }
            for row in (bundle.get("facts") or [])[:10]
        ],
        "dimensions_sample": [
            {
                "name": row.get("name"),
                "keys": row.get("keys"),
                "attributes": row.get("attributes"),
                "source_run_id": row.get("source_run_id"),
            }
            for row in (bundle.get("dimensions") or [])[:10]
        ],
        "glossary_sample": (bundle.get("glossary") or [])[:20],
        "hierarchies_sample": (bundle.get("hierarchies") or [])[:20],
        "joins_sample": (bundle.get("joins") or [])[:20],
        "models_sample": (bundle.get("models") or [])[:20],
        "dimension_candidates_sample": (bundle.get("dimension_candidates") or [])[:50],
    }


@app.get(
    "/agentic/debug/proposals",
    tags=["agentic"],
    summary="Debug: metric/chart/dashboard proposal diagnostics for a run",
)
def agentic_debug_proposals(run_id: str) -> dict:
    agent_artifacts = _latest_agent_completed_artifacts(run_id)
    metric_artifacts = agent_artifacts.get("MetricAgent") or {}
    chart_artifacts = agent_artifacts.get("ChartPlannerAgent") or {}
    dashboard_artifacts = agent_artifacts.get("DashboardAgent") or {}
    accepted_metrics = ((metric_artifacts.get("context_metric_diagnostics") or {}).get("accepted_metrics") or [])
    rejected_metrics = ((metric_artifacts.get("context_metric_diagnostics") or {}).get("rejected_metrics") or [])
    chart_plan = chart_artifacts.get("chart_plan") or []
    chart_rejections = chart_artifacts.get("chart_rejections") or []
    return {
        "run_id": run_id,
        "metric_proposals": {
            "context_metric_diagnostics": metric_artifacts.get("context_metric_diagnostics"),
            "metric_rerank_diagnostics": metric_artifacts.get("metric_rerank_diagnostics"),
            "accepted_count": len(accepted_metrics),
            "rejected_count": len(rejected_metrics),
            "accepted_sample": accepted_metrics[:20],
            "rejected_sample": rejected_metrics[:20],
        },
        "chart_proposals": {
            "chart_proposal_diagnostics": chart_artifacts.get("chart_proposal_diagnostics"),
            "chart_rerank_diagnostics": chart_artifacts.get("chart_rerank_diagnostics"),
            "selected_count": len(chart_plan),
            "rejected_count": len(chart_rejections),
            "selected_sample": chart_plan[:30],
            "rejected_sample": chart_rejections[:30],
        },
        "dashboard_composition": {
            "dashboard_composition_diagnostics": dashboard_artifacts.get("dashboard_composition_diagnostics"),
            "dashboard_title": dashboard_artifacts.get("dashboard_title"),
            "chart_ids": dashboard_artifacts.get("chart_ids") or [],
            "chart_titles": dashboard_artifacts.get("chart_titles") or [],
            "chart_details": (dashboard_artifacts.get("chart_details") or [])[:30],
        },
    }


@app.get(
    "/agentic/debug/rollups",
    tags=["agentic"],
    summary="Debug: rollup candidates before build",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "rollup_candidates": {
                                "summary": "Rollup planner artifacts",
                                "value": {
                                    "run_id": "run_123",
                                    "rollup_artifacts": {
                                        "rollups": 3,
                                        "rollup_candidates": [
                                            {
                                                "metric_name": "production_mt",
                                                "dimensions": ["region"],
                                                "time_grain": "month",
                                            }
                                        ],
                                    },
                                },
                            }
                        }
                    }
                }
            }
        }
    },
)
def agentic_debug_rollups(run_id: str) -> dict:
    event = _latest_agent_event(run_id, "RollupPlannerAgent")
    if not event:
        raise HTTPException(status_code=404, detail="Rollup event not found")
    return {"run_id": run_id, "rollup_artifacts": event.get("artifacts")}


@app.get(
    "/agentic/runs/{run_id}/stream",
    tags=["agentic"],
    summary="Stream agentic run events",
    description="Server-sent events stream of agentic run progress.",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "text/event-stream": {
                        "examples": {
                            "running_event": {
                                "summary": "Agent started",
                                "value": "data: {\"agent_name\":\"SchemaAgent\",\"status\":\"running\",\"message\":\"Schema Agent started\"}\n\n",
                            },
                            "dq_review_required": {
                                "summary": "Data quality run requires rule review",
                                "value": "data: {\"agent_name\":\"DataQualityRuleAgent\",\"status\":\"needs_review\",\"stage_name\":\"awaiting_rule_review\",\"message\":\"Rule review required\",\"artifacts\":{\"raw_json\":{\"rule_review_required\":true,\"review_queue_pending_count\":2}}}\n\n",
                            },
                            "completed_event": {
                                "summary": "Agent completed",
                                "value": "data: {\"agent_name\":\"JoinAgent\",\"status\":\"completed\",\"message\":\"Join Agent completed\",\"artifacts\":{\"joins\":7}}\n\n",
                            },
                            "failed_event": {
                                "summary": "Run failed",
                                "value": "data: {\"agent_name\":\"WorkflowAgent\",\"status\":\"failed\",\"stage_name\":\"failed\",\"message\":\"Agentic workflow failed\",\"artifacts\":{\"error_type\":\"NameError\",\"error_message\":\"name 're' is not defined\"}}\n\n",
                            },
                            "heartbeat": {
                                "summary": "SSE heartbeat",
                                "value": ": heartbeat\n\n",
                            }
                        }
                    }
                }
            }
        }
    },
)
def agentic_run_stream(run_id: str):
    from fastapi.responses import StreamingResponse

    def _event_stream():
        last_count = 0
        while True:
            events = list_agent_run_events_stage_aware(settings, run_id, limit=2000)
            new_events = events[last_count:]
            for event in new_events:
                payload = json.dumps(event, default=str)
                yield f"data: {payload}\n\n"
            last_count = len(events)
            # heartbeat to keep clients (like Swagger) from hanging silently
            if not new_events:
                yield ": heartbeat\n\n"
            time.sleep(1.0)

    return StreamingResponse(_event_stream(), media_type="text/event-stream")


@app.get(
    "/agentic/runs/{run_id}/chat",
    tags=["agentic"],
    summary="List agentic run chat log",
    description="Return stored chat/summary stream messages for a run.",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "first_50": {
                                "summary": "First 50 messages (cursor omitted)",
                                "value": {
                                    "messages": [
                                        {"sender": "system", "message": "Plan created: Scan schema; Build semantics; Create dashboards"},
                                        {
                                            "sender": "agent",
                                            "agent_name": "DashboardAgent",
                                            "stage_name": "completed",
                                            "message": "Dashboard Agent completed",
                                            "dashboard_id": "dash_123",
                                            "dashboard_title": "Lpg Production Distribution Dashboard",
                                            "chart_ids": ["chart_a1b2c3", "chart_d4e5f6"],
                                            "chart_titles": [
                                                "Total Production Trend Over Process Date",
                                                "Total Production by Plant Name"
                                            ],
                                            "artifacts": {
                                                "raw_json": {
                                                    "dashboard_id": "dash_123",
                                                    "dashboard_title": "Lpg Production Distribution Dashboard",
                                                    "quality_report": {
                                                        "gate_passed": True,
                                                        "quality_score": 0.9,
                                                        "warnings": [],
                                                        "blocked_patterns": [],
                                                        "kpi_mix": {
                                                            "trend": 2,
                                                            "breakdown_or_share": 2,
                                                            "quality_or_rate": 1
                                                        }
                                                    },
                                                    "chart_details": [
                                                        {
                                                            "chart_id": "chart_a1b2c3",
                                                            "title": "Total Production Trend Over Process Date",
                                                            "metric_intent": "volume",
                                                            "semantic_validation": {
                                                                "status": "passed",
                                                                "reason": "eligible_metric"
                                                            }
                                                        }
                                                    ]
                                                }
                                            }
                                        },
                                        {"sender": "system", "message": "Dashboard ready: Lpg Production Distribution Dashboard"}
                                    ],
                                    "paging": {
                                        "limit": 50,
                                        "cursor": None,
                                        "returned": 50,
                                        "has_more": True,
                                        "next_cursor": "NTA="
                                    }
                                },
                            },
                            "next_50": {
                                "summary": "Next 50 messages using previous next_cursor",
                                "value": {
                                    "messages": [
                                        {"sender": "agent", "message": "Metric Agent completed"},
                                        {"sender": "agent", "message": "Semantic Model Agent completed"}
                                    ],
                                    "paging": {
                                        "limit": 50,
                                        "cursor": "NTA=",
                                        "returned": 50,
                                        "has_more": True,
                                        "next_cursor": "MTAw"
                                    }
                                },
                            },
                            "last_page": {
                                "summary": "Last page (no more records)",
                                "value": {
                                    "messages": [
                                        {"sender": "agent", "message": "Dashboard Agent completed"}
                                    ],
                                    "paging": {
                                        "limit": 50,
                                        "cursor": "MTAw",
                                        "returned": 13,
                                        "has_more": False,
                                        "next_cursor": None
                                    }
                                },
                            }
                        }
                    }
                }
            }
        }
    },
)
def get_agentic_run_chat(
    run_id: str,
    limit: int = Query(
        50,
        ge=1,
        le=2000,
        description="Maximum number of chat summary messages to return in chronological order.",
        openapi_examples={
            "first_page": {"summary": "Fetch first 50", "value": 50},
            "smaller_page": {"summary": "Fetch first 20", "value": 20},
        },
    ),
    cursor: str | None = Query(
        None,
        description="Opaque cursor for pagination. Use `paging.next_cursor` from previous response.",
        openapi_examples={
            "first_page": {"summary": "First page request", "value": None},
            "second_page": {"summary": "Next page cursor from previous response", "value": "NTA="},
        },
    ),
    include: str | None = None,
    include_stages: bool = True,
    sender: str | None = None,
) -> dict:
    bounded_limit = max(1, min(int(limit), 2000))
    if cursor:
        try:
            cursor_value = _decode_cursor(cursor)
            start_offset = max(0, int(cursor_value))
        except Exception as exc:
            raise HTTPException(status_code=400, detail="Invalid cursor") from exc
    else:
        start_offset = 0
    fetch_window = min(2000, start_offset + bounded_limit + 1)
    rows = list_agent_chat_log(settings, run_id, limit=fetch_window)
    base_messages: list[dict] = []
    for row in rows:
        item = dict(row)
        if include_stages and item.get("sender") == "agent":
            # Agent lifecycle replay comes from stage-aware events to keep parity with stream payloads.
            continue
        if not include_stages:
            item.pop("event_id", None)
            item.pop("stage_name", None)
            item.pop("logical_event_id", None)
        base_messages.append(item)

    if include_stages:
        stage_messages = _events_as_chat_messages(run_id=run_id, limit=2000, include=include)
        all_messages = base_messages + stage_messages
    else:
        all_messages = base_messages

    # De-duplicate replay records while preserving chronological order.
    deduped: list[dict] = []
    seen = set()
    for msg in all_messages:
        key = (
            msg.get("sender"),
            msg.get("message"),
            msg.get("created_at"),
            msg.get("event_id"),
            msg.get("stage_name"),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(msg)

    if sender:
        deduped = [msg for msg in deduped if msg.get("sender") == sender]

    deduped.sort(key=lambda item: str(item.get("created_at") or ""))
    page = deduped[start_offset : start_offset + bounded_limit + 1]
    has_more = len(page) > bounded_limit
    messages = page[:bounded_limit]
    next_cursor = _encode_cursor(str(start_offset + bounded_limit)) if has_more else None
    return {
        "messages": messages,
        "paging": {
            "limit": bounded_limit,
            "cursor": cursor,
            "returned": len(messages),
            "has_more": has_more,
            "next_cursor": next_cursor,
        },
    }


@app.get(
    "/views",
    response_model=ViewListResponse,
    tags=["views"],
    summary="List views",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "views": {
                                "summary": "View list",
                                "value": {
                                    "views": [
                                        {
                                            "view_name": "fact_lpg_plant_operations",
                                            "schema": "public",
                                            "type": "fact",
                                            "source_table": "lpg_plant_operations",
                                        }
                                        ,
                                        {
                                            "view_name": "view_fact_lpg_plant_operations_lpg_distributor_mapping",
                                            "schema": "public",
                                            "type": "joined",
                                            "source_table": "fact_lpg_plant_operations__lpg_distributor_mapping",
                                            "join_metadata": {
                                                "left_table": "fact_lpg_plant_operations",
                                                "right_table": "lpg_distributor_mapping",
                                                "left_key": "sap_id",
                                                "right_key": "sap_id",
                                                "coverage_ratio": 0.92
                                            }
                                        }
                                    ]
                                },
                            }
                        }
                    }
                }
            }
        }
    },
)
def list_views_endpoint(tenant_id: str, domain_id: str | None = None) -> ViewListResponse:
    views = list_registered_views(settings, tenant_id, domain_id)
    payload = []
    for view in views:
        view_type = view.get("view_type") or "fact"
        join_meta = None
        if view_type == "joined":
            source_table = view.get("source_table") or ""
            if "__" in source_table:
                left_table, right_table = source_table.split("__", 1)
                join_meta = {
                    "left_table": left_table,
                    "right_table": right_table,
                    "left_key": view.get("join_left_key"),
                    "right_key": view.get("join_right_key"),
                    "coverage_ratio": view.get("coverage_ratio"),
                }
        payload.append(
            {
                "view_name": view.get("view_name"),
                "schema": view.get("schema_name"),
                "type": view_type,
                "source_table": view.get("source_table"),
                "join_metadata": join_meta,
                "created_at": view.get("created_at"),
            }
        )
    return ViewListResponse(views=payload)


def _normalize_relation_name(raw: str) -> str:
    token = str(raw or "").strip().strip(",;")
    if not token:
        return ""
    # Remove alias tail: "schema.view v" -> "schema.view"
    token = token.split()[0]
    token = token.replace('"', "")
    return token.lower()


def _extract_sql_relation_refs(sql_text: str) -> list[str]:
    refs: list[str] = []
    for match in re.finditer(r"(?i)\b(?:from|join)\s+([a-zA-Z0-9_\"\.]+)", sql_text):
        rel = _normalize_relation_name(match.group(1))
        if not rel or rel == "select":
            continue
        refs.append(rel)
    return list(dict.fromkeys(refs))


def _allowed_view_refs_for_scope(tenant_id: str, domain_id: str) -> tuple[set[str], list[dict]]:
    rows = list_registered_views(settings, tenant_id, domain_id)
    refs: set[str] = set()
    for row in rows:
        view_name = str(row.get("view_name") or "").strip()
        schema_name = str(row.get("schema_name") or "").strip()
        if view_name:
            refs.add(view_name.lower())
        if schema_name and view_name:
            refs.add(f"{schema_name.lower()}.{view_name.lower()}")
    return refs, rows


@app.get(
    "/views/{view_name}/schema",
    response_model=ViewSchemaResponse,
    tags=["views"],
    summary="Get view schema",
    openapi_extra={
        "parameters": [
            {
                "name": "tenant_id",
                "in": "query",
                "required": True,
                "schema": {"type": "string"},
                "description": "Tenant identifier.",
            },
            {
                "name": "domain_id",
                "in": "query",
                "required": False,
                "schema": {"type": "string"},
                "description": "Domain identifier for scoped view lookup.",
            },
            {
                "name": "schema",
                "in": "query",
                "required": False,
                "schema": {"type": "string"},
                "description": "Database schema name. Defaults to registry schema for the view.",
            },
        ],
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "schema": {
                                "summary": "View schema",
                                "value": {
                                    "view_name": "fact_lpg_plant_operations",
                                    "schema": "public",
                                    "columns": [
                                        {"column_name": "sap_id", "data_type": "text"},
                                        {"column_name": "process_date", "data_type": "date"},
                                    ],
                                },
                            },
                            "schema_scoped": {
                                "summary": "View schema scoped by tenant+domain registry",
                                "value": {
                                    "view_name": "fact_lpg_plant_operations",
                                    "schema": "public",
                                    "columns": [
                                        {"column_name": "sap_id", "data_type": "character varying"},
                                        {"column_name": "process_date", "data_type": "timestamp with time zone"},
                                        {"column_name": "total_production", "data_type": "numeric"}
                                    ]
                                }
                            },
                        }
                    }
                }
            },
            "404": {
                "content": {
                    "application/json": {
                        "examples": {
                            "view_not_in_scope": {
                                "summary": "View is not registered for tenant/domain scope",
                                "value": {"detail": "View not found in tenant/domain scope"},
                            }
                        }
                    }
                }
            }
        }
    },
)
def view_schema_endpoint(
    view_name: str,
    tenant_id: str,
    domain_id: str | None = None,
    schema: str | None = None,
) -> ViewSchemaResponse:
    resolved_domain_id = _resolve_domain_id(tenant_id, domain_id)
    allowed_refs, registry_rows = _allowed_view_refs_for_scope(tenant_id, resolved_domain_id)
    requested = _normalize_relation_name(f"{schema or ''}.{view_name}" if schema else view_name)
    if requested not in allowed_refs and _normalize_relation_name(view_name) not in allowed_refs:
        raise HTTPException(
            status_code=404,
            detail="View not found in tenant/domain scope",
        )
    schema_name = schema
    if not schema_name:
        for row in registry_rows:
            if str(row.get("view_name") or "").lower() == str(view_name).lower():
                schema_name = row.get("schema_name")
                break
    schema_name = schema_name or settings.db_schema
    columns = load_view_schema(settings, schema_name, view_name)
    return ViewSchemaResponse(view_name=view_name, schema_name=schema_name, columns=columns)


def _view_chart_palette() -> list[str]:
    return ["#0077B6", "#00B4D8", "#90E0EF", "#2A9D8F", "#E9C46A", "#F4A261", "#E76F51", "#264653"]


def _to_number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip().replace(",", "")
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None
    return None


def _deterministic_query_chart(rows: list[dict], columns: list[str]) -> dict:
    if not rows or not columns:
        return {
            "status": "skipped",
            "reason": "no_data",
            "source": "deterministic",
            "confidence": 0.0,
            "chart_type": None,
            "chart_payload": None,
            "data": [],
        }
    numeric_cols: list[str] = []
    dimension_cols: list[str] = []
    for col in columns:
        sample = next((row.get(col) for row in rows if row.get(col) is not None), None)
        if _to_number(sample) is not None:
            numeric_cols.append(col)
        else:
            dimension_cols.append(col)
    if not numeric_cols:
        return {
            "status": "skipped",
            "reason": "no_numeric_measure",
            "source": "deterministic",
            "confidence": 0.0,
            "chart_type": None,
            "chart_payload": None,
            "data": [],
        }
    metric_col = numeric_cols[0]
    dimensions = dimension_cols[:2] if dimension_cols else []
    chart_type = infer_chart_type(dimensions, rows[:200], [metric_col]) if dimensions else "bar"
    chart_type = chart_type or "bar"
    data_rows = []
    for row in rows[:200]:
        point = dict(row)
        metric_value = _to_number(row.get(metric_col))
        if metric_value is None:
            continue
        point[metric_col] = metric_value
        data_rows.append(point)
    if not data_rows:
        return {
            "status": "skipped",
            "reason": "no_numeric_rows",
            "source": "deterministic",
            "confidence": 0.0,
            "chart_type": None,
            "chart_payload": None,
            "data": [],
        }
    payload = build_chart_payload(chart_type, data_rows, metric_col, dimensions or [columns[0]])
    palette = _view_chart_palette()
    payload["source"] = "deterministic"
    payload["confidence"] = 0.55
    payload["metric"] = metric_col
    payload["dimensions"] = dimensions
    payload["status"] = "ready"
    if payload.get("chart_payload"):
        payload["chart_payload"]["colors"] = palette
    return payload


def _view_llm_enabled() -> bool:
    return bool(getattr(settings, "openai_api_key", None))


def _call_openai_json(system_prompt: str, user_payload: dict, *, timeout_sec: int = 45) -> dict | None:
    if not _view_llm_enabled():
        return None
    body = {
        "model": settings.openai_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_payload, default=str)},
        ],
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
    }
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {settings.openai_api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    content = ((payload.get("choices") or [{}])[0].get("message") or {}).get("content")
    if not content:
        return None
    try:
        return json.loads(str(content))
    except json.JSONDecodeError:
        return None


def _call_openai_text(system_prompt: str, user_payload: dict, *, timeout_sec: int = 45) -> str | None:
    if not _view_llm_enabled():
        return None
    body = {
        "model": settings.openai_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_payload, default=str)},
        ],
        "temperature": 0.2,
    }
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {settings.openai_api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    text = ((payload.get("choices") or [{}])[0].get("message") or {}).get("content")
    return str(text).strip() if text else None


def _generate_view_chart_with_llm(sql_text: str, rows: list[dict], columns: list[str]) -> dict | None:
    if not rows or not columns:
        return {
            "status": "skipped",
            "reason": "no_data",
            "source": "llm",
            "confidence": 0.0,
            "chart_type": None,
            "chart_payload": None,
            "data": [],
        }
    numeric_cols: list[str] = []
    dimension_cols: list[str] = []
    for col in columns:
        sample = next((row.get(col) for row in rows if row.get(col) is not None), None)
        if _to_number(sample) is not None:
            numeric_cols.append(col)
        else:
            dimension_cols.append(col)
    if not numeric_cols:
        return {
            "status": "skipped",
            "reason": "no_numeric_measure",
            "source": "llm",
            "confidence": 0.0,
            "chart_type": None,
            "chart_payload": None,
            "data": [],
        }
    system_prompt = (
        "You are a BI chart planner for AMCharts. "
        "Return JSON only with keys chart_type, metric, dimensions, title, confidence. "
        "chart_type must be one of: line, bar, pie, none. "
        "Choose only fields that exist in provided columns."
    )
    user_payload = {
        "sql": sql_text,
        "columns": columns,
        "numeric_columns": numeric_cols,
        "dimension_columns": dimension_cols,
        "sample_rows": rows[:25],
    }
    llm = _call_openai_json(system_prompt, user_payload)
    if not llm:
        return None
    chart_type = str(llm.get("chart_type") or "").strip().lower()
    if chart_type not in {"line", "bar", "pie"}:
        if chart_type == "none":
            return {
                "status": "skipped",
                "reason": "llm_no_chart",
                "source": "llm",
                "confidence": float(llm.get("confidence") or 0.0),
                "chart_type": None,
                "chart_payload": None,
                "data": [],
            }
        return None
    metric = str(llm.get("metric") or "").strip()
    if metric not in columns:
        metric = numeric_cols[0]
    dims = [d for d in (llm.get("dimensions") or []) if isinstance(d, str) and d in columns and d != metric][:2]
    if not dims and dimension_cols:
        dims = dimension_cols[:1]
    payload = build_chart_payload(chart_type, rows[:200], metric, dims or [columns[0]])
    palette = _view_chart_palette()
    if payload.get("chart_payload"):
        payload["chart_payload"]["colors"] = palette
    payload["status"] = "ready"
    payload["source"] = "llm"
    payload["confidence"] = float(llm.get("confidence") or 0.8)
    payload["title"] = str(llm.get("title") or f"{metric} {chart_type.title()}").strip()
    payload["metric"] = metric
    payload["dimensions"] = dims
    return payload


def _generate_view_inference_with_llm(sql_text: str, rows: list[dict], columns: list[str]) -> dict:
    system_prompt = (
        "You are a concise analytics assistant. "
        "Summarize key patterns from query results without inventing values."
    )
    payload = {
        "sql": sql_text,
        "columns": columns,
        "row_count": len(rows),
        "sample_rows": rows[:25],
    }
    text = _call_openai_text(system_prompt, payload)
    if text:
        return {
            "status": "ready",
            "source": "llm",
            "confidence": 0.82,
            "text": text,
        }
    if not rows:
        fallback = "No rows were returned for this query."
    else:
        fallback = f"Returned {len(rows)} rows across {len(columns)} columns."
    return {
        "status": "ready",
        "source": "deterministic_fallback",
        "confidence": 0.4,
        "text": fallback,
    }


def _process_view_query_artifacts(
    query_id: str,
    sql_text: str,
    rows: list[dict],
    columns: list[str],
) -> None:
    try:
        mark_view_query_running(settings, query_id)
        try:
            update_view_query_chart(settings, query_id, chart_status="running", chart_payload=None, chart_error=None)
            llm_chart = _generate_view_chart_with_llm(sql_text, rows, columns)
            chart_payload = llm_chart if llm_chart is not None else _deterministic_query_chart(rows, columns)
            update_view_query_chart(
                settings,
                query_id,
                chart_status=str(chart_payload.get("status") or "ready"),
                chart_payload=chart_payload,
                chart_error=None,
            )
        except Exception as exc:
            logger.exception("views.query.chart_generation_failed | query_id=%s", query_id)
            update_view_query_chart(
                settings,
                query_id,
                chart_status="failed",
                chart_payload=None,
                chart_error=str(exc),
            )
        try:
            update_view_query_inference(
                settings,
                query_id,
                inference_status="running",
                inference_payload=None,
                inference_error=None,
            )
            inference = _generate_view_inference_with_llm(sql_text, rows, columns)
            update_view_query_inference(
                settings,
                query_id,
                inference_status=str(inference.get("status") or "ready"),
                inference_payload=inference,
                inference_error=None,
            )
        except Exception as exc:
            logger.exception("views.query.inference_generation_failed | query_id=%s", query_id)
            update_view_query_inference(
                settings,
                query_id,
                inference_status="failed",
                inference_payload=None,
                inference_error=str(exc),
            )
        finalize_view_query(settings, query_id)
    except Exception:
        logger.exception("views.query.background_failed | query_id=%s", query_id)


@app.post(
    "/views/query",
    response_model=ViewQueryResponse,
    tags=["views"],
    summary="Run SQL query on views",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "query": {
                            "summary": "SQL query scoped to tenant/domain views",
                            "value": {
                                "tenant_id": "VC_101",
                                "domain_id": "lpg_production_distribution",
                                "sql": "SELECT * FROM public.fact_lpg_plant_operations LIMIT 100",
                                "limit": 100
                            },
                        },
                        "join_query": {
                            "summary": "Query over joined registered view",
                            "value": {
                                "tenant_id": "VC_101",
                                "domain_id": "lpg_production_distribution",
                                "sql": "SELECT plant_name, SUM(total_production) AS total_production FROM public.view_fact_lpg_plant_operations_lpg_distributor_mapping GROUP BY plant_name ORDER BY total_production DESC LIMIT 50",
                                "limit": 50
                            }
                        }
                    }
                }
            }
        },
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "started": {
                                "summary": "Data returned immediately; chart/inference pending",
                                "value": {
                                    "query_id": "vq_3f7a2d1b98",
                                    "status": "running",
                                    "chart_status": "pending",
                                    "inference_status": "pending",
                                    "rows": [{"period": "2026-01-01T00:00:00", "production_mt": 1280.0}],
                                    "columns": ["period", "production_mt"],
                                    "row_count": 1,
                                    "chart": None,
                                    "inference": None
                                }
                            }
                        }
                    }
                }
            },
            "400": {
                "content": {
                    "application/json": {
                        "examples": {
                            "outside_scope": {
                                "summary": "SQL references relation outside scoped views",
                                "value": {
                                    "detail": {
                                        "message": "Query references objects outside tenant/domain scoped views",
                                        "invalid_relations": ["public.some_other_table"]
                                    }
                                }
                            },
                            "missing_relation": {
                                "summary": "No FROM/JOIN relation found",
                                "value": {"detail": "Query must reference at least one scoped view in FROM/JOIN"}
                            }
                        }
                    }
                }
            },
            "404": {
                "content": {
                    "application/json": {
                        "examples": {
                            "no_views_for_scope": {
                                "summary": "No views registered for scope",
                                "value": {"detail": "No registered views found for tenant/domain scope"}
                            }
                        }
                    }
                }
            }
        },
    },
)
def views_query(request: ViewQueryRequest) -> ViewQueryResponse:
    resolved_domain_id = _resolve_domain_id(request.tenant_id, request.domain_id)
    sql_text = request.sql.strip().rstrip(";")
    if not sql_text.lower().startswith("select"):
        raise HTTPException(status_code=400, detail="Only SELECT queries are allowed")
    allowed_refs, _ = _allowed_view_refs_for_scope(request.tenant_id, resolved_domain_id)
    if not allowed_refs:
        raise HTTPException(status_code=404, detail="No registered views found for tenant/domain scope")
    relation_refs = _extract_sql_relation_refs(sql_text)
    if not relation_refs:
        raise HTTPException(status_code=400, detail="Query must reference at least one scoped view in FROM/JOIN")
    disallowed = [ref for ref in relation_refs if ref not in allowed_refs]
    if disallowed:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Query references objects outside tenant/domain scoped views",
                "invalid_relations": disallowed,
            },
        )
    if "limit" not in sql_text.lower():
        sql_text = f"{sql_text} LIMIT {request.limit}"
    rows = run_query(settings, sql_text, [], scoped_conn=_resolve_scoped_conn(request.tenant_id, resolved_domain_id))
    columns = list(rows[0].keys()) if rows else []
    query_id = f"vq_{uuid.uuid4().hex[:10]}"
    create_view_query_run(
        settings,
        query_id=query_id,
        tenant_id=request.tenant_id,
        domain_id=resolved_domain_id,
        sql_text=sql_text,
        limit_requested=request.limit,
        data_payload={
            "rows": rows,
            "columns": columns,
            "row_count": len(rows),
        },
    )
    threading.Thread(
        target=_process_view_query_artifacts,
        args=(query_id, sql_text, rows, columns),
        daemon=True,
        name=f"view-query-{query_id}",
    ).start()
    return ViewQueryResponse(
        query_id=query_id,
        status="running",
        chart_status="pending",
        inference_status="pending",
        rows=rows,
        columns=columns,
        row_count=len(rows),
        chart=None,
        inference=None,
    )


@app.get(
    "/views/query/history",
    response_model=ViewQueryHistoryResponse,
    tags=["views"],
    summary="List recent view queries for tenant/domain",
    openapi_extra={
        "parameters": [
            {
                "name": "tenant_id",
                "in": "query",
                "required": True,
                "schema": {"type": "string"},
                "description": "Tenant identifier.",
            },
            {
                "name": "domain_id",
                "in": "query",
                "required": False,
                "schema": {"type": "string"},
                "description": "Optional domain filter.",
            },
            {
                "name": "limit",
                "in": "query",
                "required": False,
                "schema": {"type": "integer", "default": 50, "minimum": 1, "maximum": 200},
                "description": "Page size.",
            },
            {
                "name": "cursor",
                "in": "query",
                "required": False,
                "schema": {"type": "string"},
                "description": "Pagination cursor from previous response.",
            },
        ],
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "first_50": {
                                "summary": "Fetch latest 50 queries",
                                "value": {
                                    "items": [
                                        {
                                            "query_id": "vq_3f7a2d1b98",
                                            "tenant_id": "VC_101",
                                            "domain_id": "lpg_production_distribution",
                                            "status": "completed",
                                            "chart_status": "ready",
                                            "inference_status": "ready",
                                            "row_count": 120,
                                            "limit": 100,
                                            "sql_preview": "SELECT date_trunc('month', process_date) AS period, SUM(total_production) AS production_mt FROM public.fact_lpg_plant_operations ...",
                                            "created_at": "2026-03-12T14:20:00.123456+00:00",
                                            "updated_at": "2026-03-12T14:20:04.453210+00:00",
                                            "chart_error": None,
                                            "inference_error": None
                                        }
                                    ],
                                    "next_cursor": "eyJjcmVhdGVkX2F0IjogIjIwMjYtMDMtMTJUMTQ6MDA6MDAuMDAwMDAwKzAwOjAwIiwgInF1ZXJ5X2lkIjogInZxX2FiY2QxMjM0NTYifQ=="
                                }
                            },
                            "next_50": {
                                "summary": "Fetch next page using cursor",
                                "value": {
                                    "items": [],
                                    "next_cursor": None
                                }
                            }
                        }
                    }
                }
            }
        },
    },
)
def views_query_history(
    tenant_id: str,
    domain_id: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    cursor: str | None = None,
) -> ViewQueryHistoryResponse:
    rows = list_view_query_runs(
        settings,
        tenant_id=tenant_id,
        domain_id=domain_id,
        limit=limit,
        cursor=cursor,
    )
    return ViewQueryHistoryResponse(
        items=rows.get("items") or [],
        next_cursor=rows.get("next_cursor"),
    )


@app.get(
    "/views/query/{query_id}",
    response_model=ViewQueryStatusResponse,
    tags=["views"],
    summary="Get view query status, chart, and inference",
    openapi_extra={
        "parameters": [
            {
                "name": "tenant_id",
                "in": "query",
                "required": True,
                "schema": {"type": "string"},
                "description": "Tenant identifier used when the query was created.",
            },
            {
                "name": "domain_id",
                "in": "query",
                "required": False,
                "schema": {"type": "string"},
                "description": "Optional domain check for scoped polling.",
            },
        ],
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "in_progress": {
                                "summary": "Chart and inference still processing",
                                "value": {
                                    "query_id": "vq_3f7a2d1b98",
                                    "tenant_id": "VC_101",
                                    "domain_id": "lpg_production_distribution",
                                    "sql": "SELECT date_trunc('month', process_date) AS period, SUM(total_production) AS production_mt FROM public.fact_lpg_plant_operations GROUP BY 1 ORDER BY 1",
                                    "limit": 100,
                                    "status": "running",
                                    "chart_status": "running",
                                    "inference_status": "pending",
                                    "rows": [{"period": "2026-01-01T00:00:00", "production_mt": 1280.0}],
                                    "columns": ["period", "production_mt"],
                                    "row_count": 1,
                                    "chart": None,
                                    "inference": None,
                                    "chart_error": None,
                                    "inference_error": None
                                }
                            },
                            "completed": {
                                "summary": "Chart and inference ready",
                                "value": {
                                    "query_id": "vq_3f7a2d1b98",
                                    "tenant_id": "VC_101",
                                    "domain_id": "lpg_production_distribution",
                                    "sql": "SELECT date_trunc('month', process_date) AS period, SUM(total_production) AS production_mt FROM public.fact_lpg_plant_operations GROUP BY 1 ORDER BY 1",
                                    "limit": 100,
                                    "status": "completed",
                                    "chart_status": "ready",
                                    "inference_status": "ready",
                                    "rows": [{"period": "2026-01-01T00:00:00", "production_mt": 1280.0}],
                                    "columns": ["period", "production_mt"],
                                    "row_count": 1,
                                    "chart": {
                                        "status": "ready",
                                        "source": "llm",
                                        "chart_type": "line",
                                        "title": "Production Trend Over Time"
                                    },
                                    "inference": {
                                        "status": "ready",
                                        "source": "llm",
                                        "text": "Production is stable over the selected period."
                                    },
                                    "chart_error": None,
                                    "inference_error": None
                                }
                            }
                        }
                    }
                }
            },
            "404": {
                "content": {
                    "application/json": {
                        "example": {"detail": "Query not found"}
                    }
                }
            }
        }
    },
)
def get_view_query_status(
    query_id: str,
    tenant_id: str,
    domain_id: str | None = None,
) -> ViewQueryStatusResponse:
    row = get_view_query_run(settings, query_id)
    if not row:
        raise HTTPException(status_code=404, detail="Query not found")
    row_tenant = str(row.get("tenant_id") or "")
    row_domain = str(row.get("domain_id") or "")
    if row_tenant != tenant_id:
        raise HTTPException(status_code=404, detail="Query not found")
    if domain_id and row_domain != domain_id:
        raise HTTPException(status_code=404, detail="Query not found")
    payload = row.get("data_payload") or {}
    rows = payload.get("rows") or []
    columns = payload.get("columns") or []
    row_count = int(payload.get("row_count") or len(rows))
    return ViewQueryStatusResponse(
        query_id=str(row.get("query_id") or query_id),
        tenant_id=str(row.get("tenant_id") or ""),
        domain_id=str(row.get("domain_id") or ""),
        sql=str(row.get("sql_text") or ""),
        limit=int(row.get("limit_requested") or 200),
        status=str(row.get("status") or "running"),
        chart_status=str(row.get("chart_status") or "pending"),
        inference_status=str(row.get("inference_status") or "pending"),
        rows=rows,
        columns=columns,
        row_count=row_count,
        chart=row.get("chart_payload"),
        inference=row.get("inference_payload"),
        chart_error=row.get("chart_error"),
        inference_error=row.get("inference_error"),
        created_at=str(row.get("created_at") or "") or None,
        updated_at=str(row.get("updated_at") or "") or None,
    )


def _default_dashboard_title(domain_id: str | None) -> str:
    label = str(domain_id or "Auto").replace("_", " ").replace("-", " ").strip()
    return f"{label.title()} Dashboard" if label else "Auto Dashboard"


def _default_chart_title(chart: dict) -> str:
    metric_name = chart.get("metric_name") or chart.get("metric") or "Metric"
    intent = str(chart.get("intent") or "").strip().lower()
    chart_type = str(chart.get("chart_type") or chart.get("type") or "overview").strip().lower()
    time_column = chart.get("time_column")
    category_column = chart.get("category_column")
    if intent == "trend" or chart_type == "line":
        return f"{metric_name} Trend Over {time_column or 'Time'}"
    if intent in {"breakdown", "join_breakdown"} or chart_type == "bar":
        return f"{metric_name} by {category_column or 'Category'}"
    if intent == "share" or chart_type == "pie":
        return f"{category_column or 'Category'} Share of {metric_name}"
    return f"{metric_name} {chart_type.title()}"


def _regenerated_dashboard_title(domain_id: str | None, charts: list[dict]) -> str:
    metric_name = None
    table_name = None
    for chart in charts:
        if not isinstance(chart, dict):
            continue
        if not metric_name:
            metric_name = chart.get("metric_name") or chart.get("metric")
        if not table_name:
            table_name = chart.get("table")
        if metric_name and table_name:
            break
    if metric_name and table_name:
        metric_label = str(metric_name).replace("_", " ").strip().title()
        table_label = str(table_name).replace("fact_", "").replace("_", " ").strip().title()
        return f"{table_label} {metric_label} Overview".strip()
    return _default_dashboard_title(domain_id)


def _regenerated_chart_title(chart: dict) -> str:
    return _default_chart_title(chart)


def _normalize_dashboard_spec_titles(
    spec: dict | None,
    *,
    domain_id: str | None,
    dashboard_title: str | None,
) -> tuple[dict, str]:
    normalized = dict(spec or {})
    resolved_title = (dashboard_title or normalized.get("title") or normalized.get("dashboard_title") or "").strip()
    if not resolved_title:
        resolved_title = _default_dashboard_title(domain_id)
    normalized["title"] = resolved_title
    normalized["dashboard_title"] = resolved_title
    charts = []
    for item in normalized.get("charts") or []:
        chart = dict(item) if isinstance(item, dict) else {}
        title = (chart.get("title") or "").strip()
        if not title:
            title = _default_chart_title(chart)
        chart["title"] = title
        chart["chart_title"] = title
        chart["dashboard_title"] = resolved_title
        charts.append(chart)
    normalized["charts"] = charts
    return normalized, resolved_title


@app.get(
    "/dashboards",
    response_model=DashboardListResponse,
    tags=["dashboards"],
    summary="List dashboards",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "dashboards": {
                                "summary": "Dashboard list",
                                "value": {
                                    "dashboards": [
                                        {
                                            "dashboard_id": "dash_123",
                                            "tenant_id": "VC_101",
                                            "domain_id": "lpg_production_distribution",
                                            "title": "Lpg Production Distribution Dashboard",
                                            "name": "Lpg Production Distribution Dashboard",
                                            "dashboard_title": "Lpg Production Distribution Dashboard",
                                            "chart_count": 6,
                                            "chart_titles": [
                                                "Total Production Trend Over Process Date",
                                                "Total Production by Plant Name"
                                            ],
                                            "latest_agentic_run_id": "run_123abc456def",
                                            "latest_refresh_id": "dref_a1b2c3d4e5f6",
                                            "quality_score": 0.9,
                                            "quality_gate_passed": True,
                                        }
                                    ]
                                },
                            }
                        }
                    }
                }
            }
        }
    },
)
def list_dashboards_endpoint(
    tenant_id: str,
    domain_id: str | None = None,
    dashboard_type: str | None = None,
    status: str = "active",
    limit: int = 50,
    offset: int = 0,
) -> DashboardListResponse:
    dashboards = _ds_list_dashboards(
        settings, tenant_id, domain_id,
        dashboard_type=dashboard_type,
        status=status,
        limit=limit,
        offset=offset,
    )
    payload = []
    for dash in dashboards:
        d_type = dash.get("dashboard_type", "system")
        d_id = dash.get("dashboard_id")
        name = dash.get("name") or ""

        # For system dashboards enrich with resolved title and agentic run id
        latest_run_id = dash.get("run_id")
        latest_refresh_id = dash.get("latest_refresh_id")
        if d_type == "system" and d_id and not latest_run_id:
            try:
                rows = run_query(
                    settings,
                    """
                    SELECT run_id FROM public.quantyx_agent_run_events
                     WHERE agent_name = 'DashboardAgent' AND status = 'completed'
                       AND (artifacts->>'dashboard_id' = %s OR artifacts->'raw_json'->>'dashboard_id' = %s)
                     ORDER BY created_at DESC LIMIT 1
                    """,
                    [d_id, d_id],
                )
                latest_run_id = rows[0].get("run_id") if rows else None
            except Exception:
                pass
        if d_id and not latest_refresh_id:
            try:
                rows = run_query(
                    settings,
                    "SELECT refresh_id FROM public.quantyx_dashboard_refresh_runs WHERE dashboard_id = %s ORDER BY created_at DESC LIMIT 1",
                    [d_id],
                )
                latest_refresh_id = rows[0].get("refresh_id") if rows else None
            except Exception:
                pass

        def _iso(v):
            return v.isoformat() if hasattr(v, "isoformat") else v

        payload.append({
            "dashboard_id": d_id,
            "dashboard_type": d_type,
            "tenant_id": dash.get("tenant_id"),
            "domain_id": dash.get("domain_id"),
            "name": name,
            "title": name,
            "dashboard_title": name,
            "description": dash.get("description"),
            "status": dash.get("status", "active"),
            "chart_count": int(dash.get("chart_count") or 0),
            "run_id": latest_run_id,
            "latest_agentic_run_id": latest_run_id,
            "latest_refresh_id": latest_refresh_id,
            "quality_score": dash.get("quality_score"),
            "quality_gate_passed": dash.get("quality_gate_passed"),
            "chart_plan": dash.get("chart_plan") or [],
            "created_by": dash.get("created_by"),
            "created_at": _iso(dash.get("created_at")),
            "updated_at": _iso(dash.get("updated_at")),
        })
    return DashboardListResponse(total=len(payload), dashboards=payload)


@app.get(
    "/dashboards/{dashboard_id}",
    response_model=DashboardResponse,
    tags=["dashboards"],
    summary="Get dashboard",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "dashboard": {
                                "summary": "Dashboard",
                                "value": {
                                    "dashboard_id": "dash_123",
                                    "tenant_id": "VC_101",
                                    "domain_id": "lpg_production_distribution",
                                    "title": "Lpg Production Distribution Dashboard",
                                    "spec": {
                                        "title": "Lpg Production Distribution Dashboard",
                                        "dashboard_title": "Lpg Production Distribution Dashboard",
                                        "charts": [
                                            {
                                                "chart_id": "chart_a1b2c3",
                                                "title": "Total Production Trend Over Process Date",
                                                "chart_title": "Total Production Trend Over Process Date",
                                                "dashboard_title": "Lpg Production Distribution Dashboard",
                                                "metric_intent": "volume",
                                                "semantic_validation": {
                                                    "status": "passed",
                                                    "reason": "eligible_metric"
                                                }
                                            }
                                        ],
                                        "quality": {
                                            "gate_passed": True,
                                            "quality_score": 0.9,
                                            "warnings": [],
                                            "blocked_patterns": [],
                                            "kpi_mix": {
                                                "trend": 2,
                                                "breakdown_or_share": 2,
                                                "quality_or_rate": 1
                                            }
                                        }
                                    },
                                },
                            }
                        }
                    }
                }
            }
        }
    },
)
def get_dashboard_endpoint(dashboard_id: str, tenant_id: str | None = None) -> DashboardResponse:
    dash = _ds_get_with_charts(settings, dashboard_id, tenant_id=tenant_id)
    if not dash:
        raise HTTPException(status_code=404, detail="Dashboard not found")

    d_type = dash.get("dashboard_type", "system")
    name = dash.get("name") or ""

    # Build unified charts list
    charts_out = []
    for c in dash.get("charts") or []:
        charts_out.append({
            "entry_id": c.get("entry_id"),
            "chart_id": c.get("chart_id"),
            "position": c.get("position", 0),
            "title_override": c.get("title_override"),
            "title": c.get("title_override") or c.get("title") or (c.get("question") or "").split("\n\nChart context:")[0].strip() or None,
            "chart_type": c.get("chart_type"),
            "chart_source": c.get("chart_source"),
            "status": c.get("status"),
            "sql": c.get("sql"),
            "narrative_text": c.get("narrative_text"),
            "insight_text": c.get("insight_text"),
            "chart_payload": c.get("chart_payload"),
            "chart_data": c.get("chart_data") or c.get("rows_json"),
            "added_by": c.get("added_by"),
            "added_at": c.get("added_at"),
        })

    resolved_title = name

    def _iso(v):
        return v.isoformat() if hasattr(v, "isoformat") else v

    return DashboardResponse(
        dashboard_id=dash["dashboard_id"],
        tenant_id=dash["tenant_id"],
        domain_id=dash["domain_id"],
        title=resolved_title,
        name=name,
        dashboard_type=d_type,
        description=dash.get("description"),
        status=dash.get("status", "active"),
        run_id=dash.get("run_id"),
        latest_refresh_id=dash.get("latest_refresh_id"),
        quality_score=dash.get("quality_score"),
        quality_gate_passed=dash.get("quality_gate_passed"),
        created_by=dash.get("created_by"),
        chart_plan=dash.get("chart_plan") or [],
        charts=charts_out,
        created_at=_iso(dash.get("created_at")),
        updated_at=_iso(dash.get("updated_at")),
    )


@app.put(
    "/dashboards/{dashboard_id}",
    tags=["dashboards"],
    summary="Update dashboard",
    description="Update dashboard spec. Supports title updates (`update_titles`) and chart deletion (`delete_chart`).",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "update_titles": {
                            "summary": "Update dashboard and chart titles",
                            "value": {
                                "action": "update_titles",
                                "title": "North Zone LPG Distribution Command Center",
                                "chart_updates": [
                                    {"chart_id": "chart_abc123", "title": "North Zone Pending Volume Trend"}
                                ],
                            },
                        },
                        "delete_by_chart_id": {
                            "summary": "Delete chart by chart_id",
                            "value": {
                                "action": "delete_chart",
                                "chart_id": "chart_abc123",
                            },
                        },
                        "delete_by_index": {
                            "summary": "Delete chart by chart index",
                            "value": {
                                "action": "delete_chart",
                                "chart_index": 2,
                            },
                        },
                    }
                }
            }
        },
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "titles_updated": {
                                "summary": "Dashboard/chart titles updated",
                                "value": {
                                    "dashboard_id": "dash_123",
                                    "status": "updated",
                                    "dashboard_title": "North Zone LPG Distribution Command Center",
                                    "updated_dashboard_title": True,
                                    "updated_chart_titles": 1,
                                    "chart_count": 6
                                }
                            },
                            "updated": {
                                "summary": "Dashboard chart deleted",
                                "value": {
                                    "dashboard_id": "dash_123",
                                    "status": "updated",
                                    "dashboard_title": "Lpg Production Distribution Dashboard",
                                    "removed_chart_id": "chart_abc123",
                                    "removed_count": 1,
                                    "chart_count": 5,
                                },
                            }
                        }
                    }
                }
            }
        },
    },
)
def update_dashboard_endpoint(dashboard_id: str, payload: DashboardUpdateRequest) -> dict:
    row = get_dashboard_spec(settings, dashboard_id)
    if not row:
        raise HTTPException(status_code=404, detail="Dashboard not found")
    spec, resolved_title = _normalize_dashboard_spec_titles(
        row.get("spec") or {},
        domain_id=row.get("domain_id"),
        dashboard_title=row.get("title"),
    )
    charts = list(spec.get("charts") or [])
    action = (payload.action or "").strip().lower()
    wants_title_update = bool((payload.title or "").strip() or payload.chart_updates)

    if action == "update_titles" or (action != "delete_chart" and wants_title_update):
        dashboard_title = resolved_title
        updated_dashboard_title = False
        if (payload.title or "").strip():
            dashboard_title = payload.title.strip()
            updated_dashboard_title = True
            spec["title"] = dashboard_title
            spec["dashboard_title"] = dashboard_title
            for chart in charts:
                if isinstance(chart, dict):
                    chart["dashboard_title"] = dashboard_title

        chart_updates = payload.chart_updates or []
        title_by_chart_id: dict[str, str] = {}
        for item in chart_updates:
            if not isinstance(item, dict):
                continue
            chart_id = str(item.get("chart_id") or "").strip()
            chart_title = str(item.get("title") or "").strip()
            if chart_id and chart_title:
                title_by_chart_id[chart_id] = chart_title
        if chart_updates and not title_by_chart_id:
            raise HTTPException(status_code=400, detail="chart_updates must include chart_id and title")

        updated_chart_titles = 0
        if title_by_chart_id:
            for item in charts:
                chart = item if isinstance(item, dict) else {}
                chart_id = str(chart.get("chart_id") or "").strip()
                if chart_id in title_by_chart_id:
                    chart["title"] = title_by_chart_id[chart_id]
                    chart["chart_title"] = title_by_chart_id[chart_id]
                    chart["dashboard_title"] = dashboard_title
                    updated_chart_titles += 1
            if isinstance(spec.get("chart_plan"), list):
                for item in spec.get("chart_plan") or []:
                    chart = item if isinstance(item, dict) else {}
                    chart_id = str(chart.get("chart_id") or "").strip()
                    if chart_id in title_by_chart_id:
                        chart["title"] = title_by_chart_id[chart_id]
            if updated_chart_titles == 0:
                raise HTTPException(status_code=404, detail="No matching chart_id found in chart_updates")

        spec["charts"] = charts
        update_dashboard_spec(settings, dashboard_id, spec=spec, title=dashboard_title)
        updated = get_dashboard_spec(settings, dashboard_id) or {"spec": spec, "title": dashboard_title}
        return {
            "dashboard_id": dashboard_id,
            "status": "updated",
            "dashboard_title": dashboard_title,
            "updated_dashboard_title": updated_dashboard_title,
            "updated_chart_titles": updated_chart_titles,
            "chart_count": len((updated.get("spec") or {}).get("charts") or []),
            "updated_at": updated.get("updated_at"),
        }

    if action != "delete_chart":
        raise HTTPException(status_code=400, detail="Unsupported action. Use delete_chart or update_titles")
    if not charts:
        raise HTTPException(status_code=400, detail="Dashboard has no charts to delete")

    removed_chart_id: str | None = None
    removed_count = 0
    updated_charts = charts

    if payload.chart_id:
        removed_chart_id = payload.chart_id
        updated_charts = []
        for item in charts:
            chart = item if isinstance(item, dict) else {}
            cid = chart.get("chart_id")
            if cid == payload.chart_id:
                removed_count += 1
                continue
            updated_charts.append(item)
    elif payload.chart_index is not None:
        if payload.chart_index < 0 or payload.chart_index >= len(charts):
            raise HTTPException(status_code=400, detail="chart_index out of range")
        removed = charts[payload.chart_index]
        if isinstance(removed, dict):
            removed_chart_id = removed.get("chart_id")
        updated_charts = [c for idx, c in enumerate(charts) if idx != payload.chart_index]
        removed_count = 1
    elif payload.chart_title:
        updated_charts = []
        for item in charts:
            chart = item if isinstance(item, dict) else {}
            title = (chart.get("title") or "").strip().lower()
            if title == payload.chart_title.strip().lower():
                removed_count += 1
                if removed_chart_id is None:
                    removed_chart_id = chart.get("chart_id")
                continue
            updated_charts.append(item)
    else:
        raise HTTPException(status_code=400, detail="Provide chart_id, chart_index, or chart_title")

    if removed_count == 0:
        raise HTTPException(status_code=404, detail="No matching chart found to delete")

    spec["charts"] = updated_charts
    if isinstance(spec.get("chart_plan"), list):
        updated_plan = []
        for item in spec.get("chart_plan") or []:
            chart = item if isinstance(item, dict) else {}
            if payload.chart_id and chart.get("chart_id") == payload.chart_id:
                continue
            updated_plan.append(item)
        spec["chart_plan"] = updated_plan
    if isinstance(spec.get("chart_candidates"), list) and payload.chart_id:
        updated_candidates = []
        for item in spec.get("chart_candidates") or []:
            chart = item if isinstance(item, dict) else {}
            if chart.get("chart_id") == payload.chart_id:
                continue
            updated_candidates.append(item)
        spec["chart_candidates"] = updated_candidates

    update_dashboard_spec(settings, dashboard_id, spec=spec, title=spec.get("title") or row.get("title"))
    updated = get_dashboard_spec(settings, dashboard_id) or {"spec": spec}
    updated_spec = updated.get("spec") or {}
    return {
        "dashboard_id": dashboard_id,
        "status": "updated",
        "dashboard_title": updated.get("title") or spec.get("title"),
        "removed_chart_id": removed_chart_id,
        "removed_count": removed_count,
        "chart_count": len(updated_spec.get("charts") or []),
        "updated_at": updated.get("updated_at"),
    }


@app.post(
    "/dashboards/{dashboard_id}/refresh",
    tags=["dashboards"],
    summary="Start dashboard refresh",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "refresh_request": {
                            "summary": "Start a dashboard refresh",
                            "value": {
                                "tenant_id": "VC_101",
                                "domain_id": "lpg_production_distribution",
                                "trigger_source": "user",
                                "requested_by": "analyst@company.com",
                                "include_insights": True,
                                "force_recompute": False,
                                "regenerate_titles": False,
                            },
                        },
                        "refresh_with_title_regeneration": {
                            "summary": "Refresh and regenerate dashboard/chart titles",
                            "value": {
                                "tenant_id": "VC_101",
                                "domain_id": "lpg_production_distribution",
                                "trigger_source": "user",
                                "requested_by": "analyst@company.com",
                                "include_insights": True,
                                "regenerate_titles": True
                            }
                        }
                    }
                }
            }
        },
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "queued": {
                                "summary": "Refresh queued",
                                "value": {
                                    "refresh_id": "dref_a1b2c3d4e5f6",
                                    "dashboard_id": "dash_123",
                                    "status": "queued",
                                    "job_id": "job_abc123",
                                },
                            }
                        }
                    }
                }
            }
        },
    },
)
def start_dashboard_refresh(dashboard_id: str, payload: dict | None = None) -> dict:
    payload = payload or {}
    dashboard = get_dashboard_spec(settings, dashboard_id)
    if not dashboard:
        raise HTTPException(status_code=404, detail="Dashboard not found")
    tenant_id = payload.get("tenant_id") or dashboard.get("tenant_id")
    domain_id = payload.get("domain_id") or dashboard.get("domain_id")
    trigger_source = payload.get("trigger_source") or "user"
    requested_by = payload.get("requested_by")
    refresh_id = create_dashboard_refresh_run(
        settings,
        dashboard_id=dashboard_id,
        tenant_id=tenant_id,
        domain_id=domain_id,
        trigger_source=trigger_source,
        requested_by=requested_by,
        request_payload=payload,
    )
    append_dashboard_refresh_event(
        settings,
        refresh_id=refresh_id,
        dashboard_id=dashboard_id,
        stage_name="queued",
        message="Dashboard refresh queued",
        artifacts={},
    )
    job = create_job(
        settings,
        tenant_id=tenant_id,
        domain_id=domain_id,
        job_type="dashboard_refresh",
        payload={"refresh_id": refresh_id, "dashboard_id": dashboard_id},
        idempotency_key=None,
    )
    return {
        "refresh_id": refresh_id,
        "dashboard_id": dashboard_id,
        "status": "queued",
        "job_id": job.get("job_id"),
    }


@app.get(
    "/dashboards/{dashboard_id}/refresh/{refresh_id}",
    tags=["dashboards"],
    summary="Get dashboard refresh status",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "running": {
                                "summary": "Refresh in progress",
                                "value": {
                                    "refresh_id": "dref_a1b2c3d4e5f6",
                                    "dashboard_id": "dash_123",
                                    "tenant_id": "VC_101",
                                    "domain_id": "lpg_production_distribution",
                                    "status": "running",
                                    "trigger_source": "user",
                                    "requested_by": "analyst@company.com",
                                    "request_payload": {"include_insights": True, "regenerate_titles": True},
                                    "error_message": None,
                                    "started_at": "2026-03-06T11:20:00Z",
                                    "completed_at": None,
                                    "created_at": "2026-03-06T11:19:59Z",
                                    "updated_at": "2026-03-06T11:20:02Z",
                                },
                            },
                            "completed": {
                                "summary": "Refresh completed",
                                "value": {
                                    "refresh_id": "dref_a1b2c3d4e5f6",
                                    "dashboard_id": "dash_123",
                                    "tenant_id": "VC_101",
                                    "domain_id": "lpg_production_distribution",
                                    "status": "completed",
                                    "trigger_source": "user",
                                    "requested_by": "analyst@company.com",
                                    "request_payload": {"include_insights": True, "regenerate_titles": True},
                                    "error_message": None,
                                    "started_at": "2026-03-06T11:20:00Z",
                                    "completed_at": "2026-03-06T11:20:07Z",
                                    "created_at": "2026-03-06T11:19:59Z",
                                    "updated_at": "2026-03-06T11:20:07Z",
                                },
                            },
                        }
                    }
                }
            }
        }
    },
)
def get_dashboard_refresh(dashboard_id: str, refresh_id: str) -> dict:
    row = get_dashboard_refresh_run(settings, dashboard_id, refresh_id)
    if not row:
        raise HTTPException(status_code=404, detail="Dashboard refresh run not found")
    return row


@app.get(
    "/dashboards/{dashboard_id}/refresh/{refresh_id}/events",
    tags=["dashboards"],
    summary="List dashboard refresh events",
    openapi_extra={
        "parameters": [
            {
                "name": "limit",
                "in": "query",
                "required": False,
                "schema": {"type": "integer", "default": 200, "minimum": 1, "maximum": 2000},
                "description": "Maximum number of refresh events to return.",
            },
            {
                "name": "cursor",
                "in": "query",
                "required": False,
                "schema": {"type": "string"},
                "description": "Opaque cursor for pagination. Use `paging.next_cursor` from previous response.",
            }
        ],
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "first_page": {
                                "summary": "First page",
                                "value": {
                                    "events": [
                                        {
                                            "event_id": "drevt_111",
                                            "refresh_id": "dref_a1b2c3d4e5f6",
                                            "dashboard_id": "dash_123",
                                            "stage_name": "running",
                                            "message": "Dashboard refresh started",
                                            "artifacts": {},
                                            "created_at": "2026-03-06T11:20:00Z",
                                        },
                                        {
                                            "event_id": "drevt_222",
                                            "refresh_id": "dref_a1b2c3d4e5f6",
                                            "dashboard_id": "dash_123",
                                            "stage_name": "titles_regenerated",
                                            "message": "Dashboard/chart titles regenerated: 6",
                                            "artifacts": {
                                                "regenerate_titles": True,
                                                "dashboard_title": "Lpg Plant Operations Total Production Overview",
                                                "chart_titles": [
                                                    "Total Production Trend Over Process Date",
                                                    "Total Production by Plant Name"
                                                ]
                                            },
                                            "created_at": "2026-03-06T11:20:02Z",
                                        },
                                        {
                                            "event_id": "drevt_223",
                                            "refresh_id": "dref_a1b2c3d4e5f6",
                                            "dashboard_id": "dash_123",
                                            "stage_name": "charts_refreshed",
                                            "message": "Dashboard charts refreshed: 6",
                                            "artifacts": {"chart_count": 6, "regenerate_titles": True, "regenerated_chart_titles": 6},
                                            "created_at": "2026-03-06T11:20:03Z",
                                        },
                                        {
                                            "event_id": "drevt_333",
                                            "refresh_id": "dref_a1b2c3d4e5f6",
                                            "dashboard_id": "dash_123",
                                            "stage_name": "completed",
                                            "message": "Dashboard refresh completed",
                                            "artifacts": {"chart_count": 6},
                                            "created_at": "2026-03-06T11:20:07Z",
                                        },
                                    ],
                                    "paging": {
                                        "limit": 2,
                                        "cursor": None,
                                        "returned": 2,
                                        "has_more": True,
                                        "next_cursor": "Mg=="
                                    },
                                },
                            },
                            "next_page": {
                                "summary": "Next page",
                                "value": {
                                    "events": [
                                        {
                                            "event_id": "drevt_223",
                                            "refresh_id": "dref_a1b2c3d4e5f6",
                                            "dashboard_id": "dash_123",
                                            "stage_name": "charts_refreshed",
                                            "message": "Dashboard charts refreshed: 6",
                                            "artifacts": {"chart_count": 6, "regenerate_titles": True},
                                            "created_at": "2026-03-06T11:20:03Z"
                                        },
                                        {
                                            "event_id": "drevt_333",
                                            "refresh_id": "dref_a1b2c3d4e5f6",
                                            "dashboard_id": "dash_123",
                                            "stage_name": "completed",
                                            "message": "Dashboard refresh completed",
                                            "artifacts": {"chart_count": 6},
                                            "created_at": "2026-03-06T11:20:07Z"
                                        }
                                    ],
                                    "paging": {
                                        "limit": 2,
                                        "cursor": "Mg==",
                                        "returned": 2,
                                        "has_more": False,
                                        "next_cursor": None
                                    },
                                },
                            }
                        }
                    }
                }
            }
        },
    },
)
def get_dashboard_refresh_events(
    dashboard_id: str,
    refresh_id: str,
    limit: int = 200,
    cursor: str | None = None,
) -> dict:
    row = get_dashboard_refresh_run(settings, dashboard_id, refresh_id)
    if not row:
        raise HTTPException(status_code=404, detail="Dashboard refresh run not found")
    bounded_limit = max(1, min(int(limit), 2000))
    if cursor:
        try:
            cursor_value = _decode_cursor(cursor)
            start_offset = max(0, int(cursor_value))
        except Exception as exc:
            raise HTTPException(status_code=400, detail="Invalid cursor") from exc
    else:
        start_offset = 0
    fetch_window = min(5000, start_offset + bounded_limit + 1)
    events_all = list_dashboard_refresh_events(
        settings,
        dashboard_id=dashboard_id,
        refresh_id=refresh_id,
        limit=fetch_window,
    )
    page = events_all[start_offset : start_offset + bounded_limit + 1]
    has_more = len(page) > bounded_limit
    events = page[:bounded_limit]
    next_cursor = _encode_cursor(str(start_offset + bounded_limit)) if has_more else None
    return {
        "events": events,
        "paging": {
            "limit": bounded_limit,
            "cursor": cursor,
            "returned": len(events),
            "has_more": has_more,
            "next_cursor": next_cursor,
        },
    }


@app.get(
    "/dashboards/{dashboard_id}/refresh/{refresh_id}/stream",
    tags=["dashboards"],
    summary="Stream dashboard refresh events",
    description="Server-sent events stream of dashboard refresh progress.",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "text/event-stream": {
                        "examples": {
                            "refresh_event": {
                                "summary": "Refresh stage event",
                                "value": "data: {\"stage_name\":\"charts_refreshed\",\"message\":\"Dashboard charts refreshed: 6/6\"}\n\n",
                            },
                            "titles_regenerated_event": {
                                "summary": "Titles regenerated stage",
                                "value": "data: {\"stage_name\":\"titles_regenerated\",\"message\":\"Dashboard/chart titles regenerated: 6\",\"artifacts\":{\"dashboard_title\":\"Lpg Plant Operations Total Production Overview\"}}\n\n",
                            },
                            "heartbeat": {
                                "summary": "SSE heartbeat",
                                "value": ": heartbeat\n\n",
                            },
                        }
                    }
                }
            }
        }
    },
)
def dashboard_refresh_stream(dashboard_id: str, refresh_id: str):
    from fastapi.responses import StreamingResponse

    row = get_dashboard_refresh_run(settings, dashboard_id, refresh_id)
    if not row:
        raise HTTPException(status_code=404, detail="Dashboard refresh run not found")

    def _event_stream():
        last_count = 0
        while True:
            events = list_dashboard_refresh_events(
                settings,
                dashboard_id=dashboard_id,
                refresh_id=refresh_id,
                limit=2000,
            )
            new_events = events[last_count:]
            for event in new_events:
                payload = json.dumps(event, default=str)
                yield f"data: {payload}\n\n"
            last_count = len(events)
            if not new_events:
                yield ": heartbeat\n\n"
            if events and (events[-1].get("stage_name") in {"completed", "partial_completed", "failed"}):
                break
            time.sleep(1.0)

    return StreamingResponse(_event_stream(), media_type="text/event-stream")


@app.get(
    "/dashboards/{dashboard_id}/insights",
    tags=["dashboards"],
    summary="Get dashboard insights",
    openapi_extra={
        "parameters": [
            {
                "name": "refresh_id",
                "in": "query",
                "required": False,
                "schema": {"type": "string"},
                "description": "Specific refresh id. If omitted, latest completed refresh is returned.",
            },
            {
                "name": "as_of",
                "in": "query",
                "required": False,
                "schema": {"type": "string", "format": "date-time"},
                "description": "Return latest refresh completed at or before this timestamp.",
            },
        ],
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "latest": {
                                "summary": "Latest dashboard insights",
                                "value": {
                                    "artifact_id": "dins_123abc456def",
                                    "refresh_id": "dref_a1b2c3d4e5f6",
                                    "dashboard_id": "dash_123",
                                    "summary_raw_text": "Dashboard refreshed with 6 charts.",
                                    "summary_html": "<section><h4>Dashboard Summary</h4><p>Dashboard refreshed with 6 charts.</p></section>",
                                    "inference_raw_text": "Composite inference generation will include chart-level deltas and trend direction.",
                                    "inference_html": "<section><h4>Dashboard Inference</h4><p>Composite inference generation will include chart-level deltas and trend direction.</p></section>",
                                    "evidence_json": {"chart_count": 6},
                                    "quality_json": {
                                        "confidence": 0.9,
                                        "warnings": [],
                                        "gate_passed": True,
                                        "kpi_mix": {
                                            "trend": 2,
                                            "breakdown_or_share": 2,
                                            "quality_or_rate": 1
                                        }
                                    },
                                    "created_at": "2026-03-06T11:20:07Z",
                                    "updated_at": "2026-03-06T11:20:07Z",
                                },
                            }
                        }
                    }
                }
            }
        },
    },
)
def get_dashboard_insights_endpoint(
    dashboard_id: str,
    refresh_id: str | None = None,
    as_of: str | None = None,
) -> dict:
    dashboard = get_dashboard_spec(settings, dashboard_id)
    if not dashboard:
        raise HTTPException(status_code=404, detail="Dashboard not found")
    row = get_dashboard_insights(
        settings,
        dashboard_id=dashboard_id,
        refresh_id=refresh_id,
        as_of=as_of,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Dashboard insights not found")
    return row


@app.get(
    "/entities/all",
    response_model=EntitiesAllResponse,
    tags=["explore"],
    summary="List entities and hierarchies for all connections",
    description="Return all tenant-scoped entities and hierarchies grouped by connection.",
)
def entities_all(tenant_id: str) -> EntitiesAllResponse:
    domain_id = _resolve_domain_id(tenant_id, None)
    entity_overrides, hierarchy_overrides = load_overrides_all(settings, tenant_id, domain_id)
    grouped: dict[tuple[str, str, str], dict] = {}
    for entity in entity_overrides:
        key = (entity.get("connection_id"), entity.get("database_name"), entity.get("schema_name"))
        grouped.setdefault(
            key,
            {
                "entities": [],
                "hierarchies": [],
            },
        )
        grouped[key]["entities"].append(
            {
                "entity_id": entity.get("entity_id"),
                "description": entity.get("description"),
                "join_key": entity.get("join_key"),
                "examples": entity.get("examples"),
                "lifecycle_status": entity.get("lifecycle_status"),
                "source_type": entity.get("source_type"),
                "source_run_id": entity.get("source_run_id"),
                "artifact_key": entity.get("artifact_key"),
                "version_no": entity.get("version_no"),
                "is_current": entity.get("is_current"),
            }
        )
    for hierarchy in hierarchy_overrides:
        key = (hierarchy.get("connection_id"), hierarchy.get("database_name"), hierarchy.get("schema_name"))
        grouped.setdefault(
            key,
            {
                "entities": [],
                "hierarchies": [],
            },
        )
        grouped[key]["hierarchies"].append(
            {
                "name": hierarchy.get("hierarchy_name"),
                "levels": hierarchy.get("levels", []),
                "description": hierarchy.get("description"),
                "context_id": hierarchy.get("context_id"),
                "hierarchy_group": hierarchy.get("hierarchy_group"),
                "lifecycle_status": hierarchy.get("lifecycle_status"),
                "source_type": hierarchy.get("source_type"),
                "source_run_id": hierarchy.get("source_run_id"),
                "artifact_key": hierarchy.get("artifact_key"),
                "version_no": hierarchy.get("version_no"),
                "is_current": hierarchy.get("is_current"),
            }
        )
    return EntitiesAllResponse(connections=list(grouped.values()))


@app.get(
    "/hierarchies",
    tags=["explore"],
    summary="List hierarchies (connection-scoped)",
    description="Return hierarchy overrides for the given tenant/domain/connection scope.",
)
def hierarchies(
    tenant_id: str,
    context_id: str | None = None,
    group_by_context: bool = False,
) -> dict:
    domain_id = _resolve_domain_id(tenant_id, None)
    connection_id, database, schema, _ = _resolve_scope_values(
        tenant_id,
        domain_id,
    )
    active_context_ids: list[str] | None = None
    if context_id:
        active_context_ids = [context_id]
    elif not group_by_context:
        active_context_ids = list_active_context_ids(
            settings,
            tenant_id,
            domain_id,
            connection_id,
            database,
            schema,
        )
    _, hierarchy_overrides = load_overrides(
        settings,
        tenant_id,
        domain_id,
        connection_id=connection_id,
        database_name=database,
        schema_name=schema,
        context_ids=active_context_ids or None,
    )
    sorted_rows = sorted(hierarchy_overrides, key=lambda item: item.get("hierarchy_name", ""))
    if group_by_context:
        grouped: dict[str, list[dict]] = {}
        for item in sorted_rows:
            ctx_id = item.get("context_id") or "unknown"
            grouped.setdefault(ctx_id, []).append(
                {
                    "name": item.get("hierarchy_name"),
                    "levels": item.get("levels", []),
                    "description": item.get("description"),
                    "context_id": item.get("context_id"),
                    "hierarchy_group": item.get("hierarchy_group"),
                    "lifecycle_status": item.get("lifecycle_status"),
                    "source_type": item.get("source_type"),
                    "source_run_id": item.get("source_run_id"),
                    "artifact_key": item.get("artifact_key"),
                    "version_no": item.get("version_no"),
                    "is_current": item.get("is_current"),
                }
            )
        return {"contexts": [{"context_id": key, "hierarchies": value} for key, value in grouped.items()]}

    hierarchies_payload = [
        {
            "name": item.get("hierarchy_name"),
            "levels": item.get("levels", []),
            "description": item.get("description"),
            "context_id": item.get("context_id"),
            "hierarchy_group": item.get("hierarchy_group"),
            "lifecycle_status": item.get("lifecycle_status"),
            "source_type": item.get("source_type"),
            "source_run_id": item.get("source_run_id"),
            "artifact_key": item.get("artifact_key"),
            "version_no": item.get("version_no"),
            "is_current": item.get("is_current"),
        }
        for item in sorted_rows
    ]
    return {"hierarchies": hierarchies_payload}


@app.patch(
    "/entities/{entity_id}",
    tags=["admin"],
    summary="Override an entity",
    description="Upsert a tenant-specific entity override (description/join_key/examples). Scope is resolved from tenant_id.",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "update_join_key": {
                            "summary": "Update join key",
                            "value": {
                                "description": "Organizational hierarchy for LPG operations",
                                "join_key": "sap_id",
                                "examples": ["sap_id", "plant_name", "region"],
                            },
                        }
                    }
                }
            }
        },
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {"ok": {"summary": "Override saved", "value": {"ok": True}}}
                    }
                }
            }
        },
    },
)
def update_entity(
    entity_id: str,
    tenant_id: str,
    payload: EntityOverrideRequest,
) -> dict:
    domain_id = _resolve_domain_id(tenant_id, None)
    connection_id, database, schema, _ = _resolve_scope_values(tenant_id, domain_id)
    upsert_entity_override(
        settings,
        tenant_id,
        domain_id,
        connection_id,
        database,
        schema,
        {
            "entity_id": entity_id,
            "description": payload.description,
            "join_key": payload.join_key,
            "examples": payload.examples,
            "lifecycle_status": payload.status,
        },
    )
    return {"ok": True}


@app.patch(
    "/hierarchies/{hierarchy_name}",
    tags=["admin"],
    summary="Override a hierarchy",
    description="Upsert a tenant-specific hierarchy override (levels/description). Scope is resolved from tenant_id.",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "override_levels": {
                            "summary": "Override hierarchy levels",
                            "value": {
                                "levels": ["zone", "region", "sales_area"],
                                "description": "Sales organization rollup",
                                "status": "certified",
                            },
                        }
                    }
                }
            }
        },
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {"ok": {"summary": "Override saved", "value": {"ok": True}}}
                    }
                }
            }
        },
    },
)
def update_hierarchy(
    hierarchy_name: str,
    tenant_id: str,
    payload: HierarchyOverrideRequest,
) -> dict:
    domain_id = _resolve_domain_id(tenant_id, None)
    connection_id, database, schema, _ = _resolve_scope_values(tenant_id, domain_id)
    upsert_hierarchy_override(
        settings,
        tenant_id,
        domain_id,
        connection_id,
        database,
        schema,
        {
            "hierarchy_name": hierarchy_name,
            "levels": payload.levels,
            "description": payload.description,
            "context_id": payload.context_id,
            "hierarchy_group": payload.hierarchy_group,
            "lifecycle_status": payload.status,
        },
    )
    return {"ok": True}


@app.patch(
    "/hierarchies",
    response_model=dict,
    tags=["context"],
    summary="Update hierarchy override (payload)",
    description="Update hierarchy override using JSON payload instead of path/query params. Scope is resolved from tenant_id.",
)
def update_hierarchy_payload(payload: HierarchyUpdateRequest) -> dict:
    domain_id = _resolve_domain_id(payload.tenant_id, None)
    connection_id, database, schema, _ = _resolve_scope_values(payload.tenant_id, domain_id)
    upsert_hierarchy_override(
        settings,
        payload.tenant_id,
        domain_id,
        connection_id,
        database,
        schema,
        {
            "hierarchy_name": payload.hierarchy_name,
            "levels": payload.levels,
            "description": payload.description,
            "context_id": payload.context_id,
            "hierarchy_group": payload.hierarchy_group,
            "lifecycle_status": payload.status,
        },
    )
    return {"ok": True}


@app.post(
    "/facts",
    response_model=dict,
    tags=["onboard"],
    summary="Create or upsert a fact",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "create_fact": {
                            "summary": "Create fact",
                            "value": {
                                "tenant_id": "VC_101",
                                "domain_id": "lpg_production_distribution",
                                "table_name": "fact_lpg_plant_operations",
                                "grain": "day",
                                "time_column": "process_date",
                                "measures": ["production_14_2kg", "production_19kg"],
                                "dimensions": ["sap_id", "region"],
                                "description": "Daily LPG production fact",
                                "status": "certified",
                            },
                        }
                    }
                }
            }
        },
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "created": {
                                "value": {"fact_id": "fact_ab12cd34", "status": "certified"}
                            }
                        }
                    }
                }
            }
        },
    },
)
def create_fact(payload: FactsUpsertRequest) -> dict:
    domain_id = _resolve_domain_id(payload.tenant_id, payload.domain_id)
    connection_id, database_name, schema_name, tables = _resolve_scope_values(
        payload.tenant_id,
        domain_id,
    )
    _validate_fact_payload(payload.model_dump())
    fact_id = upsert_fact(
        settings,
        {
            "fact_id": None,
            "tenant_id": payload.tenant_id,
            "domain_id": domain_id,
            "connection_id": connection_id,
            "database_name": database_name,
            "schema_name": schema_name,
            "table_name": payload.table_name,
            "grain": payload.grain,
            "time_column": payload.time_column,
            "measures": payload.measures,
            "dimensions": payload.dimensions,
            "description": payload.description,
            "lifecycle_status": payload.status or "live",
            "source_type": "user",
        },
    )
    return {"fact_id": fact_id, "status": payload.status or "live"}


@app.get(
    "/facts",
    response_model=FactsResponse,
    tags=["explore"],
    summary="List facts (connection-scoped)",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "facts": {
                                "summary": "Facts list",
                                "value": {
                                    "facts": [
                                        {
                                            "fact_id": "fact_ab12cd34",
                                            "table_name": "fact_lpg_plant_operations",
                                            "grain": "day",
                                            "time_column": "process_date",
                                            "measures": ["production_14_2kg", "production_19kg"],
                                            "dimensions": ["sap_id", "region"],
                                            "status": "certified",
                                        }
                                    ]
                                },
                            }
                        }
                    }
                }
            }
        }
    },
)
def get_facts(
    tenant_id: str,
) -> FactsResponse:
    domain_id = _resolve_domain_id(tenant_id, None)
    connection_id, database, schema, _ = _resolve_scope_values(
        tenant_id,
        domain_id,
    )
    facts = list_facts(settings, tenant_id, domain_id, connection_id, database, schema)
    facts_payload = []
    for item in facts:
        entry = {key: value for key, value in item.items() if key not in {"connection_id", "database_name", "schema_name"}}
        entry["status"] = entry.get("lifecycle_status")
        facts_payload.append(entry)
    return FactsResponse(facts=facts_payload)


@app.get(
    "/facts/all",
    response_model=FactsAllResponse,
    tags=["explore"],
    summary="List facts for all connections",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "facts_all": {
                                "summary": "Facts by connection",
                                "value": {
                                    "connections": [
                                        {
                                            "facts": [
                                                {"fact_id": "fact_ab12cd34", "table_name": "fact_lpg_plant_operations"}
                                            ]
                                        }
                                    ]
                                },
                            }
                        }
                    }
                }
            }
        }
    },
)
def get_facts_all(tenant_id: str) -> FactsAllResponse:
    domain_id = _resolve_domain_id(tenant_id, None)
    rows = list_facts_all(settings, tenant_id, domain_id)
    grouped: dict[tuple[str, str, str], dict] = {}
    for row in rows:
        key = (row.get("connection_id"), row.get("database_name"), row.get("schema_name"))
        grouped.setdefault(
            key,
            {
                "facts": [],
            },
        )
        entry = {key: value for key, value in row.items() if key not in {"connection_id", "database_name", "schema_name"}}
        entry["status"] = entry.get("lifecycle_status")
        grouped[key]["facts"].append(entry)
    return FactsAllResponse(connections=list(grouped.values()))


@app.patch(
    "/facts/{fact_id}",
    tags=["onboard"],
    summary="Update a fact",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "promote_fact": {
                            "summary": "Promote to certified",
                            "value": {"status": "certified"},
                        },
                        "update_measures": {
                            "summary": "Update measures",
                            "value": {"measures": ["production_mt", "total_production"]},
                        },
                    }
                }
            }
        }
    },
)
def patch_fact(fact_id: str, payload: FactsPatchRequest) -> dict:
    updates = {key: value for key, value in payload.model_dump().items() if value is not None}
    if updates.get("status") is not None and updates.get("lifecycle_status") is None:
        updates["lifecycle_status"] = updates.get("status")
    updates.pop("status", None)
    if not updates:
        return {"ok": True}
    rows = run_query(
        settings,
        """
        SELECT table_name, measures
          FROM public.quantyx_facts_registry
         WHERE (fact_id = %s OR artifact_key = %s)
           AND COALESCE(is_current, true) = true
         LIMIT 1
        """,
        [fact_id, fact_id],
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Fact not found")
    merged = dict(rows[0])
    merged.update(updates)
    _validate_fact_payload(merged)
    update_fact(settings, fact_id, updates)
    return {"ok": True}


@app.delete(
    "/facts/{fact_id}",
    tags=["onboard"],
    summary="Delete a fact",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {"deleted": {"value": {"ok": True}}}
                    }
                }
            }
        }
    },
)
def remove_fact(fact_id: str) -> dict:
    delete_fact(settings, fact_id)
    return {"ok": True}


@app.post(
    "/dimensions",
    response_model=dict,
    tags=["onboard"],
    summary="Create or upsert a dimension",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "create_dimension": {
                            "summary": "Create dimension",
                            "value": {
                                "tenant_id": "VC_101",
                                "domain_id": "lpg_production_distribution",
                                "name": "dim_plant",
                                "keys": ["sap_id"],
                                "attributes": ["plant_name", "region"],
                                "description": "Plant dimension",
                                "status": "certified",
                            },
                        }
                    }
                }
            }
        },
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {"created": {"value": {"dimension_id": "dim_ab12cd34", "status": "certified"}}}
                    }
                }
            }
        },
    },
)
def create_dimension(payload: DimensionsUpsertRequest) -> dict:
    domain_id = _resolve_domain_id(payload.tenant_id, payload.domain_id)
    connection_id, database_name, schema_name, tables = _resolve_scope_values(
        payload.tenant_id,
        domain_id,
    )
    _validate_dimension_payload(payload.model_dump())
    dimension_id = upsert_dimension(
        settings,
        {
            "dimension_id": None,
            "tenant_id": payload.tenant_id,
            "domain_id": domain_id,
            "connection_id": connection_id,
            "database_name": database_name,
            "schema_name": schema_name,
            "name": payload.name,
            "keys": payload.keys,
            "attributes": payload.attributes,
            "description": payload.description,
            "lifecycle_status": payload.status or "live",
            "source_type": "user",
        },
    )
    return {"dimension_id": dimension_id, "status": payload.status or "live"}


@app.get(
    "/dimensions",
    response_model=DimensionsResponse,
    tags=["explore"],
    summary="List dimensions (connection-scoped)",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "dimensions": {
                                "summary": "Dimensions list",
                                "value": {
                                    "dimensions": [
                                        {
                                            "dimension_id": "dim_ab12cd34",
                                            "name": "dim_plant",
                                            "keys": ["sap_id"],
                                            "attributes": ["plant_name", "region"],
                                            "status": "certified",
                                        }
                                    ]
                                },
                            }
                        }
                    }
                }
            }
        }
    },
)
def get_dimensions(
    tenant_id: str,
) -> DimensionsResponse:
    domain_id = _resolve_domain_id(tenant_id, None)
    connection_id, database, schema, _ = _resolve_scope_values(
        tenant_id,
        domain_id,
    )
    dimensions = list_dimensions(settings, tenant_id, domain_id, connection_id, database, schema)
    dimensions_payload = []
    for item in dimensions:
        entry = {key: value for key, value in item.items() if key not in {"connection_id", "database_name", "schema_name"}}
        entry["status"] = entry.get("lifecycle_status")
        dimensions_payload.append(entry)
    return DimensionsResponse(dimensions=dimensions_payload)


@app.get(
    "/dimensions/all",
    response_model=DimensionsAllResponse,
    tags=["explore"],
    summary="List dimensions for all connections",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "dimensions_all": {
                                "summary": "Dimensions by connection",
                                "value": {
                                    "connections": [
                                        {
                                            "dimensions": [
                                                {"dimension_id": "dim_ab12cd34", "name": "dim_plant"}
                                            ]
                                        }
                                    ]
                                },
                            }
                        }
                    }
                }
            }
        }
    },
)
def get_dimensions_all(tenant_id: str) -> DimensionsAllResponse:
    domain_id = _resolve_domain_id(tenant_id, None)
    rows = list_dimensions_all(settings, tenant_id, domain_id)
    grouped: dict[tuple[str, str, str], dict] = {}
    for row in rows:
        key = (row.get("connection_id"), row.get("database_name"), row.get("schema_name"))
        grouped.setdefault(
            key,
            {
                "dimensions": [],
            },
        )
        entry = {key: value for key, value in row.items() if key not in {"connection_id", "database_name", "schema_name"}}
        entry["status"] = entry.get("lifecycle_status")
        grouped[key]["dimensions"].append(entry)
    return DimensionsAllResponse(connections=list(grouped.values()))


@app.patch(
    "/dimensions/{dimension_id}",
    tags=["onboard"],
    summary="Update a dimension",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "promote_dimension": {
                            "summary": "Promote to certified",
                            "value": {"status": "certified"},
                        },
                        "update_keys": {
                            "summary": "Update keys/attributes",
                            "value": {"keys": ["sap_id"], "attributes": ["plant_name", "region"]},
                        },
                    }
                }
            }
        }
    },
)
def patch_dimension(dimension_id: str, payload: DimensionsPatchRequest) -> dict:
    updates = {key: value for key, value in payload.model_dump().items() if value is not None}
    if updates.get("status") is not None and updates.get("lifecycle_status") is None:
        updates["lifecycle_status"] = updates.get("status")
    updates.pop("status", None)
    if not updates:
        return {"ok": True}
    rows = run_query(
        settings,
        """
        SELECT name, keys
          FROM public.quantyx_dimensions_registry
         WHERE (dimension_id = %s OR artifact_key = %s)
           AND COALESCE(is_current, true) = true
         LIMIT 1
        """,
        [dimension_id, dimension_id],
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Dimension not found")
    merged = dict(rows[0])
    merged.update(updates)
    _validate_dimension_payload(merged)
    update_dimension(settings, dimension_id, updates)
    return {"ok": True}


@app.delete(
    "/dimensions/{dimension_id}",
    tags=["onboard"],
    summary="Delete a dimension",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {"deleted": {"value": {"ok": True}}}
                    }
                }
            }
        }
    },
)
def remove_dimension(dimension_id: str) -> dict:
    delete_dimension(settings, dimension_id)
    return {"ok": True}


@app.post(
    "/review",
    response_model=ReviewResponse,
    tags=["onboard"],
    summary="Create a review event",
)
def create_review(payload: ReviewCreateRequest) -> ReviewResponse:
    domain_id = _resolve_domain_id(payload.tenant_id, payload.domain_id)
    connection_id, database_name, schema_name, tables = _resolve_scope_values(
        payload.tenant_id,
        domain_id,
    )
    review_id = create_review_event(
        settings,
        tenant_id=payload.tenant_id,
        domain_id=domain_id,
        connection_id=connection_id,
        database_name=database_name,
        schema_name=schema_name,
        artifact_type=payload.artifact_type,
        artifact_id=payload.artifact_id,
        status=payload.status,
        notes=payload.notes,
        payload=payload.payload,
    )
    return ReviewResponse(review_id=review_id, status=payload.status)


@app.post(
    "/glossary/certify",
    tags=["certify"],
    summary="Certify glossary terms",
    description="Mark glossary terms as certified for a tenant (and optional domain).",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "certify_glossary": {
                            "summary": "Certify glossary",
                            "value": {"tenant_id": "VC_101"},
                        },
                        "certify_term": {
                            "summary": "Certify a single term",
                            "value": {"tenant_id": "VC_101", "term_id": "gls_123"},
                        },
                        "certify_glossary_domain": {
                            "summary": "Certify glossary for domain",
                            "value": {
                                "tenant_id": "VC_101",
                                "domain_id": "lpg_production_distribution",
                            },
                        },
                    }
                }
            }
        }
    },
)
def certify_glossary(payload: dict) -> dict:
    tenant_id = payload.get("tenant_id")
    domain_id = payload.get("domain_id")
    term_id = payload.get("term_id")
    if not tenant_id:
        raise HTTPException(status_code=400, detail="tenant_id is required")
    params = [tenant_id]
    sql = """
        UPDATE public.quantyx_glossary_terms
           SET lifecycle_status = 'certified',
               updated_at = now()
         WHERE tenant_id = %s
    """
    if domain_id:
        sql += " AND domain_id = %s"
        params.append(domain_id)
    if term_id:
        sql += " AND term_id = %s"
        params.append(term_id)
    execute_non_query(settings, sql, params)
    return {"ok": True}


@app.post(
    "/entities/certify",
    tags=["certify"],
    summary="Certify entities",
    description="Mark entity overrides as certified for a tenant/scope.",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "certify_entity": {
                            "summary": "Certify a single entity",
                            "value": {
                                "tenant_id": "VC_101",
                                "entity_id": "plant",
                            },
                        },
                        "certify_all": {
                            "summary": "Certify all entities in scope",
                            "value": {
                                "tenant_id": "VC_101",
                            },
                        },
                    }
                }
            }
        }
    },
)
def certify_entities(payload: dict) -> dict:
    tenant_id = payload.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=400, detail="tenant_id is required")
    domain_id = _resolve_domain_id(tenant_id, payload.get("domain_id"))
    connection_id, database, schema, _ = _resolve_scope_values(tenant_id, domain_id)
    entity_id = payload.get("entity_id")
    params = [tenant_id, domain_id, connection_id, database, schema]
    sql = """
        UPDATE public.quantyx_entity_overrides
           SET lifecycle_status = 'certified',
               updated_at = now()
         WHERE tenant_id = %s
           AND domain_id = %s
           AND connection_id = %s
           AND database_name = %s
           AND schema_name = %s
    """
    if entity_id:
        sql += " AND entity_id = %s"
        params.append(entity_id)
    execute_non_query(settings, sql, params)
    return {"ok": True}


@app.post(
    "/hierarchies/certify",
    tags=["certify"],
    summary="Certify hierarchies",
    description="Mark hierarchy overrides as certified for a tenant/scope.",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "certify_hierarchy": {
                            "summary": "Certify a single hierarchy",
                            "value": {
                                "tenant_id": "VC_101",
                                "hierarchy_name": "sales_org",
                            },
                        },
                        "certify_all": {
                            "summary": "Certify all hierarchies in scope",
                            "value": {
                                "tenant_id": "VC_101",
                            },
                        },
                    }
                }
            }
        }
    },
)
def certify_hierarchies(payload: dict) -> dict:
    tenant_id = payload.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=400, detail="tenant_id is required")
    domain_id = _resolve_domain_id(tenant_id, payload.get("domain_id"))
    connection_id, database, schema, _ = _resolve_scope_values(tenant_id, domain_id)
    hierarchy_name = payload.get("hierarchy_name")
    params = [tenant_id, domain_id, connection_id, database, schema]
    sql = """
        UPDATE public.quantyx_hierarchy_overrides
           SET lifecycle_status = 'certified',
               updated_at = now()
         WHERE tenant_id = %s
           AND domain_id = %s
           AND connection_id = %s
           AND database_name = %s
           AND schema_name = %s
    """
    if hierarchy_name:
        sql += " AND hierarchy_name = %s"
        params.append(hierarchy_name)
    execute_non_query(settings, sql, params)
    return {"ok": True}


@app.post(
    "/metrics/certify",
    tags=["certify"],
    summary="Certify metrics",
    description="Mark metrics as certified for a tenant/scope.",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "certify_metric": {
                            "summary": "Certify a single metric",
                            "value": {"tenant_id": "VC_101", "metric_id": "lpg_production_distribution__production_mt"},
                        },
                        "certify_all": {
                            "summary": "Certify all metrics in scope",
                            "value": {"tenant_id": "VC_101"},
                        },
                    }
                }
            }
        }
    },
)
def certify_metrics(payload: dict) -> dict:
    tenant_id = payload.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=400, detail="tenant_id is required")
    domain_id = _resolve_domain_id(tenant_id, payload.get("domain_id"))
    connection_id, database, schema, _ = _resolve_scope_values(tenant_id, domain_id)
    metric_id = payload.get("metric_id")
    params = [tenant_id, domain_id, connection_id, database, schema]
    sql = """
        UPDATE public.quantyx_metrics_registry
           SET lifecycle_status = 'certified',
               updated_at = now()
         WHERE tenant_id = %s
           AND domain_id = %s
           AND connection_id = %s
           AND database_name = %s
           AND schema_name = %s
    """
    if metric_id:
        sql += " AND (metric_id = %s OR artifact_key = %s)"
        params.extend([metric_id, metric_id])
    execute_non_query(settings, sql, params)
    return {"ok": True}


@app.post(
    "/facts/certify",
    tags=["certify"],
    summary="Certify facts",
    description="Mark facts as certified for a tenant/scope.",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "certify_fact": {
                            "summary": "Certify a single fact",
                            "value": {"tenant_id": "VC_101", "fact_id": "fact_abc123"},
                        },
                        "certify_all": {
                            "summary": "Certify all facts in scope",
                            "value": {"tenant_id": "VC_101"},
                        },
                    }
                }
            }
        }
    },
)
def certify_facts(payload: dict) -> dict:
    tenant_id = payload.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=400, detail="tenant_id is required")
    domain_id = _resolve_domain_id(tenant_id, payload.get("domain_id"))
    connection_id, database, schema, _ = _resolve_scope_values(tenant_id, domain_id)
    fact_id = payload.get("fact_id")
    params = [tenant_id, domain_id, connection_id, database, schema]
    sql = """
        UPDATE public.quantyx_facts_registry
           SET lifecycle_status = 'certified',
               updated_at = now()
         WHERE tenant_id = %s
           AND domain_id = %s
           AND connection_id = %s
           AND database_name = %s
           AND schema_name = %s
    """
    if fact_id:
        sql += " AND (fact_id = %s OR artifact_key = %s)"
        params.extend([fact_id, fact_id])
    execute_non_query(settings, sql, params)
    return {"ok": True}


@app.post(
    "/dimensions/certify",
    tags=["certify"],
    summary="Certify dimensions",
    description="Mark dimensions as certified for a tenant/scope.",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "certify_dimension": {
                            "summary": "Certify a single dimension",
                            "value": {"tenant_id": "VC_101", "dimension_id": "dim_ab12cd34"},
                        },
                        "certify_all": {
                            "summary": "Certify all dimensions in scope",
                            "value": {"tenant_id": "VC_101"},
                        },
                    }
                }
            }
        }
    },
)
def certify_dimensions(payload: dict) -> dict:
    tenant_id = payload.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=400, detail="tenant_id is required")
    domain_id = _resolve_domain_id(tenant_id, payload.get("domain_id"))
    connection_id, database, schema, _ = _resolve_scope_values(tenant_id, domain_id)
    dimension_id = payload.get("dimension_id")
    params = [tenant_id, domain_id, connection_id, database, schema]
    sql = """
        UPDATE public.quantyx_dimensions_registry
           SET lifecycle_status = 'certified',
               updated_at = now()
         WHERE tenant_id = %s
           AND domain_id = %s
           AND connection_id = %s
           AND database_name = %s
           AND schema_name = %s
    """
    if dimension_id:
        sql += " AND (dimension_id = %s OR artifact_key = %s)"
        params.extend([dimension_id, dimension_id])
    execute_non_query(settings, sql, params)
    return {"ok": True}


@app.get(
    "/review",
    response_model=ReviewListResponse,
    tags=["onboard"],
    summary="List review events",
)
def list_review(
    tenant_id: str,
    artifact_type: str | None = None,
) -> ReviewListResponse:
    domain_id = _resolve_domain_id(tenant_id, None)
    connection_id, database, schema, _ = _resolve_scope_values(
        tenant_id,
        domain_id,
    )
    reviews = list_review_events(
        settings,
        tenant_id,
        domain_id,
        connection_id,
        database,
        schema,
        artifact_type=artifact_type,
    )
    return ReviewListResponse(reviews=reviews)


@app.patch(
    "/review/{review_id}",
    tags=["onboard"],
    summary="Update a review event",
)
def patch_review(review_id: str, payload: ReviewPatchRequest) -> dict:
    update_review_event(settings, review_id, payload.status, payload.notes)
    return {"ok": True}


@app.get(
    "/review/summary",
    response_model=ReviewSummaryResponse,
    tags=["onboard"],
    summary="Review summary",
    description="Return scan results and onboarding artifacts for review.",
)
def review_summary(
    tenant_id: str,
) -> ReviewSummaryResponse:
    domain_id = _resolve_domain_id(tenant_id, None)
    connection_id, database, schema, _ = _resolve_scope_values(
        tenant_id,
        domain_id,
    )
    active_context_ids = list_active_context_ids(
        settings,
        tenant_id,
        domain_id,
        connection_id,
        database,
        schema,
    )
    scoped_scan = load_latest_scan_for_scope(
        settings, tenant_id, domain_id, connection_id, database, schema
    )
    scan_summary = None
    if scoped_scan is not None:
        scan_summary = {
            "tables": len(scoped_scan.get("tables", [])),
            "schema_payload": scoped_scan,
        }
    entity_overrides, hierarchy_overrides = load_overrides(
        settings,
        tenant_id,
        domain_id,
        connection_id=connection_id,
        database_name=database,
        schema_name=schema,
        context_ids=active_context_ids or None,
    )
    facts = list_facts(settings, tenant_id, domain_id, connection_id, database, schema)
    dimensions = list_dimensions(settings, tenant_id, domain_id, connection_id, database, schema)
    metrics_rows = fetch_registry_metrics(
        settings,
        tenant_id=tenant_id,
        domain_id=domain_id,
        connection_id=connection_id,
        database_name=database,
        schema_name=schema,
        include_all_statuses=True,
    )
    glossary_terms = fetch_glossary_terms(settings, tenant_id, domain_id)
    review_events = list_review_events(
        settings, tenant_id, domain_id, connection_id, database, schema
    )
    review_map: dict[tuple[str, str], dict] = {}
    for event in review_events:
        key = (event.get("artifact_type"), event.get("artifact_id"))
        if key not in review_map:
            review_map[key] = event

    entities_payload = []
    for entity in entity_overrides:
        entry = dict(entity)
        status = review_map.get(("entities", entity.get("entity_id")))
        if status:
            entry["status"] = status.get("status")
            entry["review_id"] = status.get("review_id")
        entities_payload.append(entry)

    hierarchies_payload = []
    for hierarchy in hierarchy_overrides:
        entry = {
            "name": hierarchy.get("hierarchy_name"),
            "levels": hierarchy.get("levels", []),
            "description": hierarchy.get("description"),
            "context_id": hierarchy.get("context_id"),
            "hierarchy_group": hierarchy.get("hierarchy_group"),
            "lifecycle_status": hierarchy.get("lifecycle_status"),
            "source_type": hierarchy.get("source_type"),
            "source_run_id": hierarchy.get("source_run_id"),
            "artifact_key": hierarchy.get("artifact_key"),
            "version_no": hierarchy.get("version_no"),
            "is_current": hierarchy.get("is_current"),
        }
        status = review_map.get(("hierarchies", hierarchy.get("artifact_key") or hierarchy.get("hierarchy_name")))
        if status:
            entry["status"] = status.get("status")
            entry["review_id"] = status.get("review_id")
        hierarchies_payload.append(entry)

    facts_payload = []
    for fact in facts:
        entry = dict(fact)
        status = review_map.get(("facts", fact.get("fact_id")))
        if status:
            entry["review_status"] = status.get("status")
            entry["review_id"] = status.get("review_id")
        facts_payload.append(entry)

    dims_payload = []
    for dim in dimensions:
        entry = dict(dim)
        status = review_map.get(("dimensions", dim.get("dimension_id")))
        if status:
            entry["review_status"] = status.get("status")
            entry["review_id"] = status.get("review_id")
        dims_payload.append(entry)

    metrics_payload = []
    for metric in metrics_rows:
        entry = dict(metric)
        status = review_map.get(("metrics", metric.get("metric_id")))
        if status:
            entry["review_status"] = status.get("status")
            entry["review_id"] = status.get("review_id")
        metrics_payload.append(entry)

    return ReviewSummaryResponse(
        scan=scan_summary,
        glossary=glossary_terms or [],
        entities=entities_payload,
        hierarchies=hierarchies_payload,
        facts=facts_payload,
        dimensions=dims_payload,
        metrics=metrics_payload,
        ontology={
            "entities": entities_payload,
            "hierarchies": hierarchies_payload,
        },
    )

@app.get(
    "/schema",
    response_model=SchemaResponse,
    tags=["explore"],
    summary="List dbt models",
    description="Return models and columns from dbt manifest.json, scoped by tenant scope.",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "models": {
                                "summary": "Model list",
                                "value": {
                                    "models": [
                                        {
                                            "name": "fact_lpg_plant_operations",
                                            "schema": "public",
                                            "columns": ["process_date", "production_14_2kg", "production_19kg"],
                                        }
                                    ],
                                    "limit": 200,
                                    "cursor": None,
                                    "next_cursor": "ZmFjdF9scGdfcGxhbnRfb3BlcmF0aW9ucw==",
                                },
                            }
                        }
                    }
                }
            }
        }
    },
)
def schema(
    tenant_id: str,
    domain_id: str | None = None,
    limit: int = 200,
    cursor: str | None = None,
) -> SchemaResponse:
    resolved_domain = _resolve_domain_id(tenant_id, domain_id)
    _, database, schema, _ = _resolve_scope_values(
        tenant_id,
        resolved_domain,
    )
    models = load_manifest_models(settings)
    if database:
        models = [model for model in models if model.get("database") == database]
    if schema:
        models = [model for model in models if model.get("schema") == schema]
    page, next_cursor = _paginate_list(models, cursor, limit, key_fn=lambda item: item["name"])
    return SchemaResponse(models=page, limit=limit, cursor=cursor, next_cursor=next_cursor)


@app.post(
    "/onboard/scan",
    response_model=OnboardScanResponse,
    tags=["onboard"],
    summary="Scan source schema",
    description="Inspect tables and columns in the target schema.",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "scan_public": {
                            "summary": "Scan public schema",
                            "value": {
                                "tenant_id": "VC_101",
                                "domain_id": "lpg_production_distribution",
                            },
                        }
                    }
                }
            }
        },
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "scan_result": {
                                "summary": "Scan results",
                                "value": {
                                    "tables": [
                                        {
                                            "table": "fact_lpg_plant_operations",
                                            "columns": [
                                                {
                                                    "name": "process_date",
                                                    "data_type": "date",
                                                    "null_frac": 0.0,
                                                },
                                                {
                                                    "name": "production_19kg",
                                                    "data_type": "numeric",
                                                    "null_frac": 0.0,
                                                },
                                            ],
                                        }
                                    ]
                                },
                            }
                        }
                    }
                }
            }
        },
    },
)
def onboard_scan(request: OnboardScanRequest) -> OnboardScanResponse:
    tables = scan_schema(settings, settings.db_schema)
    return OnboardScanResponse(tables=tables)


@app.post(
    "/onboard/scan-connection/async",
    response_model=JobCreateResponse,
    status_code=202,
    tags=["onboard"],
    summary="Scan provided connections (async)",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "scan_connections_async": {
                            "summary": "Scan multiple connections (async)",
                            "value": {
                                "tenant_id": "VC_101",
                                "domain_id": "lpg_production_distribution",
                                "connections": [
                                    {
                                        "connection_id": "conn_prod",
                                        "db_type": "postgres",
                                        "host": "db.company.com",
                                        "port": 5432,
                                        "user": "readonly_user",
                                        "password": "******",
                                        "sample_rows": 100,
                                        "databases": [
                                            {
                                                "name": "prod_warehouse",
                                                "schemas": [
                                                    {
                                                        "name": "public",
                                                        "tables": ["lpg_plant_operations"],
                                                        "limit": 20,
                                                        "cursor": None,
                                                    }
                                                ],
                                            }
                                        ],
                                    }
                                ]
                            },
                        }
                    }
                }
            }
        },
        "responses": {
            "202": {
                "content": {
                    "application/json": {
                        "examples": {
                            "queued": {
                                "value": {
                                    "job_id": "job_123",
                                    "status": "queued",
                                }
                            }
                        }
                    }
                }
            }
        },
    },
)
def onboard_scan_connection_async(
    request: OnboardScanMultiConnectionRequest,
    generate_dbt: bool = True,
) -> JobCreateResponse:
    tenant_id = request.tenant_id
    if not tenant_id:
        raise HTTPException(status_code=400, detail="tenant_id is required")
    domain_id = _resolve_domain_id(tenant_id, request.domain_id)
    payload = request.model_dump()
    payload["generate_dbt"] = generate_dbt
    job = create_job(
        settings,
        tenant_id=tenant_id,
        domain_id=domain_id,
        job_type="scan_connection",
        payload=payload,
    )
    return JobCreateResponse(job_id=job["job_id"], status=job["status"])


def _run_scan_connection(
    request: OnboardScanMultiConnectionRequest,
    generate_dbt: bool,
    progress_cb: Callable[[int, str], None] | None = None,
) -> OnboardScanConnectionResponse:
    tenant_id = request.tenant_id
    if not tenant_id:
        raise HTTPException(status_code=400, detail="tenant_id is required")
    domain_id = _resolve_domain_id(tenant_id, request.domain_id)
    total_schemas = sum(
        len(database.schemas)
        for connection in request.connections
        for database in connection.databases
    )
    scanned_schemas = 0
    if progress_cb:
        progress_cb(0, "scan.start")
    _log_scan_step(
        "start",
        {
            "tenant_id": tenant_id,
            "domain_id": domain_id,
            "connections": len(request.connections),
            "generate_dbt": generate_dbt,
        },
    )
    connections_payload = []
    payload_by_connection: dict[str, list[dict]] = {}
    for connection in request.connections:
        _log_scan_step(
            "connection.begin",
            {"connection_id": connection.connection_id, "db_type": connection.db_type},
        )
        databases_payload = []
        scopes: list[tuple[str, str]] = []
        for database in connection.databases:
            _log_scan_step(
                "database.begin",
                {"connection_id": connection.connection_id, "database": database.name},
            )
            schemas_payload = []
            for schema in database.schemas:
                _log_scan_step(
                    "schema.begin",
                    {
                        "connection_id": connection.connection_id,
                        "database": database.name,
                        "schema": schema.name,
                        "tables": len(schema.tables or []),
                    },
                )
                cursor_value = _decode_cursor(schema.cursor) if schema.cursor else None
                tables, next_cursor = scan_connection(
                    db_type=connection.db_type,
                    host=connection.host,
                    port=connection.port,
                    database=database.name,
                    user=connection.user,
                    password=decrypt_password(connection.password),
                    schema=schema.name,
                    tables=schema.tables,
                    limit=schema.limit,
                    sample_rows=connection.sample_rows,
                    cursor_value=cursor_value,
                )
                _log_scan_step(
                    "schema.scanned",
                    {
                        "connection_id": connection.connection_id,
                        "database": database.name,
                        "schema": schema.name,
                        "tables_scanned": len(tables),
                    },
                )
                schemas_payload.append(
                    {
                        "name": schema.name,
                        "tables": tables,
                        "limit": schema.limit,
                        "cursor": schema.cursor,
                        "next_cursor": _encode_cursor(next_cursor) if next_cursor else None,
                    }
                )
                scopes.append((database.name, schema.name))
                scanned_schemas += 1
                if progress_cb and total_schemas > 0:
                    pct = int((scanned_schemas / total_schemas) * 80)
                    progress_cb(min(pct, 80), f"scan.schema:{schema.name}")
            databases_payload.append({"name": database.name, "schemas": schemas_payload})
            _log_scan_step(
                "database.complete",
                {"connection_id": connection.connection_id, "database": database.name},
            )
        connection_payload = {"connection_id": connection.connection_id, "databases": databases_payload}
        connections_payload.append(connection_payload)
        payload_by_connection[connection.connection_id] = databases_payload
        register_connection(settings, connection.connection_id)
        if scopes:
            register_connection_scopes(settings, connection.connection_id, scopes)
        _log_scan_step(
            "connection.complete",
            {"connection_id": connection.connection_id, "schemas": len(scopes)},
        )

    persist_schema_scan(
        settings,
        request.model_dump(),
        {"connections": connections_payload},
        tenant_id=tenant_id,
        domain_id=domain_id,
    )
    _log_scan_step("persisted.scan", {"tenant_id": tenant_id, "domain_id": domain_id})
    if progress_cb:
        progress_cb(85, "scan.persisted")

    if generate_dbt:
        try:
            for connection in request.connections:
                _log_scan_step(
                    "dbt.begin",
                    {"connection_id": connection.connection_id, "tenant_id": tenant_id},
                )
                dbt_project_path = ensure_tenant_dbt_project(
                    tenant_id,
                    template_dir=settings.dbt_project_template,
                )
                _log_scan_step(
                    "dbt.project.ready",
                    {"connection_id": connection.connection_id, "path": dbt_project_path},
                )
                databases_payload = payload_by_connection.get(connection.connection_id, [])
                for database_payload in databases_payload:
                    for schema_payload in database_payload.get("schemas", []):
                        schema_tables = schema_payload.get("tables", [])
                        if not schema_tables:
                            continue
                        _log_scan_step(
                            "dbt.scaffold.begin",
                            {
                                "connection_id": connection.connection_id,
                                "database": database_payload.get("name", ""),
                                "schema": schema_payload.get("name", ""),
                                "tables": len(schema_tables),
                            },
                        )
                        payload = build_scaffold_payload(
                            settings,
                            database=database_payload.get("name", ""),
                            schema=schema_payload.get("name", ""),
                            tables=schema_tables,
                            context_text=None,
                            use_llm=True,
                        )
                        payload["connection"] = {
                            "host": connection.host,
                            "port": connection.port,
                            "user": connection.user,
                            "password": decrypt_password(connection.password),
                        }
                        write_scaffold_files(dbt_project_path, payload)
                        persist_scaffold(
                            settings,
                            tenant_id=tenant_id,
                            domain_id=domain_id,
                            connection_id=connection.connection_id,
                            database=database_payload.get("name", ""),
                            schema=schema_payload.get("name", ""),
                            tables=[t.get("table") for t in schema_tables if t.get("table")],
                            context_id=None,
                            payload=payload,
                        )
                        _log_scan_step(
                            "dbt.scaffold.complete",
                            {
                                "connection_id": connection.connection_id,
                                "database": database_payload.get("name", ""),
                                "schema": schema_payload.get("name", ""),
                            },
                        )
                resolved = resolve_dbt_config(
                    settings,
                    tenant_id=tenant_id,
                    domain_id=domain_id,
                    connection_id=connection.connection_id,
                )
                resolved["dbt_project_path"] = dbt_project_path
                if resolved.get("config_id") is None:
                    upsert_dbt_config(
                        settings,
                        tenant_id=tenant_id,
                        domain_id=domain_id,
                        connection_id=connection.connection_id,
                        dbt_project_path=dbt_project_path,
                        profile_name=resolved["profile_name"],
                        target_name=resolved["target_name"],
                        profiles_dir=resolved.get("profiles_dir"),
                    )
                    _log_scan_step(
                        "dbt.config.seeded",
                        {"connection_id": connection.connection_id, "tenant_id": tenant_id},
                    )
                upsert_tenant_project_dir(settings, tenant_id, domain_id, dbt_project_path)
                database_name = None
                schema_name = None
                if connection.databases:
                    database_name = connection.databases[0].name
                    if connection.databases[0].schemas:
                        schema_name = connection.databases[0].schemas[0].name
                profiles_dir = create_temp_profiles_dir(
                    tenant_id=tenant_id,
                    target_name=resolved["target_name"],
                    connection=connection.model_dump(),
                    database=database_name or settings.db_name,
                    schema=schema_name or settings.db_schema,
                )
                _log_scan_step(
                    "dbt.compile.begin",
                    {"connection_id": connection.connection_id, "profiles_dir": profiles_dir},
                )
                manifest_json = run_dbt_compile(
                    settings,
                    dbt_project_path=dbt_project_path,
                    profile_name=normalize_profile_name(resolved["profile_name"]),
                    target_name=resolved["target_name"],
                    profiles_dir=profiles_dir,
                )
                _log_scan_step(
                    "dbt.compile.complete",
                    {"connection_id": connection.connection_id},
                )
                store_manifest(
                    settings,
                    tenant_id=tenant_id,
                    domain_id=domain_id,
                    connection_id=connection.connection_id,
                    dbt_project_path=dbt_project_path,
                    profile_name=resolved["profile_name"],
                    target_name=resolved["target_name"],
                    manifest_json=manifest_json,
                )
                _log_scan_step(
                    "dbt.manifest.stored",
                    {"connection_id": connection.connection_id},
                )
        except RuntimeError as exc:
            logger.warning("dbt manifest generation skipped: %s", exc)
            _log_scan_step("dbt.error", {"error": str(exc)})

    if progress_cb:
        progress_cb(100, "scan.complete")
    _log_scan_step("complete", {"tenant_id": tenant_id, "domain_id": domain_id})
    return OnboardScanConnectionResponse(connections=connections_payload)


@app.post(
    "/onboard/scan-connection",
    response_model=OnboardScanConnectionResponse,
    tags=["onboard"],
    summary="Scan provided connections",
    description="Scan tables and columns for multiple connections (sample_rows capped at 100).",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "scan_connections": {
                            "summary": "Scan multiple connections",
                            "value": {
                                "tenant_id": "VC_101",
                                "domain_id": "lpg_production_distribution",
                                "connections": [
                                    {
                                        "connection_id": "conn_prod",
                                        "db_type": "postgres",
                                        "host": "db.company.com",
                                        "port": 5432,
                                        "user": "readonly_user",
                                        "password": "******",
                                        "sample_rows": 100,
                                        "databases": [
                                            {
                                                "name": "prod_warehouse",
                                                "schemas": [
                                                    {
                                                        "name": "public",
                                                        "tables": ["lpg_plant_operations"],
                                                        "limit": 20,
                                                        "cursor": None,
                                                    }
                                                ],
                                            }
                                        ],
                                    }
                                ]
                            },
                        }
                    }
                }
            }
        },
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "scan_result": {
                                "summary": "Scan results",
                                "value": {
                                    "connections": [
                                        {
                                            "connection_id": "conn_prod",
                                            "databases": [
                                                {
                                                    "name": "prod_warehouse",
                                                    "schemas": [
                                                        {
                                                            "name": "public",
                                                            "tables": [
                                                                {
                                                                    "table": "lpg_plant_operations",
                                                                    "columns": [
                                                                        {
                                                                            "name": "process_date",
                                                                            "data_type": "date",
                                                                            "null_frac": 0.0,
                                                                            "distinct": 365,
                                                                            "profile": {"min": "2025-01-01", "max": "2026-12-31"},
                                                                        }
                                                                    ],
                                                                }
                                                            ],
                                                            "limit": 20,
                                                            "cursor": None,
                                                            "next_cursor": "ZmFjdF9wcm9kdWN0aW9uX2RhaWx5",
                                                        }
                                                    ],
                                                }
                                            ],
                                        }
                                    ]
                                },
                            }
                        }
                    }
                }
            }
        },
    },
)
def onboard_scan_connection(
    request: OnboardScanMultiConnectionRequest,
    generate_dbt: bool = True,
) -> OnboardScanConnectionResponse:
    return _run_scan_connection(request, generate_dbt, progress_cb=None)


def _merge_entity_candidates(
    rule_based: list[dict],
    llm_based: list[dict],
) -> list[dict]:
    merged: dict[tuple[str, str], dict] = {}
    for candidate in rule_based:
        key = (candidate.get("table"), candidate.get("column"))
        merged[key] = {**candidate, "source": "rule"}
    for candidate in llm_based:
        key = (candidate.get("table"), candidate.get("column"))
        existing = merged.get(key)
        if not existing or candidate.get("confidence", 0) > existing.get("confidence", 0):
            merged[key] = {**candidate, "source": "llm"}
    return list(merged.values())


def _normalize_mapping_candidate(candidate: dict) -> dict:
    normalized = dict(candidate)
    entity_id = normalized.get("entity_id") or normalized.get("mapped_entity_type")
    if entity_id:
        normalized["entity_id"] = entity_id
    if not normalized.get("mapped_entity_type") and entity_id:
        normalized["mapped_entity_type"] = entity_id
    return normalized


def _candidate_identity(candidate: dict) -> tuple[str, str, str]:
    return (
        str(candidate.get("table") or ""),
        str(candidate.get("column") or ""),
        str(candidate.get("mapped_entity_type") or candidate.get("entity_id") or ""),
    )


def _candidate_artifact_key(candidate: dict) -> str:
    entity_id = str(candidate.get("mapped_entity_type") or candidate.get("entity_id") or "").strip()
    table_name = candidate.get("table")
    column_name = candidate.get("column") or candidate.get("join_key")
    if table_name and column_name:
        return f"{entity_id}::{table_name}.{column_name}"
    if column_name:
        return f"{entity_id}::{column_name}"
    return entity_id


def _pick_best_candidates_per_entity(candidates: list[dict]) -> tuple[list[dict], int]:
    by_entity: dict[str, dict] = {}
    skipped = 0
    for candidate in candidates:
        entity_id = str(candidate.get("mapped_entity_type") or candidate.get("entity_id") or "").strip()
        if not entity_id:
            skipped += 1
            continue
        current = by_entity.get(entity_id)
        if not current or float(candidate.get("confidence", 0) or 0) > float(current.get("confidence", 0) or 0):
            by_entity[entity_id] = candidate
        else:
            skipped += 1
    return list(by_entity.values()), skipped


@app.post(
    "/onboard/map/async",
    response_model=JobCreateResponse,
    status_code=202,
    tags=["onboard"],
    summary="Map schema to ontology (async)",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "map_async": {
                            "summary": "Map schema (async)",
                            "value": {
                                "tenant_id": "VC_101",
                                "domain_id": "lpg_production_distribution",
                            },
                        }
                    }
                }
            }
        },
        "responses": {
            "202": {
                "content": {
                    "application/json": {"examples": {"queued": {"value": {"job_id": "job_124", "status": "queued"}}}}
                }
            }
        },
    },
)
def onboard_map_async(
    request: OnboardScanRequest,
    use_llm: bool = True,
) -> JobCreateResponse:
    tenant_id = request.tenant_id
    if not tenant_id:
        raise HTTPException(status_code=400, detail="tenant_id is required")
    domain_id = _resolve_domain_id(tenant_id, None)
    connection_id, database_name, schema_name, tables = _resolve_scope_values(
        tenant_id,
        domain_id,
    )
    payload = request.model_dump()
    payload["connection_id"] = connection_id
    payload["database"] = database_name
    payload["schema"] = schema_name
    if tables is not None:
        payload["tables"] = tables
    payload["use_llm"] = use_llm
    job = create_job(
        settings,
        tenant_id=tenant_id,
        domain_id=domain_id,
        job_type="map_entities",
        payload=payload,
    )
    return JobCreateResponse(job_id=job["job_id"], status=job["status"])


@app.post(
    "/onboard/map",
    response_model=OnboardMapResponse,
    response_model_exclude_none=True,
    tags=["onboard"],
    summary="Map schema to ontology",
    description="Suggest entity mappings from schema columns to the selected domain ontology.",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "map_public": {
                            "summary": "Map public schema",
                            "value": {
                                "tenant_id": "VC_101",
                                "domain_id": "lpg_production_distribution",
                            },
                        }
                    }
                }
            }
        },
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "map_result": {
                                "summary": "Mapping result",
                                "value": {
                                    "mapping_id": "map_ab12cd34",
                                    "tenant_id": "VC_101",
                                    "candidates": [
                                        {
                                            "table": "lpg_plant_operations",
                                            "column": "region",
                                            "mapped_entity_type": "organizational_unit",
                                            "confidence": 0.92,
                                            "source": "llm",
                                        }
                                    ],
                                    "low_confidence_candidates": [],
                                    "low_confidence_threshold": 0.7,
                                },
                            }
                        }
                    }
                }
            }
        },
    },
)
def onboard_map(
    request: OnboardScanRequest,
    use_llm: bool = True,
) -> OnboardMapResponse:
    return _run_onboard_map(request, use_llm=use_llm)


def _run_onboard_map(
    request: OnboardScanRequest,
    use_llm: bool = True,
    job_id: str | None = None,
) -> OnboardMapResponse:
    tenant_id = request.tenant_id
    if not tenant_id:
        raise HTTPException(status_code=400, detail="tenant_id is required")
    domain_id = _resolve_domain_id(tenant_id, None)
    connection_id, database_name, schema_name, tables = _resolve_scope_values(
        tenant_id,
        domain_id,
    )
    schema_payload = load_latest_scan_for_scope(
        settings,
        tenant_id,
        domain_id,
        connection_id,
        database_name,
        schema_name,
    )
    if not schema_payload:
        raise HTTPException(status_code=400, detail="No scan results found for scope")
    tables = schema_payload.get("tables", [])
    ontology = load_pack(f"packs/{domain_id}").get("ontology", {})
    glossary = fetch_glossary_terms(settings, tenant_id, domain_id) if tenant_id else None
    rule_candidates = map_entities(tables, ontology, glossary=glossary)
    llm_candidates: list[dict] = []
    if use_llm:
        try:
            llm_candidates = llm_map_entities(
                settings,
                tables,
                ontology,
                glossary=glossary,
                agent_context={
                    "job_id": job_id,
                    "mapping_id": None,
                    "tenant_id": tenant_id,
                    "domain_id": domain_id,
                    "connection_id": connection_id,
                    "database_name": database_name,
                    "schema_name": schema_name,
                },
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    candidates = _merge_entity_candidates(rule_candidates, llm_candidates)
    low_confidence_candidates = [
        _normalize_mapping_candidate(candidate)
        for candidate in candidates
        if candidate.get("confidence", 0) < LOW_CONFIDENCE_THRESHOLD
    ]
    high_confidence_candidates = [
        _normalize_mapping_candidate(candidate)
        for candidate in candidates
        if candidate.get("confidence", 0) >= LOW_CONFIDENCE_THRESHOLD
    ]
    mapping_id = persist_entity_mapping(
        settings,
        tenant_id,
        domain_id,
        connection_id,
        database_name,
        schema_name,
        [table.get("table") for table in tables],
        high_confidence_candidates,
        low_confidence_candidates,
        LOW_CONFIDENCE_THRESHOLD,
    )
    if job_id:
        attach_mapping_id_to_agents(settings, job_id=job_id, mapping_id=mapping_id)
    return OnboardMapResponse(
        mapping_id=mapping_id,
        tenant_id=tenant_id,
        candidates=high_confidence_candidates,
        low_confidence_candidates=low_confidence_candidates,
        low_confidence_threshold=LOW_CONFIDENCE_THRESHOLD,
    )


@app.get(
    "/onboard/map",
    tags=["onboard"],
    summary="Get latest mapping run",
    description="Return the latest entity mapping run for the active tenant scope.",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "latest": {
                                "summary": "Latest mapping",
                                "value": {
                                    "mapping_id": "map_123",
                                    "tenant_id": "VC_101",
                                    "domain_id": "lpg_production_distribution",
                                    "connection_id": "conn_lpg",
                                    "database_name": "hpcl_ceg",
                                    "schema_name": "public",
                                    "status": "live",
                                    "candidates": [],
                                },
                            }
                        }
                    }
                }
            }
        }
    },
)
def onboard_map_latest(
    tenant_id: str,
    connection_id: str | None = None,
    database: str | None = None,
    schema: str | None = None,
) -> OnboardMapRunResponse:
    domain_id = _resolve_domain_id(tenant_id, None)
    if not connection_id or not database or not schema:
        resolved_connection_id, resolved_database, resolved_schema, _ = _resolve_scope_values(
            tenant_id,
            domain_id,
        )
        connection_id = connection_id or resolved_connection_id
        database = database or resolved_database
        schema = schema or resolved_schema
    runs = list_entity_mappings(
        settings,
        tenant_id,
        domain_id,
        connection_id,
        database,
        schema,
        limit=1,
    )
    if not runs:
        raise HTTPException(status_code=404, detail="Mapping not found")
    row = runs[0]
    return OnboardMapRunResponse(
        mapping_id=row.get("mapping_id"),
        tenant_id=row.get("tenant_id"),
        domain_id=row.get("domain_id"),
        connection_id=row.get("connection_id"),
        database_name=row.get("database_name"),
        schema_name=row.get("schema_name"),
        tables=row.get("tables") or [],
        candidates=row.get("candidates") or [],
        low_confidence_candidates=row.get("low_confidence_candidates") or [],
        low_confidence_threshold=float(row.get("low_confidence_threshold") or LOW_CONFIDENCE_THRESHOLD),
        status=row.get("status") or "live",
        created_at=row.get("created_at").isoformat() if row.get("created_at") else None,
        updated_at=row.get("updated_at").isoformat() if row.get("updated_at") else None,
    )


@app.get(
    "/onboard/map/history",
    tags=["onboard"],
    summary="List mapping history",
    description="Return recent entity mapping runs for the given scope.",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "history": {
                                "summary": "Recent runs",
                                "value": {
                                    "runs": [
                                        {
                                            "mapping_id": "map_ab12cd34",
                                            "created_at": "2026-02-22T10:12:11Z",
                                            "candidates": 18,
                                            "low_confidence": 2,
                                            "status": "live",
                                        }
                                    ]
                                },
                            }
                        }
                    }
                }
            }
        }
    },
)
def onboard_map_history(
    tenant_id: str,
    connection_id: str | None = None,
    database: str | None = None,
    schema: str | None = None,
    limit: int = 20,
) -> dict:
    domain_id = _resolve_domain_id(tenant_id, None)
    if not connection_id or not database or not schema:
        resolved_connection_id, resolved_database, resolved_schema, _ = _resolve_scope_values(
            tenant_id,
            domain_id,
        )
        connection_id = connection_id or resolved_connection_id
        database = database or resolved_database
        schema = schema or resolved_schema
    runs = list_entity_mappings(
        settings,
        tenant_id,
        domain_id,
        connection_id,
        database,
        schema,
        limit=limit,
    )
    summarized = [
        {
            "mapping_id": run.get("mapping_id"),
            "created_at": run.get("created_at"),
            "candidates": len(run.get("candidates", []) or []),
            "low_confidence": len(run.get("low_confidence_candidates", []) or []),
            "status": run.get("status"),
        }
        for run in runs
    ]
    return {"runs": summarized}


@app.get(
    "/onboard/map/agents",
    tags=["onboard"],
    summary="List mapping agent runs",
    description="Return recent entity mapping agent runs for the given scope.",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "agents": {
                                "summary": "Agent runs",
                                "value": {
                                    "agents": [
                                        {
                                            "agent_run_id": "emap_123",
                                            "job_id": "job_abc",
                                            "table_name": "fact_sales",
                                            "created_at": "2026-02-20T10:05:12Z",
                                        }
                                    ]
                                },
                            }
                        }
                    }
                }
            }
        }
    },
)
def onboard_map_agents(
    tenant_id: str,
    connection_id: str | None = None,
    database: str | None = None,
    schema: str | None = None,
    limit: int = 50,
) -> dict:
    domain_id = _resolve_domain_id(tenant_id, None)
    if not connection_id or not database or not schema:
        resolved_connection_id, resolved_database, resolved_schema, _ = _resolve_scope_values(
            tenant_id,
            domain_id,
        )
        connection_id = connection_id or resolved_connection_id
        database = database or resolved_database
        schema = schema or resolved_schema
    agents = list_entity_mapping_agents(
        settings,
        tenant_id=tenant_id,
        domain_id=domain_id,
        connection_id=connection_id,
        database_name=database,
        schema_name=schema,
        limit=limit,
    )
    return {"agents": agents}


@app.get(
    "/onboard/map/{mapping_id}",
    response_model=OnboardMapRunResponse,
    tags=["onboard"],
    summary="Get mapping run",
    description="Return a single mapping run by mapping_id for the active tenant scope.",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "mapping": {
                                "summary": "Mapping run",
                                "value": {
                                    "mapping_id": "map_ab12cd34",
                                    "tenant_id": "VC_101",
                                    "domain_id": "lpg_production_distribution",
                                    "connection_id": "conn_lpg",
                                    "database_name": "hpcl_ceg",
                                    "schema_name": "public",
                                    "tables": ["lpg_plant_operations"],
                                    "candidates": [
                                        {
                                            "table": "lpg_plant_operations",
                                            "column": "sap_id",
                                            "mapped_entity_type": "plant",
                                            "confidence": 0.93,
                                            "source": "llm",
                                        }
                                    ],
                                    "low_confidence_candidates": [],
                                    "low_confidence_threshold": 0.7,
                                    "status": "live",
                                },
                            }
                        }
                    }
                }
            }
        }
    },
)
def onboard_map_get(mapping_id: str, tenant_id: str) -> OnboardMapRunResponse:
    domain_id = _resolve_domain_id(tenant_id, None)
    connection_id, database, schema, _ = _resolve_scope_values(
        tenant_id,
        domain_id,
    )
    row = get_entity_mapping(
        settings,
        mapping_id=mapping_id,
        tenant_id=tenant_id,
        domain_id=domain_id,
        connection_id=connection_id,
        database_name=database,
        schema_name=schema,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Mapping not found")
    return OnboardMapRunResponse(
        mapping_id=row.get("mapping_id"),
        tenant_id=row.get("tenant_id"),
        domain_id=row.get("domain_id"),
        connection_id=row.get("connection_id"),
        database_name=row.get("database_name"),
        schema_name=row.get("schema_name"),
        tables=row.get("tables") or [],
        candidates=row.get("candidates") or [],
        low_confidence_candidates=row.get("low_confidence_candidates") or [],
        low_confidence_threshold=float(row.get("low_confidence_threshold") or LOW_CONFIDENCE_THRESHOLD),
        status=row.get("status") or "live",
        created_at=row.get("created_at").isoformat() if row.get("created_at") else None,
        updated_at=row.get("updated_at").isoformat() if row.get("updated_at") else None,
    )


@app.post(
    "/onboard/map/{mapping_id}/apply",
    response_model=OnboardMapApplyResponse,
    tags=["onboard"],
    summary="Apply mapping run to entity overrides",
    description="Promote mapping candidates from a mapping run into canonical entity overrides.",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "apply_all": {
                            "summary": "Apply all candidates",
                            "value": {
                                "tenant_id": "VC_101",
                                "selection_mode": "all",
                                "status": "live",
                                "notes": "Apply from mapping run",
                            },
                        },
                        "apply_selected": {
                            "summary": "Apply selected candidates",
                            "value": {
                                "tenant_id": "VC_101",
                                "selection_mode": "selected",
                                "candidates": [
                                    {
                                        "table": "lpg_plant_operations",
                                        "column": "sap_id",
                                        "mapped_entity_type": "plant",
                                    }
                                ],
                                "status": "live",
                                "notes": "Apply selected only",
                            },
                        },
                    }
                }
            }
        },
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "applied": {
                                "summary": "Apply success",
                                "value": {
                                    "ok": True,
                                    "mapping_id": "map_ab12cd34",
                                    "applied_count": 8,
                                    "skipped_count": 2,
                                },
                            }
                        }
                    }
                }
            }
        },
    },
)
def onboard_map_apply(mapping_id: str, payload: OnboardMapApplyRequest) -> OnboardMapApplyResponse:
    domain_id = _resolve_domain_id(payload.tenant_id, payload.domain_id)
    connection_id, database_name, schema_name, _ = _resolve_scope_values(
        payload.tenant_id,
        domain_id,
    )
    mapping = get_entity_mapping(
        settings,
        mapping_id=mapping_id,
        tenant_id=payload.tenant_id,
        domain_id=domain_id,
        connection_id=connection_id,
        database_name=database_name,
        schema_name=schema_name,
    )
    if not mapping:
        raise HTTPException(status_code=404, detail="Mapping not found")

    candidates = mapping.get("candidates") or []
    if payload.selection_mode == "selected":
        if not payload.candidates:
            raise HTTPException(status_code=400, detail="candidates are required when selection_mode=selected")
        allowed = {_candidate_identity(item.model_dump()) for item in payload.candidates}
        candidates = [candidate for candidate in candidates if _candidate_identity(candidate) in allowed]

    selected_total = len(candidates)
    candidates_to_apply, skipped_count = _pick_best_candidates_per_entity(candidates)
    for candidate in candidates_to_apply:
        entity_id = candidate.get("mapped_entity_type") or candidate.get("entity_id")
        column_name = candidate.get("column")
        table_name = candidate.get("table")
        artifact_key = _candidate_artifact_key(candidate)
        upsert_entity_override(
            settings,
            payload.tenant_id,
            domain_id,
            connection_id,
            database_name,
            schema_name,
            {
                "entity_id": entity_id,
                "description": candidate.get("description")
                or f"Auto-mapped from {table_name}.{column_name}",
                "join_key": column_name,
                "examples": candidate.get("examples") or [column_name],
                "lifecycle_status": payload.status,
                "source_type": "user",
                "source_run_id": mapping_id,
                "artifact_key": artifact_key,
                "source_table": table_name,
                "source_column": column_name,
                "confidence": candidate.get("confidence"),
                "change_reason": payload.notes,
            },
        )

    applied_count = len(candidates_to_apply)
    skipped_count += max(selected_total - applied_count - skipped_count, 0)
    mapping_status = (
        "applied" if payload.selection_mode == "all" and skipped_count == 0 else "partially_applied"
    )
    update_entity_mapping_status(
        settings,
        mapping_id=mapping_id,
        tenant_id=payload.tenant_id,
        domain_id=domain_id,
        connection_id=connection_id,
        database_name=database_name,
        schema_name=schema_name,
        status=mapping_status,
    )
    review_id = create_review_event(
        settings,
        tenant_id=payload.tenant_id,
        domain_id=domain_id,
        connection_id=connection_id,
        database_name=database_name,
        schema_name=schema_name,
        artifact_type="mapping",
        artifact_id=mapping_id,
        status="applied",
        notes=payload.notes,
        payload={
            "selection_mode": payload.selection_mode,
            "requested_candidates": len(payload.candidates),
            "selected_candidates": selected_total,
            "applied_count": applied_count,
            "skipped_count": skipped_count,
            "entity_status": payload.status,
        },
    )
    return OnboardMapApplyResponse(
        ok=True,
        mapping_id=mapping_id,
        applied_count=applied_count,
        skipped_count=skipped_count,
        status=payload.status,
        review_id=review_id,
        mapping_status=mapping_status,
    )


def _infer_models_from_scan(
    tables: list[dict],
    time_column: str | None,
    grain: str | None,
) -> tuple[list[dict], list[dict]]:
    facts = []
    dims = []
    for table in tables:
        columns = table.get("columns", [])
        column_names = [col.get("name") for col in columns]
        numeric_cols = [
            col["name"]
            for col in columns
            if str(col.get("data_type", "")).lower() in {"integer", "bigint", "smallint", "numeric", "double precision", "real"}
        ]
        text_cols = [
            col["name"]
            for col in columns
            if str(col.get("data_type", "")).lower() in {"text", "character varying", "varchar"}
        ]
        date_cols = [
            col["name"]
            for col in columns
            if str(col.get("data_type", "")).lower() in {"date", "timestamp", "timestamp without time zone", "timestamp with time zone"}
        ]

        candidate_time = time_column if time_column in column_names else (date_cols[0] if date_cols else None)
        is_fact = bool(numeric_cols) and bool(candidate_time)
        if is_fact:
            facts.append(
                {
                    "name": table.get("table"),
                    "grain": grain or "day",
                    "time_column": candidate_time,
                    "measures": numeric_cols[:10],
                    "dimensions": text_cols[:10],
                    "confidence": 0.7 if len(numeric_cols) < 3 else 0.85,
                }
            )
        else:
            dim_keys = [col for col in column_names if col.endswith("_id") or col.endswith("_code")]
            dims.append(
                {
                    "name": table.get("table"),
                    "keys": dim_keys[:5],
                    "attributes": text_cols[:15],
                    "confidence": 0.6 if not dim_keys else 0.8,
                }
            )
    return facts, dims


def _merge_models(rule_facts: list[dict], rule_dims: list[dict], llm_payload: dict) -> tuple[list[dict], list[dict]]:
    llm_facts = llm_payload.get("facts", []) if llm_payload else []
    llm_dims = llm_payload.get("dimensions", []) if llm_payload else []

    merged_facts = {fact.get("name"): fact for fact in rule_facts if fact.get("name")}
    for fact in llm_facts:
        name = fact.get("name")
        if not name:
            continue
        if name not in merged_facts or fact.get("confidence", 0) > merged_facts[name].get("confidence", 0):
            merged_facts[name] = fact

    merged_dims = {dim.get("name"): dim for dim in rule_dims if dim.get("name")}
    for dim in llm_dims:
        name = dim.get("name")
        if not name:
            continue
        if name not in merged_dims or dim.get("confidence", 0) > merged_dims[name].get("confidence", 0):
            merged_dims[name] = dim

    return list(merged_facts.values()), list(merged_dims.values())


@app.post(
    "/onboard/infer-models/async",
    response_model=JobCreateResponse,
    status_code=202,
    tags=["onboard"],
    summary="Infer facts and dimensions (async)",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "infer_async": {
                            "summary": "Infer models (async)",
                            "value": {
                                "tenant_id": "VC_101",
                                "domain_id": "lpg_production_distribution",
                                "grain": "day",
                                "use_llm": False,
                            },
                        }
                    }
                }
            }
        },
        "responses": {
            "202": {
                "content": {
                    "application/json": {"examples": {"queued": {"value": {"job_id": "job_125", "status": "queued"}}}}
                }
            }
        },
    },
)
def infer_models_async(request: InferModelsRequest) -> JobCreateResponse:
    if not request.tenant_id:
        raise HTTPException(status_code=400, detail="tenant_id is required")
    domain_id = _resolve_domain_id(request.tenant_id, None)
    connection_id, database_name, schema_name, tables = _resolve_scope_values(
        request.tenant_id,
        domain_id,
    )
    payload = request.model_dump()
    payload["connection_id"] = connection_id
    payload["database"] = database_name
    payload["schema"] = schema_name
    if tables is not None:
        payload["tables"] = tables
    job = create_job(
        settings,
        tenant_id=request.tenant_id,
        domain_id=domain_id,
        job_type="infer_models",
        payload=payload,
    )
    return JobCreateResponse(job_id=job["job_id"], status=job["status"])


@app.post(
    "/onboard/infer-models",
    response_model=InferModelsResponse,
    tags=["onboard"],
    summary="Infer facts and dimensions",
    description="Suggest candidate dbt facts and dimensions from scanned schema and ontology.",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "infer_models": {
                            "summary": "Infer models",
                            "value": {
                                "tenant_id": "VC_101",
                                "domain_id": "lpg_production_distribution",
                                "time_column": "production_date",
                                "grain": "day",
                                "use_llm": True,
                            },
                        }
                    }
                }
            }
        },
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "suggested_models": {
                                "summary": "Suggested facts/dims",
                                "value": {
                                    "facts": [
                                        {
                                            "name": "fact_lpg_plant_operations",
                                            "grain": "day",
                                            "time_column": "process_date",
                                            "measures": ["production_14_2kg", "production_19kg"],
                                            "dimensions": ["sap_id", "region", "sales_area"],
                                            "confidence": 0.85,
                                        }
                                    ],
                                    "dimensions": [
                                        {
                                            "name": "dim_plant",
                                            "keys": ["sap_id"],
                                            "attributes": ["plant_name", "region"],
                                            "confidence": 0.8,
                                        }
                                    ],
                                },
                            }
                        }
                    }
                }
            }
        },
    },
)
def infer_models(request: InferModelsRequest) -> InferModelsResponse:
    if not request.tenant_id:
        raise HTTPException(status_code=400, detail="tenant_id is required")
    domain_id = _resolve_domain_id(request.tenant_id, None)
    connection_id, database_name, schema_name, tables = _resolve_scope_values(
        request.tenant_id,
        domain_id,
    )
    schema_payload = load_latest_scan_for_scope(
        settings,
        request.tenant_id,
        domain_id,
        connection_id,
        database_name,
        schema_name,
    )
    if not schema_payload:
        raise HTTPException(status_code=400, detail="No scan results found for scope")
    tables = schema_payload.get("tables", [])
    facts, dims = _infer_models_from_scan(tables, request.time_column, request.grain)
    if request.use_llm:
        try:
            schema_summary = build_schema_summary(tables)
            suggestions = suggest_semantic_model(
                settings,
                schema_summary=schema_summary,
                questions=[],
                glossary=None,
                domain_id=domain_id,
                model_override=None,
                tables=tables,
            )
            llm_facts = []
            for fact in suggestions.get("facts", []) or []:
                name = fact.get("table_name") or fact.get("name")
                if not name:
                    continue
                llm_facts.append(
                    {
                        "name": name,
                        "grain": fact.get("grain"),
                        "time_column": fact.get("time_column"),
                        "measures": fact.get("measures", []),
                        "dimensions": fact.get("dimensions", []),
                        "description": fact.get("description"),
                        "status": fact.get("status", "suggested"),
                        "confidence": fact.get("confidence", 0.85),
                    }
                )
            llm_dims = []
            for dim in suggestions.get("dimensions", []) or []:
                name = dim.get("name")
                if not name:
                    continue
                llm_dims.append(
                    {
                        "name": name,
                        "keys": dim.get("keys", []),
                        "attributes": dim.get("attributes", []),
                        "description": dim.get("description"),
                        "status": dim.get("status", "suggested"),
                        "confidence": dim.get("confidence", 0.8),
                    }
                )
            facts, dims = _merge_models(facts, dims, {"facts": llm_facts, "dimensions": llm_dims})
        except ValueError:
            pass
    for fact in facts:
        table_name = fact.get("name")
        if not table_name:
            continue
        upsert_fact(
            settings,
            {
                "fact_id": fact.get("fact_id"),
                "tenant_id": request.tenant_id,
                "domain_id": domain_id,
                "connection_id": connection_id,
                "database_name": database_name,
                "schema_name": schema_name,
                "table_name": table_name,
                "grain": fact.get("grain"),
                "time_column": fact.get("time_column"),
                "measures": fact.get("measures", []),
                "dimensions": fact.get("dimensions", []),
                "description": fact.get("description"),
                "lifecycle_status": fact.get("status", "suggested"),
                "source_type": "llm" if request.use_llm else "rule",
            },
        )
    for dim in dims:
        name = dim.get("name")
        if not name:
            continue
        upsert_dimension(
            settings,
            {
                "dimension_id": dim.get("dimension_id"),
                "tenant_id": request.tenant_id,
                "domain_id": domain_id,
                "connection_id": connection_id,
                "database_name": database_name,
                "schema_name": schema_name,
                "name": name,
                "keys": dim.get("keys", []),
                "attributes": dim.get("attributes", []),
                "description": dim.get("description"),
                "lifecycle_status": dim.get("status", "suggested"),
                "source_type": "llm" if request.use_llm else "rule",
            },
        )
    return InferModelsResponse(facts=facts, dimensions=dims)


@app.post(
    "/metrics/suggested/async",
    response_model=JobCreateResponse,
    status_code=202,
    tags=["onboard"],
    summary="Suggest metrics (async)",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "metrics_async": {
                            "summary": "Suggest metrics (async)",
                            "value": {
                                "tenant_id": "VC_101",
                                "domain_id": "lpg_production_distribution",
                            },
                        }
                    }
                }
            }
        },
        "responses": {
            "202": {
                "content": {
                    "application/json": {"examples": {"queued": {"value": {"job_id": "job_126", "status": "queued"}}}}
                }
            }
        },
    },
)
def suggested_metrics_async(
    request: OnboardScanRequest,
    persist: bool = True,
) -> JobCreateResponse:
    if not request.tenant_id:
        raise HTTPException(status_code=400, detail="tenant_id is required")
    domain_id = _resolve_domain_id(request.tenant_id, None)
    connection_id, database_name, schema_name, tables = _resolve_scope_values(
        request.tenant_id,
        domain_id,
    )
    payload = request.model_dump()
    payload["connection_id"] = connection_id
    payload["database"] = database_name
    payload["schema"] = schema_name
    if tables is not None:
        payload["tables"] = tables
    payload["persist"] = persist
    job = create_job(
        settings,
        tenant_id=request.tenant_id,
        domain_id=domain_id,
        job_type="metrics_suggested",
        payload=payload,
    )
    return JobCreateResponse(job_id=job["job_id"], status=job["status"])


def _suggested_metrics_impl(
    request: OnboardScanRequest,
    persist: bool = True,
    progress_cb: Callable[[int, str], None] | None = None,
) -> SuggestedMetricsResponse:
    if not request.tenant_id:
        raise HTTPException(status_code=400, detail="tenant_id is required")
    if progress_cb:
        progress_cb(5, "resolve_scope")
    domain_id = _resolve_domain_id(request.tenant_id, None)
    connection_id, database_name, schema_name, tables = _resolve_scope_values(
        request.tenant_id,
        domain_id,
    )
    schema_payload = load_latest_scan_for_scope(
        settings,
        request.tenant_id,
        domain_id,
        connection_id,
        database_name,
        schema_name,
    )
    if not schema_payload:
        raise HTTPException(status_code=400, detail="No scan results found for scope")
    tables = schema_payload.get("tables", [])
    logger.info(
        "metrics_suggested: start | tenant=%s domain=%s tables=%s persist=%s",
        request.tenant_id,
        domain_id,
        len(tables),
        persist,
    )
    if progress_cb:
        progress_cb(20, "detect_measures")
    measures = detect_measures(tables)
    if progress_cb:
        progress_cb(40, "detect_time_columns")
    low_confidence_measures = [
        measure
        for measure in measures
        if measure.get("confidence", 0) < LOW_CONFIDENCE_THRESHOLD
    ]
    high_confidence_measures = [
        measure
        for measure in measures
        if measure.get("confidence", 0) >= LOW_CONFIDENCE_THRESHOLD
    ]
    time_columns = detect_time_columns(tables)
    if progress_cb:
        progress_cb(55, "map_entities")
    ontology = load_pack(f"packs/{domain_id}").get("ontology", {})
    entity_candidates = map_entities(tables, ontology)
    if progress_cb:
        progress_cb(75, "persist_metrics" if persist else "skip_persist")
    if persist:
        persist_suggested_metrics(
            settings,
            request.tenant_id,
            domain_id,
            connection_id,
            database_name,
            schema_name,
            measures,
        )
    if progress_cb:
        progress_cb(95, "finalize_response")
    return SuggestedMetricsResponse(
        measures=high_confidence_measures,
        low_confidence_measures=low_confidence_measures,
        low_confidence_threshold=LOW_CONFIDENCE_THRESHOLD,
        time_columns=time_columns,
        entity_candidates=entity_candidates,
    )


@app.post(
    "/metrics/suggested",
    response_model=SuggestedMetricsResponse,
    tags=["onboard"],
    summary="Suggest metrics",
    description="Generate suggested measures, time columns, and entity mappings.",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "suggest_public": {
                            "summary": "Suggest metrics for public schema",
                            "value": {
                                "tenant_id": "VC_101",
                                "domain_id": "lpg_production_distribution",
                            },
                        }
                    }
                }
            }
        },
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "suggested_metrics": {
                                "summary": "Suggestions",
                                "value": {
                                    "measures": [
                                        {
                                            "table": "lpg_plant_operations",
                                            "column": "production_19kg",
                                            "measure_type": "volume",
                                            "unit": "kg",
                                            "confidence": 0.9,
                                            "additive": True,
                                        }
                                    ],
                                    "low_confidence_measures": [
                                        {
                                            "table": "lpg_plant_operations",
                                            "column": "production_14_2kg",
                                            "measure_type": "number",
                                            "unit": None,
                                            "confidence": 0.6,
                                            "additive": False,
                                        }
                                    ],
                                    "low_confidence_threshold": 0.7,
                                    "time_columns": [
                                        {"table": "lpg_plant_operations", "column": "process_date"}
                                    ],
                                    "entity_candidates": [
                                        {
                                            "table": "lpg_plant_operations",
                                            "column": "region",
                                            "mapped_entity_type": "organizational_unit",
                                            "confidence": 0.9,
                                        }
                                    ],
                                },
                            }
                        }
                    }
                }
            }
        },
    },
)
def suggested_metrics(
    request: OnboardScanRequest,
    persist: bool = True,
) -> SuggestedMetricsResponse:
    return _suggested_metrics_impl(request, persist=persist, progress_cb=None)


def _validate_contract_metrics(request: ContractValidateRequest) -> ContractValidateResponse:
    errors: list[dict] = []
    warnings: list[dict] = []
    dimension_names = set(catalog.dimensions.keys())

    for metric in request.metrics:
        if metric.type not in ALLOWED_METRIC_TYPES:
            errors.append(
                {
                    "metric_name": metric.metric_name,
                    "issue": f"Unsupported type '{metric.type}'",
                }
            )
        if not metric.sql:
            errors.append(
                {
                    "metric_name": metric.metric_name,
                    "issue": "Missing SQL",
                }
            )
        if not metric.grain:
            warnings.append(
                {
                    "metric_name": metric.metric_name,
                    "issue": "Missing grain",
                }
            )
        unknown_dims = [dim for dim in metric.dimensions if dim not in dimension_names]
        if unknown_dims:
            errors.append(
                {
                    "metric_name": metric.metric_name,
                    "issue": f"Unknown dimensions: {', '.join(unknown_dims)}",
                }
            )
        if metric.metric_name in catalog.metrics:
            warnings.append(
                {
                    "metric_name": metric.metric_name,
                    "issue": "Metric already exists and will be overridden",
                }
            )

    return ContractValidateResponse(valid=not errors, errors=errors, warnings=warnings)


@app.post(
    "/contracts/validate",
    response_model=ContractValidateResponse,
    tags=["admin"],
    summary="Validate metric contracts",
    description="Validate metric definitions against known dimensions and allowed types.",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "validate_metrics": {
                            "summary": "Validate metrics",
                            "value": {
                                "metrics": [
                                    {
                                        "metric_name": "production_mt",
                                        "type": "sum",
                                        "sql": "({{ ref('fact_lpg_plant_operations') }}.production_14_2kg * 14.2 + {{ ref('fact_lpg_plant_operations') }}.production_19kg * 19) / 1000",
                                        "grain": "day",
                                        "dimensions": ["region", "sap_id"],
                                    }
                                ]
                            },
                        }
                    }
                }
            }
        }
    },
)
def validate_contracts(request: ContractValidateRequest) -> ContractValidateResponse:
    return _validate_contract_metrics(request)


@app.post(
    "/contracts/apply",
    tags=["admin"],
    summary="Apply contracts",
    description="Reload the metric catalog from the registry and contracts file.",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "reloaded": {
                                "summary": "Reloaded catalog",
                                "value": {"metrics": 42, "dimensions": 18},
                            }
                        }
                    }
                }
            }
        }
    },
)
def apply_contracts() -> dict:
    global catalog
    catalog = load_catalog_with_registry(settings, settings.metrics_catalog_path)
    return {"metrics": len(catalog.metrics), "dimensions": len(catalog.dimensions)}


def _resolve_metrics(
    request: QueryRequest,
    *,
    glossary: list[dict] | None = None,
    allowed_dimensions: list[str] | None = None,
    domain_id: str | None = None,
    metric_catalog: MetricCatalog | None = None,
) -> tuple[list[str], list[str], list[dict]]:
    catalog_ref = metric_catalog or catalog
    if request.metrics:
        logger.info("request.metrics provided: %s", request.metrics)
        return request.metrics, request.dimensions, [flt.model_dump() for flt in request.filters]

    if request.metric:
        logger.info("request.metric provided: %s", request.metric)
        return [request.metric], request.dimensions, [flt.model_dump() for flt in request.filters]

    if request.question:
        logger.info("resolving question: %s", request.question)
        deterministic_metrics = _deterministic_metrics_from_question(request.question, catalog_ref)
        if deterministic_metrics:
            logger.info("resolver.deterministic_metrics | metrics=%s", deterministic_metrics)
            metric_fact_cols: set[str] = set()
            for metric_name in deterministic_metrics:
                metric = catalog_ref.metrics.get(metric_name)
                if not metric:
                    continue
                metric_fact_cols.update(_fact_columns_for_metric(metric.sql, settings.db_schema))
            llm_allowed_dimensions = sorted(metric_fact_cols) if metric_fact_cols else allowed_dimensions
            deterministic_dims = _deterministic_dimensions_from_question(
                request.question,
                glossary,
                llm_allowed_dimensions,
            )
            deterministic_filters = _deterministic_date_filters_from_question(
                request.question,
                llm_allowed_dimensions,
            )
            if deterministic_dims or deterministic_filters:
                logger.info(
                    "resolver.deterministic_dims_filters | dimensions=%s filters=%s",
                    deterministic_dims,
                    deterministic_filters,
                )
                metrics = deterministic_metrics
                dimensions = deterministic_dims
                filters = deterministic_filters
            else:
                resolved = resolve_question(
                    request.question,
                    catalog_ref,
                    settings,
                    allowed_metrics=deterministic_metrics,
                    glossary=glossary,
                    allowed_dimensions=llm_allowed_dimensions,
                )
                logger.info("resolver output (dims/filters): %s", resolved)
                metrics = deterministic_metrics
                dimensions = resolved.get("dimensions", [])
                filters = resolved.get("filters", [])
        else:
            semantic_resolved = None
            if domain_id and request.tenant_id:
                try:
                    semantic_resolved = resolve_question_semantic(
                        settings,
                        request.question,
                        domain_id,
                        allowed_dimensions=allowed_dimensions,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.info("resolver.semantic_graph failed: %s", exc)
            if semantic_resolved and semantic_resolved.get("metrics"):
                logger.info("resolver.semantic_graph | metrics=%s dimensions=%s matched=%s",
                            semantic_resolved.get("metrics"),
                            semantic_resolved.get("dimensions"),
                            semantic_resolved.get("matched"))
                metrics = semantic_resolved.get("metrics", [])
                dimensions = semantic_resolved.get("dimensions", [])
                filters = _deterministic_date_filters_from_question(
                    request.question,
                    allowed_dimensions,
                )
            else:
                resolved = resolve_question(
                    request.question,
                    catalog_ref,
                    settings,
                    glossary=glossary,
                    allowed_dimensions=allowed_dimensions,
                )
                logger.info("resolver output: %s", resolved)
                metrics = resolved.get("metrics", [])
                dimensions = resolved.get("dimensions", [])
                filters = resolved.get("filters", [])
        if allowed_dimensions:
            allowed_metrics_set = {m for m in catalog_ref.metric_names()}
            if allowed_metrics_set:
                filtered_metrics = []
                for metric in metrics:
                    if metric in allowed_metrics_set:
                        filtered_metrics.append(metric)
                if filtered_metrics != metrics:
                    logger.info("resolver filtered metrics to catalog: %s -> %s", metrics, filtered_metrics)
                    metrics = filtered_metrics
        expanded_dimensions = _expand_dimensions_from_glossary(
            dimensions,
            glossary,
            allowed_dimensions,
        )
        if expanded_dimensions != dimensions:
            logger.info("resolver expanded dimensions from glossary: %s -> %s", dimensions, expanded_dimensions)
            dimensions = expanded_dimensions
        if allowed_dimensions:
            allowed_set = {d.lower() for d in allowed_dimensions}
            filtered_dims = [d for d in dimensions if d.lower() in allowed_set]
            if filtered_dims != dimensions:
                logger.info("resolver filtered dimensions to allowed: %s -> %s", dimensions, filtered_dims)
                dimensions = filtered_dims
            filtered_filters = []
            for flt in filters:
                payload = flt if isinstance(flt, dict) else flt.model_dump()
                field = payload.get("field")
                if isinstance(field, str) and field.lower() in allowed_set:
                    filtered_filters.append(payload)
            if len(filtered_filters) != len(filters):
                logger.info("resolver filtered filters to allowed fields: %s -> %s", filters, filtered_filters)
                filters = filtered_filters
        if not metrics:
            question = request.question.lower()
            if "required run rate" in question:
                metrics = ["current_run_rate_mmt", "required_run_rate_mmt"]
                dimensions = ["sales_area_name", "month_name", "fiscal_year"]
            if "sales volume" in question:
                metrics = ["total_sales_volume_tmt"]
                dimensions = ["sales_area_name", "product_name", "calendar_quarter_sales", "fiscal_year"]

        filters = _coerce_sbu_filters(filters)
        filters = _coerce_product_filters(filters)
        dimensions = _coerce_sbu_dimensions(dimensions, filters)
        if "total_sales_volume_tmt" in metrics:
            filters = _normalize_sales_quarter_filters(filters, metrics)
            dimensions = [
                "calendar_quarter_sales" if dim == "calendar_quarter" else dim
                for dim in dimensions
            ]

        filter_fields = []
        for flt in filters:
            payload = flt if isinstance(flt, dict) else flt.model_dump()
            filter_fields.append(payload["field"])

        allowed_metrics = []
        for metric in catalog_ref.metrics.values():
            if all(dim in metric.dimensions for dim in dimensions) and all(
                field in metric.dimensions for field in filter_fields
            ):
                allowed_metrics.append(metric.name)

        if metrics and any(metric not in allowed_metrics for metric in metrics):
            if not allowed_metrics:
                # Defer filtering; downstream will coerce/drop unsupported dims/filters.
                return (metrics, dimensions, filters)
            logger.info("re-resolving with allowed metrics: %s", allowed_metrics)
            resolved = resolve_question(
                request.question,
                catalog_ref,
                settings,
                allowed_metrics=allowed_metrics,
                glossary=glossary,
                allowed_dimensions=allowed_dimensions,
            )
            logger.info("resolver output (restricted): %s", resolved)
            restricted_dimensions = resolved.get("dimensions", [])
            expanded_dimensions = _expand_dimensions_from_glossary(
                restricted_dimensions,
                glossary,
                allowed_dimensions,
            )
            if expanded_dimensions != restricted_dimensions:
                logger.info(
                    "resolver expanded dimensions from glossary (restricted): %s -> %s",
                    restricted_dimensions,
                    expanded_dimensions,
                )
            if allowed_dimensions:
                allowed_set = {d.lower() for d in allowed_dimensions}
                filtered_dims = [d for d in expanded_dimensions if d.lower() in allowed_set]
                if filtered_dims != expanded_dimensions:
                    logger.info(
                        "resolver filtered dimensions to allowed (restricted): %s -> %s",
                        expanded_dimensions,
                        filtered_dims,
                    )
                    expanded_dimensions = filtered_dims
            return (
                resolved.get("metrics", []),
                expanded_dimensions,
                resolved.get("filters", []),
            )

        return (metrics, dimensions, filters)

    raise HTTPException(status_code=400, detail="Provide metric(s) or question")


def _normalize_filter_value(field: str, value: object) -> object:
    if isinstance(value, (list, tuple)):
        return [_normalize_filter_value(field, item) for item in value]
    if field == "calendar_quarter" and isinstance(value, str):
        cleaned = value.strip().upper()
        if cleaned.startswith("Q") and cleaned[1:].isdigit():
            return int(cleaned[1:])
    if field == "calendar_quarter_sales" and isinstance(value, str):
        cleaned = value.strip().upper()
        if cleaned.startswith("Q") and cleaned[1:].isdigit():
            return int(cleaned[1:])
    if field == "state_name" and isinstance(value, str):
        cleaned = value.strip().upper()
        if cleaned == "UP":
            return "UTTAR PRADESH"
    if field == "month_name" and isinstance(value, str):
        cleaned = value.strip()
        if len(cleaned) >= 3:
            return cleaned[:3].title()
    if field == "zone_name" and isinstance(value, str):
        cleaned = value.strip().upper()
        zone_map = {
            "EZ": "East",
            "ECZ": "East Central Zone",
            "SZ": "South",
            "WZ": "West",
            "NZ": "North",
            "NFZ": "North Frontier Zone",
            "NWZ": "North West Frontier",
            "SWZ": "South Western Zone",
            "NCZ": "North Central Retail",
        }
        if cleaned in zone_map:
            return zone_map[cleaned]
    if field == "fiscal_year" and isinstance(value, str):
        cleaned = value.strip()
        if cleaned.upper().startswith("FY "):
            return cleaned[3:].strip()
    return value


def _infer_time_grain(dimensions: list[str]) -> str:
    if "process_month" in dimensions:
        return "month"
    if "process_week" in dimensions:
        return "week"
    for dim in dimensions:
        if dim in {"process_date", "pdate", "date_day", "date"}:
            return "day"
    return "none"


def _build_rollup_query(
    rollup: dict,
    metric_name: str,
    dimensions: list[str],
    filters: list[dict],
    order_desc: bool,
    limit: int,
) -> tuple[str, list[object]] | None:
    rollup_dims = rollup.get("dimensions") or []
    rollup_table = rollup.get("rollup_table")
    if not rollup_table:
        return None

    # Ensure all filter fields are available in rollup
    filter_fields = []
    for flt in filters:
        payload = flt if isinstance(flt, dict) else flt.model_dump()
        field = payload.get("field")
        if field:
            filter_fields.append(field)
    if any(field not in rollup_dims for field in filter_fields):
        return None

    select_parts = []
    for dim in dimensions:
        select_parts.append(f"{rollup_table}.{dim} AS \"{dim}\"")
    select_parts.append(f"{rollup_table}.\"{metric_name}\" AS \"{metric_name}\"")

    where_parts: list[str] = []
    params: list[object] = []
    for flt in filters:
        payload = flt if isinstance(flt, dict) else flt.model_dump()
        field = payload.get("field")
        operator = payload.get("operator")
        value = payload.get("value")
        if not field or field not in rollup_dims:
            continue
        if operator == "IN":
            if not isinstance(value, (list, tuple)) or not value:
                return None
            placeholders = ",".join(["%s"] * len(value))
            where_parts.append(f"{rollup_table}.{field} IN ({placeholders})")
            params.extend(list(value))
        else:
            where_parts.append(f"{rollup_table}.{field} {operator} %s")
            params.append(value)

    where_clause = f" WHERE {' AND '.join(where_parts)}" if where_parts else ""
    order_clause = f' ORDER BY "{metric_name}" {"DESC" if order_desc else "ASC"}'
    sql = (
        f"SELECT {', '.join(select_parts)} FROM {rollup_table}"
        f"{where_clause}{order_clause} LIMIT {limit}"
    )
    return sql, params


def _coerce_sbu_filters(filters: list[dict]) -> list[dict]:
    sbu_names = {"AVIATION", "GAS", "I&C", "LPG", "LUBES", "PETCHEM", "RETAIL"}
    coerced = []
    for flt in filters:
        if isinstance(flt.get("value"), str) and flt["value"].strip().upper() in sbu_names:
            if flt.get("field") in {"psu_pvt", "region_name"}:
                coerced.append(
                    {"field": "sbu_name", "operator": flt["operator"], "value": flt["value"]}
                )
                continue
        coerced.append(flt)
    return coerced


def _coerce_product_filters(filters: list[dict]) -> list[dict]:
    product_names = {"MS", "HSD"}
    coerced = []
    for flt in filters:
        if flt.get("field") == "company_name" and isinstance(flt.get("value"), str):
            if flt["value"].strip().upper() in product_names:
                coerced.append(
                    {"field": "product_name", "operator": flt["operator"], "value": flt["value"]}
                )
                continue
        coerced.append(flt)
    return coerced


def _coerce_sbu_dimensions(dimensions: list[str], filters: list[dict]) -> list[str]:
    if "psu_pvt" not in dimensions:
        return dimensions
    for flt in filters:
        if flt.get("field") == "sbu_name":
            return [dim if dim != "psu_pvt" else "sbu_name" for dim in dimensions]
    return dimensions


def _resolve_this_month(settings: object) -> tuple[str | None, str | None]:
    sql = (
        "SELECT month_name, fiscal_year "
        "FROM public.fact_hpcl_sales_monthly_targets "
        "WHERE target_month IS NOT NULL "
        "ORDER BY target_month DESC LIMIT 1"
    )
    rows = run_query(settings, sql, [])
    if not rows:
        return None, None
    return rows[0].get("month_name"), rows[0].get("fiscal_year")


def _normalize_filters(filters: list[dict], settings: object) -> list[dict]:
    normalized = []
    month_name = None
    fiscal_year = None
    for flt in filters:
        value = flt.get("value")
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"last week start date", "last week end date"}:
                today = _date.today()
                last_week_end = today - _timedelta(days=today.weekday() + 1)
                last_week_start = last_week_end - _timedelta(days=6)
                if lowered == "last week start date":
                    normalized.append({"field": flt["field"], "operator": flt["operator"], "value": last_week_start.isoformat()})
                else:
                    normalized.append({"field": flt["field"], "operator": flt["operator"], "value": last_week_end.isoformat()})
                continue
        if isinstance(value, str) and value.strip().lower() == "this month":
            month_name, fiscal_year = _resolve_this_month(settings)
            if month_name:
                normalized.append({"field": "month_name", "operator": "=", "value": month_name})
            if fiscal_year:
                normalized.append({"field": "fiscal_year", "operator": "=", "value": fiscal_year})
            continue
        normalized.append(flt)
    return normalized


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = str(value or "").strip()
        if not key:
            continue
        marker = key.lower()
        if marker in seen:
            continue
        seen.add(marker)
        result.append(key)
    return result


def _expand_relative_date_filters(filters: list[dict]) -> list[dict]:
    expanded: list[dict] = []
    for flt in filters:
        value = flt.get("value")
        if isinstance(value, list) and len(value) == 1 and isinstance(value[0], str):
            value = value[0]
            flt = dict(flt)
            flt["value"] = value
        if isinstance(value, str) and value.strip().lower() == "last week" and flt.get("operator") == "IN":
            today = _date.today()
            last_week_end = today - _timedelta(days=today.weekday() + 1)
            last_week_start = last_week_end - _timedelta(days=6)
            expanded.append({"field": flt["field"], "operator": ">=", "value": last_week_start.isoformat()})
            expanded.append({"field": flt["field"], "operator": "<=", "value": last_week_end.isoformat()})
            continue
        if isinstance(value, str) and flt.get("operator") == "IN":
            lowered = value.strip().lower()
            match = re.match(r"last\\s+(\\d+)\\s+months", lowered)
            if match:
                months = int(match.group(1))
                today = _date.today()
                start = today - _timedelta(days=30 * months)
                expanded.append({"field": flt["field"], "operator": ">=", "value": start.isoformat()})
                expanded.append({"field": flt["field"], "operator": "<=", "value": today.isoformat()})
                continue
            if lowered in {"last three months", "last 3 months", "past three months", "past 3 months"}:
                today = _date.today()
                start = today - _timedelta(days=90)
                expanded.append({"field": flt["field"], "operator": ">=", "value": start.isoformat()})
                expanded.append({"field": flt["field"], "operator": "<=", "value": today.isoformat()})
                continue
        expanded.append(flt)
    return expanded


def _coerce_relative_date_filter_fields(
    filters: list[dict],
    allowed_dimensions: list[str] | None,
) -> list[dict]:
    if not allowed_dimensions:
        return filters
    allowed_set = {d.lower() for d in allowed_dimensions}
    if "process_date" not in allowed_set and "pdate" not in allowed_set and "date_day" not in allowed_set:
        return filters
    coerced = []
    for flt in filters:
        payload = flt if isinstance(flt, dict) else flt.model_dump()
        value = payload.get("value")
        if isinstance(value, str) and value.strip().lower() == "last week":
            if "process_date" in allowed_set:
                payload["field"] = "process_date"
            elif "pdate" in allowed_set:
                payload["field"] = "pdate"
            elif "date_day" in allowed_set:
                payload["field"] = "date_day"
        coerced.append(payload)
    return coerced


def _filter_dimension_filters(filters: list[dict], dimension_names: set[str]) -> list[dict]:
    filtered = []
    for flt in filters:
        if flt.get("field") in dimension_names:
            filtered.append(flt)
        else:
            logger.info("dropping non-dimension filter: %s", flt)
    return filtered


def _coerce_dimension_aliases(
    dimensions: list[str],
    filters: list[dict],
    catalog_dimensions: set[str],
    metric_dimensions: set[str],
) -> tuple[list[str], list[dict]]:
    alias_map: dict[str, str] = {}
    for dim in dimensions:
        if dim in metric_dimensions:
            continue
        if dim in {"plant", "plant_id"} and ("plant_name" in metric_dimensions or "plant_name" in catalog_dimensions):
            alias_map[dim] = "plant_name"
        elif dim in {"plant", "plant_id"} and ("sap_id" in metric_dimensions or "sap_id" in catalog_dimensions):
            alias_map[dim] = "sap_id"
        elif dim in {"pdate", "date_day", "date"} and ("process_date" in metric_dimensions or "process_date" in catalog_dimensions):
            alias_map[dim] = "process_date"
        elif f"{dim}_name" in metric_dimensions:
            alias_map[dim] = f"{dim}_name"

    if not alias_map:
        return dimensions, filters

    coerced_dimensions = [alias_map.get(dim, dim) for dim in dimensions]
    coerced_filters = []
    for flt in filters:
        payload = flt if isinstance(flt, dict) else flt.model_dump()
        field = payload.get("field")
        if isinstance(field, str) and field in alias_map:
            payload["field"] = alias_map[field]
        coerced_filters.append(payload)
    return coerced_dimensions, coerced_filters


def _coerce_dimensions_from_glossary(
    dimensions: list[str],
    filters: list[dict],
    glossary: list[dict] | None,
    fact_columns: set[str],
) -> tuple[list[str], list[dict]]:
    if not glossary or not fact_columns:
        return dimensions, filters
    synonym_map: dict[str, set[str]] = {}
    for term in glossary:
        synonyms = term.get("synonyms") or []
        normalized = term.get("normalized_term") or term.get("term")
        if not normalized:
            continue
        key = str(normalized).strip().lower()
        for syn in synonyms:
            if not syn:
                continue
            synonym_map.setdefault(str(syn).strip().lower(), set()).add(key)
            synonym_map.setdefault(key, set()).add(str(syn).strip().lower())
    if not synonym_map:
        return dimensions, filters
    def _map_dim(dim: str) -> str:
        if dim in fact_columns:
            return dim
        candidates = synonym_map.get(dim.lower(), set())
        for cand in candidates:
            if cand in fact_columns:
                return cand
        return dim
    coerced_dimensions = [_map_dim(dim) for dim in dimensions]
    coerced_filters = []
    for flt in filters:
        payload = flt if isinstance(flt, dict) else flt.model_dump()
        field = payload.get("field")
        if isinstance(field, str):
            payload["field"] = _map_dim(field)
        coerced_filters.append(payload)
    return coerced_dimensions, coerced_filters


def _expand_dimensions_from_glossary(
    dimensions: list[str],
    glossary: list[dict] | None,
    allowed_dimensions: list[str] | None,
) -> list[str]:
    if not glossary or not allowed_dimensions:
        return dimensions
    allowed_set = {d.lower() for d in allowed_dimensions}
    synonym_map: dict[str, set[str]] = {}
    for term in glossary:
        synonyms = term.get("synonyms") or []
        normalized = term.get("normalized_term") or term.get("term")
        if not normalized:
            continue
        key = str(normalized).strip().lower()
        for syn in synonyms:
            if not syn:
                continue
            synonym_map.setdefault(key, set()).add(str(syn).strip().lower())
            synonym_map.setdefault(str(syn).strip().lower(), set()).add(key)
    expanded = []
    for dim in dimensions:
        dim_l = dim.lower()
        if dim_l in allowed_set:
            expanded.append(dim)
        for syn in synonym_map.get(dim_l, set()):
            if syn in allowed_set:
                expanded.append(syn)
    # de-dupe while preserving order
    seen = set()
    result = []
    for dim in expanded:
        if dim not in seen:
            seen.add(dim)
            result.append(dim)
    return result


def _normalize_sales_quarter_filters(filters: list[dict], metric_names: list[str]) -> list[dict]:
    if "total_sales_volume_tmt" not in metric_names:
        return filters
    normalized = []
    for flt in filters:
        if flt.get("field") == "calendar_quarter":
            normalized.append(
                {"field": "calendar_quarter_sales", "operator": flt["operator"], "value": flt["value"]}
            )
            continue
        normalized.append(flt)
    return normalized


def _normalize_text_for_match(text: str) -> list[str]:
    cleaned = re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()
    tokens = [tok for tok in cleaned.split() if tok]
    return tokens


def _deterministic_metrics_from_question(question: str, catalog: MetricCatalog) -> list[str]:
    if not question:
        return []
    stopwords = {
        "the", "a", "an", "by", "of", "for", "in", "on", "to", "from", "last", "this",
        "that", "week", "month", "year", "today", "yesterday", "total", "vs", "and",
    }
    unit_tokens = {"mt", "tmt", "mmt", "kg", "kgs", "lakh", "cyl", "cyls", "percent", "pct"}
    q_tokens = [t for t in _normalize_text_for_match(question) if t not in stopwords]
    if not q_tokens:
        return []

    scored: list[tuple[float, int, str]] = []
    for name in catalog.metric_names():
        m_tokens_raw = _normalize_text_for_match(name)
        m_tokens = [t for t in m_tokens_raw if t not in stopwords]
        m_tokens_no_units = [t for t in m_tokens if t not in unit_tokens]
        base_tokens = m_tokens_no_units or m_tokens
        if not base_tokens:
            continue
        overlap = len(set(base_tokens) & set(q_tokens))
        score = overlap / max(1, len(set(base_tokens)))
        if score >= 0.5:
            scored.append((score, len(base_tokens), name))

    if not scored:
        return []
    scored.sort(key=lambda item: (-item[0], -item[1], item[2]))
    top_score = scored[0][0]
    winners = [name for score, _, name in scored if score == top_score]
    return winners[:1]


def _score_metric_match(question: str, metric_name: str) -> float:
    if not question or not metric_name:
        return 0.0
    stopwords = {
        "the", "a", "an", "by", "of", "for", "in", "on", "to", "from", "last", "this",
        "that", "week", "month", "year", "today", "yesterday", "total", "vs", "and",
    }
    q_tokens = [t for t in _normalize_text_for_match(question) if t not in stopwords]
    m_tokens = [t for t in _normalize_text_for_match(metric_name) if t not in stopwords]
    if not q_tokens or not m_tokens:
        return 0.0
    overlap = len(set(q_tokens) & set(m_tokens))
    return overlap / max(1, len(set(m_tokens)))


def _deterministic_dimensions_from_question(
    question: str,
    glossary: list[dict] | None,
    allowed_dimensions: list[str] | None,
) -> list[str]:
    if not question or not glossary or not allowed_dimensions:
        return []
    question_l = question.lower()
    question_tokens = set(_normalize_text_for_match(question))
    allowed_set = {d.lower() for d in allowed_dimensions}
    resolved: list[str] = []
    for term in glossary:
        normalized = term.get("normalized_term") or term.get("term")
        if not normalized:
            continue
        normalized_l = str(normalized).strip().lower()
        synonyms = [s for s in (term.get("synonyms") or []) if s]
        synonyms_l = [str(s).strip().lower() for s in synonyms]
        mention = normalized_l in question_l or normalized_l in question_tokens or any(
            s in question_l or s in question_tokens for s in synonyms_l
        )
        if not mention:
            continue
        # include all matching columns from normalized term + synonyms that exist in fact table
        if normalized_l in allowed_set:
            resolved.append(normalized_l)
        for syn_l in synonyms_l:
            if syn_l in allowed_set:
                resolved.append(syn_l)
    # de-dupe preserving order
    seen = set()
    result = []
    for dim in resolved:
        if dim not in seen:
            seen.add(dim)
            result.append(dim)
    if result:
        logger.info("resolver.deterministic_dim_match | question=%s dims=%s", question, result)
    return result


def _deterministic_date_filters_from_question(
    question: str,
    allowed_dimensions: list[str] | None,
) -> list[dict]:
    if not question or not allowed_dimensions:
        question_l = (question or "").lower()
        if "last week" in question_l:
            return [{"field": "process_date", "operator": "IN", "value": "last week"}]
        match = re.search(r"last\\s+(\\d+)\\s+months", question_l)
        if match:
            return [{"field": "process_date", "operator": "IN", "value": f"last {match.group(1)} months"}]
        if "last three months" in question_l or "last 3 months" in question_l:
            return [{"field": "process_date", "operator": "IN", "value": "last three months"}]
        return []
    question_l = question.lower()
    if "last week" not in question_l and "last three months" not in question_l and "last 3 months" not in question_l and not re.search(r"last\\s+\\d+\\s+months", question_l):
        return []
    allowed_set = {d.lower() for d in allowed_dimensions}
    date_field = None
    for candidate in ("process_date", "pdate", "date_day"):
        if candidate in allowed_set:
            date_field = candidate
            break
    if not date_field:
        return []
    if "last week" in question_l:
        return [{"field": date_field, "operator": "IN", "value": "last week"}]
    match = re.search(r"last\\s+(\\d+)\\s+months", question_l)
    if match:
        return [{"field": date_field, "operator": "IN", "value": f"last {match.group(1)} months"}]
    return [{"field": date_field, "operator": "IN", "value": "last three months"}]


def _strip_time_filters(filters: list[dict]) -> list[dict]:
    time_fields = {"process_date", "pdate", "date_day", "date"}
    stripped = []
    for flt in filters:
        payload = flt if isinstance(flt, dict) else flt.model_dump()
        field = payload.get("field")
        if isinstance(field, str) and field.lower() in time_fields:
            continue
        stripped.append(payload)
    return stripped


def _coerce_time_filter_fields(filters: list[dict], metric_dimension_set: set[str]) -> list[dict]:
    if not metric_dimension_set:
        return filters
    if "process_date" not in metric_dimension_set:
        return filters
    coerced = []
    for flt in filters:
        payload = flt if isinstance(flt, dict) else flt.model_dump()
        field = payload.get("field")
        value = payload.get("value")
        if isinstance(value, list) and len(value) == 1 and isinstance(value[0], str):
            value = value[0]
        if isinstance(field, str) and field not in metric_dimension_set:
            if isinstance(value, str) and ("last" in value.lower() or re.match(r"\\d{4}-\\d{2}-\\d{2}", value)):
                payload["field"] = "process_date"
            elif field.lower() in {"month_year", "month", "month_number"}:
                payload["field"] = "process_date"
        coerced.append(payload)
    return coerced


def _join_connected_tables(
    base_tables: set[str],
    join_edges: list[dict[str, Any]] | None,
) -> set[str]:
    normalized_bases = {_normalize_table_token(table) for table in base_tables if _normalize_table_token(table)}
    if not normalized_bases:
        return set()
    graph: dict[str, set[str]] = {}
    for edge in join_edges or []:
        if not isinstance(edge, dict):
            continue
        left = _normalize_table_token(edge.get("left_table") or edge.get("left"))
        right = _normalize_table_token(edge.get("right_table") or edge.get("right"))
        if not left or not right:
            continue
        graph.setdefault(left, set()).add(right)
        graph.setdefault(right, set()).add(left)
    visited = set(normalized_bases)
    pending = list(normalized_bases)
    while pending:
        current = pending.pop(0)
        for neighbor in graph.get(current, set()):
            if neighbor in visited:
                continue
            visited.add(neighbor)
            pending.append(neighbor)
    return visited


def _build_scoped_dimension_access(
    *,
    schema_name: str,
    metrics: list[Metric],
    join_edges: list[dict[str, Any]] | None,
    model_map: dict[str, dict[str, Any]] | None,
    scoped_conn: ScopedConnection | None = None,
) -> tuple[set[str], dict[str, list[str]], dict[str, str]]:
    base_tables = {
        _normalize_table_token(_infer_fact_table_from_metric_sql(metric.sql))
        for metric in metrics
        if _infer_fact_table_from_metric_sql(metric.sql)
    }
    accessible_tables = _join_connected_tables(base_tables, join_edges) | {table for table in base_tables if table}
    if not accessible_tables:
        return set(), {}, {}
    model_info = model_map or {}
    ranked_tables = sorted(
        accessible_tables,
        key=lambda table: (
            0 if (model_info.get(table) or {}).get("model_type") == "dimension" else 1,
            0 if table in base_tables else 1,
            table,
        ),
    )
    allowed_columns: set[str] = set()
    column_tables: dict[str, list[str]] = {}
    preferred_table_for_column: dict[str, str] = {}
    for table in ranked_tables:
        cols = [str(col) for col in _list_fact_table_columns(schema_name, table, scoped_conn=scoped_conn) if str(col or "").strip()]
        for col in cols:
            allowed_columns.add(col)
            column_tables.setdefault(col, [])
            if table not in column_tables[col]:
                column_tables[col].append(table)
            preferred_table_for_column.setdefault(col, table)
    return allowed_columns, column_tables, preferred_table_for_column


def _build_ad_hoc_dimension(
    *,
    dim_name: str,
    preferred_table: str | None,
    model_map: dict[str, dict[str, Any]] | None,
) -> Dimension | None:
    table = str(preferred_table or "").strip()
    if not table:
        return None
    model_type = (model_map or {}).get(_normalize_table_token(table), {}).get("model_type") or "scoped"
    quoted_dim_name = str(dim_name).replace('"', '""')
    return Dimension(
        name=dim_name,
        description=f"Ad-hoc {model_type} dimension from {table}",
        data_type="string",
        sql=f'{{{{ ref(\'{table}\') }}}}."{quoted_dim_name}"',
    )


def _load_persisted_hierarchy_overrides(
    *,
    tenant_id: str,
    domain_id: str,
    connection_id: str,
    database_name: str,
    schema_name: str,
) -> list[dict[str, Any]]:
    active_context_ids = list_active_context_ids(
        settings,
        tenant_id,
        domain_id,
        connection_id,
        database_name,
        schema_name,
    )
    _, hierarchy_overrides = load_overrides(
        settings,
        tenant_id,
        domain_id,
        connection_id=connection_id,
        database_name=database_name,
        schema_name=schema_name,
        context_ids=active_context_ids or None,
    )
    return hierarchy_overrides or []


def _artifact_lineage_snapshot(
    *,
    tenant_id: str | None,
    domain_id: str | None,
    run_id: str | None,
    connection_id: str | None,
    database_name: str | None,
    schema_name: str | None,
    bundle: dict[str, Any] | None,
    metrics: list[Metric],
) -> dict[str, Any] | None:
    if not tenant_id or not domain_id or not run_id:
        return None
    payload = bundle or {}
    selected_metric_names = {metric.name for metric in metrics}
    metric_rows = []
    for row in payload.get("metrics") or []:
        metric_name = str(row.get("metric_name") or "").strip()
        if metric_name and metric_name in selected_metric_names:
            metric_rows.append(
                {
                    "metric_name": metric_name,
                    "artifact_key": row.get("artifact_key"),
                    "version_no": row.get("version_no"),
                    "source_model": row.get("source_model"),
                    "dataset_id": row.get("dataset_id"),
                    "source_run_id": row.get("source_run_id"),
                }
            )
    return {
        "run_id": run_id,
        "scope": {
            "tenant_id": tenant_id,
            "domain_id": domain_id,
            "connection_id": connection_id,
            "database_name": database_name,
            "schema_name": schema_name,
        },
        "metrics": metric_rows,
        "joins": [
            {
                "artifact_key": row.get("artifact_key"),
                "version_no": row.get("version_no"),
                "left_table": row.get("left_table"),
                "right_table": row.get("right_table"),
            }
            for row in (payload.get("joins") or [])
        ],
        "models": [
            {
                "artifact_key": row.get("artifact_key"),
                "version_no": row.get("version_no"),
                "table_name": row.get("table_name"),
                "model_type": row.get("model_type"),
                "grain": row.get("grain"),
                "time_column": row.get("time_column"),
            }
            for row in (payload.get("models") or [])
        ],
        "facts": [
            {
                "artifact_key": row.get("artifact_key"),
                "version_no": row.get("version_no"),
                "table_name": row.get("table_name"),
                "source_run_id": row.get("source_run_id"),
            }
            for row in (payload.get("facts") or [])
        ],
        "dimensions": [
            {
                "artifact_key": row.get("artifact_key"),
                "version_no": row.get("version_no"),
                "name": row.get("name"),
                "source_run_id": row.get("source_run_id"),
            }
            for row in (payload.get("dimensions") or [])
        ],
        "glossary": [
            {
                "term": row.get("term"),
                "normalized_term": row.get("normalized_term"),
            }
            for row in (payload.get("glossary") or [])[:50]
        ],
        "hierarchies": [
            {
                "hierarchy_name": row.get("hierarchy_name"),
                "artifact_key": row.get("artifact_key"),
                "version_no": row.get("version_no"),
            }
            for row in (payload.get("hierarchies") or [])
        ],
        "schema_graph": {
            "artifact_key": (payload.get("schema_graph_row") or {}).get("artifact_key"),
            "version_no": (payload.get("schema_graph_row") or {}).get("version_no"),
        },
        "table_profiles": {
            "artifact_key": (payload.get("table_profile_row") or {}).get("artifact_key"),
            "version_no": (payload.get("table_profile_row") or {}).get("version_no"),
        },
    }


def _validate_metric_semantics(
    *,
    metrics: list[Metric],
    dimensions: list[str],
    filters: list[dict[str, Any]],
    model_map: dict[str, dict[str, Any]] | None,
) -> dict[str, Any] | None:
    if not metrics:
        return None
    model_lookup = model_map or {}
    signatures: set[tuple[str, str]] = set()
    time_supported = False
    metric_details: list[dict[str, Any]] = []
    for metric in metrics:
        base_table = _infer_fact_table_from_metric_sql(metric.sql)
        model_info = _model_info_for_base_table(model_lookup, base_table)
        grain = str((model_info.get("grain") or metric.grain or "unknown")).strip().lower()
        time_column = str(model_info.get("time_column") or "").strip()
        if time_column:
            time_supported = True
        signatures.add((grain, time_column))
        metric_details.append(
            {
                "metric_name": metric.name,
                "base_table": base_table,
                "grain": grain,
                "time_column": time_column or None,
                "model_type": model_info.get("model_type"),
            }
        )
    temporal_fields = {str(dim).strip().lower() for dim in dimensions if str(dim).strip()}
    temporal_fields.update(
        str((flt or {}).get("field") or "").strip().lower()
        for flt in filters
        if isinstance(flt, dict)
    )
    requests_time = bool(
        temporal_fields
        & {"process_month", "process_date", "date_day", "pdate", "date", "week", "month_name", "fiscal_year"}
    )
    if len(signatures) > 1:
        return {
            "message": "Selected metrics have incompatible semantic grains for one query",
            "issue": "grain_conflict",
            "metrics": metric_details,
        }
    if requests_time and not time_supported:
        return {
            "message": "Selected metrics do not support time-based grouping or filtering",
            "issue": "missing_time_support",
            "metrics": metric_details,
            "dimensions": dimensions,
            "filters": filters,
        }
    return None


def _extract_top_n(question: str | None) -> int | None:
    if not question:
        return None
    lowered = question.lower()
    if "top" not in lowered:
        return None
    match = re.search(r"top\\s+(\\d+)", lowered)
    if match:
        return int(match.group(1))
    return 5


def _infer_sort_desc(question: str | None) -> bool:
    if not question:
        return True
    lowered = question.lower()
    if "ascending" in lowered or "asc" in lowered:
        return False
    if "descending" in lowered or "desc" in lowered:
        return True
    return True


def _infer_fact_table_from_metric_sql(metric_sql: str) -> str | None:
    match = re.search(r"ref\('([^']+)'\)", metric_sql or "")
    if match:
        return match.group(1)
    match = re.search(r'ref\\(\"([^\"]+)\"\\)', metric_sql or "")
    if match:
        return match.group(1)
    return None


def _infer_table_from_dimension_sql(dim_sql: str) -> str | None:
    match = re.search(r"ref\('([^']+)'\)", dim_sql or "")
    if match:
        return match.group(1)
    match = re.search(r'ref\(\"([^\"]+)\"\)', dim_sql or "")
    if match:
        return match.group(1)
    return None


def _normalize_table_token(value: object) -> str:
    return str(value or "").split(".")[-1].strip().lower()


def _model_info_for_base_table(
    model_map: dict[str, dict[str, Any]] | None,
    base_table: str | None,
) -> dict[str, Any]:
    normalized = _normalize_table_token(base_table)
    if not normalized:
        return {}
    lookup = model_map or {}
    direct = lookup.get(normalized)
    if direct:
        return direct
    candidates = [normalized]
    if normalized.startswith("fact_"):
        candidates.append(normalized.removeprefix("fact_"))
    else:
        candidates.append(f"fact_{normalized}")
    for candidate in candidates:
        if candidate in lookup:
            return lookup[candidate]
    return {}


def _build_model_intelligence_map(bundle: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    payload = bundle or {}
    models = payload.get("models") or []
    agent_artifacts = payload.get("agent_artifacts") or {}
    profile_tables: list[dict[str, Any]] = []
    table_profile_artifact = payload.get("table_profile_artifact")
    if isinstance(table_profile_artifact, dict):
        profile_tables.extend(table_profile_artifact.get("tables") or [])
    profile_tables.extend(agent_artifacts.get("ProfilingAgent", {}).get("profiles") or [])
    profile_map: dict[str, dict[str, Any]] = {}
    for table in profile_tables:
        if not isinstance(table, dict):
            continue
        table_name = _normalize_table_token(table.get("name") or table.get("table"))
        if table_name and table_name not in profile_map:
            profile_map[table_name] = table

    model_rows = list(models)
    if not model_rows:
        model_rows = agent_artifacts.get("SemanticModelAgent", {}).get("model_classifications_detail") or []

    model_map: dict[str, dict[str, Any]] = {}
    for row in model_rows:
        if not isinstance(row, dict):
            continue
        table_name = _normalize_table_token(row.get("table_name") or row.get("table") or row.get("name"))
        if not table_name:
            continue
        profile = profile_map.get(table_name) or {}
        time_columns = [
            str(value).strip()
            for value in (profile.get("time_columns") or [])
            if str(value or "").strip()
        ]
        time_column = (
            row.get("time_column")
            or (row.get("metadata") or {}).get("time_column")
            or (time_columns[0] if time_columns else None)
        )
        grain = row.get("grain") or (row.get("metadata") or {}).get("grain")
        if not grain and time_column:
            grain = "day"
        model_map[table_name] = {
            "table_name": table_name,
            "model_type": str(row.get("model_type") or (row.get("metadata") or {}).get("model_type") or "").strip().lower() or None,
            "grain": str(grain or "").strip().lower() or None,
            "time_column": str(time_column or "").strip() or None,
            "confidence": row.get("confidence"),
            "numeric_columns": row.get("numeric_columns") or profile.get("numeric_columns") or [],
            "categorical_columns": row.get("categorical_columns") or profile.get("categorical_columns") or [],
            "time_columns": time_columns,
        }
    return model_map


def _metric_debug_payload(metric: Metric, model_map: dict[str, dict[str, Any]] | None = None) -> dict[str, object]:
    base_table = _infer_fact_table_from_metric_sql(metric.sql)
    model_info = (model_map or {}).get(_normalize_table_token(base_table))
    return {
        "name": metric.name,
        "base_table": base_table,
        "dimensions": list(metric.dimensions or []),
        "metric_type": metric.metric_type,
        "grain": metric.grain,
        "model_type": (model_info or {}).get("model_type"),
        "time_column": (model_info or {}).get("time_column"),
        "sql_preview": (metric.sql or "")[:160],
    }


def _question_supports_multi_metric(question: str | None) -> bool:
    lowered = str(question or "").lower()
    if not lowered:
        return False
    markers = (
        " vs ",
        " versus ",
        "compare",
        "comparison",
        "between",
        "difference",
        "ratio",
        "split by",
        "alongside",
        "required run rate",
        "achievement",
        "actual vs",
        "target vs",
        "actual and target",
    )
    return any(marker in lowered for marker in markers)


def _select_metrics_with_model_intelligence(
    *,
    metrics: list[Metric],
    question: str | None,
    dimensions: list[str],
    filters: list[dict[str, Any]],
    model_map: dict[str, dict[str, Any]] | None,
) -> tuple[list[Metric], dict[str, Any]]:
    if not metrics or not model_map:
        return metrics, {"reason": "no_model_intelligence"}

    filter_fields = {
        str((flt or {}).get("field") or "").strip()
        for flt in filters
        if isinstance(flt, dict) and str((flt or {}).get("field") or "").strip()
    }
    requested_dimensions = {str(dim).strip() for dim in dimensions if str(dim or "").strip()}
    candidates: list[dict[str, Any]] = []
    for metric in metrics:
        base_table = _infer_fact_table_from_metric_sql(metric.sql)
        model_info = _model_info_for_base_table(model_map, base_table)
        metric_dimensions = set(metric.dimensions or [])
        dimension_support = len(requested_dimensions & metric_dimensions) + len(filter_fields & metric_dimensions)
        lexical_score = _score_metric_match(question or "", metric.name)
        fact_bonus = 0.35 if (model_info or {}).get("model_type") == "fact" else 0.0
        time_bonus = 0.1 if (model_info or {}).get("time_column") and any("month" in dim.lower() or "date" in dim.lower() for dim in requested_dimensions | filter_fields) else 0.0
        final_score = lexical_score + fact_bonus + time_bonus + (0.05 * dimension_support)
        candidates.append(
            {
                "metric": metric,
                "metric_name": metric.name,
                "base_table": base_table,
                "model_type": (model_info or {}).get("model_type"),
                "grain": (model_info or {}).get("grain") or metric.grain or None,
                "time_column": (model_info or {}).get("time_column"),
                "dimension_support": dimension_support,
                "lexical_score": lexical_score,
                "score": final_score,
            }
        )

    # In multi-metric queries, don't discard non-fact table metrics — the user
    # explicitly asked for them (e.g. TARGET_QTY_TMT from a dimension table).
    # Only apply the fact-preference filter for single-metric disambiguation.
    is_multi_metric = _question_supports_multi_metric(question) or len(metrics) > 1
    if is_multi_metric:
        working = candidates
        dropped_non_fact = []
    else:
        fact_candidates = [item for item in candidates if item.get("model_type") == "fact"]
        working = fact_candidates or candidates
        dropped_non_fact = [item for item in candidates if item not in working]

    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for item in working:
        signature = (
            str(item.get("grain") or "unknown"),
            str(item.get("time_column") or ""),
        )
        grouped.setdefault(signature, []).append(item)

    chosen_signature = None
    if len(grouped) > 1 and not is_multi_metric:
        scored_groups = []
        for signature, items in grouped.items():
            group_score = sum(float(entry.get("score") or 0.0) for entry in items)
            scored_groups.append((group_score, len(items), signature))
        scored_groups.sort(key=lambda item: (-item[0], -item[1], item[2]))
        chosen_signature = scored_groups[0][2]
        working = grouped[chosen_signature]

    if not _question_supports_multi_metric(question) and len(working) > 1:
        working = sorted(
            working,
            key=lambda item: (-float(item.get("score") or 0.0), item.get("metric_name") or ""),
        )[:1]

    selected = [item["metric"] for item in working]
    return selected, {
        "reason": "model_pruned",
        "candidate_count": len(candidates),
        "selected_count": len(selected),
        "chosen_signature": chosen_signature,
        "dropped_non_fact": [item.get("metric_name") for item in dropped_non_fact],
        "candidates": [
            {
                "metric_name": item.get("metric_name"),
                "base_table": item.get("base_table"),
                "model_type": item.get("model_type"),
                "grain": item.get("grain"),
                "time_column": item.get("time_column"),
                "dimension_support": item.get("dimension_support"),
                "lexical_score": round(float(item.get("lexical_score") or 0.0), 3),
                "score": round(float(item.get("score") or 0.0), 3),
                "selected": item["metric"] in selected,
            }
            for item in sorted(
                candidates,
                key=lambda entry: (-float(entry.get("score") or 0.0), str(entry.get("metric_name") or "")),
            )
        ],
    }


def _catalog_from_registry_rows(rows: list[dict[str, object]], dimensions: dict[str, Dimension]) -> MetricCatalog:
    metrics: dict[str, Metric] = {}
    for row in rows:
        sql = str(row.get("sql") or "").strip()
        if not sql:
            continue
        metric_name = str(row.get("metric_name") or row.get("metric_id") or "").strip()
        if not metric_name:
            continue
        dimensions_list = row.get("dimensions") or []
        if not isinstance(dimensions_list, list):
            dimensions_list = []
        metric_obj = Metric(
            name=metric_name,
            description=str(row.get("description") or ""),
            metric_type=str(row.get("type") or ""),
            sql=sql,
            grain=str(row.get("grain") or ""),
            dimensions=[str(item) for item in dimensions_list if str(item or "").strip()],
            status=str(row.get("lifecycle_status") or "") or None,
            owner=str(row.get("owner") or "") or None,
            version=str(row.get("version") or "") or None,
        )
        metrics[metric_name] = metric_obj
        display_name = str(row.get("display_name") or "").strip()
        if display_name and display_name != metric_name and display_name not in metrics:
            metrics[display_name] = Metric(
                name=display_name,
                description=metric_obj.description,
                metric_type=metric_obj.metric_type,
                sql=metric_obj.sql,
                grain=metric_obj.grain,
                dimensions=list(metric_obj.dimensions),
                status=metric_obj.status,
                owner=metric_obj.owner,
                version=metric_obj.version,
            )
    return MetricCatalog(metrics=metrics, dimensions=dimensions)


def _latest_completed_agent_raw_artifacts(run_id: str) -> dict[str, dict[str, Any]]:
    rows = list_agent_run_events_stage_aware(settings, run_id, limit=5000)
    completed_events = [
        row
        for row in rows
        if row.get("agent_name")
        and ((row.get("stage_name") == "completed") or (row.get("status") == "completed"))
    ]
    artifact_by_event_id: dict[str, dict[str, Any]] = {}
    event_ids = [str(row.get("event_id")) for row in completed_events if row.get("event_id")]
    if event_ids:
        try:
            artifact_by_event_id = list_agent_event_artifacts_by_event_ids(settings, run_id, event_ids)
        except Exception:
            artifact_by_event_id = {}
    latest: dict[str, dict[str, Any]] = {}
    for row in completed_events:
        agent_name = str(row.get("agent_name") or "").strip()
        if not agent_name:
            continue
        event_id = str(row.get("event_id") or "")
        artifact_row = artifact_by_event_id.get(event_id) or {}
        raw_json = artifact_row.get("raw_json")
        if not isinstance(raw_json, dict):
            artifacts = row.get("artifacts") or {}
            if isinstance(artifacts, dict) and isinstance(artifacts.get("raw_json"), dict):
                raw_json = artifacts.get("raw_json")
            elif isinstance(artifacts, dict):
                raw_json = artifacts
        latest[agent_name] = raw_json if isinstance(raw_json, dict) else {}
    return latest


def _extract_bundle_glossary_terms(agent_artifacts: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []

    def _add_term(term: str, *, synonyms: list[str] | None = None, abbreviations: list[str] | None = None) -> None:
        normalized = str(term or "").strip().lower()
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        out.append(
            {
                "term": str(term).strip(),
                "normalized_term": normalized,
                "definition": None,
                "synonyms": synonyms or [],
                "abbreviations": abbreviations or [],
            }
        )

    for item in agent_artifacts.get("ContextAgent", {}).get("glossary_terms") or []:
        if isinstance(item, dict):
            _add_term(
                str(item.get("term") or "").strip(),
                synonyms=[str(v) for v in (item.get("synonyms") or []) if str(v).strip()],
                abbreviations=[str(v) for v in (item.get("abbreviations") or []) if str(v).strip()],
            )
    for item in agent_artifacts.get("GlossaryAgent", {}).get("terms_detail") or []:
        if isinstance(item, dict):
            _add_term(
                str(item.get("term") or "").strip(),
                synonyms=[str(v) for v in (item.get("synonyms") or []) if str(v).strip()],
                abbreviations=[str(v) for v in (item.get("abbreviations") or []) if str(v).strip()],
            )
    for concept in agent_artifacts.get("OntologyAgent", {}).get("concepts_detail") or []:
        if concept:
            _add_term(str(concept))
    return out


def _artifact_dimension_candidates(
    facts_rows: list[dict[str, Any]],
    dimension_rows: list[dict[str, Any]],
    agent_artifacts: dict[str, dict[str, Any]],
) -> list[str]:
    names: list[str] = []
    for row in facts_rows:
        for value in (row.get("dimensions") or []):
            if value:
                names.append(str(value))
        if row.get("time_column"):
            names.append(str(row.get("time_column")))
    for row in dimension_rows:
        if row.get("name"):
            names.append(str(row.get("name")))
        for value in (row.get("keys") or []):
            if value:
                names.append(str(value))
        for value in (row.get("attributes") or []):
            if value:
                names.append(str(value))
    for table in agent_artifacts.get("SchemaAgent", {}).get("tables_detail") or []:
        if isinstance(table, dict):
            for col in table.get("columns") or []:
                if isinstance(col, dict) and col.get("name"):
                    names.append(str(col.get("name")))
    for table in agent_artifacts.get("ProfilingAgent", {}).get("profiles") or []:
        if isinstance(table, dict):
            for key in (
                "categorical_columns",
                "time_columns",
                "eligible_numeric_columns",
                "numeric_columns",
            ):
                for value in table.get(key) or []:
                    if value:
                        names.append(str(value))
    for edge in agent_artifacts.get("JoinAgent", {}).get("join_edges_detail") or []:
        if isinstance(edge, dict):
            for key in ("left_key", "right_key"):
                value = edge.get(key)
                if value:
                    names.append(str(value))
    for model in agent_artifacts.get("SemanticModelAgent", {}).get("model_classifications_detail") or []:
        if isinstance(model, dict):
            for key in ("time_column",):
                value = model.get(key)
                if value:
                    names.append(str(value))
    deduped: list[str] = []
    seen: set[str] = set()
    for name in names:
        normalized = name.strip().lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(name.strip())
    return deduped


def _load_run_scoped_intelligence(
    *,
    tenant_id: str,
    domain_id: str,
    run_id: str | None,
    connection_id: str,
    database_name: str,
    schema_name: str,
) -> dict[str, Any]:
    persisted_glossary = fetch_glossary_terms(settings, tenant_id, domain_id)
    if run_id:
        facts_rows = list_facts_by_run(settings, run_id)
        dimension_rows = list_dimensions_by_run(settings, run_id)
        # Fall back to tenant-scoped query if this run has no facts/dims yet
        if not facts_rows:
            facts_rows = list_facts(settings, tenant_id, domain_id, connection_id, database_name, schema_name)
        if not dimension_rows:
            dimension_rows = list_dimensions(settings, tenant_id, domain_id, connection_id, database_name, schema_name)
    else:
        facts_rows = list_facts(settings, tenant_id, domain_id, connection_id, database_name, schema_name)
        dimension_rows = list_dimensions(settings, tenant_id, domain_id, connection_id, database_name, schema_name)
    metrics_rows = fetch_registry_metrics(
        settings,
        tenant_id=tenant_id,
        domain_id=domain_id,
        connection_id=connection_id,
        database_name=database_name,
        schema_name=schema_name,
        source_run_id=run_id,
        include_all_statuses=True,
    ) if run_id else fetch_registry_metrics(
        settings,
        tenant_id=tenant_id,
        domain_id=domain_id,
        connection_id=connection_id,
        database_name=database_name,
        schema_name=schema_name,
        include_all_statuses=True,
    )
    agent_artifacts = _latest_completed_agent_raw_artifacts(run_id) if run_id else {}
    schema_graph_artifact = (
        get_schema_graph_artifact(
            settings,
            tenant_id=tenant_id,
            domain_id=domain_id,
            run_id=run_id,
            connection_id=connection_id,
            database_name=database_name,
            schema_name=schema_name,
        )
        if run_id
        else None
    )
    table_profile_artifact = (
        get_table_profile_artifact(
            settings,
            tenant_id=tenant_id,
            domain_id=domain_id,
            run_id=run_id,
            connection_id=connection_id,
            database_name=database_name,
            schema_name=schema_name,
        )
        if run_id
        else None
    )
    joins = (
        list_join_registry(
            settings,
            tenant_id=tenant_id,
            domain_id=domain_id,
            run_id=run_id,
            connection_id=connection_id,
            database_name=database_name,
            schema_name=schema_name,
        )
        if run_id
        else []
    )
    models = (
        list_model_registry(
            settings,
            tenant_id=tenant_id,
            domain_id=domain_id,
            run_id=run_id,
            connection_id=connection_id,
            database_name=database_name,
            schema_name=schema_name,
        )
        if run_id
        else []
    )
    hierarchies = _load_persisted_hierarchy_overrides(
        tenant_id=tenant_id,
        domain_id=domain_id,
        connection_id=connection_id,
        database_name=database_name,
        schema_name=schema_name,
    )
    if schema_graph_artifact and isinstance(schema_graph_artifact.get("graph_json"), dict):
        agent_artifacts.setdefault("SchemaAgent", {})
        agent_artifacts["SchemaAgent"].setdefault("tables_detail", (schema_graph_artifact.get("graph_json") or {}).get("tables", []))
    if table_profile_artifact and isinstance(table_profile_artifact.get("profiling_json"), dict):
        agent_artifacts.setdefault("ProfilingAgent", {})
        agent_artifacts["ProfilingAgent"].setdefault("profiles", (table_profile_artifact.get("profiling_json") or {}).get("tables", []))
    bundle_glossary = _extract_bundle_glossary_terms(agent_artifacts)
    glossary_map: dict[str, dict[str, Any]] = {}
    for row in persisted_glossary + bundle_glossary:
        term = str((row or {}).get("term") or "").strip()
        normalized = str((row or {}).get("normalized_term") or term.lower()).strip()
        if not term and not normalized:
            continue
        glossary_map[normalized or term.lower()] = {
            "term": term or normalized,
            "normalized_term": normalized or term.lower(),
            "definition": (row or {}).get("definition"),
            "synonyms": (row or {}).get("synonyms") or [],
            "abbreviations": (row or {}).get("abbreviations") or [],
        }
    dimension_candidates = _artifact_dimension_candidates(facts_rows, dimension_rows, agent_artifacts)
    return {
        "run_id": run_id,
        "facts": facts_rows,
        "dimensions": dimension_rows,
        "metrics": metrics_rows,
        "glossary": list(glossary_map.values()),
        "hierarchies": hierarchies,
        "joins": joins,
        "models": models,
        "schema_graph_row": schema_graph_artifact,
        "schema_graph_artifact": schema_graph_artifact.get("graph_json") if schema_graph_artifact else None,
        "table_profile_row": table_profile_artifact,
        "table_profile_artifact": table_profile_artifact.get("profiling_json") if table_profile_artifact else None,
        "agent_artifacts": agent_artifacts,
        "dimension_candidates": dimension_candidates,
    }


def _missing_required_intelligence(bundle: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    # In LLM-first SQL mode the LLM generates SQL directly from table schemas —
    # only the profiling artifact is strictly required; semantic layer artifacts
    # (metrics, facts, dimensions, models, glossary, joins) are optional.
    llm_sql_mode = os.getenv("CONVERSATION_LLM_SQL_MODE", "").lower() in ("true", "1", "yes")
    if not (bundle.get("schema_graph_artifact") or (bundle.get("agent_artifacts") or {}).get("SchemaAgent")):
        missing.append("schema_graph")
    if not (bundle.get("table_profile_artifact") or (bundle.get("agent_artifacts") or {}).get("ProfilingAgent")):
        missing.append("table_profiles")
    if llm_sql_mode:
        # Table profiles are sufficient for LLM SQL mode — skip semantic layer checks
        return missing
    if not (bundle.get("glossary") or (bundle.get("agent_artifacts") or {}).get("ContextAgent") or (bundle.get("agent_artifacts") or {}).get("GlossaryAgent") or (bundle.get("agent_artifacts") or {}).get("OntologyAgent")):
        missing.append("glossary_ontology")
    if not (bundle.get("joins") or (bundle.get("agent_artifacts") or {}).get("JoinAgent")):
        missing.append("joins")
    if not (bundle.get("models") or (bundle.get("agent_artifacts") or {}).get("SemanticModelAgent")):
        missing.append("semantic_models")
    if not (bundle.get("metrics") or []):
        missing.append("metrics")
    if not (bundle.get("facts") or []):
        missing.append("facts")
    if not (bundle.get("dimensions") or []):
        missing.append("dimensions")
    return missing


def _list_fact_table_columns(schema_name: str, table_name: str, scoped_conn: ScopedConnection | None = None) -> list[str]:
    if not schema_name or not table_name:
        return []
    # dbt model names are prefixed with "fact_" or "dim_" but the actual PostgreSQL
    # table has no such prefix. Strip it so the information_schema lookup succeeds.
    _raw_name = table_name
    for _prefix in ("fact_", "dim_"):
        if _raw_name.lower().startswith(_prefix):
            _raw_name = _raw_name[len(_prefix):]
            break
    sql = """
        SELECT column_name
          FROM information_schema.columns
         WHERE table_schema = %s
           AND lower(table_name) = lower(%s)
         ORDER BY ordinal_position
    """
    try:
        rows = run_query(settings, sql, [schema_name, _raw_name], scoped_conn=scoped_conn)
    except Exception:
        return []
    return [row.get("column_name") for row in rows if row.get("column_name")]


def _fact_columns_for_metric(metric_sql: str, schema_name: str, scoped_conn: ScopedConnection | None = None) -> set[str]:
    fact_table = _infer_fact_table_from_metric_sql(metric_sql)
    if not fact_table:
        return set()
    return set(_list_fact_table_columns(schema_name, fact_table, scoped_conn=scoped_conn))


def _augment_catalog_dimensions_from_facts(
    tenant_id: str,
    domain_id: str,
    connection_id: str,
    database_name: str,
    schema_name: str,
) -> None:
    if not tenant_id or not domain_id or not connection_id or not database_name or not schema_name:
        return
    facts = list_facts(
        settings,
        tenant_id=tenant_id,
        domain_id=domain_id,
        connection_id=connection_id,
        database_name=database_name,
        schema_name=schema_name,
    )
    if not facts:
        return
    added = 0
    for fact in facts:
        table_name = fact.get("table_name")
        if not table_name:
            continue
        db_dims = _list_fact_table_columns(schema_name, table_name, scoped_conn=_resolve_scoped_conn(tenant_id, domain_id))
        if not db_dims:
            continue
        for dim in db_dims:
            if dim in catalog.dimensions:
                continue
            catalog.dimensions[dim] = Dimension(
                name=dim,
                description=f"Auto-detected from {table_name}",
                data_type="string",
                sql=f"{{{{ ref('{table_name}') }}}}.{dim}",
            )
            added += 1
    if added:
        logger.info("catalog.dimensions augmented from facts | added=%s", added)


def _dimension_candidates_for_scope(
    tenant_id: str,
    domain_id: str,
    connection_id: str,
    database_name: str,
    schema_name: str,
) -> list[str]:
    candidates: set[str] = set()
    facts = list_facts(
        settings,
        tenant_id=tenant_id,
        domain_id=domain_id,
        connection_id=connection_id,
        database_name=database_name,
        schema_name=schema_name,
    )
    for fact in facts:
        table_name = fact.get("table_name")
        if not table_name:
            continue
        db_dims = _list_fact_table_columns(schema_name, table_name, scoped_conn=_resolve_scoped_conn(tenant_id, domain_id))
        candidates.update(db_dims)
    return sorted(candidates)


@app.post(
    "/query",
    response_model=QueryResult,
    tags=["ask"],
    summary="Run a query",
    description="Resolve a question or structured request into SQL and return results.",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "sales_volume_top5": {
                            "summary": "Top 5 plants (LPG production)",
                            "value": {
                                "question": "Top 5 LPG plants by production last week.",
                                "tenant_id": "VC_101",
                                "domain_id": "lpg_production_distribution",
                                "limit": 100,
                                "explain": True,
                            },
                        },
                        "hpcl_vs_bpcl": {
                            "summary": "Production by region (last 3 months)",
                            "value": {
                                "question": "Total LPG production by region for last three months.",
                                "tenant_id": "VC_101",
                                "domain_id": "lpg_production_distribution",
                                "limit": 100,
                                "explain": True,
                            },
                        },
                        "run_rate_risk": {
                            "summary": "Plant production trend",
                            "value": {
                                "question": "LPG production trend by plant for last 6 months.",
                                "tenant_id": "VC_101",
                                "domain_id": "lpg_production_distribution",
                                "limit": 100,
                                "explain": True,
                            },
                        },
                    }
                }
            }
        },
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "result_rows": {
                                "summary": "Query response",
                                "value": {
                                    "metrics": ["production_mt"],
                                    "dimensions": ["region", "process_month"],
                                    "chart_id": "chart_2f7a9c4d",
                                    "sql": "SELECT region, to_char(date_trunc('month', process_date), 'Mon-YY') AS process_month, SUM(...) AS production_mt FROM public.fact_lpg_plant_operations WHERE process_date >= %s AND process_date <= %s GROUP BY region, process_month ORDER BY production_mt DESC LIMIT 100",
                                    "rows": [
                                        {
                                            "region": "BANGALORE LPG RO",
                                            "process_month": "Jan-26",
                                            "production_mt": "39694.3732"
                                        }
                                    ],
                                    "by_company_sql": None,
                                    "by_company_rows": None,
                                },
                            }
                        }
                    }
                }
            }
        },
    },
)
def query(request: QueryRequest) -> QueryResult:
    start_time = time.perf_counter()
    last_step = start_time
    def _log_step(name: str) -> None:
        nonlocal last_step
        now = time.perf_counter()
        logger.info("query.timing | step=%s elapsed_ms=%.1f total_ms=%.1f",
                    name, (now - last_step) * 1000, (now - start_time) * 1000)
        last_step = now
    sql_text = None
    row_count = None
    glossary = None
    contract = None
    domain_id = None
    query_catalog = catalog
    intelligence_bundle: dict[str, Any] | None = None
    scoped_join_edges: list[dict[str, Any]] = []
    model_intelligence_map: dict[str, dict[str, Any]] = {}
    logger.info("query.start | tenant=%s domain=%s question=%s metric=%s metrics=%s dims=%s filters=%s limit=%s",
                request.tenant_id, request.domain_id, request.question, request.metric, request.metrics,
                request.dimensions, request.filters, request.limit)
    fact_dims_map: dict[str, set[str]] = {}
    dimension_candidates: list[str] | None = None
    scoped_metric_names: set[str] | None = None
    cached_payload = None
    if request.question and request.tenant_id:
        logger.info("query.cache_lookup | tenant=%s question=%s", request.tenant_id, request.question)
        cached = get_latest_chart_request_by_question(
            settings,
            tenant_id=request.tenant_id,
            question=request.question,
        )
        if cached and cached.get("query_payload"):
            cached_payload = cached.get("query_payload")
            if isinstance(cached_payload, str):
                try:
                    cached_payload = json.loads(cached_payload)
                except json.JSONDecodeError:
                    cached_payload = None
            logger.info("query.cache_hit | chart_id=%s", cached.get("chart_id"))
        else:
            logger.info("query.cache_miss")

    if request.tenant_id:
        domain_id = _resolve_domain_id(request.tenant_id, request.domain_id)
        effective_run_id = request.run_id
        if not effective_run_id:
            deployment = get_current_deployment(settings, request.tenant_id, domain_id)
            if deployment:
                effective_run_id = deployment.get("run_id")
        if not effective_run_id:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "No completed deployment available for tenant/domain",
                    "tenant_id": request.tenant_id,
                    "domain_id": domain_id,
                },
            )
        connection_id, database_name, schema_name, tables = _resolve_scope_values(
            request.tenant_id,
            domain_id,
        )
        _query_scoped_conn = _resolve_scoped_conn(request.tenant_id, domain_id)
        intelligence_bundle = _load_run_scoped_intelligence(
            tenant_id=request.tenant_id,
            domain_id=domain_id,
            run_id=effective_run_id,
            connection_id=connection_id,
            database_name=database_name,
            schema_name=schema_name,
        )
        logger.info("query.scope | domain=%s connection=%s db=%s schema=%s tables=%s",
                    domain_id, connection_id, database_name, schema_name, tables)
        logger.info(
            "query.intelligence_bundle | requested_run_id=%s effective_run_id=%s metrics=%s facts=%s dimensions=%s glossary=%s hierarchies=%s artifact_agents=%s dimension_candidates=%s",
            request.run_id,
            effective_run_id,
            len((intelligence_bundle or {}).get("metrics") or []),
            len((intelligence_bundle or {}).get("facts") or []),
            len((intelligence_bundle or {}).get("dimensions") or []),
            len((intelligence_bundle or {}).get("glossary") or []),
            len((intelligence_bundle or {}).get("hierarchies") or []),
            sorted(list(((intelligence_bundle or {}).get("agent_artifacts") or {}).keys())),
            len((intelligence_bundle or {}).get("dimension_candidates") or []),
        )
        model_intelligence_map = _build_model_intelligence_map(intelligence_bundle)
        logger.info(
            "query.model_scope | count=%s sample=%s",
            len(model_intelligence_map),
            list(model_intelligence_map.values())[:10],
        )
        scoped_join_edges = [dict(item) for item in ((intelligence_bundle or {}).get("joins") or []) if isinstance(item, dict)]
        active_semantic_state = load_active_semantic_state(
            settings,
            tenant_id=request.tenant_id,
            domain_id=domain_id,
            connection_id=connection_id,
            database_name=database_name,
            schema_name=schema_name,
        )
        if active_semantic_state:
            join_constraints = semantic_join_constraints(active_semantic_state)
            scoped_join_edges, removed_join_edges = apply_join_constraints_to_edges(scoped_join_edges, join_constraints)
            if removed_join_edges:
                logger.info(
                    "query.semantic_constraints | removed_joins=%s constraints=%s",
                    len(removed_join_edges),
                    join_constraints,
                )
        missing_artifacts = _missing_required_intelligence(intelligence_bundle or {})
        if missing_artifacts:
            logger.error(
                "query.fail | reason=incomplete_intelligence requested_run_id=%s effective_run_id=%s missing=%s",
                request.run_id,
                effective_run_id,
                missing_artifacts,
            )
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "Deployment intelligence is incomplete for this tenant/domain scope",
                    "tenant_id": request.tenant_id,
                    "domain_id": domain_id,
                    "run_id": effective_run_id,
                    "missing_artifacts": missing_artifacts,
                },
            )
        _log_step("scope_resolved")
        _augment_catalog_dimensions_from_facts(
            request.tenant_id,
            domain_id,
            connection_id,
            database_name,
            schema_name,
        )
        _log_step("catalog_augmented")
        facts_for_scope = (intelligence_bundle or {}).get("facts") or []
        _log_step("facts_listed")
        scoped_metric_rows = (intelligence_bundle or {}).get("metrics") or []
        scoped_metric_names: set[str] = set()
        for row in scoped_metric_rows:
            metric_name = str(row.get("metric_name") or "").strip()
            display_name = str(row.get("display_name") or "").strip()
            if metric_name:
                scoped_metric_names.add(metric_name)
            if display_name:
                scoped_metric_names.add(display_name)
        logger.info(
            "query.scope_metrics | count=%s sample=%s",
            len(scoped_metric_names),
            [
                {
                    "metric_name": row.get("metric_name"),
                    "display_name": row.get("display_name"),
                    "dataset_id": row.get("dataset_id"),
                    "source_model": row.get("source_model"),
                    "lifecycle_status": row.get("lifecycle_status"),
                    "source_run_id": row.get("source_run_id"),
                }
                for row in scoped_metric_rows[:10]
            ],
        )
        query_catalog = _catalog_from_registry_rows(scoped_metric_rows, catalog.dimensions)
        logger.info(
            "query.scope_catalog | metric_count=%s dimension_count=%s",
            len(query_catalog.metrics),
            len(query_catalog.dimensions),
        )
        for fact in facts_for_scope:
            table_name = fact.get("table_name")
            if table_name:
                db_dims = _list_fact_table_columns(schema_name, table_name, scoped_conn=_query_scoped_conn)
                fact_dims_map[table_name] = set(db_dims)
        _log_step("fact_columns_loaded")
        dimension_candidates = (intelligence_bundle or {}).get("dimension_candidates") or _dimension_candidates_for_scope(
            request.tenant_id,
            domain_id,
            connection_id,
            database_name,
            schema_name,
        )
        logger.info("query.fact_dim_candidates | count=%s dims=%s", len(dimension_candidates), dimension_candidates)
        _log_step("dimension_candidates")
        glossary = (intelligence_bundle or {}).get("glossary") or fetch_glossary_terms(settings, request.tenant_id, domain_id)
        if active_semantic_state:
            glossary = merge_semantic_glossary(glossary, active_semantic_state)
        logger.info("query.glossary | loaded=%s", len(glossary or []))
        contract = get_active_semantic_contract(settings, request.tenant_id, domain_id)
        _log_step("glossary_contract")
    elif request.tenant_id and cached_payload:
        logger.info("query.scope_skipped | reason=cache_hit")

    if cached_payload:
        metric_names = cached_payload.get("metrics") or []
        dimensions = cached_payload.get("dimensions") or []
        filters = cached_payload.get("filters") or []
        if request.question:
            # Refresh time filters based on current question
            filters = _strip_time_filters(filters)
            filters.extend(_deterministic_date_filters_from_question(request.question, dimension_candidates))
        if not dimensions and request.question:
            logger.info("query.cache_empty_dimensions | fallback_resolve=true")
            cached_payload = None

    if not cached_payload:
        metric_names, dimensions, filters = _resolve_metrics(
            request,
            glossary=glossary,
            allowed_dimensions=dimension_candidates,
            domain_id=domain_id,
            metric_catalog=query_catalog,
        )
    _log_step("resolve_metrics")
    logger.info("query.resolve_metrics | metrics=%s dimensions=%s filters=%s", metric_names, dimensions, filters)
    if metric_names or dimensions or filters:
        metric_lookup = {name.lower(): name for name in query_catalog.metrics.keys()}
        dim_lookup = {name.lower(): name for name in query_catalog.dimensions.keys()}
        metric_names = [metric_lookup.get(name.lower(), name) for name in metric_names]
        dimensions = _dedupe_preserve_order([dim_lookup.get(name.lower(), name) for name in dimensions])
        normalized_filters = []
        for flt in filters:
            payload = flt if isinstance(flt, dict) else flt.model_dump()
            field = payload.get("field")
            if isinstance(field, str):
                payload["field"] = dim_lookup.get(field.lower(), field)
            normalized_filters.append(payload)
        filters = normalized_filters
        logger.info("query.normalized | metrics=%s dimensions=%s filters=%s", metric_names, dimensions, filters)
    if scoped_metric_names:
        filtered_metric_names = [m for m in metric_names if m in scoped_metric_names]
        if filtered_metric_names != metric_names:
            logger.info(
                "query.scope_metric_filter | before=%s after=%s",
                metric_names,
                filtered_metric_names,
            )
            metric_names = filtered_metric_names
    if not metric_names and request.question:
        question = request.question.lower()
        if "required run rate" in question and not scoped_metric_names:
            metric_names = ["current_run_rate_mmt", "required_run_rate_mmt"]
            dimensions = ["sales_area_name", "month_name", "fiscal_year"]
    logger.info("metrics: %s", metric_names)
    filters = _coerce_relative_date_filter_fields(filters, dimension_candidates)
    filters = _expand_relative_date_filters(filters)
    filters = _coerce_sbu_filters(filters)
    filters = _coerce_product_filters(filters)
    dimensions = _coerce_sbu_dimensions(dimensions, filters)
    filters = _normalize_filters(filters, settings)
    filters = _normalize_sales_quarter_filters(filters, metric_names)
    if not (cached_payload and dimension_candidates is None):
        filters = _filter_dimension_filters(filters, set(query_catalog.dimensions.keys()))
    _log_step("normalize_inputs")
    logger.info("query.coerced | metrics=%s dimensions=%s filters=%s", metric_names, dimensions, filters)
    logger.info("dimensions: %s", dimensions)
    logger.info("filters: %s", filters)
    if request.question and request.tenant_id:
        if domain_id is None:
            domain_id = _resolve_domain_id(request.tenant_id, request.domain_id)
        try:
            log_semantic_usage(
                settings,
                question=request.question,
                tenant_id=request.tenant_id,
                domain_id=domain_id,
                metrics=metric_names,
                dimensions=dimensions,
                filters=filters,
            )
        except Exception as exc:  # noqa: BLE001
            logger.info("query.semantic_usage failed: %s", exc)

    if request.question and "sales volume" in request.question.lower() and not metric_names:
        metric_names = ["total_sales_volume_tmt"]
        dimensions = ["sales_area_name", "product_name", "calendar_quarter_sales", "fiscal_year"]

    if not metric_names:
        log_query_audit(
            settings,
            request.question,
            metric_names,
            dimensions,
            filters,
            sql_text,
            None,
            row_count,
            error_message="No metrics resolved",
        )
        logger.error("query.fail | reason=no_metrics_resolved metrics=%s dimensions=%s filters=%s",
                     metric_names, dimensions, filters)
        raise HTTPException(status_code=400, detail="No metrics resolved")

    metrics = []
    metrics_all = []
    for metric_name in metric_names:
        if metric_name not in query_catalog.metrics:
            logger.error("query.fail | reason=unknown_metric metric=%s", metric_name)
            raise HTTPException(status_code=400, detail=f"Unknown metric: {metric_name}")
        metrics.append(query_catalog.metrics[metric_name])
        metrics_all.append(query_catalog.metrics[metric_name])
        if request.question:
            score = _score_metric_match(request.question, metric_name)
            base_table = _infer_fact_table_from_metric_sql(query_catalog.metrics[metric_name].sql)
            logger.info(
                "query.metric_score | metric=%s score=%.3f base_table=%s",
                metric_name,
                score,
                base_table,
            )
    logger.info(
        "query.metric_candidates | count=%s sample=%s",
        len(metrics_all),
        [_metric_debug_payload(metric, model_intelligence_map) for metric in metrics_all[:10]],
    )
    metrics, model_selection = _select_metrics_with_model_intelligence(
        metrics=metrics,
        question=request.question,
        dimensions=dimensions,
        filters=[flt if isinstance(flt, dict) else flt.model_dump() for flt in filters],
        model_map=model_intelligence_map,
    )
    metrics_all = list(metrics)
    metric_names = [metric.name for metric in metrics]
    logger.info("query.model_selection | details=%s", model_selection)
    _log_step("metrics_loaded")

    filter_fields = []
    for flt in filters:
        payload = flt if isinstance(flt, dict) else flt.model_dump()
        filter_fields.append(payload["field"])

    metric_dimension_set = set()
    for metric in metrics_all:
        fact_cols = _fact_columns_for_metric(metric.sql, settings.db_schema, scoped_conn=_query_scoped_conn)
        metric_dimension_set.update(fact_cols)
    scoped_dimension_set, scoped_column_tables, preferred_table_for_column = _build_scoped_dimension_access(
        schema_name=schema_name or settings.db_schema,
        metrics=metrics,
        join_edges=scoped_join_edges,
        model_map=model_intelligence_map,
        scoped_conn=_query_scoped_conn,
    )
    if scoped_dimension_set:
        metric_dimension_set.update(scoped_dimension_set)
    dimensions, filters = _coerce_dimension_aliases(
        dimensions,
        filters,
        set(query_catalog.dimensions.keys()),
        metric_dimension_set,
    )
    filters = _coerce_time_filter_fields(filters, metric_dimension_set)
    _log_step("alias_coerced")
    logger.info(
        "query.dim_alias | dimensions=%s filters=%s metric_dims=%s scoped_column_tables=%s",
        dimensions,
        filters,
        sorted(metric_dimension_set),
        {key: value for key, value in list(scoped_column_tables.items())[:25]},
    )
    if metric_dimension_set:
        _metric_dim_lower = {d.lower() for d in metric_dimension_set}
        filtered_dimensions = [
            dim for dim in dimensions
            if dim in metric_dimension_set or dim.lower() in _metric_dim_lower or dim == "process_month"
        ]
        if filtered_dimensions != dimensions:
            logger.info(
                "query.dimensions_filtered_to_scope | before=%s after=%s",
                dimensions,
                filtered_dimensions,
            )
            dimensions = filtered_dimensions
    if request.question and metric_dimension_set:
        question_l = request.question.lower()
        if "trend" in question_l or "last three months" in question_l or "last 3 months" in question_l or re.search(r"last\\s+\\d+\\s+months", question_l):
            if "process_date" in metric_dimension_set:
                if "process_month" not in dimensions:
                    dimensions.append("process_month")
                dimensions = [d for d in dimensions if d not in {"process_date", "pdate", "date_day", "date"}]
    filter_fields = []
    for flt in filters:
        payload = flt if isinstance(flt, dict) else flt.model_dump()
        filter_fields.append(payload["field"])

    if dimensions or filter_fields:
        filtered_metrics = []
        for metric in metrics:
            metric_base_table = _infer_fact_table_from_metric_sql(metric.sql)
            metric_base_tables = {_normalize_table_token(metric_base_table)} if metric_base_table else set()
            metric_scope_tables = _join_connected_tables(metric_base_tables, scoped_join_edges) | metric_base_tables
            metric_dims: set[str] = set()
            for table in metric_scope_tables:
                metric_dims.update(_list_fact_table_columns(schema_name or settings.db_schema, table, scoped_conn=_query_scoped_conn))
            logger.info(
                "query.metric_scope_cols | metric=%s base_table=%s tables=%s cols=%s",
                metric.name,
                metric_base_table,
                sorted(metric_scope_tables),
                sorted(metric_dims),
            )
            dimensions, filters = _coerce_dimensions_from_glossary(
                dimensions,
                filters,
                glossary,
                metric_dims,
            )
            logger.info("query.glossary_coerced | dimensions=%s filters=%s", dimensions, filters)
            _metric_dims_lower = {d.lower() for d in metric_dims}
            supported_dims = [
                dim for dim in dimensions
                if dim in metric_dims or dim.lower() in _metric_dims_lower or dim == "process_month"
            ]
            supported_filters = [
                flt for flt in filters
                if flt.get("field") in metric_dims or str(flt.get("field") or "").lower() in _metric_dims_lower
            ]
            if supported_dims or supported_filters:
                filtered_metrics.append(metric)
                # Narrow dims/filters to what this metric supports.
                dimensions = supported_dims
                filters = supported_filters
        metrics = filtered_metrics
        logger.info("query.filtered_metrics | count=%s names=%s",
                    len(metrics), [m.name for m in metrics])
        logger.info(
            "query.filtered_metric_details | sample=%s",
            [_metric_debug_payload(metric, model_intelligence_map) for metric in metrics[:10]],
        )
    _log_step("metric_filtering")

    if request.question and metric_names and len(metrics) != len(metric_names):
        allowed_metrics = [metric.name for metric in metrics]
        if allowed_metrics:
            logger.info("re-resolving after coercion with allowed metrics: %s", allowed_metrics)
            resolved = resolve_question(
                request.question,
                query_catalog,
                settings,
                allowed_metrics=allowed_metrics,
                glossary=glossary,
                allowed_dimensions=dimension_candidates,
            )
            metric_names = resolved.get("metrics", [])
            dimensions = _coerce_sbu_dimensions(resolved.get("dimensions", []), resolved.get("filters", []))
            filters = _coerce_sbu_filters(resolved.get("filters", []))
            logger.info("metrics (post-coercion): %s", metric_names)
            logger.info("dimensions (post-coercion): %s", dimensions)
            logger.info("filters (post-coercion): %s", filters)

            metrics = []
            for metric_name in metric_names:
                if metric_name not in query_catalog.metrics:
                    logger.error("query.fail | reason=unknown_metric_after_reresolve metric=%s", metric_name)
                    raise HTTPException(status_code=400, detail=f"Unknown metric: {metric_name}")
                metrics.append(query_catalog.metrics[metric_name])

            filter_fields = [flt["field"] for flt in filters]
            if dimensions or filter_fields:
                filtered_metrics = []
                for metric in metrics:
                    if all(dim in metric.dimensions for dim in dimensions) and all(
                        field in metric.dimensions for field in filter_fields
                    ):
                        filtered_metrics.append(metric)
                metrics = filtered_metrics
            logger.info("query.filtered_metrics_post_reresolve | count=%s names=%s",
                        len(metrics), [m.name for m in metrics])
            metrics, model_selection = _select_metrics_with_model_intelligence(
                metrics=metrics,
                question=request.question,
                dimensions=dimensions,
                filters=[flt if isinstance(flt, dict) else flt.model_dump() for flt in filters],
                model_map=model_intelligence_map,
            )
            metric_names = [metric.name for metric in metrics]
            logger.info("query.model_selection_post_reresolve | details=%s", model_selection)

    if not metrics and metrics_all and not scoped_metric_names:
        logger.info("dropping unsupported dimensions/filters for resolved metrics")
        allowed_dims = set()
        for metric in metrics_all:
            allowed_dims.update(metric.dimensions)
        dimensions = [dim for dim in dimensions if dim in allowed_dims]
        filters = [flt for flt in filters if flt.get("field") in allowed_dims]
        metrics = metrics_all
        logger.info("query.drop_unsupported | dimensions=%s filters=%s metrics=%s",
                    dimensions, filters, [m.name for m in metrics])

    if not metrics:
        logger.error("query.fail | reason=no_metrics_after_filtering")
        raise HTTPException(
            status_code=400,
            detail="No metrics support the requested dimensions/filters",
        )

    semantic_issue = _validate_metric_semantics(
        metrics=metrics,
        dimensions=dimensions,
        filters=[flt if isinstance(flt, dict) else flt.model_dump() for flt in filters],
        model_map=model_intelligence_map,
    )
    if semantic_issue:
        logger.error(
            "query.fail | reason=semantic_validation_failed issue=%s details=%s",
            semantic_issue.get("issue"),
            semantic_issue,
        )
        raise HTTPException(status_code=400, detail=semantic_issue)

    dim_objects = []
    for dim_name in dimensions:
        preferred_table = preferred_table_for_column.get(dim_name)
        if dim_name in query_catalog.dimensions:
            existing_dimension = query_catalog.dimensions[dim_name]
            existing_table = _normalize_table_token(_infer_table_from_dimension_sql(existing_dimension.sql))
            preferred_table_token = _normalize_table_token(preferred_table)
            if (
                dim_name in metric_dimension_set
                and preferred_table_token
                and existing_table
                and existing_table != preferred_table_token
            ):
                ad_hoc_dimension = _build_ad_hoc_dimension(
                    dim_name=dim_name,
                    preferred_table=preferred_table,
                    model_map=model_intelligence_map,
                )
                if ad_hoc_dimension:
                    dim_objects.append(ad_hoc_dimension)
                    logger.info(
                        "query.dimension_scope_override | name=%s catalog_table=%s preferred_table=%s",
                        dim_name,
                        existing_table,
                        preferred_table_token,
                    )
                    continue
            dim_objects.append(existing_dimension)
            continue
        if dim_name == "process_month":
            base_table = _infer_fact_table_from_metric_sql(metrics[0].sql)
            if base_table:
                dim_objects.append(
                    Dimension(
                        name=dim_name,
                        description="Process month (Mon-YY)",
                        data_type="string",
                        sql=f"to_char(date_trunc('month', {{{{ ref('{base_table}') }}}}.process_date), 'Mon-YY')",
                    )
                )
                logger.info("query.ad_hoc_dimension | name=%s base_table=%s", dim_name, base_table)
                continue
        if dim_name in metric_dimension_set and preferred_table:
            ad_hoc_dimension = _build_ad_hoc_dimension(
                dim_name=dim_name,
                preferred_table=preferred_table,
                model_map=model_intelligence_map,
            )
            if ad_hoc_dimension:
                dim_objects.append(ad_hoc_dimension)
                logger.info(
                    "query.ad_hoc_dimension | name=%s table=%s candidate_tables=%s",
                    dim_name,
                    preferred_table,
                    scoped_column_tables.get(dim_name) or [preferred_table],
                )
                continue
        raise HTTPException(status_code=400, detail=f"Unknown dimension: {dim_name}")
    _log_step("dimension_objects")

    built_filters: List[Filter] = []
    for flt in filters:
        payload = flt if isinstance(flt, dict) else flt.model_dump()
        preferred_table = preferred_table_for_column.get(payload["field"])
        if payload["field"] in query_catalog.dimensions and preferred_table:
            existing_dimension = query_catalog.dimensions[payload["field"]]
            existing_table = _normalize_table_token(_infer_table_from_dimension_sql(existing_dimension.sql))
            preferred_table_token = _normalize_table_token(preferred_table)
            if existing_table and preferred_table_token and existing_table != preferred_table_token:
                ad_hoc_filter_dimension = _build_ad_hoc_dimension(
                    dim_name=payload["field"],
                    preferred_table=preferred_table,
                    model_map=model_intelligence_map,
                )
                if ad_hoc_filter_dimension:
                    query_catalog.dimensions[payload["field"]] = ad_hoc_filter_dimension
        if payload["field"] not in query_catalog.dimensions:
            if preferred_table:
                ad_hoc_filter_dimension = _build_ad_hoc_dimension(
                    dim_name=payload["field"],
                    preferred_table=preferred_table,
                    model_map=model_intelligence_map,
                )
                if ad_hoc_filter_dimension:
                    query_catalog.dimensions[payload["field"]] = ad_hoc_filter_dimension
            if payload["field"] not in query_catalog.dimensions:
                continue
        normalized_value = _normalize_filter_value(payload["field"], payload["value"])
        built_filters.append(
            Filter(field=payload["field"], operator=payload["operator"], value=normalized_value)
        )
    _log_step("filter_objects")

    sort_desc = _infer_sort_desc(request.question)
    top_n = _extract_top_n(request.question)
    effective_limit = top_n if top_n else request.limit

    rollup_used = False
    rollup_sql = None
    rollup_params: list[object] = []
    rollup_rows: list[dict] | None = None
    if request.tenant_id and domain_id and len(metrics) == 1:
        time_grain = _infer_time_grain(dimensions)
        rollup = find_matching_rollup(
            settings,
            tenant_id=request.tenant_id,
            domain_id=domain_id,
            metric_name=metrics[0].name,
            dimensions=sorted(dimensions),
            time_grain=time_grain,
        )
        if rollup:
            rollup_table = f"{settings.db_schema}.{rollup.get('rollup_table')}"
            rollup_sql_payload = _build_rollup_query(
                {**rollup, "rollup_table": rollup_table},
                metrics[0].name,
                dimensions,
                filters,
                sort_desc,
                effective_limit,
            )
            if rollup_sql_payload:
                rollup_sql, rollup_params = rollup_sql_payload
                try:
                    rollup_rows = run_query(settings, rollup_sql, rollup_params, scoped_conn=_query_scoped_conn)
                    rollup_used = True
                    sql_text = rollup_sql
                    row_count = len(rollup_rows)
                    logger.info(
                        "query.rollup_hit | rollup_id=%s table=%s rows=%s",
                        rollup.get("rollup_id"),
                        rollup.get("rollup_table"),
                        row_count,
                    )
                    _log_step("rollup_query")
                except Exception as exc:  # noqa: BLE001
                    logger.info("query.rollup_failed | error=%s", exc)
        else:
            logger.info(
                "query.rollup_miss | metric=%s dims=%s time_grain=%s",
                metrics[0].name,
                dimensions,
                time_grain,
            )

    if rollup_used and rollup_rows is not None:
        semantic_validation = _build_semantic_validation(metrics, contract)
        lineage = _build_lineage(metrics)
        artifact_lineage = _artifact_lineage_snapshot(
            tenant_id=request.tenant_id,
            domain_id=domain_id,
            run_id=effective_run_id if request.tenant_id else None,
            connection_id=connection_id if request.tenant_id else None,
            database_name=database_name if request.tenant_id else None,
            schema_name=schema_name if request.tenant_id else None,
            bundle=intelligence_bundle,
            metrics=metrics,
        )
        chart_id = None
        if request.question and request.tenant_id:
            try:
                query_payload = {
                    "tenant_id": request.tenant_id,
                    "domain_id": domain_id,
                    "question": request.question,
                    "metrics": [metric.name for metric in metrics],
                    "dimensions": dimensions,
                    "source_dimensions": dimensions,
                    "filters": [flt.model_dump() if hasattr(flt, "model_dump") else flt for flt in filters],
                    "limit": request.limit,
                    "table": base_table,
                    "time_grain": time_grain,
                }
                chart_row = create_chart_request(
                    settings,
                    tenant_id=request.tenant_id,
                    domain_id=domain_id,
                    question=request.question,
                    query_payload=query_payload,
                    sql=rollup_sql,
                    params=rollup_params,
                    rows_json=rollup_rows,
                    chart_source="workspace",
                )
                create_chart_event(
                    settings,
                    chart_row["chart_id"],
                    "queued",
                    details={"question": request.question},
                )
                create_job(
                    settings,
                    tenant_id=request.tenant_id,
                    domain_id=domain_id,
                    job_type="chart_build",
                    payload={"chart_id": chart_row["chart_id"]},
                )
                chart_id = chart_row["chart_id"]
            except Exception:  # noqa: BLE001
                logger.exception("chart enqueue failed")
        return QueryResult(
            metrics=[metric.name for metric in metrics],
            dimensions=dimensions,
            chart_id=chart_id,
            sql=rollup_sql,
            rows=rollup_rows,
            by_company_sql=None,
            by_company_rows=None,
            semantic_validation=semantic_validation,
            lineage=lineage,
            artifact_lineage=artifact_lineage,
        )
    try:
        filter_dimensions = dict(query_catalog.dimensions)
        base_table = _infer_fact_table_from_metric_sql(metrics[0].sql)
        metric_base_tables = sorted(
            {
                str(_infer_fact_table_from_metric_sql(metric.sql) or "<multi_or_unknown>")
                for metric in metrics
            }
        )
        logger.info(
            "query.build_input | metric_count=%s base_tables=%s dimensions=%s filters=%s metrics=%s",
            len(metrics),
            metric_base_tables,
            dimensions,
            [flt.model_dump() if hasattr(flt, "model_dump") else flt for flt in built_filters],
            [_metric_debug_payload(metric, model_intelligence_map) for metric in metrics[:10]],
        )
        if base_table:
            for flt in filters:
                payload = flt if isinstance(flt, dict) else flt.model_dump()
                field = payload.get("field")
                if field and field not in filter_dimensions and field in metric_dimension_set:
                    preferred_table = preferred_table_for_column.get(field) or _normalize_table_token(base_table)
                    ad_hoc_filter_dimension = _build_ad_hoc_dimension(
                        dim_name=field,
                        preferred_table=preferred_table,
                        model_map=model_intelligence_map,
                    )
                    if ad_hoc_filter_dimension:
                        filter_dimensions[field] = ad_hoc_filter_dimension
        built = build_query(
            metrics=metrics,
            dimensions=dim_objects,
            filter_dimensions=filter_dimensions,
            filters=built_filters,
            schema=settings.db_schema,
            limit=effective_limit,
            order_by_metric=True,
            order_desc=sort_desc,
            join_edges=scoped_join_edges,
        )
        _log_step("sql_built")
        sql_text = built.sql
        logger.info("sql: %s", built.sql)
        logger.info("params: %s", built.params)
        rows = run_query(settings, built.sql, built.params, scoped_conn=_query_scoped_conn)
        row_count = len(rows)
        logger.info("rows: %s", row_count)
        _log_step("sql_executed")
    except Exception as exc:
        error_message = str(exc)
        logger.error(
            "query.build_failed | question=%s tenant=%s domain=%s metrics=%s dimensions=%s filters=%s details=%s",
            request.question,
            request.tenant_id,
            domain_id,
            [_metric_debug_payload(metric, model_intelligence_map) for metric in metrics[:10]],
            dimensions,
            [flt.model_dump() if hasattr(flt, "model_dump") else flt for flt in built_filters],
            error_message,
        )
        execution_ms = int((time.perf_counter() - start_time) * 1000)
        log_query_audit(
            settings,
            request.question,
            metric_names,
            dimensions,
            [flt.model_dump() if hasattr(flt, "model_dump") else flt for flt in filters],
            sql_text,
            execution_ms,
            row_count,
            error_message=error_message,
        )
        if isinstance(exc, ValueError):
            logger.exception("build_query failed")
            raise HTTPException(status_code=400, detail=error_message) from exc
        raise

    top_n = _extract_top_n(request.question)
    if top_n and rows:
        sort_metric = metrics[0].name
        try:
            rows = sorted(
                rows,
                key=lambda row: float(row.get(sort_metric) or 0),
                reverse=True,
            )[:top_n]
        except (TypeError, ValueError):
            pass

    if request.question and "below required run rate" in request.question.lower():
        filtered_rows = []
        for row in rows:
            try:
                current = float(row.get("current_run_rate_mmt"))
                required = float(row.get("required_run_rate_mmt"))
            except (TypeError, ValueError):
                continue
            if current < required:
                filtered_rows.append(row)
        rows = filtered_rows

    by_company_sql = None
    by_company_rows = None
    if request.explain and "industry_sales_by_company_tmt" in [m.name for m in metrics]:
        if "industry_sales_by_company_tmt" in query_catalog.metrics:
            by_company_metric = query_catalog.metrics["industry_sales_by_company_tmt"]
            by_company_dimensions = list(dim_objects)
            if "company_name" not in [dim.name for dim in by_company_dimensions]:
                by_company_dimensions.append(query_catalog.dimensions["company_name"])
            by_company_built = build_query(
                metrics=[by_company_metric],
                dimensions=by_company_dimensions,
                filter_dimensions=filter_dimensions,
                filters=built_filters,
                schema=settings.db_schema,
                limit=effective_limit,
                order_by_metric=True,
                order_desc=sort_desc,
                join_edges=scoped_join_edges,
            )
            by_company_sql = by_company_built.sql
            logger.info("by_company_sql: %s", by_company_sql)
            logger.info("by_company_params: %s", by_company_built.params)
            by_company_rows = run_query(settings, by_company_built.sql, by_company_built.params, scoped_conn=_query_scoped_conn)
            logger.info("by_company_rows: %s", len(by_company_rows))

    execution_ms = int((time.perf_counter() - start_time) * 1000)
    log_query_audit(
        settings,
        request.question,
        metric_names,
        dimensions,
        [flt.model_dump() if hasattr(flt, "model_dump") else flt for flt in filters],
        sql_text,
        execution_ms,
        row_count,
        error_message=None,
    )

    semantic_validation = _build_semantic_validation(metrics, contract)
    lineage = _build_lineage(metrics)
    artifact_lineage = _artifact_lineage_snapshot(
        tenant_id=request.tenant_id,
        domain_id=domain_id,
        run_id=effective_run_id if request.tenant_id else None,
        connection_id=connection_id if request.tenant_id else None,
        database_name=database_name if request.tenant_id else None,
        schema_name=schema_name if request.tenant_id else None,
        bundle=intelligence_bundle,
        metrics=metrics,
    )
    if semantic_validation and request.tenant_id:
        for policy_name in semantic_validation.get("policy_applied", []):
            log_policy_audit(
                settings,
                tenant_id=request.tenant_id,
                query_id=None,
                policy_name=policy_name,
                action="applied",
                details={"metrics": metric_names},
            )

    chart_id = None
    if request.question and request.tenant_id:
        try:
            domain_id = _resolve_domain_id(request.tenant_id, request.domain_id)
            query_payload = {
                "tenant_id": request.tenant_id,
                "domain_id": domain_id,
                "question": request.question,
                "metrics": [metric.name for metric in metrics],
                "dimensions": [dim.name for dim in dim_objects if dim.name != "company_name"],
                "source_dimensions": dimensions,
                "filters": [flt.model_dump() if hasattr(flt, "model_dump") else flt for flt in filters],
                "limit": request.limit,
                "table": base_table,
                "time_grain": _infer_time_grain(dimensions),
            }
            chart_row = create_chart_request(
                settings,
                tenant_id=request.tenant_id,
                domain_id=domain_id,
                question=request.question,
                query_payload=query_payload,
                sql=built.sql,
                params=built.params,
                rows_json=rows,
                chart_source="workspace",
            )
            create_chart_event(
                settings,
                chart_row["chart_id"],
                "queued",
                details={"question": request.question},
            )
            create_job(
                settings,
                tenant_id=request.tenant_id,
                domain_id=domain_id,
                job_type="chart_build",
                payload={"chart_id": chart_row["chart_id"]},
            )
            chart_id = chart_row["chart_id"]
        except Exception:  # noqa: BLE001
            logger.exception("chart enqueue failed")

    return QueryResult(
        metrics=[metric.name for metric in metrics],
        dimensions=[dim.name for dim in dim_objects if dim.name != "company_name"],
        chart_id=chart_id,
        sql=built.sql,
        rows=rows,
        by_company_sql=by_company_sql,
        by_company_rows=by_company_rows,
        semantic_validation=semantic_validation,
        lineage=lineage,
        artifact_lineage=artifact_lineage,
    )


@app.post(
    "/charts",
    response_model=ChartStatusResponse,
    tags=["charts"],
    summary="Create async chart request",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "chart_from_question": {
                            "summary": "Create chart from question",
                            "value": {
                                "tenant_id": "VC_101",
                                "domain_id": "lpg_production_distribution",
                                "question": "What is total LPG production by plant last week?",
                                "limit": 200,
                            },
                        }
                    }
                }
            }
        },
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "queued": {
                                "summary": "Queued chart",
                                "value": {"chart_id": "chart_2f7a9c4d", "status": "queued"},
                            }
                        }
                    }
                }
            }
        },
    },
)
def create_chart(request: ChartRequest) -> ChartStatusResponse:
    domain_id = _resolve_domain_id(request.tenant_id, request.domain_id)
    filters_payload = [flt.model_dump() for flt in (request.filters or [])]
    query_payload = {
        "tenant_id": request.tenant_id,
        "domain_id": domain_id,
        "question": request.question,
        "metrics": request.metrics,
        "dimensions": request.dimensions or [],
        "filters": filters_payload,
        "limit": request.limit,
    }
    chart_row = create_chart_request(
        settings,
        tenant_id=request.tenant_id,
        domain_id=domain_id,
        question=request.question,
        query_payload=query_payload,
        chart_source="workspace",
    )
    create_chart_event(
        settings,
        chart_row["chart_id"],
        "queued",
        details={"question": request.question},
    )
    create_job(
        settings,
        tenant_id=request.tenant_id,
        domain_id=domain_id,
        job_type="chart_build",
        payload={"chart_id": chart_row["chart_id"], "query_payload": query_payload},
    )
    return ChartStatusResponse(chart_id=chart_row["chart_id"], status=chart_row.get("status", "queued"))


@app.get(
    "/rollups",
    response_model=list[RollupResponse],
    tags=["rollups"],
    summary="List rollups",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "rollups": {
                                "summary": "Rollup list",
                                "value": [
                                    {
                                        "rollup_id": "rollup_123",
                                        "tenant_id": "VC_101",
                                        "domain_id": "lpg_production_distribution",
                                        "base_model": "fact_lpg_plant_operations",
                                        "metric_name": "production_mt",
                                        "dimensions": ["region"],
                                        "time_grain": "month",
                                        "rollup_table": "rollup_production_mt_abc123",
                                        "status": "active",
                                    }
                                ],
                            }
                        }
                    }
                }
            }
        }
    },
)
def list_rollups_endpoint(tenant_id: str, domain_id: str | None = None) -> list[RollupResponse]:
    return list_rollups(settings, tenant_id, domain_id)


@app.post(
    "/rollups",
    response_model=RollupResponse,
    tags=["rollups"],
    summary="Create rollup",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "create": {
                            "summary": "Create rollup",
                            "value": {
                                "tenant_id": "VC_101",
                                "domain_id": "lpg_production_distribution",
                                "metric_name": "production_mt",
                                "dimensions": ["region"],
                                "time_grain": "month",
                                "build_now": True,
                            },
                        }
                    }
                }
            }
        }
    },
)
def create_rollup_endpoint(request: RollupCreateRequest) -> RollupResponse:
    domain_id = _resolve_domain_id(request.tenant_id, request.domain_id)
    rollup = create_rollup(
        settings,
        tenant_id=request.tenant_id,
        domain_id=domain_id,
        metric_name=request.metric_name,
        dimensions=request.dimensions,
        time_grain=request.time_grain,
        filters=request.filters,
    )
    if request.build_now:
        update_rollup_status(settings, rollup["rollup_id"], "building")
        create_job(
            settings,
            tenant_id=request.tenant_id,
            domain_id=domain_id,
            job_type="rollup_build",
            payload={"rollup_id": rollup["rollup_id"]},
        )
        rollup["status"] = "building"
    return rollup


@app.post(
    "/rollups/{rollup_id}/refresh",
    response_model=RollupRefreshResponse,
    tags=["rollups"],
    summary="Refresh rollup",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "refresh": {
                            "summary": "Refresh rollup",
                            "value": {"tenant_id": "VC_101"},
                        }
                    }
                }
            }
        }
    },
)
def refresh_rollup_endpoint(rollup_id: str, tenant_id: str) -> RollupRefreshResponse:
    rollup = get_rollup(settings, rollup_id)
    if not rollup or rollup.get("tenant_id") != tenant_id:
        raise HTTPException(status_code=404, detail="Rollup not found")
    update_rollup_status(settings, rollup_id, "refreshing")
    create_job(
        settings,
        tenant_id=tenant_id,
        domain_id=rollup.get("domain_id"),
        job_type="rollup_refresh",
        payload={"rollup_id": rollup_id},
    )
    return RollupRefreshResponse(rollup_id=rollup_id, status="refreshing")


@app.post(
    "/chat",
    response_model=ChatResponse,
    tags=["chat"],
    summary="Chat-style query",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "sync": {
                            "summary": "Sync chat",
                            "value": {
                                "question": "What is total LPG production by plant last week?",
                                "tenant_id": "VC_101",
                                "domain_id": "lpg_production_distribution",
                                "mode": "sync",
                            },
                        },
                        "async": {
                            "summary": "Async chat",
                            "value": {
                                "question": "What is total LPG production by plant last week?",
                                "tenant_id": "VC_101",
                                "domain_id": "lpg_production_distribution",
                                "mode": "async",
                            },
                        },
                    }
                }
            }
        }
    },
)
def chat_query(request: ChatRequest) -> ChatResponse:
    mode = (request.mode or "sync").lower()
    request_payload = {
        "question": request.question,
        "tenant_id": request.tenant_id,
        "domain_id": request.domain_id,
        "run_id": request.run_id,
        "metrics": request.metrics,
        "dimensions": request.dimensions,
        "filters": [flt.model_dump() for flt in request.filters],
        "limit": request.limit,
        "explain": request.explain,
    }
    if mode == "async":
        chat_row = create_chat_request(
            settings,
            tenant_id=request.tenant_id,
            domain_id=request.domain_id,
            question=request.question,
            request_payload=request_payload,
        )
        create_job(
            settings,
            tenant_id=request.tenant_id,
            domain_id=request.domain_id,
            job_type="chat_build",
            payload={"chat_id": chat_row["chat_id"]},
        )
        return ChatResponse(chat_id=chat_row["chat_id"], status=chat_row.get("status", "queued"))

    query_result = query(
        QueryRequest(
            question=request.question,
            tenant_id=request.tenant_id,
            domain_id=request.domain_id,
            run_id=request.run_id,
            metrics=request.metrics,
            dimensions=request.dimensions,
            filters=request.filters,
            limit=request.limit,
            explain=request.explain,
        )
    )
    chart_payload = None
    chart_type = None
    if query_result.rows and query_result.metrics:
        chart_type = infer_chart_type(query_result.dimensions, query_result.rows, query_result.metrics)
        if chart_type:
            chart_payload = build_chart_payload(
                chart_type,
                query_result.rows,
                query_result.metrics[0],
                query_result.dimensions,
            )
    response_payload = {
        "metrics": query_result.metrics,
        "dimensions": query_result.dimensions,
        "chart_id": query_result.chart_id,
        "chart_type": chart_type,
        "chart_payload": chart_payload.get("chart_payload") if chart_payload else None,
        "data": chart_payload.get("data") if chart_payload else None,
        "sql": query_result.sql,
        "rows": query_result.rows,
    }
    return ChatResponse(chat_id=None, status="complete", response=response_payload)


@app.get(
    "/chat/{chat_id}",
    response_model=ChatResponse,
    tags=["chat"],
    summary="Get chat response",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "complete": {
                                "summary": "Chat complete",
                                "value": {
                                    "chat_id": "chat_123",
                                    "status": "complete",
                                    "response": {
                                        "metrics": ["production_mt"],
                                        "dimensions": ["region"],
                                        "sql": "SELECT ...",
                                        "rows": [],
                                    },
                                },
                            }
                        }
                    }
                }
            }
        }
    },
)
def get_chat(chat_id: str) -> ChatResponse:
    row = get_chat_request(settings, chat_id)
    if not row:
        raise HTTPException(status_code=404, detail="Chat request not found")
    return ChatResponse(
        chat_id=row["chat_id"],
        status=row.get("status", "queued"),
        response=row.get("response_payload"),
        error_message=row.get("error_message"),
    )


@app.get(
    "/chat/{chat_id}/events",
    tags=["chat"],
    summary="List chat events",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "events": {
                                "summary": "Chat events",
                                "value": {
                                    "events": [
                                        {"event_type": "resolve", "message": "Resolving metrics and dimensions"},
                                        {"event_type": "query", "message": "Executing SQL"},
                                        {"event_type": "complete", "message": "Chat response ready"},
                                    ]
                                },
                            }
                        }
                    }
                }
            }
        }
    },
)
def get_chat_events(chat_id: str, limit: int = 200) -> dict:
    events = list_chat_events(settings, chat_id, limit=limit)
    return {"events": events}


@app.get(
    "/chat/{chat_id}/stream",
    tags=["chat"],
    summary="Stream chat events",
    description="Server-sent events stream of chat lifecycle events.",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "text/event-stream": {
                        "examples": {
                            "resolve_event": {
                                "summary": "Resolve step",
                                "value": "data: {\"event_type\":\"resolve\",\"message\":\"Resolving metrics and dimensions\"}\n\n",
                            },
                            "query_event": {
                                "summary": "SQL step",
                                "value": "data: {\"event_type\":\"query\",\"message\":\"Executing SQL\"}\n\n",
                            },
                            "complete_event": {
                                "summary": "Completion step",
                                "value": "data: {\"event_type\":\"complete\",\"message\":\"Chat response ready\"}\n\n",
                            }
                        }
                    }
                }
            }
        }
    },
)
def chat_stream(chat_id: str):
    from fastapi.responses import StreamingResponse

    def _event_stream():
        last_count = 0
        while True:
            events = list_chat_events(settings, chat_id, limit=2000)
            new_events = events[last_count:]
            for event in new_events:
                payload = json.dumps(event, default=str)
                yield f"data: {payload}\n\n"
            last_count = len(events)
            time.sleep(1.0)

    return StreamingResponse(_event_stream(), media_type="text/event-stream")


def _refinement_artifact_response(row: dict) -> SemanticRefinementArtifactResponse:
    return SemanticRefinementArtifactResponse(
        artifact_id=row.get("artifact_id"),
        refinement_input_id=row.get("refinement_input_id"),
        tenant_id=row.get("tenant_id"),
        domain_id=row.get("domain_id"),
        artifact_type=row.get("artifact_type"),
        artifact_json=row.get("artifact_json") or {},
        validation_status=row.get("validation_status") or "pending",
        validation_errors_json=row.get("validation_errors_json") or [],
        approval_status=row.get("approval_status") or "pending",
        approved_by=row.get("approved_by"),
        approved_at=row.get("approved_at"),
        created_at=row.get("created_at"),
    )


def _refinement_response(row: dict, artifacts: list[dict] | None = None, semantic_state_id: str | None = None) -> SemanticRefinementResponse:
    return SemanticRefinementResponse(
        refinement_input_id=row.get("refinement_input_id"),
        tenant_id=row.get("tenant_id"),
        domain_id=row.get("domain_id"),
        source_type=row.get("source_type"),
        refinement_kind=row.get("refinement_kind"),
        status=row.get("status"),
        source_text=row.get("source_text"),
        source_payload_json=row.get("source_payload_json"),
        source_run_id=row.get("source_run_id"),
        source_context_id=row.get("source_context_id"),
        conversation_id=row.get("conversation_id"),
        submitted_by=row.get("submitted_by"),
        connection_id=row.get("connection_id"),
        database_name=row.get("database_name"),
        schema_name=row.get("schema_name"),
        artifacts=[_refinement_artifact_response(item) for item in (artifacts or [])],
        semantic_state_id=semantic_state_id,
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


def _semantic_state_response(row: dict, tenant_id: str, domain_id: str) -> SemanticStateResponse:
    return SemanticStateResponse(
        semantic_state_id=row.get("semantic_state_id"),
        tenant_id=row.get("tenant_id") or tenant_id,
        domain_id=row.get("domain_id") or domain_id,
        connection_id=row.get("connection_id"),
        database_name=row.get("database_name"),
        schema_name=row.get("schema_name"),
        version_no=row.get("version_no"),
        state_json=row.get("state_json") or {},
        created_from_artifact_ids=row.get("created_from_artifact_ids") or [],
        trigger_type=row.get("trigger_type"),
        is_active=row.get("is_active"),
        created_at=row.get("created_at"),
    )


def _semantic_propagation_response(row: dict, tenant_id: str, domain_id: str) -> SemanticPropagationJobResponse:
    return SemanticPropagationJobResponse(
        job_id=row.get("job_id"),
        tenant_id=row.get("tenant_id") or tenant_id,
        domain_id=row.get("domain_id") or domain_id,
        connection_id=row.get("connection_id"),
        database_name=row.get("database_name"),
        schema_name=row.get("schema_name"),
        trigger_type=row.get("trigger_type") or "manual",
        affected_scope_json=row.get("affected_scope_json") or {},
        status=row.get("status") or "queued",
        created_at=row.get("created_at"),
        completed_at=row.get("completed_at"),
    )


def _semantic_intake_artifact_summary(row: dict) -> SemanticIntakeArtifactSummary:
    artifact_json = row.get("artifact_json") or {}
    if not isinstance(artifact_json, dict):
        artifact_json = {}
    summary = (
        artifact_json.get("description")
        or artifact_json.get("source_text")
        or artifact_json.get("guidance")
        or artifact_json.get("rule")
        or artifact_json.get("text")
    )
    if not summary and artifact_json.get("metric_name"):
        summary = f"Metric refinement for {artifact_json.get('metric_name')}"
    if not summary and artifact_json.get("column"):
        summary = f"Column annotation for {artifact_json.get('column')}"
    return SemanticIntakeArtifactSummary(
        artifact_id=row.get("artifact_id"),
        artifact_type=row.get("artifact_type"),
        validation_status=row.get("validation_status") or "pending",
        approval_status=row.get("approval_status") or "pending",
        artifact_json=artifact_json,
        validation_errors_json=row.get("validation_errors_json") or [],
        summary=summary,
    )


def _semantic_intake_propagation_summary(row: dict | None) -> list[SemanticIntakePropagationSummary]:
    if not row:
        return []
    affected_scope = row.get("affected_scope_json") or {}
    if not isinstance(affected_scope, dict):
        affected_scope = {}
    return [
        SemanticIntakePropagationSummary(
            job_id=row.get("job_id"),
            status=row.get("status") or "queued",
            refresh_actions=affected_scope.get("refresh_actions") or [],
            affected_scope_json=affected_scope,
        )
    ]


@app.post(
    "/semantic/intake",
    response_model=SemanticIntakeResponse,
    tags=["semantic"],
    summary="Submit UI semantic intake text",
    description=(
        "UI-facing wrapper for semantic improvements. The UI sends only text plus type=semantics; "
        "the backend infers refinement kind, extracts artifacts, auto-approves valid artifacts, "
        "rebuilds semantic state, and queues propagation."
    ),
)
def semantic_intake(payload: SemanticIntakeRequest) -> SemanticIntakeResponse:
    intake_type = str(payload.type or "").strip().lower()
    if intake_type != "semantics":
        raise HTTPException(status_code=400, detail="Only type='semantics' is supported")
    text = str(payload.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="text is required")

    domain_id = _resolve_domain_id(payload.tenant_id, payload.domain_id)
    connection_id = payload.connection_id
    database_name = payload.database_name
    schema_name = payload.schema_name
    if not (connection_id and database_name and schema_name):
        resolved_connection, resolved_database, resolved_schema, _ = _resolve_scope_values(payload.tenant_id, domain_id)
        connection_id = connection_id or resolved_connection
        database_name = database_name or resolved_database
        schema_name = schema_name or resolved_schema

    refinement_kind = infer_refinement_kind(text)
    source_type = "conversation" if payload.conversation_id else "text"
    errors = validate_refinement_input_payload(
        source_type=source_type,
        refinement_kind=refinement_kind,
        source_text=text,
        source_payload_json=None,
    )
    if errors:
        raise HTTPException(status_code=400, detail={"errors": errors})

    refinement_input_id = create_refinement_input(
        settings,
        tenant_id=payload.tenant_id,
        domain_id=domain_id,
        connection_id=connection_id,
        database_name=database_name,
        schema_name=schema_name,
        source_run_id=payload.source_run_id,
        source_type=source_type,
        refinement_kind=refinement_kind,
        source_text=text,
        source_payload_json={},
        source_context_id=payload.conversation_id,
        conversation_id=payload.conversation_id,
        submitted_by=payload.submitted_by,
    )
    row = get_refinement_input(settings, refinement_input_id)
    artifacts: list[dict] = []
    semantic_state_id: str | None = None
    propagation_job: dict | None = None
    if row:
        artifacts = process_refinement_input(
            settings,
            row,
            auto_approve=True,
            approved_by=payload.submitted_by or "system:auto_approve",
        )
        row = get_refinement_input(settings, refinement_input_id) or row
        valid_artifacts = [
            artifact
            for artifact in artifacts
            if artifact.get("validation_status") == "valid"
            and artifact.get("approval_status") in {"approved", "auto_approved"}
        ]
        if valid_artifacts:
            state_result = rebuild_semantic_state(
                settings,
                tenant_id=payload.tenant_id,
                domain_id=domain_id,
                connection_id=connection_id,
                database_name=database_name,
                schema_name=schema_name,
                trigger_type="semantic_intake_auto_approved",
            )
            semantic_state_id = state_result.get("semantic_state_id")
            propagation_job = enqueue_semantic_propagation_for_artifacts(
                settings,
                tenant_id=payload.tenant_id,
                domain_id=domain_id,
                connection_id=connection_id,
                database_name=database_name,
                schema_name=schema_name,
                artifacts=valid_artifacts,
                trigger_type="semantic_intake_auto_approved",
                semantic_state_id=semantic_state_id,
            )

    return SemanticIntakeResponse(
        status=(row or {}).get("status") or ("processed" if artifacts else "submitted"),
        type="semantics",
        tenant_id=payload.tenant_id,
        domain_id=domain_id,
        inferred_refinement_kind=refinement_kind,
        refinement_input_id=refinement_input_id,
        semantic_state_id=semantic_state_id,
        artifacts=[_semantic_intake_artifact_summary(item) for item in artifacts],
        propagation_jobs=_semantic_intake_propagation_summary(propagation_job),
    )


@app.post(
    "/semantic/impact-preview",
    response_model=SemanticImpactPreviewResponse,
    tags=["semantic"],
    summary="Preview semantic refinement impact",
    description=(
        "Read-only preview of semantic refinement impact. Accepts either an existing refinement_input_id "
        "or raw text/payload, extracts/profiles artifacts, compares them with active semantic state, and "
        "returns affected scope without changing approval status or active state."
    ),
)
def semantic_impact_preview(payload: SemanticImpactPreviewRequest) -> SemanticImpactPreviewResponse:
    domain_id = _resolve_domain_id(payload.tenant_id, payload.domain_id)
    connection_id = payload.connection_id
    database_name = payload.database_name
    schema_name = payload.schema_name
    if not (connection_id and database_name and schema_name):
        resolved_connection, resolved_database, resolved_schema, _ = _resolve_scope_values(payload.tenant_id, domain_id)
        connection_id = connection_id or resolved_connection
        database_name = database_name or resolved_database
        schema_name = schema_name or resolved_schema

    refinement_input_id = payload.refinement_input_id
    refinement_kind: str | None = None
    artifacts: list[dict] = []
    if refinement_input_id:
        row = get_refinement_input(settings, refinement_input_id)
        if not row or row.get("tenant_id") != payload.tenant_id or row.get("domain_id") != domain_id:
            raise HTTPException(status_code=404, detail="Refinement not found")
        refinement_kind = row.get("refinement_kind")
        artifacts = list_refinement_artifacts(
            settings,
            tenant_id=payload.tenant_id,
            domain_id=domain_id,
            refinement_input_id=refinement_input_id,
            limit=100,
        )
        if not artifacts:
            artifacts = extract_refinement_artifacts_with_llm(settings, row)
    else:
        text = str(payload.text or "").strip()
        source_payload = payload.payload or {}
        if not text and not source_payload:
            raise HTTPException(status_code=400, detail="Provide refinement_input_id, text, or payload")
        refinement_kind = str(payload.refinement_kind or "auto").strip()
        if refinement_kind == "auto":
            refinement_kind = infer_refinement_kind(text, source_payload)
        errors = validate_refinement_input_payload(
            source_type="text" if text else "structured",
            refinement_kind=refinement_kind,
            source_text=text,
            source_payload_json=source_payload,
        )
        if errors:
            raise HTTPException(status_code=400, detail={"errors": errors})
        artifacts = extract_refinement_artifacts_with_llm(
            settings,
            {
                "tenant_id": payload.tenant_id,
                "domain_id": domain_id,
                "connection_id": connection_id,
                "database_name": database_name,
                "schema_name": schema_name,
                "source_type": "text" if text else "structured",
                "refinement_kind": refinement_kind,
                "source_text": text,
                "source_payload_json": source_payload,
            },
        )

    active_row = get_current_semantic_state(
        settings,
        tenant_id=payload.tenant_id,
        domain_id=domain_id,
        connection_id=connection_id,
        database_name=database_name,
        schema_name=schema_name,
    )
    active_state = (active_row or {}).get("state_json") or {}
    preview = build_semantic_impact_preview(artifacts, active_state=active_state)
    return SemanticImpactPreviewResponse(
        tenant_id=payload.tenant_id,
        domain_id=domain_id,
        refinement_input_id=refinement_input_id,
        inferred_refinement_kind=refinement_kind,
        impact_level=preview.get("impact_level") or "none",
        diff_summary=preview.get("diff_summary") or [],
        affected_scope=preview.get("affected_scope") or {},
        artifact_count=len(artifacts),
        active_semantic_state_id=(active_row or {}).get("semantic_state_id"),
    )


@app.get(
    "/semantic/audit",
    response_model=SemanticAuditResponse,
    tags=["semantic"],
    summary="Get semantic audit timeline",
    description=(
        "Read-only audit timeline for semantic refinements, extracted artifacts, semantic state versions, "
        "and propagation jobs in a tenant/domain scope."
    ),
)
def get_semantic_audit(
    tenant_id: str,
    domain_id: str | None = None,
    connection_id: str | None = None,
    database_name: str | None = None,
    schema_name: str | None = None,
    limit: int = 100,
) -> SemanticAuditResponse:
    resolved_domain_id = _resolve_domain_id(tenant_id, domain_id)
    refinements = list_refinement_inputs(
        settings,
        tenant_id=tenant_id,
        domain_id=resolved_domain_id,
        connection_id=connection_id,
        database_name=database_name,
        schema_name=schema_name,
        limit=limit,
    )
    artifacts_by_refinement: dict[str, list[dict]] = {}
    for refinement in refinements:
        refinement_input_id = str(refinement.get("refinement_input_id") or "")
        if not refinement_input_id:
            continue
        artifacts_by_refinement[refinement_input_id] = list_refinement_artifacts(
            settings,
            tenant_id=tenant_id,
            domain_id=resolved_domain_id,
            refinement_input_id=refinement_input_id,
            limit=100,
        )
    semantic_states = list_semantic_states(
        settings,
        tenant_id=tenant_id,
        domain_id=resolved_domain_id,
        connection_id=connection_id,
        database_name=database_name,
        schema_name=schema_name,
        limit=limit,
    )
    propagation_jobs = list_semantic_propagation_jobs(
        settings,
        tenant_id=tenant_id,
        domain_id=resolved_domain_id,
        connection_id=connection_id,
        database_name=database_name,
        schema_name=schema_name,
        limit=limit,
    )
    audit = build_semantic_audit(
        refinements=refinements,
        artifacts_by_refinement=artifacts_by_refinement,
        semantic_states=semantic_states,
        propagation_jobs=propagation_jobs,
    )
    return SemanticAuditResponse(
        tenant_id=tenant_id,
        domain_id=resolved_domain_id,
        refinements=audit.get("refinements") or [],
        semantic_states=audit.get("semantic_states") or [],
        propagation_jobs=audit.get("propagation_jobs") or [],
        timeline=audit.get("timeline") or [],
    )


@app.get(
    "/semantic/conflicts",
    response_model=SemanticConflictResponse,
    tags=["semantic"],
    summary="Detect semantic refinement conflicts",
    description="Read-only diagnostics for competing semantic refinement artifacts in a tenant/domain scope.",
)
def get_semantic_conflicts(
    tenant_id: str,
    domain_id: str | None = None,
    connection_id: str | None = None,
    database_name: str | None = None,
    schema_name: str | None = None,
    limit: int = 500,
) -> SemanticConflictResponse:
    resolved_domain_id = _resolve_domain_id(tenant_id, domain_id)
    artifacts = list_refinement_artifacts(
        settings,
        tenant_id=tenant_id,
        domain_id=resolved_domain_id,
        connection_id=connection_id,
        database_name=database_name,
        schema_name=schema_name,
        validation_status="valid",
        limit=limit,
    )
    conflicts = detect_semantic_conflicts(artifacts)
    return SemanticConflictResponse(
        tenant_id=tenant_id,
        domain_id=resolved_domain_id,
        conflicts=conflicts,
        conflict_count=len(conflicts),
    )


@app.post(
    "/semantic/refinements",
    response_model=SemanticRefinementResponse,
    tags=["semantic"],
    summary="Submit a semantic refinement",
    description=(
        "Create a post-deployment semantic refinement. Current backend behavior auto-processes "
        "and auto-approves valid artifacts by default; manual approval is intentionally deferred."
    ),
)
def create_semantic_refinement(payload: SemanticRefinementCreateRequest) -> SemanticRefinementResponse:
    domain_id = _resolve_domain_id(payload.tenant_id, payload.domain_id)
    refinement_kind = str(payload.refinement_kind or "auto").strip()
    if refinement_kind == "auto":
        refinement_kind = infer_refinement_kind(payload.text, payload.payload)
    errors = validate_refinement_input_payload(
        source_type=payload.source_type,
        refinement_kind=refinement_kind,
        source_text=payload.text,
        source_payload_json=payload.payload,
    )
    if errors:
        raise HTTPException(status_code=400, detail={"errors": errors})

    connection_id = payload.connection_id
    database_name = payload.database_name
    schema_name = payload.schema_name
    if not (connection_id and database_name and schema_name):
        resolved_connection, resolved_database, resolved_schema, _ = _resolve_scope_values(payload.tenant_id, domain_id)
        connection_id = connection_id or resolved_connection
        database_name = database_name or resolved_database
        schema_name = schema_name or resolved_schema

    refinement_input_id = create_refinement_input(
        settings,
        tenant_id=payload.tenant_id,
        domain_id=domain_id,
        connection_id=connection_id,
        database_name=database_name,
        schema_name=schema_name,
        source_run_id=payload.source_run_id,
        source_type=payload.source_type,
        refinement_kind=refinement_kind,
        source_text=payload.text,
        source_payload_json=payload.payload,
        source_context_id=payload.source_context_id,
        source_file_id=payload.source_file_id,
        conversation_id=payload.conversation_id,
        submitted_by=payload.submitted_by,
    )
    row = get_refinement_input(settings, refinement_input_id)
    artifacts: list[dict] = []
    semantic_state_id: str | None = None
    if row and payload.auto_process:
        artifacts = process_refinement_input(
            settings,
            row,
            auto_approve=True,
            approved_by=payload.submitted_by or "system:auto_approve",
        )
        row = get_refinement_input(settings, refinement_input_id) or row
        if payload.rebuild_state:
            state_result = rebuild_semantic_state(
                settings,
                tenant_id=payload.tenant_id,
                domain_id=domain_id,
                connection_id=connection_id,
                database_name=database_name,
                schema_name=schema_name,
                trigger_type="refinement_auto_approved",
            )
            semantic_state_id = state_result.get("semantic_state_id")
        enqueue_semantic_propagation_for_artifacts(
            settings,
            tenant_id=payload.tenant_id,
            domain_id=domain_id,
            connection_id=connection_id,
            database_name=database_name,
            schema_name=schema_name,
            artifacts=artifacts,
            trigger_type="refinement_auto_approved",
            semantic_state_id=semantic_state_id,
        )
    return _refinement_response(row or {"refinement_input_id": refinement_input_id}, artifacts, semantic_state_id)


@app.get(
    "/semantic/refinements",
    response_model=SemanticRefinementListResponse,
    tags=["semantic"],
    summary="List semantic refinements",
)
def list_semantic_refinements(
    tenant_id: str,
    domain_id: str | None = None,
    status: str | None = None,
    refinement_kind: str | None = None,
    submitted_by: str | None = None,
    include_artifacts: bool = True,
    limit: int = 100,
) -> SemanticRefinementListResponse:
    resolved_domain_id = _resolve_domain_id(tenant_id, domain_id)
    rows = list_refinement_inputs(
        settings,
        tenant_id=tenant_id,
        domain_id=resolved_domain_id,
        status=status,
        refinement_kind=refinement_kind,
        submitted_by=submitted_by,
        limit=limit,
    )
    responses: list[SemanticRefinementResponse] = []
    for row in rows:
        artifacts = []
        if include_artifacts:
            artifacts = list_refinement_artifacts(
                settings,
                tenant_id=tenant_id,
                domain_id=resolved_domain_id,
                refinement_input_id=row.get("refinement_input_id"),
                limit=100,
            )
        responses.append(_refinement_response(row, artifacts))
    return SemanticRefinementListResponse(refinements=responses)


@app.get(
    "/semantic/refinements/{refinement_input_id}",
    response_model=SemanticRefinementResponse,
    tags=["semantic"],
    summary="Get a semantic refinement",
)
def get_semantic_refinement(refinement_input_id: str, tenant_id: str) -> SemanticRefinementResponse:
    row = get_refinement_input(settings, refinement_input_id)
    if not row or row.get("tenant_id") != tenant_id:
        raise HTTPException(status_code=404, detail="Refinement not found")
    artifacts = list_refinement_artifacts(
        settings,
        tenant_id=tenant_id,
        domain_id=row.get("domain_id"),
        refinement_input_id=refinement_input_id,
        limit=100,
    )
    return _refinement_response(row, artifacts)


@app.post(
    "/semantic/refinements/{refinement_input_id}/process",
    response_model=SemanticRefinementProcessResponse,
    tags=["semantic"],
    summary="Process a semantic refinement",
    description="Extract structured artifacts and auto-approve valid artifacts. Manual approval is deferred.",
)
def process_semantic_refinement(
    refinement_input_id: str,
    tenant_id: str,
    rebuild_state: bool = True,
) -> SemanticRefinementProcessResponse:
    row = get_refinement_input(settings, refinement_input_id)
    if not row or row.get("tenant_id") != tenant_id:
        raise HTTPException(status_code=404, detail="Refinement not found")
    artifacts = process_refinement_input(settings, row, auto_approve=True, approved_by="system:auto_approve")
    semantic_state_id = None
    if rebuild_state:
        state_result = rebuild_semantic_state(
            settings,
            tenant_id=tenant_id,
            domain_id=row.get("domain_id"),
            connection_id=row.get("connection_id"),
            database_name=row.get("database_name"),
            schema_name=row.get("schema_name"),
            trigger_type="refinement_process_auto_approved",
        )
        semantic_state_id = state_result.get("semantic_state_id")
    enqueue_semantic_propagation_for_artifacts(
        settings,
        tenant_id=tenant_id,
        domain_id=row.get("domain_id"),
        connection_id=row.get("connection_id"),
        database_name=row.get("database_name"),
        schema_name=row.get("schema_name"),
        artifacts=artifacts,
        trigger_type="refinement_process_auto_approved",
        semantic_state_id=semantic_state_id,
    )
    return SemanticRefinementProcessResponse(
        refinement_input_id=refinement_input_id,
        artifacts=[_refinement_artifact_response(item) for item in artifacts],
        semantic_state_id=semantic_state_id,
    )


@app.post(
    "/semantic/refinement-artifacts/{artifact_id}/approve",
    response_model=SemanticRefinementArtifactResponse,
    tags=["semantic"],
    summary="Approve a semantic refinement artifact",
    description="Mark a valid artifact approved, rebuild semantic state, and queue propagation when requested.",
)
def approve_semantic_refinement_artifact(
    artifact_id: str,
    payload: SemanticRefinementApprovalRequest,
) -> SemanticRefinementArtifactResponse:
    artifact = get_refinement_artifact(settings, artifact_id, tenant_id=payload.tenant_id)
    if not artifact:
        raise HTTPException(status_code=404, detail="Refinement artifact not found")
    if artifact.get("validation_status") != "valid":
        raise HTTPException(status_code=400, detail="Only valid artifacts can be approved")
    update_refinement_artifact_approval(
        settings,
        artifact_id,
        tenant_id=payload.tenant_id,
        approval_status="approved",
        approved_by=payload.approved_by or "system:manual_approval",
    )
    artifact = get_refinement_artifact(settings, artifact_id, tenant_id=payload.tenant_id) or artifact
    semantic_state_id = None
    if payload.rebuild_state:
        state_result = rebuild_semantic_state(
            settings,
            tenant_id=payload.tenant_id,
            domain_id=artifact.get("domain_id"),
            connection_id=artifact.get("connection_id"),
            database_name=artifact.get("database_name"),
            schema_name=artifact.get("schema_name"),
            trigger_type="manual_artifact_approved",
        )
        semantic_state_id = state_result.get("semantic_state_id")
        enqueue_semantic_propagation_for_artifacts(
            settings,
            tenant_id=payload.tenant_id,
            domain_id=artifact.get("domain_id"),
            connection_id=artifact.get("connection_id"),
            database_name=artifact.get("database_name"),
            schema_name=artifact.get("schema_name"),
            artifacts=[artifact],
            trigger_type="manual_artifact_approved",
            semantic_state_id=semantic_state_id,
        )
    return _refinement_artifact_response(artifact)


@app.post(
    "/semantic/refinement-artifacts/{artifact_id}/reject",
    response_model=SemanticRefinementArtifactResponse,
    tags=["semantic"],
    summary="Reject a semantic refinement artifact",
    description="Mark an artifact rejected and rebuild semantic state when requested.",
)
def reject_semantic_refinement_artifact(
    artifact_id: str,
    payload: SemanticRefinementApprovalRequest,
) -> SemanticRefinementArtifactResponse:
    artifact = get_refinement_artifact(settings, artifact_id, tenant_id=payload.tenant_id)
    if not artifact:
        raise HTTPException(status_code=404, detail="Refinement artifact not found")
    was_active = artifact.get("approval_status") in {"approved", "auto_approved"}
    update_refinement_artifact_approval(
        settings,
        artifact_id,
        tenant_id=payload.tenant_id,
        approval_status="rejected",
        approved_by=payload.approved_by or "system:manual_rejection",
    )
    artifact = get_refinement_artifact(settings, artifact_id, tenant_id=payload.tenant_id) or artifact
    if payload.rebuild_state and was_active:
        rebuild_semantic_state(
            settings,
            tenant_id=payload.tenant_id,
            domain_id=artifact.get("domain_id"),
            connection_id=artifact.get("connection_id"),
            database_name=artifact.get("database_name"),
            schema_name=artifact.get("schema_name"),
            trigger_type="manual_artifact_rejected",
        )
    return _refinement_artifact_response(artifact)


@app.get(
    "/semantic/state",
    response_model=SemanticStateResponse,
    tags=["semantic"],
    summary="Get current semantic state",
)
def get_semantic_state_endpoint(
    tenant_id: str,
    domain_id: str | None = None,
    connection_id: str | None = None,
    database_name: str | None = None,
    schema_name: str | None = None,
) -> SemanticStateResponse:
    resolved_domain_id = _resolve_domain_id(tenant_id, domain_id)
    if not (connection_id and database_name and schema_name):
        resolved_connection, resolved_database, resolved_schema, _ = _resolve_scope_values(tenant_id, resolved_domain_id)
        connection_id = connection_id or resolved_connection
        database_name = database_name or resolved_database
        schema_name = schema_name or resolved_schema
    row = get_current_semantic_state(
        settings,
        tenant_id=tenant_id,
        domain_id=resolved_domain_id,
        connection_id=connection_id,
        database_name=database_name,
        schema_name=schema_name,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Semantic state not found")
    return _semantic_state_response(row, tenant_id, resolved_domain_id)


@app.get(
    "/semantic/state/history",
    response_model=list[SemanticStateResponse],
    tags=["semantic"],
    summary="List semantic state history",
)
def list_semantic_state_history(
    tenant_id: str,
    domain_id: str | None = None,
    connection_id: str | None = None,
    database_name: str | None = None,
    schema_name: str | None = None,
    limit: int = 100,
) -> list[SemanticStateResponse]:
    resolved_domain_id = _resolve_domain_id(tenant_id, domain_id)
    rows = list_semantic_states(
        settings,
        tenant_id=tenant_id,
        domain_id=resolved_domain_id,
        connection_id=connection_id,
        database_name=database_name,
        schema_name=schema_name,
        limit=limit,
    )
    return [_semantic_state_response(row, tenant_id, resolved_domain_id) for row in rows]


@app.post(
    "/semantic/state/{semantic_state_id}/activate",
    response_model=SemanticStateResponse,
    tags=["semantic"],
    summary="Activate a previous semantic state",
    description="Rollback/activate a semantic state version by switching active state for its tenant/domain/scope.",
)
def activate_semantic_state_endpoint(
    semantic_state_id: str,
    payload: SemanticStateActivateRequest,
) -> SemanticStateResponse:
    row = get_semantic_state(settings, semantic_state_id, tenant_id=payload.tenant_id)
    if not row:
        raise HTTPException(status_code=404, detail="Semantic state not found")
    activated = activate_semantic_state(settings, semantic_state_id, tenant_id=payload.tenant_id)
    if not activated:
        raise HTTPException(status_code=404, detail="Semantic state not found")
    return _semantic_state_response(activated, payload.tenant_id, activated.get("domain_id") or "")


@app.post(
    "/semantic/state/rebuild",
    response_model=SemanticStateResponse,
    tags=["semantic"],
    summary="Rebuild semantic state",
    description="Build a new active semantic state snapshot from auto-approved/approved refinement artifacts and existing overrides.",
)
def rebuild_semantic_state_endpoint(payload: SemanticStateRebuildRequest) -> SemanticStateResponse:
    domain_id = _resolve_domain_id(payload.tenant_id, payload.domain_id)
    connection_id = payload.connection_id
    database_name = payload.database_name
    schema_name = payload.schema_name
    if not (connection_id and database_name and schema_name):
        resolved_connection, resolved_database, resolved_schema, _ = _resolve_scope_values(payload.tenant_id, domain_id)
        connection_id = connection_id or resolved_connection
        database_name = database_name or resolved_database
        schema_name = schema_name or resolved_schema
    result = rebuild_semantic_state(
        settings,
        tenant_id=payload.tenant_id,
        domain_id=domain_id,
        connection_id=connection_id,
        database_name=database_name,
        schema_name=schema_name,
        trigger_type=payload.trigger_type,
    )
    row = get_current_semantic_state(
        settings,
        tenant_id=payload.tenant_id,
        domain_id=domain_id,
        connection_id=connection_id,
        database_name=database_name,
        schema_name=schema_name,
    )
    return _semantic_state_response(row or {"semantic_state_id": result.get("semantic_state_id"), "state_json": result.get("state_json")}, payload.tenant_id, domain_id)


@app.post(
    "/semantic/propagation",
    response_model=SemanticPropagationJobResponse,
    tags=["semantic"],
    summary="Queue semantic propagation",
    description="Queue a selective propagation job for downstream semantic consumers. The runner is intentionally deferred.",
)
def create_semantic_propagation(payload: SemanticPropagationRequest) -> SemanticPropagationJobResponse:
    domain_id = _resolve_domain_id(payload.tenant_id, payload.domain_id)
    connection_id = payload.connection_id
    database_name = payload.database_name
    schema_name = payload.schema_name
    if not (connection_id and database_name and schema_name):
        resolved_connection, resolved_database, resolved_schema, _ = _resolve_scope_values(payload.tenant_id, domain_id)
        connection_id = connection_id or resolved_connection
        database_name = database_name or resolved_database
        schema_name = schema_name or resolved_schema
    affected_scope = payload.affected_scope or {
        "artifact_ids": [],
        "artifact_types": [],
        "refresh_actions": ["refresh_semantic_state"],
        "affected_tables": [],
        "affected_columns": [],
        "affected_metrics": [],
        "impact_level": "manual",
    }
    job_id = create_semantic_propagation_job(
        settings,
        tenant_id=payload.tenant_id,
        domain_id=domain_id,
        connection_id=connection_id,
        database_name=database_name,
        schema_name=schema_name,
        trigger_type=payload.trigger_type,
        affected_scope_json=affected_scope,
    )
    return _semantic_propagation_response(
        {
            "job_id": job_id,
            "tenant_id": payload.tenant_id,
            "domain_id": domain_id,
            "connection_id": connection_id,
            "database_name": database_name,
            "schema_name": schema_name,
            "trigger_type": payload.trigger_type,
            "affected_scope_json": affected_scope,
            "status": "queued",
        },
        payload.tenant_id,
        domain_id,
    )


@app.get(
    "/semantic/propagation",
    response_model=SemanticPropagationListResponse,
    tags=["semantic"],
    summary="List semantic propagation jobs",
)
def list_semantic_propagation(
    tenant_id: str,
    domain_id: str | None = None,
    status: str | None = None,
    connection_id: str | None = None,
    database_name: str | None = None,
    schema_name: str | None = None,
    limit: int = 100,
) -> SemanticPropagationListResponse:
    resolved_domain_id = _resolve_domain_id(tenant_id, domain_id)
    rows = list_semantic_propagation_jobs(
        settings,
        tenant_id=tenant_id,
        domain_id=resolved_domain_id,
        connection_id=connection_id,
        database_name=database_name,
        schema_name=schema_name,
        status=status,
        limit=limit,
    )
    return SemanticPropagationListResponse(
        jobs=[_semantic_propagation_response(row, tenant_id, resolved_domain_id) for row in rows]
    )


@app.post(
    "/semantic/propagation/{job_id}/run",
    response_model=SemanticPropagationJobResponse,
    tags=["semantic"],
    summary="Run a semantic propagation job",
    description=(
        "Run queued semantic propagation actions best-effort. Currently this rebuilds semantic state, "
        "recomputes chart interaction metadata, and queues dashboard refresh jobs where possible."
    ),
)
def run_semantic_propagation(job_id: str, tenant_id: str) -> SemanticPropagationJobResponse:
    try:
        row = run_semantic_propagation_job(settings, job_id, tenant_id=tenant_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Semantic propagation job not found")
    return _semantic_propagation_response(row, tenant_id, row.get("domain_id") or "")


@app.post(
    "/semantic/feedback",
    response_model=SemanticFeedbackResponse,
    tags=["governance"],
    summary="Submit semantic feedback",
    description="Legacy semantic edge feedback endpoint.",
)
def semantic_feedback(payload: SemanticFeedbackRequest) -> SemanticFeedbackResponse:
    domain_id = _resolve_domain_id(payload.tenant_id, payload.domain_id)
    record = create_semantic_feedback(
        settings,
        tenant_id=payload.tenant_id,
        domain_id=domain_id,
        edge_id=payload.edge_id,
        action=payload.action,
        delta_confidence=payload.delta_confidence,
        notes=payload.notes,
    )
    apply_semantic_feedback(settings, payload.edge_id, payload.delta_confidence)
    return SemanticFeedbackResponse(**record)


@app.get(
    "/semantic/feedback",
    response_model=list[SemanticFeedbackResponse],
    tags=["governance"],
    summary="List semantic feedback",
)
def list_semantic_feedback_endpoint(tenant_id: str, domain_id: str | None = None) -> list[SemanticFeedbackResponse]:
    rows = list_semantic_feedback(settings, tenant_id, domain_id)
    return [SemanticFeedbackResponse(**row) for row in rows]


@app.get(
    "/charts/{chart_id}",
    response_model=ChartStatusResponse,
    tags=["charts"],
    summary="Get chart status and payload",
    openapi_extra={
        "parameters": [
            {
                "name": "refresh",
                "in": "query",
                "required": False,
                "schema": {"type": "boolean", "default": False},
                "description": "If true, re-run the SQL and refresh chart payload/data.",
            }
        ],
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "ready": {
                                "summary": "Chart ready",
                                "value": {
                                    "chart_id": "chart_2f7a9c4d",
                                    "status": "ready",
                                    "chart_type": "bar",
                                    "chart_payload": {
                                        "chart": {"type": "XYChart"},
                                        "xAxis": {"type": "CategoryAxis", "categoryField": "category"},
                                        "yAxis": {"type": "ValueAxis"},
                                    },
                                    "data": [
                                        {"category": "Plant A", "value": 123.4},
                                        {"category": "Plant B", "value": 98.1},
                                    ],
                                },
                            }
                        }
                    }
                }
            }
        }
    },
)
def get_chart(chart_id: str, refresh: bool = False) -> ChartStatusResponse:
    row = get_chart_request(settings, chart_id)
    if not row:
        raise HTTPException(status_code=404, detail="Chart not found")
    existing_interaction_context = row.get("interaction_context_json") if isinstance(row, dict) else None
    if refresh:
        if not row.get("sql"):
            raise HTTPException(status_code=400, detail="No SQL stored for chart")
        logger.info("charts.refresh | chart_id=%s sql=%s params=%s", chart_id, row.get("sql"), row.get("params"))
        try:
            _chart_tenant_id = row.get("tenant_id")
            _chart_domain_id = row.get("domain_id")
            _chart_scoped_conn = None
            if _chart_tenant_id and _chart_domain_id:
                _chart_scoped_conn = _resolve_scoped_conn(_chart_tenant_id, _chart_domain_id)
            rows = run_query(settings, row.get("sql") or "", row.get("params") or [], scoped_conn=_chart_scoped_conn)
            _refresh_chart_type = row.get("chart_type") or "bar"
            _refresh_metric = (row.get("query_payload") or {}).get("metrics", [None])[0] or "metric"
            _refresh_dims = (row.get("query_payload") or {}).get("dimensions", []) or ["category"]
            _refresh_dim_key = _refresh_dims[0] if _refresh_dims else None
            payload = build_chart_payload(_refresh_chart_type, rows, _refresh_metric, _refresh_dims)
            inference = build_chart_inference(
                settings,
                chart_type=_refresh_chart_type,
                rows=rows,
                metric_name=_refresh_metric,
                dim_key=_refresh_dim_key,
                chart_title=row.get("title"),
            )
            update_chart_request(
                settings,
                chart_id,
                status="ready",
                rows_json=rows,
                chart_payload=payload.get("chart_payload"),
                chart_data=payload.get("data"),
                insight_text=inference["insight_text"],
                narrative_text=inference["narrative_text"],
                stats_json=inference["stats_json"],
            )
            row = get_chart_request(settings, chart_id)
            logger.info(
                "charts.refresh | chart_id=%s rows=%s sample=%s",
                chart_id,
                len(rows),
                rows[0] if rows else None,
            )
        except Exception as exc:
            logger.exception("charts.refresh failed | chart_id=%s", chart_id)
            update_chart_request(
                settings,
                chart_id,
                status="failed",
                error_message=str(exc),
            )
            row = get_chart_request(settings, chart_id)
    row = ensure_chart_interaction_metadata(settings, row)
    interaction_response = build_chart_interaction_response(
        chart_row=row,
        interaction_context=row.get("interaction_context_json") if isinstance(row, dict) else None,
    )
    breadcrumb, lineage_summary = _reconstruct_chart_breadcrumb(row)
    interaction_response["breadcrumb"] = breadcrumb
    interaction_response["lineage_summary"] = {
        **(interaction_response.get("lineage_summary") or {}),
        **lineage_summary,
    }
    if not existing_interaction_context and interaction_response:
        update_chart_request(
            settings,
            chart_id,
            interaction_context_json=row.get("interaction_context_json") or {},
            lineage_json=(row.get("lineage_json") or {}),
            root_chart_id=row.get("root_chart_id") or row.get("chart_id"),
        )
    return ChartStatusResponse(
        chart_id=row["chart_id"],
        status=row.get("status"),
        chart_type=row.get("chart_type"),
        chart_payload=row.get("chart_payload"),
        data=row.get("chart_data"),
        sql=row.get("sql"),
        params=row.get("params"),
        rows_json=row.get("rows_json"),
        error_message=row.get("error_message"),
        insight_text=row.get("insight_text"),
        narrative_text=row.get("narrative_text"),
        stats_json=row.get("stats_json"),
        conversation_ids=row.get("conversation_ids") or [],
        interaction_context=interaction_response.get("interaction_context"),
        available_filters=interaction_response.get("available_filters"),
        available_drilldowns=interaction_response.get("available_drilldowns"),
        available_dimension_navigation=interaction_response.get("available_dimension_navigation"),
        suggested_drilldowns=interaction_response.get("suggested_drilldowns"),
        available_areas=interaction_response.get("available_areas"),
        breadcrumb=interaction_response.get("breadcrumb"),
        lineage_summary=interaction_response.get("lineage_summary"),
    )


def _reconstruct_chart_breadcrumb(chart_row: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    chain: list[dict[str, Any]] = []
    seen: set[str] = set()
    current = chart_row
    while current and isinstance(current, dict):
        chart_id = str(current.get("chart_id") or "").strip()
        if not chart_id or chart_id in seen:
            break
        seen.add(chart_id)
        current = ensure_chart_interaction_metadata(settings, current)
        interaction_context = current.get("interaction_context_json") or {}
        lineage = interaction_context.get("lineage") or current.get("lineage_json") or {}
        chain.append(
            {
                "chart_id": chart_id,
                "title": current.get("title") or current.get("question"),
                "level_id": interaction_context.get("current_level"),
                "interaction_type": lineage.get("interaction_type"),
                "source_level_id": lineage.get("source_level_id"),
                "target_level_id": lineage.get("target_level_id"),
                "filters_added": lineage.get("filters_added") or [],
                "selected_dimension": lineage.get("selected_dimension"),
                "selected_value": lineage.get("selected_value"),
                "action_label": lineage.get("action_label"),
                "hierarchy_id": lineage.get("hierarchy_id"),
            }
        )
        parent_chart_id = str(current.get("parent_chart_id") or "").strip()
        if not parent_chart_id:
            break
        current = get_chart_request(settings, parent_chart_id)
    chain.reverse()
    current_chart_id = str(chart_row.get("chart_id") or "").strip()
    back_chart_id = chain[-2]["chart_id"] if len(chain) >= 2 else None
    lineage_summary = {
        "root_chart_id": chain[0]["chart_id"] if chain else (chart_row.get("root_chart_id") or current_chart_id),
        "parent_chart_id": chart_row.get("parent_chart_id"),
        "current_chart_id": current_chart_id,
        "depth": max(len(chain) - 1, 0),
        "can_go_back": bool(back_chart_id),
        "back_chart_id": back_chart_id,
        "lineage_path_chart_ids": [item.get("chart_id") for item in chain],
    }
    return chain, lineage_summary


def _build_lineage_payload(
    *,
    row: dict[str, Any],
    interaction_type: str,
    source_level_id: str | None = None,
    target_level_id: str | None = None,
    filters_before: list[dict[str, Any]] | None = None,
    filters_added: list[dict[str, Any]] | None = None,
    filters_after: list[dict[str, Any]] | None = None,
    selected_dimension: str | None = None,
    selected_value: Any = None,
    hierarchy_id: str | None = None,
    action_label: str | None = None,
) -> dict[str, Any]:
    return {
        "root_chart_id": row.get("root_chart_id") or row.get("chart_id"),
        "parent_chart_id": row.get("chart_id"),
        "interaction_type": interaction_type,
        "source_level_id": source_level_id,
        "target_level_id": target_level_id,
        "filters_before": filters_before or [],
        "filters_added": filters_added or [],
        "filters_after": filters_after or [],
        "selected_dimension": selected_dimension,
        "selected_value": selected_value,
        "hierarchy_id": hierarchy_id,
        "action_label": action_label,
    }


@app.get(
    "/charts/{chart_id}/actions",
    tags=["charts"],
    summary="Get available deterministic chart actions",
)
def get_chart_actions(chart_id: str) -> dict:
    row = get_chart_request(settings, chart_id)
    if not row:
        raise HTTPException(status_code=404, detail="Chart not found")
    row = ensure_chart_interaction_metadata(settings, row)
    interaction_response = build_chart_interaction_response(
        chart_row=row,
        interaction_context=row.get("interaction_context_json") if isinstance(row, dict) else None,
    )
    breadcrumb, lineage_summary = _reconstruct_chart_breadcrumb(row)
    interaction_response["breadcrumb"] = breadcrumb
    interaction_response["lineage_summary"] = {
        **(interaction_response.get("lineage_summary") or {}),
        **lineage_summary,
    }
    return {
        "chart_id": chart_id,
        "available_filters": interaction_response.get("available_filters") or [],
        "available_drilldowns": interaction_response.get("available_drilldowns") or [],
        "available_dimension_navigation": interaction_response.get("available_dimension_navigation") or [],
        "suggested_drilldowns": interaction_response.get("suggested_drilldowns") or [],
        "available_areas": interaction_response.get("available_areas") or {},
        "breadcrumb": interaction_response.get("breadcrumb") or [],
        "lineage_summary": interaction_response.get("lineage_summary") or {},
    }


def _persist_derived_interaction_chart(
    *,
    source_row: dict[str, Any],
    title: str,
    query_payload: dict[str, Any],
    compiled: dict[str, Any],
    interaction_type: str,
    interaction_context_json: dict[str, Any],
    lineage_json: dict[str, Any],
    drill_hierarchy_id: str | None = None,
    drill_level_id: str | None = None,
) -> str:
    tenant_id = str(source_row.get("tenant_id") or "")
    domain_id = str(source_row.get("domain_id") or "").strip() or None
    created = create_chart_request(
        settings,
        tenant_id=tenant_id,
        domain_id=domain_id,
        question=title,
        query_payload=query_payload,
        sql=compiled.get("sql"),
        params=compiled.get("params") or [],
        rows_json=compiled.get("rows") or [],
        run_id=source_row.get("run_id"),
        chart_source=source_row.get("chart_source") or "chart_interaction",
        title=title,
        created_by="ChartInteractionAgent",
        interaction_context_json=interaction_context_json,
        lineage_json=lineage_json,
        parent_chart_id=source_row.get("chart_id"),
        root_chart_id=source_row.get("root_chart_id") or source_row.get("chart_id"),
        drill_hierarchy_id=drill_hierarchy_id,
        drill_level_id=drill_level_id,
    )
    chart_id = str((created or {}).get("chart_id") or "").strip()
    if not chart_id:
        raise HTTPException(status_code=500, detail="Failed to create derived chart")
    rebuilt_row = {
        **source_row,
        "chart_id": chart_id,
        "question": title,
        "title": title,
        "query_payload": query_payload,
        "rows_json": compiled.get("rows") or [],
        "chart_type": compiled.get("chart_type"),
        "parent_chart_id": source_row.get("chart_id"),
        "root_chart_id": source_row.get("root_chart_id") or source_row.get("chart_id"),
        "lineage_json": lineage_json,
        "drill_hierarchy_id": drill_hierarchy_id,
        "drill_level_id": drill_level_id,
    }
    hierarchies = list_business_hierarchies(settings, tenant_id, domain_id)
    rebuilt_interaction_context = build_chart_interaction_context(
        chart_row=rebuilt_row,
        hierarchies=hierarchies,
    )
    inference = compiled.get("inference") or {}
    update_chart_request(
        settings,
        chart_id,
        status="ready",
        sql=compiled.get("sql"),
        params=compiled.get("params") or [],
        rows_json=compiled.get("rows") or [],
        chart_type=compiled.get("chart_type"),
        chart_payload=compiled.get("chart_payload"),
        chart_data=compiled.get("chart_data"),
        insight_text=inference.get("insight_text"),
        narrative_text=inference.get("narrative_text"),
        stats_json=inference.get("stats_json"),
        interaction_context_json=rebuilt_interaction_context,
        lineage_json=lineage_json,
        parent_chart_id=source_row.get("chart_id"),
        root_chart_id=source_row.get("root_chart_id") or source_row.get("chart_id"),
        drill_hierarchy_id=drill_hierarchy_id,
        drill_level_id=drill_level_id,
    )
    create_chart_event(
        settings,
        chart_id,
        "ready",
        details={"interaction_type": interaction_type, "source_chart_id": source_row.get("chart_id")},
    )
    return chart_id


@app.post(
    "/charts/{chart_id}/filter",
    response_model=ChartStatusResponse,
    tags=["charts"],
    summary="Create a deterministically filtered derived chart",
)
def filter_chart(chart_id: str, request: ChartFilterRequest) -> ChartStatusResponse:
    row = get_chart_request(settings, chart_id)
    if not row:
        raise HTTPException(status_code=404, detail="Chart not found")
    row = ensure_chart_interaction_metadata(settings, row)
    interaction_context = row.get("interaction_context_json") or {}
    allowed_fields = {str(item.get("field") or "") for item in (interaction_context.get("available_filter_fields") or []) if str(item.get("field") or "").strip()}
    compiled_filters = []
    for flt in request.filters or []:
        if str(flt.field or "").strip() not in allowed_fields:
            raise HTTPException(status_code=400, detail=f"Unsupported chart filter field: {flt.field}")
        compiled_filters.append({"field": flt.field, "operator": flt.operator, "value": flt.value})
    tenant_id = str(row.get("tenant_id") or "")
    domain_id = str(row.get("domain_id") or "")
    scoped_conn = _resolve_scoped_conn(tenant_id, domain_id) if tenant_id and domain_id else None
    try:
        compiled = execute_chart_compilation(
            settings,
            chart_row=row,
            interaction_context=interaction_context,
            appended_filters=compiled_filters,
            scoped_conn=scoped_conn,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    filters_before = list(interaction_context.get("filters") or [])
    filters_after = [*filters_before, *compiled_filters]
    lineage_json = _build_lineage_payload(
        row=row,
        interaction_type="filter",
        source_level_id=str(interaction_context.get("current_level") or "").strip() or None,
        target_level_id=str(interaction_context.get("current_level") or "").strip() or None,
        filters_before=filters_before,
        filters_added=compiled_filters,
        filters_after=filters_after,
        action_label="Apply chart filters",
    )
    new_interaction_context = {
        **interaction_context,
        "filters": filters_after,
        "lineage": lineage_json,
    }
    title = f"{str(row.get('title') or row.get('question') or 'Chart')} — Filtered"
    query_payload = {
        **(row.get("query_payload") or {}),
        "filters": new_interaction_context.get("filters") or [],
        "source_chart_id": row.get("chart_id"),
    }
    derived_chart_id = _persist_derived_interaction_chart(
        source_row=row,
        title=title,
        query_payload=query_payload,
        compiled=compiled,
        interaction_type="filter",
        interaction_context_json=new_interaction_context,
        lineage_json=lineage_json,
    )
    import uuid
    create_chart_interaction(
        settings,
        interaction_id=f"ci_{uuid.uuid4().hex[:10]}",
        tenant_id=tenant_id,
        domain_id=domain_id or None,
        source_chart_id=str(row.get("chart_id")),
        result_chart_id=derived_chart_id,
        interaction_type="filter",
        source_level_id=str(interaction_context.get("current_level") or "").strip() or None,
        target_level_id=str(interaction_context.get("current_level") or "").strip() or None,
        interaction_payload_json=lineage_json,
    )
    return get_chart(derived_chart_id, refresh=False)


def _resolve_chart_navigation(
    *,
    row: dict,
    request: ChartNavigationRequest,
    expected_action_type: str | None = None,
) -> tuple[dict, dict, str, dict]:
    row = ensure_chart_interaction_metadata(settings, row)
    interaction_context = row.get("interaction_context_json") or {}
    navigations = [
        item for item in (interaction_context.get("available_dimension_navigation") or [])
        if str(item.get("target_level_id") or item.get("target_level") or "").strip()
    ]
    target = str(request.target_level_id or "").strip()
    if not target:
        raise HTTPException(status_code=400, detail="Navigation target_level_id is required")
    chosen = next(
        (
            item for item in navigations
            if str(item.get("target_level_id") or item.get("target_level") or "").strip() == target
        ),
        None,
    )
    if not chosen:
        raise HTTPException(status_code=400, detail=f"Unsupported chart navigation target: {target}")
    actual_action_type = str(chosen.get("action_type") or "switch_level").strip() or "switch_level"
    if expected_action_type and actual_action_type != expected_action_type:
        raise HTTPException(
            status_code=400,
            detail=f"Target '{target}' is '{actual_action_type}', not '{expected_action_type}'",
        )
    return row, interaction_context, target, chosen


def _nearest_navigation_target(
    interaction_context: dict,
    *,
    action_type: str,
) -> str | None:
    candidates = [
        item for item in (interaction_context.get("available_dimension_navigation") or [])
        if str(item.get("action_type") or "").strip() == action_type
        and str(item.get("target_level_id") or item.get("target_level") or "").strip()
    ]
    if not candidates:
        return None
    ranked = sorted(
        candidates,
        key=lambda item: (
            int(item.get("distance") or item.get("priority") or 999),
            str(item.get("target_level_id") or item.get("target_level") or ""),
        ),
    )
    return str(ranked[0].get("target_level_id") or ranked[0].get("target_level") or "").strip() or None


@app.post(
    "/charts/{chart_id}/navigate",
    response_model=ChartStatusResponse,
    tags=["charts"],
    summary="Create a deterministically navigated derived chart",
)
def navigate_chart(chart_id: str, request: ChartNavigationRequest) -> ChartStatusResponse:
    row = get_chart_request(settings, chart_id)
    if not row:
        raise HTTPException(status_code=404, detail="Chart not found")
    row, interaction_context, target, chosen = _resolve_chart_navigation(row=row, request=request)
    current_level = str(interaction_context.get("current_level") or "")
    appended_filters = list(interaction_context.get("filters") or [])
    if request.selected_dimension and request.selected_value not in (None, "", []):
        appended_filters = [
            *appended_filters,
            {"field": request.selected_dimension, "operator": "=", "value": request.selected_value},
        ]
    tenant_id = str(row.get("tenant_id") or "")
    domain_id = str(row.get("domain_id") or "")
    scoped_conn = _resolve_scoped_conn(tenant_id, domain_id) if tenant_id and domain_id else None
    try:
        compiled = execute_chart_compilation(
            settings,
            chart_row=row,
            interaction_context=interaction_context,
            override_dimensions=[target],
            appended_filters=appended_filters,
            scoped_conn=scoped_conn,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    action_type = str(chosen.get("action_type") or "switch_level")
    action_verb = {
        "drill_down": "Drill to",
        "drill_up": "Roll up to",
        "switch_level": "Switch to",
    }.get(action_type, "View by")
    lineage_json = _build_lineage_payload(
        row=row,
        interaction_type=action_type,
        source_level_id=current_level or None,
        target_level_id=target,
        filters_before=list(interaction_context.get("filters") or []),
        filters_added=[
            {"field": request.selected_dimension, "operator": "=", "value": request.selected_value}
        ] if request.selected_dimension and request.selected_value not in (None, "", []) else [],
        filters_after=appended_filters,
        selected_dimension=request.selected_dimension,
        selected_value=request.selected_value,
        hierarchy_id=str(chosen.get("hierarchy_id") or "").strip() or None,
        action_label=f"{action_verb} {target.replace('_', ' ').title()}",
    )
    new_interaction_context = {
        **interaction_context,
        "query_shape": {
            **(interaction_context.get("query_shape") or {}),
            "group_dimensions": [target],
        },
        "filters": appended_filters,
        "current_level": target,
        "lineage": lineage_json,
    }
    title = f"{str(row.get('title') or row.get('question') or 'Chart')} — {action_verb} {target.replace('_', ' ').title()}"
    query_payload = {
        **(row.get("query_payload") or {}),
        "dimensions": [target],
        "source_dimensions": [target],
        "filters": appended_filters,
        "source_chart_id": row.get("chart_id"),
    }
    derived_chart_id = _persist_derived_interaction_chart(
        source_row=row,
        title=title,
        query_payload=query_payload,
        compiled=compiled,
        interaction_type=action_type,
        interaction_context_json=new_interaction_context,
        lineage_json=lineage_json,
        drill_hierarchy_id=str(chosen.get("hierarchy_id") or "").strip() or None,
        drill_level_id=target,
    )
    import uuid
    create_chart_interaction(
        settings,
        interaction_id=f"ci_{uuid.uuid4().hex[:10]}",
        tenant_id=tenant_id,
        domain_id=domain_id or None,
        source_chart_id=str(row.get("chart_id")),
        result_chart_id=derived_chart_id,
        interaction_type=action_type,
        selected_dimension=request.selected_dimension,
        selected_value_json=request.selected_value,
        source_level_id=current_level or None,
        target_level_id=target,
        interaction_payload_json=lineage_json,
    )
    return get_chart(derived_chart_id, refresh=False)


@app.post(
    "/charts/{chart_id}/back",
    response_model=ChartStatusResponse,
    tags=["charts"],
    summary="Return the previous chart state in the interaction lineage",
)
def back_chart(chart_id: str) -> ChartStatusResponse:
    row = get_chart_request(settings, chart_id)
    if not row:
        raise HTTPException(status_code=404, detail="Chart not found")
    parent_chart_id = str(row.get("parent_chart_id") or "").strip()
    if not parent_chart_id:
        raise HTTPException(status_code=400, detail="No previous chart state available")
    return get_chart(parent_chart_id, refresh=False)


@app.post(
    "/charts/{chart_id}/drill-down",
    response_model=ChartStatusResponse,
    tags=["charts"],
    summary="Create a deterministic drill-down derived chart",
)
def drill_down_chart(chart_id: str, request: ChartNavigationRequest) -> ChartStatusResponse:
    row = get_chart_request(settings, chart_id)
    if not row:
        raise HTTPException(status_code=404, detail="Chart not found")
    row = ensure_chart_interaction_metadata(settings, row)
    if not request.target_level_id:
        target = _nearest_navigation_target(row.get("interaction_context_json") or {}, action_type="drill_down")
        if not target:
            raise HTTPException(status_code=400, detail="No drill-down target available for this chart")
        request = ChartNavigationRequest(
            target_level_id=target,
            selected_dimension=request.selected_dimension,
            selected_value=request.selected_value,
        )
    _resolve_chart_navigation(row=row, request=request, expected_action_type="drill_down")
    return navigate_chart(chart_id, request)


@app.post(
    "/charts/{chart_id}/drill-up",
    response_model=ChartStatusResponse,
    tags=["charts"],
    summary="Create a deterministic drill-up derived chart",
)
def drill_up_chart(chart_id: str, request: ChartNavigationRequest) -> ChartStatusResponse:
    row = get_chart_request(settings, chart_id)
    if not row:
        raise HTTPException(status_code=404, detail="Chart not found")
    row = ensure_chart_interaction_metadata(settings, row)
    if not request.target_level_id:
        target = _nearest_navigation_target(row.get("interaction_context_json") or {}, action_type="drill_up")
        if not target:
            parent_chart_id = str(row.get("parent_chart_id") or "").strip()
            if parent_chart_id:
                return get_chart(parent_chart_id, refresh=False)
            raise HTTPException(status_code=400, detail="No drill-up target available for this chart")
        request = ChartNavigationRequest(
            target_level_id=target,
            selected_dimension=request.selected_dimension,
            selected_value=request.selected_value,
        )
    _resolve_chart_navigation(row=row, request=request, expected_action_type="drill_up")
    return navigate_chart(chart_id, request)


@app.post(
    "/charts/{chart_id}/switch-level",
    response_model=ChartStatusResponse,
    tags=["charts"],
    summary="Create a deterministic level-switch derived chart",
)
def switch_level_chart(chart_id: str, request: ChartNavigationRequest) -> ChartStatusResponse:
    row = get_chart_request(settings, chart_id)
    if not row:
        raise HTTPException(status_code=404, detail="Chart not found")
    row = ensure_chart_interaction_metadata(settings, row)
    if not request.target_level_id:
        target = _nearest_navigation_target(row.get("interaction_context_json") or {}, action_type="switch_level")
        if not target:
            raise HTTPException(status_code=400, detail="No level-switch target available for this chart")
        request = ChartNavigationRequest(
            target_level_id=target,
            selected_dimension=request.selected_dimension,
            selected_value=request.selected_value,
        )
    _resolve_chart_navigation(row=row, request=request, expected_action_type="switch_level")
    return navigate_chart(chart_id, request)


@app.get(
    "/charts/{chart_id}/interaction-context",
    tags=["charts"],
    summary="Inspect stored chart interaction metadata",
)
def get_chart_interaction_context(chart_id: str, refresh: bool = Query(default=False)) -> dict:
    row = get_chart_request(settings, chart_id)
    if not row:
        raise HTTPException(status_code=404, detail="Chart not found")
    if refresh:
        row = ensure_chart_interaction_metadata(settings, row)
    interaction_context = row.get("interaction_context_json") or {}
    tenant_id = str(row.get("tenant_id") or "").strip()
    domain_id = str(row.get("domain_id") or "").strip() or None
    hierarchies = list_business_hierarchies(settings, tenant_id, domain_id) if tenant_id else []
    return {
        "chart_id": chart_id,
        "interaction_context": interaction_context,
        "lineage_json": row.get("lineage_json") or {},
        "parent_chart_id": row.get("parent_chart_id"),
        "root_chart_id": row.get("root_chart_id") or row.get("chart_id"),
        "drill_hierarchy_id": row.get("drill_hierarchy_id"),
        "drill_level_id": row.get("drill_level_id"),
        "hierarchies": hierarchies,
    }


@app.get(
    "/charts/plan",
    tags=["charts"],
    summary="Get chart plan for a dashboard",
    description="Return chart_candidates and chart_plan stored in the dashboard spec.",
)
def get_chart_plan(dashboard_id: str) -> dict:
    row = get_dashboard_spec(settings, dashboard_id)
    if not row:
        raise HTTPException(status_code=404, detail="Dashboard not found")
    spec = row.get("spec") or {}
    return {
        "dashboard_id": dashboard_id,
        "chart_candidates": spec.get("chart_candidates") or [],
        "chart_plan": spec.get("chart_plan") or [],
    }


# ---------------------------------------------------------------------------
# Phase 42: Chart Conversations and User Dashboard Management
# ---------------------------------------------------------------------------


@app.post(
    "/agentic/conversations",
    tags=["agentic"],
    summary="Create a new agentic conversation",
    status_code=201,
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "basic": {
                            "summary": "Create a conversation for a run",
                            "value": {
                                "run_id": "run_abc123def456",
                                "tenant_id": "a13",
                                "domain_id": "market_performance_analysis",
                            },
                        },
                        "from_chart": {
                            "summary": "Create a conversation linked to a chart",
                            "value": {
                                "run_id": "run_abc123def456",
                                "tenant_id": "a13",
                                "domain_id": "market_performance_analysis",
                                "source_chart_id": "chart_344ec6b3c9",
                            },
                        },
                    }
                }
            }
        },
        "responses": {
            "201": {
                "content": {
                    "application/json": {
                        "examples": {
                            "created": {
                                "summary": "Conversation created",
                                "value": {
                                    "conversation_id": "conv_6f0f0f1a2b3c",
                                    "tenant_id": "a13",
                                    "domain_id": "market_performance_analysis",
                                    "run_id": "run_abc123def456",
                                    "title": "Market Performance Analysis Conversation",
                                    "display_name": "Market Performance Analysis Conversation",
                                    "status": "active",
                                    "source_chart_id": None,
                                    "run_display_name": "Market Performance Analysis Deployment v2",
                                    "created_at": "2026-03-25T10:00:00Z",
                                    "updated_at": "2026-03-25T10:00:00Z",
                                },
                            }
                        }
                    }
                }
            }
        },
    },
)
def create_agentic_conversation(body: CreateConversationRequest) -> dict:
    run_row = run_query(
        settings,
        "SELECT run_id, tenant_id, domain_id, display_name FROM public.quantyx_agent_runs WHERE run_id = %s LIMIT 1",
        [body.run_id],
    )
    if not run_row:
        raise HTTPException(status_code=404, detail=f"Run {body.run_id!r} not found")
    run = run_row[0]
    title = generate_conversation_title(None, body.domain_id)
    conversation = create_workspace_conversation(
        settings,
        tenant_id=body.tenant_id,
        domain_id=body.domain_id,
        run_id=body.run_id,
        title=title,
        source_chart_id=body.source_chart_id,
    )
    return {**conversation, "run_display_name": run.get("display_name")}


@app.get(
    "/charts/{chart_id}/conversations",
    tags=["charts"],
    summary="List conversations started from a chart",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "with_conversations": {
                                "summary": "Chart has linked conversations",
                                "value": {
                                    "chart_id": "chart_344ec6b3c9",
                                    "total": 2,
                                    "conversations": [
                                        {
                                            "conversation_id": "conv_6f0f0f1a2b3c",
                                            "tenant_id": "a13",
                                            "domain_id": "market_performance_analysis",
                                            "run_id": "run_abc123def456",
                                            "source_chart_id": "chart_344ec6b3c9",
                                            "title": "Daily Sales Deep Dive",
                                            "status": "active",
                                            "message_count": 7,
                                            "created_at": "2026-03-25T10:00:00Z",
                                            "updated_at": "2026-03-25T10:05:00Z",
                                        },
                                        {
                                            "conversation_id": "conv_9a1b2c3d4e5f",
                                            "tenant_id": "a13",
                                            "domain_id": "market_performance_analysis",
                                            "run_id": "run_abc123def456",
                                            "source_chart_id": "chart_344ec6b3c9",
                                            "title": "Market Performance Analysis Conversation",
                                            "status": "active",
                                            "message_count": 3,
                                            "created_at": "2026-03-24T09:00:00Z",
                                            "updated_at": "2026-03-24T09:10:00Z",
                                        },
                                    ],
                                },
                            },
                            "no_conversations": {
                                "summary": "No conversations linked to this chart yet",
                                "value": {
                                    "chart_id": "chart_c762fa59d7",
                                    "total": 0,
                                    "conversations": [],
                                },
                            },
                        }
                    }
                }
            }
        }
    },
)
def list_chart_conversations(
    chart_id: str,
    tenant_id: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    conversations = list_conversations_by_chart(
        settings,
        chart_id=chart_id,
        tenant_id=tenant_id,
        limit=limit,
        offset=offset,
    )
    return {"chart_id": chart_id, "total": len(conversations), "conversations": conversations}


@app.post(
    "/dashboards",
    tags=["dashboards"],
    summary="Create a dashboard",
    status_code=201,
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "sales_overview": {
                            "summary": "Create a sales overview dashboard",
                            "value": {
                                "tenant_id": "a13",
                                "domain_id": "market_performance_analysis",
                                "name": "HPCL Sales Overview",
                                "description": "Key sales and target charts for FY2026",
                                "created_by": "user_001",
                            },
                        },
                        "minimal": {
                            "summary": "Minimal — name only",
                            "value": {
                                "tenant_id": "a13",
                                "domain_id": "market_performance_analysis",
                                "name": "My Dashboard",
                            },
                        },
                    }
                }
            }
        },
        "responses": {
            "201": {
                "content": {
                    "application/json": {
                        "examples": {
                            "created": {
                                "summary": "Dashboard created",
                                "value": {
                                    "dashboard_id": "udash_a1b2c3d4e5",
                                    "tenant_id": "a13",
                                    "domain_id": "market_performance_analysis",
                                    "name": "HPCL Sales Overview",
                                    "description": "Key sales and target charts for FY2026",
                                    "status": "active",
                                    "chart_count": 0,
                                    "created_by": "user_001",
                                    "created_at": "2026-03-25T10:00:00Z",
                                    "updated_at": "2026-03-25T10:00:00Z",
                                },
                            }
                        }
                    }
                }
            }
        },
    },
)
def create_dashboard_endpoint(body: CreateDashboardRequest) -> dict:
    return _ds_create_dashboard(
        settings,
        tenant_id=body.tenant_id,
        domain_id=body.domain_id,
        name=body.name,
        description=body.description,
        dashboard_type=getattr(body, "dashboard_type", "user") or "user",
        created_by=body.created_by,
    )


@app.get(
    "/dashboards/",
    tags=["dashboards"],
    include_in_schema=False,  # retired — use GET /dashboards (no trailing slash)
    summary="List user dashboards for a tenant (deprecated alias)",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "active_dashboards": {
                                "summary": "Active dashboards for a tenant",
                                "value": {
                                    "total": 2,
                                    "dashboards": [
                                        {
                                            "dashboard_id": "udash_a1b2c3d4e5",
                                            "name": "HPCL Sales Overview",
                                            "domain_id": "market_performance_analysis",
                                            "description": "Key sales and target charts for FY2026",
                                            "status": "active",
                                            "chart_count": 4,
                                            "created_by": "user_001",
                                            "updated_at": "2026-03-25T10:05:00Z",
                                        },
                                        {
                                            "dashboard_id": "udash_f6g7h8i9j0",
                                            "name": "LPG Distribution KPIs",
                                            "domain_id": "lpg_production_distribution",
                                            "description": None,
                                            "status": "active",
                                            "chart_count": 2,
                                            "created_by": "user_002",
                                            "updated_at": "2026-03-24T08:00:00Z",
                                        },
                                    ],
                                },
                            },
                            "empty": {
                                "summary": "No dashboards yet",
                                "value": {"total": 0, "dashboards": []},
                            },
                        }
                    }
                }
            }
        }
    },
)
def list_dashboards_user_alias(
    tenant_id: str,
    domain_id: Optional[str] = None,
    status: str = "active",
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Deprecated trailing-slash alias — delegates to unified list_dashboards_endpoint."""
    result = list_dashboards_endpoint(
        tenant_id=tenant_id, domain_id=domain_id,
        dashboard_type="user", status=status, limit=limit, offset=offset,
    )
    return {"total": result.total, "dashboards": result.dashboards}


@app.get(
    "/dashboards/{dashboard_id}",
    tags=["dashboards"],
    include_in_schema=False,  # retired duplicate — primary handler is get_dashboard_endpoint above
    summary="Get a dashboard with all its charts (deprecated duplicate)",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "with_charts": {
                                "summary": "Dashboard with charts in order",
                                "value": {
                                    "dashboard_id": "udash_a1b2c3d4e5",
                                    "name": "HPCL Sales Overview",
                                    "domain_id": "market_performance_analysis",
                                    "description": "Key sales and target charts for FY2026",
                                    "status": "active",
                                    "chart_count": 2,
                                    "created_by": "user_001",
                                    "created_at": "2026-03-25T10:00:00Z",
                                    "updated_at": "2026-03-25T10:05:00Z",
                                    "charts": [
                                        {
                                            "entry_id": "dce_001",
                                            "position": 0,
                                            "chart_id": "chart_344ec6b3c9",
                                            "title": "Daily Sales by Month",
                                            "chart_type": "line",
                                            "metric": "daily_sales",
                                            "status": "ready",
                                            "added_at": "2026-03-25T10:01:00Z",
                                        },
                                        {
                                            "entry_id": "dce_002",
                                            "position": 1,
                                            "chart_id": "chart_c762fa59d7",
                                            "title": "Target Qty Tmt by Month",
                                            "chart_type": "line",
                                            "metric": "TARGET_QTY_TMT",
                                            "status": "ready",
                                            "added_at": "2026-03-25T10:02:00Z",
                                        },
                                    ],
                                },
                            },
                            "empty_dashboard": {
                                "summary": "Dashboard with no charts yet",
                                "value": {
                                    "dashboard_id": "udash_f6g7h8i9j0",
                                    "name": "New Dashboard",
                                    "domain_id": "market_performance_analysis",
                                    "description": None,
                                    "status": "active",
                                    "chart_count": 0,
                                    "charts": [],
                                    "created_at": "2026-03-25T10:00:00Z",
                                    "updated_at": "2026-03-25T10:00:00Z",
                                },
                            },
                        }
                    }
                }
            }
        }
    },
)
def get_dashboard_user_alias(dashboard_id: str, tenant_id: Optional[str] = None) -> dict:
    """Retired duplicate — primary handler is get_dashboard_endpoint."""
    return get_dashboard_endpoint(dashboard_id, tenant_id=tenant_id)


@app.patch(
    "/dashboards/{dashboard_id}",
    tags=["dashboards"],
    summary="Update dashboard metadata",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "rename": {
                            "summary": "Rename the dashboard",
                            "value": {"name": "HPCL FY2026 Executive Dashboard"},
                        },
                        "update_description": {
                            "summary": "Update description only",
                            "value": {"description": "Refreshed for Q4 FY2026 board review"},
                        },
                        "rename_and_describe": {
                            "summary": "Rename and update description",
                            "value": {
                                "name": "HPCL FY2026 Executive Dashboard",
                                "description": "Refreshed for Q4 FY2026 board review",
                            },
                        },
                    }
                }
            }
        },
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "updated": {
                                "summary": "Dashboard updated",
                                "value": {
                                    "dashboard_id": "udash_a1b2c3d4e5",
                                    "name": "HPCL FY2026 Executive Dashboard",
                                    "description": "Refreshed for Q4 FY2026 board review",
                                    "status": "active",
                                    "chart_count": 4,
                                    "updated_at": "2026-03-25T11:00:00Z",
                                },
                            }
                        }
                    }
                }
            }
        },
    },
)
def patch_dashboard(dashboard_id: str, body: UpdateDashboardRequest) -> dict:
    dash = _ds_update_dashboard(
        settings, dashboard_id,
        name=body.name,
        description=body.description,
    )
    if not dash:
        raise HTTPException(status_code=404, detail=f"Dashboard {dashboard_id!r} not found")
    return dash


@app.delete(
    "/dashboards/{dashboard_id}",
    tags=["dashboards"],
    summary="Delete or archive a dashboard",
    description="Soft-delete (archive) by default. Pass `permanent=true` to hard-delete the dashboard and all its chart entries.",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "archived": {
                                "summary": "Soft-deleted (archived)",
                                "value": {"dashboard_id": "udash_a1b2c3d4e5", "status": "archived"},
                            },
                            "permanently_deleted": {
                                "summary": "Hard-deleted (permanent=true)",
                                "value": {"dashboard_id": "udash_a1b2c3d4e5", "deleted": True},
                            },
                        }
                    }
                }
            }
        }
    },
)
def delete_dashboard_endpoint(dashboard_id: str, permanent: bool = False) -> dict:
    existing = _ds_get_dashboard(settings, dashboard_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Dashboard {dashboard_id!r} not found")
    if permanent:
        _ds_delete_dashboard(settings, dashboard_id)
        return {"dashboard_id": dashboard_id, "deleted": True}
    _ds_update_dashboard(settings, dashboard_id, status="archived")
    return {"dashboard_id": dashboard_id, "status": "archived"}


@app.post(
    "/dashboards/{dashboard_id}/charts",
    tags=["dashboards"],
    summary="Add a chart to a dashboard",
    status_code=201,
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "append": {
                            "summary": "Append chart at the end (no position)",
                            "value": {"chart_id": "chart_344ec6b3c9"},
                        },
                        "at_position": {
                            "summary": "Insert chart at position 0 (front)",
                            "value": {"chart_id": "chart_344ec6b3c9", "position": 0},
                        },
                        "with_user": {
                            "summary": "Add chart, record who added it",
                            "value": {
                                "chart_id": "chart_c762fa59d7",
                                "position": 2,
                                "added_by": "user_001",
                            },
                        },
                    }
                }
            }
        },
        "responses": {
            "201": {
                "content": {
                    "application/json": {
                        "examples": {
                            "added": {
                                "summary": "Chart added to dashboard",
                                "value": {
                                    "entry_id": "dce_001",
                                    "dashboard_id": "udash_a1b2c3d4e5",
                                    "chart_id": "chart_344ec6b3c9",
                                    "position": 0,
                                    "added_by": "user_001",
                                    "added_at": "2026-03-25T10:01:00Z",
                                },
                            }
                        }
                    }
                }
            },
            "409": {
                "content": {
                    "application/json": {
                        "examples": {
                            "duplicate": {
                                "summary": "Chart already in dashboard",
                                "value": {"detail": "Chart 'chart_344ec6b3c9' already in dashboard"},
                            }
                        }
                    }
                }
            },
        },
    },
)
def add_chart_endpoint(dashboard_id: str, body: AddChartToDashboardRequest) -> dict:
    dash = _ds_get_dashboard(settings, dashboard_id)
    if not dash:
        raise HTTPException(status_code=404, detail=f"Dashboard {dashboard_id!r} not found")
    chart_row = run_query(
        settings,
        "SELECT chart_id FROM public.quantyx_chart_requests WHERE chart_id = %s LIMIT 1",
        [body.chart_id],
    )
    if not chart_row:
        raise HTTPException(status_code=404, detail=f"Chart {body.chart_id!r} not found")
    try:
        entry = _ds_add_chart(
            settings,
            dashboard_id=dashboard_id,
            chart_id=body.chart_id,
            position=body.position,
            title_override=getattr(body, "title_override", None),
            added_by=body.added_by,
        )
    except Exception as exc:
        if "unique" in str(exc).lower() or "duplicate" in str(exc).lower():
            raise HTTPException(status_code=409, detail=f"Chart {body.chart_id!r} already in dashboard")
        raise
    return entry


@app.delete(
    "/dashboards/{dashboard_id}/charts/{chart_id}",
    tags=["dashboards"],
    summary="Remove a chart from a dashboard",
    description="Removes the chart entry from the dashboard. Does not delete the underlying chart.",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "removed": {
                                "summary": "Chart removed from dashboard",
                                "value": {
                                    "dashboard_id": "udash_a1b2c3d4e5",
                                    "chart_id": "chart_344ec6b3c9",
                                    "removed": True,
                                },
                            }
                        }
                    }
                }
            }
        }
    },
)
def remove_chart_endpoint(dashboard_id: str, chart_id: str) -> dict:
    dash = _ds_get_dashboard(settings, dashboard_id)
    if not dash:
        raise HTTPException(status_code=404, detail=f"Dashboard {dashboard_id!r} not found")
    _ds_remove_chart(settings, dashboard_id, chart_id)
    return {"dashboard_id": dashboard_id, "chart_id": chart_id, "removed": True}


@app.put(
    "/dashboards/{dashboard_id}/charts/order",
    tags=["dashboards"],
    summary="Reorder charts in a dashboard",
    description="Supply the full ordered list of chart_ids. Positions are normalized to 0, 1, 2, … in the given order.",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "reorder_three": {
                            "summary": "Reorder 3 charts",
                            "value": {
                                "chart_ids": [
                                    "chart_c762fa59d7",
                                    "chart_344ec6b3c9",
                                    "chart_ce1784971c",
                                ]
                            },
                        },
                        "move_to_front": {
                            "summary": "Promote one chart to position 0",
                            "value": {
                                "chart_ids": [
                                    "chart_ce1784971c",
                                    "chart_344ec6b3c9",
                                    "chart_c762fa59d7",
                                ]
                            },
                        },
                    }
                }
            }
        },
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "reordered": {
                                "summary": "New chart order",
                                "value": {
                                    "dashboard_id": "udash_a1b2c3d4e5",
                                    "chart_count": 3,
                                    "order": [
                                        {"position": 0, "chart_id": "chart_c762fa59d7"},
                                        {"position": 1, "chart_id": "chart_344ec6b3c9"},
                                        {"position": 2, "chart_id": "chart_ce1784971c"},
                                    ],
                                },
                            }
                        }
                    }
                }
            }
        },
    },
)
def reorder_charts_endpoint(dashboard_id: str, body: ReorderDashboardChartsRequest) -> dict:
    dash = _ds_get_dashboard(settings, dashboard_id)
    if not dash:
        raise HTTPException(status_code=404, detail=f"Dashboard {dashboard_id!r} not found")
    order = _ds_reorder_charts(settings, dashboard_id, body.chart_ids)
    return {"dashboard_id": dashboard_id, "chart_count": len(order), "order": order}


# ---------------------------------------------------------------------------
# Phase 43: Statistical Correlation, Anomaly, and Forward Pattern Agent
# ---------------------------------------------------------------------------


def _run_correlation_background(
    correlation_run_id: str,
    tenant_id: str,
    domain_id: str,
    run_id: str,
    analysis_mode: str,
    forecast_periods: int,
) -> None:
    """Background thread: run full correlation intelligence and persist results."""
    _log = logging.getLogger(__name__)
    try:
        semantic_context = semantic_interpretation_context(
            load_active_semantic_state(
                settings,
                tenant_id=tenant_id,
                domain_id=domain_id,
            )
        )
        result = run_correlation_intelligence(
            settings,
            correlation_run_id=correlation_run_id,
            tenant_id=tenant_id,
            domain_id=domain_id,
            run_id=run_id,
            forecast_periods=forecast_periods,
            analysis_mode=analysis_mode,
            semantic_context=semantic_context,
        )

        # Generate chart specs and register each one in quantyx_chart_requests
        try:
            corr_charts = generate_correlation_charts(
                correlation_run_id=correlation_run_id,
                kpi_snapshots=result.get("kpi_snapshots") or [],
                anomaly_results=result.get("anomaly_results") or [],
                correlation_pairs=result.get("correlation_pairs") or [],
                forward_projections=result.get("forward_projections") or [],
                snapshot_eligibility_summary=result.get("snapshot_eligibility_summary") or {},
                data_quality_warnings=result.get("data_quality_warnings") or [],
            )
            registered_chart_ids: list[str] = []
            for cc in corr_charts:
                spec = cc.get("spec") or {}
                chart_title = spec.get("title") or cc.get("chart_type", "")
                created = create_chart_request(
                    settings,
                    tenant_id=tenant_id,
                    domain_id=domain_id,
                    question=None,
                    query_payload=None,
                    run_id=run_id or correlation_run_id,
                    chart_source="correlation",
                    title=chart_title,
                    created_by="CorrelationAgent",
                )
                cid = created.get("chart_id")
                if cid:
                    _bg_rows = cc.get("data") or []
                    _bg_metric = cc.get("metric_name") or ""
                    _bg_chart_type = cc.get("chart_type") or "line"
                    bg_inference = build_chart_inference(
                        settings,
                        chart_type=_bg_chart_type,
                        rows=_bg_rows,
                        metric_name=_bg_metric,
                        dim_key=None,
                        chart_title=chart_title,
                    )
                    _bg_insight_text = bg_inference["insight_text"] or cc.get("description") or ""
                    _bg_narrative_text = (
                        bg_inference["narrative_text"]
                        or cc.get("description")
                        or bg_inference["insight_text"]
                        or chart_title
                    )
                    update_chart_request(
                        settings,
                        cid,
                        status="completed",
                        chart_type=_bg_chart_type,
                        chart_payload=spec,
                        chart_data=_bg_rows,
                        insight_text=_bg_insight_text,
                        narrative_text=_bg_narrative_text,
                        stats_json=bg_inference["stats_json"],
                    )
                    if not _bg_insight_text or not _bg_narrative_text:
                        _log.warning(
                            "[correlation] chart_annotations_missing | correlation_run_id=%s chart_id=%s chart_type=%s title=%s insight_present=%s narrative_present=%s",
                            correlation_run_id,
                            cid,
                            _bg_chart_type,
                            chart_title,
                            bool(_bg_insight_text),
                            bool(_bg_narrative_text),
                        )
                    registered_chart_ids.append(cid)

            # Create a correlation dashboard and link all charts
            if registered_chart_ids:
                dash = _ds_create_dashboard(
                    settings,
                    tenant_id=tenant_id,
                    domain_id=domain_id,
                    name=f"Correlation Analysis — {domain_id}",
                    description=f"Auto-generated by CorrelationAgent (run {correlation_run_id})",
                    dashboard_type="system",
                    run_id=run_id or correlation_run_id,
                )
                dash_id = dash.get("dashboard_id")
                if dash_id:
                    for pos, cid in enumerate(registered_chart_ids):
                        _ds_add_chart(
                            settings, dash_id, cid,
                            position=pos, added_by="CorrelationAgent",
                        )
        except Exception:
            _log.warning("[correlation] Chart generation/registration failed", exc_info=True)

        # Narrate threads and generate summary
        narration = {"summary_text": "", "summary_html": ""}
        try:
            narration = narrate_correlation_results(
                settings,
                kpi_snapshots=result.get("kpi_snapshots") or [],
                anomaly_results=result.get("anomaly_results") or [],
                correlation_pairs=result.get("correlation_pairs") or [],
                forward_projections=result.get("forward_projections") or [],
                investigation_threads=result.get("investigation_threads") or [],
                data_quality_warnings=result.get("data_quality_warnings") or [],
                snapshot_eligibility_summary=result.get("snapshot_eligibility_summary") or {},
                semantic_context=result.get("semantic_context") or {},
            )
        except Exception:
            _log.warning("[correlation] Narration failed", exc_info=True)

        save_correlation_run_results(
            settings,
            correlation_run_id=correlation_run_id,
            tenant_id=tenant_id,
            domain_id=domain_id,
            run_result=result,
            summary_text=narration.get("summary_text") or "",
            summary_html=narration.get("summary_html") or "",
            insights_json=narration.get("insights") or [],
        )
    except Exception:
        _log.exception("[correlation] Background run failed for %s", correlation_run_id)
        try:
            from services.ai.correlation_store import update_correlation_run
            update_correlation_run(
                settings,
                correlation_run_id,
                status="failed",
                error_message="Unhandled exception in background worker",
            )
        except Exception:
            pass


@app.post(
    "/correlation/runs",
    response_model=CorrelationRunResponse,
    status_code=202,
    tags=["correlation"],
    summary="Trigger a correlation intelligence run",
    description=(
        "Starts a Phase 43 statistical correlation run in the background. "
        "Returns immediately with status='running'. Poll `/correlation/runs/{id}` for completion."
    ),
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "scoped_by_run": {
                            "summary": "Scoped to a specific deployment run",
                            "value": {
                                "tenant_id": "VC_101",
                                "domain_id": "lpg_production_distribution",
                                "run_id": "run_1a0f427c86ec",
                                "analysis_mode": "full",
                                "forecast_periods": 12,
                            },
                        },
                        "anomaly_only": {
                            "summary": "Anomaly detection only (skip correlation + projection)",
                            "value": {
                                "tenant_id": "VC_101",
                                "domain_id": "lpg_production_distribution",
                                "analysis_mode": "anomaly_only",
                            },
                        },
                    }
                }
            }
        },
        "responses": {
            "202": {
                "content": {
                    "application/json": {
                        "examples": {
                            "accepted": {
                                "summary": "Run accepted and started",
                                "value": {
                                    "correlation_run_id": "corrrun_a1b2c3d4e5",
                                    "tenant_id": "VC_101",
                                    "domain_id": "lpg_production_distribution",
                                    "run_id": "run_1a0f427c86ec",
                                    "status": "running",
                                    "analysis_mode": "full",
                                    "forecast_periods": 12,
                                },
                            }
                        }
                    }
                }
            }
        },
    },
)
def trigger_correlation_run(body: CorrelationRunRequest) -> dict:
    correlation_run_id = f"corrrun_{uuid.uuid4().hex[:12]}"
    effective_run_id = body.run_id or ""
    row = create_correlation_run(
        settings,
        correlation_run_id=correlation_run_id,
        tenant_id=body.tenant_id,
        domain_id=body.domain_id,
        run_id=effective_run_id,
        analysis_mode=body.analysis_mode,
        forecast_periods=body.forecast_periods,
        triggered_by=body.triggered_by,
    )
    threading.Thread(
        target=_run_correlation_background,
        args=(
            correlation_run_id,
            body.tenant_id,
            body.domain_id,
            effective_run_id,
            body.analysis_mode,
            body.forecast_periods,
        ),
        daemon=True,
        name=f"corrrun-{correlation_run_id}",
    ).start()
    return row


@app.get(
    "/correlation/runs/{correlation_run_id}",
    response_model=CorrelationRunResponse,
    tags=["correlation"],
    summary="Get a correlation run",
    openapi_extra={
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "examples": {
                            "done": {
                                "summary": "Completed run",
                                "value": {
                                    "correlation_run_id": "corrrun_a1b2c3d4e5",
                                    "status": "done",
                                    "metric_count": 8,
                                    "anomaly_count": 3,
                                    "correlation_pair_count": 12,
                                    "thread_count": 2,
                                },
                            }
                        }
                    }
                }
            }
        }
    },
)
def get_correlation_run_route(correlation_run_id: str) -> dict:
    row = get_correlation_run(settings, correlation_run_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"Correlation run {correlation_run_id!r} not found")
    return row


@app.get(
    "/correlation/runs",
    response_model=CorrelationRunListResponse,
    tags=["correlation"],
    summary="List correlation runs for a tenant/domain",
)
def list_correlation_runs_route(
    tenant_id: str = Query(..., description="Tenant identifier"),
    domain_id: str = Query(..., description="Domain identifier"),
    limit: int = Query(20, ge=1, le=100),
) -> dict:
    runs = list_correlation_runs(settings, tenant_id, domain_id, limit=limit)
    return {"runs": runs, "total": len(runs)}


@app.get(
    "/correlation/runs/{correlation_run_id}/anomalies",
    response_model=CorrelationAnomalyListResponse,
    tags=["correlation"],
    summary="Get anomaly results for a correlation run",
)
def get_anomalies_route(
    correlation_run_id: str,
    metric_name: Optional[str] = Query(None, description="Filter by metric name"),
    min_score: float = Query(0.0, ge=0.0, le=1.0, description="Minimum anomaly score"),
    limit: int = Query(200, ge=1, le=1000),
) -> dict:
    _assert_run_exists(correlation_run_id)
    anomalies = get_anomaly_results(
        settings, correlation_run_id,
        metric_name=metric_name, min_score=min_score, limit=limit,
    )
    return {"correlation_run_id": correlation_run_id, "anomalies": anomalies, "total": len(anomalies)}


@app.get(
    "/correlation/runs/{correlation_run_id}/pairs",
    response_model=CorrelationPairListResponse,
    tags=["correlation"],
    summary="Get correlation pairs for a run",
)
def get_pairs_route(
    correlation_run_id: str,
    metric_name: Optional[str] = Query(None, description="Filter to pairs involving this metric"),
    min_abs_r: float = Query(0.0, ge=0.0, le=1.0, description="Minimum absolute Pearson r"),
    limit: int = Query(100, ge=1, le=500),
) -> dict:
    _assert_run_exists(correlation_run_id)
    pairs = get_correlation_pairs(
        settings, correlation_run_id,
        metric_name=metric_name, min_abs_r=min_abs_r, limit=limit,
    )
    return {"correlation_run_id": correlation_run_id, "pairs": pairs, "total": len(pairs)}


@app.get(
    "/correlation/runs/{correlation_run_id}/threads",
    response_model=CorrelationThreadListResponse,
    tags=["correlation"],
    summary="Get investigation threads for a run",
)
def get_threads_route(
    correlation_run_id: str,
    metric_name: Optional[str] = Query(None, description="Filter by trigger metric"),
    min_confidence: float = Query(0.0, ge=0.0, le=1.0),
    limit: int = Query(50, ge=1, le=200),
) -> dict:
    _assert_run_exists(correlation_run_id)
    threads = get_investigation_threads(
        settings, correlation_run_id,
        metric_name=metric_name, min_confidence=min_confidence, limit=limit,
    )
    return {"correlation_run_id": correlation_run_id, "threads": threads, "total": len(threads)}


@app.get(
    "/correlation/runs/{correlation_run_id}/projections",
    response_model=CorrelationProjectionListResponse,
    tags=["correlation"],
    summary="Get forward projections for a run",
)
def get_projections_route(
    correlation_run_id: str,
    metric_name: Optional[str] = Query(None, description="Filter by metric name"),
) -> dict:
    _assert_run_exists(correlation_run_id)
    projections = get_forward_projections(
        settings, correlation_run_id, metric_name=metric_name,
    )
    return {"correlation_run_id": correlation_run_id, "projections": projections, "total": len(projections)}


def _assert_run_exists(correlation_run_id: str) -> None:
    """Raise 404 if the correlation run does not exist."""
    row = get_correlation_run(settings, correlation_run_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"Correlation run {correlation_run_id!r} not found")
import uuid
