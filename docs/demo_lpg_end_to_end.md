# LPG Demo End-to-End Runner

This doc mirrors the current behavior of `scripts/demo_lpg_end_to_end.py`.

## What It Does

Runs a full LPG onboarding + analytics flow:
1. Context ingest
2. Context extract (async)
3. Scan connection (async)
4. Context apply (async)
5. Entity mapping (async)
6. Infer models (async)
7. Metrics suggestion (async)
8. Create fact views + register inferred facts (certified)
9. Register inferred dimensions (certified)
10. Create derived metric `production_mt`
11. Certify glossary/entities/hierarchies/facts/dimensions/metrics
12. Reload contracts/catalog
13. Ask “what” and “why” questions

Every step logs the IDs for that step and includes previous step IDs in the log.

## Environment Variables

These are used by the script (see `.env.example` for the full list):

```
QUANTYX_API_BASE=http://127.0.0.1:8787
QUANTYX_DOMAIN=lpg_production_distribution
DEMO_CONNECTION_ID=conn_lpg

DEMO_DB_HOST=127.0.0.1
DEMO_DB_PORT=5432
DEMO_DB_NAME=prod_warehouse
DEMO_DB_USER=readonly_user
DEMO_DB_PASSWORD=password
DEMO_DB_SCHEMA=public

OPENAI_MODEL=gpt-4o-mini
JOB_TIMEOUT_SEC=12000
JOB_POLL_SEC=4
AGENTIC_CHART_RERANK_MODE=auto
AGENTIC_METRIC_RERANK_MODE=auto

RESUME_CONTEXT_ID=
RESUME_EXTRACTION_ID=
RESUME_INFER_JOB_ID=
RESUME_METRICS_JOB_ID=

OPENAI_API_KEY=
```

## Run From Start

```
python3 scripts/demo_lpg_end_to_end.py
```

## Resume From a Phase

Use `--resume-from` to skip earlier phases. If you skip `ingest`, set `RESUME_CONTEXT_ID`. If you skip `extract`, set `RESUME_EXTRACTION_ID`.

By default, the script will auto-resume by querying existing context and completed jobs for the tenant (no env vars needed). Disable this with `--no-auto-resume`.

```
RESUME_CONTEXT_ID=ctx_... \
RESUME_EXTRACTION_ID=ext_... \
python3 scripts/demo_lpg_end_to_end.py --resume-from metrics
```

Valid phases:

```
start
ingest
extract
scan
apply
map
infer
metrics
ask
```

## Skip Metrics Generation

If async metrics have already been generated, skip the expensive step:

```
python3 scripts/demo_lpg_end_to_end.py --resume-from infer --skip-metrics
```

You can optionally set `RESUME_METRICS_JOB_ID` for logging.

## Resume Infer Without Re-running It

If you already have a completed infer job, reuse it:

```
RESUME_CONTEXT_ID=ctx_... \
RESUME_EXTRACTION_ID=ext_... \
RESUME_INFER_JOB_ID=job_... \
python3 scripts/demo_lpg_end_to_end.py --resume-from infer --skip-metrics
```

## Fact Views

For each inferred fact, a DB view is created:

```
fact_<source_table>
```

These are created with:
```
CREATE OR REPLACE VIEW <schema>.fact_<source_table> AS
SELECT * FROM <schema>.<source_table>
```

Each view is registered in `public.quantyx_fact_views_registry`.

## Derived Metric: Production (MT)

`production_mt` is created as:

```
({{ ref('fact_lpg_plant_operations') }}.production_14_2kg * 14.2
 + {{ ref('fact_lpg_plant_operations') }}.production_19kg * 19) / 1000
```

The script validates that `{{ ref('fact_*') }}` is present before POSTing.

## Notes

- Dimensions are registered as certified metadata. If you need physical dimension views, add them explicitly.
- If a run fails after creating views, you can safely resume without purging because views are created with `CREATE OR REPLACE VIEW` and registry inserts are idempotent.

## API → Storage Tables (Postgres)

This is where each API in the demo persists data:

- `POST /context/ingest`
  - `public.quantyx_business_context`
- `POST /context/extract/async` (job result writes extraction)
  - `public.quantyx_jobs`
  - `public.quantyx_context_extractions`
  - `public.quantyx_context_extraction_agents` (if multi-agent)
- `POST /context/apply/async`
  - `public.quantyx_jobs`
  - `public.quantyx_entity_overrides`
  - `public.quantyx_hierarchy_overrides`
  - `public.quantyx_glossary_terms`
- `PATCH /hierarchies` (payload-based hierarchy update)
  - `public.quantyx_hierarchy_overrides`
- `POST /onboard/scan-connection/async`
  - `public.quantyx_jobs`
  - `public.quantyx_schema_scans`
- `POST /onboard/map/async`
  - `public.quantyx_jobs`
  - `public.quantyx_entity_mappings`
  - `public.quantyx_entity_mapping_agents` (if multi-agent)
- `POST /onboard/infer-models/async`
  - `public.quantyx_jobs`
  - `public.quantyx_facts_registry`
  - `public.quantyx_dimensions_registry`
- `POST /metrics/suggested/async`
  - `public.quantyx_jobs`
  - `public.quantyx_metrics_registry`
- `POST /facts`
  - `public.quantyx_facts_registry`
- `POST /dimensions`
  - `public.quantyx_dimensions_registry`
- `POST /metrics`
  - `public.quantyx_metrics_registry`
- `POST /glossary/certify`
  - `public.quantyx_glossary_terms`
- `POST /tenant/domain`
  - `public.quantyx_tenant_domains`
- `POST /tenant/scope`
  - `public.quantyx_tenant_scopes`
