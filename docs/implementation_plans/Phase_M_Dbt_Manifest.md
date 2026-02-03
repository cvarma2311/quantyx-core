# Phase M: dbt Manifest Generation and DB Storage

Goal: run dbt automatically in all deployments, store `manifest.json` in Postgres, and make all code read manifest data from the database (no filesystem reads).

---

## Why this exists

`manifest.json` is required to resolve dbt models, schemas, and lineage metadata. To make the product portable across deployments, we run dbt in-process and persist the manifest JSON in Postgres so all services read from the DB, not the filesystem.

---

## SQL changes

```sql
CREATE TABLE IF NOT EXISTS public.quantyx_dbt_manifest (
  manifest_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  connection_id TEXT NULL,
  dbt_project_path TEXT NOT NULL,
  profile_name TEXT NOT NULL,
  target_name TEXT NOT NULL,
  manifest_json JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_quantyx_dbt_manifest_tenant
  ON public.quantyx_dbt_manifest (tenant_id, domain_id, created_at DESC);
```

---

## API

### 1) Generate and store manifest

`POST /dbt/manifest/generate`

Request:
```json
{
  "tenant_id": "tenant_a",
  "domain_id": "manufacturing",
  "connection_id": "conn_prod",
  "dbt_project_path": "dbt_projects/dbt_tenant_a",
  "profile_name": "default",
  "target_name": "dev",
  "profiles_dir": "~/.dbt"
}
```

Response:
```json
{
  "manifest_id": "manifest_123",
  "status": "stored",
  "tenant_id": "tenant_a",
  "dbt_project_path": "dbt_projects/dbt_tenant_a"
}
```

### 2) Fetch latest manifest

`GET /dbt/manifest/latest?tenant_id=...&domain_id=...`

Response:
```json
{
  "manifest_id": "manifest_123",
  "tenant_id": "tenant_a",
  "domain_id": "manufacturing",
  "connection_id": "conn_prod",
  "dbt_project_path": "dbt",
  "profile_name": "default",
  "target_name": "dev",
  "created_at": "2025-02-14T10:00:00Z",
  "manifest_json": {"metadata": {"dbt_version": "1.7.0"}}
}
```

---

## Execution flow

1) API receives dbt parameters.
2) Run `dbt compile` with `--project-dir`, `--profile`, `--target`, and optional `--profiles-dir`.
3) Read `dbt/target/manifest.json`.
4) Store JSON into `public.quantyx_dbt_manifest`.
5) All manifest reads use DB API, never filesystem.

---

## Code changes

- Replace filesystem reads in:
  - `services/ai/schema_loader.py`
  - `services/ai/onboarding/metrics_registry.py`
  - `services/ai/governance.py`
  - `/schema` + lineage endpoints
- Add `services/ai/dbt_manifest.py` for run/store/load logic.

---

## Acceptance criteria

- `POST /dbt/manifest/generate` runs dbt and stores manifest in DB.
- `GET /dbt/manifest/latest` returns the latest manifest.
- No code path reads `manifest.json` from disk.
- `metrics/suggested?persist=true` uses DB manifest for model resolution.
