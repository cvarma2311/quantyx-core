from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from uuid import uuid4
from typing import Any

from services.ai.config import Settings
from services.ai.db import execute_non_query, run_query


def run_dbt_compile(
    settings: Settings,
    dbt_project_path: str,
    profile_name: str,
    target_name: str,
    profiles_dir: str | None = None,
) -> dict[str, Any]:
    command = [
        "dbt",
        "compile",
        "--project-dir",
        dbt_project_path,
        "--profile",
        profile_name,
        "--target",
        target_name,
    ]
    if profiles_dir:
        command.extend(["--profiles-dir", profiles_dir])
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        env=None,
    )
    if result.returncode != 0:
        raise RuntimeError(f"dbt compile failed: {result.stderr.strip() or result.stdout.strip()}")
    manifest_path = Path(dbt_project_path) / "target" / "manifest.json"
    if not manifest_path.exists():
        raise RuntimeError("dbt manifest.json not found after compile")
    return json.loads(manifest_path.read_text())


def resolve_dbt_project_dir(tenant_id: str | None) -> str:
    base_dir = os.getenv("DBT_PROJECT_BASE", "dbt_projects")
    if tenant_id:
        project_dir = f"dbt-{tenant_id}"
    else:
        project_dir = f"dbt-{uuid4().hex[:6]}"
    path = Path(base_dir) / project_dir
    path.mkdir(parents=True, exist_ok=True)
    return str(path)


def upsert_tenant_project_dir(
    settings: Settings,
    tenant_id: str,
    domain_id: str,
    dbt_project_dir: str,
) -> None:
    sql = """
        INSERT INTO public.quantyx_tenant_dbt_projects (
          tenant_id,
          domain_id,
          dbt_project_dir,
          updated_at
        )
        VALUES (%s, %s, %s, now())
        ON CONFLICT (tenant_id, domain_id)
        DO UPDATE SET
          dbt_project_dir = EXCLUDED.dbt_project_dir,
          updated_at = now()
    """
    execute_non_query(settings, sql, [tenant_id, domain_id, dbt_project_dir])


def store_manifest(
    settings: Settings,
    tenant_id: str,
    domain_id: str,
    connection_id: str | None,
    dbt_project_path: str,
    profile_name: str,
    target_name: str,
    manifest_json: dict[str, Any],
) -> str:
    manifest_id = f"manifest_{uuid4().hex[:12]}"
    sql = """
        INSERT INTO public.quantyx_dbt_manifest (
          manifest_id,
          tenant_id,
          domain_id,
          connection_id,
          dbt_project_path,
          profile_name,
          target_name,
          manifest_json
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    """
    execute_non_query(
        settings,
        sql,
        [
            manifest_id,
            tenant_id,
            domain_id,
            connection_id,
            dbt_project_path,
            profile_name,
            target_name,
            manifest_json,
        ],
    )
    return manifest_id


def load_latest_manifest(
    settings: Settings,
    domain_id: str | None = None,
    tenant_id: str | None = None,
) -> dict[str, Any] | None:
    filters = []
    params: list[Any] = []
    if tenant_id:
        filters.append("tenant_id = %s")
        params.append(tenant_id)
    if domain_id:
        filters.append("domain_id = %s")
        params.append(domain_id)
    where_clause = ""
    if filters:
        where_clause = "WHERE " + " AND ".join(filters)
    sql = f"""
        SELECT manifest_json
          FROM public.quantyx_dbt_manifest
          {where_clause}
         ORDER BY created_at DESC
         LIMIT 1
    """
    rows = run_query(settings, sql, params)
    if not rows:
        return None
    return rows[0].get("manifest_json")


def load_latest_manifest_row(
    settings: Settings,
    domain_id: str | None = None,
    tenant_id: str | None = None,
) -> dict[str, Any] | None:
    filters = []
    params: list[Any] = []
    if tenant_id:
        filters.append("tenant_id = %s")
        params.append(tenant_id)
    if domain_id:
        filters.append("domain_id = %s")
        params.append(domain_id)
    where_clause = ""
    if filters:
        where_clause = "WHERE " + " AND ".join(filters)
    sql = f"""
        SELECT manifest_id,
               tenant_id,
               domain_id,
               connection_id,
               dbt_project_path,
               profile_name,
               target_name,
               manifest_json,
               created_at
          FROM public.quantyx_dbt_manifest
          {where_clause}
         ORDER BY created_at DESC
         LIMIT 1
    """
    rows = run_query(settings, sql, params)
    return rows[0] if rows else None
