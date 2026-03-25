"""
Phase 43 — Statistical Correlation, Anomaly, and Forward Pattern Agent.

This module is the pure statistical computation layer. It loads KPI snapshots
from quantyx_chart_requests (using rows_json + run_id scoping), runs anomaly
detection, cross-metric correlation, investigation threading, and forward
projections, then persists results via correlation_store.

No table-specific SQL is written here — all data comes from rows_json already
stored during the agentic deployment run.
"""

from __future__ import annotations

import logging
import math
import re
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

import numpy as np
import psycopg2
from psycopg2.extras import RealDictCursor

from services.ai.config import Settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PERIOD_KEY_WORDS = frozenset(
    {
        "period", "date", "month", "week", "year", "quarter", "day",
        "time", "timestamp", "dt", "ym", "yearmonth", "fiscal",
        "created", "updated", "at",
    }
)

_ISO_DATE_RE = re.compile(
    r"^\d{4}-\d{2}(-\d{2})?( \d{2}:\d{2}(:\d{2})?)?$"
)

_ANOMALY_ZSCORE_THRESHOLD = 2.5
_ANOMALY_IQR_MULTIPLIER = 1.5
_MIN_SERIES_LEN = 4          # below this, skip anomaly / correlation
_CORRELATION_MIN_R = 0.20    # prune weak pairs
_INVESTIGATION_MIN_CONF = 0.35


# ---------------------------------------------------------------------------
# Data loading helpers
# ---------------------------------------------------------------------------

def _detect_period_column(row: dict) -> str | None:
    """
    Auto-detect the period/date column in a single data row.

    Strategy:
    1. Prefer keys whose lower-case name contains a known time-dimension word.
    2. Among those, prefer keys whose value matches an ISO date pattern.
    3. Fall back to the first key whose *value* matches the ISO pattern.
    4. Return None if no period column can be found.
    """
    if not row:
        return None

    candidates_by_name: list[str] = []
    candidates_by_value: list[str] = []

    for key, value in row.items():
        lower_key = key.lower().replace("_", " ")
        if any(word in lower_key for word in _PERIOD_KEY_WORDS):
            candidates_by_name.append(key)
        if isinstance(value, str) and _ISO_DATE_RE.match(value.strip()):
            candidates_by_value.append(key)

    # Intersection first (name match + ISO value)
    for key in candidates_by_name:
        if key in candidates_by_value:
            return key

    if candidates_by_name:
        return candidates_by_name[0]
    if candidates_by_value:
        return candidates_by_value[0]
    return None


def _coerce_numeric(value: Any) -> float | None:
    """Safely cast a value to float, returning None on failure."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def load_kpi_snapshots(
    settings: Settings,
    tenant_id: str,
    domain_id: str,
    run_id: str | None = None,
) -> list[dict]:
    """
    Load KPI snapshots from quantyx_chart_requests.

    Scoping strategy:
    - Primary: WHERE run_id = %s (exact deployment run)
    - Fallback: WHERE tenant_id = %s AND domain_id = %s (latest 10 charts)

    Returns a list of snapshot dicts, each containing:
      {
        "chart_id": str,
        "question": str,
        "rows_json": list[dict],      # raw data rows
        "query_payload": dict | None,
        "metric_name": str,           # derived from question / query_payload
        "period_col": str | None,
        "value_col": str | None,
        "series": list[float],
        "timestamps": list[str],
      }
    """
    conn = psycopg2.connect(
        host=settings.db_host,
        port=settings.db_port,
        dbname=settings.db_name,
        user=settings.db_user,
        password=settings.db_password,
    )
    rows: list[Any] = []
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if run_id:
                cur.execute(
                    """
                    SELECT chart_id, question, query_payload, rows_json
                      FROM public.quantyx_chart_requests
                     WHERE run_id = %s
                       AND status IN ('done', 'complete', 'success')
                       AND rows_json IS NOT NULL
                     ORDER BY created_at ASC
                    """,
                    [run_id],
                )
                rows = cur.fetchall()

            if not rows:
                # Fallback: latest 10 completed charts for this scope
                cur.execute(
                    """
                    SELECT chart_id, question, query_payload, rows_json
                      FROM public.quantyx_chart_requests
                     WHERE tenant_id = %s
                       AND domain_id  = %s
                       AND status IN ('done', 'complete', 'success')
                       AND rows_json IS NOT NULL
                     ORDER BY created_at DESC
                     LIMIT 10
                    """,
                    [tenant_id, domain_id],
                )
                rows = cur.fetchall()
    except psycopg2.errors.UndefinedTable:
        logger.warning("quantyx_chart_requests table not found — returning empty snapshots")
        return []
    finally:
        conn.close()

    snapshots: list[dict] = []
    for raw in rows:
        rows_json: list[dict] = raw.get("rows_json") or []
        if not rows_json or not isinstance(rows_json, list):
            continue

        first_row = rows_json[0] if rows_json else {}
        period_col = _detect_period_column(first_row)

        # Detect value column: first numeric, non-period column
        value_col: str | None = None
        for key, val in first_row.items():
            if key == period_col:
                continue
            if _coerce_numeric(val) is not None:
                value_col = key
                break

        if value_col is None:
            continue  # no numeric column found — skip

        series: list[float] = []
        timestamps: list[str] = []
        for row in rows_json:
            v = _coerce_numeric(row.get(value_col))
            if v is None:
                continue
            series.append(v)
            ts = str(row.get(period_col, "")) if period_col else str(len(series))
            timestamps.append(ts)

        if len(series) < _MIN_SERIES_LEN:
            continue

        # Derive metric name from question or query_payload
        qp: dict = raw.get("query_payload") or {}
        metric_name: str = (
            qp.get("metric_name")
            or qp.get("metric")
            or (raw.get("question") or value_col or "unknown")
        )

        snapshots.append(
            {
                "chart_id": raw["chart_id"],
                "question": raw.get("question") or "",
                "rows_json": rows_json,
                "query_payload": qp,
                "metric_name": metric_name,
                "period_col": period_col,
                "value_col": value_col,
                "series": series,
                "timestamps": timestamps,
            }
        )

    return snapshots


def extract_dimension_breakdown(
    snapshot: dict,
    anomaly_period: str,
) -> dict | None:
    """
    Derive dimension concentration for an anomaly period from rows_json.

    Looks through all rows for those matching the anomaly_period, then finds
    the non-period, non-numeric column with the highest value concentration.

    Returns {"dimension": str, "value": str, "pct": float} or None.
    """
    rows_json: list[dict] = snapshot.get("rows_json") or []
    period_col: str | None = snapshot.get("period_col")
    value_col: str | None = snapshot.get("value_col")

    if not rows_json or not value_col:
        return None

    # Find rows for this period
    period_rows = [
        r for r in rows_json
        if period_col is None or str(r.get(period_col, "")).startswith(anomaly_period[:7])
    ]
    if not period_rows:
        period_rows = rows_json  # fall back to all rows

    # Find candidate dimension columns (non-period, non-numeric, non-id)
    dim_cols: list[str] = []
    for key, val in (period_rows[0] if period_rows else {}).items():
        if key in (period_col, value_col):
            continue
        if _coerce_numeric(val) is not None:
            continue
        dim_cols.append(key)

    if not dim_cols:
        return None

    best_dim = dim_cols[0]
    dim_col_to_use = best_dim

    # Sum values by dimension value
    totals: dict[str, float] = defaultdict(float)
    grand_total = 0.0
    for row in period_rows:
        v = _coerce_numeric(row.get(value_col, 0)) or 0.0
        dim_val = str(row.get(dim_col_to_use, "unknown"))
        totals[dim_val] += v
        grand_total += v

    if grand_total == 0:
        return None

    top_val = max(totals, key=lambda k: totals[k])
    pct = round(totals[top_val] / grand_total * 100, 1)

    return {
        "dimension": dim_col_to_use,
        "value": top_val,
        "pct": pct,
    }


# ---------------------------------------------------------------------------
# Anomaly detection
# ---------------------------------------------------------------------------

def score_anomalies(
    metric_name: str,
    series: list[float],
    timestamps: list[str],
    dimension_breakdown: dict | None = None,
) -> list[dict]:
    """
    Run Z-score + IQR + CUSUM anomaly detection on a numeric time series.

    Returns a list of AnomalyResult dicts (one per detected point) with keys:
      anomaly_id, metric_name, anomaly_class, anomaly_score, z_score,
      iqr_flag, cusum_signal, detected_at, period_label, baseline_value,
      observed_value, deviation_pct, top_dimension, top_dimension_value,
      dimension_pct, stats_json
    """
    if len(series) < _MIN_SERIES_LEN:
        return []

    arr = np.array(series, dtype=float)
    mean = float(np.mean(arr))
    std = float(np.std(arr, ddof=1)) if len(arr) > 1 else 0.0

    # IQR fences
    q1 = float(np.percentile(arr, 25))
    q3 = float(np.percentile(arr, 75))
    iqr = q3 - q1
    lower_fence = q1 - _ANOMALY_IQR_MULTIPLIER * iqr
    upper_fence = q3 + _ANOMALY_IQR_MULTIPLIER * iqr

    # CUSUM (cumulative sum of deviations from mean)
    cusum_pos = np.zeros(len(arr))
    cusum_neg = np.zeros(len(arr))
    slack = 0.5 * std if std > 0 else 0.01
    for i in range(1, len(arr)):
        cusum_pos[i] = max(0.0, cusum_pos[i - 1] + (arr[i] - mean) - slack)
        cusum_neg[i] = max(0.0, cusum_neg[i - 1] - (arr[i] - mean) - slack)
    cusum_threshold = 4 * std if std > 0 else 1.0

    results: list[dict] = []
    for i, (val, ts) in enumerate(zip(series, timestamps)):
        z = (val - mean) / std if std > 0 else 0.0
        abs_z = abs(z)

        iqr_flag = val < lower_fence or val > upper_fence
        cusum_signal = (cusum_pos[i] > cusum_threshold or cusum_neg[i] > cusum_threshold)

        # Composite anomaly score [0, 1]
        z_component = min(abs_z / (_ANOMALY_ZSCORE_THRESHOLD * 2), 1.0)
        iqr_component = 1.0 if iqr_flag else 0.0
        cusum_component = 1.0 if cusum_signal else 0.0
        anomaly_score = round(
            0.5 * z_component + 0.3 * iqr_component + 0.2 * cusum_component,
            4,
        )

        if anomaly_score < 0.3 and abs_z < _ANOMALY_ZSCORE_THRESHOLD:
            continue  # not anomalous enough

        # Classify anomaly
        if z > _ANOMALY_ZSCORE_THRESHOLD:
            anomaly_class = "spike"
        elif z < -_ANOMALY_ZSCORE_THRESHOLD:
            anomaly_class = "drop"
        elif cusum_signal and cusum_pos[i] > cusum_threshold:
            anomaly_class = "drift_up"
        elif cusum_signal and cusum_neg[i] > cusum_threshold:
            anomaly_class = "drift_down"
        elif iqr_flag:
            anomaly_class = "step_change"
        else:
            anomaly_class = "spike" if z > 0 else "drop"

        deviation_pct: float | None = None
        if mean != 0:
            deviation_pct = round((val - mean) / abs(mean) * 100, 2)

        top_dim = top_dim_val = dim_pct_val = None
        if dimension_breakdown:
            top_dim = dimension_breakdown.get("dimension")
            top_dim_val = dimension_breakdown.get("value")
            dim_pct_val = dimension_breakdown.get("pct")

        results.append(
            {
                "anomaly_id": f"anom_{uuid.uuid4().hex[:12]}",
                "metric_name": metric_name,
                "anomaly_class": anomaly_class,
                "anomaly_score": anomaly_score,
                "z_score": round(z, 4),
                "iqr_flag": iqr_flag,
                "cusum_signal": cusum_signal,
                "detected_at": ts,
                "period_label": ts,
                "baseline_value": round(mean, 6),
                "observed_value": val,
                "deviation_pct": deviation_pct,
                "top_dimension": top_dim,
                "top_dimension_value": top_dim_val,
                "dimension_pct": dim_pct_val,
                "stats_json": {
                    "mean": mean,
                    "std": std,
                    "q1": q1,
                    "q3": q3,
                    "iqr": iqr,
                    "cusum_pos": float(cusum_pos[i]),
                    "cusum_neg": float(cusum_neg[i]),
                    "series_len": len(series),
                },
            }
        )

    return results


# ---------------------------------------------------------------------------
# Correlation analysis
# ---------------------------------------------------------------------------

def lagged_correlation(
    series_a: list[float],
    series_b: list[float],
    max_lag: int = 6,
) -> dict:
    """
    Compute Pearson/Spearman correlations and find the best lag between two series.

    Returns:
      {
        "pearson_r": float | None,
        "spearman_rho": float | None,
        "best_lag": int,
        "lagged_r": float | None,
        "lag_direction": str,   # "a_leads_b" | "b_leads_a" | "concurrent"
        "sample_size": int,
        "p_value": float | None,
      }
    """
    from scipy import stats as scipy_stats

    n = min(len(series_a), len(series_b))
    if n < _MIN_SERIES_LEN:
        return {
            "pearson_r": None, "spearman_rho": None,
            "best_lag": 0, "lagged_r": None,
            "lag_direction": "concurrent", "sample_size": n, "p_value": None,
        }

    a = np.array(series_a[:n], dtype=float)
    b = np.array(series_b[:n], dtype=float)

    # Pearson at lag 0
    pearson_r = p_value = None
    try:
        pr, pv = scipy_stats.pearsonr(a, b)
        pearson_r = round(float(pr), 4)
        p_value = round(float(pv), 6)
    except Exception:
        pass

    # Spearman at lag 0
    spearman_rho = None
    try:
        sr, _ = scipy_stats.spearmanr(a, b)
        spearman_rho = round(float(sr), 4)
    except Exception:
        pass

    # Best lagged correlation
    best_lag = 0
    best_r = pearson_r or 0.0
    for lag in range(1, min(max_lag + 1, n // 2)):
        # A leads B by lag
        try:
            r_ab, _ = scipy_stats.pearsonr(a[:-lag], b[lag:])
            if abs(r_ab) > abs(best_r):
                best_r = round(float(r_ab), 4)
                best_lag = lag
        except Exception:
            pass

        # B leads A by lag
        try:
            r_ba, _ = scipy_stats.pearsonr(b[:-lag], a[lag:])
            if abs(r_ba) > abs(best_r):
                best_r = round(float(r_ba), 4)
                best_lag = -lag  # negative = B leads A
        except Exception:
            pass

    lag_direction = (
        "concurrent" if best_lag == 0
        else "a_leads_b" if best_lag > 0
        else "b_leads_a"
    )

    return {
        "pearson_r": pearson_r,
        "spearman_rho": spearman_rho,
        "best_lag": abs(best_lag),
        "lagged_r": round(best_r, 4) if best_r else None,
        "lag_direction": lag_direction,
        "sample_size": n,
        "p_value": p_value,
    }


def build_correlation_matrix(
    kpi_snapshots: list[dict],
    max_lag: int = 6,
) -> list[dict]:
    """
    Compute pairwise correlations for all KPI snapshot combinations.

    Returns a list of CorrelationPair dicts with keys:
      pair_id, metric_a, metric_b, pearson_r, spearman_rho, best_lag,
      lagged_r, lag_direction, strength_label, direction_label,
      sample_size, p_value, is_stable, rolling_r_json
    """
    pairs: list[dict] = []
    n = len(kpi_snapshots)

    for i in range(n):
        for j in range(i + 1, n):
            snap_a = kpi_snapshots[i]
            snap_b = kpi_snapshots[j]

            result = lagged_correlation(
                snap_a["series"], snap_b["series"], max_lag=max_lag
            )

            r = result.get("pearson_r") or 0.0
            if abs(r) < _CORRELATION_MIN_R:
                continue  # prune weak correlations

            abs_r = abs(r)
            if abs_r >= 0.7:
                strength_label = "strong"
            elif abs_r >= 0.4:
                strength_label = "moderate"
            else:
                strength_label = "weak"

            direction_label = "positive" if r >= 0 else "negative"

            # Rolling correlation stability (window = max 6 points)
            rolling_r_json: list[float] = []
            try:
                series_a = snap_a["series"]
                series_b = snap_b["series"]
                window = max(4, min(6, len(series_a) // 3))
                from scipy import stats as scipy_stats

                for w in range(window, len(series_a)):
                    try:
                        rr, _ = scipy_stats.pearsonr(
                            series_a[w - window: w],
                            series_b[w - window: w],
                        )
                        rolling_r_json.append(round(float(rr), 4))
                    except Exception:
                        rolling_r_json.append(0.0)
            except Exception:
                pass

            # Stability: std of rolling r < 0.25
            is_stable = True
            if rolling_r_json and len(rolling_r_json) >= 3:
                is_stable = float(np.std(rolling_r_json)) < 0.25

            pairs.append(
                {
                    "pair_id": f"pair_{uuid.uuid4().hex[:12]}",
                    "metric_a": snap_a["metric_name"],
                    "metric_b": snap_b["metric_name"],
                    "pearson_r": result["pearson_r"],
                    "spearman_rho": result["spearman_rho"],
                    "best_lag": result["best_lag"],
                    "lagged_r": result["lagged_r"],
                    "lag_direction": result["lag_direction"],
                    "strength_label": strength_label,
                    "direction_label": direction_label,
                    "sample_size": result["sample_size"],
                    "p_value": result["p_value"],
                    "is_stable": is_stable,
                    "rolling_r_json": rolling_r_json,
                }
            )

    return pairs


# ---------------------------------------------------------------------------
# Investigation threading
# ---------------------------------------------------------------------------

def build_investigation_threads(
    anomaly_results: list[dict],
    correlation_pairs: list[dict],
    min_confidence: float = _INVESTIGATION_MIN_CONF,
) -> list[dict]:
    """
    Link anomalies to correlated metrics, forming evidence chains.

    For each anomaly, find all correlation pairs that include its metric,
    then build an evidence chain of connected metrics. Confidence is the
    product of anomaly_score × |lagged_r|.

    Returns a list of InvestigationThread dicts with keys:
      thread_id, trigger_metric, trigger_anomaly_id, evidence_chain,
      leading_dimension, leading_dim_value, confidence, suggested_focus,
      narrative_text, narrative_html
    """
    # Index pairs by metric
    metric_to_pairs: dict[str, list[dict]] = defaultdict(list)
    for pair in correlation_pairs:
        metric_to_pairs[pair["metric_a"]].append(pair)
        metric_to_pairs[pair["metric_b"]].append(pair)

    threads: list[dict] = []

    for anomaly in anomaly_results:
        metric = anomaly["metric_name"]
        related_pairs = metric_to_pairs.get(metric, [])
        if not related_pairs:
            continue

        evidence_chain: list[dict] = []
        for pair in related_pairs:
            related_metric = (
                pair["metric_b"] if pair["metric_a"] == metric else pair["metric_a"]
            )
            r = pair.get("lagged_r") or pair.get("pearson_r") or 0.0
            evidence_chain.append(
                {
                    "related_metric": related_metric,
                    "pearson_r": pair.get("pearson_r"),
                    "lagged_r": pair.get("lagged_r"),
                    "best_lag": pair.get("best_lag"),
                    "lag_direction": pair.get("lag_direction"),
                    "strength_label": pair.get("strength_label"),
                    "direction_label": pair.get("direction_label"),
                    "abs_r": abs(r),
                }
            )

        if not evidence_chain:
            continue

        # Confidence: anomaly_score × mean(|r|) of evidence chain
        mean_abs_r = float(
            np.mean([e["abs_r"] for e in evidence_chain])
        )
        confidence = round(anomaly["anomaly_score"] * mean_abs_r, 4)

        if confidence < min_confidence:
            continue

        # Sort evidence by strength
        evidence_chain.sort(key=lambda e: e["abs_r"], reverse=True)

        # Suggested focus: top 3 related metrics
        suggested_focus = [e["related_metric"] for e in evidence_chain[:3]]

        threads.append(
            {
                "thread_id": f"thread_{uuid.uuid4().hex[:12]}",
                "trigger_metric": metric,
                "trigger_anomaly_id": anomaly["anomaly_id"],
                "evidence_chain": evidence_chain,
                "leading_dimension": anomaly.get("top_dimension"),
                "leading_dim_value": anomaly.get("top_dimension_value"),
                "confidence": confidence,
                "suggested_focus": suggested_focus,
                "narrative_text": None,  # filled by narrate step
                "narrative_html": None,
            }
        )

    # Deduplicate: keep highest-confidence thread per anomaly
    seen_anomaly_ids: set[str] = set()
    deduped: list[dict] = []
    threads.sort(key=lambda t: t["confidence"], reverse=True)
    for t in threads:
        if t["trigger_anomaly_id"] not in seen_anomaly_ids:
            deduped.append(t)
            seen_anomaly_ids.add(t["trigger_anomaly_id"])

    return deduped


# ---------------------------------------------------------------------------
# Forward projections
# ---------------------------------------------------------------------------

def project_forward(
    metric_name: str,
    series: list[float],
    timestamps: list[str],
    forecast_periods: int = 12,
    anomaly_results: list[dict] | None = None,
) -> dict:
    """
    Project a metric forward using STL decomposition (≥30 points) or
    linear extrapolation (fallback for shorter series).

    Returns a ProjectionResult dict with keys:
      metric_name, forecast_periods, trend_direction, trend_slope,
      seasonality_present, inflection_signal, inflection_detail,
      projection_json, anomaly_density_trend, chart_spec
    """
    n = len(series)
    arr = np.array(series, dtype=float)

    trend_direction = "flat"
    trend_slope: float | None = None
    seasonality_present = False
    inflection_signal: str | None = None
    inflection_detail: str | None = None
    projection_json: list[dict] = []
    anomaly_density_trend: str | None = None

    # --- Linear trend fit (always computed for slope/direction) ---
    x = np.arange(n, dtype=float)
    try:
        coeffs = np.polyfit(x, arr, 1)
        trend_slope = round(float(coeffs[0]), 6)
        rel_slope = trend_slope / (float(np.mean(arr)) or 1.0)
        if rel_slope > 0.02:
            trend_direction = "up"
        elif rel_slope < -0.02:
            trend_direction = "down"
        else:
            trend_direction = "flat"
    except Exception:
        coeffs = [0.0, float(np.mean(arr))]

    # --- STL decomposition (requires ≥30 points) ---
    residual_std: float = float(np.std(arr, ddof=1))
    trend_component: np.ndarray | None = None

    if n >= 30:
        try:
            from statsmodels.tsa.seasonal import STL

            stl = STL(arr, period=12, robust=True)
            res = stl.fit()
            trend_component = res.trend
            seasonal = res.seasonal
            residual_std = float(np.std(res.resid, ddof=1))
            seasonality_present = float(np.std(seasonal)) > 0.1 * float(np.std(arr))
        except Exception as exc:
            logger.debug("STL failed (%s), falling back to linear", exc)

    # --- Forecasting ---
    if trend_component is not None:
        # Extrapolate trend from STL
        tc = trend_component
        t_x = np.arange(len(tc), dtype=float)
        t_coeffs = np.polyfit(t_x, tc, 1)
    else:
        t_coeffs = coeffs

    sigma = residual_std if residual_std > 0 else (float(np.std(arr, ddof=1)) or 1.0)

    for k in range(1, forecast_periods + 1):
        fv = float(np.polyval(t_coeffs, n - 1 + k))
        projection_json.append(
            {
                "period_offset": k,
                "forecast": round(fv, 4),
                "lower_1sigma": round(fv - sigma, 4),
                "upper_1sigma": round(fv + sigma, 4),
                "lower_2sigma": round(fv - 2 * sigma, 4),
                "upper_2sigma": round(fv + 2 * sigma, 4),
            }
        )

    # --- Inflection detection ---
    if trend_component is not None and len(trend_component) >= 6:
        # Detect sign change in second derivative of trend
        second_diff = np.diff(np.diff(trend_component))
        recent = second_diff[-6:]
        if np.any(recent > 0.5 * sigma) and trend_direction == "down":
            inflection_signal = "potential_recovery"
            inflection_detail = "Trend curvature suggests deceleration of decline"
        elif np.any(recent < -0.5 * sigma) and trend_direction == "up":
            inflection_signal = "potential_plateau"
            inflection_detail = "Trend curvature suggests growth is slowing"

    # --- Anomaly density trend ---
    if anomaly_results:
        metric_anomalies = [
            a for a in anomaly_results if a["metric_name"] == metric_name
        ]
        if len(metric_anomalies) >= 3:
            anomaly_density_trend = "increasing"
        elif len(metric_anomalies) == 0:
            anomaly_density_trend = "none"
        else:
            anomaly_density_trend = "stable"

    return {
        "metric_name": metric_name,
        "forecast_periods": forecast_periods,
        "trend_direction": trend_direction,
        "trend_slope": trend_slope,
        "seasonality_present": seasonality_present,
        "inflection_signal": inflection_signal,
        "inflection_detail": inflection_detail,
        "projection_json": projection_json,
        "anomaly_density_trend": anomaly_density_trend,
        "chart_spec": None,  # filled by generate_correlation_charts step
    }


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

def run_correlation_intelligence(
    settings: Settings,
    correlation_run_id: str,
    tenant_id: str,
    domain_id: str,
    run_id: str | None = None,
    forecast_periods: int = 12,
    analysis_mode: str = "full",
) -> dict:
    """
    Entry point for the Phase 43 correlation intelligence run.

    Orchestrates:
      1. Load KPI snapshots
      2. Score anomalies per metric
      3. Build correlation matrix
      4. Build investigation threads
      5. Project each metric forward

    Returns a summary dict:
      {
        "correlation_run_id": str,
        "kpi_snapshots": list[dict],
        "anomaly_results": list[dict],
        "correlation_pairs": list[dict],
        "investigation_threads": list[dict],
        "forward_projections": list[dict],
        "metric_count": int,
        "anomaly_count": int,
        "correlation_pair_count": int,
        "thread_count": int,
        "error_message": str | None,
      }
    """
    logger.info(
        "[correlation] Starting run %s for tenant=%s domain=%s run_id=%s",
        correlation_run_id, tenant_id, domain_id, run_id,
    )

    error_message: str | None = None

    # --- Step 1: Load KPI snapshots ---
    kpi_snapshots: list[dict] = []
    try:
        kpi_snapshots = load_kpi_snapshots(
            settings, tenant_id, domain_id, run_id=run_id
        )
        logger.info("[correlation] Loaded %d KPI snapshots", len(kpi_snapshots))
    except Exception as exc:
        logger.exception("[correlation] Failed to load KPI snapshots")
        error_message = f"Snapshot load failed: {exc}"

    if not kpi_snapshots:
        return {
            "correlation_run_id": correlation_run_id,
            "kpi_snapshots": [],
            "anomaly_results": [],
            "correlation_pairs": [],
            "investigation_threads": [],
            "forward_projections": [],
            "metric_count": 0,
            "anomaly_count": 0,
            "correlation_pair_count": 0,
            "thread_count": 0,
            "error_message": error_message or "No KPI snapshots found",
        }

    # --- Step 2: Score anomalies ---
    anomaly_results: list[dict] = []
    for snap in kpi_snapshots:
        # Extract dimension breakdown for the most anomalous period (if any)
        dim_breakdown: dict | None = None

        try:
            anoms = score_anomalies(
                snap["metric_name"],
                snap["series"],
                snap["timestamps"],
                dimension_breakdown=dim_breakdown,
            )
            # Now enrich with dimension breakdown for each anomaly
            for anom in anoms:
                db = extract_dimension_breakdown(snap, anom["detected_at"])
                if db:
                    anom["top_dimension"] = db.get("dimension")
                    anom["top_dimension_value"] = db.get("value")
                    anom["dimension_pct"] = db.get("pct")
            anomaly_results.extend(anoms)
        except Exception as exc:
            logger.warning(
                "[correlation] Anomaly scoring failed for %s: %s",
                snap["metric_name"], exc,
            )

    logger.info("[correlation] Detected %d anomalies", len(anomaly_results))

    # --- Step 3: Build correlation matrix ---
    correlation_pairs: list[dict] = []
    if len(kpi_snapshots) >= 2 and analysis_mode != "anomaly_only":
        try:
            correlation_pairs = build_correlation_matrix(kpi_snapshots)
            logger.info(
                "[correlation] Built %d correlation pairs", len(correlation_pairs)
            )
        except Exception as exc:
            logger.warning("[correlation] Correlation matrix failed: %s", exc)

    # --- Step 4: Build investigation threads ---
    investigation_threads: list[dict] = []
    if anomaly_results and correlation_pairs:
        try:
            investigation_threads = build_investigation_threads(
                anomaly_results, correlation_pairs
            )
            logger.info(
                "[correlation] Built %d investigation threads",
                len(investigation_threads),
            )
        except Exception as exc:
            logger.warning("[correlation] Investigation threading failed: %s", exc)

    # --- Step 5: Forward projections ---
    forward_projections: list[dict] = []
    if analysis_mode != "anomaly_only":
        for snap in kpi_snapshots:
            try:
                proj = project_forward(
                    snap["metric_name"],
                    snap["series"],
                    snap["timestamps"],
                    forecast_periods=forecast_periods,
                    anomaly_results=anomaly_results,
                )
                forward_projections.append(proj)
            except Exception as exc:
                logger.warning(
                    "[correlation] Projection failed for %s: %s",
                    snap["metric_name"], exc,
                )

    logger.info(
        "[correlation] Run %s complete — metrics=%d anomalies=%d pairs=%d threads=%d projections=%d",
        correlation_run_id,
        len(kpi_snapshots),
        len(anomaly_results),
        len(correlation_pairs),
        len(investigation_threads),
        len(forward_projections),
    )

    return {
        "correlation_run_id": correlation_run_id,
        "kpi_snapshots": kpi_snapshots,
        "anomaly_results": anomaly_results,
        "correlation_pairs": correlation_pairs,
        "investigation_threads": investigation_threads,
        "forward_projections": forward_projections,
        "metric_count": len(kpi_snapshots),
        "anomaly_count": len(anomaly_results),
        "correlation_pair_count": len(correlation_pairs),
        "thread_count": len(investigation_threads),
        "error_message": error_message,
    }