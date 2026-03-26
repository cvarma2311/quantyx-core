#!/usr/bin/env python3
from __future__ import annotations

"""
Verify deployment + workspace persistence for a tenant/domain/run.

Usage:
  python3 scripts/verify_workspace_deployment_persistence.py \
    --tenant-id DEBUG_LPG_001 \
    --domain-id lpg_production_distribution

  python3 scripts/verify_workspace_deployment_persistence.py \
    --tenant-id DEBUG_LPG_001 \
    --domain-id lpg_production_distribution \
    --run-id run_78f1665046c4 \
    --conversation-id conv_9783b0722d1e

  python3 scripts/verify_workspace_deployment_persistence.py \
    --tenant-id DEBUG_LPG_001 \
    --domain-id lpg_production_distribution \
    --db-host 13.126.249.159 \
    --db-port 5432 \
    --db-name hpcl_ceg \
    --db-user novex \
    --db-password '***'

  python3 scripts/verify_workspace_deployment_persistence.py --help

What this verifies:
  1) Deployment scope/run artifacts:
     - quantyx_tenant_scopes
     - quantyx_agent_runs
     - quantyx_agent_run_events
     - quantyx_agent_event_artifacts
     - quantyx_schema_graph_artifacts
     - quantyx_table_profile_artifacts
     - quantyx_join_registry
     - quantyx_model_registry
  2) Semantic persistence from initial run:
     - quantyx_facts_registry
     - quantyx_dimensions_registry
     - quantyx_metrics_registry
     - quantyx_glossary_terms
     - quantyx_hierarchy_overrides
     - quantyx_semantic_contracts
     - quantyx_semantic_nodes / quantyx_semantic_edges
     - quantyx_fact_views_registry
     - quantyx_dashboards (Phase 44 unified; was quantyx_dashboard_specs)
  3) Workspace chat persistence:
     - quantyx_workspace_conversations
     - quantyx_workspace_messages
     - quantyx_workspace_conversation_memory
     - turn-level artifact_lineage in message JSON
"""

import argparse
import json
import os
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Load .env if python-dotenv is installed; no-op otherwise.
try:
    from dotenv import load_dotenv  # type: ignore

    load_dotenv(REPO_ROOT / ".env")
except Exception:
    pass

from services.ai.config import load_settings  # noqa: E402


def _run_query_with_psycopg2(settings, sql: str, params: list[object]) -> list[dict[str, Any]]:
    import psycopg2
    from psycopg2.extras import RealDictCursor

    conn = psycopg2.connect(
        host=settings.db_host,
        port=settings.db_port,
        dbname=settings.db_name,
        user=settings.db_user,
        password=settings.db_password,
    )
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def _run_query_with_psycopg3(settings, sql: str, params: list[object]) -> list[dict[str, Any]]:
    import psycopg

    conn = psycopg.connect(
        host=settings.db_host,
        port=settings.db_port,
        dbname=settings.db_name,
        user=settings.db_user,
        password=settings.db_password,
        autocommit=True,
    )
    try:
        with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def run_query(settings, sql: str, params: list[object]) -> list[dict[str, Any]]:
    try:
        return _run_query_with_psycopg2(settings, sql, params)
    except ModuleNotFoundError:
        pass
    except Exception:
        raise
    try:
        return _run_query_with_psycopg3(settings, sql, params)
    except ModuleNotFoundError:
        raise RuntimeError(
            "No PostgreSQL driver found. Install either 'psycopg2-binary' or 'psycopg' in this environment."
        )


def _count(settings, sql: str, params: list[object]) -> int:
    rows = run_query(settings, sql, params)
    if not rows:
        return 0
    return int(rows[0].get("count") or 0)


def _rows(settings, sql: str, params: list[object], limit: int = 5) -> list[dict[str, Any]]:
    return run_query(settings, sql, params)[:limit]


def _table_columns(settings, table_name: str, schema_name: str = "public") -> set[str]:
    rows = run_query(
        settings,
        """
        SELECT column_name
          FROM information_schema.columns
         WHERE table_schema = %s AND table_name = %s
        """,
        [schema_name, table_name],
    )
    return {str(r.get("column_name")) for r in rows if r.get("column_name")}


def _pick_first_existing(available: set[str], candidates: list[str]) -> str | None:
    for c in candidates:
        if c in available:
            return c
    return None


def _safe_rows(
    settings,
    sql: str,
    params: list[object],
    *,
    limit: int = 5,
) -> list[dict[str, Any]]:
    try:
        return _rows(settings, sql, params, limit)
    except Exception as exc:
        return [{"error": str(exc)}]


def _safe_count(settings, sql: str, params: list[object]) -> int | dict[str, Any]:
    try:
        return _count(settings, sql, params)
    except Exception as exc:
        return {"error": str(exc)}


def _int_or_none(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify workspace deployment persistence.")
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--domain-id", required=True)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--conversation-id", default=None)
    parser.add_argument("--sample-limit", type=int, default=5)
    parser.add_argument("--db-host", default=None)
    parser.add_argument("--db-port", type=int, default=None)
    parser.add_argument("--db-name", default=None)
    parser.add_argument("--db-user", default=None)
    parser.add_argument("--db-password", default=None)
    args = parser.parse_args()

    settings = load_settings()
    demo_db_host = os.getenv("DEMO_DB_HOST")
    demo_db_port = _int_or_none(os.getenv("DEMO_DB_PORT"))
    demo_db_name = os.getenv("DEMO_DB_NAME")
    demo_db_user = os.getenv("DEMO_DB_USER")
    demo_db_password = os.getenv("DEMO_DB_PASSWORD")

    settings = replace(
        settings,
        db_host=args.db_host or demo_db_host or settings.db_host,
        db_port=args.db_port or demo_db_port or settings.db_port,
        db_name=args.db_name or demo_db_name or settings.db_name,
        db_user=args.db_user or demo_db_user or settings.db_user,
        db_password=(
            args.db_password
            if args.db_password is not None
            else (demo_db_password if demo_db_password is not None else settings.db_password)
        ),
    )
    tenant_id = args.tenant_id
    domain_id = args.domain_id
    run_id = args.run_id
    conversation_id = args.conversation_id
    sample_limit = max(1, min(args.sample_limit, 20))

    report: dict[str, Any] = {
        "scope": {
            "tenant_id": tenant_id,
            "domain_id": domain_id,
            "run_id": run_id,
            "conversation_id": conversation_id,
        },
        "checks": {},
    }
    checks = report["checks"]

    try:
        checks["tenant_scope"] = {
            "count": _count(
                settings,
                """
                SELECT COUNT(*) AS count
                  FROM public.quantyx_tenant_scopes
                 WHERE tenant_id = %s AND domain_id = %s
                """,
                [tenant_id, domain_id],
            ),
            "sample": _rows(
                settings,
                """
                SELECT tenant_id, domain_id, connection_id, database_name, schema_name, tables, updated_at
                  FROM public.quantyx_tenant_scopes
                 WHERE tenant_id = %s AND domain_id = %s
                 ORDER BY updated_at DESC
                """,
                [tenant_id, domain_id],
                sample_limit,
            ),
        }

        checks["agent_runs"] = {
            "count": _count(
                settings,
                """
                SELECT COUNT(*) AS count
                  FROM public.quantyx_agent_runs
                 WHERE tenant_id = %s AND domain_id = %s
                """,
                [tenant_id, domain_id],
            ),
            "sample": _rows(
                settings,
                """
                SELECT run_id, status, display_name, version_no, is_canonical, created_at, updated_at
                  FROM public.quantyx_agent_runs
                 WHERE tenant_id = %s AND domain_id = %s
                 ORDER BY created_at DESC
                """,
                [tenant_id, domain_id],
                sample_limit,
            ),
        }

        run_filter: list[object] = [tenant_id, domain_id]
        run_where = "r.tenant_id = %s AND r.domain_id = %s"
        if run_id:
            run_where += " AND r.run_id = %s"
            run_filter.append(run_id)

        checks["agent_run_events"] = {
            "count": _count(
                settings,
                f"""
                SELECT COUNT(*) AS count
                  FROM public.quantyx_agent_run_events e
                  JOIN public.quantyx_agent_runs r ON r.run_id = e.run_id
                 WHERE {run_where}
                """,
                run_filter,
            ),
            "sample": _rows(
                settings,
                f"""
                SELECT e.run_id, e.agent_name, e.status, e.stage_name, e.message, e.created_at
                  FROM public.quantyx_agent_run_events e
                  JOIN public.quantyx_agent_runs r ON r.run_id = e.run_id
                 WHERE {run_where}
                 ORDER BY e.created_at DESC
                """,
                run_filter,
                sample_limit,
            ),
        }

        checks["agent_event_artifacts"] = {
            "count": _count(
                settings,
                f"""
                SELECT COUNT(*) AS count
                  FROM public.quantyx_agent_event_artifacts a
                  JOIN public.quantyx_agent_runs r ON r.run_id = a.run_id
                 WHERE {run_where}
                """,
                run_filter,
            ),
        }

        artifact_scope_params: list[object] = [tenant_id, domain_id]
        artifact_scope_where = "tenant_id = %s AND domain_id = %s"
        if run_id:
            artifact_scope_where += " AND run_id = %s"
            artifact_scope_params.append(run_id)

        checks["schema_graph_artifacts"] = {
            "count": _safe_count(
                settings,
                f"""
                SELECT COUNT(*) AS count
                  FROM public.quantyx_schema_graph_artifacts
                 WHERE {artifact_scope_where}
                   AND COALESCE(is_current, true) = true
                """,
                artifact_scope_params,
            ),
            "sample": _safe_rows(
                settings,
                f"""
                SELECT artifact_id, run_id, connection_id, database_name, schema_name,
                       artifact_key, version_no, lifecycle_status, updated_at
                  FROM public.quantyx_schema_graph_artifacts
                 WHERE {artifact_scope_where}
                   AND COALESCE(is_current, true) = true
                 ORDER BY updated_at DESC
                 LIMIT %s
                """,
                [*artifact_scope_params, sample_limit],
                limit=sample_limit,
            ),
        }

        checks["table_profile_artifacts"] = {
            "count": _safe_count(
                settings,
                f"""
                SELECT COUNT(*) AS count
                  FROM public.quantyx_table_profile_artifacts
                 WHERE {artifact_scope_where}
                   AND COALESCE(is_current, true) = true
                """,
                artifact_scope_params,
            ),
            "sample": _safe_rows(
                settings,
                f"""
                SELECT artifact_id, run_id, connection_id, database_name, schema_name,
                       artifact_key, version_no, lifecycle_status, updated_at
                  FROM public.quantyx_table_profile_artifacts
                 WHERE {artifact_scope_where}
                   AND COALESCE(is_current, true) = true
                 ORDER BY updated_at DESC
                 LIMIT %s
                """,
                [*artifact_scope_params, sample_limit],
                limit=sample_limit,
            ),
        }

        checks["join_registry"] = {
            "count": _safe_count(
                settings,
                f"""
                SELECT COUNT(*) AS count
                  FROM public.quantyx_join_registry
                 WHERE {artifact_scope_where}
                   AND COALESCE(is_current, true) = true
                """,
                artifact_scope_params,
            ),
            "sample": _safe_rows(
                settings,
                f"""
                SELECT join_id, run_id, left_table, left_key, right_table, right_key,
                       relationship, confidence, artifact_key, version_no, created_at
                  FROM public.quantyx_join_registry
                 WHERE {artifact_scope_where}
                   AND COALESCE(is_current, true) = true
                 ORDER BY created_at DESC
                 LIMIT %s
                """,
                [*artifact_scope_params, sample_limit],
                limit=sample_limit,
            ),
        }

        checks["model_registry"] = {
            "count": _safe_count(
                settings,
                f"""
                SELECT COUNT(*) AS count
                  FROM public.quantyx_model_registry
                 WHERE {artifact_scope_where}
                   AND COALESCE(is_current, true) = true
                """,
                artifact_scope_params,
            ),
            "sample": _safe_rows(
                settings,
                f"""
                SELECT model_id, run_id, table_name, model_type, grain, time_column,
                       confidence, artifact_key, version_no, created_at
                  FROM public.quantyx_model_registry
                 WHERE {artifact_scope_where}
                   AND COALESCE(is_current, true) = true
                 ORDER BY created_at DESC
                 LIMIT %s
                """,
                [*artifact_scope_params, sample_limit],
                limit=sample_limit,
            ),
        }

        checks["facts_registry"] = {
            "count": _count(
                settings,
                """
                SELECT COUNT(*) AS count
                  FROM public.quantyx_facts_registry
                 WHERE tenant_id = %s AND domain_id = %s AND COALESCE(is_current, true) = true
                """,
                [tenant_id, domain_id],
            ),
            "sample": _rows(
                settings,
                """
                SELECT fact_id, table_name, grain, time_column, source_type, source_run_id, created_at
                  FROM public.quantyx_facts_registry
                 WHERE tenant_id = %s AND domain_id = %s AND COALESCE(is_current, true) = true
                 ORDER BY created_at DESC
                """,
                [tenant_id, domain_id],
                sample_limit,
            ),
        }

        checks["dimensions_registry"] = {
            "count": _count(
                settings,
                """
                SELECT COUNT(*) AS count
                  FROM public.quantyx_dimensions_registry
                 WHERE tenant_id = %s AND domain_id = %s AND COALESCE(is_current, true) = true
                """,
                [tenant_id, domain_id],
            ),
            "sample": _rows(
                settings,
                """
                SELECT dimension_id, name, source_type, source_run_id, created_at
                  FROM public.quantyx_dimensions_registry
                 WHERE tenant_id = %s AND domain_id = %s AND COALESCE(is_current, true) = true
                 ORDER BY created_at DESC
                """,
                [tenant_id, domain_id],
                sample_limit,
            ),
        }

        checks["metrics_registry"] = {
            "count": _count(
                settings,
                """
                SELECT COUNT(*) AS count
                  FROM public.quantyx_metrics_registry
                 WHERE tenant_id = %s AND domain_id = %s AND COALESCE(is_current, true) = true
                """,
                [tenant_id, domain_id],
            ),
            "sample": _rows(
                settings,
                """
                SELECT metric_id, metric_name, type, source_model, source_type, source_run_id, created_at
                  FROM public.quantyx_metrics_registry
                 WHERE tenant_id = %s AND domain_id = %s AND COALESCE(is_current, true) = true
                 ORDER BY created_at DESC
                """,
                [tenant_id, domain_id],
                sample_limit,
            ),
        }

        checks["glossary_terms"] = {
            "count": _count(
                settings,
                """
                SELECT COUNT(*) AS count
                  FROM public.quantyx_glossary_terms
                 WHERE tenant_id = %s AND domain_id = %s
                """,
                [tenant_id, domain_id],
            ),
        }

        checks["hierarchy_overrides"] = {
            "count": _count(
                settings,
                """
                SELECT COUNT(*) AS count
                  FROM public.quantyx_hierarchy_overrides
                 WHERE tenant_id = %s AND domain_id = %s AND COALESCE(is_current, true) = true
                """,
                [tenant_id, domain_id],
            ),
        }

        checks["semantic_contracts"] = {
            "count": _count(
                settings,
                """
                SELECT COUNT(*) AS count
                  FROM public.quantyx_semantic_contracts
                 WHERE tenant_id = %s AND industry = %s
                """,
                [tenant_id, domain_id],
            ),
            "sample": _rows(
                settings,
                """
                SELECT contract_id, industry, version, status, created_at
                  FROM public.quantyx_semantic_contracts
                 WHERE tenant_id = %s AND industry = %s
                 ORDER BY created_at DESC
                """,
                [tenant_id, domain_id],
                sample_limit,
            ),
        }

        checks["semantic_graph"] = {
            "nodes": _count(
                settings,
                "SELECT COUNT(*) AS count FROM public.quantyx_semantic_nodes WHERE domain_id = %s",
                [domain_id],
            ),
            "edges": _count(
                settings,
                """
                SELECT COUNT(*) AS count
                  FROM public.quantyx_semantic_edges e
                  JOIN public.quantyx_semantic_nodes s ON s.node_id = e.src_node_id
                 WHERE s.domain_id = %s
                """,
                [domain_id],
            ),
        }

        fact_view_cols = _table_columns(settings, "quantyx_fact_views_registry")
        fact_view_table_col = _pick_first_existing(
            fact_view_cols, ["base_table", "table_name", "source_table", "source_model", "fact_table_name"]
        )
        fact_view_sample_cols = ["view_id", "schema_name", "view_name"]
        if fact_view_table_col:
            fact_view_sample_cols.append(fact_view_table_col)
        fact_view_order_col = "created_at" if "created_at" in fact_view_cols else "view_id"
        if "created_at" in fact_view_cols:
            fact_view_sample_cols.append("created_at")

        checks["fact_views_registry"] = {
            "count": _count(
                settings,
                """
                SELECT COUNT(*) AS count
                  FROM public.quantyx_fact_views_registry
                 WHERE tenant_id = %s AND domain_id = %s
                """,
                [tenant_id, domain_id],
            ),
            "sample": _rows(
                settings,
                f"""
                SELECT {", ".join(fact_view_sample_cols)}
                  FROM public.quantyx_fact_views_registry
                 WHERE tenant_id = %s AND domain_id = %s
                 ORDER BY {fact_view_order_col} DESC NULLS LAST
                """,
                [tenant_id, domain_id],
                sample_limit,
            ),
        }

        checks["dashboard_specs"] = {
            "count": _count(
                settings,
                """
                SELECT COUNT(*) AS count
                  FROM public.quantyx_dashboards
                 WHERE tenant_id = %s AND domain_id = %s AND dashboard_type = 'system'
                """,
                [tenant_id, domain_id],
            ),
            "sample": _rows(
                settings,
                """
                SELECT dashboard_id, name AS title, dashboard_type, created_at, updated_at
                  FROM public.quantyx_dashboards
                 WHERE tenant_id = %s AND domain_id = %s AND dashboard_type = 'system'
                 ORDER BY created_at DESC
                """,
                [tenant_id, domain_id],
                sample_limit,
            ),
        }

        checks["workspace_conversations"] = {
            "count": _count(
                settings,
                """
                SELECT COUNT(*) AS count
                  FROM public.quantyx_workspace_conversations
                 WHERE tenant_id = %s AND domain_id = %s
                """,
                [tenant_id, domain_id],
            ),
        }

        conv_where = "c.tenant_id = %s AND c.domain_id = %s"
        conv_params: list[object] = [tenant_id, domain_id]
        if conversation_id:
            conv_where += " AND c.conversation_id = %s"
            conv_params.append(conversation_id)

        checks["workspace_messages"] = {
            "count": _count(
                settings,
                f"""
                SELECT COUNT(*) AS count
                  FROM public.quantyx_workspace_messages m
                  JOIN public.quantyx_workspace_conversations c ON c.conversation_id = m.conversation_id
                 WHERE {conv_where}
                """,
                conv_params,
            ),
            "sample": _rows(
                settings,
                f"""
                SELECT m.message_id,
                       m.conversation_id,
                       m.sender,
                       LEFT(m.message_text, 140) AS message_preview,
                       CASE
                         WHEN COALESCE(m.summary_json ? 'artifact_lineage', false)
                           OR COALESCE(m.inference_json ? 'artifact_lineage', false)
                         THEN true
                         ELSE false
                       END AS has_artifact_lineage,
                       m.created_at
                  FROM public.quantyx_workspace_messages m
                  JOIN public.quantyx_workspace_conversations c ON c.conversation_id = m.conversation_id
                 WHERE {conv_where}
                 ORDER BY m.created_at DESC
                """,
                conv_params,
                sample_limit,
            ),
        }

        checks["workspace_message_artifact_lineage"] = {
            "count": _safe_count(
                settings,
                f"""
                SELECT COUNT(*) AS count
                  FROM public.quantyx_workspace_messages m
                  JOIN public.quantyx_workspace_conversations c ON c.conversation_id = m.conversation_id
                 WHERE {conv_where}
                   AND (
                     COALESCE(m.summary_json ? 'artifact_lineage', false)
                     OR COALESCE(m.inference_json ? 'artifact_lineage', false)
                   )
                """,
                conv_params,
            ),
            "sample": _safe_rows(
                settings,
                f"""
                SELECT m.message_id,
                       m.conversation_id,
                       m.sender,
                       m.summary_json -> 'artifact_lineage' AS summary_artifact_lineage,
                       m.inference_json -> 'artifact_lineage' AS inference_artifact_lineage,
                       m.created_at
                  FROM public.quantyx_workspace_messages m
                  JOIN public.quantyx_workspace_conversations c ON c.conversation_id = m.conversation_id
                 WHERE {conv_where}
                   AND (
                     COALESCE(m.summary_json ? 'artifact_lineage', false)
                     OR COALESCE(m.inference_json ? 'artifact_lineage', false)
                   )
                 ORDER BY m.created_at DESC
                 LIMIT %s
                """,
                [*conv_params, sample_limit],
                limit=sample_limit,
            ),
        }

        checks["workspace_memory"] = {
            "count": _count(
                settings,
                f"""
                SELECT COUNT(*) AS count
                  FROM public.quantyx_workspace_conversation_memory m
                  JOIN public.quantyx_workspace_conversations c ON c.conversation_id = m.conversation_id
                 WHERE {conv_where}
                """,
                conv_params,
            ),
        }

        # Diagnostics: verify write privileges + required columns for semantic persistence tables.
        semantic_tables = [
            "quantyx_schema_graph_artifacts",
            "quantyx_table_profile_artifacts",
            "quantyx_join_registry",
            "quantyx_model_registry",
            "quantyx_facts_registry",
            "quantyx_dimensions_registry",
            "quantyx_metrics_registry",
            "quantyx_glossary_terms",
            "quantyx_hierarchy_overrides",
            "quantyx_semantic_contracts",
        ]
        required_columns: dict[str, list[str]] = {
            "quantyx_schema_graph_artifacts": [
                "tenant_id",
                "domain_id",
                "run_id",
                "connection_id",
                "database_name",
                "schema_name",
                "artifact_key",
                "version_no",
                "is_current",
                "graph_json",
            ],
            "quantyx_table_profile_artifacts": [
                "tenant_id",
                "domain_id",
                "run_id",
                "connection_id",
                "database_name",
                "schema_name",
                "artifact_key",
                "version_no",
                "is_current",
                "profiling_json",
            ],
            "quantyx_join_registry": [
                "tenant_id",
                "domain_id",
                "run_id",
                "connection_id",
                "database_name",
                "schema_name",
                "left_table",
                "left_key",
                "right_table",
                "right_key",
                "artifact_key",
                "version_no",
                "is_current",
            ],
            "quantyx_model_registry": [
                "tenant_id",
                "domain_id",
                "run_id",
                "connection_id",
                "database_name",
                "schema_name",
                "table_name",
                "model_type",
                "artifact_key",
                "version_no",
                "is_current",
            ],
            "quantyx_facts_registry": [
                "tenant_id",
                "domain_id",
                "connection_id",
                "database_name",
                "schema_name",
                "table_name",
                "artifact_key",
                "source_run_id",
                "is_current",
            ],
            "quantyx_dimensions_registry": [
                "tenant_id",
                "domain_id",
                "connection_id",
                "database_name",
                "schema_name",
                "name",
                "artifact_key",
                "source_run_id",
                "is_current",
            ],
            "quantyx_metrics_registry": [
                "tenant_id",
                "domain_id",
                "connection_id",
                "database_name",
                "schema_name",
                "metric_name",
                "artifact_key",
                "source_run_id",
                "is_current",
            ],
            "quantyx_glossary_terms": [
                "tenant_id",
                "domain_id",
                "term",
                "normalized_term",
                "source_context_id",
            ],
            "quantyx_hierarchy_overrides": [
                "tenant_id",
                "domain_id",
                "connection_id",
                "database_name",
                "schema_name",
                "context_id",
                "hierarchy_name",
                "levels",
                "artifact_key",
                "source_run_id",
                "is_current",
            ],
            "quantyx_semantic_contracts": [
                "tenant_id",
                "industry",
                "version",
                "payload",
                "status",
            ],
        }
        diagnostics: dict[str, Any] = {"tables": {}}
        for t in semantic_tables:
            cols = _table_columns(settings, t)
            req = required_columns.get(t, [])
            missing = [c for c in req if c not in cols]
            priv_rows = _safe_rows(
                settings,
                """
                SELECT current_user AS db_user,
                       has_table_privilege(current_user, %s, 'INSERT') AS can_insert,
                       has_table_privilege(current_user, %s, 'UPDATE') AS can_update,
                       has_table_privilege(current_user, %s, 'SELECT') AS can_select
                """,
                [f"public.{t}", f"public.{t}", f"public.{t}"],
                limit=1,
            )
            diagnostics["tables"][t] = {
                "missing_required_columns": missing,
                "can_insert": (priv_rows[0].get("can_insert") if priv_rows else None),
                "can_update": (priv_rows[0].get("can_update") if priv_rows else None),
                "can_select": (priv_rows[0].get("can_select") if priv_rows else None),
                "db_user": (priv_rows[0].get("db_user") if priv_rows else None),
            }
        checks["persistence_diagnostics"] = diagnostics

        # Diagnostics: inspect latest DashboardAgent completed artifact for persisted counters.
        checks["dashboard_agent_persisted_counters"] = {
            "sample": _safe_rows(
                settings,
                """
                SELECT a.run_id,
                       a.created_at,
                       a.raw_json -> 'registry_persisted' AS registry_persisted,
                       a.raw_json -> 'semantics_persisted' AS semantics_persisted
                  FROM public.quantyx_agent_event_artifacts a
                  JOIN public.quantyx_agent_runs r ON r.run_id = a.run_id
                 WHERE r.tenant_id = %s
                   AND r.domain_id = %s
                   AND a.agent_name = 'DashboardAgent'
                   AND a.stage_name = 'completed'
                 ORDER BY a.created_at DESC
                 LIMIT %s
                """,
                [tenant_id, domain_id, sample_limit],
                limit=sample_limit,
            ),
        }
    except RuntimeError as exc:
        print(
            json.dumps(
                {
                    "error": str(exc),
                    "hint": "Example: pip install psycopg2-binary  OR  pip install psycopg",
                },
                indent=2,
            )
        )
        return 2
    except Exception as exc:
        print(
            json.dumps(
                {
                    "error": str(exc),
                    "hint": (
                        "Verify DB connection settings. You can override with "
                        "--db-host/--db-port/--db-name/--db-user/--db-password or DB_* env vars."
                    ),
                    "db_target": {
                        "host": settings.db_host,
                        "port": settings.db_port,
                        "db_name": settings.db_name,
                        "db_user": settings.db_user,
                    },
                },
                indent=2,
                default=str,
            )
        )
        return 3

    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
