from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    db_host: str
    db_port: int
    db_name: str
    db_user: str
    db_password: str
    db_schema: str
    openai_api_key: str | None
    openai_model: str
    dbt_manifest_path: str
    metrics_catalog_path: str
    dbt_profile_name: str
    dbt_target_name: str
    dbt_profiles_dir: str | None
    dbt_project_template: str | None
    default_tenant_id: str
    default_domain_id: str
    workspace_query_plan_mode: str
    workspace_query_plan_model: str | None
    workspace_query_plan_timeout_sec: int


def load_settings() -> Settings:
    return Settings(
        db_host=os.getenv("DB_HOST", "localhost"),
        db_port=int(os.getenv("DB_PORT", "5432")),
        db_name=os.getenv("DB_NAME", "hpcl_ceg"),
        db_user=os.getenv("DB_USER", "ceg_user"),
        db_password=os.getenv("DB_PASSWORD", ""),
        db_schema=os.getenv("DB_SCHEMA", "public"),
        openai_api_key=os.getenv("OPENAI_API_KEY"),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        dbt_manifest_path=os.getenv("DBT_MANIFEST_PATH", "dbt/target/manifest.json"),
        metrics_catalog_path=os.getenv("METRICS_CATALOG_PATH", "contracts/metrics/core_metrics.yml"),
        dbt_profile_name=os.getenv("DBT_PROFILE_NAME", "default"),
        dbt_target_name=os.getenv("DBT_TARGET_NAME", "dev"),
        dbt_profiles_dir=os.getenv("DBT_PROFILES_DIR"),
        dbt_project_template=os.getenv("DBT_PROJECT_TEMPLATE"),
        default_tenant_id=os.getenv("DEFAULT_TENANT_ID", "tenant_default"),
        default_domain_id=os.getenv("DEFAULT_DOMAIN_ID", "default_domain"),
        workspace_query_plan_mode=os.getenv("WORKSPACE_QUERY_PLAN_MODE", "auto"),
        workspace_query_plan_model=os.getenv("WORKSPACE_QUERY_PLAN_MODEL"),
        workspace_query_plan_timeout_sec=int(os.getenv("WORKSPACE_QUERY_PLAN_TIMEOUT_SEC", "30")),
    )
