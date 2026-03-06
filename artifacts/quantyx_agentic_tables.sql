-- Agentic platform storage tables (all quantyx_*)

CREATE TABLE IF NOT EXISTS public.quantyx_agent_runs (
  run_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.quantyx_agent_run_events (
  event_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  agent_name TEXT NOT NULL,
  status TEXT NOT NULL,
  message TEXT NOT NULL,
  artifacts JSONB NULL,
  stage_name TEXT NULL,
  stage_seq INT NULL,
  logical_event_id TEXT NULL,
  payload_compacted BOOLEAN NOT NULL DEFAULT false,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_agent_run_events_run_stage
  ON public.quantyx_agent_run_events (run_id, created_at, stage_seq);

CREATE TABLE IF NOT EXISTS public.quantyx_agent_chat_log (
  message_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  sender TEXT NOT NULL,
  message TEXT NOT NULL,
  event_id TEXT NULL,
  stage_name TEXT NULL,
  logical_event_id TEXT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_agent_chat_log_run_stage
  ON public.quantyx_agent_chat_log (run_id, created_at);

CREATE TABLE IF NOT EXISTS public.quantyx_agent_event_artifacts (
  artifact_id TEXT PRIMARY KEY,
  event_id TEXT NOT NULL,
  logical_event_id TEXT NOT NULL,
  run_id TEXT NOT NULL,
  agent_name TEXT NOT NULL,
  stage_name TEXT NOT NULL,
  raw_json JSONB NULL,
  summary_raw_text TEXT NULL,
  summary_html TEXT NULL,
  inference_raw_text TEXT NULL,
  inference_html TEXT NULL,
  truncation JSONB NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_agent_event_artifacts_run
  ON public.quantyx_agent_event_artifacts (run_id, created_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_event_artifacts_stage
  ON public.quantyx_agent_event_artifacts (logical_event_id, stage_name);

CREATE TABLE IF NOT EXISTS public.quantyx_semantic_nodes (
  node_id TEXT PRIMARY KEY,
  node_type TEXT NOT NULL,
  name TEXT NOT NULL,
  normalized_name TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  metadata JSONB NULL,
  confidence NUMERIC NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.quantyx_semantic_edges (
  edge_id TEXT PRIMARY KEY,
  src_node_id TEXT NOT NULL,
  dst_node_id TEXT NOT NULL,
  edge_type TEXT NOT NULL,
  confidence NUMERIC NULL,
  source TEXT NOT NULL,
  metadata JSONB NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.quantyx_semantic_usage (
  usage_id TEXT PRIMARY KEY,
  question_hash TEXT NOT NULL,
  question_text TEXT NOT NULL,
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  resolved_metric TEXT NOT NULL,
  resolved_dimensions JSONB NULL,
  resolved_filters JSONB NULL,
  intent TEXT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.quantyx_rollup_registry (
  rollup_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  base_model TEXT NOT NULL,
  metric_name TEXT NOT NULL,
  dimensions JSONB NOT NULL,
  time_grain TEXT NOT NULL,
  filters JSONB NULL,
  rollup_table TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.quantyx_dashboard_specs (
  dashboard_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  title TEXT NOT NULL,
  spec JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.quantyx_semantic_feedback (
  feedback_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  edge_id TEXT NOT NULL,
  action TEXT NOT NULL,
  delta_confidence NUMERIC NULL,
  notes TEXT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
