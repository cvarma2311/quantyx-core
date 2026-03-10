# Phase 25: Tenant-First Chat Entry and History APIs

## Objective
Continue Phase 24 by defining customer-first entry APIs so UI can:
1. list tenants,
2. check agentic deployment readiness per tenant/domain,
3. show conversation history grouped by tenant/domain,
4. start a new chat instantly with SSE response streaming.

---

## Why This Phase
Phase 24 defines deployment run + conversation model.  
Phase 25 adds the concrete UI-facing discovery/listing APIs needed for production navigation and first-message experience.

---

## UI Entry Flow (Target)
1. UI loads all tenants.
2. User selects tenant.
3. UI loads domains + deployment readiness status for that tenant.
4. User selects domain.
5. UI loads chat history (conversation list) for tenant/domain.
6. UI shows "Start new conversation".
7. On user prompt, response streams via SSE.

---

## API Additions

## 1) List tenants
`GET /workspace/tenants`

Response:
```json
{
  "tenants": [
    {"tenant_id": "VC_101", "tenant_name": "HPCL VC 101", "status": "active"},
    {"tenant_id": "BT_01", "tenant_name": "BT Demo", "status": "active"}
  ]
}
```

## 2) List domains for selected tenant with readiness
`GET /workspace/tenants/{tenant_id}/domains`

Response:
```json
{
  "tenant_id": "VC_101",
  "domains": [
    {
      "domain_id": "lpg_production_distribution",
      "display_name": "LPG Production and Distribution",
      "scan_status": "completed",
      "deployment_status": "completed",
      "current_run_id": "run_1a0f427c86ec",
      "current_run_display_name": "LPG Distribution Deployment v4"
    }
  ]
}
```

## 3) Connection scan status for tenant/domain
`GET /workspace/tenants/{tenant_id}/domains/{domain_id}/scan-status`

Purpose:
- answer: "Is connection scan completed?"
- return API-ready status object for UI gating.

Response:
```json
{
  "tenant_id": "VC_101",
  "domain_id": "lpg_production_distribution",
  "scan_status": "completed",
  "last_scan_id": "scan_2233e9a1",
  "last_scanned_at": "2026-02-23T05:31:07.901Z",
  "tables_detected": 9
}
```

Allowed `scan_status`:
- `not_started | running | completed | failed`

## 4) Deployment run status for tenant/domain
`GET /workspace/tenants/{tenant_id}/domains/{domain_id}/deployment-status`

Response:
```json
{
  "tenant_id": "VC_101",
  "domain_id": "lpg_production_distribution",
  "status": "completed",
  "run_id": "run_1a0f427c86ec",
  "display_name": "LPG Distribution Deployment v4",
  "version_no": 4,
  "completed_at": "2026-03-06T21:54:18.326901Z"
}
```

## 5) List conversation history for tenant/domain
`GET /workspace/tenants/{tenant_id}/domains/{domain_id}/conversations`

Query params:
- `status=active|archived|deleted` (default active)
- `limit`, `cursor`

Response:
```json
{
  "tenant_id": "VC_101",
  "domain_id": "lpg_production_distribution",
  "conversations": [
    {
      "conversation_id": "conv_6f0f0f",
      "title": "North Zone Bottleneck Analysis",
      "display_name": "North Zone Bottleneck Analysis",
      "run_id": "run_1a0f427c86ec",
      "run_display_name": "LPG Distribution Deployment v4",
      "last_message_preview": "Top contributors are Sitarganj and Bahadurgarh...",
      "last_message_at": "2026-03-09T10:11:00Z",
      "message_count": 24
    }
  ],
  "paging": {"limit": 20, "next_cursor": null}
}
```

## 6) Start new conversation from tenant/domain
`POST /workspace/tenants/{tenant_id}/domains/{domain_id}/conversations`

Creates new conversation using current canonical run and generated title/display_name.

## 7) Send message (SSE default)
`POST /workspace/conversations/{conversation_id}/messages`

Default:
- `stream=true`
- returns `text/event-stream`

Opt-out:
- `stream=false` for synchronous JSON response.

## 8) Get chat history by deployment run (for "run history" view)
`GET /workspace/tenants/{tenant_id}/domains/{domain_id}/runs/{run_id}/conversations`

Purpose:
- show chat history grouped by run/deployment version.

---

## PUT/DELETE Decisions (Customer-first)

## PUT endpoints
1. `PUT /workspace/conversations/{conversation_id}`
   - rename title/display_name
   - archive/unarchive
2. `PUT /workspace/deployments/{run_id}`
   - update display_name only (and guarded canonical switch if needed)

## DELETE endpoints
1. `DELETE /workspace/conversations/{conversation_id}`
   - soft delete only
2. No DELETE for deployment runs
   - preserve lineage and audit.

---

## Data/Query Sources (Implementation Mapping)
1. Tenant list:
   - existing tenant registry table/API source.
2. Scan status:
   - onboarding scan store latest scoped scan rows (`scan_id`, timestamps, status).
3. Deployment status:
   - `quantyx_agent_runs` canonical row (`is_canonical=true`) for tenant/domain.
4. Conversation history:
   - `quantyx_workspace_conversations` + `quantyx_workspace_messages` aggregates.
5. Run-grouped conversations:
   - filter conversation rows by `run_id`.

---

## Acceptance Criteria
1. UI can load all tenants with one API call.
2. Selecting tenant shows all domains with scan/deployment readiness.
3. If scan/deployment status is `completed`, user can chat immediately.
4. Selecting tenant+domain returns full conversation history list.
5. User can always start new conversation from tenant/domain.
6. Chat responses stream via SSE by default.
7. History can be filtered by run/deployment version.
