from __future__ import annotations

import json
import urllib.request
from typing import Any

from services.ai.config import Settings


def _sanitize_candidates(raw: list[dict[str, Any]], allowed_entities: set[str]) -> list[dict[str, Any]]:
    cleaned = []
    for candidate in raw:
        mapped = candidate.get("mapped_entity_type")
        if mapped not in allowed_entities:
            continue
        confidence = candidate.get("confidence")
        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = min(max(confidence, 0.0), 1.0)
        cleaned.append(
            {
                "table": candidate.get("table"),
                "column": candidate.get("column"),
                "mapped_entity_type": mapped,
                "confidence": confidence,
            }
        )
    return cleaned


def llm_map_entities(
    settings: Settings,
    tables: list[dict[str, Any]],
    ontology: dict[str, Any],
) -> list[dict[str, Any]]:
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY is not set")

    entity_types = ontology.get("entity_types", {})
    allowed_entities = set(entity_types.keys())
    entities = {
        key: {
            "description": body.get("description"),
            "examples": body.get("examples", []),
            "join_key": body.get("join_key"),
        }
        for key, body in entity_types.items()
    }
    columns = []
    for table in tables:
        for col in table.get("columns", []):
            columns.append(
                {
                    "table": table.get("table"),
                    "column": col.get("name"),
                    "data_type": col.get("data_type"),
                }
            )

    system_prompt = (
        "You map database columns to ontology entity types. "
        "Return JSON with key 'candidates' as a list. "
        "Each item: table, column, mapped_entity_type, confidence (0-1). "
        "Only use the provided entity types."
    )
    user_prompt = {
        "entities": entities,
        "columns": columns,
        "confidence_guidance": "0.9+ for exact match, 0.7 for partial, <=0.6 if unsure",
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

    request = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {settings.openai_api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    for _ in range(2):
        with urllib.request.urlopen(request, timeout=30) as response:
            body = json.loads(response.read().decode("utf-8"))
        content = body["choices"][0]["message"]["content"]
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            continue
        candidates = parsed.get("candidates", [])
        if isinstance(candidates, list):
            return _sanitize_candidates(candidates, allowed_entities)

    return []
