-- Phase 59: Data Quality anomaly persistence and reporting

CREATE TABLE IF NOT EXISTS public.quantyx_data_quality_anomalies (
  anomaly_id TEXT PRIMARY KEY,
  anomaly_key TEXT NOT NULL,
  quality_run_id TEXT NULL,
  run_id TEXT NOT NULL,
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  trend_scope_key TEXT NULL,
  baseline_run_id TEXT NULL,
  object_type TEXT NOT NULL,
  object_key TEXT NOT NULL,
  object_name TEXT NULL,
  anomaly_type TEXT NOT NULL,
  title TEXT NOT NULL,
  severity TEXT NOT NULL,
  evidence_path TEXT NULL,
  current_value_num NUMERIC NULL,
  current_value_text TEXT NULL,
  previous_value_num NUMERIC NULL,
  previous_value_text TEXT NULL,
  delta_value NUMERIC NULL,
  delta_pct NUMERIC NULL,
  summary_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_dq_anomalies_run_key
  ON public.quantyx_data_quality_anomalies (quality_run_id, anomaly_key);

CREATE INDEX IF NOT EXISTS idx_dq_anomalies_scope
  ON public.quantyx_data_quality_anomalies (tenant_id, domain_id, trend_scope_key, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_dq_anomalies_run
  ON public.quantyx_data_quality_anomalies (run_id, object_type, anomaly_type, created_at DESC);
