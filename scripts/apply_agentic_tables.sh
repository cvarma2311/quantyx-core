#!/usr/bin/env bash
set -euo pipefail

cd /Users/vnagaraju/PycharmProjects/quantyx-core
set -a
source .env
set +a

export PGHOST="${DB_HOST}"
export PGPORT="${DB_PORT}"
export PGDATABASE="${DB_NAME}"
export PGUSER="${DB_USER}"
export PGPASSWORD="${DB_PASSWORD}"

# Phase 22 migration-only SQL for existing agentic tables.
psql -v ON_ERROR_STOP=1 <<'SQL'
ALTER TABLE public.quantyx_agent_run_events
  ADD COLUMN IF NOT EXISTS stage_name TEXT NULL;

ALTER TABLE public.quantyx_agent_run_events
  ADD COLUMN IF NOT EXISTS stage_seq INT NULL;

ALTER TABLE public.quantyx_agent_run_events
  ADD COLUMN IF NOT EXISTS logical_event_id TEXT NULL;

ALTER TABLE public.quantyx_agent_run_events
  ADD COLUMN IF NOT EXISTS payload_compacted BOOLEAN NOT NULL DEFAULT false;

CREATE INDEX IF NOT EXISTS idx_agent_run_events_run_stage
  ON public.quantyx_agent_run_events (run_id, created_at, stage_seq);

ALTER TABLE public.quantyx_agent_chat_log
  ADD COLUMN IF NOT EXISTS event_id TEXT NULL;

ALTER TABLE public.quantyx_agent_chat_log
  ADD COLUMN IF NOT EXISTS stage_name TEXT NULL;

ALTER TABLE public.quantyx_agent_chat_log
  ADD COLUMN IF NOT EXISTS logical_event_id TEXT NULL;

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

CREATE TABLE IF NOT EXISTS public.quantyx_dashboard_refresh_runs (
  refresh_id TEXT PRIMARY KEY,
  dashboard_id TEXT NOT NULL,
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  status TEXT NOT NULL,
  trigger_source TEXT NOT NULL,
  requested_by TEXT NULL,
  request_payload JSONB NULL,
  error_message TEXT NULL,
  started_at TIMESTAMPTZ NULL,
  completed_at TIMESTAMPTZ NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_dashboard_refresh_runs_dashboard
  ON public.quantyx_dashboard_refresh_runs (dashboard_id, created_at DESC);

CREATE TABLE IF NOT EXISTS public.quantyx_dashboard_refresh_events (
  event_id TEXT PRIMARY KEY,
  refresh_id TEXT NOT NULL,
  dashboard_id TEXT NOT NULL,
  stage_name TEXT NOT NULL,
  message TEXT NOT NULL,
  artifacts JSONB NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_dashboard_refresh_events_refresh
  ON public.quantyx_dashboard_refresh_events (refresh_id, created_at);

CREATE TABLE IF NOT EXISTS public.quantyx_dashboard_chart_snapshots (
  snapshot_id TEXT PRIMARY KEY,
  refresh_id TEXT NOT NULL,
  dashboard_id TEXT NOT NULL,
  chart_id TEXT NOT NULL,
  chart_type TEXT NOT NULL,
  sql TEXT NULL,
  params JSONB NULL,
  row_count INT NOT NULL DEFAULT 0,
  data_json JSONB NOT NULL,
  stats_json JSONB NULL,
  insight_json JSONB NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_dashboard_chart_snapshots_refresh
  ON public.quantyx_dashboard_chart_snapshots (refresh_id, chart_id);

CREATE TABLE IF NOT EXISTS public.quantyx_dashboard_insight_artifacts (
  artifact_id TEXT PRIMARY KEY,
  refresh_id TEXT NOT NULL,
  dashboard_id TEXT NOT NULL,
  summary_raw_text TEXT NULL,
  summary_html TEXT NULL,
  inference_raw_text TEXT NULL,
  inference_html TEXT NULL,
  evidence_json JSONB NULL,
  quality_json JSONB NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_dashboard_insight_artifacts_refresh
  ON public.quantyx_dashboard_insight_artifacts (refresh_id);

ALTER TABLE public.quantyx_agent_runs
  ADD COLUMN IF NOT EXISTS is_canonical BOOLEAN NOT NULL DEFAULT false;

ALTER TABLE public.quantyx_agent_runs
  ADD COLUMN IF NOT EXISTS version_no INTEGER NOT NULL DEFAULT 1;

ALTER TABLE public.quantyx_agent_runs
  ADD COLUMN IF NOT EXISTS display_name TEXT NULL;

ALTER TABLE public.quantyx_agent_runs
  ADD COLUMN IF NOT EXISTS superseded_by_run_id TEXT NULL;

ALTER TABLE public.quantyx_agent_runs
  ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_runs_canonical_scope
  ON public.quantyx_agent_runs (tenant_id, domain_id)
  WHERE is_canonical = true;

CREATE INDEX IF NOT EXISTS idx_agent_runs_scope_version
  ON public.quantyx_agent_runs (tenant_id, domain_id, version_no DESC, updated_at DESC);

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

-- Phase 38: Chart Conversations and User Dashboard Management

ALTER TABLE public.quantyx_workspace_conversations
  ADD COLUMN IF NOT EXISTS source_chart_id TEXT NULL;

CREATE INDEX IF NOT EXISTS idx_workspace_conversations_chart
  ON public.quantyx_workspace_conversations (source_chart_id, created_at DESC)
  WHERE source_chart_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS public.quantyx_user_dashboards (
  dashboard_id   TEXT PRIMARY KEY,
  tenant_id      TEXT NOT NULL,
  domain_id      TEXT NOT NULL,
  name           TEXT NOT NULL,
  description    TEXT NULL,
  status         TEXT NOT NULL DEFAULT 'active',
  created_by     TEXT NULL,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_user_dashboards_tenant
  ON public.quantyx_user_dashboards (tenant_id, domain_id, status, updated_at DESC);

CREATE TABLE IF NOT EXISTS public.quantyx_user_dashboard_charts (
  entry_id       TEXT PRIMARY KEY,
  dashboard_id   TEXT NOT NULL REFERENCES public.quantyx_user_dashboards(dashboard_id)
                   ON DELETE CASCADE,
  chart_id       TEXT NOT NULL,
  position       INTEGER NOT NULL DEFAULT 0,
  added_by       TEXT NULL,
  added_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (dashboard_id, chart_id)
);

CREATE INDEX IF NOT EXISTS idx_user_dashboard_charts_dashboard
  ON public.quantyx_user_dashboard_charts (dashboard_id, position ASC);

CREATE INDEX IF NOT EXISTS idx_user_dashboard_charts_chart
  ON public.quantyx_user_dashboard_charts (chart_id);

-- Phase 43: add run_id to quantyx_chart_requests so correlation agent can
-- load exactly the KPI charts produced by a specific canonical deployment run.
ALTER TABLE public.quantyx_chart_requests
  ADD COLUMN IF NOT EXISTS run_id TEXT NULL;

CREATE INDEX IF NOT EXISTS idx_chart_requests_run
  ON public.quantyx_chart_requests (run_id, tenant_id, domain_id, status)
  WHERE run_id IS NOT NULL;

-- Phase 43: Statistical Correlation, Anomaly, and Forward Pattern Agent tables

CREATE TABLE IF NOT EXISTS public.quantyx_correlation_runs (
  correlation_run_id    TEXT PRIMARY KEY,
  tenant_id             TEXT NOT NULL,
  domain_id             TEXT NOT NULL,
  run_id                TEXT NOT NULL,
  analysis_mode         TEXT NOT NULL DEFAULT 'full',
  status                TEXT NOT NULL DEFAULT 'pending',
  forecast_periods      INT  NOT NULL DEFAULT 12,
  metric_count          INT  NULL,
  anomaly_count         INT  NULL,
  correlation_pair_count INT  NULL,
  thread_count          INT  NULL,
  error_message         TEXT NULL,
  triggered_by          TEXT NULL,
  summary_text          TEXT NULL,
  summary_html          TEXT NULL,
  started_at            TIMESTAMPTZ NULL,
  completed_at          TIMESTAMPTZ NULL,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_correlation_runs_scope
  ON public.quantyx_correlation_runs (tenant_id, domain_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_correlation_runs_run
  ON public.quantyx_correlation_runs (run_id, created_at DESC);

CREATE TABLE IF NOT EXISTS public.quantyx_anomaly_results (
  anomaly_id            TEXT PRIMARY KEY,
  correlation_run_id    TEXT NOT NULL,
  tenant_id             TEXT NOT NULL,
  domain_id             TEXT NOT NULL,
  metric_name           TEXT NOT NULL,
  anomaly_class         TEXT NOT NULL,
  anomaly_score         NUMERIC(6,4) NOT NULL,
  z_score               NUMERIC(8,4) NULL,
  iqr_flag              BOOLEAN NOT NULL DEFAULT false,
  cusum_signal          BOOLEAN NOT NULL DEFAULT false,
  detected_at           TEXT NOT NULL,
  period_label          TEXT NULL,
  baseline_value        NUMERIC NULL,
  observed_value        NUMERIC NULL,
  deviation_pct         NUMERIC(8,2) NULL,
  top_dimension         TEXT NULL,
  top_dimension_value   TEXT NULL,
  dimension_pct         NUMERIC(6,2) NULL,
  stats_json            JSONB NULL,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_anomaly_results_run
  ON public.quantyx_anomaly_results (correlation_run_id, anomaly_score DESC);

CREATE INDEX IF NOT EXISTS idx_anomaly_results_metric
  ON public.quantyx_anomaly_results (tenant_id, domain_id, metric_name, detected_at DESC);

CREATE TABLE IF NOT EXISTS public.quantyx_correlation_pairs (
  pair_id               TEXT PRIMARY KEY,
  correlation_run_id    TEXT NOT NULL,
  tenant_id             TEXT NOT NULL,
  domain_id             TEXT NOT NULL,
  metric_a              TEXT NOT NULL,
  metric_b              TEXT NOT NULL,
  pearson_r             NUMERIC(6,4) NULL,
  spearman_rho          NUMERIC(6,4) NULL,
  best_lag              INT  NULL,
  lagged_r              NUMERIC(6,4) NULL,
  lag_direction         TEXT NULL,
  strength_label        TEXT NOT NULL,
  direction_label       TEXT NOT NULL,
  sample_size           INT  NULL,
  p_value               NUMERIC(10,6) NULL,
  is_stable             BOOLEAN NOT NULL DEFAULT true,
  rolling_r_json        JSONB NULL,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_correlation_pairs_run
  ON public.quantyx_correlation_pairs (correlation_run_id, ABS(pearson_r) DESC);

CREATE UNIQUE INDEX IF NOT EXISTS uq_correlation_pairs_run_metrics
  ON public.quantyx_correlation_pairs (correlation_run_id, metric_a, metric_b);

CREATE TABLE IF NOT EXISTS public.quantyx_investigation_threads (
  thread_id             TEXT PRIMARY KEY,
  correlation_run_id    TEXT NOT NULL,
  tenant_id             TEXT NOT NULL,
  domain_id             TEXT NOT NULL,
  trigger_metric        TEXT NOT NULL,
  trigger_anomaly_id    TEXT NOT NULL,
  evidence_chain        JSONB NOT NULL,
  leading_dimension     TEXT NULL,
  leading_dim_value     TEXT NULL,
  confidence            NUMERIC(6,4) NOT NULL,
  suggested_focus       JSONB NULL,
  narrative_text        TEXT NULL,
  narrative_html        TEXT NULL,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_investigation_threads_run
  ON public.quantyx_investigation_threads (correlation_run_id, confidence DESC);

CREATE TABLE IF NOT EXISTS public.quantyx_forward_projections (
  projection_id         TEXT PRIMARY KEY,
  correlation_run_id    TEXT NOT NULL,
  tenant_id             TEXT NOT NULL,
  domain_id             TEXT NOT NULL,
  metric_name           TEXT NOT NULL,
  forecast_periods      INT  NOT NULL,
  trend_direction       TEXT NOT NULL,
  trend_slope           NUMERIC NULL,
  seasonality_present   BOOLEAN NOT NULL DEFAULT false,
  inflection_signal     TEXT NULL,
  inflection_detail     TEXT NULL,
  projection_json       JSONB NOT NULL,
  anomaly_density_trend TEXT NULL,
  chart_spec            JSONB NULL,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_forward_projections_run
  ON public.quantyx_forward_projections (correlation_run_id, metric_name);

-- Phase 46: Per-chart inference, narrative and stats persistence
ALTER TABLE public.quantyx_chart_requests
  ADD COLUMN IF NOT EXISTS insight_text   TEXT  NULL,
  ADD COLUMN IF NOT EXISTS narrative_text TEXT  NULL,
  ADD COLUMN IF NOT EXISTS stats_json     JSONB NULL;

COMMENT ON COLUMN public.quantyx_chart_requests.insight_text   IS 'One-line callout: top dimension value or latest trend delta (LLM-generated, deterministic fallback)';
COMMENT ON COLUMN public.quantyx_chart_requests.narrative_text IS 'Best/worst dimension comparison sentence (LLM-generated, deterministic fallback)';
COMMENT ON COLUMN public.quantyx_chart_requests.stats_json     IS 'Descriptive statistics over primary metric: {count, min, max, avg, total}';
SQL
