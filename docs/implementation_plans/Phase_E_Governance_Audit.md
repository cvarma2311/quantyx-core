# Phase E: Governance and Audit

Goal: implement lineage and audit for explainability.

## Current state
- Lineage and policies endpoints implemented.
- Query audit logging implemented in `/query`.

## Deliverables
1) **Lineage builder**
   - Metric → dataset → dbt model mapping
   - `/governance/lineage`

2) **Query audit log**
   - `public.quantyx_query_audit` table
   - Log question, metrics, SQL hash, runtime

3) **Policies endpoint**
   - `/policies` returns active policies

4) **Metric registry (optional)**
   - `public.quantyx_metrics_registry` table
   - Stores lifecycle status: suggested/live/certified/deprecated

## Database prerequisites
- Run `artifacts/quantyx_tables.sql` to create `public.quantyx_query_audit` and
  `public.quantyx_metrics_registry`.

## Acceptance criteria
- Every query is auditable
- Lineage returns dbt model dependencies
