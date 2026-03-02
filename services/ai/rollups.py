from __future__ import annotations

import hashlib
import re
import uuid
from typing import Any

from services.ai.catalog import load_catalog_with_registry, resolve_ref
from services.ai.config import Settings
from services.ai.db import run_query, execute_non_query


_TIME_COL_CANDIDATES = ["process_date", "pdate", "date_day", "date", "execution_date"]


def _sanitize(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]+", "_", name or "").strip("_").lower()


def _hash_parts(parts: list[str]) -> str:
    joined = "|".join(parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:10]


def _infer_base_model(metric_sql: str) -> str | None:
    match = re.search(r"ref\\('([^']+)'\\)", metric_sql or "")
    if match:
        return match.group(1)
    return None


def _list_table_columns(settings: Settings, schema: str, table: str) -> list[str]:
    rows = run_query(
        settings,
        """
        SELECT column_name
          FROM information_schema.columns
         WHERE table_schema = %s
           AND table_name = %s
        """,
        [schema, table],
    )
    return [row["column_name"] for row in rows]


def _pick_time_column(columns: list[str]) -> str | None:
    column_set = {c.lower(): c for c in columns}
    for candidate in _TIME_COL_CANDIDATES:
        if candidate in column_set:
            return column_set[candidate]
    return None


def create_rollup_registry(
    settings: Settings,
    *,
    tenant_id: str,
    domain_id: str,
    base_model: str,
    metric_name: str,
    dimensions: list[str],
    time_grain: str,
    rollup_table: str,
    filters: list[dict] | None = None,
) -> dict[str, Any]:
    rollup_id = f"rollup_{uuid.uuid4().hex[:10]}"
    execute_non_query(
        settings,
        """
        INSERT INTO public.quantyx_rollup_registry (
          rollup_id, tenant_id, domain_id, base_model, metric_name, dimensions,
          time_grain, filters, rollup_table, status, created_at, updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s::jsonb, %s, 'active', now(), now())
        """,
        [
            rollup_id,
            tenant_id,
            domain_id,
            base_model,
            metric_name,
            dimensions,
            time_grain,
            filters or [],
            rollup_table,
        ],
    )
    return {
        "rollup_id": rollup_id,
        "tenant_id": tenant_id,
        "domain_id": domain_id,
        "base_model": base_model,
        "metric_name": metric_name,
        "dimensions": dimensions,
        "time_grain": time_grain,
        "filters": filters or [],
        "rollup_table": rollup_table,
        "status": "active",
    }


def get_rollup(settings: Settings, rollup_id: str) -> dict[str, Any] | None:
    rows = run_query(
        settings,
        """
        SELECT rollup_id, tenant_id, domain_id, base_model, metric_name, dimensions,
               time_grain, filters, rollup_table, status, created_at, updated_at
          FROM public.quantyx_rollup_registry
         WHERE rollup_id = %s
        """,
        [rollup_id],
    )
    return rows[0] if rows else None


def update_rollup_status(settings: Settings, rollup_id: str, status: str) -> None:
    execute_non_query(
        settings,
        """
        UPDATE public.quantyx_rollup_registry
           SET status = %s, updated_at = now()
         WHERE rollup_id = %s
        """,
        [status, rollup_id],
    )


def list_rollups(settings: Settings, tenant_id: str, domain_id: str | None) -> list[dict[str, Any]]:
    if domain_id:
        return run_query(
            settings,
            """
            SELECT rollup_id, tenant_id, domain_id, base_model, metric_name, dimensions,
                   time_grain, filters, rollup_table, status, created_at, updated_at
              FROM public.quantyx_rollup_registry
             WHERE tenant_id = %s AND domain_id = %s
             ORDER BY created_at DESC
            """,
            [tenant_id, domain_id],
        )
    return run_query(
        settings,
        """
        SELECT rollup_id, tenant_id, domain_id, base_model, metric_name, dimensions,
               time_grain, filters, rollup_table, status, created_at, updated_at
          FROM public.quantyx_rollup_registry
         WHERE tenant_id = %s
         ORDER BY created_at DESC
        """,
        [tenant_id],
    )


def find_matching_rollup(
    settings: Settings,
    *,
    tenant_id: str,
    domain_id: str,
    metric_name: str,
    dimensions: list[str],
    time_grain: str,
) -> dict[str, Any] | None:
    dims_sorted = sorted(dimensions or [])
    rows = run_query(
        settings,
        """
        SELECT rollup_id, base_model, metric_name, dimensions, time_grain, filters, rollup_table, status
          FROM public.quantyx_rollup_registry
         WHERE tenant_id = %s
           AND domain_id = %s
           AND metric_name = %s
           AND time_grain = %s
           AND dimensions = %s::jsonb
           AND status = 'active'
         LIMIT 1
        """,
        [tenant_id, domain_id, metric_name, time_grain, dims_sorted],
    )
    return rows[0] if rows else None


def build_rollup_table(
    settings: Settings,
    rollup: dict[str, Any],
    *,
    schema_name: str | None = None,
    time_column: str | None = None,
) -> None:
    schema = schema_name or settings.db_schema
    metric_name = rollup["metric_name"]
    base_model = rollup["base_model"]
    dimensions = rollup.get("dimensions") or []
    time_grain = rollup.get("time_grain") or "none"
    rollup_table = rollup["rollup_table"]

    catalog = load_catalog_with_registry(settings, settings.metrics_catalog_path)
    metric = catalog.metrics.get(metric_name)
    if not metric:
        raise ValueError(f"Unknown metric: {metric_name}")

    metric_sql = resolve_ref(metric.sql, schema)
    if metric.metric_type == "sum":
        metric_sql = f"SUM({metric_sql})"
    elif metric.metric_type in {"average", "avg"}:
        metric_sql = f"AVG({metric_sql})"
    elif metric.metric_type == "min":
        metric_sql = f"MIN({metric_sql})"
    elif metric.metric_type == "max":
        metric_sql = f"MAX({metric_sql})"

    table_ref = f"{schema}.{base_model}"
    columns = _list_table_columns(settings, schema, base_model)
    time_column = time_column or _pick_time_column(columns)

    select_parts: list[str] = []
    group_parts: list[str] = []
    for dim in dimensions:
        if time_grain in {"day", "week", "month"} and dim.startswith("process_") and time_column:
            grain = "month" if "month" in dim else "week" if "week" in dim else "day"
            expr = f"date_trunc('{grain}', {table_ref}.{time_column})"
            select_parts.append(f"{expr} AS {dim}")
            group_parts.append(expr)
        else:
            select_parts.append(f"{table_ref}.{dim} AS {dim}")
            group_parts.append(f"{table_ref}.{dim}")

    select_parts.append(f'{metric_sql} AS "{metric_name}"')

    select_sql = (
        f"SELECT {', '.join(select_parts)} FROM {table_ref}"
        + (f" GROUP BY {', '.join(group_parts)}" if group_parts else "")
    )

    execute_non_query(
        settings,
        f"CREATE TABLE IF NOT EXISTS {schema}.{rollup_table} AS {select_sql}",
        [],
    )
    execute_non_query(settings, f"DELETE FROM {schema}.{rollup_table}", [])
    execute_non_query(settings, f"INSERT INTO {schema}.{rollup_table} {select_sql}", [])


def create_rollup(
    settings: Settings,
    *,
    tenant_id: str,
    domain_id: str,
    metric_name: str,
    dimensions: list[str],
    time_grain: str,
    filters: list[dict] | None = None,
) -> dict[str, Any]:
    catalog = load_catalog_with_registry(settings, settings.metrics_catalog_path)
    metric = catalog.metrics.get(metric_name)
    if not metric:
        raise ValueError(f"Unknown metric: {metric_name}")
    base_model = _infer_base_model(metric.sql)
    if not base_model:
        raise ValueError("Unable to infer base model from metric SQL")
    dims_sorted = sorted(dimensions or [])
    rollup_table = f"rollup_{_sanitize(metric_name)}_{_hash_parts([base_model, metric_name, time_grain, ','.join(dims_sorted)])}"
    rollup = create_rollup_registry(
        settings,
        tenant_id=tenant_id,
        domain_id=domain_id,
        base_model=base_model,
        metric_name=metric_name,
        dimensions=dims_sorted,
        time_grain=time_grain,
        filters=filters,
        rollup_table=rollup_table,
    )
    return rollup
