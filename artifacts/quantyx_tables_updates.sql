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

UPDATE public.quantyx_entity_mappings
  SET tables = COALESCE(tables, '[]'::jsonb)
  WHERE tables IS NULL;

ALTER TABLE public.quantyx_entity_mappings
  ALTER COLUMN tables SET DEFAULT '[]'::jsonb;
