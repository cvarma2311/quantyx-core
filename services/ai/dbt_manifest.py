from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from uuid import uuid4
from typing import Any
import shutil
import tempfile
import re

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
    if shutil.which("dbt") is None:
        raise RuntimeError("dbt binary not found in PATH")
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
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            env=None,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("dbt binary not found in PATH") from exc
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
    project_name = _sanitize_project_name(project_dir.name)
    if project_file.exists():
        content = project_file.read_text()
        updated = False
        if "name:" in content and not _is_valid_project_name(_extract_project_name(content)):
            content = _replace_project_name(content, project_name)
            updated = True
        profile_value = normalize_profile_name(profile_name or "default")
        if "profile:" in content:
            content = _replace_profile_name(content, profile_value)
            updated = True
        if updated:
            project_file.write_text(content)
        return
    models_dir = project_dir / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    (models_dir / ".gitkeep").touch()
    packages_file = project_dir / "packages.yml"
    if not packages_file.exists():
        packages_file.write_text("packages: []\n")
    profile_value = normalize_profile_name(profile_name or "default")
    project_file.write_text(
        "\n".join(
            [
                f"name: {project_name}",
                "version: '1.0'",
                "config-version: 2",
                f"profile: \"{profile_value}\"",
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


def _extract_project_name(content: str) -> str:
    for line in content.splitlines():
        if line.strip().startswith("name:"):
            return line.split(":", 1)[1].strip().strip("'\"")
    return ""


def _replace_project_name(content: str, project_name: str) -> str:
    lines = []
    replaced = False
    for line in content.splitlines():
        if line.strip().startswith("name:") and not replaced:
            lines.append(f"name: {project_name}")
            replaced = True
        else:
            lines.append(line)
    if not replaced:
        lines.insert(0, f"name: {project_name}")
    return "\n".join(lines)


def _replace_profile_name(content: str, profile_name: str) -> str:
    lines = []
    replaced = False
    for line in content.splitlines():
        if line.strip().startswith("profile:") and not replaced:
            lines.append(f"profile: \"{normalize_profile_name(profile_name)}\"")
            replaced = True
        else:
            lines.append(line)
    if not replaced:
        lines.insert(1, f"profile: \"{normalize_profile_name(profile_name)}\"")
    return "\n".join(lines)


def _is_valid_project_name(name: str) -> bool:
    return bool(re.match(r"^[^\\d\\W]\\w*$", name))


def _sanitize_project_name(raw: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z_]+", "_", raw)
    if not cleaned or cleaned[0].isdigit():
        cleaned = f"dbt_tenant_{cleaned}"
    if not _is_valid_project_name(cleaned):
        cleaned = "dbt_project"
    return cleaned


def normalize_profile_name(raw: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z_]+", "_", raw)
    if not cleaned or cleaned[0].isdigit():
        cleaned = f"dbt_{cleaned}"
    return cleaned


def create_temp_profiles_dir(
    tenant_id: str,
    target_name: str,
    connection: dict[str, Any],
    database: str,
    schema: str,
) -> str:
    profiles_dir = tempfile.mkdtemp(prefix=f"dbt_profiles_{tenant_id}_")
    profiles_path = Path(profiles_dir) / "profiles.yml"
    profile_name = normalize_profile_name(tenant_id)
    profile_key = f"\"{profile_name}\""
    host = connection.get("host")
    port = connection.get("port")
    user = connection.get("user")
    password = connection.get("password")
    profile_yaml = "\n".join(
        [
            f"{profile_key}:",
            f"  target: {target_name}",
            "  outputs:",
            f"    {target_name}:",
            "      type: postgres",
            f"      host: {host}",
            f"      port: {port}",
            f"      user: {user}",
            f"      password: {password}",
            f"      dbname: {database}",
            f"      schema: {schema}",
            "",
        ]
    )
    profiles_path.write_text(profile_yaml)
    return profiles_dir


def resolve_dbt_project_dir(tenant_id: str | None) -> str:
    base_dir = os.getenv("DBT_PROJECT_BASE", "dbt_projects")
    if tenant_id:
        project_dir = f"dbt_{tenant_id}"
        legacy_dir = f"dbt-{tenant_id}"
    else:
        project_dir = f"dbt_{uuid4().hex[:6]}"
        legacy_dir = None
    path = Path(base_dir) / project_dir
    if legacy_dir:
        legacy_path = Path(base_dir) / legacy_dir
        if not path.exists() and legacy_path.exists():
            legacy_path.rename(path)
    path.mkdir(parents=True, exist_ok=True)
    return str(path)


def ensure_tenant_dbt_project(
    tenant_id: str,
    template_dir: str | None = None,
) -> str:
    project_dir = resolve_dbt_project_dir(tenant_id)
    project_path = Path(project_dir)
    project_file = project_path / "dbt_project.yml"
    if project_file.exists():
        ensure_dbt_project(project_dir, profile_name=tenant_id)
        return project_dir
    if template_dir:
        template_path = Path(template_dir)
        if template_path.exists():
            for item in template_path.iterdir():
                dest = project_path / item.name
                if dest.exists():
                    continue
                if item.is_dir():
                    shutil.copytree(item, dest)
                else:
                    shutil.copy2(item, dest)
            if project_file.exists():
                return project_dir
    ensure_dbt_project(project_dir, profile_name=tenant_id)
    return project_dir


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
        profile_name = normalize_profile_name(tenant_id)
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
    if "dbt-" in dbt_project_path and "dbt_" not in dbt_project_path:
        migrated_path = resolve_dbt_project_dir(tenant_id)
        if Path(dbt_project_path).exists() and not Path(migrated_path).exists():
            Path(dbt_project_path).rename(migrated_path)
        dbt_project_path = migrated_path
        try:
            execute_non_query(
                settings,
                "UPDATE public.quantyx_dbt_config SET dbt_project_path = %s, updated_at = now() WHERE config_id = %s",
                [dbt_project_path, config.get("config_id")],
            )
        except Exception:
            pass
    Path(dbt_project_path).mkdir(parents=True, exist_ok=True)
    config["dbt_project_path"] = dbt_project_path
    if config.get("profile_name"):
        config["profile_name"] = normalize_profile_name(config["profile_name"])
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
            json.dumps(manifest_json),
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
