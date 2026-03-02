# Phase Z: Unified Single-Table Lifecycle + Versioning (All Semantic Artifacts)

Goal: standardize artifact persistence so each artifact type uses one canonical registry table with strong lifecycle and versioning semantics, eliminating split staging/canonical tables.

Scope:
- Entities
- Hierarchies
- Facts
- Dimensions
- Metrics

Out of scope:
- Physical merge into one universal table for all artifact types.
- UI redesign (only API contract additions/adjustments required).

---

## 0) Design Principles

1) **One table per artifact type**
- Each artifact type has exactly one registry table as source of truth.
- No separate staging/canonical tables.

2) **Versioned rows, current pointer**
- Every logical artifact can have multiple versions.
- Exactly one row is `is_current=true` per artifact key and scope.

3) **Lifecycle status is explicit**
- Lifecycle values (minimum):
  - `inferred`
  - `suggested`
  - `live`
  - `reviewed`
  - `certified`
  - `deprecated`
  - `archived`

4) **Source provenance is first-class**
- Every row records whether it was created by:
  - `rule`
  - `llm`
  - `user`
  - `system`
- Optional run linkage (`source_run_id`) for traceability.

5) **Idempotent upsert + append version**
- Machine-generated refreshes can update same version when appropriate.
- User edits create new version rows.

---

## 1) Target Data Model

### 1.1 Common lifecycle/version columns (applied to each registry table)

Add to each registry table:
- `artifact_key TEXT NOT NULL` (stable logical key inside scope)
- `version_no INTEGER NOT NULL DEFAULT 1`
- `is_current BOOLEAN NOT NULL DEFAULT true`
- `lifecycle_status TEXT NOT NULL DEFAULT 'live'`
- `source_type TEXT NOT NULL DEFAULT 'system'` (`rule|llm|user|system`)
- `source_run_id TEXT NULL` (job id / mapping run id / extraction id)
- `change_reason TEXT NULL`
- `approved_by TEXT NULL`
- `approved_at TIMESTAMPTZ NULL`
- `supersedes_version_no INTEGER NULL`
- `created_by TEXT NULL`
- `updated_by TEXT NULL`

Constraints:
- Unique current row per scope + artifact key:
  - `UNIQUE (...scope..., artifact_key) WHERE is_current = true`
- Unique version per scope + artifact key:
  - `UNIQUE (...scope..., artifact_key, version_no)`

### 1.2 Entities/hierarchies normalization

Current split:
- `quantyx_entity_mappings` (run output)
- `quantyx_entity_overrides` (canonical)

Target:
- `quantyx_entity_overrides` becomes unified entity registry.
- `quantyx_hierarchy_overrides` becomes unified hierarchy registry.
- `quantyx_entity_mappings` retained temporarily only for migration/backfill; then deprecated.

Entity payload columns remain:
- `entity_id`, `description`, `join_key`, `examples`

Hierarchy payload columns remain:
- `hierarchy_name`, `levels`, `description`

---

## 2) SQL Migration Plan

### Phase Z.1: Add lifecycle/version columns

Apply to:
- `public.quantyx_entity_overrides`
- `public.quantyx_hierarchy_overrides`
- `public.quantyx_facts_registry`
- `public.quantyx_dimensions_registry`
- `public.quantyx_metrics_registry`

Representative SQL (entities):
```sql
ALTER TABLE public.quantyx_entity_overrides
  ADD COLUMN IF NOT EXISTS artifact_key TEXT,
  ADD COLUMN IF NOT EXISTS version_no INTEGER NOT NULL DEFAULT 1,
  ADD COLUMN IF NOT EXISTS is_current BOOLEAN NOT NULL DEFAULT true,
  ADD COLUMN IF NOT EXISTS lifecycle_status TEXT NOT NULL DEFAULT 'live',
  ADD COLUMN IF NOT EXISTS source_type TEXT NOT NULL DEFAULT 'system',
  ADD COLUMN IF NOT EXISTS source_run_id TEXT NULL,
  ADD COLUMN IF NOT EXISTS change_reason TEXT NULL,
  ADD COLUMN IF NOT EXISTS approved_by TEXT NULL,
  ADD COLUMN IF NOT EXISTS approved_at TIMESTAMPTZ NULL,
  ADD COLUMN IF NOT EXISTS supersedes_version_no INTEGER NULL,
  ADD COLUMN IF NOT EXISTS created_by TEXT NULL,
  ADD COLUMN IF NOT EXISTS updated_by TEXT NULL;

UPDATE public.quantyx_entity_overrides
  SET artifact_key = COALESCE(artifact_key, entity_id)
  WHERE artifact_key IS NULL;
```

Representative SQL (metrics):
```sql
ALTER TABLE public.quantyx_metrics_registry
  ADD COLUMN IF NOT EXISTS artifact_key TEXT,
  ADD COLUMN IF NOT EXISTS version_no INTEGER NOT NULL DEFAULT 1,
  ADD COLUMN IF NOT EXISTS is_current BOOLEAN NOT NULL DEFAULT true,
  ADD COLUMN IF NOT EXISTS lifecycle_status TEXT NOT NULL DEFAULT 'suggested',
  ADD COLUMN IF NOT EXISTS source_type TEXT NOT NULL DEFAULT 'system',
  ADD COLUMN IF NOT EXISTS source_run_id TEXT NULL,
  ADD COLUMN IF NOT EXISTS change_reason TEXT NULL,
  ADD COLUMN IF NOT EXISTS approved_by TEXT NULL,
  ADD COLUMN IF NOT EXISTS approved_at TIMESTAMPTZ NULL,
  ADD COLUMN IF NOT EXISTS supersedes_version_no INTEGER NULL,
  ADD COLUMN IF NOT EXISTS created_by TEXT NULL,
  ADD COLUMN IF NOT EXISTS updated_by TEXT NULL;

UPDATE public.quantyx_metrics_registry
  SET artifact_key = COALESCE(artifact_key, metric_name)
  WHERE artifact_key IS NULL;

UPDATE public.quantyx_metrics_registry
  SET lifecycle_status = COALESCE(lifecycle_status, 'suggested');
```

### Phase Z.2: Add version/current uniqueness indexes

Representative SQL:
```sql
CREATE UNIQUE INDEX IF NOT EXISTS uq_entity_current
  ON public.quantyx_entity_overrides
  (tenant_id, domain_id, connection_id, database_name, schema_name, artifact_key)
  WHERE is_current = true;

CREATE UNIQUE INDEX IF NOT EXISTS uq_entity_version
  ON public.quantyx_entity_overrides
  (tenant_id, domain_id, connection_id, database_name, schema_name, artifact_key, version_no);

CREATE UNIQUE INDEX IF NOT EXISTS uq_metric_current
  ON public.quantyx_metrics_registry
  (tenant_id, domain_id, connection_id, database_name, schema_name, artifact_key)
  WHERE is_current = true;

CREATE UNIQUE INDEX IF NOT EXISTS uq_metric_version
  ON public.quantyx_metrics_registry
  (tenant_id, domain_id, connection_id, database_name, schema_name, artifact_key, version_no);
```

### Phase Z.3: Backfill entity mapping runs into unified entity registry

Convert high-confidence mapping candidates into inferred entity rows:
```sql
-- Pseudocode migration pattern; execute via app migration script for deterministic conflict handling.
-- For each mapping candidate:
--   artifact_key = mapped_entity_type
--   lifecycle_status = 'inferred'
--   source_type = 'rule' or 'llm'
--   source_run_id = mapping_id
--   is_current = true (unless current exists; then append version)
```

### Phase Z.4: Deprecate mapping table (after cutover)

```sql
-- Soft deprecate first:
ALTER TABLE public.quantyx_entity_mappings
  ADD COLUMN IF NOT EXISTS deprecated BOOLEAN NOT NULL DEFAULT false;

-- Hard deprecate only after 2 stable releases:
-- DROP TABLE public.quantyx_entity_mappings;
```

---

## 3) Backend Logic Changes

## Phase Z.A: Shared lifecycle service

Create `services/ai/lifecycle_registry.py` with shared primitives:
- `get_current(scope, artifact_type, artifact_key)`
- `append_version(scope, artifact_type, artifact_key, payload, metadata)`
- `promote_status(scope, artifact_type, artifact_key, from_status, to_status)`
- `list_current(scope, artifact_type, statuses=None)`
- `list_versions(scope, artifact_type, artifact_key)`

Behavior:
- Any write that changes payload:
  1. mark previous current row `is_current=false`
  2. insert new row with `version_no = prev + 1`, `supersedes_version_no = prev`
  3. set `is_current=true`

## Phase Z.B: API write-path unification

### Entities
- `/onboard/map` and `/onboard/map/async`:
  - write inferred candidates directly to unified entity registry with:
    - `lifecycle_status='inferred'`
    - `source_run_id=<mapping_id or job_id>`
    - `source_type='rule'|'llm'`
- `/onboard/map/{mapping_id}/apply`:
  - transition selected inferred entities to `live`/`reviewed` by versioned writes.

### Facts/Dimensions
- `/onboard/infer-models` and async variant:
  - write rows with `lifecycle_status='live'`, `source_type='rule'|'llm'`, `source_run_id=job_id`.

### Metrics
- `/metrics/suggested` and async variant:
  - write rows with `lifecycle_status='suggested'`, `source_type='rule'`, `source_run_id=job_id`.
- `/metrics/{metric_id}` patch:
  - user edits append new version with updated lifecycle.

## Phase Z.C: API read-path consistency

Default read behavior:
- `GET /entities`, `GET /facts`, `GET /dimensions`, `GET /metrics` return only `is_current=true`.
- Default lifecycle filter excludes `deprecated` and `archived`.
- Optional query param `statuses=` to include `inferred`/`suggested` in review UIs.

Add version endpoints:
- `GET /entities/{entity_id}/versions`
- `GET /facts/{fact_id}/versions`
- `GET /dimensions/{dimension_id}/versions`
- `GET /metrics/{metric_id}/versions`

## Phase Z.D: Review + promotion workflow

Promotion transitions (app-enforced):
- inferred -> live
- suggested -> live
- live -> reviewed
- reviewed -> certified
- certified -> deprecated
- deprecated -> archived

Each transition:
- appends version row (unless metadata-only transition policy chosen),
- records `approved_by`, `approved_at`, `change_reason`,
- writes a `quantyx_review_events` row.

---

## 4) API Contract Deltas

Required additions:
- Add lifecycle/version fields in list responses (at least):
  - `artifact_key`
  - `version_no`
  - `lifecycle_status`
  - `is_current`
  - `source_type`
  - `source_run_id`

Optional controls:
- `include_versions=false` default
- `statuses=inferred,live,reviewed,...`
- `source_run_id=...` for trace filtering

Hard cutover policy:
- No backward compatibility window.
- Use `lifecycle_status` as the only lifecycle field.
- Remove legacy staging tables and legacy alias columns after cutover.

---

## 5) Rollout Phases

## Phase Z1: Schema-first rollout
- Add lifecycle/version columns + indexes.
- Do not change API behavior yet.
- Backfill artifact keys and lifecycle defaults.
- Keep `artifact_key` nullable in Z1 to avoid breaking existing insert paths; enforce non-null after Z2 write-path updates.

## Phase Z2: Direct-write rollout
- Write only to unified lifecycle registries.
- No dual-write to legacy staging tables.

## Phase Z3: Read-path switch
- `GET /entities` reads unified current rows only.
- Review UI uses `statuses=` filters as needed.

## Phase Z4: Versioned update enforcement
- All PATCH/apply operations append versions (no in-place overwrite).
- Enable version history endpoints.

## Phase Z5: Legacy cleanup (hard cutover)
- Stop writing to `quantyx_entity_mappings`.
- Drop `quantyx_entity_mappings` table.
- Drop legacy `status` columns from registries.

Hard cutover SQL (representative):
```sql
ALTER TABLE public.quantyx_entity_overrides ALTER COLUMN artifact_key SET NOT NULL;
ALTER TABLE public.quantyx_hierarchy_overrides ALTER COLUMN artifact_key SET NOT NULL;
ALTER TABLE public.quantyx_facts_registry ALTER COLUMN artifact_key SET NOT NULL;
ALTER TABLE public.quantyx_dimensions_registry ALTER COLUMN artifact_key SET NOT NULL;
ALTER TABLE public.quantyx_metrics_registry ALTER COLUMN artifact_key SET NOT NULL;

DROP INDEX IF EXISTS idx_quantyx_entity_mappings_scope;
DROP TABLE IF EXISTS public.quantyx_entity_mappings;

ALTER TABLE public.quantyx_facts_registry DROP COLUMN IF EXISTS status;
ALTER TABLE public.quantyx_dimensions_registry DROP COLUMN IF EXISTS status;
ALTER TABLE public.quantyx_metrics_registry DROP COLUMN IF EXISTS status;
```

---

## 6) Acceptance Criteria

1) Every artifact type supports versioned rows with one current row per scope+artifact key.
2) Lifecycle transitions are consistent across entities/facts/dims/metrics.
3) Async and sync paths produce identical lifecycle state semantics.
4) `GET` APIs return deterministic current rows and optional status-filtered views.
5) Full traceability exists from artifact row to source run/job/review event.
6) No runtime dependency on split staging/canonical tables for entities.

---

## 7) Risks and Mitigations

Risk: write amplification from version appends.  
Mitigation: partial indexes + archival policy for old versions.

Risk: API consumers relying on old `status` semantics.  
Mitigation: hard cutover release notes + strict contract enforcement.

Risk: migration conflicts on duplicate current rows.  
Mitigation: pre-migration dedupe script choosing latest `updated_at` as current.

---

## 8) Status

- Strategy defined: **approved**
- Phase Z1 SQL (schema-first columns/backfill/indexes): **completed**
- Phase Z2/Z3 write+read switch to unified lifecycle registries: **completed**
- Phase Z4 append-only versioning in update/apply paths: **completed**
- Phase Z5 legacy cleanup SQL (drop staging + drop alias status columns): **completed**
