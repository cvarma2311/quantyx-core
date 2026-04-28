# 60. Data Quality Trend API Chart-Ready Backend-First UI Contract

## Objective

Refactor the existing data quality trend API so the backend returns a fully prepared UI contract:

- summary counts
- card metrics
- chart-ready series
- grouped drill-through slices
- evidence paths

This phase is explicitly **not** about preserving backward compatibility.

The goal is to make the UI lightweight:

- no client-side aggregation
- no client-side top-N selection
- no client-side grouping logic
- no client-side chart bucketing

The frontend should only:

- fetch trend payload
- render cards
- render charts
- wire drill-through interactions

This phase updates the **existing trend API itself**, rather than introducing a second parallel trend API.

---

## Builds On

- [57_Data_Quality_UI_Integration_E2E_API_Flow.md](./57_Data_Quality_UI_Integration_E2E_API_Flow.md)
- [59_Enterprise_Data_Quality_Reporting_Observability_and_Stewardship.md](./59_Enterprise_Data_Quality_Reporting_Observability_and_Stewardship.md)

---

## Decision

The current `GET /data-quality/trends` response is too raw for a production UI because it still expects the frontend to calculate:

- status counts
- object-type counts
- top improved deltas
- top worsened deltas
- grouped slices for rules, tables, stages, and run summary

We will move those calculations to the backend and make the trend API the source of truth for:

1. counts
2. cards
3. chart series
4. grouped sections
5. drill-through routing

This is a **future-only contract**.

Existing client assumptions may be broken deliberately if needed.

---

## Implementation Checklist

### Done

- [x] redesign `GET /data-quality/trends` response shape as chart-ready contract
- [x] remove frontend-required aggregation assumptions from the trend response
- [x] add `cards` section to the trend API
- [x] add `chart_plan` section to the trend API
- [x] add grouped trend sections for:
  - [x] rules
  - [x] tables
  - [x] stages
  - [x] run/final dataset
- [x] add chart metadata for rendering:
  - [x] `chart_key`
  - [x] `chart_type`
  - [x] `title`
  - [x] `rows`
  - [x] `evidence_path`
- [x] expose top improved delta bars from backend
- [x] expose top worsened delta bars from backend
- [x] expose status distribution chart data from backend
- [x] expose object-type distribution chart data from backend
- [x] update `GET /data-quality/trends/tables/{table_name}` to return chart-ready detail payload
- [x] update `GET /data-quality/trends/rules/{rule_logical_key}` to return chart-ready detail payload
- [x] update FastAPI/OpenAPI examples for trend endpoints
- [x] add per-chart summary blocks in backend
- [x] extend chart metadata for rendering where needed:
  - [x] `subtitle`
  - [x] `series_fields`
  - [x] `x_field`
  - [x] `y_field`
- [x] expose readiness/certification cards from backend in the same trend payload
- [x] expose business-term grouped chart data from backend in the same trend payload
- [x] update the local trend visualizer to consume the backend-first contract with minimal UI logic
- [x] update Phase 57 UI flow documentation for the new trend contract

### Pending

- [ ] update Phase 57 UI flow documentation for the new trend contract

### Future

- [ ] optional compatibility shim for old consumers if still needed later

### Done

- [x] add chart-ready drill-through payload rules for:
  - [x] table trend detail
  - [x] rule trend detail
  - [x] stage trend detail
  - [x] run/final dataset trend detail

---

## Current Problem

Today the backend returns:

- `summary`
- `trends`

That is enough for persistence and debugging, but not enough for a lightweight UI.

The browser currently has to derive:

- status histogram
- object type histogram
- top improved list
- top worsened list
- filtered slices
- card-level summaries

That duplicates domain logic in the UI and will drift from:

- dashboard rendering
- hydration summaries
- Excel generation
- issue/anomaly generation

---

## Target End State

The backend trend API should return one response that can directly drive the UI.

### Target response shape

```json
{
  "tenant_id": "demo-rerun-04",
  "domain_id": "data_quality_observability",
  "run_id": "run_34053b80fe9f",
  "trend_scope_key": "cdr_primary_reconciliation",
  "baseline_run_id": "run_70e21d86a580",

  "summary": {
    "trend_row_count": 191,
    "improved_metric_count": 5,
    "worsened_metric_count": 0,
    "baseline_metric_count": 42,
    "unchanged_metric_count": 144,
    "changed_metric_count": 0
  },

  "cards": [
    {
      "card_key": "overall_trust_score",
      "title": "Overall Trust Score",
      "value": 78.05,
      "note": 77.13,
      "delta_value": 0.92,
      "delta_pct": 1.19,
      "trend_status": "improved",
      "evidence_path": "/data-quality/trends?tenant_id=...&domain_id=...&run_id=...&object_type=run&object_key=__run__&metric_name=overall_trust_score"
    },
    {
      "card_key": "final_dataset_readiness",
      "title": "Final Dataset Readiness",
      "value": "ready",
      "note": "ready",
      "trend_status": "unchanged",
      "evidence_path": "/data-quality/final-dataset?tenant_id=...&domain_id=...&run_id=..."
    }
  ],

  "chart_plan": [
    {
      "chart_key": "trend_status_distribution",
      "chart_type": "column",
      "title": "Trend Status Distribution",
      "rows": [
        {"category": "improved", "value": 5, "evidence_path": "/data-quality/trends?...&trend_status=improved"},
        {"category": "worsened", "value": 0, "evidence_path": "/data-quality/trends?...&trend_status=worsened"},
        {"category": "baseline", "value": 42, "evidence_path": "/data-quality/trends?...&trend_status=baseline"},
        {"category": "unchanged", "value": 144, "evidence_path": "/data-quality/trends?...&trend_status=unchanged"}
      ],
      "x_field": "category",
      "y_field": "value"
    },
    {
      "chart_key": "top_improved_deltas",
      "chart_type": "bar",
      "title": "Top Improved Deltas",
      "rows": [
        {
          "label": "billing_cdr_data trust_score",
          "value": 0.86,
          "object_type": "table",
          "object_key": "billing_cdr_data",
          "metric_name": "trust_score",
          "trend_status": "improved",
          "evidence_path": "/data-quality/trends/tables/billing_cdr_data?tenant_id=...&domain_id=...&run_id=..."
        }
      ],
      "x_field": "label",
      "y_field": "value"
    }
  ],

  "groups": {
    "tables": {
      "summary": {...},
      "rows": [...]
    },
    "rules": {
      "summary": {...},
      "rows": [...]
    },
    "stages": {
      "summary": {...},
      "rows": [...]
    },
    "run": {
      "summary": {...},
      "rows": [...]
    }
  },

  "trends": [...]
}
```

---

## API Contract Changes

### Existing endpoint to update

- `GET /data-quality/trends`

### Existing detail endpoints to update

- `GET /data-quality/trends/tables/{table_name}`
- `GET /data-quality/trends/rules/{rule_logical_key}`

### Existing filters to keep

- `object_type`
- `object_key`
- `trend_status`
- `metric_name`

These stay useful for drill-through and filtered rendering.

### New top-level sections

- `cards`
- `chart_plan`
- `groups`

### Backward compatibility

None required.

The response should be optimized for the future UI contract even if old consumers need to change.

---

## Backend Responsibilities

The backend must calculate and return:

### Summary counts

- `trend_row_count`
- `improved_metric_count`
- `worsened_metric_count`
- `baseline_metric_count`
- `unchanged_metric_count`
- `changed_metric_count`

### Cards

- overall trust score delta
- final dataset readiness status delta
- final row count delta
- failed rule count delta
- rejected row count delta
- duplicate candidate count delta

### Chart series

- status distribution
- object type distribution
- top improved deltas
- top worsened deltas
- table trust score deltas
- rule violation deltas
- stage rejection deltas
- readiness summary chart
- business-term grouped trend chart

### Groups

- grouped rule trend rows
- grouped table trend rows
- grouped stage trend rows
- grouped run/final dataset trend rows

### Drill-through

Each row or bar returned in `cards`, `chart_plan`, and `groups` must include:

- `evidence_path`

So the UI does not need to infer routes.

---

## Chart Plan Model

Each trend chart entry should be backend-defined.

### Required fields

- `chart_key`
- `chart_type`
- `title`
- `subtitle`
- `rows`
- `x_field`
- `y_field`
- optional `series_field`
- optional `color_field`
- `summary`

### Supported `chart_type` values

- `column`
- `bar`
- `donut`
- `stacked_column`
- `metric_row`
- `table`

These types are for UI rendering only. They should not go through the SQL chart compilation pipeline.

Trend charts are **artifact charts**, not **query charts**.

---

## Why This Should Not Use the Generic Chart Execution API

The existing chart API is SQL-driven and semantic-query driven.

Trend charts are different:

- they are derived from persisted trend artifacts
- they are already fully computed
- they do not need SQL compilation
- they only need rendering metadata

Therefore:

- use the same frontend charting library if desired
- do **not** route trend charts through the query execution planner

The backend should emit chart-ready artifact payloads directly.

---

## Frontend Responsibilities After This Phase

The UI should only:

- render summary cards from `cards`
- render charts from `chart_plan`
- render filtered sections from `groups`
- use `evidence_path` for click actions

The UI should **not**:

- compute counts
- sort top deltas
- choose top-N rows
- group rows by status or object type
- derive drill-through routes

---

## Detail Endpoint Shape

### `GET /data-quality/trends/tables/{table_name}`

Should return:

- `summary`
- `cards`
- `chart_plan`
- `rows`

focused only on the selected table.

### `GET /data-quality/trends/rules/{rule_logical_key}`

Should return:

- business-facing rule identity
- summary
- chart-ready rule metrics
- all row-level trend metrics for the logical rule

This is especially important for clickable delta bars.

### Later extension

Add:

- `GET /data-quality/trends/stages/{stage_logical_key}`

if stage-level drill-through needs a dedicated contract.

---

## Integration With Other DQ Surfaces

This backend-first trend contract should also feed:

- hydration trend cards
- dashboard trend sections
- Excel trend sheets
- issue register trend regressions
- anomaly trend surfaces
- readiness/certification trend surfaces

That way there is one canonical backend source of truth.

---

## FastAPI / Swagger Requirements

When implemented, update OpenAPI examples for:

- `GET /data-quality/trends`
- `GET /data-quality/trends/tables/{table_name}`
- `GET /data-quality/trends/rules/{rule_logical_key}`

Examples must include:

- `cards`
- `chart_plan`
- `groups`
- `evidence_path`

The examples should match real runtime payload shape, not an aspirational shape.

---

## Phase 57 Update Requirement

After implementing this phase, update:

- [57_Data_Quality_UI_Integration_E2E_API_Flow.md](./57_Data_Quality_UI_Integration_E2E_API_Flow.md)

Specifically:

- trend page fetch contract
- drill-through behavior
- trend detail modals
- chart rendering expectations
- zero-client-calculation expectation

---

## Recommended Implementation Order

1. refactor `GET /data-quality/trends` backend payload
2. add backend `cards`
3. add backend `chart_plan`
4. add backend `groups`
5. update detail trend endpoints to chart-ready payloads
6. update FastAPI examples
7. update Phase 57 docs
8. update trend visualizer to consume backend-first contract

---

## Acceptance Criteria

This phase is complete when:

- the UI can render the trend page without computing counts itself
- top improved/worsened charts are fully backend-defined
- summary cards are fully backend-defined
- trend detail views are fully backend-defined
- every clickable chart element has a backend-provided `evidence_path`
- the frontend only renders and routes, with no domain aggregation logic
