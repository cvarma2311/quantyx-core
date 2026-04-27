from __future__ import annotations

from decimal import Decimal
from hashlib import sha1
from typing import Any
import json
import logging
import os
import re
import urllib.request
from urllib.parse import quote

from services.ai.config import Settings
from services.ai.data_quality_store import (
    list_quality_dataset_stages,
    list_quality_rules,
    list_quality_tables,
    list_quality_trends,
)
from services.ai.workspace_store import list_runs_by_trend_scope


logger = logging.getLogger(__name__)


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
        with urllib.request.urlopen(request, timeout=45) as response:
            body = json.loads(response.read().decode("utf-8"))
        return json.loads(body["choices"][0]["message"]["content"])
    except Exception as exc:
        logger.warning("data_quality_trends trend scope llm failed: %s", exc)
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
        label = str(rule.get("rule_label") or rule.get("rule_type") or key)
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


def build_business_term_trend_payload(
    *,
    tenant_id: str,
    domain_id: str,
    run_id: str,
    trends: list[dict[str, Any]] | None,
    glossary_terms: list[dict[str, Any]] | None,
    term: str | None = None,
) -> dict[str, Any]:
    trend_rows = [row for row in (trends or []) if isinstance(row, dict)]
    glossary_rows = [row for row in (glossary_terms or []) if isinstance(row, dict)]
    filtered_term = _normalize_term_phrase(term) if term else None
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
                "evidence_path": (
                    f"/data-quality/trends/business-terms?tenant_id={tenant_id}&domain_id={domain_id}"
                    f"&run_id={run_id}&term={quote(normalized_term)}"
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
) -> dict[str, Any]:
    rows = [
        {
            "object_type": row.get("object_type"),
            "object_key": row.get("object_key"),
            "object_name": row.get("object_name"),
            "metric_name": row.get("metric_name"),
            "previous_value_num": row.get("previous_value_num"),
            "previous_value_text": row.get("previous_value_text"),
            "current_value_num": row.get("current_value_num"),
            "current_value_text": row.get("current_value_text"),
            "delta_value": row.get("delta_value"),
            "delta_pct": row.get("delta_pct"),
            "trend_status": row.get("trend_status"),
            "directionality": row.get("directionality"),
        }
        for row in trends
    ]
    return {
        "tenant_id": tenant_id,
        "domain_id": domain_id,
        "run_id": run_id,
        "trend_scope_key": trend_scope_key,
        "baseline_run_id": baseline_run_id,
        "summary": summarize_trends(trends),
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
    payload["table_name"] = table_name
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
    payload["rule_logical_key"] = rule_key
    return payload
