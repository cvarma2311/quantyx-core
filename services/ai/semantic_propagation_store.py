from __future__ import annotations

from typing import Any
from uuid import uuid4

from psycopg2.extras import Json

from services.ai.config import Settings
from services.ai.db import execute_non_query, run_query


ARTIFACT_PROPAGATION_ACTIONS: dict[str, tuple[str, ...]] = {
    "business_context": ("refresh_semantic_state", "refresh_workspace_semantics"),
    "hierarchy_override": (
        "refresh_hierarchies",
        "refresh_chart_interaction_metadata",
        "refresh_affected_dashboards",
        "refresh_workspace_semantics",
    ),
    "column_annotation": (
        "refresh_glossary",
        "refresh_chart_labels",
        "refresh_chart_interaction_metadata",
        "refresh_workspace_semantics",
    ),
    "metric_refinement": (
        "refresh_metrics",
        "refresh_affected_dashboards",
        "refresh_anomaly_correlation_context",
        "refresh_workspace_semantics",
    ),
    "join_rule": (
        "refresh_query_planner_constraints",
        "refresh_affected_dashboards",
        "refresh_workspace_semantics",
    ),
    "chart_guidance": ("refresh_chart_interaction_metadata", "refresh_affected_dashboards"),
    "interpretation_rule": ("refresh_anomaly_correlation_context",),
    "context_question_answer": ("refresh_semantic_state", "refresh_workspace_semantics"),
}

HIGH_IMPACT_TYPES = {"metric_refinement", "join_rule"}
BROAD_IMPACT_TYPES = {"business_context", "hierarchy_override"}


def _dedupe_preserve(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _artifact_json(artifact: dict[str, Any]) -> dict[str, Any]:
    value = artifact.get("artifact_json") or {}
    return value if isinstance(value, dict) else {}


def _artifact_tables(artifact: dict[str, Any]) -> list[str]:
    payload = _artifact_json(artifact)
    tables: list[str] = []
    for key in ("table", "left_table", "right_table"):
        value = payload.get(key)
        if value:
            tables.append(str(value))
    return _dedupe_preserve(tables)


def _artifact_columns(artifact: dict[str, Any]) -> list[str]:
    payload = _artifact_json(artifact)
    columns: list[str] = []
    if payload.get("column"):
        columns.append(str(payload["column"]))
    for key in ("levels", "preferred_drill_path"):
        values = payload.get(key)
        if isinstance(values, list):
            columns.extend(str(value) for value in values if str(value or "").strip())
    return _dedupe_preserve(columns)


def _artifact_metrics(artifact: dict[str, Any]) -> list[str]:
    payload = _artifact_json(artifact)
    metrics = [payload.get("metric_name"), payload.get("metric_id")]
    return _dedupe_preserve([str(value) for value in metrics if str(value or "").strip()])


def plan_semantic_propagation_scope(artifacts: list[dict[str, Any]]) -> dict[str, Any]:
    artifact_ids: list[str] = []
    artifact_types: list[str] = []
    refresh_actions: list[str] = []
    tables: list[str] = []
    columns: list[str] = []
    metrics: list[str] = []

    for artifact in artifacts:
        artifact_type = str(artifact.get("artifact_type") or "").strip()
        if not artifact_type:
            continue
        if artifact.get("artifact_id"):
            artifact_ids.append(str(artifact["artifact_id"]))
        artifact_types.append(artifact_type)
        refresh_actions.extend(ARTIFACT_PROPAGATION_ACTIONS.get(artifact_type, ("refresh_semantic_state",)))
        tables.extend(_artifact_tables(artifact))
        columns.extend(_artifact_columns(artifact))
        metrics.extend(_artifact_metrics(artifact))

    deduped_types = _dedupe_preserve(artifact_types)
    impact_level = "none"
    if any(artifact_type in HIGH_IMPACT_TYPES for artifact_type in deduped_types):
        impact_level = "high"
    elif any(artifact_type in BROAD_IMPACT_TYPES for artifact_type in deduped_types):
        impact_level = "broad"
    elif deduped_types:
        impact_level = "local"

    return {
        "artifact_ids": _dedupe_preserve(artifact_ids),
        "artifact_types": deduped_types,
        "refresh_actions": _dedupe_preserve(refresh_actions),
        "affected_tables": _dedupe_preserve(tables),
        "affected_columns": _dedupe_preserve(columns),
        "affected_metrics": _dedupe_preserve(metrics),
        "impact_level": impact_level,
    }


def create_semantic_propagation_job(
    settings: Settings,
    *,
    tenant_id: str,
    domain_id: str,
    trigger_type: str,
    affected_scope_json: dict[str, Any],
    connection_id: str | None = None,
    database_name: str | None = None,
    schema_name: str | None = None,
    status: str = "queued",
) -> str:
    job_id = f"semprop_{uuid4().hex[:12]}"
    execute_non_query(
        settings,
        """
        INSERT INTO public.quantyx_semantic_propagation_jobs (
          job_id, tenant_id, domain_id, connection_id, database_name, schema_name,
          trigger_type, affected_scope_json, status, created_at, completed_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, now(),
                CASE WHEN %s IN ('completed', 'failed', 'skipped') THEN now() ELSE NULL END)
        """,
        [
            job_id,
            tenant_id,
            domain_id,
            connection_id,
            database_name,
            schema_name,
            trigger_type,
            Json(affected_scope_json or {}),
            status,
            status,
        ],
    )
    return job_id


def enqueue_semantic_propagation_for_artifacts(
    settings: Settings,
    *,
    tenant_id: str,
    domain_id: str,
    artifacts: list[dict[str, Any]],
    trigger_type: str,
    connection_id: str | None = None,
    database_name: str | None = None,
    schema_name: str | None = None,
    semantic_state_id: str | None = None,
) -> dict[str, Any] | None:
    approved_artifacts = [
        artifact
        for artifact in artifacts
        if artifact.get("validation_status") == "valid"
        and artifact.get("approval_status") in {"approved", "auto_approved"}
    ]
    scope = plan_semantic_propagation_scope(approved_artifacts)
    if not scope["artifact_types"]:
        return None
    if semantic_state_id:
        scope["semantic_state_id"] = semantic_state_id
    job_id = create_semantic_propagation_job(
        settings,
        tenant_id=tenant_id,
        domain_id=domain_id,
        connection_id=connection_id,
        database_name=database_name,
        schema_name=schema_name,
        trigger_type=trigger_type,
        affected_scope_json=scope,
    )
    return {"job_id": job_id, "affected_scope_json": scope, "status": "queued"}


def list_semantic_propagation_jobs(
    settings: Settings,
    *,
    tenant_id: str,
    domain_id: str | None = None,
    connection_id: str | None = None,
    database_name: str | None = None,
    schema_name: str | None = None,
    status: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    filters = ["tenant_id = %s"]
    params: list[Any] = [tenant_id]
    if domain_id:
        filters.append("domain_id = %s")
        params.append(domain_id)
    if connection_id:
        filters.append("connection_id IS NOT DISTINCT FROM %s")
        params.append(connection_id)
    if database_name:
        filters.append("database_name IS NOT DISTINCT FROM %s")
        params.append(database_name)
    if schema_name:
        filters.append("schema_name IS NOT DISTINCT FROM %s")
        params.append(schema_name)
    if status:
        filters.append("status = %s")
        params.append(status)
    params.append(max(1, min(int(limit or 100), 500)))
    return run_query(
        settings,
        f"""
        SELECT *
          FROM public.quantyx_semantic_propagation_jobs
         WHERE {' AND '.join(filters)}
         ORDER BY created_at DESC
         LIMIT %s
        """,
        params,
    )


def get_semantic_propagation_job(settings: Settings, job_id: str, *, tenant_id: str) -> dict[str, Any] | None:
    rows = run_query(
        settings,
        """
        SELECT *
          FROM public.quantyx_semantic_propagation_jobs
         WHERE job_id = %s
           AND tenant_id = %s
         LIMIT 1
        """,
        [job_id, tenant_id],
    )
    return rows[0] if rows else None


def update_semantic_propagation_job_status(settings: Settings, job_id: str, *, status: str) -> None:
    execute_non_query(
        settings,
        """
        UPDATE public.quantyx_semantic_propagation_jobs
           SET status = %s,
               completed_at = CASE WHEN %s IN ('completed', 'failed', 'skipped') THEN now() ELSE completed_at END
         WHERE job_id = %s
        """,
        [status, status, job_id],
    )


def update_semantic_propagation_job_result(
    settings: Settings,
    job_id: str,
    *,
    status: str,
    affected_scope_json: dict[str, Any],
) -> None:
    execute_non_query(
        settings,
        """
        UPDATE public.quantyx_semantic_propagation_jobs
           SET status = %s,
               affected_scope_json = %s::jsonb,
               completed_at = CASE WHEN %s IN ('completed', 'failed', 'partial_completed', 'skipped') THEN now() ELSE completed_at END
         WHERE job_id = %s
        """,
        [status, Json(affected_scope_json or {}), status, job_id],
    )
