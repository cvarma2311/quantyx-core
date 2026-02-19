# Phase AA: Flow Node Data Registry for Derived Views and NL Query

Goal: store durable metadata for each selected flow node (facts, dimensions, derived views, joined outputs) so the Ask-NL layer can resolve where data lives and query it through Trino/PyIceberg using SQL.

Scope:
- Registry table design
- SQL DDL and indexes
- Write/update lifecycle from flow builder
- Query resolution contract for Ask-NL
- Integration phases (backend + UI)

Out of scope:
- Full NL planner redesign
- Physical data pipeline implementation for every engine

---

## 1) Problem We Are Solving

In the flow-builder product, users join multiple sources and generate derived views.  
UI shows nodes and user selects one/more nodes for analysis.  
Ask-NL needs deterministic metadata for selected nodes:
- where data is stored (`minio_path`, Iceberg/Trino location),
- how to query it (catalog/schema/table or object path),
- what the schema is,
- sample records for preview and prompt grounding.

Without this registry, NL query routing becomes brittle and UI cannot reliably open/query a selected node.

---

## 2) Proposed Table (Single Source of Truth)

Table name:
- `public.quantyx_flow_node_data_registry`

One row = one version of one node output.

Logical identity:
- `artifact_key = flow_id + '::' + node_id`
- current pointer via `is_current=true`

Lifecycle:
- append-only versions; no in-place overwrite for payload-changing updates

---

## 3) SQL DDL (Initial)

```sql
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'quantyx_storage_engine') THEN
    CREATE TYPE public.quantyx_storage_engine AS ENUM ('parquet');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'quantyx_query_engine') THEN
    CREATE TYPE public.quantyx_query_engine AS ENUM ('pyiceberg');
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS public.quantyx_flow_node_data_registry (
  row_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  flow_id TEXT NOT NULL,
  node_id TEXT NOT NULL,
  node_type TEXT NOT NULL,                  -- source|fact|dimension|derived_view|join|metric_input

  artifact_key TEXT NOT NULL,               -- flow_id::node_id
  version_no INTEGER NOT NULL DEFAULT 1,
  is_current BOOLEAN NOT NULL DEFAULT true,

  storage_engine public.quantyx_storage_engine NOT NULL DEFAULT 'parquet',
  query_engine public.quantyx_query_engine NOT NULL DEFAULT 'pyiceberg',
  minio_path TEXT NOT NULL,                 -- s3://bucket/prefix/... or warehouse location

  iceberg_catalog TEXT NULL,
  iceberg_namespace TEXT NULL,
  iceberg_table TEXT NULL,
  pyiceberg_table_fqn TEXT NULL,
  iceberg_snapshot_id TEXT NULL,

  data_schema JSONB NOT NULL,               -- canonical column schema [{name,type,nullable,...}]
  sample_records JSONB NULL,                -- small sample (e.g. first 10 rows)
  row_count BIGINT NULL,
  partition_spec JSONB NULL,
  sort_order JSONB NULL,
  file_format TEXT NOT NULL DEFAULT 'parquet',
  compression TEXT NULL,                    -- zstd|snappy|gzip
  physical_stats JSONB NULL,                -- compact object: size_bytes, file_count, last_modified_at

  source_node_ids JSONB NULL,               -- lineage input node ids
  source_artifact_keys JSONB NULL,          -- upstream artifact keys
  transform_sql TEXT NULL,                  -- SQL used to generate derived node
  metadata JSONB NULL,                      -- extensible key-values

  source_run_id TEXT NULL,                  -- job id / pipeline run id
  source_type TEXT NOT NULL DEFAULT 'system', -- system|user|llm|rule
  change_reason TEXT NULL,
  created_by TEXT NULL,
  updated_by TEXT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_flow_node_registry_current
  ON public.quantyx_flow_node_data_registry (tenant_id, domain_id, artifact_key)
  WHERE is_current = true;

CREATE UNIQUE INDEX IF NOT EXISTS uq_flow_node_registry_version
  ON public.quantyx_flow_node_data_registry (tenant_id, domain_id, artifact_key, version_no);

CREATE INDEX IF NOT EXISTS idx_flow_node_registry_flow
  ON public.quantyx_flow_node_data_registry (tenant_id, domain_id, flow_id, node_id, updated_at DESC);

COMMENT ON TABLE public.quantyx_flow_node_data_registry IS
  'Registry of flow node output datasets (versioned) for UI preview and NL query routing.';

COMMENT ON COLUMN public.quantyx_flow_node_data_registry.row_id IS 'Primary key row id.';
COMMENT ON COLUMN public.quantyx_flow_node_data_registry.tenant_id IS 'Tenant identifier.';
COMMENT ON COLUMN public.quantyx_flow_node_data_registry.domain_id IS 'Domain identifier.';
COMMENT ON COLUMN public.quantyx_flow_node_data_registry.flow_id IS 'Flow identifier.';
COMMENT ON COLUMN public.quantyx_flow_node_data_registry.node_id IS 'Node identifier inside flow.';
COMMENT ON COLUMN public.quantyx_flow_node_data_registry.node_type IS 'Node type: source|fact|dimension|derived_view|join|metric_input.';
COMMENT ON COLUMN public.quantyx_flow_node_data_registry.artifact_key IS 'Stable logical key: flow_id::node_id.';
COMMENT ON COLUMN public.quantyx_flow_node_data_registry.version_no IS 'Version number for artifact_key.';
COMMENT ON COLUMN public.quantyx_flow_node_data_registry.is_current IS 'True for the active version row.';
COMMENT ON COLUMN public.quantyx_flow_node_data_registry.storage_engine IS 'Physical storage engine enum (default parquet).';
COMMENT ON COLUMN public.quantyx_flow_node_data_registry.query_engine IS 'Execution engine enum (default pyiceberg).';
COMMENT ON COLUMN public.quantyx_flow_node_data_registry.minio_path IS 'Primary object-storage path for dataset files.';
COMMENT ON COLUMN public.quantyx_flow_node_data_registry.iceberg_catalog IS 'Iceberg catalog name.';
COMMENT ON COLUMN public.quantyx_flow_node_data_registry.iceberg_namespace IS 'Iceberg namespace/database.';
COMMENT ON COLUMN public.quantyx_flow_node_data_registry.iceberg_table IS 'Iceberg table name.';
COMMENT ON COLUMN public.quantyx_flow_node_data_registry.pyiceberg_table_fqn IS 'Resolved PyIceberg query target (namespace.table).';
COMMENT ON COLUMN public.quantyx_flow_node_data_registry.iceberg_snapshot_id IS 'Iceberg snapshot id used for this version.';
COMMENT ON COLUMN public.quantyx_flow_node_data_registry.data_schema IS 'Canonical output schema as JSON array.';
COMMENT ON COLUMN public.quantyx_flow_node_data_registry.sample_records IS 'Small sample rows for UI preview.';
COMMENT ON COLUMN public.quantyx_flow_node_data_registry.row_count IS 'Estimated/actual row count.';
COMMENT ON COLUMN public.quantyx_flow_node_data_registry.partition_spec IS 'Partition specification metadata.';
COMMENT ON COLUMN public.quantyx_flow_node_data_registry.sort_order IS 'Sort order metadata.';
COMMENT ON COLUMN public.quantyx_flow_node_data_registry.file_format IS 'Materialized file format (default parquet).';
COMMENT ON COLUMN public.quantyx_flow_node_data_registry.compression IS 'Compression codec.';
COMMENT ON COLUMN public.quantyx_flow_node_data_registry.physical_stats IS 'Compact stats object: size_bytes, file_count, last_modified_at.';
COMMENT ON COLUMN public.quantyx_flow_node_data_registry.source_node_ids IS 'Input lineage node ids.';
COMMENT ON COLUMN public.quantyx_flow_node_data_registry.source_artifact_keys IS 'Input lineage artifact keys.';
COMMENT ON COLUMN public.quantyx_flow_node_data_registry.transform_sql IS 'SQL used to build this node output.';
COMMENT ON COLUMN public.quantyx_flow_node_data_registry.metadata IS 'Extensible metadata JSON.';
COMMENT ON COLUMN public.quantyx_flow_node_data_registry.source_run_id IS 'Job/pipeline run id.';
COMMENT ON COLUMN public.quantyx_flow_node_data_registry.source_type IS 'Origin of write: system|user|llm|rule.';
COMMENT ON COLUMN public.quantyx_flow_node_data_registry.change_reason IS 'Human-readable reason for change.';
COMMENT ON COLUMN public.quantyx_flow_node_data_registry.created_by IS 'Creator principal.';
COMMENT ON COLUMN public.quantyx_flow_node_data_registry.updated_by IS 'Updater principal.';
COMMENT ON COLUMN public.quantyx_flow_node_data_registry.created_at IS 'Creation timestamp.';
COMMENT ON COLUMN public.quantyx_flow_node_data_registry.updated_at IS 'Last update timestamp.';
```

---

## 4) Minimum Required Metadata for UI + NL

Must-have fields per node version:
- `tenant_id`
- `flow_id`
- `node_id`
- `minio_path`
- `data_schema`
- `sample_records`
- `storage_engine`
- query target:
  - `pyiceberg_table_fqn`
  - or (`iceberg_catalog`, `iceberg_namespace`, `iceberg_table`)
  - or resolvable `minio_path`

Strongly recommended:
- `source_node_ids`
- `transform_sql`
- `row_count`
- `artifact_key`, `version_no`, `is_current`

`physical_stats` minimal example:
```json
{
  "size_bytes": 123456789,
  "file_count": 42,
  "last_modified_at": "2026-02-19T10:20:30Z"
}
```

Lineage keys example (`source_node_ids`, `source_artifact_keys`):
```json
{
  "source_node_ids": [
    "node_s3_profile",
    "node_csv_sales",
    "node_pg_product"
  ],
  "source_artifact_keys": [
    "flow_customer360::node_s3_profile",
    "flow_customer360::node_csv_sales",
    "flow_customer360::node_pg_product"
  ]
}
```

End-to-end derived view example:
- S3 Profile columns: `CUSTOMER_ID`, `CUSTOMER_LAST_NAME`, `CUSTOMER_FIRST_NAME`
- CSV Sales columns: `CUSTOMER_ID`, `PRODUCT_ID`, `QUANTITY`, `AMOUNT`
- Postgres Product columns: `PRODUCT_ID`, `REGION`, `TYPE`, `VALUE`
- Derived view columns:
  - `CUSTOMER_ID`, `PRODUCT`, `REGION`, `TYPE`, `AMOUNT`, `CUSTOMER_FULL_NAME`

Example registry payload for the derived view node:
```json
{
  "flow_id": "flow_customer360",
  "node_id": "node_view_customer_sales_enriched",
  "artifact_key": "flow_customer360::node_view_customer_sales_enriched",
  "storage_engine": "parquet",
  "query_engine": "pyiceberg",
  "minio_path": "s3://quantyx-lake/tenant_a/flow_customer360/node_view_customer_sales_enriched/v1/",
  "iceberg_catalog": "quantyx_catalog",
  "iceberg_namespace": "tenant_a_flow_customer360",
  "iceberg_table": "view_customer_sales_enriched",
  "pyiceberg_table_fqn": "tenant_a_flow_customer360.view_customer_sales_enriched",
  "data_schema": [
    {"name": "customer_id", "type": "string"},
    {"name": "product", "type": "string"},
    {"name": "region", "type": "string"},
    {"name": "type", "type": "string"},
    {"name": "amount", "type": "decimal(18,2)"},
    {"name": "customer_full_name", "type": "string"}
  ],
  "source_node_ids": [
    "node_s3_profile",
    "node_csv_sales",
    "node_pg_product"
  ],
  "source_artifact_keys": [
    "flow_customer360::node_s3_profile",
    "flow_customer360::node_csv_sales",
    "flow_customer360::node_pg_product"
  ],
  "transform_sql": "SELECT s.customer_id, s.product_id AS product, p.region, p.type, s.amount, CONCAT(pr.customer_last_name, ' ', pr.customer_first_name) AS customer_full_name FROM sales s JOIN product p ON s.product_id = p.product_id JOIN profile pr ON s.customer_id = pr.customer_id",
  "physical_stats": {
    "size_bytes": 123456789,
    "file_count": 42,
    "last_modified_at": "2026-02-19T10:20:30Z"
  }
}
```

PyIceberg query using metadata target:
```sql
SELECT customer_id, product, region, type, amount, customer_full_name
FROM tenant_a_flow_customer360.view_customer_sales_enriched;
```

---

## 5) Backend Integration Plan

## Phase AA1: Schema and migration
- Add DDL to `artifacts/quantyx_tables.sql`.
- Add migration block to `artifacts/quantyx_tables_updates.sql`.
- Add hard-reset delete block for non-prod testing.

## Phase AA2: Registry service
Create `services/ai/flow_node_registry.py`:
- `upsert_flow_node_version(...)` (append version, mark previous current false)
- `get_current_flow_node(...)`
- `list_flow_nodes_for_flow(...)`
- `resolve_query_target(...)` -> returns table FQN/path and engine mode

## Phase AA3: Flow builder write-path
When user creates/updates derived node:
- persist node output metadata into registry
- set `artifact_key = flow_id::node_id`
- set `is_current=true`, increment `version_no`
- persist schema/sample/lineage/run-id

## Phase AA4: UI read-path
Add APIs:
- `GET /flows/{flow_id}/nodes?tenant_id=...` (current node registry rows)
- `GET /flows/{flow_id}/nodes/{node_id}?tenant_id=...`
- `GET /flows/{flow_id}/nodes/{node_id}/versions?tenant_id=...`

UI can render:
- node cards
- schema preview
- sample data preview
- source lineage badges

## Phase AA5: Ask-NL resolution hook
Before SQL generation/execution:
1. receive selected `flow_id/node_id`
2. resolve current registry row
3. choose engine:
   - `query_engine='pyiceberg'` -> load Iceberg table using catalog+namespace+table or `minio_path`
4. inject schema/sample context into NL planner prompt
5. execute generated SQL and return rows

---

## 6) Query Strategy (Trino / PyIceberg)

Default (recommended):
- use PyIceberg for query execution (`query_engine='pyiceberg'`)

Fallback:
- add Trino enum values later when needed and route by `query_engine`

Resolution order:
1. `pyiceberg_table_fqn`
2. `iceberg_catalog + iceberg_namespace + iceberg_table`
3. `minio_path`

---

## 7) API Contract Sketch

### POST /flows/{flow_id}/nodes/{node_id}/materialize
Request:
- tenant/domain + engine settings + transform SQL + lineage input + optional sample limit

Response:
- registry row id, artifact key, version no, query target metadata

### GET /flows/{flow_id}/nodes/{node_id}
Response:
- current registry entry with schema/sample/query target

### POST /nl/query
Request (additions):
- `flow_id`
- `node_id`

Behavior:
- resolve target from registry and execute against selected node dataset.

---

## 8) Data Quality and Guardrails

- Validate `data_schema` is non-empty before marking `is_current=true`.
- Validate query target is present (`iceberg_catalog/namespace/table` or `minio_path`).
- Limit `sample_records` size (e.g., max 20 rows, max 1 MB JSON).
- Enforce tenant/domain match for every read/write.
- Add audit trail via `source_run_id`, `created_by`, `updated_by`.

---

## 9) Non-Prod Reset SQL (Testing)

```sql
-- Testing only (destructive)
DELETE FROM public.quantyx_flow_node_data_registry;
```

---

## 10) Acceptance Criteria

1. For any selected flow node, UI can fetch schema + sample + query target in one API call.
2. Ask-NL can resolve selected node to a deterministic SQL target.
3. Node updates create new versions with one `is_current=true` row.
4. Query execution works for Trino path; PyIceberg path is available as fallback.
5. Tenant/domain isolation is enforced end-to-end.

---

## 11) Implementation Order

1. AA1 schema migration
2. AA2 registry service
3. AA3 flow-builder write path
4. AA4 UI read APIs
5. AA5 NL resolver integration

This order allows UI preview readiness first, then NL query routing with minimal risk.

---

## 12) Semantic Binding Layer (Automatic Background Process)

Goal: automatically bind derived-view physical columns to canonical semantics (entities, facts, dimensions, metrics) immediately after a new current row is written to `quantyx_flow_node_data_registry`.

Design principles:
- background and asynchronous (never block UI materialization flow),
- deterministic-first (rules + ontology + registries),
- LLM-assisted only when needed,
- confidence-gated output with human-review fallback.

### 12.1 New Tables

```sql
CREATE TABLE IF NOT EXISTS public.quantyx_flow_node_binding_runs (
  run_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  flow_id TEXT NOT NULL,
  node_id TEXT NOT NULL,
  artifact_key TEXT NOT NULL,
  node_version_no INTEGER NOT NULL,
  status TEXT NOT NULL,                        -- queued|running|completed|failed|canceled
  model_name TEXT NULL,
  trigger_source TEXT NOT NULL DEFAULT 'system', -- system|manual|retry
  started_at TIMESTAMPTZ NULL,
  completed_at TIMESTAMPTZ NULL,
  error_message TEXT NULL,
  summary JSONB NULL,                          -- counts by confidence/status
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.quantyx_flow_node_semantic_bindings (
  binding_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  flow_id TEXT NOT NULL,
  node_id TEXT NOT NULL,
  artifact_key TEXT NOT NULL,
  node_version_no INTEGER NOT NULL,
  run_id TEXT NOT NULL REFERENCES public.quantyx_flow_node_binding_runs(run_id),

  physical_column TEXT NOT NULL,               -- column in derived view schema
  semantic_type TEXT NOT NULL,                 -- entity|dimension|fact_measure|metric|time|id|attribute
  semantic_ref_type TEXT NOT NULL,             -- entity|dimension|fact|metric|ontology_term
  semantic_ref_id TEXT NOT NULL,               -- entity_id|dimension_id|fact_id|metric_id|ontology_term_id
  semantic_ref_field TEXT NULL,                -- attribute/key/measure field name when needed

  transform_expression TEXT NULL,              -- expression lineage for derived columns
  source_binding_ids JSONB NULL,               -- upstream binding ids for propagated columns
  source_columns JSONB NULL,                   -- upstream physical source columns

  confidence NUMERIC NOT NULL,                 -- 0..1
  confidence_band TEXT NOT NULL,               -- high|medium|low
  binding_method TEXT NOT NULL,                -- exact|fuzzy|lineage|ontology|metric_rule|llm
  binding_status TEXT NOT NULL DEFAULT 'proposed', -- proposed|accepted|rejected|superseded
  rationale TEXT NULL,

  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_flow_node_binding_runs_lookup
  ON public.quantyx_flow_node_binding_runs (tenant_id, domain_id, flow_id, node_id, created_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS uq_flow_node_binding_current_column
  ON public.quantyx_flow_node_semantic_bindings (
    tenant_id, domain_id, artifact_key, node_version_no, physical_column, semantic_ref_type, semantic_ref_id, COALESCE(semantic_ref_field, '')
  )
  WHERE binding_status IN ('proposed', 'accepted');
```

### 12.2 Trigger and Orchestration

Automatic trigger:
- when a new current version is inserted into `quantyx_flow_node_data_registry`:
  - create a binding run with `status='queued'`
  - enqueue async job type: `bind_flow_node_semantics`

Execution model:
- reuse existing async job worker (`quantyx_jobs`) with a dedicated handler,
- idempotency key:
  - `(tenant_id, artifact_key, node_version_no, binding_run_version)`
- retries:
  - max N retries with backoff,
  - mark `failed` with `error_message` if exhausted.

### 12.3 Binding Pipeline (Strong Architecture)

Stage 0: Context load
- load node metadata (`data_schema`, `sample_records`, `transform_sql`, lineage),
- load domain pack ontology and glossary,
- load current canonical registries:
  - entities/hierarchies
  - facts/dimensions
  - metrics

Stage 1: Deterministic candidate generation (no LLM)
- exact name match:
  - normalized physical column vs semantic names/aliases,
- key-pattern rules:
  - `_id`, `_code`, date/time columns, amount/qty measures,
- lineage propagation:
  - if column originates from upstream nodes with known bindings, inherit with high confidence,
- metric-expression heuristics:
  - map derived expression columns to metric candidates by expression shape.

Stage 2: Ontology-aware expansion
- apply domain-pack ontology terms, synonyms, and abbreviations,
- generate additional candidates with medium confidence,
- classify semantic type (`dimension`, `fact_measure`, `entity`, `metric`, etc.).

Stage 3: LLM disambiguation (only for unresolved/ambiguous)
- invoke LLM only when:
  - top deterministic confidence < threshold, or
  - multiple close candidates,
- LLM input:
  - column name + type + sample values + transform SQL snippet + ontology terms,
- LLM output:
  - ranked semantic candidates with rationale and confidence estimate.

Stage 4: Scoring and acceptance
- unified confidence scoring:
  - deterministic score
  - lineage bonus
  - ontology bonus
  - LLM confidence adjustment (bounded),
- confidence bands:
  - `high >= 0.85` -> auto `accepted`
  - `0.60 to <0.85` -> `proposed` (review queue)
  - `<0.60` -> `proposed` low-confidence (not used for auto SQL mapping)

Stage 5: Persist + publish
- write bindings for this run into `quantyx_flow_node_semantic_bindings`,
- update run summary (`accepted/proposed/rejected counts`),
- set run `status='completed'`.

### 12.4 Runtime Use in Ask-NL

When only `tenant_id` is provided:
1. candidate target selection chooses best node/semantic target,
2. load latest accepted/proposed bindings for selected node version,
3. map NL semantic intent -> canonical refs -> physical columns via bindings,
4. generate SQL only from high-confidence accepted mappings by default,
5. if required mapping is missing:
   - fallback to canonical registry path, or
   - ask one clarification.

### 12.5 Governance and Review Workflow

Add review endpoints:
- `GET /flows/{flow_id}/nodes/{node_id}/bindings?tenant_id=...`
- `POST /flows/{flow_id}/nodes/{node_id}/bindings/review`
  - accept/reject specific bindings
- `POST /flows/{flow_id}/nodes/{node_id}/bindings/rebind`
  - manual rerun for updated ontology/metadata

Review actions:
- accepted binding -> promoted to `binding_status='accepted'`,
- rejected binding -> `binding_status='rejected'`,
- replacement writes mark old rows `superseded`.

### 12.6 Default Operational Policy

- Always auto-run binding on new current node version.
- Default LLM usage:
  - enabled for ambiguous columns only,
  - disabled for high-confidence deterministic matches.
- Maximum binding SLA target:
  - P95 run completion < 60s per node (configurable).
- Emit metrics:
  - run duration
  - accepted ratio
  - low-confidence ratio
  - LLM invocation rate
  - query-time fallback rate.

### 12.7 Suggested Implementation Steps

AA6: Schema
- add `quantyx_flow_node_binding_runs`
- add `quantyx_flow_node_semantic_bindings`

AA7: Binding service
- create `services/ai/flow_node_binding.py`
  - run orchestration
  - deterministic binders
  - LLM disambiguator
  - scorer + persistence

AA8: Async integration
- add job type `bind_flow_node_semantics`
- enqueue automatically after node materialization write

AA9: Ask-NL mapper integration
- add binding-aware semantic mapper in query planning path

AA10: Review UX APIs
- add read/review/rebind endpoints
- expose binding confidence and rationale in UI

### 12.8 Acceptance Criteria for Semantic Binding Layer

1. New node versions automatically trigger semantic binding runs.
2. At least 90% of columns in common derived views get `accepted` or medium/high `proposed` bindings without manual edits.
3. Ask-NL can generate SQL from tenant-only input using bound semantics for derived views.
4. Low-confidence mappings are isolated and do not silently corrupt generated SQL.
5. Binding runs are auditable, retryable, and observable.
