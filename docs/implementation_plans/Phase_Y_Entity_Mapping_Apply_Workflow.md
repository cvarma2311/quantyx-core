# Phase Y: Entity Mapping Run-to-Apply Workflow (mapping_id)

Goal: close the gap between async/sync mapping runs and runtime entity availability by introducing a first-class `mapping_id` apply flow.

---

## Why this phase exists

Current behavior:
- `/onboard/map` and `/onboard/map/async` generate mapping candidates and persist them in `public.quantyx_entity_mappings`.
- `GET /entities` reads canonical entities from `public.quantyx_entity_overrides`.

Gap:
- Mapping runs are stored, but there is no explicit `mapping_id` apply endpoint to promote candidates into canonical overrides.

This phase adds that missing bridge and documents the already completed persistence parity fixes.

---

## Completed changes (already implemented)

1) **Async map uses same service path as sync map**
- Worker `map_entities` now reuses the same map execution method as `POST /onboard/map`.
- Result: persistence to `quantyx_entity_mappings` is identical for sync and async.

2) **Map history supports tenant-scope resolution**
- `GET /onboard/map/history` can resolve connection scope from tenant scope registry when scope query params are omitted.
- Supports one-active-scope-per-tenant/domain usage.

3) **Migration SQL updated for mapping persistence**
- `artifacts/quantyx_tables_updates.sql` now includes:
  - `updated_at` in `quantyx_entity_mappings`
  - backfill from legacy `payload` into `candidates`, `low_confidence_candidates`, `low_confidence_threshold`
  - defaults for `tables`, `candidates`, `low_confidence_candidates`, `low_confidence_threshold`, `status`

---

## New API: Apply mapping by mapping_id

### 1) POST /onboard/map/{mapping_id}/apply

Purpose:
- Promote selected candidates (or all candidates) from a mapping run into canonical entity overrides.

Request:
```json
{
  "tenant_id": "tenant_a",
  "domain_id": "manufacturing",
  "selection_mode": "all",
  "candidates": [],
  "status": "draft",
  "notes": "Initial apply from mapping run"
}
```

Request fields:
- `tenant_id` (required)
- `domain_id` (optional if tenant-domain resolution is active)
- `selection_mode` (required): `all` or `selected`
- `candidates` (required only when `selection_mode=selected`) with items:
  - `table`
  - `column`
  - `mapped_entity_type`
- `status` (optional): `draft` (default) or `reviewed`
- `notes` (optional): audit note

Response:
```json
{
  "ok": true,
  "mapping_id": "map_ab12cd34",
  "applied_count": 8,
  "skipped_count": 2,
  "status": "draft",
  "review_id": "review_123",
  "mapping_status": "partially_applied"
}
```

Behavior:
1. Resolve `domain_id` and scope from tenant registries.
2. Load mapping run by `mapping_id` + tenant/domain/scope.
3. Select candidates based on `selection_mode`.
4. Upsert selected candidates into `quantyx_entity_overrides`.
5. Record review/audit event in `quantyx_review_events` (`artifact_type=mapping`).
6. Update mapping run status to `applied` (or `partially_applied` if partial).

Errors:
- `404` if `mapping_id` not found for tenant/domain/scope
- `400` for invalid selection input
- `409` if apply attempted on incompatible scope

---

## Optional helper API

### 2) GET /onboard/map/{mapping_id}

Purpose:
- Fetch a single mapping run payload without needing `job_id`.

Response:
```json
{
  "mapping_id": "map_ab12cd34",
  "tenant_id": "tenant_a",
  "domain_id": "manufacturing",
  "candidates": [],
  "low_confidence_candidates": [],
  "low_confidence_threshold": 0.7,
  "status": "draft",
  "created_at": "2026-02-18T10:00:00Z"
}
```

---

## SQL changes (for apply workflow)

### 1) Entity mapping status values

```sql
ALTER TABLE public.quantyx_entity_mappings
  ALTER COLUMN status SET DEFAULT 'draft';
```

Allowed status values (application-enforced):
- `draft`
- `applied`
- `partially_applied`
- `archived`

### 2) Traceability column in overrides

```sql
ALTER TABLE public.quantyx_entity_overrides
  ADD COLUMN IF NOT EXISTS source_mapping_id TEXT NULL;

CREATE INDEX IF NOT EXISTS idx_quantyx_entity_overrides_source_mapping
  ON public.quantyx_entity_overrides (source_mapping_id);
```

### 3) Optional apply event table (if explicit events preferred)

```sql
CREATE TABLE IF NOT EXISTS public.quantyx_mapping_apply_events (
  apply_id TEXT PRIMARY KEY,
  mapping_id TEXT NOT NULL,
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  connection_id TEXT NOT NULL,
  database_name TEXT NOT NULL,
  schema_name TEXT NOT NULL,
  selection_mode TEXT NOT NULL,
  applied_count INTEGER NOT NULL DEFAULT 0,
  skipped_count INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'draft',
  notes TEXT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

---

## End-to-end flow (async + mapping_id + apply)

1) Submit mapping job
- `POST /onboard/map/async`
- Response: `job_id`

2) Poll until completion
- `GET /jobs/{job_id}`
- `GET /jobs/{job_id}/result`

3) Review mapping output
- Use job result candidates
- Optional: `GET /onboard/map/history?tenant_id=...`
- Optional: `GET /onboard/map/{mapping_id}`

4) Apply mapping run
- `POST /onboard/map/{mapping_id}/apply`
- Writes canonical entities to `quantyx_entity_overrides`

5) Validate runtime entities
- `GET /entities?tenant_id=...`
- Should now return applied entities

6) Continue review workflow
- `PATCH /entities/{entity_id}` to refine
- `POST /review` / `PATCH /review/{review_id}` for status progression

---

## Acceptance criteria

1) Async and sync mapping both create rows in `quantyx_entity_mappings`.
2) A completed mapping run exposes a usable `mapping_id`.
3) `POST /onboard/map/{mapping_id}/apply` upserts canonical entities into `quantyx_entity_overrides`.
4) `GET /entities` returns applied entities immediately after apply.
5) Apply operations are auditable and traceable to `mapping_id`.

---

## Status

- Async/sync persistence parity: **completed**
- Tenant-scope history fallback: **completed**
- SQL migration hardening for mapping persistence: **completed**
- `mapping_id` apply API: **completed**
