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
from datetime import datetime, timedelta, timezone
from typing import Any


def _to_ms_epoch(ts: Any) -> int | None:
    """Convert an ISO date/datetime string to milliseconds since epoch for DateAxis."""
    if ts is None:
        return None
    if isinstance(ts, (int, float)):
        return int(ts)
    text = str(ts).strip()
    if not text:
        return None
    for candidate in (
        text.replace("Z", "+00:00"),
        f"{text}-01" if len(text) == 7 else None,   # "2025-12" → "2025-12-01"
        f"{text}-01-01" if len(text) == 4 else None, # "2025" → "2025-01-01"
    ):
        if not candidate:
            continue
        try:
            dt = datetime.fromisoformat(candidate)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.timestamp() * 1000)
        except ValueError:
            continue
    return None


def _infer_time_grain(timestamps: list[str]) -> str:
    parsed: list[datetime] = []
    for ts in timestamps:
        try:
            dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            parsed.append(dt)
        except ValueError:
            continue
    if len(parsed) < 2:
        return "day"
    parsed = sorted(parsed)
    deltas = [(parsed[i] - parsed[i - 1]).days for i in range(1, len(parsed))]
    if not deltas:
        return "day"
    median_delta = sorted(deltas)[len(deltas) // 2]
    if median_delta >= 365:
        return "year"
    if median_delta >= 80:
        return "quarter"
    if median_delta >= 25:
        return "month"
    if median_delta >= 6:
        return "week"
    return "day"


def _base_interval_for_grain(grain: str) -> dict[str, Any]:
    return {
        "day": {"timeUnit": "day", "count": 1},
        "week": {"timeUnit": "day", "count": 7},
        "month": {"timeUnit": "month", "count": 1},
        "quarter": {"timeUnit": "month", "count": 3},
        "year": {"timeUnit": "year", "count": 1},
    }.get(grain, {"timeUnit": "day", "count": 1})


def _add_months(dt: datetime, months: int) -> datetime:
    month_index = (dt.month - 1) + months
    year = dt.year + month_index // 12
    month = month_index % 12 + 1
    day = min(dt.day, 28)
    return dt.replace(year=year, month=month, day=day)

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


def _spec_slug(value: str) -> str:
    text = "".join(ch.lower() if ch.isalnum() else "_" for ch in str(value or ""))
    while "__" in text:
        text = text.replace("__", "_")
    return text.strip("_") or "series"


def _chart_entry(
    *,
    chart_type: str,
    correlation_run_id: str,
    spec: dict,
    metric_name: str | None = None,
    pair_id: str | None = None,
) -> dict:
    return {
        "chart_type": chart_type,
        "metric_name": metric_name,
        "pair_id": pair_id,
        "correlation_run_id": correlation_run_id,
        "spec": spec,
        "data": spec.get("data") or [],
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
    # period_ms = ms-epoch timestamp used by DateAxis (no categorical axis on time data)
    data: list[dict] = []
    for ts, val in zip(timestamps, series):
        data.append(
            {
                "period": ts,
                "period_ms": _to_ms_epoch(ts),
                "actual": val,
                "forecast": None,
                "lower_1s": None,
                "upper_1s": None,
                "lower_2s": None,
                "upper_2s": None,
                "is_forecast": False,
            }
        )

    grain = _infer_time_grain(timestamps)
    base_interval = _base_interval_for_grain(grain)

    # Compute forecast period labels as real dates, preserving the historical grain.
    last_ts = timestamps[-1] if timestamps else "T+0"
    try:
        base_dt = datetime.fromisoformat(last_ts.replace("Z", "+00:00"))
        if base_dt.tzinfo is None:
            base_dt = base_dt.replace(tzinfo=timezone.utc)
        def _forecast_label(offset: int) -> str:
            if grain == "year":
                dt = base_dt.replace(year=base_dt.year + offset)
            elif grain == "quarter":
                dt = _add_months(base_dt, offset * 3)
            elif grain == "month":
                dt = _add_months(base_dt, offset)
            elif grain == "week":
                dt = base_dt + timedelta(days=offset * 7)
            else:
                dt = base_dt + timedelta(days=offset)
            return dt.isoformat()
    except Exception:
        base_dt = None
        def _forecast_label(offset: int) -> str:  # type: ignore[misc]
            return f"{last_ts}+{offset}"

    for pt in projection_json:
        offset = int(pt.get("period_offset") or 0)
        label = _forecast_label(offset)
        data.append(
            {
                "period": label,
                "period_ms": _to_ms_epoch(label),
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
                "type": "DateAxis",
                "dateField": "period_ms",
                "label": "Period",
                "baseInterval": base_interval,
                "tooltipDateFormat": "MMM yyyy",
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
                    "valueXField": "period_ms",
                    "valueYField": "actual",
                    "stroke": _PALETTE["primary"],
                    "strokeWidth": 2,
                    "fill": "none",
                    "bullets": False,
                    "connect": False,
                    "tooltipText": "{period}: {actual}",
                },
                {
                    "id": "forecast",
                    "name": "Forecast",
                    "type": "LineSeries",
                    "valueXField": "period_ms",
                    "valueYField": "forecast",
                    "stroke": _PALETTE["forecast"],
                    "strokeWidth": 2,
                    "strokeDasharray": [6, 3],
                    "fill": "none",
                    "connect": False,
                    "tooltipText": "{period}: {forecast} (forecast)",
                },
                {
                    "id": "band_2s",
                    "name": "±2σ band",
                    "type": "LineSeries",
                    "valueXField": "period_ms",
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
                    "valueXField": "period_ms",
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
                "period_ms": _to_ms_epoch(ts),
                "actual": val,
                "anomaly_score": anom["anomaly_score"] if anom else None,
                "anomaly_class": anom["anomaly_class"] if anom else None,
                "z_score": anom["z_score"] if anom else None,
                "anomaly_fill": (
                    _ANOMALY_CLASS_COLOURS.get(anom["anomaly_class"], _PALETTE["muted"])
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
            "xAxis": {
                "type": "DateAxis",
                "dateField": "period_ms",
                "label": "Period",
                "baseInterval": {"timeUnit": "month", "count": 1},
                "tooltipDateFormat": "MMM yyyy",
            },
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
                    "valueXField": "period_ms",
                    "valueYField": "actual",
                    "stroke": _PALETTE["primary"],
                    "strokeWidth": 2,
                    "yAxis": "yAxis",
                    "tooltipText": "{period}: {actual}",
                },
                {
                    "id": "anomaly_score",
                    "name": "Anomaly Score",
                    "type": "ColumnSeries",
                    "valueXField": "period_ms",
                    "valueYField": "anomaly_score",
                    "yAxis": "y2Axis",
                    "fillField": "anomaly_fill",
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
    if rolling:
        rolling_range = max(rolling) - min(rolling)
        derived_is_stable = rolling_range < 0.3
    else:
        derived_is_stable = bool(pair.get("is_stable", True))

    spec = _am5_xy_base(
        title=f"Rolling Correlation: {metric_a} × {metric_b}",
        subtitle=(
            f"Overall Pearson r = {pair.get('pearson_r', 'n/a')} | "
            f"stable = {derived_is_stable}"
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


def category_trend_grouped_spec(
    *,
    measure_name: str,
    table_name: str,
    category_column: str,
    snapshots: list[dict],
) -> dict:
    data_by_period: dict[str, dict[str, Any]] = {}
    series_defs: list[dict[str, Any]] = []
    palette = [
        _PALETTE["primary"],
        _PALETTE["success"],
        _PALETTE["forecast"],
        _PALETTE["warning"],
        _PALETTE["danger"],
        _PALETTE["muted"],
    ]

    ordered_snaps = sorted(
        snapshots,
        key=lambda s: str((s.get("query_payload") or {}).get("category_value") or s.get("metric_name") or ""),
    )
    for idx, snap in enumerate(ordered_snaps):
        qp = snap.get("query_payload") or {}
        category_value = str(qp.get("category_value") or f"Category {idx + 1}")
        field = _spec_slug(category_value)
        series_defs.append(
            {
                "id": field,
                "name": category_value,
                "type": "LineSeries",
                "valueXField": "period",
                "valueYField": field,
                "stroke": palette[idx % len(palette)],
                "strokeWidth": 2,
                "fill": "none",
                "bullets": {"type": "Circle", "radius": 3, "fill": palette[idx % len(palette)]},
                "connect": False,
            }
        )
        for period, value in zip(snap.get("timestamps") or [], snap.get("series") or []):
            key = str(period)
            row = data_by_period.setdefault(key, {"period": key, "period_ms": _to_ms_epoch(key)})
            row[field] = value

    data = [data_by_period[k] for k in sorted(data_by_period.keys())]
    # Update series to use period_ms for DateAxis
    for s in series_defs:
        s["valueXField"] = "period_ms"
    spec = _am5_xy_base(
        title=f"{measure_name} by {category_column} — Category Trends",
        subtitle=f"Temporal category comparison from {table_name}",
    )
    spec.update(
        {
            "chart_type": "category_trend_grouped",
            "metric_name": measure_name,
            "xAxis": {
                "type": "DateAxis",
                "dateField": "period_ms",
                "label": "Period",
                "baseInterval": {"timeUnit": "month", "count": 1},
                "tooltipDateFormat": "MMM yyyy",
            },
            "yAxis": {"type": "ValueAxis", "label": measure_name},
            "series": series_defs,
            "data": data,
        }
    )
    return spec


def category_forecast_stacked_bar_spec(
    *,
    measure_name: str,
    table_name: str,
    category_column: str,
    snapshots: list[dict],
    forward_projections: list[dict],
) -> dict | None:
    projection_by_metric = {p.get("metric_name"): p for p in forward_projections if p.get("metric_name")}
    palette = [
        _PALETTE["primary"],
        _PALETTE["success"],
        _PALETTE["forecast"],
        _PALETTE["warning"],
        _PALETTE["danger"],
        _PALETTE["muted"],
    ]
    data_by_period: dict[str, dict[str, Any]] = {}
    series_defs: list[dict[str, Any]] = []
    included = 0

    ordered_snaps = sorted(
        snapshots,
        key=lambda s: str((s.get("query_payload") or {}).get("category_value") or s.get("metric_name") or ""),
    )
    for idx, snap in enumerate(ordered_snaps):
        qp = snap.get("query_payload") or {}
        metric_name = snap.get("metric_name")
        proj = projection_by_metric.get(metric_name)
        if not proj:
            continue
        category_value = str(qp.get("category_value") or f"Category {idx + 1}")
        field = _spec_slug(category_value)
        series_defs.append(
            {
                "id": field,
                "name": category_value,
                "type": "ColumnSeries",
                "valueXField": "period",
                "valueYField": field,
                "stacked": True,
                "fill": palette[idx % len(palette)],
                "stroke": "#ffffff",
                "strokeWidth": 1,
            }
        )
        for point in (proj.get("projection_json") or []):
            period_offset = int(point.get("period_offset") or 0)
            period = f"Forecast +{period_offset}"
            row = data_by_period.setdefault(period, {"period": period, "period_offset": period_offset})
            row[field] = point.get("forecast")
        included += 1

    if included < 2 or not data_by_period:
        return None

    data = sorted(data_by_period.values(), key=lambda row: int(row.get("period_offset") or 0))
    spec = _am5_xy_base(
        title=f"{measure_name} by {category_column} — Stacked Forecast",
        subtitle=f"Forecast contribution by category from {table_name}",
    )
    spec.update(
        {
            "chart_type": "category_forecast_stacked_bar",
            "metric_name": measure_name,
            "xAxis": {"type": "CategoryAxis", "categoryField": "period", "label": "Forecast Period"},
            "yAxis": {"type": "ValueAxis", "label": measure_name},
            "series": series_defs,
            "data": data,
        }
    )
    return spec


def temporal_eligibility_warning_card_spec(
    *,
    snapshot_eligibility_summary: dict[str, Any],
    data_quality_warnings: list[dict] | None = None,
) -> dict | None:
    excluded_count = int(snapshot_eligibility_summary.get("excluded_chart_count") or 0)
    if excluded_count <= 0 and not (data_quality_warnings or []):
        return None
    excluded_by_reason = snapshot_eligibility_summary.get("excluded_by_reason") or {}
    data = [
        {"reason": str(reason), "count": int(count)}
        for reason, count in sorted(excluded_by_reason.items(), key=lambda item: (-int(item[1]), str(item[0])))
    ]
    warning_lines = [str(item.get("message") or "").strip() for item in (data_quality_warnings or []) if str(item.get("message") or "").strip()]
    return {
        "type": "StatCard",
        "chart_type": "temporal_eligibility_warning_card",
        "title": "Correlation Input Warnings",
        "subtitle": f"Excluded snapshots: {excluded_count}",
        "body": warning_lines[:3],
        "data": data,
        "summary": snapshot_eligibility_summary,
    }


def metric_overlap_matrix_spec(
    correlation_pairs: list[dict],
) -> dict | None:
    overlap_pairs = [
        pair for pair in correlation_pairs
        if abs(pair.get("pearson_r") or 0.0) >= 0.9
    ]
    if not overlap_pairs:
        return None
    metrics = sorted(
        {
            str(pair.get("metric_a") or "")
            for pair in overlap_pairs
        } | {
            str(pair.get("metric_b") or "")
            for pair in overlap_pairs
        }
    )
    data: list[dict[str, Any]] = []
    for pair in overlap_pairs:
        r_value = float(pair.get("pearson_r") or 0.0)
        data.append(
            {
                "metric_a": pair.get("metric_a"),
                "metric_b": pair.get("metric_b"),
                "pearson_r": round(r_value, 4),
                "label": f"{r_value:.2f}",
                "fill": _PALETTE["danger"] if abs(r_value) >= 0.98 else _PALETTE["warning"],
            }
        )
    spec = _am5_xy_base(
        title="Metric Overlap Matrix",
        subtitle="Near-duplicate metric pairs by absolute Pearson correlation",
    )
    spec.update(
        {
            "chart_type": "metric_overlap_matrix",
            "xAxis": {"type": "CategoryAxis", "categoryField": "metric_b", "label": ""},
            "yAxis": {"type": "CategoryAxis", "categoryField": "metric_a", "label": ""},
            "series": [
                {
                    "id": "overlap",
                    "name": "Overlap",
                    "type": "ColumnSeries",
                    "xField": "metric_b",
                    "yField": "metric_a",
                    "valueField": "pearson_r",
                    "fillField": "fill",
                    "labelField": "label",
                    "tooltipText": "{metric_a} × {metric_b}: r = {pearson_r}",
                }
            ],
            "metrics": metrics,
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
    snapshot_eligibility_summary: dict[str, Any] | None = None,
    data_quality_warnings: list[dict] | None = None,
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
    category_groups: dict[tuple[str, str, str], list[dict]] = {}
    for snap in kpi_snapshots:
        qp = snap.get("query_payload") or {}
        if str(qp.get("source_kind") or snap.get("source_kind") or "") != "fact_category_metric":
            continue
        table_name = str(qp.get("table") or "").strip()
        category_column = str(qp.get("category_column") or "").strip()
        metric_name = str(snap.get("metric_name") or "")
        measure_name = metric_name
        prefix = f"_by_month_{table_name}_{category_column}_"
        if table_name and category_column and prefix in metric_name:
            measure_name = metric_name.split(prefix, 1)[0]
        key = (table_name, measure_name, category_column)
        category_groups.setdefault(key, []).append(snap)

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
        charts.append(_chart_entry(chart_type="forecast_band", metric_name=metric, pair_id=None, correlation_run_id=correlation_run_id, spec=spec))

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
        charts.append(_chart_entry(chart_type="anomaly_timeline", metric_name=metric, pair_id=None, correlation_run_id=correlation_run_id, spec=spec))

    # --- Correlation heatmap: one for the whole run ---
    if len(correlation_pairs) >= 2:
        spec = correlation_heatmap_spec(correlation_pairs, kpi_snapshots)
        charts.append(_chart_entry(chart_type="correlation_heatmap", metric_name=None, pair_id=None, correlation_run_id=correlation_run_id, spec=spec))
    overlap_spec = metric_overlap_matrix_spec(correlation_pairs)
    if overlap_spec:
        charts.append(_chart_entry(chart_type="metric_overlap_matrix", metric_name=None, pair_id=None, correlation_run_id=correlation_run_id, spec=overlap_spec))
    warning_spec = temporal_eligibility_warning_card_spec(
        snapshot_eligibility_summary=snapshot_eligibility_summary or {},
        data_quality_warnings=data_quality_warnings or [],
    )
    if warning_spec:
        charts.append(_chart_entry(chart_type="temporal_eligibility_warning_card", metric_name=None, pair_id=None, correlation_run_id=correlation_run_id, spec=warning_spec))

    # --- Category-temporal charts from fact-native series ---
    for (table_name, measure_name, category_column), group_snaps in category_groups.items():
        if len(group_snaps) < 2:
            continue
        trend_spec = category_trend_grouped_spec(
            measure_name=measure_name,
            table_name=table_name,
            category_column=category_column,
            snapshots=group_snaps,
        )
        charts.append(_chart_entry(chart_type="category_trend_grouped", metric_name=measure_name, pair_id=None, correlation_run_id=correlation_run_id, spec=trend_spec))
        forecast_spec = category_forecast_stacked_bar_spec(
            measure_name=measure_name,
            table_name=table_name,
            category_column=category_column,
            snapshots=group_snaps,
            forward_projections=forward_projections,
        )
        if forecast_spec:
            charts.append(_chart_entry(chart_type="category_forecast_stacked_bar", metric_name=measure_name, pair_id=None, correlation_run_id=correlation_run_id, spec=forecast_spec))

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
            charts.append(_chart_entry(chart_type="scatter_regression", metric_name=None, pair_id=pair["pair_id"], correlation_run_id=correlation_run_id, spec=scatter_spec))

        if pair.get("rolling_r_json"):
            rolling_spec = rolling_correlation_spec(pair)
            charts.append(_chart_entry(chart_type="rolling_correlation", metric_name=None, pair_id=pair["pair_id"], correlation_run_id=correlation_run_id, spec=rolling_spec))

    # --- Anomaly density: all-metrics summary ---
    if anomaly_results:
        density_all = anomaly_density_spec(anomaly_results, metric_name=None)
        charts.append(_chart_entry(chart_type="anomaly_density", metric_name=None, pair_id=None, correlation_run_id=correlation_run_id, spec=density_all))

        # Per-metric density for metrics with enough anomalies
        per_metric_counts: dict[str, int] = {}
        for a in anomaly_results:
            per_metric_counts[a["metric_name"]] = per_metric_counts.get(a["metric_name"], 0) + 1

        for metric, count in per_metric_counts.items():
            if count >= 2:
                density_spec = anomaly_density_spec(anomaly_results, metric_name=metric)
                charts.append(_chart_entry(chart_type="anomaly_density", metric_name=metric, pair_id=None, correlation_run_id=correlation_run_id, spec=density_spec))

    return charts
