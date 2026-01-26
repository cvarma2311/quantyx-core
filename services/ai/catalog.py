from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from services.ai.config import Settings
from services.ai.metrics_registry import fetch_registry_metrics

_REF_PATTERN = re.compile(r"\{\{\s*ref\('(?P<name>[^']+)'\)\s*\}\}")


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
        name = metric.get("metric_name") or metric.get("display_name") or metric["metric_id"]
        dimensions = metric.get("dimensions") or []
        metrics[name] = Metric(
            name=name,
            description=metric.get("description") or "",
            metric_type=metric.get("type") or "",
            sql=metric.get("sql") or "",
            grain=metric.get("grain") or "",
            dimensions=list(dimensions),
            status=metric.get("status"),
            owner=metric.get("owner"),
            version=metric.get("version"),
        )
    return MetricCatalog(metrics=metrics, dimensions=catalog.dimensions)


def resolve_ref(sql: str, schema: str) -> str:
    def _replace(match: re.Match) -> str:
        table = match.group("name")
        return f"{schema}.{table}"

    return _REF_PATTERN.sub(_replace, sql)
