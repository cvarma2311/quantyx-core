from __future__ import annotations

import uuid
from typing import Any

from services.ai.config import Settings
from services.ai.db import execute_non_query, execute_returning_query, run_query


# ---------------------------------------------------------------------------
# Dashboard CRUD
# ---------------------------------------------------------------------------


def create_user_dashboard(
    settings: Settings,
    *,
    tenant_id: str,
    domain_id: str,
    name: str,
    description: str | None = None,
    created_by: str | None = None,
) -> dict[str, Any]:
    dashboard_id = f"udash_{uuid.uuid4().hex[:10]}"
    rows = execute_returning_query(
        settings,
        """
        INSERT INTO public.quantyx_user_dashboards (
          dashboard_id, tenant_id, domain_id, name, description, status, created_by, created_at, updated_at
        )
        VALUES (%s, %s, %s, %s, %s, 'active', %s, now(), now())
        RETURNING dashboard_id, tenant_id, domain_id, name, description, status, created_by, created_at, updated_at
        """,
        [dashboard_id, tenant_id, domain_id, name, description, created_by],
    )
    row = dict(rows[0])
    row["chart_count"] = 0
    return row


def get_user_dashboard(
    settings: Settings,
    dashboard_id: str,
    tenant_id: str | None = None,
) -> dict[str, Any] | None:
    filters = ["d.dashboard_id = %s"]
    params: list[Any] = [dashboard_id]
    if tenant_id is not None:
        filters.append("d.tenant_id = %s")
        params.append(tenant_id)
    rows = run_query(
        settings,
        f"""
        SELECT d.dashboard_id, d.tenant_id, d.domain_id, d.name, d.description,
               d.status, d.created_by, d.created_at, d.updated_at,
               COALESCE(c.chart_count, 0) AS chart_count
          FROM public.quantyx_user_dashboards d
          LEFT JOIN (
            SELECT dashboard_id, COUNT(*)::int AS chart_count
              FROM public.quantyx_user_dashboard_charts
             GROUP BY dashboard_id
          ) c ON c.dashboard_id = d.dashboard_id
         WHERE {' AND '.join(filters)}
         LIMIT 1
        """,
        params,
    )
    return rows[0] if rows else None


def list_user_dashboards(
    settings: Settings,
    tenant_id: str,
    domain_id: str | None = None,
    status: str = "active",
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    filters = ["d.tenant_id = %s"]
    params: list[Any] = [tenant_id]
    if domain_id is not None:
        filters.append("d.domain_id = %s")
        params.append(domain_id)
    if status:
        filters.append("d.status = %s")
        params.append(status)
    params.extend([limit, offset])
    return run_query(
        settings,
        f"""
        SELECT d.dashboard_id, d.tenant_id, d.domain_id, d.name, d.description,
               d.status, d.created_by, d.created_at, d.updated_at,
               COALESCE(c.chart_count, 0) AS chart_count
          FROM public.quantyx_user_dashboards d
          LEFT JOIN (
            SELECT dashboard_id, COUNT(*)::int AS chart_count
              FROM public.quantyx_user_dashboard_charts
             GROUP BY dashboard_id
          ) c ON c.dashboard_id = d.dashboard_id
         WHERE {' AND '.join(filters)}
         ORDER BY d.updated_at DESC
         LIMIT %s OFFSET %s
        """,
        params,
    )


def update_user_dashboard(
    settings: Settings,
    dashboard_id: str,
    *,
    name: str | None = None,
    description: str | None = None,
    status: str | None = None,
) -> dict[str, Any] | None:
    updates: list[str] = []
    params: list[Any] = []
    if name is not None:
        updates.append("name = %s")
        params.append(name)
    if description is not None:
        updates.append("description = %s")
        params.append(description)
    if status is not None:
        updates.append("status = %s")
        params.append(status)
    if updates:
        updates.append("updated_at = now()")
        params.append(dashboard_id)
        execute_non_query(
            settings,
            f"UPDATE public.quantyx_user_dashboards SET {', '.join(updates)} WHERE dashboard_id = %s",
            params,
        )
    return get_user_dashboard(settings, dashboard_id)


def delete_user_dashboard(
    settings: Settings,
    dashboard_id: str,
    *,
    permanent: bool = False,
) -> bool:
    if permanent:
        execute_non_query(
            settings,
            "DELETE FROM public.quantyx_user_dashboards WHERE dashboard_id = %s",
            [dashboard_id],
        )
    else:
        execute_non_query(
            settings,
            "UPDATE public.quantyx_user_dashboards SET status = 'archived', updated_at = now() WHERE dashboard_id = %s",
            [dashboard_id],
        )
    return True


# ---------------------------------------------------------------------------
# Chart membership
# ---------------------------------------------------------------------------


def _next_chart_position(settings: Settings, dashboard_id: str) -> int:
    rows = run_query(
        settings,
        "SELECT COALESCE(MAX(position), -1) AS max_pos FROM public.quantyx_user_dashboard_charts WHERE dashboard_id = %s",
        [dashboard_id],
    )
    return int((rows[0].get("max_pos") if rows else -1) or -1) + 1


def add_chart_to_dashboard(
    settings: Settings,
    dashboard_id: str,
    chart_id: str,
    position: int | None = None,
    added_by: str | None = None,
) -> dict[str, Any]:
    if position is None:
        position = _next_chart_position(settings, dashboard_id)
    entry_id = f"dce_{uuid.uuid4().hex[:10]}"
    rows = execute_returning_query(
        settings,
        """
        INSERT INTO public.quantyx_user_dashboard_charts (
          entry_id, dashboard_id, chart_id, position, added_by, added_at
        )
        VALUES (%s, %s, %s, %s, %s, now())
        RETURNING entry_id, dashboard_id, chart_id, position, added_by, added_at
        """,
        [entry_id, dashboard_id, chart_id, position, added_by],
    )
    execute_non_query(
        settings,
        "UPDATE public.quantyx_user_dashboards SET updated_at = now() WHERE dashboard_id = %s",
        [dashboard_id],
    )
    return rows[0]


def remove_chart_from_dashboard(
    settings: Settings,
    dashboard_id: str,
    chart_id: str,
) -> bool:
    execute_non_query(
        settings,
        "DELETE FROM public.quantyx_user_dashboard_charts WHERE dashboard_id = %s AND chart_id = %s",
        [dashboard_id, chart_id],
    )
    execute_non_query(
        settings,
        "UPDATE public.quantyx_user_dashboards SET updated_at = now() WHERE dashboard_id = %s",
        [dashboard_id],
    )
    return True


def reorder_dashboard_charts(
    settings: Settings,
    dashboard_id: str,
    ordered_chart_ids: list[str],
) -> list[dict[str, Any]]:
    for position, chart_id in enumerate(ordered_chart_ids):
        execute_non_query(
            settings,
            "UPDATE public.quantyx_user_dashboard_charts SET position = %s WHERE dashboard_id = %s AND chart_id = %s",
            [position, dashboard_id, chart_id],
        )
    execute_non_query(
        settings,
        "UPDATE public.quantyx_user_dashboards SET updated_at = now() WHERE dashboard_id = %s",
        [dashboard_id],
    )
    return [{"position": i, "chart_id": cid} for i, cid in enumerate(ordered_chart_ids)]


def get_dashboard_with_charts(
    settings: Settings,
    dashboard_id: str,
    tenant_id: str | None = None,
    include_chart_data: bool = True,
) -> dict[str, Any] | None:
    dash = get_user_dashboard(settings, dashboard_id, tenant_id=tenant_id)
    if dash is None:
        return None

    if include_chart_data:
        chart_rows = run_query(
            settings,
            """
            SELECT dc.entry_id,
                   dc.position,
                   dc.chart_id,
                   dc.added_by,
                   dc.added_at,
                   cr.chart_type,
                   cr.question    AS title,
                   cr.metric,
                   cr.status,
                   cr.chart_payload,
                   cr.chart_data
              FROM public.quantyx_user_dashboard_charts dc
              LEFT JOIN public.quantyx_chart_requests cr ON cr.chart_id = dc.chart_id
             WHERE dc.dashboard_id = %s
             ORDER BY dc.position ASC
            """,
            [dashboard_id],
        )
    else:
        chart_rows = run_query(
            settings,
            """
            SELECT dc.entry_id, dc.position, dc.chart_id, dc.added_by, dc.added_at
              FROM public.quantyx_user_dashboard_charts dc
             WHERE dc.dashboard_id = %s
             ORDER BY dc.position ASC
            """,
            [dashboard_id],
        )

    result = dict(dash)
    result["charts"] = [dict(r) for r in chart_rows]
    return result
