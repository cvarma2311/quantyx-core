# Phase 52: Deterministic Chart Filtering and Hierarchy Drill-Down

## Goal

Introduce a first-class chart interaction model where:

1. `Filtering on charts`
   keeps the same analytical level and adds deterministic scoped predicates.

2. `Drill-down on charts`
   moves from one business hierarchy level to a more detailed child level.

3. `Drill-up and level switching`
   allow users to navigate to parent levels or alternate related levels while preserving the same metric intent.

The key architecture rule is:

- agentic runs determine semantics
- runtime interactions execute deterministically

This phase is about making chart interactions fast, business-aware, and reusable across all persisted chart types.

---

## Why This Phase Is Needed

The platform already supports chart creation and chart conversations, but runtime chart interaction still lacks a durable semantic model.

What is missing today:

- a clear distinction between filtering and drill-down
- precomputed business hierarchies
- chart-local interaction metadata
- deterministic SQL rebuild for click actions
- stable lineage for drill-up and breadcrumbs
- a chart API that tells the UI what interactions are available

Without this phase, chart interactions risk becoming:

- too dependent on conversational interpretation
- too slow if runtime LLM calls are needed
- too fragile if based on raw SQL rewriting

This phase fixes that by doing the expensive semantic work during agentic runs and using deterministic runtime compilers afterward.

---

## Core Product Distinction

### Filtering

Filtering means:

- same metric
- same grouping level
- same chart intent
- same grain
- narrower slice of the same query

Examples:

- `region = North`
- `product_grp = HSD`
- `site_id = 11320610`
- `month = 2025-10`
- `transaction_date between 2025-10-01 and 2025-10-31`

### Drill-Down

Drill-down means:

- same metric
- same source fact/view
- same time axis if present
- grouping dimension moves to a child business level
- clicked parent value becomes a filter

Example:

- current chart:
  `SUM(sales_volume) BY region BY month`
- user clicks:
  `region = North`
- drill-down result:
  `SUM(sales_volume) BY location_name BY month WHERE region = 'North'`

### Drill-Up

Drill-up means:

- same metric
- same source scope
- move to a parent business level
- preserve inherited filters where still valid

Example:

- current chart:
  `sales by location`
- drill-up target:
  `sales by region`

### Level Switch

Some interactions are not pure parent-child moves. They are lateral level changes.

Example:

- current chart:
  `sales by location`
- alternate view:
  `sales by zone`

This should still be deterministic, but it is better modeled as `dimension navigation` rather than only `drill-down`.

---

## Design Principle

### LLM For Semantics, Deterministic For Runtime SQL

The LLM should help during agentic runs with:

- identifying business hierarchies from `context_text`
- interpreting dimension semantics
- ranking preferred hierarchy paths
- deciding which drill paths are most meaningful
- generating suggested drill-down labels

Deterministic runtime should handle:

- loading persisted hierarchy metadata
- exposing available actions for a chart
- compiling filters
- resolving drill-up/down/switch-level actions
- rebuilding SQL
- validating scope and safety
- persisting lineage

Runtime chart interactions should not call the LLM unless the user makes a conversational or ambiguous request.

Hard rule:

- plain chart click drill/filter actions are deterministic only

---

## Scope

This phase introduces:

1. hierarchy artifact model
2. chart interaction context persistence
3. deterministic filter compiler
4. deterministic drill/down/up/level-switch compiler
5. chart lineage and breadcrumb support
6. API responses exposing chart interaction areas
7. chart action execution APIs
8. support for dashboard charts, workspace charts, anomaly charts, correlation charts, and conversation-created charts

This phase does not require:

- open-ended NL drill requests at runtime
- LLM-generated runtime SQL
- arbitrary ad hoc hierarchy discovery on each click

---

## End-to-End Flow

### Stage 1. Agentic-Time Semantic Determination

During deployment / agentic runs:

1. profile schema and tables
2. build semantic graph and join edges
3. interpret business context from `context_text`
4. ask the LLM to propose likely business hierarchies
5. validate those hierarchies deterministically
6. persist approved hierarchies at tenant/domain scope
7. derive preferred navigation paths and suggested drilldowns

### Stage 2. Chart Creation-Time Binding

Whenever any chart is created and persisted:

1. inspect its source query plan
2. identify current grouping dimension(s), time dimension, grain, metric expressions
3. bind current chart dimensions to persisted hierarchy levels if possible
4. compute:
   - available filters
   - available drilldowns
   - available dimension navigation
   - suggested drilldowns
5. persist chart interaction metadata

This should happen for:

- auto dashboard charts
- workspace charts
- anomaly charts
- correlation charts
- conversation-created charts
- charts derived from prior drill/filter actions

### Stage 3. Runtime Interaction Discovery

When UI loads a chart:

1. call `GET /charts/{chart_id}`
2. backend returns:
   - chart payload
   - chart data
   - interaction metadata
   - available filters
   - available drilldowns
   - available dimension navigation
   - suggested drilldowns
   - breadcrumbs / lineage summary

### Stage 4. Runtime Interaction Execution

When user clicks or selects an action:

- filtering uses deterministic filter compiler
- drill-down uses deterministic hierarchy compiler
- drill-up uses persisted lineage
- level switching uses deterministic dimension-navigation compiler

No LLM call is needed for these runtime actions.

---

## What Must Be Determined During Agentic Runs

The agentic run is where the expensive semantic reasoning should happen once.

### Required Outputs

During deployment / agentic runs, the system should determine and persist:

1. `approved business hierarchies`
   Examples:
   - geography hierarchy
   - product hierarchy
   - organizational hierarchy
   - channel hierarchy
   - domain-specific hierarchies from `context_text`

2. `dimension-to-hierarchy bindings`
   Map known dimensions to hierarchy levels.

3. `preferred navigation paths`
   For each hierarchy level, determine likely next useful levels.

4. `suggested drilldowns`
   For common analytical levels, rank the drill targets that should be shown first in the UI.

5. `filter eligibility metadata`
   Which dimensions and time fields are safe to filter.

### Why This Must Happen During Agentic Runs

Because this is where the system already has:

- business context
- semantic graph
- join edges
- validated metrics
- chart families
- domain semantics

That is the right time to answer:

- what hierarchies exist
- what each level means
- what level changes are useful
- what should be suggested

Then all later chart creation can reuse these persisted semantics.

---

## Hierarchy Artifact Model

We need a tenant/domain-level artifact that captures approved business drill paths.

### When It Is Determined

During agentic runs after:

- schema profiling
- semantic interpretation
- join discovery
- context understanding

### How It Is Determined

LLM proposes candidate hierarchies from:

- `context_text`
- domain semantics
- table names
- column names
- approved join edges
- example chart families

Deterministic validation then checks:

- every level exists as a real column or resolvable joined column
- the hierarchy can be queried safely
- the join path is valid
- the level ordering is plausible

### What Gets Stored

Each hierarchy should contain:

- `hierarchy_id`
- `tenant_id`
- `domain_id`
- `name`
- `description`
- `base_scope`
- `levels`
- `join_path`
- `preferred`
- `confidence`
- `provenance`
- `validation_status`

### Example

```json
{
  "hierarchy_id": "geo_sales_hierarchy",
  "tenant_id": "ns-15",
  "domain_id": "sales_forecast",
  "name": "Sales Geography",
  "description": "Geographic drill path for fuel sales analysis",
  "base_scope": {
    "schema_name": "public",
    "base_table": "nozzle_sales"
  },
  "preferred": true,
  "levels": [
    {
      "level_id": "region",
      "column": "region",
      "label": "Region",
      "table": "nozzle_sales"
    },
    {
      "level_id": "location_name",
      "column": "location_name",
      "label": "Location",
      "table": "nozzle_sales"
    },
    {
      "level_id": "sales_area",
      "column": "sales_area",
      "label": "Sales Area",
      "table": "nozzle_sales"
    },
    {
      "level_id": "site_id",
      "column": "site_id",
      "label": "Site",
      "table": "nozzle_sales"
    },
    {
      "level_id": "zone",
      "column": "zone",
      "label": "Zone",
      "table": "nozzle_sales"
    }
  ],
  "join_path": [],
  "confidence": 0.93,
  "provenance": {
    "source": "llm_plus_validation"
  },
  "validation_status": "approved"
}
```

---

## Storage Recommendation For Hierarchies

### Should We Create New Tables?

Recommendation:

- yes for hierarchy artifacts
- yes for chart interaction lineage
- chart-local interaction state should still live on the existing chart table

### Why New Tables Are Useful

Hierarchy artifacts are:

- tenant/domain scoped
- reusable across many charts
- versionable
- queryable independently of charts

That makes them a poor fit for storing only inside per-chart records.

### Recommended New Table 1

`quantyx_business_hierarchies`

Suggested columns:

- `hierarchy_id`
- `tenant_id`
- `domain_id`
- `name`
- `description`
- `base_scope_json`
- `levels_json`
- `join_path_json`
- `preferred`
- `confidence_score`
- `provenance_json`
- `validation_status`
- `created_at`
- `updated_at`

### Recommended New Table 2

`quantyx_chart_interactions`

Suggested columns:

- `interaction_id`
- `tenant_id`
- `domain_id`
- `source_chart_id`
- `result_chart_id`
- `interaction_type`
- `selected_dimension`
- `selected_value_json`
- `source_level_id`
- `target_level_id`
- `interaction_payload_json`
- `created_at`

### What Should Stay In Existing Chart Storage

Keep chart-specific interaction state in `quantyx_chart_requests`:

- `interaction_context_json`
- `lineage_json`
- `parent_chart_id`
- `root_chart_id`
- `drill_hierarchy_id`
- `drill_level_id`

This split is the best balance:

- hierarchies in reusable dedicated storage
- chart-local state on the chart
- interaction audit in a dedicated interaction table

### Explicit Storage Decision

To remove ambiguity, the recommended persistence split is:

1. `during agentic runs`
   determine and persist reusable tenant/domain semantic artifacts in:
   - `quantyx_business_hierarchies`

2. `during any chart creation`
   persist chart-local interaction state on the existing chart record in:
   - `quantyx_chart_requests.interaction_context_json`
   - `quantyx_chart_requests.lineage_json`
   - `quantyx_chart_requests.parent_chart_id`
   - `quantyx_chart_requests.root_chart_id`
   - `quantyx_chart_requests.drill_hierarchy_id`
   - `quantyx_chart_requests.drill_level_id`

3. `during every filter/drill/navigation action`
   persist interaction lineage and audit records in:
   - `quantyx_chart_interactions`

This means:

- hierarchies are not recomputed for every chart
- conversation-created charts reuse the same stored hierarchy artifacts
- runtime drill/filter does not need the LLM
- every derived chart still has its own local interaction state

---

## Chart Interaction Context Persistence

Every persisted chart should expose enough metadata for deterministic interactions.

### When It Is Determined

At chart creation time:

- dashboard charts
- workspace charts
- anomaly charts
- correlation charts
- conversation-created charts
- derived drill/filter charts

### Rule

If a chart is persisted, it must be enriched with interaction metadata at creation time.

### What Gets Stored Per Chart

- source table/view
- metric expressions
- grouping dimensions
- time dimension
- series dimension
- grain
- current filters
- hierarchy binding
- available filter fields
- available drilldowns
- available dimension navigation
- suggested drilldowns
- lineage metadata

### Proposed `interaction_context_json`

```json
{
  "source_scope": {
    "schema_name": "public",
    "base_table": "nozzle_sales",
    "base_view": null
  },
  "query_shape": {
    "metric_expressions": [
      {
        "metric_id": "sales_volume",
        "expression": "SUM(sales_volume)"
      }
    ],
    "group_dimensions": ["location_name"],
    "series_dimension": null,
    "time_dimension": "transaction_date",
    "query_grain": "month",
    "chart_intent": "trend_by_dimension"
  },
  "filters": [],
  "current_level": "location_name",
  "hierarchy_bindings": {
    "location_name": {
      "hierarchy_id": "geo_sales_hierarchy",
      "current_level_id": "location_name"
    }
  },
  "available_filter_fields": [
    {"field": "location_name", "kind": "dimension"},
    {"field": "transaction_date", "kind": "time"}
  ],
  "available_drilldowns": [
    {
      "hierarchy_id": "geo_sales_hierarchy",
      "source_level_id": "location_name",
      "target_level_id": "sales_area",
      "label": "Drill to Sales Area"
    }
  ],
  "available_dimension_navigation": [
    {
      "target_level": "region",
      "action_type": "drill_up",
      "label": "View by Region"
    },
    {
      "target_level": "sales_area",
      "action_type": "drill_down",
      "label": "View by Sales Area"
    },
    {
      "target_level": "zone",
      "action_type": "switch_level",
      "label": "View by Zone"
    }
  ],
  "suggested_drilldowns": [
    {
      "target_level": "sales_area",
      "action_type": "drill_down",
      "label": "View by Sales Area",
      "priority": 1,
      "reason": "next operational level under location"
    }
  ],
  "lineage": {
    "root_chart_id": "chart_root_1",
    "parent_chart_id": null,
    "interaction_type": null
  }
}
```

---

## Conversation-Created Charts

This requirement applies to conversation-created charts too.

### Important Rule

Conversation-created charts should not trigger a fresh full hierarchy-discovery pass by default.

Instead they should:

1. reuse tenant/domain hierarchy artifacts already created during agentic runs
2. bind chart dimensions to those stored hierarchies deterministically
3. compute interaction metadata from those stored hierarchies

Only if a conversation chart uses a dimension that cannot be matched to any known hierarchy should the system need a fallback semantic-binding step.

Recommendation:

- first attempt deterministic binding
- use LLM only as fallback for ambiguous new dimensions

### Example

If a conversation creates:

- `sales_volume by location_name`

then that chart should also get:

```json
{
  "current_level": "location_name",
  "metric": "sales_volume",
  "available_dimension_navigation": [
    {
      "target_level": "region",
      "action_type": "drill_up",
      "label": "View by Region"
    },
    {
      "target_level": "sales_area",
      "action_type": "drill_down",
      "label": "View by Sales Area"
    },
    {
      "target_level": "zone",
      "action_type": "switch_level",
      "label": "View by Zone"
    }
  ]
}
```

This should be attached during chart persistence exactly like any dashboard chart.

---

## Available Interaction Areas On `GET /charts/{chart_id}`

Every chart response should expose the interaction areas directly.

The UI should not have to infer this from chart payload alone.

### Required Additions

`GET /charts/{chart_id}` should return:

- `interaction_context`
- `available_filters`
- `available_drilldowns`
- `available_dimension_navigation`
- `suggested_drilldowns`
- `available_areas`
- `breadcrumb`
- `lineage_summary`

### Example

```json
{
  "chart_id": "chart_123",
  "title": "Sales by Location",
  "chart_type": "line",
  "chart_payload": {},
  "chart_data": [],
  "interaction_context": {
    "source_table": "nozzle_sales",
    "time_dimension": "transaction_date",
    "group_dimensions": ["location_name"],
    "query_grain": "month"
  },
  "available_filters": [
    {
      "field": "location_name",
      "label": "Location",
      "kind": "dimension"
    },
    {
      "field": "transaction_date",
      "label": "Period",
      "kind": "time"
    }
  ],
  "available_drilldowns": [
    {
      "hierarchy_id": "geo_sales_hierarchy",
      "label": "Drill to Sales Area",
      "source_level_id": "location_name",
      "target_level_id": "sales_area"
    }
  ],
  "available_dimension_navigation": [
    {
      "target_level": "region",
      "action_type": "drill_up",
      "label": "View by Region"
    },
    {
      "target_level": "sales_area",
      "action_type": "drill_down",
      "label": "View by Sales Area"
    },
    {
      "target_level": "zone",
      "action_type": "switch_level",
      "label": "View by Zone"
    }
  ],
  "suggested_drilldowns": [
    {
      "target_level": "sales_area",
      "action_type": "drill_down",
      "label": "View by Sales Area",
      "priority": 1
    }
  ],
  "available_areas": {
    "dimensions": ["location_name"],
    "time": ["transaction_date"],
    "series": [],
    "drill_paths": [
      {
        "hierarchy_id": "geo_sales_hierarchy",
        "path": ["region", "location_name", "sales_area", "site_id"]
      }
    ]
  },
  "breadcrumb": [],
  "lineage_summary": {
    "root_chart_id": "chart_123",
    "parent_chart_id": null,
    "depth": 0
  }
}
```

---

## Deterministic Filter Compiler

Filtering should be implemented first because it is the simplest and most reusable runtime action.

### Inputs

- `chart_id`
- selected field
- selected value or range
- stored interaction context

### Supported Filter Types

- equality filter
- multi-value `IN` filter
- time bucket filter
- date range filter
- series filter

### Flow

1. load chart interaction context
2. validate selected field is filterable
3. normalize selected value
4. append structured filter object to inherited filters
5. rebuild query plan
6. compile SQL deterministically
7. execute safe SQL
8. persist derived chart and lineage

### Structured Filter Example

```json
{
  "field": "region",
  "operator": "=",
  "value": "North",
  "kind": "dimension"
}
```

Time example:

```json
{
  "field": "transaction_date",
  "operator": "bucket_equals",
  "grain": "month",
  "value": "2025-10-01",
  "kind": "time"
}
```

---

## Deterministic Dimension Navigation Compiler

This compiler should cover:

- drill-down
- drill-up
- switch-level

### Inputs

- `chart_id`
- selected clicked value if needed
- target level
- interaction context
- hierarchy binding
- hierarchy artifact

### Flow

1. load interaction context
2. load bound hierarchy
3. validate target level is allowed
4. determine action type:
   - `drill_down`
   - `drill_up`
   - `switch_level`
5. preserve:
   - metric expressions
   - time axis
   - source scope
   - inherited filters
6. if current clicked value is meaningful for navigation, carry it as a filter
7. replace grouping dimension with target level
8. compile SQL deterministically
9. execute safe SQL
10. persist derived chart and lineage

### Example

Current chart:

- `sales by location`

User selects:

- `View by Zone`

Compiler behavior:

- keep metric = `sales_volume`
- keep source = `nozzle_sales`
- keep time axis if present
- change grouping dimension from `location_name` to `zone`
- preserve inherited filters
- execute deterministic SQL for `sales by zone`

---

## How Drill-Down Is Identified

Runtime should not infer drilldown from chart labels or prompt text.

It should identify drilldown from:

1. current chart grouping dimension
2. chart hierarchy binding
3. target level in `available_dimension_navigation`
4. clicked value when a parent filter must be carried

This is why hierarchy and interaction metadata must already exist before runtime.

---

## Lineage And Drill-Up

Every drill/filter/level-switch action should create a derived chart.

### Why

This gives:

- breadcrumbs
- auditability
- reversible navigation
- shareable derived charts
- caching

### What To Store

On the chart:

- `parent_chart_id`
- `root_chart_id`
- `lineage_json`

In the interaction table:

- source chart id
- result chart id
- interaction type
- selected dimension/value
- source and target levels
- payload

### Drill-Up

Drill-up should normally:

- resolve parent chart from lineage
- return the parent chart directly

If needed, prior state can also be reconstructed from stored interaction metadata.

---

## API Contract

### `GET /charts/{chart_id}`

Return:

- chart payload
- chart data
- insight/narrative
- interaction metadata
- available filters
- available drilldowns
- available dimension navigation
- suggested drilldowns
- available areas
- breadcrumb
- lineage summary

### `GET /charts/{chart_id}/actions`

Optional lightweight action-only endpoint.

### `POST /charts/{chart_id}/filter`

Input:

```json
{
  "filters": [
    {
      "field": "region",
      "operator": "=",
      "value": "North"
    }
  ]
}
```

### `POST /charts/{chart_id}/drill-down`

Input:

```json
{
  "selected_dimension": "location_name",
  "selected_value": "Delhi",
  "target_level_id": "sales_area"
}
```

### `POST /charts/{chart_id}/drill-up`

Input:

```json
{
  "target_level_id": "region"
}
```

### `POST /charts/{chart_id}/switch-level`

Input:

```json
{
  "target_level_id": "zone"
}
```

This may be implemented later as a unified navigation endpoint, but the semantic distinction should remain clear.

---

## UI Contract

The UI should use backend-provided metadata, not infer interactions from chart visuals.

### Chart Load

Call `GET /charts/{chart_id}` and render:

- chart
- available filters
- available drill/navigation options
- breadcrumb

### Click Behavior

On click, show actions such as:

- `Filter to this value`
- `Drill to Sales Area`
- `View by Region`
- `View by Zone`

### Suggested Drilldowns

The UI should highlight `suggested_drilldowns` first, but still allow access to all valid `available_dimension_navigation` actions.

---

## Caching Strategy

Deterministic interactions are cacheable.

Cache key inputs:

- source chart id
- interaction type
- selected dimension/value
- target level
- inherited filters
- tenant/domain scope

Cacheable results:

- derived chart payload
- compiled SQL
- action discovery response

---

## Validation And Safety

### Filtering

- selected field must be in available filter fields
- selected value must be type-compatible
- time filters must compile to approved predicates

### Dimension Navigation

- current dimension must be bound to a hierarchy or allowed switchable level set
- target level must be available in persisted interaction metadata
- joins must be approved
- source scope must remain valid

### Shared

- preserve tenant/domain filters
- preserve scoped connection safety
- no arbitrary SQL fragments from UI
- no runtime LLM-generated SQL

---

## Detailed Implementation Phases

### 52A. Hierarchy Artifact Generation During Agentic Runs

Produce and persist:

- approved hierarchies
- preferred drill paths
- suggested drilldowns
- dimension-to-level bindings

### 52B. Chart Interaction Context Persistence

Attach to every persisted chart:

- interaction context
- available filters
- available drilldowns
- available dimension navigation
- suggested drilldowns
- lineage fields

This includes conversation-created charts.

### 52C. `GET /charts/{chart_id}` Expansion

Expose:

- `available_filters`
- `available_drilldowns`
- `available_dimension_navigation`
- `suggested_drilldowns`
- `available_areas`
- lineage summary

### 52D. Deterministic Filter Compiler

Compile and execute chart filters without LLM.

### 52E. Deterministic Navigation Compiler

Compile and execute:

- drill-down
- drill-up
- switch-level

without LLM.

### 52F. Lineage Persistence

Persist every interaction as a derived chart plus interaction audit.

Current implementation status:

- derived charts persist lineage and parent/root chart ids
- interaction audit is stored in `quantyx_chart_interactions`
- `GET /charts/{chart_id}` reconstructs multi-step breadcrumbs
- `POST /charts/{chart_id}/back` supports prior-state restoration
- `POST /charts/{chart_id}/drill-up` now prefers semantic ancestor navigation before falling back to parent state

Deferred until after current end-to-end testing:

- deeper lineage-aware ancestor reconstruction across long mixed chains of filter + switch-level + drill actions
- richer breadcrumb labeling/UX shaping intended primarily for the UI layer
- additional lineage compaction or replay helpers if current persisted chain proves insufficient during testing

### 52G. UI Integration

Add:

- action menu
- suggested drilldown emphasis
- breadcrumb rendering

### 52H. Regression And Safety

Test:

- same-table hierarchy drill
- join-based hierarchy drill
- conversation-created chart enrichment
- filter stacking
- drill-up correctness
- level switching
- invalid navigation attempts

---

## Recommended Architecture Summary

Best model:

- hierarchies are discovered during agentic runs
- hierarchy artifacts are persisted once per tenant/domain
- every persisted chart gets interaction metadata at creation time
- `GET /charts/{chart_id}` exposes both chart content and interaction contract
- runtime interactions are deterministic
- conversation-created charts behave exactly like dashboard charts once saved

This gives the behavior you want without runtime LLM latency for ordinary drill/filter actions.

---

## Acceptance Criteria

This phase is complete when:

- agentic runs persist hierarchy artifacts for supported domains
- suggested drilldowns are determined during agentic runs
- charts persist `interaction_context_json`
- newly created conversation charts are enriched with the same interaction metadata as dashboard charts
- `GET /charts/{chart_id}` returns:
  - `available_filters`
  - `available_drilldowns`
  - `available_dimension_navigation`
  - `suggested_drilldowns`
  - `available_areas`
- filter actions execute without LLM calls
- navigation actions execute without LLM calls
- derived charts persist lineage and support drill-up
- tests cover valid and invalid filter/navigation scenarios
