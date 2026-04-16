from __future__ import annotations

import re
from typing import Any

from psycopg2.extras import Json

from services.ai.config import Settings
from services.ai.db import execute_non_query, run_query
from services.ai.domain_refinement_store import get_current_semantic_state


def _normalize(value: Any) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", str(value or "").strip().lower()).strip("_")


def load_active_semantic_state(
    settings: Settings,
    *,
    tenant_id: str,
    domain_id: str,
    connection_id: str | None = None,
    database_name: str | None = None,
    schema_name: str | None = None,
) -> dict[str, Any]:
    row = get_current_semantic_state(
        settings,
        tenant_id=tenant_id,
        domain_id=domain_id,
        connection_id=connection_id,
        database_name=database_name,
        schema_name=schema_name,
    )
    state = (row or {}).get("state_json") or {}
    return state if isinstance(state, dict) else {}


def semantic_state_artifacts(state_json: dict[str, Any], artifact_type: str) -> list[dict[str, Any]]:
    refinements = state_json.get("refinements") or {}
    key_map = {
        "business_context": "business_context",
        "hierarchy_override": "hierarchies",
        "column_annotation": "column_annotations",
        "metric_refinement": "metric_overrides",
        "join_rule": "join_rules",
        "chart_guidance": "chart_guidance",
        "interpretation_rule": "interpretation_rules",
        "context_question_answer": "context_question_answers",
    }
    bucket = refinements.get(key_map.get(artifact_type, artifact_type)) or []
    return [item for item in bucket if isinstance(item, dict)]


def semantic_artifact_payloads(state_json: dict[str, Any], artifact_type: str) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for item in semantic_state_artifacts(state_json, artifact_type):
        payload = item.get("artifact_json") or {}
        if isinstance(payload, dict):
            payloads.append(payload)
    return payloads


def semantic_join_constraints(state_json: dict[str, Any]) -> dict[str, Any]:
    restricted_pairs: set[tuple[str, str]] = set()
    excluded_tables: set[str] = set()
    filters: list[dict[str, Any]] = []
    for payload in semantic_artifact_payloads(state_json, "join_rule"):
        rule_type = str(payload.get("rule_type") or "").strip().lower()
        left = _normalize(payload.get("left_table"))
        right = _normalize(payload.get("right_table"))
        table = _normalize(payload.get("table"))
        if rule_type == "join_restriction" and left and right and payload.get("allowed") is False:
            restricted_pairs.add((left, right))
            restricted_pairs.add((right, left))
        if rule_type in {"reference_table_usage", "table_restriction"} and table:
            usage = str(payload.get("usage") or "").strip().lower()
            if usage in {"labels_only", "do_not_use_for_kpi", "excluded"}:
                excluded_tables.add(table)
        if rule_type == "exclusion_filter":
            filters.append(payload)
    return {
        "restricted_join_pairs": sorted([list(pair) for pair in restricted_pairs]),
        "excluded_tables": sorted(excluded_tables),
        "default_filters": filters,
    }


def apply_join_constraints_to_edges(join_edges: list[dict[str, Any]], constraints: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    restricted_pairs = {
        (_normalize(pair[0]), _normalize(pair[1]))
        for pair in constraints.get("restricted_join_pairs") or []
        if isinstance(pair, list) and len(pair) == 2
    }
    excluded_tables = {_normalize(table) for table in constraints.get("excluded_tables") or []}
    allowed: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    for edge in join_edges or []:
        left = _normalize(edge.get("left_table") or edge.get("left"))
        right = _normalize(edge.get("right_table") or edge.get("right"))
        blocked = (left, right) in restricted_pairs or left in excluded_tables or right in excluded_tables
        if blocked:
            removed.append(edge)
        else:
            allowed.append(edge)
    return allowed, removed


def semantic_glossary_terms(state_json: dict[str, Any]) -> list[dict[str, Any]]:
    terms: list[dict[str, Any]] = []
    for payload in semantic_artifact_payloads(state_json, "column_annotation"):
        column = str(payload.get("column") or "").strip()
        if not column:
            continue
        label = str(payload.get("business_label") or payload.get("label") or column.replace("_", " ").title()).strip()
        terms.append(
            {
                "term": label,
                "normalized_term": _normalize(column),
                "definition": payload.get("description") or payload.get("source_text"),
                "synonyms": [value for value in [column, payload.get("business_label")] if value],
                "abbreviations": [],
                "source": "semantic_refinement",
            }
        )
    return terms


def merge_semantic_glossary(glossary: list[dict[str, Any]] | None, state_json: dict[str, Any]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for item in glossary or []:
        key = str(item.get("normalized_term") or item.get("term") or "").strip().lower()
        if key:
            merged[key] = dict(item)
    for item in semantic_glossary_terms(state_json):
        key = str(item.get("normalized_term") or item.get("term") or "").strip().lower()
        if key:
            merged[key] = {**merged.get(key, {}), **item}
    return list(merged.values())


def persist_semantic_glossary_terms(
    settings: Settings,
    *,
    tenant_id: str,
    domain_id: str,
    state_json: dict[str, Any],
) -> int:
    count = 0
    for term in semantic_glossary_terms(state_json):
        normalized = str(term.get("normalized_term") or "").strip()
        if not normalized:
            continue
        term_id = f"{tenant_id}__{domain_id}__refinement__{normalized}"
        execute_non_query(
            settings,
            """
            INSERT INTO public.quantyx_glossary_terms (
              term_id, tenant_id, domain_id, term, normalized_term, definition,
              synonyms, abbreviations, lifecycle_status, source_context_id, created_at, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, 'active', %s, now(), now())
            ON CONFLICT (term_id)
            DO UPDATE SET
              term = EXCLUDED.term,
              definition = EXCLUDED.definition,
              synonyms = EXCLUDED.synonyms,
              abbreviations = EXCLUDED.abbreviations,
              lifecycle_status = EXCLUDED.lifecycle_status,
              source_context_id = EXCLUDED.source_context_id,
              updated_at = now()
            """,
            [
                term_id,
                tenant_id,
                domain_id,
                term.get("term"),
                normalized,
                term.get("definition"),
                Json(term.get("synonyms") or []),
                Json(term.get("abbreviations") or []),
                "semantic_refinement",
            ],
        )
        count += 1
    return count


def semantic_interpretation_context(state_json: dict[str, Any]) -> dict[str, Any]:
    return {
        "interpretation_rules": semantic_artifact_payloads(state_json, "interpretation_rule"),
        "metric_refinements": semantic_artifact_payloads(state_json, "metric_refinement"),
        "chart_guidance": semantic_artifact_payloads(state_json, "chart_guidance"),
        "business_context": semantic_artifact_payloads(state_json, "business_context"),
    }
