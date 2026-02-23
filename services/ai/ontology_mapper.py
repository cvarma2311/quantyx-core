from __future__ import annotations

import json
import logging
import os
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from services.ai.config import Settings
from services.ai.onboarding.entity_mapping_agents import persist_entity_mapping_agent

logger = logging.getLogger(__name__)

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
    glossary: list[dict[str, Any]] | None = None,
    agent_context: dict[str, Any] | None = None,
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
    table_map: dict[str, list[dict[str, Any]]] = {}
    for table in tables:
        table_name = table.get("table")
        table_cols: list[dict[str, Any]] = []
        for col in table.get("columns", []):
            item = {
                "table": table_name,
                "column": col.get("name"),
                "data_type": col.get("data_type"),
            }
            columns.append(item)
            table_cols.append(item)
        if table_name:
            table_map[table_name] = table_cols

    system_prompt = (
        "You map database columns to ontology entity types. "
        "Return JSON with key 'candidates' as a list. "
        "Each item: table, column, mapped_entity_type, confidence (0-1). "
        "Only use the provided entity types."
    )
    timeout_sec = int(os.getenv("OPENAI_TIMEOUT_SEC", "60"))
    retries = max(1, int(os.getenv("OPENAI_RETRIES", "2")))
    max_columns = int(os.getenv("OPENAI_MAP_COLUMNS_PER_CHUNK", "120"))
    parallel = os.getenv("OPENAI_MAP_PARALLEL", "false").lower() in {"1", "true", "yes"}
    max_workers = max(1, int(os.getenv("OPENAI_MAP_MAX_WORKERS", "4")))
    logger.info(
        "llm_map_entities: start | tables=%s columns=%s chunksz=%s timeout=%ss retries=%s model=%s",
        len(tables),
        len(columns),
        max_columns,
        timeout_sec,
        retries,
        settings.openai_model,
    )
    if parallel:
        logger.info("llm_map_entities: parallel=enabled workers=%s", max_workers)

    def _select_glossary(chunk: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not glossary:
            return []
        tokens = {c.get("column", "") for c in chunk} | {c.get("table", "") for c in chunk}
        filtered = []
        for entry in glossary:
            term = str(entry.get("term") or entry.get("abbr") or "").lower()
            if not term:
                continue
            for token in tokens:
                if term in str(token).lower():
                    filtered.append(entry)
                    break
            if len(filtered) >= 50:
                break
        return filtered

    def _invoke(chunk: list[dict[str, Any]], chunk_label: str) -> list[dict[str, Any]]:
        table_name = chunk[0].get("table") if chunk else None
        chunk_index = None
        if ":" in chunk_label:
            try:
                chunk_index = int(chunk_label.split(":", 1)[1])
            except (TypeError, ValueError):
                chunk_index = None
        user_prompt = {
            "entities": entities,
            "columns": chunk,
            "glossary": _select_glossary(chunk),
            "confidence_guidance": "0.9+ for exact match, 0.7 for partial, <=0.6 if unsure",
        }
        request_payload = {
            "table": table_name,
            "chunk_label": chunk_label,
            "columns": [{"table": c.get("table"), "column": c.get("column"), "data_type": c.get("data_type")} for c in chunk],
            "entity_types": list(entities.keys()),
            "glossary": user_prompt["glossary"],
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
        for attempt in range(retries):
            try:
                logger.info(
                    "llm_map_entities: request | chunk=%s columns=%s attempt=%s",
                    chunk_label,
                    len(chunk),
                    attempt + 1,
                )
                with urllib.request.urlopen(request, timeout=timeout_sec) as response:
                    body = json.loads(response.read().decode("utf-8"))
                content = body["choices"][0]["message"]["content"]
                parsed = json.loads(content)
                candidates = parsed.get("candidates", [])
                if isinstance(candidates, list):
                    if agent_context:
                        persist_entity_mapping_agent(
                            settings,
                            job_id=agent_context.get("job_id"),
                            mapping_id=agent_context.get("mapping_id"),
                            tenant_id=agent_context["tenant_id"],
                            domain_id=agent_context["domain_id"],
                            connection_id=agent_context["connection_id"],
                            database_name=agent_context["database_name"],
                            schema_name=agent_context["schema_name"],
                            table_name=table_name,
                            chunk_index=chunk_index,
                            chunk_label=chunk_label,
                            request_payload=request_payload,
                            response_payload={"candidates": candidates},
                            error_message=None,
                        )
                    logger.info(
                        "llm_map_entities: response | chunk=%s candidates=%s",
                        chunk_label,
                        len(candidates),
                    )
                    return _sanitize_candidates(candidates, allowed_entities)
            except Exception as exc:
                if agent_context:
                    persist_entity_mapping_agent(
                        settings,
                        job_id=agent_context.get("job_id"),
                        mapping_id=agent_context.get("mapping_id"),
                        tenant_id=agent_context["tenant_id"],
                        domain_id=agent_context["domain_id"],
                        connection_id=agent_context["connection_id"],
                        database_name=agent_context["database_name"],
                        schema_name=agent_context["schema_name"],
                        table_name=table_name,
                        chunk_index=chunk_index,
                        chunk_label=chunk_label,
                        request_payload=request_payload,
                        response_payload=None,
                        error_message=str(exc),
                    )
                logger.exception(
                    "llm_map_entities: error | chunk=%s attempt=%s err=%s",
                    chunk_label,
                    attempt + 1,
                    exc,
                )
                if attempt + 1 >= retries:
                    raise
                time.sleep(1.5 * (attempt + 1))
        return []

    if not columns:
        return []

    all_candidates: list[dict[str, Any]] = []
    # Multi-agent style: split by table first, then chunk within table.
    tasks: list[tuple[str, list[dict[str, Any]]]] = []
    for table_name, table_cols in table_map.items():
        for start in range(0, len(table_cols), max_columns):
            chunk = table_cols[start : start + max_columns]
            label = f"{table_name}:{(start // max_columns) + 1}"
            tasks.append((label, chunk))
    if parallel and len(tasks) > 1:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(_invoke, chunk, label): label for label, chunk in tasks}
            for future in as_completed(futures):
                label = futures[future]
                try:
                    all_candidates.extend(future.result())
                except Exception as exc:
                    logger.exception("llm_map_entities: chunk failed | chunk=%s err=%s", label, exc)
                    raise
    else:
        for label, chunk in tasks:
            all_candidates.extend(_invoke(chunk, label))
    logger.info("llm_map_entities: complete | total_candidates=%s", len(all_candidates))
    return all_candidates
