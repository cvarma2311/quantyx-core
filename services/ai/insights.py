from __future__ import annotations

import uuid
from typing import Any

import psycopg2

from services.ai.config import Settings
from services.ai.db import execute_non_query, run_query


def _fetch_monthly_sales(settings: Settings) -> list[dict[str, Any]]:
    sql = f"""
    WITH monthly AS (
      SELECT date_trunc('month', sales_date) AS month, SUM(sales_tmt) AS sales_tmt
      FROM {settings.db_schema}.fact_hpcl_sales_daily
      GROUP BY 1
    )
    SELECT month, sales_tmt
    FROM monthly
    ORDER BY month DESC
    LIMIT 2
    """
    return run_query(settings, sql, [])


def generate_variance_insight(settings: Settings, domain_id: str, scenario_id: str | None = None) -> dict[str, Any] | None:
    try:
        rows = _fetch_monthly_sales(settings)
    except psycopg2.errors.UndefinedTable:
        return None

    if len(rows) < 2:
        return None

    current, previous = rows[0], rows[1]
    current_value = float(current.get("sales_tmt") or 0)
    previous_value = float(previous.get("sales_tmt") or 0)
    if previous_value == 0:
        return None

    change = (current_value - previous_value) / previous_value
    pct = round(change * 100, 2)
    direction = "increased" if pct >= 0 else "decreased"
    severity = "low" if abs(pct) < 3 else "medium" if abs(pct) < 8 else "high"

    insight = {
        "insight_id": f"ins_{uuid.uuid4().hex[:8]}",
        "domain_id": domain_id,
        "scenario_id": scenario_id,
        "insight_type": "variance",
        "headline": f"Sales volume {direction} {abs(pct)}% vs last month",
        "severity": severity,
        "confidence": 0.7,
        "entity_scope": None,
        "metric_refs": ["total_sales_volume_tmt"],
        "drivers": None,
        "recommended_actions": None,
        "supporting_query_ids": None,
    }
    return insight


def persist_insight(settings: Settings, insight: dict[str, Any]) -> None:
    sql = """
    INSERT INTO public.quantyx_insight_events
      (insight_id, domain_id, scenario_id, insight_type, headline, severity, confidence,
       entity_scope, metric_refs, drivers, recommended_actions, supporting_query_ids)
    VALUES
      (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s::jsonb, %s::jsonb, %s)
    ON CONFLICT (insight_id) DO NOTHING
    """
    params = [
        insight["insight_id"],
        insight.get("domain_id"),
        insight.get("scenario_id"),
        insight.get("insight_type"),
        insight.get("headline"),
        insight.get("severity"),
        insight.get("confidence"),
        None if insight.get("entity_scope") is None else insight["entity_scope"],
        insight.get("metric_refs"),
        None if insight.get("drivers") is None else insight["drivers"],
        None if insight.get("recommended_actions") is None else insight["recommended_actions"],
        insight.get("supporting_query_ids"),
    ]
    try:
        execute_non_query(settings, sql, params)
    except psycopg2.errors.UndefinedTable:
        return


def list_insights(settings: Settings, domain_id: str | None = None) -> list[dict[str, Any]]:
    sql = """
    SELECT insight_id, created_at, domain_id, scenario_id, insight_type, headline, severity, confidence
    FROM public.quantyx_insight_events
    """
    params: list[Any] = []
    if domain_id:
        sql += " WHERE domain_id = %s"
        params.append(domain_id)
    sql += " ORDER BY created_at DESC"
    try:
        return run_query(settings, sql, params)
    except psycopg2.errors.UndefinedTable:
        return []


def get_insight(settings: Settings, insight_id: str) -> dict[str, Any] | None:
    sql = """
    SELECT *
    FROM public.quantyx_insight_events
    WHERE insight_id = %s
    """
    try:
        rows = run_query(settings, sql, [insight_id])
    except psycopg2.errors.UndefinedTable:
        return None
    return rows[0] if rows else None
