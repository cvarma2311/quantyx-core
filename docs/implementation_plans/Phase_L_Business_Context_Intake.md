# Phase L: Business Context Intake (Text, Glossary, Hierarchies, Questions)

Goal: accept business context text (table/column descriptions, abbreviations, synonyms, hierarchy notes, and sample questions), persist it, and use LLM-assisted processing to enrich ontology, entities, hierarchies, and metric candidates.

Note: multiple contexts per tenant/domain are supported. Multiple active
contexts and multi-hierarchy handling are specified in
`docs/implementation_plans/Phase_AD_Multi_Context_Multi_Hierarchy.md`.

Each **single context** can contain multiple hierarchies (e.g., geography,
supply chain). These are stored and applied independently.

---

## Why this exists

Customers often provide critical semantic context as free text (naming conventions, business definitions, abbreviations, synonyms, and hierarchy rules). This is essential to build accurate ontology, metric definitions, and entity mapping. The system must persist this context, make it queryable, and allow LLM-assisted extraction to generate structured artifacts.

---

## SQL changes

All tables are `public` and prefixed with `quantyx_`.

### 1) Context storage

```sql
CREATE TABLE IF NOT EXISTS public.quantyx_business_context (
  context_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  connection_id TEXT NULL,
  database_name TEXT NULL,
  schema_name TEXT NULL,
  source_type TEXT NOT NULL, -- e.g. 'business_context', 'table_descriptions', 'abbreviations', 'hierarchies', 'questions'
  source_title TEXT NULL,
  raw_text TEXT NOT NULL,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  status TEXT NOT NULL DEFAULT 'submitted', -- submitted | processed | archived
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS quantyx_business_context_tenant_idx
  ON public.quantyx_business_context (tenant_id, domain_id, source_type, status);

CREATE INDEX IF NOT EXISTS quantyx_business_context_conn_idx
  ON public.quantyx_business_context (connection_id, database_name, schema_name);
```

### 2) Context file storage + linking

```sql
CREATE TABLE IF NOT EXISTS public.quantyx_context_files (
  file_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  filename TEXT NOT NULL,
  content_type TEXT NULL,
  extracted_text TEXT NOT NULL,
  raw_bytes BYTEA NOT NULL,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS quantyx_context_files_tenant_idx
  ON public.quantyx_context_files (tenant_id, domain_id, created_at DESC);

CREATE TABLE IF NOT EXISTS public.quantyx_context_file_links (
  context_id TEXT NOT NULL,
  file_id TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (context_id, file_id),
  FOREIGN KEY (context_id) REFERENCES public.quantyx_business_context(context_id),
  FOREIGN KEY (file_id) REFERENCES public.quantyx_context_files(file_id)
);
```

### 3) LLM extraction outputs (structured)

```sql
CREATE TABLE IF NOT EXISTS public.quantyx_context_extractions (
  extraction_id TEXT PRIMARY KEY,
  context_id TEXT NOT NULL,
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  extraction_type TEXT NOT NULL, -- abbreviations | synonyms | hierarchies | entity_defs | metric_candidates | question_intents
  payload JSONB NOT NULL,
  llm_model TEXT NULL,
  confidence NUMERIC NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  FOREIGN KEY (context_id) REFERENCES public.quantyx_business_context(context_id)
);

CREATE INDEX IF NOT EXISTS quantyx_context_extractions_tenant_idx
  ON public.quantyx_context_extractions (tenant_id, domain_id, extraction_type);
```

### 3) Optional: enriched glossary (if we want a separate registry)

```sql
CREATE TABLE IF NOT EXISTS public.quantyx_glossary_terms (
  term_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  term TEXT NOT NULL,
  normalized_term TEXT NOT NULL,
  definition TEXT NULL,
  synonyms JSONB NOT NULL DEFAULT '[]'::jsonb,
  abbreviations JSONB NOT NULL DEFAULT '[]'::jsonb,
  source_context_id TEXT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS quantyx_glossary_terms_lookup_idx
  ON public.quantyx_glossary_terms (tenant_id, domain_id, normalized_term);
```

---

## API changes

### 1) Ingest business context (raw text + file ids)

`POST /context/ingest`

- Accept raw text with metadata and optional `file_ids` list
- Persist in `quantyx_business_context` with `status=submitted`

Request:
```json
{
  "tenant_id": "tenant_a",
  "domain_id": "energy_distribution",
  "source_type": "business_context",
  "source_title": "Operations glossary and hierarchy notes",
  "raw_text": "SBU = Strategic Business Unit...",
  "file_ids": ["file_123", "file_456"],
  "metadata": {
    "connection_id": "conn_prod",
    "database": "prod_warehouse",
    "schema": "public",
    "tables": ["fact_sales", "dim_org"],
    "columns": ["sbu_name", "zone_name"]
  }
}
```

Response:
```json
{ "context_id": "ctx_123", "status": "submitted" }
```

### 2) Upload a context file

`POST /context/ingest-file`

- Accept a single .txt or .docx file (one per request)
- Persist extracted text + raw bytes to `quantyx_context_files`
- Return `file_id` for linking in `/context/ingest`

Request (multipart/form-data):
```
tenant_id=tenant_a
domain_id=energy_distribution
source_type=business_context
source_title=Operations glossary
metadata={"connection_id":"conn_prod","database":"prod_warehouse","schema":"public"}
file=@context.txt
```

Response:
```json
{ "file_id": "file_123", "status": "stored" }
```

### 3) List context entries

`GET /context`

Query params: `tenant_id`, `domain_id`, `source_type`, `status`, `limit`, `cursor`

### 4) Run extraction (LLM)

`POST /context/extract`

- Runs LLM-based extraction for abbreviations, synonyms, hierarchies, metric candidates, and question intents
- Stores results in `quantyx_context_extractions`
- Returns structured extraction summaries and confidence

Request:
```json
{
  "tenant_id": "tenant_a",
  "domain_id": "energy_distribution",
  "context_id": "ctx_123",
  "extraction_types": ["abbreviations", "synonyms", "hierarchies", "metric_candidates", "question_intents"],
  "model": "gpt-4o-mini"
}
```

Response:
```json
{
  "extraction_id": "ext_123",
  "context_id": "ctx_123",
  "extractions": {
    "abbreviations": [{"abbr": "SBU", "definition": "Strategic Business Unit"}],
    "synonyms": [{"term": "sales area", "synonyms": ["territory"]}],
    "hierarchies": [{"name": "sales_org", "levels": ["zone", "region", "sales_area"]}],
    "metric_candidates": [{"metric_name": "sales_tmt", "table": "fact_sales"}],
    "question_intents": [{"question": "Which zones are underperforming?", "metrics": ["sales_tmt"]}]
  }
}
```

### 5) Apply extractions

`POST /context/apply`

- Applies extracted data to:
  - entity overrides/hierarchies
  - glossary terms
  - metrics registry suggestions
  - ontology mapping hints

Request:
```json
{
  "tenant_id": "tenant_a",
  "domain_id": "energy_distribution",
  "extraction_id": "ext_123",
  "apply": {
    "entities": true,
    "hierarchies": true,
    "glossary": true,
    "metrics": true
  }
}
```

Response:
```json
{ "status": "applied", "updated": {"entities": 4, "hierarchies": 1, "metrics": 8} }
```

---

## LLM processing workflow

1) Normalize the raw text input and detect sections (tables/columns, abbreviations, hierarchies, metrics, questions).
2) Extract structured objects:
   - Abbreviation dictionary
   - Synonym sets
   - Hierarchy candidates
   - Metric candidates (name, source, expression hints)
   - Question intents (metrics + dimensions)
3) Combine raw_text + linked file text before LLM extraction.
4) Validate extracted items:
   - Ensure referenced tables/columns exist (if connection scope exists)
   - Flag unknown terms as low confidence
4) Persist results and expose for review/edit before applying.

---

## Downstream usage

- Ontology mapping uses synonyms and abbreviations to improve entity matching.
- Hierarchy overrides are seeded from extracted hierarchy notes.
- Metric suggestion model uses question intents to propose candidate metrics.
- Search and NL resolver use glossary to map user phrasing to known entities/metrics.

---

## Phase plan (implementation steps)

1) **Schema changes**
   - Add `quantyx_business_context`, `quantyx_context_files`, `quantyx_context_file_links`, `quantyx_context_extractions`, and optional `quantyx_glossary_terms`.

2) **API contracts**
   - Add request/response models to `services/api/schemas.py`.
   - Add `/context/ingest-file` (single file upload) and `file_ids` on `/context/ingest`.

3) **LLM extraction service**
   - Implement `services/ai/context_extraction.py`.
   - Support multi-section parsing and structured JSON outputs.

4) **Apply pipeline**
   - Implement `services/ai/context_apply.py` to update glossary, ontology hints, entity overrides, and suggested metrics.

5) **Audit and governance**
   - Persist extraction runs and application results in `quantyx_context_extractions`.
   - Add query audit entries for extract/apply endpoints.

6) **Docs and onboarding**
   - Add new API docs in `artifacts/V2_API.md`.
   - Add new onboarding flow references in `artifacts/ONBOARDING_API_FLOW.md`.

---

## Acceptance criteria

- Raw text input stored and retrievable by tenant/domain.
- Extraction returns structured abbreviations/synonyms/hierarchies/metrics/questions.
- Apply endpoint updates downstream registries and overrides.
- Swagger shows request/response examples for each endpoint.
- All outputs are stored in the database for traceability.
