# Phase Q: Connection-Scoped Entities & Mapping (Tenant-Aware)

Goal: make all onboarding artifacts connection-scoped and tenant-aware, with
clear CRUD APIs and persistence per section:
1) Entities
2) Hierarchies
3) Dimensions & Facts
4) Metrics
5) Review (approval + status)

This phase updates:
- `/onboard/map` default behavior (use_llm=true),
- entity list/override APIs to support per-connection sections,
- storage schema for scoped entity mappings and overrides.

---

## 1) Key Requirements

1) **/onboard/map default use_llm=true**
   - If `use_llm` is not provided, default to `true`.

2) **Tenant + connection scope required**
   - Require: `tenant_id`, `connection_id`, `database`, `schema`, `tables[]`
   - Return 400 if missing scope.

3) **Entity sections per connection**
   - Responses grouped by connection scope.
   - UI can select connection/schema and see separate entity lists.

4) **CRUD per section**
   - Each section must expose POST / GET / PATCH (and PUT where applicable).
   - All writes must persist to DB tables, scoped by tenant + connection.

5) **Review workflow**
   - Draft → reviewed → applied status for each section.
   - Review artifacts stored in DB for audit.

---

## 2) API Changes

### 2.1 Entities

#### POST /onboard/map (default use_llm=true)

Query params:
- `domain_id` (required)
- `tenant_id` (required)
- `use_llm` (optional; default true)

Request:
```json
{
  "connection_id": "conn_prod",
  "database": "prod_warehouse",
  "schema": "public",
  "tables": ["fact_sales", "dim_customer"]
}
```

Response (grouped by connection scope):
```json
{
  "connection_id": "conn_prod",
  "database": "prod_warehouse",
  "schema": "public",
  "tables": ["fact_sales", "dim_customer"],
  "candidates": [
    {
      "table": "fact_sales",
      "column": "sales_area_name",
      "mapped_entity_type": "organizational_unit",
      "confidence": 0.85,
      "source": "llm"
    }
  ],
  "low_confidence_candidates": [],
  "low_confidence_threshold": 0.7
}
```

Notes:
- Store results in `quantyx_entity_mappings` (new table).
- Status defaults to `draft`.

#### GET /entities (connection-scoped)

Query params (required):
- `tenant_id`
- `domain_id`
- `connection_id`
- `database`
- `schema`

Response:
```json
{
  "connection_id": "conn_prod",
  "database": "prod_warehouse",
  "schema": "public",
  "entities": [
    {
      "entity_id": "organizational_unit",
      "description": "Sales org",
      "join_key": "sales_area_name"
    }
  ],
  "hierarchies": [
    {
      "name": "sales_org",
      "levels": ["zone", "region", "sales_area"]
    }
  ]
}
```

#### GET /entities/all (tenant-wide)

Query params:
- `tenant_id` (required)
- `domain_id` (required)

Response (grouped by connection):
```json
{
  "connections": [
    {
      "connection_id": "conn_prod",
      "database": "prod_warehouse",
      "schema": "public",
      "entities": [
        {
          "entity_id": "organizational_unit",
          "description": "Sales org",
          "join_key": "sales_area_name"
        }
      ],
      "hierarchies": [
        {
          "name": "sales_org",
          "levels": ["zone", "region", "sales_area"]
        }
      ]
    }
  ]
}
```

---

#### PATCH /entities/{entity_id} (connection-scoped)

Query params (required):
- `tenant_id`
- `domain_id`
- `connection_id`
- `database`
- `schema`

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

---

### 2.2 Hierarchies

#### GET /hierarchies (connection-scoped)
Query params:
- `tenant_id`, `domain_id`, `connection_id`, `database`, `schema`

Response:
```json
{
  "hierarchies": [
    { "name": "sales_org", "levels": ["zone", "region", "sales_area"] }
  ]
}
```

#### PATCH /hierarchies/{hierarchy_name} (connection-scoped)

Query params (required):
- `tenant_id`
- `domain_id`
- `connection_id`
- `database`
- `schema`

Request:
```json
{
  "levels": ["zone", "region", "sales_area"],
  "description": "Sales rollup"
}
```

Response:
```json
{ "ok": true }
```

Notes:
- Hierarchies are a **mix** of:
  1) Domain pack ontology (base defaults), and
  2) Tenant-scoped overrides.
- **Auto-creation** should be seeded from:
  - `/context/extract` (hierarchies in extracted payload), and
  - optional LLM mapping (future enhancement).
- When a user saves/edits a hierarchy, persist to:
  `public.quantyx_hierarchy_overrides` with tenant + connection scope.
- Context-extracted hierarchies are stored in:
  `public.quantyx_context_extractions` (payload JSON).
- **Canonical hierarchies** should live in:
  `public.quantyx_hierarchy_overrides` (scoped + persisted).

Desired behavior (no pack fallback):
- On first onboarding, **seed pack hierarchies into overrides** for the scope.
- After that, **always read hierarchies from `quantyx_hierarchy_overrides`** only.
- Pack ontology is used only as a seeding template, not as a runtime source.

---

### 2.3 Dimensions & Facts

#### POST /onboard/infer-models (connection-scoped)
Request:
```json
{
  "tenant_id": "tenant_a",
  "domain_id": "manufacturing",
  "connection_id": "conn_prod",
  "database": "prod_warehouse",
  "schema": "public",
  "tables": ["fact_sales", "dim_customer"],
  "use_llm": true
}
```

Response:
```json
{
  "facts": [
    {
      "name": "fact_sales",
      "grain": "day",
      "time_column": "sales_date",
      "measures": ["sales_amount", "discount_amount"],
      "dimensions": ["sales_area_name", "product_name"],
      "confidence": 0.85
    }
  ],
  "dimensions": [
    {
      "name": "dim_customer",
      "keys": ["customer_id"],
      "attributes": ["customer_name", "region_name"],
      "confidence": 0.8
    }
  ]
}
```

Storage:
- Facts: `public.quantyx_facts_registry`
- Dimensions: `public.quantyx_dimensions_registry`

#### GET /facts (connection-scoped)
Query params:
- `tenant_id`, `domain_id`, `connection_id`, `database`, `schema`

Response:
```json
{
  "facts": [
    {
      "fact_id": "fact_123",
      "table_name": "fact_sales",
      "grain": "day",
      "time_column": "sales_date",
      "status": "draft"
    }
  ]
}
```

Reads from:
- `public.quantyx_facts_registry` (scoped by tenant + connection)

#### GET /dimensions (connection-scoped)
Query params:
- `tenant_id`, `domain_id`, `connection_id`, `database`, `schema`

Response:
```json
{
  "dimensions": [
    {
      "dimension_id": "dim_123",
      "table_name": "dim_customer",
      "status": "draft"
    }
  ]
}
```

Reads from:
- `public.quantyx_dimensions_registry` (scoped by tenant + connection)

#### GET /facts/all (tenant-wide)
Query params:
- `tenant_id`, `domain_id`

Response:
```json
{
  "connections": [
    {
      "connection_id": "conn_prod",
      "database": "prod_warehouse",
      "schema": "public",
      "facts": [
        { "fact_id": "fact_123", "table_name": "fact_sales", "status": "draft" }
      ]
    }
  ]
}
```

Reads from:
- `public.quantyx_facts_registry` (grouped by connection)

#### GET /dimensions/all (tenant-wide)
Query params:
- `tenant_id`, `domain_id`

Response:
```json
{
  "connections": [
    {
      "connection_id": "conn_prod",
      "database": "prod_warehouse",
      "schema": "public",
      "dimensions": [
        { "dimension_id": "dim_123", "table_name": "dim_customer", "status": "draft" }
      ]
    }
  ]
}
```

Reads from:
- `public.quantyx_dimensions_registry` (grouped by connection)

#### PATCH /facts/{fact_id} (connection-scoped)
Request:
```json
{ "grain": "day", "time_column": "sales_date" }
```

Response:
```json
{ "ok": true }
```

Writes to:
- `public.quantyx_facts_registry`

#### PATCH /dimensions/{dimension_id} (connection-scoped)
Request:
```json
{ "description": "Customer region" }
```

Response:
```json
{ "ok": true }
```

Writes to:
- `public.quantyx_dimensions_registry`

#### DELETE /facts/{fact_id} (connection-scoped)
Query params:
- `tenant_id`, `domain_id`, `connection_id`, `database`, `schema`

Response:
```json
{ "ok": true }
```

Deletes from:
- `public.quantyx_facts_registry`

#### DELETE /dimensions/{dimension_id} (connection-scoped)
Query params:
- `tenant_id`, `domain_id`, `connection_id`, `database`, `schema`

Response:
```json
{ "ok": true }
```

Deletes from:
- `public.quantyx_dimensions_registry`

---

### 2.4 Metrics

#### POST /metrics (connection-scoped)
Request:
```json
{
  "tenant_id": "tenant_a",
  "domain_id": "manufacturing",
  "connection_id": "conn_prod",
  "database": "prod_warehouse",
  "schema": "public",
  "tables": ["fact_sales"],
  "metric_name": "total_sales",
  "type": "sum",
  "sql": "{{ ref('fact_sales') }}.sales_amount",
  "grain": "day",
  "dimensions": ["sales_area_name"]
}
```

#### GET /metrics (connection-scoped)
Query params:
- `tenant_id`, `domain_id`, `connection_id`, `database`, `schema`

#### PATCH /metrics/{metric_id} (connection-scoped)
Request:
```json
{ "status": "certified", "description": "Reviewed metric" }
```

Metric lifecycle (facts/dims → auto → review → promote):
1) Confirm facts/dims from `/onboard/infer-models`
2) Auto-generate suggestions:
   - `POST /metrics/suggested?domain_id=...&persist=true`
   - Persist as `status = suggested` in `quantyx_metrics_registry`
3) Review/edit:
   - `PATCH /metrics/{metric_id}` (fix SQL, dimensions, grain)
4) Promote:
   - Set `status = certified`

---

### 2.5 Review

#### POST /review
Request:
```json
{
  "tenant_id": "tenant_a",
  "domain_id": "manufacturing",
  "connection_id": "conn_prod",
  "artifact_type": "entities",
  "artifact_id": "map_123",
  "status": "reviewed",
  "notes": "Looks good"
}
```

#### GET /review
Query params:
- `tenant_id`, `domain_id`, `connection_id`, `artifact_type`

#### PATCH /review/{review_id}
Request:
```json
{ "status": "applied" }
```

---

### 2.6 Mapping history

#### GET /onboard/map/history (optional)
Return latest mapping runs for the given scope.

Query params:
- `tenant_id`, `domain_id`, `connection_id`, `database`, `schema`

Response:
```json
{
  "runs": [
    {
      "mapping_id": "map_123",
      "created_at": "2026-02-04T12:00:00Z",
      "candidates": 12,
      "low_confidence": 4
    }
  ]
}
```

---

## 3) Database Changes (SQL)

### 3.1 Entity mapping runs (new)
```sql
CREATE TABLE IF NOT EXISTS public.quantyx_entity_mappings (
  mapping_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  connection_id TEXT NOT NULL,
  database_name TEXT NOT NULL,
  schema_name TEXT NOT NULL,
  tables JSONB NOT NULL DEFAULT '[]'::jsonb,
  payload JSONB NOT NULL, -- candidates + low_confidence + threshold
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_quantyx_entity_mappings_scope
  ON public.quantyx_entity_mappings (tenant_id, domain_id, connection_id, created_at DESC);
```

### 3.2 Connection-scoped overrides (extend existing tables)
```sql
ALTER TABLE public.quantyx_entity_overrides
  ADD COLUMN IF NOT EXISTS connection_id TEXT NULL,
  ADD COLUMN IF NOT EXISTS database_name TEXT NULL,
  ADD COLUMN IF NOT EXISTS schema_name TEXT NULL;

ALTER TABLE public.quantyx_hierarchy_overrides
  ADD COLUMN IF NOT EXISTS connection_id TEXT NULL,
  ADD COLUMN IF NOT EXISTS database_name TEXT NULL,
  ADD COLUMN IF NOT EXISTS schema_name TEXT NULL;
```

Indexes:
```sql
CREATE INDEX IF NOT EXISTS idx_quantyx_entity_overrides_scope
  ON public.quantyx_entity_overrides (tenant_id, domain_id, connection_id, database_name, schema_name);

CREATE INDEX IF NOT EXISTS idx_quantyx_hierarchy_overrides_scope
  ON public.quantyx_hierarchy_overrides (tenant_id, domain_id, connection_id, database_name, schema_name);
```

### 3.3 Metrics scope (extend registry)
```sql
ALTER TABLE public.quantyx_metrics_registry
  ADD COLUMN IF NOT EXISTS connection_id TEXT NULL,
  ADD COLUMN IF NOT EXISTS database_name TEXT NULL,
  ADD COLUMN IF NOT EXISTS schema_name TEXT NULL;

CREATE INDEX IF NOT EXISTS idx_quantyx_metrics_registry_scope
  ON public.quantyx_metrics_registry (domain_id, connection_id, database_name, schema_name);
```

### 3.4 Facts & dimensions (new tables)
```sql
CREATE TABLE IF NOT EXISTS public.quantyx_facts_registry (
  fact_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  connection_id TEXT NOT NULL,
  database_name TEXT NOT NULL,
  schema_name TEXT NOT NULL,
  table_name TEXT NOT NULL,
  time_column TEXT NULL,
  grain TEXT NULL,
  status TEXT NOT NULL DEFAULT 'draft',
  payload JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.quantyx_dimensions_registry (
  dimension_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  connection_id TEXT NOT NULL,
  database_name TEXT NOT NULL,
  schema_name TEXT NOT NULL,
  table_name TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'draft',
  payload JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### 3.5 Review table (new)
```sql
CREATE TABLE IF NOT EXISTS public.quantyx_review_events (
  review_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  connection_id TEXT NOT NULL,
  artifact_type TEXT NOT NULL,
  artifact_id TEXT NOT NULL,
  status TEXT NOT NULL,
  notes TEXT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_quantyx_review_events_scope
  ON public.quantyx_review_events (tenant_id, domain_id, connection_id, artifact_type, created_at DESC);
```

---

## 4) Behavior changes

- `/onboard/map` defaults to `use_llm=true` if unset.
- All CRUD operations require tenant + connection scope.
- Each section persists to DB tables with status tracking.
- Review table captures approvals and applied status.

---

## 5) Acceptance Criteria

- `/onboard/map` returns scope-aware mapping results.
- Mapping runs are persisted and queryable.
- Each section has POST/GET/PATCH (and PUT where needed).
- Review events are stored and auditable.
- Multi-connection environments do not mix entity scopes.
