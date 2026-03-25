# Phase 43: Statistical Correlation, Anomaly, and Forward Pattern Agent

## Objective

Build a dedicated statistical intelligence layer on top of the existing semantic KPI and agentic
workflow infrastructure. Where Phase 38 answers *"what is abnormal and why?"* through LLM-first
reasoning, Phase 43 answers *"how strongly are things connected, how are patterns evolving, and
what is likely to happen next?"* through quantitative statistical computation followed by
LLM-powered interpretation and chart generation.

This phase introduces four interconnected capabilities:

1. **Statistical Anomaly Scoring** — detect outliers and drift with numerical rigour (Z-score, IQR, CUSUM).
2. **Cross-Metric Correlation Engine** — measure directional strength and lag relationships between KPIs.
3. **Investigation Thread** — when anomalies co-occur with correlations, surface the evidence chain as a structured investigation with confidence scores.
4. **Forward Pattern Projection** — project trend trajectories and flag convergence/divergence scenarios with time-series charts.

---

## Why This Is Different from Phase 38

| Dimension | Phase 38 | Phase 43 |
|---|---|---|
| Detection method | LLM reasoning over data slices | Statistical computation (Z, IQR, CUSUM, Pearson, Spearman) |
| Output type | Qualitative hypothesis + action | Numerical evidence + directional score + projection |
| Correlation | Not covered | Core feature — cross-metric, lagged, partial |
| Forward view | Not covered | Trend projection + confidence band + inflection alert |
| Chart type | Investigation summary | Anomaly timeline, correlation heatmap, scatter + R², forecast band |
| Input | Anomaly trigger from user | Runs continuously against certified KPIs after deployment |

Phase 43 is a data-science-grade complement to Phase 38's LLM reasoning. Both work together:
Phase 43 computes the statistics; Phase 38 narrates them.

---

## Core Concepts

### Anomaly Score

For each certified KPI time series, assign a numerical anomaly score per time point:

```
Z-score:   z = (x - μ) / σ            threshold ≥ 2.5 = anomaly
IQR fence: outlier if x < Q1 - 1.5·IQR  or  x > Q3 + 1.5·IQR
CUSUM:     cumulative drift from rolling baseline  (catches gradual shifts)
Composite: weighted average of all three, normalized to [0, 1]
```

Anomaly classes:
- `spike` — single point departure, Z ≥ 2.5
- `drop` — single point departure, Z ≤ -2.5
- `drift_up` / `drift_down` — CUSUM detects a sustained directional shift
- `step_change` — mean before vs after a breakpoint differs significantly (Welch t-test)

---

### Correlation Score

For each pair of certified KPIs (A, B):

```
Pearson r:   linear relationship, continuous values
Spearman ρ:  rank-order relationship, handles non-linear monotonic trends
Lagged r:    max |r| across lag offsets L = [-N, ..., 0, ..., +N]  (e.g. ±12 periods)
```

Strength classification:

| \|r\| range | Label |
|---|---|
| 0.7 – 1.0 | Strong |
| 0.4 – 0.7 | Moderate |
| 0.2 – 0.4 | Weak |
| 0.0 – 0.2 | Negligible |

Direction: positive / negative

Lag direction:
- `A leads B by L periods` — metric A is a leading indicator of metric B
- `concurrent` — max correlation at lag 0
- `B leads A by L periods` — reverse leading relationship

Correlation stability: compute rolling correlation over a sliding window to flag whether the
relationship is consistent or has recently broken down (`correlation_breakdown` event).

---

### Investigation Thread

When anomalies and correlations co-occur, the investigation thread connects them:

```
Anomaly detected: metric_A dropped 3.2σ at t₀
  → strongly correlated with: metric_B (r = -0.83, B leads A by 2 periods)
  → metric_B had a drift_down starting at t₀ - 2
  → dimension drill-down: drop concentrated in dimension SBU = "North Zone" (87% of variance)
  → evidence score: 0.91 (strong — directional, lagged, dimension-confirmed)
```

Each investigation thread has:
- `trigger_metric` — the anomalous KPI that started the thread
- `evidence_chain` — ordered list of correlated metrics + anomalies with scores
- `leading_dimension` — the dimension slice that concentrates the signal
- `confidence` — composite evidence score [0, 1]
- `suggested_focus` — top 2-3 metrics/dimensions to investigate next

---

### Forward Pattern Projection

For each metric with sufficient history (≥ 30 observations):

1. Decompose the series into **trend + seasonality + residual** (STL decomposition).
2. Fit a forward projection using a weighted combination of:
   - Linear trend extrapolation
   - Seasonal expectation from same period prior year/cycle
3. Generate **confidence bands** (±1σ, ±2σ) for the next N periods.
4. Flag inflection scenarios:
   - `convergence_alert` — two correlated metrics are diverging from their historical ratio
   - `accumulation_alert` — anomaly density is increasing over recent windows (more anomalies per period)
   - `reversal_signal` — trend momentum is flattening or turning
   - `on_track` — no significant deviation from baseline projection

---

## Source Data

All time series data is read from **`rows_json` already stored in `quantyx_chart_requests`** —
no SQL rewriting, no new raw queries against tenant tables. The certified KPI rows are computed
once during the agentic deployment run and stored; Phase 43 reads them back generically.

This approach is deliberately chosen over SQL rewriting because:
- The KPI SQL in `quantyx_chart_requests` was written for chart rendering — it may contain CTEs,
  window functions, CASE expressions, or subqueries that cannot be reliably rewritten by string
  manipulation.
- Column names vary per tenant, table, and domain — there are no universal names to target.
- `rows_json` is already the authoritative computed result; re-executing or rewriting the SQL
  would produce a different (possibly inconsistent) series.

---

### Data Pattern 1: Base Time Series (input to anomaly scoring and projection)

Load all `ready` charts for a `tenant_id + domain_id` from `quantyx_chart_requests`. For each
chart, extract a clean `(period, value)` series using only information already on the record —
no knowledge of the underlying table or column names is needed.

```python
def _detect_period_column(row: dict) -> str | None:
    """
    Identify the period column from a result row generically:
    1. Key whose name matches a known time-dimension word.
    2. Fallback: key whose value parses as an ISO date string.
    No table names or column names are hardcoded.
    """
    PERIOD_NAMES = {
        "period", "date", "month", "week", "day", "year", "time",
        "month_start", "week_start", "day_date", "report_date",
        "report_month", "report_week", "created_date", "transaction_date",
    }
    for key in row:
        if str(key).lower() in PERIOD_NAMES:
            return key
    import re
    DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")
    for key, val in row.items():
        if val and DATE_RE.match(str(val)):
            return key
    return None


def load_kpi_snapshots(
    settings: Settings,
    tenant_id: str,
    domain_id: str,
) -> list[dict]:
    """
    Load certified KPI time series for a tenant/domain.
    Reads quantyx_chart_requests scoped by tenant_id + domain_id.
    Returns one snapshot per unique metric_name.

    Each snapshot:
      {
        metric_name:   str,          # query_payload["metrics"][0]
        period_col:    str,          # auto-detected from rows_json
        value_col:     str,          # same as metric_name
        dimension_col: str | None,   # first categorical dimension, if present
        series:        list[dict],   # [{period: str, value: float}] sorted asc
        rows_json:     list[dict],   # full rows kept for dimension drill-down
        chart_id:      str,
      }

    Skips charts with no rows_json, no detectable period column,
    or fewer than 5 data points.
    """
    # Prefer exact run_id match; fall back to tenant/domain scope for on-demand calls.
    if run_id:
        rows = run_query(settings, """
            SELECT chart_id, query_payload, rows_json
              FROM public.quantyx_chart_requests
             WHERE run_id   = %s
               AND tenant_id = %s
               AND domain_id = %s
               AND status    = 'ready'
               AND rows_json IS NOT NULL
             ORDER BY created_at DESC
        """, [run_id, tenant_id, domain_id])
    else:
        rows = run_query(settings, """
            SELECT chart_id, query_payload, rows_json
              FROM public.quantyx_chart_requests
             WHERE tenant_id = %s
               AND domain_id = %s
               AND status    = 'ready'
               AND rows_json IS NOT NULL
             ORDER BY created_at DESC
        """, [tenant_id, domain_id])

    snapshots = []
    seen_metrics: set[str] = set()

    for row in rows:
        qp      = row.get("query_payload") or {}
        rj      = row.get("rows_json") or []
        metrics = qp.get("metrics") or []
        if not metrics or not rj:
            continue

        metric_name = str(metrics[0])
        if metric_name in seen_metrics:
            continue                              # one snapshot per metric (newest wins)

        first_row  = rj[0] if rj else {}
        period_col = _detect_period_column(first_row)
        if not period_col:
            continue                              # cannot build a time series

        # pick the first non-period, non-metric dimension column for drill-down
        all_dims  = [d for d in (qp.get("dimensions") or [])
                     if d != period_col and d != metric_name]
        dim_col   = all_dims[0] if all_dims else None

        series = []
        for r in rj:
            period = r.get(period_col)
            value  = r.get(metric_name)
            if period is not None and value is not None:
                try:
                    series.append({"period": str(period), "value": float(value)})
                except (TypeError, ValueError):
                    continue
        series.sort(key=lambda x: x["period"])

        if len(series) < 5:
            continue                              # too sparse for statistical analysis

        seen_metrics.add(metric_name)
        snapshots.append({
            "metric_name":   metric_name,
            "period_col":    period_col,
            "value_col":     metric_name,
            "dimension_col": dim_col,
            "series":        series,
            "rows_json":     rj,
            "chart_id":      row["chart_id"],
        })

    return snapshots
```

The returned `series` list is passed directly to `score_anomalies()` and `project_forward()`.

**Example snapshot** (shape only — actual column names vary per tenant):
```
metric_name:   "daily_sales"
period_col:    "period"        ← auto-detected; could be "month", "report_date", etc.
value_col:     "daily_sales"   ← from query_payload["metrics"][0]
dimension_col: "zone"          ← from query_payload["dimensions"]; could be any categorical
series:
  [{period: "2025-06-01", value: 1842.3},
   {period: "2025-07-01", value: 1903.7},
   ...]
```

---

### Data Pattern 2: Dimension Breakdown (for identifying which slice drives an anomaly)

No new SQL query is run. The `rows_json` stored with the chart already contains dimension-level
rows if the chart was a breakdown or grouped chart. The engine scans `rows_json` for the anomaly
period and computes which dimension value accounts for the largest share of the deviation.

```python
def extract_dimension_breakdown(
    snapshot: dict,
    anomaly_period: str,           # e.g. "2026-02-01"
) -> list[dict]:
    """
    From snapshot["rows_json"], find rows at or near anomaly_period,
    group by snapshot["dimension_col"], and return each slice with its
    share of the total metric value.

    Returns [{dim_value: str, metric_value: float, pct: float}]
    sorted by metric_value descending.

    Works on any tenant — no table names or column names are hardcoded.
    Returns [] if no dimension_col is present or no matching rows found.
    """
    dim_col    = snapshot.get("dimension_col")
    period_col = snapshot["period_col"]
    value_col  = snapshot["value_col"]
    rows_json  = snapshot.get("rows_json") or []

    if not dim_col:
        return []

    # match on YYYY-MM prefix so daily and monthly grains both work
    period_prefix = str(anomaly_period)[:7]
    period_rows = [
        r for r in rows_json
        if str(r.get(period_col, "")).startswith(period_prefix)
    ]
    if not period_rows:
        return []

    total = sum(float(r.get(value_col) or 0) for r in period_rows)
    if total == 0:
        return []

    result = []
    for r in period_rows:
        dim_val   = r.get(dim_col)
        met_val   = float(r.get(value_col) or 0)
        if dim_val is not None:
            result.append({
                "dim_value":    dim_val,
                "metric_value": met_val,
                "pct":          round(met_val / total * 100, 1),
            })
    result.sort(key=lambda x: x["metric_value"], reverse=True)
    return result
```

**Example output** (shape only — dimension name and values are tenant-specific):
```
[
  {dim_value: "North Zone",  metric_value: 1503.1, pct: 87.5},
  {dim_value: "South Zone",  metric_value: 128.4,  pct:  7.5},
  {dim_value: "East Zone",   metric_value: 86.5,   pct:  5.0},
]
```
The top entry becomes `leading_dimension` / `leading_dim_value` / `dimension_pct` on the
investigation thread.

---

### Data Pattern 3: Anomaly Density Over Time (feeds the `accumulation_alert` signal)

Run against `quantyx_anomaly_results` after the anomaly scoring step completes. Measures whether
anomaly events are clustering more densely in recent periods.

```sql
-- All values are parameterized — no tenant, domain, or run IDs are hardcoded.
SELECT
    DATE_TRUNC('month', detected_at)                        AS period,
    COUNT(*)                                                AS anomaly_count,
    AVG(anomaly_score)                                      AS avg_severity,
    COUNT(*) FILTER (WHERE anomaly_class = 'spike')         AS spike_count,
    COUNT(*) FILTER (WHERE anomaly_class = 'drop')          AS drop_count,
    COUNT(*) FILTER (WHERE anomaly_class IN ('drift_up','drift_down')) AS drift_count
FROM public.quantyx_anomaly_results
WHERE tenant_id         = %s   -- parameterized: tenant_id
  AND domain_id         = %s   -- parameterized: domain_id
  AND correlation_run_id = %s  -- parameterized: current correlation_run_id
GROUP BY 1
ORDER BY 1 ASC;
```

Returns:
```
period      | anomaly_count | avg_severity | spike_count | drop_count | drift_count
2025-06-01  | 1             | 0.42         | 1           | 0          | 0
2025-07-01  | 2             | 0.55         | 1           | 1          | 0
2025-08-01  | 1             | 0.38         | 0           | 1          | 0
2025-09-01  | 4             | 0.71         | 2           | 0          | 2
2025-10-01  | 3             | 0.68         | 1           | 1          | 1
2026-01-01  | 5             | 0.77         | 2           | 1          | 2
2026-02-01  | 6             | 0.83         | 1           | 2          | 3   ← accumulation_alert
2026-03-01  | 6             | 0.85         | 2           | 2          | 2
```

When `anomaly_count` shows a rising trend over 3+ consecutive periods, the `accumulation_alert`
inflection signal fires on all active forward projections for that domain.

---

### Query Pattern 4: Lagged Series Alignment (for correlation matrix)

To compute lagged correlations, each metric pair needs both series aligned to the same time
index and shifted by a lag offset. The alignment is done in Python (numpy), but the data is
pulled using the same Query Pattern 1 for each metric, then joined in-memory:

```python
# For lag = +2 (metric_a leads metric_b by 2 periods):
# align series_a[0:-2] with series_b[2:]
# compute pearson_r on the aligned arrays

import numpy as np
from scipy.stats import pearsonr, spearmanr

def lagged_correlation(series_a, series_b, max_lag=6):
    best_r, best_lag = 0.0, 0
    for lag in range(-max_lag, max_lag + 1):
        if lag > 0:
            a, b = series_a[:-lag], series_b[lag:]
        elif lag < 0:
            a, b = series_a[-lag:], series_b[:lag]
        else:
            a, b = series_a, series_b
        if len(a) < 5:
            continue
        r, p = pearsonr(a, b)
        if abs(r) > abs(best_r):
            best_r, best_lag = r, lag
    return best_r, best_lag
```

---

## Computation Pipeline

What happens inside `correlation_agent.py` after `load_kpi_snapshots()` returns:

```
KPI snapshots loaded from quantyx_chart_requests (rows_json + query_payload)
  — period column auto-detected per snapshot, no table/column names hardcoded

Historical series (one list[float] per metric)
        │
        ▼
  ┌─────────────────────────────────────────────┐
  │  STL Decomposition (statsmodels.STL)        │
  │                                             │
  │  Original series = Trend + Season + Resid   │
  │                                             │
  │  Trend (T):   smoothed long-run direction   │
  │  Seasonal (S): repeating cycle component    │
  │  Residual (R): unexplained remainder        │
  └─────────────────────────────────────────────┘
        │
        ▼
  ┌─────────────────────────────────────────────┐
  │  Forward Extrapolation                      │
  │                                             │
  │  point_estimate[t] = T_projected[t]         │
  │                     + S_expected[t]         │
  │                                             │
  │  σ_residual = rolling std of R (last 12p)   │
  │                                             │
  │  ±1σ band = point_estimate ± 1 × σ_residual │
  │  ±2σ band = point_estimate ± 2 × σ_residual │
  └─────────────────────────────────────────────┘
        │
        ▼
  ┌─────────────────────────────────────────────┐
  │  Inflection Signal Check                    │
  │                                             │
  │  reversal_signal      slope(T) flips sign   │
  │  accumulation_alert   anomaly density ↑     │
  │  convergence_alert    correlated pair ratio │
  │                       diverging from norm   │
  │  on_track             no signal fired       │
  └─────────────────────────────────────────────┘
```

The `projection_json` array stored in `quantyx_forward_projections` has one entry per period
(both historical and forecast):

```json
[
  {
    "period": "2025-06-01",
    "metric_value": 1842.3,
    "trend": 1850.1,
    "seasonal": -7.8,
    "residual": -0.0,
    "is_forecast": false
  },
  {
    "period": "2026-04-01",
    "point_estimate": 1980.4,
    "lower_1s": 1921.3,
    "upper_1s": 2039.5,
    "lower_2s": 1862.2,
    "upper_2s": 2098.6,
    "is_forecast": true
  }
]
```

The frontend uses `is_forecast: true` to draw dashed lines and shaded confidence bands, and
`is_forecast: false` for the solid historical line.

---

## End-to-End Trigger Chain

```
1. Deployment completes  →  finalize_canonical_deployment() in workspace_store.py
         │
         ▼
2. POST /analysis/correlation fires automatically
   {tenant_id, domain_id, run_id, analysis_mode: "full", triggered_by: "post_deployment"}
         │
         ▼
3. load_kpi_snapshots(tenant_id, domain_id) reads quantyx_chart_requests
   — rows_json + query_payload only; no tenant table names or column names referenced
   — period column auto-detected per snapshot from row key names / value patterns
   — one snapshot per unique metric_name (newest chart wins)
         │
         ▼
4. extract_dimension_breakdown() called per anomaly using snapshot["rows_json"]
   — no new SQL query; dimension concentration derived from already-stored rows
   — dimension column taken from snapshot["dimension_col"] (auto-detected)
         │
         ▼
5. numpy / scipy computation:
   - Z-score, IQR, CUSUM per metric  →  anomaly_results
   - Pearson, Spearman, lagged r for all pairs  →  correlation_pairs
   - Evidence chain linking  →  investigation_threads
   - STL decomposition + extrapolation  →  forward_projections
         │
         ▼
6. Query Pattern 3 runs against the just-written anomaly_results
   to compute anomaly_density_trend and fire accumulation_alert if needed
         │
         ▼
7. Chart specs generated for all 6 chart types
         │
         ▼
8. LLM narrate call: statistical outputs → summary_text + summary_html
         │
         ▼
9. All results persisted to the 5 new tables
         │
         ▼
10. GET /dashboards/{dashboard_id} for the workspace now surfaces
    a "Correlation Intelligence" section with the 6 chart types
```

---

## Chart Library — amCharts 5

All charts in Phase 43 are rendered exclusively with **amCharts 5** (`@amcharts/amcharts5`).
No other charting library is used for this feature.

### Package

```
@amcharts/amcharts5
@amcharts/amcharts5/xy           ← XYChart, axes, line/column/scatter series
@amcharts/amcharts5/themes/Animated
```

### amCharts 5 Component Mapping

| Phase 43 Chart | amCharts 5 Root Class | Key Series Types |
|---|---|---|
| `forecast_band` | `am5xy.XYChart` | `LineSeries` (solid + dashed) + `LineSeries` with `fillOpacity` for bands |
| `anomaly_timeline` | `am5xy.XYChart` | `LineSeries` + `am5.Bullet` circle markers |
| `correlation_heatmap` | `am5xy.XYChart` | `ColumnSeries` with `heat` colour mapping + `am5.HeatLegend` |
| `scatter_regression` | `am5xy.XYChart` | `LineSeries` (scatter mode, no stroke) + `LineSeries` (regression line) |
| `rolling_correlation` | `am5xy.XYChart` | `LineSeries` + `AxisDataItem` range for threshold band |
| `anomaly_density` | `am5xy.XYChart` | Stacked `ColumnSeries` × 4 classes + `am5xy.AxisDataItem` reference lines |

### Standard Setup (shared across all 6 charts)

```javascript
import * as am5 from "@amcharts/amcharts5";
import * as am5xy from "@amcharts/amcharts5/xy";
import am5themes_Animated from "@amcharts/amcharts5/themes/Animated";

const root = am5.Root.new("chartdiv");
root.setThemes([am5themes_Animated.new(root)]);

const chart = root.container.children.push(
  am5xy.XYChart.new(root, {
    panX: true,
    panY: false,
    wheelX: "panX",
    wheelY: "zoomX",
    layout: root.verticalLayout,
  })
);
```

---

## Charts — Detailed Specifications

### Chart 1: Forecast Band

The primary projection chart. Shows historical actuals as a solid line, transitions to a dashed
projected line at the forecast boundary, with ±1σ and ±2σ shaded bands.

```
Sales Qty TMT — Forward Projection (Apr 2026 → Mar 2027)

2100 │                                          ░░░░░░░░░░░░░
2050 │                                     ░░░▒▒▒▒▒▒▒▒▒▒▒▒▒░░░
2000 │─────────────────────────────────────▒▒▒╌╌╌╌╌╌╌╌╌╌╌╌╌╌▒▒▒
1950 │                          ▲         ▒▒▒               ▒▒▒
1900 │                                   ▒▒▒                  ▒▒▒
1850 │                                  ▒░░░░░░░░░░░░░░░░░░░░░░▒
1800 │
     └──────────────────────────────────┬───────────────────────
      Jun  Jul  Aug  Sep  Oct  Nov  Dec  │  Apr  May  Jun ... Mar
               Historical               │      Projected (12m)
                                   Apr 2026
                                   = forecast start

Legend:
  ───  Actuals (solid)
  ╌╌╌  Point estimate (dashed)
  ▒▒▒  ±1σ band  (68% confidence, medium shade)
  ░░░  ±2σ band  (95% confidence, light shade)
  ▲    Anomaly marker
```

Inflection annotations are drawn as vertical markers on the chart:
- `⚠ Reversal Signal` — at the period where the trend slope changes sign
- `⚡ Accumulation Alert` — at the first period where anomaly density crossed threshold

**amCharts 5 implementation:**

```javascript
// amCharts 5 — forecast_band
// Library: @amcharts/amcharts5 + @amcharts/amcharts5/xy

import * as am5 from "@amcharts/amcharts5";
import * as am5xy from "@amcharts/amcharts5/xy";
import am5themes_Animated from "@amcharts/amcharts5/themes/Animated";

const root = am5.Root.new("chart-forecast-daily_sales");
root.setThemes([am5themes_Animated.new(root)]);

const chart = root.container.children.push(
  am5xy.XYChart.new(root, { panX: true, wheelX: "panX", wheelY: "zoomX" })
);

// Date axis (X)
const xAxis = chart.xAxes.push(
  am5xy.DateAxis.new(root, {
    baseInterval: { timeUnit: "month", count: 1 },
    renderer: am5xy.AxisRendererX.new(root, {}),
    tooltip: am5.Tooltip.new(root, {}),
  })
);

// Value axis (Y)
const yAxis = chart.yAxes.push(
  am5xy.ValueAxis.new(root, {
    renderer: am5xy.AxisRendererY.new(root, {}),
  })
);

// ── ±2σ band (outer, lightest fill) ────────────────────────────────────────
const band2s = chart.series.push(
  am5xy.LineSeries.new(root, {
    xAxis, yAxis,
    valueXField: "period",
    valueYField: "upper_2s",
    openValueYField: "lower_2s",
    fill: am5.color("#DBEAFE"),
    fillOpacity: 0.4,
    strokeOpacity: 0,
    tooltip: am5.Tooltip.new(root, { labelText: "±2σ: {openValueY} – {valueY}" }),
  })
);
band2s.fills.template.setAll({ fillOpacity: 0.4, visible: true });
band2s.strokes.template.setAll({ strokeOpacity: 0 });

// ── ±1σ band (inner, medium fill) ──────────────────────────────────────────
const band1s = chart.series.push(
  am5xy.LineSeries.new(root, {
    xAxis, yAxis,
    valueXField: "period",
    valueYField: "upper_1s",
    openValueYField: "lower_1s",
    fill: am5.color("#BFDBFE"),
    fillOpacity: 0.6,
    strokeOpacity: 0,
  })
);
band1s.fills.template.setAll({ fillOpacity: 0.6, visible: true });
band1s.strokes.template.setAll({ strokeOpacity: 0 });

// ── Historical actuals (solid line) ────────────────────────────────────────
const actualSeries = chart.series.push(
  am5xy.LineSeries.new(root, {
    name: "Actuals",
    xAxis, yAxis,
    valueXField: "period",
    valueYField: "metric_value",
    stroke: am5.color("#2563EB"),
    strokeWidth: 2,
    tooltip: am5.Tooltip.new(root, { labelText: "{valueY}" }),
  })
);

// ── Forecast point estimate (dashed line, forecast points only) ─────────────
const forecastSeries = chart.series.push(
  am5xy.LineSeries.new(root, {
    name: "Forecast",
    xAxis, yAxis,
    valueXField: "period",
    valueYField: "point_estimate",
    stroke: am5.color("#2563EB"),
    strokeWidth: 2,
    strokeDasharray: [6, 4],
    tooltip: am5.Tooltip.new(root, { labelText: "Forecast: {valueY}" }),
  })
);

// ── Vertical range: forecast start boundary ─────────────────────────────────
const forecastRange = xAxis.makeDataItem({
  value: new Date("2026-04-01").getTime(),
  endValue: new Date("2026-04-01").getTime(),
});
xAxis.createAxisRange(forecastRange);
forecastRange.get("grid").setAll({ stroke: am5.color("#94A3B8"), strokeDasharray: [4, 4], strokeWidth: 1 });
forecastRange.get("label").setAll({ text: "Forecast Start", fill: am5.color("#94A3B8"), above: true });

// ── Inflection signal marker (if reversal_signal) ───────────────────────────
// Rendered as a DataItem range on xAxis at the reversal period
const reversalRange = xAxis.makeDataItem({ value: new Date("2026-08-01").getTime() });
xAxis.createAxisRange(reversalRange);
reversalRange.get("grid").setAll({ stroke: am5.color("#F59E0B"), strokeWidth: 2 });
reversalRange.get("label").setAll({ text: "⚠ Reversal", fill: am5.color("#F59E0B"), above: true });

// ── Feed data (projection_json from API) ────────────────────────────────────
// Filter: actual series gets is_forecast=false rows; forecast series gets is_forecast=true rows
const historicalData = projectionJson.filter(d => !d.is_forecast);
const forecastData   = projectionJson.filter(d => d.is_forecast);

actualSeries.data.setAll(historicalData);
forecastSeries.data.setAll(forecastData);
band1s.data.setAll(forecastData);
band2s.data.setAll(forecastData);

// ── Legend ───────────────────────────────────────────────────────────────────
chart.children.push(am5.Legend.new(root, { centerX: am5.p50, x: am5.p50 }));
```

**Stored chart_spec (persisted in `quantyx_forward_projections.chart_spec`):**
```json
{
  "library": "amcharts5",
  "chart_type": "forecast_band",
  "title": "Sales Qty TMT — Forward Projection",
  "metric": "daily_sales",
  "forecast_start": "2026-04-01",
  "inflection_signal": "reversal_signal",
  "inflection_at": "2026-08-01",
  "trend_direction": "up",
  "trend_slope": 12.4,
  "seasonality_present": true,
  "series": [
    { "id": "actual",   "label": "Actuals",    "color": "#2563EB", "stroke_dash": null,   "value_field": "metric_value",   "data_filter": "is_forecast=false" },
    { "id": "forecast", "label": "Forecast",   "color": "#2563EB", "stroke_dash": [6,4],  "value_field": "point_estimate", "data_filter": "is_forecast=true"  },
    { "id": "band_1s",  "label": "±1σ (68%)",  "color": "#BFDBFE", "fill_opacity": 0.6,   "upper_field": "upper_1s",       "lower_field": "lower_1s"          },
    { "id": "band_2s",  "label": "±2σ (95%)",  "color": "#DBEAFE", "fill_opacity": 0.4,   "upper_field": "upper_2s",       "lower_field": "lower_2s"          }
  ]
}
```

---

### Chart 2: Anomaly Timeline

Time series for a single metric with anomaly events overlaid as annotated markers. Each marker
is colour-coded by anomaly class.

```
Sales Qty TMT — Anomaly Timeline

2000 │              ▲spike                           ▼drop
1900 │─────────────/────────────────────────────────\────────
1800 │            /          ~~~~~~drift_down~~~~~    \
1700 │           /                                     \──────
     └──────────────────────────────────────────────────────
      Jun  Jul  Aug  Sep  Oct  Nov  Dec  Jan  Feb  Mar

Marker colours:
  ▲  spike      orange   (#F97316)
  ▼  drop       red      (#EF4444)
  ~  drift_up   green    (#22C55E)
  ~  drift_down amber    (#EAB308)
  ═  step_change purple  (#8B5CF6)

Each marker tooltip shows:
  Metric: daily_sales
  Class: spike
  Score: 0.84
  Z-score: 3.1
  Observed: 2041 TMT  (baseline: 1891 TMT, +7.9%)
  Top dimension: North Zone (62% of variance)
```

**amCharts 5 implementation:**

```javascript
// amCharts 5 — anomaly_timeline
// Markers rendered as am5.Bullet on a dedicated zero-value series

const root = am5.Root.new("chart-anomaly-daily_sales");
root.setThemes([am5themes_Animated.new(root)]);
const chart = root.container.children.push(am5xy.XYChart.new(root, { panX: true, wheelX: "panX" }));

const xAxis = chart.xAxes.push(
  am5xy.DateAxis.new(root, {
    baseInterval: { timeUnit: "month", count: 1 },
    renderer: am5xy.AxisRendererX.new(root, {}),
  })
);
const yAxis = chart.yAxes.push(
  am5xy.ValueAxis.new(root, { renderer: am5xy.AxisRendererY.new(root, {}) })
);

// ── Main time series line ────────────────────────────────────────────────────
const lineSeries = chart.series.push(
  am5xy.LineSeries.new(root, {
    name: "Sales Qty TMT",
    xAxis, yAxis,
    valueXField: "period",
    valueYField: "metric_value",
    stroke: am5.color("#2563EB"),
    strokeWidth: 2,
    tooltip: am5.Tooltip.new(root, { labelText: "{valueY} TMT" }),
  })
);

// ── Anomaly bullet markers ───────────────────────────────────────────────────
// Anomaly class → colour map
const anomalyColors = {
  spike:       "#F97316",   // orange
  drop:        "#EF4444",   // red
  drift_up:    "#22C55E",   // green
  drift_down:  "#EAB308",   // amber
  step_change: "#8B5CF6",   // purple
};

// A separate series carries only the anomaly data points so bullets render at the right Y value
const markerSeries = chart.series.push(
  am5xy.LineSeries.new(root, {
    xAxis, yAxis,
    valueXField: "period",
    valueYField: "metric_value",
    strokeOpacity: 0,        // hide the connecting line; show bullets only
  })
);

markerSeries.bullets.push((root, series, dataItem) => {
  const anomalyClass = dataItem.dataContext.anomaly_class;
  const color = am5.color(anomalyColors[anomalyClass] || "#94A3B8");
  return am5.Bullet.new(root, {
    sprite: am5.Circle.new(root, {
      radius: 7,
      fill: color,
      stroke: am5.color("#FFFFFF"),
      strokeWidth: 1.5,
      tooltipText: [
        "{anomaly_class}: {label}",
        "Score: {anomaly_score}  |  Z: {z_score}",
        "Observed: {observed_value}  Baseline: {baseline_value}",
        "Top dim: {top_dimension_value} ({dimension_pct}%)",
      ].join("\n"),
      tooltip: am5.Tooltip.new(root, {}),
    }),
  });
});

// Feed the main series with full time series data
lineSeries.data.setAll(timeSeriesData);   // [{period, metric_value}]

// Feed the marker series with anomaly rows only (which already have metric_value for Y position)
markerSeries.data.setAll(anomalyMarkers); // [{period, metric_value, anomaly_class, ...}]
```

**Stored chart_spec:**
```json
{
  "library": "amcharts5",
  "chart_type": "anomaly_timeline",
  "title": "Sales Qty TMT — Anomaly History",
  "metric": "daily_sales",
  "anomaly_color_map": {
    "spike":       "#F97316",
    "drop":        "#EF4444",
    "drift_up":    "#22C55E",
    "drift_down":  "#EAB308",
    "step_change": "#8B5CF6"
  },
  "anomaly_markers": [
    {
      "period": "2025-09-01", "metric_value": 2041,
      "anomaly_class": "spike",  "anomaly_score": 0.84, "z_score": 3.1,
      "label": "+7.9% spike",    "observed_value": 2041, "baseline_value": 1891,
      "top_dimension_value": "North Zone", "dimension_pct": 62
    },
    {
      "period": "2026-02-01", "metric_value": 1718,
      "anomaly_class": "drop",   "anomaly_score": 0.91, "z_score": -3.4,
      "label": "-9.2% drop",     "observed_value": 1718, "baseline_value": 1891,
      "top_dimension_value": "North Zone", "dimension_pct": 87
    }
  ]
}
```

---

### Chart 3: Correlation Heatmap

Full N×N matrix of all certified KPI pairs. Cells are colour-coded by Pearson r value. Cells
with `is_stable: false` (correlation has recently broken down) receive a diagonal stripe overlay.
Lag annotations appear inside each cell.

```
Correlation Heatmap — market_performance_analysis

                   daily   target  dist_   industry  fill
                   _sales  _qty    cap     _sales    _rate
daily_sales        ████    ████    ████    ████      ████
                   1.00    0.82    -0.71   0.94      0.65
                           →+0     A→B+2   →+0      A→B+1

target_qty         ████    ████    ████    ████      ████
                   0.82    1.00    -0.54   0.88      0.41
                   →+0             →+0     →+0

dist_cap           ████    ████    ████    ████      ████
                  -0.71   -0.54   1.00    -0.68     -0.83
                  B→A+2    →+0              →+0      →+0

industry_sales     ████    ████    ████    ████      ████
                   0.94    0.88   -0.68    1.00      0.59
                   →+0     →+0     →+0              →+0

fill_rate          ████    ████    ████    ████      ████
                   0.65    0.41   -0.83    0.59      1.00
                  B→A+1    →+0     →+0     →+0

Cell colours:
  Deep blue  = strong positive  (r ≥ 0.7)
  Mid blue   = moderate positive (r 0.4–0.7)
  White      = negligible
  Mid red    = moderate negative (r -0.4 to -0.7)
  Deep red   = strong negative  (r ≤ -0.7)
  ▨ stripe   = is_stable: false (correlation recently broke down)

Cell annotation format:
  Top row:    r value
  Bottom row: lag direction (→+0 = concurrent, A→B+2 = A leads B by 2 periods)
```

**amCharts 5 implementation:**

```javascript
// amCharts 5 — correlation_heatmap
// Uses XYChart with CategoryAxis on both axes + ColumnSeries heat-mapped by pearson_r

const root = am5.Root.new("chart-heatmap");
root.setThemes([am5themes_Animated.new(root)]);

const chart = root.container.children.push(
  am5xy.XYChart.new(root, {
    panX: false, panY: false,
    layout: root.verticalLayout,
  })
);

// Category axes — one per metric on X and Y
const yAxis = chart.yAxes.push(
  am5xy.CategoryAxis.new(root, {
    categoryField: "metric_a",
    renderer: am5xy.AxisRendererY.new(root, { inversed: true, minGridDistance: 30 }),
  })
);
const xAxis = chart.xAxes.push(
  am5xy.CategoryAxis.new(root, {
    categoryField: "metric_b",
    renderer: am5xy.AxisRendererX.new(root, { minGridDistance: 30 }),
  })
);
xAxis.get("renderer").labels.template.setAll({ rotation: -30, centerY: am5.p50 });

// ── ColumnSeries for the heatmap cells ──────────────────────────────────────
const heatSeries = chart.series.push(
  am5xy.ColumnSeries.new(root, {
    xAxis, yAxis,
    categoryXField: "metric_b",
    categoryYField: "metric_a",
    valueField: "pearson_r",
    tooltip: am5.Tooltip.new(root, {
      labelText: "{metric_a} ↔ {metric_b}\nr = {pearson_r}  ({strength_label})\n{lag_label}",
    }),
  })
);

heatSeries.columns.template.setAll({
  strokeOpacity: 0,
  width: am5.percent(100),
  height: am5.percent(100),
  tooltipY: am5.percent(50),
  templateField: "columnSettings",   // allows per-cell fill colour
});

// ── HeatLegend ───────────────────────────────────────────────────────────────
const heatLegend = chart.bottomAxesContainer.children.push(
  am5xy.HeatLegend.new(root, {
    orientation: "horizontal",
    startValue: -1,
    endValue:    1,
    startColor:  am5.color("#991B1B"),   // strong negative
    endColor:    am5.color("#1D4ED8"),   // strong positive
  })
);

// ── Colour mapping ────────────────────────────────────────────────────────────
// Each cell's columnSettings.fill is pre-computed from pearson_r by the backend
// Color scale:
//   r ≤ -0.7  →  #991B1B  (strong negative, deep red)
//   r ≤ -0.4  →  #FCA5A5  (moderate negative, light red)
//   |r| < 0.2 →  #F8FAFC  (negligible, near-white)
//   r ≥  0.4  →  #93C5FD  (moderate positive, light blue)
//   r ≥  0.7  →  #1D4ED8  (strong positive, deep blue)
//
// Cells where is_stable=false get a custom stroke (striped appearance):
//   strokeDasharray: [3,3], stroke: "#94A3B8", strokeWidth: 1.5

// ── Feed data ─────────────────────────────────────────────────────────────────
// Each data item: { metric_a, metric_b, pearson_r, strength_label, lag_label,
//                   is_stable, columnSettings: { fill: am5.color("..."), ... } }
heatSeries.data.setAll(heatmapCells);
yAxis.data.setAll(metrics.map(m => ({ metric_a: m })));
xAxis.data.setAll(metrics.map(m => ({ metric_b: m })));
```

**Stored chart_spec:**
```json
{
  "library": "amcharts5",
  "chart_type": "correlation_heatmap",
  "title": "KPI Correlation Matrix",
  "metrics": ["daily_sales", "target_qty", "distributor_capacity", "industry_sales", "fill_rate"],
  "color_scale": {
    "strong_negative":   "#991B1B",
    "moderate_negative": "#FCA5A5",
    "negligible":        "#F8FAFC",
    "moderate_positive": "#93C5FD",
    "strong_positive":   "#1D4ED8"
  },
  "cells": [
    {
      "metric_a": "daily_sales", "metric_b": "distributor_capacity",
      "pearson_r": -0.71, "strength_label": "strong", "direction_label": "negative",
      "best_lag": 2, "lag_direction": "b_leads_a",
      "lag_label": "dist_cap leads daily_sales by 2 months",
      "is_stable": true, "fill_color": "#991B1B"
    }
  ]
}
```

---

### Chart 4: Scatter + Regression (per correlated pair)

One chart per top correlated pair (up to 10). Shows the scatter of metric A values vs metric B
values (at the optimal lag), with the regression line, R² value, and interpretation text.

```
daily_sales vs distributor_capacity
(distributor_capacity leads daily_sales by 2 months, r = -0.71)

dist_cap
(t)
1200 │  ●
1100 │     ●  ●
1000 │       ●   ●
 900 │          ●  ●  ●
 800 │            ●      ●
 700 │                ●    ●
     └──────────────────────────── daily_sales (t+2)
        1600  1700  1800  1900  2000  2100

  ───  Regression line
  ● ●  Observed data points (one per period)

  R² = 0.50  │  slope = -0.38  │  p < 0.001  │  n = 18 periods

Interpretation label (generated by narrate step):
  "For every 100-unit drop in distributor capacity, daily sales falls
   approximately 38 units two months later."
```

**amCharts 5 implementation:**

```javascript
// amCharts 5 — scatter_regression
// LineSeries in scatter mode (no stroke) for points + LineSeries for regression line

const root = am5.Root.new("chart-scatter-daily_sales-distributor_capacity");
root.setThemes([am5themes_Animated.new(root)]);
const chart = root.container.children.push(am5xy.XYChart.new(root, { panX: true, panY: true }));

// X axis — daily_sales (lagged)
const xAxis = chart.xAxes.push(
  am5xy.ValueAxis.new(root, {
    renderer: am5xy.AxisRendererX.new(root, {}),
    tooltip: am5.Tooltip.new(root, {}),
  })
);
// Y axis — distributor_capacity
const yAxis = chart.yAxes.push(
  am5xy.ValueAxis.new(root, {
    renderer: am5xy.AxisRendererY.new(root, {}),
  })
);

// ── Scatter series (points only, no connecting line) ─────────────────────────
const scatterSeries = chart.series.push(
  am5xy.LineSeries.new(root, {
    name: "Observed periods",
    xAxis, yAxis,
    valueXField: "x",        // daily_sales lagged value
    valueYField: "y",        // distributor_capacity value
    strokeOpacity: 0,        // no line between points
    tooltip: am5.Tooltip.new(root, {
      labelText: "{period}\ndaily_sales(t+2): {x}\ndist_cap(t): {y}",
    }),
  })
);
scatterSeries.bullets.push(root =>
  am5.Bullet.new(root, {
    sprite: am5.Circle.new(root, { radius: 5, fill: am5.color("#2563EB"), fillOpacity: 0.7 }),
  })
);

// ── Regression line ───────────────────────────────────────────────────────────
// Compute regression line endpoints from slope + intercept
// y = intercept + slope * x
const xMin = Math.min(...scatterData.map(d => d.x));
const xMax = Math.max(...scatterData.map(d => d.x));
const regressionPoints = [
  { x: xMin, y: intercept + slope * xMin },
  { x: xMax, y: intercept + slope * xMax },
];

const regressionSeries = chart.series.push(
  am5xy.LineSeries.new(root, {
    name: `Regression  R²=${rSquared.toFixed(2)}`,
    xAxis, yAxis,
    valueXField: "x",
    valueYField: "y",
    stroke: am5.color("#EF4444"),
    strokeWidth: 2,
    strokeDasharray: [6, 3],
  })
);
regressionSeries.data.setAll(regressionPoints);

// ── Annotation label (R², slope, interpretation) ─────────────────────────────
chart.plotContainer.children.push(
  am5.Label.new(root, {
    text: `R² = ${rSquared}  |  slope = ${slope}  |  p < 0.001  |  n = ${n}\n${interpretation}`,
    x: am5.percent(5),
    y: am5.percent(5),
    fontSize: 11,
    fill: am5.color("#475569"),
  })
);

chart.children.push(am5.Legend.new(root, { centerX: am5.p50, x: am5.p50 }));
scatterSeries.data.setAll(scatterData);
```

**Stored chart_spec:**
```json
{
  "library": "amcharts5",
  "chart_type": "scatter_regression",
  "title": "daily_sales vs distributor_capacity (dist_cap leads by 2m)",
  "metric_a": "daily_sales",
  "metric_b": "distributor_capacity",
  "best_lag": 2,
  "lag_direction": "b_leads_a",
  "pearson_r": -0.71,
  "r_squared": 0.504,
  "slope": -0.38,
  "intercept": 1285.4,
  "p_value": 0.00041,
  "n": 18,
  "interpretation": "For every 100-unit drop in distributor capacity, daily sales falls ~38 units 2 months later.",
  "data_points": [{ "x": 1842.3, "y": 1180.0, "period": "2025-06-01" }]
}
```

---

### Chart 5: Rolling Correlation

Shows how the correlation r between a metric pair has evolved over time. Reveals whether a
relationship is stable, strengthening, weakening, or has recently broken down.

```
Rolling Correlation — daily_sales vs distributor_capacity
(12-month rolling window)

 1.0 │
 0.5 │
 0.0 │───────────────────────────────────────────────
-0.5 │          ╲
-0.7 │─ ─ ─ ─ ─ ─╲─ ─ ─ ─ ─ ─ ─ ─ ─ ─  (threshold)
-0.8 │             ╲─────────╲
-0.9 │                        ╲──────────────────────
-1.0 │
     └──────────────────────────────────────────────
      Jun  Jul  Aug  Sep  Oct  Nov  Dec  Jan  Feb  Mar

  ─── Rolling Pearson r (12m window)
  ─ ─ Strength threshold (±0.7)
  ●   Period where is_stable flipped to false
```

**amCharts 5 implementation:**

```javascript
// amCharts 5 — rolling_correlation
// LineSeries for rolling r + AxisDataItem range bands for threshold zones

const root = am5.Root.new("chart-rolling-corr-daily_sales-dist_cap");
root.setThemes([am5themes_Animated.new(root)]);
const chart = root.container.children.push(
  am5xy.XYChart.new(root, { panX: true, wheelX: "panX", wheelY: "zoomX" })
);

const xAxis = chart.xAxes.push(
  am5xy.DateAxis.new(root, {
    baseInterval: { timeUnit: "month", count: 1 },
    renderer: am5xy.AxisRendererX.new(root, {}),
  })
);
const yAxis = chart.yAxes.push(
  am5xy.ValueAxis.new(root, {
    min: -1, max: 1,
    strictMinMax: true,
    renderer: am5xy.AxisRendererY.new(root, {}),
  })
);

// ── Threshold reference band: strong zone (|r| ≥ 0.7) ───────────────────────
// Upper strong zone (r ≥ 0.7)
const upperStrong = yAxis.makeDataItem({ value: 0.7, endValue: 1.0 });
yAxis.createAxisRange(upperStrong);
upperStrong.get("axisFill").setAll({ fill: am5.color("#DBEAFE"), fillOpacity: 0.3, visible: true });
upperStrong.get("grid").setAll({ stroke: am5.color("#2563EB"), strokeDasharray: [4, 4] });
upperStrong.get("label").setAll({ text: "Strong (+0.7)", fill: am5.color("#2563EB"), location: 1 });

// Lower strong zone (r ≤ -0.7)
const lowerStrong = yAxis.makeDataItem({ value: -1.0, endValue: -0.7 });
yAxis.createAxisRange(lowerStrong);
lowerStrong.get("axisFill").setAll({ fill: am5.color("#FEE2E2"), fillOpacity: 0.3, visible: true });
lowerStrong.get("grid").setAll({ stroke: am5.color("#EF4444"), strokeDasharray: [4, 4] });
lowerStrong.get("label").setAll({ text: "Strong (-0.7)", fill: am5.color("#EF4444"), location: 0 });

// Zero reference line
const zeroRange = yAxis.makeDataItem({ value: 0 });
yAxis.createAxisRange(zeroRange);
zeroRange.get("grid").setAll({ stroke: am5.color("#94A3B8"), strokeWidth: 1 });

// ── Rolling r line ────────────────────────────────────────────────────────────
const rollingSeries = chart.series.push(
  am5xy.LineSeries.new(root, {
    name: "Rolling r (12m window)",
    xAxis, yAxis,
    valueXField: "period",
    valueYField: "r_value",
    stroke: am5.color("#2563EB"),
    strokeWidth: 2,
    tooltip: am5.Tooltip.new(root, { labelText: "{valueX.formatDate()}: r = {valueY}" }),
  })
);

// ── Stability event markers (is_stable flipped to false) ─────────────────────
rollingSeries.bullets.push((root, series, dataItem) => {
  if (!dataItem.dataContext.stability_event) return undefined;
  return am5.Bullet.new(root, {
    sprite: am5.Circle.new(root, {
      radius: 6,
      fill: am5.color("#F59E0B"),
      stroke: am5.color("#FFFFFF"),
      strokeWidth: 1.5,
      tooltipText: "Correlation weakened\nr = {r_value}",
      tooltip: am5.Tooltip.new(root, {}),
    }),
  });
});

rollingSeries.data.setAll(rollingData);
// rollingData shape: [{ period: timestamp_ms, r_value: -0.81, stability_event: false }, ...]
```

**Stored chart_spec:**
```json
{
  "library": "amcharts5",
  "chart_type": "rolling_correlation",
  "title": "Rolling Correlation: daily_sales ↔ distributor_capacity",
  "metric_a": "daily_sales",
  "metric_b": "distributor_capacity",
  "window_periods": 12,
  "threshold_strong": 0.7,
  "stability_events": [
    { "period": "2025-10-01", "r_value": -0.62, "stability_event": true, "label": "Correlation weakened" }
  ],
  "data": [
    { "period": "2025-06-01", "r_value": -0.81, "stability_event": false },
    { "period": "2025-07-01", "r_value": -0.79, "stability_event": false }
  ]
}
```

---

### Chart 6: Anomaly Density Bar

Bar chart of anomaly event count per period across all metrics in the domain. Reveals whether
anomalies are clustering (triggering `accumulation_alert`) or dispersed (healthy baseline noise).

```
Anomaly Events per Month — market_performance_analysis

6 │                                          ████
5 │                                     ████ ████
4 │                                ████ ████ ████
3 │                           ████ ████ ████ ████
2 │            ████ ████ ████ ████ ████ ████ ████
1 │ ████ ████  ████ ████ ████ ████ ████ ████ ████
  └─────────────────────────────────────────────
   Jun  Jul  Aug  Sep  Oct  Nov  Dec  Jan  Feb  Mar
                                             ↑
                               accumulation_alert fires here

Bar segments (stacked by anomaly class):
  ████  spike      (#F97316)
  ████  drop       (#EF4444)
  ████  drift      (#EAB308)
  ████  step_change (#8B5CF6)

Reference line: average anomaly density (dashed)
Alert line: 2× average density = accumulation_alert threshold
```

**amCharts 5 implementation:**

```javascript
// amCharts 5 — anomaly_density
// Stacked ColumnSeries × 4 anomaly classes + AxisDataItem reference lines

const root = am5.Root.new("chart-anomaly-density");
root.setThemes([am5themes_Animated.new(root)]);
const chart = root.container.children.push(
  am5xy.XYChart.new(root, { layout: root.verticalLayout })
);

const xAxis = chart.xAxes.push(
  am5xy.DateAxis.new(root, {
    baseInterval: { timeUnit: "month", count: 1 },
    renderer: am5xy.AxisRendererX.new(root, {}),
  })
);
const yAxis = chart.yAxes.push(
  am5xy.ValueAxis.new(root, { renderer: am5xy.AxisRendererY.new(root, {}) })
);

// ── Reference lines on Y axis ─────────────────────────────────────────────────
// Average density line
const avgRange = yAxis.makeDataItem({ value: avgDensity });
yAxis.createAxisRange(avgRange);
avgRange.get("grid").setAll({ stroke: am5.color("#94A3B8"), strokeDasharray: [4, 4], strokeWidth: 1 });
avgRange.get("label").setAll({ text: `Avg (${avgDensity})`, fill: am5.color("#94A3B8"), location: 1 });

// Accumulation alert threshold (2× average)
const alertRange = yAxis.makeDataItem({ value: alertThreshold });
yAxis.createAxisRange(alertRange);
alertRange.get("grid").setAll({ stroke: am5.color("#EF4444"), strokeDasharray: [6, 3], strokeWidth: 1.5 });
alertRange.get("label").setAll({ text: `Alert threshold (${alertThreshold})`, fill: am5.color("#EF4444"), location: 1 });

// ── Helper: create one stacked ColumnSeries per anomaly class ─────────────────
const anomalyClasses = [
  { field: "spike_count",  label: "Spike",       color: "#F97316" },
  { field: "drop_count",   label: "Drop",        color: "#EF4444" },
  { field: "drift_count",  label: "Drift",       color: "#EAB308" },
  { field: "step_count",   label: "Step Change", color: "#8B5CF6" },
];

anomalyClasses.forEach(({ field, label, color }) => {
  const series = chart.series.push(
    am5xy.ColumnSeries.new(root, {
      name: label,
      xAxis, yAxis,
      valueXField: "period",
      valueYField: field,
      stacked: true,
      fill: am5.color(color),
      stroke: am5.color(color),
      tooltip: am5.Tooltip.new(root, { labelText: `${label}: {valueY}` }),
    })
  );
  // Highlight alert periods with a brighter stroke
  series.columns.template.adapters.add("stroke", (stroke, target) => {
    const period = target.dataItem?.get("valueX");
    return alertPeriods.includes(new Date(period).toISOString().slice(0, 7))
      ? am5.color("#1E293B")
      : stroke;
  });
  series.columns.template.adapters.add("strokeWidth", (w, target) => {
    const period = target.dataItem?.get("valueX");
    return alertPeriods.includes(new Date(period).toISOString().slice(0, 7)) ? 2 : 0;
  });
  series.data.setAll(densityData);
});

// ── Legend ────────────────────────────────────────────────────────────────────
chart.children.push(am5.Legend.new(root, { centerX: am5.p50, x: am5.p50 }));
```

**Stored chart_spec:**
```json
{
  "library": "amcharts5",
  "chart_type": "anomaly_density",
  "title": "Anomaly Density by Period",
  "avg_density": 2.1,
  "alert_threshold": 4.2,
  "alert_periods": ["2026-02-01", "2026-03-01"],
  "series": [
    { "field": "spike_count",  "label": "Spike",       "color": "#F97316", "stacked": true },
    { "field": "drop_count",   "label": "Drop",        "color": "#EF4444", "stacked": true },
    { "field": "drift_count",  "label": "Drift",       "color": "#EAB308", "stacked": true },
    { "field": "step_count",   "label": "Step Change", "color": "#8B5CF6", "stacked": true }
  ],
  "data": [
    { "period": "2025-06-01", "spike_count": 1, "drop_count": 0, "drift_count": 0, "step_count": 0 },
    { "period": "2026-02-01", "spike_count": 1, "drop_count": 2, "drift_count": 3, "step_count": 0 }
  ]
}
```

---

## Architecture

### New Agent: `CorrelationIntelligenceAgent`

Runs as a standalone LangGraph node, callable:
1. **Post-deployment** — automatically triggered after a canonical agentic run certifies KPIs.
2. **On-demand** — triggered by a `/analysis/correlation` API call from the workspace UI.
3. **Scheduled** — optionally via a background job on a configurable cadence (daily/weekly).

```
Input state:
  tenant_id, domain_id, run_id
  kpi_snapshot: list of {metric_name, time_col, value_col, dimension_col, sql, data}
  analysis_mode: "full" | "anomaly_only" | "correlation_only" | "forecast_only"
  periods_back: int  (default 90 days / 12 periods depending on grain)
  forecast_periods: int  (default 12)

Output state:
  anomaly_results: list[AnomalyResult]
  correlation_matrix: dict[pair_key, CorrelationResult]
  investigation_threads: list[InvestigationThread]
  forward_projections: list[ForwardProjection]
  chart_specs: list[ChartSpec]
  summary_text: str
  summary_html: str
```

### Data Flow

```
CertifiedKPIs (from run)
    │
    ▼
[StatisticalAnomalyScorer]     ← Query Pattern 1+2 → Z, IQR, CUSUM per metric
    │
    ▼
[CorrelationMatrixBuilder]     ← Query Pattern 4 → Pearson, Spearman, lagged r for all KPI pairs
    │
    ▼
[InvestigationThreadBuilder]   ← links anomalies + correlations + dimension drill-down
    │
    ▼
[ForwardProjectionEngine]      ← STL decomposition + trend extrapolation + confidence bands
    │
    ▼
[AnomalyDensityChecker]        ← Query Pattern 3 → fires accumulation_alert if density rising
    │
    ▼
[ChartSpecGenerator]           ← produces all 6 chart specs
    │
    ▼
[LLMNarrativeBuilder]          ← converts statistical outputs into summary_text + summary_html
    │
    ▼
[PersistenceWriter]            ← writes to quantyx_correlation_runs + child tables
```

---

## New Tables

### `quantyx_correlation_runs`

Top-level run record for each correlation analysis.

```sql
CREATE TABLE IF NOT EXISTS public.quantyx_correlation_runs (
  correlation_run_id  TEXT PRIMARY KEY,
  tenant_id           TEXT NOT NULL,
  domain_id           TEXT NOT NULL,
  run_id              TEXT NOT NULL,          -- linked agentic run
  analysis_mode       TEXT NOT NULL DEFAULT 'full',
  status              TEXT NOT NULL DEFAULT 'pending',
  periods_back        INT  NOT NULL DEFAULT 90,
  forecast_periods    INT  NOT NULL DEFAULT 12,
  metric_count        INT  NULL,
  anomaly_count       INT  NULL,
  correlation_pair_count INT NULL,
  thread_count        INT  NULL,
  error_message       TEXT NULL,
  triggered_by        TEXT NULL,              -- 'post_deployment' | 'on_demand' | 'scheduled'
  started_at          TIMESTAMPTZ NULL,
  completed_at        TIMESTAMPTZ NULL,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_correlation_runs_scope
  ON public.quantyx_correlation_runs (tenant_id, domain_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_correlation_runs_run
  ON public.quantyx_correlation_runs (run_id, created_at DESC);
```

---

### `quantyx_anomaly_results`

Per-metric anomaly scoring output.

```sql
CREATE TABLE IF NOT EXISTS public.quantyx_anomaly_results (
  anomaly_id          TEXT PRIMARY KEY,
  correlation_run_id  TEXT NOT NULL,
  tenant_id           TEXT NOT NULL,
  domain_id           TEXT NOT NULL,
  metric_name         TEXT NOT NULL,
  anomaly_class       TEXT NOT NULL,          -- spike | drop | drift_up | drift_down | step_change
  anomaly_score       NUMERIC(6,4) NOT NULL,  -- composite [0,1]
  z_score             NUMERIC(8,4) NULL,
  iqr_flag            BOOLEAN NOT NULL DEFAULT false,
  cusum_signal        BOOLEAN NOT NULL DEFAULT false,
  detected_at         TIMESTAMPTZ NOT NULL,   -- time point of anomaly
  period_label        TEXT NULL,              -- human label e.g. "Mar 2026 Week 2"
  baseline_value      NUMERIC NULL,
  observed_value      NUMERIC NULL,
  deviation_pct       NUMERIC(8,2) NULL,
  top_dimension       TEXT NULL,              -- dimension that concentrates the anomaly
  top_dimension_value TEXT NULL,
  dimension_pct       NUMERIC(6,2) NULL,      -- % of total deviation explained by that slice
  stats_json          JSONB NULL,             -- full statistical detail
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_anomaly_results_run
  ON public.quantyx_anomaly_results (correlation_run_id, anomaly_score DESC);

CREATE INDEX IF NOT EXISTS idx_anomaly_results_metric
  ON public.quantyx_anomaly_results (tenant_id, domain_id, metric_name, detected_at DESC);
```

---

### `quantyx_correlation_pairs`

Cross-metric correlation results.

```sql
CREATE TABLE IF NOT EXISTS public.quantyx_correlation_pairs (
  pair_id             TEXT PRIMARY KEY,
  correlation_run_id  TEXT NOT NULL,
  tenant_id           TEXT NOT NULL,
  domain_id           TEXT NOT NULL,
  metric_a            TEXT NOT NULL,
  metric_b            TEXT NOT NULL,
  pearson_r           NUMERIC(6,4) NULL,
  spearman_rho        NUMERIC(6,4) NULL,
  best_lag            INT  NULL,              -- lag in periods at which |r| is maximised
  lagged_r            NUMERIC(6,4) NULL,      -- r at best_lag
  lag_direction       TEXT NULL,              -- 'a_leads_b' | 'b_leads_a' | 'concurrent'
  strength_label      TEXT NOT NULL,          -- strong | moderate | weak | negligible
  direction_label     TEXT NOT NULL,          -- positive | negative
  sample_size         INT  NULL,
  p_value             NUMERIC(10,6) NULL,
  is_stable           BOOLEAN NOT NULL DEFAULT true,  -- false = correlation has recently broken down
  rolling_r_json      JSONB NULL,             -- rolling r values over time
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_correlation_pairs_run
  ON public.quantyx_correlation_pairs (correlation_run_id, ABS(pearson_r) DESC);

CREATE UNIQUE INDEX IF NOT EXISTS uq_correlation_pairs_run_metrics
  ON public.quantyx_correlation_pairs (correlation_run_id, metric_a, metric_b);
```

---

### `quantyx_investigation_threads`

Linked anomaly + correlation evidence chains.

```sql
CREATE TABLE IF NOT EXISTS public.quantyx_investigation_threads (
  thread_id           TEXT PRIMARY KEY,
  correlation_run_id  TEXT NOT NULL,
  tenant_id           TEXT NOT NULL,
  domain_id           TEXT NOT NULL,
  trigger_metric      TEXT NOT NULL,
  trigger_anomaly_id  TEXT NOT NULL,
  evidence_chain      JSONB NOT NULL,         -- ordered list of {metric, anomaly_id, pair_id, score}
  leading_dimension   TEXT NULL,
  leading_dim_value   TEXT NULL,
  confidence          NUMERIC(6,4) NOT NULL,
  suggested_focus     JSONB NULL,             -- top 2-3 next investigation areas
  narrative_text      TEXT NULL,
  narrative_html      TEXT NULL,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_investigation_threads_run
  ON public.quantyx_investigation_threads (correlation_run_id, confidence DESC);
```

---

### `quantyx_forward_projections`

Trend projections per metric.

```sql
CREATE TABLE IF NOT EXISTS public.quantyx_forward_projections (
  projection_id       TEXT PRIMARY KEY,
  correlation_run_id  TEXT NOT NULL,
  tenant_id           TEXT NOT NULL,
  domain_id           TEXT NOT NULL,
  metric_name         TEXT NOT NULL,
  forecast_periods    INT  NOT NULL,
  trend_direction     TEXT NOT NULL,          -- up | down | flat
  trend_slope         NUMERIC NULL,           -- units per period
  seasonality_present BOOLEAN NOT NULL DEFAULT false,
  inflection_signal   TEXT NULL,              -- convergence_alert | accumulation_alert | reversal_signal | on_track
  inflection_detail   TEXT NULL,
  projection_json     JSONB NOT NULL,         -- [{period, point_estimate, lower_1sigma, upper_1sigma, lower_2sigma, upper_2sigma, is_forecast}]
  anomaly_density_trend TEXT NULL,            -- increasing | stable | decreasing
  chart_spec          JSONB NULL,             -- forecast chart spec for frontend
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_forward_projections_run
  ON public.quantyx_forward_projections (correlation_run_id, metric_name);
```

---

## New Python Module: `services/ai/correlation_agent.py`

### Key functions

The two data-loading helpers below are the only functions that touch `quantyx_chart_requests`.
All functions below them operate on plain Python lists — no table names, column names, or
tenant-specific SQL appear anywhere in the statistical engine.

```python
def _detect_period_column(row: dict) -> str | None:
    """
    Auto-detect the period column from a single result row.
    Checks key names against a set of common time-dimension words first,
    then falls back to scanning values for ISO date patterns.
    Returns None if no period column can be identified.
    No table names or column names are hardcoded.
    """


def load_kpi_snapshots(
    settings: Settings,
    tenant_id: str,
    domain_id: str,
    run_id: str | None = None,
) -> list[dict]:
    """
    Load certified KPI time series for a tenant/domain from quantyx_chart_requests.

    Scoping:
    - Primary: filter by run_id when provided (exact deployment run match).
      quantyx_chart_requests.run_id is populated by agentic_orchestrator at chart
      creation time, so the post-deployment trigger always has it.
    - Fallback: if run_id is None (e.g. on-demand call without a run context),
      scope by tenant_id + domain_id and take one snapshot per metric_name
      ordered by created_at DESC (newest chart wins).

    Returns one snapshot per unique metric_name.

    Each snapshot shape:
      {
        metric_name:   str,          # from query_payload["metrics"][0]
        period_col:    str,          # auto-detected
        value_col:     str,          # same as metric_name
        dimension_col: str | None,   # first categorical dimension
        series:        [{period, value}],  # sorted asc, values as float
        rows_json:     list[dict],   # full rows for dimension drill-down
        chart_id:      str,
      }

    Skips charts with: no rows_json, no detectable period column, < 5 data points.
    """


def extract_dimension_breakdown(
    snapshot: dict,
    anomaly_period: str,
) -> list[dict]:
    """
    Derive dimension concentration for an anomaly period from snapshot["rows_json"].
    No SQL query is issued — uses rows already stored with the chart.
    Matches on YYYY-MM prefix so daily and monthly grains both work.

    Returns [{dim_value, metric_value, pct}] sorted by metric_value descending.
    Returns [] if no dimension_col or no matching rows.
    """


def run_correlation_intelligence(
    settings: Settings,
    tenant_id: str,
    domain_id: str,
    run_id: str,
    analysis_mode: str = "full",      # "full" | "anomaly_only" | "correlation_only" | "forecast_only"
    forecast_periods: int = 12,
    triggered_by: str = "on_demand",  # "post_deployment" | "on_demand" | "scheduled"
) -> dict:
    """
    Entry point. Loads KPI snapshots from quantyx_chart_requests by tenant_id + domain_id,
    runs all statistical sub-steps, persists results, returns correlation_run record.

    KPI data is sourced generically via load_kpi_snapshots() — no table names,
    column names, or tenant-specific SQL is referenced here or in any sub-step.
    """


def score_anomalies(
    metric_name: str,
    series: list[float],
    timestamps: list[str],
    dimension_breakdown: list[dict] | None = None,
) -> list[AnomalyResult]:
    """
    Computes Z-score, IQR fence, and CUSUM for a time series.
    Returns one AnomalyResult per detected anomaly point.
    If dimension_breakdown is provided, identifies the top contributing slice.

    Example output (field names are fixed; values are tenant-specific at runtime):
      AnomalyResult(
        metric_name=<from snapshot["metric_name"]>,
        anomaly_class="drop",
        anomaly_score=0.91,
        z_score=-3.4,
        iqr_flag=True,
        cusum_signal=True,
        detected_at=<period string from series>,
        baseline_value=<rolling mean>,
        observed_value=<actual value at anomaly point>,
        deviation_pct=-9.15,
        top_dimension=<snapshot["dimension_col"]>,       # auto-detected, not hardcoded
        top_dimension_value=<top slice from extract_dimension_breakdown()>,
        dimension_pct=87.2,
      )
    """


def build_correlation_matrix(
    kpi_snapshots: list[dict],
    max_lag: int = 6,
) -> list[CorrelationPair]:
    """
    Computes Pearson, Spearman, and lagged r for every (A, B) metric pair.
    Returns the upper triangle only (A < B lexicographically).
    Prunes pairs with |pearson_r| < 0.2 (negligible) before returning.

    Uses lagged_correlation() helper to find the lag offset with maximum |r|.
    """


def lagged_correlation(
    series_a: list[float],
    series_b: list[float],
    max_lag: int = 6,
) -> tuple[float, int]:
    """
    Returns (best_r, best_lag) where best_lag is the offset in periods
    at which the absolute Pearson r is maximised.

    Positive lag = A leads B (shift A backward, align with future B).
    Negative lag = B leads A.

    Implementation:
      for lag in range(-max_lag, max_lag + 1):
        align arrays at this offset
        compute pearson_r
        track maximum |r|
    """


def build_investigation_threads(
    anomaly_results: list[AnomalyResult],
    correlation_pairs: list[CorrelationPair],
    min_confidence: float = 0.4,
) -> list[InvestigationThread]:
    """
    For each anomaly with score >= min_confidence:
      1. Find all correlation pairs involving the trigger metric.
      2. For each correlated metric, check if it also has a co-occurring anomaly.
      3. If lag_direction indicates the correlated metric leads the trigger,
         check whether its anomaly preceded the trigger anomaly by ~lag periods.
      4. Build an ordered evidence_chain with per-link scores.
      5. Composite confidence = weighted mean of link scores.

    Evidence chain example:
      [
        {"metric": "distributor_capacity", "anomaly_class": "drift_down",
         "anomaly_score": 0.74, "r": -0.71, "lag": 2, "precedes_trigger": true, "link_score": 0.89},
        {"metric": "fill_rate", "anomaly_class": "drop",
         "anomaly_score": 0.61, "r": -0.83, "lag": 1, "precedes_trigger": true, "link_score": 0.72}
      ]
    """


def project_forward(
    metric_name: str,
    series: list[float],
    timestamps: list[str],
    forecast_periods: int = 12,
    anomaly_results: list[AnomalyResult] | None = None,
) -> ForwardProjection:
    """
    1. STL decomposition via statsmodels.tsa.seasonal.STL
       (period = 12 for monthly, 52 for weekly, inferred from timestamp spacing)
    2. Extract trend component T, seasonal component S, residual R
    3. Fit linear regression on T to get slope + intercept
    4. Project T forward: T_proj[t] = intercept + slope * (n + t)
    5. Project S forward: S_proj[t] = S[t % seasonal_period]
    6. Point estimate: T_proj[t] + S_proj[t]
    7. σ_residual = rolling std of R over last min(12, len(R)) periods
    8. Confidence bands: point_estimate ± k * σ_residual  (k=1, k=2)
    9. Compute inflection_signal:
       - reversal_signal   if sign(slope) != sign(T[-1] - T[-3])
       - accumulation_alert if anomaly_density rising over last 3 periods
       - on_track          otherwise
    """


def generate_correlation_charts(
    kpi_snapshots: list[dict],
    anomaly_results: list[AnomalyResult],
    correlation_pairs: list[CorrelationPair],
    forward_projections: list[ForwardProjection],
    anomaly_density: list[dict],
    top_n_pairs: int = 10,
) -> list[dict]:
    """
    Returns a list of chart spec dicts, one per chart:
    - forecast_band        per metric with projection data
    - anomaly_timeline     per metric with >= 1 anomaly
    - correlation_heatmap  one for the domain (all certified KPI pairs)
    - scatter_regression   for the top_n_pairs strongest correlated pairs
    - rolling_correlation  for the top_n_pairs strongest correlated pairs
    - anomaly_density      one for the domain
    """


def narrate_correlation_results(
    anomaly_results: list[AnomalyResult],
    correlation_pairs: list[CorrelationPair],
    investigation_threads: list[InvestigationThread],
    forward_projections: list[ForwardProjection],
    domain_id: str,
    tenant_context: str | None = None,
) -> dict:
    """
    LLM call (single prompt) that takes the top anomalies, strongest correlation pairs,
    highest-confidence investigation threads, and inflection signals as structured input,
    and returns:
      - executive_bullets: list of 3-5 plain-English bullet points
      - summary_text: paragraph form narrative
      - summary_html: HTML-formatted version of summary_text
      - forward_outlook: 2-3 sentence forward-looking statement per inflection signal
    """
```

---

## New Store: `services/ai/correlation_store.py`

```python
def create_correlation_run(settings, *, tenant_id, domain_id, run_id, analysis_mode, ...) -> dict
def update_correlation_run(settings, correlation_run_id, *, status, metric_count, ...) -> dict
def get_correlation_run(settings, correlation_run_id) -> dict | None
def list_correlation_runs(settings, tenant_id, domain_id, limit=20, offset=0) -> list[dict]
def insert_anomaly_results(settings, correlation_run_id, results: list[dict]) -> None
def insert_correlation_pairs(settings, correlation_run_id, pairs: list[dict]) -> None
def insert_investigation_threads(settings, correlation_run_id, threads: list[dict]) -> None
def insert_forward_projections(settings, correlation_run_id, projections: list[dict]) -> None
def get_latest_correlation_run_results(settings, tenant_id, domain_id) -> dict
    """
    Returns the most recent completed run with all child results joined.
    Shape:
      {
        correlation_run_id, status, completed_at,
        anomaly_results: [...],
        correlation_pairs: [...],
        investigation_threads: [...],
        forward_projections: [...],    # each includes chart_spec
        summary_text, summary_html
      }
    """
```

---

## API Routes — `services/api/main.py`

All routes under `/analysis/`.

---

### `POST /analysis/correlation`

Trigger a correlation intelligence run on demand.

Request:
```json
{
  "tenant_id": "<tenant_id>",
  "domain_id": "<domain_id>",
  "run_id": "<run_id>",
  "analysis_mode": "full",
  "periods_back": 90,
  "forecast_periods": 12
}
```

Response `202`:
```json
{
  "correlation_run_id": "corr_7f8a9b0c1d",
  "status": "running",
  "tenant_id": "<tenant_id>",
  "domain_id": "<domain_id>",
  "run_id": "<run_id>"
}
```

---

### `GET /analysis/correlation/{correlation_run_id}`

Get full results of a correlation run.

Response includes: `anomaly_results`, `correlation_matrix`, `investigation_threads`,
`forward_projections`, `chart_specs`, `summary_text`, `summary_html`.

---

### `GET /analysis/correlation/latest`

Get the latest completed correlation run for a `tenant_id` + `domain_id`.

Query params: `tenant_id`, `domain_id`

---

### `GET /analysis/correlation/{correlation_run_id}/anomalies`

List anomaly results for a run. Sortable by `anomaly_score`, `detected_at`, `metric_name`.

---

### `GET /analysis/correlation/{correlation_run_id}/pairs`

List correlation pairs. Filterable by `metric_a`, `metric_b`, `strength_label`, `min_r`.

---

### `GET /analysis/correlation/{correlation_run_id}/threads`

List investigation threads, sorted by `confidence DESC`.

---

### `GET /analysis/correlation/{correlation_run_id}/projections`

List forward projections. Includes `chart_spec` for each metric's forecast chart.

---

### `GET /analysis/correlation/{correlation_run_id}/stream`

SSE stream that emits progress events as the correlation agent runs:

```
event: anomaly_scored   data: {"metric": "daily_sales", "anomaly_count": 3}
event: correlation_done data: {"pair_count": 28, "strong_pairs": 4}
event: threads_built    data: {"thread_count": 2}
event: projections_done data: {"metric_count": 7}
event: completed        data: {"correlation_run_id": "corr_7f8a9b0c1d"}
```

---

## Schema Models — `services/api/schemas.py`

```python
class CorrelationRunRequest(BaseModel):
    tenant_id: str
    domain_id: str
    run_id: str
    analysis_mode: str = "full"   # full | anomaly_only | correlation_only | forecast_only
    periods_back: int = 90
    forecast_periods: int = 12

class AnomalyResultResponse(BaseModel):
    anomaly_id: str
    metric_name: str
    anomaly_class: str            # spike | drop | drift_up | drift_down | step_change
    anomaly_score: float          # composite [0,1]
    z_score: Optional[float]
    iqr_flag: bool
    cusum_signal: bool
    detected_at: str
    period_label: Optional[str]
    baseline_value: Optional[float]
    observed_value: Optional[float]
    deviation_pct: Optional[float]
    top_dimension: Optional[str]
    top_dimension_value: Optional[str]
    dimension_pct: Optional[float]

class CorrelationPairResponse(BaseModel):
    pair_id: str
    metric_a: str
    metric_b: str
    pearson_r: Optional[float]
    spearman_rho: Optional[float]
    best_lag: Optional[int]       # periods
    lagged_r: Optional[float]
    lag_direction: Optional[str]  # a_leads_b | b_leads_a | concurrent
    strength_label: str           # strong | moderate | weak | negligible
    direction_label: str          # positive | negative
    p_value: Optional[float]
    is_stable: bool

class InvestigationThreadResponse(BaseModel):
    thread_id: str
    trigger_metric: str
    evidence_chain: list[dict]
    leading_dimension: Optional[str]
    leading_dim_value: Optional[str]
    confidence: float
    suggested_focus: Optional[list[dict]]
    narrative_text: Optional[str]
    narrative_html: Optional[str]

class ForwardProjectionResponse(BaseModel):
    projection_id: str
    metric_name: str
    trend_direction: str           # up | down | flat
    trend_slope: Optional[float]   # units per period
    seasonality_present: bool
    inflection_signal: Optional[str]  # convergence_alert | accumulation_alert | reversal_signal | on_track
    inflection_detail: Optional[str]
    anomaly_density_trend: Optional[str]  # increasing | stable | decreasing
    projection_json: list[dict]    # [{period, point_estimate, lower_1s, upper_1s, lower_2s, upper_2s, is_forecast}]
    chart_spec: Optional[dict]
```

---

## Chart Types Summary

All charts use **amCharts 5** (`@amcharts/amcharts5`). No other charting library is used.

| Chart | amCharts 5 Class | Series Types | Trigger |
|---|---|---|---|
| `forecast_band` | `am5xy.XYChart` | `LineSeries` (solid + dashed) + `LineSeries` fill areas for ±1σ / ±2σ | Per metric |
| `anomaly_timeline` | `am5xy.XYChart` | `LineSeries` + `am5.Bullet` circles per anomaly class | Per metric with ≥1 anomaly |
| `correlation_heatmap` | `am5xy.XYChart` | `ColumnSeries` with `templateField` per-cell fill + `am5xy.HeatLegend` | One per domain run |
| `scatter_regression` | `am5xy.XYChart` | `LineSeries` scatter (no stroke) + `LineSeries` regression line | Top 10 correlated pairs |
| `rolling_correlation` | `am5xy.XYChart` | `LineSeries` + `AxisDataItem` range bands for strong threshold zones | Top 10 correlated pairs |
| `anomaly_density` | `am5xy.XYChart` | Stacked `ColumnSeries` × 4 classes + `AxisDataItem` reference lines | One per domain run |

---

## Integration with Phase 38

Phase 38 (`AnomalyInvestigationAgent`) now receives the `investigation_threads` from Phase 43 as
pre-computed context before it does LLM reasoning. This means Phase 38's LLM call has **numerical
evidence** to work from rather than generating hypotheses purely from data slices.

Sequence:
```
Phase 43 runs first  →  builds statistical threads  →  persists to quantyx_investigation_threads
Phase 38 reads threads  →  LLM narrates + expands each thread  →  generates action recommendations
```

This separation keeps the statistical logic deterministic and the narrative logic LLM-first.

---

## Statistical Library Dependencies

```
numpy        — array math, Z-score, rolling stats, array alignment for lag
scipy        — pearsonr, spearmanr, p-values, Welch t-test, IQR (scipy.stats)
statsmodels  — STL decomposition (statsmodels.tsa.seasonal.STL), CUSUM
```

All are lightweight and already compatible with Python 3.10/3.11.

---

## Implementation Order

### Step 1 — Database migrations
File: `scripts/apply_agentic_tables.sh`
- `quantyx_correlation_runs`
- `quantyx_anomaly_results`
- `quantyx_correlation_pairs`
- `quantyx_investigation_threads`
- `quantyx_forward_projections`

### Step 2 — Statistical computation layer
File: `services/ai/correlation_agent.py`
- `_detect_period_column()` — auto-detect period column from a result row (no hardcoded names)
- `load_kpi_snapshots()` — load certified KPI series from `quantyx_chart_requests` by `tenant_id + domain_id`
- `extract_dimension_breakdown()` — derive dimension concentration from `rows_json` (no SQL)
- `score_anomalies()` — Z, IQR, CUSUM + dimension concentration
- `build_correlation_matrix()` — Pearson, Spearman, lagged r for all pairs
- `lagged_correlation()` — helper for lag offset optimisation
- `build_investigation_threads()` — evidence chain builder with confidence scoring
- `project_forward()` — STL decomposition + extrapolation + confidence bands + inflection check

### Step 3 — Chart generation
- `generate_correlation_charts()` — all 6 chart spec types

### Step 4 — LLM narrative
- `narrate_correlation_results()` — executive bullets + summary + forward outlook

### Step 5 — Store layer
File: `services/ai/correlation_store.py`
- All persistence functions listed above

### Step 6 — API routes + schema models
Files: `services/api/main.py` and `services/api/schemas.py`
- 7 routes under `/analysis/`
- SSE streaming endpoint

### Step 7 — Post-deployment trigger
- Hook into `finalize_canonical_deployment()` in `workspace_store.py` to auto-launch
  a `full` correlation run after each successful canonical deployment

---

## File Inventory

| File | Change type |
|---|---|
| `scripts/apply_agentic_tables.sh` | Add `run_id` column to `quantyx_chart_requests`; add 5 new table DDLs |
| `services/ai/charts_store.py` | Add `run_id` parameter to `create_chart_request()` |
| `services/ai/agentic_orchestrator.py` | Pass `run_id` at both `create_chart_request()` call sites |
| `services/ai/correlation_agent.py` | New file — statistical engine + chart spec generation |
| `services/ai/correlation_store.py` | New file — persistence layer |
| `services/api/schemas.py` | Add 5 new Pydantic models |
| `services/api/main.py` | Add 7 new routes under `/analysis/` |
| `services/ai/workspace_store.py` | Add post-deployment trigger hook in `finalize_canonical_deployment()` |

---

## Constraints and Design Decisions

- **No external time-series DB.** All data is read from `rows_json` in `quantyx_chart_requests`,
  computed in-process with numpy/scipy/statsmodels, and results persisted back to PostgreSQL.

- **No SQL rewriting.** The KPI SQL stored in `quantyx_chart_requests` is never modified or
  re-executed by Phase 43. Using `rows_json` avoids brittle string manipulation of arbitrary
  SQL (CTEs, window functions, subqueries) and avoids coupling to specific table/column names.

- **Generic data loading.** `load_kpi_snapshots()` uses only `tenant_id` and `domain_id` as
  scope keys. Period columns are auto-detected from row key names and value patterns. Metric
  value columns come from `query_payload["metrics"][0]`. No table names, column names, or
  tenant-specific identifiers appear anywhere in the statistical engine.

- **KPI scoping uses `run_id` when available, `tenant_id + domain_id` as fallback.**
  `quantyx_chart_requests.run_id` is populated by `agentic_orchestrator` at chart creation time
  (Phase 43 prerequisite: `ALTER TABLE quantyx_chart_requests ADD COLUMN run_id TEXT NULL`).
  The post-deployment trigger always has `run_id`, so charts are scoped precisely to the
  canonical deployment run. On-demand `/analysis/correlation` calls without a `run_id` fall back
  to `tenant_id + domain_id` with newest-chart-per-metric deduplication.

- **Computation is synchronous within the agent, async at the API layer.** The
  `/analysis/correlation` endpoint enqueues a background job; the client polls or streams via SSE.

- **Pairs are upper-triangle only.** For N metrics, there are N(N-1)/2 pairs. At N=20 this is
  190 pairs — manageable without batching. For N > 50, pairs with `|pearson_r| < 0.2` are pruned
  before persistence.

- **Lag window defaults to ±6 periods.** Appropriate for monthly/weekly grain. Daily grain should
  use ±30.

- **Minimum series length is 30 observations** for STL decomposition. Metrics with 5–29 points
  fall back to simple linear trend extrapolation without seasonality. Metrics with fewer than 5
  points are skipped entirely.

- **No ML models in this phase.** All computation is classical statistics. ML-based forecasting
  (ARIMA, Prophet) is explicitly deferred to a future phase.

---

## Not in Scope

- Machine learning forecasting (ARIMA, Prophet, LSTM)
- Causal inference (Granger causality, instrumental variables)
- Multi-variate regression for driver decomposition
- Real-time streaming anomaly detection
- Cross-tenant or cross-domain correlation
- User-defined alert thresholds (those belong in Phase 07 Governance)