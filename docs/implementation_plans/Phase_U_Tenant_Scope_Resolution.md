# Phase U: Tenant Scope Resolution (Remove Connection Scope from APIs)

Goal: remove connection scope from API request/response payloads for onboarding, jobs, ask, and insights. Resolve scope server‑side from tenant defaults and registry.

This phase mirrors Phase R (domain resolution) and extends it to connection scope.

---

## 1) Requirements

1) **Remove scope fields from API payloads**
   - Remove `connection_id`, `database`, `schema`, `tables` from:
     - onboarding APIs
     - job APIs
     - ask APIs
     - insights APIs
   - Responses should also omit scope.

2) **Tenant connection scope registry**
   - Store the active/default scope for each tenant (+ domain).
   - Use this for all server‑side resolution.

3) **Resolution order**
   - Resolve scope via:
     1. `quantyx_tenant_scopes` (tenant_id + domain_id)
     2. fallback: explicit scope in payload (transition only, log warnings)
     3. error if unresolved

4) **Backwards compatibility**
   - For a transition window, allow scope in payload but log warnings.
   - Remove scope fields from response payloads in new versioned endpoints.

---

## 2) Database Changes

### 2.1 New table: tenant scope registry

```sql
CREATE TABLE IF NOT EXISTS public.quantyx_tenant_scopes (
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  connection_id TEXT NOT NULL,
  database_name TEXT NOT NULL,
  schema_name TEXT NOT NULL,
  tables JSONB NULL,
  status TEXT NOT NULL DEFAULT 'active',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, domain_id)
);
```

Indexing:
```sql
CREATE INDEX IF NOT EXISTS idx_quantyx_tenant_scopes_status
  ON public.quantyx_tenant_scopes (status, updated_at DESC);
```

Optional history:
```sql
CREATE TABLE IF NOT EXISTS public.quantyx_tenant_scope_history (
  history_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  connection_id TEXT NOT NULL,
  database_name TEXT NOT NULL,
  schema_name TEXT NOT NULL,
  tables JSONB NULL,
  status TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### 2.2 Alter existing tables for Phase U lookups

```sql
ALTER TABLE public.quantyx_job_scopes
  ADD COLUMN IF NOT EXISTS tenant_id TEXT NULL;

ALTER TABLE public.quantyx_job_scopes
  ADD COLUMN IF NOT EXISTS domain_id TEXT NULL;

CREATE INDEX IF NOT EXISTS idx_quantyx_dbt_config_tenant_domain
  ON public.quantyx_dbt_config (tenant_id, domain_id, updated_at DESC);
```

---

## 3) New Admin APIs

### 3.1 POST /tenant/scope (admin)
Set or update the active scope for a tenant.

Request:
```json
{
  "tenant_id": "tenant_a",
  "domain_id": "manufacturing",
  "connection_id": "conn_prod",
  "database": "prod_warehouse",
  "schema": "public",
  "tables": ["fact_sales", "dim_customer"]
}
```

Response:
```json
{ "ok": true }
```

Notes:
- Overwrites the active scope for the tenant/domain.
- Writes a history row if history table is enabled.

### 3.2 GET /tenant/scope (admin)
Fetch active scope for a tenant.

Request:
```
GET /tenant/scope?tenant_id=tenant_a
```

Response:
```json
{
  "tenant_id": "tenant_a",
  "domain_id": "manufacturing",
  "connection_id": "conn_prod",
  "database": "prod_warehouse",
  "schema": "public",
  "tables": ["fact_sales", "dim_customer"],
  "status": "active"
}
```

---

## 3a) New Payload Schemas

### 3a.1 TenantScopeUpsertRequest
```json
{
  "tenant_id": "tenant_a",
  "domain_id": "manufacturing",
  "connection_id": "conn_prod",
  "database": "prod_warehouse",
  "schema": "public",
  "tables": ["fact_sales", "dim_customer"]
}
```

### 3a.2 TenantScopeResponse
```json
{
  "tenant_id": "tenant_a",
  "domain_id": "manufacturing",
  "connection_id": "conn_prod",
  "database": "prod_warehouse",
  "schema": "public",
  "tables": ["fact_sales", "dim_customer"],
  "status": "active"
}
```

---

## 4) Scope Resolution Helper

Add shared helper:

```
resolve_scope(tenant_id: str, domain_id: str) -> Scope
```

Behavior:
- Query `quantyx_tenant_scopes`.
- Return scope if found.
- Else, if request provided scope (transition), use it + log warning.
- Else raise 400: "scope not configured for tenant".

Implementation notes:
- Use the same resolution order as Phase R for `domain_id`.
- Cache resolved scope for the request lifecycle.
- Emit structured log: `scope_resolution=registry|payload|error`.

---

## 5) API Contract Changes (Phase U)

### 5.1 Remove scope from request payloads

Affected endpoints:
- `POST /onboard/scan-connection`
- `POST /onboard/map`
- `POST /onboard/infer-models`
- `POST /metrics/suggested`
- `POST /entities/certify`
- `POST /hierarchies/certify`
- `POST /jobs`
- `POST /query`
- `POST /insights/generate`

Revised request shapes:
- Remove `connection_id`, `database`, `schema`, `tables`.
- The server resolves scope and applies it internally.

### 5.2 Remove scope from responses

Affected responses:
- onboarding responses
- job status/result payloads
- query responses
- insights responses

Example: `POST /onboard/map` response should omit `connection_id`, `database`, `schema`, `tables`.

### 5.3 Transitional behavior

- If scope is provided in payload during migration, accept it but log:
  `"scope_in_payload is deprecated"`

---

## 5a) Endpoint-by-Endpoint Deltas

### Onboarding
- `POST /onboard/scan-connection`
  - Remove per-request scope; uses tenant scope.
  - Response omits scope fields.
- `POST /onboard/map`
  - No scope fields in request.
  - Scope resolved from tenant registry.
- `POST /onboard/infer-models`
  - No scope fields in request.
- `POST /metrics/suggested`
  - No scope fields in request.

### Admin (Certify)
- `POST /entities/certify`
  - Only `tenant_id` (optional `domain_id`, `entity_id`).
  - Scope resolved from tenant registry.
- `POST /hierarchies/certify`
  - Only `tenant_id` (optional `domain_id`, `hierarchy_name`).
  - Scope resolved from tenant registry.

### Jobs
- `POST /jobs`
  - Payload no longer contains scope.
  - Server resolves scope before executing.
- `GET /jobs/{job_id}`
  - Omit scope fields from response payload.

### Ask
- `POST /query`
  - Remove scope from payload.
  - Scope derived server-side.

### Insights
- `POST /insights/generate`
  - Remove scope from payload.
  - Scope derived server-side.

---

## 5b) Request/Response Examples (Before vs After)

### 5b.1 POST /onboard/map

Before:
```json
{
  "tenant_id": "tenant_a",
  "schema": "public",
  "tables": ["fact_dispatch", "dim_bay"],
  "connection_id": "conn_prod",
  "database": "prod_warehouse"
}
```

After:
```json
{
  "tenant_id": "tenant_a"
}
```

Response (after, scope removed):
```json
{
  "mapping_id": "map_123",
  "candidates": [{"table": "fact_dispatch", "column": "bay_name", "mapped_entity_type": "organizational_unit"}],
  "low_confidence_candidates": [],
  "low_confidence_threshold": 0.7
}
```

### 5b.2 POST /onboard/infer-models

Before:
```json
{
  "tenant_id": "tenant_a",
  "schema": "public",
  "tables": ["fact_dispatch", "dim_bay"],
  "connection_id": "conn_prod",
  "database": "prod_warehouse",
  "grain": "day",
  "use_llm": true
}
```

After:
```json
{
  "tenant_id": "tenant_a",
  "grain": "day",
  "use_llm": true
}
```

### 5b.3 POST /metrics/suggested

Before:
```json
{
  "tenant_id": "tenant_a",
  "schema": "public",
  "tables": ["fact_dispatch"],
  "connection_id": "conn_prod",
  "database": "prod_warehouse"
}
```

After:
```json
{
  "tenant_id": "tenant_a"
}
```

### 5b.4 POST /jobs

Before:
```json
{
  "tenant_id": "tenant_a",
  "job_type": "scan_connection",
  "payload": {
    "tenant_id": "tenant_a",
    "connections": [
      {
        "connection_id": "conn_prod",
        "db_type": "postgres",
        "host": "db.company.com",
        "port": 5432,
        "user": "readonly_user",
        "password": "******",
        "sample_rows": 100,
        "databases": [
          { "name": "prod_warehouse", "schemas": [{ "name": "public" }] }
        ]
      }
    ]
  }
}
```

After:
```json
{
  "tenant_id": "tenant_a",
  "job_type": "scan_connection",
  "payload": {
    "tenant_id": "tenant_a"
  }
}
```

### 5b.5 POST /query

Before:
```json
{
  "tenant_id": "tenant_a",
  "connection_id": "conn_prod",
  "database": "prod_warehouse",
  "schema": "public",
  "question": "Top 5 bays by throughput"
}
```

After:
```json
{
  "tenant_id": "tenant_a",
  "question": "Top 5 bays by throughput"
}
```

### 5b.6 POST /insights/generate

Before:
```json
{
  "tenant_id": "tenant_a",
  "connection_id": "conn_prod",
  "database": "prod_warehouse",
  "schema": "public",
  "type": "anomaly"
}
```

After:
```json
{
  "tenant_id": "tenant_a",
  "type": "anomaly"
}
```

---

## 5c) Code Change Map

Primary files to update:
- `services/api/main.py`:
  - remove scope params from request parsing
  - resolve scope via `resolve_scope`
  - remove scope fields from response payloads
- `services/api/schemas.py`:
  - update request models to remove scope fields
  - update response examples to omit scope
- `services/ai/onboarding/*`:
  - replace direct scope usage with resolved scope
- `services/ai/metrics_registry.py`:
  - resolve scope before metric suggestion persistence
- `services/ai/insights.py`:
  - remove scope assumptions from insights generation
- `services/ai/onboarding/scan_store.py`:
  - resolve scope for scan fetches

---

## 5d) Feature Flag (Optional)

Add `SCOPE_RESOLUTION_MODE`:
- `payload` (legacy)
- `registry` (default)
- `strict` (reject payload scope)

---

## 6) Worker + Jobs Changes

- Jobs should store only tenant_id and job_type in payload.
- Scope derived server‑side using `resolve_scope`.
- `quantyx_job_scopes` still stored for auditing but not exposed.

---

## 7) UI Flow

1) Admin sets tenant scope once via `POST /tenant/scope`.
2) UI sends onboarding jobs without scope fields.
3) Backend resolves scope automatically for every call.

---

## 8) Rollout Plan (Phased)

### Phase U.1 (Prepare)
- Add `quantyx_tenant_scopes` table.
- Add `POST /tenant/scope` and `GET /tenant/scope`.
- Add `resolve_scope` helper.

### Phase U.2 (Dual support)
- Accept scope fields in payloads but prefer registry.
- Add warning logs when scope is present in payload.

### Phase U.3 (Default to registry)
- Update all API handlers to resolve scope internally.
- Remove scope fields from responses in versioned endpoints (`/v2/...` if available).

### Phase U.4 (Deprecate payload scope)
- Reject scope fields in payloads (400).
- Remove any UI references to scope fields.

---

## Acceptance Criteria

- No onboarding/ask/insight/job request requires scope fields.
- Backend resolves scope for every request.
- Existing payloads with scope still work during transition.
- All responses omit scope fields by default.
- Tenant scope can be updated and immediately used by the API.
