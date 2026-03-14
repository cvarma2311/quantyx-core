from __future__ import annotations

import hashlib
import re
from typing import Any

from psycopg2.extras import Json

from services.ai.config import Settings
from services.ai.db import run_query, execute_non_query


def _normalize(text: str | None) -> str:
    return str(text or "").strip().lower()


def _question_hash(question: str) -> str:
    return hashlib.sha256(question.encode("utf-8")).hexdigest()


def load_semantic_graph(settings: Settings, domain_id: str) -> tuple[list[dict], list[dict]]:
    nodes = run_query(
        settings,
        """
        SELECT node_id, node_type, name, normalized_name, metadata
          FROM public.quantyx_semantic_nodes
         WHERE domain_id = %s
        """,
        [domain_id],
    )
    edges = run_query(
        settings,
        """
        SELECT e.edge_id, e.src_node_id, e.dst_node_id, e.edge_type, e.confidence, e.source, e.metadata
          FROM public.quantyx_semantic_edges e
          JOIN public.quantyx_semantic_nodes s ON s.node_id = e.src_node_id
          JOIN public.quantyx_semantic_nodes d ON d.node_id = e.dst_node_id
         WHERE s.domain_id = %s
           AND d.domain_id = %s
        """,
        [domain_id, domain_id],
    )
    return nodes, edges


def _match_nodes(question: str, nodes: list[dict]) -> list[dict]:
    q = _normalize(question)
    matched = []
    for node in nodes:
        name = _normalize(node.get("normalized_name") or node.get("name"))
        if not name:
            continue
        if name in q:
            matched.append(node)
            continue
        # Try word-boundary match for short tokens
        if len(name.split()) == 1 and re.search(rf"\\b{re.escape(name)}\\b", q):
            matched.append(node)
    return matched


def resolve_question_semantic(
    settings: Settings,
    question: str,
    domain_id: str,
    allowed_dimensions: list[str] | None = None,
) -> dict[str, Any]:
    nodes, edges = load_semantic_graph(settings, domain_id)
    if not nodes:
        return {"metrics": [], "dimensions": [], "matched": []}

    nodes_by_id = {node["node_id"]: node for node in nodes}
    edges_by_src: dict[str, list[dict]] = {}
    for edge in edges:
        edges_by_src.setdefault(edge["src_node_id"], []).append(edge)

    matched_nodes = _match_nodes(question, nodes)
    metrics: set[str] = set()
    dimensions: set[str] = set()

    def add_dimension(name: str | None) -> None:
        if not name:
            return
        if allowed_dimensions:
            allowed = {d.lower() for d in allowed_dimensions}
            if name.lower() not in allowed:
                return
        dimensions.add(name)

    for node in matched_nodes:
        node_type = node.get("node_type")
        name = node.get("name")
        if node_type == "metric":
            if name:
                metrics.add(name)
        elif node_type == "dimension":
            add_dimension(name)
        elif node_type == "concept":
            for edge in edges_by_src.get(node["node_id"], []):
                dst = nodes_by_id.get(edge["dst_node_id"])
                if not dst:
                    continue
                if edge["edge_type"] == "concept_metric" and dst.get("name"):
                    metrics.add(dst["name"])
                if edge["edge_type"] == "concept_dimension":
                    add_dimension(dst.get("name"))
        elif node_type == "synonym":
            for edge in edges_by_src.get(node["node_id"], []):
                if edge["edge_type"] != "synonym_of":
                    continue
                concept = nodes_by_id.get(edge["dst_node_id"])
                if not concept:
                    continue
                for concept_edge in edges_by_src.get(concept["node_id"], []):
                    dst = nodes_by_id.get(concept_edge["dst_node_id"])
                    if not dst:
                        continue
                    if concept_edge["edge_type"] == "concept_metric" and dst.get("name"):
                        metrics.add(dst["name"])
                    if concept_edge["edge_type"] == "concept_dimension":
                        add_dimension(dst.get("name"))

    return {
        "metrics": sorted(metrics),
        "dimensions": sorted(dimensions),
        "matched": [node.get("name") for node in matched_nodes if node.get("name")],
    }


def log_semantic_usage(
    settings: Settings,
    *,
    question: str,
    tenant_id: str,
    domain_id: str,
    metrics: list[str],
    dimensions: list[str],
    filters: list[dict],
    intent: str | None = None,
) -> None:
    usage_id = f"usage_{_question_hash(question)[:12]}"
    execute_non_query(
        settings,
        """
        INSERT INTO public.quantyx_semantic_usage (
          usage_id, question_hash, question_text, tenant_id, domain_id,
          resolved_metric, resolved_dimensions, resolved_filters, intent, created_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, now())
        ON CONFLICT DO NOTHING
        """,
        [
            usage_id,
            _question_hash(question),
            question,
            tenant_id,
            domain_id,
            metrics[0] if metrics else "",
            Json(dimensions or []),
            Json(filters or []),
            intent,
        ],
    )
