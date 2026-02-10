# Phase T: Semantic Layer Enhancement (Logical Data Management)

Goal: align the semantic layer with logical data management principles (universal semantic layer, real-time access, governance, and AI-ready outputs), with LLMs used for focused, bounded tasks.

This phase focuses on:
- stronger semantic contracts and pack versioning
- policy enforcement at query time
- multi-source federation readiness
- self-service discovery metadata
- AI-ready outputs with lineage + validation
- LLM-assisted semantic extraction and validation with strict prompts

---

## 1) Semantic Contracts + Pack Versioning

### 1.1 Contract schema (new)
Add a `contracts/semantic_contracts/` directory with:
- `business_terms.yml` (glossary terms, synonyms, abbreviations)
- `metric_definitions.yml` (metric business definitions)
- `dataset_definitions.yml` (dataset descriptions, owners, refresh SLAs)
- `policy_definitions.yml` (access + masking + aggregation rules)
- `entity_definitions.yml` (entities, join keys, hierarchies)

### 1.2 Pack versioning
Add explicit version metadata and changelog per pack:
- `packs/<industry>/pack.yml` with:
  - `version`, `release_date`, `breaking_changes`, `notes`

Acceptance:
- Packs can be versioned and promoted per tenant.
- Contracts are loaded by `version` (default latest).
- Every semantic contract bundle has a validated hash and provenance.

---

## 2) Policy Enforcement in Query Execution

### 2.1 Policy runtime
Apply `policies.yml` at runtime inside `/query`:
- row-level filters (include/exclude)
- column masking (redact or hash)
- minimum aggregation (k‑anonymity style)

### 2.2 Policy audit log
Extend query audit to include:
- applied policies
- masked fields
- blocked queries (with reason)

Acceptance:
- Policy violations block queries.
- Audit logs show which policies were applied.
- Masking/aggregation policies are enforced and visible in query responses.

---

## 3) Federation & Multi‑Source Readiness

### 3.1 Source registry
Extend connection registry:
- add `source_type` (warehouse, lake, app, api)
- add `priority` and `latency_tier`

### 3.2 Query planner routing
Add routing rules:
- prefer lower latency sources for interactive queries
- allow override via query params

Acceptance:
- Schema + datasets are aggregated across sources.
- Queries can target a specific source or use priority routing.

---

## 4) Self‑Service Discovery Enhancements

Add metadata to `/schema`, `/datasets`, `/metrics`:
- `owner`
- `refresh_frequency`
- `data_quality_score`
- `usage_stats` (last used, top queries)
- `sample_queries`

Acceptance:
- UI can show discovery cards with ownership + freshness + usage.

---

## 5) AI‑Ready Outputs

Enhance `/query` response to include:
- `semantic_validation` (metric definitions + checks)
- `lineage` (models, source tables)
- `assumptions` (filters, defaults, joins)

Acceptance:
- AI clients can explain answers with definitions + lineage.

---

## 6) LLM‑Assisted Semantic Extraction (Focused Prompts)

LLMs are used to enrich semantic contracts and improve mapping quality. Each LLM call:
- has a strict schema for output
- uses small, bounded context
- avoids free‑form responses
- is deterministic when possible (temperature ~0.0–0.2)

### 6.1 LLM tasks

1) **Glossary extraction**
   - Input: raw business text, table/column descriptions
   - Output: glossary terms, synonyms, abbreviations

2) **Metric definition drafting**
   - Input: suggested metrics + table profiles
   - Output: business definition + grain + dimensions

3) **Entity mapping assistance**
   - Input: columns + ontology entities
   - Output: entity_type mapping + confidence

4) **Dataset description drafting**
   - Input: dataset schema + usage stats
   - Output: concise dataset description + owner hints

### 6.2 Prompt templates (examples)

**Glossary extraction prompt**
```
You are a semantic extraction engine. Extract glossary terms from the input.
Return JSON only with schema:
{
  "terms": [
    {
      "term": "string",
      "definition": "string",
      "synonyms": ["string"],
      "abbreviations": ["string"]
    }
  ]
}
Rules:
- Only use information present in the input.
- Do not invent definitions.
- If unsure, omit the term.
Input:
{raw_text}
```

**Entity mapping prompt**
```
Map columns to the provided ontology entity types.
Return JSON only with schema:
{
  "mappings": [
    { "table": "string", "column": "string", "entity_type": "string", "confidence": 0.0 }
  ]
}
Rules:
- Choose entity_type only from this list: {entity_types}
- Confidence between 0.0 and 1.0
- If confidence < 0.7, include it anyway but keep confidence low.
Input:
{tables_and_columns}
```

**Metric definition prompt**
```
Given a metric candidate, produce a business definition and grain.
Return JSON only:
{
  "metric_name": "string",
  "definition": "string",
  "grain": "string",
  "dimensions": ["string"]
}
Rules:
- Use only provided context.
- Do not change metric_name.
Input:
{metric_candidate_and_columns}
```

### 6.3 Storage for LLM outputs

Persist all LLM outputs to:
- `public.quantyx_context_extractions`
- `public.quantyx_semantic_contracts`

---

## 7) API Changes (Detailed)

### New
- `GET /packs` returns available packs + versions
- `POST /packs/apply` apply pack version to tenant
- `GET /contracts/semantic` returns active semantic contract bundle
- `POST /contracts/semantic/validate` validate contract bundle
- `POST /contracts/semantic/extract` run LLM extraction on raw inputs
- `POST /contracts/semantic/apply` apply extracted terms to active contracts
- `GET /query/lineage` return lineage for last query
- `GET /policies/effective` return resolved policies for a tenant/scope

### Extended
- `GET /datasets` includes owner + freshness + quality
- `GET /metrics` includes definition + lineage refs
- `POST /query` returns semantic_validation + lineage

---

## 8) Storage (Detailed)

New tables:
- `public.quantyx_pack_versions`
- `public.quantyx_semantic_contracts`
- `public.quantyx_policy_audit`
- `public.quantyx_usage_stats`

### 8.1 SQL (proposed)

```sql
CREATE TABLE IF NOT EXISTS public.quantyx_pack_versions (
  pack_id TEXT PRIMARY KEY,
  industry TEXT NOT NULL,
  version TEXT NOT NULL,
  release_date DATE NOT NULL,
  breaking_changes TEXT NULL,
  notes TEXT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_pack_versions_unique
  ON public.quantyx_pack_versions (industry, version);

CREATE TABLE IF NOT EXISTS public.quantyx_semantic_contracts (
  contract_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  industry TEXT NOT NULL,
  version TEXT NOT NULL,
  payload JSONB NOT NULL,
  hash TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_semantic_contracts_tenant
  ON public.quantyx_semantic_contracts (tenant_id, industry, created_at DESC);

CREATE TABLE IF NOT EXISTS public.quantyx_policy_audit (
  policy_audit_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  query_id TEXT NULL,
  policy_name TEXT NOT NULL,
  action TEXT NOT NULL,
  details JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_policy_audit_tenant
  ON public.quantyx_policy_audit (tenant_id, created_at DESC);

CREATE TABLE IF NOT EXISTS public.quantyx_usage_stats (
  stat_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  artifact_type TEXT NOT NULL,
  artifact_id TEXT NOT NULL,
  last_used_at TIMESTAMPTZ NULL,
  usage_count INTEGER NOT NULL DEFAULT 0,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_usage_stats_tenant
  ON public.quantyx_usage_stats (tenant_id, artifact_type, usage_count DESC);
```

---

## Acceptance Criteria

- Packs are versioned and tenant‑selectable.
- Policies are enforced on every `/query`.
- `/query` returns lineage + semantic validation.
- Discovery endpoints show ownership + freshness.
- LLM extraction endpoints produce structured JSON with validation.

---

## 9) Minimal Integration Path (Safe Rollout)

### 9.1 Step 1: Contract Storage + Pack Versioning
- Add `quantyx_pack_versions` + `quantyx_semantic_contracts` tables.
- Add `packs/<industry>/pack.yml` with version metadata.
- Add admin API: `POST /packs/apply` to bind a pack version to a tenant.

SQL (Step 1):
```sql
CREATE TABLE IF NOT EXISTS public.quantyx_pack_versions (
  pack_id TEXT PRIMARY KEY,
  industry TEXT NOT NULL,
  version TEXT NOT NULL,
  release_date DATE NOT NULL,
  breaking_changes TEXT NULL,
  notes TEXT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_pack_versions_unique
  ON public.quantyx_pack_versions (industry, version);

CREATE TABLE IF NOT EXISTS public.quantyx_semantic_contracts (
  contract_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  industry TEXT NOT NULL,
  version TEXT NOT NULL,
  payload JSONB NOT NULL,
  hash TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_semantic_contracts_tenant
  ON public.quantyx_semantic_contracts (tenant_id, industry, created_at DESC);
```

API (Step 1):
```
POST /packs/apply
```

Request:
```json
{
  "tenant_id": "tenant_a",
  "industry": "petroleum_refinery",
  "version": "1.0.0"
}
```

Response:
```json
{ "ok": true }
```

### 9.2 Step 2: Read‑Only Contract Integration
- Load semantic contracts into catalog responses (`/metrics`, `/datasets`).
- Add `definition`, `owner`, `freshness` fields from contracts.
- No query behavior change yet (safe).

API changes (Step 2):
- `GET /metrics` returns:
```json
{
  "metrics": [
    {
      "metric_name": "throughput_volume",
      "definition": "Total metered throughput volume",
      "owner": "ops-analytics",
      "freshness": "daily"
    }
  ]
}
```

- `GET /datasets` returns:
```json
{
  "datasets": [
    {
      "name": "dispatch_events",
      "description": "Lorry dispatch and load events",
      "owner": "ops-analytics",
      "refresh_frequency": "hourly"
    }
  ]
}
```

### 9.3 Step 3: LLM Extraction (Write‑Only)
- Add `POST /contracts/semantic/extract`:
  - run focused LLM prompts
  - persist structured outputs to `quantyx_semantic_contracts`
- Add `POST /contracts/semantic/apply`:
  - apply extracted definitions to active contracts
- Still no query behavior changes.

API (Step 3):

```
POST /contracts/semantic/extract
```

Request:
```json
{
  "tenant_id": "tenant_a",
  "industry": "petroleum_refinery",
  "inputs": {
    "raw_text": "MFM = mass flow meter. Stock_code identifies product...",
    "tables": ["fact_dispatch", "dim_product"]
  },
  "model": "gpt-4o-mini"
}
```

Response:
```json
{
  "contract_id": "contract_123",
  "status": "extracted"
}
```

```
POST /contracts/semantic/apply
```

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

### 9.4 Step 4: Policy Enforcement (Behavior Change)
- Enforce policies at query time (masking, filters, aggregation rules).
- Add `quantyx_policy_audit` logs.
- Return `semantic_validation` + `lineage` in `/query` responses.

SQL (Step 4):
```sql
CREATE TABLE IF NOT EXISTS public.quantyx_policy_audit (
  policy_audit_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  query_id TEXT NULL,
  policy_name TEXT NOT NULL,
  action TEXT NOT NULL,
  details JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_policy_audit_tenant
  ON public.quantyx_policy_audit (tenant_id, created_at DESC);
```

API change (Step 4):
```json
{
  "rows": [],
  "semantic_validation": {
    "definitions": ["throughput_volume"],
    "assumptions": ["default grain=day"],
    "policy_applied": ["suppress_small_groups"]
  },
  "lineage": {
    "models": ["fact_dispatch"],
    "tables": ["public.fact_dispatch"]
  }
}
```
