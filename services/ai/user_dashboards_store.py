"""
Deprecated shim — delegates to dashboards_store (Phase 44).
All callers should migrate to importing from services.ai.dashboards_store directly.
"""
from __future__ import annotations

from typing import Any

from services.ai.config import Settings
from services.ai.dashboards_store import (
    create_dashboard,
    get_dashboard,
    list_dashboards,
    update_dashboard,
    delete_dashboard,
    add_chart,
    remove_chart,
    reorder_charts,
    get_dashboard_with_charts as _get_dashboard_with_charts,
)


def create_user_dashboard(
    settings: Settings,
    *,
    tenant_id: str,
    domain_id: str,
    name: str,
    description: str | None = None,
    created_by: str | None = None,
) -> dict[str, Any]:
    return create_dashboard(
        settings,
        tenant_id=tenant_id,
        domain_id=domain_id,
        name=name,
        description=description,
        dashboard_type="user",
        created_by=created_by,
    )


def get_user_dashboard(
    settings: Settings,
    dashboard_id: str,
    tenant_id: str | None = None,
) -> dict[str, Any] | None:
    return get_dashboard(settings, dashboard_id, tenant_id=tenant_id)


def list_user_dashboards(
    settings: Settings,
    tenant_id: str,
    domain_id: str | None = None,
    status: str = "active",
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    return list_dashboards(
        settings, tenant_id, domain_id,
        dashboard_type="user", status=status, limit=limit, offset=offset,
    )


def update_user_dashboard(
    settings: Settings,
    dashboard_id: str,
    *,
    name: str | None = None,
    description: str | None = None,
    status: str | None = None,
) -> dict[str, Any] | None:
    return update_dashboard(
        settings, dashboard_id,
        name=name, description=description, status=status,
    )


def delete_user_dashboard(
    settings: Settings,
    dashboard_id: str,
    *,
    permanent: bool = False,
) -> bool:
    if permanent:
        return delete_dashboard(settings, dashboard_id)
    return bool(update_dashboard(settings, dashboard_id, status="archived"))


def add_chart_to_dashboard(
    settings: Settings,
    dashboard_id: str,
    chart_id: str,
    position: int | None = None,
    added_by: str | None = None,
) -> dict[str, Any]:
    return add_chart(settings, dashboard_id, chart_id, position=position, added_by=added_by)


def remove_chart_from_dashboard(
    settings: Settings,
    dashboard_id: str,
    chart_id: str,
) -> bool:
    return remove_chart(settings, dashboard_id, chart_id)


def reorder_dashboard_charts(
    settings: Settings,
    dashboard_id: str,
    ordered_chart_ids: list[str],
) -> list[dict[str, Any]]:
    return reorder_charts(settings, dashboard_id, ordered_chart_ids)


def get_dashboard_with_charts(
    settings: Settings,
    dashboard_id: str,
    tenant_id: str | None = None,
    include_chart_data: bool = True,
) -> dict[str, Any] | None:
    return _get_dashboard_with_charts(settings, dashboard_id, tenant_id=tenant_id)