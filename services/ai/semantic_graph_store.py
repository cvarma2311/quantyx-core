from __future__ import annotations

import logging
import json
import time
import uuid
from datetime import date, datetime, time as dt_time
from decimal import Decimal
from typing import Any

from psycopg2.extras import Json

from services.ai.config import Settings
from services.ai.db import run_query, execute_non_query

logger = logging.getLogger(__name__)


def _json_default(value: Any) -> Any:
    if isinstance(value, (datetime, date, dt_time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return str(value)


def _json_dumps(value: Any) -> str:
    return json.dumps(value, default=_json_default)


def _normalize(name: str) -> str:
    return str(name or "").strip().lower()


def _get_node_id(settings: Settings, domain_id: str, node_type: str, normalized_name: str) -> str | None:
    rows = run_query(
        settings,
        """
        SELECT node_id
          FROM public.quantyx_semantic_nodes
         WHERE domain_id = %s
           AND node_type = %s
           AND normalized_name = %s
         LIMIT 1
        """,
        [domain_id, node_type, normalized_name],
    )
    return rows[0]["node_id"] if rows else None


def _ensure_node(
    settings: Settings,
    domain_id: str,
    node_type: str,
    name: str,
    metadata: dict[str, Any] | None = None,
    node_cache: dict[tuple[str, str], str] | None = None,
) -> str:
    normalized = _normalize(name)
    cache_key = (node_type, normalized)
    if node_cache is not None and cache_key in node_cache:
        return node_cache[cache_key]
    existing = _get_node_id(settings, domain_id, node_type, normalized)
    if existing:
        if node_cache is not None:
            node_cache[cache_key] = existing
        return existing
    node_id = f"node_{uuid.uuid4().hex[:12]}"
    execute_non_query(
        settings,
        """
        INSERT INTO public.quantyx_semantic_nodes (
          node_id, node_type, name, normalized_name, domain_id, metadata, confidence, created_at, updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, now(), now())
        """,
        [
            node_id,
            node_type,
            name,
            normalized,
            domain_id,
            Json(metadata, dumps=_json_dumps) if metadata is not None else None,
            None,
        ],
    )
    if node_cache is not None:
        node_cache[cache_key] = node_id
    return node_id


def _update_node_metadata(settings: Settings, node_id: str, metadata: dict[str, Any]) -> None:
    execute_non_query(
        settings,
        """
        UPDATE public.quantyx_semantic_nodes
           SET metadata = COALESCE(metadata, '{}'::jsonb) || %s::jsonb,
               updated_at = now()
         WHERE node_id = %s
        """,
        [Json(metadata, dumps=_json_dumps), node_id],
    )


def _edge_exists(settings: Settings, src: str, dst: str, edge_type: str) -> bool:
    rows = run_query(
        settings,
        """
        SELECT edge_id
          FROM public.quantyx_semantic_edges
         WHERE src_node_id = %s
           AND dst_node_id = %s
           AND edge_type = %s
         LIMIT 1
        """,
        [src, dst, edge_type],
    )
    return bool(rows)


_QUALITY_THRESHOLD = 0.7


def _insert_edge(
    settings: Settings,
    src: str,
    dst: str,
    edge_type: str,
    source: str = "rule",
    confidence: float | None = None,
    metadata: dict[str, Any] | None = None,
    edge_cache: set[tuple[str, str, str]] | None = None,
) -> None:
    cache_key = (src, dst, edge_type)
    if edge_cache is not None and cache_key in edge_cache:
        return
    if edge_cache is None and _edge_exists(settings, src, dst, edge_type):
        return
    if confidence is not None and confidence < _QUALITY_THRESHOLD:
        metadata = dict(metadata or {})
        metadata.setdefault("review_required", True)
        metadata.setdefault("confidence_gate", _QUALITY_THRESHOLD)
    edge_id = f"edge_{uuid.uuid4().hex[:12]}"
    execute_non_query(
        settings,
        """
        INSERT INTO public.quantyx_semantic_edges (
          edge_id, src_node_id, dst_node_id, edge_type, confidence, source, metadata, created_at, updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, now(), now())
        """,
        [
            edge_id,
            src,
            dst,
            edge_type,
            confidence,
            source,
            Json(metadata, dumps=_json_dumps) if metadata is not None else None,
        ],
    )
    if edge_cache is not None:
        edge_cache.add(cache_key)


def persist_semantic_graph(
    settings: Settings,
    domain_id: str,
    schema_graph: dict[str, Any],
    profiling_stats: dict[str, Any],
    joins: list[dict[str, Any]],
    metrics: list[dict[str, Any]],
    glossary_terms: list[dict[str, Any]] | None = None,
    hierarchy_hints: list[str] | None = None,
    ontology: dict[str, Any] | None = None,
    model_classifications: list[dict[str, Any]] | None = None,
) -> dict[str, int]:
    started = time.perf_counter()
    counts = {"nodes": 0, "edges": 0}
    glossary_terms = glossary_terms or []
    hierarchy_hints = hierarchy_hints or []
    ontology = ontology or {}
    logger.info("semantic_graph.persist | stage=start domain=%s", domain_id)

    existing_nodes = run_query(
        settings,
        """
        SELECT node_id, node_type, normalized_name
          FROM public.quantyx_semantic_nodes
         WHERE domain_id = %s
        """,
        [domain_id],
    )
    node_cache: dict[tuple[str, str], str] = {}
    for row in existing_nodes:
        node_type = row.get("node_type")
        normalized = row.get("normalized_name")
        node_id = row.get("node_id")
        if node_type and normalized and node_id:
            node_cache[(str(node_type), str(normalized))] = str(node_id)
    logger.info(
        "semantic_graph.persist | stage=loaded_nodes domain=%s count=%s elapsed_ms=%.1f",
        domain_id,
        len(node_cache),
        (time.perf_counter() - started) * 1000,
    )

    existing_edges = run_query(
        settings,
        """
        SELECT e.src_node_id, e.dst_node_id, e.edge_type
          FROM public.quantyx_semantic_edges e
          JOIN public.quantyx_semantic_nodes s ON s.node_id = e.src_node_id
         WHERE s.domain_id = %s
        """,
        [domain_id],
    )
    edge_cache: set[tuple[str, str, str]] = set()
    for row in existing_edges:
        src = row.get("src_node_id")
        dst = row.get("dst_node_id")
        edge_type = row.get("edge_type")
        if src and dst and edge_type:
            edge_cache.add((str(src), str(dst), str(edge_type)))
    logger.info(
        "semantic_graph.persist | stage=loaded_edges domain=%s count=%s elapsed_ms=%.1f",
        domain_id,
        len(edge_cache),
        (time.perf_counter() - started) * 1000,
    )

    dimension_names: set[str] = set()
    for table in profiling_stats.get("tables", []):
        dimension_names.update(table.get("categorical_columns") or [])
        dimension_names.update(table.get("time_columns") or [])
    metric_names: set[str] = {metric.get("metric_name") for metric in metrics if metric.get("metric_name")}

    model_classifications = model_classifications or []
    model_meta_map = {c.get("table"): c for c in model_classifications if c.get("table")}

    # Model + column nodes
    for table in schema_graph.get("tables", []):
        model_node = _ensure_node(settings, domain_id, "model", table.get("name"), node_cache=node_cache)
        meta = model_meta_map.get(table.get("name"))
        if meta:
            _update_node_metadata(
                settings,
                model_node,
                {
                    "model_type": meta.get("model_type"),
                    "confidence": meta.get("confidence"),
                    "numeric_columns": meta.get("numeric_columns"),
                    "time_columns": meta.get("time_columns"),
                    "categorical_columns": meta.get("categorical_columns"),
                },
            )
        counts["nodes"] += 1
        for col in table.get("columns", []):
            col_name = col.get("name")
            if not col_name:
                continue
            col_node = _ensure_node(
                settings,
                domain_id,
                "column",
                f"{table.get('name')}.{col_name}",
                {"table": table.get("name"), "column": col_name, "data_type": col.get("data_type")},
                node_cache=node_cache,
            )
            counts["nodes"] += 1
            _insert_edge(settings, model_node, col_node, "model_column", edge_cache=edge_cache)
            counts["edges"] += 1
    logger.info(
        "semantic_graph.persist | stage=model_column_done domain=%s nodes=%s edges=%s elapsed_ms=%.1f",
        domain_id,
        counts["nodes"],
        counts["edges"],
        (time.perf_counter() - started) * 1000,
    )

    # Dimensions from profiling (categorical + time)
    for table in profiling_stats.get("tables", []):
        model_node = _ensure_node(settings, domain_id, "model", table.get("name"), node_cache=node_cache)
        for col in (table.get("categorical_columns") or []) + (table.get("time_columns") or []):
            dim_node = _ensure_node(
                settings, domain_id, "dimension", col, {"table": table.get("name")}, node_cache=node_cache
            )
            counts["nodes"] += 1
            col_node = _ensure_node(
                settings, domain_id, "column", f"{table.get('name')}.{col}", node_cache=node_cache
            )
            _insert_edge(settings, dim_node, col_node, "dimension_column", edge_cache=edge_cache)
            counts["edges"] += 1
            _insert_edge(settings, dim_node, model_node, "dimension_model", edge_cache=edge_cache)
            counts["edges"] += 1
            if col in (table.get("time_columns") or []):
                grain = "day"
                lower = col.lower()
                if "month" in lower:
                    grain = "month"
                elif "week" in lower:
                    grain = "week"
                _update_node_metadata(settings, dim_node, {"time_grain": grain})
                grain_node = _ensure_node(settings, domain_id, "time_grain", grain, node_cache=node_cache)
                _insert_edge(
                    settings,
                    dim_node,
                    grain_node,
                    "dimension_time_grain",
                    source="rule",
                    confidence=0.7,
                    edge_cache=edge_cache,
                )
                counts["edges"] += 1
    logger.info(
        "semantic_graph.persist | stage=dimensions_done domain=%s nodes=%s edges=%s elapsed_ms=%.1f",
        domain_id,
        counts["nodes"],
        counts["edges"],
        (time.perf_counter() - started) * 1000,
    )

    # Metrics
    for metric in metrics:
        metric_node = _ensure_node(
            settings,
            domain_id,
            "metric",
            metric.get("metric_name"),
            {"formula": metric.get("formula")},
            node_cache=node_cache,
        )
        counts["nodes"] += 1
        base_table = metric.get("base_table")
        if base_table:
            model_node = _ensure_node(settings, domain_id, "model", base_table, node_cache=node_cache)
            _insert_edge(settings, metric_node, model_node, "metric_model", edge_cache=edge_cache)
            counts["edges"] += 1
    logger.info(
        "semantic_graph.persist | stage=metrics_done domain=%s nodes=%s edges=%s elapsed_ms=%.1f",
        domain_id,
        counts["nodes"],
        counts["edges"],
        (time.perf_counter() - started) * 1000,
    )

    # Concepts + synonyms from glossary/context
    concept_names = set()
    for term in glossary_terms:
        if term.get("term"):
            concept_names.add(term["term"])
    for name in ontology.get("concepts", []) or []:
        if name:
            concept_names.add(name)

    concept_nodes: dict[str, str] = {}
    for concept in sorted(concept_names, key=lambda n: n.lower()):
        node_id = _ensure_node(settings, domain_id, "concept", concept, node_cache=node_cache)
        concept_nodes[concept.lower()] = node_id
        counts["nodes"] += 1

        if concept in dimension_names:
            dim_node = _ensure_node(settings, domain_id, "dimension", concept, node_cache=node_cache)
            _insert_edge(
                settings, node_id, dim_node, "concept_dimension", source="rule", confidence=0.8, edge_cache=edge_cache
            )
            counts["edges"] += 1
        if concept in metric_names:
            metric_node = _ensure_node(settings, domain_id, "metric", concept, node_cache=node_cache)
            _insert_edge(
                settings, node_id, metric_node, "concept_metric", source="rule", confidence=0.8, edge_cache=edge_cache
            )
            counts["edges"] += 1

    for term in glossary_terms:
        head = term.get("term")
        if not head:
            continue
        head_node = concept_nodes.get(head.lower())
        if not head_node:
            head_node = _ensure_node(settings, domain_id, "concept", head, node_cache=node_cache)
            concept_nodes[head.lower()] = head_node
            counts["nodes"] += 1
        for syn in (term.get("synonyms") or []) + (term.get("abbreviations") or []):
            if not syn:
                continue
            syn_node = _ensure_node(settings, domain_id, "synonym", syn, node_cache=node_cache)
            counts["nodes"] += 1
            _insert_edge(
                settings,
                syn_node,
                head_node,
                "synonym_of",
                source="glossary",
                confidence=0.7,
                metadata={"term": head},
                edge_cache=edge_cache,
            )
            counts["edges"] += 1
            if syn in dimension_names:
                dim_node = _ensure_node(settings, domain_id, "dimension", syn, node_cache=node_cache)
                _insert_edge(
                    settings,
                    head_node,
                    dim_node,
                    "concept_dimension",
                    source="glossary",
                    confidence=0.7,
                    edge_cache=edge_cache,
                )
                counts["edges"] += 1
            if syn in metric_names:
                metric_node = _ensure_node(settings, domain_id, "metric", syn, node_cache=node_cache)
                _insert_edge(
                    settings,
                    head_node,
                    metric_node,
                    "concept_metric",
                    source="glossary",
                    confidence=0.7,
                    edge_cache=edge_cache,
                )
                counts["edges"] += 1
    logger.info(
        "semantic_graph.persist | stage=concepts_done domain=%s nodes=%s edges=%s elapsed_ms=%.1f",
        domain_id,
        counts["nodes"],
        counts["edges"],
        (time.perf_counter() - started) * 1000,
    )

    for edge in ontology.get("hierarchy_edges", []) or []:
        parent = edge.get("parent")
        child = edge.get("child")
        if not parent or not child:
            continue
        parent_node = concept_nodes.get(parent.lower()) or _ensure_node(
            settings, domain_id, "concept", parent, node_cache=node_cache
        )
        child_node = concept_nodes.get(child.lower()) or _ensure_node(
            settings, domain_id, "concept", child, node_cache=node_cache
        )
        _insert_edge(
            settings,
            parent_node,
            child_node,
            "hierarchy_parent",
            source=edge.get("source") or "context",
            confidence=edge.get("confidence") or 0.6,
            edge_cache=edge_cache,
        )
        counts["edges"] += 1

    # Joins
    for join in joins:
        left = join.get("left_table")
        right = join.get("right_table")
        if not left or not right:
            continue
        left_node = _ensure_node(settings, domain_id, "model", left, node_cache=node_cache)
        right_node = _ensure_node(settings, domain_id, "model", right, node_cache=node_cache)
        _insert_edge(
            settings,
            left_node,
            right_node,
            "model_join",
            confidence=join.get("confidence"),
            metadata={
                "left_key": join.get("left_key"),
                "right_key": join.get("right_key"),
            },
            edge_cache=edge_cache,
        )
        counts["edges"] += 1
    logger.info(
        "semantic_graph.persist | stage=joins_done domain=%s nodes=%s edges=%s elapsed_ms=%.1f",
        domain_id,
        counts["nodes"],
        counts["edges"],
        (time.perf_counter() - started) * 1000,
    )
    logger.info(
        "semantic_graph.persist | stage=completed domain=%s nodes=%s edges=%s elapsed_ms=%.1f",
        domain_id,
        counts["nodes"],
        counts["edges"],
        (time.perf_counter() - started) * 1000,
    )

    return counts


def persist_dashboard_spec(
    settings: Settings,
    tenant_id: str,
    domain_id: str,
    spec: dict[str, Any],
    title: str = "Auto Dashboard",
) -> str:
    """Deprecated: delegates to dashboards_store.create_dashboard()."""
    from services.ai.dashboards_store import create_dashboard
    result = create_dashboard(
        settings,
        tenant_id=tenant_id,
        domain_id=domain_id,
        name=title,
        dashboard_type="system",
        chart_plan=spec.get("chart_plan"),
        quality_score=(
            float(spec["quality"]["quality_score"])
            if isinstance(spec.get("quality"), dict) and spec["quality"].get("quality_score") is not None
            else None
        ),
        quality_gate_passed=(
            bool(spec["quality"].get("gate_passed"))
            if isinstance(spec.get("quality"), dict)
            else None
        ),
    )
    return result.get("dashboard_id") or f"dash_{uuid.uuid4().hex[:10]}"


def list_dashboard_specs(settings: Settings, tenant_id: str, domain_id: str | None) -> list[dict[str, Any]]:
    """Deprecated: delegates to dashboards_store.list_dashboards()."""
    from services.ai.dashboards_store import list_dashboards, get_dashboard_with_charts
    rows = list_dashboards(settings, tenant_id, domain_id, dashboard_type="system", status="active", limit=200)
    # Synthesize backward-compat spec field so callers using spec.get("charts") still work
    result = []
    for row in rows:
        dash = get_dashboard_with_charts(settings, row["dashboard_id"])
        if dash:
            row["spec"] = _synthesize_spec(dash)
            row["title"] = row.get("name")
        result.append(row)
    return result


def get_dashboard_spec(settings: Settings, dashboard_id: str) -> dict[str, Any] | None:
    """Deprecated: delegates to dashboards_store.get_dashboard_with_charts()."""
    from services.ai.dashboards_store import get_dashboard_with_charts
    dash = get_dashboard_with_charts(settings, dashboard_id)
    if not dash:
        return None
    dash["spec"] = _synthesize_spec(dash)
    dash["title"] = dash.get("name")
    return dash


def _synthesize_spec(dash: dict[str, Any]) -> dict[str, Any]:
    """Reconstruct a backward-compat spec blob from a unified dashboard + charts dict."""
    charts_out = []
    for c in dash.get("charts") or []:
        qp = c.get("query_payload") or {}
        if isinstance(qp, str):
            import json
            try:
                qp = json.loads(qp)
            except Exception:
                qp = {}
        charts_out.append({
            "chart_id": c.get("chart_id"),
            "title": c.get("title_override") or c.get("title") or c.get("question"),
            "type": c.get("chart_type"),
            "sql": c.get("sql"),
            "params": c.get("params") or [],
            "metric": (qp.get("metrics") or [None])[0],
            "dimensions": qp.get("dimensions") or [],
            "chart_data": c.get("rows_json") or c.get("chart_data") or [],
            "chart_payload": c.get("chart_payload"),
        })
    return {
        "charts": charts_out,
        "chart_plan": dash.get("chart_plan") or [],
        "quality": {
            "quality_score": dash.get("quality_score"),
            "gate_passed": dash.get("quality_gate_passed"),
        },
    }


def update_dashboard_spec(
    settings: Settings,
    dashboard_id: str,
    *,
    spec: dict[str, Any] | None = None,
    title: str | None = None,
) -> None:
    """Deprecated: delegates to dashboards_store.update_dashboard()."""
    from services.ai.dashboards_store import update_dashboard
    update_kw: dict[str, Any] = {}
    if title is not None:
        update_kw["name"] = title
    if spec is not None:
        update_kw["chart_plan"] = spec.get("chart_plan")
        quality = spec.get("quality") or {}
        if isinstance(quality, dict):
            if quality.get("quality_score") is not None:
                update_kw["quality_score"] = float(quality["quality_score"])
            if quality.get("gate_passed") is not None:
                update_kw["quality_gate_passed"] = bool(quality["gate_passed"])
    if update_kw:
        update_dashboard(settings, dashboard_id, **update_kw)
