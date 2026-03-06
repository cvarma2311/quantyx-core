# Phase 23: Dashboard Refresh + Composite Insights

## Objective
Add dashboard-level summary and inference that are computed across all charts, persisted, streamed, and refreshable on demand via API.

This phase extends Phase 22 from per-agent inference to full-dashboard inference.

---

## Problem Statement
- Current insights are chart-level and fragmented.
- No API exists to refresh a dashboard and recompute all chart data + global insights.
- UI cannot reliably show a single trusted "dashboard summary" and "dashboard inference" snapshot.

---

## Scope
1. Add refresh API to recompute all dashboard charts.
2. Add composite dashboard summary + inference generation across all chart outputs.
3. Persist dashboard refresh runs, chart snapshots, and insight artifacts.
4. Stream refresh lifecycle events to UI.
5. Support deterministic-first + LLM-enhanced insight generation.

Out of scope:
- Replacing query planner or semantic graph design.
- Replacing existing chart rendering payload format.

---

## Architecture Decision
Recommended: **Hybrid orchestration**
- **LangGraph/job orchestration** for execution order, retries, stage events, and state.
- **Deterministic analytics layer** for factual aggregates/trends/anomaly candidates.
- **LLM layer** only for natural-language narrative synthesis from deterministic facts.

Why this is better:
- deterministic facts prevent hallucinated claims;
- LLM still improves readability and business context phrasing;
- orchestration remains observable and resumable.

---

## Refresh Lifecycle (Dashboard)
Stages per refresh run:
1. `queued`
2. `running`
3. `charts_refreshed`
4. `summary_ready`
5. `inference_ready`
6. `completed`

Failure stages:
- `failed`
- `partial_completed` (some charts refreshed, insights available with warnings)

---

## Data Model Changes

### 1) `quantyx_dashboard_refresh_runs`
```sql
CREATE TABLE IF NOT EXISTS public.quantyx_dashboard_refresh_runs (
  refresh_id TEXT PRIMARY KEY,
  dashboard_id TEXT NOT NULL,
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  status TEXT NOT NULL, -- queued|running|charts_refreshed|summary_ready|inference_ready|completed|failed|partial_completed
  trigger_source TEXT NOT NULL, -- user|schedule|system
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
```

### 2) `quantyx_dashboard_chart_snapshots`
```sql
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
```

### 3) `quantyx_dashboard_insight_artifacts`
```sql
CREATE TABLE IF NOT EXISTS public.quantyx_dashboard_insight_artifacts (
  artifact_id TEXT PRIMARY KEY,
  refresh_id TEXT NOT NULL,
  dashboard_id TEXT NOT NULL,
  summary_raw_text TEXT NULL,
  summary_html TEXT NULL,
  inference_raw_text TEXT NULL,
  inference_html TEXT NULL,
  evidence_json JSONB NULL, -- deterministic facts used by narrative
  quality_json JSONB NULL,  -- confidence, warnings, missing charts
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_dashboard_insight_artifacts_refresh
  ON public.quantyx_dashboard_insight_artifacts (refresh_id);
```

---

## API Plan

## `POST /dashboards/{dashboard_id}/refresh`
Start async refresh.

Request:
```json
{
  "tenant_id": "VC_101",
  "domain_id": "lpg_production_distribution",
  "mode": "full",
  "include_insights": true,
  "force_recompute": false
}
```

Response:
```json
{
  "refresh_id": "dref_123",
  "dashboard_id": "dash_123",
  "status": "queued"
}
```

## `GET /dashboards/{dashboard_id}/refresh/{refresh_id}`
Response:
```json
{
  "refresh_id": "dref_123",
  "dashboard_id": "dash_123",
  "status": "inference_ready",
  "started_at": "2026-03-06T10:00:00Z",
  "updated_at": "2026-03-06T10:00:07Z"
}
```

## `GET /dashboards/{dashboard_id}/refresh/{refresh_id}/events`
Response:
```json
{
  "events": [
    {"stage_name": "running", "message": "Refreshing 6 charts"},
    {"stage_name": "charts_refreshed", "message": "6/6 charts refreshed"},
    {"stage_name": "summary_ready", "message": "Dashboard summary ready"},
    {"stage_name": "inference_ready", "message": "Dashboard inference ready"}
  ]
}
```

## `GET /dashboards/{dashboard_id}/insights`
Returns latest completed refresh insights by default.

Query params:
- `refresh_id` (optional; fetch insights for a specific refresh snapshot)
- `as_of` (optional ISO timestamp; fetch latest refresh completed at/before timestamp)

Response:
```json
{
  "dashboard_id": "dash_123",
  "refresh_id": "dref_123",
  "summary_raw_text": "Production improved week-over-week with stronger performance in West and South.",
  "summary_html": "<section><h4>Dashboard Summary</h4><p>...</p></section>",
  "inference_raw_text": "Sustained gains appear tied to higher run-rate in plants with lower downtime.",
  "inference_html": "<section><h4>Dashboard Inference</h4><p>...</p></section>",
  "quality": {"confidence": 0.82, "warnings": []}
}
```

## Optional stream endpoint
`GET /dashboards/{dashboard_id}/refresh/{refresh_id}/stream`
- SSE for stage-by-stage UI progress.

---

## Composite Summary + Inference Logic

1) Build deterministic evidence from all refreshed charts:
- top movers, biggest deltas, trend direction, concentration/share, outliers, data gaps.

2) Generate dashboard summary:
- factual short narrative of "what happened".

3) Generate dashboard inference:
- likely drivers/implications constrained to deterministic evidence.

4) Persist all outputs:
- `summary_raw_text`, `summary_html`, `inference_raw_text`, `inference_html`, evidence + quality metadata.

5) Emit stage events:
- `summary_ready`, `inference_ready`, `completed`.

---

## Contextual Naming Requirements
- DashboardAgent must assign a contextual dashboard title from semantic context (metric + table/domain), not generic labels like "Auto Dashboard".
- ChartPlanner/ChartAgent must assign contextual chart titles using:
  - intent (`trend`, `breakdown`, `share`, `multi_series`, `join_breakdown`)
  - metric name
  - grouping dimension/category
  - time grain/column where relevant
- Naming should remain deterministic-first, with optional LLM rewrite for readability.
- Persist resolved names in `quantyx_dashboard_specs.spec` and top-level `title`.

Examples:
- Dashboard: `Lpg Plant Operations Performance Overview`
- Chart: `Production Mt Trend Over Process Date`
- Chart: `Sap Id Share of Production Mt`

---

## Quality Guardrails
- Every narrative sentence must map to evidence keys in `evidence_json`.
- If confidence below threshold (e.g. 0.65), include warning banner in HTML.
- Enforce HTML-safe template rendering only (escaped values).
- Max output size caps:
  - text fields: 8KB
  - html fields: 32KB

---

## Implementation Phases

### Phase 23.1: Storage + run orchestration
- add refresh run tables and events
- add refresh worker path
- add status/events APIs

### Phase 23.2: Chart refresh engine
- refresh all dashboard charts
- snapshot chart outputs and deterministic stats
- support partial completion + retries

### Phase 23.3: Composite summary/inference
- implement deterministic evidence builder
- add LLM narrative synthesis with deterministic fallback
- persist insight artifacts

### Phase 23.4: UI/stream integration
- stream refresh stages
- show dashboard-level summary/inference panel
- add manual "Refresh Dashboard" action

---

## Dependencies
- Depends on Phase 05 (dashboard generation baseline).
- Depends on Phase 11/22 (streaming + staged metadata persistence patterns).
- Depends on Phase 20 for orchestration strategy.

---

## Success Criteria
- Dashboard refresh API recomputes all charts and status transitions reliably.
- Dashboard-level summary and inference are persisted and queryable.
- UI can render composite insights independent of per-chart drilldowns.
- Narrative quality improves without sacrificing deterministic trust.
