# Phase 04: Rollups + Cache Orchestration

## Objective
Add Cube‑style pre‑aggregations and caching for fast query serving.

## Features
- Rollup registry (metric, dims, grain)
- Materialized rollup tables
- Refresh jobs + scheduling
- Query planner prefers rollups
- Rollup APIs: list/create/refresh

## Deliverables
- `quantyx_rollup_registry`
- Rollup build/refresh jobs
- Cache hit telemetry
 - `/rollups` and `/rollups/{rollup_id}/refresh`
