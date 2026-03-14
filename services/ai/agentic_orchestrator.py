from __future__ import annotations

from typing import Any, Callable
from concurrent.futures import Future, ThreadPoolExecutor, wait
from html import escape
import json
import os
import re
import time
import urllib.request

try:
    from langgraph.graph import StateGraph, END
except Exception:  # pragma: no cover
    StateGraph = None
    END = None

from services.ai.agentic_store import (
    append_agent_run_event,
    append_agent_chat_log,
    append_agent_run_stage_event,
    append_agent_chat_log_stage,
    upsert_agent_event_artifact,
)
import logging
from services.ai.agentic_agents import (
    build_schema_graph,
    enrich_schema_graph_columns,
    profile_tables,
    extract_context,
    propose_ontology,
    propose_joins,
    propose_metrics,
    propose_chart_candidates,
    select_charts,
    classify_models,
    propose_rollups,
    build_dashboard_spec,
)
from services.ai.semantic_graph_store import persist_semantic_graph, persist_dashboard_spec
from services.ai.views import create_views_from_schema, create_joined_views
from services.ai.charts_store import create_chart_request, update_chart_request
from services.ai.charts import build_chart_payload
from services.ai.db import run_query, execute_non_query
from services.ai.quality_gate import evaluate_quality_report
from services.ai.metrics_registry import upsert_metric
from services.ai.onboarding.models_registry import upsert_fact, upsert_dimension
from services.ai.semantic_contracts import store_semantic_contract
from services.ai.agentic_artifacts_registry import (
    persist_schema_graph_artifact,
    persist_table_profile_artifact,
    replace_join_registry,
    replace_model_registry,
)
from psycopg2.extras import Json


def _qident(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def _resolve_int_setting(
    state: dict[str, Any],
    state_key: str,
    env_key: str,
    default: int,
    minimum: int = 1,
) -> int:
    tuning = state.get("runtime_tuning") or {}
    raw = tuning.get(state_key, os.getenv(env_key, default))
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return max(minimum, value)


def _log_agent_conversation(settings, run_id: str, payload: dict[str, Any], event_type: str) -> None:
    append_agent_run_event(
        settings,
        run_id,
        "AgentConversation",
        event_type,
        payload.get("question") or payload.get("answer") or "agent_conversation",
        payload,
    )


def _check_unique(settings, schema_name: str, table: str, column: str) -> tuple[bool | None, dict[str, Any]]:
    try:
        q_schema = _qident(schema_name)
        q_table = _qident(table)
        q_col = _qident(column)
        rows = run_query(
            settings,
            f"SELECT COUNT(*) AS cnt, COUNT(DISTINCT {q_col}) AS distinct_cnt FROM {q_schema}.{q_table}",
            [],
        )
        if not rows:
            return None, {}
        cnt = rows[0]["cnt"]
        distinct_cnt = rows[0]["distinct_cnt"]
        return cnt == distinct_cnt, {"row_count": cnt, "distinct_count": distinct_cnt}
    except Exception:
        return None, {}
from services.ai.rollups import create_rollup, build_rollup_table, update_rollup_status

_POSTPROCESS_EXECUTOR = ThreadPoolExecutor(max_workers=max(2, int(os.getenv("AGENTIC_POSTPROCESS_MAX_WORKERS", "4"))))
_RUN_POSTPROCESS_FUTURES: dict[str, list[Future]] = {}


def _stream_sample_limit() -> int:
    try:
        value = int(os.getenv("AGENTIC_STREAM_SAMPLE_LIMIT", "50"))
    except (TypeError, ValueError):
        value = 50
    return max(1, min(value, 100))


def _compact_sample_values(sample_values: dict[str, Any], sample_limit: int) -> tuple[dict[str, Any], list[str]]:
    compacted: dict[str, Any] = {}
    truncated_fields: list[str] = []
    for col, values in sample_values.items():
        field_path = f"sample_values.{col}"
        if isinstance(values, list):
            total = len(values)
            sent = values[:sample_limit]
            truncated = total > sample_limit
            if truncated:
                truncated_fields.append(field_path)
            compacted[col] = {
                "values": sent,
                "sent_count": len(sent),
                "total_count": total,
                "truncated": truncated,
            }
            continue
        if isinstance(values, dict) and isinstance(values.get("values"), list):
            raw_values = values.get("values") or []
            total = len(raw_values)
            sent = raw_values[:sample_limit]
            truncated = total > sample_limit
            if truncated:
                truncated_fields.append(f"{field_path}.values")
            item = dict(values)
            item["values"] = sent
            item["sent_count"] = len(sent)
            item["total_count"] = total
            item["truncated"] = truncated
            compacted[col] = item
            continue
        compacted[col] = values
    return compacted, truncated_fields


def _compact_event_artifacts(artifacts: dict[str, Any] | None, sample_limit: int) -> tuple[dict[str, Any], dict[str, Any]]:
    if not artifacts:
        return {}, {"applied": False, "sample_limit": sample_limit, "fields_truncated": []}
    compacted = dict(artifacts)
    truncated_fields: list[str] = []
    if isinstance(compacted.get("sample_values"), dict):
        sample_compacted, sample_fields = _compact_sample_values(compacted.get("sample_values") or {}, sample_limit)
        compacted["sample_values"] = sample_compacted
        truncated_fields.extend(sample_fields)
    if isinstance(compacted.get("profiles"), list):
        profiles = []
        for idx, profile in enumerate(compacted.get("profiles") or []):
            if not isinstance(profile, dict):
                profiles.append(profile)
                continue
            item = dict(profile)
            if isinstance(item.get("sample_values"), dict):
                sample_compacted, sample_fields = _compact_sample_values(item.get("sample_values") or {}, sample_limit)
                item["sample_values"] = sample_compacted
                truncated_fields.extend([f"profiles[{idx}].{field}" for field in sample_fields])
            profiles.append(item)
        compacted["profiles"] = profiles
    return compacted, {"applied": bool(truncated_fields), "sample_limit": sample_limit, "fields_truncated": truncated_fields}


def _summary_text(agent_name: str, raw_json: dict[str, Any]) -> str:
    parts = [f"{agent_name} generated {len(raw_json)} top-level fields."]
    for key, value in list(raw_json.items())[:4]:
        if isinstance(value, list):
            parts.append(f"{key}: {len(value)} items")
        elif isinstance(value, dict):
            parts.append(f"{key}: {len(value)} entries")
        else:
            parts.append(f"{key}: available")
    return " ".join(parts)


def _summary_html(agent_name: str, summary_raw_text: str, raw_json: dict[str, Any]) -> str:
    bullets = []
    for key, value in list(raw_json.items())[:5]:
        if isinstance(value, list):
            val = f"{len(value)} items"
        elif isinstance(value, dict):
            val = f"{len(value)} entries"
        else:
            val = "available"
        bullets.append(f"<li><strong>{escape(str(key))}</strong>: {escape(val)}</li>")
    return (
        f"<section><h4>{escape(agent_name)} Summary</h4>"
        f"<p>{escape(summary_raw_text)}</p>"
        f"<ul>{''.join(bullets)}</ul></section>"
    )[:32768]


def _inference_text(agent_name: str, raw_json: dict[str, Any]) -> str:
    if "tables" in raw_json and isinstance(raw_json.get("tables"), int):
        return f"{agent_name} suggests table coverage is {raw_json.get('tables')} and suitable for downstream modeling."
    if "joins" in raw_json and isinstance(raw_json.get("joins"), int):
        return f"{agent_name} detected {raw_json.get('joins')} join candidates for semantic relationship graphing."
    if "metrics" in raw_json and isinstance(raw_json.get("metrics"), int):
        return f"{agent_name} identified {raw_json.get('metrics')} metrics to seed deterministic query planning."
    return f"{agent_name} output is ready for downstream agent consumption."


def _inference_html(agent_name: str, inference_raw_text: str) -> str:
    return (
        f"<section><h4>{escape(agent_name)} Inference</h4>"
        f"<p>{escape(inference_raw_text)}</p></section>"
    )[:32768]


def _clip_text(value: str, max_chars: int = 4096) -> str:
    text = str(value or "").strip()
    return text[:max_chars]


def _llm_enabled(settings) -> bool:
    mode = os.getenv("AGENTIC_SUMMARY_INFERENCE_MODE", "auto").lower()
    if mode in {"off", "false", "0"}:
        return False
    if mode in {"on", "true", "1"}:
        return bool(getattr(settings, "openai_api_key", None))
    return bool(getattr(settings, "openai_api_key", None))


def _llm_extract_text(
    settings,
    *,
    agent_name: str,
    kind: str,
    raw_json: dict[str, Any],
) -> str | None:
    if not _llm_enabled(settings):
        return None
    model = os.getenv("AGENTIC_SUMMARY_INFERENCE_MODEL", getattr(settings, "openai_model", "gpt-4o-mini"))
    timeout_sec = int(os.getenv("AGENTIC_SUMMARY_INFERENCE_TIMEOUT_SEC", "30"))
    raw_payload = json.dumps(raw_json, default=str)
    if len(raw_payload) > 12000:
        raw_payload = raw_payload[:12000]
    system_prompt = (
        "You summarize agent outputs for users. "
        "Return JSON only with key 'text'. "
        "No chain-of-thought. Keep it concise and factual."
    )
    user_payload = {
        "agent_name": agent_name,
        "kind": kind,
        "raw_json": raw_payload,
        "output_requirements": {
            "summary": "What happened and what artifacts were produced.",
            "inference": "What likely meaning or implication can be drawn.",
        },
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_payload)},
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
        with urllib.request.urlopen(request, timeout=timeout_sec) as response:
            body = json.loads(response.read().decode("utf-8"))
        content = body["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        text = parsed.get("text")
        if isinstance(text, str) and text.strip():
            return _clip_text(text, max_chars=2048)
    except Exception:
        logging.getLogger(__name__).warning("agentic.%s_llm_failed", kind, exc_info=True)
    return None


def _safe_event_callback(event_callback: Callable[[dict[str, Any]], None] | None, payload: dict[str, Any]) -> None:
    if not event_callback:
        return
    try:
        event_callback(payload)
    except Exception:
        logging.getLogger(__name__).exception("agentic.event_callback_failed")


def _emit_stage_event(
    settings,
    run_id: str,
    agent_name: str,
    stage_name: str,
    message: str,
    *,
    logical_event_id: str | None = None,
    artifacts: dict[str, Any] | None = None,
    payload_compacted: bool = False,
    event_callback: Callable[[dict[str, Any]], None] | None = None,
    sender: str = "agent",
) -> dict[str, str]:
    logger = logging.getLogger(__name__)
    event_meta: dict[str, str] | None = None
    try:
        event_meta = append_agent_run_stage_event(
            settings,
            run_id,
            agent_name,
            stage_name,
            message,
            logical_event_id=logical_event_id,
            artifacts=artifacts,
            payload_compacted=payload_compacted,
        )
    except Exception:
        # Fallback for environments without Phase 22 migration applied yet.
        event_id = append_agent_run_event(settings, run_id, agent_name, stage_name, message, artifacts)
        event_meta = {"event_id": event_id, "logical_event_id": logical_event_id or ""}
    try:
        append_agent_chat_log_stage(
            settings,
            run_id,
            sender,
            message,
            event_id=event_meta.get("event_id"),
            logical_event_id=event_meta.get("logical_event_id"),
            stage_name=stage_name,
        )
    except Exception:
        append_agent_chat_log(settings, run_id, sender, message)
    event_payload = {
        "run_id": run_id,
        "event_id": event_meta.get("event_id"),
        "logical_event_id": event_meta.get("logical_event_id"),
        "agent_name": agent_name,
        "status": stage_name,
        "stage_name": stage_name,
        "message": message,
        "payload_compacted": payload_compacted,
        "artifacts": artifacts or {},
    }
    logger.info(
        "agentic.%s | stage=%s status=%s event_id=%s logical_event_id=%s payload_compacted=%s message=%s artifacts=%s",
        agent_name,
        stage_name,
        stage_name,
        event_payload.get("event_id"),
        event_payload.get("logical_event_id"),
        payload_compacted,
        message,
        "none" if not artifacts else list((artifacts or {}).keys()),
    )
    _safe_event_callback(event_callback, event_payload)
    return event_meta


def _emit(
    settings,
    run_id: str,
    agent_name: str,
    status: str,
    message: str,
    artifacts: dict[str, Any] | None = None,
    event_callback: Callable[[dict[str, Any]], None] | None = None,
) -> None:
    if status == "completed":
        sample_limit = _stream_sample_limit()
        compact_raw, truncation = _compact_event_artifacts(artifacts or {}, sample_limit)
        raw_meta = _emit_stage_event(
            settings,
            run_id,
            agent_name,
            "raw_json_ready",
            f"{agent_name} raw payload ready",
            artifacts={"raw_json": compact_raw, "truncation": truncation},
            payload_compacted=bool(truncation.get("applied")),
            event_callback=event_callback,
        )
        logical_event_id = raw_meta.get("logical_event_id")

        def _summary_job() -> dict[str, Any]:
            summary_raw_text = _llm_extract_text(
                settings,
                agent_name=agent_name,
                kind="summary",
                raw_json=compact_raw,
            ) or _summary_text(agent_name, compact_raw)
            summary_html = _summary_html(agent_name, summary_raw_text, compact_raw)
            summary_meta = _emit_stage_event(
                settings,
                run_id,
                agent_name,
                "summary_ready",
                f"{agent_name} summary ready",
                logical_event_id=logical_event_id,
                artifacts={"summary_raw_text": summary_raw_text, "summary_html": summary_html},
                payload_compacted=bool(truncation.get("applied")),
                event_callback=event_callback,
            )
            try:
                upsert_agent_event_artifact(
                    settings,
                    event_id=summary_meta.get("event_id") or "",
                    run_id=run_id,
                    agent_name=agent_name,
                    stage_name="summary_ready",
                    logical_event_id=logical_event_id or "",
                    summary_raw_text=summary_raw_text,
                    summary_html=summary_html,
                    truncation=truncation,
                )
            except Exception:
                pass
            return {"summary_raw_text": summary_raw_text, "summary_html": summary_html}

        def _inference_job() -> dict[str, Any]:
            inference_raw_text = _llm_extract_text(
                settings,
                agent_name=agent_name,
                kind="inference",
                raw_json=compact_raw,
            ) or _inference_text(agent_name, compact_raw)
            inference_html = _inference_html(agent_name, inference_raw_text)
            inference_meta = _emit_stage_event(
                settings,
                run_id,
                agent_name,
                "inference_ready",
                f"{agent_name} inference ready",
                logical_event_id=logical_event_id,
                artifacts={"inference_raw_text": inference_raw_text, "inference_html": inference_html},
                payload_compacted=bool(truncation.get("applied")),
                event_callback=event_callback,
            )
            try:
                upsert_agent_event_artifact(
                    settings,
                    event_id=inference_meta.get("event_id") or "",
                    run_id=run_id,
                    agent_name=agent_name,
                    stage_name="inference_ready",
                    logical_event_id=logical_event_id or "",
                    inference_raw_text=inference_raw_text,
                    inference_html=inference_html,
                    truncation=truncation,
                )
            except Exception:
                pass
            return {"inference_raw_text": inference_raw_text, "inference_html": inference_html}

        summary_future = _POSTPROCESS_EXECUTOR.submit(_summary_job)
        inference_future = _POSTPROCESS_EXECUTOR.submit(_inference_job)

        def _complete_job() -> None:
            wait([summary_future, inference_future])
            summary_data = {}
            inference_data = {}
            try:
                summary_data = summary_future.result() or {}
            except Exception:
                summary_data = {}
            try:
                inference_data = inference_future.result() or {}
            except Exception:
                inference_data = {}
            completed_meta = _emit_stage_event(
                settings,
                run_id,
                agent_name,
                "completed",
                message,
                logical_event_id=logical_event_id,
                artifacts={
                    "raw_json": compact_raw,
                    **summary_data,
                    **inference_data,
                    "truncation": truncation,
                },
                payload_compacted=bool(truncation.get("applied")),
                event_callback=event_callback,
            )
            try:
                upsert_agent_event_artifact(
                    settings,
                    event_id=raw_meta.get("event_id") or "",
                    run_id=run_id,
                    agent_name=agent_name,
                    stage_name="raw_json_ready",
                    logical_event_id=logical_event_id or "",
                    raw_json=compact_raw,
                    truncation=truncation,
                )
                upsert_agent_event_artifact(
                    settings,
                    event_id=completed_meta.get("event_id") or "",
                    run_id=run_id,
                    agent_name=agent_name,
                    stage_name="completed",
                    logical_event_id=logical_event_id or "",
                    raw_json=compact_raw,
                    summary_raw_text=summary_data.get("summary_raw_text"),
                    summary_html=summary_data.get("summary_html"),
                    inference_raw_text=inference_data.get("inference_raw_text"),
                    inference_html=inference_data.get("inference_html"),
                    truncation=truncation,
                )
            except Exception:
                pass

        completion_future = _POSTPROCESS_EXECUTOR.submit(_complete_job)
        _RUN_POSTPROCESS_FUTURES.setdefault(run_id, []).append(completion_future)
    else:
        _emit_stage_event(
            settings,
            run_id,
            agent_name,
            status,
            message,
            artifacts=artifacts,
            payload_compacted=False,
            event_callback=event_callback,
        )
    logging.getLogger(__name__).info(
        "agentic.%s | status=%s message=%s artifacts=%s",
        agent_name,
        status,
        message,
        "none" if not artifacts else list(artifacts.keys()),
    )


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _chart_insight(chart_type: str, rows: list[dict], metric_name: str, dim_key: str | None) -> dict[str, Any]:
    if not rows or not metric_name:
        return {"summary": "No data available", "type": chart_type}
    if chart_type in {"bar", "pie"} and dim_key:
        best = None
        for row in rows:
            value = _safe_float(row.get(metric_name))
            if value is None:
                continue
            if not best or value > best[1]:
                best = (row.get(dim_key), value)
        if best:
            return {
                "summary": f"Top {dim_key}: {best[0]}",
                "value": best[1],
                "type": chart_type,
            }
    if chart_type == "line" and dim_key:
        ordered = []
        for row in rows:
            value = _safe_float(row.get(metric_name))
            if value is None:
                continue
            ordered.append((row.get(dim_key), value))
        if len(ordered) >= 2:
            last = ordered[-1]
            prev = ordered[-2]
            delta = last[1] - prev[1]
            return {
                "summary": f"Latest {metric_name}: {last[1]:.2f} (Δ {delta:.2f})",
                "value": last[1],
                "type": chart_type,
            }
        if ordered:
            return {
                "summary": f"Latest {metric_name}: {ordered[-1][1]:.2f}",
                "value": ordered[-1][1],
                "type": chart_type,
            }
    return {"summary": f"{metric_name} insights generated", "type": chart_type}


def _chart_stats(rows: list[dict], metric_name: str) -> dict[str, Any]:
    values = []
    for row in rows:
        value = _safe_float(row.get(metric_name))
        if value is not None:
            values.append(value)
    if not values:
        return {"count": 0}
    return {
        "count": len(values),
        "min": min(values),
        "max": max(values),
        "avg": sum(values) / len(values),
        "total": sum(values),
    }


def _chart_narrative(rows: list[dict], metric_name: str, dim_key: str | None) -> dict[str, Any]:
    if not rows or not metric_name:
        return {"summary": "No narrative available"}
    values = []
    for row in rows:
        value = _safe_float(row.get(metric_name))
        if value is None:
            continue
        values.append(value)
    if not values:
        return {"summary": "No narrative available"}
    best_idx = values.index(max(values))
    worst_idx = values.index(min(values))
    best_label = rows[best_idx].get(dim_key) if dim_key else None
    worst_label = rows[worst_idx].get(dim_key) if dim_key else None
    summary = f"Top {dim_key}: {best_label} ({values[best_idx]:.2f}); "
    summary += f"Lowest {dim_key}: {worst_label} ({values[worst_idx]:.2f})"
    return {"summary": summary, "top": best_label, "bottom": worst_label}


def _qualify_formula(formula: str, table_ref: str, table_profile: dict[str, Any]) -> str:
    cols = set(
        (table_profile.get("eligible_numeric_columns") or [])
        + (table_profile.get("numeric_columns") or [])
        + (table_profile.get("time_columns") or [])
        + (table_profile.get("categorical_columns") or [])
    )
    qualified = str(formula or "")
    for col in sorted(cols, key=len, reverse=True):
        if not col:
            continue
        qcol = _qident(col)
        replacement = f"{table_ref}.{qcol}"
        # Replace quoted identifier usage: "col"
        quoted_pat = re.compile(rf'(?<![\w\.])"{re.escape(col)}"(?![\w])')
        qualified = quoted_pat.sub(replacement, qualified)
        # Replace bare identifier usage: col
        bare_pat = re.compile(rf"(?<![\w\.\"]){re.escape(col)}(?![\w\"])")
        qualified = bare_pat.sub(replacement, qualified)
    return qualified


def _normalize_metric_type(metric_type: str | None) -> str:
    value = str(metric_type or "").strip().lower()
    if value in {"sum", "average", "avg", "min", "max", "count", "count_distinct", "ratio", "rate", "derived"}:
        return value
    if value in {"efficiency", "utilization", "yield"}:
        return "derived"
    return "sum"


def _normalize_term(value: str | None) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"\s+", " ", text)
    return text


def _persist_agentic_semantic_assets(
    settings,
    run_id: str,
    state: dict[str, Any],
    *,
    persist_glossary: bool = True,
    persist_hierarchy: bool = True,
    persist_contract: bool = True,
) -> dict[str, Any]:
    tenant_id = str(state.get("tenant_id") or "").strip()
    domain_id = str(state.get("domain_id") or "").strip()
    connection_id = str(state.get("connection_id") or "").strip()
    database_name = str(state.get("database_name") or "").strip()
    schema_name = str(state.get("schema_name") or "public").strip() or "public"
    if not tenant_id or not domain_id:
        return {"glossary_terms": 0, "hierarchies": 0, "semantic_contract_id": None}

    glossary_terms = state.get("glossary_terms") or []
    context_entities = state.get("context_entities") or []
    ontology = state.get("ontology") or {}
    hierarchy_hints = state.get("hierarchy_hints") or []
    metric_defs = state.get("metric_defs") or []
    model_classifications = state.get("model_classifications") or []
    join_edges = state.get("join_edges") or []

    glossary_count = 0
    hierarchy_count = 0

    # Persist glossary terms inferred by Context/Glossary/Ontology agents.
    seen_terms: set[str] = set()
    glossary_rows: list[dict[str, Any]] = []
    if persist_glossary:
        for entry in glossary_terms:
            if isinstance(entry, dict):
                term = str(entry.get("term") or "").strip()
                if not term:
                    continue
                normalized = _normalize_term(term)
                if not normalized or normalized in seen_terms:
                    continue
                seen_terms.add(normalized)
                glossary_rows.append(
                    {
                        "term": term,
                        "normalized_term": normalized,
                        "definition": entry.get("definition"),
                        "synonyms": list(entry.get("synonyms") or []),
                        "abbreviations": list(entry.get("abbreviations") or []),
                    }
                )
        for name in context_entities + (ontology.get("concepts") or []):
            term = str(name or "").strip()
            if not term:
                continue
            normalized = _normalize_term(term)
            if not normalized or normalized in seen_terms:
                continue
            seen_terms.add(normalized)
            glossary_rows.append(
                {
                    "term": term,
                    "normalized_term": normalized,
                    "definition": None,
                    "synonyms": [],
                    "abbreviations": [],
                }
            )
        for row in glossary_rows:
            try:
                term_id = f"{tenant_id}__{domain_id}__{row['normalized_term']}"
                execute_non_query(
                    settings,
                    """
                    INSERT INTO public.quantyx_glossary_terms (
                      term_id,
                      tenant_id,
                      domain_id,
                      term,
                      normalized_term,
                      definition,
                      synonyms,
                      abbreviations,
                      lifecycle_status,
                      source_context_id,
                      created_at,
                      updated_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now(), now())
                    ON CONFLICT (term_id)
                    DO UPDATE SET
                      term = EXCLUDED.term,
                      definition = EXCLUDED.definition,
                      synonyms = EXCLUDED.synonyms,
                      abbreviations = EXCLUDED.abbreviations,
                      lifecycle_status = EXCLUDED.lifecycle_status,
                      source_context_id = EXCLUDED.source_context_id,
                      updated_at = now()
                    """,
                    [
                        term_id,
                        tenant_id,
                        domain_id,
                        row["term"],
                        row["normalized_term"],
                        row.get("definition"),
                        Json(row.get("synonyms") or []),
                        Json(row.get("abbreviations") or []),
                        "active",
                        run_id,
                    ],
                )
                glossary_count += 1
            except Exception:
                logging.getLogger(__name__).exception(
                    "agentic.registry.glossary_persist_failed | run_id=%s term=%s",
                    run_id,
                    row.get("term"),
                )

    # Persist hierarchy hints/edges inferred by Context/Ontology agents.
    hierarchy_records: list[tuple[str, list[str], str | None]] = []
    for hint in hierarchy_hints:
        parts = [p.strip() for p in str(hint or "").split(">") if p.strip()]
        if len(parts) >= 2:
            name = parts[0].lower().replace(" ", "_")
            hierarchy_records.append((name, parts, str(hint)))
    if not hierarchy_records:
        for edge in ontology.get("hierarchy_edges") or []:
            parent = str(edge.get("parent") or "").strip()
            child = str(edge.get("child") or "").strip()
            if not parent or not child:
                continue
            name = parent.lower().replace(" ", "_")
            hierarchy_records.append((name, [parent, child], edge.get("source")))
    if persist_hierarchy:
        for idx, (name, levels, description) in enumerate(hierarchy_records, start=1):
            hierarchy_name = name or f"agentic_hierarchy_{idx}"
            try:
                artifact_key = f"{run_id}::{hierarchy_name}"
                execute_non_query(
                    settings,
                    """
                    INSERT INTO public.quantyx_hierarchy_overrides (
                      tenant_id,
                      domain_id,
                      connection_id,
                      database_name,
                      schema_name,
                      context_id,
                      hierarchy_name,
                      hierarchy_group,
                      levels,
                      description,
                      artifact_key,
                      lifecycle_status,
                      source_type,
                      source_run_id,
                      source_context_id,
                      is_current,
                      created_at,
                      updated_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now(), now())
                    ON CONFLICT (tenant_id, domain_id, connection_id, database_name, schema_name, context_id, hierarchy_name)
                    DO UPDATE SET
                      levels = EXCLUDED.levels,
                      description = EXCLUDED.description,
                      artifact_key = EXCLUDED.artifact_key,
                      lifecycle_status = EXCLUDED.lifecycle_status,
                      source_type = EXCLUDED.source_type,
                      source_run_id = EXCLUDED.source_run_id,
                      source_context_id = EXCLUDED.source_context_id,
                      is_current = EXCLUDED.is_current,
                      updated_at = now()
                    """,
                    [
                        tenant_id,
                        domain_id,
                        connection_id,
                        database_name,
                        schema_name,
                        run_id,
                        hierarchy_name,
                        "agentic",
                        Json(levels),
                        description,
                        artifact_key,
                        "active",
                        "agentic",
                        run_id,
                        run_id,
                        True,
                    ],
                )
                hierarchy_count += 1
            except Exception:
                logging.getLogger(__name__).exception(
                    "agentic.registry.hierarchy_persist_failed | run_id=%s hierarchy=%s",
                    run_id,
                    hierarchy_name,
                )

    # Persist full semantic snapshot as contract per run (auditable replay).
    contract_id = None
    if persist_contract:
        try:
            semantic_payload = {
                "ontology": ontology,
                "metric_definitions": metric_defs,
                "dataset_definitions": model_classifications,
                "join_candidates": join_edges,
                "glossary_terms": glossary_rows,
                "hierarchy_hints": hierarchy_hints,
                "run_id": run_id,
            }
            contract_id = store_semantic_contract(
                settings,
                tenant_id=tenant_id,
                industry=domain_id,
                version=f"run-{run_id}",
                payload=semantic_payload,
                status="active",
            )
        except Exception:
            logging.getLogger(__name__).exception(
                "agentic.registry.semantic_contract_persist_failed | run_id=%s",
                run_id,
            )

    return {
        "glossary_terms": glossary_count,
        "hierarchies": hierarchy_count,
        "semantic_contract_id": contract_id,
    }


def _persist_agentic_registry_outputs(
    settings,
    run_id: str,
    state: dict[str, Any],
    *,
    persist_facts: bool = True,
    persist_dimensions: bool = True,
    persist_metrics: bool = True,
) -> dict[str, int]:
    tenant_id = str(state.get("tenant_id") or "").strip()
    domain_id = str(state.get("domain_id") or "").strip()
    connection_id = str(state.get("connection_id") or "").strip()
    database_name = str(state.get("database_name") or "").strip()
    schema_name = str(state.get("schema_name") or "public").strip() or "public"
    if not tenant_id or not domain_id or not connection_id or not database_name:
        return {"facts": 0, "dimensions": 0, "metrics": 0}

    profiling_tables = (state.get("profiling_stats") or {}).get("tables") or []
    profiling_map = {str(t.get("name") or ""): t for t in profiling_tables if t.get("name")}
    schema_tables = (state.get("schema_graph") or {}).get("tables") or []
    metric_defs = state.get("metric_defs") or []
    logger = logging.getLogger(__name__)
    logger.info(
        "agentic.registry.persist.start | run_id=%s tenant=%s domain=%s connection=%s db=%s schema=%s schema_tables=%s profiling_tables=%s metric_defs=%s persist_facts=%s persist_dimensions=%s persist_metrics=%s",
        run_id,
        tenant_id,
        domain_id,
        connection_id,
        database_name,
        schema_name,
        len(schema_tables),
        len(profiling_tables),
        len(metric_defs),
        persist_facts,
        persist_dimensions,
        persist_metrics,
    )

    persisted_facts = 0
    persisted_dimensions = 0
    persisted_metrics = 0

    # Persist facts for all scanned tables.
    if persist_facts:
        for table in schema_tables:
            base_table = str(table.get("name") or "").strip()
            if not base_table:
                continue
            profile = profiling_map.get(base_table) or {}
            time_cols = profile.get("time_columns") or []
            cat_cols = profile.get("categorical_columns") or []
            eligible_measures = profile.get("eligible_numeric_columns") or []
            numeric_cols = profile.get("numeric_columns") or []
            measures = list(dict.fromkeys([*eligible_measures, *numeric_cols]))
            dimensions = list(dict.fromkeys([*time_cols, *cat_cols]))
            time_column = time_cols[0] if time_cols else None
            grain = "day" if time_column else "unknown"
            fact_model = f"fact_{base_table}"
            try:
                upsert_fact(
                    settings,
                    {
                        "fact_id": f"{domain_id}__{fact_model}",
                        "tenant_id": tenant_id,
                        "domain_id": domain_id,
                        "connection_id": connection_id,
                        "database_name": database_name,
                        "schema_name": schema_name,
                        "table_name": fact_model,
                        "grain": grain,
                        "time_column": time_column,
                        "measures": measures,
                        "dimensions": dimensions,
                        "description": f"Agentic inferred fact for {base_table}",
                        "artifact_key": f"{domain_id}__{fact_model}",
                        "lifecycle_status": "active",
                        "source_type": "agentic",
                        "source_run_id": run_id,
                        "is_current": True,
                    },
                )
                persisted_facts += 1
            except Exception:
                logging.getLogger(__name__).exception(
                    "agentic.registry.fact_persist_failed | run_id=%s table=%s",
                    run_id,
                    base_table,
                )

    # Persist dimensions by unique dimension name across profiled tables.
    if persist_dimensions:
        dim_map: dict[str, dict[str, Any]] = {}
        for table_name, profile in profiling_map.items():
            for col in (profile.get("categorical_columns") or []) + (profile.get("time_columns") or []):
                if not col:
                    continue
                entry = dim_map.setdefault(
                    str(col),
                    {"keys": [col], "attributes": [], "tables": set()},
                )
                entry["tables"].add(table_name)
        for dim_name, meta in dim_map.items():
            tables_list = sorted(list(meta["tables"]))[:8]
            try:
                upsert_dimension(
                    settings,
                    {
                        "dimension_id": f"{domain_id}__dim__{dim_name}",
                        "tenant_id": tenant_id,
                        "domain_id": domain_id,
                        "connection_id": connection_id,
                        "database_name": database_name,
                        "schema_name": schema_name,
                        "name": dim_name,
                        "keys": meta["keys"] or [dim_name],
                        "attributes": meta["attributes"] or [],
                        "description": f"Agentic inferred dimension used in {', '.join(tables_list)}",
                        "artifact_key": f"{domain_id}__dim__{dim_name}",
                        "lifecycle_status": "active",
                        "source_type": "agentic",
                        "source_run_id": run_id,
                        "is_current": True,
                    },
                )
                persisted_dimensions += 1
            except Exception:
                logging.getLogger(__name__).exception(
                    "agentic.registry.dimension_persist_failed | run_id=%s dimension=%s",
                    run_id,
                    dim_name,
                )

    # Persist all generated metrics (no selection gate).
    if persist_metrics:
        for metric in metric_defs:
            metric_name = str(metric.get("metric_name") or "").strip()
            base_table = str(metric.get("base_table") or "").strip()
            formula = str(metric.get("formula") or "").strip()
            if not metric_name or not base_table:
                continue
            fact_model = f"fact_{base_table}"
            table_ref = "{{ ref('%s') }}" % fact_model
            table_profile = profiling_map.get(base_table) or {}
            sql_expr = _qualify_formula(formula, table_ref, table_profile) if formula else ""
            if not sql_expr:
                fallback_col = None
                for key in ("eligible_numeric_columns", "numeric_columns", "categorical_columns", "time_columns"):
                    cols = table_profile.get(key) or []
                    if cols:
                        fallback_col = cols[0]
                        break
                if fallback_col:
                    sql_expr = f"SUM({table_ref}.{_qident(fallback_col)})"
                else:
                    # Last-resort expression to keep metric present; execution may still reject on usage.
                    sql_expr = "COUNT(1)"
            metric_dims = list(
                dict.fromkeys(
                    (table_profile.get("categorical_columns") or [])
                    + (table_profile.get("time_columns") or [])
                )
            )
            metric_type = _normalize_metric_type(metric.get("metric_type"))
            artifact_key = f"{domain_id}__{base_table}__{metric_name}"
            existing = run_query(
                settings,
                """
                SELECT metric_id
                  FROM public.quantyx_metrics_registry
                 WHERE tenant_id = %s
                   AND domain_id = %s
                   AND connection_id = %s
                   AND database_name = %s
                   AND schema_name = %s
                   AND artifact_key = %s
                   AND source_run_id = %s
                   AND COALESCE(is_current, true) = true
                 LIMIT 1
                """,
                [tenant_id, domain_id, connection_id, database_name, schema_name, artifact_key, run_id],
            )
            if existing:
                continue
            try:
                upsert_metric(
                    settings,
                    {
                        "metric_id": artifact_key,
                        "artifact_key": artifact_key,
                        "tenant_id": tenant_id,
                        "domain_id": domain_id,
                        "connection_id": connection_id,
                        "database": database_name,
                        "schema": schema_name,
                        "metric_name": metric_name,
                        "display_name": metric_name.replace("_", " ").title(),
                        "description": f"Agentic inferred metric for {base_table}",
                        "type": metric_type,
                        "unit": metric.get("unit"),
                        "confidence": metric.get("measure_confidence"),
                        "additive": metric_type in {"sum", "count", "avg", "average", "min", "max"},
                        "grain": "day" if (table_profile.get("time_columns") or []) else "unknown",
                        "dimensions": metric_dims,
                        "dataset_id": fact_model,
                        "source_model": fact_model,
                        "source_schema": schema_name,
                        "sql": sql_expr,
                        "lifecycle_status": "active",
                        "source_type": "agentic",
                        "source_run_id": run_id,
                        "is_current": True,
                    },
                )
                persisted_metrics += 1
                logger.info(
                    "agentic.registry.metric_persisted | run_id=%s metric_name=%s base_table=%s artifact_key=%s dataset_id=%s source_model=%s",
                    run_id,
                    metric_name,
                    base_table,
                    artifact_key,
                    fact_model,
                    fact_model,
                )
            except Exception:
                logging.getLogger(__name__).exception(
                    "agentic.registry.metric_persist_failed | run_id=%s metric=%s base_table=%s",
                    run_id,
                    metric_name,
                    base_table,
                )

    result = {
        "facts": persisted_facts,
        "dimensions": persisted_dimensions,
        "metrics": persisted_metrics,
    }
    logger.info(
        "agentic.registry.persist.complete | run_id=%s facts=%s dimensions=%s metrics=%s",
        run_id,
        result["facts"],
        result["dimensions"],
        result["metrics"],
    )
    return result


def run_agentic_workflow(
    settings,
    run_id: str,
    initial_state: dict[str, Any],
    event_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    if StateGraph is None:
        raise RuntimeError("LangGraph is not available")

    logger = logging.getLogger(__name__)
    logger.info(
        "agentic.workflow.start | run_id=%s tenant=%s domain=%s schema=%s connection_id=%s database=%s",
        run_id,
        initial_state.get("tenant_id"),
        initial_state.get("domain_id"),
        initial_state.get("schema_name"),
        initial_state.get("connection_id"),
        initial_state.get("database_name"),
    )

    graph = StateGraph(dict)

    def schema_node(state: dict[str, Any]) -> dict[str, Any]:
        _emit(settings, run_id, "SchemaAgent", "running", "Schema Agent started", event_callback=event_callback)
        append_agent_chat_log(settings, run_id, "system", "Scanning schema for tables.")
        schema_payload = state.get("schema_payload") or {}
        schema_name = state.get("schema_name") or "public"
        logger.info(
            "agentic.schema.input | run_id=%s schema=%s payload_keys=%s",
            run_id,
            schema_name,
            sorted(schema_payload.keys()) if isinstance(schema_payload, dict) else [],
        )
        state["schema_graph"] = enrich_schema_graph_columns(
            settings,
            build_schema_graph(schema_payload),
            schema_name,
        )
        tables = state["schema_graph"].get("tables", []) or []
        with_columns = sum(1 for t in tables if (t.get("columns") or []))
        logger.info(
            "agentic.schema.output | run_id=%s tables=%s with_columns=%s without_columns=%s",
            run_id,
            len(tables),
            with_columns,
            max(0, len(tables) - with_columns),
        )
        try:
            persist_schema_graph_artifact(
                settings,
                tenant_id=str(state.get("tenant_id") or ""),
                domain_id=str(state.get("domain_id") or ""),
                run_id=run_id,
                connection_id=str(state.get("connection_id") or ""),
                database_name=str(state.get("database_name") or ""),
                schema_name=str(state.get("schema_name") or "public"),
                schema_graph=state["schema_graph"],
            )
        except Exception:
            logger.exception("agentic.schema.persist_failed | run_id=%s", run_id)
        _emit(
            settings,
            run_id,
            "SchemaAgent",
            "completed",
            "Schema Agent completed",
            {
                "tables": len(state["schema_graph"].get("tables", [])),
                "table_names": [t.get("name") for t in state["schema_graph"].get("tables", [])],
                "tables_detail": state["schema_graph"].get("tables", []),
            },
            event_callback=event_callback,
        )
        return state

    def profiling_node(state: dict[str, Any]) -> dict[str, Any]:
        _emit(settings, run_id, "ProfilingAgent", "running", "Profiling Agent started", event_callback=event_callback)
        schema_name = state.get("schema_name") or "public"
        state["profiling_stats"] = profile_tables(settings, state.get("schema_graph", {}), schema_name)
        prof_tables = state["profiling_stats"].get("tables", []) or []
        logger.info(
            "agentic.profiling.output | run_id=%s tables=%s sample=%s",
            run_id,
            len(prof_tables),
            [
                {
                    "table": t.get("name"),
                    "row_count": t.get("row_count"),
                    "eligible_numeric_columns": len(t.get("eligible_numeric_columns") or []),
                    "time_columns": len(t.get("time_columns") or []),
                    "categorical_columns": len(t.get("categorical_columns") or []),
                }
                for t in prof_tables[:5]
            ],
        )
        append_agent_chat_log(
            settings,
            run_id,
            "system",
            "Profiling completed: detected %s tables."
            % len(state["profiling_stats"].get("tables", [])),
        )
        try:
            persist_table_profile_artifact(
                settings,
                tenant_id=str(state.get("tenant_id") or ""),
                domain_id=str(state.get("domain_id") or ""),
                run_id=run_id,
                connection_id=str(state.get("connection_id") or ""),
                database_name=str(state.get("database_name") or ""),
                schema_name=str(state.get("schema_name") or "public"),
                profiling_json=state["profiling_stats"],
            )
        except Exception:
            logger.exception("agentic.profiling.persist_failed | run_id=%s", run_id)
        registry_persisted = {"facts": 0, "dimensions": 0, "metrics": 0}
        try:
            registry_persisted = _persist_agentic_registry_outputs(
                settings,
                run_id,
                state,
                persist_facts=True,
                persist_dimensions=True,
                persist_metrics=False,
            )
        except Exception:
            logger.exception("agentic.registry.profile_persist_failed | run_id=%s", run_id)
        _emit(
            settings,
            run_id,
            "ProfilingAgent",
            "completed",
            "Profiling Agent completed",
            {
                "tables": len(state["profiling_stats"].get("tables", [])),
                "profiles": state["profiling_stats"].get("tables", []),
                "registry_persisted": registry_persisted,
            },
            event_callback=event_callback,
        )
        return state

    def context_node(state: dict[str, Any]) -> dict[str, Any]:
        _emit(settings, run_id, "ContextAgent", "running", "Context Agent started", event_callback=event_callback)
        context_text = state.get("context_text")
        logger.info(
            "agentic.context.input | run_id=%s has_context_text=%s context_len=%s",
            run_id,
            bool(context_text),
            len(str(context_text or "")),
        )
        extracted = extract_context(settings, context_text, state.get("schema_graph", {}))
        state["context_entities"] = extracted.get("context_entities", [])
        state["hierarchy_hints"] = extracted.get("hierarchy_hints", [])
        state["glossary_terms"] = extracted.get("glossary_terms", [])
        if not state["glossary_terms"] and state.get("schema_graph"):
            # fallback if context extraction yielded nothing
            extracted = extract_context(settings, None, state.get("schema_graph", {}))
            state["context_entities"] = extracted.get("context_entities", [])
            state["hierarchy_hints"] = extracted.get("hierarchy_hints", [])
            state["glossary_terms"] = extracted.get("glossary_terms", [])
        semantics_persisted = {"glossary_terms": 0, "hierarchies": 0, "semantic_contract_id": None}
        try:
            semantics_persisted = _persist_agentic_semantic_assets(
                settings,
                run_id,
                state,
                persist_glossary=True,
                persist_hierarchy=True,
                persist_contract=False,
            )
        except Exception:
            logger.exception("agentic.registry.context_persist_failed | run_id=%s", run_id)
        _emit(
            settings,
            run_id,
            "ContextAgent",
            "completed",
            "Context Agent completed",
            {
                "entities": len(state["context_entities"]),
                "sample_entities": state["context_entities"][:10],
                "glossary_terms": state["glossary_terms"],
                "semantics_persisted": semantics_persisted,
            },
            event_callback=event_callback,
        )
        if state.get("context_entities"):
            append_agent_chat_log(
                settings,
                run_id,
                "system",
                "Context applied: %s terms detected." % len(state["context_entities"]),
            )
        logger.info(
            "agentic.context.output | run_id=%s entities=%s hierarchy_hints=%s glossary_terms=%s",
            run_id,
            len(state.get("context_entities") or []),
            len(state.get("hierarchy_hints") or []),
            len(state.get("glossary_terms") or []),
        )
        return state

    def glossary_node(state: dict[str, Any]) -> dict[str, Any]:
        _emit(settings, run_id, "GlossaryAgent", "running", "Glossary Agent started", event_callback=event_callback)
        if "glossary_terms" not in state:
            state["glossary_terms"] = []
        if not state["glossary_terms"] and state.get("profiling_stats"):
            inferred_terms = []
            for table in state["profiling_stats"].get("tables", []):
                name = table.get("name")
                if name:
                    inferred_terms.append({"term": name.replace("_", " "), "synonyms": [name], "abbreviations": []})
                for col in (table.get("numeric_columns") or []) + (table.get("time_columns") or []) + (
                    table.get("categorical_columns") or []
                ):
                    inferred_terms.append({"term": col.replace("_", " "), "synonyms": [col], "abbreviations": []})
            state["glossary_terms"] = inferred_terms
        logger.info(
            "agentic.glossary.output | run_id=%s terms=%s",
            run_id,
            len(state.get("glossary_terms") or []),
        )
        semantics_persisted = {"glossary_terms": 0, "hierarchies": 0, "semantic_contract_id": None}
        try:
            semantics_persisted = _persist_agentic_semantic_assets(
                settings,
                run_id,
                state,
                persist_glossary=True,
                persist_hierarchy=False,
                persist_contract=False,
            )
        except Exception:
            logger.exception("agentic.registry.glossary_persist_failed | run_id=%s", run_id)
        _emit(
            settings,
            run_id,
            "GlossaryAgent",
            "completed",
            "Glossary Agent completed",
            {
                "terms": len(state["glossary_terms"]),
                "terms_detail": state["glossary_terms"],
                "semantics_persisted": semantics_persisted,
            },
            event_callback=event_callback,
        )
        return state

    def ontology_node(state: dict[str, Any]) -> dict[str, Any]:
        _emit(settings, run_id, "OntologyAgent", "running", "Ontology Agent started", event_callback=event_callback)
        ontology = propose_ontology(
            state.get("context_entities") or [],
            state.get("hierarchy_hints") or [],
            state.get("glossary_terms") or [],
        )
        if not ontology.get("concepts") and state.get("profiling_stats"):
            inferred = []
            for table in state["profiling_stats"].get("tables", []):
                name = table.get("name")
                if name:
                    inferred.append(name.replace("_", " "))
            if inferred:
                ontology["concepts"] = inferred
        state["ontology"] = ontology
        logger.info(
            "agentic.ontology.output | run_id=%s concepts=%s hierarchy_edges=%s synonym_edges=%s",
            run_id,
            len(ontology.get("concepts", []) or []),
            len(ontology.get("hierarchy_edges", []) or []),
            len(ontology.get("synonym_edges", []) or []),
        )
        semantics_persisted = {"glossary_terms": 0, "hierarchies": 0, "semantic_contract_id": None}
        try:
            semantics_persisted = _persist_agentic_semantic_assets(
                settings,
                run_id,
                state,
                persist_glossary=True,
                persist_hierarchy=True,
                persist_contract=False,
            )
        except Exception:
            logger.exception("agentic.registry.ontology_persist_failed | run_id=%s", run_id)
        _emit(
            settings,
            run_id,
            "OntologyAgent",
            "completed",
            "Ontology Agent completed",
            {
                "concepts": len(ontology.get("concepts", [])),
                "hierarchy_edges": len(ontology.get("hierarchy_edges", [])),
                "synonym_edges": len(ontology.get("synonym_edges", [])),
                "concepts_detail": ontology.get("concepts", []),
                "hierarchy_edges_detail": ontology.get("hierarchy_edges", []),
                "synonym_edges_detail": ontology.get("synonym_edges", []),
                "semantics_persisted": semantics_persisted,
            },
            event_callback=event_callback,
        )
        return state

    def join_node(state: dict[str, Any]) -> dict[str, Any]:
        _emit(settings, run_id, "JoinAgent", "running", "Join Agent started", event_callback=event_callback)
        state["join_edges"] = propose_joins(
            state.get("schema_graph", {}),
            state.get("profiling_stats", {}),
        )
        logger.info(
            "agentic.join.candidates | run_id=%s count=%s",
            run_id,
            len(state.get("join_edges") or []),
        )
        _emit(
            settings,
            run_id,
            "JoinAgent",
            "running",
            "Join Agent proposed join candidates",
            {"candidates": len(state.get("join_edges") or [])},
            event_callback=event_callback,
        )
        schema_name = state.get("schema_name") or "public"
        profiling_map = {t.get("name"): t for t in (state.get("profiling_stats", {}).get("tables") or [])}
        max_validation_rows = _resolve_int_setting(
            state,
            "join_validation_max_rows",
            "AGENTIC_JOIN_VALIDATION_MAX_ROWS",
            500_000,
        )
        max_coverage_left_rows = _resolve_int_setting(
            state,
            "join_coverage_left_sample_limit",
            "AGENTIC_JOIN_COVERAGE_LEFT_SAMPLE_LIMIT",
            200_000,
        )
        max_coverage_right_rows = _resolve_int_setting(
            state,
            "join_coverage_right_sample_limit",
            "AGENTIC_JOIN_COVERAGE_RIGHT_SAMPLE_LIMIT",
            200_000,
        )
        max_uniqueness_joins = _resolve_int_setting(
            state,
            "join_uniqueness_max_joins",
            "AGENTIC_JOIN_UNIQUENESS_MAX_JOINS",
            2,
        )
        max_coverage_joins = _resolve_int_setting(
            state,
            "join_coverage_max_joins",
            "AGENTIC_JOIN_COVERAGE_MAX_JOINS",
            5,
        )
        _emit(
            settings,
            run_id,
            "JoinAgent",
            "running",
            "Join Agent validating uniqueness on top joins",
            {"max_joins": max_uniqueness_joins, "max_rows": max_validation_rows},
            event_callback=event_callback,
        )
        # Agent-to-agent validation for first few joins
        for join in state["join_edges"][:max_uniqueness_joins]:
            table = join.get("left_table")
            column = join.get("left_key")
            if not table or not column:
                continue
            row_count = int((profiling_map.get(table) or {}).get("row_count") or 0)
            if row_count > max_validation_rows:
                join["uniqueness_check"] = {
                    "status": "skipped",
                    "reason": "table_too_large",
                    "row_count": row_count,
                    "max_rows": max_validation_rows,
                }
                continue
            request_payload = {
                "from_agent": "JoinAgent",
                "to_agent": "SchemaAgent",
                "question": f"Is {column} unique in {table}?",
                "expected_answer_type": "boolean",
                "context": {"table": table, "column": column},
            }
            _log_agent_conversation(settings, run_id, request_payload, "request")
            answer, evidence = _check_unique(settings, schema_name, table, column)
            response_payload = {
                "from_agent": "SchemaAgent",
                "to_agent": "JoinAgent",
                "answer": answer,
                "confidence": 0.9 if answer else 0.4 if answer is not None else 0.2,
                "evidence": evidence,
            }
            _log_agent_conversation(settings, run_id, response_payload, "response")
            if answer is not None:
                base_conf = join.get("confidence") or 0.5
                join["confidence"] = min(1.0, (base_conf + response_payload["confidence"]) / 2)
                join["uniqueness_check"] = {
                    "status": "completed",
                    "row_count": evidence.get("row_count"),
                    "distinct_count": evidence.get("distinct_count"),
                }
        _emit(
            settings,
            run_id,
            "JoinAgent",
            "running",
            "Join Agent computing join coverage ratios",
            {"max_joins": max_coverage_joins, "sample_limit": max_coverage_left_rows},
            event_callback=event_callback,
        )
        # Join coverage check for top joins
        for idx, join in enumerate(state["join_edges"][:max_coverage_joins], start=1):
            left_table = join.get("left_table")
            right_table = join.get("right_table")
            left_key = join.get("left_key")
            right_key = join.get("right_key")
            if not (left_table and right_table and left_key and right_key):
                continue
            left_row_count = int((profiling_map.get(left_table) or {}).get("row_count") or 0)
            right_row_count = int((profiling_map.get(right_table) or {}).get("row_count") or 0)
            _emit(
                settings,
                run_id,
                "JoinAgent",
                "running",
                f"Join Agent coverage check {idx}/5: {left_table}.{left_key} -> {right_table}.{right_key}",
                {
                    "left_rows": left_row_count,
                    "right_rows": right_row_count,
                    "left_table": left_table,
                    "right_table": right_table,
                },
                event_callback=event_callback,
            )
            if left_row_count > max_validation_rows:
                join["coverage_check"] = {
                    "status": "skipped",
                    "reason": "left_table_too_large",
                    "row_count": left_row_count,
                    "max_rows": max_validation_rows,
                }
                continue
            if right_row_count > max_validation_rows:
                join["coverage_check"] = {
                    "status": "skipped",
                    "reason": "right_table_too_large",
                    "row_count": right_row_count,
                    "max_rows": max_validation_rows,
                }
                continue
            try:
                q_schema = _qident(schema_name)
                q_left_table = _qident(left_table)
                q_right_table = _qident(right_table)
                q_left_key = _qident(left_key)
                q_right_key = _qident(right_key)
                sql = (
                    "WITH l AS ("
                    f"SELECT {q_left_key} AS join_key "
                    f"FROM {q_schema}.{q_left_table} "
                    f"WHERE {q_left_key} IS NOT NULL "
                    f"LIMIT {max_coverage_left_rows}"
                    "), r AS ("
                    f"SELECT {q_right_key} AS join_key "
                    f"FROM {q_schema}.{q_right_table} "
                    f"WHERE {q_right_key} IS NOT NULL "
                    f"LIMIT {max_coverage_right_rows}"
                    ") "
                    f"SELECT COUNT(*) AS total, "
                    "COUNT(*) FILTER (WHERE r.join_key IS NOT NULL) AS matched "
                    "FROM l "
                    "LEFT JOIN r "
                    "ON l.join_key = r.join_key"
                )
                rows = run_query(settings, sql, [])
                if rows:
                    total = rows[0].get("total") or 0
                    matched = rows[0].get("matched") or 0
                    join["coverage_ratio"] = (matched / total) if total else None
                    join["coverage_total"] = total
                    join["coverage_matched"] = matched
                    join["coverage_check"] = {
                        "status": "completed",
                        "sample_limit": max_coverage_left_rows,
                        "right_sample_limit": max_coverage_right_rows,
                    }
            except Exception:
                join["coverage_check"] = {"status": "failed"}
                continue
        _emit(
            settings,
            run_id,
            "JoinAgent",
            "completed",
            "Join Agent completed",
            {
                "joins": len(state["join_edges"]),
                "join_edges_detail": state["join_edges"],
            },
            event_callback=event_callback,
        )
        logger.info(
            "agentic.join.output | run_id=%s joins=%s sample=%s",
            run_id,
            len(state.get("join_edges") or []),
            [
                {
                    "left": j.get("left_table"),
                    "right": j.get("right_table"),
                    "coverage_ratio": j.get("coverage_ratio"),
                    "confidence": j.get("confidence"),
                    "coverage_check": (j.get("coverage_check") or {}).get("status"),
                    "uniqueness_check": (j.get("uniqueness_check") or {}).get("status"),
                }
                for j in (state.get("join_edges") or [])[:5]
            ],
        )
        try:
            persisted = replace_join_registry(
                settings,
                tenant_id=str(state.get("tenant_id") or ""),
                domain_id=str(state.get("domain_id") or ""),
                run_id=run_id,
                connection_id=str(state.get("connection_id") or ""),
                database_name=str(state.get("database_name") or ""),
                schema_name=str(state.get("schema_name") or "public"),
                joins=state.get("join_edges") or [],
            )
            logger.info("agentic.join.persisted | run_id=%s joins=%s", run_id, persisted)
        except Exception:
            logger.exception("agentic.join.persist_failed | run_id=%s", run_id)
        return state

    def metric_node(state: dict[str, Any]) -> dict[str, Any]:
        _emit(settings, run_id, "MetricAgent", "running", "Metric Agent started", event_callback=event_callback)
        state["metric_defs"] = propose_metrics(
            state.get("profiling_stats", {}),
            domain_id=state.get("domain_id"),
        )
        logger.info(
            "agentic.metrics.output | run_id=%s metrics=%s sample=%s",
            run_id,
            len(state.get("metric_defs") or []),
            [
                {
                    "name": m.get("metric_name"),
                    "table": m.get("base_table"),
                    "type": m.get("metric_type"),
                    "eligible_measure": m.get("eligible_measure"),
                    "intent": m.get("metric_intent"),
                }
                for m in (state.get("metric_defs") or [])[:8]
            ],
        )
        if state.get("metric_defs"):
            append_agent_chat_log(
                settings,
                run_id,
                "system",
                "Metrics generated: %s"
                % ", ".join([m.get("metric_name") for m in state["metric_defs"][:5]]),
            )
        registry_persisted = {"facts": 0, "dimensions": 0, "metrics": 0}
        try:
            registry_persisted = _persist_agentic_registry_outputs(
                settings,
                run_id,
                state,
                persist_facts=False,
                persist_dimensions=False,
                persist_metrics=True,
            )
        except Exception:
            logger.exception("agentic.registry.metric_persist_failed | run_id=%s", run_id)
        _emit(
            settings,
            run_id,
            "MetricAgent",
            "completed",
            "Metric Agent completed",
            {
                "metrics": len(state["metric_defs"]),
                "metric_defs_detail": state["metric_defs"],
                "registry_persisted": registry_persisted,
            },
            event_callback=event_callback,
        )
        return state

    def model_node(state: dict[str, Any]) -> dict[str, Any]:
        _emit(
            settings,
            run_id,
            "SemanticModelAgent",
            "running",
            "Semantic Model Agent started",
            event_callback=event_callback,
        )
        state["model_classifications"] = classify_models(state.get("profiling_stats", {}))
        logger.info(
            "agentic.model.output | run_id=%s models=%s sample=%s",
            run_id,
            len(state.get("model_classifications") or []),
            (state.get("model_classifications") or [])[:5],
        )
        append_agent_chat_log(settings, run_id, "system", "Semantic model classified.")
        try:
            persisted = replace_model_registry(
                settings,
                tenant_id=str(state.get("tenant_id") or ""),
                domain_id=str(state.get("domain_id") or ""),
                run_id=run_id,
                connection_id=str(state.get("connection_id") or ""),
                database_name=str(state.get("database_name") or ""),
                schema_name=str(state.get("schema_name") or "public"),
                models=state.get("model_classifications") or [],
            )
            logger.info("agentic.model.persisted | run_id=%s models=%s", run_id, persisted)
        except Exception:
            logger.exception("agentic.model.persist_failed | run_id=%s", run_id)
        _emit(
            settings,
            run_id,
            "SemanticModelAgent",
            "completed",
            "Semantic Model Agent completed",
            {
                "models": len(state["model_classifications"]),
                "model_classifications_detail": state["model_classifications"],
            },
            event_callback=event_callback,
        )
        return state

    def rollup_node(state: dict[str, Any]) -> dict[str, Any]:
        _emit(
            settings,
            run_id,
            "RollupPlannerAgent",
            "running",
            "Rollup Planner Agent started",
            event_callback=event_callback,
        )
        rollups = propose_rollups(state.get("metric_defs", []), state.get("profiling_stats", {}))
        logger.info(
            "agentic.rollup.candidates | run_id=%s candidates=%s",
            run_id,
            len(rollups or []),
        )
        created = 0
        created_defs: list[dict[str, Any]] = []
        for rollup in rollups:
            try:
                created_rollup = create_rollup(
                    settings,
                    tenant_id=state.get("tenant_id") or "",
                    domain_id=state.get("domain_id") or "",
                    metric_name=rollup["metric_name"],
                    dimensions=rollup["dimensions"],
                    time_grain=rollup["time_grain"],
                )
                update_rollup_status(settings, created_rollup["rollup_id"], "building")
                build_rollup_table(settings, created_rollup, schema_name=settings.db_schema)
                update_rollup_status(settings, created_rollup["rollup_id"], "active")
                created += 1
                created_defs.append(created_rollup)
            except Exception:
                continue
        _emit(
            settings,
            run_id,
            "RollupPlannerAgent",
            "completed",
            "Rollup Planner Agent completed",
            {"rollups": created, "rollup_defs": created_defs, "rollup_candidates": rollups},
            event_callback=event_callback,
        )
        if created:
            append_agent_chat_log(settings, run_id, "system", f"Rollups created: {created}")
        logger.info(
            "agentic.rollup.output | run_id=%s created=%s",
            run_id,
            created,
        )
        return state

    def chart_planner_node(state: dict[str, Any]) -> dict[str, Any]:
        _emit(settings, run_id, "ChartPlannerAgent", "running", "Chart Planner started", event_callback=event_callback)
        min_charts = _resolve_int_setting(
            state,
            "chart_min_charts",
            "AGENTIC_CHART_MIN_CHARTS",
            4,
        )
        max_charts = _resolve_int_setting(
            state,
            "chart_max_charts",
            "AGENTIC_CHART_MAX_CHARTS",
            8,
        )
        if min_charts > max_charts:
            min_charts = max_charts
        candidates = propose_chart_candidates(
            state.get("profiling_stats", {}),
            state.get("metric_defs", []),
            state.get("join_edges", []),
        )
        selected = select_charts(candidates, min_charts=min_charts, max_charts=max_charts)
        rejected = [cand for cand in candidates if cand.get("skipped")]
        logger.info(
            "agentic.chart_planner.output | run_id=%s candidates=%s selected=%s rejected=%s sample_selected=%s",
            run_id,
            len(candidates),
            len(selected),
            len(rejected),
            [
                {
                    "title": c.get("title"),
                    "table": c.get("table"),
                    "metric": c.get("metric"),
                    "metric_expr": c.get("metric_expr"),
                    "type": c.get("type"),
                    "intent": c.get("intent"),
                }
                for c in selected[:8]
            ],
        )
        state["chart_candidates"] = candidates
        state["chart_plan"] = selected
        state["chart_candidate_rejections"] = rejected
        _emit(
            settings,
            run_id,
            "ChartPlannerAgent",
            "completed",
            "Chart Planner completed",
            {
                "candidates": len(candidates),
                "selected": len(selected),
                "rejected": len(rejected),
                "min_charts": min_charts,
                "max_charts": max_charts,
                "chart_plan": selected,
                "chart_rejections": rejected,
            },
            event_callback=event_callback,
        )
        return state

    def quality_node(state: dict[str, Any]) -> dict[str, Any]:
        _emit(settings, run_id, "QualityGateAgent", "running", "Quality Gate started", event_callback=event_callback)
        quality_report = evaluate_quality_report(state)
        state["quality_report"] = quality_report
        logger.info(
            "agentic.quality.output | run_id=%s gate_passed=%s score=%s warnings=%s chart_rejections=%s",
            run_id,
            quality_report.get("gate_passed"),
            quality_report.get("quality_score"),
            quality_report.get("warnings"),
            len(quality_report.get("chart_rejections") or []),
        )
        _emit(
            settings,
            run_id,
            "QualityGateAgent",
            "completed",
            "Quality Gate completed",
            quality_report,
            event_callback=event_callback,
        )
        return state

    def dashboard_node(state: dict[str, Any]) -> dict[str, Any]:
        logger = logging.getLogger(__name__)
        _emit(settings, run_id, "DashboardAgent", "running", "Dashboard Agent started", event_callback=event_callback)
        dashboard_start = time.perf_counter()
        dashboard_spec = build_dashboard_spec(
            state.get("metric_defs", []),
            state.get("profiling_stats", {}),
        )
        dashboard_title = (dashboard_spec.get("title") or "").strip()
        if not dashboard_title:
            domain_label = str(state.get("domain_id") or "Auto").replace("_", " ").replace("-", " ").strip()
            dashboard_title = f"{domain_label.title()} Dashboard" if domain_label else "Auto Dashboard"
        dashboard_spec["title"] = dashboard_title
        dashboard_spec["dashboard_title"] = dashboard_title
        charts_spec = state.get("chart_plan") or dashboard_spec.get("charts", [])
        logger.info(
            "agentic.dashboard.input | run_id=%s charts_spec=%s metrics=%s profiling_tables=%s",
            run_id,
            len(charts_spec or []),
            len(state.get("metric_defs") or []),
            len((state.get("profiling_stats") or {}).get("tables") or []),
        )
        dashboard_spec["chart_plan"] = state.get("chart_plan") or []
        dashboard_spec["chart_candidates"] = state.get("chart_candidates") or []
        chart_ids = []
        schema_name = state.get("schema_name") or "public"
        line_single_limit = _resolve_int_setting(
            state,
            "chart_line_single_limit",
            "AGENTIC_CHART_LINE_SINGLE_LIMIT",
            200,
        )
        line_multi_limit = _resolve_int_setting(
            state,
            "chart_line_multi_limit",
            "AGENTIC_CHART_LINE_MULTI_LIMIT",
            500,
        )
        category_limit = _resolve_int_setting(
            state,
            "chart_category_limit",
            "AGENTIC_CHART_CATEGORY_LIMIT",
            50,
        )
        bar_limit = _resolve_int_setting(
            state,
            "chart_bar_limit",
            "AGENTIC_CHART_BAR_LIMIT",
            20,
        )
        pie_limit = _resolve_int_setting(
            state,
            "chart_pie_limit",
            "AGENTIC_CHART_PIE_LIMIT",
            10,
        )
        enriched_charts = []
        profiling_map = {t.get("name"): t for t in (state.get("profiling_stats", {}).get("tables") or [])}
        join_edges = state.get("join_edges") or []
        for chart in charts_spec:
            metric_name = chart.get("metric") or "metric"
            metric_col = chart.get("metric_column")
            table_name = chart.get("table")
            time_col = chart.get("time_column")
            category_col = chart.get("category_column")
            chart_title = chart.get("title")
            if not chart_title:
                if chart.get("intent") == "trend":
                    chart_title = f"{metric_name} Trend Over {time_col or 'Time'}"
                elif chart.get("intent") in {"breakdown", "join_breakdown"}:
                    chart_title = f"{metric_name} by {category_col or 'Category'}"
                elif chart.get("intent") == "share":
                    chart_title = f"{category_col or 'Category'} Share of {metric_name}"
                elif chart.get("intent") == "multi_series":
                    chart_title = f"{metric_name} Trend by {category_col or 'Category'}"
                else:
                    chart_title = f"{metric_name} {chart.get('type') or 'Overview'}"
            chart["title"] = chart_title

            if table_name:
                fact_table = table_name if table_name.startswith("fact_") else f"fact_{table_name}"
                table_ref = f"{schema_name}.{fact_table}"
            else:
                fact_table = None
                table_ref = None

            chart_type = chart.get("type") or "bar"
            sql = None
            params: list[Any] = []
            dimensions: list[str] = []
            rows: list[dict] = []

            metric_expr = chart.get("metric_expr")
            metric_name = chart.get("metric") or metric_name
            q_schema = _qident(schema_name)
            q_fact_table = _qident(fact_table) if fact_table else None
            table_alias = "t"
            sql_from = f"{q_schema}.{q_fact_table} {table_alias}" if q_fact_table else None
            logger.info(
                "dashboard.chart.prep | run_id=%s title=%s table=%s fact_table=%s chart_type=%s metric=%s metric_col=%s metric_expr=%s time_col=%s category_col=%s sql_from=%s",
                run_id,
                chart_title,
                table_name,
                fact_table,
                chart_type,
                metric_name,
                metric_col,
                metric_expr,
                time_col,
                category_col,
                sql_from,
            )
            if table_ref and metric_col:
                table_profile = profiling_map.get(table_name) or {}
                eligible_numeric_cols = set(table_profile.get("eligible_numeric_columns") or [])
                if metric_col in eligible_numeric_cols:
                    metric_expr = f"SUM({table_alias}.{_qident(metric_col)})"
                else:
                    logger.warning(
                        "dashboard.chart.metric_blocked | table=%s column=%s reason=invalid_metric_role",
                        table_name,
                        metric_col,
                    )
                    metric_expr = None
            if metric_expr and table_ref:
                metric_expr = _qualify_formula(metric_expr, table_alias, profiling_map.get(table_name) or {})
                logger.info(
                    "dashboard.chart.metric_expr_qualified | run_id=%s title=%s qualified_metric_expr=%s",
                    run_id,
                    chart_title,
                    metric_expr,
                )
            if not metric_expr:
                logger.warning(
                        "dashboard.chart.skip | title=%s reason=invalid_metric metric=%s table=%s",
                        chart_title,
                        metric_col,
                        table_name,
                    )
                enriched_charts.append(
                    {
                        **chart,
                        "skipped": True,
                        "reason": "invalid_metric",
                        "semantic_validation": {
                            "status": "rejected",
                            "reason": "invalid_metric_role_or_expression",
                        },
                    }
                )
                continue

            # choose a better dimension using join metadata if none provided
            if not category_col:
                for edge in join_edges:
                    if edge.get("left_table") == table_name and edge.get("relationship") in {
                        "many_to_one",
                        "one_to_many",
                    }:
                        category_col = edge.get("left_key")
                        break

            if table_ref and metric_expr:
                if chart_type == "line":
                    if time_col:
                        dim_expr = f"date_trunc('month', {table_alias}.{_qident(time_col)})"
                        dim_alias = "period"
                        if category_col:
                            cat_alias = "category"
                            sql = (
                                f"SELECT {dim_expr} AS {dim_alias}, "
                                f"{table_alias}.{_qident(category_col)} AS {cat_alias}, "
                                f"{metric_expr} AS \"{metric_name}\" "
                                f"FROM {sql_from} "
                                f"GROUP BY {dim_alias}, {cat_alias} "
                                f"ORDER BY {dim_alias} ASC "
                                f"LIMIT {line_multi_limit}"
                            )
                            dimensions = [dim_alias, cat_alias]
                        else:
                            sql = (
                                f"SELECT {dim_expr} AS {dim_alias}, "
                                f"{metric_expr} AS \"{metric_name}\" "
                                f"FROM {sql_from} "
                                f"GROUP BY {dim_alias} "
                                f"ORDER BY {dim_alias} ASC "
                                f"LIMIT {line_single_limit}"
                            )
                            dimensions = [dim_alias]
                    elif category_col:
                        dim_alias = "category"
                        sql = (
                            f"SELECT {table_alias}.{_qident(category_col)} AS {dim_alias}, "
                            f"{metric_expr} AS \"{metric_name}\" "
                            f"FROM {sql_from} "
                            f"GROUP BY {dim_alias} "
                            f"ORDER BY \"{metric_name}\" DESC "
                            f"LIMIT {category_limit}"
                        )
                        dimensions = [dim_alias]
                elif chart_type in {"bar", "pie"}:
                    dim_col = category_col or time_col
                    if dim_col:
                        dim_alias = "category"
                        limit = bar_limit if chart_type == "bar" else pie_limit
                        sql = (
                            f"SELECT {table_alias}.{_qident(dim_col)} AS {dim_alias}, "
                            f"{metric_expr} AS \"{metric_name}\" "
                            f"FROM {sql_from} "
                            f"GROUP BY {dim_alias} "
                            f"ORDER BY \"{metric_name}\" DESC "
                            f"LIMIT {limit}"
                        )
                        dimensions = [dim_alias]
                if not sql:
                    # Fallback for valid metrics when no chart dimension is available.
                    sql = (
                        f"SELECT {metric_expr} AS \"{metric_name}\" "
                        f"FROM {sql_from}"
                    )
                    dimensions = []
                    logger.info(
                        "dashboard.chart.sql_fallback | run_id=%s title=%s sql=%s",
                        run_id,
                        chart_title,
                        sql,
                    )
            if not sql:
                logger.warning(
                    "dashboard.chart.sql_missing | run_id=%s title=%s table=%s chart_type=%s table_ref=%s metric_expr=%s time_col=%s category_col=%s",
                    run_id,
                    chart_title,
                    table_name,
                    chart_type,
                    table_ref,
                    metric_expr,
                    time_col,
                    category_col,
                )

            if sql:
                try:
                    rows = run_query(settings, sql, params)
                    logger.info(
                        "dashboard.chart.sql_ok | title=%s rows=%s",
                        chart_title,
                        len(rows),
                    )
                except Exception as exc:
                    logger.exception(
                        "dashboard.chart.sql_failed | title=%s sql=%s params=%s",
                        chart_title,
                        sql,
                        params,
                    )
                    rows = []
            logger.info(
                "dashboard.chart | title=%s type=%s table=%s sql=%s rows=%s",
                chart_title,
                chart_type,
                table_ref,
                sql,
                len(rows),
            )

            chart_id = create_chart_request(
                settings,
                state.get("tenant_id") or "",
                state.get("domain_id"),
                question=chart_title,
                query_payload={
                    "metrics": [metric_name],
                    "dimensions": dimensions,
                    "chart": chart_type,
                    "chart_title": chart_title,
                    "dashboard_title": dashboard_title,
                    "metric_intent": chart.get("metric_intent"),
                    "table": table_name,
                },
                sql=sql,
                params=params,
                rows_json=rows,
            ).get("chart_id")
            logger.info(
                "dashboard.chart.request_created | run_id=%s title=%s chart_id=%s sql_is_null=%s rows=%s",
                run_id,
                chart_title,
                chart_id,
                sql is None,
                len(rows),
            )
            if chart_id:
                chart_ids.append(chart_id)
                payload = build_chart_payload(chart_type, rows, metric_name, dimensions or ["category"])
                dim_key = dimensions[0] if dimensions else None
                insight = _chart_insight(chart_type, rows, metric_name, dim_key)
                stats = _chart_stats(rows, metric_name)
                narrative = _chart_narrative(rows, metric_name, dim_key)
                update_chart_request(
                    settings,
                    chart_id,
                    status="ready",
                    sql=sql,
                    params=params,
                    rows_json=rows,
                    chart_type=chart_type,
                    chart_payload=payload.get("chart_payload"),
                    chart_data=payload.get("data"),
                )
                logger.info(
                    "dashboard.chart.request_updated | run_id=%s chart_id=%s status=ready sql_is_null=%s rows=%s dims=%s",
                    run_id,
                    chart_id,
                    sql is None,
                    len(rows),
                    dimensions,
                )
                enriched_charts.append(
                    {
                        **chart,
                        "chart_id": chart_id,
                        "chart_type": chart_type,
                        "dimensions": dimensions,
                        "metric_name": metric_name,
                        "sql": sql,
                        "rows_count": len(rows),
                        "insight": insight,
                        "stats": stats,
                        "narrative": narrative,
                        "chart_payload": payload.get("chart_payload"),
                        "chart_data": payload.get("data"),
                        "dashboard_title": dashboard_title,
                        "semantic_validation": {
                            "status": "passed",
                            "reason": "eligible_metric",
                        },
                    }
                )
            else:
                logger.warning(
                    "dashboard.chart.request_missing_id | run_id=%s title=%s sql_is_null=%s",
                    run_id,
                    chart_title,
                    sql is None,
                )
                enriched_charts.append({**chart, "dashboard_title": dashboard_title})

        dashboard_spec["charts"] = enriched_charts
        dashboard_spec["story"] = {
            "title": dashboard_title,
            "cards": [
                {
                    "title": "Trend",
                    "summary": "Track change over time with a KPI trend chart.",
                },
                {
                    "title": "Breakdown",
                    "summary": "Compare categories to identify top contributors.",
                },
                {
                    "title": "Share",
                    "summary": "Visualize distribution across key categories.",
                },
            ],
        }
        dashboard_spec["insights"] = [chart.get("insight") for chart in enriched_charts if chart.get("insight")]
        if state.get("quality_report"):
            dashboard_spec["quality"] = state.get("quality_report")
        state["dashboard_spec"] = dashboard_spec
        null_sql_count = sum(1 for c in enriched_charts if c.get("sql") is None and not c.get("skipped"))
        logger.info(
            "agentic.dashboard.output | run_id=%s charts=%s null_sql_non_skipped=%s chart_ids=%s",
            run_id,
            len(enriched_charts),
            null_sql_count,
            len(chart_ids),
        )
        append_agent_chat_log(
            settings,
            run_id,
            "system",
            f"Dashboard ready: {dashboard_title}",
        )
        fast_mode = os.getenv("AGENTIC_DASHBOARD_FAST_MODE", "false").lower() in {"1", "true", "yes"}
        counts = {"nodes": 0, "edges": 0}
        created_views: list[str] = []
        joined_views: list[dict[str, Any]] = []
        registry_persisted = {"facts": 0, "dimensions": 0, "metrics": 0}
        semantics_persisted: dict[str, Any] = {"glossary_terms": 0, "hierarchies": 0, "semantic_contract_id": None}
        if fast_mode:
            _emit(
                settings,
                run_id,
                "DashboardAgent",
                "running",
                "Dashboard Agent fast mode enabled: skipping semantic graph and view persistence",
                {"fast_mode": True},
                event_callback=event_callback,
            )
            _emit(
                settings,
                run_id,
                "DashboardAgent",
                "running",
                "Dashboard Agent persisting semantic registry entities",
                {},
                event_callback=event_callback,
            )
            t3 = time.perf_counter()
            registry_persisted = _persist_agentic_registry_outputs(
                settings,
                run_id,
                state,
                persist_facts=True,
                persist_dimensions=True,
                persist_metrics=False,
            )
            _emit(
                settings,
                run_id,
                "DashboardAgent",
                "running",
                "Dashboard Agent semantic registry entities persisted",
                {"elapsed_ms": round((time.perf_counter() - t3) * 1000, 1), **registry_persisted},
                event_callback=event_callback,
            )
            _emit(
                settings,
                run_id,
                "DashboardAgent",
                "running",
                "Dashboard Agent persisting semantic context assets",
                {},
                event_callback=event_callback,
            )
            t4 = time.perf_counter()
            semantics_persisted = _persist_agentic_semantic_assets(
                settings,
                run_id,
                state,
                persist_glossary=True,
                persist_hierarchy=True,
                persist_contract=True,
            )
            _emit(
                settings,
                run_id,
                "DashboardAgent",
                "running",
                "Dashboard Agent semantic context assets persisted",
                {"elapsed_ms": round((time.perf_counter() - t4) * 1000, 1), **semantics_persisted},
                event_callback=event_callback,
            )
        else:
            _emit(
                settings,
                run_id,
                "DashboardAgent",
                "running",
                "Dashboard Agent persisting semantic graph",
                {},
                event_callback=event_callback,
            )
            t0 = time.perf_counter()
            counts = persist_semantic_graph(
                settings,
                state.get("domain_id") or "",
                state.get("schema_graph", {}),
                state.get("profiling_stats", {}),
                state.get("join_edges", []),
                state.get("metric_defs", []),
                glossary_terms=state.get("glossary_terms", []),
                hierarchy_hints=state.get("hierarchy_hints", []),
                ontology=state.get("ontology", {}),
                model_classifications=state.get("model_classifications", []),
            )
            _emit(
                settings,
                run_id,
                "DashboardAgent",
                "running",
                "Dashboard Agent semantic graph persisted",
                {"elapsed_ms": round((time.perf_counter() - t0) * 1000, 1), **counts},
                event_callback=event_callback,
            )
            _emit(
                settings,
                run_id,
                "DashboardAgent",
                "running",
                "Dashboard Agent creating registered views",
                {},
                event_callback=event_callback,
            )
            t1 = time.perf_counter()
            created_views = create_views_from_schema(
                settings,
                state.get("tenant_id") or "",
                state.get("domain_id") or "",
                state.get("connection_id") or "",
                state.get("database_name") or "",
                state.get("schema_name") or "public",
                state.get("schema_payload") or {},
            )
            _emit(
                settings,
                run_id,
                "DashboardAgent",
                "running",
                "Dashboard Agent registered views created",
                {"elapsed_ms": round((time.perf_counter() - t1) * 1000, 1), "views": len(created_views)},
                event_callback=event_callback,
            )
            _emit(
                settings,
                run_id,
                "DashboardAgent",
                "running",
                "Dashboard Agent creating joined views",
                {},
                event_callback=event_callback,
            )
            t2 = time.perf_counter()
            joined_views = create_joined_views(
                settings,
                state.get("tenant_id") or "",
                state.get("domain_id") or "",
                state.get("schema_name") or "public",
                state.get("join_edges") or [],
            )
            _emit(
                settings,
                run_id,
                "DashboardAgent",
                "running",
                "Dashboard Agent joined views created",
                {"elapsed_ms": round((time.perf_counter() - t2) * 1000, 1), "joined_views": len(joined_views)},
                event_callback=event_callback,
            )
            _emit(
                settings,
                run_id,
                "DashboardAgent",
                "running",
                "Dashboard Agent persisting semantic registry entities",
                {},
                event_callback=event_callback,
            )
            t3 = time.perf_counter()
            registry_persisted = _persist_agentic_registry_outputs(
                settings,
                run_id,
                state,
                persist_facts=True,
                persist_dimensions=True,
                persist_metrics=False,
            )
            _emit(
                settings,
                run_id,
                "DashboardAgent",
                "running",
                "Dashboard Agent semantic registry entities persisted",
                {"elapsed_ms": round((time.perf_counter() - t3) * 1000, 1), **registry_persisted},
                event_callback=event_callback,
            )
            _emit(
                settings,
                run_id,
                "DashboardAgent",
                "running",
                "Dashboard Agent persisting semantic context assets",
                {},
                event_callback=event_callback,
            )
            t4 = time.perf_counter()
            semantics_persisted = _persist_agentic_semantic_assets(
                settings,
                run_id,
                state,
                persist_glossary=True,
                persist_hierarchy=True,
                persist_contract=True,
            )
            _emit(
                settings,
                run_id,
                "DashboardAgent",
                "running",
                "Dashboard Agent semantic context assets persisted",
                {"elapsed_ms": round((time.perf_counter() - t4) * 1000, 1), **semantics_persisted},
                event_callback=event_callback,
            )
        _emit(
            settings,
            run_id,
            "DashboardAgent",
            "running",
            "Dashboard Agent persisting dashboard spec",
            {},
            event_callback=event_callback,
        )
        dash_id = persist_dashboard_spec(
            settings,
            state.get("tenant_id") or "",
            state.get("domain_id") or "",
            dashboard_spec,
            title=dashboard_title,
        )
        _emit(
            settings,
            run_id,
            "DashboardAgent",
            "completed",
            "Dashboard Agent completed",
            {
                "charts": len(state["dashboard_spec"].get("charts", [])),
                "semantic_nodes": counts.get("nodes"),
                "semantic_edges": counts.get("edges"),
                "dashboard_id": dash_id,
                "dashboard_title": dashboard_title,
                "views": len(created_views),
                "joined_views": joined_views,
                "chart_ids": chart_ids,
                "chart_titles": [c.get("title") for c in enriched_charts if c.get("title")],
                "chart_details": enriched_charts,
                "quality_report": state.get("quality_report"),
                "views_detail": created_views,
                "registry_persisted": registry_persisted,
                "semantics_persisted": semantics_persisted,
                "elapsed_ms": round((time.perf_counter() - dashboard_start) * 1000, 1),
                "fast_mode": fast_mode,
            },
            event_callback=event_callback,
        )
        return state

    graph.add_node("schema", schema_node)
    graph.add_node("profiling", profiling_node)
    graph.add_node("context", context_node)
    graph.add_node("ontology", ontology_node)
    graph.add_node("glossary", glossary_node)
    graph.add_node("join", join_node)
    graph.add_node("metric", metric_node)
    graph.add_node("model", model_node)
    graph.add_node("rollup", rollup_node)
    graph.add_node("chart_planner", chart_planner_node)
    graph.add_node("quality", quality_node)
    graph.add_node("dashboard", dashboard_node)

    graph.set_entry_point("schema")
    # NOTE:
    # We use dict state for the graph. Parallel branches can concurrently write to the same
    # root channel and raise InvalidUpdateError in LangGraph. Keep flow sequential until we
    # migrate to a typed state/reducer-based graph.
    graph.add_edge("schema", "profiling")
    graph.add_edge("profiling", "context")
    graph.add_edge("context", "ontology")
    graph.add_edge("ontology", "glossary")
    graph.add_edge("glossary", "join")
    graph.add_edge("join", "metric")
    graph.add_edge("metric", "model")
    graph.add_edge("model", "rollup")
    graph.add_edge("rollup", "chart_planner")
    graph.add_edge("chart_planner", "quality")
    graph.add_edge("quality", "dashboard")
    graph.add_edge("dashboard", END)

    app = graph.compile()
    result = app.invoke(initial_state)
    pending = _RUN_POSTPROCESS_FUTURES.pop(run_id, [])
    if pending:
        wait(pending)
    logger.info("agentic.workflow.completed | run_id=%s", run_id)
    return result
