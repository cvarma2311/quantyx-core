
from __future__ import annotations

import uuid

from fastapi import HTTPException

from services.ai.config import Settings
from services.ai.db import execute_non_query, run_query


def upsert_entity_override(
    settings: Settings,
    tenant_id: str,
    domain_id: str,
    connection_id: str,
    database_name: str,
    schema_name: str,
    payload: dict,
) -> None:
    if not payload.get("entity_id"):
        raise HTTPException(status_code=400, detail="entity_id is required")
    lifecycle_status = payload.get("lifecycle_status") or payload.get("status") or "draft"
    artifact_key = payload.get("artifact_key") or payload["entity_id"]

    current_rows = run_query(
        settings,
        """
        SELECT entity_id, version_no
          FROM public.quantyx_entity_overrides
         WHERE tenant_id = %s
           AND domain_id = %s
           AND connection_id = %s
           AND database_name = %s
           AND schema_name = %s
           AND artifact_key = %s
           AND COALESCE(is_current, true) = true
         LIMIT 1
        """,
        [tenant_id, domain_id, connection_id, database_name, schema_name, artifact_key],
    )
    previous_version = 0
    if current_rows:
        previous_version = int(current_rows[0].get("version_no") or 1)
        execute_non_query(
            settings,
            """
            UPDATE public.quantyx_entity_overrides
               SET is_current = false,
                   updated_at = now()
             WHERE tenant_id = %s
               AND domain_id = %s
               AND connection_id = %s
               AND database_name = %s
               AND schema_name = %s
               AND artifact_key = %s
               AND COALESCE(is_current, true) = true
            """,
            [tenant_id, domain_id, connection_id, database_name, schema_name, artifact_key],
        )
    version_no = previous_version + 1
    execute_non_query(
        settings,
        """
        INSERT INTO public.quantyx_entity_overrides
          (tenant_id, domain_id, connection_id, database_name, schema_name, entity_id, description, join_key, examples,
           artifact_key, version_no, lifecycle_status, source_type, source_run_id, change_reason, approved_by, approved_at,
           source_table, source_column, confidence,
           supersedes_version_no, created_by, updated_by, is_current, created_at, updated_at)
        VALUES
          (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now(), now())
        """,
        [
            tenant_id,
            domain_id,
            connection_id,
            database_name,
            schema_name,
            payload["entity_id"],
            payload.get("description"),
            payload.get("join_key"),
            payload.get("examples"),
            artifact_key,
            version_no,
            lifecycle_status,
            payload.get("source_type", "system"),
            payload.get("source_run_id"),
            payload.get("change_reason"),
            payload.get("approved_by"),
            payload.get("approved_at"),
            payload.get("source_table"),
            payload.get("source_column"),
            payload.get("confidence"),
            payload.get("supersedes_version_no") or (previous_version or None),
            payload.get("created_by"),
            payload.get("updated_by"),
            payload.get("is_current", True),
        ],
    )


def upsert_hierarchy_override(
    settings: Settings,
    tenant_id: str,
    domain_id: str,
    connection_id: str,
    database_name: str,
    schema_name: str,
    payload: dict,
) -> None:
    if not payload.get("hierarchy_name"):
        raise HTTPException(status_code=400, detail="hierarchy_name is required")
    context_id = payload.get("context_id") or payload.get("source_context_id") or "ctx_legacy"
    lifecycle_status = payload.get("lifecycle_status") or payload.get("status") or "draft"
    artifact_key = payload.get("artifact_key") or f"{context_id}::{payload['hierarchy_name']}"

    current_rows = run_query(
        settings,
        """
        SELECT hierarchy_name, version_no
          FROM public.quantyx_hierarchy_overrides
         WHERE tenant_id = %s
           AND domain_id = %s
           AND connection_id = %s
           AND database_name = %s
           AND schema_name = %s
           AND context_id = %s
           AND artifact_key = %s
           AND COALESCE(is_current, true) = true
         LIMIT 1
        """,
        [tenant_id, domain_id, connection_id, database_name, schema_name, context_id, artifact_key],
    )
    previous_version = 0
    if current_rows:
        previous_version = int(current_rows[0].get("version_no") or 1)
        execute_non_query(
            settings,
            """
            UPDATE public.quantyx_hierarchy_overrides
               SET is_current = false,
                   updated_at = now()
             WHERE tenant_id = %s
               AND domain_id = %s
               AND connection_id = %s
               AND database_name = %s
               AND schema_name = %s
               AND context_id = %s
               AND artifact_key = %s
               AND COALESCE(is_current, true) = true
            """,
            [tenant_id, domain_id, connection_id, database_name, schema_name, context_id, artifact_key],
        )
    version_no = previous_version + 1
    row_hierarchy_name = artifact_key if version_no == 1 else f"{artifact_key}__v{version_no}_{uuid.uuid4().hex[:6]}"
    execute_non_query(
        settings,
        """
        INSERT INTO public.quantyx_hierarchy_overrides
          (tenant_id, domain_id, connection_id, database_name, schema_name, context_id, hierarchy_name, hierarchy_group,
           levels, description, source_context_id,
           artifact_key, version_no, lifecycle_status, source_type, source_run_id, change_reason, approved_by, approved_at,
           supersedes_version_no, created_by, updated_by, is_current, created_at, updated_at)
        VALUES
          (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now(), now())
        """,
        [
            tenant_id,
            domain_id,
            connection_id,
            database_name,
            schema_name,
            context_id,
            row_hierarchy_name,
            payload.get("hierarchy_group") or payload.get("group"),
            payload.get("levels", []),
            payload.get("description"),
            payload.get("source_context_id") or context_id,
            artifact_key,
            version_no,
            lifecycle_status,
            payload.get("source_type", "system"),
            payload.get("source_run_id"),
            payload.get("change_reason"),
            payload.get("approved_by"),
            payload.get("approved_at"),
            payload.get("supersedes_version_no") or (previous_version or None),
            payload.get("created_by"),
            payload.get("updated_by"),
            payload.get("is_current", True),
        ],
    )
