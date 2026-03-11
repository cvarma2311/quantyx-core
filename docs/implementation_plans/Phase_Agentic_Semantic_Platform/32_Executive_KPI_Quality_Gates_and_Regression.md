# Phase 32: Executive KPI Quality Gates and Regression

## Objective
Enforce dashboard business quality with deterministic gates, observability, and regression protection.

---

## Problem
Without strict quality gates, invalid metrics/charts can still pass and degrade customer trust.

---

## Scope
1. Add KPI composition gate for dashboards.
2. Add anti-pattern detection (`sum_code`, `sum_id`, generic titles, weak insights).
3. Add quality telemetry and thresholds.
4. Add regression test suite and CI checks.

Out of scope:
- Human approval workflow UI.

---

## Dashboard Quality Gates
Required composition per dashboard:
1. At least 1 trend chart.
2. At least 1 breakdown/share chart.
3. At least 1 rate/productivity/quality chart.
4. Zero blocked metric aggregations.

If gate fails:
- mark status `partial_completed` or `failed_quality_gate`
- persist reasons in quality artifact
- expose in stream/chat replay

---

## Quality Artifact Contract
Store per refresh/run:
```json
{
  "quality_score": 0.87,
  "blocked_patterns": [],
  "warnings": ["low_kpi_diversity"],
  "kpi_mix": {
    "trend": 2,
    "breakdown": 2,
    "quality_or_rate": 1
  }
}
```

---

## Observability
Add counters/logging:
- `kpi_metrics_generated_total`
- `kpi_metrics_rejected_total`
- `charts_rejected_semantic_total`
- `dashboards_failed_quality_gate_total`
- `sum_code_attempt_total`

---

## Implementation Details
Primary files:
- `services/ai/agentic_orchestrator.py`
- `services/ai/dashboard_insights.py`
- `tests/` regression suite

Add:
- quality-gate evaluator utility
- quality summary in run completion artifacts
- CI guard test that fails on known invalid SQL patterns

---

## Acceptance Criteria
1. Quality gate result is available in run artifacts and refresh insights.
2. Dashboards with invalid metric patterns do not ship as `completed`.
3. CI regression suite fails when blocked SQL patterns reappear.
4. Quality score and warnings are available to UI APIs.

---

## Test Plan
1. Integration test: invalid code-sum dashboard -> blocked by gate.
2. Integration test: KPI-diverse dashboard -> passes gate.
3. API test: quality artifact visible in replay/insight endpoints.
4. Regression test: deny-list patterns remain blocked.
