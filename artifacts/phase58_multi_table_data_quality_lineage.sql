-- Phase 58: Multi-table data quality stages, joins, lineage, and final dataset reporting
-- Idempotent migration for stage planning and join artifact persistence.

CREATE TABLE IF NOT EXISTS public.quantyx_data_quality_dataset_stages (
  stage_id TEXT PRIMARY KEY,
  quality_run_id TEXT NOT NULL,
  run_id TEXT NOT NULL,
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  stage_seq INTEGER NOT NULL,
  stage_name TEXT NOT NULL,
  stage_type TEXT NOT NULL,
  input_row_count BIGINT NULL,
  output_row_count BIGINT NULL,
  rejected_row_count BIGINT NULL,
  summary_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE public.quantyx_data_quality_dataset_stages ADD COLUMN IF NOT EXISTS input_row_count BIGINT NULL;
ALTER TABLE public.quantyx_data_quality_dataset_stages ADD COLUMN IF NOT EXISTS output_row_count BIGINT NULL;
ALTER TABLE public.quantyx_data_quality_dataset_stages ADD COLUMN IF NOT EXISTS rejected_row_count BIGINT NULL;
ALTER TABLE public.quantyx_data_quality_dataset_stages ADD COLUMN IF NOT EXISTS summary_json JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE public.quantyx_data_quality_dataset_stages ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

CREATE INDEX IF NOT EXISTS idx_quantyx_data_quality_dataset_stages_scope
  ON public.quantyx_data_quality_dataset_stages (tenant_id, domain_id, run_id, stage_seq, created_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS uq_quantyx_data_quality_dataset_stages_quality_stage
  ON public.quantyx_data_quality_dataset_stages (quality_run_id, stage_name);

CREATE TABLE IF NOT EXISTS public.quantyx_data_quality_join_artifacts (
  join_artifact_id TEXT PRIMARY KEY,
  quality_run_id TEXT NOT NULL,
  run_id TEXT NOT NULL,
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  join_name TEXT NOT NULL,
  left_table TEXT NOT NULL,
  right_table TEXT NOT NULL,
  join_type TEXT NOT NULL,
  join_keys_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  matched_row_count BIGINT NULL,
  unmatched_left_row_count BIGINT NULL,
  unmatched_right_row_count BIGINT NULL,
  duplicate_match_count BIGINT NULL,
  summary_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE public.quantyx_data_quality_join_artifacts ADD COLUMN IF NOT EXISTS join_keys_json JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE public.quantyx_data_quality_join_artifacts ADD COLUMN IF NOT EXISTS matched_row_count BIGINT NULL;
ALTER TABLE public.quantyx_data_quality_join_artifacts ADD COLUMN IF NOT EXISTS unmatched_left_row_count BIGINT NULL;
ALTER TABLE public.quantyx_data_quality_join_artifacts ADD COLUMN IF NOT EXISTS unmatched_right_row_count BIGINT NULL;
ALTER TABLE public.quantyx_data_quality_join_artifacts ADD COLUMN IF NOT EXISTS duplicate_match_count BIGINT NULL;
ALTER TABLE public.quantyx_data_quality_join_artifacts ADD COLUMN IF NOT EXISTS summary_json JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE public.quantyx_data_quality_join_artifacts ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

CREATE INDEX IF NOT EXISTS idx_quantyx_data_quality_join_artifacts_scope
  ON public.quantyx_data_quality_join_artifacts (tenant_id, domain_id, run_id, created_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS uq_quantyx_data_quality_join_artifacts_quality_join
  ON public.quantyx_data_quality_join_artifacts (quality_run_id, join_name);

CREATE TABLE IF NOT EXISTS public.quantyx_data_quality_stage_row_outcomes (
  outcome_id TEXT PRIMARY KEY,
  quality_run_id TEXT NOT NULL,
  run_id TEXT NOT NULL,
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  stage_id TEXT NOT NULL,
  stage_name TEXT NOT NULL,
  outcome_type TEXT NOT NULL,
  row_lineage_id TEXT NULL,
  row_ref TEXT NULL,
  source_table TEXT NULL,
  source_key_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  reason_code TEXT NULL,
  reason_detail TEXT NULL,
  row_data_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE public.quantyx_data_quality_stage_row_outcomes ADD COLUMN IF NOT EXISTS row_ref TEXT NULL;
ALTER TABLE public.quantyx_data_quality_stage_row_outcomes ADD COLUMN IF NOT EXISTS row_lineage_id TEXT NULL;
ALTER TABLE public.quantyx_data_quality_stage_row_outcomes ADD COLUMN IF NOT EXISTS source_table TEXT NULL;
ALTER TABLE public.quantyx_data_quality_stage_row_outcomes ADD COLUMN IF NOT EXISTS source_key_json JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE public.quantyx_data_quality_stage_row_outcomes ADD COLUMN IF NOT EXISTS reason_code TEXT NULL;
ALTER TABLE public.quantyx_data_quality_stage_row_outcomes ADD COLUMN IF NOT EXISTS reason_detail TEXT NULL;
ALTER TABLE public.quantyx_data_quality_stage_row_outcomes ADD COLUMN IF NOT EXISTS row_data_json JSONB NOT NULL DEFAULT '{}'::jsonb;

CREATE INDEX IF NOT EXISTS idx_quantyx_data_quality_stage_row_outcomes_scope
  ON public.quantyx_data_quality_stage_row_outcomes (tenant_id, domain_id, run_id, stage_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_quantyx_data_quality_stage_row_outcomes_lineage
  ON public.quantyx_data_quality_stage_row_outcomes (tenant_id, domain_id, run_id, row_lineage_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_quantyx_data_quality_stage_row_outcomes_type
  ON public.quantyx_data_quality_stage_row_outcomes (tenant_id, domain_id, run_id, outcome_type, created_at DESC);

CREATE TABLE IF NOT EXISTS public.quantyx_data_quality_lineage_edges (
  edge_id TEXT PRIMARY KEY,
  quality_run_id TEXT NOT NULL,
  run_id TEXT NOT NULL,
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  row_lineage_id TEXT NOT NULL,
  from_stage_id TEXT NULL,
  from_stage_name TEXT NULL,
  to_stage_id TEXT NULL,
  to_stage_name TEXT NULL,
  edge_type TEXT NOT NULL,
  summary_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE public.quantyx_data_quality_lineage_edges ADD COLUMN IF NOT EXISTS row_lineage_id TEXT NOT NULL DEFAULT '';
ALTER TABLE public.quantyx_data_quality_lineage_edges ADD COLUMN IF NOT EXISTS from_stage_id TEXT NULL;
ALTER TABLE public.quantyx_data_quality_lineage_edges ADD COLUMN IF NOT EXISTS from_stage_name TEXT NULL;
ALTER TABLE public.quantyx_data_quality_lineage_edges ADD COLUMN IF NOT EXISTS to_stage_id TEXT NULL;
ALTER TABLE public.quantyx_data_quality_lineage_edges ADD COLUMN IF NOT EXISTS to_stage_name TEXT NULL;
ALTER TABLE public.quantyx_data_quality_lineage_edges ADD COLUMN IF NOT EXISTS edge_type TEXT NOT NULL DEFAULT 'transition';
ALTER TABLE public.quantyx_data_quality_lineage_edges ADD COLUMN IF NOT EXISTS summary_json JSONB NOT NULL DEFAULT '{}'::jsonb;

CREATE INDEX IF NOT EXISTS idx_quantyx_data_quality_lineage_edges_scope
  ON public.quantyx_data_quality_lineage_edges (tenant_id, domain_id, run_id, row_lineage_id, created_at DESC);

CREATE TABLE IF NOT EXISTS public.quantyx_data_quality_final_dataset_artifacts (
  artifact_id TEXT PRIMARY KEY,
  quality_run_id TEXT NOT NULL,
  run_id TEXT NOT NULL,
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  final_stage_name TEXT NULL,
  final_row_count BIGINT NULL,
  total_rejected_row_count BIGINT NULL,
  readiness_status TEXT NULL,
  summary_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE public.quantyx_data_quality_final_dataset_artifacts ADD COLUMN IF NOT EXISTS final_stage_name TEXT NULL;
ALTER TABLE public.quantyx_data_quality_final_dataset_artifacts ADD COLUMN IF NOT EXISTS final_row_count BIGINT NULL;
ALTER TABLE public.quantyx_data_quality_final_dataset_artifacts ADD COLUMN IF NOT EXISTS total_rejected_row_count BIGINT NULL;
ALTER TABLE public.quantyx_data_quality_final_dataset_artifacts ADD COLUMN IF NOT EXISTS readiness_status TEXT NULL;
ALTER TABLE public.quantyx_data_quality_final_dataset_artifacts ADD COLUMN IF NOT EXISTS summary_json JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE public.quantyx_data_quality_final_dataset_artifacts ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

CREATE UNIQUE INDEX IF NOT EXISTS uq_quantyx_data_quality_final_dataset_artifacts_quality_run
  ON public.quantyx_data_quality_final_dataset_artifacts (quality_run_id);

CREATE INDEX IF NOT EXISTS idx_quantyx_data_quality_final_dataset_artifacts_scope
  ON public.quantyx_data_quality_final_dataset_artifacts (tenant_id, domain_id, run_id, created_at DESC);
