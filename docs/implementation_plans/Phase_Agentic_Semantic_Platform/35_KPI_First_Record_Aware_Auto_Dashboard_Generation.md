# Phase 35: KPI-First Record-Aware Auto Dashboard Generation

## Objective
Make auto dashboard generation prefer business-meaningful KPI columns and real record patterns over generic first-numeric-column heuristics, so deployments automatically produce charts like:
- `total_productivity` by day
- `total_productivity` by month
- `total_production` by day
- `total_production` by month
- `total_productivity` by plant / zone / region
- `total_production` by plant / zone / region

This phase is specifically intended to fix cases where the platform already has good source columns such as `total_productivity`, `total_production`, and `process_date`, but the agents still generate weaker or misleading dashboard charts.

---

## Problem
- `MetricAgent` still generates too many generic fallback metrics such as `sum_*` without strongly prioritizing semantically strong KPI columns already present in the data.
- `ChartPlannerAgent` and `build_dashboard_spec(...)` are still driven too heavily by:
  - first numeric column
  - first time column
  - first categorical column
- The current flow understands schema shape, but not enough of the actual data record patterns and business importance.
- As a result, dashboards can miss the obvious executive charts even when the raw table already contains the exact KPI columns needed.

---

## Target State
1. Agents identify canonical KPI columns from both schema semantics and observed record distributions.
2. Strong KPI columns such as `total_productivity` and `total_production` outrank generic fallback measures.
3. Canonical time columns such as `process_date` are preferred for trend charts automatically.
4. Auto dashboards always prioritize:
   - daily trend
   - monthly trend
   - business breakdowns by plant / zone / region
5. Dashboard generation becomes KPI-first, record-aware, and domain-aware.

---

## Scope
1. Improve record-aware semantic profiling.
2. Improve KPI ranking in `MetricAgent`.
3. Improve chart candidate generation in `ChartPlannerAgent`.
4. Improve default dashboard assembly in `DashboardAgent`.
5. Add observability proving why a KPI and chart were selected.

Out of scope:
- manual dashboard editing UX
- conversation query planner changes unrelated to auto dashboards
- replacing the entire chart refresh subsystem

---

## Why Current Output Is Wrong

### 1) Metric generation is still too fallback-heavy
In `propose_metrics(...)`, the system creates:
- generic `sum_<column>` metrics
- generic derived formulas from pattern matches

But it does not strongly say:
- if `total_productivity` exists, this is probably the canonical productivity KPI
- if `total_production` exists, this is probably the canonical production KPI

### 2) Dashboard selection is still too positional
In `build_dashboard_spec(...)`, the system effectively picks:
- first eligible numeric column
- first time column
- first categorical column

That is not a business ranking system.

### 3) Chart planning does not explicitly require KPI trend coverage
`ChartPlannerAgent` creates useful chart candidates, but it does not enforce default dashboard coverage like:
- KPI by day
- KPI by month
- KPI by top operational breakdown

---

## Desired Agent Behavior

### 1) ProfilingAgent must become record-aware
For each table, it should persist and expose:
- row count and date coverage
- null ratio for candidate KPI columns
- cardinality and distribution quality for breakdown columns
- time continuity and recency for time columns
- additive vs ratio-like hints for numeric columns

Expected result for `lpg_plant_operations`:
- `process_date` identified as canonical trend time column
- `total_productivity` identified as a high-confidence KPI
- `total_production` identified as a high-confidence KPI
- `plant`, `zone`, and `region` identified as strong business breakdowns

### 2) MetricAgent must rank canonical KPI measures above fallback measures
Priority order should be:
1. existing business-style KPI columns
2. semantically strong totals
3. semantically strong ratios / productivity / efficiency metrics
4. validated domain templates
5. generic fallback `sum_*` measures only if no better KPI exists

For this case, `MetricAgent` should strongly prioritize:
- `total_productivity`
- `total_production`

and treat generic formulas as secondary.

### 3) ChartPlannerAgent must generate mandatory KPI coverage templates
For each selected top KPI metric with a usable time column:
- line chart: KPI by day
- line chart: KPI by month
- bar chart: KPI by plant
- bar chart: KPI by zone
- bar chart: KPI by region

Optional:
- multi-series trend by zone
- top/bottom plant comparisons

### 4) DashboardAgent must assemble dashboards from KPI bundles, not column order
The default dashboard should be built from:
- top KPI metrics
- top time dimensions
- top business breakdown dimensions

For the LPG operations case, the expected default dashboard should include at least:
- `total_productivity` by month
- `total_productivity` by day
- `total_production` by month
- `total_production` by day
- `total_productivity` by zone or plant
- `total_production` by zone or plant

---

## Implementation Plan

### Phase 35.1: Record-Aware Profiling
- extend profiling outputs with:
  - date coverage
  - null ratio
  - distinct count
  - monotonic / continuity hints for time columns
  - business breakdown strength for categorical columns
- persist this into the profiling artifact bundle

### Phase 35.2: KPI Column Ranking
- add deterministic KPI ranking rules in `propose_metrics(...)`
- prefer columns matching patterns such as:
  - `total_*`
  - `*_productivity`
  - `*_production`
  - `*_throughput`
  - `*_efficiency`
- score columns using:
  - semantic role
  - record coverage
  - domain name quality
  - additive / ratio safety

### Phase 35.3: Canonical Time Dimension Selection
- explicitly choose a canonical time axis per fact table
- prefer:
  - `process_date`
  - operational date columns
  - date columns with best coverage and continuity
- persist this as part of model/profile intelligence

### Phase 35.4: KPI-First Chart Candidate Generation
- update `propose_chart_candidates(...)` so top-ranked KPI metrics always emit:
  - day trend
  - month trend
  - top business breakdown charts
- stop defaulting to whatever first numeric column happens to be present

### Phase 35.5: Dashboard Composition Rules
- update `build_dashboard_spec(...)` so default dashboards guarantee:
  - trend coverage
  - operational breakdown coverage
  - KPI diversity
- define chart quotas such as:
  - 2 time-series charts
  - 2 operational breakdown charts
  - optional 1 comparison/share chart

### Phase 35.6: Data-Aware Quality Gates
- reject charts if:
  - metric column is weak or low-confidence
  - time column is poor quality
  - category column is too high-cardinality or not business-meaningful
- prefer charts supported by strong record evidence

### Phase 35.7: Observability
- add logs proving:
  - why a KPI column was ranked highly
  - why a time column was selected
  - why a chart candidate was accepted or rejected
  - which dashboard slots were filled by which KPI bundles

---

## API / Behavior Impact

No public API shape change is required.

Behavior changes:
- future deployments should generate better default dashboard charts automatically
- dashboard specs should contain more business-meaningful KPI trend charts
- chart planner output should clearly reflect KPI-first selection

Optional future debug endpoint extension:
- include KPI ranking evidence and chart selection reasons in dashboard debug payloads

---

## Implementation Status

Implemented in this pass:
- Phase 35.2:
  - deterministic KPI ranking in `propose_metrics(...)`
  - canonical KPI promotion for columns like `total_productivity` and `total_production`
- Phase 35.3:
  - canonical time selection preferring `process_date`, then other operational date columns
- Phase 35.4:
  - chart candidate generation now emits KPI-first day and month trend charts
  - chart candidate generation now prefers business breakdowns such as plant / zone / region
- Phase 35.5:
  - dashboard spec generation now uses top KPI metrics and preferred breakdowns instead of first-column heuristics
  - chart selection now preserves both day and month trends and guarantees breakdown coverage
- Phase 35.7:
  - added KPI/chart selection logs such as `agentic.chart.metric_selected`
  - dashboard SQL generation now respects `time_grain`

Partially implemented:
- Phase 35.1:
  - record-aware ranking currently uses existing profiling evidence such as sample values and candidate key uniqueness
  - deeper profiling persistence for null ratio, date continuity, and explicit breakdown strength is still to be added
- Phase 35.6:
  - chart selection now favors meaningful breakdowns and smaller-cardinality share charts
  - explicit chart rejection gates for poor-quality time/category evidence still need to be tightened further

---

## Acceptance Criteria
1. If a fact table contains strong KPI columns like `total_productivity` and `total_production`, they are prioritized above generic fallback measures.
2. If `process_date` exists with good coverage, it is selected as the canonical time column for trend charts.
3. Auto dashboards include day and month trend charts for the top KPI metrics when time support exists.
4. Auto dashboards include business breakdown charts for the top KPI metrics using meaningful dimensions such as plant / zone / region.
5. Chart planner output shows deterministic reasoning for KPI, time, and breakdown selection.
6. Dashboard generation no longer depends primarily on first-column heuristics.

---

## Test Plan
1. Deploy against a table containing `total_productivity`, `total_production`, and `process_date`.
   Verify those columns become top KPI candidates.

2. Verify `ChartPlannerAgent` produces:
   - productivity by day
   - productivity by month
   - production by day
   - production by month

3. Verify `DashboardAgent` persists a dashboard spec containing those charts.

4. Verify high-cardinality or weak categorical columns do not displace better business dimensions like plant / zone / region.

5. Regression test:
   ensure fallback `sum_*` metrics are still available when a table truly lacks better KPI columns.

---

## Dependencies
- Phase 29 for semantic role classification and measure eligibility
- Phase 30 for template-first KPI metric generation
- Phase 31 for KPI chart planner and SQL semantic safety
- Phase 32 for KPI quality gates
- Phase 34 for persisted agent artifact intelligence

---

## Success Criteria
- Auto dashboards reflect the actual business KPIs present in the data.
- The system can inspect table records and automatically infer the most useful KPI trend and breakdown charts.
- Agents produce dashboards that align with business expectations without manual chart curation.
