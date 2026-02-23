from __future__ import annotations

from typing import Any

import psycopg2
from psycopg2.extras import RealDictCursor

from services.ai.config import Settings


def purge_tenant_data(
    settings: Settings,
    tenant_id: str,
    dry_run: bool = False,
) -> list[dict[str, Any]]:
    conn = psycopg2.connect(
        host=settings.db_host,
        port=settings.db_port,
        dbname=settings.db_name,
        user=settings.db_user,
        password=settings.db_password,
    )
    results: list[dict[str, Any]] = []
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT DISTINCT table_name
                  FROM information_schema.columns
                 WHERE table_schema = 'public'
                   AND column_name = 'tenant_id'
                 ORDER BY table_name
                """
            )
            tenant_tables = [row["table_name"] for row in cur.fetchall()]
            cur.execute(
                """
                SELECT table_name
                  FROM information_schema.tables
                 WHERE table_schema = 'public'
                """
            )
            existing_tables = {row["table_name"] for row in cur.fetchall()}
            extra_join_tables = [
                "quantyx_context_extraction_agents",
                "quantyx_context_file_links",
                "quantyx_job_events",
                "quantyx_canvas_nodes",
                "quantyx_canvas_edges",
                "quantyx_connection_scopes",
                "quantyx_query_audit",
                "quantyx_insight_events",
                "quantyx_fact_views_registry",
            ]
            # Delete children before parents to avoid FK violations.
            deletion_order = [
                "quantyx_fact_views_registry",
                "quantyx_context_extraction_agents",
                "quantyx_context_file_links",
                "quantyx_context_extractions",
                "quantyx_context_files",
                "quantyx_glossary_terms",
                "quantyx_context_scope_active",
                "quantyx_hierarchy_overrides",
                "quantyx_entity_overrides",
                "quantyx_metrics_registry",
                "quantyx_facts_registry",
                "quantyx_dimensions_registry",
                "quantyx_review_events",
                "quantyx_dbt_manifest",
                "quantyx_dbt_config",
                "quantyx_entity_mappings",
                "quantyx_dbt_scaffolds",
                "quantyx_tenant_dbt_projects",
                "quantyx_flow_node_data_registry",
                "quantyx_business_context",
                "quantyx_schema_scans",
                "quantyx_connection_scopes",
                "quantyx_connection_registry",
                "quantyx_job_events",
                "quantyx_jobs",
                "quantyx_job_scopes",
                "quantyx_canvas_nodes",
                "quantyx_canvas_edges",
                "quantyx_canvases",
                "quantyx_tenant_scopes",
                "quantyx_tenant_scope_history",
                "quantyx_query_audit",
                "quantyx_insight_events",
                "quantyx_tenant_domains",
                "quantyx_semantic_contracts",
                "quantyx_policy_audit",
                "quantyx_usage_stats",
            ]
            ordered = []
            for name in deletion_order:
                if name in existing_tables and (name in tenant_tables or name in extra_join_tables):
                    if name not in ordered:
                        ordered.append(name)
            # Append any remaining tenant_id tables not in explicit order.
            for name in tenant_tables:
                if name in existing_tables and name not in ordered:
                    ordered.append(name)
            for table in ordered:
                if table not in existing_tables:
                    results.append({"table": table, "rows": 0, "skipped": "missing"})
                    continue
                if table == "quantyx_fact_views_registry":
                    if dry_run:
                        cur.execute(
                            """
                            SELECT schema_name, view_name
                              FROM public.quantyx_fact_views_registry
                             WHERE tenant_id = %s
                            """,
                            [tenant_id],
                        )
                        views = cur.fetchall()
                        results.append({"table": table, "rows": len(views)})
                        continue
                    cur.execute(
                        """
                        SELECT schema_name, view_name
                          FROM public.quantyx_fact_views_registry
                         WHERE tenant_id = %s
                        """,
                        [tenant_id],
                    )
                    views = cur.fetchall()
                    for view in views:
                        schema_name = view.get("schema_name")
                        view_name = view.get("view_name")
                        if schema_name and view_name:
                            cur.execute(f"DROP VIEW IF EXISTS {schema_name}.{view_name}")
                    cur.execute(
                        "DELETE FROM public.quantyx_fact_views_registry WHERE tenant_id = %s",
                        [tenant_id],
                    )
                    results.append({"table": table, "rows": cur.rowcount})
                    continue
                if table == "quantyx_context_extraction_agents":
                    if dry_run:
                        cur.execute(
                            """
                            SELECT COUNT(*) AS count
                              FROM public.quantyx_context_extraction_agents a
                              JOIN public.quantyx_context_extractions e
                                ON e.extraction_id = a.extraction_id
                             WHERE e.tenant_id = %s
                            """,
                            [tenant_id],
                        )
                        count = cur.fetchone()["count"]
                        results.append({"table": table, "rows": int(count)})
                        continue
                    cur.execute(
                        """
                        DELETE FROM public.quantyx_context_extraction_agents a
                        USING public.quantyx_context_extractions e
                        WHERE e.extraction_id = a.extraction_id
                          AND e.tenant_id = %s
                        """,
                        [tenant_id],
                    )
                    results.append({"table": table, "rows": cur.rowcount})
                    continue
                if table == "quantyx_context_file_links":
                    if dry_run:
                        cur.execute(
                            """
                            SELECT COUNT(*) AS count
                              FROM public.quantyx_context_file_links l
                              JOIN public.quantyx_context_files f
                                ON f.file_id = l.file_id
                             WHERE f.tenant_id = %s
                            """,
                            [tenant_id],
                        )
                        count = cur.fetchone()["count"]
                        results.append({"table": table, "rows": int(count)})
                        continue
                    cur.execute(
                        """
                        DELETE FROM public.quantyx_context_file_links l
                        USING public.quantyx_context_files f
                        WHERE f.file_id = l.file_id
                          AND f.tenant_id = %s
                        """,
                        [tenant_id],
                    )
                    results.append({"table": table, "rows": cur.rowcount})
                    continue
                if table == "quantyx_job_events":
                    if dry_run:
                        cur.execute(
                            """
                            SELECT COUNT(*) AS count
                              FROM public.quantyx_job_events e
                              JOIN public.quantyx_jobs j
                                ON j.job_id = e.job_id
                             WHERE j.tenant_id = %s
                            """,
                            [tenant_id],
                        )
                        count = cur.fetchone()["count"]
                        results.append({"table": table, "rows": int(count)})
                        continue
                    cur.execute(
                        """
                        DELETE FROM public.quantyx_job_events e
                        USING public.quantyx_jobs j
                        WHERE j.job_id = e.job_id
                          AND j.tenant_id = %s
                        """,
                        [tenant_id],
                    )
                    results.append({"table": table, "rows": cur.rowcount})
                    continue
                if table == "quantyx_canvas_nodes":
                    if dry_run:
                        cur.execute(
                            """
                            SELECT COUNT(*) AS count
                              FROM public.quantyx_canvas_nodes n
                              JOIN public.quantyx_canvases c
                                ON c.canvas_id = n.canvas_id
                             WHERE c.tenant_id = %s
                            """,
                            [tenant_id],
                        )
                        count = cur.fetchone()["count"]
                        results.append({"table": table, "rows": int(count)})
                        continue
                    cur.execute(
                        """
                        DELETE FROM public.quantyx_canvas_nodes n
                        USING public.quantyx_canvases c
                        WHERE c.canvas_id = n.canvas_id
                          AND c.tenant_id = %s
                        """,
                        [tenant_id],
                    )
                    results.append({"table": table, "rows": cur.rowcount})
                    continue
                if table == "quantyx_canvas_edges":
                    if dry_run:
                        cur.execute(
                            """
                            SELECT COUNT(*) AS count
                              FROM public.quantyx_canvas_edges e
                              JOIN public.quantyx_canvases c
                                ON c.canvas_id = e.canvas_id
                             WHERE c.tenant_id = %s
                            """,
                            [tenant_id],
                        )
                        count = cur.fetchone()["count"]
                        results.append({"table": table, "rows": int(count)})
                        continue
                    cur.execute(
                        """
                        DELETE FROM public.quantyx_canvas_edges e
                        USING public.quantyx_canvases c
                        WHERE c.canvas_id = e.canvas_id
                          AND c.tenant_id = %s
                        """,
                        [tenant_id],
                    )
                    results.append({"table": table, "rows": cur.rowcount})
                    continue
                if table == "quantyx_connection_scopes":
                    if dry_run:
                        cur.execute(
                            """
                            SELECT COUNT(*) AS count
                              FROM public.quantyx_connection_scopes s
                              JOIN public.quantyx_connection_registry r
                                ON r.connection_id = s.connection_id
                             WHERE r.tenant_id = %s
                            """,
                            [tenant_id],
                        )
                        count = cur.fetchone()["count"]
                        results.append({"table": table, "rows": int(count)})
                        continue
                    cur.execute(
                        """
                        DELETE FROM public.quantyx_connection_scopes s
                        USING public.quantyx_connection_registry r
                        WHERE r.connection_id = s.connection_id
                          AND r.tenant_id = %s
                        """,
                        [tenant_id],
                    )
                    results.append({"table": table, "rows": cur.rowcount})
                    continue
                if table == "quantyx_query_audit":
                    if dry_run:
                        cur.execute(
                            """
                            SELECT COUNT(*) AS count
                              FROM public.quantyx_query_audit q
                              JOIN public.quantyx_tenant_domains d
                                ON d.domain_id = q.domain_id
                             WHERE d.tenant_id = %s
                            """,
                            [tenant_id],
                        )
                        count = cur.fetchone()["count"]
                        results.append({"table": table, "rows": int(count)})
                        continue
                    cur.execute(
                        """
                        DELETE FROM public.quantyx_query_audit q
                        USING public.quantyx_tenant_domains d
                        WHERE d.domain_id = q.domain_id
                          AND d.tenant_id = %s
                        """,
                        [tenant_id],
                    )
                    results.append({"table": table, "rows": cur.rowcount})
                    continue
                if table == "quantyx_insight_events":
                    if dry_run:
                        cur.execute(
                            """
                            SELECT COUNT(*) AS count
                              FROM public.quantyx_insight_events i
                              JOIN public.quantyx_tenant_domains d
                                ON d.domain_id = i.domain_id
                             WHERE d.tenant_id = %s
                            """,
                            [tenant_id],
                        )
                        count = cur.fetchone()["count"]
                        results.append({"table": table, "rows": int(count)})
                        continue
                    cur.execute(
                        """
                        DELETE FROM public.quantyx_insight_events i
                        USING public.quantyx_tenant_domains d
                        WHERE d.domain_id = i.domain_id
                          AND d.tenant_id = %s
                        """,
                        [tenant_id],
                    )
                    results.append({"table": table, "rows": cur.rowcount})
                    continue
                if dry_run:
                    cur.execute(f"SELECT COUNT(*) AS count FROM public.{table} WHERE tenant_id = %s", [tenant_id])
                    count = cur.fetchone()["count"]
                    results.append({"table": table, "rows": int(count)})
                    continue
                cur.execute(f"DELETE FROM public.{table} WHERE tenant_id = %s", [tenant_id])
                results.append({"table": table, "rows": cur.rowcount})
        if not dry_run:
            conn.commit()
        return results
    finally:
        conn.close()
