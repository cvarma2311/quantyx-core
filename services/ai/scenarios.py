from __future__ import annotations

import uuid
from typing import Any

import psycopg2

from services.ai.config import Settings
from services.ai.db import execute_non_query, run_query


def list_scenarios(settings: Settings, domain_id: str | None = None) -> list[dict[str, Any]]:
    sql = """
    SELECT scenario_id, domain_id, name, description, status, is_baseline, created_at
    FROM public.quantyx_scenario
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


def get_scenario(settings: Settings, scenario_id: str) -> dict[str, Any] | None:
    sql = """
    SELECT *
    FROM public.quantyx_scenario
    WHERE scenario_id = %s
    """
    try:
        rows = run_query(settings, sql, [scenario_id])
    except psycopg2.errors.UndefinedTable:
        return None
    return rows[0] if rows else None


def create_scenario(settings: Settings, payload: dict[str, Any]) -> str:
    scenario_id = payload.get("scenario_id") or f"scen_{uuid.uuid4().hex[:8]}"
    sql = """
    INSERT INTO public.quantyx_scenario
      (scenario_id, domain_id, name, description, status, is_baseline, created_by)
    VALUES
      (%s, %s, %s, %s, %s, %s, %s)
    """
    params = [
        scenario_id,
        payload.get("domain_id"),
        payload.get("name"),
        payload.get("description"),
        payload.get("status", "live"),
        payload.get("is_baseline", False),
        payload.get("created_by"),
    ]
    try:
        execute_non_query(settings, sql, params)
    except psycopg2.errors.UndefinedTable:
        return scenario_id
    return scenario_id


def update_scenario(settings: Settings, scenario_id: str, updates: dict[str, Any]) -> None:
    allowed = {"name", "description", "status", "is_baseline"}
    filtered = {key: value for key, value in updates.items() if key in allowed}
    if not filtered:
        return
    columns = []
    params: list[Any] = []
    for key, value in filtered.items():
        columns.append(f"{key} = %s")
        params.append(value)
    params.append(scenario_id)
    sql = f"UPDATE public.quantyx_scenario SET {', '.join(columns)} WHERE scenario_id = %s"
    try:
        execute_non_query(settings, sql, params)
    except psycopg2.errors.UndefinedTable:
        return


def run_scenario(settings: Settings, scenario_id: str, parameters: dict[str, Any]) -> None:
    sql = """
    INSERT INTO public.quantyx_scenario_inputs
      (scenario_id, parameter, value)
    VALUES
      (%s, %s, %s::jsonb)
    """
    try:
        for key, value in parameters.items():
            execute_non_query(settings, sql, [scenario_id, key, value])
    except psycopg2.errors.UndefinedTable:
        return


def compare_scenarios(
    settings: Settings,
    base_scenario_id: str,
    compare_scenario_id: str,
    metric_name: str,
) -> float | None:
    sql = """
    SELECT
      SUM(CASE WHEN scenario_id = %s THEN value::numeric END) AS base_value,
      SUM(CASE WHEN scenario_id = %s THEN value::numeric END) AS compare_value
    FROM public.quantyx_scenario_outputs
    WHERE metric_key = %s
    """
    try:
        rows = run_query(settings, sql, [base_scenario_id, compare_scenario_id, metric_name])
    except psycopg2.errors.UndefinedTable:
        return None
    if not rows:
        return None
    base_value = rows[0].get("base_value")
    compare_value = rows[0].get("compare_value")
    if base_value is None or compare_value is None:
        return None
    return float(compare_value) - float(base_value)
