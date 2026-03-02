# Phase 3: Deterministic Resolution Pipeline

## Objective
Resolve metrics/dimensions/filters deterministically using cache + rules + semantic graph.

## Inputs
- Question text
- Tenant/domain scope
- Semantic graph
- Rule engine

## Outputs
- Metric(s), dimension(s), filters
- SQL + params
- Trace log

## Steps
1) **Cache lookup**
   - Hash question + tenant/domain
   - If hit, reload resolved objects and refresh time filters
2) **Rule engine**
   - Time grammar (last week/month)
   - "by" grouping detection
   - "total/sum" metrics
3) **Graph resolution**
   - Tokenize question
   - Concept match → metrics + dimensions
4) **Validation**
   - Ensure all metrics share same base model
   - Ensure dimensions exist in fact or joinable dims
5) **SQL builder**
   - Apply time window
   - Apply GROUP BY
   - Default ORDER BY metric DESC

## Failure Conditions
- No metric resolved
- Multiple base models with no join path
- Time filter unresolved

## Logging
- `query.cache_hit` / `query.cache_miss`
- `query.rules_applied`
- `query.graph_candidates`
- `query.validation_fail`

## Success Metrics
- Deterministic resolution success ≥ 70%
- Average latency < 1s for cache hits

