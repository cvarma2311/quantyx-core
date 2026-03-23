from __future__ import annotations

from datetime import datetime
from typing import Any


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _is_date_like(value: Any) -> bool:
    if isinstance(value, datetime):
        return True
    text = str(value or "").strip()
    if not text:
        return False
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def _normalize_dashboard_suggestions(dashboard_suggestions: list[dict[str, Any]] | list[Any] | None) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for idx, item in enumerate(dashboard_suggestions or [], start=1):
        if isinstance(item, str) and item.strip():
            normalized.append(
                {
                    "suggestion_id": f"suggestion_{idx}",
                    "title": item.strip(),
                    "section": "story",
                    "priority": idx,
                    "summary": item.strip(),
                    "include": True,
                }
            )
            continue
        if not isinstance(item, dict):
            continue
        normalized.append(
            {
                "suggestion_id": str(item.get("suggestion_id") or f"suggestion_{idx}"),
                "title": str(item.get("title") or item.get("panel_title") or item.get("chart_title") or f"Suggestion {idx}"),
                "section": str(item.get("section") or "chart").strip().lower(),
                "priority": _safe_float(item.get("priority"), float(idx)),
                "summary": str(item.get("summary") or item.get("description") or "").strip() or None,
                "query_id": str(item.get("query_id") or "").strip() or None,
                "chart_title": str(item.get("chart_title") or "").strip() or None,
                "include": item.get("include", True) is not False,
                "chart_intent": str(item.get("chart_intent") or "").strip() or None,
                "chart_type": str(item.get("chart_type") or "").strip() or None,
            }
        )
    normalized.sort(key=lambda item: (_safe_float(item.get("priority"), 999.0), str(item.get("title") or "")))
    return normalized


def _story_cards_from_suggestions(suggestions: list[dict[str, Any]], existing_titles: set[str]) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for suggestion in suggestions:
        if suggestion.get("section") not in {"story", "summary", "hypothesis", "action"}:
            continue
        title = str(suggestion.get("title") or "").strip()
        summary = str(suggestion.get("summary") or "").strip()
        if not title or not summary or title in existing_titles:
            continue
        cards.append({"title": title[:80], "summary": summary[:280]})
        existing_titles.add(title)
    return cards


def _chart_priority(chart: dict[str, Any], suggestions: list[dict[str, Any]]) -> tuple[float, int]:
    query_id = str(((chart.get("metadata") or {}).get("query_id")) or "").strip()
    chart_title = str(chart.get("title") or "").strip().lower()
    best_rank = 999
    best_priority = 999.0
    for idx, suggestion in enumerate(suggestions):
        if suggestion.get("section") not in {"chart", "panel", "evidence"}:
            continue
        if suggestion.get("include") is False:
            continue
        suggestion_query_id = str(suggestion.get("query_id") or "").strip()
        suggestion_chart_title = str(suggestion.get("chart_title") or suggestion.get("title") or "").strip().lower()
        if suggestion_query_id and query_id and suggestion_query_id == query_id:
            return (_safe_float(suggestion.get("priority"), float(idx + 1)), idx)
        if suggestion_chart_title and chart_title and suggestion_chart_title == chart_title:
            best_rank = min(best_rank, idx)
            best_priority = min(best_priority, _safe_float(suggestion.get("priority"), float(idx + 1)))
    return (best_priority, best_rank)


def _chart_allowed(chart: dict[str, Any], suggestions: list[dict[str, Any]]) -> bool:
    query_id = str(((chart.get("metadata") or {}).get("query_id")) or "").strip()
    chart_title = str(chart.get("title") or "").strip().lower()
    matched = False
    for suggestion in suggestions:
        suggestion_query_id = str(suggestion.get("query_id") or "").strip()
        suggestion_chart_title = str(suggestion.get("chart_title") or suggestion.get("title") or "").strip().lower()
        if suggestion_query_id and query_id and suggestion_query_id == query_id:
            matched = True
            if suggestion.get("include") is False:
                return False
        elif suggestion_chart_title and chart_title and suggestion_chart_title == chart_title:
            matched = True
            if suggestion.get("include") is False:
                return False
    return True if not matched else True


def _infer_chart_fields(rows: list[dict[str, Any]]) -> tuple[list[str], str | None]:
    if not rows:
        return [], None
    first = rows[0]
    time_dims: list[str] = []
    category_dims: list[str] = []
    numeric_metrics: list[str] = []
    for key, value in first.items():
        if _is_number(value):
            numeric_metrics.append(str(key))
        elif _is_date_like(value) or str(key).strip().lower() in {"date", "process_date", "period", "month"}:
            time_dims.append(str(key))
        else:
            category_dims.append(str(key))
    metric_name = numeric_metrics[-1] if numeric_metrics else None
    ordered_dimensions = time_dims[:1] + category_dims[:1]
    if not ordered_dimensions:
        ordered_dimensions = time_dims[:2] or category_dims[:2]
    if metric_name is None:
        for key in first.keys():
            if str(key) not in ordered_dimensions:
                metric_name = str(key)
                break
        if metric_name is None:
            metric_name = str(next(iter(first.keys()), "value"))
    return ordered_dimensions[:2], metric_name


def build_anomaly_dashboard_spec(
    *,
    domain_id: str | None,
    investigation_id: str,
    anomaly_ids: list[str],
    hypothesis_ids: list[str],
    action_ids: list[str],
    summary_text: str | None,
    insights: list[str],
    hypotheses: list[dict[str, Any]],
    actions: list[dict[str, Any]],
    high_signal_areas: dict[str, list[dict[str, Any]]],
    executed_queries: list[dict[str, Any]],
    dashboard_suggestions: list[dict[str, Any]] | list[Any] | None,
    quality: dict[str, Any] | None = None,
) -> dict[str, Any]:
    suggestions = _normalize_dashboard_suggestions(dashboard_suggestions)
    domain_label = str(domain_id or "Domain").replace("_", " ").replace("-", " ").strip().title()
    title = f"{domain_label} Anomaly Investigation"
    story_cards = []
    if summary_text:
        story_cards.append({"title": "Summary", "summary": str(summary_text)})
    if high_signal_areas:
        sample = []
        for anomaly_id, areas in list(high_signal_areas.items())[:2]:
            for area in (areas or [])[:1]:
                sample.append(
                    f"{area.get('dimension')}={area.get('value')}"
                    if area.get("value") is not None
                    else str(area.get("dimension"))
                )
        if sample:
            story_cards.append(
                {
                    "title": "High-Signal Areas",
                    "summary": f"Priority investigative areas include {', '.join(sample[:4])}.",
                }
            )
    if hypotheses:
        top = hypotheses[0]
        story_cards.append(
            {
                "title": "Top Hypothesis",
                "summary": str(top.get("title") or "Leading explanation"),
            }
        )
    if actions:
        top_action = actions[0]
        story_cards.append(
            {
                "title": "Action",
                "summary": str(top_action.get("action_text") or "Follow-up action available."),
            }
        )
    existing_story_titles = {str(card.get("title") or "").strip() for card in story_cards if str(card.get("title") or "").strip()}
    story_cards.extend(_story_cards_from_suggestions(suggestions, existing_story_titles))

    charts: list[dict[str, Any]] = []
    for item in executed_queries[:6]:
        rows = [row for row in (item.get("rows") or []) if isinstance(row, dict)]
        if not rows:
            continue
        dimensions, metric_name = _infer_chart_fields(rows)
        chart = {
            "title": str(item.get("title") or "Anomaly Evidence"),
            "metric": metric_name,
            "dimensions": dimensions,
            "rows_count": len(rows),
            "chart_data": rows,
            "sql": item.get("sql"),
            "params": [],
            "metadata": {
                "investigation_id": investigation_id,
                "anomaly_ids": anomaly_ids,
                "hypothesis_ids": hypothesis_ids,
                "action_ids": action_ids,
                "query_id": item.get("query_id"),
                "reason": item.get("reason"),
            },
        }
        matched_suggestion = next(
            (
                suggestion
                for suggestion in suggestions
                if suggestion.get("query_id") == item.get("query_id")
                or str(suggestion.get("chart_title") or suggestion.get("title") or "").strip().lower() == str(chart.get("title") or "").strip().lower()
            ),
            None,
        )
        if matched_suggestion:
            if matched_suggestion.get("chart_type"):
                chart["type"] = matched_suggestion.get("chart_type")
            if matched_suggestion.get("chart_intent"):
                chart["intent"] = matched_suggestion.get("chart_intent")
            chart["metadata"]["dashboard_suggestion_id"] = matched_suggestion.get("suggestion_id")
        charts.append(chart)
    charts = [chart for chart in charts if _chart_allowed(chart, suggestions)]
    charts.sort(key=lambda chart: _chart_priority(chart, suggestions))

    suggested_insights = [
        str(item.get("summary") or "").strip()
        for item in suggestions
        if item.get("section") in {"insight", "story", "summary"} and str(item.get("summary") or "").strip()
    ]
    merged_insights: list[str] = []
    for text in suggested_insights + [str(v).strip() for v in insights if str(v).strip()]:
        if text and text not in merged_insights:
            merged_insights.append(text)

    spec: dict[str, Any] = {
        "title": title,
        "dashboard_title": title,
        "dashboard_kind": "anomaly",
        "anomaly_summary": {
            "investigation_id": investigation_id,
            "anomaly_ids": anomaly_ids,
            "hypothesis_ids": hypothesis_ids,
            "action_ids": action_ids,
            "primary_summary": summary_text,
        },
        "anomaly_ids": anomaly_ids,
        "hypothesis_ids": hypothesis_ids,
        "action_ids": action_ids,
        "charts": charts,
        "story": {
            "title": title,
            "cards": story_cards[:6],
        },
        "insights": merged_insights[:10],
        "quality": quality or {
            "confidence": None,
            "warnings": [],
        },
        "chart_plan": [],
        "chart_candidates": [],
    }
    if suggestions:
        spec["dashboard_suggestions"] = suggestions
    return spec
