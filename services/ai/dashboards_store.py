"""
Phase 44 — Unified dashboard store.

Single source of truth for all dashboard CRUD over:
  quantyx_dashboards        — header row for both system and user dashboards
  quantyx_dashboard_charts  — chart links (position, title_override, added_by)
"""
from __future__ import annotations

import json
import uuid
from typing import Any

import psycopg2
from psycopg2.extras import RealDictCursor

from services.ai.config import Settings


def _json_default(value: Any):
    from datetime import date, datetime
    from decimal import Decimal

    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _conn(settings: Settings):
    return psycopg2.connect(
        host=settings.db_host,
        port=settings.db_port,
        dbname=settings.db_name,
        user=settings.db_user,
        password=settings.db_password,
    )


# ---------------------------------------------------------------------------
# Dashboard CRUD
# ---------------------------------------------------------------------------

def create_dashboard(
    settings: Settings,
    *,
    tenant_id: str,
    domain_id: str,
    name: str,
    description: str | None = None,
    dashboard_type: str = "system",   # "system" | "user"
    run_id: str | None = None,
    chart_plan: list | dict | None = None,
    quality_score: float | None = None,
    quality_gate_passed: bool | None = None,
    created_by: str | None = None,
) -> dict:
    dashboard_id = f"db_{uuid.uuid4().hex[:10]}"
    sql = """
        INSERT INTO public.quantyx_dashboards
          (dashboard_id, tenant_id, domain_id, name, description, dashboard_type, status,
           run_id, chart_plan, quality_score, quality_gate_passed, created_by)
        VALUES
          (%s, %s, %s, %s, %s, %s, 'active',
           %s, %s::jsonb, %s, %s, %s)
        RETURNING *
    """
    params = [
        dashboard_id, tenant_id, domain_id, name, description, dashboard_type,
        run_id,
        json.dumps(chart_plan, default=_json_default) if chart_plan is not None else None,
        quality_score, quality_gate_passed, created_by,
    ]
    c = _conn(settings)
    try:
        with c.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
        c.commit()
        return dict(row) if row else {"dashboard_id": dashboard_id}
    except (psycopg2.errors.UndefinedTable, psycopg2.errors.UndefinedColumn):
        return {"dashboard_id": dashboard_id}
    finally:
        c.close()


def get_dashboard(
    settings: Settings,
    dashboard_id: str,
    tenant_id: str | None = None,
) -> dict | None:
    where = "WHERE dashboard_id = %s"
    params: list[Any] = [dashboard_id]
    if tenant_id:
        where += " AND tenant_id = %s"
        params.append(tenant_id)
    sql = f"SELECT * FROM public.quantyx_dashboards {where}"
    c = _conn(settings)
    try:
        with c.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
        return dict(row) if row else None
    except (psycopg2.errors.UndefinedTable, psycopg2.errors.UndefinedColumn):
        return None
    finally:
        c.close()


def list_dashboards(
    settings: Settings,
    tenant_id: str,
    domain_id: str | None = None,
    *,
    dashboard_type: str | None = None,
    status: str = "active",
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    conditions = ["tenant_id = %s"]
    params: list[Any] = [tenant_id]
    if domain_id:
        conditions.append("domain_id = %s")
        params.append(domain_id)
    if dashboard_type:
        conditions.append("dashboard_type = %s")
        params.append(dashboard_type)
    if status:
        conditions.append("status = %s")
        params.append(status)
    params.extend([limit, offset])

    sql = f"""
        SELECT d.*,
               (SELECT COUNT(*) FROM public.quantyx_dashboard_charts dc
                 WHERE dc.dashboard_id = d.dashboard_id) AS chart_count
          FROM public.quantyx_dashboards d
         WHERE {" AND ".join(conditions)}
         ORDER BY d.updated_at DESC
         LIMIT %s OFFSET %s
    """
    c = _conn(settings)
    try:
        with c.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
        return [dict(r) for r in rows]
    except (psycopg2.errors.UndefinedTable, psycopg2.errors.UndefinedColumn):
        return []
    finally:
        c.close()


def update_dashboard(
    settings: Settings,
    dashboard_id: str,
    *,
    name: str | None = None,
    description: str | None = None,
    status: str | None = None,
    run_id: str | None = None,
    latest_refresh_id: str | None = None,
    quality_score: float | None = None,
    quality_gate_passed: bool | None = None,
    chart_plan: list | dict | None = None,
) -> dict | None:
    updates = ["updated_at = now()"]
    params: list[Any] = []
    if name is not None:
        updates.append("name = %s"); params.append(name)
    if description is not None:
        updates.append("description = %s"); params.append(description)
    if status is not None:
        updates.append("status = %s"); params.append(status)
    if run_id is not None:
        updates.append("run_id = %s"); params.append(run_id)
    if latest_refresh_id is not None:
        updates.append("latest_refresh_id = %s"); params.append(latest_refresh_id)
    if quality_score is not None:
        updates.append("quality_score = %s"); params.append(quality_score)
    if quality_gate_passed is not None:
        updates.append("quality_gate_passed = %s"); params.append(quality_gate_passed)
    if chart_plan is not None:
        updates.append("chart_plan = %s::jsonb"); params.append(json.dumps(chart_plan, default=_json_default))
    params.append(dashboard_id)

    sql = f"""
        UPDATE public.quantyx_dashboards
           SET {", ".join(updates)}
         WHERE dashboard_id = %s
        RETURNING *
    """
    c = _conn(settings)
    try:
        with c.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
        c.commit()
        return dict(row) if row else None
    except (psycopg2.errors.UndefinedTable, psycopg2.errors.UndefinedColumn):
        return None
    finally:
        c.close()


def delete_dashboard(
    settings: Settings,
    dashboard_id: str,
    tenant_id: str | None = None,
) -> bool:
    conditions = "WHERE dashboard_id = %s"
    params: list[Any] = [dashboard_id]
    if tenant_id:
        conditions += " AND tenant_id = %s"
        params.append(tenant_id)
    sql = f"DELETE FROM public.quantyx_dashboards {conditions}"
    c = _conn(settings)
    try:
        with c.cursor() as cur:
            cur.execute(sql, params)
            deleted = cur.rowcount > 0
        c.commit()
        return deleted
    except (psycopg2.errors.UndefinedTable, psycopg2.errors.UndefinedColumn):
        return False
    finally:
        c.close()


# ---------------------------------------------------------------------------
# Chart links
# ---------------------------------------------------------------------------

def add_chart(
    settings: Settings,
    dashboard_id: str,
    chart_id: str,
    *,
    position: int | None = None,
    title_override: str | None = None,
    added_by: str | None = None,
) -> dict:
    entry_id = f"dc_{uuid.uuid4().hex[:10]}"
    # Auto-assign next position if not supplied
    if position is None:
        pos_sql = """
            SELECT COALESCE(MAX(position) + 1, 0)
              FROM public.quantyx_dashboard_charts
             WHERE dashboard_id = %s
        """
    insert_sql = """
        INSERT INTO public.quantyx_dashboard_charts
          (entry_id, dashboard_id, chart_id, position, title_override, added_by)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (dashboard_id, chart_id) DO NOTHING
        RETURNING *
    """
    c = _conn(settings)
    try:
        with c.cursor(cursor_factory=RealDictCursor) as cur:
            if position is None:
                cur.execute(pos_sql, [dashboard_id])
                # position = cur.fetchone()[0]
                position = cur.fetchone()["coalesce"]
            cur.execute(insert_sql, [entry_id, dashboard_id, chart_id, position, title_override, added_by])
            row = cur.fetchone()
        c.commit()
        return dict(row) if row else {"entry_id": entry_id, "dashboard_id": dashboard_id, "chart_id": chart_id}
    except (psycopg2.errors.UndefinedTable, psycopg2.errors.UndefinedColumn,
            psycopg2.errors.ForeignKeyViolation):
        return {"entry_id": entry_id, "dashboard_id": dashboard_id, "chart_id": chart_id}
    finally:
        c.close()


def remove_chart(settings: Settings, dashboard_id: str, chart_id: str) -> bool:
    sql = "DELETE FROM public.quantyx_dashboard_charts WHERE dashboard_id = %s AND chart_id = %s"
    c = _conn(settings)
    try:
        with c.cursor() as cur:
            cur.execute(sql, [dashboard_id, chart_id])
            deleted = cur.rowcount > 0
        c.commit()
        return deleted
    except (psycopg2.errors.UndefinedTable, psycopg2.errors.UndefinedColumn):
        return False
    finally:
        c.close()


def reorder_charts(settings: Settings, dashboard_id: str, ordered_chart_ids: list[str]) -> list[dict]:
    c = _conn(settings)
    try:
        with c.cursor(cursor_factory=RealDictCursor) as cur:
            for pos, cid in enumerate(ordered_chart_ids):
                cur.execute(
                    "UPDATE public.quantyx_dashboard_charts SET position = %s WHERE dashboard_id = %s AND chart_id = %s",
                    [pos, dashboard_id, cid],
                )
            cur.execute(
                "SELECT * FROM public.quantyx_dashboard_charts WHERE dashboard_id = %s ORDER BY position",
                [dashboard_id],
            )
            rows = cur.fetchall()
        c.commit()
        return [dict(r) for r in rows]
    except (psycopg2.errors.UndefinedTable, psycopg2.errors.UndefinedColumn):
        return []
    finally:
        c.close()


def get_dashboard_with_charts(
    settings: Settings,
    dashboard_id: str,
    tenant_id: str | None = None,
) -> dict | None:
    dashboard = get_dashboard(settings, dashboard_id, tenant_id=tenant_id)
    if not dashboard:
        return None
    sql = """
        SELECT dc.entry_id, dc.chart_id, dc.position, dc.title_override, dc.added_by, dc.added_at,
               cr.chart_type, cr.title, cr.chart_source, cr.status,
               cr.chart_payload, cr.rows_json, cr.question,
               cr.sql, cr.params, cr.query_payload, cr.chart_data, cr.insight_text, cr.narrative_text,
               cr.interaction_context_json, cr.lineage_json,
               cr.parent_chart_id, cr.root_chart_id,
               cr.drill_hierarchy_id, cr.drill_level_id
          FROM public.quantyx_dashboard_charts dc
          LEFT JOIN public.quantyx_chart_requests cr ON cr.chart_id = dc.chart_id
         WHERE dc.dashboard_id = %s
         ORDER BY dc.position ASC
    """
    c = _conn(settings)
    try:
        with c.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, [dashboard_id])
            charts = [dict(r) for r in cur.fetchall()]
    except (psycopg2.errors.UndefinedTable, psycopg2.errors.UndefinedColumn):
        charts = []
    finally:
        c.close()
    dashboard["charts"] = charts
    return dashboard
