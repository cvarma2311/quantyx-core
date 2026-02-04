ALTER TABLE public.quantyx_entity_overrides
  ADD COLUMN IF NOT EXISTS source_context_id TEXT NULL;

ALTER TABLE public.quantyx_entity_overrides
  ADD COLUMN IF NOT EXISTS connection_id TEXT DEFAULT 'global';

ALTER TABLE public.quantyx_entity_overrides
  ADD COLUMN IF NOT EXISTS database_name TEXT DEFAULT 'global';

ALTER TABLE public.quantyx_entity_overrides
  ADD COLUMN IF NOT EXISTS schema_name TEXT DEFAULT 'global';

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
  DROP CONSTRAINT IF EXISTS quantyx_entity_overrides_pkey;

ALTER TABLE public.quantyx_entity_overrides
  ADD PRIMARY KEY (tenant_id, domain_id, connection_id, database_name, schema_name, entity_id);

CREATE INDEX IF NOT EXISTS idx_quantyx_entity_overrides_scope
  ON public.quantyx_entity_overrides (tenant_id, domain_id, connection_id, database_name, schema_name);

ALTER TABLE public.quantyx_hierarchy_overrides
  ADD COLUMN IF NOT EXISTS source_context_id TEXT NULL;

ALTER TABLE public.quantyx_hierarchy_overrides
  ADD COLUMN IF NOT EXISTS connection_id TEXT DEFAULT 'global';

ALTER TABLE public.quantyx_hierarchy_overrides
  ADD COLUMN IF NOT EXISTS database_name TEXT DEFAULT 'global';

ALTER TABLE public.quantyx_hierarchy_overrides
  ADD COLUMN IF NOT EXISTS schema_name TEXT DEFAULT 'global';

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
  DROP CONSTRAINT IF EXISTS quantyx_hierarchy_overrides_pkey;

ALTER TABLE public.quantyx_hierarchy_overrides
  ADD PRIMARY KEY (tenant_id, domain_id, connection_id, database_name, schema_name, hierarchy_name);

CREATE INDEX IF NOT EXISTS idx_quantyx_hierarchy_overrides_scope
  ON public.quantyx_hierarchy_overrides (tenant_id, domain_id, connection_id, database_name, schema_name);

ALTER TABLE public.quantyx_context_extractions
  ADD COLUMN IF NOT EXISTS status TEXT NULL;

ALTER TABLE public.quantyx_context_extractions
  ADD COLUMN IF NOT EXISTS notes TEXT NULL;

CREATE TABLE IF NOT EXISTS public.quantyx_dbt_config (
  config_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  connection_id TEXT NULL,
  dbt_project_path TEXT NOT NULL,
  profile_name TEXT NOT NULL,
  target_name TEXT NOT NULL,
  profiles_dir TEXT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_quantyx_dbt_config_lookup
  ON public.quantyx_dbt_config (tenant_id, domain_id, connection_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS public.quantyx_dbt_scaffolds (
  scaffold_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  connection_id TEXT NOT NULL,
  database_name TEXT NOT NULL,
  schema_name TEXT NOT NULL,
  tables JSONB NOT NULL DEFAULT '[]'::jsonb,
  context_id TEXT NULL,
  status TEXT NOT NULL DEFAULT 'draft',
  payload JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_quantyx_dbt_scaffolds_lookup
  ON public.quantyx_dbt_scaffolds (tenant_id, domain_id, connection_id, created_at DESC);

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

CREATE TABLE IF NOT EXISTS public.quantyx_entity_mappings (
  mapping_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  connection_id TEXT NOT NULL,
  database_name TEXT NOT NULL,
  schema_name TEXT NOT NULL,
  tables JSONB NOT NULL DEFAULT '[]'::jsonb,
  candidates JSONB NOT NULL,
  low_confidence_candidates JSONB NOT NULL,
  low_confidence_threshold NUMERIC NOT NULL,
  status TEXT NOT NULL DEFAULT 'draft',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_quantyx_entity_mappings_scope
  ON public.quantyx_entity_mappings (tenant_id, domain_id, connection_id, created_at DESC);

CREATE TABLE IF NOT EXISTS public.quantyx_facts_registry (
  fact_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  connection_id TEXT NOT NULL,
  database_name TEXT NOT NULL,
  schema_name TEXT NOT NULL,
  name TEXT NOT NULL,
  grain TEXT NULL,
  time_column TEXT NULL,
  measures TEXT[] NOT NULL DEFAULT '{}'::text[],
  dimensions TEXT[] NOT NULL DEFAULT '{}'::text[],
  description TEXT NULL,
  status TEXT NOT NULL DEFAULT 'draft',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_quantyx_facts_registry_scope
  ON public.quantyx_facts_registry (tenant_id, domain_id, connection_id, created_at DESC);

CREATE TABLE IF NOT EXISTS public.quantyx_dimensions_registry (
  dimension_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  connection_id TEXT NOT NULL,
  database_name TEXT NOT NULL,
  schema_name TEXT NOT NULL,
  name TEXT NOT NULL,
  keys TEXT[] NOT NULL DEFAULT '{}'::text[],
  attributes TEXT[] NOT NULL DEFAULT '{}'::text[],
  description TEXT NULL,
  status TEXT NOT NULL DEFAULT 'draft',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_quantyx_dimensions_registry_scope
  ON public.quantyx_dimensions_registry (tenant_id, domain_id, connection_id, created_at DESC);

CREATE TABLE IF NOT EXISTS public.quantyx_review_events (
  review_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  connection_id TEXT NOT NULL,
  database_name TEXT NOT NULL,
  schema_name TEXT NOT NULL,
  artifact_type TEXT NOT NULL,
  artifact_id TEXT NOT NULL,
  status TEXT NOT NULL,
  notes TEXT NULL,
  payload JSONB NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_quantyx_review_events_scope
  ON public.quantyx_review_events (tenant_id, domain_id, connection_id, artifact_type, created_at DESC);
