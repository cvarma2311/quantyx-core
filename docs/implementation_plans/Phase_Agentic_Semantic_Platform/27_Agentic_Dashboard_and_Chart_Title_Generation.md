# Phase 27: Agentic Dashboard and Chart Title Generation

## Objective
Ensure every generated dashboard and chart has a clear, contextual, customer-facing title produced by agents, with deterministic fallback and consistent naming across create/refresh/update flows.

---

## Problem Statement
- Auto-generated artifacts can have generic names (`Auto Dashboard`, `Chart 1`) that reduce usability.
- Naming behavior can drift between initial generation, refresh, and edits.
- UI and API consumers need predictable, human-readable titles without client-side naming logic.

---

## Scope
1. Title generation policy for dashboard and chart creation.
2. Title regeneration policy during dashboard refresh.
3. API/storage consistency for title fields.
4. Governance controls (`PUT`) for manual title override.
5. Quality checks for meaningful, non-generic names.

Out of scope:
- Localization/multi-language title generation.
- Branding/theme-specific copywriting.

---

## Naming Principles
1. Titles must be domain-contextual, metric-aware, and user-readable.
2. Titles must avoid placeholders/generic terms (e.g., `Chart 1`, `Auto Dashboard`).
3. Titles must be concise:
- dashboard: 4-10 words
- chart: 4-12 words
4. Titles should be stable for same intent/query context unless semantics materially change.
5. Deterministic fallback must always exist when LLM is unavailable.

---

## Title Generation Inputs

## Dashboard title inputs
- tenant/domain semantic context
- dominant metrics across charts
- dominant dimensions/time grain
- dashboard intent/theme (operations, trend, risk, performance)

## Chart title inputs
- chart intent (`trend`, `breakdown`, `comparison`, `share`, `rank`, `distribution`)
- primary metric(s)
- grouping dimension(s)
- time grain/time field if present
- optional filter highlights (zone, plant, period)

---

## Generation Strategy

## Step 1: Deterministic base title
Generate a structured baseline:
- Dashboard: `<Domain Focus> <Insight Theme> Overview`
- Chart: `<Metric> by <Dimension>` or `<Metric> Trend by <Time Grain>`

## Step 2: Agent/LLM rewrite
Agent rewrites baseline to natural concise title while preserving facts.

## Step 3: Safety and quality checks
Reject/repair titles that are:
- too short (`< 3` words) or too long (`> 14` words)
- generic placeholders
- missing metric/dimension context when available

## Step 4: Persist final + provenance
Store:
- `title` (final title shown to users)
- `title_meta` JSON (`source=deterministic|llm`, `base_title`, `confidence`, `generated_at`)

---

## Data Model Changes

## `quantyx_dashboard_specs` (existing)
- top-level `title` is always populated and updated.
- `spec` JSON also carries `title` and `dashboard_title` for downstream consumers.
- optional future enhancement: `title_meta JSONB NULL`.

## Dashboard spec JSON
For each chart object, persist:
- `chart_id`
- `title` (required)
- `dashboard_title` (required for consistency in replay/UI payloads)
- `title_meta` (optional, future enhancement)

Example:
```json
{
  "dashboard_id": "dash_123",
  "title": "LPG Plant Throughput Performance Overview",
  "title_meta": {"source": "llm", "base_title": "LPG Throughput Overview", "confidence": 0.84},
  "charts": [
    {
      "chart_id": "chart_01",
      "title": "Production MT Trend by Process Date",
      "dashboard_title": "LPG Plant Throughput Performance Overview",
      "title_meta": {"source": "deterministic", "confidence": 0.93}
    }
  ]
}
```

## `quantyx_chart_requests` (existing)
On initial deployment run, chart rows persist:
- `question` = chart title
- `query_payload.chart_title`
- `query_payload.dashboard_title`
- `query_payload.table` (context for title quality and replay)

Example `query_payload`:
```json
{
  "metrics": ["total_production"],
  "dimensions": ["period"],
  "chart": "line",
  "chart_title": "Total Production Trend Over Process Date",
  "dashboard_title": "LPG Production Distribution Dashboard",
  "table": "lpg_plant_operations"
}
```

## `quantyx_agent_run_events` / stage artifacts (existing)
Dashboard completion artifacts now include:
- `dashboard_id`
- `dashboard_title`
- `chart_ids`
- `chart_titles`
- `chart_details` (each chart includes `title`, `dashboard_title`, `chart_id`, etc.)

This ensures `/chat` by `run_id` replay can return titles consistently without UI-side title synthesis.

---

## API Plan

## 1) On generation endpoints (existing)
No payload change required; backend guarantees titles are always set.
- `POST /workspace/deployments`
- dashboard generation in agentic flow
- `POST /agentic/runs` (if used internally)

## 2) `GET /dashboards` and `GET /dashboards/{dashboard_id}`
Must always return contextual dashboard title and chart titles.
- implemented: responses now normalize missing titles with deterministic fallback and include chart title lists for UI rendering.

## 2.1) Run replay/chat APIs
`GET /chat` by `run_id` and stream-replay payloads must include dashboard/chart titles from persisted artifacts, not regenerated labels.

## 3) `PUT /dashboards/{dashboard_id}`
Allow optional title updates:
- dashboard title override
- chart title override by `chart_id`
- implemented: `action=update_titles` with `title` and `chart_updates[]`.

Request example:
```json
{
  "title": "North Zone LPG Distribution Command Center",
  "chart_updates": [
    {"chart_id": "chart_01", "title": "North Zone Pending Volume Trend"}
  ]
}
```

## 4) Refresh behavior
`POST /dashboards/{dashboard_id}/refresh`
- preserve manual overrides by default.
- regenerate titles only for:
  - new charts
  - charts with missing/invalid titles
  - when `regenerate_titles=true` is passed.

---

## Agent Responsibilities
1. `DashboardAgent`
- produce dashboard-level title using full chart context.
2. `ChartPlannerAgent` / `ChartAgent`
- produce per-chart contextual titles.
 - pass final `chart_title` into chart persistence payload.
3. `RefreshAgent` path
- validate title quality, preserve overrides, regenerate where needed.

---

## Quality Gate Rules
1. Block generic titles:
- regex blacklist: `^(auto dashboard|chart\\s*\\d+|untitled.*)$` (case-insensitive)
2. Ensure chart title contains at least one metric or dimension token from chart payload.
3. Ensure dashboard title reflects dominant domain/metric cluster.
4. Emit warnings in refresh events when title quality is degraded.

---

## Implementation Phases

### Phase 27.1: Deterministic naming foundation
- central title builder utility (dashboard + chart)
- enforce title population in all generation paths
- add quality gate validation
- status: implemented for initial run path; fallback now derives domain-based dashboard title when missing.

### Phase 27.2: LLM rewrite + fallback
- optional LLM rewrite service for concise natural titles
- fallback to deterministic titles on failure
- persist `title_meta`
- status: planned.

### Phase 27.3: API + override controls
- extend dashboard update API for title overrides
- preserve manual overrides on refresh
- add `regenerate_titles` refresh option
- status: partially implemented (`PUT /dashboards/{dashboard_id}` now supports `update_titles` and `delete_chart`); `regenerate_titles` and `title_meta` governance are pending.

### Phase 27.4: Observability and regression tests
- metrics: `% generic titles`, `% overridden titles`, `% regenerated on refresh`
- test cases for create, refresh, old dashboard migration, and override preservation
- status: pending.

---

## Implemented Behavior (As of March 10, 2026)
1. Initial deployment run now always sets `dashboard_title` before persistence.
2. Dashboard title is persisted in:
- `quantyx_dashboard_specs.title`
- `quantyx_dashboard_specs.spec.title`
- `quantyx_dashboard_specs.spec.dashboard_title`
3. Chart title is persisted in:
- `quantyx_chart_requests.question`
- `quantyx_chart_requests.query_payload.chart_title`
4. Dashboard title is also persisted with chart row:
- `quantyx_chart_requests.query_payload.dashboard_title`
5. Stream/replay artifacts include both title levels:
- `dashboard_title`
- `chart_titles`
- `chart_details[].title`
- `chart_details[].dashboard_title`
6. Dashboard retrieval endpoints normalize titles for old specs:
- `GET /dashboards` returns `title`, `name`, `dashboard_title`, and `chart_titles`.
- `GET /dashboards/{dashboard_id}` returns normalized `spec.title`, `spec.dashboard_title`, and per-chart `title`.
7. Manual title override API:
- `PUT /dashboards/{dashboard_id}` with `action=update_titles` updates dashboard and chart titles in persisted dashboard spec.

Result: UI can render stable titles directly from backend payloads for both live stream and replay GET flows, including initial run artifacts.

---

## Acceptance Criteria
1. 100% of generated dashboards and charts have non-empty contextual titles.
2. No generic placeholder titles appear in API responses.
3. Manual title overrides persist across refresh by default.
4. Title regeneration can be explicitly triggered via API.
5. Old dashboards can be backfilled with contextual titles without breaking chart IDs.
