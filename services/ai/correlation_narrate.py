"""
Phase 43 — Narrative generation for correlation intelligence results.

Produces human-readable text + HTML for:
  - Each investigation thread (localised cause-effect narrative)
  - The overall correlation run summary

Uses the same urllib-based OpenAI REST pattern as the rest of the codebase.
Falls back to template-based text when LLM is unavailable or fails.
"""

from __future__ import annotations

import json
import logging
import os
import ssl
import urllib.request
from html import escape
from typing import Any

from services.ai.config import Settings

context = ssl._create_unverified_context()

logger = logging.getLogger(__name__)

_NARRATE_MODEL_ENV = "CORRELATION_NARRATE_MODEL"
_NARRATE_TIMEOUT_ENV = "CORRELATION_NARRATE_TIMEOUT_SEC"


# ---------------------------------------------------------------------------
# LLM call helper (mirrors _llm_json_response in agentic_orchestrator)
# ---------------------------------------------------------------------------

def _llm_call(
    settings: Settings,
    *,
    system_prompt: str,
    user_payload: dict | list,
    temperature: float = 0.3,
    timeout: int | None = None,
) -> dict | None:
    """
    POST to OpenAI chat/completions in JSON-object mode.
    Returns parsed dict or None on any failure.
    """
    api_key = getattr(settings, "openai_api_key", None)
    if not api_key:
        logger.warning("[correlation.narrate.llm] No API key configured — skipping LLM call")
        return None

    model = os.getenv(_NARRATE_MODEL_ENV, getattr(settings, "openai_model", "gpt-4o-mini"))
    timeout_sec = timeout or int(os.getenv(_NARRATE_TIMEOUT_ENV, "60"))

    # Determine call context from the user payload shape for log labelling
    if isinstance(user_payload, dict):
        call_label = (
            "thread_narrate" if "trigger_metric" in user_payload
            else "run_summary" if "total_metrics_analyzed" in user_payload
            else "llm_call"
        )
    else:
        call_label = "llm_call"

    user_payload_str = json.dumps(user_payload, default=str)
    logger.info(
        "[correlation.narrate.llm.request] call=%s model=%s temperature=%s "
        "payload_chars=%d system_prompt_chars=%d",
        call_label, model, temperature,
        len(user_payload_str), len(system_prompt),
    )

    body = json.dumps(
        {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_payload_str},
            ],
            "temperature": temperature,
            "response_format": {"type": "json_object"},
        },
        default=str,
    ).encode("utf-8")

    request = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_sec, context=context) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
        result = json.loads(raw["choices"][0]["message"]["content"])
        usage = raw.get("usage") or {}
        logger.info(
            "[correlation.narrate.llm.response] call=%s model=%s "
            "prompt_tokens=%s completion_tokens=%s total_tokens=%s "
            "response_keys=%s summary_preview=%r",
            call_label, model,
            usage.get("prompt_tokens"), usage.get("completion_tokens"), usage.get("total_tokens"),
            list(result.keys()) if isinstance(result, dict) else type(result).__name__,
            str(result.get("summary_text") or result.get("narrative_text") or "")[:120],
        )
        return result
    except Exception:
        logger.warning(
            "[correlation.narrate.llm.failed] call=%s model=%s error — falling back to template",
            call_label, model, exc_info=True,
        )
        return None


# ---------------------------------------------------------------------------
# Template fallbacks
# ---------------------------------------------------------------------------

def _thread_narrative_fallback(thread: dict) -> tuple[str, str]:
    """Plain-text + HTML narrative when LLM is unavailable."""
    metric = thread["trigger_metric"]
    anomaly_id = thread["trigger_anomaly_id"]
    chain = thread.get("evidence_chain") or []
    confidence = thread.get("confidence", 0.0)
    leading_dim = thread.get("leading_dimension")
    leading_dim_val = thread.get("leading_dim_value")
    suggested = thread.get("suggested_focus") or []

    related = [e["related_metric"] for e in chain[:3]]
    related_str = ", ".join(related) if related else "no correlated metrics"

    dim_sentence = ""
    if leading_dim and leading_dim_val:
        dim_sentence = (
            f" The anomaly is most concentrated in {leading_dim} = '{leading_dim_val}'."
        )

    text = (
        f"An anomaly was detected in '{metric}' (confidence {confidence:.0%}).{dim_sentence} "
        f"This metric is statistically correlated with: {related_str}. "
        f"Recommended investigation focus: {', '.join(suggested) if suggested else metric}."
    )

    html = (
        f"<p>An anomaly was detected in <strong>{escape(metric)}</strong> "
        f"(confidence <strong>{confidence:.0%}</strong>).{escape(dim_sentence)}</p>"
        f"<p>Correlated metrics: {', '.join(f'<em>{escape(m)}</em>' for m in related)}.</p>"
        f"<p>Recommended focus: "
        + ", ".join(f"<strong>{escape(s)}</strong>" for s in suggested)
        + ".</p>"
    )
    return text, html


def _summary_fallback(
    anomaly_results: list[dict],
    correlation_pairs: list[dict],
    forward_projections: list[dict],
    investigation_threads: list[dict],
    data_quality_warnings: list[dict] | None = None,
    category_temporal_summary: list[dict] | None = None,
    snapshot_eligibility_summary: dict[str, Any] | None = None,
    semantic_context: dict[str, Any] | None = None,
) -> tuple[str, str]:
    """Plain-text + HTML overall summary when LLM is unavailable."""
    n_metrics = len({a["metric_name"] for a in anomaly_results})
    n_anomalies = len(anomaly_results)
    n_pairs = len(correlation_pairs)
    n_threads = len(investigation_threads)

    strong_pairs = [
        p for p in correlation_pairs
        if abs(p.get("pearson_r") or 0) >= 0.7
    ]

    trending_up = [p for p in forward_projections if p.get("trend_direction") == "up"]
    trending_down = [p for p in forward_projections if p.get("trend_direction") == "down"]

    parts: list[str] = [
        f"Statistical analysis identified {n_anomalies} anomalies across {n_metrics} metrics.",
    ]
    if strong_pairs:
        names = " and ".join(
            f"'{p['metric_a']}' ↔ '{p['metric_b']}'" for p in strong_pairs[:2]
        )
        parts.append(f"Strong correlations were found between {names}.")
    if trending_up:
        parts.append(
            f"{', '.join(p['metric_name'] for p in trending_up[:2])} show an upward trend."
        )
    if trending_down:
        parts.append(
            f"{', '.join(p['metric_name'] for p in trending_down[:2])} show a downward trend."
        )
    if n_threads:
        parts.append(
            f"{n_threads} investigation thread(s) were generated linking anomalies to potential causes."
        )
    if snapshot_eligibility_summary:
        source_mode = str(snapshot_eligibility_summary.get("source_mode") or "").strip()
        if source_mode.startswith("fact"):
            parts.append("Live fact-native temporal series were used as the primary evidence source.")
    if category_temporal_summary:
        top_category = category_temporal_summary[0]
        parts.append(
            f"Category-temporal analysis was generated for {top_category.get('measure_name')} by "
            f"{top_category.get('category_column')}."
        )
    if data_quality_warnings:
        parts.append(str(data_quality_warnings[0].get("message") or "").strip())
    if semantic_context and semantic_context.get("interpretation_rules"):
        rule = semantic_context["interpretation_rules"][0]
        parts.append(str(rule.get("rule") or rule.get("text") or "Domain interpretation guidance was applied."))

    text = " ".join(parts)
    html = "".join(f"<p>{escape(p)}</p>" for p in parts)
    return text, html


# ---------------------------------------------------------------------------
# Thread narrative
# ---------------------------------------------------------------------------

_THREAD_SYSTEM_PROMPT = """\
You are an expert business intelligence analyst. Given statistical findings about \
an anomalous metric and its correlated metrics, produce a concise, actionable \
investigation narrative in plain business language.

Respond in JSON with exactly two keys:
  "narrative_text"  — 2-4 sentence plain-text narrative (no markdown)
  "narrative_html"  — the same content formatted as minimal HTML \
(<p>, <strong>, <em>, <ul>/<li> only)

Rules:
- Do not repeat raw numbers unless they add insight
- Focus on what the anomaly means and where to look next
- Mention the dimension breakdown if present
- Keep it under 120 words
"""


def narrate_thread(
    settings: Settings,
    thread: dict,
    anomaly_lookup: dict[str, dict],
) -> tuple[str, str]:
    """
    Generate narrative for one investigation thread.

    Returns (narrative_text, narrative_html).
    Falls back to template if LLM unavailable.
    """
    anomaly = anomaly_lookup.get(thread["trigger_anomaly_id"], {})
    chain = thread.get("evidence_chain") or []

    payload: dict[str, Any] = {
        "trigger_metric": thread["trigger_metric"],
        "anomaly_class": anomaly.get("anomaly_class", "unknown"),
        "anomaly_score": anomaly.get("anomaly_score"),
        "z_score": anomaly.get("z_score"),
        "deviation_pct": anomaly.get("deviation_pct"),
        "detected_at": anomaly.get("detected_at"),
        "top_dimension": anomaly.get("top_dimension"),
        "top_dimension_value": anomaly.get("top_dimension_value"),
        "dimension_pct": anomaly.get("dimension_pct"),
        "confidence": thread.get("confidence"),
        "correlated_metrics": [
            {
                "metric": e["related_metric"],
                "pearson_r": e.get("pearson_r"),
                "lagged_r": e.get("lagged_r"),
                "best_lag": e.get("best_lag"),
                "lag_direction": e.get("lag_direction"),
                "strength": e.get("strength_label"),
                "direction": e.get("direction_label"),
            }
            for e in chain[:5]
        ],
        "suggested_focus": thread.get("suggested_focus") or [],
    }

    result = _llm_call(
        settings,
        system_prompt=_THREAD_SYSTEM_PROMPT,
        user_payload=payload,
        temperature=0.3,
    )
    if result and result.get("narrative_text"):
        return result["narrative_text"], result.get("narrative_html") or (
            f"<p>{escape(result['narrative_text'])}</p>"
        )

    return _thread_narrative_fallback(thread)


# ---------------------------------------------------------------------------
# Run-level summary narrative
# ---------------------------------------------------------------------------

_SUMMARY_SYSTEM_PROMPT = """\
You are an expert operations intelligence analyst. Given a set of statistical \
findings from a multi-metric correlation run, produce an executive summary \
that highlights the most important anomalies, key correlations, trend outlook, \
recommended actions, source quality, and category-temporal behavior.

Respond in JSON with exactly two keys:
  "summary_text"  — 3-5 sentences of plain-text executive summary (no markdown)
  "summary_html"  — the same content as minimal HTML \
(<h4>, <p>, <strong>, <em>, <ul>/<li> only)

Rules:
- Lead with the most critical finding
- Mention at most 3 anomalies by name
- Mention at most 2 strong correlation pairs
- Include forward-looking trend signal if notable
- Mention if live fact-native sources were preferred over chart fallbacks
- Mention category mix / category forecast signals when available
- Call out weak or limited coverage when the quality payload indicates it
- End with 1 sentence recommending next action
- Keep total under 200 words
"""


def _build_category_temporal_summary(
    kpi_snapshots: list[dict],
    forward_projections: list[dict],
) -> list[dict[str, Any]]:
    projection_by_metric = {
        str(item.get("metric_name") or ""): item
        for item in forward_projections
        if str(item.get("metric_name") or "").strip()
    }
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for snap in kpi_snapshots:
        qp = snap.get("query_payload") or {}
        source_kind = str(qp.get("source_kind") or snap.get("source_kind") or "")
        if source_kind != "fact_category_metric":
            continue
        table_name = str(qp.get("table") or "").strip()
        category_column = str(qp.get("category_column") or "").strip()
        category_value = str(qp.get("category_value") or "").strip()
        metric_name = str(snap.get("metric_name") or "").strip()
        prefix = f"_by_month_{table_name}_{category_column}_"
        measure_name = metric_name.split(prefix, 1)[0] if table_name and category_column and prefix in metric_name else metric_name
        grouped.setdefault((table_name, measure_name, category_column), []).append(
            {
                "metric_name": metric_name,
                "category_value": category_value,
                "projection": projection_by_metric.get(metric_name) or {},
            }
        )

    summary: list[dict[str, Any]] = []
    for (table_name, measure_name, category_column), items in grouped.items():
        direction_counts: dict[str, int] = {}
        categories: list[str] = []
        for item in items:
            categories.append(item.get("category_value") or "")
            direction = str((item.get("projection") or {}).get("trend_direction") or "flat")
            direction_counts[direction] = direction_counts.get(direction, 0) + 1
        dominant_direction = max(direction_counts, key=direction_counts.get) if direction_counts else "flat"
        summary.append(
            {
                "table_name": table_name,
                "measure_name": measure_name,
                "category_column": category_column,
                "category_count": len(items),
                "categories": categories[:5],
                "dominant_direction": dominant_direction,
                "direction_counts": direction_counts,
            }
        )
    return sorted(summary, key=lambda item: (-int(item.get("category_count") or 0), str(item.get("measure_name") or "")))[:5]


def _build_run_insights(
    *,
    kpi_snapshots: list[dict],
    correlation_pairs: list[dict],
    forward_projections: list[dict],
    snapshot_eligibility_summary: dict[str, Any] | None = None,
    data_quality_warnings: list[dict] | None = None,
) -> list[dict[str, Any]]:
    insights: list[dict[str, Any]] = []
    summary = snapshot_eligibility_summary or {}
    source_mode = str(summary.get("source_mode") or "").strip()
    if source_mode.startswith("fact"):
        fact_summary = summary.get("fact_source_summary") or {}
        llm_ranked = bool(fact_summary.get("llm_ranked"))
        insights.append(
            {
                "type": "source_selection",
                "title": "Fact-Native Evidence Preferred",
                "detail": (
                    "Live fact-based temporal series were selected ahead of reconstructed chart snapshots."
                    + (" Source ranking was LLM-assisted before deterministic validation." if llm_ranked else "")
                ),
                "severity": "info",
            }
        )

    category_temporal_summary = _build_category_temporal_summary(kpi_snapshots, forward_projections)
    for item in category_temporal_summary[:2]:
        insights.append(
            {
                "type": "category_temporal",
                "title": f"{item.get('measure_name')} by {item.get('category_column')}",
                "detail": (
                    f"{item.get('category_count')} categories analyzed; dominant forecast direction is "
                    f"{item.get('dominant_direction')}."
                ),
                "severity": "info",
            }
        )

    for pair in [p for p in correlation_pairs if abs(p.get("pearson_r") or 0.0) >= 0.95][:2]:
        insights.append(
            {
                "type": "overlap_warning",
                "title": f"{pair.get('metric_a')} vs {pair.get('metric_b')}",
                "detail": "Near-perfect correlation suggests possible duplicate or semantically overlapping signals.",
                "severity": "warning",
            }
        )

    for warning in (data_quality_warnings or [])[:2]:
        insights.append(
            {
                "type": "quality_warning",
                "title": str(warning.get("code") or "quality_warning"),
                "detail": str(warning.get("message") or ""),
                "severity": str(warning.get("severity") or "warning"),
            }
        )
    if not insights:
        insights.append(
            {
                "type": "coverage_summary",
                "title": "Correlation Coverage Summary",
                "detail": (
                    f"Analyzed {len(kpi_snapshots)} temporal series, generated {len(correlation_pairs)} correlation pairs, "
                    f"and produced {len(forward_projections)} forward projections."
                ),
                "severity": "info",
            }
        )
    return insights[:6]


def narrate_run_summary(
    settings: Settings,
    *,
    kpi_snapshots: list[dict],
    anomaly_results: list[dict],
    correlation_pairs: list[dict],
    forward_projections: list[dict],
    investigation_threads: list[dict],
    data_quality_warnings: list[dict] | None = None,
    snapshot_eligibility_summary: dict[str, Any] | None = None,
    semantic_context: dict[str, Any] | None = None,
) -> tuple[str, str]:
    """
    Generate an executive summary for the entire correlation run.

    Returns (summary_text, summary_html).
    Falls back to template if LLM unavailable.
    """
    # Top anomalies by score
    top_anomalies = sorted(
        anomaly_results, key=lambda a: a.get("anomaly_score", 0), reverse=True
    )[:5]

    # Strongest pairs by |pearson_r|
    top_pairs = sorted(
        correlation_pairs,
        key=lambda p: abs(p.get("pearson_r") or 0),
        reverse=True,
    )[:5]

    # Notable projections (non-flat with inflection signals)
    notable_projections = [
        p for p in forward_projections
        if p.get("trend_direction") != "flat" or p.get("inflection_signal")
    ][:5]
    category_temporal_summary = _build_category_temporal_summary(kpi_snapshots, forward_projections)

    payload: dict[str, Any] = {
        "total_metrics_analyzed": len({a["metric_name"] for a in anomaly_results}),
        "total_anomalies": len(anomaly_results),
        "total_correlation_pairs": len(correlation_pairs),
        "total_investigation_threads": len(investigation_threads),
        "top_anomalies": [
            {
                "metric": a["metric_name"],
                "class": a["anomaly_class"],
                "score": a["anomaly_score"],
                "deviation_pct": a.get("deviation_pct"),
                "detected_at": a["detected_at"],
                "dimension": a.get("top_dimension"),
                "dimension_value": a.get("top_dimension_value"),
            }
            for a in top_anomalies
        ],
        "strongest_correlations": [
            {
                "metric_a": p["metric_a"],
                "metric_b": p["metric_b"],
                "pearson_r": p.get("pearson_r"),
                "lagged_r": p.get("lagged_r"),
                "best_lag": p.get("best_lag"),
                "lag_direction": p.get("lag_direction"),
                "strength": p.get("strength_label"),
                "direction": p.get("direction_label"),
                "is_stable": p.get("is_stable"),
            }
            for p in top_pairs
        ],
        "trend_outlook": [
            {
                "metric": p["metric_name"],
                "direction": p.get("trend_direction"),
                "inflection_signal": p.get("inflection_signal"),
                "inflection_detail": p.get("inflection_detail"),
                "seasonality": p.get("seasonality_present"),
                "anomaly_density_trend": p.get("anomaly_density_trend"),
            }
            for p in notable_projections
        ],
        "top_threads": [
            {
                "trigger_metric": t["trigger_metric"],
                "confidence": t["confidence"],
                "suggested_focus": t.get("suggested_focus") or [],
                "leading_dimension": t.get("leading_dimension"),
                "leading_dim_value": t.get("leading_dim_value"),
            }
            for t in sorted(
                investigation_threads,
                key=lambda t: t.get("confidence", 0),
                reverse=True,
            )[:3]
        ],
        "category_temporal_summary": category_temporal_summary,
        "data_quality_warnings": data_quality_warnings or [],
        "snapshot_eligibility_summary": snapshot_eligibility_summary or {},
        "semantic_context": semantic_context or {},
    }

    result = _llm_call(
        settings,
        system_prompt=_SUMMARY_SYSTEM_PROMPT,
        user_payload=payload,
        temperature=0.3,
        timeout=90,
    )
    if result and result.get("summary_text"):
        return result["summary_text"], result.get("summary_html") or (
            f"<p>{escape(result['summary_text'])}</p>"
        )

    return _summary_fallback(
        anomaly_results,
        correlation_pairs,
        forward_projections,
        investigation_threads,
        data_quality_warnings,
        category_temporal_summary,
        snapshot_eligibility_summary,
        semantic_context,
    )


# ---------------------------------------------------------------------------
# Main entry point: narrate everything in one pass
# ---------------------------------------------------------------------------

def narrate_correlation_results(
    settings: Settings,
    *,
    kpi_snapshots: list[dict],
    anomaly_results: list[dict],
    correlation_pairs: list[dict],
    forward_projections: list[dict],
    investigation_threads: list[dict],
    data_quality_warnings: list[dict] | None = None,
    snapshot_eligibility_summary: dict[str, Any] | None = None,
    semantic_context: dict[str, Any] | None = None,
) -> dict:
    """
    Enrich investigation threads with narrative text + HTML, then generate
    an overall run summary.

    Mutates threads in-place (adds narrative_text, narrative_html).

    Returns:
      {
        "summary_text": str,
        "summary_html": str,
        "threads_narrated": int,
        "insights": list[dict],
      }
    """
    # Build anomaly lookup for fast access inside thread narration
    anomaly_lookup: dict[str, dict] = {
        a["anomaly_id"]: a for a in anomaly_results
    }

    narrated = 0
    for thread in investigation_threads:
        try:
            text, html = narrate_thread(settings, thread, anomaly_lookup)
            thread["narrative_text"] = text
            thread["narrative_html"] = html
            narrated += 1
        except Exception:
            logger.warning(
                "[correlation.narrate] Thread narration failed for %s",
                thread.get("thread_id"),
                exc_info=True,
            )

    logger.info("[correlation.narrate] Narrated %d threads", narrated)

    # Overall run summary
    summary_text = summary_html = ""
    try:
        summary_text, summary_html = narrate_run_summary(
            settings,
            kpi_snapshots=kpi_snapshots,
            anomaly_results=anomaly_results,
            correlation_pairs=correlation_pairs,
            forward_projections=forward_projections,
            investigation_threads=investigation_threads,
            data_quality_warnings=data_quality_warnings,
            snapshot_eligibility_summary=snapshot_eligibility_summary,
            semantic_context=semantic_context,
        )
    except Exception:
        logger.warning("[correlation.narrate] Run summary narration failed", exc_info=True)
        summary_text, summary_html = _summary_fallback(
            anomaly_results,
            correlation_pairs,
            forward_projections,
            investigation_threads,
            data_quality_warnings,
            _build_category_temporal_summary(kpi_snapshots, forward_projections),
            snapshot_eligibility_summary,
            semantic_context,
        )

    insights = _build_run_insights(
        kpi_snapshots=kpi_snapshots,
        correlation_pairs=correlation_pairs,
        forward_projections=forward_projections,
        snapshot_eligibility_summary=snapshot_eligibility_summary,
        data_quality_warnings=data_quality_warnings,
    )

    return {
        "summary_text": summary_text,
        "summary_html": summary_html,
        "threads_narrated": narrated,
        "insights": insights,
        "semantic_context": semantic_context or {},
    }
