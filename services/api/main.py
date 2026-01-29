from __future__ import annotations

from typing import Callable, List, TypeVar

import base64
import logging
import time
import re
import uuid

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException

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
from services.ai.resolver import resolve_question
from services.ai.schema_loader import load_manifest_models
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


def _model_schema_map() -> dict[str, str]:
    models = load_manifest_models(settings.dbt_manifest_path)
    return {model["name"]: model.get("schema") or "" for model in models}


def _model_database_map() -> dict[str, str]:
    models = load_manifest_models(settings.dbt_manifest_path)
    return {model["name"]: model.get("database") or "" for model in models}


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
    lineage = build_lineage(catalog, settings.dbt_manifest_path)
    if metric_name:
        lineage = [entry for entry in lineage if entry.get("metric_name") == metric_name]
    return LineageResponse(lineage=lineage)


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
    models = load_manifest_models(settings.dbt_manifest_path)
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
def onboard_scan_connection(request: OnboardScanMultiConnectionRequest) -> OnboardScanConnectionResponse:
    connections_payload = []
    for connection in request.connections:
        databases_payload = []
        scopes: list[tuple[str, str]] = []
        for database in connection.databases:
            schemas_payload = []
            for schema in database.schemas:
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
        connections_payload.append(
            {"connection_id": connection.connection_id, "databases": databases_payload}
        )
        register_connection(settings, connection.connection_id)
        if scopes:
            register_connection_scopes(settings, connection.connection_id, scopes)

    persist_schema_scan(
        settings,
        request.model_dump(),
        {"connections": connections_payload},
    )

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
                            "value": {"schema": "public"},
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
) -> OnboardMapResponse:
    schemas = request.schemas or ([request.schema] if request.schema else [settings.db_schema])
    tables = []
    for schema_name in schemas:
        schema_tables = scan_schema(settings, schema_name)
        if request.tables:
            schema_tables = [table for table in schema_tables if table.get("table") in request.tables]
        tables.extend(schema_tables)
    ontology = load_pack(f"packs/{domain_id}").get("ontology", {})
    rule_candidates = map_entities(tables, ontology)
    llm_candidates: list[dict] = []
    if use_llm:
        try:
            llm_candidates = llm_map_entities(settings, tables, ontology)
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
        resolved = resolve_question(request.question, catalog, settings)
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
                                "limit": 100,
                                "explain": True,
                            },
                        },
                        "hpcl_vs_bpcl": {
                            "summary": "HPCL vs BPCL market share",
                            "value": {
                                "question": "HPCL vs BPCL market share for MS in UTTAR PRADESH during FY 2024-2025.",
                                "limit": 100,
                                "explain": True,
                            },
                        },
                        "run_rate_risk": {
                            "summary": "Below required run rate",
                            "value": {
                                "question": "Which sales areas are below required run rate this month?",
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
            resolved = resolve_question(request.question, catalog, settings, allowed_metrics=allowed_metrics)
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
