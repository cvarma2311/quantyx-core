# Phase H: Multi-Table and Multi-Metric Expansion

Goal: support complex metrics and joins beyond single-table queries.

## Current state
- Join graph added with `contracts/joins.yml`.
- Multi-table metrics supported when join definition exists.

## Deliverables
1) **Multi-table query builder**
   - Query plan with join graph

2) **Unified fact models**
   - dbt intermediate models for cross-domain metrics

## Acceptance criteria
- Queries spanning multiple facts succeed with guardrails
