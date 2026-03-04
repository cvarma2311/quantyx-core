# Phase 05: Auto‑Dashboard Story Engine

## Objective
Generate intelligent dashboards with story‑driven charts and narratives.

## Agents
- **Story Agent**: suggests key questions + story arc
- **ChartPlannerAgent**: builds chart candidates (4–8) based on schema/profile/joins
- **Chart Agent**: selects chart types + payloads (amCharts compatible)
- **Insight Agent**: highlights anomalies + drivers

## Inputs
- Semantic graph
- Metrics usage patterns
- Rollup availability

## Outputs
- Dashboard spec (cards, charts, narratives)
- Chart payloads (amCharts compatible)
- Minimum 4 charts, maximum 8 per auto‑dashboard
- Story cards + insights per chart

---

## ChartPlannerAgent (Dynamic Chart Generation)

### Inputs
- Profiling stats (time cols, numeric cols, categorical cols)
- Derived metrics (productivity, utilization, yield, rejection rate)
- Join metadata (cardinality, coverage_ratio)

### Candidate Rules
- **Trend**: time dimension → line chart
- **Breakdown**: category dimension → bar chart
- **Share**: category dimension with ≤ 10 values → pie chart
- **Multi‑series**: time + small category (≤ 6) → line multi‑series
- **Join‑breakdown**: use join key with highest coverage ratio as category

### Ranking + Selection
- Score by intent + derived metrics + coverage ratio
- Ensure diversity: at least 1 trend, 1 breakdown, 1 share, 1 efficiency metric
- Select **4–8 charts** deterministically

---

## Deterministic Chart Heuristics (Baseline)

### Line Chart
Use when:
- Time dimension present (`date`, `week`, `month`, `process_date`)
- Question implies trend: “trend”, “over time”, “last X months”

### Bar Chart
Use when:
- One categorical dimension + one metric
- No time dimension
- Question implies comparison: “by region”, “top N”

### Pie Chart
Use when:
- Single categorical dimension + one metric
- Category count ≤ 6
- Question implies share: “share”, “distribution”, “contribution”

### Table Chart (fallback)
Use when:
- Multiple dimensions or unclear chart mapping
- Used as safe default when chart selection is ambiguous

### Stacked Bar (deterministic)
Use when:
- Two categorical dimensions + one metric
- One dimension has ≤ 6 categories (stack)

### Line + Breakdown (multi‑series)
Use when:
- Time dimension + one categorical dimension with ≤ 6 categories
- Plot multiple lines (one per category)

### Scatter (optional, deterministic)
Use when:
- Two numeric metrics, no categorical dimension

---

## Deterministic Priority Order
1. Time dimension → Line (or multi‑line if 1 small category dimension)\n2. Share/distribution intent + small categories → Pie\n3. Comparison intent or categorical → Bar/Stacked Bar\n4. Fallback → Table

---

## Minimum Chart Set (Auto‑Dashboard)

Always generate at least 3 charts:
1. **KPI Trend** (line chart, time grain default)\n2. **Category Breakdown** (bar or stacked bar)\n3. **Share/Distribution** (pie, else bar if categories too many)

If a **productivity** metric exists, include it as either:
- a second KPI trend line, or
- a separate KPI card + trend chart.
