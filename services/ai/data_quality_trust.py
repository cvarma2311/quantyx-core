from __future__ import annotations

from typing import Any
import os


def _as_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _severity_from_score(score: Any) -> str:
    value = _as_float(score)
    if value is None:
        return "unknown"
    if value < 50.0:
        return "critical"
    if value < 75.0:
        return "warning"
    return "good"


def _rule_score(rule_rows: list[dict[str, Any]]) -> float | None:
    if not rule_rows:
        return 100.0
    checked = 0.0
    violations = 0.0
    error_count = 0
    for row in rule_rows:
        status = str(row.get("result_status") or row.get("status") or "").strip().lower()
        if status == "error":
            error_count += 1
        checked += float(row.get("checked_row_count") or 0)
        violations += float(row.get("violation_count") or 0)
    if checked > 0:
        return max(0.0, 100.0 - min((violations / checked) * 100.0, 100.0))
    if error_count:
        return 50.0
    return 100.0


def _uniqueness_score(row_count: float | None, duplicate_rows: list[dict[str, Any]]) -> float | None:
    exact_rows = [row for row in duplicate_rows if str(row.get("duplicate_type") or "").startswith("exact_")]
    if row_count in (None, 0):
        return 100.0 if not exact_rows else 60.0
    if not exact_rows:
        return 100.0
    affected = sum(float(row.get("candidate_record_count") or 0) for row in exact_rows)
    return max(0.0, 100.0 - min((affected / row_count) * 100.0, 100.0))


def _duplicate_risk_score(existing_score: Any, duplicate_rows: list[dict[str, Any]]) -> float | None:
    base = _as_float(existing_score)
    exact_count = sum(1 for row in duplicate_rows if str(row.get("duplicate_type") or "").startswith("exact_"))
    fuzzy_count = sum(1 for row in duplicate_rows if str(row.get("duplicate_type") or "").startswith("fuzzy_"))
    if base is None:
        base = 100.0
    penalty = min((exact_count * 12.0) + (fuzzy_count * 6.0), 60.0)
    return max(0.0, min(base, 100.0 - penalty))


def _freshness_score(existing_score: Any, freshness_row: dict[str, Any] | None) -> float | None:
    if freshness_row:
        score = _as_float(freshness_row.get("freshness_score"))
        if score is not None:
            return score
        status = str(freshness_row.get("freshness_status") or "").strip().lower()
        if status == "no_freshness_column":
            return 60.0
    return _as_float(existing_score)


def _stability_score(freshness_row: dict[str, Any] | None) -> float | None:
    if not freshness_row:
        return None
    status = str(freshness_row.get("stability_status") or "").strip().lower()
    if not status or status == "no_baseline":
        return None
    if status == "stable":
        return 100.0
    row_change = abs(_as_float(freshness_row.get("row_count_change_pct")) or 0.0)
    completeness_change = abs(_as_float(freshness_row.get("completeness_score_change")) or 0.0)
    penalty = min((row_change * 0.8) + (completeness_change * 4.0), 100.0)
    return max(0.0, 100.0 - penalty)


def _enrichment_readiness(opportunity_count: int) -> float:
    return max(60.0, 100.0 - min(float(opportunity_count) * 10.0, 40.0))


def _weights() -> dict[str, float]:
    return {
        "completeness": float(os.getenv("DQ_TRUST_WEIGHT_COMPLETENESS", "0.28")),
        "validity": float(os.getenv("DQ_TRUST_WEIGHT_VALIDITY", "0.18")),
        "uniqueness": float(os.getenv("DQ_TRUST_WEIGHT_UNIQUENESS", "0.12")),
        "referential_integrity": float(os.getenv("DQ_TRUST_WEIGHT_REFERENTIAL", "0.14")),
        "freshness": float(os.getenv("DQ_TRUST_WEIGHT_FRESHNESS", "0.10")),
        "duplicate_risk": float(os.getenv("DQ_TRUST_WEIGHT_DUPLICATE", "0.10")),
        "stability": float(os.getenv("DQ_TRUST_WEIGHT_STABILITY", "0.04")),
        "enrichment_readiness": float(os.getenv("DQ_TRUST_WEIGHT_ENRICHMENT", "0.04")),
    }


def compute_data_quality_trust_scores(
    *,
    quality_tables: list[dict[str, Any]],
    quality_rules: list[dict[str, Any]],
    duplicate_candidates: list[dict[str, Any]],
    freshness_results: list[dict[str, Any]],
    enrichment_opportunities: list[dict[str, Any]],
) -> dict[str, Any]:
    weight_map = _weights()
    duplicates_by_table: dict[str, list[dict[str, Any]]] = {}
    for row in duplicate_candidates:
        table_name = str(row.get("table_name") or "").strip()
        if table_name:
            duplicates_by_table.setdefault(table_name, []).append(row)
    freshness_by_table = {
        str(row.get("table_name") or "").strip(): row
        for row in freshness_results
        if str(row.get("table_name") or "").strip()
    }
    rules_by_table: dict[str, list[dict[str, Any]]] = {}
    for row in quality_rules:
        table_name = str(row.get("table_name") or "").strip()
        if table_name:
            rules_by_table.setdefault(table_name, []).append(row)
    enrichment_counts: dict[str, int] = {}
    for row in enrichment_opportunities:
        table_name = str(row.get("table_name") or "").strip()
        if table_name:
            enrichment_counts[table_name] = enrichment_counts.get(table_name, 0) + 1

    table_results: list[dict[str, Any]] = []
    for table in quality_tables:
        table_name = str(table.get("table_name") or "").strip()
        row_count = _as_float(table.get("row_count"))
        table_rules = rules_by_table.get(table_name, [])
        referential_rules = [row for row in table_rules if str(row.get("rule_type") or "").strip().lower() == "referential_integrity"]
        validity_rules = [row for row in table_rules if str(row.get("rule_type") or "").strip().lower() != "referential_integrity"]
        freshness_row = freshness_by_table.get(table_name)
        duplicate_rows = duplicates_by_table.get(table_name, [])
        components = {
            "completeness": _as_float(table.get("completeness_score")),
            "validity": _rule_score(validity_rules),
            "uniqueness": _uniqueness_score(row_count, duplicate_rows),
            "referential_integrity": _rule_score(referential_rules),
            "freshness": _freshness_score(table.get("freshness_score"), freshness_row),
            "duplicate_risk": _duplicate_risk_score(table.get("duplicate_risk_score"), duplicate_rows),
            "stability": _stability_score(freshness_row),
            "enrichment_readiness": _enrichment_readiness(enrichment_counts.get(table_name, 0)),
        }
        weighted_total = 0.0
        applied_weight = 0.0
        for key, weight in weight_map.items():
            value = components.get(key)
            if value is None:
                continue
            weighted_total += float(value) * weight
            applied_weight += weight
        trust_score = round(weighted_total / applied_weight, 2) if applied_weight > 0 else None
        component_explanations = {
            "validity_rule_count": len(validity_rules),
            "referential_rule_count": len(referential_rules),
            "duplicate_candidate_count": len(duplicate_rows),
            "enrichment_opportunity_count": enrichment_counts.get(table_name, 0),
            "stability_status": (freshness_row or {}).get("stability_status"),
            "freshness_status": (freshness_row or {}).get("freshness_status"),
        }
        table_results.append(
            {
                "table_name": table_name,
                "trust_score": trust_score,
                "severity": _severity_from_score(trust_score),
                "validity_score": components["validity"],
                "uniqueness_score": components["uniqueness"],
                "referential_integrity_score": components["referential_integrity"],
                "freshness_score": components["freshness"],
                "duplicate_risk_score": components["duplicate_risk"],
                "trust_components": components,
                "trust_component_explanations": component_explanations,
            }
        )

    average_score = None
    if table_results:
        available = [float(item["trust_score"]) for item in table_results if item.get("trust_score") is not None]
        if available:
            average_score = round(sum(available) / len(available), 2)

    return {
        "tables": table_results,
        "summary": {
            "average_table_trust_score": average_score,
            "low_trust_tables_count": sum(1 for item in table_results if _as_float(item.get("trust_score")) is not None and float(item.get("trust_score")) < 75.0),
            "critical_issue_count": sum(1 for item in table_results if str(item.get("severity")) == "critical"),
            "warning_issue_count": sum(1 for item in table_results if str(item.get("severity")) == "warning"),
        },
    }
