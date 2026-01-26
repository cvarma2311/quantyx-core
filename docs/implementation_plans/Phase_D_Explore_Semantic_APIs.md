# Phase D: Explore and Semantic APIs

Goal: fulfill Explore endpoints in `V2_API.md`.

## Current state
- `/metrics` includes status/owner/version metadata.
- `/datasets` endpoint implemented from domain packs.
- `/entities` endpoint implemented with overrides.

## Deliverables
1) **Datasets registry**
   - `contracts/datasets/*.yml` per pack
   - `/datasets` endpoint

2) **Metric catalog endpoint**
   - `/metrics` includes status, owner, version

3) **Entities endpoint**
   - `/entities` returns hierarchy from ontology

4) **Dimensions exploration**
   - `/dimensions` list
   - `/dimension-values` distinct values
   - cursor-based pagination for explore endpoints

## Acceptance criteria
- UI can browse datasets, metrics, entities, and dimension values
