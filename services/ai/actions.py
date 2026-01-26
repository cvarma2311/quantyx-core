from __future__ import annotations

import uuid
from typing import Any

import psycopg2

from services.ai.config import Settings
from services.ai.db import execute_non_query, run_query


def list_actions(settings: Settings, domain_id: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
    sql = """
    SELECT action_id, source_insight_id, domain_id, scenario_id, headline, severity, status, assigned_to, created_at
    FROM public.quantyx_actions
    """
    params: list[Any] = []
    filters = []
    if domain_id:
        filters.append("domain_id = %s")
        params.append(domain_id)
    if status:
        filters.append("status = %s")
        params.append(status)
    if filters:
        sql += " WHERE " + " AND ".join(filters)
    sql += " ORDER BY created_at DESC"
    try:
        return run_query(settings, sql, params)
    except psycopg2.errors.UndefinedTable:
        return []


def get_action(settings: Settings, action_id: str) -> dict[str, Any] | None:
    sql = """
    SELECT *
    FROM public.quantyx_actions
    WHERE action_id = %s
    """
    try:
        rows = run_query(settings, sql, [action_id])
    except psycopg2.errors.UndefinedTable:
        return None
    return rows[0] if rows else None


def create_action(settings: Settings, payload: dict[str, Any]) -> str:
    action_id = payload.get("action_id") or f"act_{uuid.uuid4().hex[:8]}"
    sql = """
    INSERT INTO public.quantyx_actions
      (action_id, source_insight_id, domain_id, scenario_id, headline, severity, status, assigned_to)
    VALUES
      (%s, %s, %s, %s, %s, %s, %s, %s)
    """
    params = [
        action_id,
        payload.get("source_insight_id"),
        payload.get("domain_id"),
        payload.get("scenario_id"),
        payload.get("headline"),
        payload.get("severity"),
        payload.get("status"),
        payload.get("assigned_to"),
    ]
    try:
        execute_non_query(settings, sql, params)
    except psycopg2.errors.UndefinedTable:
        return action_id
    return action_id


def update_action(settings: Settings, action_id: str, updates: dict[str, Any]) -> None:
    allowed = {"headline", "severity", "status", "assigned_to"}
    filtered = {key: value for key, value in updates.items() if key in allowed}
    if not filtered:
        return
    columns = []
    params: list[Any] = []
    for key, value in filtered.items():
        columns.append(f"{key} = %s")
        params.append(value)
    columns.append("updated_at = now()")
    params.append(action_id)
    sql = f"UPDATE public.quantyx_actions SET {', '.join(columns)} WHERE action_id = %s"
    try:
        execute_non_query(settings, sql, params)
    except psycopg2.errors.UndefinedTable:
        return


def create_feedback(settings: Settings, action_id: str, payload: dict[str, Any]) -> None:
    sql = """
    INSERT INTO public.quantyx_action_feedback
      (action_id, source_insight_id, domain_id, scenario_id, status, outcome, notes, impact_window, assigned_to)
    VALUES
      (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)
    ON CONFLICT (action_id)
    DO UPDATE SET
      status = EXCLUDED.status,
      outcome = EXCLUDED.outcome,
      notes = EXCLUDED.notes,
      impact_window = EXCLUDED.impact_window,
      assigned_to = EXCLUDED.assigned_to,
      updated_at = now()
    """
    params = [
        action_id,
        payload.get("source_insight_id"),
        payload.get("domain_id"),
        payload.get("scenario_id"),
        payload.get("status"),
        payload.get("outcome"),
        payload.get("notes"),
        payload.get("impact_window"),
        payload.get("assigned_to"),
    ]
    try:
        execute_non_query(settings, sql, params)
    except psycopg2.errors.UndefinedTable:
        return
