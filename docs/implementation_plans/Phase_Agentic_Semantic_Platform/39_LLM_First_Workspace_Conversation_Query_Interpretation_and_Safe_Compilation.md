# Phase 39: LLM-First Workspace Conversation Query Interpretation and Safe Compilation

## Objective
Make workspace conversation query understanding LLM-first, with deterministic validation and SQL/chart compilation afterward.

The goal is to fix failures where conversational questions are partially understood or compiled incorrectly, such as:
- missing explicit date filters from user questions
- leakage of identifier columns like `id` into grouped analytics
- broken aggregation plans caused by grouping on row-level fields
- chart dimensions not matching the requested breakdown

Example target behavior:
- user asks: `Provide productivity (in cylinders per hour) by zone and filling head for 19-Mar-2026`
- system should produce:
  - metric: `productivity`
  - dimensions: `zone`, `filling_head`
  - filter: `process_date = 2026-03-19`
  - chart intent: grouped bar/table
  - deterministic SQL that validates against deployed semantic artifacts

---

## Problem

The current workspace message path is still too heuristic-first.

Observed failure modes:
- date phrases are not consistently converted into filters
- identifiers such as `id` can enter grouped query dimensions
- the system can group by both the measure and an identifier, collapsing the result back to near-row-level output
- the returned chart can ignore part of the user-requested breakdown
- narrative text can claim one interpretation while SQL reflects another

This is especially visible in workspace conversation queries, where user phrasing is richer and more specific than simple NL-to-SQL templates.

---

## Target State
1. Workspace message interpretation is LLM-first.
2. The LLM produces a structured intermediate query plan instead of SQL.
3. Deterministic validators resolve and approve:
   - metric
   - dimensions
   - filters
   - time grain
   - chart intent
4. The SQL builder compiles only validated plans.
5. Identifier fields and other disallowed dimensions never appear in grouped analytics unless explicitly allowed for a detail-table intent.
6. Requested date/time constraints are preserved in the final SQL.
7. Requested breakdowns are preserved in both SQL and chart shape.

---

## Core Principles

### 1) LLM First for Meaning
The LLM should interpret the user question first.

It should extract:
- business intent
- metric candidates
- requested dimensions
- requested filters
- date/time constraints
- desired chart/table intent
- ranking/sort direction if implied or explicit

The LLM should not emit executable SQL as the source of truth.

### 2) Deterministic Validation for Safety
After interpretation, deterministic validators must:
- bind requested fields to deployed semantic artifacts
- reject unknown metrics/dimensions
- reject identifiers from analytic group-bys
- validate time filters and time columns
- validate aggregation compatibility
- compile safe SQL

### 3) Conversation Semantics Must Match SQL
The system should not narrate one interpretation and execute another.

The final response must have alignment across:
- user request
- resolved structured plan
- SQL
- chart payload
- assistant summary

---

## Scope

### In scope
- workspace conversation query interpretation
- LLM-first extraction of metrics, dimensions, filters, and chart intent
- deterministic validation and safe compilation
- identifier exclusion for grouped analytics
- explicit date filter extraction and binding
- response/chart alignment with resolved query intent
- observability and diagnostics for interpreted conversation plans

### Out of scope
- replacing deployment-time agentic build flow
- unrestricted LLM-authored SQL execution
- broad UI redesign

---

## User Stories
- As a workspace user, when I ask for a KPI by specific dimensions on a specific date, the SQL should honor those exact constraints.
- As an analyst, I should never get grouped analytics broken by row identifiers like `id`.
- As a user, the chart should reflect the breakdowns I asked for, not a simplified or unrelated projection.
- As a developer, I need to inspect the interpreted query plan separately from compiled SQL.

---

## Proposed Architecture

### Step 1: LLM Query Interpretation
Input:
- user query
- conversation memory summary
- run-scoped semantic artifacts
- deployed metric/dimension glossary
- eligible time columns
- approved business dimensions

Output:
- structured conversation query plan

Suggested shape:
```json
{
  "intent": "analytic_query",
  "metric_candidates": ["productivity"],
  "dimensions": ["zone", "filling_head"],
  "filters": [
    {
      "field_role": "date",
      "operator": "=",
      "value": "2026-03-19"
    }
  ],
  "time_grain": "day",
  "chart_intent": "grouped_bar",
  "sort": [
    {
      "field": "productivity",
      "direction": "desc"
    }
  ],
  "response_mode": "chart_plus_table"
}
```

### Step 2: Deterministic Binding and Validation
The validator resolves the plan against:
- deployed metrics
- approved dimensions
- eligible time columns
- semantic role classification
- chart restrictions

Validation rules:
- reject identifier fields in grouped analytics:
  - `id`
  - `*_id`
  - candidate keys
  - near-unique identifiers
- reject grouping by the measure itself
- bind date filters to the canonical time column if confidence is high
- ensure requested dimensions exist and are eligible

### Step 3: Safe SQL Compilation
Compile only validated plans.

Examples:
- grouped analytic query
- trend query
- detail table query
- ranking query

### Step 4: Response Alignment
The compiled response should use the validated plan for:
- SQL
- chart type
- chart dimensions
- chart title
- summary text
- inference text

---

## Required Fixes from Current Behavior

### 39.1 Date Filter Extraction
Explicit date phrases like:
- `for 19-Mar-2026`
- `on March 19, 2026`
- `yesterday`
- `this month`

must become structured time filters before SQL compilation.

### 39.2 Identifier Exclusion in Grouped Analytics
Fields like:
- `id`
- `entity_id`
- `sap_id`
- any candidate key

must be excluded from analytic group-bys unless the resolved intent is explicitly a detail-table query.

### 39.3 Requested Breakdown Preservation
If the user asks:
- `by zone and filling head`

the final SQL and chart should preserve both dimensions unless validation forces a clear fallback.

### 39.4 Measure and Group-By Separation
The query compiler must reject plans that:
- group by the same measure being aggregated
- combine aggregate intent with row-level identifiers

### 39.5 Chart Shape Alignment
The chart builder must respect the resolved conversation plan:
- `zone + filling_head` should not collapse into only `filling_head`
- grouped vs stacked vs table intent should come from the validated plan

---

## Workflow Placement

This phase affects the workspace conversation path:
- `POST /workspace/conversations/{conversation_id}/messages`

Recommended internal order:
1. load conversation memory + run-scoped artifacts
2. LLM interpret query
3. deterministic validate/bind
4. safe compile SQL
5. execute
6. build aligned chart payload
7. persist assistant message with the interpreted plan

---

## API and Persistence Changes

### Response Artifacts
The assistant message should additionally persist:
- interpreted query plan
- validated query plan
- validation warnings

Recommended fields inside assistant artifacts:
```json
{
  "conversation_plan": {
    "raw_llm_plan": {},
    "validated_plan": {},
    "validation_warnings": []
  }
}
```

### Message Persistence Shape
The current workspace assistant message already persists:
- `sql_text`
- `data_json`
- `chart_json`
- `summary_json`
- `inference_json`

This phase should extend the persisted assistant message artifacts with:
```json
{
  "conversation_plan": {
    "raw_llm_plan": {
      "intent": "analytic_query",
      "metric_candidates": ["productivity"],
      "dimensions": ["zone", "filling_head"],
      "filters": [
        {
          "field_role": "date",
          "operator": "=",
          "value": "2026-03-19"
        }
      ],
      "time_grain": "day",
      "chart_intent": "grouped_bar",
      "response_mode": "chart_plus_table"
    },
    "validated_plan": {
      "metric_name": "productivity",
      "base_table": "fact_lpg_plant_operations",
      "dimensions": ["zone", "filling_head"],
      "filters": [
        {
          "column": "process_date",
          "operator": "=",
          "value": "2026-03-19",
          "value_type": "date"
        }
      ],
      "chart_type": "grouped_bar",
      "sort": [
        {
          "field": "productivity",
          "direction": "desc"
        }
      ],
      "response_mode": "chart_plus_table"
    },
    "rejected_candidates": {
      "dimensions": ["id"],
      "filters": [],
      "metrics": []
    },
    "validation_warnings": [
      "identifier_dimension_rejected:id"
    ]
  }
}
```

---

## Concrete Code Changes

### Primary Files

The initial implementation should focus on these files:

1. [main.py](/Users/vnagaraju/PycharmProjects/quantyx-core/services/api/main.py)
- update `_workspace_query_response(...)`
- update `workspace_send_message(...)`
- optionally add a debug/read API for the persisted conversation plan

2. [resolver.py](/Users/vnagaraju/PycharmProjects/quantyx-core/services/ai/resolver.py)
- extend or replace current LLM resolver output with a richer structured conversation plan contract

3. New module recommended:
- `services/ai/workspace_query_planner.py`

This module should contain:
- `interpret_workspace_query(...)`
- `validate_workspace_query_plan(...)`
- `compile_workspace_query_plan(...)`
- `conversation_plan_diagnostics(...)`

4. [charts.py](/Users/vnagaraju/PycharmProjects/quantyx-core/services/ai/charts.py)
- align chart inference/building with validated conversation plan
- prevent collapsing requested multi-breakdown plans into single-category charts unless fallback is explicit

5. [workspace_store.py](/Users/vnagaraju/PycharmProjects/quantyx-core/services/ai/workspace_store.py)
- ensure the persisted assistant message can store the enriched `conversation_plan` artifact cleanly

### Existing Function Touchpoints

The current conversation path runs through:
- `_workspace_query_response(...)` in [main.py](/Users/vnagaraju/PycharmProjects/quantyx-core/services/api/main.py)
- `workspace_send_message(...)` in [main.py](/Users/vnagaraju/PycharmProjects/quantyx-core/services/api/main.py)
- `resolve_question(...)` in [resolver.py](/Users/vnagaraju/PycharmProjects/quantyx-core/services/ai/resolver.py)
- `resolve_question_semantic(...)` in [semantic_graph_resolver.py](/Users/vnagaraju/PycharmProjects/quantyx-core/services/ai/semantic_graph_resolver.py)
- `build_chart_payload(...)` and `infer_chart_type(...)` in [charts.py](/Users/vnagaraju/PycharmProjects/quantyx-core/services/ai/charts.py)

This phase should explicitly refactor that path so question interpretation becomes a first-class staged artifact instead of an implicit side effect of resolution.

---

## Detailed Intermediate Contracts

### Raw LLM Conversation Plan
The LLM should return only structured interpretation, never SQL:

```json
{
  "intent": "analytic_query",
  "question_type": "breakdown",
  "metric_candidates": [
    {
      "name": "productivity",
      "confidence": 0.93,
      "reason": "user explicitly asked for productivity in cylinders per hour"
    }
  ],
  "dimensions": [
    {
      "name": "zone",
      "role": "business_breakdown",
      "confidence": 0.97
    },
    {
      "name": "filling_head",
      "role": "business_breakdown",
      "confidence": 0.96
    }
  ],
  "filters": [
    {
      "field_role": "date",
      "operator": "=",
      "value": "2026-03-19",
      "source_text": "for 19-Mar-2026",
      "confidence": 0.99
    }
  ],
  "time_grain": "day",
  "chart_intent": "grouped_bar",
  "response_mode": "chart_plus_table",
  "sort": [
    {
      "field": "productivity",
      "direction": "desc"
    }
  ]
}
```

### Validated Query Plan
The deterministic binder should resolve the plan to real artifacts:

```json
{
  "intent": "analytic_query",
  "metric_name": "productivity",
  "metric_source": "registry_metric",
  "metric_sql": "CASE WHEN SUM(total_net_hours) > 0 THEN SUM(total_production) / SUM(total_net_hours) ELSE 0 END",
  "base_table": "fact_lpg_plant_operations",
  "dimensions": [
    {
      "column": "zone",
      "semantic_role": "business_dimension"
    },
    {
      "column": "filling_head",
      "semantic_role": "business_dimension"
    }
  ],
  "filters": [
    {
      "column": "process_date",
      "operator": "=",
      "value": "2026-03-19",
      "value_type": "date"
    }
  ],
  "disallowed_dimensions_removed": ["id"],
  "chart_type": "grouped_bar",
  "response_mode": "chart_plus_table",
  "sort": [
    {
      "field": "productivity",
      "direction": "desc"
    }
  ]
}
```

### Validation Warnings
Warnings should be explicit and machine-readable:

Examples:
- `identifier_dimension_rejected:id`
- `candidate_measure_dimension_conflict:total_productivity`
- `time_filter_bound_to_canonical_column:process_date`
- `chart_intent_fallback:grouped_bar->table`
- `dimension_not_found_rejected:head_type`

---

## Validator Rules in Detail

### Dimension Eligibility
Grouped analytic queries should reject:
- `id`
- `*_id`
- `*_code`
- candidate keys
- columns with uniqueness ratios above the configured business threshold
- raw metric columns when they are being aggregated as measures

Grouped analytic queries should prefer:
- registered business dimensions
- ontology-approved business breakdowns
- dimensions explicitly requested by the user

### Date and Time Binding
The validator should:
- normalize user date phrases to ISO date literals
- bind them to the canonical time column for the chosen metric/table
- reject ambiguous date binding when confidence is low

Example:
- `for 19-Mar-2026`
becomes:
```json
{
  "column": "process_date",
  "operator": "=",
  "value": "2026-03-19",
  "value_type": "date"
}
```

### Aggregation Safety
The compiler must reject plans where:
- grouped dimensions include the selected measure column
- grouped dimensions include a unique row identifier
- aggregate measure SQL is combined with row-level projection fields without aggregation

### Chart Alignment
Chart generation should follow the validated plan:
- 1 requested dimension + 1 metric -> standard bar
- 2 requested dimensions -> grouped bar or table fallback
- date + metric -> trend chart
- date + category + metric -> multi-series trend only when explicitly validated

If chart tooling cannot faithfully represent the validated plan, the response should:
- preserve SQL/table correctness
- emit a warning
- choose a safe fallback chart or no chart

---

## Example End-to-End Behaviors

### Example A: Correct Breakdown Query
Question:
- `Provide productivity (in cylinders per hour) by zone and filling head for 19-Mar-2026`

Expected validated plan:
- metric: `productivity`
- dimensions: `zone`, `filling_head`
- filter: `process_date = 2026-03-19`
- reject `id`

Expected SQL shape:
```sql
SELECT
  t."zone" AS "zone",
  t."filling_head" AS "filling_head",
  CASE
    WHEN SUM(t."total_net_hours") > 0
    THEN SUM(t."total_production") / SUM(t."total_net_hours")
    ELSE 0
  END AS "productivity"
FROM public.fact_lpg_plant_operations t
WHERE DATE(t."process_date") = DATE '2026-03-19'
GROUP BY t."zone", t."filling_head"
ORDER BY "productivity" DESC
LIMIT 200
```

### Example B: Detail Query with Identifier Allowed
Question:
- `Show top 20 records for plant EZ on 19-Mar-2026`

Expected behavior:
- this is a detail-table intent
- row identifiers may be allowed
- aggregation rules should not be applied

### Example C: Trend Query
Question:
- `Show productivity trend by day for March 2026`

Expected behavior:
- metric: `productivity`
- time grain: `day`
- filter: March 2026
- no identifier leakage
- line chart or area chart

---

## API and Debugging Enhancements

### Optional Message Plan API
Recommended new endpoint:
- `GET /workspace/conversations/{conversation_id}/messages/{message_id}/plan`

Response:
```json
{
  "conversation_id": "conv_123",
  "message_id": "wmsg_456",
  "raw_llm_plan": {},
  "validated_plan": {},
  "validation_warnings": [],
  "compiled_sql_preview": "SELECT ..."
}
```

### Optional Stream Artifact
For `stream=true`, add a final SSE artifact:
- `artifact: conversation_plan`

This helps clients debug mismatches without re-fetching the message row.

---

## Testing Plan

### Unit Tests
- raw LLM plan normalization
- date phrase normalization
- identifier rejection for grouped analytics
- dimension preservation for multi-breakdown queries
- aggregate safety rejection

### Integration Tests
- workspace message with `stream=false`
- workspace message with `stream=true`
- persisted assistant message contains `conversation_plan`
- chart payload matches validated plan

### Regression Queries
At minimum:
1. `Provide productivity (in cylinders per hour) by zone and filling head for 19-Mar-2026`
2. `Show total production by zone for 19-Mar-2026`
3. `Show productivity trend for March 2026`
4. `Top 10 plants by productivity yesterday`
5. `Show raw records for zone EZ on 19-Mar-2026`

Each regression should verify:
- date binding
- dimension set
- absence/presence of identifiers according to intent
- chart alignment
- summary alignment

---

## Rollout Plan

### Phase 39.1
- introduce raw LLM workspace query plan extraction
- add plan logging only
- keep existing deterministic compilation path active

### Phase 39.2
- enable validated plan binding for metrics/dimensions/filters
- reject identifiers and broken aggregation mixes

### Phase 39.3
- compile SQL from validated plan
- align chart builder with validated plan

### Phase 39.4
- persist `conversation_plan`
- add debug/read endpoint
- add regression tests

### Optional Debug API
Recommended:
- `GET /workspace/conversations/{conversation_id}/messages/{message_id}/plan`

This would expose:
- raw interpreted plan
- validated plan
- rejected dimensions/filters
- compiled SQL summary

---

## Observability

Add logs such as:
- `workspace.query_plan.interpret.start`
- `workspace.query_plan.interpret.output`
- `workspace.query_plan.validate.output`
- `workspace.query_plan.rejected_dimension`
- `workspace.query_plan.bound_date_filter`
- `workspace.query_plan.compile.output`

This is critical for diagnosing mismatches between:
- question
- plan
- SQL
- chart

---

## Environment Knobs

Recommended:
- `WORKSPACE_QUERY_PLAN_MODE=auto|on|off`
- `WORKSPACE_QUERY_PLAN_MODEL`
- `WORKSPACE_QUERY_PLAN_TIMEOUT_SEC`

Behavior:
- `auto`: use LLM interpretation if API key exists
- `off`: deterministic legacy parser only
- `on`: require LLM interpretation, fallback only if explicitly allowed

Current implemented defaults:
- `WORKSPACE_QUERY_PLAN_MODE=auto`
- `WORKSPACE_QUERY_PLAN_MODEL=gpt-4o-mini` via `OPENAI_MODEL` unless explicitly overridden
- `WORKSPACE_QUERY_PLAN_TIMEOUT_SEC=30`

Recommended runtime values:
- normal development:
  - `WORKSPACE_QUERY_PLAN_MODE=auto`
  - `WORKSPACE_QUERY_PLAN_MODEL=gpt-4o-mini`
  - `WORKSPACE_QUERY_PLAN_TIMEOUT_SEC=20`
- strict planner testing:
  - `WORKSPACE_QUERY_PLAN_MODE=on`
  - `WORKSPACE_QUERY_PLAN_MODEL=gpt-4o-mini`
  - `WORKSPACE_QUERY_PLAN_TIMEOUT_SEC=30`
- deterministic fallback testing:
  - `WORKSPACE_QUERY_PLAN_MODE=off`

---

## Acceptance Criteria
- questions with explicit dates produce SQL with matching date filters
- grouped analytics do not include `id` or identifier columns unless detail intent is selected
- requested multi-dimension breakdowns are preserved in SQL and chart payload
- chart title reflects the resolved plan
- assistant summary matches the executed SQL
- validated plan and warnings are inspectable in persisted artifacts

Example acceptance query:
- `Provide productivity (in cylinders per hour) by zone and filling head for 19-Mar-2026`

Expected:
- metric: `productivity`
- dimensions: `zone`, `filling_head`
- date filter: `process_date = 2026-03-19`
- no `id` in dimensions or SQL `GROUP BY`
- chart reflects both requested breakdowns or returns a clear validated fallback

---

## Suggested Implementation Order
1. Add LLM-first conversation query interpretation step
2. Add deterministic validator/binder for workspace plans
3. Add identifier exclusion and measure/group-by protection
4. Add explicit date filter extraction and canonical binding
5. Align chart builder with validated plan
6. Persist plan artifacts and add diagnostics

---

## Current Status
- Partially implemented
- Implemented:
  - workspace conversation path now performs LLM-first interpretation with deterministic validation/binding
  - exact date parsing for explicit dates
  - relative date parsing for `yesterday`, `today`, `last week`, `this month`, `this year`, `last N months`, named month/year, and quarter phrases
  - fiscal quarter parsing for `Qn FY YYYY-YYYY` using an April-March fiscal year assumption
  - identifier rejection for grouped analytics
  - stronger aggregation-safety checks for measure/dimension conflicts
  - grouped multi-dimension chart handling for workspace conversations
  - explicit chart fallback warnings and table fallback for unsupported chart shapes
  - persisted `conversation_plan` artifacts in workspace assistant message outputs
  - `GET /workspace/conversations/{conversation_id}/messages/{message_id}/plan`
  - regression coverage in `tests/test_workspace_query_planner.py`
- Still pending:
  - fuller raw/validated artifact contract only if additional downstream consumers need more metadata than the current `raw_llm_plan`/`validated_plan`/warnings/rejections/SQL preview shape
  - stronger semantic validation if uniqueness-ratio or data-profile based rejection rules are required at runtime
