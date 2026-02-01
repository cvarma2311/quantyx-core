
from __future__ import annotations

from fastapi import HTTPException

from services.ai.config import Settings
from services.ai.db import execute_non_query


def upsert_entity_override(settings: Settings, tenant_id: str, domain_id: str, payload: dict) -> None:
    if not payload.get("entity_id"):
        raise HTTPException(status_code=400, detail="entity_id is required")

    sql = """
    INSERT INTO public.quantyx_entity_overrides
      (tenant_id, domain_id, entity_id, description, join_key, examples, updated_at)
    VALUES
      (%s, %s, %s, %s, %s, %s, now())
    ON CONFLICT (tenant_id, domain_id, entity_id)
    DO UPDATE SET
      description = EXCLUDED.description,
      join_key = EXCLUDED.join_key,
      examples = EXCLUDED.examples,
      updated_at = now()
    """
    params = (
        tenant_id,
        domain_id,
        payload["entity_id"],
        payload.get("description"),
        payload.get("join_key"),
        payload.get("examples"),
    )
    execute_non_query(settings, sql, list(params))


def upsert_hierarchy_override(settings: Settings, tenant_id: str, domain_id: str, payload: dict) -> None:
    if not payload.get("hierarchy_name"):
        raise HTTPException(status_code=400, detail="hierarchy_name is required")

    sql = """
    INSERT INTO public.quantyx_hierarchy_overrides
      (tenant_id, domain_id, hierarchy_name, levels, description, updated_at)
    VALUES
      (%s, %s, %s, %s, %s, now())
    ON CONFLICT (tenant_id, domain_id, hierarchy_name)
    DO UPDATE SET
      levels = EXCLUDED.levels,
      description = EXCLUDED.description,
      updated_at = now()
    """
    params = (
        tenant_id,
        domain_id,
        payload["hierarchy_name"],
        payload.get("levels", []),
        payload.get("description"),
    )
    execute_non_query(settings, sql, list(params))
