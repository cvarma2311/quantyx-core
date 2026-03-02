# Phase 21: UI-to-API Flow (End-to-End)

## Objective
Define the exact API call order the UI should follow from **schema selection** to **chat completion**, including progress streaming and polling.

---

## Assumptions
- The UI already knows `tenant_id` and `domain_id`.
- Connection and tables have been selected in the UI.
- All APIs are unauthenticated for now.

---

## 1) User Selects Connection + Tables

**UI Action:** user selects a connection + tables.

**API (optional UI save):**
If you store selection, send it via your existing onboarding/scan APIs.
This can remain internal, but the next step requires `schema_payload` or a scan run.

---

## 2) Start Agentic Run

**UI → API:**
```http
POST /agentic/runs
```

**Request:**
```json
{
  "tenant_id": "VC_101",
  "domain_id": "lpg_production_distribution",
  "mode": "full"
}
```

**Response:**
```json
{ "run_id": "run_123", "status": "queued", "job_id": "job_abc" }
```

---

## 3) Stream Progress (or Poll)

**UI → API (SSE):**
```http
GET /agentic/runs/run_123/stream
```

If SSE not available:
```http
GET /agentic/runs/run_123/events
GET /agentic/runs/run_123/chat
```

**Notes:**
- `/events` contains structured agent events.
- `/chat` contains safe summarized progress for end users.

---

## 4) Dashboard Auto-Generation (Implicit)

The agent run writes dashboards and charts automatically.

**UI can fetch dashboards after run completion:**
```http
GET /dashboards/{dashboard_id}
```

If you store `dashboard_id` from agent events, load it here.

---

## 5) User Asks a Natural Language Question

### Option A: Chat API (recommended)

**UI → API:**
```http
POST /chat
```

**Request (sync):**
```json
{
  "tenant_id": "VC_101",
  "domain_id": "lpg_production_distribution",
  "question": "What is total LPG production by plant last week?",
  "mode": "sync"
}
```

**Response (sync):**
```json
{
  "status": "complete",
  "response": {
    "metrics": ["production_mt"],
    "dimensions": ["sap_id"],
    "sql": "SELECT ...",
    "rows": [],
    "chart_id": "chart_abc",
    "chart_type": "bar",
    "chart_payload": { "root": {}, "chart": {} },
    "data": []
  }
}
```

### Option B: Async Chat

**UI → API:**
```http
POST /chat
```

**Request (async):**
```json
{
  "tenant_id": "VC_101",
  "domain_id": "lpg_production_distribution",
  "question": "What is total LPG production by plant last week?",
  "mode": "async"
}
```

**Response:**
```json
{ "chat_id": "chat_123", "status": "queued" }
```

**UI polls:**
```http
GET /chat/chat_123
GET /chat/chat_123/events
GET /chat/chat_123/stream
```

---

## 6) Render Chart

If the chat response includes `chart_id`, UI can also poll:

```http
GET /charts/{chart_id}
```

This returns amCharts payload + data.

---

## 7) Optional: View Explorer + SQL Editor

If user opens SQL editor:

```http
GET /views?tenant_id=VC_101&domain_id=lpg_production_distribution
GET /views/{view_name}/schema?tenant_id=VC_101
POST /views/query
```

---

## Full Example Sequence (Minimal)

1. `POST /agentic/runs`
2. `GET /agentic/runs/{run_id}/stream`
3. `POST /chat` (sync)
4. Render chart payload in UI

---

## Full Example Sequence (Async + Streaming)

1. `POST /agentic/runs`
2. `GET /agentic/runs/{run_id}/stream`
3. `POST /chat` (async)
4. `GET /chat/{chat_id}/stream`
5. `GET /chat/{chat_id}`
6. `GET /charts/{chart_id}`

