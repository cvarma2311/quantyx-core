-- Quantyx operational metadata tables
-- Schema: public
-- Run this script once at the end of implementation to create all tables.
-- Version: 1
-- Last updated: 2025-02-14

CREATE TABLE IF NOT EXISTS public.quantyx_query_audit (
  query_id TEXT PRIMARY KEY,
  asked_by TEXT,
  asked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  domain_id TEXT,
  scenario_id TEXT,
  question TEXT,
  resolved_metrics TEXT[],
  resolved_dimensions TEXT[],
  resolved_filters JSONB,
  sql_text TEXT,
  sql_hash TEXT,
  execution_ms INTEGER,
  row_count INTEGER,
  error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_quantyx_query_audit_domain_time
  ON public.quantyx_query_audit (domain_id, asked_at DESC);

CREATE INDEX IF NOT EXISTS idx_quantyx_query_audit_scenario
  ON public.quantyx_query_audit (scenario_id);


CREATE TABLE IF NOT EXISTS public.quantyx_insight_events (
  insight_id TEXT PRIMARY KEY,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  domain_id TEXT,
  scenario_id TEXT,
  insight_type TEXT,
  headline TEXT,
  severity TEXT,
  confidence NUMERIC(5,4),
  entity_scope JSONB,
  metric_refs TEXT[],
  drivers JSONB,
  recommended_actions JSONB,
  supporting_query_ids TEXT[]
);

CREATE INDEX IF NOT EXISTS idx_quantyx_insight_events_domain_time
  ON public.quantyx_insight_events (domain_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_quantyx_insight_events_scenario
  ON public.quantyx_insight_events (scenario_id);

CREATE INDEX IF NOT EXISTS idx_quantyx_insight_events_type_time
  ON public.quantyx_insight_events (insight_type, created_at DESC);


CREATE TABLE IF NOT EXISTS public.quantyx_scenario (
  scenario_id TEXT PRIMARY KEY,
  domain_id TEXT NOT NULL,
  name TEXT NOT NULL,
  description TEXT,
  status TEXT NOT NULL DEFAULT 'live',
  is_baseline BOOLEAN NOT NULL DEFAULT false,
  created_by TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_quantyx_scenario_domain
  ON public.quantyx_scenario (domain_id);


CREATE TABLE IF NOT EXISTS public.quantyx_scenario_inputs (
  scenario_id TEXT NOT NULL REFERENCES public.quantyx_scenario(scenario_id),
  entity_type TEXT,
  entity_id TEXT,
  parameter TEXT NOT NULL,
  value JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_quantyx_scenario_inputs_scenario
  ON public.quantyx_scenario_inputs (scenario_id);


CREATE TABLE IF NOT EXISTS public.quantyx_scenario_outputs (
  scenario_id TEXT NOT NULL REFERENCES public.quantyx_scenario(scenario_id),
  metric_key TEXT NOT NULL,
  entity_type TEXT,
  entity_id TEXT,
  ds DATE,
  value NUMERIC,
  computed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_quantyx_scenario_outputs_scenario
  ON public.quantyx_scenario_outputs (scenario_id);

CREATE INDEX IF NOT EXISTS idx_quantyx_scenario_outputs_metric_ds
  ON public.quantyx_scenario_outputs (metric_key, ds);


CREATE TABLE IF NOT EXISTS public.quantyx_action_feedback (
  action_id TEXT PRIMARY KEY REFERENCES public.quantyx_actions(action_id),
  source_insight_id TEXT,
  domain_id TEXT,
  scenario_id TEXT,
  status TEXT,
  outcome TEXT,
  notes TEXT,
  impact_window JSONB,
  assigned_to TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_quantyx_action_feedback_domain_time
  ON public.quantyx_action_feedback (domain_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_quantyx_action_feedback_scenario
  ON public.quantyx_action_feedback (scenario_id);


CREATE TABLE IF NOT EXISTS public.quantyx_actions (
  action_id TEXT PRIMARY KEY,
  source_insight_id TEXT,
  domain_id TEXT,
  scenario_id TEXT,
  headline TEXT,
  severity TEXT,
  status TEXT,
  assigned_to TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_quantyx_actions_domain_time
  ON public.quantyx_actions (domain_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_quantyx_actions_scenario
  ON public.quantyx_actions (scenario_id);

CREATE INDEX IF NOT EXISTS idx_quantyx_actions_status
  ON public.quantyx_actions (status);


CREATE TABLE IF NOT EXISTS public.quantyx_timeseries_cache (
  cache_id TEXT PRIMARY KEY,
  metric_name TEXT NOT NULL,
  dimension_hash TEXT,
  grain TEXT NOT NULL,
  period_start DATE NOT NULL,
  actual NUMERIC,
  baseline NUMERIC,
  deviation NUMERIC,
  is_anomaly BOOLEAN NOT NULL DEFAULT false,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_quantyx_timeseries_cache_metric_time
  ON public.quantyx_timeseries_cache (metric_name, grain, period_start DESC);

CREATE INDEX IF NOT EXISTS idx_quantyx_timeseries_cache_dimension
  ON public.quantyx_timeseries_cache (dimension_hash);


CREATE TABLE IF NOT EXISTS public.quantyx_schema_scans (
  scan_id TEXT PRIMARY KEY,
  tenant_id TEXT,
  domain_id TEXT,
  requested_by TEXT,
  status TEXT NOT NULL DEFAULT 'completed',
  request_payload JSONB NOT NULL,
  result_payload JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_quantyx_schema_scans_domain_time
  ON public.quantyx_schema_scans (domain_id, created_at DESC);


CREATE TABLE IF NOT EXISTS public.quantyx_schema_graph_artifacts (
  artifact_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  run_id TEXT NOT NULL,
  connection_id TEXT NOT NULL,
  database_name TEXT NOT NULL,
  schema_name TEXT NOT NULL,
  artifact_key TEXT NOT NULL,
  version_no INTEGER NOT NULL DEFAULT 1,
  is_current BOOLEAN NOT NULL DEFAULT true,
  lifecycle_status TEXT NOT NULL DEFAULT 'active',
  source_type TEXT NOT NULL DEFAULT 'agentic',
  graph_json JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, domain_id, run_id, connection_id, database_name, schema_name)
);

CREATE INDEX IF NOT EXISTS idx_quantyx_schema_graph_artifacts_scope
  ON public.quantyx_schema_graph_artifacts (tenant_id, domain_id, run_id, connection_id, database_name, schema_name);


CREATE TABLE IF NOT EXISTS public.quantyx_table_profile_artifacts (
  artifact_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  run_id TEXT NOT NULL,
  connection_id TEXT NOT NULL,
  database_name TEXT NOT NULL,
  schema_name TEXT NOT NULL,
  artifact_key TEXT NOT NULL,
  version_no INTEGER NOT NULL DEFAULT 1,
  is_current BOOLEAN NOT NULL DEFAULT true,
  lifecycle_status TEXT NOT NULL DEFAULT 'active',
  source_type TEXT NOT NULL DEFAULT 'agentic',
  profiling_json JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, domain_id, run_id, connection_id, database_name, schema_name)
);

CREATE INDEX IF NOT EXISTS idx_quantyx_table_profile_artifacts_scope
  ON public.quantyx_table_profile_artifacts (tenant_id, domain_id, run_id, connection_id, database_name, schema_name);


CREATE TABLE IF NOT EXISTS public.quantyx_join_registry (
  join_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  run_id TEXT NOT NULL,
  connection_id TEXT NOT NULL,
  database_name TEXT NOT NULL,
  schema_name TEXT NOT NULL,
  left_table TEXT NOT NULL,
  left_key TEXT NOT NULL,
  right_table TEXT NOT NULL,
  right_key TEXT NOT NULL,
  relationship TEXT NULL,
  confidence DOUBLE PRECISION NULL,
  coverage_ratio DOUBLE PRECISION NULL,
  coverage_total BIGINT NULL,
  coverage_matched BIGINT NULL,
  uniqueness_check JSONB NULL,
  coverage_check JSONB NULL,
  metadata JSONB NULL,
  artifact_key TEXT NOT NULL,
  version_no INTEGER NOT NULL DEFAULT 1,
  is_current BOOLEAN NOT NULL DEFAULT true,
  lifecycle_status TEXT NOT NULL DEFAULT 'active',
  source_type TEXT NOT NULL DEFAULT 'agentic',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_quantyx_join_registry_scope
  ON public.quantyx_join_registry (tenant_id, domain_id, run_id, connection_id, database_name, schema_name);


CREATE TABLE IF NOT EXISTS public.quantyx_model_registry (
  model_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  run_id TEXT NOT NULL,
  connection_id TEXT NOT NULL,
  database_name TEXT NOT NULL,
  schema_name TEXT NOT NULL,
  table_name TEXT NOT NULL,
  model_type TEXT NULL,
  grain TEXT NULL,
  time_column TEXT NULL,
  confidence DOUBLE PRECISION NULL,
  metadata JSONB NULL,
  artifact_key TEXT NOT NULL,
  version_no INTEGER NOT NULL DEFAULT 1,
  is_current BOOLEAN NOT NULL DEFAULT true,
  lifecycle_status TEXT NOT NULL DEFAULT 'active',
  source_type TEXT NOT NULL DEFAULT 'agentic',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_quantyx_model_registry_scope
  ON public.quantyx_model_registry (tenant_id, domain_id, run_id, connection_id, database_name, schema_name);


CREATE TABLE IF NOT EXISTS public.quantyx_connection_registry (
  connection_id TEXT PRIMARY KEY,
  tenant_id TEXT,
  domain_id TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_quantyx_connection_registry_domain
  ON public.quantyx_connection_registry (domain_id);

CREATE TABLE IF NOT EXISTS public.quantyx_connection_scopes (
  connection_id TEXT NOT NULL REFERENCES public.quantyx_connection_registry(connection_id),
  database_name TEXT NOT NULL,
  schema_name TEXT NOT NULL,
  PRIMARY KEY (connection_id, database_name, schema_name)
);

CREATE INDEX IF NOT EXISTS idx_quantyx_connection_scopes_db
  ON public.quantyx_connection_scopes (database_name, schema_name);


DO $$
BEGIN
  CREATE TYPE public.quantyx_job_status AS ENUM (
    'queued',
    'running',
    'completed',
    'failed',
    'canceled'
  );
EXCEPTION
  WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS public.quantyx_job_scopes (
  scope_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  domain_id TEXT NULL,
  connection_id TEXT NULL,
  database_name TEXT NULL,
  schema_name TEXT NULL,
  tables JSONB NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_quantyx_job_scopes_tenant
  ON public.quantyx_job_scopes (tenant_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_quantyx_job_scopes_conn
  ON public.quantyx_job_scopes (connection_id, database_name, schema_name);

CREATE TABLE IF NOT EXISTS public.quantyx_jobs (
  job_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  scope_id TEXT NULL REFERENCES public.quantyx_job_scopes(scope_id),
  job_type TEXT NOT NULL,
  status public.quantyx_job_status NOT NULL DEFAULT 'queued',
  progress_pct NUMERIC NULL,
  progress_stage TEXT NULL,
  request_payload JSONB NOT NULL,
  result_payload JSONB NULL,
  error_message TEXT NULL,
  idempotency_key TEXT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  started_at TIMESTAMPTZ NULL,
  completed_at TIMESTAMPTZ NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_quantyx_jobs_tenant_time
  ON public.quantyx_jobs (tenant_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_quantyx_jobs_status
  ON public.quantyx_jobs (status, created_at ASC);

CREATE UNIQUE INDEX IF NOT EXISTS idx_quantyx_jobs_idempotency
  ON public.quantyx_jobs (tenant_id, job_type, idempotency_key)
  WHERE idempotency_key IS NOT NULL;

CREATE TABLE IF NOT EXISTS public.quantyx_job_events (
  event_id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL REFERENCES public.quantyx_jobs(job_id),
  status public.quantyx_job_status NOT NULL,
  message TEXT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_quantyx_job_events_job
  ON public.quantyx_job_events (job_id, created_at DESC);


CREATE TABLE IF NOT EXISTS public.quantyx_tenant_domains (
  tenant_id TEXT PRIMARY KEY,
  domain_id TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);


CREATE TABLE IF NOT EXISTS public.quantyx_metrics_registry (
  metric_id TEXT PRIMARY KEY,
  tenant_id TEXT NULL,
  metric_name TEXT,
  domain_id TEXT,
  connection_id TEXT NULL,
  database_name TEXT NULL,
  schema_name TEXT NULL,
  display_name TEXT,
  description TEXT,
  type TEXT,
  unit TEXT,
  confidence DOUBLE PRECISION,
  additive BOOLEAN,
  grain TEXT,
  dimensions TEXT[],
  dataset_id TEXT,
  source_model TEXT,
  source_schema TEXT,
  sql TEXT,
  owner TEXT,
  version TEXT,
  deprecated BOOLEAN NOT NULL DEFAULT false,
  artifact_key TEXT NULL,
  version_no INTEGER NOT NULL DEFAULT 1,
  is_current BOOLEAN NOT NULL DEFAULT true,
  lifecycle_status TEXT NOT NULL DEFAULT 'suggested',
  source_type TEXT NOT NULL DEFAULT 'system',
  source_run_id TEXT NULL,
  semantic_metadata JSONB NULL,
  change_reason TEXT NULL,
  approved_by TEXT NULL,
  approved_at TIMESTAMPTZ NULL,
  supersedes_version_no INTEGER NULL,
  created_by TEXT NULL,
  updated_by TEXT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE public.quantyx_metrics_registry
  ADD COLUMN IF NOT EXISTS metric_name TEXT;
ALTER TABLE public.quantyx_metrics_registry
  ADD COLUMN IF NOT EXISTS confidence DOUBLE PRECISION;
ALTER TABLE public.quantyx_metrics_registry
  ADD COLUMN IF NOT EXISTS additive BOOLEAN;
ALTER TABLE public.quantyx_metrics_registry
  ADD COLUMN IF NOT EXISTS dimensions TEXT[];

CREATE INDEX IF NOT EXISTS idx_quantyx_metrics_registry_domain
  ON public.quantyx_metrics_registry (domain_id);

CREATE INDEX IF NOT EXISTS idx_quantyx_metrics_registry_scope
  ON public.quantyx_metrics_registry (tenant_id, domain_id, connection_id, database_name, schema_name);
CREATE UNIQUE INDEX IF NOT EXISTS uq_quantyx_metrics_registry_current
  ON public.quantyx_metrics_registry (tenant_id, domain_id, connection_id, database_name, schema_name, artifact_key)
  WHERE is_current = true;
CREATE UNIQUE INDEX IF NOT EXISTS uq_quantyx_metrics_registry_version
  ON public.quantyx_metrics_registry (tenant_id, domain_id, connection_id, database_name, schema_name, artifact_key, version_no);


CREATE TABLE IF NOT EXISTS public.quantyx_entity_overrides (
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  connection_id TEXT NOT NULL,
  database_name TEXT NOT NULL,
  schema_name TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  description TEXT,
  join_key TEXT,
  examples TEXT[],
  source_context_id TEXT NULL,
  artifact_key TEXT NULL,
  version_no INTEGER NOT NULL DEFAULT 1,
  is_current BOOLEAN NOT NULL DEFAULT true,
  lifecycle_status TEXT NOT NULL DEFAULT 'live',
  source_type TEXT NOT NULL DEFAULT 'system',
  source_run_id TEXT NULL,
  change_reason TEXT NULL,
  approved_by TEXT NULL,
  approved_at TIMESTAMPTZ NULL,
  supersedes_version_no INTEGER NULL,
  created_by TEXT NULL,
  updated_by TEXT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, domain_id, connection_id, database_name, schema_name, entity_id),
  CHECK (connection_id <> 'global' AND database_name <> 'global' AND schema_name <> 'global')
);

CREATE INDEX IF NOT EXISTS idx_quantyx_entity_overrides_domain
  ON public.quantyx_entity_overrides (tenant_id, domain_id);

CREATE INDEX IF NOT EXISTS idx_quantyx_entity_overrides_scope
  ON public.quantyx_entity_overrides (tenant_id, domain_id, connection_id, database_name, schema_name);
CREATE UNIQUE INDEX IF NOT EXISTS uq_quantyx_entity_overrides_current
  ON public.quantyx_entity_overrides (tenant_id, domain_id, connection_id, database_name, schema_name, artifact_key)
  WHERE is_current = true;
CREATE UNIQUE INDEX IF NOT EXISTS uq_quantyx_entity_overrides_version
  ON public.quantyx_entity_overrides (tenant_id, domain_id, connection_id, database_name, schema_name, artifact_key, version_no);


CREATE TABLE IF NOT EXISTS public.quantyx_hierarchy_overrides (
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  connection_id TEXT NOT NULL,
  database_name TEXT NOT NULL,
  schema_name TEXT NOT NULL,
  context_id TEXT NOT NULL,
  hierarchy_name TEXT NOT NULL,
  hierarchy_group TEXT NULL,
  levels TEXT[] NOT NULL,
  description TEXT,
  source_context_id TEXT NULL,
  artifact_key TEXT NULL,
  version_no INTEGER NOT NULL DEFAULT 1,
  is_current BOOLEAN NOT NULL DEFAULT true,
  lifecycle_status TEXT NOT NULL DEFAULT 'live',
  source_type TEXT NOT NULL DEFAULT 'system',
  source_run_id TEXT NULL,
  change_reason TEXT NULL,
  approved_by TEXT NULL,
  approved_at TIMESTAMPTZ NULL,
  supersedes_version_no INTEGER NULL,
  created_by TEXT NULL,
  updated_by TEXT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, domain_id, connection_id, database_name, schema_name, context_id, hierarchy_name),
  CHECK (connection_id <> 'global' AND database_name <> 'global' AND schema_name <> 'global')
);

CREATE INDEX IF NOT EXISTS idx_quantyx_hierarchy_overrides_domain
  ON public.quantyx_hierarchy_overrides (tenant_id, domain_id);

CREATE INDEX IF NOT EXISTS idx_quantyx_hierarchy_overrides_scope
  ON public.quantyx_hierarchy_overrides (tenant_id, domain_id, connection_id, database_name, schema_name, context_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_quantyx_hierarchy_overrides_current
  ON public.quantyx_hierarchy_overrides (tenant_id, domain_id, connection_id, database_name, schema_name, artifact_key)
  WHERE is_current = true;
CREATE UNIQUE INDEX IF NOT EXISTS uq_quantyx_hierarchy_overrides_version
  ON public.quantyx_hierarchy_overrides (tenant_id, domain_id, connection_id, database_name, schema_name, artifact_key, version_no);


CREATE TABLE IF NOT EXISTS public.quantyx_business_context (
  context_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  connection_id TEXT NULL,
  database_name TEXT NULL,
  schema_name TEXT NULL,
  source_type TEXT NOT NULL,
  source_title TEXT NULL,
  raw_text TEXT NOT NULL,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  status TEXT NOT NULL DEFAULT 'submitted',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_quantyx_business_context_tenant
  ON public.quantyx_business_context (tenant_id, domain_id, source_type, status);

CREATE INDEX IF NOT EXISTS idx_quantyx_business_context_conn
  ON public.quantyx_business_context (connection_id, database_name, schema_name);


CREATE TABLE IF NOT EXISTS public.quantyx_context_scope_active (
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  connection_id TEXT NULL,
  database_name TEXT NULL,
  schema_name TEXT NULL,
  context_id TEXT NOT NULL,
  is_active BOOLEAN NOT NULL DEFAULT true,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, domain_id, connection_id, database_name, schema_name, context_id)
);

CREATE INDEX IF NOT EXISTS idx_context_scope_active_context
  ON public.quantyx_context_scope_active (context_id);

CREATE INDEX IF NOT EXISTS idx_context_scope_active_scope
  ON public.quantyx_context_scope_active (tenant_id, domain_id, connection_id, database_name, schema_name, is_active);


CREATE TABLE IF NOT EXISTS public.quantyx_context_extractions (
  extraction_id TEXT PRIMARY KEY,
  context_id TEXT NOT NULL,
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  extraction_type TEXT NOT NULL,
  payload JSONB NOT NULL,
  llm_model TEXT NULL,
  confidence NUMERIC NULL,
  agent_name TEXT NULL,
  parent_job_id TEXT NULL,
  status TEXT NULL,
  notes TEXT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  FOREIGN KEY (context_id) REFERENCES public.quantyx_business_context(context_id)
);

CREATE INDEX IF NOT EXISTS idx_quantyx_context_extractions_tenant
  ON public.quantyx_context_extractions (tenant_id, domain_id, extraction_type);


CREATE TABLE IF NOT EXISTS public.quantyx_context_extraction_agents (
  agent_run_id TEXT PRIMARY KEY,
  extraction_id TEXT NOT NULL,
  agent_name TEXT NOT NULL,
  payload JSONB NOT NULL,
  confidence NUMERIC NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);


CREATE TABLE IF NOT EXISTS public.quantyx_glossary_terms (
  term_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  term TEXT NOT NULL,
  normalized_term TEXT NOT NULL,
  definition TEXT NULL,
  synonyms JSONB NOT NULL DEFAULT '[]'::jsonb,
  abbreviations JSONB NOT NULL DEFAULT '[]'::jsonb,
  lifecycle_status TEXT NOT NULL DEFAULT 'suggested',
  source_context_id TEXT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_quantyx_glossary_terms_lookup
  ON public.quantyx_glossary_terms (tenant_id, domain_id, normalized_term);


CREATE TABLE IF NOT EXISTS public.quantyx_context_files (
  file_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  filename TEXT NOT NULL,
  content_type TEXT NULL,
  extracted_text TEXT NOT NULL,
  raw_bytes BYTEA NOT NULL,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_quantyx_context_files_tenant
  ON public.quantyx_context_files (tenant_id, domain_id, created_at DESC);


CREATE TABLE IF NOT EXISTS public.quantyx_context_file_links (
  context_id TEXT NOT NULL,
  file_id TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (context_id, file_id),
  FOREIGN KEY (context_id) REFERENCES public.quantyx_business_context(context_id),
  FOREIGN KEY (file_id) REFERENCES public.quantyx_context_files(file_id)
);


CREATE TABLE IF NOT EXISTS public.quantyx_dbt_manifest (
  manifest_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  connection_id TEXT NULL,
  dbt_project_path TEXT NOT NULL,
  profile_name TEXT NOT NULL,
  target_name TEXT NOT NULL,
  manifest_json JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_quantyx_dbt_manifest_tenant
  ON public.quantyx_dbt_manifest (tenant_id, domain_id, created_at DESC);


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


CREATE TABLE IF NOT EXISTS public.quantyx_facts_registry (
  fact_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  connection_id TEXT NOT NULL,
  database_name TEXT NOT NULL,
  schema_name TEXT NOT NULL,
  table_name TEXT NOT NULL,
  time_column TEXT NULL,
  grain TEXT NULL,
  measures JSONB NULL,
  dimensions JSONB NULL,
  description TEXT NULL,
  artifact_key TEXT NULL,
  version_no INTEGER NOT NULL DEFAULT 1,
  is_current BOOLEAN NOT NULL DEFAULT true,
  lifecycle_status TEXT NOT NULL DEFAULT 'live',
  source_type TEXT NOT NULL DEFAULT 'system',
  source_run_id TEXT NULL,
  change_reason TEXT NULL,
  approved_by TEXT NULL,
  approved_at TIMESTAMPTZ NULL,
  supersedes_version_no INTEGER NULL,
  created_by TEXT NULL,
  updated_by TEXT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.quantyx_entity_mapping_agents (
  agent_run_id TEXT PRIMARY KEY,
  job_id TEXT NULL,
  mapping_id TEXT NULL,
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  connection_id TEXT NOT NULL,
  database_name TEXT NOT NULL,
  schema_name TEXT NOT NULL,
  table_name TEXT NULL,
  chunk_index INTEGER NULL,
  chunk_label TEXT NULL,
  request_payload JSONB NOT NULL,
  response_payload JSONB NULL,
  error_message TEXT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_quantyx_entity_mapping_agents_tenant
  ON public.quantyx_entity_mapping_agents (tenant_id, domain_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_quantyx_entity_mapping_agents_job
  ON public.quantyx_entity_mapping_agents (job_id, created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS uq_quantyx_facts_registry_current
  ON public.quantyx_facts_registry (tenant_id, domain_id, connection_id, database_name, schema_name, artifact_key)
  WHERE is_current = true;
CREATE UNIQUE INDEX IF NOT EXISTS uq_quantyx_facts_registry_version
  ON public.quantyx_facts_registry (tenant_id, domain_id, connection_id, database_name, schema_name, artifact_key, version_no);

CREATE TABLE IF NOT EXISTS public.quantyx_dimensions_registry (
  dimension_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  connection_id TEXT NOT NULL,
  database_name TEXT NOT NULL,
  schema_name TEXT NOT NULL,
  name TEXT NOT NULL,
  keys JSONB NULL,
  attributes JSONB NULL,
  description TEXT NULL,
  artifact_key TEXT NULL,
  version_no INTEGER NOT NULL DEFAULT 1,
  is_current BOOLEAN NOT NULL DEFAULT true,
  lifecycle_status TEXT NOT NULL DEFAULT 'live',
  source_type TEXT NOT NULL DEFAULT 'system',
  source_run_id TEXT NULL,
  change_reason TEXT NULL,
  approved_by TEXT NULL,
  approved_at TIMESTAMPTZ NULL,
  supersedes_version_no INTEGER NULL,
  created_by TEXT NULL,
  updated_by TEXT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_quantyx_dimensions_registry_current
  ON public.quantyx_dimensions_registry (tenant_id, domain_id, connection_id, database_name, schema_name, artifact_key)
  WHERE is_current = true;
CREATE UNIQUE INDEX IF NOT EXISTS uq_quantyx_dimensions_registry_version
  ON public.quantyx_dimensions_registry (tenant_id, domain_id, connection_id, database_name, schema_name, artifact_key, version_no);

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
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_quantyx_review_events_scope
  ON public.quantyx_review_events (tenant_id, domain_id, connection_id, artifact_type, created_at DESC);


CREATE TABLE IF NOT EXISTS public.quantyx_dbt_scaffolds (
  scaffold_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  connection_id TEXT NOT NULL,
  database_name TEXT NOT NULL,
  schema_name TEXT NOT NULL,
  tables JSONB NOT NULL DEFAULT '[]'::jsonb,
  context_id TEXT NULL,
  status TEXT NOT NULL DEFAULT 'live',
  payload JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_quantyx_dbt_scaffolds_lookup
  ON public.quantyx_dbt_scaffolds (tenant_id, domain_id, connection_id, created_at DESC);


CREATE TABLE IF NOT EXISTS public.quantyx_tenant_dbt_projects (
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  dbt_project_dir TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, domain_id)
);

CREATE INDEX IF NOT EXISTS idx_quantyx_tenant_dbt_projects_dir
  ON public.quantyx_tenant_dbt_projects (dbt_project_dir);


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


CREATE TABLE IF NOT EXISTS public.quantyx_canvases (
  canvas_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  name TEXT NOT NULL,
  description TEXT NULL,
  graph_json JSONB NOT NULL,
  root_node_id TEXT NULL,
  status TEXT NOT NULL DEFAULT 'live',
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
  data_schema JSONB NOT NULL,
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

-- Fact view registry (tracks demo/provisioned fact views)
CREATE TABLE IF NOT EXISTS public.quantyx_fact_views_registry (
  view_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  connection_id TEXT NOT NULL,
  database_name TEXT NOT NULL,
  schema_name TEXT NOT NULL,
  view_name TEXT NOT NULL,
  source_table TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_quantyx_fact_views_tenant
  ON public.quantyx_fact_views_registry (tenant_id, domain_id, created_at DESC);

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
