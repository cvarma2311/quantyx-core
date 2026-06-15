from __future__ import annotations

from decimal import Decimal
from hashlib import sha1
from typing import Any
import json
import logging
import os
import re
import ssl
import urllib.request
from urllib.parse import quote

from services.ai.agentic_agents import build_schema_graph
from services.ai.config import Settings
from services.ai.connection_registry import resolve_database_credentials_cached
from services.ai.db import run_query
from services.ai.data_quality_evidence import fetch_final_dataset_rows, fetch_rule_records, fetch_stage_evidence
from services.ai.data_quality_rules import derive_quality_rule_label
from services.ai.data_quality_store import (
    get_quality_run_by_run_id,
    list_quality_dataset_stages,
    list_quality_rules,
    list_quality_tables,
    list_quality_trends,
)
from services.ai.glossary import upsert_glossary_terms
from services.ai.workspace_store import get_deployment_run, list_runs_by_trend_scope


context = ssl._create_unverified_context()

logger = logging.getLogger(__name__)


def _business_term_summary_path(*, tenant_id: str, domain_id: str, run_id: str, normalized_term: str) -> str:
    return (
        f"/data-quality/trends/business-terms?tenant_id={tenant_id}&domain_id={domain_id}"
        f"&run_id={run_id}&term={quote(normalized_term)}"
    )


def _business_term_records_path(*, tenant_id: str, domain_id: str, run_id: str, normalized_term: str) -> str:
    return (
        f"/data-quality/trends/business-terms/records?tenant_id={tenant_id}&domain_id={domain_id}"
        f"&run_id={run_id}&term={quote(normalized_term)}"
    )


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_scope_token(value: Any) -> str:
    text = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")
    return text


def normalize_trend_scope_key(value: str | None) -> str | None:
    text = _normalize_scope_token(value)
    if not text:
        return None
    return text[:120]


def _trend_scope_llm_enabled(settings: Settings | None) -> bool:
    return bool(settings and getattr(settings, "openai_api_key", None))


def _business_term_llm_enabled(settings: Settings | None) -> bool:
    mode = os.getenv("DATA_QUALITY_BUSINESS_TERM_LLM_MODE", "auto").strip().lower()
    if mode == "off":
        return False
    return bool(settings and getattr(settings, "openai_api_key", None))


def _business_term_llm_timeout_sec() -> int:
    return max(10, int(os.getenv("DATA_QUALITY_BUSINESS_TERM_LLM_TIMEOUT_SEC", "45")))


def _business_term_llm_model(settings: Settings) -> str:
    return os.getenv("DATA_QUALITY_BUSINESS_TERM_LLM_MODEL", getattr(settings, "openai_model", "gpt-4o-mini"))


def _trend_scope_llm_json(
    settings: Settings | None,
    *,
    system_prompt: str,
    user_payload: dict[str, Any],
) -> dict[str, Any] | None:
    if not _trend_scope_llm_enabled(settings):
        return None
    model = os.getenv("DATA_QUALITY_TREND_SCOPE_MODEL", getattr(settings, "openai_model", "gpt-4o-mini"))
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_payload)},
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
    try:
        with urllib.request.urlopen(request, timeout=45, context=context) as response:
            body = json.loads(response.read().decode("utf-8"))
        return json.loads(body["choices"][0]["message"]["content"])
    except Exception as exc:
        logger.warning("data_quality_trends trend scope llm failed: %s", exc)
        return None


def _business_term_llm_json(
    settings: Settings | None,
    *,
    user_payload: dict[str, Any],
) -> dict[str, Any] | None:
    if not _business_term_llm_enabled(settings):
        return None
    payload = {
        "model": _business_term_llm_model(settings),
        "messages": [
            {
                "role": "system",
                "content": (
                    "You infer stable business glossary terms for enterprise data-quality reporting. "
                    "Return JSON only with key business_terms. "
                    "Each item must include: term, definition, synonyms, abbreviations. "
                    "Prefer reusable business nouns and data concepts over rule phrases. "
                    "Use the supplied glossary if present. Add aliases that map technical column and rule names to the business term. "
                    "Do not emit duplicates, table names without business meaning, or more than 12 terms."
                ),
            },
            {"role": "user", "content": json.dumps(user_payload)},
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
    try:
        with urllib.request.urlopen(request, timeout=_business_term_llm_timeout_sec(), context=context) as response:
            body = json.loads(response.read().decode("utf-8"))
        return json.loads(body["choices"][0]["message"]["content"])
    except Exception as exc:
        logger.warning("data_quality_trends business term llm failed: %s", exc)
        return None


def _scope_type_from_context(context_text: str | None) -> str:
    text = str(context_text or "").lower()
    if any(term in text for term in ["reconcile", "reconciliation", "match", "settlement"]):
        return "reconciliation"
    if any(term in text for term in ["final dataset", "publish", "readiness", "certification"]):
        return "final_dataset"
    return "monitor"


def _trend_scope_fallback(
    *,
    tenant_id: str,
    domain_id: str,
    connection_id: str | None,
    database_name: str | None,
    schema_name: str | None,
    table_names: list[str] | None,
    context_text: str | None,
) -> tuple[str, str]:
    tables = sorted({str(item).strip().lower() for item in (table_names or []) if str(item).strip()})
    scope_type = _scope_type_from_context(context_text)
    parts = [
        _normalize_scope_token(domain_id) or "data_quality",
        scope_type,
    ]
    parts.extend(_normalize_scope_token(item) for item in tables[:4] if _normalize_scope_token(item))
    readable = "_".join(item for item in parts if item)[:80]
    fingerprint = json.dumps(
        {
            "tenant_id": tenant_id,
            "domain_id": domain_id,
            "connection_id": connection_id,
            "database_name": database_name,
            "schema_name": schema_name,
            "tables": tables,
            "scope_type": scope_type,
        },
        sort_keys=True,
    )
    digest = sha1(fingerprint.encode("utf-8")).hexdigest()[:10]
    key = normalize_trend_scope_key(f"{readable}_{digest}") or f"dqscope_{digest}"
    label = " ".join(item.replace("_", " ").title() for item in parts if item) or "Data Quality Monitor"
    return key, label[:120]


def infer_trend_scope_key(
    *,
    tenant_id: str,
    domain_id: str,
    connection_id: str | None,
    database_name: str | None,
    schema_name: str | None,
    table_names: list[str] | None,
    context_text: str | None,
    trend_mode: str | None = None,
    settings: Settings | None = None,
    previous_runs: list[dict[str, Any]] | None = None,
    source_run: dict[str, Any] | None = None,
) -> tuple[str, str]:
    if source_run:
        existing = normalize_trend_scope_key(source_run.get("trend_scope_key"))
        if existing:
            label = str(source_run.get("trend_scope_label") or existing.replace("_", " ").title()).strip()
            return existing, label
    fallback_key, fallback_label = _trend_scope_fallback(
        tenant_id=tenant_id,
        domain_id=domain_id,
        connection_id=connection_id,
        database_name=database_name,
        schema_name=schema_name,
        table_names=table_names,
        context_text=context_text,
    )
    normalized_mode = str(trend_mode or "").strip().lower() or "ad_hoc"
    candidate_runs = [
        row
        for row in (previous_runs or [])
        if normalize_trend_scope_key((row or {}).get("trend_scope_key"))
    ]
    llm_result = _trend_scope_llm_json(
        settings,
        system_prompt=(
            "You infer a stable monitoring scope for enterprise data-quality trend analysis. "
            "Return JSON only with keys decision, selected_existing_scope_key, selected_existing_scope_label, "
            "proposed_scope_key, proposed_scope_label, scope_type, match_confidence, rationale. "
            "If the current run clearly belongs to an existing monitoring family, set decision=reuse_existing "
            "and return the exact selected_existing_scope_key from the candidates. "
            "If the current run is materially different, set decision=create_new and return a short semantic "
            "proposed_scope_key and proposed_scope_label. "
            "Keep proposed_scope_key stable, business-meaningful, snake_case, and free of run-specific data."
        ),
        user_payload={
            "tenant_id": tenant_id,
            "domain_id": domain_id,
            "trend_mode": normalized_mode,
            "current_scope": {
                "connection_id": connection_id,
                "database_name": database_name,
                "schema_name": schema_name,
                "tables": sorted({str(item).strip().lower() for item in (table_names or []) if str(item).strip()}),
                "context_text": str(context_text or ""),
                "fallback_scope_key": fallback_key,
                "fallback_scope_label": fallback_label,
                "scope_type": _scope_type_from_context(context_text),
            },
            "candidate_scopes": [
                {
                    "run_id": row.get("run_id"),
                    "trend_scope_key": normalize_trend_scope_key(row.get("trend_scope_key")),
                    "trend_scope_label": str(row.get("trend_scope_label") or "").strip() or None,
                    "trend_mode": str(row.get("trend_mode") or "").strip() or None,
                    "display_name": str(row.get("display_name") or "").strip() or None,
                    "deployment_payload": {
                        "connection_id": ((row.get("deployment_payload_json") or {}) or {}).get("connection_id"),
                        "database": ((row.get("deployment_payload_json") or {}) or {}).get("database"),
                        "schema_name": ((row.get("deployment_payload_json") or {}) or {}).get("schema_name"),
                        "context_text": ((row.get("deployment_payload_json") or {}) or {}).get("context_text"),
                    },
                }
                for row in candidate_runs[:20]
            ],
        },
    )
    if normalized_mode in {"monitor", "baseline_reset"} and isinstance(llm_result, dict):
        if str(llm_result.get("decision") or "").strip().lower() == "reuse_existing":
            selected = normalize_trend_scope_key(llm_result.get("selected_existing_scope_key"))
            if selected:
                for row in candidate_runs:
                    existing = normalize_trend_scope_key(row.get("trend_scope_key"))
                    if existing == selected:
                        label = str(row.get("trend_scope_label") or llm_result.get("selected_existing_scope_label") or existing.replace("_", " ").title()).strip()
                        return existing, label[:120]
        proposed_key = normalize_trend_scope_key(llm_result.get("proposed_scope_key"))
        proposed_label = str(llm_result.get("proposed_scope_label") or "").strip()
        if proposed_key:
            return proposed_key, (proposed_label or proposed_key.replace("_", " ").title())[:120]
    return fallback_key, fallback_label


def rule_logical_key(rule: dict[str, Any]) -> str:
    normalized = {
        "table_name": str(rule.get("table_name") or "").strip().lower(),
        "column_name": str(rule.get("column_name") or "").strip().lower(),
        "rule_type": str(rule.get("rule_type") or "").strip().lower(),
        "reference_table": str(rule.get("reference_table") or "").strip().lower(),
        "reference_column": str(rule.get("reference_column") or "").strip().lower(),
        "condition_json": rule.get("condition_json") or {},
    }
    return f"rule_{sha1(json.dumps(normalized, sort_keys=True, default=str).encode('utf-8')).hexdigest()[:16]}"


def stage_logical_key(stage: dict[str, Any]) -> str:
    normalized = {
        "stage_type": str(stage.get("stage_type") or "").strip().lower(),
        "stage_name": str(stage.get("stage_name") or "").strip().lower(),
        "output_dataset": str(stage.get("output_dataset") or "").strip().lower(),
        "expression": stage.get("expression") or {},
    }
    return f"stage_{sha1(json.dumps(normalized, sort_keys=True, default=str).encode('utf-8')).hexdigest()[:16]}"


def build_run_metric_snapshots(
    *,
    run_row: dict[str, Any],
    tables: list[dict[str, Any]],
    rules: list[dict[str, Any]],
    stages: list[dict[str, Any]],
    final_dataset: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    summary = run_row.get("summary_json") or {}
    return [
        {"metric_name": "overall_trust_score", "metric_value_num": _as_float(run_row.get("overall_trust_score")), "metric_unit": "score"},
        {"metric_name": "failed_rule_count", "metric_value_num": _as_float(summary.get("failed_rule_count", 0)), "metric_unit": "count"},
        {"metric_name": "duplicate_candidate_count", "metric_value_num": _as_float(summary.get("duplicate_candidate_count", 0)), "metric_unit": "count"},
        {"metric_name": "stale_table_count", "metric_value_num": _as_float(summary.get("stale_table_count", 0)), "metric_unit": "count"},
        {"metric_name": "rejected_record_count", "metric_value_num": _as_float(summary.get("total_rejected_row_count", 0)), "metric_unit": "count"},
        {"metric_name": "final_dataset_row_count", "metric_value_num": _as_float((final_dataset or {}).get("final_row_count") or summary.get("final_dataset_row_count")), "metric_unit": "count"},
        {"metric_name": "final_dataset_readiness_status", "metric_value_text": str((final_dataset or {}).get("readiness_status") or summary.get("final_dataset_readiness_status") or "").strip(), "metric_unit": "status"},
        {"metric_name": "dataset_stage_count", "metric_value_num": _as_float(len(stages)), "metric_unit": "count"},
        {"metric_name": "table_count", "metric_value_num": _as_float(len(tables)), "metric_unit": "count"},
        {"metric_name": "validation_rule_count", "metric_value_num": _as_float(len(rules)), "metric_unit": "count"},
    ]


def build_object_metric_snapshots(
    *,
    tables: list[dict[str, Any]],
    rules: list[dict[str, Any]],
    stages: list[dict[str, Any]],
    final_dataset: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    snapshots: list[dict[str, Any]] = []
    for table in tables:
        table_name = str(table.get("table_name") or "").strip()
        if not table_name:
            continue
        for metric_name, value, unit in [
            ("row_count", table.get("row_count"), "count"),
            ("trust_score", table.get("trust_score"), "score"),
            ("completeness_score", table.get("completeness_score"), "score"),
            ("validity_score", table.get("validity_score"), "score"),
            ("uniqueness_score", table.get("uniqueness_score"), "score"),
            ("referential_integrity_score", table.get("referential_integrity_score"), "score"),
            ("freshness_score", table.get("freshness_score"), "score"),
            ("duplicate_risk_score", table.get("duplicate_risk_score"), "score"),
        ]:
            snapshots.append(
                {
                    "object_type": "table",
                    "object_key": table_name,
                    "object_name": table_name,
                    "metric_name": metric_name,
                    "metric_value_num": _as_float(value),
                    "metric_unit": unit,
                }
            )
    for rule in rules:
        key = rule_logical_key(rule)
        label = str(rule.get("rule_label") or "").strip()
        if not label:
            label = derive_quality_rule_label(rule)
        label = label or str(rule.get("rule_type") or key)
        snapshots.extend(
            [
                {
                    "object_type": "rule",
                    "object_key": key,
                    "object_name": label,
                    "metric_name": "violation_count",
                    "metric_value_num": _as_float(rule.get("violation_count") or 0),
                    "metric_unit": "count",
                },
                {
                    "object_type": "rule",
                    "object_key": key,
                    "object_name": label,
                    "metric_name": "violation_pct",
                    "metric_value_num": _as_float(rule.get("violation_pct")),
                    "metric_unit": "pct",
                },
                {
                    "object_type": "rule",
                    "object_key": key,
                    "object_name": label,
                    "metric_name": "result_status",
                    "metric_value_text": str(rule.get("result_status") or rule.get("status") or "").strip(),
                    "metric_unit": "status",
                },
            ]
        )
    for stage in stages:
        key = stage_logical_key(stage)
        name = str(stage.get("stage_name") or key)
        for metric_name, value, unit in [
            ("input_row_count", stage.get("input_row_count"), "count"),
            ("output_row_count", stage.get("output_row_count"), "count"),
            ("rejected_row_count", stage.get("rejected_row_count"), "count"),
        ]:
            snapshots.append(
                {
                    "object_type": "stage",
                    "object_key": key,
                    "object_name": name,
                    "metric_name": metric_name,
                    "metric_value_num": _as_float(value),
                    "metric_unit": unit,
                }
            )
    if final_dataset:
        snapshots.extend(
            [
                {
                    "object_type": "final_dataset",
                    "object_key": "final_dataset",
                    "object_name": "Final Dataset",
                    "metric_name": "final_row_count",
                    "metric_value_num": _as_float(final_dataset.get("final_row_count")),
                    "metric_unit": "count",
                },
                {
                    "object_type": "final_dataset",
                    "object_key": "final_dataset",
                    "object_name": "Final Dataset",
                    "metric_name": "readiness_status",
                    "metric_value_text": str(final_dataset.get("readiness_status") or "").strip(),
                    "metric_unit": "status",
                },
            ]
        )
    return snapshots


_HIGHER_IS_BETTER = {
    "overall_trust_score",
    "trust_score",
    "completeness_score",
    "validity_score",
    "uniqueness_score",
    "referential_integrity_score",
    "freshness_score",
    "output_row_count",
    "final_row_count",
}
_LOWER_IS_BETTER = {
    "failed_rule_count",
    "duplicate_candidate_count",
    "rejected_record_count",
    "violation_count",
    "violation_pct",
    "rejected_row_count",
}
_STATUS_METRICS = {"final_dataset_readiness_status", "readiness_status", "result_status"}


def _directionality(metric_name: str) -> str:
    if metric_name in _HIGHER_IS_BETTER:
        return "higher_better"
    if metric_name in _LOWER_IS_BETTER:
        return "lower_better"
    if metric_name in _STATUS_METRICS:
        return "status_transition"
    return "neutral"


def _classify_status(metric_name: str, previous: str | None, current: str | None) -> str:
    prev = str(previous or "").strip().lower()
    curr = str(current or "").strip().lower()
    if not prev:
        return "baseline"
    if prev == curr:
        return "unchanged"
    readiness_rank = {"blocked": 0, "warning": 1, "ready": 2, "passed": 2, "failed": 0}
    if metric_name in {"final_dataset_readiness_status", "readiness_status"} and prev in readiness_rank and curr in readiness_rank:
        return "improved" if readiness_rank[curr] > readiness_rank[prev] else "worsened"
    if metric_name == "result_status":
        if prev in {"failed", "error"} and curr in {"passed", "completed", "active"}:
            return "resolved"
        if prev in {"passed", "completed", "active"} and curr in {"failed", "error"}:
            return "newly_introduced"
    return "changed"


def build_trend_rows(
    *,
    current_run_id: str,
    baseline_run_id: str | None,
    current_snapshots: list[dict[str, Any]],
    previous_snapshots: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    previous_index = {
        (
            str(item.get("object_type") or "run"),
            str(item.get("object_key") or "__run__"),
            str(item.get("metric_name") or ""),
        ): item
        for item in previous_snapshots
    }
    trends: list[dict[str, Any]] = []
    for item in current_snapshots:
        object_type = str(item.get("object_type") or "run")
        object_key = str(item.get("object_key") or "__run__")
        metric_name = str(item.get("metric_name") or "")
        previous = previous_index.get((object_type, object_key, metric_name))
        directionality = _directionality(metric_name)
        current_num = _as_float(item.get("metric_value_num"))
        previous_num = _as_float((previous or {}).get("metric_value_num"))
        current_text = str(item.get("metric_value_text") or "").strip() or None
        previous_text = str((previous or {}).get("metric_value_text") or "").strip() or None
        delta_value = None
        delta_pct = None
        if current_num is not None and previous_num is not None:
            delta_value = current_num - previous_num
            delta_pct = ((delta_value / previous_num) * 100.0) if previous_num not in (0.0, None) else None
            if directionality == "higher_better":
                status = "improved" if delta_value > 0 else "worsened" if delta_value < 0 else "unchanged"
            elif directionality == "lower_better":
                status = "improved" if delta_value < 0 else "worsened" if delta_value > 0 else "unchanged"
            else:
                status = "changed" if delta_value else "unchanged"
        elif directionality == "status_transition":
            status = _classify_status(metric_name, previous_text, current_text)
        else:
            status = "baseline" if previous is None else "changed"
        trends.append(
            {
                "baseline_run_id": baseline_run_id,
                "object_type": object_type,
                "object_key": object_key,
                "object_name": item.get("object_name"),
                "metric_name": metric_name,
                "previous_value_num": previous_num,
                "previous_value_text": previous_text,
                "current_value_num": current_num,
                "current_value_text": current_text,
                "delta_value": delta_value,
                "delta_pct": round(delta_pct, 4) if delta_pct is not None else None,
                "trend_status": status,
                "directionality": directionality,
                "summary_json": {
                    "current_run_id": current_run_id,
                    "baseline_run_id": baseline_run_id,
                    "metric_unit": item.get("metric_unit"),
                },
            }
        )
    return trends


def summarize_trends(trends: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "trend_row_count": len(trends),
        "improved_metric_count": sum(1 for item in trends if str(item.get("trend_status")) == "improved"),
        "worsened_metric_count": sum(1 for item in trends if str(item.get("trend_status")) == "worsened"),
        "baseline_metric_count": sum(1 for item in trends if str(item.get("trend_status")) == "baseline"),
        "unchanged_metric_count": sum(1 for item in trends if str(item.get("trend_status")) == "unchanged"),
        "changed_metric_count": sum(1 for item in trends if str(item.get("trend_status")) == "changed"),
    }


def _trend_display_value(row: dict[str, Any], prefix: str) -> Any:
    numeric = row.get(f"{prefix}_value_num")
    if numeric is not None:
        return numeric
    return row.get(f"{prefix}_value_text")


def _normalized_trend_row(
    *,
    row: dict[str, Any],
    tenant_id: str,
    domain_id: str,
    run_id: str,
) -> dict[str, Any]:
    def _evidence_path(item: dict[str, Any]) -> str:
        object_type = str(item.get("object_type") or "").strip()
        object_key = str(item.get("object_key") or "").strip()
        if object_type == "table" and object_key:
            return (
                f"/data-quality/trends/tables/{quote(object_key)}"
                f"?tenant_id={quote(str(tenant_id))}&domain_id={quote(str(domain_id))}&run_id={quote(str(run_id))}"
            )
        if object_type == "rule" and object_key:
            return (
                f"/data-quality/trends/rules/{quote(object_key)}"
                f"?tenant_id={quote(str(tenant_id))}&domain_id={quote(str(domain_id))}&run_id={quote(str(run_id))}"
            )
        if object_type == "stage" and object_key:
            return (
                f"/data-quality/trends/stages/{quote(object_key)}"
                f"?tenant_id={quote(str(tenant_id))}&domain_id={quote(str(domain_id))}&run_id={quote(str(run_id))}"
            )
        if object_type == "run":
            return (
                f"/data-quality/trends/run-summary"
                f"?tenant_id={quote(str(tenant_id))}&domain_id={quote(str(domain_id))}&run_id={quote(str(run_id))}"
            )
        if object_type == "final_dataset":
            return (
                f"/data-quality/trends/final-dataset"
                f"?tenant_id={quote(str(tenant_id))}&domain_id={quote(str(domain_id))}&run_id={quote(str(run_id))}"
            )
        base = (
            f"/data-quality/trends?tenant_id={quote(str(tenant_id))}"
            f"&domain_id={quote(str(domain_id))}&run_id={quote(str(run_id))}"
        )
        if object_type:
            base += f"&object_type={quote(object_type)}"
        if object_key:
            base += f"&object_key={quote(object_key)}"
        metric_name = str(item.get("metric_name") or "").strip()
        if metric_name:
            base += f"&metric_name={quote(metric_name)}"
        return base

    previous_display = _trend_display_value(row, "previous")
    current_display = _trend_display_value(row, "current")
    return {
        "object_type": row.get("object_type"),
        "object_key": row.get("object_key"),
        "object_name": row.get("object_name"),
        "metric_name": row.get("metric_name"),
        "previous_value_num": row.get("previous_value_num"),
        "previous_value_text": row.get("previous_value_text"),
        "previous_display_value": previous_display,
        "current_value_num": row.get("current_value_num"),
        "current_value_text": row.get("current_value_text"),
        "current_display_value": current_display,
        "delta_value": row.get("delta_value"),
        "delta_pct": row.get("delta_pct"),
        "trend_status": row.get("trend_status"),
        "directionality": row.get("directionality"),
        "evidence_path": _evidence_path(row),
    }


def _sort_trend_rows_for_delta(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        rows,
        key=lambda item: (
            -abs(_as_float(item.get("delta_value")) or 0.0),
            str(item.get("object_name") or item.get("object_key") or ""),
            str(item.get("metric_name") or ""),
        ),
    )


def _build_trend_cards(
    *,
    rows: list[dict[str, Any]],
    summary: dict[str, Any],
    baseline_run_id: str | None,
    tenant_id: str,
    domain_id: str,
    run_id: str,
    readiness_overview: dict[str, Any] | None = None,
    business_term_overview: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    run_trust = next(
        (
            item
            for item in rows
            if str(item.get("object_type") or "") == "run"
            and str(item.get("metric_name") or "") == "overall_trust_score"
        ),
        None,
    )
    final_readiness = next(
        (
            item
            for item in rows
            if str(item.get("object_type") or "") == "final_dataset"
            and str(item.get("metric_name") or "") == "readiness_status"
        ),
        None,
    )
    final_rows = next(
        (
            item
            for item in rows
            if str(item.get("object_type") or "") == "final_dataset"
            and str(item.get("metric_name") or "") == "final_row_count"
        ),
        None,
    )
    cards = [
        {
            "card_key": "trend_scope",
            "title": "Trend Scope",
            "value": summary.get("trend_row_count", 0),
            "subtitle": "Tracked Metrics",
            "note": "Baseline run linked" if baseline_run_id else "Baseline run not available yet",
            "trend_status": "baseline" if baseline_run_id is None else "unchanged",
            "evidence_path": None,
        },
        {
            "card_key": "overall_trust_score",
            "title": "Overall Trust Score",
            "value": run_trust.get("current_display_value") if run_trust else None,
            "subtitle": "Run Summary",
            "note": run_trust.get("previous_display_value") if run_trust else None,
            "delta_value": run_trust.get("delta_value") if run_trust else None,
            "delta_pct": run_trust.get("delta_pct") if run_trust else None,
            "trend_status": run_trust.get("trend_status") if run_trust else "baseline",
            "evidence_path": run_trust.get("evidence_path") if run_trust else None,
        },
        {
            "card_key": "final_dataset_readiness",
            "title": "Final Dataset Readiness",
            "value": final_readiness.get("current_display_value") if final_readiness else None,
            "subtitle": "Final Dataset",
            "note": final_readiness.get("previous_display_value") if final_readiness else None,
            "trend_status": final_readiness.get("trend_status") if final_readiness else "baseline",
            "evidence_path": final_readiness.get("evidence_path") if final_readiness else None,
        },
        {
            "card_key": "final_row_count",
            "title": "Final Row Count",
            "value": final_rows.get("current_display_value") if final_rows else None,
            "subtitle": "Final Dataset",
            "note": final_rows.get("previous_display_value") if final_rows else None,
            "delta_value": final_rows.get("delta_value") if final_rows else None,
            "delta_pct": final_rows.get("delta_pct") if final_rows else None,
            "trend_status": final_rows.get("trend_status") if final_rows else "baseline",
            "evidence_path": final_rows.get("evidence_path") if final_rows else None,
        },
    ]
    readiness_overview = dict(readiness_overview or {})
    if readiness_overview:
        readiness_path = str(readiness_overview.get("evidence_path_template") or "").replace(
            "{tenant_id}", quote(str(tenant_id))
        ).replace("{domain_id}", quote(str(domain_id)))
        cards.append(
            {
                "card_key": "publish_readiness",
                "title": "Publish Readiness",
                "value": readiness_overview.get("current_readiness_status"),
                "subtitle": "Certification",
                "note": readiness_overview.get("previous_readiness_status") or "No previous readiness state",
                "trend_status": readiness_overview.get("readiness_trend_status") or "baseline",
                "evidence_path": readiness_path,
            }
        )
    business_term_overview = dict(business_term_overview or {})
    business_term_summary = dict(business_term_overview.get("summary") or {})
    if business_term_summary:
        cards.append(
            {
                "card_key": "business_term_groups",
                "title": "Business Term Groups",
                "value": business_term_summary.get("business_term_group_count", 0),
                "subtitle": "Glossary Trend Coverage",
                "note": f"{business_term_summary.get('worsened_business_term_count', 0)} worsened groups",
                "trend_status": "worsened" if int(business_term_summary.get("worsened_business_term_count") or 0) > 0 else "unchanged",
                "evidence_path": f"/data-quality/trends/business-terms?tenant_id={quote(str(tenant_id))}&domain_id={quote(str(domain_id))}&run_id={quote(str(run_id))}",
            }
        )
    return cards


def _build_trend_chart_plan(
    *,
    rows: list[dict[str, Any]],
    summary: dict[str, Any],
    tenant_id: str,
    domain_id: str,
    run_id: str,
    readiness_overview: dict[str, Any] | None = None,
    business_term_overview: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    base_trend_path = (
        f"/data-quality/trends?tenant_id={quote(str(tenant_id))}"
        f"&domain_id={quote(str(domain_id))}&run_id={quote(str(run_id))}"
    )
    status_chart_rows: list[dict[str, Any]] = []
    for status in ["improved", "worsened", "baseline", "unchanged", "changed"]:
        count = int(summary.get(f"{status}_metric_count") or 0)
        status_chart_rows.append(
            {
                "category": status,
                "value": count,
                "evidence_path": f"{base_trend_path}&trend_status={quote(status)}",
            }
        )

    object_type_counts: dict[str, int] = {}
    for row in rows:
        object_type = str(row.get("object_type") or "unknown")
        object_type_counts[object_type] = object_type_counts.get(object_type, 0) + 1
    object_type_rows = [
        {
            "category": object_type,
            "value": count,
            "evidence_path": f"{base_trend_path}&object_type={quote(object_type)}",
        }
        for object_type, count in sorted(object_type_counts.items(), key=lambda item: (-item[1], item[0]))
    ]

    improved_rows = _sort_trend_rows_for_delta(
        [row for row in rows if str(row.get("trend_status") or "") == "improved" and _as_float(row.get("delta_value")) is not None]
    )[:10]
    worsened_rows = _sort_trend_rows_for_delta(
        [row for row in rows if str(row.get("trend_status") or "") == "worsened" and _as_float(row.get("delta_value")) is not None]
    )[:10]

    def _delta_chart_rows(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "label": f"{item.get('object_name') or item.get('object_key')} - {item.get('metric_name')}",
                "value": _as_float(item.get("delta_value")),
                "delta_pct": item.get("delta_pct"),
                "object_type": item.get("object_type"),
                "object_key": item.get("object_key"),
                "metric_name": item.get("metric_name"),
                "evidence_path": item.get("evidence_path"),
            }
            for item in items
        ]

    chart_plan = [
        {
            "chart_key": "trend_status_distribution",
            "chart_type": "column",
            "title": "Trend Status Distribution",
            "subtitle": "Metric rows grouped by trend status",
            "summary": {
                "total_count": int(summary.get("trend_row_count") or 0),
                "largest_bucket": max((row.get("value") or 0 for row in status_chart_rows), default=0),
            },
            "x_field": "category",
            "y_field": "value",
            "series_fields": ["value"],
            "rows": status_chart_rows,
        },
        {
            "chart_key": "object_type_distribution",
            "chart_type": "pie",
            "title": "Trend Rows by Object Type",
            "subtitle": "Distribution across run, table, rule, and stage metrics",
            "summary": {
                "object_type_count": len(object_type_rows),
                "largest_bucket": max((row.get("value") or 0 for row in object_type_rows), default=0),
            },
            "x_field": "category",
            "y_field": "value",
            "series_fields": ["value"],
            "rows": object_type_rows,
        },
        {
            "chart_key": "top_improved_deltas",
            "chart_type": "bar",
            "title": "Top Improved Deltas",
            "subtitle": "Largest positive changes for the selected run",
            "summary": {
                "row_count": len(improved_rows),
                "largest_delta": max((_as_float(row.get("delta_value")) or 0.0 for row in improved_rows), default=0.0),
            },
            "x_field": "label",
            "y_field": "value",
            "series_fields": ["value"],
            "rows": _delta_chart_rows(improved_rows),
        },
        {
            "chart_key": "top_worsened_deltas",
            "chart_type": "bar",
            "title": "Top Worsened Deltas",
            "subtitle": "Largest regressions for the selected run",
            "summary": {
                "row_count": len(worsened_rows),
                "largest_delta": max((abs(_as_float(row.get("delta_value")) or 0.0) for row in worsened_rows), default=0.0),
            },
            "x_field": "label",
            "y_field": "value",
            "series_fields": ["value"],
            "rows": _delta_chart_rows(worsened_rows),
        },
    ]

    readiness_overview = dict(readiness_overview or {})
    if readiness_overview:
        chart_plan.append(
            {
                "chart_key": "publish_readiness",
                "chart_type": "summary_cards",
                "title": "Publish Readiness",
                "subtitle": "Current certification state against the previous comparable run",
                "summary": {
                    "current_readiness_status": readiness_overview.get("current_readiness_status"),
                    "previous_readiness_status": readiness_overview.get("previous_readiness_status"),
                    "certification_blocker_count": readiness_overview.get("certification_blocker_count"),
                    "residual_anomaly_count": readiness_overview.get("residual_anomaly_count"),
                },
                "rows": [
                    {
                        "metric_key": "current_readiness_status",
                        "label": "Current Readiness",
                        "value": readiness_overview.get("current_readiness_status"),
                        "note": readiness_overview.get("previous_readiness_status"),
                        "trend_status": readiness_overview.get("readiness_trend_status"),
                        "evidence_path": str(readiness_overview.get("evidence_path_template") or "").replace(
                            "{tenant_id}", quote(str(tenant_id))
                        ).replace("{domain_id}", quote(str(domain_id))),
                    },
                    {
                        "metric_key": "final_row_count_delta",
                        "label": "Final Row Delta",
                        "value": readiness_overview.get("final_row_count_delta"),
                        "note": readiness_overview.get("final_row_count_delta_pct"),
                        "trend_status": readiness_overview.get("readiness_trend_status"),
                        "evidence_path": str(readiness_overview.get("evidence_path_template") or "").replace(
                            "{tenant_id}", quote(str(tenant_id))
                        ).replace("{domain_id}", quote(str(domain_id))),
                    },
                    {
                        "metric_key": "certification_blocker_count",
                        "label": "Certification Blockers",
                        "value": readiness_overview.get("certification_blocker_count"),
                        "note": readiness_overview.get("open_issue_count"),
                        "trend_status": "worsened" if int(readiness_overview.get("certification_blocker_count") or 0) > 0 else "unchanged",
                        "evidence_path": str(readiness_overview.get("evidence_path_template") or "").replace(
                            "{tenant_id}", quote(str(tenant_id))
                        ).replace("{domain_id}", quote(str(domain_id))),
                    },
                    {
                        "metric_key": "residual_anomaly_count",
                        "label": "Residual Anomalies",
                        "value": readiness_overview.get("residual_anomaly_count"),
                        "note": readiness_overview.get("critical_anomaly_count"),
                        "trend_status": "worsened" if int(readiness_overview.get("critical_anomaly_count") or 0) > 0 else "unchanged",
                        "evidence_path": str(readiness_overview.get("evidence_path_template") or "").replace(
                            "{tenant_id}", quote(str(tenant_id))
                        ).replace("{domain_id}", quote(str(domain_id))),
                    },
                ],
            }
        )

    business_term_overview = dict(business_term_overview or {})
    business_term_rows = [row for row in (business_term_overview.get("rows") or []) if isinstance(row, dict)]
    business_term_summary = dict(business_term_overview.get("summary") or {})
    if business_term_rows or business_term_summary:
        chart_plan.append(
            {
                "chart_key": "business_term_trends",
                "chart_type": "table",
                "title": "Business Term Trends",
                "subtitle": "Glossary-grouped trend coverage for the current run",
                "summary": business_term_summary,
                "columns": [
                    {"field": "business_term", "label": "Business Term"},
                    {"field": "trend_row_count", "label": "Trend Rows"},
                    {"field": "improved_metric_count", "label": "Improved"},
                    {"field": "worsened_metric_count", "label": "Worsened"},
                    {"field": "baseline_metric_count", "label": "Baseline"},
                    {"field": "affected_object_count", "label": "Affected Objects"},
                    {"field": "evidence_path", "label": "Evidence"},
                ],
                "rows": business_term_rows,
            }
        )

    return chart_plan


def _build_trend_groups(rows: list[dict[str, Any]]) -> dict[str, Any]:
    def _slice(*, status: str | None = None, object_type: str | None = None, limit: int = 50) -> dict[str, Any]:
        filtered = [
            row
            for row in rows
            if (status is None or str(row.get("trend_status") or "") == status)
            and (object_type is None or str(row.get("object_type") or "") == object_type)
        ]
        ordered = _sort_trend_rows_for_delta(filtered)
        return {
            "count": len(filtered),
            "summary": summarize_trends(filtered),
            "rows": ordered[:limit],
        }

    return {
        "run_final_dataset": {
            "count": len(
                [
                    row
                    for row in rows
                    if str(row.get("object_type") or "") in {"run", "final_dataset"}
                ]
            ),
            "summary": summarize_trends(
                [
                    row
                    for row in rows
                    if str(row.get("object_type") or "") in {"run", "final_dataset"}
                ]
            ),
            "rows": _sort_trend_rows_for_delta(
                [
                    row
                    for row in rows
                    if str(row.get("object_type") or "") in {"run", "final_dataset"}
                ]
            )[:20],
        },
        "tables": _slice(object_type="table"),
        "rules": _slice(object_type="rule"),
        "stages": _slice(object_type="stage"),
        "improved": _slice(status="improved"),
        "worsened": _slice(status="worsened"),
        "baseline": _slice(status="baseline"),
        "changed": _slice(status="changed"),
        "unchanged": _slice(status="unchanged"),
    }


def _normalize_term_phrase(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").strip().lower()).strip()


def _glossary_term_aliases(entry: dict[str, Any]) -> list[str]:
    aliases: list[str] = []
    for raw in [
        entry.get("term"),
        entry.get("normalized_term"),
        *((entry.get("synonyms") or []) if isinstance(entry.get("synonyms"), list) else []),
        *((entry.get("abbreviations") or []) if isinstance(entry.get("abbreviations"), list) else []),
    ]:
        normalized = _normalize_term_phrase(raw)
        if normalized:
            aliases.append(normalized)
    deduped: list[str] = []
    seen: set[str] = set()
    for alias in sorted(aliases, key=len, reverse=True):
        if alias not in seen:
            seen.add(alias)
            deduped.append(alias)
    return deduped


def _trend_business_term_match(
    trend: dict[str, Any],
    glossary_terms: list[dict[str, Any]],
) -> dict[str, Any] | None:
    search_text = " ".join(
        filter(
            None,
            [
                _normalize_term_phrase(trend.get("object_name")),
                _normalize_term_phrase(trend.get("object_key")),
                _normalize_term_phrase(trend.get("metric_name")),
            ],
        )
    )
    if not search_text:
        return None
    best_match: tuple[int, dict[str, Any]] | None = None
    for entry in glossary_terms:
        for alias in _glossary_term_aliases(entry):
            if not alias:
                continue
            if f" {alias} " in f" {search_text} " or alias in search_text:
                score = len(alias)
                if best_match is None or score > best_match[0]:
                    best_match = (score, entry)
                break
    return best_match[1] if best_match else None


def _group_business_term_trends(
    *,
    tenant_id: str,
    domain_id: str,
    run_id: str,
    trend_rows: list[dict[str, Any]],
    glossary_rows: list[dict[str, Any]],
    filtered_term: str | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    grouped: dict[str, dict[str, Any]] = {}
    unmatched_trend_count = 0
    matched_trends: list[dict[str, Any]] = []

    for trend in trend_rows:
        entry = _trend_business_term_match(trend, glossary_rows)
        if not entry:
            unmatched_trend_count += 1
            continue
        normalized_term = _normalize_term_phrase(entry.get("normalized_term") or entry.get("term"))
        if not normalized_term:
            unmatched_trend_count += 1
            continue
        if filtered_term and normalized_term != filtered_term:
            continue
        bucket = grouped.setdefault(
            normalized_term,
            {
                "business_term": str(entry.get("term") or entry.get("normalized_term") or normalized_term).strip(),
                "normalized_term": normalized_term,
                "definition": str(entry.get("definition") or "").strip() or None,
                "trend_row_count": 0,
                "improved_metric_count": 0,
                "worsened_metric_count": 0,
                "baseline_metric_count": 0,
                "affected_objects": set(),
                "top_metrics": set(),
            },
        )
        bucket["trend_row_count"] += 1
        status = str(trend.get("trend_status") or "").strip().lower()
        if status == "improved":
            bucket["improved_metric_count"] += 1
        elif status == "worsened":
            bucket["worsened_metric_count"] += 1
        elif status == "baseline":
            bucket["baseline_metric_count"] += 1
        object_name = str(trend.get("object_name") or trend.get("object_key") or "").strip()
        metric_name = str(trend.get("metric_name") or "").strip()
        if object_name:
            bucket["affected_objects"].add(object_name)
        if metric_name:
            bucket["top_metrics"].add(metric_name)
        matched_trends.append(
            {
                **trend,
                "business_term": bucket["business_term"],
                "normalized_term": normalized_term,
            }
        )

    rows: list[dict[str, Any]] = []
    for normalized_term, bucket in grouped.items():
        rows.append(
            {
                "business_term": bucket["business_term"],
                "normalized_term": normalized_term,
                "definition": bucket["definition"],
                "trend_row_count": bucket["trend_row_count"],
                "improved_metric_count": bucket["improved_metric_count"],
                "worsened_metric_count": bucket["worsened_metric_count"],
                "baseline_metric_count": bucket["baseline_metric_count"],
                "affected_object_count": len(bucket["affected_objects"]),
                "affected_objects": ", ".join(sorted(bucket["affected_objects"]))[:240],
                "top_metrics": ", ".join(sorted(bucket["top_metrics"]))[:240],
                "evidence_path": _business_term_records_path(
                    tenant_id=tenant_id,
                    domain_id=domain_id,
                    run_id=run_id,
                    normalized_term=normalized_term,
                ),
                "detail_evidence_path": _business_term_summary_path(
                    tenant_id=tenant_id,
                    domain_id=domain_id,
                    run_id=run_id,
                    normalized_term=normalized_term,
                ),
            }
        )
    rows.sort(
        key=lambda row: (
            -int(row.get("worsened_metric_count") or 0),
            -int(row.get("trend_row_count") or 0),
            str(row.get("business_term") or ""),
        )
    )
    return rows, matched_trends, unmatched_trend_count


def _rule_trend_outcome(trend: dict[str, Any]) -> str | None:
    metric_name = str(trend.get("metric_name") or "").strip()
    current_text = str(trend.get("current_value_text") or "").strip().lower()
    current_num = _as_float(trend.get("current_value_num"))
    if metric_name == "result_status":
        if current_text in {"failed", "error"}:
            return "failed"
        if current_text == "passed":
            return "passed"
        return None
    if metric_name in {"violation_count", "violation_pct"}:
        if current_num is None:
            return None
        return "failed" if current_num > 0 else "passed"
    return None


def _build_business_term_record_groups(
    settings: Settings,
    *,
    tenant_id: str,
    domain_id: str,
    run_id: str,
    matched_trends: list[dict[str, Any]],
    limit: int,
    offset: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    quality_rules = list_quality_rules(settings, tenant_id=tenant_id, domain_id=domain_id, run_id=run_id, limit=1200)
    dataset_stages = list_quality_dataset_stages(settings, tenant_id=tenant_id, domain_id=domain_id, run_id=run_id, limit=1200)
    rules_by_key = {rule_logical_key(row): row for row in quality_rules if str(rule_logical_key(row)).strip()}
    stages_by_key = {stage_logical_key(row): row for row in dataset_stages if str(stage_logical_key(row)).strip()}

    record_groups: list[dict[str, Any]] = []
    unsupported_trends: list[dict[str, Any]] = []
    seen_sources: set[str] = set()

    for trend in matched_trends:
        object_type = str(trend.get("object_type") or "").strip()
        object_key = str(trend.get("object_key") or "").strip()
        metric_name = str(trend.get("metric_name") or "").strip()

        if object_type == "rule":
            rule = rules_by_key.get(object_key)
            if not rule:
                unsupported_trends.append({**trend, "unsupported_reason": "rule_not_found_for_logical_key"})
                continue
            outcome = _rule_trend_outcome(trend)
            if not outcome:
                unsupported_trends.append({**trend, "unsupported_reason": "trend_metric_has_no_rule_record_outcome"})
                continue
            rule_id = str(rule.get("rule_id") or "").strip()
            dedupe_key = f"rule:{rule_id}:{outcome}"
            if dedupe_key in seen_sources:
                continue
            seen_sources.add(dedupe_key)
            payload = fetch_rule_records(
                settings,
                tenant_id=tenant_id,
                domain_id=domain_id,
                run_id=run_id,
                rule_id=rule_id,
                outcome=outcome,
                limit=limit,
                offset=offset,
            )
            record_groups.append(
                {
                    "source_type": f"rule_{outcome}_records",
                    "source_key": rule_id,
                    "source_label": str(rule.get("rule_label") or derive_quality_rule_label(rule) or object_key).strip(),
                    "trend_metric_name": metric_name,
                    "trend_status": trend.get("trend_status"),
                    "evidence_path": (
                        f"/data-quality/runs/{run_id}/rules/{rule_id}/{outcome}-records"
                        f"?tenant_id={tenant_id}&domain_id={domain_id}"
                    ),
                    "detail_evidence_path": (
                        f"/data-quality/trends/rules/{object_key}"
                        f"?tenant_id={tenant_id}&domain_id={domain_id}&run_id={run_id}"
                    ),
                    "supported": bool(payload.get("supported", True)),
                    "unsupported_reason": payload.get("unsupported_reason"),
                    "affected_row_count": payload.get("affected_row_count"),
                    "rows": payload.get("rows") or [],
                    "summary": {
                        "rule_id": rule_id,
                        "rule_type": rule.get("rule_type"),
                        "severity": rule.get("severity"),
                        "outcome": outcome,
                    },
                }
            )
            continue

        if object_type == "stage":
            stage = stages_by_key.get(object_key)
            if not stage:
                unsupported_trends.append({**trend, "unsupported_reason": "stage_not_found_for_logical_key"})
                continue
            stage_id = str(stage.get("stage_id") or "").strip()
            dedupe_key = f"stage:{stage_id}"
            if dedupe_key in seen_sources:
                continue
            seen_sources.add(dedupe_key)
            payload = fetch_stage_evidence(
                settings,
                stage_id=stage_id,
                tenant_id=tenant_id,
                domain_id=domain_id,
                limit=limit,
                offset=offset,
            )
            summary = dict(payload.get("summary") or {})
            record_groups.append(
                {
                    "source_type": "stage_evidence",
                    "source_key": stage_id,
                    "source_label": str(stage.get("stage_name") or object_key).strip(),
                    "trend_metric_name": metric_name,
                    "trend_status": trend.get("trend_status"),
                    "evidence_path": f"/data-quality/evidence/stages/{stage_id}?tenant_id={tenant_id}&domain_id={domain_id}",
                    "detail_evidence_path": (
                        f"/data-quality/trends/stages/{object_key}"
                        f"?tenant_id={tenant_id}&domain_id={domain_id}&run_id={run_id}"
                    ),
                    "supported": True,
                    "unsupported_reason": None,
                    "affected_row_count": summary.get("rejected_row_count", len(payload.get("rows") or [])),
                    "rows": payload.get("rows") or [],
                    "summary": summary,
                }
            )
            continue

        if object_type == "final_dataset" and metric_name in {"final_row_count", "final_dataset_row_count"}:
            dedupe_key = "final_dataset_rows"
            if dedupe_key in seen_sources:
                continue
            seen_sources.add(dedupe_key)
            payload = fetch_final_dataset_rows(
                settings,
                tenant_id=tenant_id,
                domain_id=domain_id,
                run_id=run_id,
                limit=limit,
                offset=offset,
            )
            record_groups.append(
                {
                    "source_type": "final_dataset_rows",
                    "source_key": "final_dataset",
                    "source_label": "Final Dataset",
                    "trend_metric_name": metric_name,
                    "trend_status": trend.get("trend_status"),
                    "evidence_path": (
                        f"/data-quality/final-dataset/rows?tenant_id={tenant_id}&domain_id={domain_id}&run_id={run_id}"
                    ),
                    "detail_evidence_path": (
                        f"/data-quality/trends/final-dataset?tenant_id={tenant_id}&domain_id={domain_id}&run_id={run_id}"
                    ),
                    "supported": True,
                    "unsupported_reason": None,
                    "affected_row_count": len(payload.get("rows") or []),
                    "rows": payload.get("rows") or [],
                    "summary": {
                        "basis_stage": payload.get("basis_stage") or {},
                        "final_dataset": payload.get("final_dataset") or {},
                    },
                }
            )
            continue

        unsupported_trends.append({**trend, "unsupported_reason": "record_drill_not_available_for_trend_object"})

    return record_groups, unsupported_trends


def _business_term_inference_threshold() -> float:
    try:
        return max(0.0, min(float(os.getenv("DATA_QUALITY_BUSINESS_TERM_UNMATCHED_RATIO", "0.6")), 1.0))
    except (TypeError, ValueError):
        return 0.6


def _should_infer_business_terms(*, trend_row_count: int, grouped_count: int, unmatched_count: int) -> bool:
    if trend_row_count <= 0:
        return False
    if grouped_count <= 0:
        return True
    return (unmatched_count / max(trend_row_count, 1)) >= _business_term_inference_threshold()


def _qident(name: str | None) -> str:
    return '"' + str(name or "").replace('"', '""') + '"'


def _schema_table_context(schema_payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(schema_payload, dict) or not schema_payload:
        return []
    table_context: list[dict[str, Any]] = []
    schema_graph = build_schema_graph(schema_payload)
    for table in schema_graph.get("tables") or []:
        table_name = str(table.get("name") or "").strip()
        if not table_name:
            continue
        columns = []
        for column in table.get("columns") or []:
            column_name = str(column.get("name") or "").strip()
            if column_name:
                columns.append(column_name)
        table_context.append({"table_name": table_name, "columns": columns})
    return table_context


def _fetch_business_term_sample_rows(
    settings: Settings,
    *,
    run_row: dict[str, Any] | None,
    table_names: list[str],
) -> dict[str, list[dict[str, Any]]]:
    if not run_row:
        return {}
    connection_id = str(run_row.get("connection_id") or "").strip()
    schema_name = str(run_row.get("schema_name") or "public").strip() or "public"
    if not connection_id or not table_names:
        return {}
    scoped_conn = resolve_database_credentials_cached(settings, connection_id, schema_name)
    if scoped_conn is None:
        return {}
    max_tables = max(1, int(os.getenv("DATA_QUALITY_BUSINESS_TERM_SAMPLE_TABLES", "4")))
    sample_rows = max(1, int(os.getenv("DATA_QUALITY_BUSINESS_TERM_SAMPLE_ROWS", "3")))
    samples: dict[str, list[dict[str, Any]]] = {}
    for table_name in [str(item).strip() for item in table_names if str(item).strip()][:max_tables]:
        try:
            rows = run_query(
                settings,
                f'SELECT * FROM {_qident(schema_name)}.{_qident(table_name)} LIMIT {sample_rows}',
                [],
                scoped_conn=scoped_conn,
            ) or []
            samples[table_name] = [dict(row) for row in rows]
        except Exception as exc:
            logger.warning("data_quality_trends sample rows failed | table=%s err=%s", table_name, exc)
    return samples


def _sanitize_inferred_business_terms(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in ((payload or {}).get("business_terms") or []):
        if not isinstance(item, dict):
            continue
        term = str(item.get("term") or "").strip()
        normalized = _normalize_term_phrase(item.get("normalized_term") or term)
        if not term or not normalized:
            continue
        synonyms = []
        for value in item.get("synonyms") or []:
            cleaned = str(value or "").strip()
            if cleaned:
                synonyms.append(cleaned)
        abbreviations = []
        for value in item.get("abbreviations") or []:
            cleaned = str(value or "").strip()
            if cleaned:
                abbreviations.append(cleaned)
        rows.append(
            {
                "term": term,
                "normalized_term": normalized,
                "definition": str(item.get("definition") or "").strip() or None,
                "synonyms": list(dict.fromkeys(synonyms)),
                "abbreviations": list(dict.fromkeys(abbreviations)),
            }
        )
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in rows:
        normalized = str(item.get("normalized_term") or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(item)
    return deduped[:12]


def _infer_business_terms_for_run(
    settings: Settings | None,
    *,
    tenant_id: str,
    domain_id: str,
    run_id: str,
    trend_rows: list[dict[str, Any]],
    glossary_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not _business_term_llm_enabled(settings):
        return []
    deployment_run = get_deployment_run(settings, run_id) or {}
    deployment_payload = dict(deployment_run.get("deployment_payload_json") or {})
    run_row = get_quality_run_by_run_id(settings, run_id) or {}
    schema_payload = deployment_payload.get("schema_payload") or {}
    schema_tables = _schema_table_context(schema_payload)
    quality_rules = list_quality_rules(settings, tenant_id=tenant_id, domain_id=domain_id, run_id=run_id, limit=200)
    table_names = list(
        dict.fromkeys(
            [str(item.get("table_name") or "").strip() for item in schema_tables]
            + [str(rule.get("table_name") or "").strip() for rule in quality_rules]
            + [str(row.get("object_key") or "").strip() for row in trend_rows if str(row.get("object_type") or "") == "table"]
        )
    )
    sample_rows = _fetch_business_term_sample_rows(
        settings,
        run_row=run_row,
        table_names=[item for item in table_names if item],
    )
    result = _business_term_llm_json(
        settings,
        user_payload={
            "tenant_id": tenant_id,
            "domain_id": domain_id,
            "run_id": run_id,
            "deployment_context": str(deployment_payload.get("context_text") or "")[:12000],
            "schema_tables": schema_tables[:8],
            "sample_rows": sample_rows,
            "rules": [
                {
                    "rule_label": str(rule.get("rule_label") or derive_quality_rule_label(rule) or "").strip(),
                    "rule_type": str(rule.get("rule_type") or "").strip(),
                    "table_name": str(rule.get("table_name") or "").strip() or None,
                    "column_name": str(rule.get("column_name") or "").strip() or None,
                    "source_text": str(rule.get("source_text") or "").strip() or None,
                }
                for rule in quality_rules[:80]
            ],
            "trend_rows": [
                {
                    "object_type": row.get("object_type"),
                    "object_name": row.get("object_name"),
                    "object_key": row.get("object_key"),
                    "metric_name": row.get("metric_name"),
                    "trend_status": row.get("trend_status"),
                }
                for row in trend_rows[:200]
            ],
            "existing_glossary_terms": [
                {
                    "term": entry.get("term"),
                    "normalized_term": entry.get("normalized_term"),
                    "definition": entry.get("definition"),
                    "synonyms": entry.get("synonyms") or [],
                    "abbreviations": entry.get("abbreviations") or [],
                }
                for entry in glossary_rows[:80]
            ],
        },
    )
    inferred_terms = _sanitize_inferred_business_terms(result)
    if not inferred_terms:
        return []
    source_context_id = None
    context_ids = deployment_payload.get("context_ids") or []
    if context_ids:
        source_context_id = str(context_ids[0] or "").strip() or None
    try:
        upsert_glossary_terms(
            settings,
            tenant_id=tenant_id,
            domain_id=domain_id,
            terms=inferred_terms,
            lifecycle_status="suggested",
            source_context_id=source_context_id,
        )
    except Exception:
        logger.exception("data_quality_trends inferred glossary persist failed | run_id=%s", run_id)
    return inferred_terms


def build_business_term_trend_payload(
    *,
    tenant_id: str,
    domain_id: str,
    run_id: str,
    trends: list[dict[str, Any]] | None,
    glossary_terms: list[dict[str, Any]] | None,
    term: str | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    trend_rows = [row for row in (trends or []) if isinstance(row, dict)]
    glossary_rows = [row for row in (glossary_terms or []) if isinstance(row, dict)]
    filtered_term = _normalize_term_phrase(term) if term else None
    rows, matched_trends, unmatched_trend_count = _group_business_term_trends(
        tenant_id=tenant_id,
        domain_id=domain_id,
        run_id=run_id,
        trend_rows=trend_rows,
        glossary_rows=glossary_rows,
        filtered_term=filtered_term,
    )
    if _should_infer_business_terms(
        trend_row_count=len(trend_rows),
        grouped_count=len(rows),
        unmatched_count=unmatched_trend_count,
    ):
        inferred_terms = _infer_business_terms_for_run(
            settings,
            tenant_id=tenant_id,
            domain_id=domain_id,
            run_id=run_id,
            trend_rows=trend_rows,
            glossary_rows=glossary_rows,
        )
        if inferred_terms:
            glossary_rows = glossary_rows + [
                {
                    "term": item.get("term"),
                    "normalized_term": item.get("normalized_term"),
                    "definition": item.get("definition"),
                    "synonyms": item.get("synonyms") or [],
                    "abbreviations": item.get("abbreviations") or [],
                }
                for item in inferred_terms
            ]
            rows, matched_trends, unmatched_trend_count = _group_business_term_trends(
                tenant_id=tenant_id,
                domain_id=domain_id,
                run_id=run_id,
                trend_rows=trend_rows,
                glossary_rows=glossary_rows,
                filtered_term=filtered_term,
            )
    return {
        "tenant_id": tenant_id,
        "domain_id": domain_id,
        "run_id": run_id,
        "term": filtered_term,
        "summary": {
            "business_term_group_count": len(rows),
            "worsened_business_term_count": sum(1 for row in rows if int(row.get("worsened_metric_count") or 0) > 0),
            "improved_business_term_count": sum(1 for row in rows if int(row.get("improved_metric_count") or 0) > 0),
            "unmatched_trend_row_count": unmatched_trend_count,
        },
        "rows": rows,
        "matched_trends": matched_trends if filtered_term else [],
    }


def build_business_term_record_payload(
    *,
    tenant_id: str,
    domain_id: str,
    run_id: str,
    term: str,
    trends: list[dict[str, Any]] | None,
    glossary_terms: list[dict[str, Any]] | None,
    settings: Settings,
    limit: int = 200,
    offset: int = 0,
) -> dict[str, Any]:
    overview = build_business_term_trend_payload(
        tenant_id=tenant_id,
        domain_id=domain_id,
        run_id=run_id,
        trends=trends,
        glossary_terms=glossary_terms,
        term=term,
        settings=settings,
    )
    filtered_term = str(overview.get("term") or "").strip()
    matched_trends = [row for row in (overview.get("matched_trends") or []) if isinstance(row, dict)]
    rows = [row for row in (overview.get("rows") or []) if isinstance(row, dict)]
    business_term = str((rows[0] if rows else {}).get("business_term") or filtered_term).strip() or filtered_term
    record_groups, unsupported_trends = _build_business_term_record_groups(
        settings,
        tenant_id=tenant_id,
        domain_id=domain_id,
        run_id=run_id,
        matched_trends=matched_trends,
        limit=limit,
        offset=offset,
    )
    total_record_count = 0
    for item in record_groups:
        try:
            total_record_count += int(item.get("affected_row_count") or 0)
        except (TypeError, ValueError):
            continue
    return {
        "tenant_id": tenant_id,
        "domain_id": domain_id,
        "run_id": run_id,
        "term": filtered_term or _normalize_term_phrase(term),
        "business_term": business_term,
        "detail_evidence_path": _business_term_summary_path(
            tenant_id=tenant_id,
            domain_id=domain_id,
            run_id=run_id,
            normalized_term=filtered_term or _normalize_term_phrase(term),
        ),
        "summary": {
            "matched_trend_row_count": len(matched_trends),
            "record_group_count": len(record_groups),
            "supported_record_group_count": sum(1 for item in record_groups if bool(item.get("supported", True))),
            "unsupported_trend_row_count": len(unsupported_trends),
            "total_record_count": total_record_count,
        },
        "record_groups": record_groups,
        "unsupported_trends": unsupported_trends,
        "matched_trends": matched_trends,
    }


def build_readiness_trend_payload(
    *,
    run_id: str,
    baseline_run_id: str | None,
    final_dataset: dict[str, Any] | None,
    trends: list[dict[str, Any]] | None,
    issues: list[dict[str, Any]] | None,
    anomalies: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    final_dataset = dict(final_dataset or {})
    trend_rows = [row for row in (trends or []) if isinstance(row, dict)]
    issue_rows = [row for row in (issues or []) if isinstance(row, dict)]
    anomaly_rows = [row for row in (anomalies or []) if isinstance(row, dict)]
    readiness_trend = next(
        (
            row
            for row in trend_rows
            if str(row.get("object_type") or "") == "final_dataset"
            and str(row.get("metric_name") or "") == "readiness_status"
        ),
        None,
    )
    row_count_trend = next(
        (
            row
            for row in trend_rows
            if str(row.get("object_type") or "") == "final_dataset"
            and str(row.get("metric_name") or "") == "final_row_count"
        ),
        None,
    )
    open_issues = [
        row
        for row in issue_rows
        if str(row.get("status") or "").strip().lower() in {"open", "in_progress", "deferred"}
    ]
    blocker_issues = [
        row
        for row in open_issues
        if str(row.get("issue_type") or "").strip().lower() == "publish_readiness_blocker"
        or str(row.get("severity") or "").strip().lower() == "critical"
    ]
    critical_anomalies = [
        row for row in anomaly_rows if str(row.get("severity") or "").strip().lower() == "critical"
    ]
    current_status = str(final_dataset.get("readiness_status") or "").strip() or None
    previous_status = str((readiness_trend or {}).get("previous_value_text") or "").strip() or None
    trend_status = str((readiness_trend or {}).get("trend_status") or "").strip() or ("baseline" if baseline_run_id is None else "unchanged")
    current_final_row_count = final_dataset.get("final_row_count")
    previous_final_row_count = (row_count_trend or {}).get("previous_value_num")
    blocker_titles = [str(row.get("title") or "").strip() for row in blocker_issues if str(row.get("title") or "").strip()]
    evidence_path = f"/data-quality/final-dataset?tenant_id={{tenant_id}}&domain_id={{domain_id}}&run_id={run_id}"
    return {
        "run_id": run_id,
        "baseline_run_id": baseline_run_id,
        "current_readiness_status": current_status,
        "previous_readiness_status": previous_status,
        "readiness_trend_status": trend_status,
        "current_final_row_count": current_final_row_count,
        "previous_final_row_count": previous_final_row_count,
        "final_row_count_delta": (row_count_trend or {}).get("delta_value"),
        "final_row_count_delta_pct": (row_count_trend or {}).get("delta_pct"),
        "certification_blocker_count": len(blocker_issues),
        "open_issue_count": len(open_issues),
        "residual_anomaly_count": len(anomaly_rows),
        "critical_anomaly_count": len(critical_anomalies),
        "blocker_titles": blocker_titles[:5],
        "evidence_path_template": evidence_path,
    }


def build_trend_api_payload(
    *,
    tenant_id: str,
    domain_id: str,
    run_id: str,
    trend_scope_key: str | None,
    baseline_run_id: str | None,
    trends: list[dict[str, Any]],
    readiness_overview: dict[str, Any] | None = None,
    business_term_overview: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rows = [
        _normalized_trend_row(row=row, tenant_id=tenant_id, domain_id=domain_id, run_id=run_id)
        for row in trends
    ]
    summary = summarize_trends(trends)
    return {
        "tenant_id": tenant_id,
        "domain_id": domain_id,
        "run_id": run_id,
        "trend_scope_key": trend_scope_key,
        "baseline_run_id": baseline_run_id,
        "summary": summary,
        "cards": _build_trend_cards(
            rows=rows,
            summary=summary,
            baseline_run_id=baseline_run_id,
            tenant_id=tenant_id,
            domain_id=domain_id,
            run_id=run_id,
            readiness_overview=readiness_overview,
            business_term_overview=business_term_overview,
        ),
        "chart_plan": _build_trend_chart_plan(
            rows=rows,
            summary=summary,
            tenant_id=tenant_id,
            domain_id=domain_id,
            run_id=run_id,
            readiness_overview=readiness_overview,
            business_term_overview=business_term_overview,
        ),
        "groups": _build_trend_groups(rows),
        "trends": rows,
    }


def build_previous_snapshot_index(
    settings,
    *,
    tenant_id: str,
    domain_id: str,
    trend_scope_key: str,
    current_run_id: str,
) -> tuple[str | None, list[dict[str, Any]]]:
    previous_runs = list_runs_by_trend_scope(
        settings,
        tenant_id=tenant_id,
        domain_id=domain_id,
        trend_scope_key=trend_scope_key,
        exclude_run_id=current_run_id,
        completed_only=True,
        limit=20,
    )
    baseline_run = previous_runs[0] if previous_runs else None
    baseline_run_id = str((baseline_run or {}).get("run_id") or "").strip() or None
    return baseline_run_id, []


def select_trend_baseline_run(
    *,
    trend_mode: str | None,
    previous_runs: list[dict[str, Any]],
) -> dict[str, Any] | None:
    normalized_mode = str(trend_mode or "").strip().lower()
    if normalized_mode == "baseline_reset":
        return None
    completed_runs = [row for row in previous_runs if isinstance(row, dict)]
    if not completed_runs:
        return None
    latest_reset_index = next(
        (
            idx
            for idx, row in enumerate(completed_runs)
            if str(row.get("trend_mode") or "").strip().lower() == "baseline_reset"
        ),
        None,
    )
    if latest_reset_index is not None:
        completed_runs = completed_runs[: latest_reset_index + 1]
    return completed_runs[0] if completed_runs else None


def build_trend_table_payload(
    *,
    tenant_id: str,
    domain_id: str,
    run_id: str,
    trend_scope_key: str | None,
    table_name: str,
    trends: list[dict[str, Any]],
) -> dict[str, Any]:
    rows = [row for row in trends if row.get("object_type") == "table" and str(row.get("object_key") or "") == table_name]
    payload = build_trend_api_payload(
        tenant_id=tenant_id,
        domain_id=domain_id,
        run_id=run_id,
        trend_scope_key=trend_scope_key,
        baseline_run_id=rows[0].get("baseline_run_id") if rows else None,
        trends=rows,
    )
    payload["focus"] = {
        "focus_type": "table",
        "focus_key": table_name,
        "focus_label": table_name,
    }
    payload["table_name"] = table_name
    return payload


def build_trend_stage_payload(
    *,
    tenant_id: str,
    domain_id: str,
    run_id: str,
    trend_scope_key: str | None,
    stage_key: str,
    trends: list[dict[str, Any]],
) -> dict[str, Any]:
    rows = [row for row in trends if row.get("object_type") == "stage" and str(row.get("object_key") or "") == stage_key]
    payload = build_trend_api_payload(
        tenant_id=tenant_id,
        domain_id=domain_id,
        run_id=run_id,
        trend_scope_key=trend_scope_key,
        baseline_run_id=rows[0].get("baseline_run_id") if rows else None,
        trends=rows,
    )
    payload["focus"] = {
        "focus_type": "stage",
        "focus_key": stage_key,
        "focus_label": rows[0].get("object_name") if rows else stage_key,
    }
    payload["stage_logical_key"] = stage_key
    return payload


def build_trend_run_summary_payload(
    *,
    tenant_id: str,
    domain_id: str,
    run_id: str,
    trend_scope_key: str | None,
    trends: list[dict[str, Any]],
) -> dict[str, Any]:
    rows = [row for row in trends if row.get("object_type") == "run"]
    payload = build_trend_api_payload(
        tenant_id=tenant_id,
        domain_id=domain_id,
        run_id=run_id,
        trend_scope_key=trend_scope_key,
        baseline_run_id=rows[0].get("baseline_run_id") if rows else None,
        trends=rows,
    )
    payload["focus"] = {
        "focus_type": "run",
        "focus_key": "__run__",
        "focus_label": "Run Summary",
    }
    return payload


def build_trend_final_dataset_payload(
    *,
    tenant_id: str,
    domain_id: str,
    run_id: str,
    trend_scope_key: str | None,
    trends: list[dict[str, Any]],
) -> dict[str, Any]:
    rows = [row for row in trends if row.get("object_type") == "final_dataset"]
    payload = build_trend_api_payload(
        tenant_id=tenant_id,
        domain_id=domain_id,
        run_id=run_id,
        trend_scope_key=trend_scope_key,
        baseline_run_id=rows[0].get("baseline_run_id") if rows else None,
        trends=rows,
    )
    payload["focus"] = {
        "focus_type": "final_dataset",
        "focus_key": "final_dataset",
        "focus_label": "Final Dataset",
    }
    return payload


def build_trend_rule_payload(
    *,
    tenant_id: str,
    domain_id: str,
    run_id: str,
    trend_scope_key: str | None,
    rule_key: str,
    trends: list[dict[str, Any]],
) -> dict[str, Any]:
    rows = [row for row in trends if row.get("object_type") == "rule" and str(row.get("object_key") or "") == rule_key]
    payload = build_trend_api_payload(
        tenant_id=tenant_id,
        domain_id=domain_id,
        run_id=run_id,
        trend_scope_key=trend_scope_key,
        baseline_run_id=rows[0].get("baseline_run_id") if rows else None,
        trends=rows,
    )
    payload["focus"] = {
        "focus_type": "rule",
        "focus_key": rule_key,
        "focus_label": rows[0].get("object_name") if rows else rule_key,
    }
    payload["rule_logical_key"] = rule_key
    return payload
