# 59. Enterprise Data Quality Reporting, Observability, and Stewardship

## Objective

Extend the current data quality reporting layer so it behaves like an enterprise DQ operating system rather than a single-run validation export. The goal is to support:

- run-to-run quality monitoring
- anomaly-aware reporting
- issue lifecycle management
- business-facing stewardship views
- certification / publish-readiness decisions
- richer executive and operational reporting in dashboard, API, and Excel

This phase builds on:

- [55_Data_Quality_Agentic_Workflow_Validation_and_Enrichment.md](./55_Data_Quality_Agentic_Workflow_Validation_and_Enrichment.md)
- [58_Multi_Table_Data_Quality_Joins_Filters_Lineage_and_Final_Dataset_Reporting.md](./58_Multi_Table_Data_Quality_Joins_Filters_Lineage_and_Final_Dataset_Reporting.md)

It does not replace those phases. It adds the enterprise reporting and stewardship layer on top of them.

---

## Implementation Checklist

### Done

- [x] `trend_mode` persisted on deployment and DQ runs
- [x] backend-derived `trend_scope_key` and `trend_scope_label`
- [x] `POST /workspace/deployments/{run_id}/rerun`
- [x] run lineage persistence and APIs
- [x] run-level metric snapshot table
- [x] object-level metric snapshot table
- [x] derived trend table
- [x] trend APIs
- [x] hydration trend card
- [x] dashboard trend section
- [x] Excel trend sheets
- [x] resume-after-review trend persistence
- [x] baseline reset comparison cutoff behavior
- [x] rerun lineage edge typing for `rerun`, `rerun_monitor`, and `baseline_reset`
- [x] richer LLM-first semantic `trend_scope_key` inference with prior-scope reuse
- [x] issue register persistence and APIs
- [x] hydration issue card
- [x] dashboard issue sections
- [x] Excel issue register sheets

### Pending

- [x] anomaly snapshotting and anomaly trend surfaces
- [x] certification / publish-readiness trend surfaces
- [x] glossary / business-term grouped trend views
- [ ] stronger rule identity evolution handling across changed rule text
- [ ] trend-aware recommendation escalation beyond current remediation integration
- [x] UI graph examples for run lineage + trend chains

---

## Problems To Solve

The current platform is strong on:

- profiling
- rule execution
- evidence
- dashboard generation
- Excel generation
- lineage and stage reporting

But it is still weak in the areas that enterprise DQ tools treat as first-class:

1. quality trends across runs
2. anomaly detection and drift reporting
3. issue register with owner / status / SLA
4. business-term grouping of validations
5. certification and publish-readiness views
6. steward work queues
7. aggregated executive reporting across runs

Today the system answers:

- what failed in this run

It needs to also answer:

- what changed since last run
- what is worsening
- what is stable
- what needs action now
- who owns the action
- is the dataset fit for publication

---

## Desired Product Outcome

For any DQ run, the system should be able to produce:

1. a technical validation report
2. an operational issue register
3. an executive summary with trends and readiness
4. a steward work queue
5. a historical quality monitoring view across runs

The report should support both:

- one-run deep analysis
- cross-run observability and decision-making

---

## Core Capabilities To Add

### 59A. Quality Trends Across Runs

Persist and expose run-over-run trends for:

- trust score
- completeness
- validity
- uniqueness
- referential integrity
- freshness
- duplicate risk
- enrichment opportunity count
- rejected record count
- final dataset readiness

The system should classify changes as:

- improved
- worsened
- unchanged
- newly introduced
- resolved

#### New report sections

- `Quality Trends`
- `Rule Trends`
- `Table Trend Summary`
- `Final Dataset Trend Summary`

#### New dashboard sections

- trend cards
- trust trend by table
- failed rule trend
- duplicate trend
- freshness trend
- rejected record trend

#### New APIs

- `GET /data-quality/trends`
- `GET /data-quality/trends/tables/{table_name}`
- `GET /data-quality/trends/rules/{rule_id}`

#### Deployment and Comparison Scope Decision

For trend analysis, the system should continue to allow:

- multiple `run_id`s for the same `tenant_id`
- multiple `run_id`s for the same `tenant_id + domain_id`

Trend analysis should **not** compare all runs in a tenant/domain blindly.

Instead, each run should belong to a stable monitoring comparison scope.

##### Required deployment field

- `trend_mode`

Recommended values:

- `monitor`
- `ad_hoc`
- `baseline_reset`

##### Meaning

`monitor`

- include the run in trend history
- compare it to prior runs in the same inferred monitoring scope

`ad_hoc`

- run normal DQ workflow
- do not include the run in official trend history by default

`baseline_reset`

- include the run in trend history
- treat it as the new baseline for future comparisons in that scope

##### `trend_scope_key`

Each run should persist a `trend_scope_key`, but users should **not** be required to provide it in normal flows.

The `trend_scope_key` is used only for one purpose:

- determine which previous runs are comparable to the current run

It answers:

- “when computing trends for this run, which prior runs belong to the same monitoring scope?”

##### Inference strategy

If `trend_mode = monitor`, backend should infer `trend_scope_key` automatically.

Inference should use:

- tenant
- domain
- connection
- database
- schema
- sorted tables in scope
- compiled stage-plan identity
- final dataset intent if present

The backend should:

1. build a normalized fingerprint for the current run
2. search prior monitor runs for the same tenant/domain
3. score similarity against previous scope fingerprints
4. reuse the previous `trend_scope_key` when the match is strong
5. create a new `trend_scope_key` when the run is materially different

This avoids forcing users to invent and manage scope keys themselves.

##### User override behavior

Advanced users may optionally supply `trend_scope_key`, but this should be treated as an override, not as a required deployment parameter.

Normal UX should be:

- user provides `trend_mode`
- backend infers or reuses `trend_scope_key`

##### Preferred monitoring UX: rerun endpoint

The preferred monitoring UX should not require users to re-enter:

- business context
- scope
- tables
- reconciliation logic
- final dataset intent

Instead, the system should support a dedicated rerun endpoint:

- `POST /workspace/deployments/{run_id}/rerun`

Payload:

```json
{
  "trend_mode": "monitor"
}
```

Backend behavior:

1. load the original run definition
2. reuse:
   - `tenant_id`
   - `domain_id`
   - `connection_id`
   - `database`
   - `schema_name`
   - scoped tables
   - `context_text`
   - deployment mode
   - compiled monitoring intent where available
3. create a new `run_id`
4. set `trend_mode`
5. infer or reuse `trend_scope_key`
6. execute the workflow as a new run
7. compute trend artifacts against prior runs in the same scope

The original run remains immutable. A rerun always creates a new run.

Recommended future UI actions:

- `Rerun`
- `Rerun as Monitor`
- `Rerun as New Baseline`

##### Comparison policy

Trend analysis should only compare runs that match on:

- same `tenant_id`
- same `domain_id`
- same `trend_scope_key`

This is the minimum technically sound comparison contract.

##### Run lineage across reruns

To support future run-history graph visualization, reruns should persist run lineage metadata in addition to row lineage from Phase 58.

Run lineage answers:

- which run was created from which prior run
- which run is the root of a monitoring chain
- which reruns belong to the same monitoring series
- where baseline resets happened

Each run should persist:

- `parent_run_id`
- `rerun_root_run_id`
- `rerun_reason`
- `trend_mode`
- `trend_scope_key`

Recommended `rerun_reason` values:

- `manual_rerun`
- `trend_monitor`
- `baseline_reset`
- `post_remediation`
- `scheduled_monitor`

Add a persistence table for run lineage, for example:

`quantyx_agent_run_lineage`

Columns:

- `lineage_edge_id`
- `tenant_id`
- `domain_id`
- `parent_run_id`
- `child_run_id`
- `edge_type`
- `trend_scope_key`
- `created_at`
- `summary_json`

Recommended `edge_type` values:

- `rerun`
- `rerun_monitor`
- `baseline_reset`
- `scheduled_followup`

Add APIs:

- `GET /agentic/runs/{run_id}/lineage`
- `GET /agentic/runs/lineage?tenant_id=...&domain_id=...`

This enables future UI views such as:

- rerun chains
- trend-monitoring history graph
- baseline reset markers
- run-event graph overlays

##### Timeline events for reruns and trends

Rerun lineage should also be reflected in the run event stream so the UI can render:

- “rerun started from run_X”
- “monitoring scope reused”
- “baseline reset created”
- “trend comparison completed”
- “worsened metrics detected”

Recommended event artifacts:

- `parent_run_id`
- `rerun_root_run_id`
- `rerun_reason`
- `trend_mode`
- `trend_scope_key`
- `baseline_run_id`
- `trend_summary`

This ensures the event timeline and the run-lineage graph are consistent views of the same underlying execution chain.

##### UI Graph Contract for Run Lineage and Trend Chains

The run-lineage API should be directly usable by the frontend graph view.

Preferred response shape:

- `graph`
- `nodes`
- `edges`

Where:

- `graph`
  - root/focus metadata
  - counts
  - participating `trend_scope_key` values
- `nodes`
  - one node per run in the lineage chain
  - includes run metadata such as:
    - `run_id`
    - `display_name`
    - `status`
    - `version_no`
    - `trend_mode`
    - `trend_scope_key`
    - `trend_scope_label`
    - `parent_run_id`
    - `rerun_root_run_id`
    - `created_at`
    - `is_focus_run`
    - `is_root_run`
- `edges`
  - persisted lineage edges with:
    - `parent_run_id`
    - `child_run_id`
    - `edge_type`
    - `trend_scope_key`

This graph payload should support:

- rerun chain visualization
- monitor chain visualization
- baseline reset markers
- future overlay of trend summaries per run node

#### Trend Analysis Implementation Model

Trend analysis should be implemented as a dedicated derived layer over persisted run artifacts.

The system should **not** compute trends:

- inside dashboard rendering only
- inside Excel generation only
- only in UI
- ad hoc from many raw tables on every read

Instead, trend analysis should have two layers:

1. snapshot layer
2. derived trend layer

##### 1. Snapshot layer

Every DQ run should persist a canonical, trend-friendly metric snapshot.

This snapshot should be normalized and stable so trend logic can reuse it without scraping many different artifact tables each time.

The snapshot layer should include:

###### Run-level metrics

- overall trust score
- failed rule count
- duplicate candidate count
- stale table count
- rejected record count
- final dataset row count
- final dataset readiness status
- anomaly count
- open issue count

###### Table-level metrics

Per table:

- row count
- trust score
- completeness
- validity
- uniqueness
- referential integrity score
- freshness score
- duplicate risk score
- failed rule count
- rejected record count
- anomaly count

###### Rule-level metrics

Per logical rule:

- result status
- violation count
- violation pct
- severity

###### Stage-level metrics

Per stage:

- input row count
- output row count
- rejected row count
- matched row count
- unmatched left row count
- unmatched right row count
- duplicate match count
- rejection pct

###### Final dataset metrics

- final row count
- readiness status
- blocking issue count
- warning issue count
- residual failed rule count
- residual anomaly count

#### Stable logical keys for trend comparison

Trend analysis must compare the same logical object across runs.

The system should define stable comparison keys:

###### Table key

- `table_name`

###### Column key

- `table_name + column_name`

###### Rule logical key

Rules are often run-scoped, so trend analysis should not depend only on `rule_id`.

Define a stable `rule_logical_key` from:

- `table_name`
- `column_name`
- `rule_type`
- `reference_table`
- `reference_column`
- normalized `condition_json`

###### Stage logical key

Define `stage_logical_key` from:

- `stage_type`
- `stage_name`
- `output_dataset`
- normalized join/filter expression if present

###### Final dataset key

- `final_dataset`
- or a compiled final dataset intent key

Without stable logical keys, trend analysis will produce noisy and misleading comparisons.

#### Trend storage model

The system should persist both snapshots and derived trends.

##### `quantyx_data_quality_run_metric_snapshots`

One row per run-level metric.

Columns:

- `snapshot_id`
- `tenant_id`
- `domain_id`
- `run_id`
- `quality_run_id`
- `trend_scope_key`
- `metric_name`
- `metric_value_num`
- `metric_value_text`
- `metric_unit`
- `captured_at`

##### `quantyx_data_quality_object_metric_snapshots`

One row per object-level metric.

Columns:

- `object_snapshot_id`
- `tenant_id`
- `domain_id`
- `run_id`
- `quality_run_id`
- `trend_scope_key`
- `object_type`
- `object_key`
- `object_name`
- `metric_name`
- `metric_value_num`
- `metric_value_text`
- `metric_unit`
- `captured_at`

Supported `object_type` values:

- `table`
- `rule`
- `stage`
- `final_dataset`

##### Snapshot creation requirements

Snapshot creation must happen for every completed DQ run, regardless of whether a previous comparable run exists.

This is required so:

- first runs become future baselines
- ad hoc runs still have metrics available if later promoted
- trend history can be backfilled consistently

Each snapshot row should be written from already persisted DQ artifacts, not recomputed by re-scanning source data.

The source of truth should be:

- run summary artifacts
- table summary artifacts
- rule result artifacts
- stage / join artifacts
- final dataset artifacts
- issue / anomaly / certification artifacts once implemented

##### Required snapshot groups

###### A. Run summary snapshot

One logical snapshot per run containing:

- `overall_trust_score`
- `validation_rule_count`
- `failed_rule_count`
- `duplicate_candidate_count`
- `stale_table_count`
- `rejected_record_count`
- `join_exception_count`
- `final_dataset_row_count`
- `final_dataset_readiness_status`
- `dataset_stage_count`
- `join_stage_count`
- `filter_stage_count`
- `lineage_edge_count`
- `approved_enrichment_row_count`
- `deferred_enrichment_row_count`

###### B. Table snapshot

One logical snapshot per table containing:

- `row_count`
- `trust_score`
- `completeness_score`
- `validity_score`
- `uniqueness_score`
- `referential_integrity_score`
- `freshness_score`
- `duplicate_risk_score`
- `failed_rule_count`
- `rejected_record_count`
- `freshness_status`
- `stability_status`

###### C. Rule snapshot

One logical snapshot per logical rule containing:

- `rule_logical_key`
- `rule_label`
- `rule_type`
- `severity`
- `result_status`
- `violation_count`
- `violation_pct`
- `checked_row_count`

This is what enables:

- trend line per rule
- recurring rule failures
- resolved rules
- newly introduced failures

###### D. Stage snapshot

One logical snapshot per stage containing:

- `stage_logical_key`
- `stage_name`
- `stage_type`
- `input_row_count`
- `output_row_count`
- `rejected_row_count`
- `matched_row_count`
- `unmatched_left_row_count`
- `unmatched_right_row_count`
- `duplicate_match_count`
- `rejection_pct`

This is what enables:

- stage waterfall trend lines
- join-health trend lines
- filter-loss trend lines

###### E. Final dataset snapshot

One logical snapshot for final dataset output containing:

- `final_row_count`
- `readiness_status`
- `blocking_issue_count`
- `warning_issue_count`
- `residual_failed_rule_count`
- `residual_anomaly_count`

This is what enables:

- publish-readiness trend lines
- final-output stability monitoring

###### F. Issue and anomaly snapshots

Once Phase 59 issue/anomaly artifacts are implemented, snapshots should also be created for:

- open issue count
- overdue issue count
- critical issue count
- anomaly count
- schema drift count
- repeated anomaly count

These are needed for stewardship and executive trend lines.

##### Snapshot granularity and naming

Snapshot rows should be narrow and metric-oriented rather than one large JSON blob per object.

This gives:

- simpler comparisons
- simpler indexing
- easier aggregation across runs
- easier charting for trend lines

Do not store trend history only as one nested JSON document per run.

That makes rule-level and stage-level trend lines unnecessarily difficult.

##### Snapshot keys required for trend lines

Each snapshot row must include:

- `tenant_id`
- `domain_id`
- `run_id`
- `quality_run_id`
- `trend_scope_key`
- `object_type`
- `object_key`
- `metric_name`
- `captured_at`

This is the minimum key needed to build:

- trend by run order
- trend by timestamp
- trend by object
- trend by monitoring scope

##### Snapshot retention and historical behavior

Snapshots should not be overwritten.

Every run adds new snapshot rows.

Trend lines are then built by ordering snapshots by:

- `captured_at`
- or run creation time

This gives:

- clean time series
- rerun chain continuity
- baseline reset markers without losing history

##### Baseline reset handling

When `trend_mode = baseline_reset`:

- snapshot rows are still persisted normally
- trend rows should mark this run as a new baseline boundary
- future runs in the same scope should compare against this new baseline chain

This should not delete old history.

Instead it should mark:

- baseline transition
- previous baseline run id
- new baseline run id

##### Trend lines across multiple rules

To generate trend lines across many rules, the system should:

1. normalize each rule into `rule_logical_key`
2. snapshot per-rule metrics for every run
3. group rule snapshots by:
   - `tenant_id`
   - `domain_id`
   - `trend_scope_key`
   - `rule_logical_key`
4. sort by run timestamp
5. emit rule trend rows and chartable series

This allows:

- per-rule violation trend
- top worsening rules
- most frequently failing rules
- newly introduced rules
- resolved rules

##### Trend lines across multiple tables and stages

The same pattern should be used for:

- table trend lines via `table_name`
- stage trend lines via `stage_logical_key`
- final dataset trend lines via `final_dataset`

This should produce:

- trust trend by table
- row count trend by table
- join match rate trend by stage
- filter rejection trend by stage
- final row count trend by final dataset

##### Snapshot-driven APIs

Trend APIs should read from trend tables and snapshots, not from raw run artifacts directly.

This allows:

- fast hydration
- stable Excel generation
- chart-friendly dashboard responses
- time-series queries without recomputing DQ metrics

##### Timeline integration with snapshots

When trend artifacts are created, the run timeline should emit an event like:

- `TrendAnalysisAgent completed`

with artifact payload:

- `trend_scope_key`
- `baseline_run_id`
- `run_metric_snapshot_count`
- `object_metric_snapshot_count`
- `trend_row_count`
- `improved_metric_count`
- `worsened_metric_count`

This makes the event timeline itself explain how the trend layer was produced.

##### `quantyx_data_quality_trends`

Derived comparison rows.

Columns:

- `trend_id`
- `tenant_id`
- `domain_id`
- `run_id`
- `quality_run_id`
- `trend_scope_key`
- `baseline_run_id`
- `object_type`
- `object_key`
- `metric_name`
- `previous_value`
- `baseline_value`
- `current_value`
- `delta_value`
- `delta_pct`
- `trend_status`
- `directionality`
- `summary_json`
- `created_at`

#### Trend directionality registry

The system should not use one generic up/down rule for all metrics.

Each metric must define whether:

- higher is better
- lower is better
- status transition logic is required

##### Higher is better

- trust score
- completeness
- validity
- uniqueness
- referential integrity score
- freshness score
- join match rate

##### Lower is better

- failed rule count
- duplicate candidate count
- stale lag
- rejected record count
- filter rejection pct
- unmatched join counts

##### Status-transition metrics

- final dataset readiness
- certification status
- issue severity state

These must use explicit transition mapping such as:

- `blocked -> ready` = improved
- `ready -> blocked` = worsened

#### Comparison baselines

Trend analysis should support two comparison references:

##### Previous comparable run

Used for:

- operational monitoring
- what changed since last run

##### Rolling baseline

Used for:

- anomaly support
- smoothing one-off noise
- longer-term quality drift

The first implementation can use previous comparable run only, but the storage model should allow baseline support later.

#### When trend analysis should run

Trend analysis should execute near the end of the workflow, after all final artifacts are persisted.

Recommended order:

1. profiling
2. rules
3. duplicates
4. freshness
5. trust
6. lineage / final dataset
7. snapshot persistence
8. trend analysis
9. dashboard generation
10. Excel generation

This ensures:

- dashboard uses persisted trend artifacts
- Excel uses persisted trend artifacts
- hydration does not need to recompute trends

#### Agents for trend analysis

##### `TrendSnapshotAgent`

Responsibilities:

- collect normalized run/table/rule/stage/final-dataset metrics
- persist snapshot rows

##### `TrendScopeInferenceAgent`

Responsibilities:

- infer or reuse `trend_scope_key`
- normalize scope keys
- find best prior comparable scope

##### `TrendAnalysisAgent`

Responsibilities:

- load current snapshot
- load prior comparable snapshots
- compute trend rows
- classify trend status
- persist trend artifacts

#### Tools for trend analysis

All interpretation-oriented parts should be LLM-first where semantics matter, with deterministic normalization and persistence.

##### `TrendScopeInferenceTool`

Inputs:

- tenant
- domain
- connection
- database
- schema
- tables
- compiled stage plan
- final dataset intent
- prior monitor runs

Outputs:

- `trend_scope_key`
- `trend_scope_label`
- `scope_type`
- `matched_prior_scope`
- `confidence`
- `rationale`

This tool should be LLM-first for semantic grouping, followed by deterministic normalization and exact reuse logic.

##### `RunMetricSnapshotTool`

Build run-level snapshot rows from current persisted artifacts.

##### `ObjectMetricSnapshotTool`

Build table/rule/stage/final-dataset snapshot rows.

##### `MetricDirectionalityTool`

Resolve metric interpretation:

- higher better
- lower better
- status transition

This can be deterministic from a metric registry.

##### `TrendDeltaComputationTool`

Compute:

- previous value
- current value
- delta value
- delta pct

##### `TrendClassificationTool`

Classify:

- improved
- worsened
- unchanged
- newly introduced
- resolved
- baseline

##### `PersistTrendArtifactsTool`

Persist derived trend rows into `quantyx_data_quality_trends`.

#### Trend APIs in detail

##### `GET /data-quality/trends`

Purpose:

- run-level and mixed summary trends for the current run

Recommended response:

- `trend_scope_key`
- `planner_mode`
- `baseline_run_id`
- run-level trend summary
- notable worsened metrics
- notable improved metrics
- grouped trend rows

##### `GET /data-quality/trends/tables/{table_name}`

Purpose:

- table-focused trend history and current deltas

Should return:

- table trend summary
- metric rows
- previous comparable run id
- evidence links

##### `GET /data-quality/trends/rules/{rule_logical_key}`

Purpose:

- rule-focused history using logical key, not only run-scoped `rule_id`

Should return:

- prior results
- current result
- trend classification
- recurring issue summary

#### Hydration integration

`GET /data-quality/runs/{run_id}/hydration` should include:

- trend summary card
- improved metric count
- worsened metric count
- baseline run id
- top worsened items
- top improved items

This keeps reload to:

1. timeline/events API
2. hydration API

without requiring immediate separate trend fetches.

#### Dashboard and Excel integration

Dashboard and Excel should render trend artifacts from the same persisted trend rows.

##### Dashboard sections

- executive trend cards
- trust trend by table
- failed rule trend
- duplicate trend
- rejected record trend
- final dataset trend

##### Excel sheets

- `Quality Trends`
- `Rule Trends`
- `Table Trend Summary`
- `Final Dataset Trend Summary`

All trend surfaces should include:

- previous value
- current value
- delta
- delta pct
- trend status
- baseline / previous run reference

#### Decision rules for when trends should appear

Trend analysis should be persisted for every run, but only shown as meaningful comparison when:

- there is a previous run with the same `trend_scope_key`, or
- the run is explicitly marked `monitor`, or
- certification / readiness evaluation requires history

If there is no prior comparable run, the system should return:

- `trend_status = baseline`
- `baseline_run_id = null`

This avoids special-case UI logic.

#### Recommendations integration

Recommendations should use trend artifacts to produce stronger guidance.

Examples:

- trust score worsened 3 runs in a row -> escalate stewardship priority
- duplicate count spiked -> recommend upstream key normalization
- final dataset rows dropped sharply -> recommend investigating filter/join bottlenecks
- readiness remained blocked for multiple runs -> recommend blocking publication until resolution

Trend-aware recommendations should be a first-class derivative of the trend layer, not a separate ad hoc heuristic in the dashboard.

---

### 59B. Anomaly Detection and Drift Reporting

Add anomaly and drift surfaces for:

- row-count anomalies
- null-rate anomalies
- duplicate spikes
- freshness regressions
- distribution shifts
- schema drift
- final dataset output drift

Each anomaly should include:

- anomaly id
- anomaly type
- impacted table / column / stage
- baseline
- current value
- delta
- severity
- evidence path
- first seen / last seen

#### New report sections

- `Anomalies`
- `Schema Changes`
- `Metric Drift`

#### New dashboard sections

- anomaly summary cards
- drift heatmap
- schema change summary

#### New APIs

- `GET /data-quality/anomalies`
- `GET /data-quality/anomalies/{anomaly_id}`
- `GET /data-quality/schema-drift`

---

### 59C. Issue Register and Stewardship Workflow

Add a first-class issue register derived from:

- failed rules
- join exceptions
- filter loss concentration
- anomalies
- duplicate candidates
- stale datasets
- final dataset readiness blockers

Each issue should have:

- issue id
- title
- issue type
- severity
- impacted object
- owner
- status
- first seen
- last seen
- due date / SLA
- evidence path
- recommendation
- related run ids

#### Standard issue statuses

- `open`
- `in_progress`
- `deferred`
- `resolved`
- `accepted_risk`

#### New report sections

- `Issue Register`
- `Steward Work Queue`
- `SLA Breaches`

#### New dashboard sections

- open issues by severity
- issue aging
- owner workload
- overdue issues

#### New APIs

- `GET /data-quality/issues`
- `GET /data-quality/issues/{issue_id}`
- `POST /data-quality/issues/{issue_id}/assign`
- `POST /data-quality/issues/{issue_id}/status`

---

### 59D. Business-Term and Domain-Control Grouping

Group validations by business meaning, not only by table and column.

Examples:

- subscriber identity quality
- mediation completeness
- billing integrity
- roaming settlement consistency
- financial reconciliation quality

Each rule or issue should optionally map to:

- business domain
- business term
- control family
- regulatory / audit classification

#### New report sections

- `Business Control Coverage`
- `Control Family Summary`
- `Domain Risk Summary`

#### New dashboard sections

- controls by family
- risk by business domain
- uncovered controls

#### New APIs

- `GET /data-quality/control-coverage`
- `GET /data-quality/business-risk`

---

### 59E. Certification and Publish Readiness

Add an explicit readiness decision layer:

- `ready`
- `warning`
- `blocked`

This should be computed from:

- critical failed rules
- join exception thresholds
- filter loss thresholds
- anomaly severity
- freshness requirements
- unresolved high-severity issues
- final dataset quality thresholds

#### New report sections

- `Certification Summary`
- `Publish Readiness`
- `Blocking Issues`

#### New dashboard sections

- readiness badge
- blocking issue cards
- certification rationale

#### New APIs

- `GET /data-quality/certification`
- `GET /data-quality/publish-readiness`

---

## Storage Model

### 1. `quantyx_data_quality_trends`

One row per run/object/metric trend.

Columns:

- `trend_id`
- `tenant_id`
- `domain_id`
- `run_id`
- `quality_run_id`
- `object_type`
- `object_name`
- `metric_name`
- `previous_value`
- `current_value`
- `delta_value`
- `delta_pct`
- `trend_status`
- `created_at`

### 2. `quantyx_data_quality_anomalies`

Columns:

- `anomaly_id`
- `tenant_id`
- `domain_id`
- `run_id`
- `quality_run_id`
- `anomaly_type`
- `table_name`
- `column_name`
- `stage_id`
- `severity`
- `baseline_value`
- `current_value`
- `delta_value`
- `delta_pct`
- `summary_json`
- `evidence_path`
- `first_seen_at`
- `last_seen_at`
- `status`

### 3. `quantyx_data_quality_issues`

Columns:

- `issue_id`
- `tenant_id`
- `domain_id`
- `run_id`
- `quality_run_id`
- `issue_type`
- `title`
- `severity`
- `table_name`
- `column_name`
- `stage_id`
- `owner_id`
- `status`
- `due_at`
- `first_seen_at`
- `last_seen_at`
- `evidence_path`
- `recommendation_json`
- `summary_json`

### 4. `quantyx_data_quality_control_groups`

Columns:

- `control_group_id`
- `tenant_id`
- `domain_id`
- `run_id`
- `quality_run_id`
- `control_family`
- `business_term`
- `risk_level`
- `summary_json`

### 5. `quantyx_data_quality_certification`

Columns:

- `certification_id`
- `tenant_id`
- `domain_id`
- `run_id`
- `quality_run_id`
- `readiness_status`
- `blocking_issue_count`
- `warning_issue_count`
- `certification_summary_json`
- `created_at`

---

## Agents

### 1. `TrendAnalysisAgent`

Responsibilities:

- compare current run against prior runs
- compute metric deltas and status
- persist trend artifacts

### 2. `AnomalyDetectionAgent`

Responsibilities:

- detect metric drift and anomaly conditions
- persist anomalies with evidence

### 3. `IssueRegisterAgent`

Responsibilities:

- convert failures, anomalies, and stage issues into tracked issues
- derive severity and ownership hints
- persist issue records

### 4. `BusinessControlGroupingAgent`

Responsibilities:

- map rules and issues into business control families
- identify uncovered controls

### 5. `CertificationAgent`

Responsibilities:

- determine readiness state
- identify blockers and warnings
- persist certification decision

### 6. `ExecutiveReportingAgent`

Responsibilities:

- create executive summary view across all the above artifacts
- shape summary for dashboard, hydration, and Excel

---

## Tools

All reporting-oriented agents in this phase should be LLM-first for interpretation and deterministic for metric computation and persistence.

### `TrendAnalysisAgent`

Tools:

- `RunMetricHistoryTool`
- `MetricDeltaComputationTool`
- `TrendClassificationTool`
- `PersistTrendArtifactsTool`

### `AnomalyDetectionAgent`

Tools:

- `MetricBaselineLoaderTool`
- `AnomalyThresholdTool`
- `SchemaDriftDetectionTool`
- `PersistAnomalyArtifactsTool`

### `IssueRegisterAgent`

Tools:

- `IssueDerivationTool`
- `IssueSeverityTool`
- `IssueOwnerHintTool`
- `PersistIssueTool`

### `BusinessControlGroupingAgent`

Tools:

- `ControlFamilyInferenceTool`
- `BusinessTermMapperTool`
- `CoverageGapTool`
- `PersistControlGroupingTool`

### `CertificationAgent`

Tools:

- `ReadinessPolicyTool`
- `BlockingIssueResolverTool`
- `CertificationDecisionTool`
- `PersistCertificationTool`

### `ExecutiveReportingAgent`

Tools:

- `ExecutiveSummaryBuilderTool`
- `StewardQueueBuilderTool`
- `TrendNarrativeTool`
- `PersistReportingSummaryTool`

---

## Excel Workbook Design

The workbook should evolve into an enterprise DQ operating report.

### Required sheets

- `Legend`
- `Executive Summary`
- `Certification Summary`
- `Publish Readiness`
- `Quality Trends`
- `Anomalies`
- `Schema Changes`
- `Issue Register`
- `Steward Work Queue`
- `Business Control Coverage`
- `Rule Summary`
- `Rule Violations`
- one sheet per failed rule
- `Join Health`
- `Filter Impact`
- `Rejected Records`
- `Join Exceptions`
- `Lineage Overview`
- `Final Dataset`
- one `All Data {table}` per source table
- one `Stage {n} {name}` per measured stage
- `Recommended Actions`

### Excel principles

- no raw JSON in cells
- all summaries flattened into readable columns
- failed rule sheets contain the actual failed records
- issue sheets contain status / owner / SLA columns
- trend sheets contain previous/current/delta columns
- anomaly sheets contain baseline/current/deviation columns
- certification sheets clearly show `ready`, `warning`, or `blocked`

---

## Dashboard Design

### Required sections

- `summary_view`
- `executive_summary`
- `publish_readiness`
- `quality_trends`
- `anomaly_summary`
- `issue_register`
- `steward_queue`
- `business_control_coverage`
- `join_health`
- `filter_impact`
- `final_dataset_quality`
- `lineage_overview`
- `recommended_actions`

### Design requirements

- no empty sections
- every aggregate metric must have an evidence path
- trend sections must show baseline and delta
- issue sections must support actionability, not only observation
- readiness must be visible as a top-level decision surface

---

## API Additions

### Trend APIs

- `GET /data-quality/trends`
- `GET /data-quality/trends/tables/{table_name}`
- `GET /data-quality/trends/rules/{rule_id}`

### Anomaly APIs

- `GET /data-quality/anomalies`
- `GET /data-quality/anomalies/{anomaly_id}`
- `GET /data-quality/schema-drift`

### Issue APIs

- `GET /data-quality/issues`
- `GET /data-quality/issues/{issue_id}`
- `POST /data-quality/issues/{issue_id}/assign`
- `POST /data-quality/issues/{issue_id}/status`

### Control / Business APIs

- `GET /data-quality/control-coverage`
- `GET /data-quality/business-risk`

### Certification APIs

- `GET /data-quality/certification`
- `GET /data-quality/publish-readiness`

### Hydration additions

`GET /data-quality/runs/{run_id}/hydration` should include:

- trend summary card
- anomaly summary card
- issue register summary card
- readiness summary card
- steward queue summary card

---

## Recommendations Inference

Recommendations should no longer be derived only from single-run rule failures. They should also account for:

- worsening trends
- repeated anomalies
- issue aging
- unresolved blockers
- large filter loss concentrations
- persistent join mismatch patterns
- certification blockers

Examples:

- repeated freshness degradation -> recommend upstream refresh SLA alignment
- duplicate spike after a source change -> recommend key normalization review
- unresolved join mismatch across 3 runs -> recommend reference-data governance fix
- final dataset blocked by critical billing control -> recommend steward hold before publication

---

## Implementation Order

### Step 1

Trend persistence and trend APIs

### Step 2

Anomaly persistence and anomaly APIs

### Step 3

Issue register and stewardship workflow

### Step 4

Certification and publish-readiness decision layer

### Step 5

Business control grouping and coverage views

### Step 6

Excel and dashboard expansion

### Step 7

Hydration and workspace integration

---

## Acceptance Criteria

1. A DQ run can be compared to prior runs with persisted trend artifacts.
2. The system can detect and expose anomalies with evidence.
3. A first-class issue register exists with owner, status, and SLA fields.
4. The system can determine `ready`, `warning`, or `blocked` publish readiness.
5. The dashboard includes trends, anomalies, issue register, stewardship queue, and readiness sections.
6. The Excel workbook includes trend, anomaly, issue, and certification sheets.
7. All new report surfaces remain explainable with evidence links.
8. No JSON blobs are rendered directly into Excel cells.
9. Hydration includes summary cards for enterprise reporting state.

---

## Out Of Scope For This Phase

- source-system writeback
- external MDM/workflow integration
- ticketing system integration
- full regulatory control library management

Those can be added later once the internal issue and certification model is stable.
