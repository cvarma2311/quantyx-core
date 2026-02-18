# Onboarding API Flow (New Customer)

This document shows the end-to-end flow to onboard a new customer and get them
to a usable AI analytics experience. It connects the API calls to a narrative
so the value is clear at each step.
For connection-scoped onboarding and multi-context apply rules, see
`docs/implementation_plans/Phase_N_Connection_Scoped_Onboarding.md`.

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

Async variant (recommended for large schemas):

POST /onboard/scan-connection/async

Response:
```json
{ "job_id": "job_123", "status": "queued" }
```

Poll:
GET /jobs/{job_id}

Fetch results:
GET /jobs/{job_id}/result

Pending result example (202):
```json
{
  "job_id": "job_123",
  "status": "running",
  "result": null
}
```

Request:
```json
{
  "tenant_id": "tenant_a",
  "domain_id": "manufacturing",
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

Request (example):
```
tenant_id=tenant_a
domain_id=manufacturing
source_type=business_context
source_title=Ops glossary
metadata={"columns":["plant_name","region_name"]}
file=@context.txt
```

Response:
```json
{ "file_id": "file_123", "status": "stored" }
```

Expected outcome:
- We persist all business context text and linked file content for LLM-based extraction and review.

---

## 3a) Semantic contract extraction (optional)

Use this if you want the semantic layer to enrich `/metrics` and `/datasets` with
definitions and freshness metadata.

POST /contracts/semantic/extract

Request:
```json
{
  "tenant_id": "tenant_a",
  "industry": "manufacturing",
  "inputs": {
    "raw_text": "MFM = mass flow meter. Stock_code identifies product.",
    "tables_and_columns": "fact_dispatch: [bay_name, mfm_id, product_name]",
    "entity_types": ["organizational_unit", "mass_flow_meter", "product"],
    "metric_candidate": "metric_name=throughput_volume, columns=[mfm_volume, product_name]"
  },
  "model": "gpt-4o-mini"
}
```

Response:
```json
{ "contract_id": "contract_123", "status": "extracted" }
```

Apply extracted contract:

POST /contracts/semantic/apply

Request:
```json
{
  "tenant_id": "tenant_a",
  "contract_id": "contract_123"
}
```

Response:
```json
{ "ok": true }
```

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

## 6) Entity mapping (async run + apply to overrides)

POST /onboard/map?domain_id=manufacturing&tenant_id=tenant_a

Purpose: map schema columns to ontology (rule + LLM, default `use_llm=true`) and produce a `mapping_id`.

Async variant (recommended for large schemas):

POST /onboard/map/async

Response:
```json
{ "job_id": "job_124", "status": "queued" }
```

Poll:
GET /jobs/{job_id}

Fetch results:
GET /jobs/{job_id}/result

Pending result example (202):
```json
{
  "job_id": "job_124",
  "status": "running",
  "result": null
}
```

Request:
```json
{
  "tenant_id": "tenant_a"
}
```

Response (example):
```json
{
  "tenant_id": "tenant_a",
  "mapping_id": "map_ab12cd34",
  "candidates": [
    {
      "table": "fact_production_daily",
      "column": "plant_name",
      "entity_id": "facility",
      "mapped_entity_type": "facility",
      "confidence": 0.7
    }
  ],
  "low_confidence_candidates": [
    {
      "table": "fact_production_daily",
      "column": "plant_location",
      "entity_id": "facility",
      "mapped_entity_type": "facility",
      "confidence": 0.45
    }
  ],
  "low_confidence_threshold": 0.7
}
```

Minimum fields expected by UI from map job result:
- `tenant_id`
- `mapping_id`
- `candidates` (each candidate must include `entity_id`)
- `low_confidence_candidates` (each candidate must include `entity_id`)

After job completion:
- Fetch mapping payload:
  - `GET /onboard/map/{mapping_id}?tenant_id=tenant_a`
- Apply selected/all candidates into canonical entity overrides:
  - `POST /onboard/map/{mapping_id}/apply`

Apply request (example):
```json
{
  "tenant_id": "tenant_a",
  "selection_mode": "all",
  "status": "draft",
  "notes": "Initial onboarding apply"
}
```

Optional history:

GET /onboard/map/history?tenant_id=tenant_a&domain_id=manufacturing

---

## 7) Entities + hierarchies (connection-scoped, persisted overrides)

GET /entities?domain_id=manufacturing&tenant_id=tenant_a

Purpose: list tenant overrides for entities + hierarchies (no pack fallback after overrides seeded).

PATCH /entities/{entity_id}?domain_id=manufacturing&tenant_id=tenant_a

Request:
```json
{
  "description": "Plant hierarchy for X Manufacturing",
  "join_key": "plant_name",
  "examples": ["plant", "facility", "site"]
}
```

PATCH /hierarchies/{hierarchy_name}?domain_id=manufacturing&tenant_id=tenant_a

Request:
```json
{
  "levels": ["division", "plant", "line"],
  "description": "Operational rollup for plants"
}
```

Optional:

GET /entities/all?domain_id=manufacturing&tenant_id=tenant_a

GET /hierarchies?tenant_id=tenant_a&domain_id=manufacturing

---

## 8) Infer facts and dimensions (async, persisted to registries)

POST /onboard/infer-models?domain_id=manufacturing

Purpose: suggest candidate facts and dimensions based on the latest scan for the scope.

Async variant (recommended for large schemas):

POST /onboard/infer-models/async

Response:
```json
{ "job_id": "job_125", "status": "queued" }
```

Poll:
GET /jobs/{job_id}

Fetch results:
GET /jobs/{job_id}/result

Pending result example (202):
```json
{
  "job_id": "job_125",
  "status": "running",
  "result": null
}
```

Request:
```json
{
  "tenant_id": "tenant_a",
  "time_column": "production_date",
  "grain": "day",
  "use_llm": true
}
```

When the async job completes, inferred artifacts are persisted directly into:
- `public.quantyx_facts_registry`
- `public.quantyx_dimensions_registry`

UI read path after completion:

GET /facts?tenant_id=tenant_a&domain_id=manufacturing

GET /dimensions?tenant_id=tenant_a&domain_id=manufacturing

Note:
- On first run, these endpoints can be empty before infer-models finishes.

---

## 9) Generate dbt manifest (store in DB)

POST /dbt/manifest/generate

Purpose: run dbt compile and store manifest.json in Postgres for lineage + model resolution.

Note: When using automated dbt (Phase O), this is triggered automatically after
`/onboard/scan-connection` and does not require UI input.

Request:
```json
{
  "tenant_id": "tenant_a",
  "domain_id": "manufacturing",
  "dbt_project_path": "dbt_projects/dbt_tenant_a",
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
  "dbt_project_path": "dbt_projects/dbt_tenant_a"
}
```

Expected outcome:
- Manifest is available from DB for schema listing and metric persistence.
- If `dbt_project_path` is not provided, the API creates `dbt_projects/dbt_<tenant_id>` automatically.
- Automated dbt can be configured per tenant via `quantyx_dbt_config`.

---

## 9a) Auto-generate dbt scaffolds (draft models)

Triggered automatically after `/onboard/scan-connection` when dbt automation is enabled.
Outputs draft dbt models into:
`dbt_projects/dbt_<tenant_id>/models/auto/`

Draft models must be reviewed before apply.

---

## 10) Metrics suggestions + catalog review + promotion (after facts/dims)

POST /metrics/suggested?domain_id=manufacturing&persist=true

Purpose: generate candidate metrics from scan + ontology and persist them directly to `public.quantyx_metrics_registry`.

Async variant (recommended for large schemas):

POST /metrics/suggested/async?persist=true

Response:
```json
{ "job_id": "job_126", "status": "queued" }
```

Poll:
GET /jobs/{job_id}

Fetch results:
GET /jobs/{job_id}/result

Pending result example (202):
```json
{
  "job_id": "job_126",
  "status": "running",
  "result": null
}
```

Request:
```json
{
  "tenant_id": "tenant_a"
}
```

After async completion, list the catalog:

GET /metrics?tenant_id=tenant_a&domain_id=manufacturing

Note:
- On first run, `/metrics` can be empty before metrics-suggested finishes.

Response (example):
```json
{
  "metrics": [
    {
      "metric_name": "total_sales",
      "type": "sum",
      "sql": "{{ ref('fact_sales') }}.sales_amount",
      "grain": "day",
      "dimensions": ["sales_area_name"],
      "tables": ["fact_sales"],
      "status": "certified"
    }
  ],
  "limit": 200,
  "cursor": null,
  "next_cursor": null
}
```

Review and promote:

PATCH /metrics/{metric_id}

Purpose: promote suggested metrics to certified and fix SQL/dimensions.

Request:
```json
{
  "tenant_id": "tenant_a",
  "domain_id": "manufacturing",
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
  "tenant_id": "tenant_a",
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

## 11) Review summary (all artifacts in one call)

GET /review/summary?tenant_id=tenant_a&domain_id=manufacturing

Purpose: fetch scan results + entities + hierarchies + facts + dimensions + metrics with review status.

Optional review events:

POST /review
```json
{
  "tenant_id": "tenant_a",
  "domain_id": "manufacturing",
  "artifact_type": "facts",
  "artifact_id": "fact_123",
  "status": "reviewed",
  "notes": "Looks good"
}
```

---

## 12) Apply the contracts (reload catalog so the app can use them)

POST /contracts/apply

Purpose: reload the in-memory catalog so new metrics become queryable.

Expected outcome:
- The API instantly recognizes the certified metrics without a code deploy.

---

## 13) Validate schema + explore (confirm the semantic layer is ready)

GET /schema
GET /metrics?tenant_id=tenant_a&domain_id=manufacturing
GET /datasets?domain_id=manufacturing
GET /dimensions?tenant_id=tenant_a&domain_id=manufacturing
GET /dimension-values?dimension=plant_name&limit=50

Expected outcome:
- We confirm the catalog is populated and explore dimension values for UI filters.

---

## 14) Ask a question (first live query to prove value)

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
