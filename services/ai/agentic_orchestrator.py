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
)
from services.ai.semantic_graph_store import persist_semantic_graph
from services.ai.dashboards_store import (
    create_dashboard as _create_dashboard,
    add_chart as _add_chart_to_dashboard,
)
from services.ai.anomaly_detection import detect_agentic_anomalies
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
from services.ai.views import create_views_from_schema, create_joined_views, extract_schema_table_names
from services.ai.charts_store import create_chart_request, update_chart_request
from services.ai.charts import build_chart_payload, infer_chart_type
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
        if cat_col and cat_col not in valid_cols:
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
    system_prompt = (
        "You propose dashboard chart candidates from validated metrics. "
        "Use only the provided metric names, tables, time columns, and category columns. "
        "Prefer KPI trends by day/month and strong operational breakdowns. "
        "Return JSON only with keys: charts, rationale. "
        "Each chart must contain: type, intent, table, metric, time_column, time_grain, category_column, title."
    )
    user_payload = {
        "domain_id": domain_id,
        "context_text": str(context_text or "")[:8000],
        "metrics": metric_payload,
        "tables": table_payload,
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
        raise RuntimeError("LangGraph is not available")

    logger = logging.getLogger(__name__)
    logger.info(
        "agentic.workflow.start | run_id=%s tenant=%s domain=%s schema=%s connection_id=%s database=%s anomaly_enabled=%s anomaly_dashboard_enabled=%s anomaly_llm_mode=%s",
        run_id,
        initial_state.get("tenant_id"),
        initial_state.get("domain_id"),
        initial_state.get("schema_name"),
        initial_state.get("connection_id"),
        initial_state.get("database_name"),
        _env_bool("AGENTIC_ANOMALY_DETECTION_ENABLED", True),
        _env_bool("AGENTIC_ANOMALY_DASHBOARD_ENABLED", True),
        os.getenv("AGENTIC_ANOMALY_LLM_MODE", "auto"),
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
        state["profiling_stats"] = profile_tables(
            settings,
            state.get("schema_graph", {}),
            schema_name,
            scoped_conn=_scoped_conn_from_state(state, settings),
        )
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
        deterministic_candidates = propose_chart_candidates(
            state.get("profiling_stats", {}),
            state.get("metric_defs", []),
            state.get("join_edges", []),
            domain_id=state.get("domain_id"),
        )
        llm_candidates_raw, llm_chart_diag = _llm_propose_chart_candidates(
            settings,
            domain_id=state.get("domain_id"),
            profiling=state.get("profiling_stats", {}) or {},
            metrics=state.get("metric_defs", []) or [],
            context_text=state.get("context_text"),
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
                    cand.get("type"),
                    cand.get("category_column"),
                    cand.get("time_column"),
                    cand.get("time_grain"),
                )
                if key not in {
                    (
                        item.get("table"),
                        item.get("metric"),
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
        profiling_map = {t.get("name"): t for t in (state.get("profiling_stats", {}).get("tables") or [])}
        join_edges = state.get("join_edges") or []
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
            if chart_type == "line" and chart_intent != "multi_series":
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
                            sql = (
                                f"WITH _top_cats AS ("
                                f"SELECT {table_alias}.{_qident(category_col)} AS {cat_alias} "
                                f"FROM {sql_from}"
                                f"{top_cats_where}"
                                f"GROUP BY {cat_alias} "
                                f"ORDER BY {metric_expr} DESC "
                                f"LIMIT {top_n_cats}"
                                f") "
                                f"SELECT {dim_expr} AS {dim_alias}, "
                                f"{table_alias}.{_qident(category_col)} AS {cat_alias}, "
                                f"{metric_expr} AS \"{metric_name}\" "
                                f"FROM {sql_from} "
                                f"JOIN _top_cats ON {table_alias}.{_qident(category_col)} = _top_cats.{cat_alias} "
                                f"{main_where}"
                                f"GROUP BY {dim_alias}, {cat_alias} "
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
                                f"GROUP BY {dim_alias} "
                                f"ORDER BY {dim_alias} DESC "
                                f"LIMIT {line_single_limit}"
                            )
                            dimensions = [dim_alias]
                    elif category_col:
                        dim_alias = "category"
                        sql = (
                            f"SELECT {table_alias}.{_qident(category_col)} AS {dim_alias}, "
                            f"{metric_expr} AS \"{metric_name}\" "
                            f"FROM {sql_from}"
                            f"{where_clause}"
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
                            f"FROM {sql_from}"
                            f"{where_clause}"
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
                    "chart": chart_type,
                    "chart_title": chart_title,
                    "dashboard_title": dashboard_title,
                    "metric_intent": chart.get("metric_intent"),
                    "table": table_name,
                },
                sql=sql,
                params=params,
                rows_json=rows,
                run_id=run_id or None,
                chart_source="agentic_run",
                title=chart_title,
                created_by="DashboardAgent",
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
        )
        narration: dict[str, Any] = {"summary_text": "", "summary_html": ""}
        try:
            narration = narrate_correlation_results(
                settings,
                anomaly_results=result.get("anomaly_results") or [],
                correlation_pairs=result.get("correlation_pairs") or [],
                forward_projections=result.get("forward_projections") or [],
                investigation_threads=result.get("investigation_threads") or [],
            )
        except Exception:
            logger.warning("agentic.correlation.narration_failed | run_id=%s", run_id, exc_info=True)
        save_correlation_run_results(
            settings,
            correlation_run_id=correlation_run_id,
            tenant_id=tenant_id,
            domain_id=domain_id,
            run_result=result,
            summary_text=narration.get("summary_text") or "",
            summary_html=narration.get("summary_html") or "",
        )
        state["correlation_run_id"] = correlation_run_id
        state["correlation_result"] = {
            **result,
            "summary_text": narration.get("summary_text") or "",
            "summary_html": narration.get("summary_html") or "",
        }
        _emit(
            settings,
            run_id,
            "CorrelationAgent",
            "completed",
            "Correlation Agent completed",
            {
                "correlation_run_id": correlation_run_id,
                "analysis_mode": analysis_mode,
                "forecast_periods": forecast_periods,
                "metric_count": result.get("metric_count"),
                "anomaly_count": result.get("anomaly_count"),
                "correlation_pair_count": result.get("correlation_pair_count"),
                "thread_count": result.get("thread_count"),
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
            logger.info("agentic.anomaly_detection.skip | run_id=%s reason=no_candidates_above_threshold", run_id)
            _emit(
                settings,
                run_id,
                "AnomalyDetectionAgent",
                "completed",
                "Anomaly Detection Agent completed",
                {
                    "candidate_count": 0,
                    "summary": detection.get("summary") or {},
                    "runtime_config": runtime_config,
                    "reason": "no_candidates_above_threshold",
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
        if not investigation_id or not llm_synthesis or not executed_queries:
            logger.info(
                "agentic.anomaly_dashboard.skip | run_id=%s reason=insufficient_artifacts investigation_id=%s has_synthesis=%s executed_queries=%s",
                run_id,
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
                {"reason": "insufficient_artifacts"},
                event_callback=event_callback,
            )
            return state
        quality_warnings = [
            item
            for item in (
                (((state.get("anomaly_detection") or {}).get("summary") or {}).get("candidate_count_after_threshold") or 0) == 0 and "no_candidates_above_threshold" or None,
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
            chart_id = create_chart_request(
                settings,
                state.get("tenant_id") or "",
                state.get("domain_id"),
                question=chart.get("title"),
                query_payload={
                    "metrics": [metric_name],
                    "dimensions": dimensions,
                    "chart": chart_type,
                    "chart_title": chart.get("title"),
                    "dashboard_title": dashboard_title,
                    "investigation_id": investigation_id,
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
                )
                chart_ids.append(chart_id)
            enriched_charts.append(
                {
                    **chart,
                    "chart_id": chart_id,
                    "chart_type": chart_type,
                    "chart_payload": payload.get("chart_payload"),
                    "chart_data": payload.get("data"),
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
    graph.add_edge("correlation", "anomaly_detection")
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
