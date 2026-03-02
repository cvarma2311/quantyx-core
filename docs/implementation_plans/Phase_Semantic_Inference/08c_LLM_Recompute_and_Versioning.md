# Phase 8c: LLM Recompute + Versioning

## Objective
Define what happens when LLM input changes and how semantic graph updates are recomputed and versioned.

---

## When to Recompute
Recompute when any of the following changes:
- `context_text` (primary)
- `schema_summary`
- `known_metrics`
- `known_glossary`

Use a `context_hash` of the full input bundle to detect change.

---

## Recompute Flow
1) Compute `context_hash`
2) If new hash:
   - Run LLM with new bundle
   - Validate outputs
   - Insert new nodes/edges
3) Mark old edges as inactive or lower confidence

---

## Update Strategy
- **Additive**: insert new edges with `is_current=true`
- **Supersede**: set previous edges `is_current=false`
- **Confidence decay**: reduce confidence if replaced

---

## Versioning Metadata
Store in `metadata`:
```json
{
  "context_hash": "ctx_abc123",
  "version": 3,
  "source": "llm"
}
```

---

## Idempotency
- If the same `context_hash` exists, no changes applied.
- If partial changes, only update the impacted edges.

---

## Failure Handling
- If LLM fails or validation fails, preserve current graph.
- Log with error context for retry.

