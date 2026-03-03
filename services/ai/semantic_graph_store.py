from __future__ import annotations

import uuid
from typing import Any

from services.ai.config import Settings
from services.ai.db import run_query, execute_non_query


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
) -> str:
    normalized = _normalize(name)
    existing = _get_node_id(settings, domain_id, node_type, normalized)
    if existing:
        return existing
    node_id = f"node_{uuid.uuid4().hex[:12]}"
    execute_non_query(
        settings,
        """
        INSERT INTO public.quantyx_semantic_nodes (
          node_id, node_type, name, normalized_name, domain_id, metadata, confidence, created_at, updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, now(), now())
        """,
        [node_id, node_type, name, normalized, domain_id, metadata, None],
    )
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
        [metadata, node_id],
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
) -> None:
    if _edge_exists(settings, src, dst, edge_type):
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
        VALUES (%s, %s, %s, %s, %s, %s, %s, now(), now())
        """,
        [edge_id, src, dst, edge_type, confidence, source, metadata],
    )


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
    counts = {"nodes": 0, "edges": 0}
    glossary_terms = glossary_terms or []
    hierarchy_hints = hierarchy_hints or []
    ontology = ontology or {}

    dimension_names: set[str] = set()
    for table in profiling_stats.get("tables", []):
        dimension_names.update(table.get("categorical_columns") or [])
        dimension_names.update(table.get("time_columns") or [])
    metric_names: set[str] = {metric.get("metric_name") for metric in metrics if metric.get("metric_name")}

    model_classifications = model_classifications or []
    model_meta_map = {c.get("table"): c for c in model_classifications if c.get("table")}

    # Model + column nodes
    for table in schema_graph.get("tables", []):
        model_node = _ensure_node(settings, domain_id, "model", table.get("name"))
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
            )
            counts["nodes"] += 1
            _insert_edge(settings, model_node, col_node, "model_column")
            counts["edges"] += 1

    # Dimensions from profiling (categorical + time)
    for table in profiling_stats.get("tables", []):
        model_node = _ensure_node(settings, domain_id, "model", table.get("name"))
        for col in (table.get("categorical_columns") or []) + (table.get("time_columns") or []):
            dim_node = _ensure_node(settings, domain_id, "dimension", col, {"table": table.get("name")})
            counts["nodes"] += 1
            col_node = _ensure_node(settings, domain_id, "column", f"{table.get('name')}.{col}")
            _insert_edge(settings, dim_node, col_node, "dimension_column")
            counts["edges"] += 1
            _insert_edge(settings, dim_node, model_node, "dimension_model")
            counts["edges"] += 1
            if col in (table.get("time_columns") or []):
                grain = "day"
                lower = col.lower()
                if "month" in lower:
                    grain = "month"
                elif "week" in lower:
                    grain = "week"
                _update_node_metadata(settings, dim_node, {"time_grain": grain})
                grain_node = _ensure_node(settings, domain_id, "time_grain", grain)
                _insert_edge(settings, dim_node, grain_node, "dimension_time_grain", source="rule", confidence=0.7)
                counts["edges"] += 1

    # Metrics
    for metric in metrics:
        metric_node = _ensure_node(
            settings,
            domain_id,
            "metric",
            metric.get("metric_name"),
            {"formula": metric.get("formula")},
        )
        counts["nodes"] += 1
        base_table = metric.get("base_table")
        if base_table:
            model_node = _ensure_node(settings, domain_id, "model", base_table)
            _insert_edge(settings, metric_node, model_node, "metric_model")
            counts["edges"] += 1

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
        node_id = _ensure_node(settings, domain_id, "concept", concept)
        concept_nodes[concept.lower()] = node_id
        counts["nodes"] += 1

        if concept in dimension_names:
            dim_node = _ensure_node(settings, domain_id, "dimension", concept)
            _insert_edge(settings, node_id, dim_node, "concept_dimension", source="rule", confidence=0.8)
            counts["edges"] += 1
        if concept in metric_names:
            metric_node = _ensure_node(settings, domain_id, "metric", concept)
            _insert_edge(settings, node_id, metric_node, "concept_metric", source="rule", confidence=0.8)
            counts["edges"] += 1

    for term in glossary_terms:
        head = term.get("term")
        if not head:
            continue
        head_node = concept_nodes.get(head.lower())
        if not head_node:
            head_node = _ensure_node(settings, domain_id, "concept", head)
            concept_nodes[head.lower()] = head_node
            counts["nodes"] += 1
        for syn in (term.get("synonyms") or []) + (term.get("abbreviations") or []):
            if not syn:
                continue
            syn_node = _ensure_node(settings, domain_id, "synonym", syn)
            counts["nodes"] += 1
            _insert_edge(
                settings,
                syn_node,
                head_node,
                "synonym_of",
                source="glossary",
                confidence=0.7,
                metadata={"term": head},
            )
            counts["edges"] += 1
            if syn in dimension_names:
                dim_node = _ensure_node(settings, domain_id, "dimension", syn)
                _insert_edge(settings, head_node, dim_node, "concept_dimension", source="glossary", confidence=0.7)
                counts["edges"] += 1
            if syn in metric_names:
                metric_node = _ensure_node(settings, domain_id, "metric", syn)
                _insert_edge(settings, head_node, metric_node, "concept_metric", source="glossary", confidence=0.7)
                counts["edges"] += 1

    for edge in ontology.get("hierarchy_edges", []) or []:
        parent = edge.get("parent")
        child = edge.get("child")
        if not parent or not child:
            continue
        parent_node = concept_nodes.get(parent.lower()) or _ensure_node(settings, domain_id, "concept", parent)
        child_node = concept_nodes.get(child.lower()) or _ensure_node(settings, domain_id, "concept", child)
        _insert_edge(
            settings,
            parent_node,
            child_node,
            "hierarchy_parent",
            source=edge.get("source") or "context",
            confidence=edge.get("confidence") or 0.6,
        )
        counts["edges"] += 1

    # Joins
    for join in joins:
        left = join.get("left_table")
        right = join.get("right_table")
        if not left or not right:
            continue
        left_node = _ensure_node(settings, domain_id, "model", left)
        right_node = _ensure_node(settings, domain_id, "model", right)
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
        )
        counts["edges"] += 1

    return counts


def persist_dashboard_spec(
    settings: Settings,
    tenant_id: str,
    domain_id: str,
    spec: dict[str, Any],
    title: str = "Auto Dashboard",
) -> str:
    dashboard_id = f"dash_{uuid.uuid4().hex[:10]}"
    execute_non_query(
        settings,
        """
        INSERT INTO public.quantyx_dashboard_specs (
          dashboard_id, tenant_id, domain_id, title, spec, created_at, updated_at
        )
        VALUES (%s, %s, %s, %s, %s, now(), now())
        """,
        [dashboard_id, tenant_id, domain_id, title, spec],
    )
    return dashboard_id


def list_dashboard_specs(settings: Settings, tenant_id: str, domain_id: str | None) -> list[dict[str, Any]]:
    if domain_id:
        return run_query(
            settings,
            """
            SELECT dashboard_id, tenant_id, domain_id, title, spec, created_at, updated_at
              FROM public.quantyx_dashboard_specs
             WHERE tenant_id = %s AND domain_id = %s
             ORDER BY created_at DESC
            """,
            [tenant_id, domain_id],
        )
    return run_query(
        settings,
        """
        SELECT dashboard_id, tenant_id, domain_id, title, spec, created_at, updated_at
          FROM public.quantyx_dashboard_specs
         WHERE tenant_id = %s
         ORDER BY created_at DESC
        """,
        [tenant_id],
    )


def get_dashboard_spec(settings: Settings, dashboard_id: str) -> dict[str, Any] | None:
    rows = run_query(
        settings,
        """
        SELECT dashboard_id, tenant_id, domain_id, title, spec, created_at, updated_at
          FROM public.quantyx_dashboard_specs
         WHERE dashboard_id = %s
         LIMIT 1
        """,
        [dashboard_id],
    )
    return rows[0] if rows else None
