ALTER TABLE public.quantyx_entity_overrides
  ADD COLUMN IF NOT EXISTS source_context_id TEXT NULL;

ALTER TABLE public.quantyx_hierarchy_overrides
  ADD COLUMN IF NOT EXISTS source_context_id TEXT NULL;

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
