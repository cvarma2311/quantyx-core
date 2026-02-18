from __future__ import annotations

import json
import urllib.request
from pathlib import Path
from typing import Any

from services.ai.config import Settings


PROMPTS_DIR = Path(__file__).parent / "prompts" / "semantic_suggest"


def _load_prompt(name: str) -> str:
    return (PROMPTS_DIR / name).read_text()


def _render_prompt(template: str, values: dict[str, str]) -> str:
    rendered = template
    for key, value in values.items():
        rendered = rendered.replace("{" + key + "}", value)
    return rendered


def _call_llm(
    settings: Settings,
    system_prompt: str,
    user_prompt: str,
    model_override: str | None = None,
) -> dict[str, Any]:
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY is not set")
    payload = {
        "model": model_override or settings.openai_model,
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


def build_schema_summary(tables: list[dict[str, Any]]) -> str:
    lines = []
    for table in tables:
        table_name = table.get("table") or table.get("name")
        columns = table.get("columns", [])
        col_names = [col.get("name") for col in columns if col.get("name")]
        if not table_name:
            continue
        if col_names:
            lines.append(f"{table_name}: [{', '.join(col_names[:40])}]")
        else:
            lines.append(f"{table_name}: []")
    return "\n".join(lines)


def classify_question_types(questions: list[str]) -> list[str]:
    if not questions:
        return []
    keywords = {
        "trend": ["trend", "trending", "over time", "month", "quarter", "year", "yoy", "mom"],
        "comparison": ["compare", "vs", "versus", "variance", "difference", "delta"],
        "top_n": ["top", "highest", "largest", "rank", "ranking"],
        "share": ["share", "contribution", "percent", "%"],
        "anomaly": ["anomaly", "spike", "drop", "outlier"],
        "breakdown": ["breakdown", "by", "segment", "category"],
        "cohort": ["cohort", "retention"],
    }
    detected = set()
    for question in questions:
        lower = question.lower()
        for qtype, words in keywords.items():
            if any(word in lower for word in words):
                detected.add(qtype)
    return sorted(detected)


def _infer_models_from_tables(
    tables: list[dict[str, Any]],
    time_column: str | None = None,
    grain: str | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    facts = []
    dims = []
    for table in tables:
        columns = table.get("columns", [])
        column_names = [col.get("name") for col in columns]
        numeric_cols = [
            col["name"]
            for col in columns
            if str(col.get("data_type", "")).lower()
            in {"integer", "bigint", "smallint", "numeric", "double precision", "real"}
        ]
        text_cols = [
            col["name"]
            for col in columns
            if str(col.get("data_type", "")).lower() in {"text", "character varying", "varchar"}
        ]
        date_cols = [
            col["name"]
            for col in columns
            if str(col.get("data_type", "")).lower()
            in {"date", "timestamp", "timestamp without time zone", "timestamp with time zone"}
        ]

        candidate_time = time_column if time_column in column_names else (date_cols[0] if date_cols else None)
        is_fact = bool(numeric_cols) and bool(candidate_time)
        if is_fact:
            facts.append(
                {
                    "table_name": table.get("table") or table.get("name"),
                    "grain": grain or "day",
                    "time_column": candidate_time,
                    "measures": numeric_cols[:10],
                    "dimensions": text_cols[:10],
                    "confidence": 0.7 if len(numeric_cols) < 3 else 0.85,
                }
            )
        else:
            dim_keys = [col for col in column_names if col and (col.endswith("_id") or col.endswith("_code"))]
            dims.append(
                {
                    "name": table.get("table") or table.get("name"),
                    "keys": dim_keys[:5],
                    "attributes": text_cols[:15],
                    "confidence": 0.6 if not dim_keys else 0.8,
                }
            )
    return facts, dims


def _heuristic_lineage(
    facts: list[dict[str, Any]],
    dimensions: list[dict[str, Any]],
    metrics: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    dim_names = {dim.get("name") for dim in dimensions if dim.get("name")}
    fact_names = {fact.get("table_name") or fact.get("name") for fact in facts if fact.get("table_name") or fact.get("name")}

    for fact in facts:
        fact_name = fact.get("table_name") or fact.get("name")
        for dim in fact.get("dimensions", []) or []:
            if dim in dim_names and fact_name:
                edges.append({"from": dim, "to": fact_name, "edge_type": "dimension_to_fact"})

    for metric in metrics:
        metric_name = metric.get("metric_name")
        sql = metric.get("sql") or ""
        referenced = None
        for name in fact_names:
            if not name:
                continue
            if name in sql:
                referenced = name
                break
        if not referenced:
            source_model = metric.get("source_model") or metric.get("dataset_id")
            if source_model in fact_names:
                referenced = source_model
        if referenced and metric_name:
            edges.append({"from": referenced, "to": metric_name, "edge_type": "fact_to_metric"})

    return edges


def build_lineage_edges(
    facts: list[dict[str, Any]],
    dimensions: list[dict[str, Any]],
    metrics: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return _heuristic_lineage(facts, dimensions, metrics)


def _normalize_suggestions(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "facts": payload.get("facts", []) if isinstance(payload.get("facts"), list) else [],
        "dimensions": payload.get("dimensions", []) if isinstance(payload.get("dimensions"), list) else [],
        "metrics": payload.get("metrics", []) if isinstance(payload.get("metrics"), list) else [],
        "lineage": payload.get("lineage", {}) if isinstance(payload.get("lineage"), dict) else {},
        "question_types": payload.get("question_types", []) if isinstance(payload.get("question_types"), list) else [],
    }


def suggest_semantic_model(
    settings: Settings,
    schema_summary: str | None,
    questions: list[str] | None = None,
    glossary: str | None = None,
    domain_id: str | None = None,
    model_override: str | None = None,
    tables: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    questions = questions or []
    question_types = classify_question_types(questions)
    if not schema_summary and tables:
        schema_summary = build_schema_summary(tables)

    system_prompt = "You create semantic models. Return JSON only."
    user_prompt = _render_prompt(
        _load_prompt("semantic_suggest.md"),
        {
            "domain_id": domain_id or "",
            "schema_summary": schema_summary or "",
            "questions": "\n".join(questions) if questions else "",
            "glossary": glossary or "",
            "question_types": ", ".join(question_types),
        },
    )

    payload: dict[str, Any] | None = None
    if schema_summary:
        try:
            payload = _call_llm(settings, system_prompt, user_prompt, model_override=model_override)
        except ValueError:
            payload = None

    if not payload:
        facts, dimensions = _infer_models_from_tables(tables or [])
        suggestions = {
            "facts": facts,
            "dimensions": dimensions,
            "metrics": [],
            "lineage": {"edges": _heuristic_lineage(facts, dimensions, [])},
            "question_types": question_types,
        }
        return suggestions

    suggestions = _normalize_suggestions(payload)
    if not suggestions["question_types"]:
        suggestions["question_types"] = question_types
    else:
        suggestions["question_types"] = sorted(set(suggestions["question_types"]) | set(question_types))

    if not suggestions["lineage"]:
        suggestions["lineage"] = {"edges": []}

    edges = suggestions["lineage"].get("edges")
    if not isinstance(edges, list) or not edges:
        edges = _heuristic_lineage(
            suggestions["facts"],
            suggestions["dimensions"],
            suggestions["metrics"],
        )
        suggestions["lineage"]["edges"] = edges

    return suggestions
