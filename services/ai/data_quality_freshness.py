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


def _current_quality(table: dict[str, Any]) -> dict[str, Any]:
    return table.get("quality_summary") or {}


def analyze_freshness_and_stability(
    *,
    profiling: dict[str, Any],
    previous_tables_by_name: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    previous_tables_by_name = previous_tables_by_name or {}
    stale_days_threshold = float(os.getenv("DATA_QUALITY_STALE_DAYS_THRESHOLD", "7"))
    row_change_threshold = float(os.getenv("DATA_QUALITY_STABILITY_ROW_CHANGE_PCT", "20"))
    completeness_change_threshold = float(os.getenv("DATA_QUALITY_STABILITY_COMPLETENESS_CHANGE_PCT", "10"))

    results: list[dict[str, Any]] = []
    stale_count = 0
    no_freshness_column_count = 0
    stability_issue_count = 0

    for table in (profiling.get("tables") or []):
        if not isinstance(table, dict):
            continue
        table_name = str(table.get("name") or "").strip()
        if not table_name:
            continue
        quality = _current_quality(table)
        current_row_count = _as_float(quality.get("row_count") or table.get("row_count"))
        current_completeness = _as_float(quality.get("table_completeness_score"))
        freshness_lag_days = _as_float(quality.get("freshness_lag_days"))
        primary_time_column = quality.get("primary_time_column")

        previous = previous_tables_by_name.get(table_name) or {}
        previous_summary = previous.get("summary_json") or {}
        previous_quality = previous_summary.get("quality_summary") or {}
        baseline_row_count = _as_float(previous.get("row_count") or previous_quality.get("row_count"))
        baseline_completeness = _as_float(previous.get("completeness_score") or previous_quality.get("table_completeness_score"))

        row_count_change_pct = None
        if baseline_row_count not in (None, 0) and current_row_count is not None:
            row_count_change_pct = round(abs((current_row_count - baseline_row_count) / baseline_row_count) * 100.0, 2)

        completeness_score_change = None
        if baseline_completeness is not None and current_completeness is not None:
            completeness_score_change = round(current_completeness - baseline_completeness, 2)

        freshness_score = None
        freshness_status = "no_freshness_column"
        if freshness_lag_days is not None:
            freshness_score = max(0.0, 100.0 - min(max(freshness_lag_days, 0.0), 20.0) * 5.0)
            freshness_status = "stale" if freshness_lag_days > stale_days_threshold else "fresh"
        elif primary_time_column:
            freshness_status = "unknown"

        stability_status = "no_baseline"
        stability_issues: list[str] = []
        if previous:
            stability_status = "stable"
            if row_count_change_pct is not None and row_count_change_pct > row_change_threshold:
                stability_status = "changed"
                stability_issues.append(f"row_count_change_pct>{row_change_threshold:g}")
            if completeness_score_change is not None and abs(completeness_score_change) > completeness_change_threshold:
                stability_status = "changed"
                stability_issues.append(f"completeness_score_change>{completeness_change_threshold:g}")

        if freshness_status == "stale":
            stale_count += 1
        if freshness_status == "no_freshness_column":
            no_freshness_column_count += 1
        if stability_status == "changed":
            stability_issue_count += 1

        results.append(
            {
                "table_name": table_name,
                "freshness_column": primary_time_column,
                "latest_timestamp": quality.get("latest_timestamp"),
                "earliest_timestamp": quality.get("earliest_timestamp"),
                "freshness_lag_days": freshness_lag_days,
                "freshness_score": round(freshness_score, 2) if freshness_score is not None else None,
                "freshness_status": freshness_status,
                "baseline_quality_run_id": previous.get("quality_run_id"),
                "baseline_row_count": baseline_row_count,
                "current_row_count": current_row_count,
                "row_count_change_pct": row_count_change_pct,
                "baseline_completeness_score": baseline_completeness,
                "current_completeness_score": current_completeness,
                "completeness_score_change": completeness_score_change,
                "stability_status": stability_status,
                "stability_issues": stability_issues,
            }
        )

    return {
        "results": results,
        "summary": {
            "stale_table_count": stale_count,
            "tables_without_freshness_column_count": no_freshness_column_count,
            "stability_issue_count": stability_issue_count,
            "baseline_table_count": len(previous_tables_by_name),
        },
    }
