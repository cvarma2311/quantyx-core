# Phase N: Connection-Scoped Onboarding + Multi-Context Apply

Goal: make onboarding fully connection-scoped and allow multiple business contexts
per connection/schema/tables, with extraction results segregated and applied only
when explicitly requested.

---

## 1) Scope model (required everywhere)

Every onboarding step must be bound to a specific scope:
- connection_id
- database
- schema
- tables[]

If multiple connections exist and scope is missing, return 400 with guidance.

---

## 2) Multiple context entries (same scope allowed)

Users can submit multiple contexts for the same scope.
Each context yields its own context_id and extraction run(s).

### 2.0 Context naming (required)
- Each context must have a short, human-friendly name.
- If the user provides a name/title, use it.
- If missing, auto-generate a concise name derived from the content or metadata
  (e.g., first 6–10 words of raw_text, normalized, max 80 chars).
- Store the resolved name in source_title for consistent display in lists.

### 2.1 POST /context/ingest (required scope in metadata)
Request (example):
```json
{
  "tenant_id": "tenant_a",
  "domain_id": "manufacturing",
  "source_type": "business_context",
  "source_title": "Ops glossary v1",
  "raw_text": "SBU = Strategic Business Unit...",
  "metadata": {
    "connection_id": "conn_prod",
    "database": "prod_warehouse",
    "schema": "public",
    "tables": ["fact_production_daily", "dim_plant"]
  }
}
```

### 2.2 POST /context/ingest-file (required scope in metadata)
metadata (JSON string) must include connection scope.

---

## 3) Segregated extraction outcomes

### 3.1 POST /context/extract
- Uses a single context_id.
- Persist one row per extraction run in quantyx_context_extractions:
  - extraction_type = "combined"
  - payload contains hierarchies/synonyms/abbreviations/etc.

### 3.2 GET /context (list)
- Add optional filters: connection_id, database, schema.
- Include extraction_types list by aggregating quantyx_context_extractions
  per context_id.

---

## 4) Apply-only persistence (ontology + hierarchy)

Persist extracted artifacts only when user calls /context/apply.

### 4.1 POST /context/apply (hierarchies)
- Read extraction payload (combined)
- For each extracted hierarchy:
  - Upsert into quantyx_hierarchy_overrides
  - Set source_context_id

### 4.2 POST /context/apply (glossary + entities)
- Upsert glossary terms into quantyx_glossary_terms (source_context_id)
- Upsert entity overrides into quantyx_entity_overrides (source_context_id)

---

## 5) Connection-scoped onboarding APIs

Require scope for:
- POST /onboard/map
- POST /onboard/infer-models
- POST /metrics/suggested
- POST /metrics, PATCH /metrics/{id}
- POST /query

Optional scope filters for:
- GET /schema
- GET /datasets
- GET /dimensions
- GET /dimension-values

---

## 6) Database changes (SQL)

Add traceability for applied ontology artifacts:
```sql
ALTER TABLE public.quantyx_entity_overrides
  ADD COLUMN IF NOT EXISTS source_context_id TEXT NULL;

ALTER TABLE public.quantyx_hierarchy_overrides
  ADD COLUMN IF NOT EXISTS source_context_id TEXT NULL;
```

Apply via:
- `artifacts/quantyx_tables_updates.sql`
- `scripts/create_quantyx_tables.sh`

---

## 7) Acceptance criteria

- Multiple contexts for the same connection scope are accepted.
- Extraction results are segregated by context_id.
- /context list returns extraction_types per context.
- Applying one context only updates ontology/hierarchy rows tied to that context.
- Applied hierarchy/entity/glossary rows are traceable via source_context_id.
- Contexts always have a short name (user-provided or auto-generated).

---

## 8) Update endpoints (PATCH/PUT)

Every onboarding artifact must be updatable via PATCH/PUT:

- Contexts:
  - PATCH /context/{context_id}
  - Fields: source_title, raw_text, metadata (including tables), status
- Context files:
  - PATCH /context/files/{file_id} (metadata only)
- Extractions:
  - PATCH /context/extractions/{extraction_id} (status/notes; payload locked by default)
- Ontology artifacts (already exist but must be enforced):
  - PATCH /entities/{entity_id}
  - PATCH /hierarchies/{hierarchy_name}
  - PATCH /metrics/{metric_id}
  - PATCH /metrics/suggested/{id}

Add validation so updates cannot change tenant/domain scope and must remain within
the original connection scope (connection_id/database/schema/tables).
