# Phase 29: Semantic Role Classification and Measure Eligibility

## Objective
Classify every column into semantic roles and block non-measure columns from metric aggregation.

---

## Problem
Numeric datatype alone is currently treated as aggregatable, which allows invalid metrics such as `SUM(payment_error_code)` and `SUM(distributor_code)`.

---

## Scope
1. Add deterministic semantic-role classifier for columns.
2. Extend profiling payload with role metadata.
3. Add metric eligibility flags with reason codes.
4. Add deny-list + allow-list policy support.

Out of scope:
- Full LLM-driven role classification.

---

## Column Semantic Roles
Allowed base roles:
- `measure_additive`
- `measure_non_additive`
- `measure_ratio_component`
- `identifier_code`
- `identifier_key`
- `dimension_attribute`
- `time_dimension`
- `status_flag`
- `unknown`

---

## Eligibility Rules
A column is `eligible_measure=true` only if:
1. role is measure-like (`measure_additive` or `measure_ratio_component`), and
2. it is not code/key-like by naming pattern, and
3. uniqueness ratio is below configured threshold, and
4. not explicitly blocked by domain policy.

Hard reject patterns:
- `*_id`
- `*_code`
- `code_*`
- `identifier*`
- known surrogate key names

---

## Data Contract Changes
Extend profiling table column metadata:
```json
{
  "name": "PaymentErrorCode",
  "data_type": "bigint",
  "semantic_role": "identifier_code",
  "eligible_measure": false,
  "eligibility_reason": "name_pattern_code",
  "uniqueness_ratio": 0.94
}
```

---

## API/Artifact Impact
No endpoint changes. Existing run artifacts and chat replay payloads include enriched profiling metadata.

Affected artifacts:
- `ProfilingAgent raw payload`
- `MetricAgent raw payload`

---

## Implementation Details
Primary files:
- `services/ai/agentic_agents.py`
- `services/ai/agentic_orchestrator.py`

Add:
- `_classify_column_semantic_role(...)`
- `_is_measure_eligible(...)`
- config knobs:
  - `AGENTIC_MEASURE_MAX_UNIQUENESS_RATIO`
  - `AGENTIC_MEASURE_ALLOWLIST`
  - `AGENTIC_MEASURE_DENYLIST`

---

## Acceptance Criteria
1. All profiled columns have a semantic role.
2. `*_id` and `*_code` are never marked `eligible_measure=true` unless allow-listed.
3. Metric generation consumes only eligible measure columns.
4. Logs show rejection reason for blocked columns.

---

## Test Plan
1. Unit test: `PaymentErrorCode` => `identifier_code`, ineligible.
2. Unit test: `total_production` => `measure_additive`, eligible.
3. Unit test: allow-listed exceptional column can pass.
4. Integration test: generated metric set contains no `sum_*code` or `sum_*id`.
