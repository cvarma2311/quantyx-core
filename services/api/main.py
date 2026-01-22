from __future__ import annotations

from typing import List

import logging
import re

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException

from services.ai.catalog import load_catalog
from services.ai.config import load_settings
from services.ai.db import run_query
from services.ai.resolver import resolve_question
from services.ai.schema_loader import load_manifest_models
from services.ai.sql_builder import Filter, build_query
from services.api.schemas import MetricsResponse, QueryRequest, QueryResult, SchemaResponse


load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("quantyx.api")

app = FastAPI(title="quantyx-core-services API", version="0.1.0")

settings = load_settings()
catalog = load_catalog(settings.metrics_catalog_path)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/metrics", response_model=MetricsResponse)
def metrics() -> MetricsResponse:
    payload = [
        {
            "name": metric.name,
            "description": metric.description,
            "type": metric.metric_type,
            "grain": metric.grain,
            "dimensions": metric.dimensions,
        }
        for metric in catalog.metrics.values()
    ]
    return MetricsResponse(metrics=payload)


@app.get("/schema", response_model=SchemaResponse)
def schema() -> SchemaResponse:
    models = load_manifest_models(settings.dbt_manifest_path)
    return SchemaResponse(models=models)


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


@app.post("/query", response_model=QueryResult)
def query(request: QueryRequest) -> QueryResult:
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
    except ValueError as exc:
        logger.exception("build_query failed")
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    logger.info("sql: %s", built.sql)
    logger.info("params: %s", built.params)
    rows = run_query(settings, built.sql, built.params)
    logger.info("rows: %s", len(rows))

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

    return QueryResult(
        metrics=[metric.name for metric in metrics],
        dimensions=[dim.name for dim in dim_objects if dim.name != "company_name"],
        sql=built.sql if request.explain else None,
        rows=rows,
        by_company_sql=by_company_sql,
        by_company_rows=by_company_rows,
    )
