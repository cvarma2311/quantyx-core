from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from services.ai.config import Settings
from services.ai.metrics_registry import fetch_registry_metrics

_REF_PATTERN = re.compile(r"\{\{\s*ref\('(?P<name>[^']+)'\)\s*\}\}")
# Matches an unquoted column identifier immediately after schema."TABLE".
# Used to double-quote column names so PostgreSQL preserves their case.
_UNQUOTED_COL_AFTER_QUOTED_TABLE = re.compile(
    r'(\b[a-zA-Z_][a-zA-Z0-9_]*\."[^"]+")\.'
    r'([a-zA-Z_][a-zA-Z0-9_]*)(?!")'
)


@dataclass(frozen=True)
class Metric:
    name: str
    description: str
    metric_type: str
    sql: str
    grain: str
    dimensions: list[str]
    status: str | None = None
    owner: str | None = None
    version: str | None = None
    semantic_metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class Dimension:
    name: str
    description: str
    data_type: str
    sql: str


@dataclass(frozen=True)
class MetricCatalog:
    metrics: dict[str, Metric]
    dimensions: dict[str, Dimension]

    def metric_names(self) -> list[str]:
        return sorted(self.metrics.keys())

    def dimension_names(self) -> list[str]:
        return sorted(self.dimensions.keys())


def _load_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text())


def load_catalog(path: str) -> MetricCatalog:
    data = _load_yaml(Path(path))
    metrics = {}
    for metric in data.get("metrics", []):
        metrics[metric["name"]] = Metric(
            name=metric["name"],
            description=metric.get("description", ""),
            metric_type=metric.get("type", ""),
            sql=metric["sql"],
            grain=metric.get("grain", ""),
            dimensions=metric.get("dimensions", []),
            status="static",
        )

    dimensions = {}
    for dim in data.get("dimensions", []):
        dimensions[dim["name"]] = Dimension(
            name=dim["name"],
            description=dim.get("description", ""),
            data_type=dim.get("data_type", ""),
            sql=dim["sql"],
        )

    return MetricCatalog(metrics=metrics, dimensions=dimensions)


def load_catalog_with_registry(settings: Settings, path: str) -> MetricCatalog:
    catalog = load_catalog(path)
    registry_metrics = fetch_registry_metrics(settings)
    metrics = dict(catalog.metrics)
    for metric in registry_metrics:
        sql = (metric.get("sql") or "").strip()
        if not sql:
            # Skip registry metrics with empty SQL (placeholders) so they don't shadow real metrics.
            continue
        metric_name = metric.get("metric_name") or metric.get("metric_id")
        display_name = metric.get("display_name")
        name = metric_name or display_name or metric["metric_id"]
        dimensions = metric.get("dimensions") or []
        metric_obj = Metric(
            name=name,
            description=metric.get("description") or "",
            metric_type=metric.get("type") or "",
            sql=sql,
            grain=metric.get("grain") or "",
            dimensions=list(dimensions),
            status=metric.get("status"),
            owner=metric.get("owner"),
            version=metric.get("version"),
            semantic_metadata=metric.get("semantic_metadata"),
        )
        metrics[name] = metric_obj
        if display_name and display_name != name:
            existing = metrics.get(display_name)
            should_replace = existing is None or (not existing.sql and metric_obj.sql)
            if should_replace:
                metrics[display_name] = Metric(
                    name=display_name,
                    description=metric_obj.description,
                    metric_type=metric_obj.metric_type,
                    sql=metric_obj.sql,
                    grain=metric_obj.grain,
                    dimensions=list(metric_obj.dimensions),
                    status=metric_obj.status,
                    owner=metric_obj.owner,
                    version=metric_obj.version,
                    semantic_metadata=metric_obj.semantic_metadata,
                )
    return MetricCatalog(metrics=metrics, dimensions=catalog.dimensions)


def resolve_ref(sql: str, schema: str) -> str:
    def _replace(match: re.Match) -> str:
        table = match.group("name")
        # dbt model names are prefixed with "fact_" or "dim_" but the
        # underlying PostgreSQL table/view may only exist without that
        # prefix (e.g. when dbt has not been run for this tenant yet).
        # Strip the prefix so the resolved SQL always targets the raw table.
        for _prefix in ("fact_", "dim_"):
            if table.lower().startswith(_prefix):
                table = table[len(_prefix):]
                break
        # Double-quote the table name so PostgreSQL preserves case for
        # tables that were created with mixed-case identifiers.
        return f'{schema}."{table}"'

    sql = _REF_PATTERN.sub(_replace, sql)
    # After ref substitution, quote any unquoted column identifier that
    # immediately follows a schema."TABLE". pattern so PostgreSQL preserves
    # the column's original case (e.g. SBU_Name → "SBU_Name").
    sql = _UNQUOTED_COL_AFTER_QUOTED_TABLE.sub(
        lambda m: f'{m.group(1)}."{m.group(2)}"', sql
    )
    return sql
