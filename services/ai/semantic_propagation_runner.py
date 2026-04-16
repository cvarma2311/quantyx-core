from __future__ import annotations

import logging
from typing import Any

from services.ai.chart_interactions import build_chart_interaction_context
from services.ai.charts_store import update_chart_request
from services.ai.config import Settings
from services.ai.dashboard_refresh_store import (
    append_dashboard_refresh_event,
    create_dashboard_refresh_run,
)
from services.ai.db import execute_non_query, run_query
from services.ai.domain_semantic_state_builder import rebuild_semantic_state
from services.ai.hierarchy_store import list_business_hierarchies, upsert_business_hierarchies
from services.ai.jobs_store import create_job
from services.ai.metrics_registry import upsert_metric
from services.ai.semantic_runtime import (
    load_active_semantic_state,
    persist_semantic_glossary_terms,
    semantic_interpretation_context,
    semantic_join_constraints,
)
from services.ai.semantic_propagation_store import (
    get_semantic_propagation_job,
    update_semantic_propagation_job_result,
    update_semantic_propagation_job_status,
)

logger = logging.getLogger(__name__)

DEFERRED_ACTIONS = {
    "refresh_chart_labels",
}


def _scope_list(scope: dict[str, Any], key: str) -> list[str]:
    value = scope.get(key) or []
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item or "").strip()]


def _value_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _chart_matches_scope(chart: dict[str, Any], scope: dict[str, Any]) -> bool:
    affected_columns = {item.lower() for item in _scope_list(scope, "affected_columns")}
    affected_metrics = {item.lower() for item in _scope_list(scope, "affected_metrics")}
    affected_tables = {item.lower() for item in _scope_list(scope, "affected_tables")}
    if not (affected_columns or affected_metrics or affected_tables):
        return True

    query_payload = chart.get("query_payload") or {}
    if not isinstance(query_payload, dict):
        query_payload = {}
    dimensions = {
        str(item).lower()
        for item in [
            *_value_list(query_payload.get("dimensions")),
            *_value_list(query_payload.get("source_dimensions")),
            query_payload.get("time_dimension"),
            query_payload.get("time_column"),
        ]
        if str(item or "").strip()
    }
    metrics = {
        str(item).lower()
        for item in [
            *_value_list(query_payload.get("metrics")),
            query_payload.get("metric_name"),
            query_payload.get("metric"),
        ]
        if str(item or "").strip()
    }
    tables = {
        str(item).lower()
        for item in [
            query_payload.get("table"),
            query_payload.get("base_table"),
            query_payload.get("fact_table"),
            query_payload.get("dataset_id"),
        ]
        if str(item or "").strip()
    }
    return bool((affected_columns & dimensions) or (affected_metrics & metrics) or (affected_tables & tables))


def _load_domain_charts(
    settings: Settings,
    *,
    tenant_id: str,
    domain_id: str,
    limit: int = 500,
) -> list[dict[str, Any]]:
    try:
        return run_query(
            settings,
            """
            SELECT chart_id, tenant_id, domain_id, run_id, question, query_payload, sql, params,
                   rows_json, chart_type, chart_payload, chart_data, status, error_message,
                   interaction_context_json, lineage_json, parent_chart_id, root_chart_id,
                   drill_hierarchy_id, drill_level_id, title, updated_at
              FROM public.quantyx_chart_requests
             WHERE tenant_id = %s
               AND domain_id IS NOT DISTINCT FROM %s
             ORDER BY updated_at DESC
             LIMIT %s
            """,
            [tenant_id, domain_id, max(1, min(limit, 1000))],
        )
    except Exception:
        logger.warning("semantic_propagation.load_domain_charts_failed", exc_info=True)
        return []


def _load_refinement_artifacts_for_scope(
    settings: Settings,
    *,
    tenant_id: str,
    domain_id: str,
    scope: dict[str, Any],
) -> list[dict[str, Any]]:
    artifact_ids = _scope_list(scope, "artifact_ids")
    if not artifact_ids:
        return []
    try:
        return run_query(
            settings,
            """
            SELECT *
              FROM public.quantyx_domain_refinement_artifacts
             WHERE tenant_id = %s
               AND domain_id = %s
               AND artifact_id = ANY(%s)
               AND validation_status = 'valid'
               AND approval_status IN ('approved', 'auto_approved')
             ORDER BY created_at ASC
            """,
            [tenant_id, domain_id, artifact_ids],
        )
    except Exception:
        logger.warning("semantic_propagation.load_refinement_artifacts_failed", exc_info=True)
        return []


def _existing_current_hierarchy_override_version(
    settings: Settings,
    *,
    tenant_id: str,
    domain_id: str,
    connection_id: str | None,
    database_name: str | None,
    schema_name: str | None,
    artifact_key: str,
) -> tuple[int, str | None]:
    rows = run_query(
        settings,
        """
        SELECT version_no, hierarchy_name
          FROM public.quantyx_hierarchy_overrides
         WHERE tenant_id = %s
           AND domain_id = %s
           AND connection_id IS NOT DISTINCT FROM %s
           AND database_name IS NOT DISTINCT FROM %s
           AND schema_name IS NOT DISTINCT FROM %s
           AND artifact_key = %s
           AND COALESCE(is_current, true) = true
         ORDER BY version_no DESC, updated_at DESC
         LIMIT 1
        """,
        [tenant_id, domain_id, connection_id, database_name, schema_name, artifact_key],
    )
    if not rows:
        return 0, None
    return int(rows[0].get("version_no") or 1), rows[0].get("hierarchy_name")


def _persist_hierarchy_override_from_artifact(
    settings: Settings,
    *,
    job: dict[str, Any],
    artifact: dict[str, Any],
) -> dict[str, Any]:
    payload = artifact.get("artifact_json") or {}
    if not isinstance(payload, dict):
        payload = {}
    levels = [str(level).strip() for level in (payload.get("levels") or []) if str(level or "").strip()]
    if len(levels) < 2:
        return {"artifact_id": artifact.get("artifact_id"), "status": "skipped", "reason": "hierarchy requires at least two levels"}

    tenant_id = str(job.get("tenant_id") or "")
    domain_id = str(job.get("domain_id") or "")
    connection_id = job.get("connection_id")
    database_name = job.get("database_name")
    schema_name = job.get("schema_name")
    artifact_id = str(artifact.get("artifact_id") or "")
    base_name = str(payload.get("name") or "refined_hierarchy").strip().lower().replace(" ", "_")
    context_id = str(payload.get("source_context_id") or artifact.get("refinement_input_id") or "refinement").strip()
    artifact_key = str(payload.get("artifact_key") or f"refinement::{base_name}").strip()

    previous_version, _ = _existing_current_hierarchy_override_version(
        settings,
        tenant_id=tenant_id,
        domain_id=domain_id,
        connection_id=connection_id,
        database_name=database_name,
        schema_name=schema_name,
        artifact_key=artifact_key,
    )
    if previous_version:
        execute_non_query(
            settings,
            """
            UPDATE public.quantyx_hierarchy_overrides
               SET is_current = false,
                   updated_at = now()
             WHERE tenant_id = %s
               AND domain_id = %s
               AND connection_id IS NOT DISTINCT FROM %s
               AND database_name IS NOT DISTINCT FROM %s
               AND schema_name IS NOT DISTINCT FROM %s
               AND artifact_key = %s
               AND COALESCE(is_current, true) = true
            """,
            [tenant_id, domain_id, connection_id, database_name, schema_name, artifact_key],
        )
    version_no = previous_version + 1
    hierarchy_name = artifact_key if version_no == 1 else f"{artifact_key}__v{version_no}"
    execute_non_query(
        settings,
        """
        INSERT INTO public.quantyx_hierarchy_overrides (
          tenant_id, domain_id, connection_id, database_name, schema_name, context_id,
          hierarchy_name, hierarchy_group, levels, description, source_context_id,
          artifact_key, version_no, lifecycle_status, source_type, source_run_id,
          change_reason, approved_by, approved_at, supersedes_version_no,
          created_by, updated_by, is_current, created_at, updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                COALESCE(%s, now()), %s, %s, %s, true, now(), now())
        """,
        [
            tenant_id,
            domain_id,
            connection_id,
            database_name,
            schema_name,
            context_id,
            hierarchy_name,
            payload.get("hierarchy_group") or payload.get("group") or "refinement",
            levels,
            payload.get("description") or payload.get("source_text") or "Approved semantic refinement hierarchy",
            payload.get("source_context_id") or context_id,
            artifact_key,
            version_no,
            "live",
            "refinement",
            artifact_id,
            f"Semantic refinement artifact {artifact_id}",
            artifact.get("approved_by") or "system:auto_approve",
            artifact.get("approved_at"),
            previous_version or None,
            artifact.get("approved_by") or "system:auto_approve",
            "system:semantic_propagation",
        ],
    )

    level_rows = [
        {
            "level_id": level,
            "column": level,
            "label": level.replace("_", " ").title(),
            **({"table": payload.get("table")} if payload.get("table") else {}),
        }
        for level in levels
    ]
    upsert_business_hierarchies(
        settings,
        [
            {
                "hierarchy_id": f"refinement_{domain_id}_{base_name}",
                "tenant_id": tenant_id,
                "domain_id": domain_id,
                "name": str(payload.get("name") or base_name.replace("_", " ").title()),
                "description": payload.get("description") or payload.get("source_text") or "Approved semantic refinement hierarchy",
                "base_scope_json": {
                    "connection_id": connection_id,
                    "database_name": database_name,
                    "schema_name": schema_name,
                    **({"base_table": payload.get("table")} if payload.get("table") else {}),
                },
                "levels_json": level_rows,
                "join_path_json": [],
                "preferred": bool(payload.get("preferred", True)),
                "confidence_score": float(payload.get("confidence_score") or 0.98),
                "provenance_json": {
                    "source": "semantic_refinement",
                    "artifact_id": artifact_id,
                    "artifact_key": artifact_key,
                    "refinement_input_id": artifact.get("refinement_input_id"),
                },
                "validation_status": "approved",
            }
        ],
    )
    return {
        "artifact_id": artifact_id,
        "status": "applied",
        "hierarchy_name": hierarchy_name,
        "artifact_key": artifact_key,
        "version_no": version_no,
        "levels": levels,
    }


def _refresh_hierarchies(
    settings: Settings,
    *,
    tenant_id: str,
    domain_id: str,
    job: dict[str, Any],
    scope: dict[str, Any],
) -> dict[str, Any]:
    artifacts = [
        artifact
        for artifact in _load_refinement_artifacts_for_scope(settings, tenant_id=tenant_id, domain_id=domain_id, scope=scope)
        if artifact.get("artifact_type") == "hierarchy_override"
    ]
    applied: list[dict[str, Any]] = []
    failed: list[dict[str, str]] = []
    for artifact in artifacts:
        try:
            applied.append(_persist_hierarchy_override_from_artifact(settings, job=job, artifact=artifact))
        except Exception as exc:
            logger.warning("semantic_propagation.hierarchy_apply_failed | artifact_id=%s", artifact.get("artifact_id"), exc_info=True)
            failed.append({"artifact_id": str(artifact.get("artifact_id") or ""), "error": str(exc)})
    return {
        "action": "refresh_hierarchies",
        "status": "completed" if not failed else "partial_completed",
        "matched_artifact_count": len(artifacts),
        "applied": applied,
        "failed": failed,
    }


def _current_metric_for_refinement(
    settings: Settings,
    *,
    tenant_id: str,
    domain_id: str,
    connection_id: str | None,
    database_name: str | None,
    schema_name: str | None,
    metric_name: str | None,
    metric_id: str | None,
) -> dict[str, Any] | None:
    if not (metric_name or metric_id):
        return None
    rows = run_query(
        settings,
        """
        SELECT *
          FROM public.quantyx_metrics_registry
         WHERE tenant_id = %s
           AND domain_id = %s
           AND connection_id IS NOT DISTINCT FROM %s
           AND database_name IS NOT DISTINCT FROM %s
           AND schema_name IS NOT DISTINCT FROM %s
           AND COALESCE(is_current, true) = true
           AND (
                (%s IS NOT NULL AND metric_name = %s)
             OR (%s IS NOT NULL AND metric_id = %s)
             OR (%s IS NOT NULL AND artifact_key = %s)
           )
         ORDER BY updated_at DESC
         LIMIT 1
        """,
        [
            tenant_id,
            domain_id,
            connection_id,
            database_name,
            schema_name,
            metric_name,
            metric_name,
            metric_id,
            metric_id,
            metric_id,
            metric_id,
        ],
    )
    return rows[0] if rows else None


def _metric_payload_from_refinement(
    *,
    job: dict[str, Any],
    artifact: dict[str, Any],
    current_metric: dict[str, Any] | None,
) -> dict[str, Any]:
    payload = artifact.get("artifact_json") or {}
    if not isinstance(payload, dict):
        payload = {}
    tenant_id = str(job.get("tenant_id") or artifact.get("tenant_id") or "")
    domain_id = str(job.get("domain_id") or artifact.get("domain_id") or "")
    metric_name = str(payload.get("metric_name") or (current_metric or {}).get("metric_name") or "").strip()
    artifact_key = str(
        (current_metric or {}).get("artifact_key")
        or payload.get("artifact_key")
        or payload.get("metric_id")
        or f"{domain_id}__{metric_name}"
    ).strip()
    formula_sql = payload.get("formula_sql") or payload.get("sql")
    semantic_metadata = {
        **(((current_metric or {}).get("semantic_metadata") or {}) if isinstance((current_metric or {}).get("semantic_metadata"), dict) else {}),
        "refinement_artifact_id": artifact.get("artifact_id"),
        "refinement_input_id": artifact.get("refinement_input_id"),
        "refinement_formula": payload.get("formula"),
        "refinement_metric_role": payload.get("metric_role"),
        "refinement_requires_filter_rule": payload.get("requires_filter_rule"),
        "refinement_source_text": payload.get("source_text"),
    }
    semantic_metadata = {key: value for key, value in semantic_metadata.items() if value not in (None, "", [])}
    return {
        "metric_id": artifact_key,
        "artifact_key": artifact_key,
        "tenant_id": tenant_id,
        "domain_id": domain_id,
        "connection_id": job.get("connection_id") or (current_metric or {}).get("connection_id"),
        "database": job.get("database_name") or (current_metric or {}).get("database_name"),
        "schema": job.get("schema_name") or (current_metric or {}).get("schema_name"),
        "metric_name": metric_name,
        "display_name": payload.get("display_name") or (current_metric or {}).get("display_name") or metric_name.replace("_", " ").title(),
        "description": payload.get("description") or (current_metric or {}).get("description"),
        "type": payload.get("type") or (current_metric or {}).get("type"),
        "unit": payload.get("unit") or (current_metric or {}).get("unit"),
        "confidence": payload.get("confidence") or (current_metric or {}).get("confidence"),
        "additive": payload.get("additive") if "additive" in payload else (current_metric or {}).get("additive"),
        "grain": payload.get("grain") or (current_metric or {}).get("grain"),
        "dimensions": payload.get("dimensions") or (current_metric or {}).get("dimensions"),
        "dataset_id": payload.get("dataset_id") or payload.get("table") or (current_metric or {}).get("dataset_id"),
        "source_model": payload.get("source_model") or payload.get("table") or (current_metric or {}).get("source_model"),
        "source_schema": payload.get("source_schema") or job.get("schema_name") or (current_metric or {}).get("source_schema"),
        "sql": formula_sql if formula_sql else (current_metric or {}).get("sql"),
        "lifecycle_status": payload.get("lifecycle_status") or "active",
        "source_type": "refinement",
        "source_run_id": artifact.get("artifact_id"),
        "change_reason": payload.get("change_reason") or f"Semantic refinement artifact {artifact.get('artifact_id')}",
        "approved_by": artifact.get("approved_by") or "system:auto_approve",
        "approved_at": artifact.get("approved_at"),
        "created_by": artifact.get("approved_by") or "system:auto_approve",
        "updated_by": "system:semantic_propagation",
        "owner": payload.get("owner") or (current_metric or {}).get("owner"),
        "version": payload.get("version") or (current_metric or {}).get("version"),
        "semantic_metadata": semantic_metadata,
    }


def _refresh_metrics(
    settings: Settings,
    *,
    tenant_id: str,
    domain_id: str,
    job: dict[str, Any],
    scope: dict[str, Any],
) -> dict[str, Any]:
    artifacts = [
        artifact
        for artifact in _load_refinement_artifacts_for_scope(settings, tenant_id=tenant_id, domain_id=domain_id, scope=scope)
        if artifact.get("artifact_type") == "metric_refinement"
    ]
    applied: list[dict[str, Any]] = []
    failed: list[dict[str, str]] = []
    for artifact in artifacts:
        try:
            payload = artifact.get("artifact_json") or {}
            if not isinstance(payload, dict):
                payload = {}
            metric_name = str(payload.get("metric_name") or "").strip() or None
            metric_id = str(payload.get("metric_id") or "").strip() or None
            current_metric = _current_metric_for_refinement(
                settings,
                tenant_id=tenant_id,
                domain_id=domain_id,
                connection_id=job.get("connection_id"),
                database_name=job.get("database_name"),
                schema_name=job.get("schema_name"),
                metric_name=metric_name,
                metric_id=metric_id,
            )
            metric_payload = _metric_payload_from_refinement(job=job, artifact=artifact, current_metric=current_metric)
            if not metric_payload.get("metric_name"):
                applied.append({"artifact_id": artifact.get("artifact_id"), "status": "skipped", "reason": "metric_name is missing"})
                continue
            new_metric_id = upsert_metric(settings, metric_payload)
            applied.append(
                {
                    "artifact_id": artifact.get("artifact_id"),
                    "status": "applied",
                    "metric_id": new_metric_id,
                    "metric_name": metric_payload.get("metric_name"),
                    "artifact_key": metric_payload.get("artifact_key"),
                    "updated_existing": bool(current_metric),
                }
            )
        except Exception as exc:
            logger.warning("semantic_propagation.metric_apply_failed | artifact_id=%s", artifact.get("artifact_id"), exc_info=True)
            failed.append({"artifact_id": str(artifact.get("artifact_id") or ""), "error": str(exc)})
    return {
        "action": "refresh_metrics",
        "status": "completed" if not failed else "partial_completed",
        "matched_artifact_count": len(artifacts),
        "applied": applied,
        "failed": failed,
    }


def _refresh_chart_interaction_metadata(
    settings: Settings,
    *,
    tenant_id: str,
    domain_id: str,
    scope: dict[str, Any],
) -> dict[str, Any]:
    charts = [chart for chart in _load_domain_charts(settings, tenant_id=tenant_id, domain_id=domain_id) if _chart_matches_scope(chart, scope)]
    hierarchies = list_business_hierarchies(settings, tenant_id, domain_id)
    refreshed: list[str] = []
    failed: list[dict[str, str]] = []
    for chart in charts:
        chart_id = str(chart.get("chart_id") or "")
        if not chart_id:
            continue
        try:
            interaction_context = build_chart_interaction_context(chart_row=chart, hierarchies=hierarchies)
            update_chart_request(settings, chart_id, interaction_context_json=interaction_context)
            refreshed.append(chart_id)
        except Exception as exc:
            logger.warning("semantic_propagation.chart_interaction_refresh_failed | chart_id=%s", chart_id, exc_info=True)
            failed.append({"chart_id": chart_id, "error": str(exc)})
    return {
        "action": "refresh_chart_interaction_metadata",
        "status": "completed" if not failed else "partial_completed",
        "matched_chart_count": len(charts),
        "refreshed_chart_ids": refreshed,
        "failed": failed,
    }


def _load_affected_dashboard_ids(
    settings: Settings,
    *,
    tenant_id: str,
    domain_id: str,
    scope: dict[str, Any],
    limit: int = 100,
) -> list[str]:
    has_specific_scope = bool(
        _scope_list(scope, "affected_columns")
        or _scope_list(scope, "affected_metrics")
        or _scope_list(scope, "affected_tables")
    )
    charts = [chart for chart in _load_domain_charts(settings, tenant_id=tenant_id, domain_id=domain_id) if _chart_matches_scope(chart, scope)]
    chart_ids = [str(chart.get("chart_id")) for chart in charts if chart.get("chart_id")]
    if has_specific_scope and not chart_ids:
        return []
    try:
        if chart_ids:
            rows = run_query(
                settings,
                """
                SELECT DISTINCT d.dashboard_id
                  FROM public.quantyx_dashboards d
                  JOIN public.quantyx_dashboard_charts dc ON dc.dashboard_id = d.dashboard_id
                 WHERE d.tenant_id = %s
                   AND d.domain_id IS NOT DISTINCT FROM %s
                   AND dc.chart_id = ANY(%s)
                   AND COALESCE(d.status, 'active') = 'active'
                 ORDER BY d.dashboard_id
                 LIMIT %s
                """,
                [tenant_id, domain_id, chart_ids, max(1, min(limit, 500))],
            )
        else:
            rows = run_query(
                settings,
                """
                SELECT d.dashboard_id
                  FROM public.quantyx_dashboards d
                 WHERE d.tenant_id = %s
                   AND d.domain_id IS NOT DISTINCT FROM %s
                   AND COALESCE(d.status, 'active') = 'active'
                 ORDER BY d.updated_at DESC
                 LIMIT %s
                """,
                [tenant_id, domain_id, max(1, min(limit, 500))],
            )
        return [str(row.get("dashboard_id")) for row in rows if row.get("dashboard_id")]
    except Exception:
        logger.warning("semantic_propagation.load_affected_dashboards_failed", exc_info=True)
        return []


def _queue_dashboard_refreshes(
    settings: Settings,
    *,
    tenant_id: str,
    domain_id: str,
    scope: dict[str, Any],
    propagation_job_id: str,
) -> dict[str, Any]:
    dashboard_ids = _load_affected_dashboard_ids(settings, tenant_id=tenant_id, domain_id=domain_id, scope=scope)
    queued: list[dict[str, str | None]] = []
    failed: list[dict[str, str]] = []
    for dashboard_id in dashboard_ids:
        try:
            refresh_id = create_dashboard_refresh_run(
                settings,
                dashboard_id=dashboard_id,
                tenant_id=tenant_id,
                domain_id=domain_id,
                trigger_source="semantic_propagation",
                requested_by="system:semantic_propagation",
                request_payload={
                    "semantic_propagation_job_id": propagation_job_id,
                    "affected_scope": scope,
                },
            )
            append_dashboard_refresh_event(
                settings,
                refresh_id=refresh_id,
                dashboard_id=dashboard_id,
                stage_name="queued",
                message="Dashboard refresh queued by semantic propagation",
                artifacts={"semantic_propagation_job_id": propagation_job_id},
            )
            job = create_job(
                settings,
                tenant_id=tenant_id,
                domain_id=domain_id,
                job_type="dashboard_refresh",
                payload={"refresh_id": refresh_id, "dashboard_id": dashboard_id},
                idempotency_key=f"semantic_propagation:{propagation_job_id}:{dashboard_id}",
            )
            queued.append({"dashboard_id": dashboard_id, "refresh_id": refresh_id, "job_id": job.get("job_id")})
        except Exception as exc:
            logger.warning("semantic_propagation.dashboard_refresh_queue_failed | dashboard_id=%s", dashboard_id, exc_info=True)
            failed.append({"dashboard_id": dashboard_id, "error": str(exc)})
    return {
        "action": "refresh_affected_dashboards",
        "status": "completed" if not failed else "partial_completed",
        "matched_dashboard_count": len(dashboard_ids),
        "queued": queued,
        "failed": failed,
    }


def _refresh_semantic_state(
    settings: Settings,
    *,
    tenant_id: str,
    domain_id: str,
    job: dict[str, Any],
) -> dict[str, Any]:
    result = rebuild_semantic_state(
        settings,
        tenant_id=tenant_id,
        domain_id=domain_id,
        connection_id=job.get("connection_id"),
        database_name=job.get("database_name"),
        schema_name=job.get("schema_name"),
        trigger_type="semantic_propagation_runner",
    )
    return {
        "action": "refresh_semantic_state",
        "status": "completed",
        "semantic_state_id": result.get("semantic_state_id"),
    }


def _refresh_query_planner_constraints(
    settings: Settings,
    *,
    tenant_id: str,
    domain_id: str,
    job: dict[str, Any],
) -> dict[str, Any]:
    state = load_active_semantic_state(
        settings,
        tenant_id=tenant_id,
        domain_id=domain_id,
        connection_id=job.get("connection_id"),
        database_name=job.get("database_name"),
        schema_name=job.get("schema_name"),
    )
    constraints = semantic_join_constraints(state)
    return {
        "action": "refresh_query_planner_constraints",
        "status": "completed",
        "mode": "active_semantic_state_read_through",
        "restricted_join_pair_count": len(constraints.get("restricted_join_pairs") or []),
        "excluded_table_count": len(constraints.get("excluded_tables") or []),
        "default_filter_count": len(constraints.get("default_filters") or []),
    }


def _refresh_workspace_semantics(
    settings: Settings,
    *,
    tenant_id: str,
    domain_id: str,
    job: dict[str, Any],
) -> dict[str, Any]:
    state = load_active_semantic_state(
        settings,
        tenant_id=tenant_id,
        domain_id=domain_id,
        connection_id=job.get("connection_id"),
        database_name=job.get("database_name"),
        schema_name=job.get("schema_name"),
    )
    return {
        "action": "refresh_workspace_semantics",
        "status": "completed",
        "mode": "active_semantic_state_read_through",
        "approved_refinement_artifact_count": ((state.get("summary") or {}).get("approved_refinement_artifact_count") or 0),
    }


def _refresh_glossary(
    settings: Settings,
    *,
    tenant_id: str,
    domain_id: str,
    job: dict[str, Any],
) -> dict[str, Any]:
    state = load_active_semantic_state(
        settings,
        tenant_id=tenant_id,
        domain_id=domain_id,
        connection_id=job.get("connection_id"),
        database_name=job.get("database_name"),
        schema_name=job.get("schema_name"),
    )
    applied_count = persist_semantic_glossary_terms(settings, tenant_id=tenant_id, domain_id=domain_id, state_json=state)
    return {
        "action": "refresh_glossary",
        "status": "completed",
        "applied_term_count": applied_count,
    }


def _refresh_anomaly_correlation_context(
    settings: Settings,
    *,
    tenant_id: str,
    domain_id: str,
    job: dict[str, Any],
) -> dict[str, Any]:
    state = load_active_semantic_state(
        settings,
        tenant_id=tenant_id,
        domain_id=domain_id,
        connection_id=job.get("connection_id"),
        database_name=job.get("database_name"),
        schema_name=job.get("schema_name"),
    )
    context = semantic_interpretation_context(state)
    return {
        "action": "refresh_anomaly_correlation_context",
        "status": "completed",
        "mode": "active_semantic_state_read_through",
        "interpretation_rule_count": len(context.get("interpretation_rules") or []),
        "metric_refinement_count": len(context.get("metric_refinements") or []),
        "chart_guidance_count": len(context.get("chart_guidance") or []),
    }


def _deferred_action(action: str) -> dict[str, str]:
    return {
        "action": action,
        "status": "deferred",
        "reason": "no direct runtime refresh runner is implemented for this action yet",
    }


def run_semantic_propagation_job(settings: Settings, job_id: str, *, tenant_id: str) -> dict[str, Any]:
    job = get_semantic_propagation_job(settings, job_id, tenant_id=tenant_id)
    if not job:
        raise ValueError("semantic propagation job not found")
    domain_id = str(job.get("domain_id") or "")
    scope = job.get("affected_scope_json") or {}
    if not isinstance(scope, dict):
        scope = {}
    actions = _scope_list(scope, "refresh_actions") or ["refresh_semantic_state"]

    update_semantic_propagation_job_status(settings, job_id, status="running")
    action_results: list[dict[str, Any]] = []
    try:
        for action in actions:
            if action == "refresh_semantic_state":
                action_results.append(_refresh_semantic_state(settings, tenant_id=tenant_id, domain_id=domain_id, job=job))
            elif action == "refresh_hierarchies":
                action_results.append(_refresh_hierarchies(settings, tenant_id=tenant_id, domain_id=domain_id, job=job, scope=scope))
            elif action == "refresh_metrics":
                action_results.append(_refresh_metrics(settings, tenant_id=tenant_id, domain_id=domain_id, job=job, scope=scope))
            elif action == "refresh_chart_interaction_metadata":
                action_results.append(
                    _refresh_chart_interaction_metadata(settings, tenant_id=tenant_id, domain_id=domain_id, scope=scope)
                )
            elif action == "refresh_affected_dashboards":
                action_results.append(
                    _queue_dashboard_refreshes(
                        settings,
                        tenant_id=tenant_id,
                        domain_id=domain_id,
                        scope=scope,
                        propagation_job_id=job_id,
                    )
                )
            elif action == "refresh_query_planner_constraints":
                action_results.append(_refresh_query_planner_constraints(settings, tenant_id=tenant_id, domain_id=domain_id, job=job))
            elif action == "refresh_workspace_semantics":
                action_results.append(_refresh_workspace_semantics(settings, tenant_id=tenant_id, domain_id=domain_id, job=job))
            elif action in {"refresh_glossary", "refresh_chart_labels"}:
                action_results.append(_refresh_glossary(settings, tenant_id=tenant_id, domain_id=domain_id, job=job))
            elif action == "refresh_anomaly_correlation_context":
                action_results.append(_refresh_anomaly_correlation_context(settings, tenant_id=tenant_id, domain_id=domain_id, job=job))
            elif action in DEFERRED_ACTIONS:
                action_results.append(_deferred_action(action))
            else:
                action_results.append({"action": action, "status": "skipped", "reason": "unknown propagation action"})

        terminal_statuses = {str(item.get("status")) for item in action_results}
        if terminal_statuses <= {"completed", "deferred", "skipped"}:
            status = "completed"
        elif "completed" in terminal_statuses or "partial_completed" in terminal_statuses:
            status = "partial_completed"
        else:
            status = "failed"
        result_scope = {**scope, "action_results": action_results}
        update_semantic_propagation_job_result(settings, job_id, status=status, affected_scope_json=result_scope)
        return {**job, "status": status, "affected_scope_json": result_scope}
    except Exception as exc:
        result_scope = {**scope, "action_results": [*action_results, {"action": "runner", "status": "failed", "error": str(exc)}]}
        update_semantic_propagation_job_result(settings, job_id, status="failed", affected_scope_json=result_scope)
        raise
