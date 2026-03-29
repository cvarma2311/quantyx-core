from __future__ import annotations

import json
import logging
import os
import urllib.request
from datetime import datetime
from typing import Any

from services.ai.config import Settings

logger = logging.getLogger(__name__)


def _is_date_value(value: Any) -> bool:
    if isinstance(value, (datetime,)):
        return True
    if isinstance(value, str):
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
            return True
        except ValueError:
            return False
    return False


def _is_time_dimension(dim_name: str, sample_values: list[Any]) -> bool:
    if dim_name.lower() in {"process_date", "pdate", "date_day", "date", "month", "month_year"}:
        return True
    return any(_is_date_value(val) for val in sample_values if val is not None)


def infer_chart_type(dimensions: list[str], rows: list[dict], metric_names: list[str]) -> str | None:
    if not rows or not metric_names:
        return None
    if not dimensions:
        return None
    if len(dimensions) == 1:
        dim = dimensions[0]
        values = [row.get(dim) for row in rows[:10]]
        if _is_time_dimension(dim, values):
            return "line"
        if len(rows) <= 10:
            return "pie"
        return "bar"
    if len(dimensions) >= 2:
        # If any time-like dimension exists, default to line
        for dim in dimensions:
            values = [row.get(dim) for row in rows[:10]]
            if _is_time_dimension(dim, values):
                return "line"
        return "bar"
    return None


def _default_time_axis(sample_values: list[Any]) -> dict[str, Any]:
    del sample_values
    return {"type": "DateAxis", "baseInterval": {"timeUnit": "day", "count": 1}}


def build_chart_payload(chart_type: str, rows: list[dict], metric_name: str, dimensions: list[str]) -> dict:
    chart_type = str(chart_type or "").strip().lower()

    if chart_type in {"pie", "donut"}:
        dim = dimensions[0]
        data = [
            {"category": row.get(dim), "value": row.get(metric_name)}
            for row in rows
        ]
        chart_payload = {
            "root": {"useTheme": "Animated"},
            "chart": {"type": "PieChart"},
            "series": {"type": "PieSeries", "valueField": "value", "categoryField": "category"},
            "legend": {"type": "Legend"},
        }
        if chart_type == "donut":
            chart_payload["series"]["innerRadius"] = "55%"
        return {
            "chart_type": chart_type,
            "chart_payload": chart_payload,
            "data": data,
        }

    if chart_type in {"bar", "horizontal_bar"}:
        dim = dimensions[0]
        data = [
            {"category": row.get(dim), "value": row.get(metric_name)}
            for row in rows
        ]
        if chart_type == "horizontal_bar":
            chart_payload = {
                "root": {"useTheme": "Animated"},
                "chart": {"type": "XYChart", "panX": False, "panY": False},
                "xAxis": {"type": "ValueAxis"},
                "yAxis": {"type": "CategoryAxis", "categoryField": "category"},
                "series": [
                    {
                        "type": "ColumnSeries",
                        "name": metric_name,
                        "valueXField": "value",
                        "categoryYField": "category",
                    }
                ],
                "legend": {"type": "Legend"},
            }
        else:
            chart_payload = {
                "root": {"useTheme": "Animated"},
                "chart": {"type": "XYChart", "panX": False, "panY": False},
                "xAxis": {"type": "CategoryAxis", "categoryField": "category"},
                "yAxis": {"type": "ValueAxis"},
                "series": [
                    {
                        "type": "ColumnSeries",
                        "name": metric_name,
                        "valueYField": "value",
                        "categoryXField": "category",
                    }
                ],
                "legend": {"type": "Legend"},
            }
        return {
            "chart_type": chart_type,
            "chart_payload": chart_payload,
            "data": data,
        }

    if chart_type in {"line", "area", "stacked_area"}:
        # time series (single or multi-series)
        time_dim = dimensions[0]
        axis = _default_time_axis([row.get(time_dim) for row in rows[:10]])
        if len(dimensions) > 1:
            cat_dim = dimensions[1]
            data = [
                {"date": row.get(time_dim), "category": row.get(cat_dim), "value": row.get(metric_name)}
                for row in rows
            ]
            series_type = "LineSeries"
            series_obj: dict[str, Any] = {
                "type": series_type,
                "nameField": "category",
                "valueYField": "value",
                "valueXField": "date",
            }
            if chart_type in {"area", "stacked_area"}:
                series_obj["fillOpacity"] = 0.35
            if chart_type == "stacked_area":
                series_obj["stacked"] = True
            return {
                "chart_type": chart_type,
                "chart_payload": {
                    "root": {"useTheme": "Animated"},
                    "chart": {"type": "XYChart", "panX": True, "panY": False},
                    "xAxis": axis,
                    "yAxis": {"type": "ValueAxis"},
                    "series": [series_obj],
                    "legend": {"type": "Legend"},
                },
                "data": data,
            }
        data = [{"date": row.get(time_dim), "value": row.get(metric_name)} for row in rows]
        series_obj = {
            "type": "LineSeries",
            "name": metric_name,
            "valueYField": "value",
            "valueXField": "date",
        }
        if chart_type in {"area", "stacked_area"}:
            series_obj["fillOpacity"] = 0.35
        return {
            "chart_type": chart_type,
            "chart_payload": {
                "root": {"useTheme": "Animated"},
                "chart": {"type": "XYChart", "panX": True, "panY": False},
                "xAxis": axis,
                "yAxis": {"type": "ValueAxis"},
                "series": [series_obj],
                "legend": {"type": "Legend"},
            },
            "data": data,
        }

    if chart_type in {"grouped_bar", "stacked_bar"}:
        if len(dimensions) < 2:
            return build_chart_payload("bar", rows, metric_name, dimensions)
        first_dim, second_dim = dimensions[0], dimensions[1]
        grouped_rows: dict[str, dict[str, Any]] = {}
        series_names = [str(value) for value in dict.fromkeys(row.get(second_dim) for row in rows if row.get(second_dim) is not None)]
        for row in rows:
            category = str(row.get(first_dim))
            series_name = str(row.get(second_dim))
            if category not in grouped_rows:
                grouped_rows[category] = {"category": category}
            grouped_rows[category][series_name] = row.get(metric_name)
        return {
            "chart_type": chart_type,
            "chart_payload": {
                "root": {"useTheme": "Animated"},
                "chart": {"type": "XYChart", "panX": False, "panY": False},
                "xAxis": {"type": "CategoryAxis", "categoryField": "category"},
                "yAxis": {"type": "ValueAxis"},
                "series": [
                    {
                        "type": "ColumnSeries",
                        "name": series_name,
                        "valueYField": series_name,
                        "categoryXField": "category",
                        "stacked": chart_type == "stacked_bar",
                    }
                    for series_name in series_names
                ],
                "legend": {"type": "Legend"},
            },
            "data": list(grouped_rows.values()),
        }

    return {"chart_type": None, "chart_payload": None, "data": []}


def infer_chart_type_with_llm(
    question: str | None,
    metric_names: list[str],
    dimensions: list[str],
    rows: list[dict],
    settings: Settings,
) -> str | None:
    if not settings.openai_api_key or not question:
        return None
    sample_rows = rows[:20]
    system_prompt = (
        "You are a chart type selector. "
        "Pick a chart_type from: pie, donut, bar, horizontal_bar, grouped_bar, stacked_bar, line, area, stacked_area, none. "
        "Return JSON: {\"chart_type\": \"...\"}."
    )
    user_prompt = {
        "question": question,
        "metrics": metric_names,
        "dimensions": dimensions,
        "rows_sample": sample_rows,
        "allowed_chart_types": ["pie", "donut", "bar", "horizontal_bar", "grouped_bar", "stacked_bar", "line", "area", "stacked_area", "none"],
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
    with urllib.request.urlopen(request, timeout=20) as response:
        body = json.loads(response.read().decode("utf-8"))
    content = body["choices"][0]["message"]["content"]
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return None
    chart_type = parsed.get("chart_type")
    if chart_type in {"pie", "donut", "bar", "horizontal_bar", "grouped_bar", "stacked_bar", "line", "area", "stacked_area"}:
        return chart_type
    return None


# ── Per-chart inference: LLM-first, deterministic fallback ──────────────────

def _safe_float(val: Any) -> float | None:
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _deterministic_insight(chart_type: str, rows: list[dict], metric_name: str, dim_key: str | None) -> str:
    """One-line callout derived purely from the data."""
    if not rows or not metric_name:
        return ""
    values = [(row.get(dim_key), _safe_float(row.get(metric_name))) for row in rows]
    values = [(d, v) for d, v in values if v is not None]
    if not values:
        return ""
    if chart_type in {"bar", "pie", "donut", "horizontal_bar"} and dim_key:
        best = max(values, key=lambda x: x[1])
        return f"Top {dim_key}: {best[0]} ({best[1]:,.2f})"
    if chart_type in {"line", "area", "stacked_area"} and len(values) >= 2:
        last, prev = values[-1], values[-2]
        delta = last[1] - prev[1]
        sign = "+" if delta >= 0 else ""
        return f"Latest {metric_name}: {last[1]:,.2f} ({sign}{delta:,.2f} vs prior period)"
    if values:
        latest = values[-1]
        return f"{metric_name}: {latest[1]:,.2f}"
    return ""


def _deterministic_narrative(rows: list[dict], metric_name: str, dim_key: str | None) -> str:
    """Best/worst dimension sentence."""
    if not rows or not metric_name or not dim_key:
        return ""
    values = [(row.get(dim_key), _safe_float(row.get(metric_name))) for row in rows]
    values = [(d, v) for d, v in values if v is not None]
    if len(values) < 2:
        return ""
    best = max(values, key=lambda x: x[1])
    worst = min(values, key=lambda x: x[1])
    if best[0] == worst[0]:
        return ""
    total = sum(v for _, v in values)
    best_pct = f" ({best[1] / total * 100:.1f}% of total)" if total else ""
    return (
        f"Highest: {best[0]} at {best[1]:,.2f}{best_pct}. "
        f"Lowest: {worst[0]} at {worst[1]:,.2f}."
    )


def _deterministic_stats(rows: list[dict], metric_name: str) -> dict[str, Any]:
    """Descriptive statistics over the primary metric."""
    values = [_safe_float(row.get(metric_name)) for row in rows]
    values = [v for v in values if v is not None]
    if not values:
        return {"count": 0}
    return {
        "count": len(values),
        "min": min(values),
        "max": max(values),
        "avg": round(sum(values) / len(values), 4),
        "total": round(sum(values), 4),
    }


def _llm_chart_inference(
    settings: Settings,
    chart_type: str,
    metric_name: str,
    dim_key: str | None,
    rows: list[dict],
    chart_title: str | None,
    stats: dict[str, Any],
) -> dict[str, Any] | None:
    """
    Ask the LLM to generate a one-line insight and a narrative sentence for a single chart.
    Returns {"insight_text": str, "narrative_text": str} or None on any failure.
    """
    if not getattr(settings, "openai_api_key", None):
        return None
    model = os.getenv("CHART_INFERENCE_MODEL", getattr(settings, "openai_model", "gpt-4o-mini"))
    timeout = int(os.getenv("CHART_INFERENCE_TIMEOUT", "20"))
    # Send up to 30 rows as a compact summary — avoid huge payloads
    sample_rows = rows[:30]
    system_prompt = (
        "You are a data analyst generating short chart annotations for a business dashboard. "
        "Given a chart's data sample and statistics, produce:\n"
        "- insight_text: ONE sentence (max 20 words) highlighting the most important number or trend. "
        "Be specific — include actual values, dimension names, and direction (up/down). "
        "Do NOT use generic phrases like 'data shows' or 'as seen in the chart'.\n"
        "- narrative_text: ONE sentence (max 30 words) comparing the best and worst performers "
        "or explaining the key pattern. Include actual values.\n"
        "Return JSON only: {\"insight_text\": \"...\", \"narrative_text\": \"...\"}"
    )
    user_payload = {
        "chart_title": chart_title or metric_name,
        "chart_type": chart_type,
        "metric": metric_name,
        "dimension": dim_key,
        "stats": stats,
        "data_sample": sample_rows,
    }
    request = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(
            {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": json.dumps(user_payload, default=str)},
                ],
                "temperature": 0.2,
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
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
        result = json.loads(body["choices"][0]["message"]["content"])
        insight = str(result.get("insight_text") or "").strip()
        narrative = str(result.get("narrative_text") or "").strip()
        if insight or narrative:
            return {"insight_text": insight, "narrative_text": narrative}
        return None
    except Exception:
        logger.warning("charts.inference.llm_failed | metric=%s chart_type=%s", metric_name, chart_type, exc_info=True)
        return None


def build_chart_inference(
    settings: Settings,
    chart_type: str,
    rows: list[dict],
    metric_name: str,
    dim_key: str | None,
    chart_title: str | None = None,
) -> dict[str, Any]:
    """
    Generate insight_text, narrative_text, and stats_json for a chart.

    Strategy:
      1. Always compute deterministic stats (fast, always available).
      2. Try LLM for insight_text + narrative_text (richer language).
      3. Fall back to deterministic insight + narrative if LLM fails or is disabled.

    Returns:
      {
        "insight_text":   str,   # one-liner for display below chart title
        "narrative_text": str,   # best/worst comparison sentence
        "stats_json":     dict,  # {count, min, max, avg, total}
      }
    """
    stats = _deterministic_stats(rows, metric_name)

    # LLM path — only attempt if there are rows to reason over
    if rows and metric_name:
        llm_result = _llm_chart_inference(
            settings,
            chart_type=chart_type,
            metric_name=metric_name,
            dim_key=dim_key,
            rows=rows,
            chart_title=chart_title,
            stats=stats,
        )
        if llm_result:
            return {
                "insight_text":   llm_result.get("insight_text") or "",
                "narrative_text": llm_result.get("narrative_text") or "",
                "stats_json":     stats,
            }

    # Deterministic fallback
    return {
        "insight_text":   _deterministic_insight(chart_type, rows, metric_name, dim_key),
        "narrative_text": _deterministic_narrative(rows, metric_name, dim_key),
        "stats_json":     stats,
    }
