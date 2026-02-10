from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import psycopg2
from psycopg2.extras import RealDictCursor

from services.ai.config import Settings
from services.ai.db import execute_non_query, run_query


def _json_fallback(value: object) -> str | float:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return str(value)


def _hash_payload(payload: dict) -> str:
    serialized = json.dumps(payload, sort_keys=True, default=_json_fallback).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def register_pack_version(
    settings: Settings,
    industry: str,
    version: str,
    release_date: str | None,
    breaking_changes: str | None,
    notes: str | None,
) -> None:
    sql = """
        INSERT INTO public.quantyx_pack_versions
          (pack_id, industry, version, release_date, breaking_changes, notes)
        VALUES
          (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (pack_id)
        DO NOTHING
    """
    pack_id = f"pack_{uuid.uuid4().hex[:10]}"
    params = [pack_id, industry, version, release_date, breaking_changes, notes]
    try:
        execute_non_query(settings, sql, params)
    except psycopg2.errors.UndefinedTable:
        return


def store_semantic_contract(
    settings: Settings,
    tenant_id: str,
    industry: str,
    version: str,
    payload: dict[str, Any],
    status: str = "active",
) -> str:
    contract_id = f"contract_{uuid.uuid4().hex[:12]}"
    sql = """
        INSERT INTO public.quantyx_semantic_contracts
          (contract_id, tenant_id, industry, version, payload, hash, status)
        VALUES
          (%s, %s, %s, %s, %s::jsonb, %s, %s)
    """
    payload_json = json.dumps(payload, default=_json_fallback)
    payload_hash = _hash_payload(payload)
    params = [contract_id, tenant_id, industry, version, payload_json, payload_hash, status]
    try:
        execute_non_query(settings, sql, params)
    except psycopg2.errors.UndefinedTable:
        return contract_id
    return contract_id


def get_active_semantic_contract(
    settings: Settings,
    tenant_id: str,
    industry: str,
) -> dict[str, Any] | None:
    sql = """
        SELECT contract_id, tenant_id, industry, version, payload, hash, status, created_at
          FROM public.quantyx_semantic_contracts
         WHERE tenant_id = %s
           AND industry = %s
           AND status = 'active'
         ORDER BY created_at DESC
         LIMIT 1
    """
    try:
        rows = run_query(settings, sql, [tenant_id, industry])
    except psycopg2.errors.UndefinedTable:
        return None
    if not rows:
        return None
    return rows[0]


def get_semantic_contract(settings: Settings, contract_id: str) -> dict[str, Any] | None:
    sql = """
        SELECT contract_id, tenant_id, industry, version, payload, hash, status, created_at
          FROM public.quantyx_semantic_contracts
         WHERE contract_id = %s
    """
    try:
        rows = run_query(settings, sql, [contract_id])
    except psycopg2.errors.UndefinedTable:
        return None
    if not rows:
        return None
    return rows[0]


def update_contract_status(settings: Settings, contract_id: str, status: str) -> None:
    sql = """
        UPDATE public.quantyx_semantic_contracts
           SET status = %s
         WHERE contract_id = %s
    """
    try:
        execute_non_query(settings, sql, [status, contract_id])
    except psycopg2.errors.UndefinedTable:
        return


def list_pack_versions(settings: Settings, industry: str | None = None) -> list[dict]:
    filters = []
    params: list[object] = []
    if industry:
        filters.append("industry = %s")
        params.append(industry)
    where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
    sql = f"""
        SELECT pack_id, industry, version, release_date, breaking_changes, notes, created_at
          FROM public.quantyx_pack_versions
          {where_clause}
         ORDER BY industry, version
    """
    try:
        return run_query(settings, sql, params)
    except psycopg2.errors.UndefinedTable:
        return []


def validate_semantic_payload(payload: dict[str, Any]) -> list[dict]:
    errors = []
    if "ontology" in payload and not isinstance(payload["ontology"], dict):
        errors.append({"field": "ontology", "issue": "must be object"})
    if "datasets" in payload and not isinstance(payload["datasets"], dict):
        errors.append({"field": "datasets", "issue": "must be object"})
    if "metric_definitions" in payload and not isinstance(payload["metric_definitions"], list):
        errors.append({"field": "metric_definitions", "issue": "must be list"})
    if "dataset_definitions" in payload and not isinstance(payload["dataset_definitions"], list):
        errors.append({"field": "dataset_definitions", "issue": "must be list"})
    return errors
