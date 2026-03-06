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
SQL
