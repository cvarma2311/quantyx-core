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
    )
