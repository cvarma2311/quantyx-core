from __future__ import annotations

import json
import logging
import ssl
import urllib.request
from html import escape
import os
from typing import Any

from services.ai.config import Settings


context = ssl._create_unverified_context()

logger = logging.getLogger(__name__)


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _find_metric_key(rows: list[dict[str, Any]], preferred: str | None = None) -> str | None:
    if preferred and rows and preferred in rows[0]:
        return preferred
    if not rows:
        return preferred
    skip = {"category", "date", "period"}
    for key in rows[0].keys():
        if key in skip:
            continue
        if _safe_float(rows[0].get(key)) is not None:
            return key
    return preferred


def chart_stats(rows: list[dict[str, Any]], metric_key: str | None) -> dict[str, Any]:
    if not rows or not metric_key:
        return {"count": 0}
    values = [_safe_float(row.get(metric_key)) for row in rows]
    cleaned = [v for v in values if v is not None]
    if not cleaned:
        return {"count": 0}
    return {
        "count": len(cleaned),
        "min": min(cleaned),
        "max": max(cleaned),
        "avg": sum(cleaned) / len(cleaned),
        "total": sum(cleaned),
        "latest": cleaned[-1],
        "delta_vs_prev": (cleaned[-1] - cleaned[-2]) if len(cleaned) >= 2 else None,
    }


def chart_insight(rows: list[dict[str, Any]], metric_key: str | None, chart_type: str) -> dict[str, Any]:
    stats = chart_stats(rows, metric_key)
    if stats.get("count", 0) == 0:
        return {"summary": "No numeric data available", "chart_type": chart_type}
    if chart_type == "line":
        delta = stats.get("delta_vs_prev")
        trend = "flat"
        if delta is not None:
            trend = "up" if delta > 0 else "down" if delta < 0 else "flat"
        return {
            "summary": f"Latest {metric_key}: {stats.get('latest')} ({trend})",
            "trend": trend,
            "latest": stats.get("latest"),
            "delta_vs_prev": delta,
            "chart_type": chart_type,
        }
    return {
        "summary": f"Total {metric_key}: {round(stats.get('total', 0.0), 2)}",
        "latest": stats.get("latest"),
        "chart_type": chart_type,
    }


def build_dashboard_evidence(chart_results: list[dict[str, Any]]) -> dict[str, Any]:
    total_charts = len(chart_results)
    refreshed = len([c for c in chart_results if c.get("status") == "ok"])
    failed = len([c for c in chart_results if c.get("status") != "ok"])
    trend_up = 0
    trend_down = 0
    total_rows = 0
    top_chart = None
    for item in chart_results:
        stats = item.get("stats") or {}
        insight = item.get("insight") or {}
        total_rows += int(stats.get("count") or 0)
        if insight.get("trend") == "up":
            trend_up += 1
        if insight.get("trend") == "down":
            trend_down += 1
        score = stats.get("total")
        if isinstance(score, (int, float)):
            if not top_chart or score > top_chart[1]:
                top_chart = (item.get("chart_id"), score)
    return {
        "total_charts": total_charts,
        "refreshed_charts": refreshed,
        "failed_charts": failed,
        "total_numeric_points": total_rows,
        "trend_up_charts": trend_up,
        "trend_down_charts": trend_down,
        "top_chart_by_total": {"chart_id": top_chart[0], "value": top_chart[1]} if top_chart else None,
    }


def deterministic_dashboard_summary(evidence: dict[str, Any]) -> str:
    return (
        f"Refreshed {evidence.get('refreshed_charts', 0)} of {evidence.get('total_charts', 0)} charts "
        f"with {evidence.get('total_numeric_points', 0)} numeric points. "
        f"Upward trends: {evidence.get('trend_up_charts', 0)}, downward trends: {evidence.get('trend_down_charts', 0)}."
    )


def deterministic_dashboard_inference(evidence: dict[str, Any]) -> str:
    refreshed = int(evidence.get("refreshed_charts", 0))
    failed = int(evidence.get("failed_charts", 0))
    up = int(evidence.get("trend_up_charts", 0))
    down = int(evidence.get("trend_down_charts", 0))
    if refreshed == 0:
        return "No refreshed charts were available; inference confidence is low."
    if up > down:
        return "Overall dashboard momentum appears positive based on line-trend dominance."
    if down > up:
        return "Overall dashboard momentum appears negative based on line-trend declines."
    if failed > 0:
        return "Dashboard trends are mixed; some chart refresh failures reduce inference confidence."
    return "Dashboard trends are balanced with no dominant directional movement."


def _llm_rewrite_enabled(settings: Settings) -> bool:
    flag = str(os.getenv("DASHBOARD_INSIGHTS_LLM_MODE", "auto")).lower()
    if flag in {"off", "false", "0"}:
        return False
    return bool(settings.openai_api_key)


def llm_rewrite_text(
    settings: Settings,
    *,
    kind: str,
    base_text: str,
    evidence: dict[str, Any],
) -> str:
    if not _llm_rewrite_enabled(settings):
        return base_text
    model = os.getenv("DASHBOARD_INSIGHTS_LLM_MODEL", settings.openai_model)
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "Rewrite text for business readability using only provided facts. Return JSON {\"text\":\"...\"}.",
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "kind": kind,
                        "base_text": base_text,
                        "evidence": evidence,
                        "constraints": ["Do not invent numbers", "Keep under 120 words", "No chain-of-thought"],
                    }
                ),
            },
        ],
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
    }
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {settings.openai_api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=25, context=context) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        parsed = json.loads(body["choices"][0]["message"]["content"])
        text = parsed.get("text")
        if isinstance(text, str) and text.strip():
            return text.strip()[:2000]
    except Exception:
        logger.warning("dashboard_insights.llm_rewrite_failed", exc_info=True)
    return base_text


def render_summary_html(text: str, evidence: dict[str, Any]) -> str:
    bullets = [
        f"Refreshed charts: {evidence.get('refreshed_charts', 0)} / {evidence.get('total_charts', 0)}",
        f"Numeric points: {evidence.get('total_numeric_points', 0)}",
        f"Trends up/down: {evidence.get('trend_up_charts', 0)} / {evidence.get('trend_down_charts', 0)}",
    ]
    li = "".join([f"<li>{escape(str(item))}</li>" for item in bullets])
    return f"<section><h4>Dashboard Summary</h4><p>{escape(text)}</p><ul>{li}</ul></section>"[:32768]


def render_inference_html(text: str, evidence: dict[str, Any]) -> str:
    top = evidence.get("top_chart_by_total") or {}
    extra = ""
    if top.get("chart_id") is not None:
        extra = f"<p>Top chart by total: {escape(str(top.get('chart_id')))} ({escape(str(top.get('value')))})</p>"
    return f"<section><h4>Dashboard Inference</h4><p>{escape(text)}</p>{extra}</section>"[:32768]
