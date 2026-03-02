CREATE TABLE IF NOT EXISTS public.quantyx_chat_requests (
  chat_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  domain_id TEXT NULL,
  question TEXT NULL,
  request_payload JSONB NOT NULL,
  response_payload JSONB NULL,
  status TEXT NOT NULL DEFAULT 'queued',
  error_message TEXT NULL,
  timing_ms JSONB NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.quantyx_chat_events (
  event_id TEXT PRIMARY KEY,
  chat_id TEXT NOT NULL,
  event_type TEXT NOT NULL,
  message TEXT NOT NULL,
  details JSONB NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
