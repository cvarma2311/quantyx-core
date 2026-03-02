# Phase 11: Streaming Progress + Chat Log Persistence

## Objective
Provide a streaming, high‑level lifecycle view of the multi‑agent workflow after schema selection, and persist the entire chat/progress stream in the backend regardless of UI visibility.

---

## User Experience Requirements
- As soon as schema selection begins, stream **high‑level progress updates**.
- Show **which agent is running**, what was produced, and what's next.
- Provide **natural‑language status updates** (not just raw logs).
- Allow UI to **hide** the stream (background mode), but backend must still execute and store all progress messages.
- Streams must be **safe and summarized** (no chain‑of‑thought or internal reasoning details).

---

## Backend Behavior

### 1) Job Lifecycle Streaming
Each agent task emits:
- `status`: queued → running → completed / failed
- `summary`: human‑readable message
- `artifacts`: outputs created (e.g., schema graph, glossary, metrics)

### 2) Streaming Channel
Use an event stream (SSE / WebSocket / polling):
- `/agentic/run/{run_id}/stream`
- fallback: `/agentic/run/{run_id}` polling
 - `/agentic/runs/{run_id}/chat` for stored summaries

### 3) Chat Log Persistence
All streamed messages are stored in a table regardless of UI visibility.

---

## Proposed Tables

### `quantyx_agent_runs`
```sql
CREATE TABLE IF NOT EXISTS public.quantyx_agent_runs (
  run_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### `quantyx_agent_run_events`
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

## Example Stream Messages

1. "Schema Agent started. Scanning 12 tables."
2. "Profiling Agent completed: detected 4 facts, 18 dimensions."
3. "Glossary Agent generated 28 terms + synonyms."
4. "Join Agent detected 7 join paths."
5. "Semantic graph ready. Deterministic query engine enabled."
6. "Dashboard Story Agent generated 3 charts."
7. "Join Agent asked Schema Agent to verify sap_id uniqueness."
8. "Schema Agent confirmed sap_id is unique (high confidence)."
9. "Metric Agent validated production_mt formula against schema columns."

---

## Success Criteria
- Users can see progress in real time.
- All progress is stored and retrievable.
- UI can optionally hide the stream without affecting execution.
