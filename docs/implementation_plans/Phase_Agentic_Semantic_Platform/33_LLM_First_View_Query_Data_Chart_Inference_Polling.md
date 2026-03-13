# 33. LLM-First View Query: Data + Chart + Inference (Polling)

## Objective
- Keep `/views/query` fast for immediate data tab rendering.
- Generate chart and inference asynchronously for the same query.
- Use LLM as the primary planner/generator for chart + inference.
- Keep deterministic charting as fallback only.
- Expose consistent polling-friendly APIs for UI tabs: `data`, `chart`, `inference`.

## UX Contract
- User submits SQL once.
- UI gets immediate `data` and `query_id`.
- UI polls by `query_id` for chart and inference readiness.
- UI stops polling when both `chart_status` and `inference_status` reach terminal states.

## API Contract

### 1) `POST /views/query`
Purpose:
- Execute SQL immediately.
- Return data payload and `query_id`.
- Trigger async LLM chart/inference jobs.

Response contract:
- `query_id`
- `data_status` (always `ready` if query succeeds)
- `chart_status` (`pending`)
- `inference_status` (`pending`)
- `data` (`columns`, `rows`, `row_count`)
- `chart` (`null` initially)
- `inference` (`null` initially)
- `errors` object
- `created_at`, `updated_at`

### 2) `GET /views/query/{query_id}`
Purpose:
- Return latest query state for all tabs.

Response contract:
- `query_id`, scope metadata
- `data_status`, `chart_status`, `inference_status`
- `chart_source` (`llm` or `deterministic_fallback`)
- `inference_source` (`llm` or `fallback_template`)
- `chart_confidence`, `inference_confidence`
- `data`, `chart`, `inference`
- `errors` (`chart_error`, `inference_error`)
- timestamps

### Optional 3) `GET /views/query/{query_id}/status`
Purpose:
- Lightweight status polling endpoint.

## Status Model

### Shared status enum (chart/inference)
- `pending`
- `running`
- `ready`
- `failed`
- `skipped`

### Terminal states
- `ready`, `failed`, `skipped`

UI rule:
- Stop polling when both `chart_status` and `inference_status` are terminal.

## Storage Plan
- Add or extend query job table keyed by `query_id`.
- Store:
  - identity: `tenant_id`, `domain_id`, `query_id`
  - request: `sql_text`, optional `user_query`
  - data: `data_json`
  - chart: `chart_json`, `chart_status`, `chart_source`, `chart_confidence`, `chart_error`
  - inference: `inference_json`, `inference_status`, `inference_source`, `inference_confidence`, `inference_error`
  - timestamps
- Indexes:
  - unique `query_id`
  - `(tenant_id, domain_id, created_at desc)`

## LLM-First Chart Generation

### Inputs to LLM
- SQL text
- result schema (column names/types)
- sampled rows + aggregate stats
- domain context + charting constraints

### Required output (strict JSON)
- `chart_type`
- `x_field`, `y_field`, optional `series_field`
- `amcharts_payload`
- `color_tokens`
- `reason`
- `confidence`

### Validation
- Server validates shape/type compatibility.
- Reject invalid LLM output and trigger fallback.

## Deterministic Fallback (Safety Only)
- Trigger only when:
  - LLM parse fails
  - output invalid for schema
  - timeout/error
  - confidence below threshold
- Build chart by result-shape heuristics.
- Mark `chart_source = deterministic_fallback`.

## LLM Inference Generation

### Inputs
- SQL + result profile + chart decision.

### Output JSON
- `summary`
- `key_findings[]`
- `caveats[]`
- `confidence`

### Fallback
- Use factual template summary if LLM fails.
- Mark `inference_source = fallback_template`.

## amCharts Color Strategy (Non-Monotonic)
- LLM returns palette tokens, not raw arbitrary colors.
- Backend token resolver maps to approved theme palette.
- Enforce semantic coloring:
  - trend up/down
  - warning/critical thresholds
  - categorical palette rotation
- Keep output deterministic per token map for UI consistency.

## Async Execution Model
- `POST /views/query` writes initial row and returns immediately.
- Background workers:
  - set `chart_status = running` -> `ready|failed|skipped`
  - set `inference_status = running` -> `ready|failed|skipped`
- Update `updated_at` on every transition.

## Observability
- Structured logs by `query_id`:
  - LLM request/response validation
  - fallback reason
  - status transitions
  - timings
- Metrics:
  - LLM chart success rate
  - fallback rate
  - mean chart ready latency
  - mean inference ready latency

## Rollout Phases

### Phase A: Data + Query Job Baseline
- Persist `query_id` row and return immediate data.
- Add status fields and polling endpoint.

### Phase B: LLM Chart + Validation
- Implement LLM chart planner and validator.
- Persist amCharts payload and chart status.

### Phase C: LLM Inference + Validation
- Implement inference generator and persistence.

### Phase D: Fallback + Reliability
- Add deterministic chart fallback and template inference fallback.
- Add retries/timeouts and robust error propagation.

### Phase E: OpenAPI + UI Integration
- Add examples for:
  - immediate POST response
  - in-progress poll response
  - completed response
  - failed/skipped scenarios
- Finalize UI polling stop conditions.

## Acceptance Criteria
- `POST /views/query` always returns data quickly with `query_id`.
- UI can render `data` immediately and poll for chart/inference.
- LLM output drives chart selection in primary path.
- Deterministic fallback handles LLM failures safely.
- Chart payload includes resolved color theme tokens.
- API payload shape remains consistent across pending/running/ready/failed/skipped states.
