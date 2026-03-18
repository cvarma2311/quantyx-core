from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any
import urllib.error
import urllib.request

from services.ai.config import Settings

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).parent / "prompts" / "semantic_contract"


def _load_prompt(name: str) -> str:
    path = PROMPTS_DIR / name
    return path.read_text()


def _build_prompt(instructions: str, sections: list[tuple[str, str | None]]) -> str:
    parts = [instructions.strip()]
    for title, value in sections:
        text = str(value or "").strip()
        if not text:
            continue
        parts.append(f"{title}:\n{text}")
    return "\n\n".join(parts)


def _call_llm(settings: Settings, system_prompt: str, user_prompt: str) -> dict[str, Any]:
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY is not set")
    logger.debug(
        "llm.semantic_extract: request | model=%s prompt_chars=%s",
        settings.openai_model,
        len(user_prompt or ""),
    )
    payload = {
        "model": settings.openai_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.1,
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
        with urllib.request.urlopen(request, timeout=45) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        response_body = ""
        try:
            response_body = exc.read().decode("utf-8")
        except Exception:
            response_body = "<unreadable>"
        logger.error(
            "llm.semantic_extract: http_error | status=%s reason=%s body=%s",
            exc.code,
            exc.reason,
            response_body[:4000],
        )
        raise
    except Exception:
        logger.exception("llm.semantic_extract: request_failed")
        raise
    content = body["choices"][0]["message"]["content"]
    logger.debug("llm.semantic_extract: response | chars=%s", len(content or ""))
    return json.loads(content)


def _validate_glossary(payload: dict[str, Any]) -> list[dict]:
    errors = []
    terms = payload.get("terms")
    if terms is None or not isinstance(terms, list):
        return [{"field": "terms", "issue": "missing_or_not_list"}]
    for idx, term in enumerate(terms):
        if not isinstance(term, dict):
            errors.append({"field": f"terms[{idx}]", "issue": "not_object"})
            continue
        if not term.get("term") or not isinstance(term.get("term"), str):
            errors.append({"field": f"terms[{idx}].term", "issue": "missing"})
    return errors


def _validate_mappings(payload: dict[str, Any]) -> list[dict]:
    errors = []
    mappings = payload.get("mappings")
    if mappings is None or not isinstance(mappings, list):
        return [{"field": "mappings", "issue": "missing_or_not_list"}]
    for idx, mapping in enumerate(mappings):
        if not isinstance(mapping, dict):
            errors.append({"field": f"mappings[{idx}]", "issue": "not_object"})
            continue
        if not mapping.get("table") or not mapping.get("column") or not mapping.get("entity_type"):
            errors.append({"field": f"mappings[{idx}]", "issue": "missing_fields"})
        conf = mapping.get("confidence")
        if conf is not None and not isinstance(conf, (int, float)):
            errors.append({"field": f"mappings[{idx}].confidence", "issue": "not_number"})
    return errors


def _validate_metric_def(payload: dict[str, Any]) -> list[dict]:
    errors = []
    if not payload.get("metric_name"):
        errors.append({"field": "metric_name", "issue": "missing"})
    if "dimensions" in payload and not isinstance(payload["dimensions"], list):
        errors.append({"field": "dimensions", "issue": "not_list"})
    return errors


def extract_semantic_contract(
    settings: Settings,
    raw_text: str,
    tables_and_columns: str | None = None,
    entity_types: list[str] | None = None,
    metric_candidate_payload: str | None = None,
) -> dict[str, Any]:
    system_prompt = "You extract structured business context. Return JSON only."
    logger.info(
        "semantic_extract.start | raw_text_chars=%s tables_and_columns=%s entity_types=%s metric_candidate=%s",
        len(raw_text or ""),
        bool(tables_and_columns),
        len(entity_types or []),
        bool(metric_candidate_payload),
    )
    glossary_prompt = _build_prompt(
        _load_prompt("glossary_extract.txt"),
        [("Input", raw_text)],
    )
    logger.debug("semantic_extract.glossary_prompt | chars=%s", len(glossary_prompt or ""))
    glossary = _call_llm(settings, system_prompt, glossary_prompt)
    glossary_errors = _validate_glossary(glossary)
    if glossary_errors:
        logger.error("semantic_extract.glossary_invalid | errors=%s payload=%s", glossary_errors, glossary)
        raise ValueError(f"Glossary extraction invalid: {glossary_errors}")

    mappings = {"mappings": []}
    if tables_and_columns and entity_types:
        mapping_prompt = _build_prompt(
            _load_prompt("entity_mapping.txt"),
            [
                ("Allowed entity types", ", ".join(entity_types)),
                ("Tables and columns", tables_and_columns),
            ],
        )
        logger.debug("semantic_extract.mapping_prompt | chars=%s entity_types=%s", len(mapping_prompt or ""), len(entity_types or []))
        mappings = _call_llm(settings, system_prompt, mapping_prompt)
        mapping_errors = _validate_mappings(mappings)
        if mapping_errors:
            logger.error("semantic_extract.mapping_invalid | errors=%s payload=%s", mapping_errors, mappings)
            raise ValueError(f"Entity mapping invalid: {mapping_errors}")

    metric_defs = {"metric_name": None, "definition": "", "grain": "", "dimensions": []}
    if metric_candidate_payload:
        metric_prompt = _build_prompt(
            _load_prompt("metric_definition.txt"),
            [("Metric candidate and columns", metric_candidate_payload)],
        )
        logger.debug("semantic_extract.metric_prompt | chars=%s", len(metric_prompt or ""))
        metric_defs = _call_llm(settings, system_prompt, metric_prompt)
        metric_errors = _validate_metric_def(metric_defs)
        if metric_errors:
            logger.error("semantic_extract.metric_invalid | errors=%s payload=%s", metric_errors, metric_defs)
            raise ValueError(f"Metric definition invalid: {metric_errors}")

    logger.info(
        "semantic_extract.completed | business_terms=%s entity_mappings=%s metric_definitions=%s",
        len(glossary.get("terms", []) or []),
        len(mappings.get("mappings", []) or []),
        1 if metric_defs.get("metric_name") else 0,
    )
    return {
        "business_terms": glossary.get("terms", []),
        "entity_mappings": mappings.get("mappings", []),
        "metric_definitions": [metric_defs] if metric_defs.get("metric_name") else [],
    }
