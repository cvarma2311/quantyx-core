from __future__ import annotations

import json
import urllib.request

from services.ai.catalog import MetricCatalog
from services.ai.config import Settings


def resolve_question(
    question: str,
    catalog: MetricCatalog,
    settings: Settings,
    allowed_metrics: list[str] | None = None,
    glossary: list[dict] | None = None,
) -> dict:
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY is not set")

    system_prompt = (
        "You are a data metric resolver. "
        "Return JSON with keys: metrics, dimensions, filters. "
        "metrics must be a list of metric names. "
        "Use only the provided metric and dimension names."
    )

    user_prompt = {
        "question": question,
        "metrics": allowed_metrics or catalog.metric_names(),
        "dimensions": catalog.dimension_names(),
        "glossary": glossary or [],
        "filter_format": {"field": "dimension_name", "operator": "=|!=|>|>=|<|<=|IN|ILIKE", "value": "..."},
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

    with urllib.request.urlopen(request, timeout=30) as response:
        body = json.loads(response.read().decode("utf-8"))

    content = body["choices"][0]["message"]["content"]
    return json.loads(content)
