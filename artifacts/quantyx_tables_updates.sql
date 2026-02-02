ALTER TABLE public.quantyx_entity_overrides
  ADD COLUMN IF NOT EXISTS source_context_id TEXT NULL;

ALTER TABLE public.quantyx_hierarchy_overrides
  ADD COLUMN IF NOT EXISTS source_context_id TEXT NULL;

ALTER TABLE public.quantyx_context_extractions
  ADD COLUMN IF NOT EXISTS status TEXT NULL;

ALTER TABLE public.quantyx_context_extractions
  ADD COLUMN IF NOT EXISTS notes TEXT NULL;
