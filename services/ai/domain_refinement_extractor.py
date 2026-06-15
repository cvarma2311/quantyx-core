from __future__ import annotations

import json
import logging
import os
import re
import ssl
import urllib.request
from typing import Any

from services.ai.config import Settings
from services.ai.db import run_query
from services.ai.domain_refinement_store import (
    create_refinement_artifact,
    list_refinement_artifacts,
    update_refinement_input_status,
)

context = ssl._create_unverified_context()

logger = logging.getLogger(__name__)

ALLOWED_REFINEMENT_KINDS = {
    "business_context",
    "hierarchy",
    "column_annotation",
    "metric_refinement",
    "join_rule",
    "chart_guidance",
    "interpretation_rule",
    "context_question_answer",
}

_WORD_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)?")
_IDENTIFIER_HINT_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)?$")

ALLOWED_SOURCE_TYPES = {"text", "structured", "conversation", "file"}

_KIND_TO_ARTIFACT = {
    "business_context": "business_context",
    "hierarchy": "hierarchy_override",
    "column_annotation": "column_annotation",
    "metric_refinement": "metric_refinement",
    "join_rule": "join_rule",
    "chart_guidance": "chart_guidance",
    "interpretation_rule": "interpretation_rule",
    "context_question_answer": "context_question_answer",
}


def validate_refinement_input_payload(
    *,
    source_type: str,
    refinement_kind: str,
    source_text: str | None,
    source_payload_json: dict[str, Any] | None,
) -> list[str]:
    errors: list[str] = []
    if source_type not in ALLOWED_SOURCE_TYPES:
        errors.append(f"source_type must be one of {sorted(ALLOWED_SOURCE_TYPES)}")
    if refinement_kind not in ALLOWED_REFINEMENT_KINDS:
        errors.append(f"refinement_kind must be one of {sorted(ALLOWED_REFINEMENT_KINDS)}")
    if not (source_text and source_text.strip()) and not source_payload_json:
        errors.append("at least one of text or payload is required")
    return errors


def _hierarchy_from_text(text: str) -> dict[str, Any] | None:
    match = re.search(r"([A-Za-z0-9_ /.-]+(?:\s*>\s*[A-Za-z0-9_ /.-]+){1,})", text)
    if not match:
        return None
    raw_levels = [part.strip(" .,-") for part in match.group(1).split(">")]
    if raw_levels:
        raw_levels[0] = re.sub(
            r"(?i)^(use|prefer|set|define|apply)?\s*(the\s+)?(hierarchy|drill\s+path|path)\s+",
            "",
            raw_levels[0],
        ).strip()
    levels = [re.sub(r"\s+", "_", level.strip()).lower() for level in raw_levels if level.strip()]
    if len(levels) < 2:
        return None
    return {
        "name": "refined_hierarchy",
        "levels": levels,
        "preferred": True,
        "source_text": text,
    }


def _normalize_identifier(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.]+", "_", value.strip()).strip("_").lower()
    return re.sub(r"_+", "_", cleaned)


def _normalize_lookup(value: Any) -> str:
    return _normalize_identifier(str(value or "")).split(".")[-1]


def _split_sentences(text: str) -> list[str]:
    rough_parts = re.split(r"[\n;]+|(?<=[.!?])\s+", text)
    return [part.strip().strip(".!?") for part in rough_parts if part.strip().strip(".!?")]


def _table_column_from_identifier(identifier: str) -> tuple[str | None, str]:
    if "." in identifier:
        table, column = identifier.split(".", 1)
        return _normalize_identifier(table), _normalize_identifier(column)
    return None, _normalize_identifier(identifier)


def _empty_schema_context() -> dict[str, Any]:
    return {
        "available": False,
        "tables": set(),
        "columns": set(),
        "columns_by_table": {},
        "metrics": set(),
        "joins": set(),
    }


def _add_table_columns(context: dict[str, Any], table_name: Any, columns: Any) -> None:
    table = _normalize_lookup(table_name)
    if not table:
        return
    context["tables"].add(table)
    context["columns_by_table"].setdefault(table, set())
    for col in columns or []:
        if isinstance(col, dict):
            col_name = col.get("name") or col.get("column") or col.get("column_name")
        else:
            col_name = col
        normalized = _normalize_lookup(col_name)
        if not normalized:
            continue
        context["columns"].add(normalized)
        context["columns_by_table"][table].add(normalized)


def _load_refinement_schema_context(settings: Settings, refinement_input: dict[str, Any]) -> dict[str, Any]:
    context = _empty_schema_context()
    tenant_id = str(refinement_input.get("tenant_id") or "").strip()
    domain_id = str(refinement_input.get("domain_id") or "").strip()
    connection_id = refinement_input.get("connection_id")
    database_name = refinement_input.get("database_name")
    schema_name = refinement_input.get("schema_name")
    source_run_id = refinement_input.get("source_run_id")
    if not (tenant_id and domain_id):
        return context

    scope_filter = """
           AND connection_id IS NOT DISTINCT FROM %s
           AND database_name IS NOT DISTINCT FROM %s
           AND schema_name IS NOT DISTINCT FROM %s
    """
    scope_params = [connection_id, database_name, schema_name]
    run_filter = " AND run_id = %s" if source_run_id else ""
    run_params = [source_run_id] if source_run_id else []
    try:
        graph_rows = run_query(
            settings,
            f"""
            SELECT graph_json
              FROM public.quantyx_schema_graph_artifacts
             WHERE tenant_id = %s
               AND domain_id = %s
               {scope_filter}
               {run_filter}
               AND COALESCE(is_current, true) = true
             ORDER BY updated_at DESC
             LIMIT 1
            """,
            [tenant_id, domain_id, *scope_params, *run_params],
        )
        graph_json = (graph_rows[0] or {}).get("graph_json") if graph_rows else None
        for table in (graph_json or {}).get("tables") or []:
            if isinstance(table, dict):
                _add_table_columns(context, table.get("name") or table.get("table"), table.get("columns") or [])
    except Exception:
        logger.warning("domain_refinement.schema_graph_context_unavailable", exc_info=True)

    try:
        profile_rows = run_query(
            settings,
            f"""
            SELECT profiling_json
              FROM public.quantyx_table_profile_artifacts
             WHERE tenant_id = %s
               AND domain_id = %s
               {scope_filter}
               {run_filter}
               AND COALESCE(is_current, true) = true
             ORDER BY updated_at DESC
             LIMIT 1
            """,
            [tenant_id, domain_id, *scope_params, *run_params],
        )
        profiling_json = (profile_rows[0] or {}).get("profiling_json") if profile_rows else None
        for table in (profiling_json or {}).get("tables") or []:
            if not isinstance(table, dict):
                continue
            column_names: list[Any] = []
            for key in ("column_profiles", "column_semantics"):
                column_names.extend(table.get(key) or [])
            for key in ("numeric_columns", "eligible_numeric_columns", "time_columns", "categorical_columns"):
                column_names.extend(table.get(key) or [])
            _add_table_columns(context, table.get("name") or table.get("table"), column_names)
    except Exception:
        logger.warning("domain_refinement.profile_context_unavailable", exc_info=True)

    try:
        metric_rows = run_query(
            settings,
            """
            SELECT metric_name, metric_id
              FROM public.quantyx_metrics_registry
             WHERE tenant_id = %s
               AND domain_id = %s
               AND connection_id IS NOT DISTINCT FROM %s
               AND database_name IS NOT DISTINCT FROM %s
               AND schema_name IS NOT DISTINCT FROM %s
               AND COALESCE(is_current, true) = true
            """,
            [tenant_id, domain_id, connection_id, database_name, schema_name],
        )
        for row in metric_rows:
            for key in ("metric_name", "metric_id"):
                normalized = _normalize_lookup(row.get(key))
                if normalized:
                    context["metrics"].add(normalized)
    except Exception:
        logger.warning("domain_refinement.metric_context_unavailable", exc_info=True)

    try:
        join_rows = run_query(
            settings,
            f"""
            SELECT left_table, right_table
              FROM public.quantyx_join_registry
             WHERE tenant_id = %s
               AND domain_id = %s
               {scope_filter}
               {run_filter}
               AND COALESCE(is_current, true) = true
            """,
            [tenant_id, domain_id, *scope_params, *run_params],
        )
        for row in join_rows:
            left = _normalize_lookup(row.get("left_table"))
            right = _normalize_lookup(row.get("right_table"))
            if left and right:
                context["joins"].add((left, right))
                context["joins"].add((right, left))
    except Exception:
        logger.warning("domain_refinement.join_context_unavailable", exc_info=True)

    context["available"] = bool(context["tables"] or context["columns"] or context["metrics"])
    return context


def _column_annotation_from_text(text: str) -> dict[str, Any] | None:
    for sentence in _split_sentences(text):
        match = re.search(
            r"(?:column\s+|field\s+)?`?([A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)?)`?\s+"
            r"(?:means|is|represents|should be treated as|should be shown as)\s+(.+)",
            sentence,
            flags=re.IGNORECASE,
        )
        if not match:
            match = re.search(
                r"`?([A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)?)`?\s+"
                r"(?:values\s+)?map\s+to\s+(.+)",
                sentence,
                flags=re.IGNORECASE,
            )
        if not match:
            continue
        identifier = match.group(1)
        description = match.group(2).strip()
        table, column = _table_column_from_identifier(identifier)
        display_priority = "normal"
        lowered = sentence.lower()
        if "internal" in lowered or "not be shown" in lowered or "should not appear" in lowered:
            display_priority = "low"
        elif "business" in lowered or "customer-facing" in lowered or "preferred" in lowered:
            display_priority = "high"
        artifact = {
            "column": column,
            "description": description,
            "display_priority": display_priority,
            "source_text": sentence,
        }
        if table:
            artifact["table"] = table
        if len(description) <= 80:
            artifact["business_label"] = description.strip(" .")
        return artifact
    return None


def _metric_refinement_from_text(text: str) -> dict[str, Any] | None:
    for sentence in _split_sentences(text):
        lowered = sentence.lower()
        match = re.search(
            r"(?:metric\s+)?`?([A-Za-z][A-Za-z0-9_ ]{2,80}?)`?\s+"
            r"(?:should|must|needs to|formula\s+is|means|is)\s+(.+)",
            sentence,
            flags=re.IGNORECASE,
        )
        metric_name = None
        detail = sentence
        if match:
            metric_name = _normalize_identifier(match.group(1))
            detail = match.group(2).strip()
        elif "growth rate" in lowered:
            metric_name = "growth_rate"
        elif "total volume" in lowered:
            metric_name = "total_volume"
        elif "kpi" in lowered:
            words = [w for w in _WORD_PATTERN.findall(sentence) if w.lower() not in {"kpi", "metric", "should", "use"}]
            if words:
                metric_name = _normalize_identifier("_".join(words[:3]))
        if not metric_name:
            continue

        artifact: dict[str, Any] = {
            "metric_name": metric_name,
            "description": detail,
            "source_text": sentence,
        }
        if "month over month" in lowered or "prior month" in lowered or "previous month" in lowered:
            artifact["formula"] = "month_over_month_growth"
            artifact["grain"] = "month"
        elif "prior day" in lowered or "previous day" in lowered or "day over day" in lowered:
            artifact["formula"] = "day_over_day_growth"
            artifact["grain"] = "day"
        elif "prior year" in lowered or "year over year" in lowered or "previous year" in lowered:
            artifact["formula"] = "year_over_year_growth"
            artifact["grain"] = "year"
        if "operational" in lowered and "executive" not in lowered:
            artifact["metric_role"] = "operational"
        elif "executive" in lowered:
            artifact["metric_role"] = "executive_kpi"
        if "exclude" in lowered or "filter" in lowered:
            artifact["requires_filter_rule"] = True
        return artifact
    return None


def _join_rule_from_text(text: str) -> dict[str, Any] | None:
    for sentence in _split_sentences(text):
        lowered = sentence.lower()
        do_not_join = re.search(
            r"do\s+not\s+join\s+`?([A-Za-z][A-Za-z0-9_]*)`?\s+(?:to|with)\s+`?([A-Za-z][A-Za-z0-9_]*)`?",
            sentence,
            flags=re.IGNORECASE,
        )
        if do_not_join:
            return {
                "rule_type": "join_restriction",
                "left_table": _normalize_identifier(do_not_join.group(1)),
                "right_table": _normalize_identifier(do_not_join.group(2)),
                "allowed": False,
                "source_text": sentence,
            }
        reference_only = re.search(
            r"use\s+`?([A-Za-z][A-Za-z0-9_]*)`?\s+(?:only\s+)?for\s+labels",
            sentence,
            flags=re.IGNORECASE,
        )
        if reference_only:
            return {
                "rule_type": "reference_table_usage",
                "table": _normalize_identifier(reference_only.group(1)),
                "usage": "labels_only",
                "source_text": sentence,
            }
        if "join" in lowered and ("not" in lowered or "only" in lowered):
            return {"rule_type": "join_guidance", "text": sentence, "source_text": sentence}
    return None


def _chart_guidance_from_text(text: str) -> dict[str, Any] | None:
    for sentence in _split_sentences(text):
        lowered = sentence.lower()
        if not any(token in lowered for token in ("chart", "dashboard", "trend", "grain", "drill", "forecast")):
            continue
        artifact: dict[str, Any] = {"guidance": sentence, "source_text": sentence}
        if "daily" in lowered:
            artifact["preferred_time_grain"] = "day"
        elif "weekly" in lowered:
            artifact["preferred_time_grain"] = "week"
        elif "monthly" in lowered:
            artifact["preferred_time_grain"] = "month"
        elif "quarter" in lowered:
            artifact["preferred_time_grain"] = "quarter"
        if "forecast" in lowered:
            artifact["chart_intent"] = "forecast"
        elif "trend" in lowered:
            artifact["chart_intent"] = "trend"
        elif "ranking" in lowered or "rank" in lowered:
            artifact["chart_intent"] = "ranking"
        hierarchy = _hierarchy_from_text(sentence)
        if hierarchy:
            artifact["preferred_drill_path"] = hierarchy["levels"]
        return artifact
    return None


def _interpretation_rule_from_text(text: str) -> dict[str, Any] | None:
    for sentence in _split_sentences(text):
        lowered = sentence.lower()
        if not any(token in lowered for token in ("significant", "anomaly", "expected", "ignore", "alert", "treat")):
            continue
        artifact: dict[str, Any] = {"rule": sentence, "source_text": sentence}
        if "anomaly" in lowered or "alert" in lowered:
            artifact["applies_to"] = "anomaly"
        elif "correlation" in lowered:
            artifact["applies_to"] = "correlation"
        if "not" in lowered or "ignore" in lowered:
            artifact["polarity"] = "suppress"
        elif "expected" in lowered:
            artifact["polarity"] = "expected_variation"
        return artifact
    return None


def _filter_rule_from_text(text: str) -> dict[str, Any] | None:
    for sentence in _split_sentences(text):
        lowered = sentence.lower()
        if not any(token in lowered for token in ("exclude", "ignore", "filter out", "do not include")):
            continue
        artifact: dict[str, Any] = {"rule_type": "exclusion_filter", "description": sentence, "source_text": sentence}
        zero_match = re.search(r"(?:zero|0)[-\s]?value\s+records|records\s+with\s+zero|records\s+where\s+([A-Za-z][A-Za-z0-9_]*)\s*(?:=|is)\s*0", lowered)
        if zero_match:
            field = zero_match.group(1) if zero_match.lastindex else None
            artifact["condition"] = f"{field or '<measure>'} > 0"
        invalid_state = re.search(r"(?:state|status)\s+`?([A-Za-z0-9_ -]+)`?", sentence, flags=re.IGNORECASE)
        if invalid_state:
            artifact["invalid_state"] = invalid_state.group(1).strip()
        return artifact
    return None


def _context_question_artifacts(payload: dict[str, Any]) -> list[dict[str, Any]]:
    question_id = payload.get("question_id")
    answer_text = str(payload.get("answer_text") or payload.get("answer") or "").strip()
    maps_to = payload.get("maps_to") or []
    if isinstance(maps_to, str):
        maps_to = [maps_to]
    base = {
        "artifact_type": "context_question_answer",
        "artifact_json": {
            "question_id": question_id,
            "group_id": payload.get("group_id"),
            "answer_text": answer_text,
            "maps_to": maps_to,
        },
    }
    artifacts = [base]
    derived_input = {"refinement_kind": "business_context", "source_text": answer_text, "source_payload_json": {}}
    for artifact in _deterministic_artifacts_from_text(derived_input):
        artifact_type = artifact.get("artifact_type")
        if maps_to and artifact_type not in set(maps_to):
            if not (artifact_type == "hierarchy_override" and "hierarchy_override" in maps_to):
                continue
        artifacts.append(artifact)
    return artifacts


def _deterministic_artifacts_from_text(refinement_input: dict[str, Any]) -> list[dict[str, Any]]:
    refinement_kind = str(refinement_input.get("refinement_kind") or "").strip()
    source_text = str(refinement_input.get("source_text") or "").strip()
    artifacts: list[dict[str, Any]] = []
    if not source_text:
        return artifacts

    if refinement_kind == "hierarchy":
        hierarchy = _hierarchy_from_text(source_text)
        if hierarchy:
            artifacts.append({"artifact_type": "hierarchy_override", "artifact_json": hierarchy})
        return artifacts

    if refinement_kind == "business_context":
        artifacts.append(
            {
                "artifact_type": "business_context",
                "artifact_json": {"text": source_text, "source": "refinement_input"},
            }
        )
        for artifact_type, parser in (
            ("hierarchy_override", _hierarchy_from_text),
            ("column_annotation", _column_annotation_from_text),
            ("metric_refinement", _metric_refinement_from_text),
            ("join_rule", _join_rule_from_text),
            ("chart_guidance", _chart_guidance_from_text),
            ("interpretation_rule", _interpretation_rule_from_text),
            ("join_rule", _filter_rule_from_text),
        ):
            parsed = parser(source_text)
            if parsed:
                artifacts.append({"artifact_type": artifact_type, "artifact_json": parsed})
        return artifacts

    parser_by_kind = {
        "column_annotation": _column_annotation_from_text,
        "metric_refinement": _metric_refinement_from_text,
        "join_rule": _join_rule_from_text,
        "chart_guidance": _chart_guidance_from_text,
        "interpretation_rule": _interpretation_rule_from_text,
    }
    parser = parser_by_kind.get(refinement_kind)
    if parser:
        parsed = parser(source_text)
        if parsed:
            artifacts.append({"artifact_type": _KIND_TO_ARTIFACT.get(refinement_kind, refinement_kind), "artifact_json": parsed})
    if not artifacts:
        artifacts.append(
            {
                "artifact_type": _KIND_TO_ARTIFACT.get(refinement_kind, refinement_kind),
                "artifact_json": {"text": source_text, "source": "refinement_input"},
            }
        )
    return artifacts


def _llm_refinement_enabled(settings: Settings) -> bool:
    mode = os.getenv("DOMAIN_REFINEMENT_LLM_MODE", "off").lower()
    if mode in {"off", "false", "0"}:
        return False
    return bool(getattr(settings, "openai_api_key", None))


def _llm_extract_refinement_artifacts(settings: Settings, refinement_input: dict[str, Any]) -> list[dict[str, Any]]:
    if not _llm_refinement_enabled(settings):
        return []
    source_text = str(refinement_input.get("source_text") or "").strip()
    payload = refinement_input.get("source_payload_json") or {}
    if not source_text and not payload:
        return []
    model = os.getenv("DOMAIN_REFINEMENT_LLM_MODEL", getattr(settings, "openai_model", "gpt-4o-mini"))
    timeout_sec = int(os.getenv("DOMAIN_REFINEMENT_LLM_TIMEOUT_SEC", "30"))
    prompt = {
        "refinement_kind": refinement_input.get("refinement_kind"),
        "source_text": source_text[:8000],
        "source_payload_json": payload,
        "allowed_artifact_types": [
            "business_context",
            "hierarchy_override",
            "column_annotation",
            "metric_refinement",
            "join_rule",
            "chart_guidance",
            "interpretation_rule",
            "context_question_answer",
        ],
        "required_response_shape": {
            "artifacts": [
                {
                    "artifact_type": "hierarchy_override",
                    "artifact_json": {"name": "Primary Geography", "levels": ["zone", "region"]},
                }
            ]
        },
    }
    body = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Extract structured semantic refinement artifacts from user-provided domain knowledge. "
                    "Return JSON only. Do not invent table or column names not present in the input."
                ),
            },
            {"role": "user", "content": json.dumps(prompt)},
        ],
        "temperature": 0.0,
        "response_format": {"type": "json_object"},
    }
    request = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {settings.openai_api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_sec, context=context) as response:
            parsed = json.loads(response.read().decode("utf-8"))
        content = ((parsed.get("choices") or [{}])[0].get("message") or {}).get("content") or "{}"
        result = json.loads(content)
        artifacts = result.get("artifacts") or []
        if not isinstance(artifacts, list):
            return []
        valid: list[dict[str, Any]] = []
        for artifact in artifacts:
            if not isinstance(artifact, dict):
                continue
            artifact_type = str(artifact.get("artifact_type") or "")
            artifact_json = artifact.get("artifact_json") or {}
            if artifact_type in _KIND_TO_ARTIFACT.values() and isinstance(artifact_json, dict):
                artifact_json.setdefault("source", "llm_refinement_extractor")
                valid.append({"artifact_type": artifact_type, "artifact_json": artifact_json})
        return valid
    except Exception:
        logger.warning("domain_refinement.llm_extract_failed", exc_info=True)
        return []


def _artifact_from_structured_payload(refinement_kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    artifact_type = _KIND_TO_ARTIFACT.get(refinement_kind, refinement_kind)
    if refinement_kind == "hierarchy":
        return {
            "artifact_type": artifact_type,
            "artifact_json": {
                "name": payload.get("name") or payload.get("hierarchy_name") or "refined_hierarchy",
                "levels": payload.get("levels") or [],
                "preferred": bool(payload.get("preferred", True)),
                **{k: v for k, v in payload.items() if k not in {"name", "hierarchy_name", "levels", "preferred"}},
            },
        }
    if refinement_kind == "context_question_answer":
        return _context_question_artifacts(payload)[0]
    return {"artifact_type": artifact_type, "artifact_json": dict(payload)}


def extract_refinement_artifacts(refinement_input: dict[str, Any]) -> list[dict[str, Any]]:
    refinement_kind = str(refinement_input.get("refinement_kind") or "").strip()
    source_text = str(refinement_input.get("source_text") or "").strip()
    payload = refinement_input.get("source_payload_json") or {}
    if not isinstance(payload, dict):
        payload = {}

    artifacts: list[dict[str, Any]] = []
    if payload:
        if refinement_kind == "context_question_answer":
            artifacts.extend(_context_question_artifacts(payload))
        else:
            artifacts.append(_artifact_from_structured_payload(refinement_kind, payload))

    if source_text:
        artifacts.extend(_deterministic_artifacts_from_text(refinement_input))

    # Deduplicate identical type/json pairs produced by both structured and text paths.
    seen: set[tuple[str, str]] = set()
    deduped: list[dict[str, Any]] = []
    for artifact in artifacts:
        key = (str(artifact.get("artifact_type")), repr(sorted((artifact.get("artifact_json") or {}).items())))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(artifact)
    return deduped


def extract_refinement_artifacts_with_llm(settings: Settings, refinement_input: dict[str, Any]) -> list[dict[str, Any]]:
    artifacts = extract_refinement_artifacts(refinement_input)
    artifacts.extend(_llm_extract_refinement_artifacts(settings, refinement_input))
    seen: set[tuple[str, str]] = set()
    deduped: list[dict[str, Any]] = []
    for artifact in artifacts:
        key = (str(artifact.get("artifact_type")), json.dumps(artifact.get("artifact_json") or {}, sort_keys=True, default=str))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(artifact)
    return deduped


def _schema_context_available(schema_context: dict[str, Any] | None) -> bool:
    return bool(schema_context and schema_context.get("available"))


def _schema_context_set(schema_context: dict[str, Any] | None, key: str) -> set[str]:
    if not schema_context:
        return set()
    values = schema_context.get(key) or set()
    return {_normalize_lookup(value) for value in values if _normalize_lookup(value)}


def _schema_columns_by_table(schema_context: dict[str, Any] | None) -> dict[str, set[str]]:
    if not schema_context:
        return {}
    result: dict[str, set[str]] = {}
    for table, columns in (schema_context.get("columns_by_table") or {}).items():
        normalized_table = _normalize_lookup(table)
        normalized_columns = {_normalize_lookup(column) for column in columns or [] if _normalize_lookup(column)}
        if normalized_table:
            result[normalized_table] = normalized_columns
    return result


def _validate_table_reference(
    schema_context: dict[str, Any] | None,
    table: Any,
    field: str,
    errors: list[dict[str, Any]],
) -> str | None:
    normalized_table = _normalize_lookup(table)
    if not normalized_table or not _schema_context_available(schema_context):
        return normalized_table or None
    tables = _schema_context_set(schema_context, "tables")
    if tables and normalized_table not in tables:
        errors.append({"field": field, "message": f"unknown table '{table}' for this semantic scope"})
    return normalized_table


def _validate_column_reference(
    schema_context: dict[str, Any] | None,
    column: Any,
    field: str,
    errors: list[dict[str, Any]],
    *,
    table: Any | None = None,
) -> str | None:
    normalized_column = _normalize_lookup(column)
    if not normalized_column or not _schema_context_available(schema_context):
        return normalized_column or None

    columns = _schema_context_set(schema_context, "columns")
    columns_by_table = _schema_columns_by_table(schema_context)
    normalized_table = _normalize_lookup(table) if table else None
    if normalized_table and normalized_table in columns_by_table and columns_by_table[normalized_table]:
        if normalized_column not in columns_by_table[normalized_table]:
            errors.append(
                {
                    "field": field,
                    "message": f"unknown column '{column}' on table '{table}' for this semantic scope",
                }
            )
        return normalized_column
    if columns and normalized_column not in columns:
        errors.append({"field": field, "message": f"unknown column '{column}' for this semantic scope"})
    return normalized_column


def _validate_metric_reference(
    schema_context: dict[str, Any] | None,
    metric: Any,
    field: str,
    errors: list[dict[str, Any]],
) -> str | None:
    normalized_metric = _normalize_lookup(metric)
    if not normalized_metric or not _schema_context_available(schema_context):
        return normalized_metric or None
    metrics = _schema_context_set(schema_context, "metrics")
    if metrics and normalized_metric not in metrics:
        errors.append({"field": field, "message": f"unknown metric '{metric}' for this semantic scope"})
    return normalized_metric


def _validate_column_list(
    schema_context: dict[str, Any] | None,
    values: Any,
    field: str,
    errors: list[dict[str, Any]],
) -> None:
    if not isinstance(values, list):
        return
    for value in values:
        _validate_column_reference(schema_context, value, field, errors)


def _validate_filter_condition(
    schema_context: dict[str, Any] | None,
    condition: Any,
    errors: list[dict[str, Any]],
) -> None:
    condition_text = str(condition or "").strip()
    if not condition_text or "<measure>" in condition_text:
        return
    match = re.match(r"\s*([A-Za-z][A-Za-z0-9_.]*)\s*(?:=|!=|<>|>=|<=|>|<|IN\b|NOT\s+IN\b|LIKE\b)", condition_text, flags=re.IGNORECASE)
    if match:
        table, column = _table_column_from_identifier(match.group(1))
        if table:
            _validate_table_reference(schema_context, table, "condition", errors)
        _validate_column_reference(schema_context, column, "condition", errors, table=table)


def validate_refinement_artifact(
    artifact_type: str,
    artifact_json: dict[str, Any],
    schema_context: dict[str, Any] | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    errors: list[dict[str, Any]] = []
    if not artifact_type:
        errors.append({"field": "artifact_type", "message": "artifact_type is required"})
    if not isinstance(artifact_json, dict) or not artifact_json:
        errors.append({"field": "artifact_json", "message": "artifact_json must be a non-empty object"})

    if artifact_type == "hierarchy_override":
        levels = artifact_json.get("levels")
        if not isinstance(levels, list) or len([level for level in levels if str(level).strip()]) < 2:
            errors.append({"field": "levels", "message": "hierarchy_override requires at least two levels"})
        else:
            _validate_column_list(schema_context, levels, "levels", errors)
    elif artifact_type == "column_annotation":
        if not artifact_json.get("column"):
            errors.append({"field": "column", "message": "column_annotation requires column"})
        else:
            table = artifact_json.get("table")
            if table:
                _validate_table_reference(schema_context, table, "table", errors)
            _validate_column_reference(schema_context, artifact_json.get("column"), "column", errors, table=table)
    elif artifact_type == "metric_refinement":
        if not (artifact_json.get("metric_name") or artifact_json.get("metric_id")):
            errors.append({"field": "metric_name", "message": "metric_refinement requires metric_name or metric_id"})
        else:
            if artifact_json.get("metric_name"):
                _validate_metric_reference(schema_context, artifact_json.get("metric_name"), "metric_name", errors)
            if artifact_json.get("metric_id"):
                _validate_metric_reference(schema_context, artifact_json.get("metric_id"), "metric_id", errors)
    elif artifact_type == "join_rule":
        if not (artifact_json.get("rule_type") or artifact_json.get("text") or artifact_json.get("description")):
            errors.append({"field": "rule_type", "message": "join_rule requires rule_type, text, or description"})
        for field in ("table", "left_table", "right_table"):
            if artifact_json.get(field):
                _validate_table_reference(schema_context, artifact_json.get(field), field, errors)
        _validate_filter_condition(schema_context, artifact_json.get("condition"), errors)
    elif artifact_type == "chart_guidance":
        if not (artifact_json.get("guidance") or artifact_json.get("preferred_time_grain") or artifact_json.get("chart_intent")):
            errors.append({"field": "guidance", "message": "chart_guidance requires guidance or a chart preference"})
        _validate_column_list(schema_context, artifact_json.get("preferred_drill_path"), "preferred_drill_path", errors)
    elif artifact_type == "interpretation_rule":
        if not (artifact_json.get("rule") or artifact_json.get("text")):
            errors.append({"field": "rule", "message": "interpretation_rule requires rule or text"})
    elif artifact_type == "context_question_answer":
        if not artifact_json.get("question_id"):
            errors.append({"field": "question_id", "message": "context_question_answer requires question_id"})

    return ("invalid" if errors else "valid", errors)


def process_refinement_input(
    settings: Settings,
    refinement_input: dict[str, Any],
    *,
    auto_approve: bool = True,
    approved_by: str | None = "system:auto_approve",
) -> list[dict[str, Any]]:
    existing = list_refinement_artifacts(
        settings,
        tenant_id=str(refinement_input.get("tenant_id") or ""),
        domain_id=str(refinement_input.get("domain_id") or ""),
        refinement_input_id=str(refinement_input.get("refinement_input_id") or ""),
        limit=100,
    )
    if existing:
        return existing

    artifacts = extract_refinement_artifacts_with_llm(settings, refinement_input)
    persisted: list[dict[str, Any]] = []
    if not artifacts:
        update_refinement_input_status(settings, str(refinement_input["refinement_input_id"]), "no_artifacts")
        return []

    schema_context = _load_refinement_schema_context(settings, refinement_input)
    for artifact in artifacts:
        artifact_type = str(artifact.get("artifact_type") or "")
        artifact_json = artifact.get("artifact_json") or {}
        validation_status, validation_errors = validate_refinement_artifact(artifact_type, artifact_json, schema_context)
        approval_status = "auto_approved" if auto_approve and validation_status == "valid" else "pending"
        artifact_id = create_refinement_artifact(
            settings,
            refinement_input_id=str(refinement_input["refinement_input_id"]),
            tenant_id=str(refinement_input["tenant_id"]),
            domain_id=str(refinement_input["domain_id"]),
            connection_id=refinement_input.get("connection_id"),
            database_name=refinement_input.get("database_name"),
            schema_name=refinement_input.get("schema_name"),
            artifact_type=artifact_type,
            artifact_json=artifact_json,
            validation_status=validation_status,
            validation_errors_json=validation_errors,
            approval_status=approval_status,
            approved_by=approved_by if approval_status == "auto_approved" else None,
        )
        persisted.append(
            {
                "artifact_id": artifact_id,
                "refinement_input_id": refinement_input["refinement_input_id"],
                "tenant_id": refinement_input["tenant_id"],
                "domain_id": refinement_input["domain_id"],
                "connection_id": refinement_input.get("connection_id"),
                "database_name": refinement_input.get("database_name"),
                "schema_name": refinement_input.get("schema_name"),
                "artifact_type": artifact_type,
                "artifact_json": artifact_json,
                "validation_status": validation_status,
                "validation_errors_json": validation_errors,
                "approval_status": approval_status,
                "approved_by": approved_by if approval_status == "auto_approved" else None,
            }
        )

    update_refinement_input_status(settings, str(refinement_input["refinement_input_id"]), "processed")
    return persisted
