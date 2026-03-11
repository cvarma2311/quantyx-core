# Phase 26: Workspace UI Sequential API Flow

## Objective
Define one customer-facing API sequence for workspace onboarding and chat usage, starting from either:
1. creating a new tenant, or
2. selecting an existing tenant.

This document is the integration contract for UI teams.

---

## Canonical Request Contract (Important)
To keep payloads consistent across similar APIs:
- Use `user_query` as the canonical query field.
- Backend accepts aliases (`query`, `message_text`, `first_question`) for backward compatibility.
- UI should always send `user_query`.

---

## API Groups Used In Flow
1. Tenant bootstrap:
- `POST /tenants`
- `POST /tenant/domain`
- `POST /tenant/scope`

2. Scan and readiness:
- `POST /onboard/scan-connection` (or async variant)
- `GET /workspace/tenants/{tenant_id}/domains/{domain_id}/scan-status`

3. Deployment:
- `POST /workspace/deployments` (first build and rebuild; single canonical API)
- `GET /agentic/runs/{run_id}/stream` (live build stream)
- `GET /agentic/runs/{run_id}/chat` (replay of completed run timeline)
- `GET /agentic/runs/{run_id}/events` (detailed event list, optional)
- `GET /agentic/runs/{run_id}/events/{event_id}/artifacts` (artifact drilldown, optional)
- `GET /workspace/tenants/{tenant_id}/domains/{domain_id}/deployment-status`
- `GET /workspace/deployments/current?tenant_id=...&domain_id=...`

4. Conversation discovery:
- `GET /workspace/tenants/{tenant_id}/conversations` (all domains)
- `GET /workspace/tenants/{tenant_id}/domains/{domain_id}/conversations`
- `GET /workspace/tenants/{tenant_id}/domains/{domain_id}/runs/{run_id}/conversations`

5. Conversation creation and chat:
- `POST /workspace/tenants/{tenant_id}/domains/{domain_id}/conversations`
- `POST /workspace/conversations/{conversation_id}/messages` (SSE by default)
- `GET /workspace/conversations/{conversation_id}/messages`
- `GET /workspace/conversations/{conversation_id}/context`

---

## Flow A: New Tenant (First-Time Setup)

1. Create tenant
```http
POST /tenants
```

2. Bind tenant to default domain
```http
POST /tenant/domain
```

3. Persist tenant scope (connection/database/schema/tables)
```http
POST /tenant/scope
```

4. Run connection scan
```http
POST /onboard/scan-connection
```

5. Poll scan readiness until complete
```http
GET /workspace/tenants/{tenant_id}/domains/{domain_id}/scan-status
```

6. Start deployment build
```http
POST /workspace/deployments
```

7. Poll deployment readiness
```http
GET /workspace/tenants/{tenant_id}/domains/{domain_id}/deployment-status
```

8. Load tenant-wide conversation history (will be empty initially)
```http
GET /workspace/tenants/{tenant_id}/conversations
```

9. Start conversation
```http
POST /workspace/tenants/{tenant_id}/domains/{domain_id}/conversations
```
Request (canonical):
```json
{
  "user_query": "Show production trend by plant for last 30 days"
}
```

10. Send message with SSE stream
```http
POST /workspace/conversations/{conversation_id}/messages
```
Request:
```json
{
  "user_query": "Show production trend by plant for last 30 days",
  "resume_context": true,
  "stream": true
}
```

---

## Flow B: Existing Tenant (Returning User)

1. Load tenants
```http
GET /workspace/tenants
```

2. User selects tenant -> load domains/readiness
```http
GET /workspace/tenants/{tenant_id}/domains
```

3. If `deployment_status != completed`:
- show setup/processing state
- trigger deployment only through:
```http
POST /workspace/deployments
```

4. Load tenant-wide history across all domains
```http
GET /workspace/tenants/{tenant_id}/conversations
```

5. If user filters by selected domain:
```http
GET /workspace/tenants/{tenant_id}/domains/{domain_id}/conversations
```

6. Resume existing conversation:
- show transcript:
```http
GET /workspace/conversations/{conversation_id}/messages
```
- send new turn:
```http
POST /workspace/conversations/{conversation_id}/messages
```

7. Start new conversation for selected domain:
```http
POST /workspace/tenants/{tenant_id}/domains/{domain_id}/conversations
```

---

## Flow C: Replay Initial Deployment Run (Build Timeline + Artifacts)

Use this flow when a user refreshes/reopens UI and wants to replay the first build execution.

1. Resolve canonical deployment run for selected scope
```http
GET /workspace/deployments/current?tenant_id={tenant_id}&domain_id={domain_id}
```
Response includes canonical `run_id`.

2. Replay run timeline (chat-like sequence)
```http
GET /agentic/runs/{run_id}/chat?include_stages=true
```
Use this as primary replay feed for progress narrative, summaries, inference, dashboard/chart titles.

3. Optional: replay raw event timeline
```http
GET /agentic/runs/{run_id}/events
```

4. Optional: drill into any event artifacts
```http
GET /agentic/runs/{run_id}/events/{event_id}/artifacts
```

5. Load generated dashboards after replay
```http
GET /dashboards?tenant_id={tenant_id}&domain_id={domain_id}
GET /dashboards/{dashboard_id}
```

Notes:
- Step 2 is the canonical replay API for UI.
- It now includes `dashboard_title`, `chart_ids`, and `chart_titles` on stage messages when available.

---

## Sequence Diagram: Tenant To First Streamed Reply

```mermaid
sequenceDiagram
  autonumber
  participant UI as UI
  participant API as FastAPI
  participant DB as Postgres
  participant ORCH as Agentic Worker

  alt New Tenant
    UI->>API: POST /tenants
    API->>DB: upsert tenant
    UI->>API: POST /tenant/domain
    API->>DB: upsert tenant-domain
    UI->>API: POST /tenant/scope
    API->>DB: upsert scope
    UI->>API: POST /onboard/scan-connection
    API->>DB: persist scan result
  else Existing Tenant
    UI->>API: GET /workspace/tenants
    UI->>API: GET /workspace/tenants/{tenant_id}/domains
  end

  UI->>API: GET /workspace/.../scan-status
  API-->>UI: scan_status=completed

  UI->>API: POST /workspace/deployments
  API->>DB: create run(status=queued)
  API->>ORCH: enqueue agentic_run
  ORCH->>DB: running -> completed -> canonicalize
  UI->>API: GET /agentic/runs/{run_id}/stream
  API-->>UI: live SSE progress events

  loop until completed
    UI->>API: GET /workspace/.../deployment-status
    API-->>UI: status
  end

  UI->>API: GET /workspace/tenants/{tenant_id}/conversations
  API-->>UI: history (all domains)
  UI->>API: POST /workspace/tenants/{tenant_id}/domains/{domain_id}/conversations
  API->>DB: create conversation
  API-->>UI: conversation_id

  UI->>API: POST /workspace/conversations/{conversation_id}/messages (stream=true,user_query=...)
  API->>DB: persist user message
  API-->>UI: SSE message_start/token/artifact/.../done
  API->>DB: persist assistant message + memory
```

---

## Sequence Diagram: Replay Initial Run

```mermaid
sequenceDiagram
  autonumber
  participant UI as UI
  participant API as FastAPI
  participant DB as Postgres

  UI->>API: GET /workspace/deployments/current?tenant_id=...&domain_id=...
  API->>DB: fetch canonical deployment
  API-->>UI: run_id + display_name + status

  UI->>API: GET /agentic/runs/{run_id}/chat?include_stages=true
  API->>DB: fetch chat log + stage-aware event artifacts
  API-->>UI: replay messages (summary/inference/dashboard_title/chart_titles)

  opt Detailed diagnostics
    UI->>API: GET /agentic/runs/{run_id}/events
    API-->>UI: event list
    UI->>API: GET /agentic/runs/{run_id}/events/{event_id}/artifacts
    API-->>UI: artifact payload
  end

  UI->>API: GET /dashboards?tenant_id=...&domain_id=...
  API-->>UI: dashboards + chart_titles + run linkage
  UI->>API: GET /dashboards/{dashboard_id}
  API-->>UI: normalized dashboard spec with chart titles
```

---

## Sequence Diagram: Resume Conversation

```mermaid
sequenceDiagram
  autonumber
  participant UI as UI
  participant API as FastAPI
  participant DB as Postgres

  UI->>API: GET /workspace/conversations/{conversation_id}/messages
  API->>DB: fetch transcript
  API-->>UI: messages

  UI->>API: GET /workspace/conversations/{conversation_id}/context
  API->>DB: fetch memory + recent turns
  API-->>UI: context package

  UI->>API: POST /workspace/conversations/{conversation_id}/messages (user_query, stream=true)
  API->>DB: persist user message
  API-->>UI: SSE token stream
  API->>DB: persist assistant message + updated memory
```

---

## UI Decision Table

1. On app load:
- call `GET /workspace/tenants`

2. On tenant select:
- call `GET /workspace/tenants/{tenant_id}/domains`
- call `GET /workspace/tenants/{tenant_id}/conversations`

3. On domain select:
- if `deployment_status != completed`, call `POST /workspace/deployments`
- else load `GET /workspace/tenants/{tenant_id}/domains/{domain_id}/conversations`

4. On "New Chat":
- call `POST /workspace/tenants/{tenant_id}/domains/{domain_id}/conversations`

5. On send:
- call `POST /workspace/conversations/{conversation_id}/messages` with `stream=true` and `user_query`

6. On “Replay Initial Build” for selected tenant/domain:
- call `GET /workspace/deployments/current?tenant_id=...&domain_id=...`
- call `GET /agentic/runs/{run_id}/chat?include_stages=true`
- optionally call `GET /dashboards?...` and `GET /dashboards/{dashboard_id}` to render final dashboard output

---

## Frontend State Machine

1. `SCOPE_SELECT`
- enter: app load
- API:
  - `GET /workspace/tenants`
  - on tenant select: `GET /workspace/tenants/{tenant_id}/domains`
- transitions:
  - if user picks tenant/domain -> `READINESS_CHECK`

2. `READINESS_CHECK`
- API:
  - `GET /workspace/tenants/{tenant_id}/domains/{domain_id}/scan-status`
  - `GET /workspace/tenants/{tenant_id}/domains/{domain_id}/deployment-status`
- transitions:
  - `scan_status != completed` -> `SETUP_BLOCKED`
  - `scan_status = completed` and `deployment_status != completed` -> `DEPLOYMENT_START`
  - `deployment_status = completed` -> `POST_DEPLOY_HOME`

3. `DEPLOYMENT_START`
- API:
  - `POST /workspace/deployments`
- save `run_id`
- transitions:
  - success -> `DEPLOYMENT_STREAMING`
  - 409 inflight -> `DEPLOYMENT_STREAMING` (reuse existing `run_id` from error payload)

4. `DEPLOYMENT_STREAMING`
- API:
  - `GET /agentic/runs/{run_id}/stream` (SSE)
  - poll `GET /workspace/.../deployment-status` for terminal status
- transitions:
  - status completed -> `INITIAL_REPLAY_READY`
  - status failed -> `DEPLOYMENT_FAILED`

5. `INITIAL_REPLAY_READY`
- API:
  - `GET /agentic/runs/{run_id}/chat?include_stages=true`
  - `GET /dashboards?tenant_id=...&domain_id=...`
- transitions:
  - user opens dashboard -> `DASHBOARD_VIEW`
  - user starts chat -> `CONVERSATION_ACTIVE`

6. `DASHBOARD_VIEW`
- API:
  - `GET /dashboards/{dashboard_id}`
  - optional refresh: `POST /dashboards/{dashboard_id}/refresh`
- transitions:
  - refresh started -> `DASHBOARD_REFRESH_STREAM`
  - start chat -> `CONVERSATION_ACTIVE`

7. `DASHBOARD_REFRESH_STREAM`
- API:
  - `GET /dashboards/{dashboard_id}/refresh/{refresh_id}/stream`
  - `GET /dashboards/{dashboard_id}/refresh/{refresh_id}/events`
- transitions:
  - completed -> `DASHBOARD_VIEW`

8. `CONVERSATION_ACTIVE`
- API:
  - create: `POST /workspace/tenants/{tenant_id}/domains/{domain_id}/conversations`
  - resume list: `GET /workspace/tenants/{tenant_id}/domains/{domain_id}/conversations`
  - history: `GET /workspace/conversations/{conversation_id}/messages`
  - send: `POST /workspace/conversations/{conversation_id}/messages` (`stream=true`)
- transitions:
  - user switches scope -> `SCOPE_SELECT`

---

## Integration Guardrails
1. Do not call `/agentic/runs` from customer UI flow.
2. Use only `/workspace/deployments` for both initial build and new versions.
3. Always send `user_query` in conversation/message request bodies.
4. Treat IDs (`run_id`, `conversation_id`) as internal handles; show `display_name`/`title` in UI.
