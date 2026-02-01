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

## 2) Scan via connection (customer-provided credentials)

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

## 3) Ingest business context (glossary, abbreviations, hierarchies, questions)

POST /context/ingest (text + file_ids)

Purpose: store business context text provided by the customer (tables/columns, abbreviations, synonyms, hierarchies, sample questions).

Request:
```json
{
  "tenant_id": "tenant_a",
  "domain_id": "manufacturing",
  "source_type": "business_context",
  "source_title": "Operations glossary and hierarchy notes",
  "raw_text": "SBU = Strategic Business Unit. Sales org is Zone > Region > Sales Area...",
  "file_ids": ["file_123", "file_456"],
  "metadata": {
    "connection_id": "conn_prod",
    "database": "prod_warehouse",
    "schema": "public",
    "tables": ["fact_production_daily", "dim_plant"],
    "columns": ["plant_name", "region_name"]
  }
}
```

Response (example):
```json
{ "context_id": "ctx_123", "status": "submitted" }
```

Or upload a file (.txt or .docx):

POST /context/ingest-file (multipart/form-data, single file)

Form fields:
- `tenant_id`, `domain_id`, `source_type`, `source_title`
- `metadata` (JSON string)
- `file` (text file)

Response:
```json
{ "file_id": "file_123", "status": "stored" }
```

Expected outcome:
- We persist all business context text and linked file content for LLM-based extraction and review.

---

## 4) Extract structured context (LLM)

POST /context/extract

Purpose: extract abbreviations, synonyms, hierarchy candidates, metric candidates, and question intents.

Request:
```json
{
  "tenant_id": "tenant_a",
  "domain_id": "manufacturing",
  "context_id": "ctx_123",
  "extraction_types": ["abbreviations", "synonyms", "hierarchies", "metric_candidates", "question_intents"],
  "model": "gpt-4o-mini"
}
```

Response (example):
```json
{
  "extraction_id": "ext_123",
  "context_id": "ctx_123",
  "extractions": {
    "abbreviations": [{"abbr": "SBU", "definition": "Strategic Business Unit"}],
    "synonyms": [{"term": "sales area", "synonyms": ["territory"]}],
    "hierarchies": [{"name": "sales_org", "levels": ["zone", "region", "sales_area"]}],
    "metric_candidates": [{"metric_name": "output_tmt", "table": "fact_production_daily"}],
    "question_intents": [{"question": "Which plants are underperforming?", "metrics": ["output_tmt"]}]
  }
}
```

Expected outcome:
- We convert raw context into structured data for reuse across ontology and metrics.

---

## 5) Apply extracted context (seed ontology + metrics)

POST /context/apply

Purpose: apply context extractions to glossary, entity overrides, hierarchy overrides, and metric suggestions.

Request:
```json
{
  "tenant_id": "tenant_a",
  "domain_id": "manufacturing",
  "extraction_id": "ext_123",
  "apply": { "entities": true, "hierarchies": true, "glossary": true, "metrics": true }
}
```

Response (example):
```json
{ "status": "applied", "updated": { "entities": 4, "hierarchies": 1, "metrics": 8 } }
```

Expected outcome:
- Ontology, hierarchies, and metric suggestions are enriched with customer context.

---

## 6) Auto-detect metrics + entities (seed suggestions for faster onboarding)

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

## 7) Review + correct entities and hierarchies (match customer reality)

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

## 8) Infer facts and dimensions (dbt-style model suggestions)

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

## 9) Generate dbt manifest (store in DB)

POST /dbt/manifest/generate

Purpose: run dbt compile and store manifest.json in Postgres for lineage + model resolution.

Request:
```json
{
  "tenant_id": "tenant_a",
  "domain_id": "manufacturing",
  "connection_id": "conn_prod",
  "dbt_project_path": "dbt_projects/dbt-tenant_a",
  "profile_name": "default",
  "target_name": "dev",
  "profiles_dir": "~/.dbt"
}
```

Response:
```json
{
  "manifest_id": "manifest_123",
  "status": "stored",
  "tenant_id": "tenant_a",
  "dbt_project_path": "dbt_projects/dbt-tenant_a"
}
```

Expected outcome:
- Manifest is available from DB for schema listing and metric persistence.
- If `dbt_project_path` is not provided, the API creates `dbt_projects/dbt-<tenant_id>` automatically.

---

## 10) Review + promote metrics (make them queryable and trusted)

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

## 11) Apply the contracts (reload catalog so the app can use them)

POST /contracts/apply

Purpose: reload the in-memory catalog so new metrics become queryable.

Expected outcome:
- The API instantly recognizes the certified metrics without a code deploy.

---

## 12) Validate schema + explore (confirm the semantic layer is ready)

GET /schema
GET /metrics
GET /datasets?domain_id=manufacturing
GET /dimensions
GET /dimension-values?dimension=plant_name&limit=50

Expected outcome:
- We confirm the catalog is populated and explore dimension values for UI filters.

---

## 13) Ask a question (first live query to prove value)

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

## 14) Governance hooks (show lineage and policies to build trust)

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

## 15) Insights + Actions (turn observations into action)

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

## 16) Anomaly detection + time-series (see issues early and explain them)

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

## 17) Scenarios (plan responses before taking action)

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
