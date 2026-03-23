from __future__ import annotations

import json
import urllib.request
from datetime import datetime
from typing import Any

from services.ai.config import Settings


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
