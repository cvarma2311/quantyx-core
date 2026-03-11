# Phase 30: Template-First KPI Metric Generation

## Objective
Move metric generation from generic numeric sums to ontology and domain template-driven KPI creation.

---

## Problem
Current metric generation relies on `sum_<numeric_column>` defaults, which often creates meaningless KPIs.

---

## Scope
1. Domain metric template loading and resolution.
2. Table/column binding for template metrics.
3. Fallback metric generation only for eligible measures.
4. Metric intent and confidence scoring.

Out of scope:
- New metric authoring UI.

---

## Metric Priority Model
1. **Template metrics (highest priority)**
- Resolve from `packs/<domain>/metric_templates.yml`.

2. **Derived deterministic metrics**
- Productivity, utilization, rejection/failure rate, backlog rate.

3. **Constrained fallback metrics**
- `sum_<column>` only for columns with `eligible_measure=true`.

---

## Metric Metadata Standard
Each metric must include:
- `metric_name`
- `formula`
- `base_table`
- `metric_type`
- `metric_intent` (`volume|rate|productivity|utilization|quality|backlog`)
- `semantic_role`
- `measure_confidence`
- `is_executive_kpi`

---

## Example
```json
{
  "metric_name": "utilization_pct",
  "formula": "SUM(total_net_hours) / NULLIF(SUM(available_hours), 0)",
  "base_table": "lpg_plant_operations",
  "metric_type": "ratio",
  "metric_intent": "utilization",
  "semantic_role": "measure_ratio_component",
  "measure_confidence": 0.91,
  "is_executive_kpi": true
}
```

---

## Implementation Details
Primary files:
- `services/ai/agentic_agents.py`
- `packs/*/metric_templates.yml`

Add:
- template resolver utility
- metric confidence scoring utility
- fallback suppression when template KPI coverage is sufficient

---

## Acceptance Criteria
1. Template-derived metrics are present for supported domains (for example LPG).
2. Generated metrics have `metric_intent` and confidence fields.
3. Fallback `sum_*` metrics are reduced and never generated for blocked roles.
4. At least one KPI from each available intent family is produced when data supports it.

---

## Test Plan
1. Unit test: LPG pack resolves template KPIs.
2. Unit test: missing template binding falls back safely.
3. Unit test: fallback excludes identifier/code columns.
4. Integration test: metric list contains business KPI names, not raw key sums.
