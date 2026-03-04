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


def build_chart_payload(chart_type: str, rows: list[dict], metric_name: str, dimensions: list[str]) -> dict:
    if chart_type == "pie":
        dim = dimensions[0]
        data = [
            {"category": row.get(dim), "value": row.get(metric_name)}
            for row in rows
        ]
        return {
            "chart_type": "pie",
            "chart_payload": {
                "root": {"useTheme": "Animated"},
                "chart": {"type": "PieChart"},
                "series": {"type": "PieSeries", "valueField": "value", "categoryField": "category"},
                "legend": {"type": "Legend"},
            },
            "data": data,
        }

    if chart_type == "bar":
        dim = dimensions[0]
        data = [
            {"category": row.get(dim), "value": row.get(metric_name)}
            for row in rows
        ]
        return {
            "chart_type": "bar",
            "chart_payload": {
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
            },
            "data": data,
        }

    if chart_type == "line":
        # time series (single or multi-series)
        time_dim = dimensions[0]
        if len(dimensions) > 1:
            cat_dim = dimensions[1]
            data = [
                {"date": row.get(time_dim), "category": row.get(cat_dim), "value": row.get(metric_name)}
                for row in rows
            ]
            return {
                "chart_type": "line",
                "chart_payload": {
                    "root": {"useTheme": "Animated"},
                    "chart": {"type": "XYChart", "panX": True, "panY": False},
                    "xAxis": {"type": "DateAxis", "baseInterval": {"timeUnit": "day", "count": 1}},
                    "yAxis": {"type": "ValueAxis"},
                    "series": [
                        {
                            "type": "LineSeries",
                            "nameField": "category",
                            "valueYField": "value",
                            "valueXField": "date",
                        }
                    ],
                    "legend": {"type": "Legend"},
                },
                "data": data,
            }
        data = [{"date": row.get(time_dim), "value": row.get(metric_name)} for row in rows]
        return {
            "chart_type": "line",
            "chart_payload": {
                "root": {"useTheme": "Animated"},
                "chart": {"type": "XYChart", "panX": True, "panY": False},
                "xAxis": {"type": "DateAxis", "baseInterval": {"timeUnit": "day", "count": 1}},
                "yAxis": {"type": "ValueAxis"},
                "series": [
                    {
                        "type": "LineSeries",
                        "name": metric_name,
                        "valueYField": "value",
                        "valueXField": "date",
                    }
                ],
                "legend": {"type": "Legend"},
            },
            "data": data,
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
        "Pick a chart_type from: pie, bar, line, none. "
        "Return JSON: {\"chart_type\": \"...\"}."
    )
    user_prompt = {
        "question": question,
        "metrics": metric_names,
        "dimensions": dimensions,
        "rows_sample": sample_rows,
        "allowed_chart_types": ["pie", "bar", "line", "none"],
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
    if chart_type in {"pie", "bar", "line"}:
        return chart_type
    return None
