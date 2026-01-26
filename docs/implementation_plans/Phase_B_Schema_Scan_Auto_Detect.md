# Phase B: Schema Scan and Auto-Detection Pipeline

Goal: implement the auto-detection pipeline from `V2_PRODUCT_PREREQUISITES.md`.

## Current state
- Basic onboarding endpoints implemented:
  - `POST /onboard/scan`
  - `POST /onboard/map`
  - `POST /metrics/suggested`
- Schema scan reads information_schema and pg_stats.
- Suggested metrics include:
  - numeric measures
  - time columns
  - entity candidates from ontology
  - measure confidence + additive flag
  - unit detection for common suffix patterns
  - low-confidence bucket for review

## Deliverables (remaining)
1) **Entity mapping confidence**
   - strengthen confidence scoring
   - require user confirmation for low confidence
   - optional LLM-assisted suggestions when API key is available

2) **Suggested metric lifecycle**
   - persist suggestions to `quantyx_metrics_registry` with confidence/additive

## Acceptance criteria
- Onboarding scan returns suggestions
- Suggested metrics available via `/metrics/suggested`
- Ontology mapping available via `/onboard/map`
