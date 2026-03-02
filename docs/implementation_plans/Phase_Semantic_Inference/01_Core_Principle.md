# Phase 1: Core Principle (Determinism First)

## Objective
Make `/query` deterministic by default using compiled semantic knowledge. Only use LLM when deterministic resolution fails, and promote successful LLM resolutions back into the semantic graph so the next run is deterministic.

## Scope
- Applies to `/query` and any API that resolves natural language into metrics/dimensions.
- Requires deterministic resolution before any LLM call.

## Inputs
- `tenant_id`, `domain_id` (resolved server-side)
- Question text
- Existing semantic graph + cache

## Outputs
- Resolved metric(s), dimension(s), filters, time window
- Deterministic resolution trace (for logging and debugging)

## Determinism Rules
1. Always check cache first.
2. Always apply rule engine before LLM.
3. If deterministic resolution yields a valid query, **skip LLM**.
4. If LLM is used, **persist** mappings to the graph.

## Resolution Decision Tree
1. Cache hit → build SQL → return result
2. Cache miss → deterministic rules → graph lookup
3. Graph resolves → validate join path + base model
4. If valid → build SQL → return result
5. If unresolved → LLM fallback → validate → persist → return result

## Required Logging
- `query.cache_lookup` → hit/miss
- `query.rules_applied` → rules triggered
- `query.graph_resolve` → matched nodes/edges
- `query.llm_fallback` → invoked or skipped
- `query.promote_to_graph` → added edges

## Success Metrics
- ≥ 60% queries resolved without LLM within 2 weeks
- LLM call rate decreasing week over week
- Mean `/query` latency reduced by 50% after rollout

## Risks
- Graph resolution mismatches due to low-quality edges
- Cache poisoning from incorrect LLM results

## Mitigations
- Validation rules before promotion
- Confidence decay for unconfirmed edges
- Manual review endpoints for edge approval

