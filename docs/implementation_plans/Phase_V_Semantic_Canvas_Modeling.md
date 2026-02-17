# Phase V: Semantic Canvas Modeling (Dimensions, Facts, Metrics)

Goal: Provide a visual, Denodo-like semantic layer where users build **Dimensions**, **Facts**, and **Metrics** on a drag‑and‑drop canvas. The canvas output is the **semantic model definition** (nodes + edges), which is persisted and powers Ask/Query, Insights, and Review.

This phase is UI‑first (dimensions → facts → metrics) but the backend does not enforce strict ordering.

---

## 1) Scope and Outcomes

1. **Semantic Canvas Workflow**
   - Users can visually create Dimensions, Facts, and Metrics.
   - Lineage is obvious: Dimensions → Facts → Metrics.

2. **Persistence**
   - All objects are persisted to registries:
     - `quantyx_dimensions_registry`
     - `quantyx_facts_registry`
     - `quantyx_metrics_registry`
   - Canvas output can be reconstructed from registries + lineage derivation.

3. **Tenant Scope Resolution**
   - APIs do not accept `connection_id`, `database_name`, `schema_name` in payloads.
   - Scope is resolved server‑side from `quantyx_tenant_scopes`.

4. **Review and Governance**
   - `review` and `review/summary` surface these objects and status.

5. **Canvas Output**
   - The “output” is a **semantic graph snapshot**:
     - Nodes = Dimensions/Facts/Metrics
     - Edges = Lineage (Dimension → Fact, Fact → Metric)

---

## 2) Core Concepts

### 2.1 Dimension
Semantic table describing entities (e.g., Plant, Product, Region).
Fields:
- `name`: model/table name (e.g., `dim_plant`)
- `keys`: business/primary keys (e.g., `plant_id`)
- `attributes`: descriptive fields (e.g., `plant_name`, `region_name`)
- `description`, `status`

### 2.2 Fact
Semantic table at a grain (e.g., daily production).
Fields:
- `table_name`: model/table name (e.g., `fact_production_daily`)
- `grain`: `day`, `month`, `transaction`, etc.
- `time_column`: (optional) time series column
- `measures`: numeric columns
- `dimensions`: dimension keys or attributes used for grouping
- `description`, `status`

### 2.3 Metric
Computed definition derived from facts.
Fields:
- `metric_name`, `type` (sum, avg, count, ratio, etc.)
- `sql` or expression
- `grain` (same or coarser than fact grain)
- `dimensions`: allowed group‑bys
- `status`, `description`

---

## 3) UI Flow (Denodo‑like Canvas)

1. **Start with Dimensions**
   - Add a dimension node.
   - Set keys + attributes.
   - Connect to facts later.

2. **Create Facts**
   - Add a fact node.
   - Assign measures and grain.
   - Link dimension nodes for grouping.

3. **Create Metrics**
   - Add metric nodes.
   - Link to fact nodes and choose aggregation.
   - Metric inherits grain from fact by default.

4. **Lineage**
   - Canvas edges are derived from:
     - Fact `dimensions[]` referencing dimension keys
     - Metric `sql` referencing fact models

---

## 4) Canvas Output (What the Canvas Produces)

The canvas produces a **semantic model definition**. This is not a query or data result; it is a curated semantic layer that powers downstream analytics.

Example output (graph snapshot):
```json
{
  "nodes": [
    { "id": "dim_plant", "type": "dimension" },
    { "id": "fact_production_daily", "type": "fact" },
    { "id": "total_output_tmt", "type": "metric" }
  ],
  "edges": [
    { "from": "dim_plant", "to": "fact_production_daily" },
    { "from": "fact_production_daily", "to": "total_output_tmt" }
  ]
}
```

The same output can be reconstructed from registries:
- **Dimension nodes** from `quantyx_dimensions_registry`
- **Fact nodes** from `quantyx_facts_registry`
- **Metric nodes** from `quantyx_metrics_registry`
- **Edges** derived from:
  - Fact `dimensions[]`
  - Metric `sql` references to facts

---

## 5) API Design (Normal Users)

### 4.1 Dimensions APIs

#### Create Dimension
`POST /dimensions`
```json
{
  "tenant_id": "tenant_a",
  "domain_id": "petroleum_refinery",
  "name": "dim_plant",
  "keys": ["plant_id"],
  "attributes": ["plant_name", "region_name"],
  "description": "Plant master dimension",
  "status": "draft"
}
```

#### Update Dimension
`PATCH /dimensions/{dimension_id}`
```json
{
  "keys": ["plant_id"],
  "attributes": ["plant_name", "region_name", "zone_name"],
  "description": "Updated description",
  "status": "reviewed"
}
```

#### Delete Dimension
`DELETE /dimensions/{dimension_id}`

#### List Dimensions (scoped)
`GET /dimensions?tenant_id=tenant_a`

---

### 4.2 Facts APIs

#### Create Fact
`POST /facts`
```json
{
  "tenant_id": "tenant_a",
  "domain_id": "petroleum_refinery",
  "table_name": "fact_production_daily",
  "grain": "day",
  "time_column": "production_date",
  "measures": ["output_tmt", "downtime_hours"],
  "dimensions": ["plant_id", "product_id", "fiscal_year"],
  "description": "Daily production fact",
  "status": "draft"
}
```

#### Update Fact
`PATCH /facts/{fact_id}`
```json
{
  "grain": "day",
  "measures": ["output_tmt", "downtime_hours", "energy_mwh"],
  "dimensions": ["plant_id", "product_id", "fiscal_year"],
  "status": "reviewed"
}
```

#### Delete Fact
`DELETE /facts/{fact_id}`

#### List Facts (scoped)
`GET /facts?tenant_id=tenant_a`

---

### 4.3 Metrics APIs

#### Create Metric
`POST /metrics`
```json
{
  "tenant_id": "tenant_a",
  "domain_id": "petroleum_refinery",
  "metric_name": "total_output_tmt",
  "type": "sum",
  "sql": "{{ ref('fact_production_daily') }}.output_tmt",
  "grain": "day",
  "dimensions": ["plant_id", "product_id", "fiscal_year"],
  "description": "Total production output in TMT",
  "status": "certified"
}
```

#### Update Metric
`PATCH /metrics/{metric_id}`
```json
{
  "description": "Updated description",
  "status": "reviewed"
}
```

#### Delete Metric
`DELETE /metrics/{metric_id}`

#### List Metrics (scoped)
`GET /metrics?tenant_id=tenant_a`

---

## 6) Aggregations, Grain, and Validation Rules

### 6.1 Grain Rules
- Fact grain defines the natural granularity (e.g., `day`, `month`, `transaction`).
- Metric grain must be **same or coarser** than the fact grain.
  - Example: fact = day, metric = month is allowed; fact = month, metric = day is not.

### 6.2 Aggregation Rules (Metric `type`)
- `sum`, `avg`, `min`, `max`, `count`, `count_distinct`, `ratio`, `rate`
- The UI should require:
  - `type` + `sql` (or expression) + `grain`
- If `type=ratio`, require numerator + denominator references in `sql`.

### 6.3 Validation
- Facts must have at least one measure.
- Dimensions must have at least one key.
- Metric `sql` must reference a fact model (`{{ ref('fact_x') }}`).
- If a fact references dimensions, those dimension keys should exist in dimension registry.

---

## 7) Lineage API (Canvas Edges)

### 5.1 GET /lineage?tenant_id=tenant_a
Returns nodes + edges for the semantic canvas.

Example:
```json
{
  "nodes": [
    {"id": "dim_plant", "type": "dimension"},
    {"id": "fact_production_daily", "type": "fact"},
    {"id": "total_output_tmt", "type": "metric"}
  ],
  "edges": [
    {"from": "dim_plant", "to": "fact_production_daily"},
    {"from": "fact_production_daily", "to": "total_output_tmt"}
  ]
}
```

---

## 8) Persistence Rules

1. **Always persist on creation**
   - `POST /dimensions`, `POST /facts`, `POST /metrics`
2. **Draft by default**
   - unless explicitly set to `reviewed` or `certified`
3. **Deletion**
   - soft delete can be added later (out of scope)

---

## 9) Review Flow

`GET /review/summary?tenant_id=...` should include:
- `facts[]` from `quantyx_facts_registry`
- `dimensions[]` from `quantyx_dimensions_registry`
- `metrics[]` from `quantyx_metrics_registry`

---

## 10) Implementation Steps

1. **API Contracts**
   - Ensure payloads match definitions above.
2. **Persistence**
   - Use upsert into registries.
3. **Lineage API**
   - Derive edges from:
     - Fact `dimensions`
     - Metric `sql` references to facts
4. **UI Hooks**
   - Canvas graph uses lineage API payload.
5. **Review Integration**
   - Review summary consumes registries (already in place).

---

## 11) Open Questions

1. Should facts allow multiple grains (e.g., daily + monthly)?
2. Should metrics allow non‑SQL expressions (DSL)?
3. Do we want validation to ensure dimension keys exist in the dimension registry?
