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
    ensure_dbt_project(dbt_project_path, profile_name=profile_name)
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


def ensure_dbt_project(dbt_project_path: str, profile_name: str | None = None) -> None:
    project_dir = Path(dbt_project_path)
    project_dir.mkdir(parents=True, exist_ok=True)
    project_file = project_dir / "dbt_project.yml"
    if project_file.exists():
        return
    project_name = project_dir.name.replace(" ", "_")
    models_dir = project_dir / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    (models_dir / ".gitkeep").touch()
    packages_file = project_dir / "packages.yml"
    if not packages_file.exists():
        packages_file.write_text("packages: []\n")
    profile_value = profile_name or "default"
    project_file.write_text(
        "\n".join(
            [
                f"name: {project_name}",
                "version: '1.0'",
                "config-version: 2",
                f"profile: {profile_value}",
                "model-paths: ['models']",
                "analysis-paths: ['analyses']",
                "test-paths: ['tests']",
                "seed-paths: ['seeds']",
                "macro-paths: ['macros']",
                "snapshot-paths: ['snapshots']",
                "target-path: 'target'",
                "clean-targets: ['target', 'dbt_packages']",
                "",
            ]
        )
    )


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


def upsert_dbt_config(
    settings: Settings,
    tenant_id: str,
    domain_id: str,
    connection_id: str | None,
    dbt_project_path: str,
    profile_name: str,
    target_name: str,
    profiles_dir: str | None,
) -> str:
    existing = get_latest_dbt_config(settings, tenant_id, domain_id, connection_id)
    if existing and existing.get("config_id"):
        sql = """
            UPDATE public.quantyx_dbt_config
               SET dbt_project_path = %s,
                   profile_name = %s,
                   target_name = %s,
                   profiles_dir = %s,
                   updated_at = now()
             WHERE config_id = %s
        """
        execute_non_query(
            settings,
            sql,
            [dbt_project_path, profile_name, target_name, profiles_dir, existing["config_id"]],
        )
        return str(existing["config_id"])

    config_id = f"dbt_cfg_{uuid4().hex[:12]}"
    sql = """
        INSERT INTO public.quantyx_dbt_config (
          config_id,
          tenant_id,
          domain_id,
          connection_id,
          dbt_project_path,
          profile_name,
          target_name,
          profiles_dir,
          updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now())
    """
    execute_non_query(
        settings,
        sql,
        [
            config_id,
            tenant_id,
            domain_id,
            connection_id,
            dbt_project_path,
            profile_name,
            target_name,
            profiles_dir,
        ],
    )
    return config_id


def get_latest_dbt_config(
    settings: Settings,
    tenant_id: str,
    domain_id: str,
    connection_id: str | None = None,
) -> dict[str, Any] | None:
    filters = ["tenant_id = %s", "domain_id = %s"]
    params: list[Any] = [tenant_id, domain_id]
    if connection_id:
        filters.append("connection_id = %s")
        params.append(connection_id)
    else:
        filters.append("connection_id IS NULL")
    where_clause = " AND ".join(filters)
    sql = f"""
        SELECT config_id,
               tenant_id,
               domain_id,
               connection_id,
               dbt_project_path,
               profile_name,
               target_name,
               profiles_dir,
               created_at,
               updated_at
          FROM public.quantyx_dbt_config
         WHERE {where_clause}
         ORDER BY updated_at DESC
         LIMIT 1
    """
    rows = run_query(settings, sql, params)
    return rows[0] if rows else None


def resolve_dbt_config(
    settings: Settings,
    tenant_id: str,
    domain_id: str,
    connection_id: str | None = None,
) -> dict[str, Any]:
    config = get_latest_dbt_config(settings, tenant_id, domain_id, connection_id)
    if not config and connection_id:
        config = get_latest_dbt_config(settings, tenant_id, domain_id, None)
    if not config:
        dbt_project_path = resolve_dbt_project_dir(tenant_id)
        profile_name = tenant_id
        target_name = settings.dbt_target_name
        profiles_dir = settings.dbt_profiles_dir
        config = {
            "config_id": None,
            "tenant_id": tenant_id,
            "domain_id": domain_id,
            "connection_id": connection_id,
            "dbt_project_path": dbt_project_path,
            "profile_name": profile_name,
            "target_name": target_name,
            "profiles_dir": profiles_dir,
        }
        return config

    dbt_project_path = config.get("dbt_project_path") or resolve_dbt_project_dir(tenant_id)
    Path(dbt_project_path).mkdir(parents=True, exist_ok=True)
    config["dbt_project_path"] = dbt_project_path
    return config


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
