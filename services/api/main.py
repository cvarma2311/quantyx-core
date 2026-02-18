from __future__ import annotations

from typing import Callable, List, TypeVar

import base64
import io
import json
import logging
import os
import time
import re
import threading
import uuid
import zipfile
import xml.etree.ElementTree as ElementTree

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Response

from services.ai.catalog import load_catalog_with_registry, resolve_ref
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
)
from services.ai.onboarding.scan_store import persist_schema_scan
from services.ai.onboarding.scan_store import load_latest_scan_result, load_latest_scan_for_scope
from services.ai.resolver import resolve_question
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
from services.ai.ontology_mapper import llm_map_entities
from services.ai.onboarding.metrics_registry import persist_suggested_metrics
from services.ai.semantic_suggest import build_lineage_edges, build_schema_summary, suggest_semantic_model
from services.ai.onboarding.models_registry import (
    delete_dimension,
    delete_fact,
    list_dimensions,
    list_dimensions_all,
    list_facts,
    list_facts_all,
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
    get_extraction,
    list_context,
    link_context_files,
    mark_context_processed,
    persist_extraction,
    get_context_file_texts,
    update_context,
    update_context_file_metadata,
    update_extraction,
)
from services.ai.context_extraction import extract_context
from services.ai.context_apply import apply_extractions
from services.ai.glossary import fetch_glossary_terms
from services.ai.sql_builder import Filter, build_query
from services.ai.tenant_domain import get_tenant_domain, upsert_tenant_domain
from services.ai.tenant_scope import get_tenant_scope, upsert_tenant_scope
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
from services.api.schemas import (
    EntitiesResponse,
    EntitiesAllResponse,
    EntityOverrideRequest,
    HierarchyOverrideRequest,
    MetricsResponse,
    MetricPatchRequest,
    MetricUpsertRequest,
    MetricUpsertResponse,
    DatasetsResponse,
    DimensionsResponse,
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
)
from services.api.validators import (
    generate_source_title,
)


load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("quantyx.api")

app = FastAPI(title="quantyx-core-services API", version="0.1.0")

settings = load_settings()
catalog = load_catalog_with_registry(settings, settings.metrics_catalog_path)
LOW_CONFIDENCE_THRESHOLD = 0.7
JOB_TYPES = {"scan_connection", "map_entities", "infer_models", "metrics_suggested"}
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

    scopes = resolve_connection_scope(settings, connection_id)
    if not scopes:
        raise HTTPException(status_code=404, detail="tenant scope connection not registered")
    database_name = scopes[0].get("database_name")
    schema_name = scopes[0].get("schema_name")
    if not database_name or not schema_name:
        raise HTTPException(status_code=400, detail="tenant scope not configured")
    return (connection_id, database_name, schema_name, registry.get("tables") if registry else None)


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
        response = _run_onboard_map(request, use_llm=use_llm)
        return response.model_dump()
    if job_type == "infer_models":
        request = InferModelsRequest(**payload)
        response = infer_models(request)
        return response.model_dump()
    if job_type == "metrics_suggested":
        persist = payload.pop("persist", True)
        request = OnboardScanRequest(**payload)
        response = suggested_metrics(request, persist=persist)
        return response.model_dump()
    raise ValueError(f"Unsupported job_type: {job_type}")


def _job_worker_loop() -> None:
    poll_seconds = float(os.getenv("JOB_WORKER_POLL_SEC", "2"))
    logger.info("Job worker started (poll=%ss)", poll_seconds)
    while not _job_worker_stop.is_set():
        job = claim_next_job(settings)
        if not job:
            _job_worker_stop.wait(poll_seconds)
            continue
        job_id = job.get("job_id")
        try:
            current = get_job(settings, job_id)
            if current and current.get("status") == "canceled":
                continue
            update_job_progress(settings, job_id, progress_pct=0, progress_stage="started")
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
        except Exception as exc:  # noqa: BLE001
            logger.exception("Job failed: %s", job_id)
            update_job_status(settings, job_id, "failed", result_payload=None, error_message=str(exc))
    logger.info("Job worker stopped")


@app.on_event("startup")
def _start_job_worker() -> None:
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
    return {"status": "ok"}


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
                                "tenant_id": "tenant_a",
                                "industry": "petroleum_refinery",
                                "inputs": {
                                    "raw_text": "MFM = mass flow meter. Stock_code identifies product.",
                                    "tables_and_columns": "fact_dispatch: [bay_name, mfm_id, product_name]",
                                    "entity_types": ["organizational_unit", "mass_flow_meter", "product"],
                                    "metric_candidate": "metric_name=throughput_volume, columns=[mfm_volume, product_name]",
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
        version="draft",
        payload=payload,
        status="draft",
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
                            "value": {"tenant_id": "tenant_a", "contract_id": "contract_123"},
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
                                "tenant_id": "tenant_a",
                                "domain_id": "petroleum_refinery",
                                "inputs": {
                                    "schema_summary": "fact_dispatch: [dispatch_date, plant_id, product_id, volume_tmt]",
                                    "questions": [
                                        "Top 5 plants by dispatch volume this month",
                                        "Which products are trending down YoY?",
                                    ],
                                    "glossary": "MFM=Mass Flow Meter, bay=loading bay",
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
                                "tenant_id": "tenant_a",
                                "domain_id": "petroleum_refinery",
                                "facts": [
                                    {
                                        "table_name": "fact_dispatch_daily",
                                        "grain": "day",
                                        "time_column": "dispatch_date",
                                        "measures": ["volume_tmt"],
                                        "dimensions": ["plant_id", "product_id"],
                                        "description": "Daily dispatch fact",
                                        "status": "draft",
                                    }
                                ],
                                "dimensions": [
                                    {
                                        "name": "dim_plant",
                                        "keys": ["plant_id"],
                                        "attributes": ["plant_name", "region_name"],
                                        "description": "Plant dimension",
                                        "status": "draft",
                                    }
                                ],
                                "metrics": [
                                    {
                                        "metric_name": "dispatch_volume_tmt",
                                        "type": "sum",
                                        "sql": "{{ ref('fact_dispatch_daily') }}.volume_tmt",
                                        "grain": "day",
                                        "dimensions": ["plant_id", "product_id"],
                                        "description": "Total dispatch volume",
                                        "status": "suggested",
                                    }
                                ],
                                "lineage": {
                                    "edges": [
                                        {"from": "dim_plant", "to": "fact_dispatch_daily"},
                                        {"from": "fact_dispatch_daily", "to": "dispatch_volume_tmt"},
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
            "status": fact.get("status", "draft"),
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
            "status": dim.get("status", "draft"),
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
            status="draft",
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
                                "tenant_id": "tenant_a",
                                "domain_id": "manufacturing",
                                "job_type": "scan_connection",
                                "payload": {
                                    "tenant_id": "tenant_a",
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
                                                        {"name": "public", "tables": ["fact_production_daily"]}
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
) -> JobListResponse:
    payload = fetch_jobs(
        settings,
        tenant_id=tenant_id,
        job_type=job_type,
        status=status,
        limit=limit,
        cursor=cursor,
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
        schema_name=payload.schema,
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
        schema=row.get("schema_name"),
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
                                            "metric_name": "total_sales",
                                            "description": "Total sales amount",
                                            "type": "sum",
                                            "sql": "{{ ref('fact_sales') }}.sales_amount",
                                            "grain": "day",
                                            "dimensions": ["sales_area_name"],
                                            "tables": ["fact_sales"],
                                            "status": "certified",
                                            "owner": "analytics@company.com",
                                            "version": "v1",
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
                                            "name": "sales_area_performance",
                                            "source_model": "fact_hpcl_sales_daily",
                                            "description": "Sales performance by sales area and product",
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
                                            "name": "sales_area_name",
                                            "description": "Sales area",
                                            "data_type": "string",
                                            "sql": "{{ ref('fact_hpcl_sales_daily') }}.sales_area_name",
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
                                            "policy_id": "sbu_exclusion",
                                            "description": "Exclude SBU values not relevant for this tenant",
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
                                            "metric_name": "total_sales_volume_tmt",
                                            "dataset": "fact_hpcl_sales_daily",
                                            "dbt_model": "fact_hpcl_sales_daily",
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
                                        {"id": "fact_production_daily", "type": "fact"},
                                        {"id": "total_output_tmt", "type": "metric"},
                                    ],
                                    "edges": [
                                        {"from": "dim_plant", "to": "fact_production_daily", "edge_type": "dimension_to_fact"},
                                        {"from": "fact_production_daily", "to": "total_output_tmt", "edge_type": "fact_to_metric"},
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
                    "status": node_payload.get("status", "draft"),
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
                    "status": node_payload.get("status", "draft"),
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
        status=payload.status or "draft",
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
                    "status": node_payload.get("status", "draft"),
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
                    "status": node_payload.get("status", "draft"),
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
        status=payload.status or "draft",
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
                                    "tenant_id": "tenant_a",
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
                                "tenant_id": "tenant_a",
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
            "password": payload.password,
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
                                            "tables": ["fact_sales", "dim_customer"],
                                            "status": "draft",
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
                                            "headline": "Sales volume decreased 4.2% vs last month",
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
                                        "headline": "Sales volume decreased 4.2% vs last month",
                                        "severity": "medium",
                                        "confidence": 0.8,
                                        "entity_scope": {"sales_area_name": "Tenali"},
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
                                        "headline": "total_sales_volume_tmt anomaly detected at 2024-06-01",
                                    },
                                    "drivers": [
                                        {
                                            "period": "2024-06-01",
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
                                "metric_name": "total_sales_volume_tmt",
                                "grain": "month",
                                "filters": [{"field": "product_name", "operator": "=", "value": "MS"}],
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
                                "tenant_id": "tenant_a",
                                "headline": "Investigate sales drop in Tenali",
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
                                        "domain_id": "energy_distribution",
                                        "name": "Distribution Disruption",
                                        "status": "draft",
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
                                "tenant_id": "tenant_a",
                                "name": "Distribution Disruption",
                                "description": "Simulate loss of supply in Zone A",
                                "status": "draft",
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
                                "value": {"scenario_id": "scenario_001", "status": "draft"},
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
    return {"scenario_id": scenario_id, "status": payload.status or "draft"}


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
                                "metric_name": "total_sales_volume_tmt",
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
                                    "metric_name": "total_sales_volume_tmt",
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
                                    "dimension": "sales_area_name",
                                    "values": [{"value": "Tenali"}, {"value": "Vijayawada"}],
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
                                "tenant_id": "tenant_a",
                                "metric_name": "total_sales_volume_tmt",
                                "description": "Total sales volume in TMT",
                                "type": "sum",
                                "sql": "{{ ref('fact_hpcl_sales_daily') }}.sales_tmt",
                                "grain": "day",
                                "dimensions": ["sales_area_name", "fiscal_year"],
                                "unit": "tmt",
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
                            "value": {"sql": "{{ ref('fact_hpcl_sales_daily') }}.sales_tmt"},
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
                                        {"domain_id": "energy_distribution", "display_name": "energy_distribution"},
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
                                "tenant_id": "tenant_a",
                                "source_type": "business_context",
                                "source_title": "Operations glossary and hierarchy notes",
                                "raw_text": "SBU = Strategic Business Unit. Sales org is Zone > Region > Sales Area...",
                                "file_ids": ["file_123", "file_456"],
                                "metadata": {
                                    "columns": ["plant_name", "region_name"],
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
    return ContextIngestResponse(context_id=context_id, status="submitted")


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
                                "tenant_id": "tenant_a",
                                "source_type": "business_context",
                                "source_title": "Operations glossary",
                                "metadata": "{\"columns\":[\"plant_name\",\"region_name\"]}",
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
                                "tenant_id": "tenant_a",
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
                                            {"abbr": "SBU", "definition": "Strategic Business Unit"}
                                        ],
                                        "synonyms": [{"term": "sales area", "synonyms": ["territory"]}],
                                        "hierarchies": [
                                            {"name": "sales_org", "levels": ["zone", "region", "sales_area"]}
                                        ],
                                        "metric_candidates": [
                                            {"metric_name": "output_tmt", "table": "fact_production_daily"}
                                        ],
                                        "question_intents": [
                                            {
                                                "question": "Which plants are underperforming?",
                                                "metrics": ["output_tmt"],
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
) -> ContextExtractionResponse:
    domain_id = _resolve_domain_id(tenant_id, None)
    extraction_row = get_extraction(settings, extraction_id)
    if not extraction_row:
        raise HTTPException(status_code=404, detail="Extraction not found")
    if extraction_row["tenant_id"] != tenant_id or extraction_row["domain_id"] != domain_id:
        raise HTTPException(status_code=400, detail="Extraction tenant/domain mismatch")
    created_at = extraction_row.get("created_at")
    return ContextExtractionResponse(
        extraction_id=extraction_row["extraction_id"],
        context_id=extraction_row["context_id"],
        extraction_type=extraction_row.get("extraction_type"),
        payload=extraction_row.get("payload") or {},
        status=extraction_row.get("status"),
        notes=extraction_row.get("notes"),
        created_at=created_at.isoformat() if created_at else None,
    )


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
                                "tenant_id": "tenant_a",
                                "extraction_id": "ext_123",
                                "apply": {
                                    "entities": True,
                                    "hierarchies": True,
                                    "glossary": True,
                                    "metrics": True,
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
        source_context_id=extraction_row.get("context_id"),
        connection_id=connection_id,
        database_name=database_name,
        schema_name=schema_name,
    )
    logger.info(
        "context.apply: complete | %s",
        {"extraction_id": payload.extraction_id, "updated": updated},
    )
    return ContextApplyResponse(status="applied", updated=updated)


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
                                            "join_key": "sales_area_name",
                                        }
                                    ],
                                    "hierarchies": [
                                        {
                                            "name": "sales_org",
                                            "levels": ["sbu", "zone", "region", "sales_area"],
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
    entity_overrides, hierarchy_overrides = load_overrides(
        settings,
        tenant_id,
        domain_id,
        connection_id=connection_id,
        database_name=database,
        schema_name=schema,
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
) -> dict:
    domain_id = _resolve_domain_id(tenant_id, None)
    connection_id, database, schema, _ = _resolve_scope_values(
        tenant_id,
        domain_id,
    )
    _, hierarchy_overrides = load_overrides(
        settings,
        tenant_id,
        domain_id,
        connection_id=connection_id,
        database_name=database,
        schema_name=schema,
    )
    hierarchies_payload = [
        {
            "name": item.get("hierarchy_name"),
            "levels": item.get("levels", []),
            "description": item.get("description"),
            "lifecycle_status": item.get("lifecycle_status"),
            "source_type": item.get("source_type"),
            "source_run_id": item.get("source_run_id"),
            "artifact_key": item.get("artifact_key"),
            "version_no": item.get("version_no"),
            "is_current": item.get("is_current"),
        }
        for item in sorted(hierarchy_overrides, key=lambda item: item.get("hierarchy_name", ""))
    ]
    return {"hierarchies": hierarchies_payload}


@app.patch(
    "/entities/{entity_id}",
    tags=["admin"],
    summary="Override an entity",
    description="Upsert a tenant-specific entity override (description/join_key/examples).",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "update_join_key": {
                            "summary": "Update join key",
                            "value": {
                                "description": "Organizational hierarchy for sales operations",
                                "join_key": "sales_area_name",
                                "examples": ["zone", "region", "sales_area"],
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
    connection_id: str,
    database: str,
    schema: str,
    payload: EntityOverrideRequest,
) -> dict:
    domain_id = _resolve_domain_id(tenant_id, None)
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
        },
    )
    return {"ok": True}


@app.patch(
    "/hierarchies/{hierarchy_name}",
    tags=["admin"],
    summary="Override a hierarchy",
    description="Upsert a tenant-specific hierarchy override (levels/description).",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "override_levels": {
                            "summary": "Override hierarchy levels",
                            "value": {
                                "levels": ["sbu", "zone", "region", "sales_area"],
                                "description": "Sales organization rollup",
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
    connection_id: str,
    database: str,
    schema: str,
    payload: HierarchyOverrideRequest,
) -> dict:
    domain_id = _resolve_domain_id(tenant_id, None)
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
        },
    )
    return {"ok": True}


@app.post(
    "/facts",
    response_model=dict,
    tags=["onboard"],
    summary="Create or upsert a fact",
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
            "lifecycle_status": payload.status or "draft",
            "source_type": "user",
        },
    )
    return {"fact_id": fact_id, "status": payload.status or "draft"}


@app.get(
    "/facts",
    response_model=FactsResponse,
    tags=["explore"],
    summary="List facts (connection-scoped)",
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
)
def remove_fact(fact_id: str) -> dict:
    delete_fact(settings, fact_id)
    return {"ok": True}


@app.post(
    "/dimensions",
    response_model=dict,
    tags=["onboard"],
    summary="Create or upsert a dimension",
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
            "lifecycle_status": payload.status or "draft",
            "source_type": "user",
        },
    )
    return {"dimension_id": dimension_id, "status": payload.status or "draft"}


@app.get(
    "/dimensions",
    response_model=DimensionsResponse,
    tags=["explore"],
    summary="List dimensions (connection-scoped)",
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
        }
        status = review_map.get(("hierarchies", hierarchy.get("hierarchy_name")))
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
                                            "name": "fact_hpcl_sales_daily",
                                            "schema": "public",
                                            "columns": ["sales_date", "sales_tmt"],
                                        }
                                    ],
                                    "limit": 200,
                                    "cursor": None,
                                    "next_cursor": "ZmFjdF9ocGNsX3NhbGVzX21vbnRobHlfdGFyZ2V0cw==",
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
                            "value": {"tenant_id": "tenant_a"},
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
                                            "table": "fact_hpcl_sales_daily",
                                            "columns": [
                                                {"name": "sales_tmt", "data_type": "numeric", "null_frac": 0.0}
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
                                "tenant_id": "tenant_a",
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
                                                        "tables": ["fact_production_daily"],
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
                    "application/json": {"examples": {"queued": {"value": {"job_id": "job_123", "status": "queued"}}}}
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
                    password=connection.password,
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
                            "password": connection.password,
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
                                "tenant_id": "tenant_a",
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
                                                        "tables": ["fact_production_daily"],
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
                                                                    "table": "fact_production_daily",
                                                                    "columns": [
                                                                        {
                                                                            "name": "production_date",
                                                                            "data_type": "date",
                                                                            "null_frac": 0.0,
                                                                            "distinct": 365,
                                                                            "profile": {"min": "2024-01-01", "max": "2024-12-31"},
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
                                "tenant_id": "tenant_a",
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
                                "tenant_id": "tenant_a",
                            },
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
            llm_candidates = llm_map_entities(settings, tables, ontology, glossary=glossary)
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
    return OnboardMapResponse(
        mapping_id=mapping_id,
        tenant_id=tenant_id,
        candidates=high_confidence_candidates,
        low_confidence_candidates=low_confidence_candidates,
        low_confidence_threshold=LOW_CONFIDENCE_THRESHOLD,
    )


@app.get(
    "/onboard/map/history",
    tags=["onboard"],
    summary="List mapping history",
    description="Return recent entity mapping runs for the given scope.",
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
    "/onboard/map/{mapping_id}",
    response_model=OnboardMapRunResponse,
    tags=["onboard"],
    summary="Get mapping run",
    description="Return a single mapping run by mapping_id for the active tenant scope.",
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
        status=row.get("status") or "draft",
        created_at=row.get("created_at").isoformat() if row.get("created_at") else None,
        updated_at=row.get("updated_at").isoformat() if row.get("updated_at") else None,
    )


@app.post(
    "/onboard/map/{mapping_id}/apply",
    response_model=OnboardMapApplyResponse,
    tags=["onboard"],
    summary="Apply mapping run to entity overrides",
    description="Promote mapping candidates from a mapping run into canonical entity overrides.",
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
                                "tenant_id": "tenant_a",
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
                                "tenant_id": "tenant_a",
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
                                            "name": "fact_production_daily",
                                            "grain": "day",
                                            "time_column": "production_date",
                                            "measures": ["output_tmt", "downtime_hours"],
                                            "dimensions": ["plant_name", "product_name", "fiscal_year"],
                                            "confidence": 0.85,
                                        }
                                    ],
                                    "dimensions": [
                                        {
                                            "name": "dim_plant",
                                            "keys": ["plant_id"],
                                            "attributes": ["plant_name", "region_name"],
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
                        "status": fact.get("status", "draft"),
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
                        "status": dim.get("status", "draft"),
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
                "lifecycle_status": fact.get("status", "draft"),
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
                "lifecycle_status": dim.get("status", "draft"),
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
                                "tenant_id": "tenant_a",
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
                                "tenant_id": "tenant_a",
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
                                            "table": "fact_hpcl_sales_daily",
                                            "column": "sales_tmt",
                                            "measure_type": "volume",
                                            "unit": "tmt",
                                            "confidence": 0.9,
                                            "additive": True,
                                        }
                                    ],
                                    "low_confidence_measures": [
                                        {
                                            "table": "fact_hpcl_sales_daily",
                                            "column": "avg_rate",
                                            "measure_type": "number",
                                            "unit": None,
                                            "confidence": 0.6,
                                            "additive": False,
                                        }
                                    ],
                                    "low_confidence_threshold": 0.7,
                                    "time_columns": [
                                        {"table": "fact_hpcl_sales_daily", "column": "sales_date"}
                                    ],
                                    "entity_candidates": [
                                        {
                                            "table": "fact_hpcl_sales_daily",
                                            "column": "sales_area_name",
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
def suggested_metrics(request: OnboardScanRequest, persist: bool = True) -> SuggestedMetricsResponse:
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
    measures = detect_measures(tables)
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
    ontology = load_pack(f"packs/{domain_id}").get("ontology", {})
    entity_candidates = map_entities(tables, ontology)
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
    return SuggestedMetricsResponse(
        measures=high_confidence_measures,
        low_confidence_measures=low_confidence_measures,
        low_confidence_threshold=LOW_CONFIDENCE_THRESHOLD,
        time_columns=time_columns,
        entity_candidates=entity_candidates,
    )


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
                                        "metric_name": "total_sales_volume_tmt",
                                        "type": "sum",
                                        "sql": "{{ ref('fact_hpcl_sales_daily') }}.sales_tmt",
                                        "grain": "day",
                                        "dimensions": ["sales_area_name", "fiscal_year"],
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


def _resolve_metrics(request: QueryRequest) -> tuple[list[str], list[str], list[dict]]:
    if request.metrics:
        logger.info("request.metrics provided: %s", request.metrics)
        return request.metrics, request.dimensions, [flt.model_dump() for flt in request.filters]

    if request.metric:
        logger.info("request.metric provided: %s", request.metric)
        return [request.metric], request.dimensions, [flt.model_dump() for flt in request.filters]

    if request.question:
        logger.info("resolving question: %s", request.question)
        glossary = None
        if request.tenant_id:
            domain_id = _resolve_domain_id(request.tenant_id, request.domain_id)
            glossary = fetch_glossary_terms(settings, request.tenant_id, domain_id)
        resolved = resolve_question(request.question, catalog, settings, glossary=glossary)
        logger.info("resolver output: %s", resolved)
        metrics = resolved.get("metrics", [])
        dimensions = resolved.get("dimensions", [])
        filters = resolved.get("filters", [])
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
        for metric in catalog.metrics.values():
            if all(dim in metric.dimensions for dim in dimensions) and all(
                field in metric.dimensions for field in filter_fields
            ):
                allowed_metrics.append(metric.name)

        if metrics and any(metric not in allowed_metrics for metric in metrics):
            if not allowed_metrics:
                return ([], dimensions, filters)
            logger.info("re-resolving with allowed metrics: %s", allowed_metrics)
            resolved = resolve_question(
                request.question,
                catalog,
                settings,
                allowed_metrics=allowed_metrics,
                glossary=glossary,
            )
            logger.info("resolver output (restricted): %s", resolved)
            return (
                resolved.get("metrics", []),
                resolved.get("dimensions", []),
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
        if isinstance(value, str) and value.strip().lower() == "this month":
            month_name, fiscal_year = _resolve_this_month(settings)
            if month_name:
                normalized.append({"field": "month_name", "operator": "=", "value": month_name})
            if fiscal_year:
                normalized.append({"field": "fiscal_year", "operator": "=", "value": fiscal_year})
            continue
        normalized.append(flt)
    return normalized


def _filter_dimension_filters(filters: list[dict], dimension_names: set[str]) -> list[dict]:
    filtered = []
    for flt in filters:
        if flt.get("field") in dimension_names:
            filtered.append(flt)
        else:
            logger.info("dropping non-dimension filter: %s", flt)
    return filtered


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
                            "summary": "Top 5 sales areas",
                            "value": {
                                "question": "Top 5 sales areas by sales volume for MS in Q2 FY 2024-2025.",
                                "tenant_id": "tenant_a",
                                "limit": 100,
                                "explain": True,
                            },
                        },
                        "hpcl_vs_bpcl": {
                            "summary": "HPCL vs BPCL market share",
                            "value": {
                                "question": "HPCL vs BPCL market share for MS in UTTAR PRADESH during FY 2024-2025.",
                                "tenant_id": "tenant_a",
                                "limit": 100,
                                "explain": True,
                            },
                        },
                        "run_rate_risk": {
                            "summary": "Below required run rate",
                            "value": {
                                "question": "Which sales areas are below required run rate this month?",
                                "tenant_id": "tenant_a",
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
                                    "metrics": ["total_sales_volume_tmt"],
                                    "dimensions": ["sales_area_name"],
                                    "sql": "SELECT sales_area_name, SUM(sales_tmt) AS total_sales_volume_tmt FROM ...",
                                    "rows": [
                                        {"sales_area_name": "Tenali", "total_sales_volume_tmt": 123.4}
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
    sql_text = None
    row_count = None
    glossary = None
    contract = None
    if request.tenant_id:
        domain_id = _resolve_domain_id(request.tenant_id, request.domain_id)
        connection_id, database_name, schema_name, tables = _resolve_scope_values(
            request.tenant_id,
            domain_id,
        )
        glossary = fetch_glossary_terms(settings, request.tenant_id, domain_id)
        contract = get_active_semantic_contract(settings, request.tenant_id, domain_id)
    metric_names, dimensions, filters = _resolve_metrics(request)
    if not metric_names and request.question:
        question = request.question.lower()
        if "required run rate" in question:
            metric_names = ["current_run_rate_mmt", "required_run_rate_mmt"]
            dimensions = ["sales_area_name", "month_name", "fiscal_year"]
    logger.info("metrics: %s", metric_names)
    filters = _coerce_sbu_filters(filters)
    filters = _coerce_product_filters(filters)
    dimensions = _coerce_sbu_dimensions(dimensions, filters)
    filters = _normalize_filters(filters, settings)
    filters = _normalize_sales_quarter_filters(filters, metric_names)
    filters = _filter_dimension_filters(filters, set(catalog.dimensions.keys()))
    logger.info("dimensions: %s", dimensions)
    logger.info("filters: %s", filters)

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
        raise HTTPException(status_code=400, detail="No metrics resolved")

    metrics = []
    for metric_name in metric_names:
        if metric_name not in catalog.metrics:
            raise HTTPException(status_code=400, detail=f"Unknown metric: {metric_name}")
        metrics.append(catalog.metrics[metric_name])

    filter_fields = []
    for flt in filters:
        payload = flt if isinstance(flt, dict) else flt.model_dump()
        filter_fields.append(payload["field"])

    if dimensions or filter_fields:
        filtered_metrics = []
        for metric in metrics:
            if all(dim in metric.dimensions for dim in dimensions) and all(
                field in metric.dimensions for field in filter_fields
            ):
                filtered_metrics.append(metric)
        metrics = filtered_metrics

    if request.question and metric_names and len(metrics) != len(metric_names):
        allowed_metrics = [metric.name for metric in metrics]
        if allowed_metrics:
            logger.info("re-resolving after coercion with allowed metrics: %s", allowed_metrics)
            resolved = resolve_question(
                request.question,
                catalog,
                settings,
                allowed_metrics=allowed_metrics,
                glossary=glossary,
            )
            metric_names = resolved.get("metrics", [])
            dimensions = _coerce_sbu_dimensions(resolved.get("dimensions", []), resolved.get("filters", []))
            filters = _coerce_sbu_filters(resolved.get("filters", []))
            logger.info("metrics (post-coercion): %s", metric_names)
            logger.info("dimensions (post-coercion): %s", dimensions)
            logger.info("filters (post-coercion): %s", filters)

            metrics = []
            for metric_name in metric_names:
                if metric_name not in catalog.metrics:
                    raise HTTPException(status_code=400, detail=f"Unknown metric: {metric_name}")
                metrics.append(catalog.metrics[metric_name])

            filter_fields = [flt["field"] for flt in filters]
            if dimensions or filter_fields:
                filtered_metrics = []
                for metric in metrics:
                    if all(dim in metric.dimensions for dim in dimensions) and all(
                        field in metric.dimensions for field in filter_fields
                    ):
                        filtered_metrics.append(metric)
                metrics = filtered_metrics

    if not metrics:
        raise HTTPException(
            status_code=400,
            detail="No metrics support the requested dimensions/filters",
        )

    dim_objects = []
    for dim_name in dimensions:
        if dim_name not in catalog.dimensions:
            raise HTTPException(status_code=400, detail=f"Unknown dimension: {dim_name}")
        dim_objects.append(catalog.dimensions[dim_name])

    built_filters: List[Filter] = []
    for flt in filters:
        payload = flt if isinstance(flt, dict) else flt.model_dump()
        if payload["field"] not in catalog.dimensions:
            continue
        normalized_value = _normalize_filter_value(payload["field"], payload["value"])
        built_filters.append(
            Filter(field=payload["field"], operator=payload["operator"], value=normalized_value)
        )

    try:
        built = build_query(
            metrics=metrics,
            dimensions=dim_objects,
            filter_dimensions=catalog.dimensions,
            filters=built_filters,
            schema=settings.db_schema,
            limit=request.limit,
        )
        sql_text = built.sql
        logger.info("sql: %s", built.sql)
        logger.info("params: %s", built.params)
        rows = run_query(settings, built.sql, built.params)
        row_count = len(rows)
        logger.info("rows: %s", row_count)
    except Exception as exc:
        error_message = str(exc)
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
        if "industry_sales_by_company_tmt" in catalog.metrics:
            by_company_metric = catalog.metrics["industry_sales_by_company_tmt"]
            by_company_dimensions = list(dim_objects)
            if "company_name" not in [dim.name for dim in by_company_dimensions]:
                by_company_dimensions.append(catalog.dimensions["company_name"])
            by_company_built = build_query(
                metrics=[by_company_metric],
                dimensions=by_company_dimensions,
                filter_dimensions=catalog.dimensions,
                filters=built_filters,
                schema=settings.db_schema,
                limit=request.limit,
            )
            by_company_sql = by_company_built.sql
            logger.info("by_company_sql: %s", by_company_sql)
            logger.info("by_company_params: %s", by_company_built.params)
            by_company_rows = run_query(settings, by_company_built.sql, by_company_built.params)
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

    return QueryResult(
        metrics=[metric.name for metric in metrics],
        dimensions=[dim.name for dim in dim_objects if dim.name != "company_name"],
        sql=built.sql if request.explain else None,
        rows=rows,
        by_company_sql=by_company_sql,
        by_company_rows=by_company_rows,
        semantic_validation=semantic_validation,
        lineage=lineage,
    )
