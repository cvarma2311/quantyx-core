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
SQL
