from __future__ import annotations

from typing import Callable, List, TypeVar

import base64
import io
import json
import logging
import time
import re
import uuid
import zipfile
import xml.etree.ElementTree as ElementTree

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, UploadFile, File, Form

from services.ai.catalog import load_catalog_with_registry, resolve_ref
from services.ai.config import load_settings
from services.ai.db import run_query
from services.ai.metrics_registry import upsert_metric, update_metric
from services.ai.audit import log_query_audit
from services.ai.connection_registry import (
    register_connection,
    register_connection_scopes,
    resolve_connection_scope,
)
from services.ai.onboarding.scan_store import persist_schema_scan
from services.ai.onboarding.scan_store import load_latest_scan_result
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
from services.api.entities import list_entities, list_hierarchies
from services.api.overrides import load_overrides, merge_entities, merge_hierarchies
from services.api.overrides_endpoints import upsert_entity_override, upsert_hierarchy_override
from services.ai.onboarding.schema_scan import scan_schema
from services.ai.onboarding.connection_scan import scan_connection
from services.ai.onboarding.measure_detection import detect_measures, detect_time_columns
from services.ai.onboarding.entity_mapping import map_entities
from services.ai.ontology_mapper import llm_map_entities
from services.ai.onboarding.metrics_registry import persist_suggested_metrics
from services.ai.onboarding.model_inference_llm import llm_infer_models
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
from services.api.schemas import (
    EntitiesResponse,
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
)
from services.api.validators import (
    extract_scope_from_metadata,
    generate_source_title,
    scopes_match,
    validate_scope_fields,
)


load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("quantyx.api")

app = FastAPI(title="quantyx-core-services API", version="0.1.0")

settings = load_settings()
catalog = load_catalog_with_registry(settings, settings.metrics_catalog_path)
LOW_CONFIDENCE_THRESHOLD = 0.7
ALLOWED_METRIC_TYPES = {"sum", "average", "avg", "ratio", "derived"}
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


def _require_scope(scope: dict | None, endpoint: str) -> None:
    missing = validate_scope_fields(scope)
    if missing:
        detail = (
            f"{endpoint} requires connection scope fields: "
            f"{', '.join(missing)}. Include connection_id, database, schema, tables."
        )
        raise HTTPException(status_code=400, detail=detail)


def _request_scope(
    connection_id: str | None,
    database: str | None,
    schema: str | None,
    tables: list[str] | None,
) -> dict:
    return {
        "connection_id": connection_id,
        "database": database,
        "schema": schema,
        "tables": tables,
    }


def _metadata_has_scope(metadata: dict | None) -> bool:
    if not metadata:
        return False
    return any(
        key in metadata
        for key in ("connection_id", "database", "database_name", "schema", "schema_name", "tables")
    )


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
    "/metrics",
    response_model=MetricsResponse,
    tags=["explore"],
    summary="List metrics",
    description="Return metric catalog entries from the contracts layer.",
    openapi_extra={
        "parameters": [
            {
                "name": "limit",
                "in": "query",
                "required": False,
                "schema": {"type": "integer"},
                "examples": {"limit": {"value": 200}},
            },
            {
                "name": "cursor",
                "in": "query",
                "required": False,
                "schema": {"type": "string"},
                "examples": {"cursor": {"value": "dG90YWxfc2FsZXNfdm9sdW1lX3RtdA=="}},
            },
        ],
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
                                            "name": "total_sales_volume_tmt",
                                            "description": "Total HPCL sales volume in TMT",
                                            "type": "sum",
                                            "grain": "day",
                                            "dimensions": [
                                                "sales_area_name",
                                                "product_name",
                                                "fiscal_year",
                                            ],
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
def metrics(limit: int = 200, cursor: str | None = None) -> MetricsResponse:
    payload = [
        {
            "name": metric.name,
            "description": metric.description,
            "type": metric.metric_type,
            "grain": metric.grain,
            "dimensions": metric.dimensions,
            "status": metric.status,
            "owner": metric.owner,
            "version": metric.version,
        }
        for metric in catalog.metrics.values()
    ]
    page, next_cursor = _paginate_list(payload, cursor, limit, key_fn=lambda item: item["name"])
    return MetricsResponse(metrics=page, limit=limit, cursor=cursor, next_cursor=next_cursor)


@app.get(
    "/datasets",
    response_model=DatasetsResponse,
    tags=["explore"],
    summary="List datasets",
    description="Return datasets defined in the selected domain pack, scoped by optional database/schema filters.",
    openapi_extra={
        "parameters": [
            {
                "name": "domain_id",
                "in": "query",
                "required": True,
                "schema": {"type": "string"},
                "examples": {"energy": {"value": "energy_distribution"}},
            },
            {
                "name": "connection_id",
                "in": "query",
                "required": False,
                "schema": {"type": "string"},
                "examples": {"connection_id": {"value": "conn_prod"}},
            },
            {
                "name": "database",
                "in": "query",
                "required": False,
                "schema": {"type": "string"},
                "examples": {"database": {"value": "prod_warehouse"}},
            },
            {
                "name": "schema",
                "in": "query",
                "required": False,
                "schema": {"type": "string"},
                "examples": {"schema": {"value": "public"}},
            },
            {
                "name": "limit",
                "in": "query",
                "required": False,
                "schema": {"type": "integer"},
                "examples": {"limit": {"value": 200}},
            },
            {
                "name": "cursor",
                "in": "query",
                "required": False,
                "schema": {"type": "string"},
                "examples": {"cursor": {"value": "c2FsZXNfYXJlYV9wZXJmb3JtYW5jZQ=="}},
            },
        ],
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
    domain_id: str,
    database: str | None = None,
    schema: str | None = None,
    limit: int = 200,
    cursor: str | None = None,
    connection_id: str | None = None,
) -> DatasetsResponse:
    if connection_id:
        scopes = resolve_connection_scope(settings, connection_id)
        if not scopes:
            raise HTTPException(status_code=404, detail="Unknown connection_id")
        if not database and not schema and scopes:
            database = scopes[0].get("database_name")
            schema = scopes[0].get("schema_name")
    pack = load_pack(f"packs/{domain_id}")
    datasets_list = pack.get("datasets", {}).get("datasets", []) or []
    datasets_list = _filter_by_model_attr(datasets_list, schema, key="source_model", attr="schema")
    datasets_list = _filter_by_model_attr(datasets_list, database, key="source_model", attr="database")
    page, next_cursor = _paginate_list(datasets_list, cursor, limit, key_fn=lambda item: item["name"])
    return DatasetsResponse(datasets=page, limit=limit, cursor=cursor, next_cursor=next_cursor)


@app.get(
    "/dimensions",
    response_model=DimensionsResponse,
    tags=["explore"],
    summary="List dimensions",
    description="Return dimensions from the metric catalog, scoped by optional database/schema filters.",
    openapi_extra={
        "parameters": [
            {
                "name": "connection_id",
                "in": "query",
                "required": False,
                "schema": {"type": "string"},
                "examples": {"connection_id": {"value": "conn_prod"}},
            },
            {
                "name": "database",
                "in": "query",
                "required": False,
                "schema": {"type": "string"},
                "examples": {"database": {"value": "prod_warehouse"}},
            },
            {
                "name": "schema",
                "in": "query",
                "required": False,
                "schema": {"type": "string"},
                "examples": {"schema": {"value": "public"}},
            },
        ],
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
def dimensions(database: str | None = None, schema: str | None = None, connection_id: str | None = None) -> DimensionsResponse:
    if connection_id:
        scopes = resolve_connection_scope(settings, connection_id)
        if not scopes:
            raise HTTPException(status_code=404, detail="Unknown connection_id")
        if not database and not schema and scopes:
            database = scopes[0].get("database_name")
            schema = scopes[0].get("schema_name")
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
        "parameters": [
            {
                "name": "domain_id",
                "in": "query",
                "required": True,
                "schema": {"type": "string"},
                "examples": {"energy": {"value": "energy_distribution"}},
            }
        ],
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
def policies(domain_id: str) -> PoliciesResponse:
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
        "parameters": [
            {
                "name": "metric_name",
                "in": "query",
                "required": False,
                "schema": {"type": "string"},
                "examples": {"metric_name": {"value": "total_sales_volume_tmt"}},
            }
        ],
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
    tenant_id = payload.tenant_id or f"tenant_{uuid.uuid4().hex[:6]}"
    dbt_project_path = payload.dbt_project_path or resolve_dbt_project_dir(tenant_id)
    upsert_tenant_project_dir(settings, tenant_id, payload.domain_id, dbt_project_path)
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
        domain_id=payload.domain_id,
        connection_id=payload.connection_id,
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
        "parameters": [
            {
                "name": "tenant_id",
                "in": "query",
                "required": True,
                "schema": {"type": "string"},
                "examples": {"tenant_a": {"value": "tenant_a"}},
            },
            {
                "name": "domain_id",
                "in": "query",
                "required": True,
                "schema": {"type": "string"},
                "examples": {"manufacturing": {"value": "manufacturing"}},
            },
        ]
        ,
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
                                    "domain_id": "manufacturing",
                                    "connection_id": "conn_prod",
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
    domain_id: str,
) -> DbtManifestLatestResponse:
    row = load_latest_manifest_row(settings, domain_id=domain_id, tenant_id=tenant_id)
    if not row:
        raise HTTPException(status_code=404, detail="Manifest not found")
    return DbtManifestLatestResponse(
        manifest_id=row["manifest_id"],
        tenant_id=row["tenant_id"],
        domain_id=row["domain_id"],
        connection_id=row.get("connection_id"),
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
    description="Store dbt config for a tenant/domain/connection (admin use only).",
)
def upsert_dbt_config_endpoint(payload: DbtConfigUpsertRequest) -> DbtConfigResponse:
    dbt_project_path = payload.dbt_project_path or resolve_dbt_project_dir(payload.tenant_id)
    profile_name = normalize_profile_name(payload.tenant_id)
    target_name = payload.target_name or settings.dbt_target_name
    profiles_dir = payload.profiles_dir or settings.dbt_profiles_dir
    config_id = upsert_dbt_config(
        settings,
        tenant_id=payload.tenant_id,
        domain_id=payload.domain_id,
        connection_id=payload.connection_id,
        dbt_project_path=dbt_project_path,
        profile_name=profile_name,
        target_name=target_name,
        profiles_dir=profiles_dir,
    )
    return DbtConfigResponse(
        config_id=config_id,
        tenant_id=payload.tenant_id,
        domain_id=payload.domain_id,
        connection_id=payload.connection_id,
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
    description="Return the latest dbt config for a tenant/domain/connection (admin use only).",
)
def get_latest_dbt_config_endpoint(
    tenant_id: str,
    domain_id: str,
    connection_id: str | None = None,
) -> DbtConfigResponse:
    config = get_latest_dbt_config(settings, tenant_id, domain_id, connection_id)
    if not config:
        raise HTTPException(status_code=404, detail="dbt config not found")
    return DbtConfigResponse(
        config_id=config.get("config_id"),
        tenant_id=config["tenant_id"],
        domain_id=config["domain_id"],
        connection_id=config.get("connection_id"),
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
        "parameters": [
            {
                "name": "generate_dbt",
                "in": "query",
                "required": False,
                "schema": {"type": "boolean"},
                "examples": {"generate_dbt": {"value": True}},
            }
        ],
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "generate_scaffold": {
                            "summary": "Generate scaffold",
                            "value": {
                                "tenant_id": "tenant_a",
                                "domain_id": "manufacturing",
                                "connection_id": "conn_prod",
                                "database": "prod_warehouse",
                                "schema": "public",
                                "tables": ["fact_sales", "dim_customer"],
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
    scan_result = load_latest_scan_result(settings, payload.tenant_id, payload.domain_id)
    if not scan_result:
        raise HTTPException(status_code=404, detail="No scan results found for tenant/domain")
    tables = _extract_tables_from_scan(
        scan_result,
        connection_id=payload.connection_id,
        database=payload.database,
        schema=payload.schema,
        tables=payload.tables,
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
        database=payload.database,
        schema=payload.schema,
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
        domain_id=payload.domain_id,
        connection_id=payload.connection_id,
        database=payload.database,
        schema=payload.schema,
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
                                            "connection_id": "conn_prod",
                                            "database_name": "prod_warehouse",
                                            "schema_name": "public",
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
    domain_id: str,
    connection_id: str | None = None,
) -> DbtScaffoldListResponse:
    scaffolds = list_scaffolds(settings, tenant_id, domain_id, connection_id)
    return DbtScaffoldListResponse(scaffolds=scaffolds)


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
    domain_id: str,
    payload: DbtScaffoldPatchRequest,
) -> dict:
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
    domain_id: str,
) -> dict:
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
        "parameters": [
            {
                "name": "domain_id",
                "in": "query",
                "required": False,
                "schema": {"type": "string"},
                "examples": {"energy": {"value": "energy_distribution"}},
            },
            {
                "name": "limit",
                "in": "query",
                "required": False,
                "schema": {"type": "integer"},
                "examples": {"limit": {"value": 200}},
            },
            {
                "name": "cursor",
                "in": "query",
                "required": False,
                "schema": {"type": "string"},
                "examples": {"cursor": {"value": "aW5zXzEyMw=="}},
            },
        ],
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
def insights(domain_id: str | None = None, limit: int = 200, cursor: str | None = None) -> InsightsResponse:
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
        "parameters": [
            {
                "name": "domain_id",
                "in": "query",
                "required": True,
                "schema": {"type": "string"},
                "examples": {"energy": {"value": "energy_distribution"}},
            },
            {
                "name": "scenario_id",
                "in": "query",
                "required": False,
                "schema": {"type": "string"},
                "examples": {"baseline": {"value": "baseline"}},
            },
            {
                "name": "type",
                "in": "query",
                "required": False,
                "schema": {"type": "string"},
                "examples": {"anomaly": {"value": "anomaly"}},
            },
            {
                "name": "metric_name",
                "in": "query",
                "required": False,
                "schema": {"type": "string"},
                "examples": {"metric_name": {"value": "total_sales_volume_tmt"}},
            },
        ],
    },
)
def generate_insights(
    domain_id: str,
    scenario_id: str | None = None,
    type: str = "variance",
    metric_name: str | None = None,
) -> InsightDetailResponse:
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
        "parameters": [
            {
                "name": "domain_id",
                "in": "query",
                "required": False,
                "schema": {"type": "string"},
                "examples": {"energy": {"value": "energy_distribution"}},
            },
            {
                "name": "status",
                "in": "query",
                "required": False,
                "schema": {"type": "string"},
                "examples": {"status": {"value": "open"}},
            },
            {
                "name": "limit",
                "in": "query",
                "required": False,
                "schema": {"type": "integer"},
                "examples": {"limit": {"value": 200}},
            },
            {
                "name": "cursor",
                "in": "query",
                "required": False,
                "schema": {"type": "string"},
                "examples": {"cursor": {"value": "YWN0XzEyMw=="}},
            },
        ]
    },
)
def actions(
    domain_id: str | None = None,
    status: str | None = None,
    limit: int = 200,
    cursor: str | None = None,
) -> ActionsResponse:
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
                                "domain_id": "energy_distribution",
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
    action_id = create_action(settings, payload.model_dump())
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
        "parameters": [
            {
                "name": "domain_id",
                "in": "query",
                "required": False,
                "schema": {"type": "string"},
                "examples": {"energy": {"value": "energy_distribution"}},
            },
            {
                "name": "limit",
                "in": "query",
                "required": False,
                "schema": {"type": "integer"},
                "examples": {"limit": {"value": 200}},
            },
            {
                "name": "cursor",
                "in": "query",
                "required": False,
                "schema": {"type": "string"},
                "examples": {"cursor": {"value": "YmFzZWxpbmU="}},
            },
        ]
    },
)
def scenarios(domain_id: str | None = None, limit: int = 200, cursor: str | None = None) -> ScenariosResponse:
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
                                "domain_id": "energy_distribution",
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
    scenario_id = create_scenario(settings, payload.model_dump())
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
        "parameters": [
            {
                "name": "dimension",
                "in": "query",
                "required": True,
                "schema": {"type": "string"},
                "examples": {"sales_area_name": {"value": "sales_area_name"}},
            },
            {
                "name": "search",
                "in": "query",
                "required": False,
                "schema": {"type": "string"},
                "examples": {"search": {"value": "ten"}},
            },
            {
                "name": "starts_with",
                "in": "query",
                "required": False,
                "schema": {"type": "string"},
                "examples": {"starts_with": {"value": "Vi"}},
            },
            {
                "name": "exclude_nulls",
                "in": "query",
                "required": False,
                "schema": {"type": "boolean"},
                "examples": {"exclude_nulls": {"value": True}},
            },
            {
                "name": "order",
                "in": "query",
                "required": False,
                "schema": {"type": "string", "enum": ["asc", "desc"]},
                "examples": {"order": {"value": "asc"}},
            },
            {
                "name": "limit",
                "in": "query",
                "required": False,
                "schema": {"type": "integer"},
                "examples": {"limit": {"value": 50}},
            },
            {
                "name": "cursor",
                "in": "query",
                "required": False,
                "schema": {"type": "string"},
                "examples": {"cursor": {"value": "VmlqYXlhd2FkYQ=="}},
            },
        ],
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
                                "domain_id": "energy_distribution",
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
    _require_scope(
        _request_scope(payload.connection_id, payload.database, payload.schema, payload.tables),
        "/metrics",
    )
    metric_id = upsert_metric(settings, payload.model_dump())
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
    _require_scope(
        _request_scope(payload.connection_id, payload.database, payload.schema, payload.tables),
        "/metrics/{metric_id}",
    )
    updates = {key: value for key, value in payload.model_dump().items() if value is not None}
    update_metric(settings, metric_id, updates)
    status = updates.get("status", "updated")
    return MetricUpsertResponse(metric_id=metric_id, status=status)

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
                                "domain_id": "manufacturing",
                                "source_type": "business_context",
                                "source_title": "Operations glossary and hierarchy notes",
                                "raw_text": "SBU = Strategic Business Unit. Sales org is Zone > Region > Sales Area...",
                                "file_ids": ["file_123", "file_456"],
                                "metadata": {
                                    "connection_id": "conn_prod",
                                    "database": "prod_warehouse",
                                    "schema": "public",
                                    "tables": ["fact_production_daily", "dim_plant"],
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
    scope = extract_scope_from_metadata(payload.metadata)
    _require_scope(scope, "/context/ingest")
    source_title = payload.source_title or generate_source_title(payload.raw_text, payload.metadata)
    context_id = create_context(
        settings,
        tenant_id=payload.tenant_id,
        domain_id=payload.domain_id,
        source_type=payload.source_type,
        source_title=source_title,
        raw_text=payload.raw_text,
        metadata=payload.metadata,
    )
    if payload.file_ids:
        link_context_files(settings, context_id, payload.file_ids)
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
                                "domain_id": "manufacturing",
                                "source_type": "business_context",
                                "source_title": "Operations glossary",
                                "metadata": "{\"connection_id\":\"conn_prod\",\"database\":\"prod_warehouse\",\"schema\":\"public\",\"tables\":[\"fact_production_daily\",\"dim_plant\"]}",
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
    domain_id: str = Form(...),
    source_type: str = Form(...),
    source_title: str | None = Form(None),
    metadata: str | None = Form(None),
    file: UploadFile = File(...),
) -> ContextFileIngestResponse:
    filename = (file.filename or "").lower()
    if filename.endswith(".doc"):
        raise HTTPException(status_code=400, detail="Unsupported file type: .doc")
    if not (filename.endswith(".txt") or filename.endswith(".docx")):
        raise HTTPException(status_code=400, detail="Unsupported file type: use .txt or .docx")
    try:
        raw_bytes = file.file.read()
    finally:
        file.file.close()
    if filename.endswith(".docx"):
        try:
            with zipfile.ZipFile(io.BytesIO(raw_bytes)) as docx:
                xml_data = docx.read("word/document.xml")
            root = ElementTree.fromstring(xml_data)
            text_nodes = [node.text for node in root.iter() if node.tag.endswith("}t") and node.text]
            raw_text = "\n".join(text_nodes).strip()
        except (KeyError, zipfile.BadZipFile, ElementTree.ParseError) as exc:
            raise HTTPException(status_code=400, detail="Invalid .docx file") from exc
    else:
        raw_text = raw_bytes.decode("utf-8", errors="replace")
    parsed_metadata = None
    if metadata:
        try:
            parsed_metadata = json.loads(metadata)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail="metadata must be valid JSON") from exc
    if not parsed_metadata:
        raise HTTPException(status_code=400, detail="metadata is required and must include connection scope")
    scope = extract_scope_from_metadata(parsed_metadata)
    _require_scope(scope, "/context/ingest-file")
    file_id = create_context_file(
        settings,
        tenant_id=tenant_id,
        domain_id=domain_id,
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
    return ContextFileIngestResponse(file_id=file_id, status="stored")


@app.get(
    "/context",
    response_model=ContextListResponse,
    tags=["context"],
    summary="List business context entries",
    description="List stored business context entries with cursor pagination.",
    openapi_extra={
        "parameters": [
            {
                "name": "tenant_id",
                "in": "query",
                "required": True,
                "schema": {"type": "string"},
                "examples": {"tenant_a": {"value": "tenant_a"}},
            },
            {
                "name": "domain_id",
                "in": "query",
                "required": True,
                "schema": {"type": "string"},
                "examples": {"manufacturing": {"value": "manufacturing"}},
            },
            {
                "name": "source_type",
                "in": "query",
                "required": False,
                "schema": {"type": "string"},
                "examples": {"business_context": {"value": "business_context"}},
            },
            {
                "name": "status",
                "in": "query",
                "required": False,
                "schema": {"type": "string"},
                "examples": {"submitted": {"value": "submitted"}},
            },
            {
                "name": "connection_id",
                "in": "query",
                "required": False,
                "schema": {"type": "string"},
                "examples": {"connection_id": {"value": "conn_prod"}},
            },
            {
                "name": "database",
                "in": "query",
                "required": False,
                "schema": {"type": "string"},
                "examples": {"database": {"value": "prod_warehouse"}},
            },
            {
                "name": "schema",
                "in": "query",
                "required": False,
                "schema": {"type": "string"},
                "examples": {"schema": {"value": "public"}},
            },
            {
                "name": "limit",
                "in": "query",
                "required": False,
                "schema": {"type": "integer"},
                "examples": {"limit": {"value": 200}},
            },
            {
                "name": "cursor",
                "in": "query",
                "required": False,
                "schema": {"type": "string"},
                "examples": {"cursor": {"value": "MjAyNS0wMS0wMVQwMDowMDowMFo="}},
            },
        ]
    },
)
def list_context_entries(
    tenant_id: str,
    domain_id: str,
    source_type: str | None = None,
    status: str | None = None,
    connection_id: str | None = None,
    database: str | None = None,
    schema: str | None = None,
    limit: int = 200,
    cursor: str | None = None,
) -> ContextListResponse:
    decoded_cursor = _decode_cursor(cursor) if cursor else None
    entries, next_cursor = list_context(
        settings,
        tenant_id=tenant_id,
        domain_id=domain_id,
        source_type=source_type,
        status=status,
        connection_id=connection_id,
        database=database,
        schema=schema,
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
                                "domain_id": "manufacturing",
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
    context_row = get_context(settings, payload.context_id)
    if not context_row:
        raise HTTPException(status_code=404, detail="Context not found")
    if context_row["tenant_id"] != payload.tenant_id or context_row["domain_id"] != payload.domain_id:
        raise HTTPException(status_code=400, detail="Context tenant/domain mismatch")

    file_texts = get_context_file_texts(settings, payload.context_id)
    combined_parts = [context_row["raw_text"]] if context_row["raw_text"] else []
    combined_parts.extend(file_texts)
    combined_text = "\n\n".join([part for part in combined_parts if part])
    extracted = extract_context(
        settings,
        raw_text=combined_text,
        extraction_types=payload.extraction_types,
    )
    extraction_id = persist_extraction(
        settings,
        context_id=payload.context_id,
        tenant_id=payload.tenant_id,
        domain_id=payload.domain_id,
        payload=extracted,
        llm_model=settings.openai_model,
    )
    mark_context_processed(settings, payload.context_id)
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
    domain_id: str,
) -> ContextExtractionResponse:
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
                                "domain_id": "manufacturing",
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
    extraction_row = get_extraction(settings, payload.extraction_id)
    if not extraction_row:
        raise HTTPException(status_code=404, detail="Extraction not found")
    if extraction_row["tenant_id"] != payload.tenant_id or extraction_row["domain_id"] != payload.domain_id:
        raise HTTPException(status_code=400, detail="Extraction tenant/domain mismatch")

    updated = apply_extractions(
        settings,
        tenant_id=payload.tenant_id,
        domain_id=payload.domain_id,
        payload=extraction_row["payload"],
        apply_flags=payload.apply,
        source_context_id=extraction_row.get("context_id"),
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
                            "summary": "Update metadata (same scope)",
                            "value": {
                                "metadata": {
                                    "connection_id": "conn_prod",
                                    "database": "prod_warehouse",
                                    "schema": "public",
                                    "tables": ["fact_production_daily", "dim_plant"],
                                }
                            },
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
    domain_id: str,
    payload: ContextPatchRequest,
) -> dict:
    context_row = get_context(settings, context_id)
    if not context_row:
        raise HTTPException(status_code=404, detail="Context not found")
    if context_row["tenant_id"] != tenant_id or context_row["domain_id"] != domain_id:
        raise HTTPException(status_code=400, detail="Context tenant/domain mismatch")

    if payload.metadata and _metadata_has_scope(payload.metadata):
        _require_scope(extract_scope_from_metadata(payload.metadata), "/context/{context_id}")
        existing_scope = {
            "connection_id": context_row.get("connection_id"),
            "database": context_row.get("database_name"),
            "schema": context_row.get("schema_name"),
            "tables": (context_row.get("metadata") or {}).get("tables"),
        }
        if extract_scope_from_metadata(payload.metadata) != existing_scope:
            raise HTTPException(status_code=400, detail="Context scope cannot be changed")

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
                            "value": {
                                "metadata": {
                                    "connection_id": "conn_prod",
                                    "database": "prod_warehouse",
                                    "schema": "public",
                                    "tables": ["fact_production_daily", "dim_plant"],
                                }
                            },
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
    domain_id: str,
    payload: ContextFilePatchRequest,
) -> dict:
    if payload.metadata is None:
        raise HTTPException(status_code=400, detail="metadata is required")
    file_row = get_context_file(settings, file_id)
    if not file_row:
        raise HTTPException(status_code=404, detail="Context file not found")
    if file_row["tenant_id"] != tenant_id or file_row["domain_id"] != domain_id:
        raise HTTPException(status_code=400, detail="Context file tenant/domain mismatch")
    if _metadata_has_scope(payload.metadata):
        _require_scope(extract_scope_from_metadata(payload.metadata), "/context/files/{file_id}")
        if not scopes_match(file_row.get("metadata"), payload.metadata):
            raise HTTPException(status_code=400, detail="Context file scope cannot be changed")
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
    domain_id: str,
    payload: ContextExtractionPatchRequest,
) -> dict:
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
    description="Return ontology entities and hierarchies, with optional tenant overrides.",
    openapi_extra={
        "parameters": [
            {
                "name": "domain_id",
                "in": "query",
                "required": True,
                "schema": {"type": "string"},
                "examples": {
                    "energy": {"value": "energy_distribution"},
                    "manufacturing": {"value": "manufacturing"},
                },
            },
            {
                "name": "tenant_id",
                "in": "query",
                "required": False,
                "schema": {"type": "string"},
                "examples": {"tenant_a": {"value": "tenant_1"}},
            },
            {
                "name": "entity_limit",
                "in": "query",
                "required": False,
                "schema": {"type": "integer"},
                "examples": {"entity_limit": {"value": 200}},
            },
            {
                "name": "entity_cursor",
                "in": "query",
                "required": False,
                "schema": {"type": "string"},
                "examples": {"entity_cursor": {"value": "b3JnYW5pemF0aW9uYWxfdW5pdA=="}},
            },
            {
                "name": "hierarchy_limit",
                "in": "query",
                "required": False,
                "schema": {"type": "integer"},
                "examples": {"hierarchy_limit": {"value": 200}},
            },
            {
                "name": "hierarchy_cursor",
                "in": "query",
                "required": False,
                "schema": {"type": "string"},
                "examples": {"hierarchy_cursor": {"value": "c2FsZXNfb3Jn"}},
            },
        ],
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
                                    "entity_limit": 200,
                                    "entity_cursor": None,
                                    "entity_next_cursor": "cHJvZHVjdA==",
                                    "hierarchy_limit": 200,
                                    "hierarchy_cursor": None,
                                    "hierarchy_next_cursor": "cmVnaW9uX29yZw==",
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
    domain_id: str,
    tenant_id: str | None = None,
    entity_limit: int = 200,
    entity_cursor: str | None = None,
    hierarchy_limit: int = 200,
    hierarchy_cursor: str | None = None,
) -> EntitiesResponse:
    pack_path = f"packs/{domain_id}"
    entities_list = list_entities(pack_path)
    hierarchies_list = list_hierarchies(pack_path)

    if tenant_id:
        entity_overrides, hierarchy_overrides = load_overrides(settings, tenant_id, domain_id)
        entities_list = merge_entities(entities_list, entity_overrides)
        hierarchies_list = merge_hierarchies(hierarchies_list, hierarchy_overrides)

    entity_page, entity_next = _paginate_list(
        entities_list,
        entity_cursor,
        entity_limit,
        key_fn=lambda item: item.get("entity_id", ""),
    )
    hierarchy_page, hierarchy_next = _paginate_list(
        hierarchies_list,
        hierarchy_cursor,
        hierarchy_limit,
        key_fn=lambda item: item.get("name", ""),
    )
    return EntitiesResponse(
        entities=entity_page,
        hierarchies=hierarchy_page,
        entity_limit=entity_limit,
        entity_cursor=entity_cursor,
        entity_next_cursor=entity_next,
        hierarchy_limit=hierarchy_limit,
        hierarchy_cursor=hierarchy_cursor,
        hierarchy_next_cursor=hierarchy_next,
    )


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
    domain_id: str,
    tenant_id: str,
    payload: EntityOverrideRequest,
) -> dict:
    upsert_entity_override(
        settings,
        tenant_id,
        domain_id,
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
    domain_id: str,
    tenant_id: str,
    payload: HierarchyOverrideRequest,
) -> dict:
    upsert_hierarchy_override(
        settings,
        tenant_id,
        domain_id,
        {
            "hierarchy_name": hierarchy_name,
            "levels": payload.levels,
            "description": payload.description,
        },
    )
    return {"ok": True}

@app.get(
    "/schema",
    response_model=SchemaResponse,
    tags=["explore"],
    summary="List dbt models",
    description="Return models and columns from dbt manifest.json, scoped by optional database/schema filters.",
    openapi_extra={
        "parameters": [
            {
                "name": "connection_id",
                "in": "query",
                "required": False,
                "schema": {"type": "string"},
                "examples": {"connection_id": {"value": "conn_prod"}},
            },
            {
                "name": "database",
                "in": "query",
                "required": False,
                "schema": {"type": "string"},
                "examples": {"database": {"value": "prod_warehouse"}},
            },
            {
                "name": "schema",
                "in": "query",
                "required": False,
                "schema": {"type": "string"},
                "examples": {"schema": {"value": "public"}},
            },
            {
                "name": "limit",
                "in": "query",
                "required": False,
                "schema": {"type": "integer"},
                "examples": {"limit": {"value": 200}},
            },
            {
                "name": "cursor",
                "in": "query",
                "required": False,
                "schema": {"type": "string"},
                "examples": {"cursor": {"value": "ZmFjdF9ocGNsX3NhbGVzX2RhaWx5"}},
            },
        ],
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
    connection_id: str | None = None,
    database: str | None = None,
    schema: str | None = None,
    limit: int = 200,
    cursor: str | None = None,
) -> SchemaResponse:
    if connection_id:
        scopes = resolve_connection_scope(settings, connection_id)
        if not scopes:
            raise HTTPException(status_code=404, detail="Unknown connection_id")
        if not database and not schema and scopes:
            database = scopes[0].get("database_name")
            schema = scopes[0].get("schema_name")
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
                            "value": {"schema": "public"},
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
    tables = scan_schema(settings, request.schema)
    return OnboardScanResponse(tables=tables)


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
                                "domain_id": "manufacturing",
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
    tenant_id = request.tenant_id or settings.default_tenant_id
    domain_id = request.domain_id or settings.default_domain_id
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

    _log_scan_step("complete", {"tenant_id": tenant_id, "domain_id": domain_id})
    return OnboardScanConnectionResponse(connections=connections_payload)


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


@app.post(
    "/onboard/map",
    response_model=OnboardMapResponse,
    tags=["onboard"],
    summary="Map schema to ontology",
    description="Suggest entity mappings from schema columns to the selected domain ontology.",
    openapi_extra={
        "parameters": [
            {
                "name": "domain_id",
                "in": "query",
                "required": True,
                "schema": {"type": "string"},
                "examples": {"manufacturing": {"value": "manufacturing"}},
            },
            {
                "name": "tenant_id",
                "in": "query",
                "required": False,
                "schema": {"type": "string"},
                "examples": {"tenant_a": {"value": "tenant_a"}},
            },
            {
                "name": "use_llm",
                "in": "query",
                "required": False,
                "schema": {"type": "boolean"},
                "examples": {"use_llm": {"value": True}},
            },
        ],
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "map_public": {
                            "summary": "Map public schema",
                            "value": {
                                "schema": "public",
                                "tables": ["fact_production_daily", "dim_plant"],
                                "connection_id": "conn_prod",
                                "database": "prod_warehouse",
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
    domain_id: str,
    use_llm: bool = False,
    tenant_id: str | None = None,
) -> OnboardMapResponse:
    schema_value = request.schema or (request.schemas[0] if request.schemas else None)
    _require_scope(
        _request_scope(request.connection_id, request.database, schema_value, request.tables),
        "/onboard/map",
    )
    schemas = request.schemas or ([request.schema] if request.schema else [settings.db_schema])
    tables = []
    for schema_name in schemas:
        schema_tables = scan_schema(settings, schema_name)
        if request.tables:
            schema_tables = [table for table in schema_tables if table.get("table") in request.tables]
        tables.extend(schema_tables)
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
        candidate
        for candidate in candidates
        if candidate.get("confidence", 0) < LOW_CONFIDENCE_THRESHOLD
    ]
    high_confidence_candidates = [
        candidate
        for candidate in candidates
        if candidate.get("confidence", 0) >= LOW_CONFIDENCE_THRESHOLD
    ]
    return OnboardMapResponse(
        candidates=high_confidence_candidates,
        low_confidence_candidates=low_confidence_candidates,
        low_confidence_threshold=LOW_CONFIDENCE_THRESHOLD,
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
    "/onboard/infer-models",
    response_model=InferModelsResponse,
    tags=["onboard"],
    summary="Infer facts and dimensions",
    description="Suggest candidate dbt facts and dimensions from scanned schema and ontology.",
    openapi_extra={
        "parameters": [
            {
                "name": "domain_id",
                "in": "query",
                "required": False,
                "schema": {"type": "string"},
                "examples": {"manufacturing": {"value": "manufacturing"}},
            }
        ],
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "infer_models": {
                            "summary": "Infer models",
                            "value": {
                                "schema": "public",
                                "tables": ["fact_production_daily", "dim_plant"],
                                "time_column": "production_date",
                                "grain": "day",
                                "use_llm": True,
                                "connection_id": "conn_prod",
                                "database": "prod_warehouse",
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
def infer_models(request: InferModelsRequest, domain_id: str | None = None) -> InferModelsResponse:
    schema_value = request.schema or (request.schemas[0] if request.schemas else None)
    _require_scope(
        _request_scope(request.connection_id, request.database, schema_value, request.tables),
        "/onboard/infer-models",
    )
    schemas = request.schemas or [request.schema]
    tables = []
    for schema_name in schemas:
        schema_tables = scan_schema(settings, schema_name)
        if request.tables:
            schema_tables = [table for table in schema_tables if table.get("table") in request.tables]
        tables.extend(schema_tables)
    facts, dims = _infer_models_from_scan(tables, request.time_column, request.grain)
    if request.use_llm:
        try:
            llm_payload = llm_infer_models(settings, tables, domain_id)
            facts, dims = _merge_models(facts, dims, llm_payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return InferModelsResponse(facts=facts, dimensions=dims)


@app.post(
    "/metrics/suggested",
    response_model=SuggestedMetricsResponse,
    tags=["onboard"],
    summary="Suggest metrics",
    description="Generate suggested measures, time columns, and entity mappings.",
    openapi_extra={
        "parameters": [
            {
                "name": "domain_id",
                "in": "query",
                "required": True,
                "schema": {"type": "string"},
                "examples": {"energy": {"value": "energy_distribution"}},
            },
            {
                "name": "persist",
                "in": "query",
                "required": False,
                "schema": {"type": "boolean"},
                "examples": {"persist": {"value": True}},
            }
        ],
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "suggest_public": {
                            "summary": "Suggest metrics for public schema",
                            "value": {
                                "schema": "public",
                                "tables": ["fact_hpcl_sales_daily"],
                                "connection_id": "conn_prod",
                                "database": "prod_warehouse",
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
def suggested_metrics(request: OnboardScanRequest, domain_id: str, persist: bool = False) -> SuggestedMetricsResponse:
    schema_value = request.schema or (request.schemas[0] if request.schemas else None)
    _require_scope(
        _request_scope(request.connection_id, request.database, schema_value, request.tables),
        "/metrics/suggested",
    )
    schemas = request.schemas or ([request.schema] if request.schema else [settings.db_schema])
    tables = []
    for schema_name in schemas:
        schema_tables = scan_schema(settings, schema_name)
        if request.tables:
            schema_tables = [table for table in schema_tables if table.get("table") in request.tables]
        tables.extend(schema_tables)
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
        persist_suggested_metrics(settings, domain_id, measures)
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
        if request.tenant_id and request.domain_id:
            glossary = fetch_glossary_terms(settings, request.tenant_id, request.domain_id)
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
                                "domain_id": "manufacturing",
                                "connection_id": "conn_prod",
                                "database": "prod_warehouse",
                                "schema": "public",
                                "tables": ["fact_sales", "dim_sales_area"],
                                "limit": 100,
                                "explain": True,
                            },
                        },
                        "hpcl_vs_bpcl": {
                            "summary": "HPCL vs BPCL market share",
                            "value": {
                                "question": "HPCL vs BPCL market share for MS in UTTAR PRADESH during FY 2024-2025.",
                                "tenant_id": "tenant_a",
                                "domain_id": "manufacturing",
                                "connection_id": "conn_prod",
                                "database": "prod_warehouse",
                                "schema": "public",
                                "tables": ["fact_sales", "dim_sales_area"],
                                "limit": 100,
                                "explain": True,
                            },
                        },
                        "run_rate_risk": {
                            "summary": "Below required run rate",
                            "value": {
                                "question": "Which sales areas are below required run rate this month?",
                                "tenant_id": "tenant_a",
                                "domain_id": "manufacturing",
                                "connection_id": "conn_prod",
                                "database": "prod_warehouse",
                                "schema": "public",
                                "tables": ["fact_sales", "dim_sales_area"],
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
    _require_scope(
        _request_scope(request.connection_id, request.database, request.schema, request.tables),
        "/query",
    )
    glossary = None
    if request.tenant_id and request.domain_id:
        glossary = fetch_glossary_terms(settings, request.tenant_id, request.domain_id)
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

    return QueryResult(
        metrics=[metric.name for metric in metrics],
        dimensions=[dim.name for dim in dim_objects if dim.name != "company_name"],
        sql=built.sql if request.explain else None,
        rows=rows,
        by_company_sql=by_company_sql,
        by_company_rows=by_company_rows,
    )
