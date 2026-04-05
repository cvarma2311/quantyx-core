# Phase 52 E2E Test Guide

This guide is for validating the implementation in
[52_Deterministic_Chart_Filtering_and_Hierarchy_Drill_Down.md](/Users/vnagaraju/PycharmProjects/quantyx-core/docs/implementation_plans/Phase_Agentic_Semantic_Platform/52_Deterministic_Chart_Filtering_and_Hierarchy_Drill_Down.md).

It uses:

- the current API on `http://localhost:8787`
- the existing deployment script patterns from [debug-logs/commands](/Users/vnagaraju/PycharmProjects/quantyx-core/debug-logs/commands)
- the current Phase 52 APIs:
  - `GET /charts/{chart_id}`
  - `GET /charts/{chart_id}/actions`
  - `GET /charts/{chart_id}/interaction-context`
  - `POST /charts/{chart_id}/filter`
  - `POST /charts/{chart_id}/navigate`
  - `POST /charts/{chart_id}/drill-down`
  - `POST /charts/{chart_id}/drill-up`
  - `POST /charts/{chart_id}/switch-level`
  - `POST /charts/{chart_id}/back`

## Goal

Validate end to end that:

1. agentic runs persist hierarchy artifacts
2. newly created charts persist interaction metadata
3. chart APIs expose available filters and navigation
4. filtering works deterministically
5. drill-down works deterministically
6. drill-up works deterministically
7. level switching works deterministically
8. lineage, breadcrumb, and backtracking work across multiple steps

## Recommended Dataset

Use the existing `nozzle_sales` deployment because it has:

- a clean geography hierarchy:
  - `zone -> region -> sales_area -> location_name / sap_id`
- useful time axis:
  - `transaction_date`
- useful filter dimensions:
  - `product_grp`

## 1. Start API

Use a hard restart so the latest backend code is definitely loaded:

```bash
lsof -ti tcp:8787 | xargs kill -9
cd /Users/vnagaraju/PycharmProjects/quantyx-core
set -a
source .env
set +a
uvicorn services.api.main:app --reload --port 8787 2>&1 | tee debug-logs/api.log
```

Open a second terminal for the deployment and API checks.

## 2. Run Deployment

Use the same deployment pattern already in [debug-logs/commands](/Users/vnagaraju/PycharmProjects/quantyx-core/debug-logs/commands):

```bash
cd /Users/vnagaraju/PycharmProjects/quantyx-core

python3 scripts/demo_workspace_deployment_lpg.py \
  --tenant-id ns-1 \
  --api-base http://localhost:8787 \
  --domain-id sales_forecast \
  --connection-id 8 \
  --database iot_rudhra \
  --schema public \
  --tables nozzle_sales \
  --context-text "Domain: Retail nozzle sales forecasting — daily transaction-level fuel sales by outlet location and product group.

Tables in scope:
  - nozzle_sales: Daily retail fuel sales. One row per outlet x product group x date.
    Key columns:
      transaction_date — Sales date stored as TIMESTAMPTZ.
      sales_volume     — Sales volume for that day.
      product_grp      — Product group.
      sap_id           — SAP outlet code.
      location_name    — Outlet display name.
      zone             — Highest geographic level.
      region           — Region within zone.
      sales_area       — Sales area within region.

Location hierarchy:
  zone > region > sales_area > location_name / sap_id

Business context:
  - Monthly aggregation: DATE_TRUNC('month', transaction_date)
  - Daily aggregation: transaction_date::date
  - Total volume: SUM(sales_volume)
  - Do NOT join nozzle_sales to any other table." \
  2>&1 | tee debug-logs/nozzle-sales-phase52-$(date +%H%M%S).log
```

## 3. Confirm Run Completed

List current deployment:

```bash
curl -s "http://localhost:8787/workspace/deployments/current?tenant_id=ns-1&domain_id=sales_forecast" | jq
```

Expected:

- `status = "completed"`
- a non-null `run_id`

Save the run id:

```bash
RUN_ID=$(curl -s "http://localhost:8787/workspace/deployments/current?tenant_id=ns-1&domain_id=sales_forecast" | jq -r '.run_id')
echo "$RUN_ID"
```

## 4. Validate Hierarchy Artifacts

Phase 52 expects hierarchies to be persisted during agentic runs.

Check DB:

```bash
psql "$DATABASE_URL" -c "
select hierarchy_id, name, preferred, confidence_score, base_scope_json, levels_json
from public.quantyx_business_hierarchies
where tenant_id = 'ns-1' and domain_id = 'sales_forecast'
order by preferred desc, updated_at desc, name asc;
"
```

Expected:

- at least one hierarchy for `nozzle_sales`
- likely a geography hierarchy containing some or all of:
  - `zone`
  - `region`
  - `sales_area`
  - `location_name`
  - `sap_id`

## 5. Find a Chart to Test

List charts created for the latest run:

```bash
psql "$DATABASE_URL" -c "
select chart_id, title, chart_type, created_by, status
from public.quantyx_chart_requests
where run_id = '$RUN_ID'
order by created_at desc
limit 50;
"
```

For Phase 52 testing, choose a chart that groups by a hierarchy dimension, ideally:

- `sales by zone`
- `sales by region`
- `sales_volume by zone`
- `sales_volume by region`

Save the chart id:

```bash
CHART_ID="<put_chart_id_here>"
```

## 6. Inspect Chart Interaction Metadata

First inspect the chart directly:

```bash
curl -s "http://localhost:8787/charts/$CHART_ID" | jq
```

Then inspect actions:

```bash
curl -s "http://localhost:8787/charts/$CHART_ID/actions" | jq
```

Then inspect raw interaction metadata:

```bash
curl -s "http://localhost:8787/charts/$CHART_ID/interaction-context" | jq
```

Expected in one or more of these responses:

- `interaction_context`
- `available_filters`
- `available_drilldowns`
- `available_dimension_navigation`
- `suggested_drilldowns`
- `available_areas`
- `breadcrumb`
- `lineage_summary`

For a geography chart, expect navigation targets such as:

- `region`
- `sales_area`
- `location_name`
- `zone`

depending on the current chart level.

## 7. Create a Conversation Anchored to the Chart

This validates that conversation-created flows can reuse the same chart context.

```bash
curl -s -X POST "http://localhost:8787/workspace/conversations" \
  -H "Content-Type: application/json" \
  -d "{
    \"tenant_id\": \"ns-1\",
    \"domain_id\": \"sales_forecast\",
    \"chart_id\": \"$CHART_ID\"
  }" | jq
```

Save the conversation id:

```bash
CONV_ID=$(curl -s -X POST "http://localhost:8787/workspace/conversations" \
  -H "Content-Type: application/json" \
  -d "{
    \"tenant_id\": \"ns-1\",
    \"domain_id\": \"sales_forecast\",
    \"chart_id\": \"$CHART_ID\"
  }" | jq -r '.conversation_id')
echo "$CONV_ID"
```

Optional follow-up conversational query:

```bash
curl -s -X POST "http://localhost:8787/workspace/conversations/$CONV_ID/messages" \
  -H "Content-Type: application/json" \
  -d '{
    "user_query": "Show me the same metric one level deeper",
    "resume_context": true,
    "stream": false
  }' | jq
```

That is conversational behavior. The remaining tests below are deterministic chart APIs.

## 8. Deterministic Filter Variations

### 8.1 Filter by Product Group

Use a value that exists in the dataset, for example `HSD`.

```bash
curl -s -X POST "http://localhost:8787/charts/$CHART_ID/filter" \
  -H "Content-Type: application/json" \
  -d '{
    "filters": [
      {"field": "product_grp", "operator": "=", "value": "HSD"}
    ]
  }' | jq
```

Expected:

- returns a new derived chart
- `lineage_summary.parent_chart_id = $CHART_ID`
- breadcrumb depth increases by 1
- SQL contains `WHERE ... product_grp = 'HSD'`

Save the derived filtered chart:

```bash
FILTERED_CHART_ID="<filtered_chart_id>"
```

### 8.2 Filter by Time Range

```bash
curl -s -X POST "http://localhost:8787/charts/$CHART_ID/filter" \
  -H "Content-Type: application/json" \
  -d '{
    "filters": [
      {"field": "transaction_date", "operator": "BETWEEN", "value": ["2026-01-01", "2026-02-29"]}
    ]
  }' | jq
```

Expected:

- new derived chart
- same grouping level as source chart
- narrower time scope

### 8.3 Stack Multiple Filters

```bash
curl -s -X POST "http://localhost:8787/charts/$CHART_ID/filter" \
  -H "Content-Type: application/json" \
  -d '{
    "filters": [
      {"field": "product_grp", "operator": "=", "value": "MS"},
      {"field": "transaction_date", "operator": "BETWEEN", "value": ["2026-01-01", "2026-03-31"]}
    ]
  }' | jq
```

Expected:

- both filters persisted in lineage
- both filters present in SQL

## 9. Deterministic Drill-Down Variations

Always inspect available navigation first:

```bash
curl -s "http://localhost:8787/charts/$CHART_ID/actions" | jq '.available_dimension_navigation'
```

Use the `target_level_id` values returned there. Do not guess them if the chart level is not obvious.

### 9.1 Explicit Drill-Down With Selected Value

Example: chart is at `zone`, and you want to drill to `region` for `North`.

```bash
curl -s -X POST "http://localhost:8787/charts/$CHART_ID/drill-down" \
  -H "Content-Type: application/json" \
  -d '{
    "target_level_id": "region",
    "selected_dimension": "zone",
    "selected_value": "North"
  }' | jq
```

Expected:

- grouping changes to `region`
- filter carries `zone = North`
- breadcrumb grows
- lineage shows:
  - `interaction_type = drill_down`
  - `source_level_id = zone`
  - `target_level_id = region`

Save result:

```bash
REGION_CHART_ID="<region_chart_id>"
```

### 9.2 Drill-Down One More Level

Example: region -> sales area.

```bash
curl -s -X POST "http://localhost:8787/charts/$REGION_CHART_ID/drill-down" \
  -H "Content-Type: application/json" \
  -d '{
    "target_level_id": "sales_area",
    "selected_dimension": "region",
    "selected_value": "North Region 1"
  }' | jq
```

Expected:

- grouping changes to `sales_area`
- previous inherited filter remains
- new selected parent value is added as filter

### 9.3 Drill-Down Without Explicit Target

This uses nearest valid `drill_down` target.

```bash
curl -s -X POST "http://localhost:8787/charts/$CHART_ID/drill-down" \
  -H "Content-Type: application/json" \
  -d '{
    "selected_dimension": "zone",
    "selected_value": "North"
  }' | jq
```

Expected:

- backend chooses nearest `drill_down` target from metadata

## 10. Deterministic Drill-Up Variations

### 10.1 Semantic Drill-Up

From a deeper chart, ask for roll-up without specifying target.

```bash
curl -s -X POST "http://localhost:8787/charts/$REGION_CHART_ID/drill-up" \
  -H "Content-Type: application/json" \
  -d '{}' | jq
```

Expected:

- backend chooses nearest valid ancestor level if one exists
- does not necessarily mean “go back one step”

### 10.2 Explicit Drill-Up Target

```bash
curl -s -X POST "http://localhost:8787/charts/$REGION_CHART_ID/drill-up" \
  -H "Content-Type: application/json" \
  -d '{
    "target_level_id": "zone"
  }' | jq
```

Expected:

- grouping changes from region to zone
- inherited filters stay if still valid

## 11. Backtracking Variations

`back` is different from semantic drill-up. It should return the immediate prior chart state.

```bash
curl -s -X POST "http://localhost:8787/charts/$REGION_CHART_ID/back" | jq
```

Expected:

- returns the parent chart
- no SQL recompilation expected at the API contract level
- useful after:
  - filter
  - switch-level
  - drill-down

## 12. Level Switch Variations

Use this when you want to keep the same metric but move to an alternate valid level, not a strict parent/child move.

Example: current chart grouped by `location_name`, switch to `zone`.

```bash
curl -s "http://localhost:8787/charts/$CHART_ID/actions" | jq '.available_dimension_navigation'
```

Then:

```bash
curl -s -X POST "http://localhost:8787/charts/$CHART_ID/switch-level" \
  -H "Content-Type: application/json" \
  -d '{
    "target_level_id": "zone"
  }' | jq
```

Expected:

- same metric
- same source scope
- grouping changes to `zone`
- lineage shows `interaction_type = switch_level`

### 12.1 Switch Level With Selected Value

Example: carry forward a clicked parent/category as a filter while switching level.

```bash
curl -s -X POST "http://localhost:8787/charts/$CHART_ID/switch-level" \
  -H "Content-Type: application/json" \
  -d '{
    "target_level_id": "zone",
    "selected_dimension": "product_grp",
    "selected_value": "HSD"
  }' | jq
```

## 13. Mixed Navigation Chain Test

This is the most important Phase 52 test because it validates lineage and breadcrumb behavior.

Suggested chain:

1. start from `sales by zone`
2. filter `product_grp = HSD`
3. drill-down to `region` with `zone = North`
4. drill-down to `sales_area`
5. switch-level to `location_name`
6. call `GET /charts/{chart_id}`
7. call `POST /charts/{chart_id}/back`
8. call `POST /charts/{chart_id}/drill-up`

At the end, validate:

- breadcrumb contains the full chain
- `lineage_summary.depth` matches the chain depth
- `lineage_summary.back_chart_id` points to the immediate previous chart
- `drill-up` and `back` are not always the same action

## 14. Inspect Persisted Derived Charts

Check stored chart interaction state:

```bash
psql "$DATABASE_URL" -c "
select chart_id, title, parent_chart_id, root_chart_id, drill_hierarchy_id, drill_level_id,
       interaction_context_json, lineage_json
from public.quantyx_chart_requests
where root_chart_id = '$CHART_ID' or chart_id = '$CHART_ID'
order by created_at asc;
"
```

Check interaction audit rows:

```bash
psql "$DATABASE_URL" -c "
select interaction_id, source_chart_id, result_chart_id, interaction_type,
       selected_dimension, selected_value_json, source_level_id, target_level_id, interaction_payload_json
from public.quantyx_chart_interactions
where source_chart_id = '$CHART_ID'
   or result_chart_id = '$CHART_ID'
   or source_chart_id in (
       select chart_id from public.quantyx_chart_requests where root_chart_id = '$CHART_ID'
   )
order by created_at asc;
"
```

## 15. Failure Cases To Test

### 15.1 Unsupported Filter Field

```bash
curl -s -X POST "http://localhost:8787/charts/$CHART_ID/filter" \
  -H "Content-Type: application/json" \
  -d '{
    "filters": [
      {"field": "id", "operator": "=", "value": 1}
    ]
  }' | jq
```

Expected:

- `400`
- unsupported filter field

### 15.2 Invalid Drill Target

```bash
curl -s -X POST "http://localhost:8787/charts/$CHART_ID/drill-down" \
  -H "Content-Type: application/json" \
  -d '{
    "target_level_id": "not_a_real_level"
  }' | jq
```

Expected:

- `400`

### 15.3 Wrong Action Type

If a target is classified as `drill_up`, calling `switch-level` with that target should fail.

```bash
curl -s -X POST "http://localhost:8787/charts/$CHART_ID/switch-level" \
  -H "Content-Type: application/json" \
  -d '{
    "target_level_id": "region"
  }' | jq
```

Expected:

- `400`
- target action type mismatch

## 16. Optional Quick Smoke Test Script Pattern

Once you have a valid `$CHART_ID`, a fast smoke sequence is:

```bash
curl -s "http://localhost:8787/charts/$CHART_ID/actions" | jq

curl -s -X POST "http://localhost:8787/charts/$CHART_ID/filter" \
  -H "Content-Type: application/json" \
  -d '{"filters":[{"field":"product_grp","operator":"=","value":"HSD"}]}' | jq

curl -s -X POST "http://localhost:8787/charts/$CHART_ID/drill-down" \
  -H "Content-Type: application/json" \
  -d '{"target_level_id":"region","selected_dimension":"zone","selected_value":"North"}' | jq
```

## 17. What To Confirm Before Calling Phase 52 Tested

Minimum pass bar:

- hierarchy rows exist in `quantyx_business_hierarchies`
- chart returns interaction metadata
- `available_dimension_navigation` is non-empty for a hierarchy-based chart
- filter creates a derived chart
- drill-down creates a derived chart with changed grouping
- drill-up works
- switch-level works where available
- breadcrumb depth grows across multiple actions
- `back` returns the prior chart state
- interaction audit rows are persisted in `quantyx_chart_interactions`

## 18. Current Known Limits During Testing

These are not test failures unless they block the core flow:

- cross-table join-aware navigation is still less mature than same-table hierarchy navigation
- deeper lineage replay refinements are intentionally deferred until after current testing
- available targets depend on actual hierarchy bindings persisted during the run, so some target names will vary by chart
