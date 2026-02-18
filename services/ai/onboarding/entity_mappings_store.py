from __future__ import annotations

import json
import uuid

import psycopg2

from services.ai.config import Settings
from services.ai.db import execute_non_query, run_query


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
    sql = """
        INSERT INTO public.quantyx_entity_mappings (
          mapping_id,
          tenant_id,
          domain_id,
          connection_id,
          database_name,
          schema_name,
          tables,
          candidates,
          low_confidence_candidates,
          low_confidence_threshold,
          status,
          created_at,
          updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s, %s, now(), now())
    """
    params = [
        mapping_id,
        tenant_id,
        domain_id,
        connection_id,
        database_name,
        schema_name,
        json.dumps(tables),
        json.dumps(candidates),
        json.dumps(low_confidence_candidates),
        low_confidence_threshold,
        status,
    ]
    try:
        execute_non_query(settings, sql, params)
    except psycopg2.errors.UndefinedTable:
        return mapping_id
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
        SELECT mapping_id, tenant_id, domain_id, connection_id, database_name, schema_name,
               tables, candidates, low_confidence_candidates, low_confidence_threshold,
               status, created_at, updated_at
          FROM public.quantyx_entity_mappings
         WHERE tenant_id = %s
           AND domain_id = %s
           AND connection_id = %s
           AND database_name = %s
           AND schema_name = %s
         ORDER BY created_at DESC
         LIMIT %s
    """
    params = [tenant_id, domain_id, connection_id, database_name, schema_name, limit]
    try:
        return run_query(settings, sql, params)
    except psycopg2.errors.UndefinedTable:
        return []


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
        SELECT mapping_id, tenant_id, domain_id, connection_id, database_name, schema_name,
               tables, candidates, low_confidence_candidates, low_confidence_threshold,
               status, created_at, updated_at
          FROM public.quantyx_entity_mappings
         WHERE mapping_id = %s
           AND tenant_id = %s
           AND domain_id = %s
           AND connection_id = %s
           AND database_name = %s
           AND schema_name = %s
         LIMIT 1
    """
    params = [mapping_id, tenant_id, domain_id, connection_id, database_name, schema_name]
    try:
        rows = run_query(settings, sql, params)
    except psycopg2.errors.UndefinedTable:
        return None
    if not rows:
        return None
    return rows[0]


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
    sql = """
        UPDATE public.quantyx_entity_mappings
           SET status = %s,
               updated_at = now()
         WHERE mapping_id = %s
           AND tenant_id = %s
           AND domain_id = %s
           AND connection_id = %s
           AND database_name = %s
           AND schema_name = %s
    """
    params = [status, mapping_id, tenant_id, domain_id, connection_id, database_name, schema_name]
    try:
        execute_non_query(settings, sql, params)
    except psycopg2.errors.UndefinedTable:
        return
