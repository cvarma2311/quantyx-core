# Phase 12: Storage Model (Tables Needed)

## Objective
Define the backend storage needed to power the multi‑agent semantic platform, deterministic query engine, and auto‑dashboard generation.

> **Naming rule:** all tables must start with `quantyx_`.

---

## 1) Agent Orchestration

### `quantyx_agent_runs`
Tracks a full multi‑agent run lifecycle.
```sql
CREATE TABLE IF NOT EXISTS public.quantyx_agent_runs (
  run_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  status TEXT NOT NULL, -- queued|running|completed|failed
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### `quantyx_agent_run_events`
Stores step‑level messages and artifacts.
```sql
CREATE TABLE IF NOT EXISTS public.quantyx_agent_run_events (
  event_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  agent_name TEXT NOT NULL,
  status TEXT NOT NULL,
  message TEXT NOT NULL,
  artifacts JSONB NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### `quantyx_agent_chat_log`
Full chat stream persisted regardless of UI visibility.
```sql
CREATE TABLE IF NOT EXISTS public.quantyx_agent_chat_log (
  message_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  sender TEXT NOT NULL, -- system|agent
  message TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

---

## 2) Semantic Graph

### `quantyx_semantic_nodes`
```sql
CREATE TABLE IF NOT EXISTS public.quantyx_semantic_nodes (
  node_id TEXT PRIMARY KEY,
  node_type TEXT NOT NULL, -- concept|metric|dimension|model|column|synonym|timegrain|rule
  name TEXT NOT NULL,
  normalized_name TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  metadata JSONB NULL,
  confidence NUMERIC NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### `quantyx_semantic_edges`
```sql
CREATE TABLE IF NOT EXISTS public.quantyx_semantic_edges (
  edge_id TEXT PRIMARY KEY,
  src_node_id TEXT NOT NULL,
  dst_node_id TEXT NOT NULL,
  edge_type TEXT NOT NULL,
  confidence NUMERIC NULL,
  source TEXT NOT NULL, -- rule|llm|user_confirmed|imported
  metadata JSONB NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### `quantyx_semantic_usage`
```sql
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
```

---

## 3) Rollups + Cache

### `quantyx_rollup_registry`
```sql
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
```

---

## 4) Dashboard Generation

### `quantyx_dashboard_specs`
```sql
CREATE TABLE IF NOT EXISTS public.quantyx_dashboard_specs (
  dashboard_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  title TEXT NOT NULL,
  spec JSONB NOT NULL, -- full dashboard story + charts
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### `quantyx_chart_requests`
(Already exists; reuse for chart async builds)

---

## 5) Governance + Feedback

### `quantyx_semantic_feedback`
```sql
CREATE TABLE IF NOT EXISTS public.quantyx_semantic_feedback (
  feedback_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  edge_id TEXT NOT NULL,
  action TEXT NOT NULL, -- confirm|reject|edit
  delta_confidence NUMERIC NULL,
  notes TEXT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

---

## 6) Chat Requests

### `quantyx_chat_requests`
```sql
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
```

---

## Success Criteria
- All agent lifecycle events persisted
- Semantic graph and usage tracking complete
- Rollup registry ready for pre‑aggregation
- Dashboard specs stored for UI rendering
