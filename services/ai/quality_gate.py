from __future__ import annotations

from typing import Any
import re


def has_blocked_metric_pattern(name: str | None) -> bool:
    lower = str(name or "").strip().lower()
    if not lower:
        return False
    return bool(re.search(r"sum_.*(?:_id|_code)\b", lower))


def evaluate_quality_report(state: dict[str, Any]) -> dict[str, Any]:
    join_edges = state.get("join_edges") or []
    ontology_edges = (state.get("ontology") or {}).get("hierarchy_edges") or []
    metric_defs = state.get("metric_defs") or []
    chart_plan = state.get("chart_plan") or []
    low_conf_edges: list[dict[str, Any]] = []
    total_edges = 0
    for edge in [*join_edges, *ontology_edges]:
        total_edges += 1
        confidence = edge.get("confidence")
        if confidence is not None and confidence < 0.7:
            low_conf_edges.append(edge)

    blocked_metric_names = [m.get("metric_name") for m in metric_defs if has_blocked_metric_pattern(m.get("metric_name"))]
    metric_rejections = [m for m in metric_defs if not m.get("eligible_measure") and m.get("metric_source") == "fallback"]
    chart_rejections = state.get("chart_candidate_rejections") or []
    trend_count = 0
    breakdown_count = 0
    quality_or_rate_count = 0
    for chart in chart_plan:
        intent = str(chart.get("intent") or "").lower()
        if intent in {"trend", "multi_series"}:
            trend_count += 1
        if intent in {"breakdown", "share", "join_breakdown"}:
            breakdown_count += 1
        metric_intent = str(chart.get("metric_intent") or "").lower()
        if metric_intent in {"quality", "rate", "productivity", "utilization"}:
            quality_or_rate_count += 1

    warnings: list[str] = []
    blocked_patterns: list[str] = []
    if blocked_metric_names:
        warnings.append("blocked_metric_name_pattern")
        blocked_patterns.extend([f"metric:{name}" for name in blocked_metric_names if name])
    if trend_count == 0:
        warnings.append("missing_trend_chart")
    if breakdown_count == 0:
        warnings.append("missing_breakdown_or_share_chart")
    if quality_or_rate_count == 0:
        warnings.append("missing_quality_or_rate_chart")
    if low_conf_edges:
        warnings.append("low_confidence_edges_present")
    if chart_rejections:
        warnings.append("chart_rejections_present")

    score = 1.0
    score -= min(0.4, 0.1 * len(warnings))
    score = max(0.0, round(score, 3))
    # missing_quality_or_rate_chart is advisory only — many domains (sales, targets)
    # have no productivity/rate/utilization KPIs and should not be blocked for it.
    gate_passed = (
        not blocked_metric_names
        and trend_count >= 1
        and breakdown_count >= 1
    )

    return {
        "gate_passed": gate_passed,
        "quality_score": score,
        "warnings": warnings,
        "blocked_patterns": blocked_patterns,
        "kpi_mix": {
            "trend": trend_count,
            "breakdown_or_share": breakdown_count,
            "quality_or_rate": quality_or_rate_count,
        },
        "edges_checked": total_edges,
        "low_confidence": len(low_conf_edges),
        "threshold": 0.7,
        "low_confidence_edges": low_conf_edges,
        "chart_rejections": chart_rejections,
        "metric_rejections": metric_rejections,
    }

