from __future__ import annotations

import json
import logging
import urllib.request
from typing import Any

from services.ai.config import Settings

logger = logging.getLogger(__name__)

def _default_extractions(extraction_types: list[str]) -> dict[str, list[dict[str, Any]]]:
    return {key: [] for key in extraction_types}


def extract_context(
    settings: Settings,
    raw_text: str,
    extraction_types: list[str],
) -> dict[str, list[dict[str, Any]]]:
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY is not set")

    requested = extraction_types or [
        "abbreviations",
        "synonyms",
        "hierarchies",
        "metric_candidates",
        "question_intents",
    ]
    system_prompt = (
        "You extract structured business context from raw text. "
        "Return JSON with keys exactly matching the requested extraction types. "
        "Each key must be a list. Use [] when nothing is found."
    )
    user_prompt = {
        "extraction_types": requested,
        "raw_text": raw_text,
        "expected_shapes": {
            "abbreviations": [{"abbr": "SBU", "definition": "Strategic Business Unit"}],
            "synonyms": [{"term": "sales area", "synonyms": ["territory"]}],
            "hierarchies": [{"name": "sales_org", "levels": ["zone", "region", "sales_area"]}],
            "metric_candidates": [{"metric_name": "output_tmt", "table": "fact_production_daily"}],
            "question_intents": [{"question": "Which zones are underperforming?", "metrics": ["sales_tmt"]}],
        },
    }

    payload = {
        "model": settings.openai_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_prompt)},
        ],
        "temperature": 0.0,
        "response_format": {"type": "json_object"},
    }

    logger.debug(
        "llm.context_extract: request | model=%s chars=%s types=%s",
        settings.openai_model,
        len(raw_text or ""),
        requested,
    )
    request = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {settings.openai_api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    for attempt in range(2):
        with urllib.request.urlopen(request, timeout=45) as response:
            body = json.loads(response.read().decode("utf-8"))
        content = body["choices"][0]["message"]["content"]
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            logger.warning("llm.context_extract: json decode failed | attempt=%s", attempt + 1)
            continue

        result: dict[str, list[dict[str, Any]]] = _default_extractions(requested)
        for key in requested:
            value = parsed.get(key, [])
            if isinstance(value, list):
                result[key] = value
        logger.debug("llm.context_extract: response | keys=%s", list(result.keys()))
        return result

    return _default_extractions(requested)
