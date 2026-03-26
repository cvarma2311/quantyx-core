-- Agentic platform storage tables (all quantyx_*)

CREATE TABLE IF NOT EXISTS public.quantyx_agent_runs (
  run_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  status TEXT NOT NULL,
  is_canonical BOOLEAN NOT NULL DEFAULT false,
  version_no INTEGER NOT NULL DEFAULT 1,
  display_name TEXT NULL,
  superseded_by_run_id TEXT NULL,
  completed_at TIMESTAMPTZ NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_runs_canonical_scope
  ON public.quantyx_agent_runs (tenant_id, domain_id)
  WHERE is_canonical = true;

CREATE INDEX IF NOT EXISTS idx_agent_runs_scope_version
  ON public.quantyx_agent_runs (tenant_id, domain_id, version_no DESC, updated_at DESC);

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

CREATE INDEX IF NOT EXISTS idx_agent_event_artifacts_run_event
  ON public.quantyx_agent_event_artifacts (run_id, event_id);

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

-- RETIRED (Phase 44): quantyx_dashboard_specs — replaced by quantyx_dashboards (dashboard_type='system')
-- Kept here for reference only. Drop after Phase 44 migration is validated:
--   DROP TABLE public.quantyx_dashboard_specs;
-- CREATE TABLE IF NOT EXISTS public.quantyx_dashboard_specs (
--   dashboard_id TEXT PRIMARY KEY, tenant_id TEXT, domain_id TEXT,
--   title TEXT, spec JSONB, created_at TIMESTAMPTZ, updated_at TIMESTAMPTZ
-- );

-- ── Phase 44: Unified dashboard table ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.quantyx_dashboards (
  dashboard_id          TEXT PRIMARY KEY,
  tenant_id             TEXT NOT NULL,
  domain_id             TEXT NOT NULL,
  name                  TEXT NOT NULL,
  description           TEXT NULL,
  dashboard_type        TEXT NOT NULL DEFAULT 'system',   -- 'system' | 'user'
  status                TEXT NOT NULL DEFAULT 'active',
  run_id                TEXT NULL,
  latest_refresh_id     TEXT NULL,
  quality_score         FLOAT NULL,
  quality_gate_passed   BOOLEAN NULL,
  chart_plan            JSONB NULL,
  created_by            TEXT NULL,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_dashboards_tenant
  ON public.quantyx_dashboards (tenant_id, domain_id, status, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_dashboards_type
  ON public.quantyx_dashboards (tenant_id, dashboard_type, status);

-- ── Phase 44: Unified chart-link table ────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.quantyx_dashboard_charts (
  entry_id              TEXT PRIMARY KEY,
  dashboard_id          TEXT NOT NULL
    REFERENCES public.quantyx_dashboards(dashboard_id) ON DELETE CASCADE,
  chart_id              TEXT NOT NULL,
  position              INTEGER NOT NULL DEFAULT 0,
  title_override        TEXT NULL,
  added_by              TEXT NULL,
  added_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (dashboard_id, chart_id)
);

CREATE INDEX IF NOT EXISTS idx_dashboard_charts_dashboard
  ON public.quantyx_dashboard_charts (dashboard_id, position ASC);

CREATE INDEX IF NOT EXISTS idx_dashboard_charts_chart
  ON public.quantyx_dashboard_charts (chart_id);

-- RETIRED (Phase 44): quantyx_user_dashboards + quantyx_user_dashboard_charts
-- Both merged into quantyx_dashboards (dashboard_type='user') + quantyx_dashboard_charts
-- Drop after Phase 44 migration is validated:
--   DROP TABLE public.quantyx_user_dashboard_charts;
--   DROP TABLE public.quantyx_user_dashboards;

CREATE TABLE IF NOT EXISTS public.quantyx_anomaly_investigations (
  investigation_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  run_id TEXT NOT NULL,
  conversation_id TEXT NULL,
  dashboard_id TEXT NULL,
  source_dashboard_id TEXT NULL,
  trigger_source TEXT NOT NULL,
  status TEXT NOT NULL,
  title TEXT NULL,
  summary_text TEXT NULL,
  severity_score NUMERIC NULL,
  confidence_score NUMERIC NULL,
  anomaly_summary_json JSONB NULL,
  quality_json JSONB NULL,
  error_message TEXT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_anomaly_investigations_scope
  ON public.quantyx_anomaly_investigations (tenant_id, domain_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_anomaly_investigations_run
  ON public.quantyx_anomaly_investigations (run_id, created_at DESC);

CREATE TABLE IF NOT EXISTS public.quantyx_anomaly_records (
  anomaly_id TEXT PRIMARY KEY,
  investigation_id TEXT NOT NULL,
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  metric_id TEXT NULL,
  raw_signal_name TEXT NULL,
  anomaly_type TEXT NOT NULL,
  entity_scope_json JSONB NULL,
  baseline_window_json JSONB NULL,
  comparison_window_json JSONB NULL,
  severity_score NUMERIC NULL,
  confidence_score NUMERIC NULL,
  evidence_json JSONB NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_anomaly_records_investigation
  ON public.quantyx_anomaly_records (investigation_id, severity_score DESC, created_at DESC);

CREATE TABLE IF NOT EXISTS public.quantyx_anomaly_hypotheses (
  hypothesis_id TEXT PRIMARY KEY,
  investigation_id TEXT NOT NULL,
  anomaly_id TEXT NULL,
  rank_no INT NOT NULL DEFAULT 1,
  title TEXT NOT NULL,
  explanation_text TEXT NOT NULL,
  confidence_score NUMERIC NULL,
  likely_drivers_json JSONB NULL,
  supporting_evidence_json JSONB NULL,
  validation_step_text TEXT NULL,
  provenance_json JSONB NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_anomaly_hypotheses_investigation
  ON public.quantyx_anomaly_hypotheses (investigation_id, rank_no ASC, created_at ASC);

CREATE TABLE IF NOT EXISTS public.quantyx_anomaly_actions (
  action_id TEXT PRIMARY KEY,
  investigation_id TEXT NOT NULL,
  anomaly_id TEXT NULL,
  hypothesis_id TEXT NULL,
  action_type TEXT NOT NULL,
  priority TEXT NULL,
  confidence_score NUMERIC NULL,
  recommended_owner TEXT NULL,
  action_text TEXT NOT NULL,
  metadata_json JSONB NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_anomaly_actions_investigation
  ON public.quantyx_anomaly_actions (investigation_id, created_at ASC);

CREATE TABLE IF NOT EXISTS public.quantyx_anomaly_dashboard_links (
  link_id TEXT PRIMARY KEY,
  investigation_id TEXT NOT NULL,
  dashboard_id TEXT NOT NULL,
  source_dashboard_id TEXT NULL,
  role TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_anomaly_dashboard_links_role
  ON public.quantyx_anomaly_dashboard_links (investigation_id, dashboard_id, role);

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

CREATE TABLE IF NOT EXISTS public.quantyx_workspace_conversations (
  conversation_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  run_id TEXT NOT NULL,
  title TEXT NULL,
  display_name TEXT NULL,
  status TEXT NOT NULL DEFAULT 'active',
  created_by TEXT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_workspace_conversations_scope
  ON public.quantyx_workspace_conversations (tenant_id, domain_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_workspace_conversations_run
  ON public.quantyx_workspace_conversations (run_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS public.quantyx_workspace_messages (
  message_id TEXT PRIMARY KEY,
  conversation_id TEXT NOT NULL,
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  run_id TEXT NOT NULL,
  sender TEXT NOT NULL,
  message_text TEXT NOT NULL,
  sql_text TEXT NULL,
  data_json JSONB NULL,
  chart_json JSONB NULL,
  inference_json JSONB NULL,
  summary_json JSONB NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_workspace_messages_conversation
  ON public.quantyx_workspace_messages (conversation_id, created_at ASC);

CREATE INDEX IF NOT EXISTS idx_workspace_messages_scope
  ON public.quantyx_workspace_messages (tenant_id, domain_id, created_at DESC);

CREATE TABLE IF NOT EXISTS public.quantyx_workspace_conversation_memory (
  memory_id TEXT PRIMARY KEY,
  conversation_id TEXT NOT NULL,
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  run_id TEXT NOT NULL,
  summary_text TEXT NULL,
  memory_json JSONB NOT NULL,
  last_message_at TIMESTAMPTZ NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_workspace_memory_conversation
  ON public.quantyx_workspace_conversation_memory (conversation_id);
