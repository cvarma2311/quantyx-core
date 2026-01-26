from __future__ import annotations

import re
from typing import Any

from services.ai.catalog import MetricCatalog
from services.ai.schema_loader import load_manifest_models


_REF_PATTERN = re.compile(r"\{\{\s*ref\('(?P<name>[^']+)'\)\s*\}\}")
_TABLE_PATTERN = re.compile(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\.([a-zA-Z_][a-zA-Z0-9_]*)\b")


def _resolve_metric_dataset(sql: str) -> str | None:
    ref_match = _REF_PATTERN.search(sql)
    if ref_match:
        return ref_match.group("name")
    table_match = _TABLE_PATTERN.search(sql)
    if table_match:
        return table_match.group(2)
    return None


def build_lineage(catalog: MetricCatalog, manifest_path: str) -> list[dict[str, Any]]:
    models = load_manifest_models(manifest_path)
    model_names = {model["name"].lower(): model["name"] for model in models}
    lineage: list[dict[str, Any]] = []

    for metric in catalog.metrics.values():
        dataset = _resolve_metric_dataset(metric.sql)
        dbt_model = model_names.get(dataset.lower()) if dataset else None
        lineage.append(
            {
                "metric_name": metric.name,
                "dataset": dataset,
                "dbt_model": dbt_model,
            }
        )

    return lineage
