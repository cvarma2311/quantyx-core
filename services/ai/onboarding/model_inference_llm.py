from __future__ import annotations

import json
import logging
import urllib.request
from typing import Any

from services.ai.config import Settings

logger = logging.getLogger(__name__)

def llm_infer_models(
    settings: Settings,
    tables: list[dict[str, Any]],
    domain_id: str | None = None,
) -> dict[str, Any]:
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY is not set")

    system_prompt = (
        "You infer candidate fact and dimension models from schema scans. "
        "Return JSON with keys: facts, dimensions. "
        "facts items: name, grain, time_column, measures, dimensions, confidence (0-1). "
        "dimensions items: name, keys, attributes, confidence (0-1)."
    )
    user_prompt = {
        "domain_id": domain_id,
        "tables": tables,
        "confidence_guidance": "0.9+ for clear facts, 0.7 for likely dims, <=0.6 if unsure",
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
        "llm.infer_models: request | model=%s tables=%s",
        settings.openai_model,
        len(tables),
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
        with urllib.request.urlopen(request, timeout=30) as response:
            body = json.loads(response.read().decode("utf-8"))
        content = body["choices"][0]["message"]["content"]
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            logger.warning("llm.infer_models: json decode failed | attempt=%s", attempt + 1)
            continue
        facts = parsed.get("facts", [])
        dimensions = parsed.get("dimensions", [])
        if isinstance(facts, list) and isinstance(dimensions, list):
            logger.debug(
                "llm.infer_models: response | facts=%s dims=%s",
                len(facts),
                len(dimensions),
            )
            return {"facts": facts, "dimensions": dimensions}

    return {"facts": [], "dimensions": []}
