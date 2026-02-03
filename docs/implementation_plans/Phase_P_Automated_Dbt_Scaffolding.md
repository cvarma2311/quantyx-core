# Phase P: Automated dbt Scaffolding (LLM-Assisted, Human Review)

Goal: automatically generate dbt model scaffolding from scan + context to
bootstrap tenant projects, while requiring explicit human review and correction
before any model is trusted for production use.

This phase builds an end-to-end pipeline that:
- infers candidate facts/dims,
- generates dbt SQL + schema.yml stubs using LLM,
- writes them to tenant-specific dbt project directories, and
- exposes review/update/apply APIs for human oversight.

---

## 1) Inputs

Required inputs:
- Schema scan results from `/onboard/scan-connection`
- Connection scope (tenant_id, domain_id, connection_id, database, schema, tables[])

Optional inputs:
- Business context from `/context/ingest` (glossary, hierarchies, abbreviations)
- LLM model name (defaults to `OPENAI_MODEL`)

---

## 2) Output location (per tenant)

Generated dbt assets are written to:

`dbt_projects/dbt-<tenant_id>/models/auto/`

Files:
- `models/auto/fact_<name>.sql`
- `models/auto/dim_<name>.sql`
- `models/auto/schema.yml` (sources, columns, tests, descriptions)

All outputs are marked **draft** until reviewed.

---

## 3) Execution flow (automated)

### 3.1 Scan + infer
1) `/onboard/scan-connection` collects table profiles.
2) `/onboard/infer-models` produces candidate facts/dims.
3) Context terms (abbreviations/synonyms/hierarchies) are loaded if present.

### 3.2 LLM scaffold generation
- For each candidate fact/dim:
  - Generate dbt SQL and YAML metadata (column descriptions, tests)
  - Suggest primary keys, grain, and join keys
  - Emit a review checklist per model

### 3.3 Persist artifacts
- Write generated SQL + YAML to tenant dbt project path.
- Store a structured copy in DB for review/edit.

---

## 4) API additions

### 4.1 Generate scaffolding (automatic)
Triggered automatically after `/onboard/scan-connection`.

Optional query flag:
`?generate_dbt=true|false` (default true)

### 4.2 Manual trigger

`POST /dbt/scaffold`

Request:
```json
{
  "tenant_id": "tenant_a",
  "domain_id": "manufacturing",
  "connection_id": "conn_prod",
  "database": "prod_warehouse",
  "schema": "public",
  "tables": ["fact_sales", "dim_customer"],
  "context_id": "ctx_123",
  "model": "gpt-4o-mini"
}
```

Response:
```json
{
  "status": "generated",
  "scaffold_id": "scaffold_123",
  "models": [
    {"name": "fact_sales", "path": "models/auto/fact_sales.sql", "status": "draft"},
    {"name": "dim_customer", "path": "models/auto/dim_customer.sql", "status": "draft"}
  ]
}
```

### 4.3 List scaffolds

`GET /dbt/scaffold?tenant_id=...&domain_id=...`

Returns generated models + status (draft/reviewed/applied).

### 4.4 Review/update scaffold

`PATCH /dbt/scaffold/{scaffold_id}`

Fields:
- `status`: draft → reviewed → applied
- `notes`: review comments
- `sql` or `schema_yaml` edits

### 4.5 Apply scaffold

`POST /dbt/scaffold/{scaffold_id}/apply`

Writes reviewed content into the tenant dbt project and re-runs compile.

---

## 5) Human review gates

- All generated models start with `status = "draft"`.
- `dbt compile` runs but outputs are marked `draft` in metadata.
- Only after manual review (`PATCH` → status=reviewed) can the scaffold be applied.
- `apply` step records reviewer and timestamp.

---

## 6) Database changes

New table: `public.quantyx_dbt_scaffolds`

Columns:
- scaffold_id (PK)
- tenant_id
- domain_id
- connection_id
- database
- schema
- tables (jsonb)
- context_id (optional)
- status (draft/reviewed/applied)
- payload (jsonb: models + yaml + review checklist)
- created_at, updated_at

---

## 7) Acceptance criteria

- Scan triggers auto-scaffold generation into tenant dbt project.
- Generated models are stored in DB and written to disk.
- All outputs are marked `draft` until explicitly reviewed.
- Review/update/apply APIs function end-to-end.
- `/dbt/manifest/generate` uses reviewed models only.

---

## 8) Risks / guardrails

- LLM output may be incorrect → enforce review.
- Joins and grains must be validated by humans.
- Do not auto-run dbt `run` for generated models.
*** End Patch다면 code its correct? and update phase readme? Wait I added not update README. need update README to include Phase P. We'll patch. Also need update to include in docs? user asked "Once md file is written and implemented we need to have onboarding_demo.py updated with this flow added and also all the documentation is updated along wiht ht eswagger, request and responses" They asked to draft complete details phase P in documentation; we should create md. But also update README to include Phase P. Let's patch README. Don't implement yet? The user asked to draft phase P. We should update phase README listing and maybe mention? We'll update docs/implementation_plans/README.md. Let's patch. We'll add Phase P after O. Also update maybe V2_API? But user asked now only draft doc. We'll do minimal now? Let's obey: "draft complete end to end details of phase p in documentation" - done. Might update README. Let's patch. We'll use apply_patch. We'll also not implement. We'll respond with doc created and updated list. Let's patch README. We'll do apply_patch. We'll ensure proper patch. Let's proceed. 
