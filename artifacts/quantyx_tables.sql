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
  status TEXT NOT NULL DEFAULT 'draft',
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
  status TEXT,
  owner TEXT,
  version TEXT,
  deprecated BOOLEAN NOT NULL DEFAULT false,
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
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, domain_id, connection_id, database_name, schema_name, entity_id),
  CHECK (connection_id <> 'global' AND database_name <> 'global' AND schema_name <> 'global')
);

CREATE INDEX IF NOT EXISTS idx_quantyx_entity_overrides_domain
  ON public.quantyx_entity_overrides (tenant_id, domain_id);

CREATE INDEX IF NOT EXISTS idx_quantyx_entity_overrides_scope
  ON public.quantyx_entity_overrides (tenant_id, domain_id, connection_id, database_name, schema_name);


CREATE TABLE IF NOT EXISTS public.quantyx_hierarchy_overrides (
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  connection_id TEXT NOT NULL,
  database_name TEXT NOT NULL,
  schema_name TEXT NOT NULL,
  hierarchy_name TEXT NOT NULL,
  levels TEXT[] NOT NULL,
  description TEXT,
  source_context_id TEXT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, domain_id, connection_id, database_name, schema_name, hierarchy_name),
  CHECK (connection_id <> 'global' AND database_name <> 'global' AND schema_name <> 'global')
);

CREATE INDEX IF NOT EXISTS idx_quantyx_hierarchy_overrides_domain
  ON public.quantyx_hierarchy_overrides (tenant_id, domain_id);

CREATE INDEX IF NOT EXISTS idx_quantyx_hierarchy_overrides_scope
  ON public.quantyx_hierarchy_overrides (tenant_id, domain_id, connection_id, database_name, schema_name);


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


CREATE TABLE IF NOT EXISTS public.quantyx_context_extractions (
  extraction_id TEXT PRIMARY KEY,
  context_id TEXT NOT NULL,
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  extraction_type TEXT NOT NULL,
  payload JSONB NOT NULL,
  llm_model TEXT NULL,
  confidence NUMERIC NULL,
  status TEXT NULL,
  notes TEXT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  FOREIGN KEY (context_id) REFERENCES public.quantyx_business_context(context_id)
);

CREATE INDEX IF NOT EXISTS idx_quantyx_context_extractions_tenant
  ON public.quantyx_context_extractions (tenant_id, domain_id, extraction_type);


CREATE TABLE IF NOT EXISTS public.quantyx_glossary_terms (
  term_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  term TEXT NOT NULL,
  normalized_term TEXT NOT NULL,
  definition TEXT NULL,
  synonyms JSONB NOT NULL DEFAULT '[]'::jsonb,
  abbreviations JSONB NOT NULL DEFAULT '[]'::jsonb,
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


CREATE TABLE IF NOT EXISTS public.quantyx_entity_mappings (
  mapping_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  connection_id TEXT NOT NULL,
  database_name TEXT NOT NULL,
  schema_name TEXT NOT NULL,
  tables JSONB NOT NULL DEFAULT '[]'::jsonb,
  payload JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
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
  table_name TEXT NOT NULL,
  time_column TEXT NULL,
  grain TEXT NULL,
  measures JSONB NULL,
  dimensions JSONB NULL,
  description TEXT NULL,
  status TEXT NOT NULL DEFAULT 'draft',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

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
  status TEXT NOT NULL DEFAULT 'draft',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

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
  status TEXT NOT NULL DEFAULT 'draft',
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
