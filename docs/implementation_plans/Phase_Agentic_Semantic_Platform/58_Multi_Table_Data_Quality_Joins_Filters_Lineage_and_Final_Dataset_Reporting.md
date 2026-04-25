# 58. Multi-Table Data Quality, Joins, Filters, Lineage, and Final Dataset Reporting

## Objective

Extend the data-quality workflow so it can handle:

- multiple source tables
- join-driven validation
- filter-driven row reduction
- cross-table rule execution
- final curated dataset quality assessment
- row-journey explainability across stages

This phase is not just about profiling individual tables.
It adds a pipeline view of data quality:

1. source-table quality
2. cross-table join/filter quality
3. final dataset quality

The output must support both:

- steward/debug views
- business-facing final curated dataset views

---

## Why this phase is needed

Single-table profiling is not enough when the final business dataset is built from:

- joins across dimensions and facts
- business filters
- enrichment or normalization steps
- rule checks that depend on more than one table

Example:

1. `orders` is joined to `customer`
2. unmatched customers are dropped
3. only active customers are kept
4. only recent orders are kept
5. records with invalid amount or invalid status are excluded
6. final publish dataset is produced

In this case, the important DQ question is not only:

- is `orders` good?
- is `customer` good?

It is also:

- what happened to the rows across the pipeline?
- where were rows lost?
- why were rows filtered out?
- how trustworthy is the final dataset?

---

## Design principle

The system should model the workflow as named **stages**.

Each stage should be explainable and queryable.

Examples of stages:

- source profile stage
- join stage
- filter stage
- normalization stage
- validation stage
- final projection stage

Every stage should retain:

- input row count
- output row count
- rejected row count
- rule/filter reason summaries
- sample evidence rows
- stage-specific metrics

---

## Three reporting layers

### 1. Source-table quality

This is the current data-quality model, extended to multi-table scope.

For each source table:

- completeness
- validity
- duplicates
- freshness
- trust score
- table-specific rule failures

### 2. Cross-table / stage quality

This is new.

For each join/filter/transformation stage:

- join match rate
- unmatched rows
- duplicate match explosion
- filter drop rates
- cross-table rule failures
- stage-level trust impact

### 3. Final curated dataset quality

This is the publish-facing view.

For the final dataset:

- final row count
- rows rejected across journey
- final completeness
- final validity
- final trust score
- final remaining issues
- publish readiness

---

## Dashboard design

The dashboard should contain both source quality and pipeline quality.

### Required sections

1. **Executive Summary**
   - overall trust
   - total source rows
   - final dataset rows
   - total rows rejected
   - top failure stage
   - top join issue
   - top filter issue
   - publish readiness

2. **Source Table Quality**
   - one row/card per source table
   - trust, completeness, duplicates, freshness

3. **Join Health**
   - join name
   - left row count
   - matched row count
   - unmatched left rows
   - unmatched right rows when relevant
   - multi-match or blow-up risk
   - evidence path

4. **Stage Waterfall**
   - source rows
   - after joins
   - after filters
   - after validations
   - final rows

5. **Filter Impact**
   - rows removed by each filter
   - percentage removed
   - dominant reason buckets

6. **Cross-Table Rule Failures**
   - orphan foreign keys
   - inconsistent dimensions
   - temporal inconsistencies across tables
   - business-rule failures involving joined fields

7. **Final Dataset Quality**
   - final row count
   - final trust score
   - remaining issue counts
   - readiness status

8. **Recommended Actions**
   - recommendations inferred from source issues, join failures, stage loss, and final quality

### Explainability requirement

Every count and chart must support drill-through.

Examples:

- unmatched rows in a join -> fetch the unmatched records
- filtered out rows -> fetch records removed by that filter
- final dataset row count -> fetch final surviving records
- stage drop -> fetch the rejected records and reasons

---

## Excel report design

The workbook should contain both:

- final curated dataset views
- row journey / stewardship views

### Recommended sheets

1. `Legend`
2. `Executive Summary`
3. `Source Table Quality`
4. `Join Health`
5. `Stage Waterfall`
6. `Filter Impact`
7. `Cross-Table Rule Failures`
8. `Recommended Actions`
9. one `All Data {table}` sheet per source table
10. one `Stage {n} {name}` sheet per major join/filter stage
11. `Rejected Records`
12. `Final Dataset`
13. `Join Exceptions`

### Sheet behavior

#### `All Data {table}`

- original rows from each source table
- failed cell-level validations highlighted
- source-only view

#### `Stage {n} {name}`

Each stage sheet should show the dataset snapshot at that stage.

Recommended columns:

- row lineage id
- source row refs
- stage status
- pass/fail
- rejection reason
- joined fields used at that stage
- selected business columns

#### `Rejected Records`

Contains rows removed anywhere in the pipeline.

Recommended columns:

- row lineage id
- source refs
- stage name
- reject reason
- rule/filter name
- sample business fields

#### `Final Dataset`

Contains the records that survive all stages.

This is the final publish-facing output.

Recommended columns:

- final row lineage id
- business-facing output fields
- issue flags if any still remain
- confidence / trust annotations if needed

---

## Final dataset vs journey

The product should support both views, not force one.

### Final dataset view

Best for:

- business consumers
- downstream export
- publish-ready review

### Journey view

Best for:

- data stewards
- debugging joins and filters
- explaining row loss
- tuning business rules

### Product decision

The run output should contain:

- a final curated dataset view
- a stage-by-stage journey view

The Excel workbook should contain both.

The dashboard should summarize both.

---

## Recommendation engine for multi-table flows

Recommendations should not be derived only from table-level nulls.

They should also come from:

- join failure patterns
- filter over-restriction
- row-loss concentration by stage
- final dataset weakness
- cross-table temporal mismatch

### Recommendation examples

#### Join failures

Pattern:

- many `orders.customer_id` do not match `customer.customer_id`

Recommendation:

- normalize customer identifiers before the join
- improve dimension completeness upstream
- add pre-join validation to block orphan rows earlier

#### Filter-heavy loss

Pattern:

- 40% of records are removed by one business filter

Recommendation:

- review whether the filter is too strict
- separate hard reject from warning
- expose a pre-publish review gate before applying the filter

#### Stage concentration

Pattern:

- source tables look healthy
- most row loss happens after join + normalization

Recommendation:

- move standardization/canonicalization earlier
- improve reference mappings before join
- add alias resolution before downstream business filters

#### Final dataset weakness

Pattern:

- final dataset still contains high-null critical columns

Recommendation:

- require enrichment or steward review before publish
- make those columns publish-gating checks

#### Freshness asymmetry

Pattern:

- one table is stale and causes join loss against a fresher table

Recommendation:

- align refresh cadence across joined tables
- add freshness gating before final publish

---

## Data model additions

To support this phase cleanly, add stage-aware persistence.

### 1. Dataset stage summary table

Suggested table:

- `quantyx_data_quality_dataset_stages`

Suggested columns:

- `stage_id`
- `quality_run_id`
- `run_id`
- `tenant_id`
- `domain_id`
- `stage_seq`
- `stage_name`
- `stage_type`
- `input_row_count`
- `output_row_count`
- `rejected_row_count`
- `summary_json`
- `created_at`

### 2. Dataset stage row outcomes table

Suggested table:

- `quantyx_data_quality_dataset_stage_rows`

Suggested columns:

- `stage_row_id`
- `stage_id`
- `row_lineage_id`
- `source_row_refs_json`
- `row_status`
- `reason_code`
- `reason_text`
- `raw_json`
- `created_at`

This allows the system to answer:

- which rows survived?
- which rows were rejected?
- at what stage?
- for what reason?

### 3. Join validation artifacts

Suggested table:

- `quantyx_data_quality_join_artifacts`

Suggested columns:

- `join_artifact_id`
- `quality_run_id`
- `run_id`
- `join_name`
- `left_table`
- `right_table`
- `join_type`
- `join_keys_json`
- `matched_row_count`
- `unmatched_left_row_count`
- `unmatched_right_row_count`
- `duplicate_match_count`
- `summary_json`
- `created_at`

### 4. Final dataset artifact table

Suggested table:

- `quantyx_data_quality_final_dataset_artifacts`

Suggested columns:

- `final_dataset_artifact_id`
- `quality_run_id`
- `run_id`
- `dataset_name`
- `row_count`
- `column_count`
- `trust_score`
- `quality_summary_json`
- `storage_uri`
- `created_at`

---

## Agent design

### Existing agents still apply

- schema
- profiling
- rules
- duplicates
- freshness
- trust
- dashboard
- report

### New agents needed

#### `DatasetStagePlannerAgent`

Responsible for:

- understanding the intended multi-table dataset flow
- identifying joins, filters, projections, and validation stages
- creating a stage plan

Inputs:

- source tables
- context text
- semantic mappings

Outputs:

- dataset stage plan

#### `JoinValidationAgent`

Responsible for:

- executing join-quality checks
- producing matched/unmatched counts
- identifying multi-match explosions
- persisting join artifacts

#### `DatasetLineageStageAgent`

Responsible for:

- materializing stage summaries
- tracking row lineage across stages
- storing stage outcomes and reject reasons

#### `FinalDatasetQualityAgent`

Responsible for:

- computing quality metrics on the final dataset
- generating publish readiness summary

---

## Agent-specific tools

For this phase, agents should not share one broad generic toolset.

They should use:

1. shared foundation tools
2. agent-specific tools
3. artifact-writing tools
4. evidence tools

The goal is:

- clear ownership
- narrow responsibilities
- better explainability
- easier testing

### Shared foundation tools

These are reusable low-level tools available across multiple agents.

Examples:

- `load_schema_graph_tool`
- `run_scoped_sql_tool`
- `fetch_sample_rows_tool`
- `fetch_row_count_tool`
- `profile_distinct_values_tool`
- `fetch_prior_run_artifact_tool`
- `llm_structured_extraction_tool`
- `persist_artifact_tool`

These should be wrapped by higher-level task tools wherever possible.

---

### `DatasetStagePlannerAgent` tools

Purpose:

- build the stage plan from schema and context

Tools:

- `load_dataset_context_tool`
- `infer_stage_plan_tool`
- `resolve_join_candidates_tool`
- `resolve_filter_candidates_tool`
- `resolve_projection_candidates_tool`
- `persist_stage_plan_tool`

Inputs:

- schema graph
- business context
- source tables in scope

Outputs:

- ordered stage plan

#### Domain-adaptive planning tools

The stage planner should not depend on domain-specific hardcoded phrases.
It should use a reusable set of planner tools that convert business context into a structured multi-stage plan.

These tools should be domain-independent and driven by:

- context text
- schema graph
- column profiling
- sample values
- prior persisted artifacts where useful

Recommended planner tools:

1. `DomainContextInterpreterTool`
   - reads business context
   - identifies:
     - workflow type
     - table roles
     - reconciliation intents
     - match goals
     - filter intents
     - tolerance/window hints
     - final dataset objective
   - should be LLM-first with structured output only

2. `SharedKeyInferenceTool`
   - infers likely shared keys across tables
   - uses:
     - schema names
     - profiled distinct counts
     - overlap hints
     - sample values
     - semantic aliases from context
   - should return exact, alias, and composite key candidates with confidence and rationale

3. `AsymmetryDetectionTool`
   - detects non-symmetric relationships between the two sides
   - examples:
     - different field names for the same business key
     - temporal aliasing like `rating_timestamp -> event_time`
     - subset/superset expectations
     - eligibility gating before comparison
   - should return normalization, tolerance, and pre-filter requirements

4. `JoinStrategyBuilderTool`
   - converts inferred keys and asymmetries into executable join strategies
   - examples:
     - exact key join
     - alias key join
     - composite join
     - windowed temporal join
     - left-only exception join
     - bidirectional reconciliation join

5. `FilterIntentResolutionTool`
   - extracts business filters from context
   - examples:
     - billable only
     - active customers only
     - inside reconciliation window
     - roaming only
   - should return structured filter plans, not only free-form text

6. `StagePlanCompilerTool`
   - compiles interpreted intents into an ordered executable stage plan
   - stage types may include:
     - source
     - normalize
     - join
     - filter
     - validate
     - final projection

7. `DomainEvidenceSamplerTool`
   - fetches representative samples to support planning and reduce blind inference
   - examples:
     - sample key values
     - null/blank patterns
     - overlap counts
     - join samples

#### Tool output contract

These planner tools should return structured JSON contracts, not prose.

Examples:

- `AsymmetryDetectionTool`
  ```json
  {
    "asymmetry_type": "temporal_alias",
    "left_table": "billing_cdr_data",
    "right_table": "roaming_settlement_data",
    "left_field": "rating_timestamp",
    "right_field": "event_time",
    "comparison_mode": "windowed_match",
    "tolerance_seconds": 900
  }
  ```

- `SharedKeyInferenceTool`
  ```json
  {
    "left_table": "network_cdr_data",
    "right_table": "mediation_data",
    "match_keys": [
      {"left_key": "call_id", "right_key": "call_id", "kind": "exact"},
      {"left_key": "msisdn", "right_key": "subscriber_number", "kind": "semantic_alias"}
    ]
  }
  ```

#### Execution model

The planner should follow this pattern:

1. use LLM-based structured interpretation for domain context
2. validate and refine with deterministic profiling and evidence sampling
3. compile the final structured stage plan deterministically
4. persist the compiled plan as the source of truth for execution

This is the general solution across domains.
It avoids brittle telecom-only or billing-only logic while still allowing domain semantics to emerge from context.

---

### `JoinValidationAgent` tools

Purpose:

- evaluate join quality and exceptions

Tools:

- `run_join_cardinality_check_tool`
- `run_join_match_rate_tool`
- `fetch_unmatched_left_rows_tool`
- `fetch_unmatched_right_rows_tool`
- `detect_join_explosion_tool`
- `persist_join_artifact_tool`

Inputs:

- join definition
- left/right source references

Outputs:

- join health metrics
- join evidence rows

---

### `DatasetLineageStageAgent` tools

Purpose:

- track row movement and rejection across stages

Tools:

- `materialize_stage_snapshot_tool`
- `compute_stage_row_diff_tool`
- `assign_row_lineage_ids_tool`
- `persist_stage_rows_tool`
- `persist_stage_summary_tool`

Inputs:

- stage definition
- prior stage output

Outputs:

- stage summary
- row lineage outcomes

---

### `RuleExecutionAgent` tools

Purpose:

- run stage-aware validation rules

Tools:

- `compile_rule_sql_tool`
- `run_rule_validation_tool`
- `fetch_rule_failure_rows_tool`
- `persist_rule_result_tool`

Inputs:

- canonical rules
- stage dataset

Outputs:

- rule results
- evidence rows

---

### `FinalDatasetQualityAgent` tools

Purpose:

- assess the final curated dataset

Tools:

- `load_final_stage_rows_tool`
- `compute_final_dataset_quality_tool`
- `compute_publish_readiness_tool`
- `persist_final_dataset_artifact_tool`

Inputs:

- final stage output
- final rule results

Outputs:

- final dataset quality summary
- publish readiness

---

### `RecommendationAgent` tools

Purpose:

- derive stage-aware recommendations

Tools:

- `load_stage_metrics_tool`
- `load_join_failures_tool`
- `load_final_dataset_quality_tool`
- `derive_recommendations_tool`
- `persist_recommendation_artifact_tool`

Inputs:

- source table metrics
- join metrics
- stage loss metrics
- final dataset metrics

Outputs:

- explainable prioritized recommendations

---

### `ExcelReportAgent` tools

Purpose:

- render the final workbook

Tools:

- `load_report_sections_tool`
- `load_all_data_sheet_rows_tool`
- `load_stage_sheet_rows_tool`
- `load_rejected_rows_tool`
- `load_join_exception_rows_tool`
- `load_final_dataset_rows_tool`
- `render_excel_workbook_tool`

Inputs:

- all persisted DQ artifacts

Outputs:

- workbook binary
- report metadata

---

### `DashboardAgent` tools

Purpose:

- build the dashboard artifact

Tools:

- `load_dashboard_metrics_tool`
- `build_summary_view_tool`
- `build_source_table_quality_view_tool`
- `build_join_health_view_tool`
- `build_stage_waterfall_view_tool`
- `build_filter_impact_view_tool`
- `build_final_dataset_view_tool`
- `persist_dashboard_tool`

Inputs:

- source metrics
- stage metrics
- join metrics
- final dataset metrics

Outputs:

- explainable dashboard artifact

---

### Artifact-writing tools

Agents should not write persistence logic ad hoc.

Use explicit persistence tools such as:

- `persist_stage_plan_tool`
- `persist_join_artifact_tool`
- `persist_stage_rows_tool`
- `persist_stage_summary_tool`
- `persist_final_dataset_artifact_tool`
- `persist_recommendation_artifact_tool`
- `persist_dashboard_tool`

This gives:

- stable contracts
- clearer ownership
- easier testability

---

### Evidence tools

All major metrics must support evidence drill-through.

Suggested reusable tools:

- `fetch_missingness_evidence_tool`
- `fetch_join_exception_evidence_tool`
- `fetch_stage_rejection_evidence_tool`
- `fetch_final_dataset_rows_tool`
- `fetch_rule_failure_evidence_tool`

These should be used by:

- dashboard drill-through
- workspace responses
- report generation
- evidence APIs

---

## Tooling principles

1. Agents should decide **what** to do.
2. Tools should decide **how** to fetch, compute, or persist data.
3. Raw unrestricted SQL access should be minimized at the agent layer.
4. Persistence should go through owned artifact-writing tools.
5. Evidence retrieval should be reusable across API, dashboard, Excel, and workspace surfaces.

---

## API additions

This section reflects the current implemented FastAPI contract, not placeholder endpoint names.

### Run-level summary and hydration

- `GET /data-quality/runs/{run_id}`
- `GET /data-quality/runs/{run_id}/hydration`
- `GET /data-quality/runs/{run_id}/dashboard`
- `GET /data-quality/reports/{run_id}/excel?tenant_id=...&domain_id=data_quality_observability`

Multi-table fields currently surfaced on the run payload:

- `dataset_stage_count`
- `join_stage_count`
- `filter_stage_count`
- `total_rejected_row_count`
- `final_dataset_row_count`
- `final_dataset_readiness_status`
- `lineage_edge_count`

Artifact links currently exposed on the run payload:

- `stages`
- `joins`
- `rejected_records`
- `final_dataset`
- `final_dataset_rows`
- `lineage`
- `lineage_base`

### Stage and join APIs

- `GET /data-quality/stages?tenant_id=...&domain_id=...&run_id=...`
- `GET /data-quality/stages/{stage_id}?tenant_id=...`
- `GET /data-quality/joins?tenant_id=...&domain_id=...&run_id=...`
- `GET /data-quality/joins/{join_artifact_id}?tenant_id=...`

These return persisted stage and join artifacts with measured counts where available.

### Stage and join evidence APIs

- `GET /data-quality/evidence/stages/{stage_id}?tenant_id=...&domain_id=...`
- `GET /data-quality/evidence/joins/{join_artifact_id}?tenant_id=...&domain_id=...`

Current evidence behavior:

- source stages return measured row samples
- join stages return matched/unmatched rows
- filter stages return passed rows and rejected rows

### Rejected records and final dataset APIs

- `GET /data-quality/rejected-records?tenant_id=...&domain_id=...&run_id=...`
- `GET /data-quality/final-dataset?tenant_id=...&domain_id=...&run_id=...`
- `GET /data-quality/final-dataset/rows?tenant_id=...&domain_id=...&run_id=...`

These are the current implemented surfaces for:

- rejected-row listings
- final dataset summary artifact
- final surviving row output

### Lineage APIs

- `GET /data-quality/lineage?tenant_id=...&domain_id=...&run_id=...`
- `GET /data-quality/lineage/{row_lineage_id}?tenant_id=...&domain_id=...&run_id=...`
- `GET /data-quality/lineage/{row_lineage_id}/journey?tenant_id=...&domain_id=...&run_id=...`

Current intent of each:

- `/data-quality/lineage`
  - run-level lineage overview rows
  - transition counts
  - latest stage
  - final state
  - final dataset membership

- `/data-quality/lineage/{row_lineage_id}`
  - raw persisted trace
  - edges
  - outcomes
  - stage trace
  - best-effort final dataset membership

- `/data-quality/lineage/{row_lineage_id}/journey`
  - UI-friendly journey
  - ordered steps
  - display labels
  - status categories

### Example: stage list response

```json
{
  "tenant_id": "VC_101",
  "domain_id": "data_quality_observability",
  "run_id": "run_dq_001",
  "stages": [
    {
      "stage_id": "dqstage_001",
      "stage_seq": 1,
      "stage_name": "source_profile_orders",
      "stage_type": "source_profile",
      "input_row_count": 100000,
      "output_row_count": 100000,
      "rejected_row_count": 0,
      "summary_json": {
        "measurement_status": "measured",
        "evidence_path": "/data-quality/evidence/stages/dqstage_001?tenant_id=VC_101&domain_id=data_quality_observability"
      }
    },
    {
      "stage_id": "dqstage_002",
      "stage_seq": 2,
      "stage_name": "orders_to_customer_customer_id",
      "stage_type": "join_validation",
      "input_row_count": 100000,
      "output_row_count": 98200,
      "rejected_row_count": 1800,
      "summary_json": {
        "measurement_status": "measured",
        "evidence_path": "/data-quality/evidence/stages/dqstage_002?tenant_id=VC_101&domain_id=data_quality_observability"
      }
    }
  ]
}
```

### Example: join list response

```json
{
  "tenant_id": "VC_101",
  "domain_id": "data_quality_observability",
  "run_id": "run_dq_001",
  "joins": [
    {
      "join_artifact_id": "dqjoin_001",
      "join_name": "orders_to_customer_customer_id",
      "left_table": "orders",
      "right_table": "customer",
      "join_type": "reference_lookup",
      "matched_row_count": 98200,
      "unmatched_left_row_count": 1800,
      "unmatched_right_row_count": 0,
      "duplicate_match_count": 0,
      "summary_json": {
        "measurement_status": "measured",
        "evidence_path": "/data-quality/evidence/joins/dqjoin_001?tenant_id=VC_101&domain_id=data_quality_observability"
      }
    }
  ]
}
```

### Example: final dataset summary response

```json
{
  "tenant_id": "VC_101",
  "domain_id": "data_quality_observability",
  "run_id": "run_dq_001",
  "final_dataset": {
    "artifact_id": "dqfinal_001",
    "final_stage_name": "final_dataset_projection",
    "final_row_count": 97120,
    "total_rejected_row_count": 2880,
    "readiness_status": "ready",
    "summary_json": {
      "measurement_status": "derived",
      "lineage_enabled": true
    }
  }
}
```

### Example: lineage overview response

```json
{
  "tenant_id": "VC_101",
  "domain_id": "data_quality_observability",
  "run_id": "run_dq_001",
  "summary": {
    "lineage_row_count": 12,
    "final_dataset_member_count": 8,
    "rejected_row_count": 3,
    "join_exception_row_count": 1
  },
  "rows": [
    {
      "row_lineage_id": "dqlin_b3JkZXJzfCgwLDEp_a1b2c3d4",
      "source_table": "orders",
      "source_row_ref": "(0,1)",
      "decoded_lineage": "orders -> (0,1)",
      "transition_count": 2,
      "stage_count": 3,
      "rejected_count": 0,
      "join_exception_count": 0,
      "latest_stage_name": "final_dataset_projection",
      "final_state": "final_dataset_member",
      "final_dataset_member": true,
      "evidence_path": "/data-quality/lineage/dqlin_b3JkZXJzfCgwLDEp_a1b2c3d4/journey?tenant_id=VC_101&domain_id=data_quality_observability&run_id=run_dq_001"
    }
  ]
}
```

### Example: lineage journey response

```json
{
  "run_id": "run_dq_001",
  "row_lineage_id": "dqlin_b3JkZXJzfCgwLDE1KQ_a1b2c3d4",
  "source": {
    "source_table": "orders",
    "source_row_ref": "(0,15)",
    "decoded_lineage": "orders|(0,15)"
  },
  "summary": {
    "step_count": 2,
    "transition_count": 1,
    "outcome_count": 1,
    "final_dataset_member": false,
    "final_state": "join_unmatched_left"
  },
  "journey": [
    {
      "step_index": 1,
      "stage_id": "dqstage_001",
      "stage_seq": 1,
      "stage_name": "source_profile_orders",
      "stage_type": "source_profile",
      "state": "entered",
      "status_category": "progressed",
      "display_label": "Entered source_profile_orders"
    },
    {
      "step_index": 2,
      "stage_id": "dqstage_002",
      "stage_seq": 2,
      "stage_name": "orders_to_customer_customer_id",
      "stage_type": "join_validation",
      "state": "join_unmatched_left",
      "status_category": "rejected",
      "display_label": "Rejected by left-side join mismatch in orders_to_customer_customer_id"
    }
  ]
}
```

### Dashboard/report hydration additions

Current hydration now includes lineage in addition to rules, enrichment, and remediation.

`GET /data-quality/runs/{run_id}/hydration` should be treated as the primary UI bootstrap for:

- stage count
- join artifact count
- final dataset row count
- rejected row count
- lineage summary
- top lineage items

---

## UI behavior

### Run summary

The run summary should show:

- source rows
- final rows
- total rejected rows
- top loss stage
- publish readiness

### Dashboard

Dashboard should support:

- source table quality views
- stage waterfall
- join health
- filter impact
- final dataset quality

### Evidence drill-through

Clicking a stage/join/filter/final count should open:

- the underlying rows
- rejection reasons
- source lineage

### Excel export

The run-level Excel export should provide:

- a final publish-facing dataset view
- a row-journey and reject-reason view

---

## Phase execution order

### 58A. Stage planning

- build stage plan from context
- persist stage metadata

### 58B. Join validation

- join health metrics
- join evidence rows

### 58C. Stage lineage persistence

- row lineage ids
- stage pass/fail outcomes
- rejected-row capture

### 58D. Final dataset quality

- final row count
- final quality/trust summary
- publish readiness

### 58E. Dashboard updates

- join health
- stage waterfall
- filter impact
- final dataset quality

### 58F. Excel updates

- stage sheets
- rejected records
- final dataset sheet

### 58G. Recommendation expansion

- stage-aware recommendations
- join/filter/final-dataset recommendations

---

## Acceptance criteria

1. The system can evaluate DQ across multiple joined tables.
2. Join quality is visible and explainable.
3. Filter impact is visible and explainable.
4. The final dataset has its own quality/trust summary.
5. The Excel workbook contains both:
   - final dataset sheets
   - stage journey sheets
6. Rejected records are exportable with stage/reason context.
7. Recommendations are based on both source-table issues and stage-level loss patterns.
8. Every aggregate metric remains drill-through capable.

---

## Out of scope for this phase

- source-table writeback
- destructive mutation of customer datasets
- hidden automatic filtering without persisted stage evidence
- ad hoc undocumented joins that are not represented in stage metadata
