# Phase 24: Tenant/Domain Deployment Run + Conversational Workspace

## Objective
Treat each `tenant_id + domain_id` as a deployed semantic workspace with one canonical run, then attach all user analytics conversations to that deployed workspace.

This phase changes the model from "many ad-hoc run IDs" to "deployment-style run lifecycle + persistent conversation memory".

---

## Problem Statement
- Multiple run IDs for the same tenant/domain create ambiguity for chat resolution and history replay.
- Run completion is not consistently used as a stable "deployed/ready" marker.
- Chat conversations are not formally modeled as workspace sessions with persisted analytical artifacts.

---

## Target State
1. Exactly one canonical deployed run per `tenant_id + domain_id`.
2. Canonical run has explicit lifecycle in DB (`queued`, `running`, `completed`, `failed`, `superseded`).
3. Canonical run and conversations have short display names/titles generated in LLM style for UI.
4. UI can select tenant/domain and immediately start chat against deployed context.
5. All conversations are persisted and queryable, including data/graph/inference artifacts.
6. Rebuild creates a new run version and supersedes the previous canonical run.

---

## Scope
1. Canonical deployment run semantics and status transitions.
2. Tenant/domain to canonical run resolution API.
3. Conversation/session model scoped to tenant/domain (+ canonical run version).
4. LLM-style short display names for runs and conversation titles.
5. Persistence of chat question/answer + chart payload + data preview + inference.
6. Backward compatibility for existing `run_id`-based APIs.

Out of scope:
- Replacing dashboard refresh logic (Phase 23 remains separate).
- Rewriting all legacy run endpoints in one step.

---

## Data Model Changes

## 1) `quantyx_agent_runs` (extend existing)
Add/confirm fields:
- `status` (already present; enforce controlled values)
- `is_canonical BOOLEAN NOT NULL DEFAULT false`
- `version_no INT NOT NULL DEFAULT 1`
- `display_name TEXT NULL` (e.g., `LPG Ops Deployment v4`)
- `superseded_by_run_id TEXT NULL`
- `completed_at TIMESTAMPTZ NULL`

Indexes/constraints:
- Partial unique index for one canonical run per tenant/domain:
```sql
CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_runs_canonical_scope
  ON public.quantyx_agent_runs (tenant_id, domain_id)
  WHERE is_canonical = true;
```

Recommended status domain:
- `queued | running | completed | failed | superseded`

## 2) `quantyx_workspace_conversations` (new)
```sql
CREATE TABLE IF NOT EXISTS public.quantyx_workspace_conversations (
  conversation_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  run_id TEXT NOT NULL, -- canonical run used when conversation started
  title TEXT NULL, -- primary UI label (LLM-generated short title)
  display_name TEXT NULL, -- optional explicit short label if title is long
  status TEXT NOT NULL DEFAULT 'active', -- active|archived
  created_by TEXT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_workspace_conversations_scope
  ON public.quantyx_workspace_conversations (tenant_id, domain_id, created_at DESC);
```

## 3) `quantyx_workspace_messages` (new)
```sql
CREATE TABLE IF NOT EXISTS public.quantyx_workspace_messages (
  message_id TEXT PRIMARY KEY,
  conversation_id TEXT NOT NULL,
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  run_id TEXT NOT NULL,
  sender TEXT NOT NULL, -- user|assistant|system
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
```

---

## API Plan

Customer-first API behavior:
1. APIs return `display_name`/`title` by default; IDs remain present but secondary.
2. `PUT` is supported for user-driven edits (rename/archive/switch deployment).
3. `DELETE` is soft-delete for conversations only.
4. Deployment runs are immutable records and are never hard-deleted by API.
5. Conversation responses are SSE-streamed by default; non-streamed reply is opt-in.

### A) Deployments

## 1) `GET /workspace/deployments/current?tenant_id=...&domain_id=...`
Returns canonical deployed run for tenant/domain.

Response:
```json
{
  "tenant_id": "VC_101",
  "domain_id": "lpg_production_distribution",
  "run_id": "run_1a0f427c86ec",
  "display_name": "LPG Distribution Deployment v4",
  "status": "completed",
  "version_no": 4,
  "completed_at": "2026-03-06T21:54:18.326901Z"
}
```

## 2) `GET /workspace/deployments?tenant_id=...&domain_id=...`
List deployment history for picker/audit (latest first).

## 3) `POST /workspace/deployments`
Starts deployment run for tenant/domain (first build or next version); supersedes previous canonical on success.

Request:
```json
{
  "tenant_id": "VC_101",
  "domain_id": "lpg_production_distribution",
  "mode": "full"
}
```

## 4) `PUT /workspace/deployments/{run_id}`
Allow only metadata/status actions:
- update `display_name`
- mark as canonical (admin-safe guarded action)

Request:
```json
{
  "display_name": "LPG Distribution Deployment v5",
  "make_canonical": false
}
```

DELETE decision:
- No `DELETE /workspace/deployments/{run_id}` in customer APIs.
- Reason: deployment run is audit lineage and should remain immutable.

### B) Conversations

## 5) `POST /workspace/conversations`
Create a new conversation bound to resolved canonical run.

## 6) `GET /workspace/conversations?tenant_id=...&domain_id=...&status=active`
List conversations with:
- `conversation_id`
- `title`
- `display_name`
- `run_display_name`
- `last_message_at`

## 7) `GET /workspace/conversations/{conversation_id}`
Get conversation metadata, pinned run, and summary counters.

## 8) `PUT /workspace/conversations/{conversation_id}`
Update user-editable metadata and lifecycle:
- rename `title`/`display_name`
- archive/unarchive (`status`)
- switch to latest canonical run (explicit action)

Request:
```json
{
  "title": "North Zone Bottleneck Analysis",
  "status": "active",
  "switch_to_latest_run": false
}
```

## 9) `DELETE /workspace/conversations/{conversation_id}`
Soft delete only:
- marks conversation as `deleted`
- keeps messages for audit/restore policy window

### C) Messages

## 10) `POST /workspace/conversations/{conversation_id}/messages`
Create user turn and stream assistant response/events via SSE by default.

Request:
```json
{
  "message_text": "Show top 5 plants with highest pending volume trend for last 30 days",
  "resume_context": true,
  "stream": true
}
```

SSE event sequence (example):
- `message_start`
- `token` (repeated incremental text chunks)
- `artifact` (`sql_text`, `chart_json`, `data_json`, `summary_json`, `inference_json`)
- `message_end`
- `done`

If `stream=false`, return single JSON response with:
- assistant text
- `sql_text` (if generated)
- `data_json`
- `chart_json`
- `summary_json`
- `inference_json`
- `context_used`

## 11) `GET /workspace/conversations/{conversation_id}/messages?limit=...&cursor=...`
Replay message history in chronological order with artifacts.

## 12) `GET /workspace/conversations/{conversation_id}/messages/{message_id}`
Retrieve one message with full artifact payload.

## 12a) `GET /workspace/conversations/{conversation_id}/messages/stream`
Optional dedicated SSE endpoint for clients that require stream-only transport.
Query params:
- `message_text`
- `resume_context` (default true)

## 13) `PUT /workspace/conversations/{conversation_id}/messages/{message_id}`
Allowed only for governance operations:
- redact sensitive text
- attach moderation metadata

DELETE decision:
- No hard delete for messages.
- Optional `DELETE` can be admin-only soft redact, not physical removal.

### D) Conversation Memory / Context

## 14) `GET /workspace/conversations/{conversation_id}/context`
Return effective context package used for next response.

## 15) `PUT /workspace/conversations/{conversation_id}/context/rebuild`
Force memory compaction recompute from raw message history.

## 16) `GET /workspace/conversations/{conversation_id}/memory`
Return persisted compact memory (`summary_text`, `memory_json`, version/timestamp).

## 17) `PUT /workspace/conversations/{conversation_id}/memory`
Admin/support override for corrected memory entries when needed.

---

## Streaming UX Contract (ChatGPT-like)
1. UI sends message once and begins rendering streamed assistant output immediately.
2. Partial text must be persisted incrementally or at least checkpointed, then finalized at `message_end`.
3. Artifact events may arrive before final text completion and should render progressively.
4. On stream interruption:
   - persist partial assistant response with status `interrupted`
   - client may call retry/resume endpoint with last received token offset.
5. Final persisted assistant message should include complete stitched text and all artifacts.

---

## Display Name and Title Rules
1. `run_id` and `conversation_id` remain system identifiers; UI should show display names/titles by default.
2. Generate run display name on completion of deployment:
   - format: `<Domain Focus> Deployment v<version_no>`
   - example: `LPG Plant Performance Deployment v4`
3. Generate conversation title at conversation creation or after first user query:
   - max 6-10 words
   - action/topic oriented
   - example: `North Zone Bottleneck Analysis`
4. Deterministic fallback when LLM unavailable:
   - run: `<domain_id> Deployment v<version_no>`
   - conversation: `Conversation <YYYY-MM-DD HH:MM>`
5. Titles are mutable; IDs are immutable.
6. APIs should return both IDs and display names, but UI should hide raw IDs unless debug mode is enabled.

---

## Canonical Run Resolution Rules
1. Prefer `is_canonical=true` + latest `updated_at`.
2. If canonical missing, fallback to latest `status='completed'`.
3. If none completed, return `404` with explicit guidance to trigger deployment.

---

## Run Lifecycle Rules
1. Rebuild request creates new run (`queued`, `is_canonical=false` initially).
2. Worker marks `running` on start.
3. On success:
   - mark new run `completed`, set `completed_at`.
   - set `is_canonical=true`.
   - mark previous canonical run `superseded`, `is_canonical=false`, `superseded_by_run_id=<new_run_id>`.
4. On failure:
   - mark run `failed`.
   - keep previous canonical run unchanged.

---

## Conversation Persistence Rules
1. Every user query is stored as a `user` message.
2. Every assistant response is stored as an `assistant` message with:
   - response text
   - SQL (if generated)
   - data payload/sample
   - chart payload/spec
   - summary/inference payloads
3. Message rows remain immutable; corrections create new message rows.
4. Conversation remains pinned to its starting `run_id` for replay consistency.

---

## Conversation Resume Context Strategy
Users can always start a new conversation for a tenant/domain, and resumed conversations must carry prior context.

### New Conversation
1. `POST /workspace/conversations` creates a fresh `conversation_id`.
2. Conversation is bound to selected `tenant_id`, `domain_id`, and resolved canonical `run_id`.
3. No prior conversational memory is injected.

### Resumed Conversation
1. Client sends follow-up to `POST /workspace/conversations/{conversation_id}/messages`.
2. Server builds context package before response generation:
   - recent turns window (`last_n_turns`, token bounded)
   - compact memory summary (`conversation_summary`)
   - structured memory (`resolved_metrics`, `resolved_dimensions`, `active_filters`, `time_window`, `open_questions`)
3. Response generation uses this context package plus current semantic workspace artifacts.

### Memory Compaction
1. Every `K` turns (e.g., 4) or when token threshold is crossed:
   - generate/update `conversation_summary` (short factual recap)
   - update structured memory fields
2. Persist compaction result in DB so resume is deterministic and cheap.
3. Never drop raw message history; compaction is additive.

### Storage Additions (Required)
Required table:
```sql
CREATE TABLE IF NOT EXISTS public.quantyx_workspace_conversation_memory (
  memory_id TEXT PRIMARY KEY,
  conversation_id TEXT NOT NULL,
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  run_id TEXT NOT NULL,
  summary_text TEXT NULL,
  memory_json JSONB NOT NULL, -- metrics/dimensions/filters/time/open_questions
  last_message_at TIMESTAMPTZ NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_workspace_memory_conversation
  ON public.quantyx_workspace_conversation_memory (conversation_id);
```

### Runtime Policy for Run Changes
1. Default: conversation stays pinned to original `run_id` for consistency.
2. If tenant/domain has a newer canonical deployment:
   - UI may offer "Switch to latest deployment".
   - if switched, record a system message/event and update conversation binding.

### API Behavior Additions
1. `POST /workspace/conversations/{conversation_id}/messages`
   - request option: `"resume_context": true` (default true)
   - response includes `context_used` metadata (`turns_loaded`, `memory_version`, `run_id`)
2. `GET /workspace/conversations/{conversation_id}/context` (debug/admin)
   - returns effective context package used for next answer.

### Acceptance Criteria (Resume)
1. Follow-up questions in same conversation use prior filters, entities, and intent without user re-specifying.
2. New conversations do not leak context from other conversations.
3. Context retrieval remains tenant/domain isolated and run-safe.
4. Long conversations maintain quality via compaction without losing auditability.

---

## Backward Compatibility
- Existing `/agentic/runs/{run_id}/...` APIs remain supported.
- New workspace APIs sit on top of canonical run resolution.
- Existing run IDs can still be used for explicit debugging/replay.

---

## Implementation Phases

### Phase 24.1: Canonical run model
- DB alters + indexes for canonical run fields
- run completion/supersede logic in orchestrator
- current deployment resolution endpoint
- run `display_name` generation and persistence

### Phase 24.2: Workspace conversation storage
- add conversation/message tables
- persist user + assistant analytics artifacts
- conversation list + replay APIs
- conversation `title`/`display_name` generation and update flow

### Phase 24.3: UI integration and migration
- tenant/domain selection resolves canonical run
- default chat path uses workspace conversation APIs
- migration helpers for legacy run-chat records

### Phase 24.4: Hardening
- idempotency keys for message writes
- pagination + retention policies
- audit fields, access controls, and observability metrics

---

## Acceptance Criteria
1. Only one canonical run exists per tenant/domain at any time.
2. Completed deployment run is visible via current deployment API.
3. Rebuild success supersedes old canonical run without losing history.
4. Conversations are listable and replayable with full analytical artifacts.
5. User can chat immediately after selecting tenant/domain, without manually passing run ID.
