# Onboarding API Flow (New Customer)

This document shows the end-to-end flow to onboard a new customer and get them
to a usable AI analytics experience. It connects the API calls to a narrative
so the value is clear at each step.

Example organization: X Manufacturing Ltd  
Selected domain pack: manufacturing

Story context:
X Manufacturing wants to track output anomalies, understand root causes, and
drive corrective actions quickly. We onboard them in a structured flow so the
system learns their data, validates metrics, and produces explainable insights.

---

## 0) Inputs you must provide (one-time)

DB connection details (stored in `.env` or secrets):
```
DB_HOST=140.245.238.142
DB_PORT=5432
DB_NAME=hpcl_ceg
DB_USER=ceg_user
DB_PASSWORD=xyxx
DB_SCHEMA=public
```

Optional (LLM):
```
OPENAI_API_KEY=...
OPENAI_MODEL=gpt-4o-mini
```

Note:
- `.env` is for internal testing only. Production should use a secrets manager.

---

## 1) Discover available domains (choose the best industry pack)

GET /context/domains

Purpose: list available industry packs.

Response (example):
```json
{
  "domains": [
    { "domain_id": "manufacturing", "display_name": "manufacturing" }
  ]
}
```

Expected outcome:
- We pick the manufacturing pack so the ontology and metric templates align with X Manufacturing’s data.

---

## 2) Scan the customer schema (understand what tables exist)

POST /onboard/scan

Purpose: read source schema and column profiles.

Request:
```json
{ "schema": "public" }
```

Response (example):
```json
{
  "tables": [
    {
      "table": "fact_production_daily",
      "columns": [
        { "name": "output_tmt", "data_type": "numeric", "null_frac": 0.0 }
      ]
    }
  ]
}
```

Expected outcome:
- We understand what raw tables and columns exist for production output, plants, and product dimensions.

---

## 3) Scan via connection (customer-provided credentials)

POST /onboard/scan-connection

Purpose: scan all tables from the customer-provided database and return profiles.

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
              "tables": ["fact_production_daily"],
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

Expected outcome:
- The UI shows a schema scan result view with profiles for each table/column.

Note:
- This endpoint is used when the customer does not want to set environment variables on our side.

---

## 4) Auto-detect metrics + entities (seed suggestions for faster onboarding)

POST /onboard/map?domain_id=manufacturing&use_llm=true

Purpose: map schema columns to the base ontology using rules (and optional LLM suggestions).

Request:
```json
{ "schema": "public" }
```

Response (example):
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

POST /metrics/suggested?domain_id=manufacturing&persist=true

Purpose: auto-detect measures, time columns, entity candidates. Persist to registry.

Request:
```json
{ "schema": "public" }
```

Response (example):
```json
{
  "measures": [
    {
      "table": "fact_production_daily",
      "column": "output_tmt",
      "measure_type": "volume",
      "unit": "tmt",
      "confidence": 0.9,
      "additive": true
    }
  ],
  "low_confidence_measures": [],
  "low_confidence_threshold": 0.7,
  "time_columns": [
    { "table": "fact_production_daily", "column": "production_date" }
  ],
  "entity_candidates": [
    {
      "table": "fact_production_daily",
      "column": "plant_name",
      "mapped_entity_type": "facility",
      "confidence": 0.7
    }
  ]
}
```

Expected outcome:
- The system suggests the most likely metrics and entity columns, reducing manual work.

---

## 5) Review + correct entities and hierarchies (match customer reality)

GET /entities?domain_id=manufacturing&tenant_id=x_mfg

Purpose: see entities + hierarchies from the pack.

PATCH /entities/{entity_id}?domain_id=manufacturing&tenant_id=x_mfg

Purpose: override entity mapping (join key, description).

Request:
```json
{
  "description": "Plant hierarchy for X Manufacturing",
  "join_key": "plant_name",
  "examples": ["plant", "facility", "site"]
}
```

Expected outcome:
- The ontology is aligned with X Manufacturing’s plant hierarchy (division → plant → line).

PATCH /hierarchies/{hierarchy_name}?domain_id=manufacturing&tenant_id=x_mfg

Purpose: override hierarchy levels if the customer differs from the default pack.

Request:
```json
{
  "levels": ["division", "plant", "line"],
  "description": "Operational rollup for plants"
}
```

---

## 6) Infer facts and dimensions (dbt-style model suggestions)

POST /onboard/infer-models?domain_id=manufacturing

Purpose: suggest candidate facts and dimensions before metric promotion.

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

Expected outcome:
- The UI shows recommended fact/dim models and confirms grain and keys.

---

## 7) Review + promote metrics (make them queryable and trusted)

PATCH /metrics/{metric_id}

Purpose: promote suggested metrics to certified and fix SQL/dimensions.

Request:
```json
{
  "display_name": "Total Output (TMT)",
  "description": "Total production output in TMT",
  "dimensions": ["plant_name", "product_name", "fiscal_year"],
  "status": "certified"
}
```

Expected outcome:
- Metrics are certified and ready for trusted analytics and anomaly detection.

If a metric does not exist, create it:

POST /metrics

Request:
```json
{
  "domain_id": "manufacturing",
  "metric_name": "total_output_tmt",
  "description": "Total production output in TMT",
  "type": "sum",
  "sql": "{{ ref('fact_production_daily') }}.output_tmt",
  "grain": "day",
  "dimensions": ["plant_name", "product_name", "fiscal_year"],
  "unit": "tmt",
  "status": "certified"
}
```

---

## 8) Apply the contracts (reload catalog so the app can use them)

POST /contracts/apply

Purpose: reload the in-memory catalog so new metrics become queryable.

Expected outcome:
- The API instantly recognizes the certified metrics without a code deploy.

---

## 9) Validate schema + explore (confirm the semantic layer is ready)

GET /schema
GET /metrics
GET /datasets?domain_id=manufacturing
GET /dimensions
GET /dimension-values?dimension=plant_name&limit=50

Expected outcome:
- We confirm the catalog is populated and explore dimension values for UI filters.

---

## 10) Ask a question (first live query to prove value)

POST /query

Request:
```json
{
  "question": "Top 5 plants by output for Q1 FY 2024-2025",
  "limit": 100,
  "explain": true
}
```

Expected outcome:
- The customer sees a real answer based on their data, proving the system works.

---

## 11) Governance hooks (show lineage and policies to build trust)

GET /policies?domain_id=manufacturing

Purpose: load pack policies for enforcement in UI.

GET /governance/lineage

Purpose: show metric → dataset → model lineage in the UI.

Example response:
```json
{
  "lineage": [
    {
      "metric_name": "total_output_tmt",
      "dataset": "fact_production_daily",
      "dbt_model": "fact_production_daily"
    }
  ]
}
```

Expected outcome:
- Users trust the metrics because they can see lineage and policy context.

---

## 12) Insights + Actions (turn observations into action)

POST /insights/generate?domain_id=manufacturing

Purpose: generate a variance insight and persist it.

GET /insights

Purpose: list recent insights.

POST /actions

Purpose: create an action from an insight.

Request:
```json
{
  "domain_id": "manufacturing",
  "headline": "Investigate output drop at Plant A",
  "severity": "medium",
  "status": "open",
  "assigned_to": "ops_manager@x-mfg.com",
  "source_insight_id": "ins_123"
}
```

Expected outcome:
- Insights are converted into trackable actions and outcomes.

POST /actions/{action_id}/feedback

Purpose: store action outcome and impact window.

Request:
```json
{
  "status": "resolved",
  "outcome": "Equipment recalibrated",
  "notes": "Resolved after maintenance",
  "impact_window": {"start": "2025-02-01", "end": "2025-02-28"}
}
```

---

## 13) Anomaly detection + time-series (see issues early and explain them)

POST /timeseries

Purpose: fetch chart-ready series with anomaly flags for line charts.

Request:
```json
{
  "metric_name": "total_output_tmt",
  "grain": "month",
  "filters": [{"field": "plant_name", "operator": "=", "value": "Plant A"}],
  "limit": 24,
  "window": 6,
  "threshold": 2.5
}
```

Expected outcome:
- The customer sees anomalies on the line chart and can drill down for root causes.

POST /insights/generate?type=anomaly&metric_name=total_output_tmt&domain_id=manufacturing

Purpose: generate and persist the latest anomaly for the metric.

GET /insights/{insight_id}/details

Purpose: drill down into drivers and correlated metrics for the anomaly point.

---

## 14) Scenarios (plan responses before taking action)

POST /scenarios  
POST /scenarios/{scenario_id}/run  
POST /scenarios/compare

Expected outcome:
- Planning teams can compare scenario impacts before committing to actions.

---

## Placeholder APIs (not yet implemented)

These are planned or referenced in docs but not currently available:
- POST /onboard/map (manual ontology mapping workflow)
- GET /contracts/export
- POST /contracts/import
- POST /insights/bulk-generate
