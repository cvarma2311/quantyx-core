# Phase 6: APIs + Storage Evolution

## Objective
Expose deterministic + diagnostic behavior and persist semantic memory.

## API Behavior
### `/query`
- Deterministic resolve (cache + rules + graph)
- LLM fallback only when unresolved
- Diagnostic queries trigger inference pipeline

### `/insights/diagnose` (future)
- Explicit diagnostic endpoint with richer payload

## Storage
- `semantic_nodes`
- `semantic_edges`
- `semantic_usage`
- `semantic_feedback` (optional)

## Metrics to Track
- LLM call rate
- Cache hit rate
- Graph resolution success rate
- Latency by step

## Migration Path
- Start in Postgres
- Add sync job to Neo4j when joins expand

## Success Criteria
- LLM calls reduced by ≥ 50%
- Response latency stable under 1s for cache hits

