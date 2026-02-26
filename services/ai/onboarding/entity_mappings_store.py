from __future__ import annotations

import uuid

from services.ai.config import Settings
from services.ai.db import run_query
from services.api.overrides_endpoints import upsert_entity_override

LOW_CONFIDENCE_THRESHOLD = 0.7


def persist_entity_mapping(
    settings: Settings,
    tenant_id: str,
    domain_id: str,
    connection_id: str,
    database_name: str,
    schema_name: str,
    tables: list[str],
    candidates: list[dict],
    low_confidence_candidates: list[dict],
    low_confidence_threshold: float,
    status: str = "draft",
) -> str:
    mapping_id = f"map_{uuid.uuid4().hex[:10]}"
    threshold = low_confidence_threshold or LOW_CONFIDENCE_THRESHOLD
    for candidate in candidates + low_confidence_candidates:
        entity_id = str(candidate.get("mapped_entity_type") or candidate.get("entity_id") or "").strip()
        if not entity_id:
            continue
        source_table = candidate.get("table")
        source_column = candidate.get("column") or candidate.get("join_key")
        artifact_key = candidate.get("artifact_key")
        if not artifact_key:
            if source_table and source_column:
                artifact_key = f"{entity_id}::{source_table}.{source_column}"
            elif source_column:
                artifact_key = f"{entity_id}::{source_column}"
            else:
                artifact_key = entity_id
        upsert_entity_override(
            settings,
            tenant_id,
            domain_id,
            connection_id,
            database_name,
            schema_name,
            {
                "entity_id": entity_id,
                "description": candidate.get("description"),
                "join_key": candidate.get("join_key") or candidate.get("column"),
                "examples": candidate.get("examples") or ([candidate.get("column")] if candidate.get("column") else None),
                "artifact_key": artifact_key,
                "lifecycle_status": candidate.get("status") or "suggested",
                "source_type": candidate.get("source") or candidate.get("source_type") or "rule",
                "source_run_id": mapping_id,
                "source_table": source_table,
                "source_column": source_column,
                "confidence": candidate.get("confidence"),
            },
        )
    return mapping_id


def list_entity_mappings(
    settings: Settings,
    tenant_id: str,
    domain_id: str,
    connection_id: str,
    database_name: str,
    schema_name: str,
    limit: int = 20,
) -> list[dict]:
    sql = """
        SELECT source_run_id AS mapping_id,
               tenant_id,
               domain_id,
               connection_id,
               database_name,
               schema_name,
               source_table,
               source_column,
               entity_id,
               description,
               join_key,
               examples,
               source_type,
               confidence,
               lifecycle_status,
               created_at,
               updated_at
          FROM public.quantyx_entity_overrides
         WHERE tenant_id = %s
           AND domain_id = %s
           AND connection_id = %s
           AND database_name = %s
           AND schema_name = %s
           AND source_run_id IS NOT NULL
           AND COALESCE(is_current, true) = true
         ORDER BY created_at DESC
         LIMIT %s
    """
    params = [tenant_id, domain_id, connection_id, database_name, schema_name, limit]
    rows = run_query(settings, sql, params)
    grouped: dict[str, dict] = {}
    for row in rows:
        mapping_id = row.get("mapping_id")
        if not mapping_id:
            continue
        grouped.setdefault(
            mapping_id,
            {
                "mapping_id": mapping_id,
                "tenant_id": row.get("tenant_id"),
                "domain_id": row.get("domain_id"),
                "connection_id": row.get("connection_id"),
                "database_name": row.get("database_name"),
                "schema_name": row.get("schema_name"),
                "tables": [],
                "candidates": [],
                "low_confidence_candidates": [],
                "low_confidence_threshold": LOW_CONFIDENCE_THRESHOLD,
                "status": "draft",
                "created_at": row.get("created_at"),
                "updated_at": row.get("updated_at"),
            },
        )
        candidate = {
            "table": row.get("source_table"),
            "column": row.get("source_column"),
            "mapped_entity_type": row.get("entity_id"),
            "confidence": row.get("confidence"),
            "source": row.get("source_type"),
            "description": row.get("description"),
            "join_key": row.get("join_key"),
            "examples": row.get("examples"),
        }
        table_name = row.get("source_table")
        if table_name and table_name not in grouped[mapping_id]["tables"]:
            grouped[mapping_id]["tables"].append(table_name)
        if row.get("confidence") is not None and float(row.get("confidence")) < LOW_CONFIDENCE_THRESHOLD:
            grouped[mapping_id]["low_confidence_candidates"].append(candidate)
        else:
            grouped[mapping_id]["candidates"].append(candidate)
    return list(grouped.values())


def get_entity_mapping(
    settings: Settings,
    mapping_id: str,
    tenant_id: str,
    domain_id: str,
    connection_id: str,
    database_name: str,
    schema_name: str,
) -> dict | None:
    sql = """
        SELECT source_run_id AS mapping_id,
               tenant_id,
               domain_id,
               connection_id,
               database_name,
               schema_name,
               source_table,
               source_column,
               entity_id,
               description,
               join_key,
               examples,
               source_type,
               confidence,
               lifecycle_status,
               created_at,
               updated_at
          FROM public.quantyx_entity_overrides
         WHERE source_run_id = %s
           AND tenant_id = %s
           AND domain_id = %s
           AND connection_id = %s
           AND database_name = %s
           AND schema_name = %s
           AND COALESCE(is_current, true) = true
         ORDER BY created_at DESC
    """
    params = [mapping_id, tenant_id, domain_id, connection_id, database_name, schema_name]
    rows = run_query(settings, sql, params)
    if not rows:
        return None
    grouped = {
        "mapping_id": mapping_id,
        "tenant_id": tenant_id,
        "domain_id": domain_id,
        "connection_id": connection_id,
        "database_name": database_name,
        "schema_name": schema_name,
        "tables": [],
        "candidates": [],
        "low_confidence_candidates": [],
        "low_confidence_threshold": LOW_CONFIDENCE_THRESHOLD,
        "status": "draft",
        "created_at": rows[0].get("created_at"),
        "updated_at": rows[0].get("updated_at"),
    }
    for row in rows:
        candidate = {
            "table": row.get("source_table"),
            "column": row.get("source_column"),
            "mapped_entity_type": row.get("entity_id"),
            "confidence": row.get("confidence"),
            "source": row.get("source_type"),
            "description": row.get("description"),
            "join_key": row.get("join_key"),
            "examples": row.get("examples"),
        }
        table_name = row.get("source_table")
        if table_name and table_name not in grouped["tables"]:
            grouped["tables"].append(table_name)
        if row.get("confidence") is not None and float(row.get("confidence")) < LOW_CONFIDENCE_THRESHOLD:
            grouped["low_confidence_candidates"].append(candidate)
        else:
            grouped["candidates"].append(candidate)
    return grouped


def update_entity_mapping_status(
    settings: Settings,
    mapping_id: str,
    tenant_id: str,
    domain_id: str,
    connection_id: str,
    database_name: str,
    schema_name: str,
    status: str,
) -> None:
    # Mapping status is derived from entity override lifecycle; no-op for single-table model.
    _ = (settings, mapping_id, tenant_id, domain_id, connection_id, database_name, schema_name, status)
    return
