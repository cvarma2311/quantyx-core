# Phase C: Metric Editing and Contract Apply

Goal: allow users to correct auto-detected metrics and add new metrics.

## Current state
- Metrics load from `contracts/metrics/core_metrics.yml` plus certified registry metrics.
- Metric registry supports suggested metrics and custom updates.

## Deliverables
1) **Metric edit API**
   - `PATCH /metrics/{id}` for SQL, description, grain, status

2) **Metric create API**
   - `POST /metrics` to add new metric

3) **Contract validation**
   - `POST /contracts/validate`

4) **Contract apply**
   - `POST /contracts/apply` to reload catalog

## Acceptance criteria
- Suggested metric can be promoted to certified
- Custom metric can be added without code change
- `POST /contracts/apply` reloads the catalog after edits

## End-to-end flow (seed → review → promote)
1) Seed suggestions
   - `POST /metrics/suggested?domain_id=...&persist=true`
2) Review / edit
   - `PATCH /metrics/{metric_id}` to fix SQL, add dimensions, or set status
3) Create custom metric
   - `POST /metrics` with explicit SQL + dimensions
4) Apply contracts
   - `POST /contracts/apply` to refresh the runtime catalog
