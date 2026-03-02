# Phase 4: Learning Loop (LLM Promotion)

## Objective
Persist LLM resolutions into the semantic graph so the next query becomes deterministic.

## Inputs
- LLM output (metrics, dimensions, filters)
- Validation results

## Outputs
- New graph edges (synonym → concept, concept → metric, etc.)
- Updated confidence scores

## Steps
1) Build LLM context from top graph candidates
2) Validate LLM output against graph + schema
3) Persist valid edges with `source=llm`
4) Increase confidence with repeated usage
5) Decrease confidence when corrected

## Edge Promotion Rules
- Only promote if mapping resolves to a valid base model
- Only promote synonyms if normalized and unique

## Feedback Handling
- If user corrects result → reduce confidence for edges used
- If user confirms → mark as `user_confirmed`

## Logging
- `llm.resolve_request` (prompt size + candidates)
- `llm.resolve_response`
- `llm.promotion_applied`

## Success Metrics
- Repeat query becomes deterministic after 1–2 uses
- LLM usage declines over time

