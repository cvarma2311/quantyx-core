from __future__ import annotations

import json
from pathlib import Path
from typing import Any
import urllib.request

from services.ai.config import Settings


PROMPTS_DIR = Path(__file__).parent / "prompts" / "semantic_contract"


def _load_prompt(name: str) -> str:
    path = PROMPTS_DIR / name
    return path.read_text()


def _call_llm(settings: Settings, system_prompt: str, user_prompt: str) -> dict[str, Any]:
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY is not set")
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
    with urllib.request.urlopen(request, timeout=45) as response:
        body = json.loads(response.read().decode("utf-8"))
    content = body["choices"][0]["message"]["content"]
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
    glossary_prompt = _load_prompt("glossary_extract.txt").format(raw_text=raw_text)
    glossary = _call_llm(settings, system_prompt, glossary_prompt)
    glossary_errors = _validate_glossary(glossary)
    if glossary_errors:
        raise ValueError(f"Glossary extraction invalid: {glossary_errors}")

    mappings = {"mappings": []}
    if tables_and_columns and entity_types:
        mapping_prompt = _load_prompt("entity_mapping.txt").format(
            tables_and_columns=tables_and_columns,
            entity_types=", ".join(entity_types),
        )
        mappings = _call_llm(settings, system_prompt, mapping_prompt)
        mapping_errors = _validate_mappings(mappings)
        if mapping_errors:
            raise ValueError(f"Entity mapping invalid: {mapping_errors}")

    metric_defs = {"metric_name": None, "definition": "", "grain": "", "dimensions": []}
    if metric_candidate_payload:
        metric_prompt = _load_prompt("metric_definition.txt").format(
            metric_candidate_and_columns=metric_candidate_payload
        )
        metric_defs = _call_llm(settings, system_prompt, metric_prompt)
        metric_errors = _validate_metric_def(metric_defs)
        if metric_errors:
            raise ValueError(f"Metric definition invalid: {metric_errors}")

    return {
        "business_terms": glossary.get("terms", []),
        "entity_mappings": mappings.get("mappings", []),
        "metric_definitions": [metric_defs] if metric_defs.get("metric_name") else [],
    }
