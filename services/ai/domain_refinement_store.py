from __future__ import annotations

from typing import Any
from uuid import uuid4

from psycopg2.extras import Json

from services.ai.config import Settings
from services.ai.db import execute_non_query, run_query


APPROVED_STATUSES = ("approved", "auto_approved")


def create_refinement_input(
    settings: Settings,
    *,
    tenant_id: str,
    domain_id: str,
    source_type: str,
    refinement_kind: str,
    source_text: str | None = None,
    source_payload_json: dict[str, Any] | None = None,
    connection_id: str | None = None,
    database_name: str | None = None,
    schema_name: str | None = None,
    source_run_id: str | None = None,
    source_context_id: str | None = None,
    source_file_id: str | None = None,
    conversation_id: str | None = None,
    submitted_by: str | None = None,
    status: str = "submitted",
) -> str:
    refinement_input_id = f"ref_{uuid4().hex[:12]}"
    execute_non_query(
        settings,
        """
        INSERT INTO public.quantyx_domain_refinement_inputs (
          refinement_input_id, tenant_id, domain_id, connection_id, database_name, schema_name,
          source_run_id, source_type, refinement_kind, source_text, source_payload_json,
          source_context_id, source_file_id, conversation_id, submitted_by, status,
          created_at, updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, now(), now())
        """,
        [
            refinement_input_id,
            tenant_id,
            domain_id,
            connection_id,
            database_name,
            schema_name,
            source_run_id,
            source_type,
            refinement_kind,
            source_text,
            Json(source_payload_json or {}) if source_payload_json is not None else None,
            source_context_id,
            source_file_id,
            conversation_id,
            submitted_by,
            status,
        ],
    )
    return refinement_input_id


def update_refinement_input_status(settings: Settings, refinement_input_id: str, status: str) -> None:
    execute_non_query(
        settings,
        """
        UPDATE public.quantyx_domain_refinement_inputs
           SET status = %s,
               updated_at = now()
         WHERE refinement_input_id = %s
        """,
        [status, refinement_input_id],
    )


def get_refinement_input(settings: Settings, refinement_input_id: str) -> dict[str, Any] | None:
    rows = run_query(
        settings,
        """
        SELECT *
          FROM public.quantyx_domain_refinement_inputs
         WHERE refinement_input_id = %s
         LIMIT 1
        """,
        [refinement_input_id],
    )
    return rows[0] if rows else None


def list_refinement_inputs(
    settings: Settings,
    *,
    tenant_id: str,
    domain_id: str | None = None,
    connection_id: str | None = None,
    database_name: str | None = None,
    schema_name: str | None = None,
    status: str | None = None,
    refinement_kind: str | None = None,
    submitted_by: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    filters = ["tenant_id = %s"]
    params: list[Any] = [tenant_id]
    if domain_id:
        filters.append("domain_id = %s")
        params.append(domain_id)
    if connection_id:
        filters.append("connection_id = %s")
        params.append(connection_id)
    if database_name:
        filters.append("database_name = %s")
        params.append(database_name)
    if schema_name:
        filters.append("schema_name = %s")
        params.append(schema_name)
    if status:
        filters.append("status = %s")
        params.append(status)
    if refinement_kind:
        filters.append("refinement_kind = %s")
        params.append(refinement_kind)
    if submitted_by:
        filters.append("submitted_by = %s")
        params.append(submitted_by)
    params.append(max(1, min(int(limit or 100), 500)))
    return run_query(
        settings,
        f"""
        SELECT *
          FROM public.quantyx_domain_refinement_inputs
         WHERE {' AND '.join(filters)}
         ORDER BY created_at DESC
         LIMIT %s
        """,
        params,
    )


def create_refinement_artifact(
    settings: Settings,
    *,
    refinement_input_id: str,
    tenant_id: str,
    domain_id: str,
    artifact_type: str,
    artifact_json: dict[str, Any],
    connection_id: str | None = None,
    database_name: str | None = None,
    schema_name: str | None = None,
    validation_status: str = "pending",
    validation_errors_json: list[dict[str, Any]] | None = None,
    approval_status: str = "pending",
    approved_by: str | None = None,
) -> str:
    artifact_id = f"ref_art_{uuid4().hex[:12]}"
    execute_non_query(
        settings,
        """
        INSERT INTO public.quantyx_domain_refinement_artifacts (
          artifact_id, refinement_input_id, tenant_id, domain_id, connection_id, database_name, schema_name,
          artifact_type, artifact_json, validation_status, validation_errors_json,
          approval_status, approved_by, approved_at, created_at, updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s::jsonb, %s, %s,
                CASE WHEN %s IN ('approved', 'auto_approved') THEN now() ELSE NULL END, now(), now())
        """,
        [
            artifact_id,
            refinement_input_id,
            tenant_id,
            domain_id,
            connection_id,
            database_name,
            schema_name,
            artifact_type,
            Json(artifact_json),
            validation_status,
            Json(validation_errors_json or []),
            approval_status,
            approved_by,
            approval_status,
        ],
    )
    return artifact_id


def list_refinement_artifacts(
    settings: Settings,
    *,
    tenant_id: str,
    domain_id: str | None = None,
    refinement_input_id: str | None = None,
    connection_id: str | None = None,
    database_name: str | None = None,
    schema_name: str | None = None,
    approval_status: str | None = None,
    validation_status: str | None = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    filters = ["tenant_id = %s"]
    params: list[Any] = [tenant_id]
    if domain_id:
        filters.append("domain_id = %s")
        params.append(domain_id)
    if refinement_input_id:
        filters.append("refinement_input_id = %s")
        params.append(refinement_input_id)
    if connection_id:
        filters.append("connection_id = %s")
        params.append(connection_id)
    if database_name:
        filters.append("database_name = %s")
        params.append(database_name)
    if schema_name:
        filters.append("schema_name = %s")
        params.append(schema_name)
    if approval_status:
        filters.append("approval_status = %s")
        params.append(approval_status)
    if validation_status:
        filters.append("validation_status = %s")
        params.append(validation_status)
    params.append(max(1, min(int(limit or 500), 1000)))
    return run_query(
        settings,
        f"""
        SELECT *
          FROM public.quantyx_domain_refinement_artifacts
         WHERE {' AND '.join(filters)}
         ORDER BY created_at DESC
         LIMIT %s
        """,
        params,
    )


def list_approved_refinement_artifacts(
    settings: Settings,
    *,
    tenant_id: str,
    domain_id: str,
    connection_id: str | None = None,
    database_name: str | None = None,
    schema_name: str | None = None,
) -> list[dict[str, Any]]:
    filters = [
        "tenant_id = %s",
        "domain_id = %s",
        "approval_status = ANY(%s)",
        "validation_status = 'valid'",
    ]
    params: list[Any] = [tenant_id, domain_id, list(APPROVED_STATUSES)]
    if connection_id:
        filters.append("connection_id IS NOT DISTINCT FROM %s")
        params.append(connection_id)
    if database_name:
        filters.append("database_name IS NOT DISTINCT FROM %s")
        params.append(database_name)
    if schema_name:
        filters.append("schema_name IS NOT DISTINCT FROM %s")
        params.append(schema_name)
    return run_query(
        settings,
        f"""
        SELECT *
          FROM public.quantyx_domain_refinement_artifacts
         WHERE {' AND '.join(filters)}
         ORDER BY created_at ASC
        """,
        params,
    )


def get_current_semantic_state(
    settings: Settings,
    *,
    tenant_id: str,
    domain_id: str,
    connection_id: str | None = None,
    database_name: str | None = None,
    schema_name: str | None = None,
) -> dict[str, Any] | None:
    rows = run_query(
        settings,
        """
        SELECT *
          FROM public.quantyx_domain_semantic_state
         WHERE tenant_id = %s
           AND domain_id = %s
           AND connection_id IS NOT DISTINCT FROM %s
           AND database_name IS NOT DISTINCT FROM %s
           AND schema_name IS NOT DISTINCT FROM %s
           AND is_active = true
         ORDER BY version_no DESC
         LIMIT 1
        """,
        [tenant_id, domain_id, connection_id, database_name, schema_name],
    )
    return rows[0] if rows else None


def persist_semantic_state(
    settings: Settings,
    *,
    tenant_id: str,
    domain_id: str,
    state_json: dict[str, Any],
    created_from_artifact_ids: list[str],
    connection_id: str | None = None,
    database_name: str | None = None,
    schema_name: str | None = None,
    trigger_type: str = "manual",
) -> str:
    current = get_current_semantic_state(
        settings,
        tenant_id=tenant_id,
        domain_id=domain_id,
        connection_id=connection_id,
        database_name=database_name,
        schema_name=schema_name,
    )
    version_no = int((current or {}).get("version_no") or 0) + 1
    semantic_state_id = f"sem_state_{uuid4().hex[:12]}"
    execute_non_query(
        settings,
        """
        UPDATE public.quantyx_domain_semantic_state
           SET is_active = false
         WHERE tenant_id = %s
           AND domain_id = %s
           AND connection_id IS NOT DISTINCT FROM %s
           AND database_name IS NOT DISTINCT FROM %s
           AND schema_name IS NOT DISTINCT FROM %s
           AND is_active = true
        """,
        [tenant_id, domain_id, connection_id, database_name, schema_name],
    )
    execute_non_query(
        settings,
        """
        INSERT INTO public.quantyx_domain_semantic_state (
          semantic_state_id, tenant_id, domain_id, connection_id, database_name, schema_name,
          version_no, state_json, created_from_artifact_ids, trigger_type, is_active, created_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, true, now())
        """,
        [
            semantic_state_id,
            tenant_id,
            domain_id,
            connection_id,
            database_name,
            schema_name,
            version_no,
            Json(state_json),
            Json(created_from_artifact_ids),
            trigger_type,
        ],
    )
    return semantic_state_id
