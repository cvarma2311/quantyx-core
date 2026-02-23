# Phase Demo: LPG Production + Distribution Onboarding + Ask (What + Why)

Goal: deliver a **demo‑ready** pipeline that:
1) ingests business context for LPG production + distribution,
2) derives facts/dimensions + hierarchies,
3) supports Ask for **What** and **Why** questions.

This plan is scoped for a Tuesday demo. It is not full productization.

---

## 0) Inputs Required (from you)

1) **Business context text**
   - LPG production + distribution process description
   - glossary terms, abbreviations, hierarchy notes
2) **Sample queries**
   - at least 5 “what” questions
   - at least 3 “why/driver” questions
3) **Schema info**
   - actual table list + column list (or sample DDL)
   - expected grain of each fact table

Validated inputs found in repo:
- `artifacts/LPG/LPG_Semantic_Context.md`
- `artifacts/LPG/LPG_SCHEMAS_WITH_DESCRIPTION.json`

---

## 1) Domain Pack + Seed Ontology (Demo Minimal)

Create a demo pack:
`packs/lpg_production_distribution/`
- `ontology.yml`
- `datasets.yml`
- `metric_templates.yml`
- `policies.yml`

Minimum ontology entities/hierarchies (example):
- entities: plant, bottling_unit, depot, distributor, customer, product, cylinder_type
- hierarchies:
  - geography: zone → region → state → district
  - supply_chain: plant → bottling_unit → depot → distributor

**Existing assets used:**
- Phase A pack loader (no new API)

**To implement (if missing):**
- Add pack folder + files

---

## 1.1 Domain Separation (Hard Rule)

- **Production domain** = Plant‑centric operations.
- **Sales/Distribution domain** = Distributor‑centric operations.
- **Never** mix Plant and Distributor in the same semantic object without the bridge table.

Bridge:
- `lpg_distributor_mapping.deliv_plant` → `lpg_plant_operations_masters.sap_id`

---

## 1.2 Source Tables (From Schema File)

Production domain:
- `event_log` (grain: cylinder inspection event)
- `production_log` (grain: accepted cylinder)
- `lpg_plant_operations` (grain: plant × carousel × date)
- `lpg_plant_operations_masters` (plant master)

Sales/Distribution domain:
- `lpg_todays_cdcms_sales_summary`
- `lpg_cdcms_last_three_months_summary`
- `lpg_monthly_cdcms_sales_summary`
- `lpg_cdcms_subsidy_failure_statistics`
- `lpg_distributor_mapping` (bridge + distributor lookup)

---

## 2) Context Ingest + Extraction (Glossary + Hierarchy)

**Use existing APIs (async extraction):**
- `POST /context/ingest`
- `POST /context/extract/async`
- `POST /context/apply`
- `GET /context`

**Data written:**
- `public.quantyx_glossary_terms`
- `public.quantyx_context_extractions`
- `public.quantyx_entity_overrides` (via apply)
- `public.quantyx_hierarchy_overrides` (via apply)

**Outcome:**
Glossary + hierarchies from LPG context are stored and available for Ask.

**Where to check (DB):**
- `public.quantyx_business_context`
- `public.quantyx_context_extractions`
- `public.quantyx_glossary_terms`
- `public.quantyx_entity_overrides`
- `public.quantyx_hierarchy_overrides`
- `public.quantyx_context_scope_active`

---

## 2.1 Hierarchies to Extract (from Context)

Geography hierarchy (shared):
- Zone → Region → Sales Area → State → District → Taluka → City → Distributor/Plant

Production hierarchy:
- Plant → Carousel/System → Filling Head → Cylinder Event

Sales/Distribution hierarchy:
- Distributor → Consumer Segment (PMUY/NPMUY) → Cylinder Type → Order Source → Order Status → Subsidy Failure

Time hierarchy:
- Financial Year → Year → Quarter → Month → Date

Rejection hierarchy (production only):
- Valve Leak → Check Scale → O‑Ring Leak

---

## 3) Schema Scan + Entity Mapping

**Use existing APIs (async):**
- `POST /onboard/scan-connection/async`
- `POST /onboard/map/async` (LLM‑assisted mapping)

**Data written (existing tables):**
- scan results (stored in onboarding tables)
- `quantyx_entity_mappings` (if present)

**Outcome:**
Tables + columns are profiled and mapped to ontology entities.

**Where to check (DB):**
- scan storage tables (if persisted in your deployment)
- `public.quantyx_entity_mappings` (if present)
- `public.quantyx_entity_overrides` (post-apply)

---

## 3.1 Key Join Keys / Entities (from Context)

Production:
- Plant: `lpg_plant_operations_masters.sap_id`
- Carousel/System: `event_log.system_id`, `lpg_plant_operations.system_id`
- Filling head: `event_log.device_id`
- Cylinder: `event_log.cyl_id_no`, `production_log.cyl_id_no`

Sales/Distribution:
- Distributor: `lpg_distributor_mapping.JDEDistributorCode`
- Distributor name: `lpg_distributor_mapping.DistributorName`
- Geography: ZO/RO/SA/State/District/Taluka/City columns

Bridge:
- `lpg_distributor_mapping.deliv_plant` → `lpg_plant_operations_masters.sap_id`

---

## 4) Facts + Dimensions (Demo‑Level)

**Use existing APIs (async):**
- `POST /onboard/infer-models/async`
  - generates candidate facts/dimensions from schema + context

**To implement for demo (if not wired end‑to‑end):**
- Persist facts/dimensions to registry tables or contracts.
- Ensure `/datasets` and `/dimensions` expose them.

**Outcome:**
Ask can refer to canonical facts/dimensions.

**Where to check (DB):**
- `public.quantyx_facts_registry` (if implemented)
- `public.quantyx_dimensions_registry` (if implemented)

---

## 4.1 Demo Fact/DIM Candidates

Production facts:
- `fact_lpg_production_daily` (from `lpg_plant_operations`)
- `fact_lpg_rejections_daily` (from `lpg_plant_operations` + `event_log`)

Production dimensions:
- `dim_plant` (from `lpg_plant_operations_masters`)
- `dim_carousel` (from `system_id`)
- `dim_filling_head` (from `device_id`)

Sales facts:
- `fact_lpg_sales_daily` (from `lpg_todays_cdcms_sales_summary`)
- `fact_lpg_sales_monthly` (from `lpg_monthly_cdcms_sales_summary`)
- `fact_lpg_subsidy_failures` (from `lpg_cdcms_subsidy_failure_statistics`)

Sales dimensions:
- `dim_distributor` (from `lpg_distributor_mapping`)
- `dim_geography` (from zone/region/sales area/state/district)

---

## 5) Metrics (Demo‑Level)

**Use existing APIs (async):**
- `POST /metrics/suggested/async`
- `POST /metrics`
- `PATCH /metrics/{id}`
- `POST /contracts/apply`

**Outcome:**
Metrics are available in `quantyx_metrics_registry` and can be used by Ask.

**Where to check (DB):**
- `public.quantyx_metrics_registry`

---

## 5.1 LPG Demo Metrics (from Context)

Production:
- Total production (MT) =
  `(production_14_2kg × 14.2 + production_19kg × 19) / 1000`
- Total production (lakh cylinders) =
  `(production_14_2kg + production_19kg) / 100000`
- Productivity (Cyl/Hour) =
  `total_production / total_net_hours`
- Rejection rate by type =
  `(handled - sortout) / handled × 100`

Sales/Distribution:
- Bookings today / yesterday
- Pending buckets (0D .. Beyond15D)
- Total sales today / yesterday
- Subsidy failure counts by error code

---

## 6) Ask for “What” (Phase AB)

**Use existing API:**
- `POST /query`

**To implement (short‑term demo constraints):**
- Enforce `tenant_id + question` only (reject other fields).
- Semantic parsing + binding using:
  - glossary + ontology + metrics registry + dataset contracts

**Outcome:**
Ask answers “what” questions for LPG domain.

**Where to check (DB):**
- `public.quantyx_query_audit`

---

## 6.1 Demo “What” Questions (Production)

- What is total LPG production (MT) by plant last week?
- Which plants have the highest valve leak rejection rate this month?
- What is productivity (Cyl/Hour) by plant and carousel for a given date?
- How much production came from overtime hours yesterday?
- What is the share of 14.2kg vs 19kg cylinders by plant?

## 6.2 Demo “What” Questions (Sales/Distribution)

- What are today’s total sales by distributor?
- Which sales areas have the highest pending orders beyond 15 days?
- What is monthly sales trend by zone for FY 2024–2025?
- Which distributors have the highest subsidy failure counts?
- What is PMUY vs NPMUY booking split by region?

---

## 7) Ask for “Why” (Driver Analysis, Phase AC Demo)

**Short‑term demo implementation:**
- Add driver analysis operator (simple baseline comparison).
- Use a **default time window** if not specified.
- Use **configured driver dimensions** per metric.

**Outcome:**
Ask answers “why” questions with ranked drivers (even if simple).

**Where to check (DB):**
- `public.quantyx_query_audit`
- `public.quantyx_insight_events` (if persisted)

---

## 7.1 Demo “Why/Driver” Questions

Production:
- Why is production down this week at a given plant?
- Which rejection type is driving the productivity drop?

Sales/Distribution:
- Why are sales down last week in a given sales area?
- What are the top drivers of pending orders beyond 15 days?

---

## 8) Demo Script (End‑to‑End)

Create a demo script (or extend `onboarding_demo.py`) that:
1) loads context
2) runs context extract + apply
3) runs scan + map + infer models
4) suggests + applies metrics
5) runs Ask for “what” + “why” questions

---

## API Checklist (Existing vs To Implement)

Existing (can use now):
- `/context/ingest`, `/context/extract`, `/context/apply`
- `/onboard/scan-connection/async`, `/onboard/map/async`, `/onboard/infer-models/async`
- `/metrics/suggested/async`, `/metrics`, `/contracts/apply`
- `/query`

To implement for demo:
- Ask restriction to **question + tenant_id only**
- Semantic binding pipeline (Phase AB)
- Driver analysis operator (Phase AC)
- Optional: pack files for LPG domain

---

## 9) Open Questions / Gaps for Demo

1) **Default time window** for “last week / last month” in Ask.
2) **Driver dimension set** per metric (configure in registry metadata).
3) **Plant vs Distributor scope**: enforce no cross‑domain joins unless via bridge.
4) **Hierarchy selection**: which hierarchies should be active for the demo?
5) **Production vs Sales defaults** when the question uses generic “sales/production”.

---

## 10) Ready-to-Run Payloads (LPG Demo)

These payloads use the schema tables from:
- `artifacts/LPG/LPG_SCHEMAS_WITH_DESCRIPTION.json`
and the context from:
- `artifacts/LPG/LPG_Semantic_Context.md`

### 10.1 Context Ingest
`POST /context/ingest`
```json
{
  "tenant_id": "tenant_lpg",
  "domain_id": "lpg_production_distribution",
  "source_type": "business_context",
  "source_title": "LPG Semantic Context v2",
  "raw_text": "<PASTE_LPG_SEMANTIC_CONTEXT_MD>",
  "metadata": {
    "connection_id": "conn_lpg",
    "database": "prod_warehouse",
    "schema": "public",
    "tables": [
      "event_log",
      "production_log",
      "lpg_plant_operations",
      "lpg_plant_operations_masters",
      "lpg_distributor_mapping",
      "lpg_todays_cdcms_sales_summary",
      "lpg_cdcms_last_three_months_summary",
      "lpg_monthly_cdcms_sales_summary",
      "lpg_cdcms_subsidy_failure_statistics"
    ]
  }
}
```

### 10.2 Context Extract (async)
`POST /context/extract/async`
```json
{
  "tenant_id": "tenant_lpg",
  "domain_id": "lpg_production_distribution",
  "context_id": "ctx_123",
  "extraction_types": [
    "abbreviations",
    "synonyms",
    "hierarchies",
    "metric_candidates",
    "question_intents"
  ],
  "mode": "parallel",
  "model": "gpt-4o-mini"
}
```
Poll:
- `GET /jobs/{job_id}`
- `GET /jobs/{job_id}/result`

### 10.3 Context Apply (all hierarchies, async)
`POST /context/apply/async`
```json
{
  "tenant_id": "tenant_lpg",
  "domain_id": "lpg_production_distribution",
  "extraction_id": "ext_123",
  "apply": {
    "entities": true,
    "hierarchies": true,
    "glossary": true,
    "metrics": true
  }
}
```

Poll:
- `GET /jobs/{job_id}`
- `GET /jobs/{job_id}/result`

### 10.4 Context Apply (select hierarchies, async)
`POST /context/apply/async`
```json
{
  "tenant_id": "tenant_lpg",
  "domain_id": "lpg_production_distribution",
  "extraction_id": "ext_123",
  "apply": {
    "entities": true,
    "hierarchies": true,
    "glossary": true,
    "metrics": true
  },
  "hierarchy_selection": {
    "names": ["geography", "supply_chain", "production", "sales_distribution"],
    "apply_all": false
  }
}
```

### 10.5 Activate Context(s)
`PATCH /context/{context_id}?tenant_id=tenant_lpg`
```json
{ "status": "active" }
```

### 10.6 Scan Connection (all LPG tables, async)
`POST /onboard/scan-connection/async?generate_dbt=false`
```json
{
  "tenant_id": "tenant_lpg",
  "domain_id": "lpg_production_distribution",
  "connections": [
    {
      "connection_id": "conn_lpg",
      "db_type": "postgres",
      "host": "YOUR_DB_HOST",
      "port": 5432,
      "user": "YOUR_DB_USER",
      "password": "YOUR_DB_PASSWORD",
      "sample_rows": 100,
      "databases": [
        {
          "name": "prod_warehouse",
          "schemas": [
            {
              "name": "public",
              "tables": [
                "event_log",
                "production_log",
                "lpg_plant_operations",
                "lpg_plant_operations_masters",
                "lpg_distributor_mapping",
                "lpg_todays_cdcms_sales_summary",
                "lpg_cdcms_last_three_months_summary",
                "lpg_monthly_cdcms_sales_summary",
                "lpg_cdcms_subsidy_failure_statistics"
              ],
              "limit": 20
            }
          ]
        }
      ]
    }
  ]
}
```

Poll:
- `GET /jobs/{job_id}`
- `GET /jobs/{job_id}/result`

### 10.7 Entity Mapping (LLM-assisted, async)
`POST /onboard/map/async?tenant_id=tenant_lpg&domain_id=lpg_production_distribution&use_llm=true`
```json
{
  "connection_id": "conn_lpg",
  "database": "prod_warehouse",
  "schema": "public",
  "tables": [
    "event_log",
    "production_log",
    "lpg_plant_operations",
    "lpg_plant_operations_masters",
    "lpg_distributor_mapping",
    "lpg_todays_cdcms_sales_summary",
    "lpg_cdcms_last_three_months_summary",
    "lpg_monthly_cdcms_sales_summary",
    "lpg_cdcms_subsidy_failure_statistics"
  ]
}
```

Poll:
- `GET /jobs/{job_id}`
- `GET /jobs/{job_id}/result`

### 10.8 Infer Facts + Dimensions (async)
`POST /onboard/infer-models/async?tenant_id=tenant_lpg&domain_id=lpg_production_distribution`
```json
{
  "connection_id": "conn_lpg",
  "database": "prod_warehouse",
  "schema": "public",
  "tables": [
    "event_log",
    "production_log",
    "lpg_plant_operations",
    "lpg_plant_operations_masters",
    "lpg_distributor_mapping",
    "lpg_todays_cdcms_sales_summary",
    "lpg_cdcms_last_three_months_summary",
    "lpg_monthly_cdcms_sales_summary",
    "lpg_cdcms_subsidy_failure_statistics"
  ],
  "use_llm": true
}
```

Poll:
- `GET /jobs/{job_id}`
- `GET /jobs/{job_id}/result`

### 10.9 Suggest Metrics (persist, async)
`POST /metrics/suggested/async?tenant_id=tenant_lpg&domain_id=lpg_production_distribution&persist=true`
```json
{
  "connection_id": "conn_lpg",
  "database": "prod_warehouse",
  "schema": "public",
  "tables": [
    "lpg_plant_operations",
    "lpg_todays_cdcms_sales_summary",
    "lpg_monthly_cdcms_sales_summary",
    "lpg_cdcms_subsidy_failure_statistics"
  ]
}
```

### 10.10 Ask “What”
`POST /query`
```json
{
  "tenant_id": "tenant_lpg",
  "question": "What is total LPG production (MT) by plant last week?"
}
```

### 10.11 Ask “Why”
`POST /query`
```json
{
  "tenant_id": "tenant_lpg",
  "question": "Why is production down last week at Secunderabad plant?"
}
```

---

### 10.12 End-to-End cURL Script (Local)

Save as `scripts/demo_lpg_end_to_end.sh` and run with your DB/env values.

```bash
#!/usr/bin/env bash
set -euo pipefail

API_BASE="${QUANTYX_API_BASE:-http://127.0.0.1:8787}"
TENANT_ID="${QUANTYX_TENANT:-tenant_lpg}"
DOMAIN_ID="${QUANTYX_DOMAIN:-lpg_production_distribution}"
CONNECTION_ID="${DEMO_CONNECTION_ID:-conn_lpg}"
DB_HOST="${DEMO_DB_HOST:-127.0.0.1}"
DB_PORT="${DEMO_DB_PORT:-5432}"
DB_NAME="${DEMO_DB_NAME:-prod_warehouse}"
DB_USER="${DEMO_DB_USER:-readonly_user}"
DB_PASSWORD="${DEMO_DB_PASSWORD:-password}"
DB_SCHEMA="${DEMO_DB_SCHEMA:-public}"

CTX_TEXT="$(cat artifacts/LPG/LPG_Semantic_Context.md)"

echo "1) Context ingest"
CTX_ID=$(curl -sS -X POST "$API_BASE/context/ingest" \
  -H "Content-Type: application/json" \
  -d "{
    \"tenant_id\": \"$TENANT_ID\",
    \"domain_id\": \"$DOMAIN_ID\",
    \"source_type\": \"business_context\",
    \"source_title\": \"LPG Semantic Context v2\",
    \"raw_text\": $(python3 - <<'PY'
import json,sys,os
print(json.dumps(os.environ['CTX_TEXT']))
PY
),
    \"metadata\": {
      \"connection_id\": \"$CONNECTION_ID\",
      \"database\": \"$DB_NAME\",
      \"schema\": \"$DB_SCHEMA\",
      \"tables\": [
        \"event_log\",
        \"production_log\",
        \"lpg_plant_operations\",
        \"lpg_plant_operations_masters\",
        \"lpg_distributor_mapping\",
        \"lpg_todays_cdcms_sales_summary\",
        \"lpg_cdcms_last_three_months_summary\",
        \"lpg_monthly_cdcms_sales_summary\",
        \"lpg_cdcms_subsidy_failure_statistics\"
      ]
    }
  }" | python3 - <<'PY'
import json,sys
print(json.load(sys.stdin)["context_id"])
PY)

echo "2) Context extract"
EXT_ID=$(curl -sS -X POST "$API_BASE/context/extract" \
  -H "Content-Type: application/json" \
  -d "{
    \"tenant_id\": \"$TENANT_ID\",
    \"domain_id\": \"$DOMAIN_ID\",
    \"context_id\": \"$CTX_ID\",
    \"extraction_types\": [\"abbreviations\",\"synonyms\",\"hierarchies\",\"metric_candidates\",\"question_intents\"],
    \"model\": \"gpt-4o-mini\"
  }" | python3 - <<'PY'
import json,sys
print(json.load(sys.stdin)["extraction_id"])
PY)

echo "3) Context apply"
curl -sS -X POST "$API_BASE/context/apply" \
  -H "Content-Type: application/json" \
  -d "{
    \"tenant_id\": \"$TENANT_ID\",
    \"domain_id\": \"$DOMAIN_ID\",
    \"extraction_id\": \"$EXT_ID\",
    \"apply\": {\"entities\": true, \"hierarchies\": true, \"glossary\": true, \"metrics\": true}
  }" | cat

echo "4) Scan connection"
curl -sS -X POST "$API_BASE/onboard/scan-connection" \
  -H "Content-Type: application/json" \
  -d "{
    \"tenant_id\": \"$TENANT_ID\",
    \"domain_id\": \"$DOMAIN_ID\",
    \"connections\": [
      {
        \"connection_id\": \"$CONNECTION_ID\",
        \"db_type\": \"postgres\",
        \"host\": \"$DB_HOST\",
        \"port\": $DB_PORT,
        \"user\": \"$DB_USER\",
        \"password\": \"$DB_PASSWORD\",
        \"sample_rows\": 100,
        \"databases\": [
          {
            \"name\": \"$DB_NAME\",
            \"schemas\": [
              {
                \"name\": \"$DB_SCHEMA\",
                \"tables\": [
                  \"event_log\",
                  \"production_log\",
                  \"lpg_plant_operations\",
                  \"lpg_plant_operations_masters\",
                  \"lpg_distributor_mapping\",
                  \"lpg_todays_cdcms_sales_summary\",
                  \"lpg_cdcms_last_three_months_summary\",
                  \"lpg_monthly_cdcms_sales_summary\",
                  \"lpg_cdcms_subsidy_failure_statistics\"
                ],
                \"limit\": 20
              }
            ]
          }
        ]
      }
    ]
  }" | cat

echo "5) Entity mapping"
curl -sS -X POST "$API_BASE/onboard/map?tenant_id=$TENANT_ID&domain_id=$DOMAIN_ID&use_llm=true" \
  -H "Content-Type: application/json" \
  -d "{
    \"connection_id\": \"$CONNECTION_ID\",
    \"database\": \"$DB_NAME\",
    \"schema\": \"$DB_SCHEMA\",
    \"tables\": [
      \"event_log\",
      \"production_log\",
      \"lpg_plant_operations\",
      \"lpg_plant_operations_masters\",
      \"lpg_distributor_mapping\",
      \"lpg_todays_cdcms_sales_summary\",
      \"lpg_cdcms_last_three_months_summary\",
      \"lpg_monthly_cdcms_sales_summary\",
      \"lpg_cdcms_subsidy_failure_statistics\"
    ]
  }" | cat

echo "6) Infer models"
curl -sS -X POST "$API_BASE/onboard/infer-models?tenant_id=$TENANT_ID&domain_id=$DOMAIN_ID" \
  -H "Content-Type: application/json" \
  -d "{
    \"connection_id\": \"$CONNECTION_ID\",
    \"database\": \"$DB_NAME\",
    \"schema\": \"$DB_SCHEMA\",
    \"tables\": [
      \"event_log\",
      \"production_log\",
      \"lpg_plant_operations\",
      \"lpg_plant_operations_masters\",
      \"lpg_distributor_mapping\",
      \"lpg_todays_cdcms_sales_summary\",
      \"lpg_cdcms_last_three_months_summary\",
      \"lpg_monthly_cdcms_sales_summary\",
      \"lpg_cdcms_subsidy_failure_statistics\"
    ],
    \"use_llm\": true
  }" | cat

echo "7) Suggested metrics (persist)"
curl -sS -X POST "$API_BASE/metrics/suggested?tenant_id=$TENANT_ID&domain_id=$DOMAIN_ID&persist=true" \
  -H "Content-Type: application/json" \
  -d "{
    \"connection_id\": \"$CONNECTION_ID\",
    \"database\": \"$DB_NAME\",
    \"schema\": \"$DB_SCHEMA\",
    \"tables\": [
      \"lpg_plant_operations\",
      \"lpg_todays_cdcms_sales_summary\",
      \"lpg_monthly_cdcms_sales_summary\",
      \"lpg_cdcms_subsidy_failure_statistics\"
    ]
  }" | cat

echo "8) Ask - What"
curl -sS -X POST "$API_BASE/query" \
  -H "Content-Type: application/json" \
  -d "{
    \"tenant_id\": \"$TENANT_ID\",
    \"question\": \"What is total LPG production (MT) by plant last week?\"
  }" | cat

echo "9) Ask - Why"
curl -sS -X POST "$API_BASE/query" \
  -H "Content-Type: application/json" \
  -d "{
    \"tenant_id\": \"$TENANT_ID\",
    \"question\": \"Why is production down last week at Secunderabad plant?\"
  }" | cat
```

---

### 10.13 Quick Smoke Test (Context → Ask)

```bash
#!/usr/bin/env bash
set -euo pipefail

API_BASE="${QUANTYX_API_BASE:-http://127.0.0.1:8787}"
TENANT_ID="${QUANTYX_TENANT:-tenant_lpg}"
DOMAIN_ID="${QUANTYX_DOMAIN:-lpg_production_distribution}"

CTX_TEXT="$(cat artifacts/LPG/LPG_Semantic_Context.md)"

CTX_ID=$(curl -sS -X POST "$API_BASE/context/ingest" \
  -H "Content-Type: application/json" \
  -d "{
    \"tenant_id\": \"$TENANT_ID\",
    \"domain_id\": \"$DOMAIN_ID\",
    \"source_type\": \"business_context\",
    \"source_title\": \"LPG Semantic Context v2\",
    \"raw_text\": $(python3 - <<'PY'
import json,sys,os
print(json.dumps(os.environ['CTX_TEXT']))
PY
)
  }" | python3 - <<'PY'
import json,sys
print(json.load(sys.stdin)["context_id"])
PY)

EXT_ID=$(curl -sS -X POST "$API_BASE/context/extract" \
  -H "Content-Type: application/json" \
  -d "{
    \"tenant_id\": \"$TENANT_ID\",
    \"domain_id\": \"$DOMAIN_ID\",
    \"context_id\": \"$CTX_ID\",
    \"extraction_types\": [\"abbreviations\",\"synonyms\",\"hierarchies\",\"metric_candidates\",\"question_intents\"],
    \"model\": \"gpt-4o-mini\"
  }" | python3 - <<'PY'
import json,sys
print(json.load(sys.stdin)["extraction_id"])
PY)

curl -sS -X POST "$API_BASE/context/apply" \
  -H "Content-Type: application/json" \
  -d "{
    \"tenant_id\": \"$TENANT_ID\",
    \"domain_id\": \"$DOMAIN_ID\",
    \"extraction_id\": \"$EXT_ID\",
    \"apply\": {\"entities\": true, \"hierarchies\": true, \"glossary\": true, \"metrics\": true}
  }" | cat

curl -sS -X POST "$API_BASE/query" \
  -H "Content-Type: application/json" \
  -d "{
    \"tenant_id\": \"$TENANT_ID\",
    \"question\": \"What is total LPG production (MT) by plant last week?\"
  }" | cat
```

---

### 10.14 Quick Smoke Test (Context → Ask Why)

```bash
#!/usr/bin/env bash
set -euo pipefail

API_BASE="${QUANTYX_API_BASE:-http://127.0.0.1:8787}"
TENANT_ID="${QUANTYX_TENANT:-tenant_lpg}"
DOMAIN_ID="${QUANTYX_DOMAIN:-lpg_production_distribution}"

CTX_TEXT="$(cat artifacts/LPG/LPG_Semantic_Context.md)"

CTX_ID=$(curl -sS -X POST "$API_BASE/context/ingest" \
  -H "Content-Type: application/json" \
  -d "{
    \"tenant_id\": \"$TENANT_ID\",
    \"domain_id\": \"$DOMAIN_ID\",
    \"source_type\": \"business_context\",
    \"source_title\": \"LPG Semantic Context v2\",
    \"raw_text\": $(python3 - <<'PY'
import json,sys,os
print(json.dumps(os.environ['CTX_TEXT']))
PY
)
  }" | python3 - <<'PY'
import json,sys
print(json.load(sys.stdin)["context_id"])
PY)

EXT_ID=$(curl -sS -X POST "$API_BASE/context/extract" \
  -H "Content-Type: application/json" \
  -d "{
    \"tenant_id\": \"$TENANT_ID\",
    \"domain_id\": \"$DOMAIN_ID\",
    \"context_id\": \"$CTX_ID\",
    \"extraction_types\": [\"abbreviations\",\"synonyms\",\"hierarchies\",\"metric_candidates\",\"question_intents\"],
    \"model\": \"gpt-4o-mini\"
  }" | python3 - <<'PY'
import json,sys
print(json.load(sys.stdin)["extraction_id"])
PY)

curl -sS -X POST "$API_BASE/context/apply" \
  -H "Content-Type: application/json" \
  -d "{
    \"tenant_id\": \"$TENANT_ID\",
    \"domain_id\": \"$DOMAIN_ID\",
    \"extraction_id\": \"$EXT_ID\",
    \"apply\": {\"entities\": true, \"hierarchies\": true, \"glossary\": true, \"metrics\": true}
  }" | cat

curl -sS -X POST "$API_BASE/query" \
  -H "Content-Type: application/json" \
  -d "{
    \"tenant_id\": \"$TENANT_ID\",
    \"question\": \"Why is production down last week at Secunderabad plant?\"
  }" | cat
```

---

## Success Criteria for Tuesday Demo

- Context ingestion + extraction produces LPG glossary + hierarchies.
- Facts/dimensions + metrics are discoverable and used in Ask.
- Ask answers at least 5 “what” questions end‑to‑end.
- Ask answers at least 3 “why/driver” questions with ranked drivers.
