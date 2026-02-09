# Phase S: Async Onboarding Jobs (Scan, Map, Infer, Metrics)

Goal: add async job orchestration for long-running onboarding steps (schema scan, entity mapping, model inference, suggested metrics) without breaking existing synchronous APIs.

This phase introduces:
- new async endpoints that return `202 Accepted` + `job_id`
- a job + scope storage model
- a backend worker to execute jobs and update status/results
- UI polling via job status

---

## Why

Large databases can have thousands of tables/schemas; synchronous scans and inference can exceed request timeouts. Async jobs allow:
- immediate response to the client
- background processing
- consistent progress + status reporting
- retry and auditability

---

## Non-breaking approach

Keep existing endpoints unchanged:
- `POST /onboard/scan-connection`
- `POST /onboard/map`
- `POST /onboard/infer-models`
- `POST /metrics/suggested`

Add new async variants with `/async` suffix (or a generic `/jobs` submit) so existing clients do not break.

---

## API additions

### 1) Submit a job (generic)

`POST /jobs`

Request:
```json
{
  "tenant_id": "tenant_a",
  "domain_id": "manufacturing",
  "job_type": "scan_connection",
  "payload": { "connections": [ /* same as /onboard/scan-connection */ ] },
  "idempotency_key": "optional-client-key"
}
```

Response (`202`):
```json
{ "job_id": "job_123", "status": "queued" }
```

Notes:
- `payload` is always identical to the synchronous endpoint’s request shape.
- The backend derives scope from `payload` and stores it in `quantyx_job_scopes`.

---

### 2) Async convenience endpoints (recommended for UI)

These mirror existing endpoints but return a job. Request payloads are identical to their synchronous counterparts.

`POST /onboard/scan-connection/async`

Request (same as `/onboard/scan-connection`):
```json
{
  "tenant_id": "tenant_a",
  "domain_id": "manufacturing",
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
        {
          "name": "prod_warehouse",
          "schemas": [
            { "name": "public", "tables": ["fact_production_daily"], "limit": 20, "cursor": null }
          ]
        }
      ]
    }
  ]
}
```

Response (`202`):
```json
{ "job_id": "job_123", "status": "queued" }
```

`POST /onboard/map/async`

Request (same as `/onboard/map`):
```json
{
  "tenant_id": "tenant_a",
  "connection_id": "conn_prod",
  "database": "prod_warehouse",
  "schema": "public",
  "tables": ["fact_production_daily"]
}
```

Response (`202`):
```json
{ "job_id": "job_124", "status": "queued" }
```

`POST /onboard/infer-models/async`

Request (same as `/onboard/infer-models`):
```json
{
  "tenant_id": "tenant_a",
  "connection_id": "conn_prod",
  "database": "prod_warehouse",
  "schema": "public",
  "tables": ["fact_production_daily"],
  "grain": "day",
  "use_llm": false
}
```

Response (`202`):
```json
{ "job_id": "job_125", "status": "queued" }
```

`POST /metrics/suggested/async`

Request (same as `/metrics/suggested`):
```json
{
  "tenant_id": "tenant_a",
  "connection_id": "conn_prod",
  "database": "prod_warehouse",
  "schema": "public",
  "tables": ["fact_production_daily"]
}
```

Response (`202`):
```json
{ "job_id": "job_126", "status": "queued" }
```

---

### 3) Job status

`GET /jobs/{job_id}`

Response:
```json
{
  "job_id": "job_123",
  "job_type": "scan_connection",
  "status": "running",
  "progress_pct": 35,
  "progress_stage": "profiling tables",
  "scope_id": "scope_456",
  "error_message": null,
  "created_at": "...",
  "updated_at": "..."
}
```

---

### 4) Job result

`GET /jobs/{job_id}/result`

Returns the exact response payload that the synchronous endpoint would return.

Completed example:
```json
{
  "job_id": "job_123",
  "status": "completed",
  "result": {
    "connections": [
      {
        "connection_id": "conn_prod",
        "databases": [
          {
            "name": "prod_warehouse",
            "schemas": [
              {
                "name": "public",
                "tables": [
                  { "table": "fact_production_daily", "columns": [{ "name": "output_tmt", "data_type": "numeric" }] }
                ]
              }
            ]
          }
        ]
      }
    ]
  }
}
```

If not complete:
- return `202` with current status and no result payload.

If canceled or failed:
- return `200` with status and `error_message` populated.

Failed example:
```json
{
  "job_id": "job_123",
  "status": "failed",
  "error_message": "Connection timeout while profiling schema public",
  "result": null
}
```

Canceled example:
```json
{
  "job_id": "job_123",
  "status": "canceled",
  "error_message": "Canceled by user request",
  "result": null
}
```

---

### 5) List jobs (optional but useful)

`GET /jobs?tenant_id=...&status=...&job_type=...&limit=...&cursor=...`

Response:
```json
{
  "jobs": [
    {
      "job_id": "job_123",
      "job_type": "scan_connection",
      "status": "running",
      "scope_id": "scope_456",
      "created_at": "...",
      "updated_at": "..."
    }
  ],
  "limit": 50,
  "cursor": null,
  "next_cursor": null
}
```

---

### 6) Cancel job (optional)

`POST /jobs/{job_id}/cancel`

Only allowed for `queued` or `running` jobs.

Response:
```json
{ "job_id": "job_123", "status": "canceled" }
```

---

## Job lifecycle

Status values (ENUM):
- `queued`
- `running`
- `completed`
- `failed`
- `canceled`

Allowed transitions:
- `queued` → `running` → `completed`
- `queued` → `canceled`
- `running` → `failed`

Optional:
- `progress_pct` and `progress_stage` updated by the worker for long tasks.
- `error_message` populated when `status` is `failed` or `canceled`.

---

## Storage schema

### 1) Scope table (separate from jobs)

```sql
CREATE TABLE IF NOT EXISTS public.quantyx_job_scopes (
  scope_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  domain_id TEXT NULL,
  connection_id TEXT NULL,
  database_name TEXT NULL,
  schema_name TEXT NULL,
  tables JSONB NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_quantyx_job_scopes_tenant
  ON public.quantyx_job_scopes (tenant_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_quantyx_job_scopes_conn
  ON public.quantyx_job_scopes (connection_id, database_name, schema_name);
```

### 2) Jobs table

```sql
CREATE TABLE IF NOT EXISTS public.quantyx_jobs (
  job_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  scope_id TEXT NULL,
  job_type TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'queued',
  progress_pct NUMERIC NULL,
  progress_stage TEXT NULL,
  request_payload JSONB NOT NULL,
  result_payload JSONB NULL,
  error_message TEXT NULL,
  idempotency_key TEXT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  started_at TIMESTAMPTZ NULL,
  completed_at TIMESTAMPTZ NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  FOREIGN KEY (scope_id) REFERENCES public.quantyx_job_scopes(scope_id)
);

CREATE INDEX IF NOT EXISTS idx_quantyx_jobs_tenant_time
  ON public.quantyx_jobs (tenant_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_quantyx_jobs_status
  ON public.quantyx_jobs (status, created_at ASC);

CREATE UNIQUE INDEX IF NOT EXISTS idx_quantyx_jobs_idempotency
  ON public.quantyx_jobs (tenant_id, job_type, idempotency_key)
  WHERE idempotency_key IS NOT NULL;
```

### 3) Optional job events

```sql
CREATE TABLE IF NOT EXISTS public.quantyx_job_events (
  event_id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL,
  status TEXT NOT NULL,
  message TEXT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  FOREIGN KEY (job_id) REFERENCES public.quantyx_jobs(job_id)
);

CREATE INDEX IF NOT EXISTS idx_quantyx_job_events_job
  ON public.quantyx_job_events (job_id, created_at DESC);
```

---

## Backend execution

### Worker responsibilities

1) Poll `quantyx_jobs` for `status='queued'` in FIFO order.
2) Mark job `running` + `started_at`.
3) Execute logic based on `job_type`:
   - `scan_connection` → same code as `POST /onboard/scan-connection`
   - `map_entities` → same code as `POST /onboard/map`
   - `infer_models` → same code as `POST /onboard/infer-models`
   - `metrics_suggested` → same code as `POST /metrics/suggested`
4) Save result JSON in `result_payload`.
5) Mark job `completed` + `completed_at`.
6) On exceptions, store `error_message` + mark `failed`.

### Progress reporting

For scan/map/infer:
- Update `progress_pct` and `progress_stage` per schema/table loop.
- Optional: write to `quantyx_job_events` with small log messages.

---

## UI flow

1) Submit async request (e.g. `POST /onboard/scan-connection/async`).
2) Receive `job_id` and show loading state.
3) Poll `GET /jobs/{job_id}` every 2–5 seconds.
4) When status is `completed`, call `GET /jobs/{job_id}/result` and render.
5) If `failed`, show `error_message` with retry action.

---

## Acceptance criteria

- Async endpoints return `202` with `job_id`.
- Jobs are persisted with scope, request payload, and status.
- Worker processes queued jobs and updates status.
- UI can poll and render results after completion.
- Existing synchronous endpoints remain unchanged.
