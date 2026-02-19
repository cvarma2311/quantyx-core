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
