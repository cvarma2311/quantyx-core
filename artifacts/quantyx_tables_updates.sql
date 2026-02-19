ALTER TABLE public.quantyx_entity_overrides
  ADD COLUMN IF NOT EXISTS source_context_id TEXT NULL;

ALTER TABLE public.quantyx_entity_overrides
  ADD COLUMN IF NOT EXISTS connection_id TEXT;

ALTER TABLE public.quantyx_entity_overrides
  ADD COLUMN IF NOT EXISTS database_name TEXT;

ALTER TABLE public.quantyx_entity_overrides
  ADD COLUMN IF NOT EXISTS schema_name TEXT;

UPDATE public.quantyx_entity_overrides
  SET connection_id = COALESCE(connection_id, 'global'),
      database_name = COALESCE(database_name, 'global'),
      schema_name = COALESCE(schema_name, 'global');

ALTER TABLE public.quantyx_entity_overrides
  ALTER COLUMN connection_id SET NOT NULL;

ALTER TABLE public.quantyx_entity_overrides
  ALTER COLUMN database_name SET NOT NULL;

ALTER TABLE public.quantyx_entity_overrides
  ALTER COLUMN schema_name SET NOT NULL;

ALTER TABLE public.quantyx_entity_overrides
  ADD CONSTRAINT quantyx_entity_overrides_no_global
  CHECK (connection_id <> 'global' AND database_name <> 'global' AND schema_name <> 'global');

ALTER TABLE public.quantyx_entity_overrides
  DROP CONSTRAINT IF EXISTS quantyx_entity_overrides_pkey;

ALTER TABLE public.quantyx_entity_overrides
  ADD PRIMARY KEY (tenant_id, domain_id, connection_id, database_name, schema_name, entity_id);

CREATE INDEX IF NOT EXISTS idx_quantyx_entity_overrides_scope
  ON public.quantyx_entity_overrides (tenant_id, domain_id, connection_id, database_name, schema_name);

ALTER TABLE public.quantyx_hierarchy_overrides
  ADD COLUMN IF NOT EXISTS source_context_id TEXT NULL;

ALTER TABLE public.quantyx_hierarchy_overrides
  ADD COLUMN IF NOT EXISTS connection_id TEXT;

ALTER TABLE public.quantyx_hierarchy_overrides
  ADD COLUMN IF NOT EXISTS database_name TEXT;

ALTER TABLE public.quantyx_hierarchy_overrides
  ADD COLUMN IF NOT EXISTS schema_name TEXT;

UPDATE public.quantyx_hierarchy_overrides
  SET connection_id = COALESCE(connection_id, 'global'),
      database_name = COALESCE(database_name, 'global'),
      schema_name = COALESCE(schema_name, 'global');

ALTER TABLE public.quantyx_hierarchy_overrides
  ALTER COLUMN connection_id SET NOT NULL;

ALTER TABLE public.quantyx_hierarchy_overrides
  ALTER COLUMN database_name SET NOT NULL;

ALTER TABLE public.quantyx_hierarchy_overrides
  ALTER COLUMN schema_name SET NOT NULL;

ALTER TABLE public.quantyx_hierarchy_overrides
  ADD CONSTRAINT quantyx_hierarchy_overrides_no_global
  CHECK (connection_id <> 'global' AND database_name <> 'global' AND schema_name <> 'global');

ALTER TABLE public.quantyx_hierarchy_overrides
  DROP CONSTRAINT IF EXISTS quantyx_hierarchy_overrides_pkey;

ALTER TABLE public.quantyx_hierarchy_overrides
  ADD PRIMARY KEY (tenant_id, domain_id, connection_id, database_name, schema_name, hierarchy_name);

CREATE INDEX IF NOT EXISTS idx_quantyx_hierarchy_overrides_scope
  ON public.quantyx_hierarchy_overrides (tenant_id, domain_id, connection_id, database_name, schema_name);

ALTER TABLE public.quantyx_context_extractions
  ADD COLUMN IF NOT EXISTS status TEXT NULL;

ALTER TABLE public.quantyx_context_extractions
  ADD COLUMN IF NOT EXISTS notes TEXT NULL;

CREATE TABLE IF NOT EXISTS public.quantyx_tenant_domains (
  tenant_id TEXT PRIMARY KEY,
  domain_id TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE public.quantyx_metrics_registry
  ADD COLUMN IF NOT EXISTS tenant_id TEXT NULL;

ALTER TABLE public.quantyx_metrics_registry
  ADD COLUMN IF NOT EXISTS connection_id TEXT NULL;

ALTER TABLE public.quantyx_metrics_registry
  ADD COLUMN IF NOT EXISTS database_name TEXT NULL;

ALTER TABLE public.quantyx_metrics_registry
  ADD COLUMN IF NOT EXISTS schema_name TEXT NULL;

CREATE INDEX IF NOT EXISTS idx_quantyx_metrics_registry_scope
  ON public.quantyx_metrics_registry (tenant_id, domain_id, connection_id, database_name, schema_name);

ALTER TABLE public.quantyx_entity_mappings
  ADD COLUMN IF NOT EXISTS candidates JSONB,
  ADD COLUMN IF NOT EXISTS low_confidence_candidates JSONB,
  ADD COLUMN IF NOT EXISTS low_confidence_threshold NUMERIC,
  ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'draft',
  ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  ADD COLUMN IF NOT EXISTS tables JSONB;

ALTER TABLE public.quantyx_facts_registry
  ADD COLUMN IF NOT EXISTS name TEXT NULL;

ALTER TABLE public.quantyx_facts_registry
  ADD COLUMN IF NOT EXISTS measures JSONB NULL;

ALTER TABLE public.quantyx_facts_registry
  ADD COLUMN IF NOT EXISTS dimensions JSONB NULL;

ALTER TABLE public.quantyx_facts_registry
  ADD COLUMN IF NOT EXISTS description TEXT NULL;

ALTER TABLE public.quantyx_facts_registry
  ADD COLUMN IF NOT EXISTS table_name TEXT NULL;

UPDATE public.quantyx_facts_registry
  SET table_name = COALESCE(table_name, name)
  WHERE table_name IS NULL
    AND name IS NOT NULL;

UPDATE public.quantyx_facts_registry
  SET name = COALESCE(name, table_name)
  WHERE name IS NULL
    AND table_name IS NOT NULL;

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

CREATE TABLE IF NOT EXISTS public.quantyx_tenant_scopes (
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  connection_id TEXT NOT NULL,
  database_name TEXT NOT NULL,
  schema_name TEXT NOT NULL,
  tables JSONB NULL,
  status TEXT NOT NULL DEFAULT 'active',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, domain_id)
);

CREATE INDEX IF NOT EXISTS idx_quantyx_tenant_scopes_status
  ON public.quantyx_tenant_scopes (status, updated_at DESC);

CREATE TABLE IF NOT EXISTS public.quantyx_tenant_scope_history (
  history_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  connection_id TEXT NOT NULL,
  database_name TEXT NOT NULL,
  schema_name TEXT NOT NULL,
  tables JSONB NULL,
  status TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

UPDATE public.quantyx_entity_mappings
  SET tables = COALESCE(tables, '[]'::jsonb)
  WHERE tables IS NULL;

UPDATE public.quantyx_entity_mappings
  SET candidates = COALESCE(candidates, payload -> 'candidates', '[]'::jsonb)
  WHERE candidates IS NULL;

UPDATE public.quantyx_entity_mappings
  SET low_confidence_candidates = COALESCE(low_confidence_candidates, payload -> 'low_confidence_candidates', '[]'::jsonb)
  WHERE low_confidence_candidates IS NULL;

UPDATE public.quantyx_entity_mappings
  SET low_confidence_threshold = COALESCE(
    low_confidence_threshold,
    CASE
      WHEN payload ? 'low_confidence_threshold' THEN (payload ->> 'low_confidence_threshold')::NUMERIC
      ELSE 0.7
    END
  )
  WHERE low_confidence_threshold IS NULL;

UPDATE public.quantyx_entity_mappings
  SET status = COALESCE(status, 'draft')
  WHERE status IS NULL;

ALTER TABLE public.quantyx_entity_mappings
  ALTER COLUMN tables SET DEFAULT '[]'::jsonb;

ALTER TABLE public.quantyx_entity_mappings
  ALTER COLUMN candidates SET DEFAULT '[]'::jsonb;

ALTER TABLE public.quantyx_entity_mappings
  ALTER COLUMN low_confidence_candidates SET DEFAULT '[]'::jsonb;

ALTER TABLE public.quantyx_entity_mappings
  ALTER COLUMN low_confidence_threshold SET DEFAULT 0.7;

ALTER TABLE public.quantyx_entity_mappings
  ALTER COLUMN status SET DEFAULT 'draft';

ALTER TABLE public.quantyx_dimensions_registry
  ADD COLUMN IF NOT EXISTS name TEXT NULL;

ALTER TABLE public.quantyx_dimensions_registry
  ADD COLUMN IF NOT EXISTS keys JSONB NULL;

ALTER TABLE public.quantyx_dimensions_registry
  ADD COLUMN IF NOT EXISTS attributes JSONB NULL;

ALTER TABLE public.quantyx_dimensions_registry
  ADD COLUMN IF NOT EXISTS description TEXT NULL;

ALTER TABLE public.quantyx_dimensions_registry
  DROP COLUMN IF EXISTS table_name;

ALTER TABLE public.quantyx_dimensions_registry
  DROP COLUMN IF EXISTS payload;

ALTER TABLE public.quantyx_review_events
  ADD COLUMN IF NOT EXISTS database_name TEXT NULL;

ALTER TABLE public.quantyx_review_events
  ADD COLUMN IF NOT EXISTS schema_name TEXT NULL;

ALTER TABLE public.quantyx_review_events
  ADD COLUMN IF NOT EXISTS payload JSONB NULL;

CREATE TABLE IF NOT EXISTS public.quantyx_canvases (
  canvas_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  name TEXT NOT NULL,
  description TEXT NULL,
  graph_json JSONB NOT NULL,
  root_node_id TEXT NULL,
  status TEXT NOT NULL DEFAULT 'draft',
  idempotency_key TEXT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_quantyx_canvases_tenant
  ON public.quantyx_canvases (tenant_id, domain_id, created_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS idx_quantyx_canvases_idempotency
  ON public.quantyx_canvases (tenant_id, domain_id, idempotency_key)
  WHERE idempotency_key IS NOT NULL;

CREATE TABLE IF NOT EXISTS public.quantyx_canvas_nodes (
  canvas_id TEXT NOT NULL REFERENCES public.quantyx_canvases(canvas_id),
  node_type TEXT NOT NULL,
  node_id TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (canvas_id, node_type, node_id)
);

CREATE INDEX IF NOT EXISTS idx_quantyx_canvas_nodes_node
  ON public.quantyx_canvas_nodes (node_type, node_id);

CREATE TABLE IF NOT EXISTS public.quantyx_canvas_edges (
  canvas_id TEXT NOT NULL REFERENCES public.quantyx_canvases(canvas_id),
  from_type TEXT NOT NULL,
  from_id TEXT NOT NULL,
  to_type TEXT NOT NULL,
  to_id TEXT NOT NULL,
  edge_type TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT 'manual',
  confidence NUMERIC NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (canvas_id, from_type, from_id, to_type, to_id)
);

CREATE INDEX IF NOT EXISTS idx_quantyx_canvas_edges_canvas
  ON public.quantyx_canvas_edges (canvas_id, created_at DESC);

-- Phase U: Tenant scope resolution compatibility
ALTER TABLE public.quantyx_job_scopes
  ADD COLUMN IF NOT EXISTS tenant_id TEXT NULL;

ALTER TABLE public.quantyx_job_scopes
  ADD COLUMN IF NOT EXISTS domain_id TEXT NULL;

CREATE INDEX IF NOT EXISTS idx_quantyx_dbt_config_tenant_domain
  ON public.quantyx_dbt_config (tenant_id, domain_id, updated_at DESC);

-- Phase Z1: Unified lifecycle/versioning columns (schema-first)

ALTER TABLE public.quantyx_entity_overrides
  ADD COLUMN IF NOT EXISTS artifact_key TEXT,
  ADD COLUMN IF NOT EXISTS version_no INTEGER NOT NULL DEFAULT 1,
  ADD COLUMN IF NOT EXISTS is_current BOOLEAN NOT NULL DEFAULT true,
  ADD COLUMN IF NOT EXISTS lifecycle_status TEXT NOT NULL DEFAULT 'draft',
  ADD COLUMN IF NOT EXISTS source_type TEXT NOT NULL DEFAULT 'system',
  ADD COLUMN IF NOT EXISTS source_run_id TEXT NULL,
  ADD COLUMN IF NOT EXISTS change_reason TEXT NULL,
  ADD COLUMN IF NOT EXISTS approved_by TEXT NULL,
  ADD COLUMN IF NOT EXISTS approved_at TIMESTAMPTZ NULL,
  ADD COLUMN IF NOT EXISTS supersedes_version_no INTEGER NULL,
  ADD COLUMN IF NOT EXISTS created_by TEXT NULL,
  ADD COLUMN IF NOT EXISTS updated_by TEXT NULL,
  ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT now();

UPDATE public.quantyx_entity_overrides
  SET artifact_key = COALESCE(artifact_key, entity_id)
  WHERE artifact_key IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_quantyx_entity_overrides_current
  ON public.quantyx_entity_overrides (tenant_id, domain_id, connection_id, database_name, schema_name, artifact_key)
  WHERE is_current = true;

CREATE UNIQUE INDEX IF NOT EXISTS uq_quantyx_entity_overrides_version
  ON public.quantyx_entity_overrides (tenant_id, domain_id, connection_id, database_name, schema_name, artifact_key, version_no);

ALTER TABLE public.quantyx_hierarchy_overrides
  ADD COLUMN IF NOT EXISTS artifact_key TEXT,
  ADD COLUMN IF NOT EXISTS version_no INTEGER NOT NULL DEFAULT 1,
  ADD COLUMN IF NOT EXISTS is_current BOOLEAN NOT NULL DEFAULT true,
  ADD COLUMN IF NOT EXISTS lifecycle_status TEXT NOT NULL DEFAULT 'draft',
  ADD COLUMN IF NOT EXISTS source_type TEXT NOT NULL DEFAULT 'system',
  ADD COLUMN IF NOT EXISTS source_run_id TEXT NULL,
  ADD COLUMN IF NOT EXISTS change_reason TEXT NULL,
  ADD COLUMN IF NOT EXISTS approved_by TEXT NULL,
  ADD COLUMN IF NOT EXISTS approved_at TIMESTAMPTZ NULL,
  ADD COLUMN IF NOT EXISTS supersedes_version_no INTEGER NULL,
  ADD COLUMN IF NOT EXISTS created_by TEXT NULL,
  ADD COLUMN IF NOT EXISTS updated_by TEXT NULL,
  ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT now();

UPDATE public.quantyx_hierarchy_overrides
  SET artifact_key = COALESCE(artifact_key, hierarchy_name)
  WHERE artifact_key IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_quantyx_hierarchy_overrides_current
  ON public.quantyx_hierarchy_overrides (tenant_id, domain_id, connection_id, database_name, schema_name, artifact_key)
  WHERE is_current = true;

CREATE UNIQUE INDEX IF NOT EXISTS uq_quantyx_hierarchy_overrides_version
  ON public.quantyx_hierarchy_overrides (tenant_id, domain_id, connection_id, database_name, schema_name, artifact_key, version_no);

ALTER TABLE public.quantyx_facts_registry
  ADD COLUMN IF NOT EXISTS artifact_key TEXT,
  ADD COLUMN IF NOT EXISTS version_no INTEGER NOT NULL DEFAULT 1,
  ADD COLUMN IF NOT EXISTS is_current BOOLEAN NOT NULL DEFAULT true,
  ADD COLUMN IF NOT EXISTS lifecycle_status TEXT NOT NULL DEFAULT 'draft',
  ADD COLUMN IF NOT EXISTS source_type TEXT NOT NULL DEFAULT 'system',
  ADD COLUMN IF NOT EXISTS source_run_id TEXT NULL,
  ADD COLUMN IF NOT EXISTS change_reason TEXT NULL,
  ADD COLUMN IF NOT EXISTS approved_by TEXT NULL,
  ADD COLUMN IF NOT EXISTS approved_at TIMESTAMPTZ NULL,
  ADD COLUMN IF NOT EXISTS supersedes_version_no INTEGER NULL,
  ADD COLUMN IF NOT EXISTS created_by TEXT NULL,
  ADD COLUMN IF NOT EXISTS updated_by TEXT NULL;

UPDATE public.quantyx_facts_registry
  SET artifact_key = COALESCE(artifact_key, fact_id)
  WHERE artifact_key IS NULL;

UPDATE public.quantyx_facts_registry
  SET lifecycle_status = COALESCE(lifecycle_status, 'draft')
  WHERE lifecycle_status IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_quantyx_facts_registry_current
  ON public.quantyx_facts_registry (tenant_id, domain_id, connection_id, database_name, schema_name, artifact_key)
  WHERE is_current = true;

CREATE UNIQUE INDEX IF NOT EXISTS uq_quantyx_facts_registry_version
  ON public.quantyx_facts_registry (tenant_id, domain_id, connection_id, database_name, schema_name, artifact_key, version_no);

ALTER TABLE public.quantyx_dimensions_registry
  ADD COLUMN IF NOT EXISTS artifact_key TEXT,
  ADD COLUMN IF NOT EXISTS version_no INTEGER NOT NULL DEFAULT 1,
  ADD COLUMN IF NOT EXISTS is_current BOOLEAN NOT NULL DEFAULT true,
  ADD COLUMN IF NOT EXISTS lifecycle_status TEXT NOT NULL DEFAULT 'draft',
  ADD COLUMN IF NOT EXISTS source_type TEXT NOT NULL DEFAULT 'system',
  ADD COLUMN IF NOT EXISTS source_run_id TEXT NULL,
  ADD COLUMN IF NOT EXISTS change_reason TEXT NULL,
  ADD COLUMN IF NOT EXISTS approved_by TEXT NULL,
  ADD COLUMN IF NOT EXISTS approved_at TIMESTAMPTZ NULL,
  ADD COLUMN IF NOT EXISTS supersedes_version_no INTEGER NULL,
  ADD COLUMN IF NOT EXISTS created_by TEXT NULL,
  ADD COLUMN IF NOT EXISTS updated_by TEXT NULL;

UPDATE public.quantyx_dimensions_registry
  SET artifact_key = COALESCE(artifact_key, dimension_id)
  WHERE artifact_key IS NULL;

UPDATE public.quantyx_dimensions_registry
  SET lifecycle_status = COALESCE(lifecycle_status, 'draft')
  WHERE lifecycle_status IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_quantyx_dimensions_registry_current
  ON public.quantyx_dimensions_registry (tenant_id, domain_id, connection_id, database_name, schema_name, artifact_key)
  WHERE is_current = true;

CREATE UNIQUE INDEX IF NOT EXISTS uq_quantyx_dimensions_registry_version
  ON public.quantyx_dimensions_registry (tenant_id, domain_id, connection_id, database_name, schema_name, artifact_key, version_no);

ALTER TABLE public.quantyx_metrics_registry
  ADD COLUMN IF NOT EXISTS artifact_key TEXT,
  ADD COLUMN IF NOT EXISTS version_no INTEGER NOT NULL DEFAULT 1,
  ADD COLUMN IF NOT EXISTS is_current BOOLEAN NOT NULL DEFAULT true,
  ADD COLUMN IF NOT EXISTS lifecycle_status TEXT NOT NULL DEFAULT 'suggested',
  ADD COLUMN IF NOT EXISTS source_type TEXT NOT NULL DEFAULT 'system',
  ADD COLUMN IF NOT EXISTS source_run_id TEXT NULL,
  ADD COLUMN IF NOT EXISTS change_reason TEXT NULL,
  ADD COLUMN IF NOT EXISTS approved_by TEXT NULL,
  ADD COLUMN IF NOT EXISTS approved_at TIMESTAMPTZ NULL,
  ADD COLUMN IF NOT EXISTS supersedes_version_no INTEGER NULL,
  ADD COLUMN IF NOT EXISTS created_by TEXT NULL,
  ADD COLUMN IF NOT EXISTS updated_by TEXT NULL;

UPDATE public.quantyx_metrics_registry
  SET artifact_key = COALESCE(artifact_key, metric_id)
  WHERE artifact_key IS NULL;

UPDATE public.quantyx_metrics_registry
  SET lifecycle_status = COALESCE(lifecycle_status, 'suggested')
  WHERE lifecycle_status IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_quantyx_metrics_registry_current
  ON public.quantyx_metrics_registry (tenant_id, domain_id, connection_id, database_name, schema_name, artifact_key)
  WHERE is_current = true;

CREATE UNIQUE INDEX IF NOT EXISTS uq_quantyx_metrics_registry_version
  ON public.quantyx_metrics_registry (tenant_id, domain_id, connection_id, database_name, schema_name, artifact_key, version_no);

-- Phase Z hard cutover cleanup (no backward compatibility)
-- Run after validating latest lifecycle/versioning behavior in production.

-- 1) Enforce artifact_key as required everywhere.
ALTER TABLE public.quantyx_entity_overrides
  ALTER COLUMN artifact_key SET NOT NULL;

ALTER TABLE public.quantyx_hierarchy_overrides
  ALTER COLUMN artifact_key SET NOT NULL;

ALTER TABLE public.quantyx_facts_registry
  ALTER COLUMN artifact_key SET NOT NULL;

ALTER TABLE public.quantyx_dimensions_registry
  ALTER COLUMN artifact_key SET NOT NULL;

ALTER TABLE public.quantyx_metrics_registry
  ALTER COLUMN artifact_key SET NOT NULL;

-- 2) Remove legacy staging table replaced by single-table lifecycle model.
DROP INDEX IF EXISTS idx_quantyx_entity_mappings_scope;
DROP TABLE IF EXISTS public.quantyx_entity_mappings;

-- 3) Remove legacy lifecycle alias columns (hard cutover).
ALTER TABLE public.quantyx_facts_registry DROP COLUMN IF EXISTS status;
ALTER TABLE public.quantyx_dimensions_registry DROP COLUMN IF EXISTS status;
ALTER TABLE public.quantyx_metrics_registry DROP COLUMN IF EXISTS status;

-- 4) Optional data pruning for old non-current versions.
-- Keep the newest 20 non-current versions per artifact key; delete older rows.
DELETE FROM public.quantyx_metrics_registry t
 WHERE COALESCE(t.is_current, true) = false
   AND t.metric_id IN (
     SELECT metric_id
       FROM (
         SELECT metric_id,
                ROW_NUMBER() OVER (
                  PARTITION BY tenant_id, domain_id, connection_id, database_name, schema_name, artifact_key
                  ORDER BY COALESCE(version_no, 1) DESC, COALESCE(updated_at, created_at) DESC
                ) AS rn
           FROM public.quantyx_metrics_registry
          WHERE COALESCE(is_current, true) = false
       ) ranked
      WHERE ranked.rn > 20
   );

-- Use when you explicitly want to wipe all pre-cutover artifact data.
-- DELETE FROM public.quantyx_entity_overrides;
-- DELETE FROM public.quantyx_hierarchy_overrides;
-- DELETE FROM public.quantyx_facts_registry;
-- DELETE FROM public.quantyx_dimensions_registry;
-- DELETE FROM public.quantyx_metrics_registry;

-- Phase AA: Flow node data registry for derived views + NL query routing

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
  node_type TEXT NOT NULL,
  artifact_key TEXT NOT NULL,
  version_no INTEGER NOT NULL DEFAULT 1,
  is_current BOOLEAN NOT NULL DEFAULT true,
  storage_engine public.quantyx_storage_engine NOT NULL DEFAULT 'parquet',
  query_engine public.quantyx_query_engine NOT NULL DEFAULT 'pyiceberg',
  minio_path TEXT NOT NULL,
  iceberg_catalog TEXT NULL,
  iceberg_namespace TEXT NULL,
  iceberg_table TEXT NULL,
  pyiceberg_table_fqn TEXT NULL,
  iceberg_snapshot_id TEXT NULL,
  data_schema JSONB NOT NULL DEFAULT '[]'::jsonb,
  sample_records JSONB NULL,
  row_count BIGINT NULL,
  partition_spec JSONB NULL,
  sort_order JSONB NULL,
  file_format TEXT NOT NULL DEFAULT 'parquet',
  compression TEXT NULL,
  physical_stats JSONB NULL,
  source_node_ids JSONB NULL,
  source_artifact_keys JSONB NULL,
  transform_sql TEXT NULL,
  metadata JSONB NULL,
  source_run_id TEXT NULL,
  source_type TEXT NOT NULL DEFAULT 'system',
  change_reason TEXT NULL,
  created_by TEXT NULL,
  updated_by TEXT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE public.quantyx_flow_node_data_registry
  ADD COLUMN IF NOT EXISTS tenant_id TEXT,
  ADD COLUMN IF NOT EXISTS domain_id TEXT,
  ADD COLUMN IF NOT EXISTS flow_id TEXT,
  ADD COLUMN IF NOT EXISTS node_id TEXT,
  ADD COLUMN IF NOT EXISTS node_type TEXT,
  ADD COLUMN IF NOT EXISTS artifact_key TEXT,
  ADD COLUMN IF NOT EXISTS version_no INTEGER NOT NULL DEFAULT 1,
  ADD COLUMN IF NOT EXISTS is_current BOOLEAN NOT NULL DEFAULT true,
  ADD COLUMN IF NOT EXISTS storage_engine public.quantyx_storage_engine NOT NULL DEFAULT 'parquet',
  ADD COLUMN IF NOT EXISTS query_engine public.quantyx_query_engine NOT NULL DEFAULT 'pyiceberg',
  ADD COLUMN IF NOT EXISTS minio_path TEXT,
  ADD COLUMN IF NOT EXISTS iceberg_catalog TEXT,
  ADD COLUMN IF NOT EXISTS iceberg_namespace TEXT,
  ADD COLUMN IF NOT EXISTS iceberg_table TEXT,
  ADD COLUMN IF NOT EXISTS pyiceberg_table_fqn TEXT,
  ADD COLUMN IF NOT EXISTS iceberg_snapshot_id TEXT,
  ADD COLUMN IF NOT EXISTS data_schema JSONB NOT NULL DEFAULT '[]'::jsonb,
  ADD COLUMN IF NOT EXISTS sample_records JSONB,
  ADD COLUMN IF NOT EXISTS row_count BIGINT,
  ADD COLUMN IF NOT EXISTS partition_spec JSONB,
  ADD COLUMN IF NOT EXISTS sort_order JSONB,
  ADD COLUMN IF NOT EXISTS file_format TEXT NOT NULL DEFAULT 'parquet',
  ADD COLUMN IF NOT EXISTS compression TEXT,
  ADD COLUMN IF NOT EXISTS physical_stats JSONB,
  ADD COLUMN IF NOT EXISTS source_node_ids JSONB,
  ADD COLUMN IF NOT EXISTS source_artifact_keys JSONB,
  ADD COLUMN IF NOT EXISTS transform_sql TEXT,
  ADD COLUMN IF NOT EXISTS metadata JSONB,
  ADD COLUMN IF NOT EXISTS source_run_id TEXT,
  ADD COLUMN IF NOT EXISTS source_type TEXT NOT NULL DEFAULT 'system',
  ADD COLUMN IF NOT EXISTS change_reason TEXT,
  ADD COLUMN IF NOT EXISTS created_by TEXT,
  ADD COLUMN IF NOT EXISTS updated_by TEXT,
  ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

CREATE UNIQUE INDEX IF NOT EXISTS uq_quantyx_flow_node_registry_current
  ON public.quantyx_flow_node_data_registry (tenant_id, domain_id, artifact_key)
  WHERE is_current = true;

CREATE UNIQUE INDEX IF NOT EXISTS uq_quantyx_flow_node_registry_version
  ON public.quantyx_flow_node_data_registry (tenant_id, domain_id, artifact_key, version_no);

CREATE INDEX IF NOT EXISTS idx_quantyx_flow_node_registry_flow
  ON public.quantyx_flow_node_data_registry (tenant_id, domain_id, flow_id, node_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_quantyx_flow_node_registry_pyiceberg_fqn
  ON public.quantyx_flow_node_data_registry (tenant_id, domain_id, pyiceberg_table_fqn);

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
