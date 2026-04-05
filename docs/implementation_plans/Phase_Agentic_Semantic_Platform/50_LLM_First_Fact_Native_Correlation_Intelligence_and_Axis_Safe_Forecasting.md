# Phase 50: LLM-First Fact-Native Correlation Intelligence and Axis-Safe Forecasting

## Objective

Redesign the current correlation intelligence layer so it:

1. reads from live fact tables and approved semantic sources first, not only from previously created charts
2. requires a real temporal axis for time-series anomaly, correlation, lag, and forecast analysis
3. handles categorical-only breakdowns explicitly instead of misclassifying categories as time
4. produces stronger LLM-first knowledge generation, narrative, and insights across correlation runs and dashboards
5. generates richer dashboard artifacts for both temporal and categorical correlation views

This phase is an evolution of Phase 43, not a replacement of its intent.

---

## Problem

The current correlation pipeline is useful but structurally unsafe in a few important ways:

1. It primarily reconstructs KPI snapshots from `quantyx_chart_requests.rows_json`.
2. It infers the period axis heuristically from arbitrary chart rows.
3. It treats any ordered series-like data as eligible for anomaly and forecast analysis.
4. It is statistical-first for computation, but not consistently LLM-first for interpretation, narrative, insight synthesis, or dashboard intelligence.
5. It does not explicitly support category-native forecasting or per-category stacked forecast views.

This leads to bugs and quality risks such as:

- non-time breakdown charts being treated as time series
- anomaly labels like `at=None` or `at=AQ`
- category values being interpreted as time points
- misleading lag and trend conclusions on non-temporal charts
- duplicate or near-duplicate correlations being surfaced without enough semantic explanation

---

## Key Example of the Current Bug

Current snapshot construction in `services/ai/correlation_agent.py`:

- loads `rows_json`
- auto-detects a `period_col`
- uses that detected column to build `timestamps`

That is acceptable only when the detected axis is a real date/time grain.

It is not acceptable when the chart is:

- `Total Sales Volume by Zone`
- `Sales Volume By Product Group by Zone`
- any categorical breakdown without temporal grain

In those cases:

- `AQ` can appear as a fake anomaly period
- `None` can appear as a fake anomaly period
- the row order of categories is treated as a pseudo-time sequence

This phase fixes that class of error at the model level, not with one-off patches.

---

## Target State

### 1) Fact-Native Correlation Inputs

Correlation analysis should source data from:

- live scoped fact tables
- validated semantic metrics
- approved semantic views
- persisted chart artifacts only as secondary convenience inputs

The preferred order should be:

1. fact-native scoped metric extraction
2. semantic metric registry / view-backed series generation
3. persisted chart rows only when the source is already known to be temporal and compatible

### 2) Axis-Safe Time-Series Eligibility

Time-series intelligence must run only when all of the following are true:

- a real time column is known
- the grain is explicit or inferable safely
- timestamps are monotonic or sortable as time
- the metric is numeric and aggregatable
- the series length meets minimum quality thresholds

If those conditions are not met, the metric is not eligible for:

- anomaly timeline
- lagged correlation
- rolling correlation
- forward projection

### 3) Category-Native Intelligence

If the source is categorical rather than temporal:

- do not run time-series anomaly or lag logic directly on category order
- instead, study the metric distribution per category
- when history exists per category over time, build category-level time series
- generate category forecasts as stacked or grouped category forecast views

Examples:

- `sales_volume by zone over month` should become multi-series temporal analysis by category
- `sales_volume by zone` with no time dimension should become categorical composition analysis, not temporal anomaly analysis

### 4) LLM-First Correlation Intelligence

All knowledge-generation and intelligence layers in the correlation pipeline should become LLM-first.

That includes:

- metric interpretation
- source eligibility reasoning
- duplicate / overlap interpretation
- anomaly significance narration
- correlation meaning synthesis
- forecast interpretation
- dashboard section planning
- executive summary and analyst insight generation

Deterministic/statistical computation remains essential, but it becomes the evidence layer rather than the sole intelligence layer.

### 5) Correlation Narrative and Insight Artifacts

Every correlation run should produce:

- executive summary
- metric-level insights
- pair-level interpretations
- anomaly significance notes
- forecast risk notes
- data quality / confidence warnings
- semantic overlap / duplicate-signal notes
- dashboard-ready narrative sections

---

## Scope

### In scope

- redesign of correlation input sourcing
- temporal eligibility rules
- category-native analysis and forecast handling
- stacked/grouped category forecast chart generation
- LLM-first narrative and insight generation
- improved correlation dashboard content planning
- confidence and warning model for correlation artifacts
- elimination of category-as-time bugs

### Out of scope

- unrestricted raw SQL execution without scoped validation
- replacing Phase 38 anomaly investigation semantics
- full causal inference
- fully autonomous business action execution

---

## Design Principles

### 1) Real Time Is Mandatory for Time-Series Logic

No chart, metric, or series should enter time-series analysis without explicit time eligibility.

### 2) Facts Before Charts

Charts are presentation artifacts, not the canonical analytical substrate.

Correlation should prefer:

- fact rows
- semantic views
- validated metric definitions

over:

- inferred chart payload reconstruction

### 3) LLM First for Meaning, Deterministic First for Evidence Validation

The architecture should be:

- deterministic/statistical for evidence production
- LLM-first for interpretation, narrative, prioritization, and dashboard intelligence

Not:

- deterministic-only with LLM narration appended at the end

More explicitly:

- every step that requires semantic judgment, business interpretation, prioritization, or category selection should be LLM-first
- every step that requires safety, truth validation, executable data access, or mathematical correctness should remain deterministic

The goal is to maximize LLM use in all places where intelligence can be improved by semantic reasoning, while keeping all execution-critical and correctness-critical steps deterministic.

### 4) Categorical Data Must Be Treated as Categorical

Category order is not time.

Category analysis should be:

- composition analysis
- share analysis
- rank-shift analysis
- category-over-time analysis when a real time axis exists
- per-category forecast when category-specific time series can be built

### 5) Every Correlation Finding Needs Confidence Context

Every surfaced correlation insight should explain:

- why it is likely meaningful
- whether the relationship is stable
- whether the compared metrics are partially redundant
- whether the signal is temporal, categorical, or mixed
- whether the source quality is high, moderate, or weak

---

## Desired User Outcomes

- As an analyst, I want correlation insights based on real time axes instead of arbitrary chart row order.
- As a business user, I want category breakdowns treated correctly and forecasted per category when possible.
- As an operator, I want explanations of what a correlation means, not just the coefficient.
- As a dashboard consumer, I want correlation dashboards with narrative sections and confidence warnings.
- As a platform owner, I want LLM-first intelligence across correlation agents and dashboards, with deterministic evidence underneath.

---

## Proposed Architecture

## 1. Source Resolver Layer

Create a new correlation source resolver that builds eligible analytical series from:

- scoped connection + profiling metadata
- semantic metric definitions
- semantic contracts / metric registry
- semantic views / fact views
- persisted charts only as fallback

Output shape:

```python
{
  "source_kind": "fact_metric" | "semantic_view_metric" | "chart_fallback",
  "metric_name": str,
  "base_table": str | None,
  "time_column": str | None,
  "grain": "day" | "week" | "month" | "quarter" | "year" | None,
  "category_columns": list[str],
  "value_expr": str,
  "series_type": "temporal" | "categorical" | "category_temporal",
  "quality": {...},
}
```

## 2. Temporal Eligibility Gate

Introduce an explicit temporal eligibility validator:

- `has_real_time_axis`
- `time_axis_parseable`
- `time_axis_sorted`
- `grain_supported`
- `enough_points`
- `enough_variance`

If false:

- block anomaly timeline
- block lag analysis
- block forecast band generation
- block rolling correlation

## 3. Category Intelligence Layer

For non-temporal but categorical metrics:

- compute share, rank, concentration, and dispersion
- generate categorical insight cards
- avoid pseudo-time anomaly detection

For temporal plus category metrics:

- build one time series per category
- cap category cardinality with top-N + other bucketing
- generate:
  - stacked bar forecast
  - grouped category trend
  - category contribution shift narrative

## 4. Correlation Intelligence LLM Layer

Add an LLM-first synthesis stage that consumes:

- anomalies
- correlations
- rolling stability
- forecast outputs
- category shift summaries
- source quality diagnostics
- semantic metric metadata
- business context text

The LLM should produce:

- pair meaning
- likely business interpretation
- duplicate/overlap warning
- leading-indicator explanation
- anomaly implication summary
- forecast risk summary
- dashboard section plan

It should also be responsible for:

- ranking candidate sources by likely business value
- proposing the most plausible business time axis when multiple time columns exist
- classifying source shapes as temporal, categorical, or category-temporal before deterministic validation
- selecting the most meaningful category dimensions for per-category forecasting
- recommending top-N category preservation and `Other` bucketing strategy
- explaining data quality, overlap, instability, and confidence in analyst-usable language

## 5. Correlation Dashboard Intelligence Layer

Dashboard generation should become section-aware and insight-aware:

- Key anomalies
- Strongest stable relationships
- Unstable / broken relationships
- Category mix shifts
- Forecast and outlook
- Data quality / interpretation warnings

---

## Charting Model Changes

### Existing chart families to retain

- anomaly timeline
- correlation heatmap
- scatter regression
- rolling correlation
- forecast band
- anomaly density

### New chart families to add

1. `category_forecast_stacked_bar`
   - stacked forecast per category across future periods
   - used only when category-specific time series exist

2. `category_mix_shift`
   - compares category composition across time windows
   - useful for share migration and sales mix changes

3. `temporal_eligibility_warning_card`
   - explains why a source was excluded from time-series intelligence

4. `metric_overlap_matrix`
   - highlights metrics that are near-duplicates or semantically overlapping

---

## LLM-First Requirements

The correlation agent and dashboards must be LLM-first in all knowledge-generation steps.

### LLM-first areas

- metric interpretation
- source-to-series classification
- anomaly explanation
- pair explanation
- lag meaning
- stability interpretation
- forecast narrative
- category shift narrative
- dashboard story section generation
- executive summary
- analyst guidance
- candidate source ranking
- preferred time-axis proposal
- categorical vs temporal shape classification
- category-dimension selection
- top-N category retention recommendation
- duplicate and semantic-overlap interpretation
- confidence rationale generation
- warning synthesis and wording

### Deterministic support areas

- source resolution
- SQL safety
- fact extraction
- statistical computation
- confidence scoring
- duplication heuristics
- chart spec rendering
- persistence

### Responsibility Matrix

The intended split for the key correlation responsibilities is:

1. Identify candidate fact / semantic sources
   - LLM-first:
     - rank likely useful fact tables, semantic views, and metrics using schema, context text, profiling, and prior artifacts
     - explain why a source is likely analytically valuable
   - Deterministic:
     - enforce scoped-access rules
     - verify source existence and eligibility

2. Validate whether a source is truly temporal
   - LLM-first:
     - interpret which candidate column is the business time axis
     - distinguish business-event time from load/update timestamps when multiple options exist
   - Deterministic:
     - validate parseability, grain support, ordering, null-rate, and minimum-point thresholds
     - make the final allow/block decision for time-series use

3. Reject category-as-time inputs
   - LLM-first:
     - classify suspicious sources as categorical, temporal, or mixed
     - explain why a dimension like zone, region, product, or site is not a valid time axis
   - Deterministic:
     - block any source failing the temporal validator from anomaly, lag, rolling-correlation, and forecast computation

4. Build per-category temporal series
   - LLM-first:
     - choose the most meaningful category dimensions
     - recommend grouping semantics and business-relevant segment selection
   - Deterministic:
     - execute the series-building queries
     - enforce cardinality limits, top-N logic, and `Other` bucketing

5. Compute anomalies, correlations, lags, stability, and forecasts
   - LLM-first:
     - none for the underlying math
     - only interpretation after computation
   - Deterministic:
     - all statistical and forecasting computation
     - reproducible thresholds and scoring

6. Cap top-N categories and bucket `Other`
   - LLM-first:
     - recommend the grouping strategy using business meaning and signal concentration
   - Deterministic:
     - apply exact rank / contribution thresholds and perform the actual bucketing

7. Assign baseline confidence and data-quality warnings
   - LLM-first:
     - synthesize readable confidence rationale and warning narratives
     - prioritize which warnings matter most to an analyst
   - Deterministic:
     - compute the base confidence, source quality, overlap flags, instability flags, and hard warning triggers

### Policy

Anything that can be improved by semantic interpretation or prioritization should be LLM-first.

Anything that can create incorrect execution, unsafe access, or mathematically wrong output if the LLM is wrong must remain deterministic.

### Explicit non-goal

Do not treat “LLM-first” as “LLM-only”.

Statistical evidence remains mandatory. The LLM must interpret grounded evidence, not invent findings.

---

## Workflow Placement

Recommended updated sequence:

1. `DashboardAgent`
2. `CorrelationSourceResolver`
3. `CorrelationComputationAgent`
4. `CorrelationNarrativeAgent`
5. `CorrelationDashboardAgent`
6. `AnomalyInvestigationAgent`

This makes correlation intelligence available upstream to anomaly investigation while preserving stronger evidence quality.

---

## Detailed Requirements

### Requirement A: Stop Using Non-Temporal Charts as Time Series

The system must reject any source for temporal analytics when:

- no time column exists
- detected axis is categorical
- values do not parse as time
- source grain is inconsistent

### Requirement B: Build Live Series from Facts

The system must be able to generate series directly from:

- fact tables
- semantic views
- approved metric expressions

without relying on existing chart output rows.

### Requirement C: Support Category Forecasting Properly

When category-level historical series exist:

- forecast each category separately
- render stacked bar or grouped category forecast views
- narrate contribution shifts and likely winners/losers

### Requirement D: Add Correlation Narrative and Insights

Every completed correlation run must persist:

- summary text
- section narratives
- pair insights
- anomaly notes
- forecast notes
- warnings
- confidence and quality metadata

### Requirement E: LLM-First Dashboard Intelligence

Correlation dashboard composition must use the LLM first for:

- section selection
- chart ordering
- duplicate suppression
- insight emphasis
- warning generation

---

## Data Model Changes

Extend correlation run persistence with:

- `source_quality_json`
- `eligibility_summary_json`
- `narrative_sections_json`
- `insights_json`
- `warnings_json`

Extend anomaly/correlation artifacts with:

- `series_type`
- `time_axis_column`
- `category_axis_columns`
- `source_kind`
- `semantic_overlap_group`

---

## API Changes

Add richer APIs for correlation diagnostics:

- `GET /correlation/runs/{id}/insights`
- `GET /correlation/runs/{id}/source-quality`
- `GET /correlation/runs/{id}/eligibility`
- `GET /correlation/runs/{id}/narrative`

Optional:

- `GET /correlation/runs/{id}/category-forecasts`

---

## Rollout Strategy

### Phase 50A: Safety and Eligibility

- block category-as-time bugs
- add temporal eligibility validator
- persist warnings

### Phase 50B: Fact-Native Source Resolver

- build fact-native and semantic-view-native series extraction
- use chart fallback only secondarily

### Phase 50C: Category Forecasting

- add category-temporal series model
- add stacked/grouped category forecast charts

### Phase 50D: LLM-First Narrative

- introduce LLM-first correlation interpretation and dashboard section planning
- persist narrative and insights

### Phase 50E: Dashboard Upgrade

- ship richer correlation dashboard layout and APIs

## Execution Tickets

### 50A.1 Temporal Eligibility Validator

- add a reusable validator for time-axis parseability, uniqueness, null-rate, and supported grain
- require explicit temporal eligibility before anomaly, lag, rolling-correlation, or forecast analysis
- log and persist exclusion reasons for rejected snapshots

### 50A.2 Snapshot Safety Refactor

- stop treating arbitrary chart rows as valid time series
- reject category-only charts such as `by zone`, `by region`, `by product`, `by site` when no real time axis exists
- make correlation snapshot construction produce eligibility metadata per snapshot

### 50A.3 Warning Surface

- expose temporal-exclusion warnings in correlation run metadata
- include dashboard-visible warning cards or summaries when snapshots were excluded

### 50B.1 Fact-Native Source Resolver

- resolve candidate fact and semantic sources from scoped connections, profiling, contracts, and metric registry
- rank candidates LLM-first, then validate deterministically

### 50B.2 Semantic View and Metric Series Builder

- build live time series from semantic views / approved fact metrics
- use chart rows only as fallback when the source is already known to be temporal

### 50B.3 Source Quality Model

- persist source kind, quality, overlap, and eligibility metadata per snapshot

### 50C.1 Category-Temporal Series Builder

- build one time series per category for approved top-N category dimensions
- support grouped and stacked category trend analysis

### 50C.2 Category Forecast Charts

- add `category_forecast_stacked_bar`
- add category mix-shift and contribution charts

### 50C.3 Category Narrative

- generate category-level forecast and contribution insights
- surface winner/loser and concentration changes

### 50D.1 LLM-First Correlation Interpretation

- add LLM-first source classification, pair explanation, overlap interpretation, and lag meaning synthesis

### 50D.2 LLM-First Forecast and Warning Narrative

- add LLM-generated forecast risk notes, quality warnings, and confidence rationale grounded in structured evidence

### 50D.3 LLM-First Dashboard Story Planning

- use the LLM to choose section ordering, chart emphasis, duplicate suppression, and executive summary composition

### 50E.1 Correlation Dashboard Upgrade

- add richer dashboard sections for anomalies, stable relationships, unstable relationships, category mix shifts, forecast outlook, and warnings

### 50E.2 Correlation Intelligence APIs

- add insights, eligibility, source-quality, and narrative endpoints for correlation runs

---

## Risks

1. Fact-native extraction can increase query cost if not scoped carefully.
2. Category-level forecasting can explode chart count without top-N limits.
3. LLM-first narration can drift unless hard-grounded by statistical evidence payloads.
4. Duplicate semantic metrics can still create misleading perfect correlations unless overlap suppression is added.

---

## Guardrails

- time-series logic only with explicit temporal eligibility
- top-N categories plus `Other`
- mandatory scoped connection and tenant/domain validation
- strict source-quality metadata on every correlation artifact
- LLM output always grounded by structured statistical payloads

---

## Success Criteria

1. No correlation run should emit anomaly periods like categorical values such as `AQ` or null labels like `None` when performing time-series anomaly analysis.
2. Correlation should succeed on fresh deployments even without pre-existing charts by using fact-native series generation.
3. Category-based sources with historical time support should produce per-category forecasts and stacked/grouped forecast charts.
4. Correlation dashboards should include persisted narrative sections, insights, and warnings.
5. Correlation and dashboard intelligence should be LLM-first across interpretation and storytelling layers.

---

## Dependencies

- Phase 24 for deployment and workspace run context
- Phase 34 for durable artifact persistence
- Phase 35/36/37 for KPI-first, context-aware metric interpretation
- Phase 38 for downstream anomaly investigation consumption
- Phase 43 as the baseline correlation phase being evolved
- Phase 45 for scoped live connection credentials
- Phase 46 for per-chart narrative and stats persistence
- Phase 47 for LLM-first dashboard intelligence patterns

---

## Recommendation

Implement this as a new phase rather than editing Phase 43 retroactively.

Reason:

- Phase 43 remains the first workable statistical intelligence milestone
- Phase 50 becomes the production-grade redesign that fixes source safety, adds fact-native correlation, and standardizes LLM-first intelligence
- this preserves historical design intent while giving the team a clean execution plan for the upgraded architecture
