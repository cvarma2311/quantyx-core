-- Phase 59B: Enterprise Data Quality Issue Register and Stewardship Workflow

CREATE TABLE IF NOT EXISTS public.quantyx_data_quality_issues (
  issue_id TEXT PRIMARY KEY,
  issue_key TEXT NOT NULL,
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  trend_scope_key TEXT NULL,
  run_id TEXT NOT NULL,
  quality_run_id TEXT NOT NULL,
  first_seen_run_id TEXT NULL,
  last_seen_run_id TEXT NULL,
  issue_type TEXT NOT NULL,
  title TEXT NOT NULL,
  severity TEXT NOT NULL,
  object_type TEXT NULL,
  object_key TEXT NULL,
  table_name TEXT NULL,
  column_name TEXT NULL,
  stage_id TEXT NULL,
  owner_id TEXT NULL,
  status TEXT NOT NULL DEFAULT 'open',
  due_at TIMESTAMPTZ NULL,
  first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  evidence_path TEXT NULL,
  recommendation_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  summary_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  related_run_ids_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_dq_issues_scope_key
  ON public.quantyx_data_quality_issues (tenant_id, domain_id, issue_key);

CREATE INDEX IF NOT EXISTS idx_dq_issues_run
  ON public.quantyx_data_quality_issues (run_id, severity, status, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_dq_issues_scope
  ON public.quantyx_data_quality_issues (tenant_id, domain_id, trend_scope_key, status, severity, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_dq_issues_owner
  ON public.quantyx_data_quality_issues (tenant_id, domain_id, owner_id, status, due_at NULLS LAST);
