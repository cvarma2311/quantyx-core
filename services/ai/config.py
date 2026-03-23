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
    minio_endpoint: str
    minio_host: str
    minio_access_key_id: str
    minio_secret_access_key: str
    minio_base_path: str
    minio_port: str
    catalog_db: str
    catalog_user: str
    catalog_password: str
    catalog_db_uri: str
    catalog_name: str
    minio_bucket_name: str

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
        minio_endpoint=os.getenv("MINIO_ENDPOINT"),
        minio_host=os.getenv("MINIO_HOST",""),
        minio_access_key_id=os.getenv("MINIO_ACCESS_KEY_ID"),
        minio_secret_access_key=os.getenv("MINIO_SECRET_ACCESS_KEY"),
        minio_base_path=os.getenv("MINIO_BASE_PATH"),
        minio_port=os.getenv("MINIO_PORT"),
        catalog_db=os.getenv("CATALOG_DB", "catalog_db"),
        catalog_user=os.getenv("CATALOG_USER", "catalog_user"),
        catalog_password=os.getenv("CATALOG_PASSWORD", ""),
        catalog_db_uri=os.getenv("CATALOG_DB_URI",""),
        catalog_name=os.getenv("CATALOG_NAME", ""),
        minio_bucket_name=os.getenv("MINIO_BUCKET_NAME", "")
    )
