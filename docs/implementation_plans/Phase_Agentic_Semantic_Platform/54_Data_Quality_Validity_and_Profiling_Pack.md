# Phase 54: Data Quality, Validity, and Profiling Pack

## Goal

Introduce a dedicated pack focused on the quality, validity, trustworthiness, and profiling characteristics of the data itself.

This pack should generate:

- data quality KPIs
- data validity KPIs
- missingness analysis
- completeness analysis
- duplication and fuzzy duplication analysis
- freshness and recency checks
- uniqueness and key health checks
- value distribution and drift indicators
- schema/profile-driven quality dashboards

The output should be a first-class domain pack that can produce dashboards and charts answering:

- how complete is the data
- which tables and columns have missing values
- where is duplication likely present
- which fields are unstable or low quality
- whether the data is fresh enough for decision-making
- which entities or tables are least trustworthy

This is not a business KPI pack.
It is a data trust and data health pack.

---

## Why This Phase Is Needed

The current platform already profiles data during deployment, but that profiling is mostly used as:

- semantic support
- metric eligibility support
- chart planning support
- validation support

It is not yet elevated into a customer-facing analytical product.

That leaves a major gap:

- users can see business dashboards
- but they cannot easily see whether the underlying data is complete, duplicated, stale, inconsistent, or reliable

In real deployments, users need dashboards that answer:

- are nulls increasing
- is one source/table degrading
- which columns are unusable for analytics
- which entity IDs are duplicated
- whether timestamps are delayed
- where data validity rules are being violated

This phase makes data quality and data profiling a packaged analytic capability, not just an internal preprocessing step.

---

## Product Positioning

This should be a new pack, for example:

- `data_quality_observability`
- or `data_trust_and_validity`

It should behave like other packs:

- has its own metric templates
- has its own chart preferences
- has its own dashboard composition guidance
- has its own quality-specific semantics and narratives

Unlike business-domain packs, this pack is meta-analytical:

- it analyzes the health of the data platform itself
- not just the business process represented by the tables

---

## Core Questions This Pack Should Answer

### Completeness

- what percentage of rows have missing values by column
- which columns have the highest null rate
- which tables have poor completeness
- how has completeness changed over time

### Validity

- which columns violate expected type/pattern/range expectations
- which fields contain unexpected categorical values
- where do business validation rules fail
- which records look malformed

### Uniqueness

- which columns or composite keys have duplicates
- which tables violate expected uniqueness assumptions
- how severe is duplication

### Fuzzy Duplication

- are there likely duplicate entities with slightly different names
- do location names or customer names look near-duplicated
- are there record clusters that represent the same entity with minor variation

### Freshness

- when was each table last updated
- what is the gap between expected and actual latest timestamps
- which tables are stale

### Stability

- are row counts drifting abnormally
- are value distributions shifting unexpectedly
- are columns becoming sparse

### Trust Score

- which tables and columns are most trustworthy
- which datasets should be avoided for KPI creation until cleaned

---

## Scope

This phase introduces:

1. a dedicated data quality pack
2. data-quality-specific metric templates
3. profiling extensions to persist missingness, duplication, freshness, validity, and fuzzy duplicate signals
4. data quality dashboard composition logic
5. data quality chart recommendations
6. trust-oriented narratives and summaries
7. optional domain-specific validation rule hooks

Out of scope for initial phase:

- full record-level remediation workflows
- automatic data correction
- ML anomaly detection over every column
- enterprise-grade data catalog replacement

---

## Pack Design

## 1. New Pack

Create a new pack under something like:

- `packs/data_quality_observability/`

Suggested files:

- `metric_templates.yml`
- `chart_guidance.yml`
- `dashboard_guidance.yml`
- `validation_rules.yml`
- `narrative_guidance.md`

This pack should work across domains, with optional domain overrides later.

---

## 2. Pack Objective

The pack should produce dashboards like:

- Data Completeness Overview
- Table Quality Health Dashboard
- Missingness and Freshness Dashboard
- Duplicate Risk Dashboard
- Data Trust Scorecard

These should be available:

- as an explicit deployment mode or optional companion dashboard
- or as a dedicated data quality dashboard generated alongside business dashboards

---

## Data Quality KPI Families

The pack should define KPI families such as:

### A. Completeness KPIs

- `row_count`
- `null_count`
- `null_pct`
- `non_null_pct`
- `columns_with_nulls`
- `rows_with_any_null`

### B. Validity KPIs

- `invalid_value_count`
- `invalid_value_pct`
- `out_of_range_count`
- `pattern_violation_count`
- `unexpected_category_count`

### C. Uniqueness KPIs

- `duplicate_count`
- `duplicate_pct`
- `distinct_count`
- `uniqueness_ratio`

### D. Freshness KPIs

- `latest_timestamp`
- `freshness_lag_hours`
- `freshness_status`
- `days_since_last_update`

### E. Consistency / Stability KPIs

- `row_count_trend`
- `null_pct_trend`
- `duplicate_pct_trend`
- `distribution_shift_score`

### F. Trust KPIs

- `table_trust_score`
- `column_trust_score`
- `quality_readiness_level`

---

## Required Profiling Extensions

Current profiling should be extended so it persists richer quality metadata per table and per column.

### Table-Level Additions

- row count
- duplicate row estimate
- freshness info
- last timestamp
- completeness score
- trust score
- candidate key quality

### Column-Level Additions

- null count
- null percentage
- distinct count
- distinct ratio
- top values
- unexpected value count
- pattern validity
- numeric range stats
- possible identifier flag
- possible duplicate-join-risk flag

### Fuzzy Duplicate Signals

For selected string dimensions such as:

- location_name
- customer_name
- outlet_name
- product labels

compute heuristic fuzzy duplicate signals:

- normalized token similarity
- edit-distance-like clustering
- punctuation/case-insensitive exact equivalence
- whitespace-normalized equivalence

This does not need to be perfect.
It should surface likely duplicates, not guarantee exact entity resolution.

---

## Suggested Profiling Output Additions

Example per-table structure:

```json
{
  "table": "nozzle_sales",
  "row_count": 123456,
  "latest_timestamp": "2026-04-08T00:00:00Z",
  "freshness_lag_hours": 18,
  "completeness_score": 0.93,
  "duplicate_row_estimate": 120,
  "duplicate_pct": 0.10,
  "trust_score": 0.88,
  "columns": [
    {
      "name": "sales_area",
      "null_count": 54,
      "null_pct": 0.04,
      "distinct_count": 27,
      "pattern_validity": null,
      "trust_score": 0.97
    }
  ],
  "fuzzy_duplicate_signals": [
    {
      "column": "location_name",
      "cluster_count": 4,
      "sample_pairs": [
        ["ABC Fuel Center", "A B C Fuel Centre"]
      ]
    }
  ]
}
```

---

## New Metrics the Pack Should Generate

The pack should generate metrics not from business measures, but from profiling outputs.

Examples:

- `null_pct__nozzle_sales__sales_area`
- `duplicate_pct__nozzle_sales`
- `freshness_lag_hours__nozzle_sales`
- `trust_score__nozzle_sales`
- `rows_with_any_null__nozzle_sales`
- `fuzzy_duplicate_cluster_count__nozzle_sales__location_name`

These metrics may come from:

- materialized profiling artifact tables
- derived quality summary tables
- or synthetic metric registry entries backed by profiling artifacts

---

## Dashboard Design

### Dashboard 1. Data Trust Scorecard

Purpose:

- quick executive view of data health

Charts:

- trust score by table
- freshness status by table
- top risky columns
- table completeness ranking

### Dashboard 2. Missingness and Completeness

Charts:

- null percentage by column
- rows with missing values by day/month
- completeness heatmap by table/column
- top sparse fields

### Dashboard 3. Duplicate and Key Health

Charts:

- duplicate rate by table
- duplicate risk by candidate key
- fuzzy duplicate clusters by string dimension
- uniqueness ratio by column

### Dashboard 4. Freshness and Validity

Charts:

- latest available data timestamp by table
- freshness lag over time
- invalid value counts by rule
- out-of-range violations by numeric column

### Dashboard 5. Profiling Deep Dive

Charts:

- cardinality distribution
- top values for suspect fields
- distribution-shift indicators
- high-null/high-duplicate/high-staleness quadrant

---

## Chart Types This Pack Should Prefer

- scorecards
- ranked bar charts
- heatmaps
- stacked missingness charts
- table/column quality matrices
- freshness trend lines
- risk scatterplots
- profile summary cards

Avoid:

- overloaded business trend charts
- charts that pretend data quality metrics are business KPIs

---

## Semantic Rules for This Pack

### 1. Prefer Profiling Artifacts Over Source Facts

This pack should read from profiling/quality summaries first, not from business fact tables directly wherever possible.

### 2. Table and Column Names Need Human Labels

Raw quality charts should show:

- table labels
- column labels
- business labels where known

not only raw identifiers.

### 3. Trust and Risk Metrics Need Guardrails

Trust scores should be deterministic and interpretable.

The scoring model should be explicit, for example:

- completeness weight
- duplication weight
- freshness weight
- validity weight

### 4. Fuzzy Duplicate Output Must Be Framed as Probabilistic

Do not present fuzzy matches as confirmed duplicates.

Narratives should say:

- likely duplicate
- possible duplicate cluster
- requires review

---

## Suggested Scoring Model

### Table Trust Score

Example formula:

```text
trust_score =
  0.35 * completeness_score +
  0.20 * uniqueness_score +
  0.20 * freshness_score +
  0.15 * validity_score +
  0.10 * stability_score
```

This should be configurable by pack.

### Column Trust Score

Example:

- high nulls reduce score
- high invalid rate reduces score
- high fuzzy duplicate risk reduces score for identifier-like fields

---

## Implementation Plan

### 54A. Pack Definition

Create the new pack and define:

- metric templates
- chart guidance
- dashboard guidance
- quality-specific narratives

### 54B. Profiling Extensions

Extend profiling to compute and persist:

- null statistics
- duplicate statistics
- freshness statistics
- rule validity stats
- fuzzy duplicate candidates

### 54C. Quality Summary Storage

Add a dedicated quality summary artifact model so downstream dashboards do not need to recalculate profiling signals every time.

Suggested storage:

- `quantyx_data_quality_artifacts`
- or extend `quantyx_table_profile_artifacts` with richer quality JSON

### 54D. Quality Metric Generation

Register data quality metrics into the metric registry as a distinct metric family.

Suggested family:

- `data_quality`
- `data_validity`
- `data_trust`

### 54E. Dashboard Composition

Teach dashboard composition to generate a dedicated data quality dashboard from this pack.

Possible modes:

- explicit pack-driven deployment mode
- auto-generate as companion dashboard
- on-demand via workspace

### 54F. Quality Narratives

Add LLM-first or deterministic narrative generation that explains:

- what quality issue is present
- where it is concentrated
- how severe it is
- what it means for downstream analytics trust

### 54G. API and UI Exposure

Expose:

- data quality dashboards
- profiling deep-dive APIs
- table trust summaries
- duplicate review candidates

---

## Required Storage Additions

### Option 1. Extend Profiling Artifacts

Pros:

- fewer tables
- simpler initial rollout

Cons:

- profiling artifact becomes overloaded
- harder to query for UI/dashboard APIs

### Option 2. Add Dedicated Quality Artifact Storage

Recommended.

Suggested table:

#### `quantyx_data_quality_artifacts`

Fields:

- `artifact_id`
- `tenant_id`
- `domain_id`
- `run_id`
- `connection_id`
- `database_name`
- `schema_name`
- `table_name`
- `quality_json`
- `profiling_version`
- `created_at`
- `updated_at`

This can store:

- table-level quality summary
- column-level quality summary
- fuzzy duplicate summary
- trust scores

---

## API Ideas

### Table Quality Summary

`GET /data-quality/tables?tenant_id=...&domain_id=...`

Returns:

- trust score
- row count
- null severity
- duplicate severity
- freshness status

### Table Quality Detail

`GET /data-quality/tables/{table_name}?tenant_id=...&domain_id=...`

Returns:

- column-level nulls
- distinctness
- validity checks
- fuzzy duplicate candidates

### Quality Dashboard

`POST /data-quality/dashboards/generate`

or integrate with workspace deployment/dashboard APIs.

### Duplicate Candidates

`GET /data-quality/duplicates?tenant_id=...&domain_id=...&table_name=...`

---

## Example Use Cases

### 1. Missing Data Dashboard

User wants:

- which columns in `nozzle_sales` are missing data
- how much is missing
- which outlets or time periods are affected

### 2. Duplicate Risk Review

User wants:

- duplicate outlet names
- fuzzy duplicate site names
- near-identical entities that may affect aggregation

### 3. Freshness Monitoring

User wants:

- whether source tables are stale
- what dashboard metrics are impacted by stale data

### 4. Data Readiness for KPI Deployment

User wants:

- whether a dataset is good enough to build executive dashboards

---

## Relationship to Existing Phases

- Phase 15 defines profiling-focused agent roles
- Phase 29 enriches semantic role classification
- Phase 34 ensures profiling artifacts persist durably
- Phase 35 already points toward deeper profiling evidence
- Phase 46 supports narrative persistence
- This phase turns profiling and quality signals into a dedicated packaged analytical product

---

## Risks

### 1. Profiling Cost

Quality profiling can become expensive on large tables.

Mitigation:

- sampling where acceptable
- capped fuzzy duplicate scans
- incremental refreshes

### 2. False Positives in Fuzzy Duplication

Mitigation:

- frame as likely duplicate
- expose confidence
- require review for action

### 3. Trust Score Oversimplification

Mitigation:

- keep weights transparent
- expose component scores

### 4. Dashboard Noise

Too many low-value quality charts will reduce usability.

Mitigation:

- rank by severity
- keep deep profiling in drillable views

---

## Success Criteria

This phase is complete when:

1. a dedicated data quality pack exists
2. profiling persists missingness, duplication, freshness, and trust-oriented signals
3. the system can generate a data quality dashboard from those artifacts
4. users can identify top problematic tables and columns quickly
5. fuzzy duplicate candidates are surfaced with appropriate caveats
6. data trust becomes visible as a first-class analytical product, not only an internal preprocessing detail

---

## Implementation Status and Remaining Work

As of the current repo state, Phase 54 is partially implemented.

### Already Implemented

1. The dedicated pack exists at `packs/data_quality_observability/`.

It includes:

- `pack.yml`
- `metric_templates.yml`
- `chart_guidance.yml`
- `dashboard_guidance.yml`
- `datasets.yml`
- `ontology.yml`
- `policies.yml`
- `validation_rules.yml`

2. Profiling already computes several data quality signals inside `services/ai/agentic_agents.py::profile_tables`.

Current profiling outputs include:

- table row count
- column null count
- column null percentage
- column non-null percentage
- text blank count
- text blank percentage
- distinct count
- distinct ratio
- candidate key duplicate count
- candidate key duplicate percentage
- candidate key uniqueness ratio
- rows with any null
- rows with any null percentage
- table completeness score
- primary time column
- earliest timestamp
- latest timestamp
- freshness lag in days
- sparse and very sparse column flags
- fuzzy duplicate signals for sampled categorical columns
- table trust score
- deployment-level `quality_overview`

3. Profiling artifacts are persisted by the agentic workflow.

The current persistence path is:

- `services/ai/agentic_orchestrator.py` runs `ProfilingAgent`
- `ProfilingAgent` calls `profile_tables`
- the result is persisted through `persist_table_profile_artifact`
- storage lands in `public.quantyx_table_profile_artifacts.profiling_json`

This means the platform already has reusable quality evidence, but it is embedded inside the general profiling artifact.

4. Existing downstream logic already references profiling artifacts for semantic and query support.

Examples:

- runtime metric synthesis reads `quantyx_table_profile_artifacts`
- LLM SQL direct mode uses profiling/table schema context
- correlation code emits some `data_quality_warnings`

These are not the same as a first-class data quality product surface, but they prove the profiling artifact is already part of the active runtime.

### Not Yet Implemented

1. No dedicated `quantyx_data_quality_artifacts` storage table exists yet.

The plan recommends dedicated storage, but the current schema only persists the quality data inside `quantyx_table_profile_artifacts.profiling_json`.

Remaining work:

- add `quantyx_data_quality_artifacts`
- write migration SQL in `artifacts/quantyx_tables.sql` and `artifacts/quantyx_tables_updates.sql`
- add indexes for tenant/domain/run/connection/database/schema/table lookup
- add purge support in tenant cleanup
- decide whether to keep profile JSON as source-of-truth and derive quality artifacts from it, or write both during profiling

2. No dedicated data quality artifact registry/service module exists yet.

Remaining work:

- add a module such as `services/ai/data_quality_artifacts.py`
- add functions to upsert and fetch table-level quality artifacts
- add functions to flatten `profiling_json.tables[*].quality_summary`, `column_profiles`, `candidate_keys`, and `fuzzy_duplicate_signals`
- keep writes idempotent per tenant/domain/run/connection/database/schema/table

3. No first-class `/data-quality/...` API surface appears to exist yet.

The doc proposes APIs such as:

- `GET /data-quality/tables`
- `GET /data-quality/tables/{table_name}`
- `GET /data-quality/duplicates`
- `POST /data-quality/dashboards/generate`

Remaining work:

- add request/response schemas in `services/api/schemas.py`
- add route handlers in `services/api/main.py` or a dedicated router if the API is split later
- support scope parameters: `tenant_id`, `domain_id`, `run_id`, `connection_id`, `database_name`, `schema_name`
- return table summaries, column details, freshness information, trust score components, and duplicate/fuzzy duplicate candidates

4. No first-class data quality dashboard generation path appears to be wired yet.

The pack has dashboard guidance, but there is no obvious dedicated path that turns profiling quality artifacts into generated dashboards.

Remaining work:

- add a dashboard composition mode for `data_quality_observability`
- build chart candidates from profiling artifacts instead of source business facts
- generate the planned dashboards:
  - Data Trust Scorecard
  - Missingness and Completeness Dashboard
  - Duplicate and Uniqueness Risk Dashboard
  - Freshness and Stability Dashboard
  - Profiling Deep Dive
- persist those dashboards with a clear dashboard type/source so they do not mix with business KPI dashboards

5. Data quality metrics are defined in the pack but are not yet clearly materialized as registry metrics.

Remaining work:

- generate metric definitions from profiling artifacts, not business facts
- use distinct metric families such as `data_quality`, `data_validity`, and `data_trust`
- decide whether metrics are synthetic/in-memory, persisted into `quantyx_metrics_registry`, or backed by a materialized quality summary table
- prevent these metrics from being treated as normal business KPI measures

6. Trust scoring is implemented but still simple and not pack-configurable.

Current scoring averages available components such as completeness, duplicate penalty, and freshness penalty.

Remaining work:

- move trust score weights into pack config or validation rules
- expose component scores, not only the final table trust score
- add explicit severity bands such as good, warning, critical
- add separate column trust scores
- make score interpretation deterministic and documented for users

7. Validity checks are still shallow.

The current implementation has null, blank, distinctness, candidate key, and freshness signals, but does not yet appear to compute the full validity family.

Remaining work:

- pattern violation counts
- out-of-range counts
- unexpected category counts
- malformed record counts
- optional domain-specific validation rule hooks from `validation_rules.yml`
- validity score and validity contribution to table/column trust score

8. Stability and drift are not yet fully implemented.

The plan calls for row count drift, value distribution shift, and columns becoming sparse over time.

Remaining work:

- store historical quality snapshots
- compare current row counts/null percentages/distinct ratios against prior snapshots
- compute drift indicators
- generate trend charts from historical quality artifacts

9. Fuzzy duplicate handling is currently heuristic and embedded in profiling.

Remaining work:

- persist fuzzy duplicate candidates in a queryable artifact shape
- include sample pairs and cluster summaries in API responses
- expose clear probability/review wording in narratives
- add thresholds in `validation_rules.yml`
- cap runtime cost for large categorical columns

10. Quality narratives are not yet a dedicated product surface.

Remaining work:

- add deterministic narrative fallback for table and column quality issues
- optionally add LLM-first quality summaries using complete quality context
- persist `insight_text`, `narrative_text`, and `stats_json` for quality dashboards/charts
- ensure narratives frame fuzzy duplicates as possible duplicates requiring review

11. UI/workspace integration remains to be defined.

Remaining work:

- decide whether data quality dashboards are generated automatically as companion dashboards during deployment
- support explicit on-demand generation from workspace
- expose table quality drill-downs
- expose duplicate review candidates
- make data quality dashboards discoverable separately from business dashboards

12. Tests and regression coverage are missing for this phase.

Suggested tests:

- unit tests for flattening profiling JSON into quality artifact rows
- unit tests for trust score component calculation
- API tests for table summary/detail endpoints
- dashboard composition tests for data quality pack mode
- regression tests ensuring data quality metrics do not become business KPI candidates
- fuzzy duplicate tests with deterministic sample data and conservative wording
