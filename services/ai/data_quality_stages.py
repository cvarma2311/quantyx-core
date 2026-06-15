from __future__ import annotations

from typing import Any
import hashlib
import json
import logging
import os
import re
import ssl
import urllib.request
import uuid
from base64 import urlsafe_b64decode, urlsafe_b64encode

from services.ai.config import Settings
from services.ai.db import ScopedConnection, run_query


context = ssl._create_unverified_context()

logger = logging.getLogger(__name__)


def _planner_llm_enabled(settings: Settings | None) -> bool:
    return bool(settings and getattr(settings, "openai_api_key", None))


def _planner_llm_json(
    settings: Settings | None,
    *,
    system_prompt: str,
    user_payload: dict[str, Any],
) -> dict[str, Any] | None:
    if not _planner_llm_enabled(settings):
        return None
    model = os.getenv("DATA_QUALITY_STAGE_PLANNER_MODEL", getattr(settings, "openai_model", "gpt-4o-mini"))
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_payload)},
        ],
        "temperature": 0.0,
        "response_format": {"type": "json_object"},
    }
    request = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {settings.openai_api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=45, context=context) as response:
            body = json.loads(response.read().decode("utf-8"))
        return json.loads(body["choices"][0]["message"]["content"])
    except Exception as exc:
        logger.warning("data_quality_stages planner llm failed: %s", exc)
        return None


def load_dataset_context_tool(context_text: str | None) -> dict[str, Any]:
    text = str(context_text or "").strip()
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return {
        "context_text": text,
        "lines": lines,
    }


def domain_context_interpreter_tool(
    *,
    schema_graph: dict[str, Any],
    context_text: str | None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    parsed = _planner_llm_json(
        settings,
        system_prompt=(
            "You interpret business context for multi-table data-quality planning. "
            "Return JSON only with keys workflow_type, table_roles, join_intents, filter_intents, quality_objectives, context_lines. "
            "table_roles must be a list of objects with table_name and roles. "
            "join_intents must be a list of objects with left_table, right_table, section_text, workflow_intent. "
            "filter_intents must be a list. quality_objectives must be a list of strings."
        ),
        user_payload={
            "schema_tables": [
                {
                    "table_name": str(table.get("name") or "").strip(),
                    "columns": [str(col.get("name") or "").strip() for col in (table.get("columns") or []) if str(col.get("name") or "").strip()],
                }
                for table in (schema_graph.get("tables") or [])
                if str(table.get("name") or "").strip()
            ],
            "context_text": str(context_text or ""),
        },
    )
    if isinstance(parsed, dict):
        return {
            "workflow_type": str(parsed.get("workflow_type") or "multi_table_quality"),
            "table_roles": list(parsed.get("table_roles") or []),
            "join_intents": list(parsed.get("join_intents") or []),
            "filter_intents": list(parsed.get("filter_intents") or []),
            "quality_objectives": [str(item) for item in (parsed.get("quality_objectives") or [])],
            "context_lines": list(parsed.get("context_lines") or []),
        }
    context = load_dataset_context_tool(context_text)
    text = str(context.get("context_text") or "")
    tables = [
        str(table.get("name") or "").strip()
        for table in (schema_graph.get("tables") or [])
        if str(table.get("name") or "").strip()
    ]
    sections = _extract_reconciliation_sections(text)
    workflow_type = "reconciliation" if sections else "multi_table_quality"
    table_roles: list[dict[str, Any]] = []
    for table_name in tables:
        lowered = table_name.lower()
        role_hints: list[str] = []
        if "network" in lowered:
            role_hints.append("source_network")
        if "mediation" in lowered:
            role_hints.append("source_mediation")
        if "billing" in lowered:
            role_hints.append("source_billing")
        if "settlement" in lowered or "roaming" in lowered:
            role_hints.append("source_settlement")
        if not role_hints:
            role_hints.append("source_table")
        table_roles.append(
            {
                "table_name": table_name,
                "roles": role_hints,
            }
        )
    join_intents = [
        {
            "left_table": section.get("left_table"),
            "right_table": section.get("right_table"),
            "section_text": "\n".join(section.get("lines") or []),
            "workflow_intent": "reconciliation_pair",
        }
        for section in sections
    ]
    quality_objectives: list[str] = []
    for phrase in (
        "join health",
        "filter impact",
        "rejected records",
        "final dataset summary",
        "final surviving rows",
        "lineage overview",
        "lineage journey",
    ):
        if phrase in text.lower():
            quality_objectives.append(phrase.replace(" ", "_"))
    return {
        "workflow_type": workflow_type,
        "table_roles": table_roles,
        "join_intents": join_intents,
        "filter_intents": resolve_filter_candidates_tool(text),
        "quality_objectives": quality_objectives,
        "context_lines": context.get("lines") or [],
    }


def resolve_join_candidates_tool(
    *,
    schema_graph: dict[str, Any],
    context_text: str | None,
) -> list[dict[str, Any]]:
    text = str(context_text or "")
    join_candidates: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    explicit_refs = re.finditer(
        r"([A-Za-z_][\w]*)\.([A-Za-z_][\w]*)\s+must\s+exist\s+in\s+([A-Za-z_][\w]*)\.([A-Za-z_][\w]*)",
        text,
        flags=re.IGNORECASE,
    )
    for match in explicit_refs:
        child_table, child_col, parent_table, parent_col = match.groups()
        key = tuple(item.lower() for item in (child_table, child_col, parent_table, parent_col))
        if key in seen:
            continue
        seen.add(key)
        join_candidates.append(
            {
                "join_name": f"{child_table}_to_{parent_table}_{child_col}",
                "join_type": "reference_lookup",
                "left_table": child_table,
                "right_table": parent_table,
                "left_key": child_col,
                "right_key": parent_col,
                "source": "context_rule",
            }
        )

    tables = {
        str(table.get("name") or "").strip(): {
            str(column.get("name") or "").strip()
            for column in (table.get("columns") or [])
            if str(column.get("name") or "").strip()
        }
        for table in (schema_graph.get("tables") or [])
        if str(table.get("name") or "").strip()
    }
    join_candidates.extend(
        _resolve_reconciliation_context_joins(
            tables=tables,
            context_text=text,
            seen=seen,
        )
    )
    names = list(tables.keys())
    for left_table in names:
        for right_table in names:
            if left_table == right_table:
                continue
            left_columns = tables.get(left_table) or set()
            right_columns = tables.get(right_table) or set()
            for left_column in left_columns:
                if not left_column.endswith("_id"):
                    continue
                if left_column in right_columns:
                    key = tuple(item.lower() for item in (left_table, left_column, right_table, left_column))
                    if key in seen:
                        continue
                    seen.add(key)
                    join_candidates.append(
                        {
                            "join_name": f"{left_table}_to_{right_table}_{left_column}",
                            "join_type": "heuristic_shared_key",
                            "left_table": left_table,
                            "right_table": right_table,
                            "left_key": left_column,
                            "right_key": left_column,
                            "source": "schema_heuristic",
                        }
                    )
    return join_candidates


def shared_key_inference_tool(
    *,
    schema_graph: dict[str, Any],
    interpreted_context: dict[str, Any],
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    parsed = _planner_llm_json(
        settings,
        system_prompt=(
            "Infer shared keys for multi-table data-quality planning. "
            "Return JSON only with key shared_key_inferences. "
            "Each item must contain left_table, right_table, match_keys, and optional section_text. "
            "match_keys must be a list of objects with left_key, right_key, kind, confidence."
        ),
        user_payload={
            "schema_tables": [
                {
                    "table_name": str(table.get("name") or "").strip(),
                    "columns": [str(col.get("name") or "").strip() for col in (table.get("columns") or []) if str(col.get("name") or "").strip()],
                }
                for table in (schema_graph.get("tables") or [])
                if str(table.get("name") or "").strip()
            ],
            "interpreted_context": interpreted_context,
        },
    )
    if isinstance(parsed, dict) and isinstance(parsed.get("shared_key_inferences"), list):
        return list(parsed.get("shared_key_inferences") or [])
    tables = {
        str(table.get("name") or "").strip(): {
            str(column.get("name") or "").strip()
            for column in (table.get("columns") or [])
            if str(column.get("name") or "").strip()
        }
        for table in (schema_graph.get("tables") or [])
        if str(table.get("name") or "").strip()
    }
    table_lookup = _table_lookup(tables)
    inferences: list[dict[str, Any]] = []
    for intent in interpreted_context.get("join_intents") or []:
        left_lookup = table_lookup.get(str(intent.get("left_table") or "").lower())
        right_lookup = table_lookup.get(str(intent.get("right_table") or "").lower())
        if not left_lookup or not right_lookup:
            continue
        left_table, left_columns = left_lookup
        right_table, right_columns = right_lookup
        section_text = str(intent.get("section_text") or "")
        preferred_names = _extract_contextual_key_names(section_text)
        matches: list[dict[str, Any]] = []
        explicit_pairs = _extract_explicit_field_pairs(
            left_table=left_table,
            right_table=right_table,
            left_columns=left_columns,
            right_columns=right_columns,
            section_text=section_text,
        )
        for left_key, right_key in explicit_pairs:
            kind = "exact" if left_key == right_key else "semantic_alias"
            matches.append(
                {
                    "left_key": left_key,
                    "right_key": right_key,
                    "kind": kind,
                    "confidence": 0.9 if kind == "exact" else 0.8,
                }
            )
        shared_columns = sorted(
            left_column
            for left_column in left_columns
            if left_column in right_columns and (_score_candidate_key(left_column, section_text) > 0 or left_column.endswith("_id"))
        )
        for shared in shared_columns:
            matches.append(
                {
                    "left_key": shared,
                    "right_key": shared,
                    "kind": "exact",
                    "confidence": 0.95 if shared.lower() in preferred_names else 0.8,
                }
            )
        if not matches:
            left_key = _best_column_match(left_columns, section_text, preferred_names=preferred_names)
            right_key = _best_column_match(right_columns, section_text, preferred_names=preferred_names)
            if left_key and right_key:
                kind = "exact" if left_key == right_key else "semantic_alias"
                matches.append(
                    {
                        "left_key": left_key,
                        "right_key": right_key,
                        "kind": kind,
                        "confidence": 0.75 if kind == "exact" else 0.65,
                    }
                )
        if matches:
            inferences.append(
                {
                    "left_table": left_table,
                    "right_table": right_table,
                    "match_keys": matches,
                    "section_text": section_text,
            }
        )
    return inferences


def _extract_explicit_field_pairs(
    *,
    left_table: str,
    right_table: str,
    left_columns: set[str],
    right_columns: set[str],
    section_text: str,
) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    left_lower = {column.lower(): column for column in left_columns}
    right_lower = {column.lower(): column for column in right_columns}
    patterns = [
        re.compile(
            rf"\b{re.escape(left_table)}\s+([A-Za-z_][\w]*)\s+to\s+{re.escape(right_table)}\s+([A-Za-z_][\w]*)\b",
            flags=re.IGNORECASE,
        ),
        re.compile(
            rf"\b([A-Za-z_][\w]*)\s+to\s+{re.escape(right_table)}\s+([A-Za-z_][\w]*)\b",
            flags=re.IGNORECASE,
        ),
    ]
    for pattern in patterns:
        for match in pattern.finditer(section_text):
            left_name = str(match.group(1) or "").lower()
            right_name = str(match.group(2) or "").lower()
            left_key = left_lower.get(left_name)
            right_key = right_lower.get(right_name)
            if left_key and right_key:
                pairs.append((left_key, right_key))
    deduped: list[tuple[str, str]] = []
    seen_pairs: set[tuple[str, str]] = set()
    for pair in pairs:
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        deduped.append(pair)
    return deduped


def asymmetry_detection_tool(
    *,
    interpreted_context: dict[str, Any],
    shared_key_inferences: list[dict[str, Any]],
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    parsed = _planner_llm_json(
        settings,
        system_prompt=(
            "Detect join asymmetries for multi-table data-quality planning. "
            "Return JSON only with key asymmetry_detections. "
            "Each item must contain left_table, right_table, asymmetries. "
            "Each asymmetry must include asymmetry_type and comparison_mode and may include left_field, right_field, tolerance_seconds."
        ),
        user_payload={
            "interpreted_context": interpreted_context,
            "shared_key_inferences": shared_key_inferences,
        },
    )
    if isinstance(parsed, dict) and isinstance(parsed.get("asymmetry_detections"), list):
        return list(parsed.get("asymmetry_detections") or [])
    results: list[dict[str, Any]] = []
    intent_lookup = {
        (str(item.get("left_table") or "").lower(), str(item.get("right_table") or "").lower()): item
        for item in (interpreted_context.get("join_intents") or [])
    }
    for inference in shared_key_inferences:
        left_table = str(inference.get("left_table") or "")
        right_table = str(inference.get("right_table") or "")
        section_text = str(intent_lookup.get((left_table.lower(), right_table.lower()), {}).get("section_text") or inference.get("section_text") or "")
        asymmetries: list[dict[str, Any]] = []
        for key in inference.get("match_keys") or []:
            left_key = str(key.get("left_key") or "")
            right_key = str(key.get("right_key") or "")
            if left_key and right_key and left_key != right_key:
                asymmetry_type = "field_alias"
                comparison_mode = "key_match"
                if any(token in left_key.lower() for token in ("time", "timestamp", "date")) and any(
                    token in right_key.lower() for token in ("time", "timestamp", "date")
                ):
                    asymmetry_type = "temporal_alias"
                    comparison_mode = "windowed_match"
                asymmetries.append(
                    {
                        "asymmetry_type": asymmetry_type,
                        "left_field": left_key,
                        "right_field": right_key,
                        "comparison_mode": comparison_mode,
                    }
                )
        window_match = re.search(r"match window:\s*(\d+)\s*seconds", section_text, flags=re.IGNORECASE)
        if window_match:
            asymmetries.append(
                {
                    "asymmetry_type": "temporal_window",
                    "left_field": None,
                    "right_field": None,
                    "comparison_mode": "windowed_match",
                    "tolerance_seconds": int(window_match.group(1)),
                }
            )
        if re.search(r"\beligib", section_text, flags=re.IGNORECASE):
            asymmetries.append(
                {
                    "asymmetry_type": "eligibility_gate",
                    "comparison_mode": "filtered_match",
                }
            )
        results.append(
            {
                "left_table": left_table,
                "right_table": right_table,
                "asymmetries": asymmetries,
            }
        )
    return results


def join_strategy_builder_tool(
    *,
    shared_key_inferences: list[dict[str, Any]],
    asymmetry_detections: list[dict[str, Any]],
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    parsed = _planner_llm_json(
        settings,
        system_prompt=(
            "Build join strategies for multi-table data-quality planning. "
            "Return JSON only with key join_strategies. "
            "Each strategy must contain left_table, right_table, match_keys, strategy_type, asymmetries, and optional section_text."
        ),
        user_payload={
            "shared_key_inferences": shared_key_inferences,
            "asymmetry_detections": asymmetry_detections,
        },
    )
    if isinstance(parsed, dict) and isinstance(parsed.get("join_strategies"), list):
        return list(parsed.get("join_strategies") or [])
    asymmetry_lookup = {
        (str(item.get("left_table") or "").lower(), str(item.get("right_table") or "").lower()): item.get("asymmetries") or []
        for item in asymmetry_detections
    }
    strategies: list[dict[str, Any]] = []
    for inference in shared_key_inferences:
        left_table = str(inference.get("left_table") or "")
        right_table = str(inference.get("right_table") or "")
        asymmetries = asymmetry_lookup.get((left_table.lower(), right_table.lower()), [])
        has_window = any(str(item.get("asymmetry_type") or "") in {"temporal_window", "temporal_alias"} for item in asymmetries)
        has_alias = any(str(item.get("kind") or "") == "semantic_alias" for item in (inference.get("match_keys") or []))
        strategy_type = "windowed_temporal_join" if has_window else "alias_key_join" if has_alias else "exact_key_join"
        strategies.append(
            {
                "left_table": left_table,
                "right_table": right_table,
                "match_keys": inference.get("match_keys") or [],
                "strategy_type": strategy_type,
                "asymmetries": asymmetries,
                "section_text": inference.get("section_text"),
            }
        )
    return strategies


def _legacy_join_candidates_to_strategies(
    *,
    schema_graph: dict[str, Any],
    context_text: str | None,
) -> list[dict[str, Any]]:
    candidates = resolve_join_candidates_tool(
        schema_graph=schema_graph,
        context_text=context_text,
    )
    strategies: list[dict[str, Any]] = []
    for candidate in candidates:
        left_table = str(candidate.get("left_table") or "").strip()
        right_table = str(candidate.get("right_table") or "").strip()
        left_key = str(candidate.get("left_key") or "").strip()
        right_key = str(candidate.get("right_key") or "").strip()
        if not left_table or not right_table or not left_key or not right_key:
            continue
        strategy_type = "alias_key_join" if left_key != right_key else "exact_key_join"
        strategies.append(
            {
                "left_table": left_table,
                "right_table": right_table,
                "match_keys": [
                    {
                        "left_key": left_key,
                        "right_key": right_key,
                        "kind": "exact" if left_key == right_key else "semantic_alias",
                        "confidence": 0.9,
                    }
                ],
                "strategy_type": strategy_type,
                "asymmetries": [],
                "section_text": candidate.get("section_text"),
                "source": candidate.get("source"),
            }
        )
    return strategies


def _normalize_words(text: str) -> list[str]:
    return [token.lower() for token in re.findall(r"[A-Za-z_][\w]*", str(text or ""))]


def _extract_reconciliation_sections(context_text: str) -> list[dict[str, Any]]:
    lines = [line.rstrip() for line in str(context_text or "").splitlines()]
    sections: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    header_re = re.compile(
        r"^\s*(?:\d+\.\s*)?([A-Za-z_][\w]*)\s+to\s+([A-Za-z_][\w]*)\s+reconciliation\b",
        flags=re.IGNORECASE,
    )
    reconcile_re = re.compile(
        r"\bReconcile\s+([A-Za-z_][\w]*)\s+to\s+([A-Za-z_][\w]*)\b",
        flags=re.IGNORECASE,
    )
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        header_match = header_re.match(line)
        reconcile_match = reconcile_re.search(line)
        if header_match or reconcile_match:
            if current:
                sections.append(current)
            match = header_match or reconcile_match
            assert match is not None
            current = {
                "left_table": match.group(1),
                "right_table": match.group(2),
                "lines": [line],
            }
            continue
        if current is not None:
            current["lines"].append(line)
    if current:
        sections.append(current)
    return sections


def _table_lookup(table_columns: dict[str, set[str]]) -> dict[str, tuple[str, set[str]]]:
    return {name.lower(): (name, columns) for name, columns in table_columns.items()}


def _score_candidate_key(column_name: str, section_text: str) -> int:
    lowered = column_name.lower()
    score = 0
    if re.search(rf"\b{re.escape(lowered)}\b", section_text, flags=re.IGNORECASE):
        score += 10
    if lowered.endswith("_id"):
        score += 2
    if lowered in {"call_id", "cdr_id", "msisdn", "event_time", "rating_timestamp"}:
        score += 3
    return score


def _best_column_match(columns: set[str], section_text: str, preferred_names: list[str] | None = None) -> str | None:
    if not columns:
        return None
    lowered_map = {column.lower(): column for column in columns}
    for name in preferred_names or []:
        matched = lowered_map.get(str(name or "").strip().lower())
        if matched:
            return matched
    scored = sorted(
        ((column, _score_candidate_key(column, section_text)) for column in columns),
        key=lambda item: (-item[1], item[0]),
    )
    best_column, best_score = scored[0]
    return best_column if best_score > 0 else None


def _extract_contextual_key_names(section_text: str) -> list[str]:
    names = []
    for token in _normalize_words(section_text):
        lowered = token.lower()
        if lowered.endswith("_id") or lowered in {
            "msisdn",
            "imei",
            "imsi",
            "event_time",
            "rating_timestamp",
            "timestamp",
            "subscriber_id",
            "partner_id",
        }:
            names.append(lowered)
    return list(dict.fromkeys(names))


def _resolve_reconciliation_context_joins(
    *,
    tables: dict[str, set[str]],
    context_text: str,
    seen: set[tuple[str, str, str, str]],
) -> list[dict[str, Any]]:
    table_lookup = _table_lookup(tables)
    candidates: list[dict[str, Any]] = []
    for section in _extract_reconciliation_sections(context_text):
        left_lookup = table_lookup.get(str(section.get("left_table") or "").lower())
        right_lookup = table_lookup.get(str(section.get("right_table") or "").lower())
        if not left_lookup or not right_lookup:
            continue
        left_table, left_columns = left_lookup
        right_table, right_columns = right_lookup
        section_text = "\n".join(section.get("lines") or [])
        preferred_names = _extract_contextual_key_names(section_text)

        key_pairs: list[tuple[str, str]] = []
        shared_preferred = [name for name in preferred_names if name in {column.lower() for column in left_columns} and name in {column.lower() for column in right_columns}]
        for key_name in shared_preferred:
            left_key = next((column for column in left_columns if column.lower() == key_name), None)
            right_key = next((column for column in right_columns if column.lower() == key_name), None)
            if left_key and right_key:
                key_pairs.append((left_key, right_key))

        pair_patterns = [
            re.compile(
                rf"{re.escape(left_table)}(?:\s+[A-Za-z_][\w]*)*\s+to\s+{re.escape(right_table)}(?:\s+[A-Za-z_][\w]*)*\s+by\s+([A-Za-z_][\w]*)",
                flags=re.IGNORECASE,
            ),
            re.compile(
                rf"{re.escape(left_table)}(?:\s+[A-Za-z_][\w]*)*\s+to\s+{re.escape(right_table)}(?:\s+[A-Za-z_][\w]*)*\s+by\s+([A-Za-z_][\w]*)\s+and\s+([A-Za-z_][\w]*)",
                flags=re.IGNORECASE,
            ),
            re.compile(
                rf"{re.escape(left_table)}(?:\s+[A-Za-z_][\w]*)*\s+([A-Za-z_][\w]*)\s+to\s+{re.escape(right_table)}(?:\s+[A-Za-z_][\w]*)*\s+([A-Za-z_][\w]*)",
                flags=re.IGNORECASE,
            ),
        ]
        for pattern in pair_patterns:
            for match in pattern.finditer(section_text):
                groups = [group for group in match.groups() if group]
                if len(groups) == 1:
                    name = groups[0].lower()
                    left_key = next((column for column in left_columns if column.lower() == name), None)
                    right_key = next((column for column in right_columns if column.lower() == name), None)
                    if left_key and right_key:
                        key_pairs.append((left_key, right_key))
                elif len(groups) >= 2:
                    left_name = groups[0].lower()
                    right_name = groups[1].lower()
                    left_key = next((column for column in left_columns if column.lower() == left_name), None)
                    right_key = next((column for column in right_columns if column.lower() == right_name), None)
                    if left_key and right_key:
                        key_pairs.append((left_key, right_key))

        if not key_pairs:
            shared_ids = sorted(
                {
                    left_column
                    for left_column in left_columns
                    if left_column.lower() == left_column and left_column in right_columns and left_column.endswith("_id")
                }
            )
            if shared_ids:
                key_pairs.append((shared_ids[0], shared_ids[0]))

        if not key_pairs:
            left_key = _best_column_match(left_columns, section_text, preferred_names=preferred_names)
            right_key = _best_column_match(right_columns, section_text, preferred_names=preferred_names)
            if left_key and right_key:
                key_pairs.append((left_key, right_key))

        deduped_pairs: list[tuple[str, str]] = []
        seen_pairs: set[tuple[str, str]] = set()
        for left_key, right_key in key_pairs:
            pair = (left_key, right_key)
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            deduped_pairs.append(pair)
        for left_key, right_key in deduped_pairs:
            key = tuple(item.lower() for item in (left_table, left_key, right_table, right_key))
            if key in seen:
                continue
            seen.add(key)
            candidates.append(
                {
                    "join_name": f"{left_table}_to_{right_table}_{left_key}_to_{right_key}",
                    "join_type": "context_reconciliation",
                    "left_table": left_table,
                    "right_table": right_table,
                    "left_key": left_key,
                    "right_key": right_key,
                    "source": "reconciliation_context",
                    "section_text": section_text,
                }
            )
    return candidates


def domain_evidence_sampler_tool(
    *,
    schema_graph: dict[str, Any],
    interpreted_context: dict[str, Any],
) -> dict[str, Any]:
    tables = [
        str(table.get("name") or "").strip()
        for table in (schema_graph.get("tables") or [])
        if str(table.get("name") or "").strip()
    ]
    return {
        "table_count": len(tables),
        "join_intent_count": len(interpreted_context.get("join_intents") or []),
        "sample_plan": [
            {
                "table_name": table_name,
                "sample_type": "planning_profile",
            }
            for table_name in tables
        ],
    }


def resolve_filter_candidates_tool(context_text: str | None) -> list[dict[str, Any]]:
    text = str(context_text or "")
    candidates: list[dict[str, Any]] = []
    patterns = [
        r"\bonly\s+([A-Za-z_][\w.]*(?:\s*=\s*[^.,;\n]+)?)",
        r"\bwhere\s+([^.;\n]+)",
        r"\bfilter\s+(?:to|for|out)?\s*([^.;\n]+)",
    ]
    seen: set[str] = set()
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            expression = " ".join(str(match.group(1) or "").split()).strip()
            if not expression:
                continue
            key = expression.lower()
            if key in seen:
                continue
            seen.add(key)
            candidates.append(
                {
                    "filter_name": f"filter_{len(candidates) + 1}",
                    "expression_text": expression,
                    "parsed_filter": _parse_filter_expression(expression),
                    "source": "context_text",
                }
            )
    return candidates


def filter_intent_resolution_tool(
    *,
    schema_graph: dict[str, Any],
    context_text: str | None,
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    parsed = _planner_llm_json(
        settings,
        system_prompt=(
            "Extract structured filter intents for multi-table data-quality planning. "
            "Return JSON only with key filter_intents. "
            "Each item must contain filter_name, expression_text, parsed_filter, and source. "
            "parsed_filter should include table_name, column_name, operator, and value when available."
        ),
        user_payload={
            "schema_tables": [
                {
                    "table_name": str(table.get("name") or "").strip(),
                    "columns": [str(col.get("name") or "").strip() for col in (table.get("columns") or []) if str(col.get("name") or "").strip()],
                }
                for table in (schema_graph.get("tables") or [])
                if str(table.get("name") or "").strip()
            ],
            "context_text": str(context_text or ""),
        },
    )
    if isinstance(parsed, dict) and isinstance(parsed.get("filter_intents"), list):
        return list(parsed.get("filter_intents") or [])
    return resolve_filter_candidates_tool(context_text)


def stage_plan_compiler_tool(
    *,
    schema_graph: dict[str, Any],
    interpreted_context: dict[str, Any],
    join_strategies: list[dict[str, Any]],
    filter_intents: list[dict[str, Any]],
) -> dict[str, Any]:
    tables = [
        str(table.get("name") or "").strip()
        for table in (schema_graph.get("tables") or [])
        if str(table.get("name") or "").strip()
    ]
    stages: list[dict[str, Any]] = []
    joins: list[dict[str, Any]] = []
    stage_seq = 1
    for table_name in tables:
        stages.append(
            {
                "stage_id": f"dqstage_{uuid.uuid4().hex[:12]}",
                "stage_seq": stage_seq,
                "stage_name": f"source_profile_{table_name}",
                "stage_type": "source_profile",
                "input_tables": [table_name],
                "output_dataset": table_name,
            }
        )
        stage_seq += 1
    for strategy in join_strategies:
        for match_key in (strategy.get("match_keys") or []):
            stage_id = f"dqstage_{uuid.uuid4().hex[:12]}"
            left_table = str(strategy.get("left_table") or "").strip()
            right_table = str(strategy.get("right_table") or "").strip()
            left_key = str(match_key.get("left_key") or "").strip()
            right_key = str(match_key.get("right_key") or "").strip()
            if not left_table or not right_table or not left_key or not right_key:
                continue
            join_with_id = {
                "join_artifact_id": f"dqjoin_{uuid.uuid4().hex[:12]}",
                "stage_id": stage_id,
                "join_name": f"{left_table}_to_{right_table}_{left_key}_to_{right_key}",
                "join_type": str(strategy.get("strategy_type") or "exact_key_join"),
                "left_table": left_table,
                "right_table": right_table,
                "left_key": left_key,
                "right_key": right_key,
                "source": "compiled_join_strategy",
                "match_key_kind": match_key.get("kind"),
                "match_key_confidence": match_key.get("confidence"),
                "asymmetries": strategy.get("asymmetries") or [],
                "section_text": strategy.get("section_text"),
            }
            joins.append(join_with_id)
            stages.append(
                {
                    "stage_id": stage_id,
                    "stage_seq": stage_seq,
                    "stage_name": str(join_with_id.get("join_name") or f"join_{stage_seq}"),
                    "stage_type": "join_validation",
                    "input_tables": [left_table, right_table],
                    "join": join_with_id,
                }
            )
            stage_seq += 1
    for candidate in filter_intents:
        parsed_filter = candidate.get("parsed_filter") or {}
        filter_table = str(parsed_filter.get("table_name") or "").strip()
        stages.append(
            {
                "stage_id": f"dqstage_{uuid.uuid4().hex[:12]}",
                "stage_seq": stage_seq,
                "stage_name": str(candidate.get("filter_name") or f"filter_{stage_seq}"),
                "stage_type": "filter",
                "input_tables": [filter_table] if filter_table else [],
                "output_dataset": filter_table or None,
                "expression": candidate,
            }
        )
        stage_seq += 1
    stages.append(
        {
            "stage_id": f"dqstage_{uuid.uuid4().hex[:12]}",
            "stage_seq": stage_seq,
            "stage_name": "final_dataset_projection",
            "stage_type": "final_projection",
            "input_tables": tables,
        }
    )
    return {
        "stage_count": len(stages),
        "source_table_count": len(tables),
        "join_stage_count": len(joins),
        "filter_stage_count": len(filter_intents),
        "stages": stages,
        "joins": joins,
        "filters": filter_intents,
    }


def _parse_filter_expression(expression: str | None) -> dict[str, Any] | None:
    text = " ".join(str(expression or "").split()).strip()
    if not text:
        return None
    match = re.match(
        r"^(?:(?P<table>[A-Za-z_][\w]*)\.)?(?P<column>[A-Za-z_][\w]*)\s+must\s+be\s+one\s+of\s+(?P<values>.+)$",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        raw_values = str(match.group("values") or "").strip().rstrip(".")
        values = [
            item.strip().strip("'").strip('"')
            for item in re.split(r",|\bor\b", raw_values, flags=re.IGNORECASE)
            if item.strip().strip("'").strip('"')
        ]
        return {
            "table_name": match.group("table"),
            "column_name": match.group("column"),
            "operator": "IN",
            "value": values,
        }
    match = re.match(
        r"^(?P<label>.+?)\s+age\s+(?:must|should)\s+be\s+between\s+(?P<min>\d+(?:\.\d+)?)\s+and\s+(?P<max>\d+(?:\.\d+)?)(?:.*using\s+(?P<dob>[A-Za-z_][\w]*)\s+and\s+(?P<created>[A-Za-z_][\w]*))?$",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        return {
            "table_name": None,
            "column_name": match.group("dob") or "dob",
            "reference_column": match.group("created") or "created_date",
            "operator": "AGE BETWEEN",
            "value": [float(match.group("min")), float(match.group("max"))],
        }
    match = re.match(
        r"^(?:(?P<table>[A-Za-z_][\w]*)\.)?(?P<column>[A-Za-z_][\w]*)\s*(?P<op>=|!=|<>|>=|<=|>|<)\s*(?P<value>.+)$",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        raw_value = str(match.group("value") or "").strip().strip("'").strip('"')
        return {
            "table_name": match.group("table"),
            "column_name": match.group("column"),
            "operator": match.group("op"),
            "value": raw_value,
        }
    match = re.match(
        r"^(?:(?P<table>[A-Za-z_][\w]*)\.)?(?P<column>[A-Za-z_][\w]*)\s+is\s+(?P<neg>not\s+)?null$",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        return {
            "table_name": match.group("table"),
            "column_name": match.group("column"),
            "operator": "is_not_null" if match.group("neg") else "is_null",
            "value": None,
        }
    return None


def _build_filter_predicate(parsed_filter: dict[str, Any] | None) -> tuple[str | None, list[Any]]:
    if not isinstance(parsed_filter, dict):
        return None, []
    column_name = str(parsed_filter.get("column_name") or "").strip()
    operator = str(parsed_filter.get("operator") or "").strip().lower()
    if not column_name or not operator:
        return None, []
    q_col = _qident(column_name)
    if operator == "is_null":
        return f"{q_col} IS NULL", []
    if operator == "is_not_null":
        return f"{q_col} IS NOT NULL", []
    if operator == "like":
        value = parsed_filter.get("value")
        if value is None:
            return None, []
        return f"{q_col}::text LIKE %s", [str(value)]
    if operator == "in":
        value = parsed_filter.get("value")
        if not isinstance(value, list) or not value:
            return None, []
        placeholders = ", ".join(["%s"] * len(value))
        return f"{q_col}::text IN ({placeholders})", [str(item) for item in value]
    if operator == "age between":
        value = parsed_filter.get("value")
        if not isinstance(value, list) or len(value) != 2:
            return None, []
        min_age, max_age = value
        reference_column = str(parsed_filter.get("reference_column") or parsed_filter.get("derived_reference_column") or "created_date").strip()
        if not reference_column:
            return None, []
        q_ref_col = _qident(reference_column)
        return (
            f"DATE_PART('year', AGE({q_ref_col}::date, {q_col}::date)) BETWEEN %s AND %s",
            [min_age, max_age],
        )
    sql_operator = "<>" if operator == "!=" else operator
    value = parsed_filter.get("value")
    if value is None:
        return None, []
    return f"{q_col}::text {sql_operator} %s", [str(value)]


def _qident(name: str | None) -> str:
    return '"' + str(name or "").replace('"', '""') + '"'


def _qtable(schema_name: str, table_name: str) -> str:
    return f"{_qident(schema_name)}.{_qident(table_name)}"


def _lineage_id(*parts: Any) -> str:
    payload = "|".join(str(part or "").strip() for part in parts)
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:20]
    encoded = urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")
    return f"dqlin_{encoded}_{digest}"


def parse_lineage_id(lineage_id: str | None) -> dict[str, Any] | None:
    text = str(lineage_id or "").strip()
    if not text.startswith("dqlin_"):
        return None
    try:
        encoded, _digest = text[len("dqlin_"):].rsplit("_", 1)
        padded = encoded + "=" * (-len(encoded) % 4)
        decoded = urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
        parts = decoded.split("|")
        return {"raw": decoded, "parts": parts}
    except Exception:
        return None


def _count_rows(
    settings: Any,
    *,
    scoped_conn: ScopedConnection,
    schema_name: str,
    table_name: str,
) -> int | None:
    rows = run_query(
        settings,
        f"SELECT COUNT(*) AS row_count FROM {_qtable(schema_name, table_name)}",
        [],
        scoped_conn=scoped_conn,
        statement_timeout_ms=60000,
    )
    row = (rows or [{}])[0]
    try:
        return int(row.get("row_count") or 0)
    except (TypeError, ValueError):
        return None


def _count_scalar(
    settings: Any,
    *,
    scoped_conn: ScopedConnection,
    sql: str,
    params: list[Any] | None = None,
) -> int | None:
    rows = run_query(
        settings,
        sql,
        params or [],
        scoped_conn=scoped_conn,
        statement_timeout_ms=60000,
    )
    row = (rows or [{}])[0]
    for key in ("row_count", "matched_row_count", "unmatched_row_count", "duplicate_match_count", "count"):
        if key in row:
            try:
                return int(row.get(key) or 0)
            except (TypeError, ValueError):
                return None
    if row:
        try:
            return int(next(iter(row.values())) or 0)
        except (StopIteration, TypeError, ValueError):
            return None
    return None


def _sample_rows(
    settings: Any,
    *,
    scoped_conn: ScopedConnection,
    sql: str,
    params: list[Any] | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    capped_sql = f"{sql} LIMIT {max(1, min(int(limit or 10), 100))}"
    return run_query(
        settings,
        capped_sql,
        params or [],
        scoped_conn=scoped_conn,
        statement_timeout_ms=60000,
    )


def fetch_stage_snapshot_rows_tool(
    settings: Any,
    *,
    scoped_conn: ScopedConnection | None,
    schema_name: str,
    stage: dict[str, Any],
    limit: int = 1200,
    offset: int = 0,
) -> list[dict[str, Any]]:
    if scoped_conn is None:
        return []
    stage_type = str(stage.get("stage_type") or "").strip()
    row_limit = max(1, min(int(limit or 1200), 4000))
    row_offset = max(0, int(offset or 0))
    if stage_type == "source_profile":
        table_name = str(stage.get("output_dataset") or "").strip()
        if not table_name:
            return []
        rows = run_query(
            settings,
            (
                f"SELECT ctid::text AS __row_ref, * "
                f"FROM {_qtable(schema_name, table_name)} "
                f"ORDER BY ctid LIMIT {row_limit} OFFSET {row_offset}"
            ),
            [],
            scoped_conn=scoped_conn,
            statement_timeout_ms=120000,
        )
        for row in rows:
            row["row_lineage_id"] = _lineage_id(table_name, row.get("__row_ref"))
        return rows
    if stage_type == "join_validation":
        join = stage.get("join") or {}
        left_table = str(join.get("left_table") or "").strip()
        right_table = str(join.get("right_table") or "").strip()
        left_key = str(join.get("left_key") or "").strip()
        right_key = str(join.get("right_key") or "").strip()
        if not left_table or not right_table or not left_key or not right_key:
            return []
        q_left_table = _qtable(schema_name, left_table)
        q_right_table = _qtable(schema_name, right_table)
        q_left_key = _qident(left_key)
        q_right_key = _qident(right_key)
        rows = run_query(
            settings,
            (
                f"SELECT l.ctid::text AS __left_row_ref, r.ctid::text AS __right_row_ref, "
                f"l.{q_left_key} AS left_key_value, r.{q_right_key} AS right_key_value "
                f"FROM {q_left_table} l "
                f"JOIN {q_right_table} r ON r.{q_right_key} = l.{q_left_key} "
                f"WHERE l.{q_left_key} IS NOT NULL "
                f"ORDER BY l.ctid LIMIT {row_limit} OFFSET {row_offset}"
            ),
            [],
            scoped_conn=scoped_conn,
            statement_timeout_ms=120000,
        )
        for row in rows:
            row["left_row_lineage_id"] = _lineage_id(left_table, row.get("__left_row_ref"))
            row["right_row_lineage_id"] = _lineage_id(right_table, row.get("__right_row_ref"))
            row["row_lineage_id"] = _lineage_id(left_table, row.get("__left_row_ref"), right_table, row.get("__right_row_ref"))
        return rows
    if stage_type == "filter":
        parsed_filter = (stage.get("summary_json") or {}).get("parsed_filter") or (stage.get("expression") or {}).get("parsed_filter")
        predicate, params = _build_filter_predicate(parsed_filter)
        table_name = str((parsed_filter or {}).get("table_name") or stage.get("output_dataset") or "").strip()
        if not table_name or not predicate:
            return []
        rows = run_query(
            settings,
            (
                f"SELECT ctid::text AS __row_ref, * "
                f"FROM {_qtable(schema_name, table_name)} "
                f"WHERE {predicate} ORDER BY ctid LIMIT {row_limit} OFFSET {row_offset}"
            ),
            params,
            scoped_conn=scoped_conn,
            statement_timeout_ms=120000,
        )
        for row in rows:
            row["row_lineage_id"] = _lineage_id(table_name, row.get("__row_ref"))
        return rows
    return []


def fetch_final_dataset_rows_tool(
    settings: Any,
    *,
    scoped_conn: ScopedConnection | None,
    schema_name: str,
    stages: list[dict[str, Any]],
    final_dataset: dict[str, Any] | None,
    limit: int = 1200,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    if scoped_conn is None:
        return [], None
    final_dataset = dict(final_dataset or {})
    preferred_stage_name = str(final_dataset.get("final_stage_name") or "").strip()
    chosen_stage: dict[str, Any] | None = None
    if preferred_stage_name:
        for stage in reversed(stages):
            if str(stage.get("stage_name") or "").strip() == preferred_stage_name and str(stage.get("stage_type") or "").strip() != "final_projection":
                chosen_stage = stage
                break
    if chosen_stage is None:
        for stage in reversed(stages):
            if stage.get("output_row_count") is not None and str(stage.get("stage_type") or "").strip() in {"join_validation", "source_profile", "filter"}:
                chosen_stage = stage
                break
    if chosen_stage is None and stages:
        for stage in reversed(stages):
            if str(stage.get("stage_type") or "").strip() in {"join_validation", "source_profile", "filter"}:
                chosen_stage = stage
                break
    if chosen_stage is None:
        return [], None
    return (
        fetch_stage_snapshot_rows_tool(
            settings,
            scoped_conn=scoped_conn,
            schema_name=schema_name,
            stage=chosen_stage,
            limit=limit,
            offset=offset,
        ),
        chosen_stage,
    )


def build_final_dataset_snapshot_tool(
    settings: Any,
    *,
    scoped_conn: ScopedConnection | None,
    schema_name: str,
    stages: list[dict[str, Any]],
    final_dataset: dict[str, Any] | None,
    sample_limit: int = 2000,
) -> dict[str, Any]:
    rows, basis_stage = fetch_final_dataset_rows_tool(
        settings,
        scoped_conn=scoped_conn,
        schema_name=schema_name,
        stages=stages,
        final_dataset=final_dataset,
        limit=max(1, min(int(sample_limit or 2000), 2000)),
        offset=0,
    )
    return {
        "basis_stage": dict(basis_stage or {}),
        "sample_rows": list(rows or []),
        "sample_row_count": len(rows or []),
        "sample_limit": max(1, min(int(sample_limit or 2000), 2000)),
        "row_source": "live_stage_snapshot" if rows else "unavailable",
    }


def _build_join_row_outcomes(
    *,
    join: dict[str, Any],
    unmatched_left_rows: list[dict[str, Any]],
    unmatched_right_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    outcomes: list[dict[str, Any]] = []
    join_name = str(join.get("join_name") or "").strip()
    left_table = str(join.get("left_table") or "").strip()
    right_table = str(join.get("right_table") or "").strip()
    left_key = str(join.get("left_key") or "").strip()
    right_key = str(join.get("right_key") or "").strip()
    for row in unmatched_left_rows:
        row_ref = str(row.get("__left_row_ref") or "").strip()
        if not row_ref:
            continue
        outcomes.append(
            {
                "outcome_id": f"dqout_{uuid.uuid4().hex[:12]}",
                "stage_id": str(join.get("stage_id") or ""),
                "stage_name": join_name,
                "outcome_type": "rejected",
                "row_lineage_id": _lineage_id(left_table, row_ref),
                "row_ref": row_ref,
                "source_table": left_table,
                "source_key_json": {left_key: row.get("left_key_value")},
                "reason_code": "join_unmatched_left",
                "reason_detail": f"Row from {left_table} did not match {right_table} on {left_key} -> {right_key}",
                "row_data_json": row,
            }
        )
    for row in unmatched_right_rows:
        row_ref = str(row.get("__right_row_ref") or "").strip()
        if not row_ref:
            continue
        outcomes.append(
            {
                "outcome_id": f"dqout_{uuid.uuid4().hex[:12]}",
                "stage_id": str(join.get("stage_id") or ""),
                "stage_name": join_name,
                "outcome_type": "join_exception",
                "row_lineage_id": _lineage_id(right_table, row_ref),
                "row_ref": row_ref,
                "source_table": right_table,
                "source_key_json": {right_key: row.get("right_key_value")},
                "reason_code": "join_unmatched_right",
                "reason_detail": f"Row from {right_table} was not referenced by {left_table} on {right_key}",
                "row_data_json": row,
            }
        )
    return outcomes


def _compute_source_stage_metrics(
    settings: Any,
    *,
    scoped_conn: ScopedConnection,
    schema_name: str,
    stage: dict[str, Any],
    tenant_id: str,
    domain_id: str,
) -> dict[str, Any]:
    table_name = str(stage.get("output_dataset") or "").strip()
    if not table_name:
        return stage
    row_count = _count_rows(
        settings,
        scoped_conn=scoped_conn,
        schema_name=schema_name,
        table_name=table_name,
    )
    summary = dict(stage)
    summary.update(
        {
            "table_name": table_name,
            "measurement_status": "measured" if row_count is not None else "unavailable",
            "lineage_basis": f"{table_name}.ctid",
            "evidence_path": (
                f"/data-quality/evidence/stages/{stage['stage_id']}?tenant_id={tenant_id}&domain_id={domain_id}"
            ),
        }
    )
    return {
        **stage,
        "input_row_count": row_count,
        "output_row_count": row_count,
        "rejected_row_count": 0 if row_count is not None else None,
        "summary_json": summary,
    }


def _build_filter_row_outcomes(
    *,
    stage: dict[str, Any],
    table_name: str,
    key_column: str,
    rejected_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    outcomes: list[dict[str, Any]] = []
    for row in rejected_rows:
        row_ref = str(row.get("__row_ref") or "").strip()
        if not row_ref:
            continue
        outcomes.append(
            {
                "outcome_id": f"dqout_{uuid.uuid4().hex[:12]}",
                "stage_id": str(stage.get("stage_id") or ""),
                "stage_name": str(stage.get("stage_name") or ""),
                "outcome_type": "rejected",
                "row_lineage_id": _lineage_id(table_name, row_ref),
                "row_ref": row_ref,
                "source_table": table_name,
                "source_key_json": ({key_column: row.get(key_column)} if key_column and key_column in row else {}),
                "reason_code": "filter_rejected",
                "reason_detail": f"Row did not satisfy filter: {str((stage.get('expression') or {}).get('expression_text') or '').strip()}",
                "row_data_json": row,
            }
        )
    return outcomes


def _compute_filter_stage_metrics(
    settings: Any,
    *,
    scoped_conn: ScopedConnection,
    schema_name: str,
    stage: dict[str, Any],
    tenant_id: str,
    domain_id: str,
) -> dict[str, Any]:
    expression = stage.get("expression") or {}
    parsed_filter = expression.get("parsed_filter") or {}
    table_name = str(parsed_filter.get("table_name") or stage.get("output_dataset") or "").strip()
    predicate, params = _build_filter_predicate(parsed_filter)
    if not table_name or not predicate:
        return {
            **stage,
            "summary_json": {
                **stage,
                "measurement_status": "planned_only",
                "parsed_filter": parsed_filter,
                "evidence_path": f"/data-quality/evidence/stages/{stage['stage_id']}?tenant_id={tenant_id}&domain_id={domain_id}",
            },
        }
    input_row_count = _count_rows(
        settings,
        scoped_conn=scoped_conn,
        schema_name=schema_name,
        table_name=table_name,
    )
    output_row_count = _count_scalar(
        settings,
        scoped_conn=scoped_conn,
        sql=f"SELECT COUNT(*) AS row_count FROM {_qtable(schema_name, table_name)} WHERE {predicate}",
        params=params,
    )
    rejected_predicate = f"NOT ({predicate})"
    rejected_rows = _sample_rows(
        settings,
        scoped_conn=scoped_conn,
        sql=f"SELECT ctid::text AS __row_ref, * FROM {_qtable(schema_name, table_name)} WHERE {rejected_predicate} ORDER BY ctid",
        params=params,
        limit=10,
    )
    key_column = str(parsed_filter.get("column_name") or "").strip()
    rejected_row_count = None
    if input_row_count is not None and output_row_count is not None:
        rejected_row_count = max(0, int(input_row_count) - int(output_row_count))
    summary = {
        **stage,
        "parsed_filter": parsed_filter,
        "expression_text": expression.get("expression_text"),
        "measurement_status": "measured" if input_row_count is not None and output_row_count is not None else "planned_only",
        "lineage_basis": f"{table_name}.ctid",
        "evidence_path": f"/data-quality/evidence/stages/{stage['stage_id']}?tenant_id={tenant_id}&domain_id={domain_id}",
        "sample_rejected_rows": rejected_rows,
    }
    return {
        **stage,
        "output_dataset": table_name,
        "input_row_count": input_row_count,
        "output_row_count": output_row_count,
        "rejected_row_count": rejected_row_count,
        "row_outcomes": _build_filter_row_outcomes(
            stage=stage,
            table_name=table_name,
            key_column=key_column,
            rejected_rows=rejected_rows,
        ),
        "summary_json": summary,
    }


def _find_previous_stage_for_table(stages: list[dict[str, Any]], *, stage_seq: int, table_name: str) -> dict[str, Any] | None:
    table_name = str(table_name or "").strip()
    for stage in reversed(stages):
        if int(stage.get("stage_seq") or 0) >= int(stage_seq or 0):
            continue
        if str(stage.get("output_dataset") or "").strip() == table_name:
            return stage
        if table_name and table_name in [str(item or "").strip() for item in (stage.get("input_tables") or [])]:
            return stage
    return None


def _build_lineage_edges(
    *,
    stages: list[dict[str, Any]],
    row_outcomes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    stage_by_id = {str(item.get("stage_id") or ""): item for item in stages if str(item.get("stage_id") or "").strip()}
    edges: list[dict[str, Any]] = []
    for outcome in row_outcomes:
        row_lineage_id = str(outcome.get("row_lineage_id") or "").strip()
        stage_id = str(outcome.get("stage_id") or "").strip()
        current_stage = stage_by_id.get(stage_id) or {}
        source_table = str(outcome.get("source_table") or current_stage.get("output_dataset") or "").strip()
        previous_stage = _find_previous_stage_for_table(
            stages,
            stage_seq=int(current_stage.get("stage_seq") or 0),
            table_name=source_table,
        )
        reason_code = str(outcome.get("reason_code") or outcome.get("outcome_type") or "transition").strip()
        if not row_lineage_id:
            continue
        edges.append(
            {
                "edge_id": f"dqedge_{uuid.uuid4().hex[:12]}",
                "row_lineage_id": row_lineage_id,
                "from_stage_id": previous_stage.get("stage_id") if previous_stage else None,
                "from_stage_name": previous_stage.get("stage_name") if previous_stage else source_table,
                "to_stage_id": stage_id or None,
                "to_stage_name": outcome.get("stage_name") or current_stage.get("stage_name"),
                "edge_type": reason_code,
                "summary_json": {
                    "row_ref": outcome.get("row_ref"),
                    "source_table": source_table,
                    "reason_detail": outcome.get("reason_detail"),
                },
            }
        )
    return edges


def _compute_join_metrics(
    settings: Any,
    *,
    scoped_conn: ScopedConnection,
    schema_name: str,
    join: dict[str, Any],
    tenant_id: str,
    domain_id: str,
) -> dict[str, Any]:
    left_table = str(join.get("left_table") or "").strip()
    right_table = str(join.get("right_table") or "").strip()
    left_key = str(join.get("left_key") or "").strip()
    right_key = str(join.get("right_key") or "").strip()
    if not left_table or not right_table or not left_key or not right_key:
        return join
    q_left_table = _qtable(schema_name, left_table)
    q_right_table = _qtable(schema_name, right_table)
    q_left_key = _qident(left_key)
    q_right_key = _qident(right_key)
    left_count = _count_rows(
        settings,
        scoped_conn=scoped_conn,
        schema_name=schema_name,
        table_name=left_table,
    )
    right_count = _count_rows(
        settings,
        scoped_conn=scoped_conn,
        schema_name=schema_name,
        table_name=right_table,
    )
    matched_left_row_count = _count_scalar(
        settings,
        scoped_conn=scoped_conn,
        sql=(
            f"SELECT COUNT(*) AS matched_row_count "
            f"FROM {q_left_table} l "
            f"WHERE l.{q_left_key} IS NOT NULL "
            f"AND EXISTS (SELECT 1 FROM {q_right_table} r WHERE r.{q_right_key} = l.{q_left_key})"
        ),
    )
    unmatched_left_row_count = _count_scalar(
        settings,
        scoped_conn=scoped_conn,
        sql=(
            f"SELECT COUNT(*) AS unmatched_row_count "
            f"FROM {q_left_table} l "
            f"WHERE l.{q_left_key} IS NULL "
            f"OR NOT EXISTS (SELECT 1 FROM {q_right_table} r WHERE r.{q_right_key} = l.{q_left_key})"
        ),
    )
    unmatched_right_row_count = _count_scalar(
        settings,
        scoped_conn=scoped_conn,
        sql=(
            f"SELECT COUNT(*) AS unmatched_row_count "
            f"FROM {q_right_table} r "
            f"WHERE r.{q_right_key} IS NULL "
            f"OR NOT EXISTS (SELECT 1 FROM {q_left_table} l WHERE l.{q_left_key} = r.{q_right_key})"
        ),
    )
    duplicate_match_count = _count_scalar(
        settings,
        scoped_conn=scoped_conn,
        sql=(
            "SELECT COUNT(*) AS duplicate_match_count "
            "FROM ("
            f"  SELECT l.ctid "
            f"  FROM {q_left_table} l "
            f"  JOIN {q_right_table} r ON r.{q_right_key} = l.{q_left_key} "
            f" WHERE l.{q_left_key} IS NOT NULL "
            " GROUP BY l.ctid "
            " HAVING COUNT(*) > 1"
            ") dup"
        ),
    )
    matched_sample_rows = _sample_rows(
        settings,
        scoped_conn=scoped_conn,
        sql=(
            f"SELECT l.ctid::text AS __left_row_ref, r.ctid::text AS __right_row_ref, "
            f"l.{q_left_key} AS left_key_value, r.{q_right_key} AS right_key_value "
            f"FROM {q_left_table} l "
            f"JOIN {q_right_table} r ON r.{q_right_key} = l.{q_left_key} "
            f"WHERE l.{q_left_key} IS NOT NULL"
        ),
        limit=10,
    )
    unmatched_left_sample_rows = _sample_rows(
        settings,
        scoped_conn=scoped_conn,
        sql=(
            f"SELECT l.ctid::text AS __left_row_ref, l.{q_left_key} AS left_key_value "
            f"FROM {q_left_table} l "
            f"WHERE l.{q_left_key} IS NULL "
            f"OR NOT EXISTS (SELECT 1 FROM {q_right_table} r WHERE r.{q_right_key} = l.{q_left_key})"
        ),
        limit=10,
    )
    unmatched_right_sample_rows = _sample_rows(
        settings,
        scoped_conn=scoped_conn,
        sql=(
            f"SELECT r.ctid::text AS __right_row_ref, r.{q_right_key} AS right_key_value "
            f"FROM {q_right_table} r "
            f"WHERE r.{q_right_key} IS NULL "
            f"OR NOT EXISTS (SELECT 1 FROM {q_left_table} l WHERE l.{q_left_key} = r.{q_right_key})"
        ),
        limit=10,
    )
    summary = dict(join)
    summary.update(
        {
            "left_row_count": left_count,
            "right_row_count": right_count,
            "matched_left_row_count": matched_left_row_count,
            "unmatched_left_row_count": unmatched_left_row_count,
            "unmatched_right_row_count": unmatched_right_row_count,
            "duplicate_match_count": duplicate_match_count,
            "measurement_status": "measured",
            "evidence_path": (
                f"/data-quality/evidence/joins/{join['join_artifact_id']}?tenant_id={tenant_id}&domain_id={domain_id}"
            ),
            "sample_matches": matched_sample_rows,
            "sample_unmatched_left_rows": unmatched_left_sample_rows,
            "sample_unmatched_right_rows": unmatched_right_sample_rows,
            "lineage_basis": f"{left_table}.ctid + {right_table}.ctid",
        }
    )
    return {
        **join,
        "left_row_count": left_count,
        "right_row_count": right_count,
        "matched_row_count": matched_left_row_count,
        "unmatched_left_row_count": unmatched_left_row_count,
        "unmatched_right_row_count": unmatched_right_row_count,
        "duplicate_match_count": duplicate_match_count,
        "row_outcomes": _build_join_row_outcomes(
            join=join,
            unmatched_left_rows=unmatched_left_sample_rows,
            unmatched_right_rows=unmatched_right_sample_rows,
        ),
        "summary_json": summary,
    }


def compute_stage_plan_metrics_tool(
    settings: Any,
    *,
    scoped_conn: ScopedConnection | None,
    schema_name: str,
    tenant_id: str,
    domain_id: str,
    stage_plan: dict[str, Any],
) -> dict[str, Any]:
    if not scoped_conn:
        return stage_plan
    enriched_stages: list[dict[str, Any]] = []
    enriched_joins: list[dict[str, Any]] = []
    row_outcomes: list[dict[str, Any]] = []
    joins_by_name: dict[str, dict[str, Any]] = {}
    for join in (stage_plan.get("joins") or []):
        try:
            measured_join = _compute_join_metrics(
                settings,
                scoped_conn=scoped_conn,
                schema_name=schema_name,
                join=join,
                tenant_id=tenant_id,
                domain_id=domain_id,
            )
        except Exception as exc:
            measured_join = {
                **join,
                "summary_json": {
                    **join,
                    "measurement_status": "failed",
                    "measurement_error": str(exc),
                },
            }
        enriched_joins.append(measured_join)
        row_outcomes.extend(list(measured_join.get("row_outcomes") or []))
        joins_by_name[str(measured_join.get("join_name") or "")] = measured_join
    previous_output_row_count: int | None = None
    for stage in (stage_plan.get("stages") or []):
        stage_type = str(stage.get("stage_type") or "").strip()
        try:
            if stage_type == "source_profile":
                measured_stage = _compute_source_stage_metrics(
                    settings,
                    scoped_conn=scoped_conn,
                    schema_name=schema_name,
                    stage=stage,
                    tenant_id=tenant_id,
                    domain_id=domain_id,
                )
            elif stage_type == "join_validation":
                join_info = dict(stage.get("join") or {})
                measured_join = joins_by_name.get(str(join_info.get("join_name") or ""))
                measured_stage = dict(stage)
                input_row_count = measured_join.get("left_row_count") if measured_join else None
                output_row_count = measured_join.get("matched_row_count") if measured_join else None
                rejected_row_count = measured_join.get("unmatched_left_row_count") if measured_join else None
                measured_stage.update(
                    {
                        "input_row_count": input_row_count,
                        "output_row_count": output_row_count,
                        "rejected_row_count": rejected_row_count,
                        "summary_json": {
                            **stage,
                            "join": measured_join or join_info,
                            "measurement_status": "measured" if measured_join else "unavailable",
                            "evidence_path": (
                                f"/data-quality/evidence/stages/{stage['stage_id']}?tenant_id={tenant_id}&domain_id={domain_id}"
                            ),
                        },
                    }
                )
            elif stage_type == "filter":
                measured_stage = _compute_filter_stage_metrics(
                    settings,
                    scoped_conn=scoped_conn,
                    schema_name=schema_name,
                    stage=stage,
                    tenant_id=tenant_id,
                    domain_id=domain_id,
                )
                row_outcomes.extend(list(measured_stage.get("row_outcomes") or []))
            elif stage_type == "final_projection":
                measured_stage = dict(stage)
                measured_stage.update(
                    {
                        "input_row_count": previous_output_row_count,
                        "output_row_count": previous_output_row_count,
                        "rejected_row_count": 0 if previous_output_row_count is not None else None,
                        "summary_json": {
                            **stage,
                            "measurement_status": "derived",
                            "evidence_path": (
                                f"/data-quality/evidence/stages/{stage['stage_id']}?tenant_id={tenant_id}&domain_id={domain_id}"
                            ),
                        },
                    }
                )
            else:
                measured_stage = dict(stage)
                measured_stage["summary_json"] = {
                    **stage,
                    "measurement_status": "planned_only",
                    "evidence_path": (
                        f"/data-quality/evidence/stages/{stage['stage_id']}?tenant_id={tenant_id}&domain_id={domain_id}"
                    ),
                }
        except Exception as exc:
            measured_stage = {
                **stage,
                "summary_json": {
                    **stage,
                    "measurement_status": "failed",
                    "measurement_error": str(exc),
                    "evidence_path": (
                        f"/data-quality/evidence/stages/{stage['stage_id']}?tenant_id={tenant_id}&domain_id={domain_id}"
                    ),
                },
            }
        if measured_stage.get("output_row_count") is not None:
            previous_output_row_count = measured_stage.get("output_row_count")
        enriched_stages.append(measured_stage)
    final_dataset = {
        "artifact_id": f"dqfinal_{uuid.uuid4().hex[:12]}",
        "final_stage_name": str((enriched_stages[-1] or {}).get("stage_name") or "") if enriched_stages else "",
        "final_row_count": previous_output_row_count,
        "total_rejected_row_count": sum(
            int(item.get("rejected_row_count") or 0)
            for item in enriched_stages
            if item.get("rejected_row_count") is not None
        ),
        "readiness_status": "ready" if previous_output_row_count not in (None, 0) else "empty",
        "summary_json": {
            "measurement_status": "derived" if previous_output_row_count is not None else "planned_only",
            "final_row_count": previous_output_row_count,
            "lineage_enabled": True,
            "total_rejected_row_count": sum(
                int(item.get("rejected_row_count") or 0)
                for item in enriched_stages
                if item.get("rejected_row_count") is not None
            ),
        },
    }
    snapshot = build_final_dataset_snapshot_tool(
        settings,
        scoped_conn=scoped_conn,
        schema_name=schema_name,
        stages=enriched_stages,
        final_dataset=final_dataset,
    )
    final_dataset["summary_json"] = {
        **dict(final_dataset.get("summary_json") or {}),
        "basis_stage": dict(snapshot.get("basis_stage") or {}),
        "sample_rows": list(snapshot.get("sample_rows") or []),
        "sample_row_count": int(snapshot.get("sample_row_count") or 0),
        "sample_limit": int(snapshot.get("sample_limit") or 0),
        "row_source": snapshot.get("row_source"),
    }
    return {
        **stage_plan,
        "stages": enriched_stages,
        "joins": enriched_joins,
        "row_outcomes": row_outcomes,
        "lineage_edges": _build_lineage_edges(stages=enriched_stages, row_outcomes=row_outcomes),
        "rejected_row_count": sum(
            int(item.get("rejected_row_count") or 0)
            for item in enriched_stages
            if item.get("rejected_row_count") is not None
        ),
        "final_dataset": final_dataset,
    }


def infer_stage_plan_tool(
    *,
    schema_graph: dict[str, Any],
    context_text: str | None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    interpreted_context = domain_context_interpreter_tool(
        schema_graph=schema_graph,
        context_text=context_text,
        settings=settings,
    )
    shared_key_inferences = shared_key_inference_tool(
        schema_graph=schema_graph,
        interpreted_context=interpreted_context,
        settings=settings,
    )
    asymmetry_detections = asymmetry_detection_tool(
        interpreted_context=interpreted_context,
        shared_key_inferences=shared_key_inferences,
        settings=settings,
    )
    join_strategies = join_strategy_builder_tool(
        shared_key_inferences=shared_key_inferences,
        asymmetry_detections=asymmetry_detections,
        settings=settings,
    )
    existing_pairs = {
        (
            str(strategy.get("left_table") or "").lower(),
            str(match_key.get("left_key") or "").lower(),
            str(strategy.get("right_table") or "").lower(),
            str(match_key.get("right_key") or "").lower(),
        )
        for strategy in join_strategies
        for match_key in (strategy.get("match_keys") or [])
    }
    for strategy in _legacy_join_candidates_to_strategies(
        schema_graph=schema_graph,
        context_text=context_text,
    ):
        strategy_pairs = {
            (
                str(strategy.get("left_table") or "").lower(),
                str(match_key.get("left_key") or "").lower(),
                str(strategy.get("right_table") or "").lower(),
                str(match_key.get("right_key") or "").lower(),
            )
            for match_key in (strategy.get("match_keys") or [])
        }
        if strategy_pairs and strategy_pairs.issubset(existing_pairs):
            continue
        join_strategies.append(strategy)
        existing_pairs.update(strategy_pairs)
    filter_candidates = filter_intent_resolution_tool(
        schema_graph=schema_graph,
        context_text=context_text,
        settings=settings,
    )
    evidence_sampling = domain_evidence_sampler_tool(
        schema_graph=schema_graph,
        interpreted_context=interpreted_context,
    )
    compiled = stage_plan_compiler_tool(
        schema_graph=schema_graph,
        interpreted_context=interpreted_context,
        join_strategies=join_strategies,
        filter_intents=filter_candidates,
    )

    return {
        **compiled,
        "workflow_type": interpreted_context.get("workflow_type"),
        "table_roles": interpreted_context.get("table_roles") or [],
        "join_intents": interpreted_context.get("join_intents") or [],
        "shared_key_inferences": shared_key_inferences,
        "asymmetry_detections": asymmetry_detections,
        "join_strategies": join_strategies,
        "evidence_sampling": evidence_sampling,
        "quality_objectives": interpreted_context.get("quality_objectives") or [],
        "context_lines": interpreted_context.get("context_lines") or [],
    }
