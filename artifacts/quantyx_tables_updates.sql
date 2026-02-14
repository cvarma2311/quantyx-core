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

ALTER TABLE public.quantyx_entity_mappings
  ALTER COLUMN tables SET DEFAULT '[]'::jsonb;

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

-- Phase U: Tenant scope resolution compatibility
ALTER TABLE public.quantyx_job_scopes
  ADD COLUMN IF NOT EXISTS tenant_id TEXT NULL;

ALTER TABLE public.quantyx_job_scopes
  ADD COLUMN IF NOT EXISTS domain_id TEXT NULL;

CREATE INDEX IF NOT EXISTS idx_quantyx_dbt_config_tenant_domain
  ON public.quantyx_dbt_config (tenant_id, domain_id, updated_at DESC);
