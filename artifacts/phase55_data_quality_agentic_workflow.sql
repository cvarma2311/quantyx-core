-- Phase 55: Data Quality Agentic Workflow, Validation, and Enrichment
-- Idempotent migration for data-quality workflow artifacts, validation rules,
-- reports, dashboards, and governed enrichment.

CREATE TABLE IF NOT EXISTS public.quantyx_data_quality_runs (
  quality_run_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  connection_id TEXT NULL,
  database_name TEXT NULL,
  schema_name TEXT NULL,
  status TEXT NOT NULL DEFAULT 'running',
  overall_trust_score NUMERIC NULL,
  summary_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at TIMESTAMPTZ NULL
);

ALTER TABLE public.quantyx_data_quality_runs ADD COLUMN IF NOT EXISTS connection_id TEXT NULL;
ALTER TABLE public.quantyx_data_quality_runs ADD COLUMN IF NOT EXISTS database_name TEXT NULL;
ALTER TABLE public.quantyx_data_quality_runs ADD COLUMN IF NOT EXISTS schema_name TEXT NULL;
ALTER TABLE public.quantyx_data_quality_runs ADD COLUMN IF NOT EXISTS overall_trust_score NUMERIC NULL;
ALTER TABLE public.quantyx_data_quality_runs ADD COLUMN IF NOT EXISTS summary_json JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE public.quantyx_data_quality_runs ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ NULL;

CREATE INDEX IF NOT EXISTS idx_quantyx_data_quality_runs_scope
  ON public.quantyx_data_quality_runs (tenant_id, domain_id, run_id, status, created_at DESC);

CREATE TABLE IF NOT EXISTS public.quantyx_data_quality_table_artifacts (
  artifact_id TEXT PRIMARY KEY,
  quality_run_id TEXT NOT NULL,
  run_id TEXT NOT NULL,
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  connection_id TEXT NULL,
  database_name TEXT NULL,
  schema_name TEXT NULL,
  table_name TEXT NOT NULL,
  row_count BIGINT NULL,
  trust_score NUMERIC NULL,
  completeness_score NUMERIC NULL,
  validity_score NUMERIC NULL,
  uniqueness_score NUMERIC NULL,
  referential_integrity_score NUMERIC NULL,
  freshness_score NUMERIC NULL,
  duplicate_risk_score NUMERIC NULL,
  severity TEXT NOT NULL DEFAULT 'unknown',
  summary_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (quality_run_id, table_name)
);

ALTER TABLE public.quantyx_data_quality_table_artifacts ADD COLUMN IF NOT EXISTS connection_id TEXT NULL;
ALTER TABLE public.quantyx_data_quality_table_artifacts ADD COLUMN IF NOT EXISTS database_name TEXT NULL;
ALTER TABLE public.quantyx_data_quality_table_artifacts ADD COLUMN IF NOT EXISTS schema_name TEXT NULL;
ALTER TABLE public.quantyx_data_quality_table_artifacts ADD COLUMN IF NOT EXISTS validity_score NUMERIC NULL;
ALTER TABLE public.quantyx_data_quality_table_artifacts ADD COLUMN IF NOT EXISTS uniqueness_score NUMERIC NULL;
ALTER TABLE public.quantyx_data_quality_table_artifacts ADD COLUMN IF NOT EXISTS referential_integrity_score NUMERIC NULL;
ALTER TABLE public.quantyx_data_quality_table_artifacts ADD COLUMN IF NOT EXISTS freshness_score NUMERIC NULL;
ALTER TABLE public.quantyx_data_quality_table_artifacts ADD COLUMN IF NOT EXISTS duplicate_risk_score NUMERIC NULL;
ALTER TABLE public.quantyx_data_quality_table_artifacts ADD COLUMN IF NOT EXISTS severity TEXT NOT NULL DEFAULT 'unknown';
ALTER TABLE public.quantyx_data_quality_table_artifacts ADD COLUMN IF NOT EXISTS summary_json JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE public.quantyx_data_quality_table_artifacts ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

CREATE INDEX IF NOT EXISTS idx_quantyx_data_quality_table_artifacts_scope
  ON public.quantyx_data_quality_table_artifacts (tenant_id, domain_id, run_id, severity, trust_score);

CREATE INDEX IF NOT EXISTS idx_quantyx_data_quality_table_artifacts_quality_run
  ON public.quantyx_data_quality_table_artifacts (quality_run_id, table_name);

CREATE UNIQUE INDEX IF NOT EXISTS uq_quantyx_data_quality_table_artifacts_quality_table
  ON public.quantyx_data_quality_table_artifacts (quality_run_id, table_name);

CREATE TABLE IF NOT EXISTS public.quantyx_data_quality_column_artifacts (
  artifact_id TEXT PRIMARY KEY,
  quality_run_id TEXT NOT NULL,
  run_id TEXT NOT NULL,
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  connection_id TEXT NULL,
  database_name TEXT NULL,
  schema_name TEXT NULL,
  table_name TEXT NOT NULL,
  column_name TEXT NOT NULL,
  data_type TEXT NULL,
  null_count BIGINT NULL,
  null_pct NUMERIC NULL,
  blank_count BIGINT NULL,
  blank_pct NUMERIC NULL,
  distinct_count BIGINT NULL,
  distinct_ratio NUMERIC NULL,
  completeness_score NUMERIC NULL,
  column_trust_score NUMERIC NULL,
  top_values_json JSONB NULL,
  pattern_summary_json JSONB NULL,
  quality_flags_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (quality_run_id, table_name, column_name)
);

ALTER TABLE public.quantyx_data_quality_column_artifacts ADD COLUMN IF NOT EXISTS connection_id TEXT NULL;
ALTER TABLE public.quantyx_data_quality_column_artifacts ADD COLUMN IF NOT EXISTS database_name TEXT NULL;
ALTER TABLE public.quantyx_data_quality_column_artifacts ADD COLUMN IF NOT EXISTS schema_name TEXT NULL;
ALTER TABLE public.quantyx_data_quality_column_artifacts ADD COLUMN IF NOT EXISTS top_values_json JSONB NULL;
ALTER TABLE public.quantyx_data_quality_column_artifacts ADD COLUMN IF NOT EXISTS pattern_summary_json JSONB NULL;
ALTER TABLE public.quantyx_data_quality_column_artifacts ADD COLUMN IF NOT EXISTS quality_flags_json JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE public.quantyx_data_quality_column_artifacts ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

CREATE INDEX IF NOT EXISTS idx_quantyx_data_quality_column_artifacts_scope
  ON public.quantyx_data_quality_column_artifacts (tenant_id, domain_id, run_id, table_name, null_pct DESC);

CREATE INDEX IF NOT EXISTS idx_quantyx_data_quality_column_artifacts_quality_run
  ON public.quantyx_data_quality_column_artifacts (quality_run_id, table_name, column_name);

CREATE UNIQUE INDEX IF NOT EXISTS uq_quantyx_data_quality_column_artifacts_quality_column
  ON public.quantyx_data_quality_column_artifacts (quality_run_id, table_name, column_name);

CREATE TABLE IF NOT EXISTS public.quantyx_data_quality_rules (
  rule_id TEXT PRIMARY KEY,
  quality_run_id TEXT NOT NULL,
  run_id TEXT NOT NULL,
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  connection_id TEXT NULL,
  database_name TEXT NULL,
  schema_name TEXT NULL,
  rule_type TEXT NOT NULL,
  severity TEXT NOT NULL DEFAULT 'warning',
  table_name TEXT NOT NULL,
  column_name TEXT NULL,
  reference_table TEXT NULL,
  reference_column TEXT NULL,
  source_text TEXT NULL,
  executor_kind TEXT NULL,
  execution_plan_json JSONB NULL,
  condition_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  source TEXT NOT NULL DEFAULT 'context_text',
  confidence NUMERIC NULL,
  status TEXT NOT NULL DEFAULT 'active',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE public.quantyx_data_quality_rules ADD COLUMN IF NOT EXISTS source_text TEXT NULL;
ALTER TABLE public.quantyx_data_quality_rules ADD COLUMN IF NOT EXISTS executor_kind TEXT NULL;
ALTER TABLE public.quantyx_data_quality_rules ADD COLUMN IF NOT EXISTS execution_plan_json JSONB NULL;
ALTER TABLE public.quantyx_data_quality_rules ADD COLUMN IF NOT EXISTS reviewed_by TEXT NULL;
ALTER TABLE public.quantyx_data_quality_rules ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMPTZ NULL;
ALTER TABLE public.quantyx_data_quality_rules ADD COLUMN IF NOT EXISTS review_notes TEXT NULL;

CREATE INDEX IF NOT EXISTS idx_quantyx_data_quality_rules_scope
  ON public.quantyx_data_quality_rules (tenant_id, domain_id, run_id, status, severity, rule_type);

CREATE INDEX IF NOT EXISTS idx_quantyx_data_quality_rules_quality_run
  ON public.quantyx_data_quality_rules (quality_run_id, table_name, column_name);

CREATE TABLE IF NOT EXISTS public.quantyx_data_quality_rule_results (
  result_id TEXT PRIMARY KEY,
  rule_id TEXT NOT NULL,
  quality_run_id TEXT NOT NULL,
  run_id TEXT NOT NULL,
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  status TEXT NOT NULL,
  checked_row_count BIGINT NULL,
  violation_count BIGINT NULL,
  violation_pct NUMERIC NULL,
  sample_rows_json JSONB NULL,
  error_message TEXT NULL,
  executed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_quantyx_data_quality_rule_results_scope
  ON public.quantyx_data_quality_rule_results (tenant_id, domain_id, run_id, status, executed_at DESC);

CREATE INDEX IF NOT EXISTS idx_quantyx_data_quality_rule_results_rule
  ON public.quantyx_data_quality_rule_results (rule_id, executed_at DESC);

CREATE TABLE IF NOT EXISTS public.quantyx_data_quality_duplicate_candidates (
  candidate_id TEXT PRIMARY KEY,
  quality_run_id TEXT NOT NULL,
  run_id TEXT NOT NULL,
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  table_name TEXT NOT NULL,
  duplicate_type TEXT NOT NULL,
  match_columns_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  confidence NUMERIC NULL,
  candidate_record_count BIGINT NULL,
  sample_rows_json JSONB NULL,
  cluster_json JSONB NULL,
  review_status TEXT NOT NULL DEFAULT 'needs_review',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_quantyx_data_quality_duplicate_candidates_scope
  ON public.quantyx_data_quality_duplicate_candidates (tenant_id, domain_id, run_id, table_name, review_status);

CREATE TABLE IF NOT EXISTS public.quantyx_data_quality_enrichment_opportunities (
  opportunity_id TEXT PRIMARY KEY,
  quality_run_id TEXT NOT NULL,
  run_id TEXT NOT NULL,
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  table_name TEXT NOT NULL,
  target_column TEXT NOT NULL,
  source_columns_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  missing_count BIGINT NULL,
  candidate_method TEXT NULL,
  requires_external_lookup BOOLEAN NOT NULL DEFAULT false,
  requires_user_approval BOOLEAN NOT NULL DEFAULT true,
  confidence NUMERIC NULL,
  question TEXT NULL,
  status TEXT NOT NULL DEFAULT 'needs_user_approval',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_quantyx_data_quality_enrichment_opportunities_scope
  ON public.quantyx_data_quality_enrichment_opportunities (tenant_id, domain_id, run_id, status, table_name);

CREATE TABLE IF NOT EXISTS public.quantyx_data_quality_enrichment_proposals (
  proposal_id TEXT PRIMARY KEY,
  opportunity_id TEXT NOT NULL,
  quality_run_id TEXT NOT NULL,
  run_id TEXT NOT NULL,
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'proposed',
  matched_count BIGINT NULL,
  unmatched_count BIGINT NULL,
  source_references_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  proposed_values_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  approved_by TEXT NULL,
  approved_at TIMESTAMPTZ NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_quantyx_data_quality_enrichment_proposals_scope
  ON public.quantyx_data_quality_enrichment_proposals (tenant_id, domain_id, run_id, status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_quantyx_data_quality_enrichment_proposals_opportunity
  ON public.quantyx_data_quality_enrichment_proposals (opportunity_id, created_at DESC);

CREATE TABLE IF NOT EXISTS public.quantyx_data_quality_reports (
  report_id TEXT PRIMARY KEY,
  quality_run_id TEXT NOT NULL,
  run_id TEXT NOT NULL,
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  report_type TEXT NOT NULL DEFAULT 'excel',
  file_name TEXT NOT NULL,
  mime_type TEXT NOT NULL,
  storage_uri TEXT NULL,
  summary_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_quantyx_data_quality_reports_scope
  ON public.quantyx_data_quality_reports (tenant_id, domain_id, run_id, report_type, created_at DESC);
