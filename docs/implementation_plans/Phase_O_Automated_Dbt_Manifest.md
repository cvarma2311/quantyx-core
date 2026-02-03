# Phase O: Automated dbt Manifest (Backend-Only)

Goal: make dbt fully automatic during connection scan so customers never see or
configure dbt. The backend resolves dbt settings, creates per-tenant dbt project
directories, runs `dbt compile`, and stores manifest.json in Postgres.

---

## 1) Dbt config registry (new table)

Store dbt settings per tenant/domain/connection so the backend can resolve
config without UI input.

Table: `public.quantyx_dbt_config`

- config_id (PK)
- tenant_id (required)
- domain_id (required)
- connection_id (nullable)
- dbt_project_path (required or auto-resolved)
- profile_name (required)
- target_name (required)
- profiles_dir (optional)
- created_at, updated_at

Recommended index:
- (tenant_id, domain_id, connection_id, updated_at desc)

---

## 2) Server-side defaults (no UI)

Resolution order for dbt config:
1) `quantyx_dbt_config` for (tenant_id, domain_id, connection_id)
2) `quantyx_dbt_config` for (tenant_id, domain_id, connection_id IS NULL)
3) Environment defaults (global server config)
4) `resolve_dbt_project_dir(tenant_id)` + default profile/target

This guarantees dbt config even if nothing is pre-seeded.

---

## 3) Per-tenant dbt project directories

- Directory per tenant: `dbt_projects/dbt_<tenant_id>/`
- Path tracked in `quantyx_dbt_config`
- If missing, auto-create on scan

---

## 4) Auto-manifest on `/onboard/scan-connection`

After scan completes:
1) Resolve tenant/domain for the scan
2) Resolve dbt config using the order above
3) Ensure dbt project directory exists (auto-create)
4) Run `dbt compile`
5) Store manifest in `public.quantyx_dbt_manifest`

This keeps dbt completely transparent to customers.

---

## 5) Internal admin APIs (optional, admin-only)

Useful for ops to seed or override config.

- `POST /dbt/config`
  - Upsert dbt config for tenant/domain/connection.
- `GET /dbt/config/latest?tenant_id=...&domain_id=...`
  - Fetch latest config for tenant/domain.

These endpoints are not exposed in customer UI.

---

## 6) Code changes

- New storage: `public.quantyx_dbt_config`
- New helpers in `services/ai/dbt_manifest.py` (or new module):
  - `upsert_dbt_config`
  - `get_latest_dbt_config`
  - `resolve_dbt_config`
- `/onboard/scan-connection`:
  - resolve tenant/domain
  - auto-manifest generation after scan

---

## 7) Acceptance criteria

- Scan triggers manifest generation with no UI input.
- Each tenant has an isolated dbt project directory.
- Manifest reads come only from DB (Phase M compliance).
- Config resolution falls back to defaults when no config exists.
