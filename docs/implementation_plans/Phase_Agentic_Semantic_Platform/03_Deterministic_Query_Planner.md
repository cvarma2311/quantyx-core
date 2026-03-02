# Phase 03: Deterministic Query Planner

## Objective
Resolve queries deterministically (cache → rules → semantic graph) with LLM fallback only when needed.

## Pipeline
1. Cache lookup (normalized question)
2. Rule engine (time, trend, by‑group)
3. Semantic graph resolution
4. Join path validation
5. SQL generation

## Deliverables
- Resolver service
- Deterministic trace logs
- SQL builder with join planner

