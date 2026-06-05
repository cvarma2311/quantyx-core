from __future__ import annotations

from typing import Any, Callable
from concurrent.futures import Future, ThreadPoolExecutor, wait
from html import escape
import json
import os
from pathlib import Path
import re
import time
import traceback
import urllib.request
import uuid

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

AGENTIC_CORRELATION_FLOW_VERSION = "2026-04-03-correlation-debug-v1"
AGENTIC_ANOMALY_FLOW_VERSION = "2026-04-03-anomaly-fallback-debug-v1"

from services.ai.agentic_agents import (
    build_schema_graph,
    enrich_schema_graph_columns,
    profile_tables,
    extract_context,
    validate_metric_candidates,
    propose_ontology,
    propose_joins,
    propose_metrics,
    propose_chart_candidates,
    select_charts,
    classify_models,
    propose_rollups,
    build_dashboard_spec,
    build_story_sections,
    build_dashboard_theme_from_charts,
    deterministic_dashboard_title,
    _chart_discovery_enabled,
    _chart_discovery_only,
    _validate_discovery_sql,
    _enforce_tool_limit,
    _fetch_table_samples,
    _pick_canonical_time_column,
    _hierarchy_breakdown_bindings,
    TableSample,
)
from services.ai.semantic_graph_store import persist_semantic_graph
from services.ai.dashboards_store import (
    create_dashboard as _create_dashboard,
    add_chart as _add_chart_to_dashboard,
)
from services.ai.anomaly_detection import detect_agentic_anomalies, build_anomaly_fallback_exploration
from services.ai.anomaly_detection import rank_high_signal_investigative_areas
from services.ai.anomaly_store import (
    create_anomaly_action,
    create_anomaly_dashboard_link,
    create_anomaly_hypothesis,
    create_anomaly_investigation,
    create_anomaly_record,
    update_anomaly_record,
    update_anomaly_investigation,
)
from services.ai.anomaly_dashboard import build_anomaly_dashboard_spec
from services.ai.correlation_agent import run_correlation_intelligence
from services.ai.correlation_narrate import narrate_correlation_results
from services.ai.correlation_store import create_correlation_run, save_correlation_run_results
from services.ai.correlation_charts import generate_correlation_charts
from services.ai.views import create_views_from_schema, create_joined_views, extract_schema_table_names
from services.ai.charts_store import create_chart_request, update_chart_request
from services.ai.hierarchy_store import ensure_business_hierarchies, list_business_hierarchies
from services.ai.chart_interactions import build_chart_interaction_context_for_creation
from services.ai.charts import build_chart_payload, infer_chart_type, build_chart_inference, build_discovery_chart_payload
from services.ai.dashboard_refresh_store import (
    create_dashboard_refresh_run,
    update_dashboard_refresh_status,
    upsert_dashboard_insights_artifact,
)
from services.ai.dashboard_insights import render_summary_html, render_inference_html
from services.ai.db import ScopedConnection, run_query, execute_non_query
from services.ai.quality_gate import evaluate_quality_report
from services.ai.metrics_registry import upsert_metric
from services.ai.onboarding.models_registry import upsert_fact, upsert_dimension
from services.ai.semantic_contracts import store_semantic_contract
from services.ai.workspace_store import create_workspace_message, get_workspace_memory, upsert_workspace_memory
from services.ai.semantic_layer.pack_loader import load_pack
from services.ai.agentic_artifacts_registry import (
    persist_schema_graph_artifact,
    persist_table_profile_artifact,
    replace_join_registry,
    replace_model_registry,
)
from services.ai.data_quality_orchestrator import is_data_quality_workflow, run_data_quality_agentic_workflow
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
_ANOMALY_PROMPTS_DIR = Path(__file__).parent / "prompts" / "anomaly_investigation"
_DASHBOARD_PROMPTS_DIR = Path(__file__).parent / "prompts" / "dashboard_composition"


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


def _load_anomaly_prompt(name: str) -> str:
    return (_ANOMALY_PROMPTS_DIR / name).read_text(encoding="utf-8")


def _load_dashboard_prompt(name: str) -> str:
    return (_DASHBOARD_PROMPTS_DIR / name).read_text(encoding="utf-8")


def _anomaly_llm_enabled(settings) -> bool:
    mode = os.getenv("AGENTIC_ANOMALY_LLM_MODE", "auto").lower()
    if mode in {"off", "false", "0"}:
        return False
    if mode in {"on", "true", "1"}:
        return bool(getattr(settings, "openai_api_key", None))
    return bool(getattr(settings, "openai_api_key", None))


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() not in {"0", "false", "no", "off"}


def _env_int(name: str, default: int, *, minimum: int | None = None) -> int:
    try:
        value = int(str(os.getenv(name, default)).strip())
    except Exception:
        value = int(default)
    if minimum is not None:
        value = max(minimum, value)
    return value


def _env_float(name: str, default: float, *, minimum: float | None = None) -> float:
    try:
        value = float(str(os.getenv(name, default)).strip())
    except Exception:
        value = float(default)
    if minimum is not None:
        value = max(minimum, value)
    return value


def _llm_json_response(
    settings,
    *,
    system_prompt: str,
    user_payload: dict[str, Any],
    model_env_key: str,
    timeout_env_key: str,
) -> dict[str, Any] | None:
    if not _anomaly_llm_enabled(settings):
        return None
    model = os.getenv(model_env_key, getattr(settings, "openai_model", "gpt-4o-mini"))
    timeout_sec = int(os.getenv(timeout_env_key, "45"))
    request = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(
            {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": json.dumps(user_payload, default=str)},
                ],
                "temperature": 0.1,
                "response_format": {"type": "json_object"},
            },
            default=str,
        ).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {settings.openai_api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_sec) as response:
            body = json.loads(response.read().decode("utf-8"))
        return json.loads(body["choices"][0]["message"]["content"])
    except Exception:
        logging.getLogger(__name__).warning("agentic.anomaly_llm_failed", exc_info=True)
        return None


# ── Phase 47: LLM Chart Discovery ────────────────────────────────────────────

_QUERY_DATA_TOOL_DEF = {
    "type": "function",
    "function": {
        "name": "query_data",
        "description": (
            "Execute a read-only SQL SELECT query against the database and return up to 50 rows. "
            "Use this to explore data before proposing charts — check date ranges, distinct values, "
            "sample records, and counts. Always include LIMIT in your SQL; the system enforces "
            "LIMIT 50 regardless of what you write."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "sql": {
                    "type": "string",
                    "description": (
                        "A valid PostgreSQL SELECT statement. "
                        "Must not contain INSERT, UPDATE, DELETE, DROP, or any DDL."
                    ),
                },
                "reason": {
                    "type": "string",
                    "description": "Brief explanation of what you are exploring and why.",
                },
            },
            "required": ["sql", "reason"],
        },
    },
}


def _build_discovery_system_prompt(chart_limit: int, max_tool_calls: int) -> str:
    return (
        f"You are a senior data analyst building an operational intelligence dashboard.\n\n"
        f"You have access to a tool `query_data` — use it to explore the data before proposing charts. "
        f"Call it up to {max_tool_calls} times. Each call returns up to 50 rows.\n\n"
        f"SCOPE RULES (strictly enforced by the system — violations are blocked automatically):\n"
        f"- ONLY query tables listed in the 'tables' section of the provided context.\n"
        f"- Tables are already schema-qualified (e.g. \"public\".\"alerts\") — always use that exact form.\n"
        f"- NEVER query information_schema, pg_catalog, or any system tables.\n"
        f"- If a tool call returns an error saying a table is not in scope, ACCEPT that restriction immediately.\n"
        f"  Do NOT retry the same table, do NOT try alternate names for it. Move on to a different query\n"
        f"  using only the tables that are in scope.\n\n"
        f"BUSINESS CONTEXT RULES (mandatory — read the 'business_context' section carefully):\n"
        f"- The business context defines KEY DIMENSIONS with explicit CASE WHEN column encodings.\n"
        f"  You MUST apply these encodings in every chart SQL — never plot raw column values.\n"
        f"- The business context defines KEY METRICS with exact filter conditions (WHERE clauses).\n"
        f"  You MUST apply those filters exactly as specified. Do not invent or relax them.\n"
        f"- The business context defines ANALYTICAL ANGLES — use these as your chart topics.\n"
        f"  Derive your chart ideas from these angles, not from generic exploration.\n\n"
        f"CHART PROPOSAL RULES:\n"
        f"1. Propose up to {chart_limit} charts as a JSON object: {{\"charts\": [...], \"rationale\": \"...\"}}\n"
        f"2. Each chart must have: title, chart_type, metric_name, sql, x_axis, y_axis, series_by (or null).\n"
        f"3. chart_type must be one of: line | bar | stacked_bar | pie | area\n"
        f"4. sql must be a single valid PostgreSQL SELECT statement using only the scoped tables.\n"
        f"5. DATES MUST BE DYNAMIC — always use CURRENT_DATE, CURRENT_DATE - INTERVAL '30 days', "
        f"DATE_TRUNC('month', ...) etc. NEVER hardcode specific dates.\n"
        f"6. Apply all business filters and CASE WHEN encodings from the business context inline in SQL.\n"
        f"7. ORDER BY time column ASC for time-series charts.\n"
        f"8. For multi-series (series_by not null): the series_by column must appear in SELECT.\n"
        f"9. x_axis and y_axis must match exact column aliases in your SELECT clause.\n"
        f"10. Always include LIMIT 500 at the end of chart SQL.\n\n"
        f"EXPLORATION GUIDANCE:\n"
        f"- Check data date ranges and verify key column values align with the business context definitions.\n"
        f"- Do NOT explore tables that are not in scope — focus all tool calls on the provided tables.\n"
        f"- When proposing charts, return ONLY valid JSON — no markdown, no code fences."
    )


def _extract_business_context_block(context_text: str | None) -> str:
    """
    Pull the structured business context block out of context_text.
    Looks for sections starting with KEY DIMENSIONS, KEY METRICS, ANALYTICAL ANGLES,
    BUSINESS CONTEXT, or DOMAIN OVERVIEW. Returns the matched block (up to 4000 chars).
    Falls back to the first 3000 chars of context_text if none found.
    """
    if not context_text:
        return ""
    markers = ["KEY DIMENSIONS", "KEY METRICS", "ANALYTICAL ANGLES", "BUSINESS CONTEXT", "DOMAIN OVERVIEW"]
    earliest = len(context_text)
    for marker in markers:
        idx = context_text.upper().find(marker)
        if 0 <= idx < earliest:
            earliest = idx
    if earliest < len(context_text):
        return context_text[earliest:earliest + 4000].strip()
    return context_text[:3000].strip()


def _build_discovery_user_payload(
    domain_id: str | None,
    context_text: str | None,
    profiling: dict,
    table_samples: dict[str, "TableSample"],
    schema: str = "public",
) -> dict:
    tables_payload = []
    for table_info in profiling.get("tables") or []:
        tname = str(table_info.get("name") or "").strip()
        if not tname:
            continue
        sample = table_samples.get(tname)
        col_schema = [
            {"name": c.get("name"), "type": c.get("type") or c.get("data_type")}
            for c in (table_info.get("columns") or [])
            if c.get("name")
        ]
        tables_payload.append({
            "name": tname,
            "qualified_name": f'"{schema}"."{tname}"',
            "schema": col_schema,
            "sample_rows": (sample.rows[:20] if sample else []),
            "distinct_values": (sample.distinct_values if sample else {}),
            "row_count_estimate": (sample.row_count_estimate if sample else 0),
        })
    business_ctx = _extract_business_context_block(context_text)
    return {
        "domain_id": domain_id or "",
        "db_schema": schema,
        "business_context": business_ctx,
        "tables": tables_payload,
        "instructions": (
            f"CRITICAL RULES:\n"
            f"1. Only query tables listed in 'tables' above. Never query any other table.\n"
            f"2. Always use the qualified_name (e.g. \"{schema}\".\"table_name\") in all SQL.\n"
            f"3. The 'business_context' section defines mandatory column encodings (CASE WHEN), "
            f"metric filters, and chart topics. Apply them exactly in every chart SQL you propose."
        ),
    }


def _qualify_table_refs(sql: str, schema: str, known_tables: list[str]) -> str:
    """Rewrite unqualified known table references to schema.table form.
    Skips tables already preceded by '.' or '"' (already schema-qualified).
    """
    for table in known_tables:
        # Negative lookbehind for both '.' and '"' to avoid double-qualifying
        # e.g. "public"."alerts" or public.alerts must not be touched.
        sql = re.sub(
            rf'(?<![."])(\b{re.escape(table)}\b)',
            f'"{schema}"."{table}"',
            sql,
            flags=re.IGNORECASE,
        )
    return sql


_FROM_JOIN_TABLE_RE = re.compile(
    r'\b(?:FROM|JOIN)\s+(?:"[^"]+"\s*\.\s*)?(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_]*))',
    re.IGNORECASE,
)


def _extract_sql_tables(sql: str) -> list[str]:
    """Return all table names referenced in FROM / JOIN clauses."""
    return [m.group(1) or m.group(2) for m in _FROM_JOIN_TABLE_RE.finditer(sql)]


def _run_tool_call(sql: str, settings, schema: str, known_tables: list[str] | None = None, scoped_conn=None) -> list[dict]:
    """Execute a validated, LIMIT-enforced LLM tool-call query. Returns rows as dicts."""
    limit = int(os.getenv("CHART_DISCOVERY_TOOL_ROW_LIMIT", "50"))
    # Reject queries that reference tables outside the profiled scope
    if known_tables:
        allowed = {t.lower() for t in known_tables}
        for ref in _extract_sql_tables(sql):
            if ref.lower() not in allowed:
                return [{"_error": f"Table '{ref}' is not in the scoped table list. Only query: {known_tables}"}]
    # Qualify any unscoped table references before validation
    if known_tables and schema:
        sql = _qualify_table_refs(sql, schema, known_tables)
    enforced_sql = _enforce_tool_limit(sql, limit)
    valid, err = _validate_discovery_sql(enforced_sql)
    if not valid:
        return [{"_error": err}]
    try:
        rows = run_query(settings, enforced_sql, [], scoped_conn=scoped_conn)
        return [dict(r) for r in (rows or [])]
    except Exception as exc:
        return [{"_error": str(exc)[:300]}]


def _parse_discovery_charts(content: str) -> list[dict]:
    """Extract the charts list from LLM response content (JSON or markdown-wrapped)."""
    # Strip markdown code fences if present
    cleaned = re.sub(r"```(?:json)?\s*", "", content).strip().rstrip("`").strip()
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            charts = parsed.get("charts") or []
            if isinstance(charts, list):
                return [c for c in charts if isinstance(c, dict)]
        if isinstance(parsed, list):
            return [c for c in parsed if isinstance(c, dict)]
    except Exception as exc:
        logger.warning("chart_discovery.parse_failed | err=%s content_head=%s", exc, content[:200])
    return []


def _llm_chart_discovery(
    settings,
    *,
    domain_id: str | None,
    context_text: str | None,
    profiling: dict,
    table_samples: dict[str, "TableSample"],
    schema: str = "public",
    scoped_conn=None,
) -> tuple[list[dict], dict]:
    """
    Agentic tool-calling loop:
    - LLM receives static context (schema + sample rows + distinct values)
    - LLM may call query_data tool up to CHART_DISCOVERY_TOOL_CALL_LIMIT times
    - App enforces LIMIT 50 on every tool call
    - LLM returns final JSON chart specs
    Returns (chart_specs, diagnostics).
    """
    logger = logging.getLogger(__name__)
    if not _chart_discovery_enabled():
        return [], {}

    model = os.getenv("CHART_DISCOVERY_MODEL", "gpt-4o-mini")
    timeout = int(os.getenv("CHART_DISCOVERY_TIMEOUT_SEC", "10000"))
    max_tool_calls = int(os.getenv("CHART_DISCOVERY_TOOL_CALL_LIMIT", "6"))
    chart_limit = int(os.getenv("CHART_DISCOVERY_CHART_LIMIT", "10"))

    known_tables = [
        str(t.get("name") or "").strip()
        for t in (profiling.get("tables") or [])
        if t.get("name")
    ]

    messages: list[dict] = [
        {"role": "system", "content": _build_discovery_system_prompt(chart_limit, max_tool_calls)},
        {"role": "user", "content": json.dumps(
            _build_discovery_user_payload(domain_id, context_text, profiling, table_samples, schema=schema),
            default=str,
        )},
    ]
    tools = [_QUERY_DATA_TOOL_DEF]
    tool_calls_made = 0
    diagnostics: dict[str, Any] = {"tool_calls": [], "model": model, "proposed": 0}

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        remaining = max(5, int(deadline - time.monotonic()))
        payload = {
            "model": model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "temperature": 0.2,
        }
        request = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=json.dumps(payload, default=str).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {settings.openai_api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=remaining) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            logger.warning("chart_discovery.llm_request_failed | err=%s", exc)
            diagnostics["error"] = str(exc)[:200]
            break

        choice = body["choices"][0]
        message = choice["message"]
        finish_reason = choice.get("finish_reason", "")

        # LLM wants to call a tool
        if finish_reason == "tool_calls":
            tool_calls_in_msg = message.get("tool_calls") or []
            if not tool_calls_in_msg:
                break

            if tool_calls_made >= max_tool_calls:
                # Tool call limit hit — LLM still wants to explore but we must stop.
                # Append a no-tool follow-up so the LLM produces its final JSON output.
                messages.append({
                    "role": "assistant",
                    "content": message.get("content"),
                    "tool_calls": tool_calls_in_msg,
                })
                # Provide dummy tool result so the conversation stays valid
                for tool_call in tool_calls_in_msg:
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call["id"],
                        "content": json.dumps([{"_info": "Tool call limit reached. Please output your final chart specs now."}]),
                    })
                messages.append({
                    "role": "user",
                    "content": (
                        "You have reached the maximum number of tool calls. "
                        "Based on all the data you have gathered so far, please output your final chart "
                        "specifications now as a JSON object: {\"charts\": [...], \"rationale\": \"...\"}. "
                        "Do not call any more tools."
                    ),
                })
                # Final call with no tools
                remaining = max(5, int(deadline - time.monotonic()))
                final_payload = {
                    "model": model,
                    "messages": messages,
                    "temperature": 0.2,
                }
                final_request = urllib.request.Request(
                    "https://api.openai.com/v1/chat/completions",
                    data=json.dumps(final_payload, default=str).encode("utf-8"),
                    headers={
                        "Authorization": f"Bearer {settings.openai_api_key}",
                        "Content-Type": "application/json",
                    },
                    method="POST",
                )
                try:
                    with urllib.request.urlopen(final_request, timeout=remaining) as resp:
                        final_body = json.loads(resp.read().decode("utf-8"))
                    content = str(final_body["choices"][0]["message"].get("content") or "")
                except Exception as exc:
                    logger.warning("chart_discovery.final_call_failed | err=%s", exc)
                    content = ""
                charts = _parse_discovery_charts(content)
                diagnostics["proposed"] = len(charts)
                diagnostics["tool_call_limit_hit"] = True
                logger.info(
                    "chart_discovery.complete_after_limit | model=%s tool_calls=%s proposed=%s",
                    model, tool_calls_made, len(charts),
                )
                return charts, diagnostics

            # Append assistant message with tool_calls
            messages.append({
                "role": "assistant",
                "content": message.get("content"),
                "tool_calls": tool_calls_in_msg,
            })
            for tool_call in tool_calls_in_msg:
                if tool_calls_made >= max_tool_calls:
                    break
                try:
                    args = json.loads(tool_call["function"]["arguments"])
                except Exception:
                    args = {}
                sql = str(args.get("sql") or "")
                reason = str(args.get("reason") or "")
                rows = _run_tool_call(sql, settings, schema=schema, known_tables=known_tables, scoped_conn=scoped_conn)
                has_error = len(rows) == 1 and "_error" in rows[0]
                diagnostics["tool_calls"].append({
                    "sql": sql,
                    "reason": reason,
                    "rows_returned": len(rows),
                    "error": rows[0].get("_error") if has_error else None,
                })
                tool_calls_made += 1
                logger.info(
                    "chart_discovery.tool_call | #%s reason=%r sql=%r rows=%s error=%s",
                    tool_calls_made, reason, sql[:200], len(rows),
                    rows[0].get("_error") if has_error else None,
                )
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call["id"],
                    "content": json.dumps(rows, default=str),
                })
            continue

        # LLM has produced final chart specs (finish_reason == "stop")
        content = str(message.get("content") or "")
        charts = _parse_discovery_charts(content)
        diagnostics["proposed"] = len(charts)
        logger.info(
            "chart_discovery.complete | model=%s tool_calls=%s proposed=%s",
            model, tool_calls_made, len(charts),
        )
        return charts, diagnostics

    diagnostics["timeout"] = True
    return [], diagnostics


def _execute_discovery_charts(
    settings,
    specs: list[dict],
    schema: str,
    tenant_id: str | None,
    domain_id: str | None,
    run_id: str | None,
    dashboard_id: str | None,
    scoped_conn=None,
) -> tuple[list[str], list[str]]:
    """
    Validate → EXPLAIN dry-run → Execute → Store each LLM-proposed chart spec.
    Returns (chart_ids, titles) for successful charts.
    """
    logger = logging.getLogger(__name__)
    chart_ids: list[str] = []
    titles: list[str] = []
    _HARDCODED_DATE_RE = re.compile(r"'\d{4}-\d{2}-\d{2}'")

    for spec in specs:
        title = str(spec.get("title") or "Discovery Chart").strip()
        sql_raw = str(spec.get("sql") or "").strip()
        chart_type = str(spec.get("chart_type") or "bar").lower()
        x_axis = spec.get("x_axis")
        y_axis = spec.get("y_axis")
        metric_name = str(spec.get("metric_name") or y_axis or "value").strip()

        # 1. Validate SQL is SELECT-only
        valid, err = _validate_discovery_sql(sql_raw)
        if not valid:
            logger.warning("chart_discovery.spec_rejected | title=%s reason=%s", title, err)
            continue

        # Append LIMIT 500 for chart storage
        sql = _enforce_tool_limit(sql_raw, limit=500)

        # 2. Warn on hardcoded dates (don't reject)
        if _HARDCODED_DATE_RE.search(sql):
            logger.warning("chart_discovery.hardcoded_date | title=%s", title)

        # 3. EXPLAIN dry-run
        try:
            run_query(settings, f"EXPLAIN {sql}", [], scoped_conn=scoped_conn)
        except Exception as exc:
            logger.warning("chart_discovery.explain_failed | title=%s err=%s", title, exc)
            continue

        # 4. Execute
        try:
            rows = run_query(settings, sql, [], scoped_conn=scoped_conn)
            rows = [dict(r) for r in (rows or [])]
        except Exception as exc:
            logger.warning("chart_discovery.exec_failed | title=%s err=%s", title, exc)
            continue

        # 5. Skip empty results
        if not rows:
            logger.info("chart_discovery.empty_result | title=%s", title)
            continue

        # 6. Column presence check
        row_keys = set(rows[0].keys())
        if x_axis and x_axis not in row_keys:
            logger.warning("chart_discovery.missing_x_axis | title=%s x_axis=%s cols=%s", title, x_axis, row_keys)
            x_axis = next(iter(row_keys), x_axis)
        if y_axis and y_axis not in row_keys:
            logger.warning("chart_discovery.missing_y_axis | title=%s y_axis=%s cols=%s", title, y_axis, row_keys)
            y_axis = next((k for k in row_keys if k != x_axis), y_axis)

        # 7. Build amCharts payload
        try:
            payload = build_discovery_chart_payload(spec, rows)
        except Exception as exc:
            logger.warning("chart_discovery.payload_failed | title=%s err=%s", title, exc)
            payload = {"chart_type": chart_type, "chart_payload": None, "data": []}

        # 8. Run inference
        try:
            from services.ai.charts import build_chart_inference
            inference = build_chart_inference(
                settings=settings,
                chart_type=chart_type,
                metric_name=metric_name,
                rows=rows,
                dimensions=[x_axis] if x_axis else [],
                title=title,
            )
        except Exception:
            inference = {"insight_text": None, "narrative_text": None, "stats_json": None}

        # 9. Store chart request
        try:
            chart_id = create_chart_request(
                settings,
                tenant_id=tenant_id,
                domain_id=domain_id,
                run_id=run_id,
                question=title,
                metric_name=metric_name,
                chart_type=chart_type,
                source="llm_discovery",
            )
            if chart_id:
                update_chart_request(
                    settings,
                    chart_id,
                    status="ready",
                    sql=sql,
                    params=[],
                    rows_json=rows,
                    chart_type=chart_type,
                    chart_payload=payload.get("chart_payload"),
                    chart_data=payload.get("data"),
                    insight_text=inference.get("insight_text"),
                    narrative_text=inference.get("narrative_text"),
                    stats_json=inference.get("stats_json"),
                )
                if dashboard_id:
                    try:
                        _add_chart_to_dashboard(settings, dashboard_id=dashboard_id, chart_id=chart_id)
                    except Exception as exc:
                        logger.warning("chart_discovery.dashboard_link_failed | chart_id=%s err=%s", chart_id, exc)
                chart_ids.append(chart_id)
                titles.append(title)
                logger.info("chart_discovery.stored | title=%s chart_id=%s rows=%s", title, chart_id, len(rows))
        except Exception as exc:
            logger.warning("chart_discovery.store_failed | title=%s err=%s", title, exc)

    return chart_ids, titles


def _llm_generate_dashboard_title(
    settings,
    *,
    domain_id: str | None,
    context_text: str | None,
    successful_charts: list[dict[str, Any]],
    dashboard_theme: dict[str, Any],
) -> dict[str, Any] | None:
    if not _dashboard_composition_enabled(settings) or not successful_charts:
        return None
    chart_payload = []
    for chart in successful_charts[:16]:
        chart_payload.append(
            {
                "title": chart.get("title"),
                "table": chart.get("table"),
                "metric": chart.get("metric") or chart.get("metric_name"),
                "primary_role": chart.get("primary_role"),
                "related_roles": chart.get("related_roles") or [],
                "kpi_family": chart.get("kpi_family"),
                "time_grain": chart.get("time_grain"),
                "intent": chart.get("intent"),
            }
        )
    return _llm_json_response(
        settings,
        system_prompt=_load_dashboard_prompt("title.md"),
        user_payload={
            "domain_id": domain_id,
            "context_text": str(context_text or "")[:5000],
            "successful_charts": chart_payload,
            "dashboard_theme": dashboard_theme,
        },
        model_env_key="AGENTIC_DASHBOARD_TITLE_MODEL",
        timeout_env_key="AGENTIC_DASHBOARD_TITLE_TIMEOUT_SEC",
    )


def _llm_review_dashboard_quality(
    settings,
    *,
    domain_id: str | None,
    context_text: str | None,
    dashboard_title: str | None,
    successful_charts: list[dict[str, Any]],
    rejected_charts: list[dict[str, Any]],
    dashboard_theme: dict[str, Any],
    quality_report: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not _dashboard_composition_enabled(settings) or not successful_charts:
        return None
    return _llm_json_response(
        settings,
        system_prompt=_load_dashboard_prompt("quality_review.md"),
        user_payload={
            "domain_id": domain_id,
            "context_text": str(context_text or "")[:5000],
            "dashboard_title": dashboard_title,
            "successful_charts": [
                {
                    "chart_id": chart.get("chart_id"),
                    "title": chart.get("title"),
                    "table": chart.get("table"),
                    "metric": chart.get("metric") or chart.get("metric_name"),
                    "primary_role": chart.get("primary_role"),
                    "related_roles": chart.get("related_roles") or [],
                    "kpi_family": chart.get("kpi_family"),
                    "intent": chart.get("intent"),
                }
                for chart in successful_charts[:16]
            ],
            "rejected_charts": [
                {
                    "title": chart.get("title"),
                    "table": chart.get("table"),
                    "metric": chart.get("metric") or chart.get("metric_name"),
                    "reason": chart.get("reason") or ((chart.get("semantic_validation") or {}).get("reason")),
                }
                for chart in rejected_charts[:12]
            ],
            "dashboard_theme": dashboard_theme,
            "quality_report": quality_report or {},
        },
        model_env_key="AGENTIC_DASHBOARD_TITLE_MODEL",
        timeout_env_key="AGENTIC_DASHBOARD_TITLE_TIMEOUT_SEC",
    )


def _title_mentions_raw_tables(title: str | None, table_names: list[str] | None) -> bool:
    normalized_title = re.sub(r"[^a-z0-9]+", " ", str(title or "").lower()).strip()
    if not normalized_title:
        return False
    for table_name in table_names or []:
        table_label = str(table_name or "").strip().lower()
        if not table_label:
            continue
        for candidate in {
            table_label,
            table_label.replace("_", " "),
            table_label.replace("fact_", "").replace("_", " "),
        }:
            cleaned = re.sub(r"[^a-z0-9]+", " ", candidate).strip()
            if cleaned and cleaned in normalized_title:
                return True
    return False


def _should_skip_anomaly_for_dashboard_quality(quality_report: dict[str, Any] | None) -> bool:
    report = quality_report or {}
    if not isinstance(report, dict) or not report:
        return False
    blocked_patterns = [item for item in (report.get("blocked_patterns") or []) if str(item).strip()]
    if blocked_patterns:
        return True
    score = float(report.get("quality_score") or 0.0)
    if score < 0.65:
        return True
    chart_rejections = [item for item in (report.get("chart_rejections") or []) if isinstance(item, dict)]
    # Use chart_selection total as the denominator, not edges_checked.
    # edges_checked counts join/ontology graph edges (often 2-3 for simple schemas)
    # which made the gate trigger with just 2 rejections even when quality_score=0.9.
    # Block only when the majority of proposed charts were rejected.
    selection_diagnostics = report.get("chart_selection_diagnostics") or {}
    total_proposed = int(selection_diagnostics.get("selected_count") or 0) + len(chart_rejections)
    if total_proposed > 0 and len(chart_rejections) / total_proposed > 0.5:
        return True
    return False


def _llm_review_anomaly_readiness(
    settings,
    *,
    domain_id: str | None,
    context_text: str | None,
    dashboard_spec: dict[str, Any] | None,
    quality_report: dict[str, Any] | None,
    evidence_coverage: dict[str, Any] | None,
    anomaly_candidate_summary: dict[str, Any] | None,
) -> dict[str, Any] | None:
    return _llm_json_response(
        settings,
        system_prompt=_load_anomaly_prompt("readiness_review.md"),
        user_payload={
            "domain_id": domain_id,
            "context_text": str(context_text or "")[:5000],
            "dashboard": {
                "title": (dashboard_spec or {}).get("dashboard_title") or (dashboard_spec or {}).get("title"),
                "dashboard_theme": (dashboard_spec or {}).get("dashboard_theme") or {},
                "table_contributions": (dashboard_spec or {}).get("table_contributions") or [],
                "kpi_family_contributions": (dashboard_spec or {}).get("kpi_family_contributions") or [],
            },
            "quality_report": quality_report or {},
            "evidence_coverage": evidence_coverage or {},
            "anomaly_candidate_summary": anomaly_candidate_summary or {},
        },
        model_env_key="AGENTIC_ANOMALY_READINESS_MODEL",
        timeout_env_key="AGENTIC_ANOMALY_READINESS_TIMEOUT_SEC",
    )


def _llm_plan_anomaly_investigation(
    settings,
    *,
    domain_id: str | None,
    context_text: str | None,
    dashboard_spec: dict[str, Any],
    investigation_summary: dict[str, Any],
    anomalies_payload: list[dict[str, Any]],
    correlation_context: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    system_prompt = _load_anomaly_prompt("plan.md")
    return _llm_json_response(
        settings,
        system_prompt=system_prompt,
        user_payload={
            "domain_id": domain_id,
            "context_text": str(context_text or "")[:8000],
            "dashboard": {
                "title": dashboard_spec.get("dashboard_title") or dashboard_spec.get("title"),
                "charts": [
                    {
                        "title": chart.get("title"),
                        "metric": chart.get("metric"),
                        "intent": chart.get("intent"),
                        "type": chart.get("type"),
                    }
                    for chart in (dashboard_spec.get("charts") or [])[:10]
                ],
                "story": dashboard_spec.get("story") or {},
                "insights": (dashboard_spec.get("insights") or [])[:10],
                "dashboard_theme": dashboard_spec.get("dashboard_theme") or {},
                "table_contributions": dashboard_spec.get("table_contributions") or [],
                "kpi_family_contributions": dashboard_spec.get("kpi_family_contributions") or [],
            },
            "investigation_summary": investigation_summary,
            "anomalies": anomalies_payload,
            "correlation_context": correlation_context or {},
        },
        model_env_key="AGENTIC_ANOMALY_PLAN_MODEL",
        timeout_env_key="AGENTIC_ANOMALY_PLAN_TIMEOUT_SEC",
    )


def _validate_llm_prioritized_areas(
    anomalies_payload: list[dict[str, Any]],
    llm_plan: dict[str, Any] | None,
) -> dict[str, list[dict[str, Any]]]:
    if not llm_plan:
        return {}
    anomaly_lookup = {str(item.get("anomaly_id") or ""): item for item in anomalies_payload if str(item.get("anomaly_id") or "").strip()}
    validated: dict[str, list[dict[str, Any]]] = {}
    for area in [item for item in (llm_plan.get("prioritized_investigative_areas") or []) if isinstance(item, dict)]:
        anomaly_id = str(area.get("anomaly_id") or "").strip()
        dimension = str(area.get("dimension") or "").strip()
        value = area.get("value")
        if not anomaly_id or anomaly_id not in anomaly_lookup or not dimension or value in {None, ""}:
            continue
        candidate = anomaly_lookup[anomaly_id]
        table_name = str(candidate.get("table_name") or "").strip()
        allowed_dimensions = {
            str(item.get("dimension") or "").strip()
            for item in (candidate.get("high_signal_investigative_areas") or [])
            if str(item.get("dimension") or "").strip()
        }
        fallback_rows = []
        for item in (candidate.get("high_signal_investigative_areas") or []):
            if str(item.get("dimension") or "").strip() == dimension:
                fallback_rows = [row for row in (item.get("rows") or []) if isinstance(row, dict)]
                break
        allowed_values = {str(row.get("value")) for row in fallback_rows if row.get("value") is not None}
        if allowed_dimensions and dimension not in allowed_dimensions:
            continue
        if allowed_values and str(value) not in allowed_values:
            continue
        validated.setdefault(anomaly_id, []).append(
            {
                "dimension": dimension,
                "value": value,
                "table_name": table_name,
                "rationale": area.get("rationale"),
                "confidence": area.get("confidence"),
                "selection_source": "llm",
            }
        )
    return validated


def _allowed_fact_tables(profiling_stats: dict[str, Any]) -> set[str]:
    allowed: set[str] = set()
    for table in (profiling_stats.get("tables") or []):
        table_name = str(table.get("name") or "").strip()
        if not table_name:
            continue
        if table.get("eligible_numeric_columns") and table.get("time_columns"):
            allowed.add(table_name)
            allowed.add(f"fact_{table_name}")
    return allowed


def _profiling_table_map(profiling_stats: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(table.get("name") or "").strip().lower(): table
        for table in (profiling_stats.get("tables") or [])
        if str(table.get("name") or "").strip()
    }


def _approved_join_keys(table_profile: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    for item in table_profile.get("candidate_keys") or []:
        column = str(item.get("column") or "").strip().lower()
        uniqueness = float(item.get("uniqueness_ratio") or 0.0)
        if column and uniqueness >= 0.5:
            keys.add(column)
    for column in (table_profile.get("categorical_columns") or []):
        col = str(column or "").strip().lower()
        if col.endswith("_id") or col.endswith("_code") or col in {"sap_id", "plant_id", "location_id"}:
            keys.add(col)
    for column in (table_profile.get("time_columns") or []):
        col = str(column or "").strip().lower()
        if col in {"process_date", "business_date", "event_date", "date"}:
            keys.add(col)
    return keys


def _extract_table_aliases(sql: str) -> dict[str, str]:
    alias_map: dict[str, str] = {}
    pattern = re.compile(
        r"\b(?:from|join)\s+(?:[a-zA-Z_][\w]*\.)?(?P<table>[a-zA-Z_][\w]*)"
        r"(?:\s+(?:as\s+)?(?P<alias>[a-zA-Z_][\w]*))?",
        re.IGNORECASE,
    )
    reserved = {"on", "where", "group", "order", "limit", "left", "right", "inner", "outer", "full", "cross"}
    for match in pattern.finditer(sql):
        table = str(match.group("table") or "").strip().lower()
        alias = str(match.group("alias") or "").strip().lower()
        alias_map[table] = table
        if alias and alias not in reserved:
            alias_map[alias] = table
    return alias_map


def _validate_join_safety(sql: str, profiling_stats: dict[str, Any], referenced_tables: set[str]) -> tuple[bool, str]:
    lower = sql.lower()
    if " cross join " in f" {lower} ":
        return False, "cross_join_not_allowed"
    from_match = re.search(r"\bfrom\b(?P<body>.+?)(?:\bwhere\b|\bgroup\b|\border\b|\blimit\b|$)", lower, re.IGNORECASE | re.DOTALL)
    if from_match and "," in from_match.group("body"):
        return False, "comma_join_not_allowed"
    if len(referenced_tables) <= 1:
        return True, ""
    if len(referenced_tables) > 2:
        return False, "too_many_joined_tables"

    alias_map = _extract_table_aliases(sql)
    profiling_map = _profiling_table_map(profiling_stats)
    join_patterns = re.findall(
        r"\bjoin\s+(?:[a-zA-Z_][\w]*\.)?(?P<table>[a-zA-Z_][\w]*)"
        r"(?:\s+(?:as\s+)?(?P<alias>[a-zA-Z_][\w]*))?\s+on\s+(?P<condition>.+?)(?=\b(?:join|where|group|order|limit)\b|$)",
        sql,
        re.IGNORECASE | re.DOTALL,
    )
    if not join_patterns:
        return False, "missing_explicit_join_condition"
    for table_name, alias, condition in join_patterns:
        table = str(table_name or "").strip().lower()
        alias_key = str(alias or table).strip().lower() or table
        if table not in profiling_map:
            return False, "join_references_non_profiled_table"
        conditions = re.findall(
            r"([a-zA-Z_][\w]*)\.([a-zA-Z_][\w]*)\s*=\s*([a-zA-Z_][\w]*)\.([a-zA-Z_][\w]*)",
            str(condition or ""),
            re.IGNORECASE,
        )
        if not conditions:
            return False, "only_equality_joins_allowed"
        approved = False
        for left_alias, left_col, right_alias, right_col in conditions:
            left_table = alias_map.get(str(left_alias).lower())
            right_table = alias_map.get(str(right_alias).lower())
            if not left_table or not right_table:
                continue
            left_keys = _approved_join_keys(profiling_map.get(left_table, {}))
            right_keys = _approved_join_keys(profiling_map.get(right_table, {}))
            left_name = str(left_col).strip().lower()
            right_name = str(right_col).strip().lower()
            if left_name == right_name and left_name in (left_keys & right_keys):
                approved = True
                break
        if not approved:
            return False, f"join_keys_not_approved:{table}:{alias_key}"
    return True, ""


def _validate_select_query(sql: str, allowed_tables: set[str], profiling_stats: dict[str, Any]) -> tuple[bool, str]:
    text = str(sql or "").strip().rstrip(";")
    lower = text.lower()
    if not text:
        return False, "empty_query"
    if ";" in text:
        return False, "multiple_statements_not_allowed"
    if not (lower.startswith("select") or lower.startswith("with")):
        return False, "only_select_queries_allowed"
    blocked = [" insert ", " update ", " delete ", " drop ", " alter ", " create ", " truncate ", " grant ", " revoke "]
    padded = f" {lower} "
    if any(token in padded for token in blocked):
        return False, "mutation_sql_not_allowed"
    referenced = set(re.findall(r"(?:from|join)\s+(?:[a-zA-Z_][\w]*\.)?([a-zA-Z_][\w]*)", lower))
    if not referenced:
        return False, "no_fact_table_references_found"
    if any(table not in {t.lower() for t in allowed_tables} for table in referenced):
        return False, "query_references_non_allowed_table"
    joins_ok, join_reason = _validate_join_safety(text, profiling_stats, referenced)
    if not joins_ok:
        return False, join_reason
    return True, text


def _execute_llm_evidence_queries(
    settings,
    *,
    schema_name: str,
    profiling_stats: dict[str, Any],
    evidence_queries: list[dict[str, Any]],
    max_queries: int = 5,
    row_limit: int = 200,
    scoped_conn: ScopedConnection | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    allowed_tables = _allowed_fact_tables(profiling_stats)
    executed: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    max_queries = max(int(max_queries), 0)
    row_limit = max(int(row_limit), 1)
    for index, item in enumerate(evidence_queries):
        if not isinstance(item, dict):
            continue
        query_id = str(item.get("query_id") or f"query_{len(executed) + len(rejected) + 1}")
        if index >= max_queries:
            rejected.append({"query_id": query_id, "title": item.get("title"), "reason": "max_query_limit_exceeded"})
            continue
        sql = str(item.get("sql") or "").strip()
        valid, reason_or_sql = _validate_select_query(sql, allowed_tables, profiling_stats)
        if not valid:
            rejected.append({"query_id": query_id, "title": item.get("title"), "reason": reason_or_sql})
            continue
        safe_sql = reason_or_sql.rstrip(";")
        if " limit " not in safe_sql.lower():
            safe_sql = f"{safe_sql} LIMIT {int(row_limit)}"
        try:
            rows = run_query(settings, safe_sql, [], scoped_conn=scoped_conn)
            executed.append(
                {
                    "query_id": query_id,
                    "title": item.get("title"),
                    "reason": item.get("reason"),
                    "sql": safe_sql,
                    "row_count": len(rows),
                    "rows": rows[: min(len(rows), min(row_limit, 50))],
                }
            )
        except Exception as exc:
            rejected.append({"query_id": query_id, "title": item.get("title"), "reason": str(exc)})
    return executed, rejected


def _llm_summarize_anomaly_investigation(
    settings,
    *,
    domain_id: str | None,
    context_text: str | None,
    dashboard_spec: dict[str, Any],
    investigation_summary: dict[str, Any],
    anomalies_payload: list[dict[str, Any]],
    executed_queries: list[dict[str, Any]],
    rejected_queries: list[dict[str, Any]],
    correlation_context: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    system_prompt = _load_anomaly_prompt("synthesize.md")
    return _llm_json_response(
        settings,
        system_prompt=system_prompt,
        user_payload={
            "domain_id": domain_id,
            "context_text": str(context_text or "")[:8000],
            "dashboard": {
                "title": dashboard_spec.get("dashboard_title") or dashboard_spec.get("title"),
                "story": dashboard_spec.get("story") or {},
                "insights": (dashboard_spec.get("insights") or [])[:10],
                "dashboard_theme": dashboard_spec.get("dashboard_theme") or {},
                "table_contributions": dashboard_spec.get("table_contributions") or [],
                "kpi_family_contributions": dashboard_spec.get("kpi_family_contributions") or [],
            },
            "investigation_summary": investigation_summary,
            "anomalies": anomalies_payload,
            "correlation_context": correlation_context or {},
            "evidence_query_results": executed_queries,
            "rejected_queries": rejected_queries,
        },
        model_env_key="AGENTIC_ANOMALY_SYNTHESIS_MODEL",
        timeout_env_key="AGENTIC_ANOMALY_SYNTHESIS_TIMEOUT_SEC",
    )


def _llm_summarize_anomaly_fallback_exploration(
    settings,
    *,
    domain_id: str | None,
    context_text: str | None,
    dashboard_spec: dict[str, Any],
    quality_report: dict[str, Any],
    exploration_payload: dict[str, Any],
    correlation_context: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    system_prompt = (
        "You are an anomaly exploration analyst. "
        "A strong anomaly detector found no confirmed candidates, so you must interpret exploratory time-series and group-by evidence "
        "from business tables and produce a grounded anomaly-readiness briefing. "
        "Return JSON only with keys: "
        "summary_text, insights, hypotheses, actions, dashboard_suggestions. "
        "Rules: "
        "- Do not claim confirmed anomalies unless the evidence clearly supports it. "
        "- Distinguish exploratory signals from confirmed anomalies. "
        "- Explain business implications using the provided context. "
        "- dashboard_suggestions should be a list of objects with title, section, priority, query_id, chart_title, summary, include. "
        "- hypotheses and actions may be empty when evidence is weak."
    )
    return _llm_json_response(
        settings,
        system_prompt=system_prompt,
        user_payload={
            "domain_id": domain_id,
            "context_text": str(context_text or "")[:8000],
            "dashboard": {
                "title": dashboard_spec.get("dashboard_title") or dashboard_spec.get("title"),
                "story": dashboard_spec.get("story") or {},
                "insights": (dashboard_spec.get("insights") or [])[:10],
            },
            "quality_report": quality_report or {},
            "exploration": exploration_payload,
            "correlation_context": correlation_context or {},
        },
        model_env_key="AGENTIC_ANOMALY_FALLBACK_MODEL",
        timeout_env_key="AGENTIC_ANOMALY_FALLBACK_TIMEOUT_SEC",
    )


def _fallback_anomaly_exploration_payload(
    *,
    exploration_payload: dict[str, Any],
    quality_report: dict[str, Any] | None = None,
    correlation_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    queries = [item for item in (exploration_payload.get("queries") or []) if isinstance(item, dict)]
    observations = [item for item in (exploration_payload.get("observations") or []) if isinstance(item, dict)]
    source_title = str(exploration_payload.get("source_dashboard_title") or "source dashboard").strip()
    summary_text = (
        f"No confirmed anomalies crossed the configured threshold, so the system generated an exploratory anomaly dashboard from table-native queries. "
        f"The analysis uses {len(queries)} exploratory quer{'ies' if len(queries) != 1 else 'y'} over {source_title}."
    )
    if observations:
        first = observations[0]
        summary_text += f" The strongest exploratory signal comes from {first.get('title') or 'the lead chart'}."
    warnings = []
    if quality_report:
        warnings = [str(v) for v in (((quality_report.get("anomaly_readiness_advisory") or {}).get("warnings") or [])) if str(v).strip()]
    insights: list[str] = []
    for obs in observations[:3]:
        title = str(obs.get("title") or "").strip()
        detail = obs.get("detail") or {}
        if title and isinstance(detail, dict):
            period = detail.get("period")
            delta = detail.get("deviation") or detail.get("delta_value")
            if period is not None:
                insights.append(f"{title} shows a notable change around {period} with deviation {delta}.")
            elif delta is not None:
                insights.append(f"{title} highlights a recent category shift with delta {delta}.")
    insights.extend(warnings[:2])
    dashboard_suggestions = [
        {
            "suggestion_id": f"fallback_{idx}",
            "title": str(item.get("title") or f"Exploration {idx}"),
            "section": "chart",
            "priority": idx,
            "summary": str(item.get("reason") or "Exploratory anomaly view"),
            "query_id": item.get("query_id"),
            "chart_title": item.get("title"),
            "include": True,
        }
        for idx, item in enumerate(queries[:6], start=1)
    ]
    if correlation_context and correlation_context.get("summary"):
        insights.append(str(correlation_context.get("summary")))
    return {
        "summary_text": summary_text,
        "hypotheses": [],
        "actions": [],
        "insights": insights[:8],
        "dashboard_suggestions": dashboard_suggestions,
        "mode": "table_native_exploration",
    }


def _llm_narrate_contextual_chart(
    settings,
    *,
    chart_title: str,
    chart_type: str,
    rows: list[dict[str, Any]],
    metric_name: str,
    dimensions: list[str],
    context_text: str | None,
    dashboard_title: str | None,
    investigation_summary: dict[str, Any] | None,
    quality_report: dict[str, Any] | None,
    correlation_context: dict[str, Any] | None,
) -> dict[str, str] | None:
    system_prompt = (
        "You are a business analyst writing contextual chart explanations for an anomaly dashboard. "
        "Use the chart data and business context to explain what the chart shows, what changed, and why it matters. "
        "Ground the explanation primarily in the displayed chart rows. "
        "Do not let external correlation or investigation context override the visible series, entities, dates, or grain in the chart. "
        "If external context is mentioned, label it clearly as related context, not as evidence shown in the chart. "
        "If the investigation mode is exploratory or no confirmed anomalies crossed threshold, say that explicitly and avoid claiming confirmed anomalies. "
        "Return JSON only with keys: insight_text, narrative_text. "
        "insight_text must be one short takeaway sentence. "
        "narrative_text must be 3 to 5 sentences, grounded in the data, with business-context interpretation and any important caveats. "
        "Do not invent causes; clearly frame hypotheses as possibilities."
    )
    payload = {
        "dashboard_title": dashboard_title,
        "chart_title": chart_title,
        "chart_type": chart_type,
        "metric_name": metric_name,
        "dimensions": dimensions,
        "context_text": str(context_text or "")[:8000],
        "investigation_summary": investigation_summary or {},
        "quality_report": quality_report or {},
        "correlation_context": correlation_context or {},
        "chart_rows": rows[:150],
    }
    result = _llm_json_response(
        settings,
        system_prompt=system_prompt,
        user_payload=payload,
        model_env_key="AGENTIC_CONTEXTUAL_CHART_MODEL",
        timeout_env_key="AGENTIC_CONTEXTUAL_CHART_TIMEOUT_SEC",
    )
    if not isinstance(result, dict):
        return None
    insight_text = str(result.get("insight_text") or "").strip()
    narrative_text = str(result.get("narrative_text") or "").strip()
    if not insight_text and not narrative_text:
        return None
    return {"insight_text": insight_text, "narrative_text": narrative_text}


def _interaction_source_dimensions(
    *,
    dimensions: list[str],
    time_column: str | None = None,
    category_column: str | None = None,
) -> list[str]:
    source_dims: list[str] = []
    if time_column:
        source_dims.append(str(time_column))
    if category_column and category_column not in source_dims:
        source_dims.append(str(category_column))
    for dim in dimensions:
        dim_text = str(dim or "").strip()
        if dim_text and dim_text not in source_dims:
            source_dims.append(dim_text)
    return source_dims


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


def _persist_anomaly_workspace_context(
    settings,
    *,
    state: dict[str, Any],
    investigation_id: str,
    summary_text: str | None,
    anomaly_ids: list[str],
    hypothesis_ids: list[str],
    action_ids: list[str],
    dashboard_id: str | None,
) -> None:
    conversation_id = str(state.get("conversation_id") or "").strip()
    tenant_id = str(state.get("tenant_id") or "").strip()
    domain_id = str(state.get("domain_id") or "").strip()
    run_id = str(state.get("run_id") or state.get("deployment_run_id") or "").strip()
    if not conversation_id or not tenant_id or not domain_id or not run_id:
        return
    summary = str(summary_text or "Anomaly investigation artifacts are available.").strip()
    payload = {
        "artifact_kind": "anomaly_investigation",
        "investigation_id": investigation_id,
        "anomaly_ids": anomaly_ids,
        "hypothesis_ids": hypothesis_ids,
        "action_ids": action_ids,
        "dashboard_id": dashboard_id,
    }
    create_workspace_message(
        settings,
        conversation_id=conversation_id,
        tenant_id=tenant_id,
        domain_id=domain_id,
        run_id=run_id,
        sender="system",
        message_text=summary,
        summary_json=payload,
        inference_json={"summary": summary, **payload},
    )
    existing_memory = get_workspace_memory(settings, conversation_id) or {}
    memory_json = dict(existing_memory.get("memory_json") or {})
    investigations = [item for item in (memory_json.get("anomaly_investigations") or []) if isinstance(item, dict)]
    investigations = [item for item in investigations if str(item.get("investigation_id") or "") != investigation_id]
    investigations.insert(
        0,
        {
            "investigation_id": investigation_id,
            "summary_text": summary,
            "anomaly_ids": anomaly_ids[:10],
            "hypothesis_ids": hypothesis_ids[:10],
            "action_ids": action_ids[:10],
            "dashboard_id": dashboard_id,
        },
    )
    memory_json["anomaly_investigations"] = investigations[:10]
    upsert_workspace_memory(
        settings,
        conversation_id=conversation_id,
        tenant_id=tenant_id,
        domain_id=domain_id,
        run_id=run_id,
        summary_text=summary,
        memory_json=memory_json,
    )


def _normalize_confidence_score(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().lower()
    if not text:
        return default
    mapping = {
        "high": 0.85,
        "medium": 0.6,
        "med": 0.6,
        "low": 0.35,
        "strong": 0.8,
        "moderate": 0.6,
        "weak": 0.3,
    }
    if text in mapping:
        return mapping[text]
    try:
        return float(text)
    except (TypeError, ValueError):
        return default


def _build_evidence_coverage_summary(
    expected_tables: list[str],
    fact_view_results: list[dict[str, Any]],
    joined_views: list[dict[str, Any]],
) -> dict[str, Any]:
    expected = [str(v) for v in expected_tables if str(v).strip()]
    fact_results = [item for item in fact_view_results if isinstance(item, dict)]
    fact_created = [item for item in fact_results if item.get("status") == "created"]
    fact_failed = [item for item in fact_results if item.get("status") != "created"]
    join_created = [item for item in joined_views if isinstance(item, dict) and item.get("status") == "created"]
    join_failed = [item for item in joined_views if isinstance(item, dict) and item.get("status") != "created"]
    coverage_ok = not fact_failed and not join_failed and len(fact_created) == len(expected)
    return {
        "status": "passed" if coverage_ok else "failed",
        "expected_fact_tables": expected,
        "expected_fact_count": len(expected),
        "fact_view_created_count": len(fact_created),
        "fact_view_failure_count": len(fact_failed),
        "join_view_created_count": len(join_created),
        "join_view_failure_count": len(join_failed),
        "fact_views": fact_results,
        "joined_views": joined_views,
        "failure_reasons": [
            item
            for item in [
                "fact_view_creation_failed" if fact_failed else None,
                "joined_view_creation_failed" if join_failed else None,
                "missing_expected_fact_views" if len(fact_created) < len(expected) else None,
            ]
            if item
        ],
    }


def _load_domain_policies(domain_id: str | None) -> list[dict[str, Any]]:
    if not domain_id:
        return []
    try:
        pack = load_pack(f"packs/{domain_id}")
    except Exception:
        return []
    policies = (pack.get("policies") or {}).get("policies") or []
    return [item for item in policies if isinstance(item, dict)]


def _table_column_case_map(table_profile: dict[str, Any]) -> dict[str, str]:
    names: list[str] = []
    for key in ("columns", "time_columns", "categorical_columns", "numeric_columns", "eligible_numeric_columns"):
        for item in (table_profile.get(key) or []):
            if isinstance(item, dict):
                name = item.get("name") or item.get("column_name")
            else:
                name = item
            if name:
                names.append(str(name))
    mapping: dict[str, str] = {}
    for name in names:
        mapping.setdefault(name.lower(), name)
    return mapping


def _rewrite_policy_sql(fragment: str, table_alias: str, table_profile: dict[str, Any]) -> str:
    text = str(fragment or "").strip()
    if not text:
        return ""
    case_map = _table_column_case_map(table_profile)
    for lower_name, actual_name in sorted(case_map.items(), key=lambda item: len(item[0]), reverse=True):
        pattern = re.compile(rf"\b{re.escape(lower_name)}\b", re.IGNORECASE)
        text = pattern.sub(f"{table_alias}.{_qident(actual_name)}", text)
    return text


def _context_scoped_tables_for_column(
    context_text: str,
    column_name: str,
    known_tables: list[str],
) -> set[str] | None:
    """
    Parse context_text to find whether a filter column is explicitly scoped to specific tables.

    Example context_text pattern:
        "Use these business rules for MOM_DAY_LEVEL_DATA and M60_LEVEL_METADATA:
         - Apply the mandatory filter WHERE sbu_name IS NOT NULL ..."

    If the context mentions specific tables alongside a filter column, the filter is
    scoped to only those tables.  Tables not mentioned in the scoping block are excluded.

    Returns:
        set of lowercased table names that the filter applies to, or
        None if no explicit table scoping is found (policy applies to all tables as usual).
    """
    if not context_text or not column_name or not known_tables:
        return None

    col_lower = column_name.lower()
    table_lower_map = {t.lower(): t for t in known_tables}

    # Walk paragraph-by-paragraph; a paragraph is any block separated by blank lines
    # or newline-prefixed bullet points.
    paragraphs = re.split(r"\n{2,}", context_text)
    for para in paragraphs:
        if col_lower not in para.lower():
            continue
        # Look for "for TABLE1 and TABLE2" / "for TABLE1, TABLE2" on any line of the paragraph
        for_match = re.search(r"\bfor\b([^:\n]+)", para, re.IGNORECASE)
        if not for_match:
            continue
        candidate_str = for_match.group(1)
        scoped: set[str] = set()
        for tl in table_lower_map:
            if re.search(rf"\b{re.escape(tl)}\b", candidate_str, re.IGNORECASE):
                scoped.add(tl)
        if scoped:
            return scoped

    return None


def _dashboard_policy_filters(
    domain_id: str | None,
    table_alias: str,
    table_profile: dict[str, Any],
    table_name: str | None = None,
    context_text: str | None = None,
    all_table_names: list[str] | None = None,
) -> list[str]:
    filters: list[str] = []
    case_map = _table_column_case_map(table_profile)
    for policy in _load_domain_policies(domain_id):
        applies_to = str(policy.get("applies_to") or "").strip().lower()
        if applies_to not in {"", "all", "chart"}:
            continue
        filter_def = policy.get("filter") or {}
        if str(filter_def.get("operator") or "").strip().lower() != "custom_sql":
            continue
        column_name = str(filter_def.get("column") or "").strip().lower()
        if column_name and column_name not in case_map:
            continue
        # If context_text explicitly scopes this filter column to a set of tables,
        # skip the policy for any table not in that set.  This lets the deployment
        # context_text say "use these rules for TABLE_A and TABLE_B" and have the
        # system respect that scope without any changes to policies.yml.
        if column_name and context_text and table_name and all_table_names:
            scoped_tables = _context_scoped_tables_for_column(
                context_text, column_name, all_table_names
            )
            if scoped_tables is not None and table_name.lower() not in scoped_tables:
                continue
        for item in filter_def.get("values") or []:
            rendered = _rewrite_policy_sql(str(item or ""), table_alias, table_profile)
            if rendered:
                filters.append(rendered)
    return filters


def _chart_output_validation(
    *,
    chart_title: str,
    chart_intent: str,
    chart_type: str,
    category_col: str | None,
    dimensions: list[str],
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    normalized_dimensions = {str(v).strip().lower() for v in dimensions}
    has_category_dimension = "category" in normalized_dimensions
    del chart_title
    if not rows:
        return {"status": "rejected", "reason": "no_rows_returned"}
    if chart_intent in {"breakdown", "share", "join_breakdown", "multi_series"} and category_col and not has_category_dimension:
        return {"status": "rejected", "reason": "missing_category_dimension"}
    if chart_type == "line" and chart_intent != "multi_series" and has_category_dimension:
        return {"status": "rejected", "reason": "unexpected_category_dimension_for_line_trend"}
    return {"status": "passed", "reason": "eligible_metric"}


def _fallback_anomaly_investigation_payload(
    *,
    anomalies_payload: list[dict[str, Any]],
    high_signal_areas_by_anomaly: dict[str, list[dict[str, Any]]],
    executed_queries: list[dict[str, Any]],
    correlation_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    prioritized = [item for item in anomalies_payload if isinstance(item, dict)][:3]
    if not prioritized:
        return {
            "summary_text": "No strong anomaly investigation narrative could be generated.",
            "hypotheses": [],
            "actions": [],
            "insights": [],
            "dashboard_suggestions": [],
        }

    first = prioritized[0]
    first_anomaly_id = str(first.get("anomaly_id") or "").strip()
    first_metric = str(first.get("metric_name") or first.get("raw_signal_name") or "signal")
    first_evidence = first.get("evidence") or {}
    summary_text = (
        f"{first_metric} shows the strongest recent anomaly at {first_evidence.get('period')}, "
        f"with actual {first_evidence.get('actual')} versus baseline {first_evidence.get('baseline')}."
    )
    hypotheses: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    insights: list[str] = []
    dashboard_suggestions: list[dict[str, Any]] = []

    for idx, item in enumerate(prioritized, start=1):
        anomaly_id = str(item.get("anomaly_id") or "").strip()
        metric_name = str(item.get("metric_name") or item.get("raw_signal_name") or f"signal_{idx}")
        evidence = item.get("evidence") or {}
        period = evidence.get("period")
        actual = evidence.get("actual")
        baseline = evidence.get("baseline")
        deviation = evidence.get("deviation")
        confidence = _normalize_confidence_score(evidence.get("confidence_score"), 0.45)
        areas = high_signal_areas_by_anomaly.get(anomaly_id) or []
        top_area = areas[0] if areas else None
        driver_summary = None
        if top_area:
            driver_summary = (
                f"{top_area.get('dimension')}={top_area.get('value') if top_area.get('value') is not None else top_area.get('top_value')}"
            )
        related_correlations = [row for row in (item.get("related_correlations") or []) if isinstance(row, dict)]
        related_threads = [row for row in (item.get("related_investigation_threads") or []) if isinstance(row, dict)]
        correlation_note = None
        if related_correlations:
            top_corr = related_correlations[0]
            peer_metric = top_corr.get("peer_metric")
            if peer_metric:
                correlation_note = f"It also co-moves with {peer_metric} (r={top_corr.get('pearson_r')})."
        if related_threads and not correlation_note:
            focus = [str(v) for v in (related_threads[0].get("suggested_focus") or []) if str(v).strip()]
            if focus:
                correlation_note = f"Correlation investigation suggests focus on {', '.join(focus[:2])}."
        explanation = (
            f"{metric_name} deviated materially during {period}. "
            f"Actual was {actual} against a baseline of {baseline}, creating deviation {deviation}."
        )
        if driver_summary:
            explanation += f" The most concentrated explanatory slice is {driver_summary}."
        if correlation_note:
            explanation += f" {correlation_note}"
        hypotheses.append(
            {
                "title": f"{metric_name} anomaly requires operational review",
                "explanation": explanation,
                "confidence": round(max(confidence, 0.4), 4),
                "anomaly_ids": [anomaly_id] if anomaly_id else [],
                "likely_drivers": [driver_summary] if driver_summary else [],
                "supporting_evidence": {
                    "period": period,
                    "actual": actual,
                    "baseline": baseline,
                    "deviation": deviation,
                    "high_signal_area": top_area,
                    "related_correlations": related_correlations[:3],
                    "related_investigation_threads": related_threads[:2],
                },
                "validation_step": (
                    f"Compare {metric_name} against plant, zone, and operational hour slices for {period}."
                ),
            }
        )
        actions.append(
            {
                "action_type": "prescriptive",
                "action_text": (
                    f"Inspect the leading drivers behind {metric_name} for {period}"
                    + (f", starting with {driver_summary}." if driver_summary else ".")
                ),
                "confidence": round(max(confidence, 0.35), 4),
                "priority": "high" if idx == 1 else "medium",
                "linked_hypothesis_titles": [f"{metric_name} anomaly requires operational review"],
                "recommended_owner": "operations_analyst",
            }
        )
        insights.append(
            f"{metric_name} moved from baseline {baseline} to actual {actual} during {period}."
            + (f" Top concentration is in {driver_summary}." if driver_summary else "")
            + (f" {correlation_note}" if correlation_note else "")
        )
        dashboard_suggestions.append(
            {
                "suggestion_id": f"fallback_chart_{idx}",
                "title": f"{metric_name} anomaly evidence",
                "section": "chart",
                "priority": idx,
                "summary": f"Show evidence for {metric_name} deviation around {period}.",
                "query_id": str(executed_queries[idx - 1].get("query_id") or "") if idx - 1 < len(executed_queries) else None,
                "include": True,
            }
        )
    return {
        "summary_text": summary_text,
        "hypotheses": hypotheses,
        "actions": actions,
        "insights": insights,
        "dashboard_suggestions": dashboard_suggestions,
    }


def _summarize_correlation_context(
    *,
    correlation_run_id: str | None,
    correlation_result: dict[str, Any] | None,
) -> dict[str, Any]:
    result = correlation_result or {}
    anomaly_results = [item for item in (result.get("anomaly_results") or []) if isinstance(item, dict)]
    correlation_pairs = [item for item in (result.get("correlation_pairs") or []) if isinstance(item, dict)]
    investigation_threads = [item for item in (result.get("investigation_threads") or []) if isinstance(item, dict)]
    forward_projections = [item for item in (result.get("forward_projections") or []) if isinstance(item, dict)]
    return {
        "correlation_run_id": correlation_run_id,
        "summary": {
            "metric_count": result.get("metric_count"),
            "anomaly_count": len(anomaly_results),
            "correlation_pair_count": len(correlation_pairs),
            "thread_count": len(investigation_threads),
            "projection_count": len(forward_projections),
            "summary_text": result.get("summary_text"),
            "error_message": result.get("error_message"),
        },
        "anomaly_results": anomaly_results[:20],
        "correlation_pairs": correlation_pairs[:20],
        "investigation_threads": investigation_threads[:10],
        "forward_projections": forward_projections[:10],
    }


def _enrich_anomalies_with_correlation_context(
    anomalies_payload: list[dict[str, Any]],
    correlation_context: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    context = correlation_context or {}
    anomaly_results = [item for item in (context.get("anomaly_results") or []) if isinstance(item, dict)]
    correlation_pairs = [item for item in (context.get("correlation_pairs") or []) if isinstance(item, dict)]
    investigation_threads = [item for item in (context.get("investigation_threads") or []) if isinstance(item, dict)]

    anomaly_lookup: dict[str, list[dict[str, Any]]] = {}
    for row in anomaly_results:
        metric_name = str(row.get("metric_name") or "").strip().lower()
        if metric_name:
            anomaly_lookup.setdefault(metric_name, []).append(row)

    pair_lookup: dict[str, list[dict[str, Any]]] = {}
    for row in correlation_pairs:
        metric_a = str(row.get("metric_a") or "").strip()
        metric_b = str(row.get("metric_b") or "").strip()
        if metric_a:
            pair_lookup.setdefault(metric_a.lower(), []).append(
                {
                    "peer_metric": metric_b,
                    "pearson_r": row.get("pearson_r"),
                    "spearman_rho": row.get("spearman_rho"),
                    "best_lag": row.get("best_lag"),
                    "lag_direction": row.get("lag_direction"),
                    "strength_label": row.get("strength_label"),
                    "direction_label": row.get("direction_label"),
                }
            )
        if metric_b:
            pair_lookup.setdefault(metric_b.lower(), []).append(
                {
                    "peer_metric": metric_a,
                    "pearson_r": row.get("pearson_r"),
                    "spearman_rho": row.get("spearman_rho"),
                    "best_lag": row.get("best_lag"),
                    "lag_direction": row.get("lag_direction"),
                    "strength_label": row.get("strength_label"),
                    "direction_label": row.get("direction_label"),
                }
            )

    thread_lookup: dict[str, list[dict[str, Any]]] = {}
    for row in investigation_threads:
        trigger_metric = str(row.get("trigger_metric") or "").strip().lower()
        if trigger_metric:
            thread_lookup.setdefault(trigger_metric, []).append(
                {
                    "confidence": row.get("confidence"),
                    "leading_dimension": row.get("leading_dimension"),
                    "leading_dim_value": row.get("leading_dim_value"),
                    "suggested_focus": row.get("suggested_focus") or [],
                    "narrative_text": row.get("narrative_text"),
                }
            )

    enriched: list[dict[str, Any]] = []
    for item in anomalies_payload:
        if not isinstance(item, dict):
            continue
        keys = [
            str(item.get("metric_name") or "").strip().lower(),
            str(item.get("raw_signal_name") or "").strip().lower(),
        ]
        related_anomalies: list[dict[str, Any]] = []
        related_pairs: list[dict[str, Any]] = []
        related_threads: list[dict[str, Any]] = []
        for key in [value for value in keys if value]:
            related_anomalies.extend(anomaly_lookup.get(key, []))
            related_pairs.extend(pair_lookup.get(key, []))
            related_threads.extend(thread_lookup.get(key, []))
        enriched.append(
            {
                **item,
                "correlation_run_id": context.get("correlation_run_id"),
                "related_correlation_anomalies": related_anomalies[:3],
                "related_correlations": related_pairs[:5],
                "related_investigation_threads": related_threads[:3],
            }
        )
    return enriched


def _chart_rerank_enabled(settings) -> bool:
    mode = os.getenv("AGENTIC_CHART_RERANK_MODE", "auto").lower()
    if mode in {"off", "false", "0"}:
        return False
    if mode in {"on", "true", "1"}:
        return bool(getattr(settings, "openai_api_key", None))
    return bool(getattr(settings, "openai_api_key", None))


def _chart_proposal_enabled(settings) -> bool:
    mode = os.getenv("AGENTIC_CHART_PROPOSAL_MODE", "auto").lower()
    if mode in {"off", "false", "0"}:
        return False
    if mode in {"on", "true", "1"}:
        return bool(getattr(settings, "openai_api_key", None))
    return bool(getattr(settings, "openai_api_key", None))


def _dashboard_composition_enabled(settings) -> bool:
    mode = os.getenv("AGENTIC_DASHBOARD_COMPOSITION_MODE", "auto").lower()
    if mode in {"off", "false", "0"}:
        return False
    if mode in {"on", "true", "1"}:
        return bool(getattr(settings, "openai_api_key", None))
    return bool(getattr(settings, "openai_api_key", None))


def _validate_llm_chart_candidates(
    candidates: list[dict[str, Any]] | None,
    *,
    profiling: dict[str, Any],
    metrics: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    profiling_tables = {str(t.get("name") or ""): t for t in (profiling.get("tables") or []) if t.get("name")}
    metric_map = {
        (str(m.get("base_table") or ""), str(m.get("metric_name") or "")): m
        for m in metrics
        if m.get("base_table") and m.get("metric_name")
    }
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for candidate in candidates or []:
        table = str(candidate.get("table") or "").strip()
        metric_name = str(candidate.get("metric") or "").strip()
        chart_type = str(candidate.get("type") or "").strip()
        if not table or not metric_name or not chart_type:
            rejected.append({"candidate": candidate, "reason": "missing_required_fields"})
            continue
        table_profile = profiling_tables.get(table)
        metric = metric_map.get((table, metric_name))
        if not table_profile or not metric:
            rejected.append({"candidate": candidate, "reason": "unknown_table_or_metric"})
            continue
        time_col = str(candidate.get("time_column") or "").strip() or None
        cat_col = str(candidate.get("category_column") or "").strip() or None
        valid_cols = set(
            list(table_profile.get("time_columns") or [])
            + list(table_profile.get("categorical_columns") or [])
            + list(table_profile.get("numeric_columns") or [])
        )
        if time_col and time_col not in valid_cols:
            rejected.append({"candidate": candidate, "reason": "unknown_time_column"})
            continue
        # Handle hierarchy chart type: LLM may propose type="hierarchy" with a
        # ">"-separated path like "location_name > equipment_type > device_type".
        # Convert to a standard bar chart using the first level as the category column.
        if chart_type == "hierarchy" and cat_col and ">" in cat_col:
            hierarchy_levels = [lvl.strip() for lvl in cat_col.split(">") if lvl.strip()]
            first_level = hierarchy_levels[0] if hierarchy_levels else None
            if not first_level or first_level not in valid_cols:
                rejected.append({"candidate": candidate, "reason": "unknown_category_column"})
                continue
            cat_col = first_level
            chart_type = "bar"
        elif cat_col and cat_col not in valid_cols:
            rejected.append({"candidate": candidate, "reason": "unknown_category_column"})
            continue
        normalized = {
            "type": chart_type,
            "intent": candidate.get("intent") or ("trend" if time_col else "breakdown"),
            "title": candidate.get("title") or metric_name.replace("_", " ").title(),
            "table": table,
            "metric": metric_name,
            "metric_intent": metric.get("metric_intent"),
            "metric_column": None,
            "metric_expr": metric.get("formula"),
            "time_column": time_col,
            "time_grain": candidate.get("time_grain"),
            "category_column": cat_col,
            "chart_source": candidate.get("chart_source") or "llm_proposed",
            "drill_hierarchy_id": candidate.get("drill_hierarchy_id"),
            "drill_level_id": candidate.get("drill_level_id"),
        }
        key = (
            normalized.get("table"),
            normalized.get("metric"),
            normalized.get("type"),
            normalized.get("intent"),
            normalized.get("time_column"),
            normalized.get("time_grain"),
            normalized.get("category_column"),
        )
        if key in seen:
            continue
        seen.add(key)
        accepted.append(normalized)
    return accepted, rejected


def _llm_propose_chart_candidates(
    settings,
    *,
    domain_id: str | None,
    profiling: dict[str, Any],
    metrics: list[dict[str, Any]],
    context_text: str | None,
    business_hierarchies: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]] | None, dict[str, Any] | None]:
    if not _chart_proposal_enabled(settings):
        return None, None
    model = os.getenv("AGENTIC_CHART_PROPOSAL_MODEL", getattr(settings, "openai_model", "gpt-4o-mini"))
    timeout_sec = int(os.getenv("AGENTIC_CHART_PROPOSAL_TIMEOUT_SEC", "45"))
    metric_payload = []
    for metric in (metrics or [])[:24]:
        metric_payload.append(
            {
                "metric_name": metric.get("metric_name"),
                "table": metric.get("base_table"),
                "metric_intent": metric.get("metric_intent"),
                "metric_source": metric.get("metric_source"),
                "preferred_time_column": metric.get("preferred_time_column"),
                "preferred_breakdowns": (metric.get("preferred_breakdowns") or [])[:4],
                "is_executive_kpi": bool(metric.get("is_executive_kpi")),
            }
        )
    table_payload = []
    for table in (profiling.get("tables") or [])[:10]:
        sample_values = table.get("sample_values") or {}
        # Only include categorical columns that were sampled and actually have
        # non-null distinct values. Columns not yet sampled (beyond the sampling
        # cap) are included as-is — we just don't know about them yet.
        usable_categoricals = [
            col for col in (table.get("categorical_columns") or [])[:12]
            if col not in sample_values or sample_values[col]
        ]
        table_payload.append(
            {
                "table": table.get("name"),
                "time_columns": (table.get("time_columns") or [])[:6],
                "categorical_columns": usable_categoricals,
            }
        )
    hierarchy_payload = [
        {
            "hierarchy_id": h.get("hierarchy_id"),
            "name": h.get("name"),
            "preferred": bool(h.get("preferred")),
            "levels": [
                str(lvl.get("column") or lvl.get("level_id") or "")
                for lvl in (h.get("levels_json") or [])
                if lvl.get("column") or lvl.get("level_id")
            ],
        }
        for h in (business_hierarchies or [])[:4]
        if h.get("levels_json")
    ]
    hierarchy_instruction = (
        " Prefer category columns that appear in the provided business_hierarchies levels "
        "(these support drill-down navigation). Avoid category columns with mostly empty values."
        if hierarchy_payload else ""
    )
    system_prompt = (
        "You propose dashboard chart candidates from validated metrics. "
        "Use only the provided metric names, tables, time columns, and category columns. "
        "Prefer KPI trends by day/month and strong operational breakdowns."
        + hierarchy_instruction +
        " Return JSON only with keys: charts, rationale. "
        "Each chart must contain: type, intent, table, metric, time_column, time_grain, category_column, title."
    )
    user_payload = {
        "domain_id": domain_id,
        "context_text": str(context_text or "")[:8000],
        "metrics": metric_payload,
        "tables": table_payload,
        "business_hierarchies": hierarchy_payload,
    }
    request = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(
            {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": json.dumps(user_payload)},
                ],
                "temperature": 0.1,
                "response_format": {"type": "json_object"},
            }
        ).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {settings.openai_api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    logger = logging.getLogger(__name__)
    try:
        with urllib.request.urlopen(request, timeout=timeout_sec) as response:
            body = json.loads(response.read().decode("utf-8"))
        parsed = json.loads(body["choices"][0]["message"]["content"])
        charts = [item for item in (parsed.get("charts") or []) if isinstance(item, dict)]
        logger.info("agentic.chart_proposal.response | domain=%s candidate_count=%s", domain_id, len(charts))
        return charts, {"model": model, "candidate_count": len(charts), "rationale": parsed.get("rationale")}
    except Exception:
        logger.warning("agentic.chart_proposal_llm_failed", exc_info=True)
        return None, None


def _llm_compose_dashboard(
    settings,
    *,
    domain_id: str | None,
    chart_candidates: list[dict[str, Any]],
    min_charts: int,
    max_charts: int,
) -> tuple[list[dict[str, Any]] | None, dict[str, Any] | None]:
    if not _dashboard_composition_enabled(settings) or not chart_candidates:
        return None, None
    model = os.getenv("AGENTIC_DASHBOARD_COMPOSITION_MODEL", getattr(settings, "openai_model", "gpt-4o-mini"))
    timeout_sec = int(os.getenv("AGENTIC_DASHBOARD_COMPOSITION_TIMEOUT_SEC", "45"))
    candidate_lookup: dict[str, dict[str, Any]] = {}
    payload_candidates = []
    for idx, cand in enumerate(chart_candidates[:40], start=1):
        cid = f"chart_{idx}"
        candidate_lookup[cid] = cand
        payload_candidates.append(
            {
                "candidate_id": cid,
                "title": cand.get("title"),
                "table": cand.get("table"),
                "metric": cand.get("metric"),
                "intent": cand.get("intent"),
                "type": cand.get("type"),
                "time_grain": cand.get("time_grain"),
                "category_column": cand.get("category_column"),
            }
        )
    system_prompt = (
        "You compose a strong operational dashboard. "
        "Choose only from the provided candidate_ids. "
        "Prefer broad KPI coverage, day and month trends, and plant/zone/region breakdowns. "
        "Return JSON only with keys: selected_ids, rationale."
    )
    request = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(
            {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "domain_id": domain_id,
                                "min_charts": min_charts,
                                "max_charts": max_charts,
                                "candidates": payload_candidates,
                            }
                        ),
                    },
                ],
                "temperature": 0.1,
                "response_format": {"type": "json_object"},
            }
        ).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {settings.openai_api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    logger = logging.getLogger(__name__)
    try:
        with urllib.request.urlopen(request, timeout=timeout_sec) as response:
            body = json.loads(response.read().decode("utf-8"))
        parsed = json.loads(body["choices"][0]["message"]["content"])
        ordered: list[dict[str, Any]] = []
        for cid in [str(v) for v in (parsed.get("selected_ids") or [])]:
            if cid in candidate_lookup:
                ordered.append(candidate_lookup[cid])
            if len(ordered) >= max_charts:
                break
        return ordered or None, {"model": model, "selected_count": len(ordered), "rationale": parsed.get("rationale")}
    except Exception:
        logger.warning("agentic.dashboard_composition_llm_failed", exc_info=True)
        return None, None


def _llm_rerank_chart_candidates(
    settings,
    *,
    domain_id: str | None,
    profiling: dict[str, Any],
    candidates: list[dict[str, Any]],
    min_charts: int,
    max_charts: int,
) -> tuple[list[dict[str, Any]] | None, dict[str, Any] | None]:
    if not _chart_rerank_enabled(settings):
        return None, None
    valid_candidates = [cand for cand in candidates if not cand.get("skipped")]
    if not valid_candidates:
        return None, None
    model = os.getenv("AGENTIC_CHART_RERANK_MODEL", getattr(settings, "openai_model", "gpt-4o-mini"))
    timeout_sec = int(os.getenv("AGENTIC_CHART_RERANK_TIMEOUT_SEC", "30"))
    candidate_payload = []
    candidate_lookup: dict[str, dict[str, Any]] = {}
    for idx, cand in enumerate(valid_candidates[:24], start=1):
        cid = f"cand_{idx}"
        candidate_lookup[cid] = cand
        candidate_payload.append(
            {
                "candidate_id": cid,
                "title": cand.get("title"),
                "table": cand.get("table"),
                "metric": cand.get("metric"),
                "metric_intent": cand.get("metric_intent"),
                "chart_type": cand.get("type"),
                "intent": cand.get("intent"),
                "time_column": cand.get("time_column"),
                "time_grain": cand.get("time_grain"),
                "category_column": cand.get("category_column"),
            }
        )
    profiling_payload = []
    for table in (profiling.get("tables") or [])[:8]:
        profiling_payload.append(
            {
                "table": table.get("name"),
                "time_columns": (table.get("time_columns") or [])[:3],
                "categorical_columns": (table.get("categorical_columns") or [])[:8],
                "eligible_numeric_columns": (table.get("eligible_numeric_columns") or [])[:8],
            }
        )
    system_prompt = (
        "You are a dashboard chart reranker. "
        "Choose only from the provided candidate_ids. "
        "Prefer executive KPI coverage, day and month trends, and business breakdowns. "
        "Do not invent charts. Return JSON only with keys: selected_ids, rationale."
    )
    user_payload = {
        "domain_id": domain_id,
        "selection_constraints": {
            "min_charts": min_charts,
            "max_charts": max_charts,
            "prefer_trends": 2,
            "prefer_breakdowns": 2,
        },
        "profiling_summary": profiling_payload,
        "candidates": candidate_payload,
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
        selected_ids = [str(item) for item in (parsed.get("selected_ids") or []) if str(item).strip()]
        ordered: list[dict[str, Any]] = []
        seen: set[str] = set()
        for cid in selected_ids:
            if cid in seen or cid not in candidate_lookup:
                continue
            seen.add(cid)
            ordered.append(candidate_lookup[cid])
            if len(ordered) >= max_charts:
                break
        if not ordered:
            return None, None
        diagnostics = {
            "model": model,
            "selected_ids": selected_ids,
            "applied_ids": [cid for cid in selected_ids if cid in candidate_lookup][:max_charts],
            "rationale": parsed.get("rationale"),
        }
        return ordered, diagnostics
    except Exception:
        logging.getLogger(__name__).warning("agentic.chart_rerank_llm_failed", exc_info=True)
        return None, None


def _metric_rerank_enabled(settings) -> bool:
    mode = os.getenv("AGENTIC_METRIC_RERANK_MODE", "auto").lower()
    if mode in {"off", "false", "0"}:
        return False
    if mode in {"on", "true", "1"}:
        return bool(getattr(settings, "openai_api_key", None))
    return bool(getattr(settings, "openai_api_key", None))


def _context_metric_llm_enabled(settings) -> bool:
    mode = os.getenv("AGENTIC_CONTEXT_METRIC_MODE", "auto").lower()
    if mode in {"off", "false", "0"}:
        return False
    if mode in {"on", "true", "1"}:
        return bool(getattr(settings, "openai_api_key", None))
    return bool(getattr(settings, "openai_api_key", None))


def _llm_propose_context_metrics(
    settings,
    *,
    domain_id: str | None,
    context_text: str | None,
    schema_graph: dict[str, Any],
    profiling: dict[str, Any],
    glossary_terms: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]] | None, dict[str, Any] | None]:
    text = str(context_text or "").strip()
    if not _context_metric_llm_enabled(settings) or not text:
        return None, None
    model = os.getenv("AGENTIC_CONTEXT_METRIC_MODEL", getattr(settings, "openai_model", "gpt-4o-mini"))
    timeout_sec = int(os.getenv("AGENTIC_CONTEXT_METRIC_TIMEOUT_SEC", "45"))
    profiling_payload = []
    for table in (profiling.get("tables") or [])[:10]:
        profiling_payload.append(
            {
                "table": table.get("name"),
                "row_count": table.get("row_count"),
                "eligible_numeric_columns": (table.get("eligible_numeric_columns") or [])[:12],
                "numeric_columns": (table.get("numeric_columns") or [])[:12],
                "time_columns": (table.get("time_columns") or [])[:6],
                "categorical_columns": (table.get("categorical_columns") or [])[:12],
            }
        )
    glossary_payload = []
    for item in (glossary_terms or [])[:30]:
        if not item.get("term"):
            continue
        glossary_payload.append(
            {
                "term": item.get("term"),
                "synonyms": (item.get("synonyms") or [])[:3],
                "abbreviations": (item.get("abbreviations") or [])[:3],
            }
        )
    system_prompt = (
        "You interpret business deployment context and propose analytical metrics. "
        "Use only provided tables and columns. "
        "Do not invent tables or columns. "
        "If the context implies formulas or KPI names, translate them into candidate metrics. "
        "Return JSON only with keys: metrics, rationale. "
        "metrics must be a list of objects with keys: metric_name, display_name, description, base_table, formula, grain, preferred_time_column, preferred_dimensions, metric_type, confidence, rationale. "
        "CRITICAL: The 'formula' field must be a valid SQL aggregate expression ONLY. "
        "Valid examples: COUNT(*), SUM(column_name), AVG(column_name), COUNT(DISTINCT column_name), "
        "COUNT(CASE WHEN column_name = value THEN 1 END), SUM(CASE WHEN col = val THEN col2 ELSE 0 END), "
        "ROUND(100.0*SUM(col)/NULLIF(SUM(total),0),2). "
        "Do NOT include WHERE, FROM, JOIN, HAVING, GROUP BY, or any SQL clause in the formula. "
        "The formula is used as a SELECT expression inside a pre-built query. "
        "To filter by a condition, embed it using CASE WHEN inside the aggregate: "
        "e.g. COUNT(CASE WHEN status = 'active' THEN 1 END) not COUNT(*) WHERE status = 'active'. "
        "If no metric is strongly implied by the context, return an empty metrics array."
    )
    user_payload = {
        "domain_id": domain_id,
        "context_text": text[:12000],
        "schema_summary": [
            {
                "table": table.get("name"),
                "columns": [c.get("name") for c in (table.get("columns") or [])[:25] if c.get("name")],
            }
            for table in (schema_graph.get("tables") or [])[:10]
        ],
        "profiling_summary": profiling_payload,
        "glossary_terms": glossary_payload,
    }
    logger = logging.getLogger(__name__)
    logger.info(
        "agentic.context_metric_prompt | domain=%s context_chars=%s tables=%s glossary_terms=%s",
        domain_id,
        len(text),
        len(profiling_payload),
        len(glossary_payload),
    )
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
        metrics = [item for item in (parsed.get("metrics") or []) if isinstance(item, dict)]
        diagnostics = {
            "model": model,
            "candidate_count": len(metrics),
            "rationale": parsed.get("rationale"),
            "used_context_text": True,
        }
        logger.info(
            "agentic.context_metric_response | domain=%s candidate_count=%s rationale=%s",
            domain_id,
            len(metrics),
            parsed.get("rationale"),
        )
        return metrics, diagnostics
    except Exception:
        logger.warning("agentic.context_metric_llm_failed", exc_info=True)
        return None, None


def _llm_rerank_metric_candidates(
    settings,
    *,
    domain_id: str | None,
    profiling: dict[str, Any],
    metrics: list[dict[str, Any]],
) -> tuple[list[str] | None, dict[str, Any] | None]:
    if not _metric_rerank_enabled(settings):
        return None, None
    if not metrics:
        return None, None
    model = os.getenv("AGENTIC_METRIC_RERANK_MODEL", getattr(settings, "openai_model", "gpt-4o-mini"))
    timeout_sec = int(os.getenv("AGENTIC_METRIC_RERANK_TIMEOUT_SEC", "30"))
    candidate_payload = []
    valid_metrics = [metric for metric in metrics if metric.get("metric_name") and metric.get("base_table")]
    metric_lookup: dict[str, dict[str, Any]] = {}
    for idx, metric in enumerate(valid_metrics[:30], start=1):
        mid = f"metric_{idx}"
        metric_lookup[mid] = metric
        candidate_payload.append(
            {
                "metric_id": mid,
                "metric_name": metric.get("metric_name"),
                "base_table": metric.get("base_table"),
                "metric_type": metric.get("metric_type"),
                "metric_intent": metric.get("metric_intent"),
                "is_executive_kpi": bool(metric.get("is_executive_kpi")),
                "measure_confidence": float(metric.get("measure_confidence") or 0.0),
                "preferred_time_column": metric.get("preferred_time_column"),
                "preferred_breakdowns": (metric.get("preferred_breakdowns") or [])[:3],
            }
        )
    profiling_payload = []
    for table in (profiling.get("tables") or [])[:8]:
        profiling_payload.append(
            {
                "table": table.get("name"),
                "time_columns": (table.get("time_columns") or [])[:3],
                "categorical_columns": (table.get("categorical_columns") or [])[:8],
                "eligible_numeric_columns": (table.get("eligible_numeric_columns") or [])[:8],
            }
        )
    system_prompt = (
        "You are a KPI metric reranker. "
        "Choose only from the provided metric_ids. "
        "Prefer business KPIs, canonical totals, productivity/efficiency measures, and metrics with strong time and breakdown support. "
        "Do not invent metrics. Return JSON only with keys: ranked_metric_ids, rationale."
    )
    user_payload = {
        "domain_id": domain_id,
        "profiling_summary": profiling_payload,
        "metric_candidates": candidate_payload,
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
        ranked_ids = [str(item) for item in (parsed.get("ranked_metric_ids") or []) if str(item).strip()]
        if not ranked_ids:
            return None, None
        diagnostics = {
            "model": model,
            "ranked_metric_ids": ranked_ids,
            "rationale": parsed.get("rationale"),
        }
        return ranked_ids, diagnostics
    except Exception:
        logging.getLogger(__name__).warning("agentic.metric_rerank_llm_failed", exc_info=True)
        return None, None


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
                        list(levels) if levels else [],
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
        logging.getLogger(__name__).error(
            "agentic.registry.persist.aborted | run_id=%s MISSING REQUIRED SCOPE "
            "tenant_id=%r domain_id=%r connection_id=%r database_name=%r — "
            "refusing to persist to prevent cross-tenant data contamination",
            run_id, tenant_id, domain_id, connection_id, database_name,
        )
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
            artifact_key = f"{tenant_id}__{domain_id}__{fact_model}"
            try:
                # Retire any previous is_current row for this artifact_key before inserting the new one.
                execute_non_query(
                    settings,
                    "UPDATE public.quantyx_facts_registry SET is_current = false, updated_at = now() "
                    "WHERE artifact_key = %s AND tenant_id = %s AND is_current = true",
                    [artifact_key, tenant_id],
                )
                upsert_fact(
                    settings,
                    {
                        "fact_id": f"{run_id}__{fact_model}",
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
                        "artifact_key": artifact_key,
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
            dim_artifact_key = f"{tenant_id}__{domain_id}__dim__{dim_name}"
            try:
                # Retire any previous is_current row for this artifact_key before inserting.
                execute_non_query(
                    settings,
                    "UPDATE public.quantyx_dimensions_registry SET is_current = false, updated_at = now() "
                    "WHERE artifact_key = %s AND tenant_id = %s AND is_current = true",
                    [dim_artifact_key, tenant_id],
                )
                upsert_dimension(
                    settings,
                    {
                        "dimension_id": f"{run_id}__dim__{dim_name}",
                        "tenant_id": tenant_id,
                        "domain_id": domain_id,
                        "connection_id": connection_id,
                        "database_name": database_name,
                        "schema_name": schema_name,
                        "name": dim_name,
                        "keys": meta["keys"] or [dim_name],
                        "attributes": meta["attributes"] or [],
                        "description": f"Agentic inferred dimension used in {', '.join(tables_list)}",
                        "artifact_key": dim_artifact_key,
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
            # Use the raw table name directly — no dbt "fact_" prefix.
            # {{ ref('TABLE') }} is resolved to schema.TABLE at query time
            # by catalog.resolve_ref, so no dbt run is required.
            table_ref = "{{ ref('%s') }}" % base_table
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
                metric_source = str(metric.get("metric_source") or "agentic").strip().lower()
                registry_source_type = (
                    "agentic_context_llm"
                    if metric_source == "context_llm"
                    else ("agentic_context_override" if metric_source == "context_override" else "agentic")
                )
                semantic_metadata = {
                    "metric_source": metric_source,
                    "metric_intent": metric.get("metric_intent"),
                    "family_name": metric.get("family_name"),
                    "family_role": metric.get("family_role"),
                    "derivation_method": metric.get("derivation_method") or metric_source,
                    "derived_from_metrics": metric.get("derived_from_metrics") or [],
                    "source_context": "context_text" if metric_source in {"context_llm", "context_override"} else "agentic",
                    "semantic_confidence": metric.get("measure_confidence"),
                    "validation_status": "validated",
                    "llm_rationale": metric.get("llm_rationale"),
                    "eligibility_reason": metric.get("eligibility_reason"),
                }
                semantic_metadata = {k: v for k, v in semantic_metadata.items() if v not in (None, "", [])}
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
                        "display_name": metric.get("display_name") or metric_name.replace("_", " ").title(),
                        "description": metric.get("description") or f"Agentic inferred metric for {base_table}",
                        "type": metric_type,
                        "unit": metric.get("unit"),
                        "confidence": metric.get("measure_confidence"),
                        "additive": metric_type in {"sum", "count", "avg", "average", "min", "max"},
                        "grain": metric.get("grain") or ("day" if (table_profile.get("time_columns") or []) else "unknown"),
                        "dimensions": metric_dims,
                        "dataset_id": fact_model,
                        "source_model": fact_model,
                        "source_schema": schema_name,
                        "sql": sql_expr,
                        "lifecycle_status": "active",
                        "source_type": registry_source_type,
                        "source_run_id": run_id,
                        "is_current": True,
                        "change_reason": (
                            f"{metric.get('llm_rationale') or metric.get('eligibility_reason') or metric_source}"
                            + (
                                f" | family={metric.get('family_name')} role={metric.get('family_role')}"
                                if metric.get("family_name") or metric.get("family_role")
                                else ""
                            )
                        ),
                        "created_by": "metric_agent",
                        "updated_by": "metric_agent",
                        "owner": metric.get("family_name") or metric_source,
                        "version": (
                            f"run-{run_id}"
                            + (
                                f"|family:{metric.get('family_name')}|role:{metric.get('family_role')}"
                                if metric.get("family_name") or metric.get("family_role")
                                else ""
                            )
                        ),
                        "semantic_metadata": semantic_metadata,
                    },
                )
                persisted_metrics += 1
                logger.info(
                    "agentic.registry.metric_persisted | run_id=%s metric_name=%s base_table=%s artifact_key=%s dataset_id=%s source_model=%s metric_source=%s source_type=%s",
                    run_id,
                    metric_name,
                    base_table,
                    artifact_key,
                    fact_model,
                    fact_model,
                    metric_source,
                    registry_source_type,
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


_CORR_CHART_TYPES = frozenset({
    "forecast_band", "anomaly_timeline", "correlation_heatmap",
    "scatter_regression", "rolling_correlation", "anomaly_density",
    "category_trend_grouped", "category_forecast_stacked_bar",
    "metric_overlap_matrix", "temporal_eligibility_warning_card",
})


def _build_correlation_chart_insight(corr_chart: dict) -> dict[str, Any]:
    """
    Build insight_text, narrative_text, and stats_json for a correlation chart
    using the chart type and its embedded spec data.

    Returns a dict with keys: insight_text, narrative_text, stats_json.
    Falls back to generic title-based text if the spec data is sparse.
    """
    chart_type = str(corr_chart.get("chart_type") or "")
    spec = corr_chart.get("spec") or {}
    data = corr_chart.get("data") or spec.get("data") or []
    metric_name = str(corr_chart.get("metric_name") or spec.get("metric_name") or "")
    pair_id = corr_chart.get("pair_id") or ""
    subtitle = str(spec.get("subtitle") or "")
    title = str(spec.get("title") or chart_type.replace("_", " ").title())

    insight_text = ""
    narrative_text = ""
    stats_json: dict = {"chart_type": chart_type, "metric_name": metric_name}

    if chart_type == "forecast_band":
        actuals = [r["actual"] for r in data if r.get("actual") is not None]
        forecasts = [r["forecast"] for r in data if r.get("forecast") is not None]
        forecast_rows = [r for r in data if r.get("forecast") is not None]
        trend = "flat"
        for part in subtitle.split(","):
            part = part.strip()
            if part.startswith("Trend:"):
                trend = part.replace("Trend:", "").strip()
                break
        seasonality = "seasonality detected" in subtitle
        if actuals and forecasts and forecast_rows:
            last_actual = actuals[-1]
            first_forecast = forecasts[0]
            forecast_end = forecasts[-1]
            pct_change = ((first_forecast - last_actual) / last_actual * 100) if last_actual else 0
            horizon_change = ((forecast_end - last_actual) / last_actual * 100) if last_actual else 0
            direction = "increase" if pct_change > 0 else ("decrease" if pct_change < 0 else "no change")
            first_period = str(forecast_rows[0].get("period") or "")
            last_period = str(forecast_rows[-1].get("period") or "")
            insight_text = (
                f"{metric_name} forecast shows a {abs(pct_change):.1f}% {direction} "
                f"from the last actual value. Trend: {trend}."
            )
            narrative_text = (
                f"This chart compares the historical actual series for {metric_name} with its forecast extension. "
                f"The first projected point at {first_period} is {first_forecast:,.0f} versus the last actual value of {last_actual:,.0f} "
                f"({pct_change:+.1f}%). By the end of the forecast horizon at {last_period}, the projection reaches {forecast_end:,.0f} "
                f"({horizon_change:+.1f}% versus the last actual). The overall direction is {trend}"
                + (", and the model detected seasonality." if seasonality else ".")
            )
        else:
            insight_text = f"{metric_name} forward projection with {trend} trend."
            narrative_text = subtitle or title
        stats_json.update({"trend_direction": trend, "seasonality": seasonality,
                           "actual_count": len(actuals), "forecast_count": len(forecasts)})

    elif chart_type == "anomaly_timeline":
        scored = [r for r in data if r.get("anomaly_score") is not None]
        anomaly_classes = {}
        for r in scored:
            cls = str(r.get("anomaly_class") or "unknown")
            anomaly_classes[cls] = anomaly_classes.get(cls, 0) + 1
        dominant = max(anomaly_classes, key=anomaly_classes.get) if anomaly_classes else None
        n = len(scored)
        if n > 0:
            insight_text = (
                f"{n} anomaly point{'s' if n != 1 else ''} detected in {metric_name}. "
                f"Dominant type: {dominant}."
            )
            narrative_text = (
                f"The anomaly timeline for {metric_name} shows {n} flagged period{'s' if n != 1 else ''}. "
                + (f"The most common anomaly class is '{dominant}', indicating "
                   + ("a sudden spike." if dominant == "spike" else
                      "a sudden drop." if dominant == "drop" else
                      "a sustained upward drift." if dominant == "drift_up" else
                      "a sustained downward drift." if dominant == "drift_down" else
                      "a step-level shift." if dominant == "step_change" else
                      f"anomalies of type '{dominant}'.")
                   if dominant else "")
            )
        else:
            insight_text = f"No anomaly periods detected for {metric_name}."
            narrative_text = f"{metric_name} shows no anomalies above the detection threshold."
        stats_json.update({"anomaly_count": n, "anomaly_classes": anomaly_classes})

    elif chart_type == "correlation_heatmap":
        if data:
            non_diagonal = [r for r in data if r.get("metric_a") != r.get("metric_b") and r.get("pearson_r") is not None]
            if non_diagonal:
                strongest = max(non_diagonal, key=lambda r: abs(r.get("pearson_r") or 0.0))
                r_val = strongest.get("pearson_r", 0.0)
                insight_text = (
                    f"Strongest correlation: {strongest['metric_a']} × {strongest['metric_b']} "
                    f"(r = {r_val:.2f})."
                )
                high_pairs = [r for r in non_diagonal if abs(r.get("pearson_r") or 0.0) >= 0.7]
                narrative_text = (
                    f"The heatmap shows {len(non_diagonal) // 2} unique metric pairs. "
                    f"{len(high_pairs) // 2} pair{'s' if len(high_pairs) // 2 != 1 else ''} have |r| ≥ 0.70, "
                    f"indicating strong relationships. "
                    f"Strongest pair: {strongest['metric_a']} × {strongest['metric_b']} (r = {r_val:.2f})."
                )
                stats_json.update({"strongest_r": round(r_val, 4), "high_correlation_pairs": len(high_pairs) // 2})

    elif chart_type == "scatter_regression":
        # Extract r and lag from subtitle: "Pearson r = 0.95 | lag = 1 periods (leading) | ..."
        r_val = None
        lag = None
        direction = None
        for part in subtitle.split("|"):
            part = part.strip()
            if part.startswith("Pearson r ="):
                try:
                    r_val = float(part.split("=")[1].strip())
                except (ValueError, IndexError):
                    pass
            elif part.startswith("lag ="):
                try:
                    lag_part = part.replace("lag =", "").strip()
                    lag = int(lag_part.split()[0])
                    if "(" in lag_part and ")" in lag_part:
                        direction = lag_part[lag_part.index("(") + 1: lag_part.index(")")]
                except (ValueError, IndexError):
                    pass
        ma = str(spec.get("metric_a") or "")
        mb = str(spec.get("metric_b") or "")
        if r_val is not None:
            strength = "very strong" if abs(r_val) >= 0.8 else ("strong" if abs(r_val) >= 0.6 else ("moderate" if abs(r_val) >= 0.4 else "weak"))
            direc_label = "positive" if r_val >= 0 else "negative"
            insight_text = (
                f"{ma} and {mb} show a {strength} {direc_label} correlation (r = {r_val:.2f})"
                + (f" with {direction} relationship (lag {lag})." if lag and direction else ".")
            )
            narrative_text = (
                f"Scatter plot of {ma} vs {mb}: Pearson r = {r_val:.2f}, indicating a {strength} {direc_label} "
                f"linear relationship. "
                + (f"The series leads by {lag} period{'s' if lag != 1 else ''} ({direction})." if lag and direction else "")
            )
            stats_json.update({"pearson_r": round(r_val, 4), "lag": lag, "direction": direction, "metric_a": ma, "metric_b": mb})

    elif chart_type == "rolling_correlation":
        rolling_vals = [r.get("rolling_r") for r in data if r.get("rolling_r") is not None]
        ma = str(spec.get("metric_a") or "")
        mb = str(spec.get("metric_b") or "")
        if rolling_vals:
            r_min = round(min(rolling_vals), 3)
            r_max = round(max(rolling_vals), 3)
            r_range = round(r_max - r_min, 3)
            is_stable = r_range < 0.3
            insight_text = (
                f"Rolling correlation between {ma} and {mb} ranges from {r_min:.2f} to {r_max:.2f}. "
                f"Relationship is {'stable' if is_stable else 'unstable'}."
            )
            narrative_text = (
                f"The rolling correlation for {ma} × {mb} varies between {r_min:.2f} and {r_max:.2f} "
                f"(spread = {r_range:.2f}). "
                + ("This narrow range indicates a stable, consistent relationship over time."
                   if is_stable else
                   "This wide spread indicates the relationship changes over time and may not be reliable.")
            )
            stats_json.update({"r_min": r_min, "r_max": r_max, "r_range": r_range, "is_stable": is_stable, "metric_a": ma, "metric_b": mb})

    elif chart_type == "anomaly_density":
        total = sum(r.get("count", 0) for r in data)
        high_severity = sum(r.get("count", 0) for r in data if (r.get("lo") or 0.0) >= 0.6)
        if total > 0:
            insight_text = (
                f"{total} anomaly score{'s' if total != 1 else ''} across all metrics"
                + (f", {high_severity} with high severity (score ≥ 0.6)" if high_severity else "") + "."
            )
            if metric_name:
                insight_text = insight_text.replace("all metrics", metric_name)
            narrative_text = (
                f"Anomaly score distribution{'for ' + metric_name if metric_name else ''}: "
                f"{total} total anomalies, {high_severity} high-severity (score ≥ 0.6). "
                + ("Most anomalies are concentrated in high-severity buckets, warranting immediate investigation."
                   if high_severity > total * 0.4 else
                   "Most anomalies are low-to-moderate severity.")
            )
            stats_json.update({"total_anomalies": total, "high_severity_count": high_severity})

    elif chart_type == "category_trend_grouped":
        series = spec.get("series") or []
        n_categories = len(series)
        category_names = [str(item.get("name") or item.get("id") or "") for item in series if str(item.get("name") or item.get("id") or "").strip()]
        top_categories = ", ".join(category_names[:3])
        insight_text = (
            f"{metric_name} trend across {n_categories} categor{'ies' if n_categories != 1 else 'y'} over time."
        )
        narrative_text = (
            f"This chart shows how {metric_name} changes over time for {n_categories} "
            f"categor{'ies' if n_categories != 1 else 'y'} on the same timeline. "
            + (f"The visible categories include {top_categories}. " if top_categories else "")
            + "Use it to compare relative size, turning points, and whether category trajectories are converging or diverging."
        )
        stats_json.update({"category_count": n_categories, "categories": category_names[:10]})

    elif chart_type == "category_forecast_stacked_bar":
        series = spec.get("series") or []
        n_categories = len(series)
        rows = [row for row in data if isinstance(row, dict)]
        first_row = rows[0] if rows else {}
        dominant_category = None
        dominant_value = None
        for item in series:
            field = str(item.get("id") or "")
            val = first_row.get(field)
            if isinstance(val, (int, float)) and (dominant_value is None or val > dominant_value):
                dominant_value = float(val)
                dominant_category = str(item.get("name") or field)
        insight_text = (
            f"Stacked forecast for {metric_name} across {n_categories} "
            f"categor{'ies' if n_categories != 1 else 'y'}."
        )
        narrative_text = (
            f"This stacked forecast shows how projected {metric_name} is distributed across "
            f"{n_categories} categor{'ies' if n_categories != 1 else 'y'} over the forecast horizon. "
            + (f"At the first forecast step, {dominant_category} contributes the largest share at {dominant_value:,.0f}. " if dominant_category and dominant_value is not None else "")
            + "Read it both for total projected volume and for how category mix shifts from one forecast period to the next."
        )
        stats_json.update({"category_count": n_categories, "dominant_first_period_category": dominant_category})

    elif chart_type == "metric_overlap_matrix":
        n_pairs = len(data)
        insight_text = (
            f"{n_pairs} near-duplicate metric pair{'s' if n_pairs != 1 else ''} detected (|r| ≥ 0.90). "
            "Review for semantic overlap."
        )
        narrative_text = (
            f"The overlap matrix flags {n_pairs} metric pair{'s' if n_pairs != 1 else ''} with |r| ≥ 0.90. "
            "These may represent the same underlying signal measured differently, which can inflate correlation results."
        )
        stats_json.update({"overlap_pair_count": n_pairs})

    elif chart_type == "temporal_eligibility_warning_card":
        body = spec.get("body") or []
        excluded = int((corr_chart.get("spec") or {}).get("subtitle", "").replace("Excluded snapshots: ", "").split()[0] if "Excluded snapshots:" in str((corr_chart.get("spec") or {}).get("subtitle", "")) else 0)
        insight_text = (
            f"Correlation input warnings: {len(body)} issue{'s' if len(body) != 1 else ''}. "
            + (body[0] if body else "")
        )
        narrative_text = (
            "This warning card explains which correlation inputs were excluded before analysis and why. "
            + (" ".join(body) if body else "Some data sources were excluded from correlation analysis.")
        )
        stats_json.update({"warning_count": len(body), "excluded_snapshot_count": excluded})

    # Final fallback
    if not insight_text:
        insight_text = subtitle or title
    if not narrative_text:
        narrative_text = subtitle or title

    return {"insight_text": insight_text, "narrative_text": narrative_text, "stats_json": stats_json}


def _scoped_conn_from_state(state: dict[str, Any], settings=None) -> ScopedConnection | None:
    """Reconstruct a ScopedConnection from the serialised dict stored in LangGraph state.

    Two-tier resolution:
    1. Full credentials stored in state["scoped_conn"] (from public.databases lookup at run start)
    2. Same-server fallback: App DB host/port/user + state["database_name"]
       (covers the common case where customer DB is on the same PostgreSQL server)
    """
    _log = logging.getLogger(__name__)
    raw = state.get("scoped_conn")
    if raw and isinstance(raw, dict):
        try:
            sc = ScopedConnection.from_dict(raw)
            _log.debug("_scoped_conn_from_state: tier-1 resolved conn=%r", sc)
            return sc
        except Exception:
            _log.exception("_scoped_conn_from_state: failed deserialising scoped_conn dict %r", raw)
    else:
        _log.warning("_scoped_conn_from_state: no scoped_conn in state (keys=%s), falling to tier-2", list(state.keys()))

    # Tier 2: same server as App DB, different database name
    db_name = str(state.get("database_name") or "").strip()
    if db_name and settings is not None:
        sc2 = ScopedConnection(
            connection_id=str(state.get("connection_id") or ""),
            host=settings.db_host,
            port=int(settings.db_port or 5432),
            user=settings.db_user,
            password=settings.db_password,
            database_name=db_name,
            schema_name=str(state.get("schema_name") or "public"),
        )
        _log.info("_scoped_conn_from_state: tier-2 fallback conn=%r", sc2)
        return sc2
    _log.warning("_scoped_conn_from_state: returning None — no scoped_conn and no database_name in state")
    return None


def run_agentic_workflow(
    settings,
    run_id: str,
    initial_state: dict[str, Any],
    event_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    if StateGraph is None:
        raise RuntimeError("LangGraph is not available. Install the 'langgraph' package in the active runtime environment.")

    logger = logging.getLogger(__name__)
    if is_data_quality_workflow(initial_state.get("domain_id"), initial_state):
        logger.info(
            "agentic.workflow.route | run_id=%s tenant=%s domain=%s workflow_kind=data_quality",
            run_id,
            initial_state.get("tenant_id"),
            initial_state.get("domain_id"),
        )
        return run_data_quality_agentic_workflow(settings, run_id, initial_state, event_callback=event_callback)

    phase52_build_version = "2026-04-04-phase52-v1"
    logger.info(
        "agentic.workflow.start | run_id=%s tenant=%s domain=%s schema=%s connection_id=%s database=%s anomaly_enabled=%s anomaly_dashboard_enabled=%s anomaly_llm_mode=%s build_version=%s",
        run_id,
        initial_state.get("tenant_id"),
        initial_state.get("domain_id"),
        initial_state.get("schema_name"),
        initial_state.get("connection_id"),
        initial_state.get("database_name"),
        _env_bool("AGENTIC_ANOMALY_DETECTION_ENABLED", True),
        _env_bool("AGENTIC_ANOMALY_DASHBOARD_ENABLED", True),
        os.getenv("AGENTIC_ANOMALY_LLM_MODE", "auto"),
        phase52_build_version,
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
            scoped_conn=_scoped_conn_from_state(state, settings),
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
        try:
            state["profiling_stats"] = profile_tables(
                settings,
                state.get("schema_graph", {}),
                schema_name,
                scoped_conn=_scoped_conn_from_state(state, settings),
            )
        except Exception:
            logger.exception("agentic.profiling.failed | run_id=%s — profile_tables raised, continuing with empty stats", run_id)
            _emit(settings, run_id, "ProfilingAgent", "failed", "Profiling failed — continuing with empty stats", event_callback=event_callback)
            state["profiling_stats"] = {"tables": []}
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
            "agentic.context.input | run_id=%s has_context_text=%s context_len=%s context_ids=%s",
            run_id,
            bool(context_text),
            len(str(context_text or "")),
            len(state.get("context_ids") or []),
        )
        try:
            extracted = extract_context(settings, context_text, state.get("schema_graph", {}))
        except Exception as exc:
            error_artifacts = {
                "error_message": str(exc),
                "error_type": exc.__class__.__name__,
                "traceback": traceback.format_exc(limit=12),
                "context_len": len(str(context_text or "")),
                "context_ids": len(state.get("context_ids") or []),
            }
            logger.exception("agentic.context.failed | run_id=%s", run_id)
            _emit(
                settings,
                run_id,
                "ContextAgent",
                "failed",
                "Context Agent failed",
                error_artifacts,
                event_callback=event_callback,
            )
            raise
        state["context_entities"] = extracted.get("context_entities", [])
        state["hierarchy_hints"] = extracted.get("hierarchy_hints", [])
        state["glossary_terms"] = extracted.get("glossary_terms", [])
        state["metric_overrides"] = extracted.get("metric_overrides", [])
        if not state["glossary_terms"] and state.get("schema_graph"):
            # fallback if context extraction yielded nothing
            extracted = extract_context(settings, None, state.get("schema_graph", {}))
            state["context_entities"] = extracted.get("context_entities", [])
            state["hierarchy_hints"] = extracted.get("hierarchy_hints", [])
            state["glossary_terms"] = extracted.get("glossary_terms", [])
            state["metric_overrides"] = extracted.get("metric_overrides", [])
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
                "metric_overrides": state.get("metric_overrides") or [],
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
            # Build heuristic fallback first
            heuristic_terms = []
            for table in state["profiling_stats"].get("tables", []):
                name = table.get("name")
                if name:
                    heuristic_terms.append({"term": name.replace("_", " "), "synonyms": [name], "abbreviations": []})
                for col in (table.get("numeric_columns") or []) + (table.get("time_columns") or []) + (
                    table.get("categorical_columns") or []
                ):
                    heuristic_terms.append({"term": col.replace("_", " "), "synonyms": [col], "abbreviations": []})
            # LLM enrichment: generate proper business glossary definitions
            _glossary_system_prompt = (
                "You are a domain expert who creates precise business glossaries for operational databases.\n"
                "Given a schema (tables and columns) and optional business context, return a JSON object:\n"
                "{\"glossary\": [{\"term\": \"...\", \"definition\": \"one-line business definition\", "
                "\"synonyms\": [\"...\"], \"abbreviations\": [\"...\"]}]}\n"
                "Rules:\n"
                "- Use plain English. Avoid technical jargon unless it is a recognised industry term.\n"
                "- Use business context to infer the correct domain meaning of ambiguous column names.\n"
                "- For table names, give a definition of what the table represents as a business entity.\n"
                "- For column names, give the business meaning of what the value represents.\n"
                "- Synonyms and abbreviations may be empty lists if none apply.\n"
                "- Return ONLY valid JSON — no markdown, no code fences."
            )
            tables_summary = []
            for table in state["profiling_stats"].get("tables", []):
                tables_summary.append({
                    "table": table.get("name"),
                    "columns": (table.get("numeric_columns") or []) + (table.get("time_columns") or []) + (table.get("categorical_columns") or []),
                    "row_count": table.get("row_count"),
                })
            _glossary_payload = {
                "context": (state.get("context_text") or "")[:4000],
                "schema": tables_summary,
            }
            llm_glossary = _llm_json_response(
                settings,
                system_prompt=_glossary_system_prompt,
                user_payload=_glossary_payload,
                model_env_key="AGENTIC_CONTEXT_METRIC_MODEL",
                timeout_env_key="AGENTIC_CONTEXT_METRIC_TIMEOUT_SEC",
            )
            llm_terms = (llm_glossary or {}).get("glossary") or []
            if llm_terms and isinstance(llm_terms, list):
                logger.info("agentic.glossary.llm_enriched | run_id=%s llm_terms=%s", run_id, len(llm_terms))
                state["glossary_terms"] = [
                    {
                        "term": t.get("term", ""),
                        "definition": t.get("definition", ""),
                        "synonyms": t.get("synonyms") or [],
                        "abbreviations": t.get("abbreviations") or [],
                    }
                    for t in llm_terms if t.get("term")
                ]
            else:
                logger.info("agentic.glossary.llm_fallback | run_id=%s using heuristic terms=%s", run_id, len(heuristic_terms))
                state["glossary_terms"] = heuristic_terms
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
        # Heuristic baseline
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
        # LLM enrichment: infer entity hierarchies and relationships
        _ontology_system_prompt = (
            "You are a data architect who infers business entity ontologies from database schemas.\n"
            "Given a schema (tables, columns) and optional business context, return a JSON object:\n"
            "{\n"
            "  \"concepts\": [\"EntityName\", ...],\n"
            "  \"hierarchy_edges\": [{\"parent\": \"...\", \"child\": \"...\", \"confidence\": 0.8, \"source\": \"llm\"}],\n"
            "  \"synonym_edges\": [{\"term\": \"...\", \"synonym\": \"...\", \"confidence\": 0.7, \"source\": \"llm\"}]\n"
            "}\n"
            "Rules:\n"
            "- Concepts are business entity names (e.g. 'Zone', 'Distributor', 'Product', 'Outlet').\n"
            "- Hierarchy edges represent is-a, part-of, or belongs-to relationships between entities.\n"
            "- Synonym edges map column/table names to their business aliases.\n"
            "- Use business context to identify meaningful hierarchies (e.g. Region > Zone > Outlet).\n"
            "- Return ONLY valid JSON — no markdown, no code fences."
        )
        tables_summary = [
            {"table": t.get("name"), "columns": (t.get("numeric_columns") or []) + (t.get("time_columns") or []) + (t.get("categorical_columns") or [])}
            for t in (state.get("profiling_stats") or {}).get("tables", [])
        ]
        _ontology_payload = {
            "context": (state.get("context_text") or "")[:4000],
            "schema": tables_summary,
            "existing_concepts": ontology.get("concepts", [])[:20],
        }
        llm_ontology = _llm_json_response(
            settings,
            system_prompt=_ontology_system_prompt,
            user_payload=_ontology_payload,
            model_env_key="AGENTIC_CONTEXT_METRIC_MODEL",
            timeout_env_key="AGENTIC_CONTEXT_METRIC_TIMEOUT_SEC",
        )
        if llm_ontology and isinstance(llm_ontology, dict):
            llm_concepts = llm_ontology.get("concepts") or []
            llm_edges = llm_ontology.get("hierarchy_edges") or []
            llm_synonyms = llm_ontology.get("synonym_edges") or []
            if llm_concepts or llm_edges:
                logger.info(
                    "agentic.ontology.llm_enriched | run_id=%s concepts=%s hierarchy_edges=%s synonym_edges=%s",
                    run_id, len(llm_concepts), len(llm_edges), len(llm_synonyms),
                )
                ontology["concepts"] = llm_concepts
                ontology["hierarchy_edges"] = llm_edges
                ontology["synonym_edges"] = llm_synonyms
            else:
                logger.info("agentic.ontology.llm_empty | run_id=%s keeping heuristic ontology", run_id)
        else:
            logger.info("agentic.ontology.llm_fallback | run_id=%s using heuristic ontology", run_id)
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
                rows = run_query(settings, sql, [], scoped_conn=_scoped_conn_from_state(state, settings))
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
        llm_metric_candidates, llm_metric_diag = _llm_propose_context_metrics(
            settings,
            domain_id=state.get("domain_id"),
            context_text=state.get("context_text"),
            schema_graph=state.get("schema_graph", {}) or {},
            profiling=state.get("profiling_stats", {}) or {},
            glossary_terms=state.get("glossary_terms") or [],
        )
        validated_context_metrics, rejected_context_metrics = validate_metric_candidates(
            llm_metric_candidates,
            state.get("profiling_stats", {}) or {},
            domain_id=state.get("domain_id"),
        )
        state["context_metric_diagnostics"] = {
            "proposal": llm_metric_diag,
            "accepted_count": len(validated_context_metrics),
            "rejected_count": len(rejected_context_metrics),
            "accepted_metrics": [
                {
                    "metric_name": m.get("metric_name"),
                    "base_table": m.get("base_table"),
                    "grain": m.get("grain"),
                    "preferred_time_column": m.get("preferred_time_column"),
                }
                for m in validated_context_metrics
            ],
            "rejected_metrics": rejected_context_metrics[:10],
        }
        combined_metric_overrides: list[dict[str, Any]] = []
        seen_override_keys: set[tuple[str, str]] = set()
        for metric in validated_context_metrics + (state.get("metric_overrides") or []):
            key = (str(metric.get("base_table") or ""), str(metric.get("metric_name") or ""))
            if not key[0] or not key[1] or key in seen_override_keys:
                continue
            seen_override_keys.add(key)
            combined_metric_overrides.append(metric)
        state["metric_defs"] = propose_metrics(
            state.get("profiling_stats", {}),
            domain_id=state.get("domain_id"),
            metric_overrides=combined_metric_overrides,
        )
        metric_rerank_ids, metric_rerank_diag = _llm_rerank_metric_candidates(
            settings,
            domain_id=state.get("domain_id"),
            profiling=state.get("profiling_stats", {}) or {},
            metrics=state.get("metric_defs") or [],
        )
        if metric_rerank_ids:
            metric_id_lookup: dict[str, dict[str, Any]] = {}
            for idx, metric in enumerate(state.get("metric_defs") or [], start=1):
                metric_id_lookup[f"metric_{idx}"] = metric
            reranked_metrics: list[dict[str, Any]] = []
            seen_metric_names: set[tuple[str, str]] = set()
            for rank, metric_id in enumerate(metric_rerank_ids):
                metric = metric_id_lookup.get(metric_id)
                if not metric:
                    continue
                key = (str(metric.get("base_table") or ""), str(metric.get("metric_name") or ""))
                if key in seen_metric_names:
                    continue
                seen_metric_names.add(key)
                boosted = dict(metric)
                boosted["llm_priority_boost"] = max(0.0, 60.0 - (rank * 5.0))
                boosted["llm_rank"] = rank + 1
                reranked_metrics.append(boosted)
            for metric in state.get("metric_defs") or []:
                key = (str(metric.get("base_table") or ""), str(metric.get("metric_name") or ""))
                if key in seen_metric_names:
                    continue
                reranked_metrics.append(metric)
            state["metric_defs"] = reranked_metrics
        state["metric_rerank_diagnostics"] = metric_rerank_diag
        logger.info(
            "agentic.metrics.output | run_id=%s metrics=%s metric_context=%s metric_rerank=%s sample=%s",
            run_id,
            len(state.get("metric_defs") or []),
            state.get("context_metric_diagnostics"),
            metric_rerank_diag,
            [
                {
                    "name": m.get("metric_name"),
                    "table": m.get("base_table"),
                    "type": m.get("metric_type"),
                    "eligible_measure": m.get("eligible_measure"),
                    "intent": m.get("metric_intent"),
                    "source": m.get("metric_source"),
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
                "context_metric_diagnostics": state.get("context_metric_diagnostics"),
                "metric_rerank_diagnostics": metric_rerank_diag,
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
        # Heuristic classification baseline
        heuristic_classifications = classify_models(state.get("profiling_stats", {}))
        # LLM enrichment: classify fact vs dimension using business context
        _model_system_prompt = (
            "You are a data modelling expert who classifies database tables as fact or dimension tables.\n"
            "Given table profiling statistics and optional business context, return a JSON object:\n"
            "{\"classifications\": [{\"table\": \"...\", \"model_type\": \"fact|dimension\", "
            "\"confidence\": 0.9, \"reasoning\": \"one sentence explanation\"}]}\n"
            "Rules:\n"
            "- Fact tables: transactional records, time-series measurements, event logs, operational data. "
            "Typically contain numeric measures, timestamps, and foreign keys to dimensions.\n"
            "- Dimension tables: master data, reference data, lookup tables. "
            "Typically contain descriptive attributes, names, codes, categories.\n"
            "- Use the business context to resolve ambiguous tables — e.g. an 'alerts' table in fuel monitoring "
            "is a fact table even if it has few numeric columns.\n"
            "- confidence: 0.9 if clear, 0.7 if somewhat ambiguous, 0.5 if genuinely uncertain.\n"
            "- Return ONLY valid JSON — no markdown, no code fences."
        )
        tables_profile = []
        for t in (state.get("profiling_stats") or {}).get("tables", []):
            tables_profile.append({
                "table": t.get("name"),
                "row_count": t.get("row_count"),
                "numeric_columns": t.get("numeric_columns") or [],
                "time_columns": t.get("time_columns") or [],
                "categorical_columns": (t.get("categorical_columns") or [])[:10],
            })
        _model_payload = {
            "context": (state.get("context_text") or "")[:4000],
            "tables": tables_profile,
        }
        llm_model = _llm_json_response(
            settings,
            system_prompt=_model_system_prompt,
            user_payload=_model_payload,
            model_env_key="AGENTIC_CONTEXT_METRIC_MODEL",
            timeout_env_key="AGENTIC_CONTEXT_METRIC_TIMEOUT_SEC",
        )
        llm_classifications = (llm_model or {}).get("classifications") or []
        if llm_classifications and isinstance(llm_classifications, list):
            # Validate and merge: only keep entries that have table + model_type
            valid_llm = [
                {
                    "table": c.get("table"),
                    "model_type": c.get("model_type", "fact") if c.get("model_type") in ("fact", "dimension") else "fact",
                    "confidence": float(c.get("confidence") or 0.7),
                    "reasoning": c.get("reasoning", ""),
                    "numeric_columns": next((h.get("numeric_columns", 0) for h in heuristic_classifications if h.get("table") == c.get("table")), 0),
                    "time_columns": next((h.get("time_columns", 0) for h in heuristic_classifications if h.get("table") == c.get("table")), 0),
                    "categorical_columns": next((h.get("categorical_columns", 0) for h in heuristic_classifications if h.get("table") == c.get("table")), 0),
                }
                for c in llm_classifications if c.get("table")
            ]
            logger.info("agentic.model.llm_enriched | run_id=%s models=%s", run_id, len(valid_llm))
            state["model_classifications"] = valid_llm
        else:
            logger.info("agentic.model.llm_fallback | run_id=%s using heuristic classifications=%s", run_id, len(heuristic_classifications))
            state["model_classifications"] = heuristic_classifications
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
        # Heuristic rollup baseline
        heuristic_rollups = propose_rollups(state.get("metric_defs", []), state.get("profiling_stats", {}))
        # LLM enrichment: propose analytically meaningful rollup dimensions using business context
        _rollup_system_prompt = (
            "You are a business intelligence architect who designs metric rollup tables.\n"
            "Given metric definitions, table profiling data, and business context, propose the most "
            "analytically useful rollup dimensions and time grains for each metric.\n"
            "Return a JSON object:\n"
            "{\"rollups\": [{\"metric_name\": \"...\", \"dimensions\": [\"time_col\", \"category_col\"], "
            "\"time_grain\": \"day|week|month|quarter|year\", \"reasoning\": \"...\"}]}\n"
            "Rules:\n"
            "- dimensions[0] MUST be the primary time column for the metric's table.\n"
            "- dimensions[1..n] should be the most analytically meaningful categoricals "
            "(e.g. prefer 'zone', 'product_code', 'region' over generic IDs).\n"
            "- Use business context to identify which categoricals are operationally important.\n"
            "- time_grain should reflect the operational reporting cadence from the business context.\n"
            "- Only include rollups for metrics that exist in the provided metric_defs list.\n"
            "- Return ONLY valid JSON — no markdown, no code fences."
        )
        metrics_summary = [
            {"metric_name": m.get("metric_name"), "base_table": m.get("base_table"), "formula": m.get("formula")}
            for m in (state.get("metric_defs") or [])[:20]
        ]
        tables_profile = []
        for t in (state.get("profiling_stats") or {}).get("tables", []):
            tables_profile.append({
                "table": t.get("name"),
                "time_columns": t.get("time_columns") or [],
                "categorical_columns": (t.get("categorical_columns") or [])[:10],
                "sample_values": {
                    col: (t.get("sample_values") or {}).get(col, [])[:5]
                    for col in (t.get("categorical_columns") or [])[:5]
                },
            })
        _rollup_payload = {
            "context": (state.get("context_text") or "")[:3000],
            "metric_defs": metrics_summary,
            "tables": tables_profile,
        }
        llm_rollup = _llm_json_response(
            settings,
            system_prompt=_rollup_system_prompt,
            user_payload=_rollup_payload,
            model_env_key="AGENTIC_CONTEXT_METRIC_MODEL",
            timeout_env_key="AGENTIC_CONTEXT_METRIC_TIMEOUT_SEC",
        )
        llm_rollups = (llm_rollup or {}).get("rollups") or []
        if llm_rollups and isinstance(llm_rollups, list):
            valid_llm_rollups = [
                {
                    "metric_name": r.get("metric_name"),
                    "dimensions": r.get("dimensions") or [],
                    "time_grain": r.get("time_grain", "month") if r.get("time_grain") in ("day", "week", "month", "quarter", "year") else "month",
                }
                for r in llm_rollups if r.get("metric_name") and r.get("dimensions")
            ]
            logger.info("agentic.rollup.llm_enriched | run_id=%s candidates=%s", run_id, len(valid_llm_rollups))
            rollups = valid_llm_rollups
        else:
            logger.info("agentic.rollup.llm_fallback | run_id=%s using heuristic candidates=%s", run_id, len(heuristic_rollups))
            rollups = heuristic_rollups
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
            8,
        )
        max_charts = _resolve_int_setting(
            state,
            "chart_max_charts",
            "AGENTIC_CHART_MAX_CHARTS",
            16,
        )
        if min_charts > max_charts:
            min_charts = max_charts
        # Pre-load persisted hierarchies so select_charts can score hierarchy columns
        # correctly even on first run (before dashboard_node bootstraps them).
        if not state.get("business_hierarchies"):
            try:
                _pre_hierarchies = list_business_hierarchies(
                    settings,
                    str(state.get("tenant_id") or ""),
                    str(state.get("domain_id") or "") or None,
                )
                if _pre_hierarchies:
                    state["business_hierarchies"] = _pre_hierarchies
            except Exception:
                pass
        deterministic_candidates = propose_chart_candidates(
            state.get("profiling_stats", {}),
            state.get("metric_defs", []),
            state.get("join_edges", []),
            domain_id=state.get("domain_id"),
            business_hierarchies=state.get("business_hierarchies") if isinstance(state.get("business_hierarchies"), list) else None,
        )
        llm_candidates_raw, llm_chart_diag = _llm_propose_chart_candidates(
            settings,
            domain_id=state.get("domain_id"),
            profiling=state.get("profiling_stats", {}) or {},
            metrics=state.get("metric_defs", []) or [],
            context_text=state.get("context_text"),
            business_hierarchies=state.get("business_hierarchies") if isinstance(state.get("business_hierarchies"), list) else None,
        )
        llm_candidates, llm_candidate_rejections = _validate_llm_chart_candidates(
            llm_candidates_raw,
            profiling=state.get("profiling_stats", {}) or {},
            metrics=state.get("metric_defs", []) or [],
        )
        candidates = list(llm_candidates or [])
        seen_candidate_keys = {
            (
                cand.get("table"),
                cand.get("metric"),
                cand.get("compare_metric"),
                cand.get("type"),
                cand.get("intent"),
                cand.get("category_column"),
                cand.get("time_column"),
                cand.get("time_grain"),
            )
            for cand in candidates
        }
        for cand in deterministic_candidates:
            key = (
                cand.get("table"),
                cand.get("metric"),
                cand.get("compare_metric"),
                cand.get("type"),
                cand.get("intent"),
                cand.get("category_column"),
                cand.get("time_column"),
                cand.get("time_grain"),
            )
            if key in seen_candidate_keys:
                continue
            seen_candidate_keys.add(key)
            candidates.append(cand)
        selected, selection_diag = select_charts(
            candidates,
            min_charts=min_charts,
            max_charts=max_charts,
            domain_id=state.get("domain_id"),
            business_hierarchies=state.get("business_hierarchies") if isinstance(state.get("business_hierarchies"), list) else None,
        )
        reranked, rerank_diag = _llm_rerank_chart_candidates(
            settings,
            domain_id=state.get("domain_id"),
            profiling=state.get("profiling_stats", {}) or {},
            candidates=candidates,
            min_charts=min_charts,
            max_charts=max_charts,
        )
        if reranked:
            selected_keys = {
                (
                    cand.get("table"),
                    cand.get("metric"),
                    cand.get("compare_metric"),
                    cand.get("type"),
                    cand.get("category_column"),
                    cand.get("time_column"),
                    cand.get("time_grain"),
                )
                for cand in selected
            }
            for cand in selected:
                key = (
                    cand.get("table"),
                    cand.get("metric"),
                    cand.get("compare_metric"),
                    cand.get("type"),
                    cand.get("category_column"),
                    cand.get("time_column"),
                    cand.get("time_grain"),
                )
                if key not in {
                    (
                        item.get("table"),
                        item.get("metric"),
                        item.get("compare_metric"),
                        item.get("type"),
                        item.get("category_column"),
                        item.get("time_column"),
                        item.get("time_grain"),
                    )
                    for item in reranked
                }:
                    reranked.append(cand)
                if len(reranked) >= max_charts:
                    break
            selected, selection_diag = select_charts(
                reranked[: max(max_charts * 2, len(reranked))],
                min_charts=min_charts,
                max_charts=max_charts,
                domain_id=state.get("domain_id"),
                business_hierarchies=state.get("business_hierarchies") if isinstance(state.get("business_hierarchies"), list) else None,
            )
        rejected = [cand for cand in candidates if cand.get("skipped")] + list(llm_candidate_rejections or [])
        logger.info(
            "agentic.chart_planner.output | run_id=%s candidates=%s llm_candidates=%s selected=%s rejected=%s llm_proposal=%s llm_rerank=%s sample_selected=%s",
            run_id,
            len(candidates),
            len(llm_candidates or []),
            len(selected),
            len(rejected),
            llm_chart_diag,
            rerank_diag,
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
        state["chart_proposal_diagnostics"] = llm_chart_diag
        state["chart_rerank_diagnostics"] = rerank_diag
        state["chart_selection_diagnostics"] = selection_diag
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
                "chart_proposal_diagnostics": llm_chart_diag,
                "chart_rerank_diagnostics": rerank_diag,
                "chart_selection_diagnostics": selection_diag,
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
        _emit(
            settings,
            run_id,
            "DashboardAgent",
            "running",
            "phase52-dashboard-node-entered",
            {
                "build_version": phase52_build_version,
                "tenant_id": state.get("tenant_id"),
                "domain_id": state.get("domain_id"),
            },
            event_callback=event_callback,
        )
        dashboard_start = time.perf_counter()
        min_charts = _resolve_int_setting(
            state,
            "chart_min_charts",
            "AGENTIC_CHART_MIN_CHARTS",
            8,
        )
        max_charts = _resolve_int_setting(
            state,
            "chart_max_charts",
            "AGENTIC_CHART_MAX_CHARTS",
            16,
        )
        if min_charts > max_charts:
            min_charts = max_charts
        dashboard_spec = build_dashboard_spec(
            state.get("metric_defs", []),
            state.get("profiling_stats", {}),
            domain_id=state.get("domain_id"),
            chart_plan=state.get("chart_plan") or [],
            context_text=state.get("context_text"),
        )
        dashboard_title = (dashboard_spec.get("title") or "").strip()
        if not dashboard_title:
            domain_label = str(state.get("domain_id") or "Auto").replace("_", " ").replace("-", " ").strip()
            dashboard_title = f"{domain_label.title()} Dashboard" if domain_label else "Auto Dashboard"
        dashboard_spec["title"] = dashboard_title
        dashboard_spec["dashboard_title"] = dashboard_title
        charts_spec = state.get("chart_plan") or dashboard_spec.get("charts", [])
        composed_charts, dashboard_comp_diag = _llm_compose_dashboard(
            settings,
            domain_id=state.get("domain_id"),
            chart_candidates=charts_spec,
            min_charts=min(min_charts, len(charts_spec) or min_charts),
            max_charts=min(max_charts, max(len(charts_spec), min_charts)),
        )
        if composed_charts:
            charts_spec = composed_charts
        dashboard_spec["dashboard_composition_diagnostics"] = dashboard_comp_diag
        dashboard_spec["charts"] = charts_spec
        logger.info(
            "agentic.dashboard.input | run_id=%s charts_spec=%s metrics=%s profiling_tables=%s composition=%s",
            run_id,
            len(charts_spec or []),
            len(state.get("metric_defs") or []),
            len((state.get("profiling_stats") or {}).get("tables") or []),
            dashboard_comp_diag,
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
        runtime_chart_rejections: list[dict[str, Any]] = []
        _forced_hierarchy_specs: list[dict] = []  # hierarchy-injected charts preserved across charts_spec resets
        ensured_hierarchies: list[dict] = []  # populated in try block below; declared here for wider scope
        profiling_map = {t.get("name"): t for t in (state.get("profiling_stats", {}).get("tables") or [])}
        join_edges = state.get("join_edges") or []
        logger.info(
            "agentic.hierarchies.block_entered | run_id=%s tenant_id=%s domain_id=%s build_version=%s join_edge_count=%s profiled_table_count=%s",
            run_id,
            state.get("tenant_id"),
            state.get("domain_id"),
            phase52_build_version,
            len(join_edges),
            len((state.get("profiling_stats", {}).get("tables") or [])),
        )
        try:
            _emit(
                settings,
                run_id,
                "HierarchyBootstrapAgent",
                "running",
                "Hierarchy bootstrap started",
                artifacts={
                    "build_version": phase52_build_version,
                    "tenant_id": state.get("tenant_id"),
                    "domain_id": state.get("domain_id"),
                    "phase52_chart_interactions_enabled": True,
                    "hierarchy_bootstrap_enabled": True,
                    "join_edge_count": len(join_edges),
                    "profiled_table_count": len((state.get("profiling_stats", {}).get("tables") or [])),
                },
                event_callback=event_callback,
            )
            logger.info(
                "agentic.hierarchies.bootstrap_start | run_id=%s tenant_id=%s domain_id=%s build_version=%s phase52_chart_interactions_enabled=%s hierarchy_bootstrap_enabled=%s join_edge_count=%s",
                run_id,
                state.get("tenant_id"),
                state.get("domain_id"),
                phase52_build_version,
                True,
                True,
                len(join_edges),
            )
            ensured_hierarchies = ensure_business_hierarchies(
                settings,
                tenant_id=str(state.get("tenant_id") or ""),
                domain_id=str(state.get("domain_id") or ""),
                profiling_stats=state.get("profiling_stats") or {},
                context_text=state.get("context_text"),
                join_edges=join_edges,
            )
            state["business_hierarchies"] = ensured_hierarchies
            # Back-fill drill_hierarchy_id on chart_plan items now that hierarchies
            # are available. chart_planner_node runs before the bootstrap, so any
            # hierarchy-linked breakdown columns would have been left unbound.
            if ensured_hierarchies and state.get("chart_plan"):
                for _cp_item in state["chart_plan"]:
                    if _cp_item.get("drill_hierarchy_id"):
                        continue
                    _cp_cat = str(_cp_item.get("category_column") or "").strip()
                    if not _cp_cat:
                        continue
                    _cp_table = str(_cp_item.get("table") or "").strip()
                    _cp_profile = profiling_map.get(_cp_table) or {}
                    _cp_bindings = _hierarchy_breakdown_bindings(_cp_profile, ensured_hierarchies)
                    for _b in _cp_bindings:
                        if str(_b.get("column") or "").strip().lower() == _cp_cat.lower():
                            _cp_item["drill_hierarchy_id"] = _b.get("hierarchy_id")
                            _cp_item["drill_level_id"] = _b.get("level_id")
                            break
            # Guarantee at least one hierarchy-backed breakdown chart in charts_spec.
            # chart_planner_node runs before hierarchy bootstrap, so it often selects
            # non-hierarchy columns (e.g. terminal_plant_name) when hierarchy data
            # is unavailable. Inject top-level hierarchy bar charts here if missing.
            if ensured_hierarchies and charts_spec is not None:
                _hierarchy_cols_present = {
                    str(item.get("category_column") or "").strip().lower()
                    for item in charts_spec
                    if item.get("drill_hierarchy_id")
                }
                # Build a lookup: base_table → best (executive KPI) metric
                _metric_by_table: dict[str, dict] = {}
                _sorted_metrics = sorted(
                    (state.get("metric_defs") or []),
                    key=lambda _m: (
                        0 if _m.get("is_executive_kpi") else 1,
                        -float(_m.get("metric_priority") or 0),
                        -float(_m.get("measure_confidence") or 0),
                    ),
                )
                for _m in _sorted_metrics:
                    _mt = str(_m.get("base_table") or "").strip()
                    if _mt and _mt not in _metric_by_table:
                        _metric_by_table[_mt] = _m
                for _hier in ensured_hierarchies:
                    if not bool(_hier.get("preferred")):
                        continue
                    _levels = _hier.get("levels_json") or []
                    _base_table = str((_hier.get("base_scope_json") or {}).get("base_table") or "").strip()
                    _top_metric = _metric_by_table.get(_base_table)
                    if not _levels or not _base_table or not _top_metric:
                        continue
                    _table_profile = profiling_map.get(_base_table) or {}
                    _cat_cols_lower = {str(c).lower() for c in (_table_profile.get("categorical_columns") or [])}
                    # Build a blank_pct lookup from column_profiles so we can auto-filter
                    # sparse hierarchy columns (e.g. equipment_type at 94% blank).
                    _col_blank_pct: dict[str, float] = {
                        str(cp.get("name") or "").lower(): float(cp.get("blank_pct") or 0.0)
                        for cp in (_table_profile.get("column_profiles") or [])
                        if cp.get("name")
                    }
                    _BLANK_FILTER_THRESHOLD = 20.0  # add blank guard when >20% of rows are blank
                    for _lvl in _levels:
                        _col = str(_lvl.get("column") or _lvl.get("level_id") or "").strip()
                        if not _col or _col.lower() in {"bu", "business_unit"}:
                            continue
                        if _col.lower() not in _cat_cols_lower:
                            continue
                        if _col.lower() in _hierarchy_cols_present:
                            break  # already have a chart for this hierarchy's top level
                        # Use metric formula if available; fall back to COUNT(*) so the
                        # chart is never skipped due to a missing metric expression.
                        _inj_metric_expr = _top_metric.get("formula") or "COUNT(*)"
                        _col_is_sparse = _col_blank_pct.get(_col.lower(), 0.0) > _BLANK_FILTER_THRESHOLD
                        _injected = {
                            "type": "bar",
                            "intent": "breakdown",
                            "title": f"{_top_metric.get('display_name') or _top_metric.get('metric_name', 'Metric')} by {_col.replace('_', ' ').title()}",
                            "table": _base_table,
                            "metric": _top_metric.get("metric_name"),
                            "metric_intent": _top_metric.get("metric_intent"),
                            "metric_expr": _inj_metric_expr,
                            "time_column": None,
                            "time_grain": None,
                            "category_column": _col,
                            "drill_hierarchy_id": str(_hier.get("hierarchy_id") or ""),
                            "drill_level_id": str(_lvl.get("level_id") or _col),
                            "chart_source": "hierarchy_injected",
                            # Flag sparse columns so the SQL builder adds blank exclusion guard.
                            "category_blank_filter": _col_is_sparse,
                        }
                        charts_spec.append(_injected)
                        _forced_hierarchy_specs.append(_injected)
                        logger.info(
                            "agentic.hierarchy.chart_injected | run_id=%s hierarchy_id=%s column=%s table=%s metric=%s",
                            run_id,
                            _hier.get("hierarchy_id"),
                            _col,
                            _base_table,
                            _top_metric.get("metric_name"),
                        )
                        _hierarchy_cols_present.add(_col.lower())
                        break  # one injection per preferred hierarchy
            _emit(
                settings,
                run_id,
                "HierarchyBootstrapAgent",
                "completed",
                "Hierarchy bootstrap completed",
                artifacts={
                    "build_version": phase52_build_version,
                    "tenant_id": state.get("tenant_id"),
                    "domain_id": state.get("domain_id"),
                    "persisted_count": len(ensured_hierarchies),
                    "hierarchy_ids": [str(item.get("hierarchy_id") or "") for item in ensured_hierarchies[:20]],
                },
                event_callback=event_callback,
            )
            logger.info(
                "agentic.hierarchies.ready | run_id=%s tenant_id=%s domain_id=%s build_version=%s hierarchy_count=%s",
                run_id,
                state.get("tenant_id"),
                state.get("domain_id"),
                phase52_build_version,
                len(ensured_hierarchies),
            )
        except Exception:
            _tb = traceback.format_exc()
            logger.error(
                "agentic.hierarchies.failed | run_id=%s tenant_id=%s domain_id=%s build_version=%s\n%s",
                run_id,
                state.get("tenant_id"),
                state.get("domain_id"),
                phase52_build_version,
                _tb,
            )
            try:
                _emit(
                    settings,
                    run_id,
                    "HierarchyBootstrapAgent",
                    "failed",
                    "Hierarchy bootstrap failed",
                    artifacts={
                        "build_version": phase52_build_version,
                        "tenant_id": state.get("tenant_id"),
                        "domain_id": state.get("domain_id"),
                        "error": _tb,
                    },
                    event_callback=event_callback,
                )
            except Exception:
                logger.error(
                    "agentic.hierarchies.failed_emit_also_failed | run_id=%s\n%s",
                    run_id,
                    traceback.format_exc(),
                )

        # Columns covered by hierarchy drill-down navigation. Discovery charts that use
        # these as their primary x_axis (standalone breakdowns) are suppressed — the user
        # navigates them via drill-up/drill-down from the single injected hierarchy chart.
        _hierarchy_discovery_skip_cols: set[str] = {
            str(_lvl.get("column") or _lvl.get("level_id") or "").strip().lower()
            for _h in ensured_hierarchies
            for _lvl in (_h.get("levels_json") or [])
            if _lvl.get("column") or _lvl.get("level_id")
        }

        # ── Phase 47: LLM Chart Discovery ──────────────────────────────────
        discovery_chart_ids: list[str] = []
        discovery_titles: list[str] = []
        if not _chart_discovery_enabled():
            _emit(
                settings, run_id, "ChartDiscoveryAgent", "skipped",
                f"Chart discovery skipped (CHART_DISCOVERY_MODE={os.getenv('CHART_DISCOVERY_MODE', 'unset')})",
                event_callback=event_callback,
            )
        if _chart_discovery_enabled():
            profiled_table_names = [
                t.get("name") for t in (state.get("profiling_stats", {}).get("tables") or [])
                if t.get("name")
            ]
            _emit(
                settings, run_id, "ChartDiscoveryAgent", "running",
                f"Sampling data from {len(profiled_table_names)} table(s)...",
                event_callback=event_callback,
            )
            try:
                _scoped_conn = _scoped_conn_from_state(state, settings)
                table_samples = _fetch_table_samples(
                    settings,
                    table_names=profiled_table_names,
                    schema=schema_name,
                    scoped_conn=_scoped_conn,
                )
                discovery_specs, discovery_diag = _llm_chart_discovery(
                    settings,
                    domain_id=state.get("domain_id"),
                    context_text=state.get("context_text"),
                    profiling=state.get("profiling_stats") or {},
                    table_samples=table_samples,
                    schema=schema_name,
                    scoped_conn=_scoped_conn,
                )
                state["chart_discovery_diagnostics"] = discovery_diag
                # Suppress discovery charts whose primary x_axis is a hierarchy level
                # column — those dimensions are already navigable via drill-down from the
                # single injected hierarchy chart. Allow time-series charts (series_by on
                # a hierarchy column is fine — it adds context without being redundant).
                if discovery_specs and _hierarchy_discovery_skip_cols:
                    _before = len(discovery_specs)
                    discovery_specs = [
                        s for s in discovery_specs
                        if str(s.get("x_axis") or "").strip().lower()
                        not in _hierarchy_discovery_skip_cols
                    ]
                    _suppressed = _before - len(discovery_specs)
                    if _suppressed:
                        logger.info(
                            "chart_discovery.hierarchy_suppressed | run_id=%s suppressed=%s skip_cols=%s",
                            run_id, _suppressed, sorted(_hierarchy_discovery_skip_cols),
                        )
                if discovery_specs:
                    # dashboard_id not yet created — pass None, link later
                    discovery_chart_ids, discovery_titles = _execute_discovery_charts(
                        settings,
                        discovery_specs,
                        schema=schema_name,
                        tenant_id=state.get("tenant_id"),
                        domain_id=state.get("domain_id"),
                        run_id=run_id,
                        dashboard_id=None,
                        scoped_conn=_scoped_conn,
                    )
                _tool_call_log = (discovery_diag or {}).get("tool_calls") or []
                logger.info(
                    "chart_discovery.tool_call_log | run_id=%s calls=%s",
                    run_id, json.dumps(_tool_call_log, default=str),
                )
                _emit(
                    settings, run_id, "ChartDiscoveryAgent", "completed",
                    f"Discovery: {len(discovery_chart_ids)} chart(s) generated",
                    {
                        "mode": os.getenv("CHART_DISCOVERY_MODE", "discovery_only"),
                        "tool_calls_made": len(_tool_call_log),
                        "tool_call_log": _tool_call_log,
                        "llm_proposed": (discovery_diag or {}).get("proposed", 0),
                        "tool_call_limit_hit": (discovery_diag or {}).get("tool_call_limit_hit", False),
                        "context_text_chars": len(state.get("context_text") or ""),
                        "tables_sampled": len(profiled_table_names),
                        "chart_ids": discovery_chart_ids,
                    },
                    event_callback=event_callback,
                )
            except Exception as _disc_err:
                logger.warning("chart_discovery.error | run_id=%s err=%s", run_id, _disc_err, exc_info=True)
                _emit(
                    settings, run_id, "ChartDiscoveryAgent", "failed",
                    f"Chart discovery failed: {_disc_err}",
                    event_callback=event_callback,
                )
        # ── End Phase 47 ───────────────────────────────────────────────────

        if _chart_discovery_only():
            # Skip legacy chart planner entirely — jump past the for loop
            charts_spec = []
        # Always include hierarchy-injected charts regardless of discovery mode.
        if _forced_hierarchy_specs:
            charts_spec.extend(_forced_hierarchy_specs)
            logger.info(
                "agentic.hierarchy.forced_specs_restored | run_id=%s count=%s",
                run_id,
                len(_forced_hierarchy_specs),
            )

        for chart in charts_spec:
            metric_name = chart.get("metric") or "metric"
            metric_col = chart.get("metric_column")
            table_name = chart.get("table")
            time_col = chart.get("time_column")
            category_col = chart.get("category_column")
            chart_intent = str(chart.get("intent") or "").strip().lower()
            if (chart.get("type") or "bar") == "line" and chart_intent != "multi_series":
                category_col = None
            if not category_col and chart_intent in {"breakdown", "join_breakdown", "share", "multi_series"}:
                for edge in join_edges:
                    if edge.get("left_table") == table_name and edge.get("relationship") in {
                        "many_to_one",
                        "one_to_many",
                    }:
                        category_col = edge.get("left_key")
                        break
            chart["category_column"] = category_col
            chart_title = chart.get("title")
            if not chart_title:
                if chart_intent == "trend":
                    chart_title = f"{metric_name} Trend Over {time_col or 'Time'}"
                elif chart_intent in {"breakdown", "join_breakdown"}:
                    chart_title = f"{metric_name} by {category_col or 'Category'}"
                elif chart_intent == "share":
                    chart_title = f"{category_col or 'Category'} Share of {metric_name}"
                elif chart_intent == "multi_series":
                    chart_title = f"{metric_name} Trend by {category_col or 'Category'}"
                else:
                    chart_title = f"{metric_name} {chart.get('type') or 'Overview'}"
            chart["title"] = chart_title

            if table_name:
                if table_name.startswith("fact_") or table_name in profiling_map:
                    # Use the name as-is: already a fact table or a known profiled table.
                    fact_table = table_name
                else:
                    candidate = f"fact_{table_name}"
                    # Prefer the profiled name; only add prefix if the prefixed name is known.
                    fact_table = candidate if candidate in profiling_map else table_name
                table_ref = f"{schema_name}.{fact_table}"
            else:
                fact_table = None
                table_ref = None

            chart_type = chart.get("type") or "bar"
            sql = None
            params: list[Any] = []
            dimensions: list[str] = []
            rows: list[dict] = []
            policy_filters: list[str] = []

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

            # Plain time-series trends must stay single-series unless explicitly marked multi_series.
            # Comparison intents keep their multi-metric nature — do NOT strip category_col.
            if chart_type == "line" and chart_intent not in {"multi_series", "comparison", "cross_table_comparison"}:
                category_col = None

            if table_ref and metric_expr:
                table_profile = profiling_map.get(table_name) or {}
                policy_filters = _dashboard_policy_filters(
                    state.get("domain_id"),
                    table_alias,
                    table_profile,
                    table_name=table_name,
                    context_text=state.get("context_text"),
                    all_table_names=list(profiling_map.keys()),
                )
                where_clause = f" WHERE {' AND '.join(policy_filters)} " if policy_filters else " "
                if chart_type == "line":
                    if time_col:
                        time_grain = str(chart.get("time_grain") or "month").strip().lower()
                        if time_grain == "day":
                            dim_expr = f"date_trunc('day', {table_alias}.{_qident(time_col)})"
                        else:
                            dim_expr = f"date_trunc('month', {table_alias}.{_qident(time_col)})"
                        dim_alias = "period"
                        if category_col:
                            cat_alias = "category"
                            # Use a CTE to first identify the top N categories by total metric
                            # value, then show their time series.  This prevents LIMIT from
                            # cutting across categories (the old LIMIT 10 gave 10 rows total,
                            # which could be only 1-2 categories each with a few periods).
                            top_n_cats = 5
                            # Build a null-safe where clause for the category filter.
                            # NULL = NULL is always FALSE in SQL, so we must exclude NULLs
                            # in _top_cats and in the main query to avoid 0-row results.
                            cat_not_null = f"{table_alias}.{_qident(category_col)} IS NOT NULL"
                            if policy_filters:
                                top_cats_where = f" WHERE {' AND '.join(policy_filters)} AND {cat_not_null} "
                                main_where = f" WHERE {' AND '.join(policy_filters)} AND {cat_not_null} "
                            else:
                                top_cats_where = f" WHERE {cat_not_null} "
                                main_where = f" WHERE {cat_not_null} "
                            cat_expr = f"{table_alias}.{_qident(category_col)}"
                            sql = (
                                f"WITH _top_cats AS ("
                                f"SELECT {cat_expr} AS {cat_alias} "
                                f"FROM {sql_from}"
                                f"{top_cats_where}"
                                f"GROUP BY {cat_expr} "
                                f"ORDER BY {metric_expr} DESC "
                                f"LIMIT {top_n_cats}"
                                f") "
                                f"SELECT {dim_expr} AS {dim_alias}, "
                                f"{cat_expr} AS {cat_alias}, "
                                f"{metric_expr} AS \"{metric_name}\" "
                                f"FROM {sql_from} "
                                f"JOIN _top_cats ON {cat_expr} = _top_cats.{cat_alias} "
                                f"{main_where}"
                                f"GROUP BY {dim_expr}, {cat_expr} "
                                f"ORDER BY {dim_alias} DESC "
                                f"LIMIT {top_n_cats * line_single_limit}"
                            )
                            dimensions = [dim_alias, cat_alias]
                        else:
                            sql = (
                                f"SELECT {dim_expr} AS {dim_alias}, "
                                f"{metric_expr} AS \"{metric_name}\" "
                                f"FROM {sql_from}"
                                f"{where_clause}"
                                f"GROUP BY {dim_expr} "
                                f"ORDER BY {dim_alias} DESC "
                                f"LIMIT {line_single_limit}"
                            )
                            dimensions = [dim_alias]
                    elif category_col:
                        dim_alias = "category"
                        cat_expr = f"{table_alias}.{_qident(category_col)}"
                        sql = (
                            f"SELECT {cat_expr} AS {dim_alias}, "
                            f"{metric_expr} AS \"{metric_name}\" "
                            f"FROM {sql_from}"
                            f"{where_clause}"
                            f"GROUP BY {cat_expr} "
                            f"ORDER BY \"{metric_name}\" DESC "
                            f"LIMIT {category_limit}"
                        )
                        dimensions = [dim_alias]
                elif chart_type in {"bar", "pie"}:
                    dim_col = category_col or time_col
                    if dim_col:
                        dim_alias = "category"
                        dim_col_expr = f"{table_alias}.{_qident(dim_col)}"
                        limit = bar_limit if chart_type == "bar" else pie_limit
                        # For sparse hierarchy columns (blank_pct > threshold), exclude
                        # blank/null values so the chart isn't dominated by a blank bucket.
                        _blank_filters: list[str] = []
                        if chart.get("category_blank_filter"):
                            _blank_filters = [
                                f"{dim_col_expr} IS NOT NULL",
                                f"{dim_col_expr} <> ''",
                            ]
                        _bar_all_filters = policy_filters + _blank_filters
                        _bar_where = (
                            f" WHERE {' AND '.join(_bar_all_filters)} "
                            if _bar_all_filters else " "
                        )
                        sql = (
                            f"SELECT {dim_col_expr} AS {dim_alias}, "
                            f"{metric_expr} AS \"{metric_name}\" "
                            f"FROM {sql_from}"
                            f"{_bar_where}"
                            f"GROUP BY {dim_col_expr} "
                            f"ORDER BY \"{metric_name}\" DESC "
                            f"LIMIT {limit}"
                        )
                        dimensions = [dim_alias]
                elif chart_type == "grouped_bar" or chart_intent in {"comparison", "cross_table_comparison"}:
                    # Multi-metric comparison chart: anchor metric vs compare metric
                    compare_metric_expr_raw = chart.get("compare_metric_expr") or ""
                    compare_metric_name = chart.get("compare_metric") or "compare"
                    compare_table_name = chart.get("compare_table") or table_name
                    compare_metric_expr_q: str | None = None
                    if compare_metric_expr_raw:
                        if compare_table_name != table_name:
                            # Cross-table: qualify against a different alias
                            compare_alias = "c"
                            compare_table_profile = profiling_map.get(compare_table_name) or {}
                            compare_metric_expr_q = _qualify_formula(
                                compare_metric_expr_raw, compare_alias, compare_table_profile
                            )
                        else:
                            compare_metric_expr_q = _qualify_formula(
                                compare_metric_expr_raw, table_alias, profiling_map.get(table_name) or {}
                            )
                    if compare_metric_expr_q:
                        compare_policy = _dashboard_policy_filters(
                            state.get("domain_id"),
                            table_alias if compare_table_name == table_name else "c",
                            profiling_map.get(compare_table_name) or {},
                            table_name=compare_table_name,
                            context_text=state.get("context_text"),
                            all_table_names=list(profiling_map.keys()),
                        )
                        if time_col:
                            # Time-based comparison: both metrics over time (line with two series)
                            time_grain_cmp = str(chart.get("time_grain") or "month").strip().lower()
                            dim_expr = f"date_trunc('{time_grain_cmp}', {table_alias}.{_qident(time_col)})"
                            dim_alias = "period"
                            if compare_table_name == table_name:
                                # Same table — both metrics in one pass
                                all_filters = policy_filters
                                where_cmp = f" WHERE {' AND '.join(all_filters)} " if all_filters else " "
                                sql = (
                                    f"SELECT {dim_expr} AS {dim_alias}, "
                                    f"{metric_expr} AS \"{metric_name}\", "
                                    f"{compare_metric_expr_q} AS \"{compare_metric_name}\" "
                                    f"FROM {sql_from}"
                                    f"{where_cmp}"
                                    f"GROUP BY {dim_expr} "
                                    f"ORDER BY {dim_alias} DESC "
                                    f"LIMIT {line_single_limit}"
                                )
                            else:
                                # Cross-table — JOIN on time dimension
                                q_compare_table = f"{q_schema}.{_qident(compare_table_name)}"
                                compare_time_col = _pick_canonical_time_column(
                                    profiling_map.get(compare_table_name) or {}, state.get("domain_id")
                                )
                                if compare_time_col:
                                    join_cond = f"date_trunc('{time_grain_cmp}', {table_alias}.{_qident(time_col)}) = date_trunc('{time_grain_cmp}', c.{_qident(compare_time_col)})"
                                    all_filters = policy_filters + compare_policy
                                    where_join = f" WHERE {' AND '.join(all_filters)} " if all_filters else " "
                                    sql = (
                                        f"SELECT {dim_expr} AS {dim_alias}, "
                                        f"{metric_expr} AS \"{metric_name}\", "
                                        f"{compare_metric_expr_q} AS \"{compare_metric_name}\" "
                                        f"FROM {sql_from} "
                                        f"LEFT JOIN {q_compare_table} c ON {join_cond}"
                                        f"{where_join}"
                                        f"GROUP BY {dim_expr} "
                                        f"ORDER BY {dim_alias} DESC "
                                        f"LIMIT {line_single_limit}"
                                    )
                            if sql:
                                chart_type = "line"  # Render as grouped line
                                dimensions = [dim_alias]
                        elif category_col:
                            # Dimension breakdown comparison: grouped_bar by category
                            dim_alias = "category"
                            cat_expr = f"{table_alias}.{_qident(category_col)}"
                            if compare_table_name == table_name:
                                where_gb = f" WHERE {' AND '.join(policy_filters)} " if policy_filters else " "
                                sql = (
                                    f"SELECT {cat_expr} AS {dim_alias}, "
                                    f"{metric_expr} AS \"{metric_name}\", "
                                    f"{compare_metric_expr_q} AS \"{compare_metric_name}\" "
                                    f"FROM {sql_from}"
                                    f"{where_gb}"
                                    f"GROUP BY {cat_expr} "
                                    f"ORDER BY \"{metric_name}\" DESC "
                                    f"LIMIT {bar_limit}"
                                )
                            else:
                                shared_col = chart.get("shared_join_col") or category_col
                                q_compare_table = f"{q_schema}.{_qident(compare_table_name)}"
                                join_cond = f"{table_alias}.{_qident(shared_col)} = c.{_qident(shared_col)}"
                                all_filters = policy_filters + compare_policy
                                where_cross = f" WHERE {' AND '.join(all_filters)} " if all_filters else " "
                                sql = (
                                    f"SELECT {cat_expr} AS {dim_alias}, "
                                    f"{metric_expr} AS \"{metric_name}\", "
                                    f"{compare_metric_expr_q} AS \"{compare_metric_name}\" "
                                    f"FROM {sql_from} "
                                    f"LEFT JOIN {q_compare_table} c ON {join_cond}"
                                    f"{where_cross}"
                                    f"GROUP BY {cat_expr} "
                                    f"ORDER BY \"{metric_name}\" DESC "
                                    f"LIMIT {bar_limit}"
                                )
                            if sql:
                                dimensions = [dim_alias]
                if not sql:
                    # Fallback for valid metrics when no chart dimension is available.
                    sql = (
                        f"SELECT {metric_expr} AS \"{metric_name}\" "
                        f"FROM {sql_from}"
                        f"{where_clause}"
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
                    _dashboard_scoped_conn = _scoped_conn_from_state(state, settings)
                    rows = run_query(settings, sql, params, scoped_conn=_dashboard_scoped_conn)
                    logger.info(
                        "dashboard.chart.sql_ok | title=%s rows=%s",
                        chart_title,
                        len(rows),
                    )
                    # If policy filters eliminated all rows, retry without them.
                    # This handles tables like benchmark/reference tables where a domain
                    # policy filter column exists in the schema but contains no meaningful
                    # values for that particular table — the data context itself signals
                    # that the filter should not apply.
                    if not rows and policy_filters:
                        sql_no_policy = sql.replace(
                            f" WHERE {' AND '.join(policy_filters)} ",
                            " ",
                        )
                        if sql_no_policy != sql:
                            try:
                                rows_retry = run_query(settings, sql_no_policy, params, scoped_conn=_dashboard_scoped_conn)
                                if rows_retry:
                                    logger.info(
                                        "dashboard.chart.policy_filter_bypassed | title=%s reason=no_rows_with_filters rows_after_retry=%s",
                                        chart_title,
                                        len(rows_retry),
                                    )
                                    rows = rows_retry
                                    sql = sql_no_policy
                            except Exception:
                                pass
                except Exception as exc:
                    _conn_info = (
                        f"{_dashboard_scoped_conn.host}:{_dashboard_scoped_conn.port}/"
                        f"{_dashboard_scoped_conn.database_name}"
                        if _dashboard_scoped_conn else "app_db"
                    )
                    logger.exception(
                        "dashboard.chart.sql_failed | title=%s conn=%s sql=%s params=%s",
                        chart_title,
                        _conn_info,
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
            semantic_validation = _chart_output_validation(
                chart_title=chart_title,
                chart_intent=chart_intent,
                chart_type=chart_type,
                category_col=category_col,
                dimensions=dimensions,
                rows=rows,
            )
            if semantic_validation.get("status") != "passed":
                runtime_chart_rejections.append(
                    {
                        "title": chart_title,
                        "reason": semantic_validation.get("reason"),
                        "table": table_name,
                        "metric": metric_name,
                    }
                )
                enriched_charts.append(
                    {
                        **chart,
                        "chart_type": chart_type,
                        "dimensions": dimensions,
                        "metric_name": metric_name,
                        "sql": sql,
                        "rows_count": len(rows),
                        "dashboard_title": dashboard_title,
                        "semantic_validation": semantic_validation,
                        "skipped": True,
                        "reason": semantic_validation.get("reason"),
                    }
                )
                continue

            chart_id = create_chart_request(
                settings,
                state.get("tenant_id") or "",
                state.get("domain_id"),
                question=chart_title,
                query_payload={
                    "metrics": [metric_name],
                    "dimensions": dimensions,
                    "source_dimensions": _interaction_source_dimensions(
                        dimensions=dimensions,
                        time_column=time_col,
                        category_column=category_col,
                    ),
                    "chart": chart_type,
                    "chart_title": chart_title,
                    "dashboard_title": dashboard_title,
                    "metric_intent": chart.get("metric_intent"),
                    "table": table_name,
                    "time_column": time_col,
                    "time_grain": chart.get("time_grain"),
                    "category_column": category_col,
                },
                sql=sql,
                params=params,
                rows_json=rows,
                run_id=run_id or None,
                chart_source="agentic_run",
                title=chart_title,
                created_by="DashboardAgent",
                drill_hierarchy_id=chart.get("drill_hierarchy_id"),
                drill_level_id=chart.get("drill_level_id"),
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
                source_dimensions = _interaction_source_dimensions(
                    dimensions=dimensions,
                    time_column=time_col,
                    category_column=category_col,
                )
                interaction_context = build_chart_interaction_context_for_creation(
                    settings,
                    chart_row={
                        "chart_id": chart_id,
                        "drill_hierarchy_id": chart.get("drill_hierarchy_id"),
                        "drill_level_id": chart.get("drill_level_id"),
                        "tenant_id": state.get("tenant_id"),
                        "domain_id": state.get("domain_id"),
                        "query_payload": {
                            "metrics": [metric_name],
                            "dimensions": dimensions,
                            "source_dimensions": source_dimensions,
                            "chart": chart_type,
                            "chart_title": chart_title,
                            "dashboard_title": dashboard_title,
                            "metric_intent": chart.get("metric_intent"),
                            "table": table_name,
                            "time_column": time_col,
                            "time_grain": chart.get("time_grain"),
                            "category_column": category_col,
                        },
                        "sql": sql,
                        "rows_json": rows,
                    },
                    tenant_id=str(state.get("tenant_id") or ""),
                    domain_id=str(state.get("domain_id") or "").strip() or None,
                    hierarchies=state.get("business_hierarchies") if isinstance(state.get("business_hierarchies"), list) else None,
                )
                hierarchy_bindings = interaction_context.get("hierarchy_bindings") or {}
                drill_hierarchy_id = chart.get("drill_hierarchy_id")
                drill_level_id = chart.get("drill_level_id")
                if not drill_hierarchy_id or not drill_level_id:
                    for value in hierarchy_bindings.values():
                        if not isinstance(value, dict):
                            continue
                        drill_hierarchy_id = drill_hierarchy_id or value.get("hierarchy_id")
                        drill_level_id = drill_level_id or value.get("current_level_id")
                        if drill_hierarchy_id and drill_level_id:
                            break
                logger.info(
                    "dashboard.chart.hierarchy_binding | run_id=%s chart_id=%s title=%s category_column=%s supplied_drill_hierarchy_id=%s supplied_drill_level_id=%s derived_bindings=%s final_drill_hierarchy_id=%s final_drill_level_id=%s",
                    run_id,
                    chart_id,
                    chart_title,
                    category_col,
                    chart.get("drill_hierarchy_id"),
                    chart.get("drill_level_id"),
                    hierarchy_bindings,
                    drill_hierarchy_id,
                    drill_level_id,
                )
                inference = build_chart_inference(
                    settings,
                    chart_type=chart_type,
                    rows=rows,
                    metric_name=metric_name,
                    dim_key=dim_key,
                    chart_title=chart_title,
                )
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
                    insight_text=inference["insight_text"],
                    narrative_text=inference["narrative_text"],
                    stats_json=inference["stats_json"],
                    interaction_context_json=interaction_context,
                    root_chart_id=chart_id,
                    drill_hierarchy_id=drill_hierarchy_id,
                    drill_level_id=drill_level_id,
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
                        "insight_text": inference["insight_text"],
                        "narrative_text": inference["narrative_text"],
                        "stats": inference["stats_json"],
                        "chart_payload": payload.get("chart_payload"),
                        "chart_data": payload.get("data"),
                        "dashboard_title": dashboard_title,
                        "semantic_validation": semantic_validation,
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

        quality_report = dict(state.get("quality_report") or {})
        existing_chart_rejections = [item for item in (quality_report.get("chart_rejections") or []) if isinstance(item, dict)]
        if runtime_chart_rejections:
            quality_report["chart_rejections"] = [*existing_chart_rejections, *runtime_chart_rejections]
            warnings = [str(v) for v in (quality_report.get("warnings") or []) if str(v).strip()]
            if "chart_rejections_present" not in warnings:
                warnings.append("chart_rejections_present")
            quality_report["warnings"] = warnings
            quality_report["gate_passed"] = False
            state["quality_report"] = quality_report
        successful_charts = [item for item in enriched_charts if isinstance(item, dict) and not item.get("skipped") and item.get("chart_id")]
        successful_chart_ids = {str(item.get("chart_id")) for item in successful_charts if str(item.get("chart_id") or "").strip()}
        successful_chart_plan = [
            item
            for item in (state.get("chart_plan") or [])
            if str(item.get("chart_id") or "") in successful_chart_ids or (
                not str(item.get("chart_id") or "").strip()
                and any(
                    item.get("table") == chart.get("table")
                    and item.get("metric") == chart.get("metric")
                    and item.get("intent") == chart.get("intent")
                    and item.get("category_column") == chart.get("category_column")
                    and item.get("time_grain") == chart.get("time_grain")
                    for chart in successful_charts
                )
            )
        ]
        story_sections = build_story_sections(successful_charts)
        dashboard_theme = build_dashboard_theme_from_charts(
            successful_charts,
            metrics=state.get("metric_defs", []),
            profiling=state.get("profiling_stats", {}),
            domain_id=state.get("domain_id"),
            context_text=state.get("context_text"),
        )
        table_contributions = dashboard_theme.get("table_contributions") or []
        kpi_family_contributions = dashboard_theme.get("kpi_family_contributions") or []
        selected_successful_chart_ids = [str(item.get("chart_id")) for item in successful_charts if str(item.get("chart_id") or "").strip()]
        rejected_chart_ids = [
            str(item.get("chart_id"))
            for item in enriched_charts
            if isinstance(item, dict) and item.get("skipped") and str(item.get("chart_id") or "").strip()
        ]
        title_generation_source = "deterministic_theme"
        title_warning = None
        final_dashboard_title = ""
        title_sources = {
            "tables": dashboard_theme.get("selected_tables") or dashboard_theme.get("eligible_tables") or [],
            "kpi_families": [item.get("family") for item in kpi_family_contributions if item.get("family")],
            "successful_chart_ids": selected_successful_chart_ids,
        }
        title_reason = "Derived from persisted successful charts, KPI families, and cross-table contribution."
        llm_title_payload = _llm_generate_dashboard_title(
            settings,
            domain_id=state.get("domain_id"),
            context_text=state.get("context_text"),
            successful_charts=successful_charts,
            dashboard_theme=dashboard_theme,
        )
        llm_title = str((llm_title_payload or {}).get("dashboard_title") or "").strip()
        all_title_tables = list(dict.fromkeys((dashboard_theme.get("selected_tables") or []) + (dashboard_theme.get("eligible_tables") or [])))
        if llm_title and not _title_mentions_raw_tables(llm_title, all_title_tables):
            final_dashboard_title = llm_title
            title_generation_source = "llm_successful_charts"
            title_reason = str((llm_title_payload or {}).get("dashboard_title_reason") or title_reason)
            if isinstance((llm_title_payload or {}).get("dashboard_title_sources"), dict):
                title_sources = dict((llm_title_payload or {}).get("dashboard_title_sources") or {})
                title_sources.setdefault("successful_chart_ids", selected_successful_chart_ids)
        elif llm_title and _title_mentions_raw_tables(llm_title, all_title_tables):
            if "table_derived_dashboard_title" not in (quality_report.get("warnings") or []):
                quality_report["warnings"] = [*list(quality_report.get("warnings") or []), "table_derived_dashboard_title"]
        if not final_dashboard_title:
            deterministic_title = deterministic_dashboard_title(dashboard_theme, state.get("domain_id"))
            if deterministic_title:
                final_dashboard_title = deterministic_title
                title_generation_source = "deterministic_theme"
        if not final_dashboard_title:
            domain_label = str(state.get("domain_id") or "").replace("_", " ").replace("-", " ").strip()
            if domain_label:
                final_dashboard_title = f"{domain_label.title()} Overview"
                title_generation_source = "domain_fallback"
                title_reason = "Derived from the domain because no stronger chart-backed title was available."
        if not final_dashboard_title:
            fallback_table = str((table_contributions[:1] or [{}])[0].get("table") or "").strip()
            final_dashboard_title = f"{fallback_table.replace('_', ' ').title()} Overview" if fallback_table else "Performance Overview"
            title_generation_source = "table_fallback"
            title_reason = "Fell back to a table-derived title because no stronger domain or chart-backed title was available."
            title_warning = "table_derived_dashboard_title"

        warnings = [str(v) for v in (quality_report.get("warnings") or []) if str(v).strip()]
        eligible_tables = list(dict.fromkeys(dashboard_theme.get("eligible_tables") or []))
        contributing_tables = [item.get("table") for item in table_contributions if item.get("table")]
        if len(eligible_tables) >= 2 and len(contributing_tables) < 2 and successful_charts:
            if "insufficient_cross_table_coverage" not in warnings:
                warnings.append("insufficient_cross_table_coverage")
        selection_diag = state.get("chart_selection_diagnostics") or {}
        if title_warning and title_warning not in warnings:
            warnings.append(title_warning)
        successful_count = len(successful_charts)
        low_value_chart_count = int(selection_diag.get("low_value_chart_count") or 0)
        if successful_count > 12 and (low_value_chart_count >= 2 or len(kpi_family_contributions) < max(2, successful_count // 6)):
            if "overexpanded_low_value_dashboard" not in warnings:
                warnings.append("overexpanded_low_value_dashboard")
        quality_report["warnings"] = warnings
        quality_report["cross_table_coverage"] = {
            "eligible_tables": eligible_tables,
            "contributing_tables": contributing_tables,
            "successful_chart_count": successful_count,
        }
        quality_report["dashboard_title_generation"] = {
            "source": title_generation_source,
            "reason": title_reason,
            "sources": title_sources,
        }
        quality_report["chart_selection_diagnostics"] = selection_diag
        llm_quality_review = _llm_review_dashboard_quality(
            settings,
            domain_id=state.get("domain_id"),
            context_text=state.get("context_text"),
            dashboard_title=final_dashboard_title,
            successful_charts=successful_charts,
            rejected_charts=[item for item in enriched_charts if isinstance(item, dict) and item.get("skipped")],
            dashboard_theme=dashboard_theme,
            quality_report=quality_report,
        )
        if isinstance(llm_quality_review, dict) and llm_quality_review:
            quality_report["llm_advisory"] = llm_quality_review
        state["quality_report"] = quality_report
        dashboard_spec["title"] = final_dashboard_title
        dashboard_spec["dashboard_title"] = final_dashboard_title
        dashboard_spec["dashboard_theme"] = dashboard_theme
        dashboard_spec["dashboard_title_reason"] = title_reason
        dashboard_spec["dashboard_title_sources"] = title_sources
        dashboard_spec["story_sections"] = story_sections
        dashboard_spec["table_contributions"] = table_contributions
        dashboard_spec["kpi_family_contributions"] = kpi_family_contributions
        dashboard_spec["charts"] = enriched_charts
        dashboard_spec["selected_successful_chart_ids"] = selected_successful_chart_ids
        dashboard_spec["rejected_chart_ids"] = rejected_chart_ids
        dashboard_spec["role_selection"] = selection_diag
        if isinstance(quality_report.get("llm_advisory"), dict):
            dashboard_spec["llm_advisory"] = quality_report.get("llm_advisory")
        dashboard_spec["chart_plan"] = successful_chart_plan
        dashboard_spec["story"] = {
            "title": final_dashboard_title,
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
        dashboard_title = final_dashboard_title
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
        _dashboard_scoped_conn = _scoped_conn_from_state(state, settings)
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
            fact_view_results = create_views_from_schema(
                settings,
                state.get("tenant_id") or "",
                state.get("domain_id") or "",
                state.get("connection_id") or "",
                state.get("database_name") or "",
                state.get("schema_name") or "public",
                state.get("schema_payload") or {},
                scoped_conn=_dashboard_scoped_conn,
            )
            created_views = [
                str(item.get("view_name"))
                for item in fact_view_results
                if isinstance(item, dict) and item.get("status") == "created" and item.get("view_name")
            ]
            _emit(
                settings,
                run_id,
                "DashboardAgent",
                "running",
                "Dashboard Agent registered views created",
                {
                    "elapsed_ms": round((time.perf_counter() - t1) * 1000, 1),
                    "views": len(created_views),
                    "fact_view_results": fact_view_results,
                },
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
                scoped_conn=_dashboard_scoped_conn,
            )
            evidence_coverage = _build_evidence_coverage_summary(
                extract_schema_table_names(state.get("schema_payload") or {}),
                fact_view_results,
                joined_views,
            )
            state["evidence_coverage"] = evidence_coverage
            _emit(
                settings,
                run_id,
                "DashboardAgent",
                "running",
                "Dashboard Agent joined views created",
                {
                    "elapsed_ms": round((time.perf_counter() - t2) * 1000, 1),
                    "joined_views": len(joined_views),
                    "evidence_coverage": evidence_coverage,
                },
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
        _quality = dashboard_spec.get("quality") or {}
        dash_result = _create_dashboard(
            settings,
            tenant_id=state.get("tenant_id") or "",
            domain_id=state.get("domain_id") or "",
            name=dashboard_title,
            dashboard_type="system",
            run_id=run_id or None,
            chart_plan=dashboard_spec.get("chart_plan"),
            quality_score=(
                float(_quality["quality_score"])
                if isinstance(_quality, dict) and _quality.get("quality_score") is not None
                else None
            ),
            quality_gate_passed=(
                bool(_quality.get("gate_passed"))
                if isinstance(_quality, dict)
                else None
            ),
        )
        dash_id = dash_result.get("dashboard_id")
        state["dashboard_id"] = dash_id
        for _pos, _cid in enumerate(chart_ids):
            _add_chart_to_dashboard(
                settings, dash_id, _cid, position=_pos, added_by="DashboardAgent",
            )
        # Link discovery charts to the newly created dashboard
        if dash_id and discovery_chart_ids:
            _offset = len(chart_ids)
            for _pos, _cid in enumerate(discovery_chart_ids):
                try:
                    _add_chart_to_dashboard(
                        settings, dash_id, _cid,
                        position=_offset + _pos,
                        added_by="ChartDiscoveryAgent",
                    )
                except Exception as _link_err:
                    logger.warning("chart_discovery.dashboard_link_failed | chart_id=%s err=%s", _cid, _link_err)
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
                "chart_ids": chart_ids + discovery_chart_ids,
                "chart_titles": [c.get("title") for c in enriched_charts if c.get("title")] + discovery_titles,
                "discovery_chart_ids": discovery_chart_ids,
                "discovery_chart_titles": discovery_titles,
                "chart_discovery_diagnostics": state.get("chart_discovery_diagnostics"),
                "chart_details": enriched_charts,
                "dashboard_theme": dashboard_theme,
                "dashboard_title_reason": dashboard_spec.get("dashboard_title_reason"),
                "dashboard_title_sources": dashboard_spec.get("dashboard_title_sources"),
                "table_contributions": table_contributions,
                "kpi_family_contributions": kpi_family_contributions,
                "story_sections": story_sections,
                "role_selection": selection_diag,
                "selected_successful_chart_ids": selected_successful_chart_ids,
                "rejected_chart_ids": rejected_chart_ids,
                "quality_report": state.get("quality_report"),
                "views_detail": created_views,
                "fact_view_results": fact_view_results,
                "registry_persisted": registry_persisted,
                "semantics_persisted": semantics_persisted,
                "evidence_coverage": evidence_coverage,
                "elapsed_ms": round((time.perf_counter() - dashboard_start) * 1000, 1),
                "fast_mode": fast_mode,
            },
            event_callback=event_callback,
        )
        logger.info(
            "agentic.dashboard.handoff | run_id=%s dashboard_id=%s charts=%s next=anomaly_detection",
            run_id,
            dash_id,
            len(state["dashboard_spec"].get("charts", [])),
        )
        return state

    def correlation_node(state: dict[str, Any]) -> dict[str, Any]:
        logger.info(
            "agentic.correlation.enter | run_id=%s dashboard_id=%s domain=%s",
            run_id,
            state.get("dashboard_id"),
            state.get("domain_id"),
        )
        _emit(
            settings,
            run_id,
            "CorrelationAgent",
            "running",
            "Correlation Agent started",
            {
                "correlation_flow_version": AGENTIC_CORRELATION_FLOW_VERSION,
            },
            event_callback=event_callback,
        )
        if not _env_bool("AGENTIC_CORRELATION_ENABLED", True):
            state["correlation_run_id"] = None
            state["correlation_result"] = {}
            _emit(
                settings,
                run_id,
                "CorrelationAgent",
                "completed",
                "Correlation Agent skipped",
                {"reason": "disabled"},
                event_callback=event_callback,
            )
            return state

        tenant_id = str(state.get("tenant_id") or "").strip()
        domain_id = str(state.get("domain_id") or "").strip()
        if not tenant_id or not domain_id:
            state["correlation_run_id"] = None
            state["correlation_result"] = {}
            _emit(
                settings,
                run_id,
                "CorrelationAgent",
                "completed",
                "Correlation Agent skipped",
                {"reason": "missing_scope"},
                event_callback=event_callback,
            )
            return state

        forecast_periods = _resolve_int_setting(
            state,
            "correlation_forecast_periods",
            "CORRELATION_FORECAST_PERIODS",
            12,
            minimum=1,
        )
        analysis_mode = str(
            (state.get("runtime_tuning") or {}).get("correlation_analysis_mode")
            or os.getenv("CORRELATION_ANALYSIS_MODE", "full")
        ).strip().lower() or "full"
        correlation_run_id = f"corrrun_{uuid.uuid4().hex[:12]}"
        create_correlation_run(
            settings,
            correlation_run_id=correlation_run_id,
            tenant_id=tenant_id,
            domain_id=domain_id,
            run_id=run_id,
            analysis_mode=analysis_mode,
            forecast_periods=forecast_periods,
            triggered_by="agentic_workflow",
        )
        result = run_correlation_intelligence(
            settings,
            correlation_run_id=correlation_run_id,
            tenant_id=tenant_id,
            domain_id=domain_id,
            run_id=run_id,
            forecast_periods=forecast_periods,
            analysis_mode=analysis_mode,
            scoped_conn=_scoped_conn_from_state(state, settings),
            profiling_stats=state.get("profiling_stats") or {},
        )
        narration: dict[str, Any] = {"summary_text": "", "summary_html": ""}
        logger.info(
            "agentic.correlation.narration.request | run_id=%s correlation_run_id=%s "
            "kpi_snapshots=%d anomalies=%d pairs=%d projections=%d threads=%d warnings=%d",
            run_id, correlation_run_id,
            len(result.get("kpi_snapshots") or []),
            len(result.get("anomaly_results") or []),
            len(result.get("correlation_pairs") or []),
            len(result.get("forward_projections") or []),
            len(result.get("investigation_threads") or []),
            len(result.get("data_quality_warnings") or []),
        )
        try:
            narration = narrate_correlation_results(
                settings,
                kpi_snapshots=result.get("kpi_snapshots") or [],
                anomaly_results=result.get("anomaly_results") or [],
                correlation_pairs=result.get("correlation_pairs") or [],
                forward_projections=result.get("forward_projections") or [],
                investigation_threads=result.get("investigation_threads") or [],
                data_quality_warnings=result.get("data_quality_warnings") or [],
                snapshot_eligibility_summary=result.get("snapshot_eligibility_summary") or {},
            )
            logger.info(
                "agentic.correlation.narration.response | run_id=%s correlation_run_id=%s "
                "threads_narrated=%d insights=%d summary_text=%r",
                run_id, correlation_run_id,
                narration.get("threads_narrated", 0),
                len(narration.get("insights") or []),
                (narration.get("summary_text") or "")[:200],
            )
        except Exception:
            logger.warning(
                "agentic.correlation.narration.failed | run_id=%s correlation_run_id=%s",
                run_id, correlation_run_id, exc_info=True,
            )
        save_correlation_run_results(
            settings,
            correlation_run_id=correlation_run_id,
            tenant_id=tenant_id,
            domain_id=domain_id,
            run_result=result,
            summary_text=narration.get("summary_text") or "",
            summary_html=narration.get("summary_html") or "",
            insights_json=narration.get("insights") or [],
        )
        # Generate and persist correlation charts inline so they are available
        # immediately in the same agentic run (no separate background trigger needed).
        try:
            corr_charts = generate_correlation_charts(
                correlation_run_id=correlation_run_id,
                kpi_snapshots=result.get("kpi_snapshots") or [],
                anomaly_results=result.get("anomaly_results") or [],
                correlation_pairs=result.get("correlation_pairs") or [],
                forward_projections=result.get("forward_projections") or [],
                snapshot_eligibility_summary=result.get("snapshot_eligibility_summary") or {},
                data_quality_warnings=result.get("data_quality_warnings") or [],
            )
            _generated_chart_types = [
                str(chart.get("chart_type") or "").strip()
                for chart in corr_charts
                if str(chart.get("chart_type") or "").strip()
            ]
            logger.info(
                "agentic.correlation.generated_charts | run_id=%s version=%s correlation_run_id=%s source_mode=%s selected_source=%s metric_count=%s chart_count=%s chart_types=%s",
                run_id,
                AGENTIC_CORRELATION_FLOW_VERSION,
                correlation_run_id,
                (result.get("snapshot_eligibility_summary") or {}).get("source_mode"),
                (result.get("snapshot_eligibility_summary") or {}).get("selected_source_kind"),
                result.get("metric_count"),
                len(corr_charts),
                _generated_chart_types,
            )
            _emit(
                settings,
                run_id,
                "CorrelationAgent",
                "raw_json_ready",
                "Correlation chart generation summary ready",
                {
                    "correlation_flow_version": AGENTIC_CORRELATION_FLOW_VERSION,
                    "correlation_run_id": correlation_run_id,
                    "snapshot_eligibility_summary": result.get("snapshot_eligibility_summary") or {},
                    "data_quality_warnings": result.get("data_quality_warnings") or [],
                    "generated_chart_count": len(corr_charts),
                    "generated_chart_types": _generated_chart_types,
                },
                event_callback=event_callback,
            )
            _corr_chart_ids: list[str] = []
            for corr_chart in corr_charts:
                chart_type = str(corr_chart.get("chart_type") or "line")
                metric_name = str(corr_chart.get("metric_name") or "")
                # Prefer the human-readable title from the spec (e.g.
                # "sales_volume — Forward Projection" or
                # "sales_volume by zone — Category Trends") over the
                # raw metric_name slug which contains table/column tokens.
                spec_title = str((corr_chart.get("spec") or {}).get("title") or "").strip()
                title = spec_title or (
                    f"{chart_type.replace('_', ' ').title()}: {metric_name}"
                    if metric_name
                    else chart_type.replace("_", " ").title()
                )
                created = create_chart_request(
                    settings,
                    tenant_id,
                    domain_id,
                    question=title,
                    query_payload={
                        "chart_type": chart_type,
                        "metric_name": metric_name,
                        "pair_id": corr_chart.get("pair_id"),
                        "correlation_run_id": correlation_run_id,
                        "dimensions": [str(v) for v in ([corr_chart.get("metric_a"), corr_chart.get("metric_b")] if chart_type in {"scatter_regression", "rolling_correlation"} else []) if str(v or "").strip()],
                        "source_dimensions": [str(v) for v in ([corr_chart.get("metric_a"), corr_chart.get("metric_b")] if chart_type in {"scatter_regression", "rolling_correlation"} else []) if str(v or "").strip()],
                    },
                    sql=None,
                    params=[],
                    rows_json=[],
                    run_id=run_id,
                    chart_source="correlation_agent",
                    title=title,
                    created_by="CorrelationAgent",
                )
                corr_chart_id = (created or {}).get("chart_id")
                if corr_chart_id:
                    corr_rows = corr_chart.get("data") or []
                    interaction_context = build_chart_interaction_context_for_creation(
                        settings,
                        chart_row={
                            "chart_id": corr_chart_id,
                            "tenant_id": tenant_id,
                            "domain_id": domain_id,
                            "query_payload": {
                                "metrics": [metric_name] if metric_name else [],
                                "dimensions": [str(v) for v in ([corr_chart.get("metric_a"), corr_chart.get("metric_b")] if chart_type in {"scatter_regression", "rolling_correlation"} else []) if str(v or "").strip()],
                                "source_dimensions": [str(v) for v in ([corr_chart.get("metric_a"), corr_chart.get("metric_b")] if chart_type in {"scatter_regression", "rolling_correlation"} else []) if str(v or "").strip()],
                                "chart": chart_type,
                                "chart_title": title,
                                "correlation_run_id": correlation_run_id,
                            },
                            "rows_json": corr_rows,
                        },
                        tenant_id=str(tenant_id or ""),
                        domain_id=str(domain_id or "").strip() or None,
                    )
                    if chart_type in _CORR_CHART_TYPES:
                        logger.info(
                            "agentic.correlation.chart_insight.request | run_id=%s correlation_run_id=%s "
                            "chart_id=%s chart_type=%s metric_name=%r title=%r data_rows=%d "
                            "pair_id=%s source=correlation_insight_builder",
                            run_id, correlation_run_id, corr_chart_id, chart_type,
                            metric_name, title,
                            len(corr_chart.get("data") or []),
                            corr_chart.get("pair_id"),
                        )
                        corr_inference = _build_correlation_chart_insight(corr_chart)
                        logger.info(
                            "agentic.correlation.chart_insight.response | run_id=%s correlation_run_id=%s "
                            "chart_id=%s chart_type=%s insight=%r narrative=%r stats=%s",
                            run_id, correlation_run_id, corr_chart_id, chart_type,
                            (corr_inference.get("insight_text") or "")[:120],
                            (corr_inference.get("narrative_text") or "")[:120],
                            corr_inference.get("stats_json"),
                        )
                    else:
                        logger.info(
                            "agentic.correlation.chart_insight.request | run_id=%s correlation_run_id=%s "
                            "chart_id=%s chart_type=%s metric_name=%r title=%r data_rows=%d "
                            "source=generic_chart_inference",
                            run_id, correlation_run_id, corr_chart_id, chart_type,
                            metric_name, title, len(corr_rows),
                        )
                        corr_inference = build_chart_inference(
                            settings,
                            chart_type=chart_type,
                            rows=corr_rows,
                            metric_name=metric_name,
                            dim_key=None,
                            chart_title=title,
                        )
                        logger.info(
                            "agentic.correlation.chart_insight.response | run_id=%s correlation_run_id=%s "
                            "chart_id=%s chart_type=%s insight=%r narrative=%r",
                            run_id, correlation_run_id, corr_chart_id, chart_type,
                            (corr_inference.get("insight_text") or "")[:120],
                            (corr_inference.get("narrative_text") or "")[:120],
                        )
                    _insight_text = corr_inference.get("insight_text") or ""
                    _narrative_text = corr_inference.get("narrative_text") or _insight_text or title
                    update_chart_request(
                        settings,
                        corr_chart_id,
                        status="ready",
                        chart_type=chart_type,
                        chart_payload=corr_chart.get("spec"),
                        chart_data=corr_chart.get("data") or [],
                        insight_text=_insight_text,
                        narrative_text=_narrative_text,
                        stats_json=corr_inference.get("stats_json"),
                        interaction_context_json=interaction_context,
                        root_chart_id=corr_chart_id,
                    )
                    if not _insight_text or not _narrative_text:
                        logger.warning(
                            "agentic.correlation.chart_annotations_missing | run_id=%s correlation_run_id=%s "
                            "chart_id=%s chart_type=%s title=%r insight_present=%s narrative_present=%s",
                            run_id, correlation_run_id, corr_chart_id, chart_type, title,
                            bool(_insight_text), bool(_narrative_text),
                        )
                    _corr_chart_ids.append(corr_chart_id)
            state["correlation_chart_ids"] = _corr_chart_ids
            # Count how many charts ended up with insight/narrative vs empty
            _charts_with_insight = sum(
                1 for cid in _corr_chart_ids if cid  # placeholder — actual count tracked below
            )
            logger.info(
                "agentic.correlation.charts_persisted | run_id=%s version=%s correlation_run_id=%s "
                "total_charts=%d persisted_chart_ids=%s",
                run_id, AGENTIC_CORRELATION_FLOW_VERSION, correlation_run_id, len(corr_charts), _corr_chart_ids,
            )
        except Exception:
            logger.warning(
                "agentic.correlation.chart_persistence_failed | run_id=%s correlation_run_id=%s",
                run_id,
                correlation_run_id,
                exc_info=True,
            )
            state.setdefault("correlation_chart_ids", [])
        state["correlation_run_id"] = correlation_run_id
        state["correlation_result"] = {
            **result,
            "summary_text": narration.get("summary_text") or "",
            "summary_html": narration.get("summary_html") or "",
            "insights": narration.get("insights") or [],
        }
        _emit(
            settings,
            run_id,
            "CorrelationAgent",
            "completed",
            "Correlation Agent completed",
            {
                "correlation_flow_version": AGENTIC_CORRELATION_FLOW_VERSION,
                "correlation_run_id": correlation_run_id,
                "analysis_mode": analysis_mode,
                "forecast_periods": forecast_periods,
                "metric_count": result.get("metric_count"),
                "anomaly_count": result.get("anomaly_count"),
                "correlation_pair_count": result.get("correlation_pair_count"),
                "thread_count": result.get("thread_count"),
                "data_quality_warnings": result.get("data_quality_warnings") or [],
                "snapshot_eligibility_summary": result.get("snapshot_eligibility_summary") or {},
                "snapshot_exclusions_preview": (result.get("snapshot_exclusions") or [])[:5],
                "insights_preview": (narration.get("insights") or [])[:3],
                "summary_text": narration.get("summary_text") or "",
                "error_message": result.get("error_message"),
            },
            event_callback=event_callback,
        )
        return state

    def anomaly_detection_node(state: dict[str, Any]) -> dict[str, Any]:
        logger.info(
            "agentic.anomaly_detection.enter | run_id=%s dashboard_id=%s has_dashboard_spec=%s metric_defs=%s profiling_tables=%s",
            run_id,
            state.get("dashboard_id"),
            bool(state.get("dashboard_spec")),
            len(state.get("metric_defs") or []),
            len(((state.get("profiling_stats") or {}).get("tables") or [])),
        )
        _emit(
            settings,
            run_id,
            "AnomalyDetectionAgent",
            "running",
            "Anomaly Detection Agent started",
            {
                "anomaly_flow_version": AGENTIC_ANOMALY_FLOW_VERSION,
            },
            event_callback=event_callback,
        )
        correlation_context = _summarize_correlation_context(
            correlation_run_id=str(state.get("correlation_run_id") or "").strip() or None,
            correlation_result=state.get("correlation_result") if isinstance(state.get("correlation_result"), dict) else None,
        )
        evidence_coverage = state.get("evidence_coverage") or {}
        quality_report = state.get("quality_report") or {}
        readiness_advisory = _llm_review_anomaly_readiness(
            settings,
            domain_id=state.get("domain_id"),
            context_text=state.get("context_text"),
            dashboard_spec=state.get("dashboard_spec") or {},
            quality_report=quality_report,
            evidence_coverage=evidence_coverage,
            anomaly_candidate_summary=(state.get("anomaly_detection") or {}).get("summary") or {},
        )
        if isinstance(quality_report, dict) and isinstance(readiness_advisory, dict) and readiness_advisory:
            quality_report["anomaly_readiness_advisory"] = readiness_advisory
            state["quality_report"] = quality_report
        if isinstance(evidence_coverage, dict) and evidence_coverage.get("status") == "failed":
            investigation_id = create_anomaly_investigation(
                settings,
                tenant_id=str(state.get("tenant_id") or ""),
                domain_id=str(state.get("domain_id") or ""),
                run_id=run_id,
                trigger_source="deployment",
                title=f"{str(state.get('domain_id') or 'Domain').replace('_', ' ').title()} Anomaly Investigation",
                dashboard_id=state.get("dashboard_id"),
                source_dashboard_id=state.get("dashboard_id"),
                summary_text="Evidence coverage failed; anomaly investigation skipped.",
                anomaly_summary_json={
                    "reason": "evidence_coverage_failed",
                    "evidence_coverage": evidence_coverage,
                    "readiness_advisory": readiness_advisory,
                    "correlation_context": correlation_context,
                },
                quality_json={
                    "status": "evidence_coverage_failed",
                    "evidence_coverage": evidence_coverage,
                    "readiness_advisory": readiness_advisory,
                },
            )
            update_anomaly_investigation(
                settings,
                investigation_id,
                status="failed",
                error_message="Evidence coverage failed; anomaly investigation skipped.",
            )
            state["anomaly_investigation_id"] = investigation_id
            state["anomaly_ids"] = []
            state["anomaly_hypothesis_ids"] = []
            state["anomaly_action_ids"] = []
            logger.info(
                "agentic.anomaly_detection.skip | run_id=%s reason=evidence_coverage_failed investigation_id=%s",
                run_id,
                investigation_id,
            )
            _emit(
                settings,
                run_id,
                "AnomalyDetectionAgent",
                "failed",
                "Anomaly Detection Agent skipped due to evidence coverage failure",
                {
                    "investigation_id": investigation_id,
                    "reason": "evidence_coverage_failed",
                    "evidence_coverage": evidence_coverage,
                    "readiness_advisory": readiness_advisory,
                },
                event_callback=event_callback,
            )
            return state
        if _should_skip_anomaly_for_dashboard_quality(quality_report):
            investigation_id = create_anomaly_investigation(
                settings,
                tenant_id=str(state.get("tenant_id") or ""),
                domain_id=str(state.get("domain_id") or ""),
                run_id=run_id,
                trigger_source="deployment",
                title=f"{str(state.get('domain_id') or 'Domain').replace('_', ' ').title()} Anomaly Investigation",
                dashboard_id=state.get("dashboard_id"),
                source_dashboard_id=state.get("dashboard_id"),
                summary_text="Dashboard quality gate failed; anomaly investigation skipped.",
                anomaly_summary_json={
                    "reason": "dashboard_quality_failed",
                    "quality_report": quality_report,
                    "readiness_advisory": readiness_advisory,
                    "correlation_context": correlation_context,
                },
                quality_json={
                    "status": "dashboard_quality_failed",
                    "quality_report": quality_report,
                    "readiness_advisory": readiness_advisory,
                },
            )
            update_anomaly_investigation(
                settings,
                investigation_id,
                status="failed",
                error_message="Dashboard quality gate failed; anomaly investigation skipped.",
            )
            state["anomaly_investigation_id"] = investigation_id
            state["anomaly_ids"] = []
            state["anomaly_hypothesis_ids"] = []
            state["anomaly_action_ids"] = []
            logger.info(
                "agentic.anomaly_detection.skip | run_id=%s reason=dashboard_quality_failed investigation_id=%s",
                run_id,
                investigation_id,
            )
            _emit(
                settings,
                run_id,
                "AnomalyDetectionAgent",
                "failed",
                "Anomaly Detection Agent skipped due to dashboard quality failure",
                {
                    "investigation_id": investigation_id,
                    "reason": "dashboard_quality_failed",
                    "quality_report": quality_report,
                    "readiness_advisory": readiness_advisory,
                },
                event_callback=event_callback,
            )
            return state
        enabled = _env_bool("AGENTIC_ANOMALY_DETECTION_ENABLED", True)
        min_severity_score = _env_float("AGENTIC_ANOMALY_MIN_SEVERITY", 0.15, minimum=0.0)
        max_evidence_queries = _env_int("AGENTIC_ANOMALY_MAX_EVIDENCE_QUERIES", 5, minimum=0)
        evidence_query_row_limit = _env_int("AGENTIC_ANOMALY_EVIDENCE_QUERY_ROW_LIMIT", 200, minimum=1)
        min_hypothesis_confidence = _env_float("AGENTIC_ANOMALY_MIN_HYPOTHESIS_CONFIDENCE", 0.35, minimum=0.0)
        runtime_config = {
            "enabled": enabled,
            "min_severity_score": min_severity_score,
            "max_evidence_queries": max_evidence_queries,
            "evidence_query_row_limit": evidence_query_row_limit,
            "min_hypothesis_confidence": min_hypothesis_confidence,
            "llm_enabled": _anomaly_llm_enabled(settings),
        }
        state["anomaly_runtime_config"] = runtime_config
        if not enabled:
            logger.info("agentic.anomaly_detection.skip | run_id=%s reason=disabled", run_id)
            _emit(
                settings,
                run_id,
                "AnomalyDetectionAgent",
                "completed",
                "Anomaly Detection Agent skipped",
                {"reason": "disabled", "runtime_config": runtime_config},
                event_callback=event_callback,
            )
            return state
        try:
            detection = detect_agentic_anomalies(
                settings,
                schema_name=str(state.get("schema_name") or "public"),
                profiling_stats=state.get("profiling_stats", {}) or {},
                metric_defs=state.get("metric_defs", []) or [],
                dashboard_spec=state.get("dashboard_spec") or {},
                min_severity_score=min_severity_score,
            )
        except Exception as exc:
            error_artifacts = {
                "error_message": str(exc),
                "error_type": exc.__class__.__name__,
                "traceback": traceback.format_exc(limit=12),
            }
            _emit(
                settings,
                run_id,
                "AnomalyDetectionAgent",
                "failed",
                "Anomaly Detection Agent failed",
                error_artifacts,
                event_callback=event_callback,
            )
            raise

        state["anomaly_detection"] = detection
        if isinstance(quality_report, dict) and isinstance(readiness_advisory, dict) and readiness_advisory:
            detection.setdefault("summary", {})
            detection["summary"]["readiness_advisory"] = readiness_advisory
        candidates = detection.get("candidates") or []
        logger.info(
            "agentic.anomaly_detection.detected | run_id=%s candidates=%s metric_candidates=%s raw_signal_candidates=%s",
            run_id,
            len(candidates),
            (detection.get("summary") or {}).get("metric_candidate_count"),
            (detection.get("summary") or {}).get("raw_signal_candidate_count"),
        )
        if not candidates:
            exploration = build_anomaly_fallback_exploration(
                settings,
                schema_name=str(state.get("schema_name") or "public"),
                profiling_stats=state.get("profiling_stats", {}) or {},
                metric_defs=state.get("metric_defs", []) or [],
                dashboard_spec=state.get("dashboard_spec") or {},
                join_edges=state.get("join_edges") or [],
                scoped_conn=_scoped_conn_from_state(state, settings),
            )
            investigation_id = create_anomaly_investigation(
                settings,
                tenant_id=str(state.get("tenant_id") or ""),
                domain_id=str(state.get("domain_id") or ""),
                run_id=run_id,
                trigger_source="deployment",
                title=f"{str(state.get('domain_id') or 'Domain').replace('_', ' ').title()} Anomaly Investigation",
                dashboard_id=state.get("dashboard_id"),
                source_dashboard_id=state.get("dashboard_id"),
                summary_text="No confirmed anomaly candidates crossed threshold; exploratory anomaly analysis was created from table-native queries.",
                anomaly_summary_json={
                    **(detection.get("summary") or {}),
                    "reason": "no_candidates_above_threshold",
                    "fallback_exploration": exploration,
                    "correlation_context": correlation_context,
                },
                quality_json={
                    "status": "fallback_exploration",
                    "runtime_config": runtime_config,
                    "readiness_advisory": readiness_advisory,
                },
            )
            llm_synthesis = _llm_summarize_anomaly_fallback_exploration(
                settings,
                domain_id=state.get("domain_id"),
                context_text=state.get("context_text"),
                dashboard_spec=state.get("dashboard_spec") or {},
                quality_report=quality_report,
                exploration_payload=exploration,
                correlation_context=correlation_context,
            ) or _fallback_anomaly_exploration_payload(
                exploration_payload=exploration,
                quality_report=quality_report,
                correlation_context=correlation_context,
            )
            state["anomaly_investigation_id"] = investigation_id
            state["anomaly_ids"] = []
            state["anomaly_hypothesis_ids"] = []
            state["anomaly_action_ids"] = []
            state["anomaly_executed_queries"] = exploration.get("queries") or []
            state["anomaly_rejected_queries"] = []
            state["anomaly_llm_synthesis"] = llm_synthesis
            state["high_signal_investigative_areas"] = {}
            logger.info(
                "agentic.anomaly_detection.fallback_exploration | run_id=%s version=%s investigation_id=%s queries=%s observations=%s",
                run_id,
                AGENTIC_ANOMALY_FLOW_VERSION,
                investigation_id,
                len(exploration.get("queries") or []),
                len(exploration.get("observations") or []),
            )
            _emit(
                settings,
                run_id,
                "AnomalyDetectionAgent",
                "completed",
                "Anomaly Detection Agent completed",
                {
                    "anomaly_flow_version": AGENTIC_ANOMALY_FLOW_VERSION,
                    "candidate_count": 0,
                    "summary": detection.get("summary") or {},
                    "runtime_config": runtime_config,
                    "reason": "no_candidates_above_threshold",
                    "fallback_mode": "table_native_exploration",
                    "investigation_id": investigation_id,
                    "fallback_attempted": True,
                    "investigation_created": bool(investigation_id),
                    "exploration_query_count": len(exploration.get("queries") or []),
                    "exploration_observation_count": len(exploration.get("observations") or []),
                    "summary_text": llm_synthesis.get("summary_text") if isinstance(llm_synthesis, dict) else None,
                },
                event_callback=event_callback,
            )
            return state

        investigation_id = create_anomaly_investigation(
            settings,
            tenant_id=str(state.get("tenant_id") or ""),
            domain_id=str(state.get("domain_id") or ""),
            run_id=run_id,
            trigger_source="deployment",
            title=f"{str(state.get('domain_id') or 'Domain').replace('_', ' ').title()} Anomaly Investigation",
            dashboard_id=state.get("dashboard_id"),
            source_dashboard_id=state.get("dashboard_id"),
            summary_text=str(((detection.get("summary") or {}).get("top_anomalies") or [{}])[0].get("metric_name") or "Anomalies detected"),
            severity_score=float(((candidates[0].get("evidence") or {}).get("severity_score") or 0.0)),
            confidence_score=float(((candidates[0].get("evidence") or {}).get("confidence_score") or 0.0)),
            anomaly_summary_json={
                **(detection.get("summary") or {}),
                "correlation_context": correlation_context,
            },
            quality_json={
                "status": "phase_38_2_detection_only",
                "runtime_config": runtime_config,
                "correlation_run_id": correlation_context.get("correlation_run_id"),
            },
        )
        created_anomaly_ids: list[str] = []
        fallback_high_signal_areas_by_anomaly: dict[str, list[dict[str, Any]]] = {}
        profiling_map = {
            str(table.get("name") or "").strip(): table
            for table in ((state.get("profiling_stats") or {}).get("tables") or [])
            if str(table.get("name") or "").strip()
        }
        for candidate in candidates:
            evidence = candidate.get("evidence") or {}
            anomaly_id = create_anomaly_record(
                settings,
                investigation_id=investigation_id,
                tenant_id=str(state.get("tenant_id") or ""),
                domain_id=str(state.get("domain_id") or ""),
                metric_id=str(candidate.get("metric_id") or "") or None,
                raw_signal_name=str(candidate.get("raw_signal_name") or "") or None,
                anomaly_type=str(candidate.get("anomaly_type") or "deviation"),
                entity_scope_json={
                    "table_name": candidate.get("table_name"),
                    "time_column": candidate.get("time_column"),
                    "grain": candidate.get("grain"),
                    "dashboard_id": state.get("dashboard_id"),
                },
                baseline_window_json={
                    "window_points": 7,
                    "period": evidence.get("period"),
                    "baseline": evidence.get("baseline"),
                },
                comparison_window_json={
                    "actual": evidence.get("actual"),
                    "deviation": evidence.get("deviation"),
                    "z_score": evidence.get("z_score"),
                },
                severity_score=float(evidence.get("severity_score") or 0.0),
                confidence_score=float(evidence.get("confidence_score") or 0.0),
                evidence_json=evidence,
            )
            table_profile = profiling_map.get(str(candidate.get("table_name") or "").strip()) or {}
            areas = rank_high_signal_investigative_areas(
                settings,
                schema_name=str(state.get("schema_name") or "public"),
                candidate=candidate,
                table_profile=table_profile,
            )
            if areas:
                fallback_high_signal_areas_by_anomaly[anomaly_id] = areas
                update_anomaly_record(
                    settings,
                    anomaly_id,
                    evidence_json={
                        **evidence,
                        "fallback_high_signal_investigative_areas": areas,
                    },
                )
            created_anomaly_ids.append(anomaly_id)
        state["anomaly_investigation_id"] = investigation_id
        state["anomaly_ids"] = created_anomaly_ids
        anomalies_payload = []
        for idx, candidate in enumerate(candidates):
            anomaly_id = created_anomaly_ids[idx] if idx < len(created_anomaly_ids) else None
            anomalies_payload.append(
                {
                    "anomaly_id": anomaly_id,
                    "candidate_type": candidate.get("candidate_type"),
                    "metric_name": candidate.get("metric_name"),
                    "raw_signal_name": candidate.get("raw_signal_name"),
                    "table_name": candidate.get("table_name"),
                    "time_column": candidate.get("time_column"),
                    "grain": candidate.get("grain"),
                    "evidence": candidate.get("evidence") or {},
                    "high_signal_investigative_areas": fallback_high_signal_areas_by_anomaly.get(str(anomaly_id or ""), []),
                }
            )
        anomalies_payload = _enrich_anomalies_with_correlation_context(anomalies_payload, correlation_context)
        llm_plan = _llm_plan_anomaly_investigation(
            settings,
            domain_id=state.get("domain_id"),
            context_text=state.get("context_text"),
            dashboard_spec=state.get("dashboard_spec") or {},
            investigation_summary={
                **(detection.get("summary") or {}),
                "correlation_context": correlation_context.get("summary") or {},
            },
            anomalies_payload=anomalies_payload,
            correlation_context=correlation_context,
        )
        logger.info(
            "agentic.anomaly_detection.plan | run_id=%s plan_present=%s prioritized_ids=%s",
            run_id,
            bool(llm_plan),
            [str(v) for v in ((llm_plan or {}).get("prioritized_anomaly_ids") or [])[:5]],
        )
        llm_prioritized_anomaly_ids = [str(v) for v in ((llm_plan or {}).get("prioritized_anomaly_ids") or []) if str(v).strip()]
        llm_high_signal_areas_by_anomaly = _validate_llm_prioritized_areas(anomalies_payload, llm_plan)
        effective_high_signal_areas_by_anomaly = llm_high_signal_areas_by_anomaly or fallback_high_signal_areas_by_anomaly
        executed_queries: list[dict[str, Any]] = []
        rejected_queries: list[dict[str, Any]] = []
        llm_synthesis: dict[str, Any] | None = None
        planning_failed = False
        if llm_plan:
            executed_queries, rejected_queries = _execute_llm_evidence_queries(
                settings,
                schema_name=str(state.get("schema_name") or "public"),
                profiling_stats=state.get("profiling_stats", {}) or {},
                evidence_queries=[item for item in (llm_plan.get("evidence_queries") or []) if isinstance(item, dict)],
                max_queries=max_evidence_queries,
                row_limit=evidence_query_row_limit,
                scoped_conn=_scoped_conn_from_state(state, settings),
            )
            logger.info(
                "agentic.anomaly_detection.queries | run_id=%s executed=%s rejected=%s",
                run_id,
                len(executed_queries),
                len(rejected_queries),
            )
            llm_synthesis = _llm_summarize_anomaly_investigation(
                settings,
                domain_id=state.get("domain_id"),
                context_text=state.get("context_text"),
                dashboard_spec=state.get("dashboard_spec") or {},
                investigation_summary={
                    **(detection.get("summary") or {}),
                    "planning_summary": llm_plan.get("planning_summary"),
                    "evidence_focus": llm_plan.get("evidence_focus"),
                    "prioritized_anomaly_ids": llm_prioritized_anomaly_ids,
                    "prioritized_investigative_areas": llm_high_signal_areas_by_anomaly,
                    "correlation_context": correlation_context.get("summary") or {},
                },
                anomalies_payload=anomalies_payload,
                executed_queries=executed_queries,
                rejected_queries=rejected_queries,
                correlation_context=correlation_context,
            )
        elif runtime_config["llm_enabled"]:
            planning_failed = True
        if not llm_synthesis:
            logger.info("agentic.anomaly_detection.fallback | run_id=%s reason=no_llm_synthesis", run_id)
            llm_synthesis = _fallback_anomaly_investigation_payload(
                anomalies_payload=anomalies_payload,
                high_signal_areas_by_anomaly=effective_high_signal_areas_by_anomaly,
                executed_queries=executed_queries,
                correlation_context=correlation_context,
            )
        for anomaly_id in created_anomaly_ids:
            candidate = next((item for item in anomalies_payload if str(item.get("anomaly_id") or "") == anomaly_id), None)
            if not candidate:
                continue
            evidence = dict(candidate.get("evidence") or {})
            update_anomaly_record(
                settings,
                anomaly_id,
                evidence_json={
                    **evidence,
                    "high_signal_investigative_areas": effective_high_signal_areas_by_anomaly.get(anomaly_id, []),
                    "fallback_high_signal_investigative_areas": fallback_high_signal_areas_by_anomaly.get(anomaly_id, []),
                    "related_correlation_anomalies": candidate.get("related_correlation_anomalies") or [],
                    "related_correlations": candidate.get("related_correlations") or [],
                    "related_investigation_threads": candidate.get("related_investigation_threads") or [],
                    "correlation_run_id": correlation_context.get("correlation_run_id"),
                },
            )
        if llm_synthesis:
            created_hypothesis_ids: list[str] = []
            for idx, item in enumerate([h for h in (llm_synthesis.get("hypotheses") or []) if isinstance(h, dict)], start=1):
                item_confidence = _normalize_confidence_score(item.get("confidence"), 0.0)
                if item_confidence < min_hypothesis_confidence:
                    continue
                linked_anomaly_ids = [str(v) for v in (item.get("anomaly_ids") or []) if str(v).strip()]
                hypothesis_id = create_anomaly_hypothesis(
                    settings,
                    investigation_id=investigation_id,
                    anomaly_id=linked_anomaly_ids[0] if linked_anomaly_ids else None,
                    rank_no=idx,
                    title=str(item.get("title") or f"Hypothesis {idx}"),
                    explanation_text=str(item.get("explanation") or ""),
                    confidence_score=item_confidence if item.get("confidence") is not None else None,
                    likely_drivers_json=item.get("likely_drivers") or [],
                    supporting_evidence_json=item.get("supporting_evidence") or {"query_results": executed_queries},
                    validation_step_text=item.get("validation_step"),
                    provenance_json={"source": "llm_anomaly_investigation"},
                )
                created_hypothesis_ids.append(hypothesis_id)
            hypothesis_title_map = {
                str((item.get("title") or f"Hypothesis {idx}")).strip(): created_hypothesis_ids[idx - 1]
                for idx, item in enumerate([h for h in (llm_synthesis.get("hypotheses") or []) if isinstance(h, dict)], start=1)
                if idx - 1 < len(created_hypothesis_ids)
            }
            created_action_ids: list[str] = []
            for item in [a for a in (llm_synthesis.get("actions") or []) if isinstance(a, dict)]:
                linked_titles = [str(v) for v in (item.get("linked_hypothesis_titles") or []) if str(v).strip()]
                linked_hypothesis_id = next((hypothesis_title_map.get(title) for title in linked_titles if hypothesis_title_map.get(title)), None)
                action_id = create_anomaly_action(
                    settings,
                    investigation_id=investigation_id,
                    hypothesis_id=linked_hypothesis_id,
                    action_type=str(item.get("action_type") or "prescriptive"),
                    priority=str(item.get("priority") or "") or None,
                    confidence_score=_normalize_confidence_score(item.get("confidence"), 0.0)
                    if item.get("confidence") is not None
                    else None,
                    recommended_owner=str(item.get("recommended_owner") or "") or None,
                    action_text=str(item.get("action_text") or ""),
                    metadata_json={"linked_hypothesis_titles": linked_titles},
                )
                created_action_ids.append(action_id)
            update_anomaly_investigation(
                settings,
                investigation_id,
                status="completed",
                summary_text=str(llm_synthesis.get("summary_text") or ""),
                anomaly_summary_json={
                    **(detection.get("summary") or {}),
                    "investigation_id": investigation_id,
                    "anomaly_ids": created_anomaly_ids,
                    "prioritized_anomaly_ids": llm_prioritized_anomaly_ids,
                    "high_signal_investigative_areas": effective_high_signal_areas_by_anomaly,
                    "fallback_high_signal_investigative_areas": fallback_high_signal_areas_by_anomaly,
                    "planning_summary": (llm_plan or {}).get("planning_summary"),
                    "evidence_focus": (llm_plan or {}).get("evidence_focus"),
                    "executed_queries": executed_queries,
                    "rejected_queries": rejected_queries,
                    "hypothesis_ids": created_hypothesis_ids,
                    "action_ids": created_action_ids,
                    "insights": llm_synthesis.get("insights") or [],
                    "dashboard_suggestions": llm_synthesis.get("dashboard_suggestions") or [],
                    "correlation_context": correlation_context,
                },
                quality_json={
                    "status": "llm_anomaly_investigation_completed" if llm_plan else "deterministic_fallback_completed",
                    "anomaly_prioritization_source": "llm" if llm_prioritized_anomaly_ids else "deterministic_fallback",
                    "investigative_area_source": "llm" if llm_high_signal_areas_by_anomaly else "deterministic_fallback",
                    "executed_query_count": len(executed_queries),
                    "rejected_query_count": len(rejected_queries),
                    "hypothesis_count": len(created_hypothesis_ids),
                    "action_count": len(created_action_ids),
                    "planning_failed": planning_failed,
                    "runtime_config": runtime_config,
                    "correlation_run_id": correlation_context.get("correlation_run_id"),
                    "warnings": [
                        item
                        for item in [
                            "llm_planning_unavailable" if planning_failed else None,
                            "no_hypotheses_above_confidence_threshold" if not created_hypothesis_ids else None,
                            "evidence_queries_rejected" if rejected_queries else None,
                            "using_deterministic_investigation_fallback" if not llm_plan else None,
                        ]
                        if item
                    ],
                },
            )
            logger.info(
                "agentic.anomaly_detection.persisted | run_id=%s investigation_id=%s hypotheses=%s actions=%s status=completed",
                run_id,
                investigation_id,
                len(created_hypothesis_ids),
                len(created_action_ids),
            )
            state["anomaly_hypothesis_ids"] = created_hypothesis_ids
            state["anomaly_action_ids"] = created_action_ids
            state["anomaly_insights"] = llm_synthesis.get("insights") or []
            state["anomaly_llm_synthesis"] = llm_synthesis
            state["anomaly_llm_plan"] = llm_plan or {}
            state["anomaly_executed_queries"] = executed_queries
            state["anomaly_rejected_queries"] = rejected_queries
            state["anomaly_correlation_context"] = correlation_context
        else:
            state["anomaly_llm_synthesis"] = {}
            state["anomaly_llm_plan"] = llm_plan or {}
            state["anomaly_executed_queries"] = executed_queries
            state["anomaly_rejected_queries"] = rejected_queries
            state["anomaly_correlation_context"] = correlation_context
        state["high_signal_investigative_areas"] = effective_high_signal_areas_by_anomaly
        _emit(
            settings,
            run_id,
            "AnomalyDetectionAgent",
            "completed",
            "Anomaly Detection Agent completed",
            {
                "investigation_id": investigation_id,
                "candidate_count": len(candidates),
                "anomaly_ids": created_anomaly_ids,
                "prioritized_anomaly_ids": llm_prioritized_anomaly_ids,
                "high_signal_investigative_areas": effective_high_signal_areas_by_anomaly,
                "fallback_high_signal_investigative_areas": fallback_high_signal_areas_by_anomaly,
                "executed_queries": executed_queries,
                "rejected_queries": rejected_queries,
                "hypothesis_ids": state.get("anomaly_hypothesis_ids") or [],
                "action_ids": state.get("anomaly_action_ids") or [],
                "anomaly_insights": state.get("anomaly_insights") or [],
                "summary": detection.get("summary") or {},
                "runtime_config": runtime_config,
                "correlation_run_id": correlation_context.get("correlation_run_id"),
                "correlation_summary": correlation_context.get("summary"),
            },
            event_callback=event_callback,
        )
        return state

    def anomaly_dashboard_node(state: dict[str, Any]) -> dict[str, Any]:
        logger.info(
            "agentic.anomaly_dashboard.enter | run_id=%s investigation_id=%s executed_queries=%s hypotheses=%s actions=%s",
            run_id,
            state.get("anomaly_investigation_id"),
            len(state.get("anomaly_executed_queries") or []),
            len(state.get("anomaly_hypothesis_ids") or []),
            len(state.get("anomaly_action_ids") or []),
        )
        _emit(
            settings,
            run_id,
            "AnomalyDashboardAgent",
            "running",
            "Anomaly Dashboard Agent started",
            {
                "anomaly_flow_version": AGENTIC_ANOMALY_FLOW_VERSION,
            },
            event_callback=event_callback,
        )
        _emit(
            settings,
            run_id,
            "AnomalyDashboardAgent",
            "running",
            "phase52-anomaly-dashboard-node-entered",
            {
                "build_version": phase52_build_version,
                "anomaly_flow_version": AGENTIC_ANOMALY_FLOW_VERSION,
                "tenant_id": state.get("tenant_id"),
                "domain_id": state.get("domain_id"),
            },
            event_callback=event_callback,
        )
        if not _env_bool("AGENTIC_ANOMALY_DASHBOARD_ENABLED", True):
            logger.info("agentic.anomaly_dashboard.skip | run_id=%s reason=disabled", run_id)
            if investigation_id := str(state.get("anomaly_investigation_id") or "").strip():
                _persist_anomaly_workspace_context(
                    settings,
                    state=state,
                    investigation_id=investigation_id,
                    summary_text=(state.get("anomaly_llm_synthesis") or {}).get("summary_text"),
                    anomaly_ids=[str(v) for v in (state.get("anomaly_ids") or []) if str(v).strip()],
                    hypothesis_ids=[str(v) for v in (state.get("anomaly_hypothesis_ids") or []) if str(v).strip()],
                    action_ids=[str(v) for v in (state.get("anomaly_action_ids") or []) if str(v).strip()],
                    dashboard_id=None,
                )
            _emit(
                settings,
                run_id,
                "AnomalyDashboardAgent",
                "completed",
                "Anomaly Dashboard Agent skipped",
                {"reason": "disabled"},
                event_callback=event_callback,
            )
            return state
        investigation_id = str(state.get("anomaly_investigation_id") or "").strip()
        llm_synthesis = state.get("anomaly_llm_synthesis") or {}
        executed_queries = state.get("anomaly_executed_queries") or []
        if not investigation_id or not llm_synthesis:
            logger.info(
                "agentic.anomaly_dashboard.skip | run_id=%s version=%s reason=insufficient_artifacts investigation_id=%s has_synthesis=%s executed_queries=%s",
                run_id,
                AGENTIC_ANOMALY_FLOW_VERSION,
                investigation_id,
                bool(llm_synthesis),
                len(executed_queries),
            )
            if investigation_id:
                _persist_anomaly_workspace_context(
                    settings,
                    state=state,
                    investigation_id=investigation_id,
                    summary_text=llm_synthesis.get("summary_text") if isinstance(llm_synthesis, dict) else None,
                    anomaly_ids=[str(v) for v in (state.get("anomaly_ids") or []) if str(v).strip()],
                    hypothesis_ids=[str(v) for v in (state.get("anomaly_hypothesis_ids") or []) if str(v).strip()],
                    action_ids=[str(v) for v in (state.get("anomaly_action_ids") or []) if str(v).strip()],
                    dashboard_id=None,
                )
            _emit(
                settings,
                run_id,
                "AnomalyDashboardAgent",
                "completed",
                "Anomaly Dashboard Agent skipped",
                {
                    "reason": "insufficient_artifacts",
                    "anomaly_flow_version": AGENTIC_ANOMALY_FLOW_VERSION,
                    "investigation_id": investigation_id or None,
                    "has_synthesis": bool(llm_synthesis),
                    "executed_query_count": len(executed_queries),
                },
                event_callback=event_callback,
            )
            return state
        quality_warnings = [
            item
            for item in (
                (((state.get("anomaly_detection") or {}).get("summary") or {}).get("candidate_count_after_threshold") or 0) == 0 and "no_candidates_above_threshold" or None,
                (not executed_queries) and "no_executed_evidence_queries" or None,
                (state.get("anomaly_rejected_queries") or []) and "evidence_queries_rejected" or None,
                not (state.get("anomaly_hypothesis_ids") or []) and "no_persisted_hypotheses" or None,
            )
            if item
        ]

        anomaly_dashboard_spec = build_anomaly_dashboard_spec(
            domain_id=state.get("domain_id"),
            investigation_id=investigation_id,
            anomaly_ids=[str(v) for v in (state.get("anomaly_ids") or []) if str(v).strip()],
            hypothesis_ids=[str(v) for v in (state.get("anomaly_hypothesis_ids") or []) if str(v).strip()],
            action_ids=[str(v) for v in (state.get("anomaly_action_ids") or []) if str(v).strip()],
            summary_text=llm_synthesis.get("summary_text"),
            insights=[str(v) for v in (llm_synthesis.get("insights") or []) if str(v).strip()],
            hypotheses=[item for item in (llm_synthesis.get("hypotheses") or []) if isinstance(item, dict)],
            actions=[item for item in (llm_synthesis.get("actions") or []) if isinstance(item, dict)],
            high_signal_areas=state.get("high_signal_investigative_areas") or {},
            executed_queries=[item for item in executed_queries if isinstance(item, dict)],
            dashboard_suggestions=llm_synthesis.get("dashboard_suggestions") or [],
            quality={
                "confidence": None,
                "warnings": quality_warnings,
                "runtime_config": state.get("anomaly_runtime_config") or {},
            },
        )
        dashboard_title = str(anomaly_dashboard_spec.get("dashboard_title") or anomaly_dashboard_spec.get("title") or "Anomaly Investigation Dashboard")
        enriched_charts: list[dict[str, Any]] = []
        chart_ids: list[str] = []
        for chart in [item for item in (anomaly_dashboard_spec.get("charts") or []) if isinstance(item, dict)]:
            rows = [row for row in (chart.get("chart_data") or []) if isinstance(row, dict)]
            metric_name = str(chart.get("metric") or "value")
            dimensions = [str(v) for v in (chart.get("dimensions") or []) if str(v).strip()]
            chart_type = chart.get("type") or infer_chart_type(dimensions, rows, [metric_name]) or "bar"
            chart_sql = chart.get("sql")
            chart_params = chart.get("params") or []
            source_dimensions = _interaction_source_dimensions(
                dimensions=dimensions,
                time_column=str(chart.get("time_column") or "").strip() or None,
                category_column=str(chart.get("category_column") or "").strip() or None,
            )
            chart_id = create_chart_request(
                settings,
                state.get("tenant_id") or "",
                state.get("domain_id"),
                question=chart.get("title"),
                query_payload={
                    "metrics": [metric_name],
                    "dimensions": dimensions,
                    "source_dimensions": source_dimensions,
                    "chart": chart_type,
                    "chart_title": chart.get("title"),
                    "dashboard_title": dashboard_title,
                    "investigation_id": investigation_id,
                    "time_column": chart.get("time_column"),
                    "time_grain": chart.get("time_grain"),
                    "category_column": chart.get("category_column"),
                },
                sql=chart_sql,
                params=chart_params,
                rows_json=rows,
                run_id=run_id or None,
                chart_source="agentic_run",
                title=chart.get("title"),
                created_by="AnomalyDetectionAgent",
            ).get("chart_id")
            payload = build_chart_payload(chart_type, rows, metric_name, dimensions or ["category"])
            dim_key = dimensions[0] if dimensions else None
            interaction_context = build_chart_interaction_context_for_creation(
                settings,
                chart_row={
                    "chart_id": chart_id,
                    "tenant_id": state.get("tenant_id"),
                    "domain_id": state.get("domain_id"),
                    "query_payload": {
                        "metrics": [metric_name],
                        "dimensions": dimensions,
                        "source_dimensions": source_dimensions,
                        "chart": chart_type,
                        "chart_title": chart.get("title"),
                        "dashboard_title": dashboard_title,
                        "investigation_id": investigation_id,
                        "table": (((chart.get("metadata") or {}).get("table")) or (chart.get("table"))),
                        "time_column": chart.get("time_column"),
                        "time_grain": chart.get("time_grain"),
                        "category_column": chart.get("category_column"),
                    },
                    "sql": chart_sql,
                    "rows_json": rows,
                },
                tenant_id=str(state.get("tenant_id") or ""),
                domain_id=str(state.get("domain_id") or "").strip() or None,
                hierarchies=state.get("business_hierarchies") if isinstance(state.get("business_hierarchies"), list) else None,
            )
            inference = build_chart_inference(
                settings,
                chart_type=chart_type,
                rows=rows,
                metric_name=metric_name,
                dim_key=dim_key,
                chart_title=chart.get("title"),
            )
            contextual_narration = _llm_narrate_contextual_chart(
                settings,
                chart_title=str(chart.get("title") or ""),
                chart_type=str(chart_type),
                rows=rows,
                metric_name=metric_name,
                dimensions=dimensions,
                context_text=state.get("context_text"),
                dashboard_title=dashboard_title,
                investigation_summary={
                    "summary_text": llm_synthesis.get("summary_text"),
                    "insights": llm_synthesis.get("insights") or [],
                    "mode": llm_synthesis.get("mode"),
                },
                quality_report=state.get("quality_report") or {},
                correlation_context=_summarize_correlation_context(
                    correlation_run_id=str(state.get("correlation_run_id") or "").strip() or None,
                    correlation_result=state.get("correlation_result") if isinstance(state.get("correlation_result"), dict) else None,
                ),
            )
            insight_text = (contextual_narration or {}).get("insight_text") or inference["insight_text"]
            narrative_text = (contextual_narration or {}).get("narrative_text") or inference["narrative_text"]
            if chart_id:
                update_chart_request(
                    settings,
                    chart_id,
                    status="ready",
                    sql=chart_sql,
                    params=chart_params,
                    rows_json=rows,
                    chart_type=chart_type,
                    chart_payload=payload.get("chart_payload"),
                    chart_data=payload.get("data"),
                    insight_text=insight_text,
                    narrative_text=narrative_text,
                    stats_json=inference["stats_json"],
                    interaction_context_json=interaction_context,
                    root_chart_id=chart_id,
                )
                chart_ids.append(chart_id)
            enriched_charts.append(
                {
                    **chart,
                    "chart_id": chart_id,
                    "chart_type": chart_type,
                    "chart_payload": payload.get("chart_payload"),
                    "chart_data": payload.get("data"),
                    "insight_text": insight_text,
                    "narrative_text": narrative_text,
                    "dashboard_title": dashboard_title,
                }
            )
        anomaly_dashboard_spec["charts"] = enriched_charts
        _anomaly_dash = _create_dashboard(
            settings,
            tenant_id=state.get("tenant_id") or "",
            domain_id=state.get("domain_id") or "",
            name=dashboard_title,
            dashboard_type="system",
            run_id=run_id or None,
        )
        anomaly_dashboard_id = _anomaly_dash.get("dashboard_id")
        for _pos, _cid in enumerate(chart_ids):
            _add_chart_to_dashboard(
                settings, anomaly_dashboard_id, _cid, position=_pos, added_by="AnomalyDetectionAgent",
            )
        create_anomaly_dashboard_link(
            settings,
            investigation_id=investigation_id,
            dashboard_id=anomaly_dashboard_id,
            role="anomaly_dashboard",
            source_dashboard_id=state.get("dashboard_id"),
        )
        if state.get("dashboard_id"):
            create_anomaly_dashboard_link(
                settings,
                investigation_id=investigation_id,
                dashboard_id=state.get("dashboard_id"),
                role="source_dashboard",
                source_dashboard_id=state.get("dashboard_id"),
            )
        update_anomaly_investigation(
            settings,
            investigation_id,
            dashboard_id=anomaly_dashboard_id,
            source_dashboard_id=state.get("dashboard_id"),
        )
        logger.info(
            "agentic.anomaly_dashboard.persisted | run_id=%s investigation_id=%s dashboard_id=%s chart_count=%s",
            run_id,
            investigation_id,
            anomaly_dashboard_id,
            len(enriched_charts),
        )
        _persist_anomaly_workspace_context(
            settings,
            state=state,
            investigation_id=investigation_id,
            summary_text=llm_synthesis.get("summary_text"),
            anomaly_ids=[str(v) for v in (state.get("anomaly_ids") or []) if str(v).strip()],
            hypothesis_ids=[str(v) for v in (state.get("anomaly_hypothesis_ids") or []) if str(v).strip()],
            action_ids=[str(v) for v in (state.get("anomaly_action_ids") or []) if str(v).strip()],
            dashboard_id=anomaly_dashboard_id,
        )
        state["anomaly_dashboard_id"] = anomaly_dashboard_id
        state["anomaly_dashboard_spec"] = anomaly_dashboard_spec
        _emit(
            settings,
            run_id,
            "AnomalyDashboardAgent",
            "completed",
            "Anomaly Dashboard Agent completed",
            {
                "dashboard_id": anomaly_dashboard_id,
                "dashboard_title": dashboard_title,
                "chart_ids": chart_ids,
                "chart_count": len(enriched_charts),
                "investigation_id": investigation_id,
            },
            event_callback=event_callback,
        )
        return state

    def correlation_dashboard_node(state: dict[str, Any]) -> dict[str, Any]:
        logger.info(
            "agentic.correlation_dashboard.enter | run_id=%s correlation_run_id=%s chart_ids=%s",
            run_id,
            state.get("correlation_run_id"),
            len(state.get("correlation_chart_ids") or []),
        )
        _emit(
            settings,
            run_id,
            "CorrelationDashboardAgent",
            "running",
            "Correlation Dashboard Agent started",
            {
                "correlation_flow_version": AGENTIC_CORRELATION_FLOW_VERSION,
            },
            event_callback=event_callback,
        )
        _emit(
            settings,
            run_id,
            "CorrelationDashboardAgent",
            "running",
            "phase52-correlation-dashboard-node-entered",
            {
                "build_version": phase52_build_version,
                "correlation_flow_version": AGENTIC_CORRELATION_FLOW_VERSION,
                "tenant_id": state.get("tenant_id"),
                "domain_id": state.get("domain_id"),
            },
            event_callback=event_callback,
        )
        correlation_run_id = str(state.get("correlation_run_id") or "").strip()
        chart_ids: list[str] = [str(c) for c in (state.get("correlation_chart_ids") or []) if str(c).strip()]
        if not correlation_run_id or not chart_ids:
            logger.info(
                "agentic.correlation_dashboard.skip | run_id=%s version=%s reason=%s correlation_run_id=%s chart_count=%s",
                run_id,
                AGENTIC_CORRELATION_FLOW_VERSION,
                "no_correlation_run_id" if not correlation_run_id else "no_charts",
                correlation_run_id or None,
                len(chart_ids),
            )
            _emit(
                settings,
                run_id,
                "CorrelationDashboardAgent",
                "completed",
                "Correlation Dashboard Agent skipped",
                {
                    "reason": "no_correlation_run_id" if not correlation_run_id else "no_charts",
                    "correlation_flow_version": AGENTIC_CORRELATION_FLOW_VERSION,
                    "correlation_run_id": correlation_run_id or None,
                    "chart_count": len(chart_ids),
                },
                event_callback=event_callback,
            )
            return state
        correlation_result = state.get("correlation_result") or {}
        summary_text = str(correlation_result.get("summary_text") or "").strip()
        dashboard_title = f"Correlation Dashboard — {state.get('domain_id') or 'Domain'}"
        _corr_dash = _create_dashboard(
            settings,
            tenant_id=str(state.get("tenant_id") or ""),
            domain_id=str(state.get("domain_id") or ""),
            name=dashboard_title,
            dashboard_type="system",
            run_id=run_id or None,
        )
        correlation_dashboard_id = (_corr_dash or {}).get("dashboard_id")
        if not correlation_dashboard_id:
            logger.warning(
                "agentic.correlation_dashboard.create_failed | run_id=%s correlation_run_id=%s",
                run_id,
                correlation_run_id,
            )
            _emit(
                settings,
                run_id,
                "CorrelationDashboardAgent",
                "completed",
                "Correlation Dashboard Agent failed to create dashboard",
                {"error": "dashboard_create_failed"},
                event_callback=event_callback,
            )
            return state
        for pos, cid in enumerate(chart_ids):
            _add_chart_to_dashboard(
                settings,
                correlation_dashboard_id,
                cid,
                position=pos,
                added_by="CorrelationDashboardAgent",
            )
        logger.info(
            "agentic.correlation_dashboard.persisted | run_id=%s correlation_run_id=%s dashboard_id=%s chart_count=%s",
            run_id,
            correlation_run_id,
            correlation_dashboard_id,
            len(chart_ids),
        )
        state["correlation_dashboard_id"] = correlation_dashboard_id
        correlation_insights = correlation_result.get("insights") or []
        correlation_quality = {
            "warnings": correlation_result.get("data_quality_warnings") or [],
            "snapshot_eligibility_summary": correlation_result.get("snapshot_eligibility_summary") or {},
        }
        try:
            refresh_id = create_dashboard_refresh_run(
                settings,
                dashboard_id=correlation_dashboard_id,
                tenant_id=str(state.get("tenant_id") or ""),
                domain_id=str(state.get("domain_id") or ""),
                trigger_source="correlation_dashboard_agent",
                requested_by="CorrelationDashboardAgent",
                request_payload={
                    "correlation_run_id": correlation_run_id,
                    "chart_count": len(chart_ids),
                },
            )
            update_dashboard_refresh_status(settings, refresh_id, "completed")
            inference_text = "\n".join(
                str(item.get("detail") or "").strip()
                for item in correlation_insights
                if str(item.get("detail") or "").strip()
            )
            if not inference_text:
                inference_text = (
                    f"Correlation dashboard generated with {len(chart_ids)} charts for run {correlation_run_id}."
                )
            upsert_dashboard_insights_artifact(
                settings,
                refresh_id=refresh_id,
                dashboard_id=correlation_dashboard_id,
                summary_raw_text=summary_text or None,
                summary_html=render_summary_html(
                    summary_text or "Correlation dashboard summary available.",
                    {
                        "correlation_run_id": correlation_run_id,
                        "chart_count": len(chart_ids),
                        "insight_count": len(correlation_insights),
                    },
                ),
                inference_raw_text=inference_text or None,
                inference_html=render_inference_html(
                    inference_text or "Correlation dashboard insights available.",
                    {
                        "top_chart_by_total": None,
                        "correlation_run_id": correlation_run_id,
                        "insights": correlation_insights[:5],
                    },
                ),
                evidence_json={
                    "correlation_run_id": correlation_run_id,
                    "chart_ids": chart_ids,
                    "insights": correlation_insights,
                },
                quality_json=correlation_quality,
            )
            logger.info(
                "agentic.correlation_dashboard.insights_persisted | run_id=%s correlation_run_id=%s dashboard_id=%s summary_present=%s insight_count=%s inference_present=%s",
                run_id,
                correlation_run_id,
                correlation_dashboard_id,
                bool(summary_text),
                len(correlation_insights),
                bool(inference_text),
            )
        except Exception:
            logger.warning(
                "agentic.correlation_dashboard.insights_persist_failed | run_id=%s correlation_run_id=%s dashboard_id=%s",
                run_id,
                correlation_run_id,
                correlation_dashboard_id,
                exc_info=True,
            )
        state["correlation_dashboard_spec"] = {
            "dashboard_id": correlation_dashboard_id,
            "dashboard_title": dashboard_title,
            "correlation_run_id": correlation_run_id,
            "chart_ids": chart_ids,
            "chart_count": len(chart_ids),
            "summary_text": summary_text,
            "summary_html": correlation_result.get("summary_html") or "",
            "insights": correlation_insights,
            "quality": correlation_quality,
        }
        _emit(
            settings,
            run_id,
            "CorrelationDashboardAgent",
            "completed",
            "Correlation Dashboard Agent completed",
            {
                "dashboard_id": correlation_dashboard_id,
                "dashboard_title": dashboard_title,
                "correlation_run_id": correlation_run_id,
                "chart_ids": chart_ids,
                "chart_count": len(chart_ids),
                "insights_preview": correlation_insights[:3],
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
    graph.add_node("correlation", correlation_node)
    graph.add_node("correlation_dashboard", correlation_dashboard_node)
    graph.add_node("anomaly_detection", anomaly_detection_node)
    graph.add_node("anomaly_dashboard", anomaly_dashboard_node)

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
    graph.add_edge("dashboard", "correlation")
    graph.add_edge("correlation", "correlation_dashboard")
    graph.add_edge("correlation_dashboard", "anomaly_detection")
    graph.add_edge("anomaly_detection", "anomaly_dashboard")
    graph.add_edge("anomaly_dashboard", END)
    logger.info(
        "agentic.workflow.graph | run_id=%s nodes=%s anomaly_edges=%s",
        run_id,
        [
            "schema",
            "profiling",
            "context",
            "ontology",
            "glossary",
            "join",
            "metric",
            "model",
            "rollup",
            "chart_planner",
            "quality",
            "dashboard",
            "correlation",
            "anomaly_detection",
            "anomaly_dashboard",
        ],
        [("dashboard", "correlation"), ("correlation", "anomaly_detection"), ("anomaly_detection", "anomaly_dashboard")],
    )

    app = graph.compile()
    logger.info("agentic.workflow.compiled | run_id=%s", run_id)
    result = app.invoke(initial_state)
    pending = _RUN_POSTPROCESS_FUTURES.pop(run_id, [])
    if pending:
        wait(pending)
    logger.info("agentic.workflow.completed | run_id=%s", run_id)
    return result
