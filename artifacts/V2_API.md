# Quantyx API Schemas v1 (UI ↔ Backend Contracts)

This document defines the HTTP APIs and JSON schemas used by the UI. It aligns
with Architecture v2 and is intentionally generic across industries. Domain
specificity is expressed via industry packs and contracts, not code.

---

## Conventions

### Base URL
- `/` (current implementation)
- `/api/v1` (future prefix if gateway added)

### Auth (recommended MVP)
- Header: `Authorization: Bearer <token>`
- Tenant header (optional if encoded in token): `X-Tenant-Id: <tenant_id>`

### Response shape
Current implementation returns raw JSON objects without a wrapper envelope. If a
gateway is added later, we can wrap responses in a standard envelope.

```json
{
  "ok": true,
  "data": {},
  "meta": {},
  "error": null
}
```

On error (FastAPI):

```json
{
  "ok": false,
  "data": null,
  "meta": {"request_id": "req_123"},
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Invalid time range",
    "details": [{"field": "time_range", "issue": "end < start"}]
  }
}
```

Pagination (list endpoints):
- Request: `?limit=50&cursor=...`
- Response meta:

```json
{ "next_cursor": "abc", "limit": 50 }
```

---

## 1) System + Context APIs

### 1.1 GET /health
Health check for the API.

Response:
```json
{ "status": "ok" }
```

### 1.2 GET /context/domains
List domain packs available to the tenant.

Response data:
```json
{
  "domains": [
    {
      "domain_id": "energy_distribution",
      "display_name": "energy_distribution"
    }
  ]
}
```

---

## 2) Explore APIs

### 2.1 GET /metrics
List metrics from the catalog.

Response:
```json
{
  "metrics": [
    {
      "name": "total_sales_volume_tmt",
      "description": "Total HPCL sales volume in TMT",
      "type": "sum",
      "grain": "day",
      "dimensions": ["sales_area_name", "product_name", "fiscal_year"]
    }
  ],
  "limit": 200,
  "cursor": null,
  "next_cursor": "c2FsZXNfdnNfdGFyZ2V0X2FjaGlldmVtZW50X3BjdA=="
}
```

Cursor pagination:
- First request: omit `cursor` and send `limit`.
- Response includes `next_cursor` if more items are available.
- Next request: pass `cursor=<next_cursor>` to fetch the next page.

### 2.2 GET /datasets?domain_id=...&connection_id=...&database=...&schema=...
List datasets defined in the domain pack.

Response:
```json
{
  "datasets": [
    {
      "name": "sales_area_performance",
      "source_model": "fact_hpcl_sales_daily",
      "description": "Sales performance by sales area and product"
    }
  ],
  "limit": 200,
  "cursor": null,
  "next_cursor": "aW5kdXN0cnlfcGVyZm9ybWFuY2U="
}
```

Cursor pagination:
- Use `cursor` + `limit` to page through datasets.

### 2.3 GET /dimensions?connection_id=...&database=...&schema=...
List dimensions from the catalog.

Response:
```json
{
  "dimensions": [
    {
      "name": "sales_area_name",
      "description": "Sales area",
      "data_type": "string",
      "sql": "{{ ref('fact_hpcl_sales_daily') }}.sales_area_name"
    }
  ]
}
```

### 2.4 GET /dimension-values?dimension=...&limit=...&cursor=...&search=...&starts_with=...&exclude_nulls=...&order=...
Return distinct values for a dimension.

Response:
```json
{
  "dimension": "sales_area_name",
  "values": [{"value": "Tenali"}, {"value": "Vijayawada"}],
  "limit": 100,
  "cursor": null,
  "next_cursor": "VmlqYXlhd2FkYQ=="
}
```

Examples:
```
GET /dimension-values?dimension=sales_area_name&search=pur
GET /dimension-values?dimension=sales_area_name&starts_with=Vi&limit=25
GET /dimension-values?dimension=sales_area_name&exclude_nulls=true&order=desc
GET /dimension-values?dimension=sales_area_name&limit=50&cursor=VmlqYXlhd2FkYQ==
```

Cursor pagination:
- First request: omit `cursor` and send `limit`.
- Response includes `next_cursor` if more values are available.
- Next request: pass `cursor=<next_cursor>` to fetch the next page.

### 2.5 GET /schema?connection_id=...&database=...&schema=...
List dbt models and columns from `manifest.json`.

Response:
```json
{
  "models": [
    { "name": "fact_hpcl_sales_daily", "schema": "public", "columns": ["sales_date"] }
  ],
  "limit": 200,
  "cursor": null,
  "next_cursor": "ZmFjdF9ocGNsX3NhbGVzX21vbnRobHlfdGFyZ2V0cw=="
}
```

Cursor pagination:
- Use `cursor` + `limit` to page through models.

### 2.6 GET /entities?domain_id=...&tenant_id=...
Return ontology entities + hierarchies for a domain. If `tenant_id` is present,
apply overrides from `quantyx_entity_overrides` and `quantyx_hierarchy_overrides`.

Response:
```json
{
  "entities": [
    { "entity_id": "organizational_unit", "description": "Sales org", "join_key": "sales_area_name" }
  ],
  "hierarchies": [
    { "name": "sales_org", "levels": ["sbu", "zone", "region", "sales_area"] }
  ],
  "entity_limit": 200,
  "entity_cursor": null,
  "entity_next_cursor": "cHJvZHVjdA==",
  "hierarchy_limit": 200,
  "hierarchy_cursor": null,
  "hierarchy_next_cursor": "cmVnaW9uX29yZw=="
}
```

Cursor pagination:
- Entities: use `entity_cursor` + `entity_limit`.
- Hierarchies: use `hierarchy_cursor` + `hierarchy_limit`.

### 2.7 PATCH /entities/{entity_id}?domain_id=...&tenant_id=...
Upsert a tenant-specific entity override.

Request:
```json
{
  "description": "Organizational hierarchy for sales operations",
  "join_key": "sales_area_name",
  "examples": ["zone", "region", "sales_area"]
}
```

Response:
```json
{ "ok": true }
```

### 2.8 PATCH /hierarchies/{hierarchy_name}?domain_id=...&tenant_id=...
Upsert a tenant-specific hierarchy override.

Request:
```json
{
  "levels": ["sbu", "zone", "region", "sales_area"],
  "description": "Sales organization rollup"
}
```

Response:
```json
{ "ok": true }
```

---

## 3) Onboarding APIs (Industry Packs + Auto Metrics)

These endpoints make onboarding generic across industries.

### 3.1 POST /onboard/scan
Inspect source schema and return detected columns and profiles.

Request:
```json
{ "schema": "public" }
```

Response:
```json
{
  "tables": [
    {
      "table": "fact_hpcl_sales_daily",
      "columns": [
        { "name": "sales_tmt", "data_type": "numeric", "null_frac": 0.0 }
      ]
    }
  ]
}
```

### 3.2 POST /onboard/map?domain_id=...&use_llm=...
Suggest ontology mappings from schema columns to the selected domain pack.

Request:
```json
{ "schema": "public" }
```

Response:
```json
{
  "candidates": [
    {
      "table": "fact_production_daily",
      "column": "plant_name",
      "mapped_entity_type": "facility",
      "confidence": 0.7
    }
  ],
  "low_confidence_candidates": [],
  "low_confidence_threshold": 0.7
}
```

Notes:
- Set `use_llm=true` to include LLM-assisted suggestions when `OPENAI_API_KEY` is configured.

### 3.3 POST /onboard/scan-connection
Scan multiple user-provided connections and return schema profiles with cursor pagination.

Request:
```json
{
  "connections": [
    {
      "connection_id": "conn_prod",
      "db_type": "postgres",
      "host": "db.company.com",
      "port": 5432,
      "user": "readonly_user",
      "password": "******",
      "sample_rows": 100,
      "databases": [
        {
          "name": "prod_warehouse",
          "schemas": [
            {
              "name": "public",
              "tables": ["fact_production_daily", "dim_plant"],
              "limit": 20,
              "cursor": null
            }
          ]
        }
      ]
    }
  ]
}
```

Response:
```json
{
  "connections": [
    {
      "connection_id": "conn_prod",
      "databases": [
        {
          "name": "prod_warehouse",
          "schemas": [
            {
              "name": "public",
              "tables": [
                {
                  "table": "fact_production_daily",
                  "columns": [
                    { "name": "production_date", "data_type": "date", "null_frac": 0.0, "distinct": 365 },
                    { "name": "output_tmt", "data_type": "numeric", "mean": 124.5, "null_frac": 0.0 }
                  ]
                }
              ],
              "limit": 20,
              "cursor": null,
              "next_cursor": "ZmFjdF9wcm9kdWN0aW9uX2RhaWx5"
            }
          ]
        }
      ]
    }
  ]
}
```

Notes:
- Currently supported for `db_type=postgres`.
- `sample_rows` is capped at 100 for safety.

### 3.4 POST /onboard/infer-models?domain_id=...
Infer candidate dbt facts and dimensions from schema scan + ontology.

Request:
```json
{
  "schema": "public",
  "tables": ["fact_production_daily", "dim_plant"],
  "time_column": "production_date",
  "grain": "day",
  "use_llm": true
}
```

Response:
```json
{
  "facts": [
    {
      "name": "fact_production_daily",
      "grain": "day",
      "measures": ["output_tmt", "downtime_hours"],
      "dimensions": ["plant_name", "product_name", "fiscal_year"],
      "confidence": 0.8
    }
  ],
  "dimensions": [
    {
      "name": "dim_plant",
      "keys": ["plant_id"],
      "attributes": ["plant_name", "region_name"],
      "confidence": 0.75
    }
  ]
}
```

### 3.5 POST /metrics/suggested?domain_id=...&persist=true
Return auto-generated metrics (status = suggested), including a low-confidence bucket.

Request:
```json
{ "schema": "public" }
```

### 3.6 Metric lifecycle flow (seed → review → promote)
Use the registry APIs to turn auto-suggested metrics into certified metrics without code changes.

Step 1: Seed suggestions into the registry
```
POST /metrics/suggested?domain_id=energy_distribution&persist=true
{ "schema": "public" }
```

Step 2: Review + promote (PATCH)
```
PATCH /metrics/energy_distribution__fact_hpcl_sales_daily__sales_tmt
{
  "display_name": "Total Sales Volume (TMT)",
  "description": "Total sales volume in TMT",
  "unit": "tmt",
  "dimensions": ["sales_area_name", "product_name", "fiscal_year"],
  "status": "certified"
}
```

Step 3: Create a custom metric (POST)
```
POST /metrics
{
  "domain_id": "energy_distribution",
  "metric_name": "total_sales_volume_tmt",
  "description": "Total sales volume in TMT",
  "type": "sum",
  "sql": "{{ ref('fact_hpcl_sales_daily') }}.sales_tmt",
  "grain": "day",
  "dimensions": ["sales_area_name", "product_name", "fiscal_year"],
  "unit": "tmt",
  "status": "certified"
}
```

Step 4: Apply contracts (reload catalog)
```
POST /contracts/apply
```

Notes:
- `POST /metrics` can create new or update existing entries (upsert).
- `PATCH /metrics/{metric_id}` is safer for small edits (status, SQL fixes, dimension list).
- `POST /contracts/apply` refreshes the in-memory catalog for the API process so new/updated metrics are queryable immediately.

Response:
```json
{
  "measures": [
    { "table": "fact_hpcl_sales_daily", "column": "sales_tmt", "measure_type": "volume", "unit": "tmt", "confidence": 0.9, "additive": true }
  ],
  "low_confidence_measures": [
    { "table": "fact_hpcl_sales_daily", "column": "avg_rate", "measure_type": "number", "unit": null, "confidence": 0.6, "additive": false }
  ],
  "low_confidence_threshold": 0.7,
  "time_columns": [
    { "table": "fact_hpcl_sales_daily", "column": "sales_date" }
  ],
  "entity_candidates": [
    { "table": "fact_hpcl_sales_daily", "column": "sales_area_name", "mapped_entity_type": "organizational_unit", "confidence": 0.9 }
  ]
}
```

---

## 4) Ask APIs (Conversational)

---

### 4.1 POST /query
Primary endpoint: NLQ → SQL-backed results.

Request:
```json
{
  "question": "Top 5 sales areas by sales volume for MS in Q2 FY 2024-2025.",
  "limit": 100,
  "explain": true
}
```

Response:
```json
{
  "metrics": ["total_sales_volume_tmt"],
  "dimensions": ["sales_area_name"],
  "sql": "SELECT sales_area_name, SUM(sales_tmt) AS total_sales_volume_tmt FROM ...",
  "rows": [
    { "sales_area_name": "Tenali", "total_sales_volume_tmt": 123.4 }
  ],
  "by_company_sql": null,
  "by_company_rows": null
}
```

---

## 5) Governance APIs

### 5.1 GET /policies?domain_id=...
Return policy rules from the domain pack.

Response:
```json
{
  "policies": [
    {
      "policy_id": "sbu_exclusion",
      "description": "Exclude SBU values not relevant for this tenant"
    }
  ]
}
```

---

## 6) Insights + Actions APIs

### 6.1 GET /insights?domain_id=...&limit=...&cursor=...
List recent insights for a domain.

Response:
```json
{
  "insights": [
    {
      "insight_id": "ins_123",
      "insight_type": "variance",
      "headline": "Sales volume decreased 4.2% vs last month",
      "severity": "medium",
      "confidence": 0.8
    }
  ],
  "limit": 200,
  "cursor": null,
  "next_cursor": "aW5zXzEyNA=="
}
```

### 6.2 GET /insights/{insight_id}
Get a single insight.

Response:
```json
{
  "insight": {
    "insight_id": "ins_123",
    "insight_type": "variance",
    "headline": "Sales volume decreased 4.2% vs last month",
    "severity": "medium",
    "confidence": 0.8
  }
}
```

### 6.3 GET /insights/{insight_id}/details
Get drivers and correlated facts for the insight.

Response:
```json
{
  "insight": {
    "insight_id": "ins_123",
    "insight_type": "anomaly",
    "headline": "total_sales_volume_tmt anomaly detected at 2024-06-01"
  },
  "drivers": [
    {
      "dimension": "sales_area_name",
      "dimension_value": "Tenali",
      "metric_value": 240.5
    }
  ],
  "correlations": [
    {
      "metric_name": "target_sales_tmt",
      "actual": 1300.0,
      "baseline": 1250.0,
      "deviation": 50.0,
      "z_score": 1.4,
      "is_anomaly": false
    }
  ]
}
```

### 6.4 POST /timeseries
Return time-series points with baseline + anomaly flags.

Request:
```json
{
  "metric_name": "total_sales_volume_tmt",
  "grain": "month",
  "filters": [{ "field": "product_name", "operator": "=", "value": "MS" }],
  "limit": 24,
  "window": 6,
  "threshold": 2.5
}
```

Response:
```json
{
  "metric_name": "total_sales_volume_tmt",
  "grain": "month",
  "series": [
    {
      "period": "2024-01-01",
      "actual": 1200.5,
      "baseline": 1150.0,
      "deviation": 50.5,
      "z_score": 1.2,
      "is_anomaly": false
    }
  ]
}
```

### 6.5 POST /insights/generate?domain_id=...&scenario_id=...
Generate a variance insight and persist it.

Response:
```json
{
  "insight": {
    "insight_id": "ins_456",
    "insight_type": "variance",
    "headline": "Sales volume increased 3.1% vs last month",
    "severity": "low",
    "confidence": 0.7
  }
}
```

### 6.6 GET /actions?domain_id=...&status=...&limit=...&cursor=...
List actions with optional filters.

Response:
```json
{
  "actions": [
    {
      "action_id": "act_123",
      "headline": "Investigate sales drop in Tenali",
      "status": "open",
      "severity": "medium"
    }
  ],
  "limit": 200,
  "cursor": null,
  "next_cursor": "YWN0XzEyNA=="
}
```

### 6.7 GET /actions/{action_id}
Get a single action.

Response:
```json
{
  "action": {
    "action_id": "act_123",
    "headline": "Investigate sales drop in Tenali",
    "status": "open",
    "severity": "medium"
  }
}
```

### 6.8 POST /actions
Create a new action.

Request:
```json
{
  "domain_id": "energy_distribution",
  "headline": "Investigate sales drop in Tenali",
  "severity": "medium",
  "status": "open",
  "assigned_to": "ops_manager@company.com",
  "source_insight_id": "ins_123"
}
```

Response:
```json
{
  "action_id": "act_456",
  "status": "open"
}
```

### 6.9 PATCH /actions/{action_id}
Update action metadata or status.

Request:
```json
{
  "status": "in_progress",
  "assigned_to": "ops_manager@company.com"
}
```

Response:
```json
{
  "action_id": "act_456",
  "status": "in_progress"
}
```

### 6.10 POST /actions/{action_id}/feedback
Store action feedback and impact.

Request:
```json
{
  "status": "resolved",
  "outcome": "Distributor restocked",
  "notes": "Resolved after 2 days",
  "impact_window": {"start": "2025-02-01", "end": "2025-02-28"}
}
```

Response:
```json
{ "ok": true }
```

---

## 7) Scenarios APIs

### 7.1 GET /scenarios?domain_id=...&limit=...&cursor=...
List scenarios for a domain.

Response:
```json
{
  "scenarios": [
    {
      "scenario_id": "baseline",
      "domain_id": "energy_distribution",
      "name": "Baseline",
      "status": "ready",
      "is_baseline": true
    }
  ],
  "limit": 200,
  "cursor": null,
  "next_cursor": "c2Nlbl8wMDE="
}
```

### 7.2 GET /scenarios/{scenario_id}
Get a single scenario.

Response:
```json
{
  "scenario": {
    "scenario_id": "scenario_001",
    "domain_id": "energy_distribution",
    "name": "Distribution Disruption",
    "status": "draft"
  }
}
```

### 7.3 POST /scenarios
Create a scenario.

Request:
```json
{
  "domain_id": "energy_distribution",
  "name": "Distribution Disruption",
  "description": "Simulate loss of supply in Zone A",
  "status": "draft"
}
```

Response:
```json
{
  "scenario_id": "scenario_001",
  "status": "draft"
}
```

### 7.4 PATCH /scenarios/{scenario_id}
Update scenario metadata or status.

Request:
```json
{
  "status": "ready"
}
```

Response:
```json
{
  "scenario_id": "scenario_001",
  "status": "ready"
}
```

### 7.5 POST /scenarios/{scenario_id}/run
Persist scenario parameters for downstream processing.

Request:
```json
{
  "parameters": {"uplift_pct": 3}
}
```

Response:
```json
{
  "scenario_id": "scenario_001",
  "status": "completed"
}
```

### 7.6 POST /scenarios/compare
Compare two scenarios for a metric.

Request:
```json
{
  "base_scenario_id": "baseline",
  "compare_scenario_id": "scenario_001",
  "metric_name": "total_sales_volume_tmt"
}
```

Response:
```json
{
  "base_scenario_id": "baseline",
  "compare_scenario_id": "scenario_001",
  "metric_name": "total_sales_volume_tmt",
  "delta": 12.3
}
```
### 5.2 GET /governance/lineage?metric_name=...
Return metric lineage (metric → dataset → dbt model).

Response:
```json
{
  "lineage": [
    {
      "metric_name": "total_sales_volume_tmt",
      "dataset": "fact_hpcl_sales_daily",
      "dbt_model": "fact_hpcl_sales_daily"
    }
  ]
}
```

Notes:
- `query_id` is used to fetch details, evidence, and audit later.
- `result` can be table or timeseries (see types below).

### 3.2 POST /query/explain
Returns the structured interpretation + query plan + (optional) SQL.

### 3.3 POST /query/followups
Given a query (or context), propose next best questions.

---

## 4) Explore APIs (Datasets / Metrics / Entities)

### 4.1 GET /datasets?domain_id=...

### 4.2 GET /metrics?domain_id=...&dataset_id=...

Metrics include:
- `status`: suggested | draft | certified | deprecated
- `owner`, `version`, `deprecated`

### 4.3 GET /entities?domain_id=...

---

## 5) Insights APIs (Proactive Feed)

### 5.1 GET /insights?domain_id=...&scenario_id=...&time_range=...

### 5.2 GET /insights/{insight_id}

---

## 6) Scenarios APIs (Planning)

### 6.1 POST /scenarios

### 6.2 POST /scenarios/{scenario_id}/run

### 6.3 POST /scenarios/compare

---

## 7) Decisions / Actions APIs (Action Loop)

### 7.1 GET /actions?domain_id=...&status=open

### 7.2 POST /actions/{action_id}/assign

### 7.3 POST /actions/{action_id}/feedback

---

## 8) Data and Semantics APIs (Admin)

### 8.1 GET/POST /datasources

### 8.2 POST /contracts/validate

### 8.3 POST /contracts/apply

---

## 9) Governance APIs (Lineage, Audit, Policies)

### 9.1 GET /governance/lineage?metric_id=...

### 9.2 GET /governance/audit?cursor=...

### 9.3 GET /policies?domain_id=...

---

## Appendix A - Shared Types

### TimeRange
```json
{
  "type": "relative | absolute",
  "grain": "day | week | month | quarter | year",
  "last_n": 3,
  "start": "2025-11-01",
  "end": "2026-01-31",
  "timezone": "Europe/Dublin"
}
```

### FilterClause
```json
{ "field": "region", "op": "=", "value": "South" }
```

### Result shapes

Table:
```json
{ "shape": "table", "columns": [{"name":"x","type":"string"}], "rows": [{"x":"a"}], "row_count": 1 }
```

Timeseries:
```json
{
  "shape": "timeseries",
  "series": [
    { "key": "actual_sales_tmt", "points": [{"ds":"2025-12-01","value": 120.5}] }
  ]
}
```

---

## Appendix B - Error Codes (recommended)

- VALIDATION_ERROR
- UNAUTHORIZED
- FORBIDDEN
- NOT_FOUND
- POLICY_VIOLATION
- QUERY_TIMEOUT
- INTERNAL_ERROR
