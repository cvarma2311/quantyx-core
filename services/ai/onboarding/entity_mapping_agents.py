from __future__ import annotations

import json
import uuid
from typing import Any

import psycopg2

from services.ai.config import Settings
from services.ai.db import execute_non_query


def persist_entity_mapping_agent(
    settings: Settings,
    *,
    job_id: str | None,
    mapping_id: str | None,
    tenant_id: str,
    domain_id: str,
    connection_id: str,
    database_name: str,
    schema_name: str,
    table_name: str | None,
    chunk_index: int | None,
    chunk_label: str | None,
    request_payload: dict[str, Any],
    response_payload: dict[str, Any] | None,
    error_message: str | None,
) -> str:
    agent_run_id = f"emap_{uuid.uuid4().hex[:10]}"
    sql = """
        INSERT INTO public.quantyx_entity_mapping_agents (
          agent_run_id,
          job_id,
          mapping_id,
          tenant_id,
          domain_id,
          connection_id,
          database_name,
          schema_name,
          table_name,
          chunk_index,
          chunk_label,
          request_payload,
          response_payload,
          error_message,
          created_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, now())
    """
    params = [
        agent_run_id,
        job_id,
        mapping_id,
        tenant_id,
        domain_id,
        connection_id,
        database_name,
        schema_name,
        table_name,
        chunk_index,
        chunk_label,
        json.dumps(request_payload),
        json.dumps(response_payload) if response_payload is not None else None,
        error_message,
    ]
    try:
        execute_non_query(settings, sql, params)
    except psycopg2.errors.UndefinedTable:
        return agent_run_id
    return agent_run_id


def attach_mapping_id_to_agents(
    settings: Settings,
    *,
    job_id: str,
    mapping_id: str,
) -> None:
    sql = """
        UPDATE public.quantyx_entity_mapping_agents
           SET mapping_id = %s
         WHERE job_id = %s
           AND mapping_id IS NULL
    """
    try:
        execute_non_query(settings, sql, [mapping_id, job_id])
    except psycopg2.errors.UndefinedTable:
        return
