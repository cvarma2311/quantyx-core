-- Phase 59: Enterprise Data Quality Reporting, Trends, and Rerun Lineage

ALTER TABLE public.quantyx_agent_runs
  ADD COLUMN IF NOT EXISTS trend_mode TEXT NULL,
  ADD COLUMN IF NOT EXISTS trend_scope_key TEXT NULL,
  ADD COLUMN IF NOT EXISTS trend_scope_label TEXT NULL,
  ADD COLUMN IF NOT EXISTS parent_run_id TEXT NULL,
  ADD COLUMN IF NOT EXISTS rerun_root_run_id TEXT NULL,
  ADD COLUMN IF NOT EXISTS rerun_reason TEXT NULL,
  ADD COLUMN IF NOT EXISTS deployment_payload_json JSONB NULL;

CREATE INDEX IF NOT EXISTS idx_agent_runs_trend_scope
  ON public.quantyx_agent_runs (tenant_id, domain_id, trend_scope_key, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_agent_runs_parent
  ON public.quantyx_agent_runs (parent_run_id, created_at DESC);

CREATE TABLE IF NOT EXISTS public.quantyx_agent_run_lineage (
  lineage_edge_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  parent_run_id TEXT NOT NULL,
  child_run_id TEXT NOT NULL,
  edge_type TEXT NOT NULL,
  trend_scope_key TEXT NULL,
  summary_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_agent_run_lineage_child
  ON public.quantyx_agent_run_lineage (child_run_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_agent_run_lineage_parent
  ON public.quantyx_agent_run_lineage (parent_run_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_agent_run_lineage_scope
  ON public.quantyx_agent_run_lineage (tenant_id, domain_id, trend_scope_key, created_at DESC);

ALTER TABLE public.quantyx_data_quality_runs
  ADD COLUMN IF NOT EXISTS trend_mode TEXT NULL,
  ADD COLUMN IF NOT EXISTS trend_scope_key TEXT NULL,
  ADD COLUMN IF NOT EXISTS trend_scope_label TEXT NULL,
  ADD COLUMN IF NOT EXISTS baseline_run_id TEXT NULL;

CREATE INDEX IF NOT EXISTS idx_quantyx_data_quality_runs_trend_scope
  ON public.quantyx_data_quality_runs (tenant_id, domain_id, trend_scope_key, created_at DESC);

CREATE TABLE IF NOT EXISTS public.quantyx_data_quality_run_metric_snapshots (
  snapshot_id TEXT PRIMARY KEY,
  quality_run_id TEXT NOT NULL,
  run_id TEXT NOT NULL,
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  trend_scope_key TEXT NULL,
  metric_name TEXT NOT NULL,
  metric_value_num NUMERIC NULL,
  metric_value_text TEXT NULL,
  metric_unit TEXT NULL,
  captured_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_dq_run_metric_snapshots_scope
  ON public.quantyx_data_quality_run_metric_snapshots (tenant_id, domain_id, trend_scope_key, metric_name, captured_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS uq_dq_run_metric_snapshots_run_metric
  ON public.quantyx_data_quality_run_metric_snapshots (quality_run_id, metric_name);

CREATE TABLE IF NOT EXISTS public.quantyx_data_quality_object_metric_snapshots (
  object_snapshot_id TEXT PRIMARY KEY,
  quality_run_id TEXT NOT NULL,
  run_id TEXT NOT NULL,
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  trend_scope_key TEXT NULL,
  object_type TEXT NOT NULL,
  object_key TEXT NOT NULL,
  object_name TEXT NULL,
  metric_name TEXT NOT NULL,
  metric_value_num NUMERIC NULL,
  metric_value_text TEXT NULL,
  metric_unit TEXT NULL,
  captured_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_dq_object_metric_snapshots_scope
  ON public.quantyx_data_quality_object_metric_snapshots (tenant_id, domain_id, trend_scope_key, object_type, object_key, metric_name, captured_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS uq_dq_object_metric_snapshots_run_object_metric
  ON public.quantyx_data_quality_object_metric_snapshots (quality_run_id, object_type, object_key, metric_name);

CREATE TABLE IF NOT EXISTS public.quantyx_data_quality_trends (
  trend_id TEXT PRIMARY KEY,
  quality_run_id TEXT NOT NULL,
  run_id TEXT NOT NULL,
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  trend_scope_key TEXT NULL,
  baseline_run_id TEXT NULL,
  object_type TEXT NOT NULL,
  object_key TEXT NOT NULL,
  object_name TEXT NULL,
  metric_name TEXT NOT NULL,
  previous_value_num NUMERIC NULL,
  previous_value_text TEXT NULL,
  current_value_num NUMERIC NULL,
  current_value_text TEXT NULL,
  delta_value NUMERIC NULL,
  delta_pct NUMERIC NULL,
  trend_status TEXT NOT NULL,
  directionality TEXT NOT NULL,
  summary_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_dq_trends_scope
  ON public.quantyx_data_quality_trends (tenant_id, domain_id, trend_scope_key, object_type, metric_name, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_dq_trends_run
  ON public.quantyx_data_quality_trends (run_id, object_type, object_key, metric_name);

