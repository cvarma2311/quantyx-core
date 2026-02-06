# Phase R: Tenant → Domain Resolution (Remove domain_id from query params)

Goal:
- Remove `domain_id` from query params across APIs.
- Store the tenant’s active `domain_id` once, then resolve it from DB for every request.
- Remove `tenant_id` from POST query params; require it in request body for POST/PATCH/PUT.
- Keep `tenant_id` in query params for GET/DELETE (for now).

---

## 1) Requirements

1) **Tenant domain registry**
   - Persist the active `domain_id` per `tenant_id`.
   - Used by all APIs that currently accept `domain_id` via query params.

2) **Domain resolution order**
   - For any request requiring domain, resolve by:
     1. `quantyx_tenant_domains` (tenant_id → active domain_id)
     2. fallback: existing domain_id in payload (if provided, during transition only)
     3. error if unresolved

3) **Tenant id in POST bodies**
   - All POST/PATCH/PUT must require `tenant_id` in request payload.
   - Remove `tenant_id` query params from these endpoints.

4) **GET/DELETE behavior**
   - Keep `tenant_id` in query params.
   - Remove `domain_id` from query params.
   - Domain is resolved via registry.

5) **Backwards compatibility**
   - For a transition window, allow `domain_id` in payloads but log warnings.
   - After migration, reject `domain_id` in query params.

---

## 2) Database Changes

### 2.1 New table: tenant domain registry

```sql
CREATE TABLE IF NOT EXISTS public.quantyx_tenant_domains (
  tenant_id TEXT PRIMARY KEY,
  domain_id TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

Optional (history):
```sql
CREATE TABLE IF NOT EXISTS public.quantyx_tenant_domain_history (
  history_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

---

## 3) New APIs

### 3.1 POST /tenant/domain (admin)

Purpose: set or update the active domain for a tenant.

Request:
```json
{
  "tenant_id": "tenant_a",
  "domain_id": "manufacturing"
}
```

Response:
```json
{ "ok": true }
```

### 3.2 GET /tenant/domain (admin)

Query params:
- `tenant_id`

Response:
```json
{
  "tenant_id": "tenant_a",
  "domain_id": "manufacturing",
  "status": "active"
}
```

---

## 4) Domain Resolution Helper

Add a shared helper used by all APIs:

```
resolve_domain_id(tenant_id: str, request_domain_id: str | None) -> str
```

Behavior:
- Query `quantyx_tenant_domains`.
- If found, return it.
- Else if `request_domain_id` provided, return it and log warning (transition only).
- Else raise 400: "domain_id not configured for tenant".

---

## 5) API Contract Changes (Phase R)

### 5.1 Remove domain_id from query params

Affected endpoints (examples):
- `/onboard/scan-connection`
- `/onboard/map`
- `/onboard/infer-models`
- `/metrics/suggested`
- `/metrics`
- `/entities`
- `/hierarchies`
- `/facts`
- `/dimensions`
- `/review/summary`

**All will resolve domain_id based on tenant_id.**

### 5.2 Remove tenant_id from POST query params

Rules:
- POST/PATCH/PUT must include `tenant_id` in body.
- GET/DELETE keep `tenant_id` in query params.

---

## 6) Schema/Validator Updates

1) Update request models:
   - Ensure `tenant_id` exists in all POST/PATCH/PUT request bodies.
   - Remove `domain_id` from request bodies where not needed.

2) Update validators:
   - Remove domain_id checks on query params.
   - Use `resolve_domain_id()` internally.

---

## 7) Implementation Steps

1) Add `quantyx_tenant_domains` table in schema files:
   - `artifacts/quantyx_tables.sql`
   - `artifacts/quantyx_tables_updates.sql`

2) Add DB access helpers:
   - `set_tenant_domain(tenant_id, domain_id)`
   - `get_tenant_domain(tenant_id)`
   - `resolve_domain_id(tenant_id, request_domain_id=None)`

3) Add admin APIs:
   - POST /tenant/domain
   - GET /tenant/domain

4) Update API handlers:
   - Remove `domain_id` from query params.
   - Always call `resolve_domain_id()` with tenant_id.
   - Update swagger examples.

5) Update tests:
   - New tests for domain resolution.
   - Update existing endpoint tests.

6) Update docs:
   - `artifacts/ONBOARDING_API_FLOW.md`
   - Phase Q and other onboarding docs.

---

## 8) Migration Plan

1) Backfill:
   - Insert rows into `quantyx_tenant_domains` for existing tenants.
2) Deploy Phase R with logging for fallback `domain_id` in payload.
3) Remove fallback + reject `domain_id` in query params after a stable window.

---

## 9) Example Updated Flows

### Before:
`POST /onboard/map?domain_id=manufacturing&tenant_id=tenant_a`

### After:
`POST /onboard/map`

Body:
```json
{
  "tenant_id": "tenant_a",
  "connection_id": "conn_prod",
  "database": "prod_warehouse",
  "schema": "public",
  "tables": ["fact_sales"]
}
```

Domain resolved from `quantyx_tenant_domains`.

