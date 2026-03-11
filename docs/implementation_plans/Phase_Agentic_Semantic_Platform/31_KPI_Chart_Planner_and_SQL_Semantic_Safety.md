# Phase 31: KPI Chart Planner and SQL Semantic Safety

## Objective
Ensure chart planning and SQL generation execute only validated KPI metrics and preserve metric semantics end-to-end.

---

## Problem
Chart planner currently can infer metrics from first numeric columns, and SQL builder can fallback to generic `SUM(column)` patterns that degrade KPI meaning.

---

## Scope
1. Planner to consume approved metric defs only.
2. Preserve formula-based metric SQL (`metric_expr`) in execution.
3. Block invalid fallback expression generation.
4. Persist skip reasons for rejected chart candidates.

Out of scope:
- New chart visualization types.

---

## Planner Policy
Candidate generation rules:
1. chart metric must exist in validated metric registry.
2. chart metric must be `is_executive_kpi=true` or pass confidence threshold.
3. dimension/time mapping must be ontology-compatible.
4. if no valid metric exists, candidate is skipped with structured reason.

Skip reason examples:
- `invalid_metric_role`
- `missing_metric_binding`
- `unsupported_dimension_for_metric`

---

## SQL Safety Policy
1. If `metric_expr` is present, execute qualified formula.
2. If `metric_column` is present without `metric_expr`, permit only when role is eligible.
3. Never cast/aggregate blocked identifier/code columns.
4. Emit telemetry and artifact details for any blocked chart.

---

## Data Contract Updates
Each chart in `dashboard_spec.charts[]` includes:
```json
{
  "title": "Rejection Rate Trend by Month",
  "metric": "rejection_rate_pct",
  "metric_intent": "quality",
  "semantic_validation": {
    "status": "passed",
    "reason": "metric_registry_valid"
  }
}
```

Rejected chart example:
```json
{
  "title": "sum_PaymentErrorCode Trend",
  "metric": "sum_PaymentErrorCode",
  "semantic_validation": {
    "status": "rejected",
    "reason": "identifier_code is not aggregatable"
  }
}
```

---

## Implementation Details
Primary files:
- `services/ai/agentic_agents.py`
- `services/ai/agentic_orchestrator.py`

Changes:
- planner uses metric registry selection, not `numeric_columns[0]`
- SQL builder enforces semantic safety gate before expression generation
- stream and replay artifacts include validation results

---

## Acceptance Criteria
1. No planned chart uses blocked metric roles.
2. Formula metrics remain formula-based through SQL generation.
3. Rejected charts are visible with reason in run events/chat replay.
4. Dashboard persists only semantically valid charts (or explicit rejected placeholders).

---

## Test Plan
1. Unit test: formula metric remains formula SQL.
2. Unit test: identifier metric candidate is rejected.
3. Integration test: dashboard chart SQL set has zero `SUM(*id|*code)` patterns.
4. Replay API test: rejected/accepted semantic validation appears in payload.
