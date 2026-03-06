# Phase 22: Agent Metadata Summary + Inference Stream Compaction

## Objective
Improve agent output usability and latency by splitting heavy metadata into:
- compact raw JSON for machines,
- user-readable summary (text + HTML),
- user-readable inference (text + HTML),
while avoiding oversized payloads in stream/chat storage.

This phase ensures we do not block the next agent while summary/inference formatting is generated.

---

## Problem Statement
- Current event metadata is too large and too raw (especially distinct/sample payloads).
- UI users must inspect full JSON to understand what happened.
- Stream "completed" appears only after all post-processing, delaying perceived progress.
- Full profiling payloads are being over-shared in persisted JSON/stream.

---

## Scope
1. Add new metadata fields to agent event artifacts:
   - `summary_raw_text`
   - `summary_html`
   - `inference_raw_text`
   - `inference_html`
2. Split completion into staged statuses:
   - raw JSON ready
   - summary ready
   - inference ready
   - completed
3. Run summary and inference generation in parallel and non-blocking to next agent.
4. Persist full history for replay in chat/event APIs (JSON + summary + inference + HTML).
5. Cap high-volume profiling/sample metadata in persisted JSON and stream payloads.

Out of scope:
- Changing core semantic resolution logic.
- Replacing existing agent orchestration graph design.

---

## UX Requirements
- Users should immediately see compact raw output and continue to next agent.
- Users should then receive progressively richer explanations:
  1) raw JSON snapshot
  2) summary
  3) inference
- HTML should be formatted for direct UI rendering.
- History should preserve all generated forms for later inspection.

---

## Event Lifecycle (New)
For each agent node, emit lifecycle status in this order:

1. `queued`
2. `running`
3. `raw_json_ready`
4. `summary_ready`
5. `inference_ready`
6. `completed`

Notes:
- `completed` means raw + summary + inference are all persisted.
- Next agent can start immediately after `raw_json_ready`.
- `summary_ready` and `inference_ready` may arrive in any order.

---

## Artifact Contract (Per Event)

```json
{
  "agent_name": "ProfilingAgent",
  "status": "summary_ready",
  "message": "Profiling summary ready",
  "artifacts": {
    "raw_json": {},
    "summary_raw_text": "Detected 4 fact-like tables and 18 dimensions.",
    "summary_html": "<section><h4>Profiling Summary</h4><ul><li>Fact-like tables: 4</li><li>Dimensions: 18</li></ul></section>",
    "inference_raw_text": "Plant-level grain is dominant; sap_id behaves as a high-confidence key.",
    "inference_html": "<section><h4>Inference</h4><p>Plant-level grain is dominant...</p></section>",
    "truncation": {
      "applied": true,
      "sample_limit": 50,
      "fields_truncated": ["sample_values.sap_id", "sample_values.region"]
    }
  }
}
```

---

## Storage Model Changes

### 1) Persist every stage as a first-class DB event
Each agent stage (`queued`, `running`, `raw_json_ready`, `summary_ready`, `inference_ready`, `completed`) must be written to `quantyx_agent_run_events` as its own row.

Schema updates:
```sql
ALTER TABLE public.quantyx_agent_run_events
  ADD COLUMN IF NOT EXISTS stage_name TEXT NULL,                 -- queued|running|raw_json_ready|summary_ready|inference_ready|completed
  ADD COLUMN IF NOT EXISTS stage_seq INT NULL,                   -- 1..6 ordering within logical event
  ADD COLUMN IF NOT EXISTS logical_event_id TEXT NULL,           -- stable id for one agent output lifecycle
  ADD COLUMN IF NOT EXISTS payload_compacted BOOLEAN NOT NULL DEFAULT false;

CREATE INDEX IF NOT EXISTS idx_agent_run_events_run_stage
  ON public.quantyx_agent_run_events (run_id, created_at, stage_seq);
```

Stage persistence rule:
- one `logical_event_id` per agent output;
- six rows per lifecycle (minimum four if `queued/running` are already emitted elsewhere);
- never overwrite prior stage rows.

### 2) Store rich artifacts separately
Keep `quantyx_agent_run_events` lightweight and create `quantyx_agent_event_artifacts`.

### `quantyx_agent_event_artifacts`
```sql
CREATE TABLE IF NOT EXISTS public.quantyx_agent_event_artifacts (
  artifact_id TEXT PRIMARY KEY,
  event_id TEXT NOT NULL,
  logical_event_id TEXT NOT NULL,
  run_id TEXT NOT NULL,
  agent_name TEXT NOT NULL,
  stage_name TEXT NOT NULL,                 -- raw_json_ready|summary_ready|inference_ready|completed
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
```

Benefits:
- avoids bloating `quantyx_agent_run_events`,
- allows progressive updates for same event (`raw_json_ready` -> `summary_ready` -> `inference_ready`).

### 3) Link chat history to exact stage records
`GET /agentic/runs/{run_id}/chat` must be able to replay all stage payloads, so add event linkage in chat log.

```sql
ALTER TABLE public.quantyx_agent_chat_log
  ADD COLUMN IF NOT EXISTS event_id TEXT NULL,
  ADD COLUMN IF NOT EXISTS stage_name TEXT NULL,
  ADD COLUMN IF NOT EXISTS logical_event_id TEXT NULL;

CREATE INDEX IF NOT EXISTS idx_agent_chat_log_run_stage
  ON public.quantyx_agent_chat_log (run_id, created_at);
```

---

## API Changes

## Existing endpoints (enhance with explicit payload contracts)

### 0) Common response contract for staged APIs

All stage-aware responses should include:
- `event_id`
- `logical_event_id`
- `stage_name`
- `stage_seq`
- `payload_compacted`
- `created_at`

Standard stage ordering map:
```json
{
  "queued": 1,
  "running": 2,
  "raw_json_ready": 3,
  "summary_ready": 4,
  "inference_ready": 5,
  "completed": 6
}
```

## `GET /agentic/runs/{run_id}/events`
Query params:
- `include=raw_json,summary,inference,html`
- `compact=true|false` (default `true`)
- `limit` (default 200)
- `stage_name` (optional filter: `queued|running|raw_json_ready|summary_ready|inference_ready|completed`)
- `agent_name` (optional filter)

Request example:
```http
GET /agentic/runs/run_123/events?include=raw_json,summary,html&compact=true&stage_name=summary_ready&limit=50
```

Response:
```json
{
  "events": [
    {
      "event_id": "event_1",
      "logical_event_id": "le_abc",
      "agent_name": "ProfilingAgent",
      "status": "raw_json_ready",
      "stage_name": "raw_json_ready",
      "stage_seq": 3,
      "message": "Profiling raw payload ready",
      "payload_compacted": true,
      "created_at": "2026-03-06T10:00:00Z",
      "artifacts": {
        "raw_json": {
          "tables": 4,
          "sample_values": {
            "sap_id": {"sent_count": 50, "total_count": 3452, "truncated": true}
          }
        }
      }
    },
    {
      "event_id": "event_2",
      "logical_event_id": "le_abc",
      "agent_name": "ProfilingAgent",
      "status": "summary_ready",
      "stage_name": "summary_ready",
      "stage_seq": 4,
      "message": "Profiling summary ready",
      "payload_compacted": true,
      "created_at": "2026-03-06T10:00:01Z",
      "artifacts": {
        "summary_raw_text": "Detected 4 fact-like tables and 18 dimensions.",
        "summary_html": "<section><h4>Profiling Summary</h4><ul><li>Fact-like tables: 4</li></ul></section>"
      }
    }
  ],
  "paging": {
    "limit": 50,
    "returned": 2
  }
}
```

Error response example:
```json
{
  "detail": "Run not found"
}
```

## `GET /agentic/runs/{run_id}/chat`
Query params:
- `include=raw_json,summary,inference,html`
- `include_stages=true|false` (default `true`)
- `limit` (default 200)
- `sender=system|agent` (optional filter)

Request example:
```http
GET /agentic/runs/run_123/chat?include_stages=true&include=summary,inference,html&limit=100
```

Response:
```json
{
  "messages": [
    {
      "message_id": "msg_1",
      "run_id": "run_123",
      "sender": "agent",
      "message": "Profiling summary ready",
      "event_id": "event_2",
      "logical_event_id": "le_abc",
      "stage_name": "summary_ready",
      "artifacts": {
        "summary_raw_text": "Detected 4 fact-like tables and 18 dimensions.",
        "summary_html": "<section><h4>Profiling Summary</h4>...</section>"
      },
      "created_at": "2026-03-06T10:00:00Z"
    }
  ],
  "paging": {
    "limit": 100,
    "returned": 1
  }
}
```

## New endpoint (recommended)
## `GET /agentic/runs/{run_id}/events/{event_id}/artifacts`
Request example:
```http
GET /agentic/runs/run_123/events/event_2/artifacts?include=raw_json,summary,inference,html
```

Response:
```json
{
  "event_id": "event_2",
  "logical_event_id": "le_abc",
  "run_id": "run_123",
  "agent_name": "ProfilingAgent",
  "stage_name": "summary_ready",
  "raw_json": {},
  "summary_raw_text": "...",
  "summary_html": "<section>...</section>",
  "inference_raw_text": "...",
  "inference_html": "<section>...</section>",
  "truncation": {},
  "created_at": "2026-03-06T10:00:01Z",
  "updated_at": "2026-03-06T10:00:02Z"
}
```

Error response example:
```json
{
  "detail": "Artifacts not found for event_id=event_2"
}
```

## SSE stream behavior
- `/agentic/runs/{run_id}/stream` should emit staged events per status above.
- Stream payload must send compact raw JSON only (truncated projection).

SSE event payload example:
```text
event: agent_stage
data: {"run_id":"run_123","event_id":"event_2","logical_event_id":"le_abc","agent_name":"ProfilingAgent","status":"summary_ready","stage_name":"summary_ready","stage_seq":4,"message":"Profiling summary ready","payload_compacted":true,"artifacts":{"summary_raw_text":"Detected 4 fact-like tables and 18 dimensions."},"created_at":"2026-03-06T10:00:01Z"}
```

Heartbeat payload example:
```text
: heartbeat
```

## Backward Compatibility
- If `include` is omitted, default include set is `summary,inference`.
- Legacy clients should continue to parse existing fields (`agent_name`, `status`, `message`) without stage fields.
- When `AGENTIC_ARTIFACTS_V2_ENABLED=false`, APIs may return only legacy `artifacts` JSON from `quantyx_agent_run_events`.

---

## Orchestration Changes

1. Agent produces full internal result in runtime state (not streamed/stored fully).
2. Create compact projection for persisted `raw_json`.
3. Persist stage row + artifact row and emit `raw_json_ready`.
4. Trigger `summary` and `inference` generation tasks in parallel.
5. As each finishes, persist stage row + artifact row and emit `summary_ready` / `inference_ready`.
6. Persist final stage row + artifact snapshot and emit `completed` when both are done.

Important:
- downstream agent execution should continue after `raw_json_ready`.
- summary/inference tasks must not block workflow critical path.

---

## Profiling Payload Compaction Rules

Default limits:
- `AGENTIC_STREAM_SAMPLE_LIMIT=50`
- hard max allowed `100`

Rules:
1. For `sample_values`/`distinct` arrays, persist only first N.
2. Persist counts and truncation metadata:
   - `total_count`
   - `sent_count`
   - `truncated=true/false`
3. Never stream/store full raw value lists beyond limit.
4. Keep full in-memory/runtime representation only for agent-to-agent use.

Example compact field:
```json
{
  "sample_values": {
    "sap_id": {
      "values": ["1001", "1002", "..."],
      "sent_count": 50,
      "total_count": 3452,
      "truncated": true
    }
  }
}
```

---

## HTML Formatting Guidelines
- Use safe, deterministic templates only (no script/style injection).
- Required structure:
  - `<section>`
  - `<h4>` heading
  - `<p>` summary paragraph
  - `<ul>/<li>` key bullets
  - optional `<table>` for top metrics (max 10 rows)
- Escape all values.
- Keep HTML under configurable size limit (for example 32KB per field).

---

## Implementation Plan

1. Data model + migrations
   - add stage columns to `quantyx_agent_run_events`
   - add `quantyx_agent_event_artifacts`
   - add event linkage columns on `quantyx_agent_chat_log`

2. Store layer updates
   - add append-stage-event helper (`logical_event_id`, `stage_name`, `stage_seq`)
   - add upsert/get methods for artifacts
   - add chat append with `event_id`, `logical_event_id`, `stage_name`
   - add compact projection helper + truncation metadata

3. Orchestrator updates
   - emit new staged statuses
   - run summary/inference in parallel background tasks
   - decouple agent progression from post-processing completion

4. API updates
   - extend `/events`, `/chat`, `/stream` payloads with stage fields
   - add `/agentic/runs/{run_id}/events/{event_id}/artifacts`

5. UI integration
   - render `summary_html` and `inference_html`
   - fallback to raw text if HTML unavailable

6. Guardrails + config
   - enforce sample limits and payload caps
   - reject oversized HTML and store fallback text

---

## Success Criteria
- Users can read summary/inference without opening full JSON.
- Next agent starts without waiting for summary/inference generation.
- Stream shows progressive statuses: raw -> summary -> inference -> completed.
- Chat history replay includes JSON + summary + inference + HTML for every step.
- Profiling stream/event payloads never exceed configured sample limits.
- `GET /agentic/runs/{run_id}/chat` returns stage-complete history even after run completion/reload.

---

## Risks and Mitigations
- Risk: extra events increase stream volume.
  - Mitigation: compact payloads + optional include filters in APIs.
- Risk: HTML generation failures.
  - Mitigation: always persist `*_raw_text`; HTML optional with fallback.
- Risk: race conditions on parallel artifact writes.
  - Mitigation: upsert by `(event_id)` and field-level updates.

---

## Rollout Strategy
1. Ship schema + write path behind feature flag:
   - `AGENTIC_ARTIFACTS_V2_ENABLED=true`
2. Enable for non-prod tenants.
3. Validate stream/chat replay and payload sizes.
4. Enable globally and deprecate oversized legacy artifact payloads.

---

## Dependencies
- Depends on Phase 11 (Streaming Progress + Chat Log Persistence).
- Depends on Phase 12 (Storage Model tables and migration pattern).
- Depends on Phase 20 (orchestration state + node execution behavior).
- Updates Phase 19 (architecture) and Phase 21 (UI/API flow) with staged metadata lifecycle.
