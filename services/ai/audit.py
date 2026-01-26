from __future__ import annotations

import hashlib
import json
import uuid

import psycopg2

from services.ai.config import Settings
from services.ai.db import execute_non_query


def log_query_audit(
    settings: Settings,
    question: str | None,
    metrics: list[str],
    dimensions: list[str],
    filters: list[dict],
    sql_text: str | None,
    execution_ms: int | None,
    row_count: int | None,
    error_message: str | None = None,
    domain_id: str | None = None,
    scenario_id: str | None = None,
    asked_by: str | None = None,
) -> None:
    query_id = str(uuid.uuid4())
    sql_hash = None
    if sql_text:
        sql_hash = hashlib.sha256(sql_text.encode("utf-8")).hexdigest()
    payload_sql = """
    INSERT INTO public.quantyx_query_audit
      (query_id, asked_by, domain_id, scenario_id, question, resolved_metrics, resolved_dimensions, resolved_filters,
       sql_text, sql_hash, execution_ms, row_count, error_message)
    VALUES
      (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s)
    """
    params = [
        query_id,
        asked_by,
        domain_id,
        scenario_id,
        question,
        metrics,
        dimensions,
        json.dumps(filters),
        sql_text,
        sql_hash,
        execution_ms,
        row_count,
        error_message,
    ]
    try:
        execute_non_query(settings, payload_sql, params)
    except psycopg2.errors.UndefinedTable:
        return
