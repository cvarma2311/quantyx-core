"""
Phase 43 — Correlation chart spec generation.

Produces amCharts 5-compatible JSON specs for all six chart types:
  1. forecast_band        — historical + projected trend with ±1σ/±2σ confidence bands
  2. anomaly_timeline     — anomaly score series coloured by anomaly class
  3. correlation_heatmap  — metric × metric Pearson-r heat map
  4. scatter_regression   — scatter + regression line for a correlated pair
  5. rolling_correlation  — rolling Pearson-r over time for a pair
  6. anomaly_density      — histogram of anomaly scores per metric

The specs are self-contained JSON blobs.  The front-end initialises an
amCharts 5 XYChart (or similar) from the spec and binds the data array.
No DOM or browser dependency lives here — this is pure Python.
"""

from __future__ import annotations

import math
from typing import Any

# ---------------------------------------------------------------------------
# Colour palette (amCharts 5 hex strings)
# ---------------------------------------------------------------------------

_PALETTE = {
    "primary":   "#3b82f6",   # blue-500
    "success":   "#22c55e",   # green-500
    "warning":   "#f59e0b",   # amber-500
    "danger":    "#ef4444",   # red-500
    "muted":     "#94a3b8",   # slate-400
    "band_1s":   "#bfdbfe",   # blue-200 (±1σ band)
    "band_2s":   "#dbeafe",   # blue-100 (±2σ band)
    "forecast":  "#8b5cf6",   # violet-500
    "positive":  "#10b981",   # emerald-500
    "negative":  "#f43f5e",   # rose-500
}

_ANOMALY_CLASS_COLOURS: dict[str, str] = {
    "spike":       _PALETTE["danger"],
    "drop":        _PALETTE["warning"],
    "drift_up":    _PALETTE["primary"],
    "drift_down":  _PALETTE["muted"],
    "step_change": _PALETTE["forecast"],
}


def _am5_xy_base(title: str, subtitle: str = "") -> dict:
    """Shared amCharts 5 XYChart skeleton."""
    return {
        "type": "XYChart",
        "settings": {
            "panX": True,
            "panY": False,
            "wheelX": "panX",
            "wheelY": "zoomX",
        },
        "title": title,
        "subtitle": subtitle,
        "legend": {"visible": True},
        "cursor": {"behavior": "zoomX"},
        "scrollbarX": {"visible": True},
    }


# ---------------------------------------------------------------------------
# 1. forecast_band
# ---------------------------------------------------------------------------

def forecast_band_spec(
    metric_name: str,
    timestamps: list[str],
    series: list[float],
    projection_json: list[dict],
    trend_direction: str = "flat",
    seasonality_present: bool = False,
    inflection_signal: str | None = None,
) -> dict:
    """
    Historical line + forecast extension + ±1σ (fill) and ±2σ (fill) bands.

    projection_json entries:
      { period_offset, forecast, lower_1sigma, upper_1sigma,
        lower_2sigma, upper_2sigma }
    """
    # Sort historical data ascending so the chart reads left→right chronologically
    # and so timestamps[-1] is always the most recent actual date.
    if timestamps and len(timestamps) == len(series):
        paired = sorted(zip(timestamps, series), key=lambda x: x[0])
        timestamps = [p[0] for p in paired]
        series = [p[1] for p in paired]

    # Build unified data array: historical then forecast
    data: list[dict] = []
    for i, (ts, val) in enumerate(zip(timestamps, series)):
        data.append(
            {
                "period": ts,
                "actual": val,
                "forecast": None,
                "lower_1s": None,
                "upper_1s": None,
                "lower_2s": None,
                "upper_2s": None,
                "is_forecast": False,
            }
        )

    # Compute forecast period labels as real dates when possible,
    # falling back to offset notation only if parsing fails.
    last_ts = timestamps[-1] if timestamps else "T+0"
    try:
        from datetime import datetime, timedelta, timezone
        # Strip trailing timezone info variants and parse
        base_dt = datetime.fromisoformat(last_ts.replace("Z", "+00:00"))
        def _forecast_label(offset: int) -> str:
            dt = base_dt + timedelta(days=offset)
            return dt.isoformat()
    except Exception:
        def _forecast_label(offset: int) -> str:  # type: ignore[misc]
            return f"{last_ts}+{offset}"

    for pt in projection_json:
        offset = int(pt.get("period_offset") or 0)
        data.append(
            {
                "period": _forecast_label(offset),
                "actual": None,
                "forecast": pt["forecast"],
                "lower_1s": pt["lower_1sigma"],
                "upper_1s": pt["upper_1sigma"],
                "lower_2s": pt["lower_2sigma"],
                "upper_2s": pt["upper_2sigma"],
                "is_forecast": True,
            }
        )

    subtitle_parts = [f"Trend: {trend_direction}"]
    if seasonality_present:
        subtitle_parts.append("seasonality detected")
    if inflection_signal:
        subtitle_parts.append(f"signal: {inflection_signal}")

    spec = _am5_xy_base(
        title=f"{metric_name} — Forward Projection",
        subtitle=", ".join(subtitle_parts),
    )
    spec.update(
        {
            "chart_type": "forecast_band",
            "metric_name": metric_name,
            "xAxis": {
                "type": "CategoryAxis",
                "categoryField": "period",
                "label": "Period",
            },
            "yAxis": {
                "type": "ValueAxis",
                "label": metric_name,
            },
            "series": [
                {
                    "id": "actual",
                    "name": "Actual",
                    "type": "LineSeries",
                    "valueXField": "period",
                    "valueYField": "actual",
                    "stroke": _PALETTE["primary"],
                    "strokeWidth": 2,
                    "fill": "none",
                    "bullets": False,
                    "connect": False,
                },
                {
                    "id": "forecast",
                    "name": "Forecast",
                    "type": "LineSeries",
                    "valueXField": "period",
                    "valueYField": "forecast",
                    "stroke": _PALETTE["forecast"],
                    "strokeWidth": 2,
                    "strokeDasharray": [6, 3],
                    "fill": "none",
                    "connect": False,
                },
                {
                    "id": "band_2s",
                    "name": "±2σ band",
                    "type": "LineSeries",
                    "valueXField": "period",
                    "openValueYField": "lower_2s",
                    "valueYField": "upper_2s",
                    "fill": _PALETTE["band_2s"],
                    "fillOpacity": 0.35,
                    "stroke": "none",
                    "connect": False,
                },
                {
                    "id": "band_1s",
                    "name": "±1σ band",
                    "type": "LineSeries",
                    "valueXField": "period",
                    "openValueYField": "lower_1s",
                    "valueYField": "upper_1s",
                    "fill": _PALETTE["band_1s"],
                    "fillOpacity": 0.55,
                    "stroke": "none",
                    "connect": False,
                },
            ],
            "data": data,
        }
    )
    return spec


# ---------------------------------------------------------------------------
# 2. anomaly_timeline
# ---------------------------------------------------------------------------

def anomaly_timeline_spec(
    metric_name: str,
    timestamps: list[str],
    series: list[float],
    anomaly_results: list[dict],
) -> dict:
    """
    Dual-layer chart: background line (actual values) + column overlay for
    anomaly scores, coloured by anomaly class.
    """
    # Map detected_at → anomaly info
    anom_by_period: dict[str, dict] = {
        a["detected_at"]: a for a in anomaly_results
        if a["metric_name"] == metric_name
    }

    data: list[dict] = []
    for ts, val in zip(timestamps, series):
        anom = anom_by_period.get(ts)
        data.append(
            {
                "period": ts,
                "actual": val,
                "anomaly_score": anom["anomaly_score"] if anom else None,
                "anomaly_class": anom["anomaly_class"] if anom else None,
                "z_score": anom["z_score"] if anom else None,
                "columnSettings": (
                    {"fill": _ANOMALY_CLASS_COLOURS.get(anom["anomaly_class"], _PALETTE["muted"])}
                    if anom else None
                ),
            }
        )

    spec = _am5_xy_base(
        title=f"{metric_name} — Anomaly Timeline",
        subtitle=f"{len(anom_by_period)} anomalies detected",
    )
    spec.update(
        {
            "chart_type": "anomaly_timeline",
            "metric_name": metric_name,
            "xAxis": {"type": "CategoryAxis", "categoryField": "period", "label": "Period"},
            "yAxis": {"type": "ValueAxis", "label": metric_name},
            "y2Axis": {
                "type": "ValueAxis",
                "label": "Anomaly Score",
                "min": 0,
                "max": 1,
                "syncWithAxis": False,
                "opposite": True,
            },
            "series": [
                {
                    "id": "actual",
                    "name": metric_name,
                    "type": "LineSeries",
                    "valueXField": "period",
                    "valueYField": "actual",
                    "stroke": _PALETTE["primary"],
                    "strokeWidth": 2,
                    "yAxis": "yAxis",
                },
                {
                    "id": "anomaly_score",
                    "name": "Anomaly Score",
                    "type": "ColumnSeries",
                    "valueXField": "period",
                    "valueYField": "anomaly_score",
                    "yAxis": "y2Axis",
                    "fillField": "columnSettings.fill",
                    "fillOpacity": 0.75,
                    "strokeOpacity": 0,
                    "tooltipText": "{period}: score={anomaly_score} ({anomaly_class})",
                },
            ],
            "annotations": [
                {
                    "type": "HorizontalLine",
                    "axis": "y2Axis",
                    "value": 0.5,
                    "stroke": _PALETTE["danger"],
                    "strokeDasharray": [4, 2],
                    "label": "Threshold",
                }
            ],
            "legend": {
                "visible": True,
                "items": [
                    {"name": cls, "fill": colour}
                    for cls, colour in _ANOMALY_CLASS_COLOURS.items()
                ],
            },
            "data": data,
        }
    )
    return spec


# ---------------------------------------------------------------------------
# 3. correlation_heatmap
# ---------------------------------------------------------------------------

def correlation_heatmap_spec(
    correlation_pairs: list[dict],
    kpi_snapshots: list[dict],
) -> dict:
    """
    amCharts 5 XYChart configured as a heat map.
    Cells are metric_a × metric_b; fill encodes Pearson r.
    """
    # Collect unique metric names
    metrics: list[str] = [s["metric_name"] for s in kpi_snapshots]

    # Build full symmetric matrix, diagonal = 1.0
    r_map: dict[tuple[str, str], float] = {}
    for pair in correlation_pairs:
        r = pair.get("pearson_r") or 0.0
        r_map[(pair["metric_a"], pair["metric_b"])] = r
        r_map[(pair["metric_b"], pair["metric_a"])] = r
    for m in metrics:
        r_map[(m, m)] = 1.0

    data: list[dict] = []
    for ma in metrics:
        for mb in metrics:
            r_val = r_map.get((ma, mb), None)
            data.append(
                {
                    "metric_a": ma,
                    "metric_b": mb,
                    "pearson_r": r_val,
                    "label": f"{r_val:.2f}" if r_val is not None else "–",
                }
            )

    def _fill_for_r(r: float | None) -> str:
        if r is None:
            return _PALETTE["muted"]
        if r >= 0.7:
            return _PALETTE["positive"]
        if r >= 0.4:
            return "#6ee7b7"   # emerald-300
        if r >= 0.2:
            return "#a7f3d0"   # emerald-100
        if r >= -0.2:
            return "#f1f5f9"   # slate-100
        if r >= -0.4:
            return "#fecdd3"   # rose-100
        if r >= -0.7:
            return "#fda4af"   # rose-300
        return _PALETTE["negative"]

    # Enrich data with fill
    for row in data:
        row["fill"] = _fill_for_r(row["pearson_r"])

    spec = _am5_xy_base(
        title="Metric Correlation Heatmap",
        subtitle="Pearson r — darker = stronger correlation",
    )
    spec.update(
        {
            "chart_type": "correlation_heatmap",
            "xAxis": {
                "type": "CategoryAxis",
                "categoryField": "metric_b",
                "label": "",
                "labels": {"rotation": -45, "truncate": 18},
            },
            "yAxis": {
                "type": "CategoryAxis",
                "categoryField": "metric_a",
                "label": "",
            },
            "series": [
                {
                    "id": "heatmap",
                    "name": "Pearson r",
                    "type": "ColumnSeries",
                    "xField": "metric_b",
                    "yField": "metric_a",
                    "valueField": "pearson_r",
                    "fillField": "fill",
                    "fillOpacity": 1.0,
                    "strokeWidth": 1,
                    "stroke": "#ffffff",
                    "labelField": "label",
                    "labelFontSize": 11,
                    "tooltipText": "{metric_a} × {metric_b}: r = {pearson_r}",
                }
            ],
            "colorScale": {
                "min": -1.0,
                "max": 1.0,
                "minColor": _PALETTE["negative"],
                "midColor": "#f8fafc",
                "maxColor": _PALETTE["positive"],
            },
            "metrics": metrics,
            "data": data,
        }
    )
    return spec


# ---------------------------------------------------------------------------
# 4. scatter_regression
# ---------------------------------------------------------------------------

def scatter_regression_spec(
    pair: dict,
    snap_a: dict,
    snap_b: dict,
) -> dict:
    """
    Scatter plot of metric_a vs metric_b with an OLS regression line overlay.
    """
    import numpy as np

    metric_a = pair["metric_a"]
    metric_b = pair["metric_b"]
    n = min(len(snap_a["series"]), len(snap_b["series"]))
    arr_a = snap_a["series"][:n]
    arr_b = snap_b["series"][:n]
    ts = snap_a["timestamps"][:n]

    # OLS regression line
    x = np.array(arr_a, dtype=float)
    y = np.array(arr_b, dtype=float)
    try:
        coeffs = np.polyfit(x, y, 1)
        x_min, x_max = float(x.min()), float(x.max())
        reg_data = [
            {"rx": x_min, "ry": round(float(np.polyval(coeffs, x_min)), 4)},
            {"rx": x_max, "ry": round(float(np.polyval(coeffs, x_max)), 4)},
        ]
    except Exception:
        reg_data = []

    scatter_data = [
        {
            "x": round(a, 4),
            "y": round(b, 4),
            "period": t,
            "tooltipText": f"{t}: {metric_a}={a:.2f}, {metric_b}={b:.2f}",
        }
        for a, b, t in zip(arr_a, arr_b, ts)
    ]

    r = pair.get("pearson_r") or 0.0
    lag = pair.get("best_lag", 0)
    direction = pair.get("lag_direction", "concurrent")

    spec = _am5_xy_base(
        title=f"{metric_a} vs {metric_b}",
        subtitle=(
            f"Pearson r = {r:.2f} | lag = {lag} periods ({direction}) | "
            f"{pair.get('strength_label', '')} {pair.get('direction_label', '')} correlation"
        ),
    )
    spec.update(
        {
            "chart_type": "scatter_regression",
            "metric_a": metric_a,
            "metric_b": metric_b,
            "xAxis": {
                "type": "ValueAxis",
                "label": metric_a,
            },
            "yAxis": {
                "type": "ValueAxis",
                "label": metric_b,
            },
            "series": [
                {
                    "id": "scatter",
                    "name": "Observations",
                    "type": "LineSeries",
                    "valueXField": "x",
                    "valueYField": "y",
                    "connect": False,
                    "fill": _PALETTE["primary"],
                    "stroke": "none",
                    "bullets": {
                        "type": "Circle",
                        "radius": 5,
                        "fill": _PALETTE["primary"],
                        "fillOpacity": 0.7,
                    },
                    "tooltipTextKey": "tooltipText",
                },
                {
                    "id": "regression",
                    "name": "Regression Line",
                    "type": "LineSeries",
                    "valueXField": "rx",
                    "valueYField": "ry",
                    "stroke": _PALETTE["danger"],
                    "strokeWidth": 2,
                    "strokeDasharray": [6, 3],
                    "fill": "none",
                    "bullets": False,
                },
            ],
            "scatter_data": scatter_data,
            "regression_data": reg_data,
            # Front-end merges scatter_data + regression_data into two series
            "data": scatter_data,
            "regression_series_data": reg_data,
        }
    )
    return spec


# ---------------------------------------------------------------------------
# 5. rolling_correlation
# ---------------------------------------------------------------------------

def rolling_correlation_spec(
    pair: dict,
) -> dict:
    """
    Line chart of the rolling Pearson-r array over time for a metric pair.
    """
    rolling: list[float] = pair.get("rolling_r_json") or []
    metric_a = pair["metric_a"]
    metric_b = pair["metric_b"]

    data = [
        {
            "index": i + 1,
            "rolling_r": round(r, 4),
            "fill": _PALETTE["positive"] if r >= 0 else _PALETTE["negative"],
        }
        for i, r in enumerate(rolling)
    ]

    spec = _am5_xy_base(
        title=f"Rolling Correlation: {metric_a} × {metric_b}",
        subtitle=(
            f"Overall Pearson r = {pair.get('pearson_r', 'n/a')} | "
            f"stable = {pair.get('is_stable', True)}"
        ),
    )
    spec.update(
        {
            "chart_type": "rolling_correlation",
            "metric_a": metric_a,
            "metric_b": metric_b,
            "xAxis": {
                "type": "ValueAxis",
                "label": "Window",
            },
            "yAxis": {
                "type": "ValueAxis",
                "label": "Pearson r",
                "min": -1.0,
                "max": 1.0,
            },
            "series": [
                {
                    "id": "rolling_r",
                    "name": "Rolling r",
                    "type": "LineSeries",
                    "valueXField": "index",
                    "valueYField": "rolling_r",
                    "stroke": _PALETTE["primary"],
                    "strokeWidth": 2,
                    "fill": _PALETTE["band_1s"],
                    "fillOpacity": 0.25,
                    "bullets": {
                        "type": "Circle",
                        "radius": 4,
                        "fill": _PALETTE["primary"],
                    },
                    "tooltipText": "Window {index}: r = {rolling_r}",
                }
            ],
            "annotations": [
                {
                    "type": "HorizontalLine",
                    "value": 0,
                    "stroke": _PALETTE["muted"],
                    "strokeDasharray": [4, 2],
                },
                {
                    "type": "HorizontalLine",
                    "value": 0.4,
                    "stroke": _PALETTE["positive"],
                    "strokeDasharray": [3, 3],
                    "label": "+0.4",
                },
                {
                    "type": "HorizontalLine",
                    "value": -0.4,
                    "stroke": _PALETTE["negative"],
                    "strokeDasharray": [3, 3],
                    "label": "−0.4",
                },
            ],
            "data": data,
        }
    )
    return spec


# ---------------------------------------------------------------------------
# 6. anomaly_density
# ---------------------------------------------------------------------------

def anomaly_density_spec(
    anomaly_results: list[dict],
    metric_name: str | None = None,
) -> dict:
    """
    Histogram of anomaly scores (bucketed 0.0–1.0 in 0.1 steps),
    optionally filtered to a single metric.
    """
    filtered = (
        [a for a in anomaly_results if a["metric_name"] == metric_name]
        if metric_name
        else anomaly_results
    )

    # Build 10 buckets: [0.0, 0.1), [0.1, 0.2), ... [0.9, 1.0]
    buckets: dict[str, dict[str, Any]] = {}
    for i in range(10):
        lo = round(i * 0.1, 1)
        hi = round((i + 1) * 0.1, 1)
        label = f"{lo:.1f}–{hi:.1f}"
        buckets[label] = {"range": label, "lo": lo, "hi": hi, "count": 0, "classes": {}}

    for anom in filtered:
        score = anom.get("anomaly_score") or 0.0
        bucket_idx = min(int(score * 10), 9)
        label = list(buckets.keys())[bucket_idx]
        buckets[label]["count"] += 1
        cls = anom.get("anomaly_class", "unknown")
        buckets[label]["classes"][cls] = buckets[label]["classes"].get(cls, 0) + 1

    data = list(buckets.values())
    # Enrich fill: darker for higher buckets
    severity_fills = [
        "#f0fdf4", "#dcfce7", "#bbf7d0", "#86efac",  # 0.0–0.4 greens
        "#fef9c3", "#fde68a",                          # 0.4–0.6 yellows
        "#fed7aa", "#fca5a5", "#f87171", "#ef4444",    # 0.6–1.0 reds
    ]
    for i, row in enumerate(data):
        row["fill"] = severity_fills[i] if i < len(severity_fills) else _PALETTE["danger"]
        row["dominant_class"] = (
            max(row["classes"], key=row["classes"].get)
            if row["classes"] else "none"
        )

    title = (
        f"Anomaly Score Distribution — {metric_name}"
        if metric_name
        else "Anomaly Score Distribution (all metrics)"
    )

    spec = _am5_xy_base(title=title, subtitle=f"{len(filtered)} anomalies")
    spec.update(
        {
            "chart_type": "anomaly_density",
            "metric_name": metric_name,
            "xAxis": {
                "type": "CategoryAxis",
                "categoryField": "range",
                "label": "Score Range",
            },
            "yAxis": {
                "type": "ValueAxis",
                "label": "Count",
                "min": 0,
            },
            "series": [
                {
                    "id": "density",
                    "name": "Anomaly Count",
                    "type": "ColumnSeries",
                    "valueXField": "range",
                    "valueYField": "count",
                    "fillField": "fill",
                    "fillOpacity": 0.85,
                    "strokeOpacity": 0,
                    "cornerRadiusTL": 4,
                    "cornerRadiusTR": 4,
                    "tooltipText": "{range}: {count} anomalies\nDominant class: {dominant_class}",
                }
            ],
            "data": data,
        }
    )
    return spec


# ---------------------------------------------------------------------------
# Main: generate all chart specs for a correlation run
# ---------------------------------------------------------------------------

def generate_correlation_charts(
    correlation_run_id: str,
    kpi_snapshots: list[dict],
    anomaly_results: list[dict],
    correlation_pairs: list[dict],
    forward_projections: list[dict],
    max_scatter_pairs: int = 5,
) -> list[dict]:
    """
    Generate all chart specs for a completed correlation intelligence run.

    Returns a flat list of chart spec dicts, each including:
      { "chart_type": str, "metric_name": str | None, "pair_id": str | None,
        "spec": dict }

    Chart types produced:
      - One forecast_band per metric (forward_projections)
      - One anomaly_timeline per metric that has anomalies
      - One correlation_heatmap (if ≥2 pairs)
      - Up to max_scatter_pairs scatter_regression specs (strongest pairs)
      - Up to max_scatter_pairs rolling_correlation specs
      - One anomaly_density across all metrics
      - One anomaly_density per metric that has ≥2 anomalies
    """
    charts: list[dict] = []

    # Snap lookup by metric_name
    snap_by_metric = {s["metric_name"]: s for s in kpi_snapshots}

    # --- Forecast band: one per metric ---
    for proj in forward_projections:
        metric = proj["metric_name"]
        snap = snap_by_metric.get(metric)
        if not snap:
            continue
        spec = forecast_band_spec(
            metric_name=metric,
            timestamps=snap["timestamps"],
            series=snap["series"],
            projection_json=proj["projection_json"],
            trend_direction=proj.get("trend_direction", "flat"),
            seasonality_present=proj.get("seasonality_present", False),
            inflection_signal=proj.get("inflection_signal"),
        )
        # Attach chart_spec back to projection for storage
        proj["chart_spec"] = spec
        charts.append(
            {
                "chart_type": "forecast_band",
                "metric_name": metric,
                "pair_id": None,
                "correlation_run_id": correlation_run_id,
                "spec": spec,
            }
        )

    # --- Anomaly timeline: one per metric with anomalies ---
    metrics_with_anomalies = {a["metric_name"] for a in anomaly_results}
    for metric in metrics_with_anomalies:
        snap = snap_by_metric.get(metric)
        if not snap:
            continue
        metric_anoms = [a for a in anomaly_results if a["metric_name"] == metric]
        spec = anomaly_timeline_spec(
            metric_name=metric,
            timestamps=snap["timestamps"],
            series=snap["series"],
            anomaly_results=metric_anoms,
        )
        charts.append(
            {
                "chart_type": "anomaly_timeline",
                "metric_name": metric,
                "pair_id": None,
                "correlation_run_id": correlation_run_id,
                "spec": spec,
            }
        )

    # --- Correlation heatmap: one for the whole run ---
    if len(correlation_pairs) >= 2:
        spec = correlation_heatmap_spec(correlation_pairs, kpi_snapshots)
        charts.append(
            {
                "chart_type": "correlation_heatmap",
                "metric_name": None,
                "pair_id": None,
                "correlation_run_id": correlation_run_id,
                "spec": spec,
            }
        )

    # --- Scatter + rolling correlation: top N pairs by |pearson_r| ---
    sorted_pairs = sorted(
        correlation_pairs,
        key=lambda p: abs(p.get("pearson_r") or 0.0),
        reverse=True,
    )[:max_scatter_pairs]

    for pair in sorted_pairs:
        snap_a = snap_by_metric.get(pair["metric_a"])
        snap_b = snap_by_metric.get(pair["metric_b"])

        if snap_a and snap_b:
            scatter_spec = scatter_regression_spec(pair, snap_a, snap_b)
            charts.append(
                {
                    "chart_type": "scatter_regression",
                    "metric_name": None,
                    "pair_id": pair["pair_id"],
                    "correlation_run_id": correlation_run_id,
                    "spec": scatter_spec,
                }
            )

        if pair.get("rolling_r_json"):
            rolling_spec = rolling_correlation_spec(pair)
            charts.append(
                {
                    "chart_type": "rolling_correlation",
                    "metric_name": None,
                    "pair_id": pair["pair_id"],
                    "correlation_run_id": correlation_run_id,
                    "spec": rolling_spec,
                }
            )

    # --- Anomaly density: all-metrics summary ---
    if anomaly_results:
        density_all = anomaly_density_spec(anomaly_results, metric_name=None)
        charts.append(
            {
                "chart_type": "anomaly_density",
                "metric_name": None,
                "pair_id": None,
                "correlation_run_id": correlation_run_id,
                "spec": density_all,
            }
        )

        # Per-metric density for metrics with enough anomalies
        per_metric_counts: dict[str, int] = {}
        for a in anomaly_results:
            per_metric_counts[a["metric_name"]] = per_metric_counts.get(a["metric_name"], 0) + 1

        for metric, count in per_metric_counts.items():
            if count >= 2:
                density_spec = anomaly_density_spec(anomaly_results, metric_name=metric)
                charts.append(
                    {
                        "chart_type": "anomaly_density",
                        "metric_name": metric,
                        "pair_id": None,
                        "correlation_run_id": correlation_run_id,
                        "spec": density_spec,
                    }
                )

    return charts