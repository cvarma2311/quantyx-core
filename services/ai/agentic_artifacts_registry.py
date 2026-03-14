from __future__ import annotations

import uuid
from typing import Any

import psycopg2
from psycopg2.extras import Json

from services.ai.config import Settings
from services.ai.db import execute_non_query, run_query


def persist_schema_graph_artifact(
    settings: Settings,
    *,
    tenant_id: str,
    domain_id: str,
    run_id: str,
    connection_id: str,
    database_name: str,
    schema_name: str,
    schema_graph: dict[str, Any],
) -> str | None:
    artifact_id = f"sg_{uuid.uuid4().hex[:12]}"
    sql = """
        INSERT INTO public.quantyx_schema_graph_artifacts (
          artifact_id, tenant_id, domain_id, run_id, connection_id, database_name, schema_name,
          artifact_key, version_no, is_current, lifecycle_status, source_type, graph_json,
          created_at, updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, now(), now())
        ON CONFLICT (tenant_id, domain_id, run_id, connection_id, database_name, schema_name)
        DO UPDATE SET
          artifact_key = EXCLUDED.artifact_key,
          version_no = EXCLUDED.version_no,
          is_current = EXCLUDED.is_current,
          lifecycle_status = EXCLUDED.lifecycle_status,
          source_type = EXCLUDED.source_type,
          graph_json = EXCLUDED.graph_json,
          updated_at = now()
    """
    try:
        execute_non_query(
            settings,
            sql,
            [
                artifact_id,
                tenant_id,
                domain_id,
                run_id,
                connection_id,
                database_name,
                schema_name,
                f"{tenant_id}::{domain_id}::{run_id}::{connection_id}::{database_name}::{schema_name}::schema_graph",
                1,
                True,
                "active",
                "agentic",
                Json(schema_graph),
            ],
        )
    except psycopg2.errors.UndefinedTable:
        return None
    return artifact_id


def get_schema_graph_artifact(
    settings: Settings,
    *,
    tenant_id: str,
    domain_id: str,
    run_id: str,
    connection_id: str,
    database_name: str,
    schema_name: str,
) -> dict[str, Any] | None:
    sql = """
        SELECT *
          FROM public.quantyx_schema_graph_artifacts
         WHERE tenant_id = %s
           AND domain_id = %s
           AND run_id = %s
           AND connection_id = %s
           AND database_name = %s
           AND schema_name = %s
           AND COALESCE(is_current, true) = true
         ORDER BY updated_at DESC
         LIMIT 1
    """
    try:
        rows = run_query(settings, sql, [tenant_id, domain_id, run_id, connection_id, database_name, schema_name])
    except psycopg2.errors.UndefinedTable:
        return None
    return rows[0] if rows else None


def persist_table_profile_artifact(
    settings: Settings,
    *,
    tenant_id: str,
    domain_id: str,
    run_id: str,
    connection_id: str,
    database_name: str,
    schema_name: str,
    profiling_json: dict[str, Any],
) -> str | None:
    artifact_id = f"tp_{uuid.uuid4().hex[:12]}"
    sql = """
        INSERT INTO public.quantyx_table_profile_artifacts (
          artifact_id, tenant_id, domain_id, run_id, connection_id, database_name, schema_name,
          artifact_key, version_no, is_current, lifecycle_status, source_type, profiling_json,
          created_at, updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, now(), now())
        ON CONFLICT (tenant_id, domain_id, run_id, connection_id, database_name, schema_name)
        DO UPDATE SET
          artifact_key = EXCLUDED.artifact_key,
          version_no = EXCLUDED.version_no,
          is_current = EXCLUDED.is_current,
          lifecycle_status = EXCLUDED.lifecycle_status,
          source_type = EXCLUDED.source_type,
          profiling_json = EXCLUDED.profiling_json,
          updated_at = now()
    """
    try:
        execute_non_query(
            settings,
            sql,
            [
                artifact_id,
                tenant_id,
                domain_id,
                run_id,
                connection_id,
                database_name,
                schema_name,
                f"{tenant_id}::{domain_id}::{run_id}::{connection_id}::{database_name}::{schema_name}::table_profiles",
                1,
                True,
                "active",
                "agentic",
                Json(profiling_json),
            ],
        )
    except psycopg2.errors.UndefinedTable:
        return None
    return artifact_id


def get_table_profile_artifact(
    settings: Settings,
    *,
    tenant_id: str,
    domain_id: str,
    run_id: str,
    connection_id: str,
    database_name: str,
    schema_name: str,
) -> dict[str, Any] | None:
    sql = """
        SELECT *
          FROM public.quantyx_table_profile_artifacts
         WHERE tenant_id = %s
           AND domain_id = %s
           AND run_id = %s
           AND connection_id = %s
           AND database_name = %s
           AND schema_name = %s
           AND COALESCE(is_current, true) = true
         ORDER BY updated_at DESC
         LIMIT 1
    """
    try:
        rows = run_query(settings, sql, [tenant_id, domain_id, run_id, connection_id, database_name, schema_name])
    except psycopg2.errors.UndefinedTable:
        return None
    return rows[0] if rows else None


def replace_join_registry(
    settings: Settings,
    *,
    tenant_id: str,
    domain_id: str,
    run_id: str,
    connection_id: str,
    database_name: str,
    schema_name: str,
    joins: list[dict[str, Any]],
) -> int:
    delete_sql = """
        DELETE FROM public.quantyx_join_registry
         WHERE tenant_id = %s
           AND domain_id = %s
           AND run_id = %s
           AND connection_id = %s
           AND database_name = %s
           AND schema_name = %s
    """
    insert_sql = """
        INSERT INTO public.quantyx_join_registry (
          join_id, tenant_id, domain_id, run_id, connection_id, database_name, schema_name,
          left_table, left_key, right_table, right_key, relationship, confidence,
          coverage_ratio, coverage_total, coverage_matched, uniqueness_check, coverage_check,
          metadata, artifact_key, version_no, is_current, lifecycle_status, source_type,
          created_at, updated_at
        )
        VALUES (
          %s, %s, %s, %s, %s, %s, %s,
          %s, %s, %s, %s, %s, %s,
          %s, %s, %s, %s::jsonb, %s::jsonb,
          %s::jsonb, %s, %s, %s, %s, %s,
          now(), now()
        )
    """
    try:
        execute_non_query(
            settings,
            delete_sql,
            [tenant_id, domain_id, run_id, connection_id, database_name, schema_name],
        )
        count = 0
        for idx, join in enumerate(joins, start=1):
            left_table = str(join.get("left_table") or "").strip()
            left_key = str(join.get("left_key") or "").strip()
            right_table = str(join.get("right_table") or "").strip()
            right_key = str(join.get("right_key") or "").strip()
            if not (left_table and left_key and right_table and right_key):
                continue
            join_id = f"join_{uuid.uuid4().hex[:12]}"
            artifact_key = f"{tenant_id}::{domain_id}::{run_id}::{connection_id}::{database_name}::{schema_name}::{left_table}.{left_key}->{right_table}.{right_key}"
            execute_non_query(
                settings,
                insert_sql,
                [
                    join_id,
                    tenant_id,
                    domain_id,
                    run_id,
                    connection_id,
                    database_name,
                    schema_name,
                    left_table,
                    left_key,
                    right_table,
                    right_key,
                    join.get("relationship"),
                    join.get("confidence"),
                    join.get("coverage_ratio"),
                    join.get("coverage_total"),
                    join.get("coverage_matched"),
                    Json(join.get("uniqueness_check") or {}),
                    Json(join.get("coverage_check") or {}),
                    Json(join),
                    artifact_key,
                    1,
                    True,
                    "active",
                    "agentic",
                ],
            )
            count += 1
        return count
    except psycopg2.errors.UndefinedTable:
        return 0


def list_join_registry(
    settings: Settings,
    *,
    tenant_id: str,
    domain_id: str,
    run_id: str,
    connection_id: str,
    database_name: str,
    schema_name: str,
) -> list[dict[str, Any]]:
    sql = """
        SELECT *
          FROM public.quantyx_join_registry
         WHERE tenant_id = %s
           AND domain_id = %s
           AND run_id = %s
           AND connection_id = %s
           AND database_name = %s
           AND schema_name = %s
           AND COALESCE(is_current, true) = true
         ORDER BY created_at ASC
    """
    try:
        return run_query(settings, sql, [tenant_id, domain_id, run_id, connection_id, database_name, schema_name])
    except psycopg2.errors.UndefinedTable:
        return []


def replace_model_registry(
    settings: Settings,
    *,
    tenant_id: str,
    domain_id: str,
    run_id: str,
    connection_id: str,
    database_name: str,
    schema_name: str,
    models: list[dict[str, Any]],
) -> int:
    delete_sql = """
        DELETE FROM public.quantyx_model_registry
         WHERE tenant_id = %s
           AND domain_id = %s
           AND run_id = %s
           AND connection_id = %s
           AND database_name = %s
           AND schema_name = %s
    """
    insert_sql = """
        INSERT INTO public.quantyx_model_registry (
          model_id, tenant_id, domain_id, run_id, connection_id, database_name, schema_name,
          table_name, model_type, grain, time_column, confidence, metadata,
          artifact_key, version_no, is_current, lifecycle_status, source_type,
          created_at, updated_at
        )
        VALUES (
          %s, %s, %s, %s, %s, %s, %s,
          %s, %s, %s, %s, %s, %s::jsonb,
          %s, %s, %s, %s, %s,
          now(), now()
        )
    """
    try:
        execute_non_query(
            settings,
            delete_sql,
            [tenant_id, domain_id, run_id, connection_id, database_name, schema_name],
        )
        count = 0
        for model in models:
            table_name = str(model.get("table") or model.get("name") or "").strip()
            if not table_name:
                continue
            model_id = f"model_{uuid.uuid4().hex[:12]}"
            artifact_key = f"{tenant_id}::{domain_id}::{run_id}::{connection_id}::{database_name}::{schema_name}::{table_name}"
            execute_non_query(
                settings,
                insert_sql,
                [
                    model_id,
                    tenant_id,
                    domain_id,
                    run_id,
                    connection_id,
                    database_name,
                    schema_name,
                    table_name,
                    model.get("model_type"),
                    model.get("grain"),
                    model.get("time_column"),
                    model.get("confidence"),
                    Json(model),
                    artifact_key,
                    1,
                    True,
                    "active",
                    "agentic",
                ],
            )
            count += 1
        return count
    except psycopg2.errors.UndefinedTable:
        return 0


def list_model_registry(
    settings: Settings,
    *,
    tenant_id: str,
    domain_id: str,
    run_id: str,
    connection_id: str,
    database_name: str,
    schema_name: str,
) -> list[dict[str, Any]]:
    sql = """
        SELECT *
          FROM public.quantyx_model_registry
         WHERE tenant_id = %s
           AND domain_id = %s
           AND run_id = %s
           AND connection_id = %s
           AND database_name = %s
           AND schema_name = %s
           AND COALESCE(is_current, true) = true
         ORDER BY created_at ASC
    """
    try:
        return run_query(settings, sql, [tenant_id, domain_id, run_id, connection_id, database_name, schema_name])
    except psycopg2.errors.UndefinedTable:
        return []
