# Phase 36: Context-Text-First LLM Metric Interpretation and Validation

## Objective
Make `context_text` the primary human-authored source of business meaning during deployment, and make the agent pipeline interpret that text with an LLM to propose metrics, formulas, grains, time columns, and chart intent before persisting validated semantic artifacts.

The target is:
- users provide plain business context text
- agents read that text together with schema and profiling evidence
- LLM proposes candidate metrics and KPI intent from the text
- the platform validates those proposals against real tables and columns
- only validated metric artifacts are persisted and used by conversations, charts, and dashboards

This phase replaces parser-first or heuristic-first context handling with a text-first, LLM-interpreted, validation-backed semantic flow.

---

## Problem

Today the platform only partially follows this architecture:
- `context_text` is accepted at deployment time and is consumed by `ContextAgent`
- `MetricAgent` is still mostly heuristic-first
- current context-to-metric support still includes parser-like extraction paths for structured text/SQL blocks
- LLM reranking improves ordering, but not the initial semantic interpretation enough
- persisted metrics do not yet fully preserve context-derived provenance

That means:
- business intent written in plain text does not yet drive metric generation strongly enough
- users may need to provide semi-structured text for best results
- metric persistence is still too disconnected from the original business context

---

## Desired Architecture

### 1) Input Layer: Human-Friendly Text
`/workspace/deployments` accepts:
- `context_text`
- optional `context_ids`

The contract is:
- users can provide plain text
- no rigid schema is required at the API boundary
- SQL examples, formulas, and business rules are all allowed as text

### 2) Interpretation Layer: LLM Reads Context
`ContextAgent` and `MetricAgent` should jointly interpret:
- `context_text`
- schema graph
- profiling evidence
- glossary and ontology context
- domain pack preferences

The LLM should propose:
- candidate metrics
- business names
- formulas
- grains
- canonical time columns
- preferred breakdown dimensions
- chart preferences

### 3) Normalization and Validation Layer
LLM output must be normalized into deterministic artifacts and validated against:
- real tables
- real columns
- profiling/model evidence
- grain/time compatibility
- safe SQL/formula rules

Invalid or hallucinated proposals must not persist.

### 4) Persistence Layer
Only validated outputs become durable artifacts:
- metrics registry entries
- context-derived semantic artifacts
- provenance metadata

### 5) Consumption Layer
Downstream consumers use persisted artifacts, not raw text:
- conversations
- query planner
- chart planner
- dashboard generation

---

## Current Gaps

### 1) `context_text` is not first-class input to `MetricAgent`
Today:
- `ContextAgent` reads it
- `MetricAgent` mainly generates heuristically from profiling and templates

Gap:
- `MetricAgent` should directly incorporate `context_text` during metric proposal

### 2) Metric proposal is still heuristic-first
Today:
- deterministic heuristics create candidates
- LLM reranking happens after that

Gap:
- LLM should propose candidate metrics from business meaning, not only rerank heuristic outputs

### 3) Context extraction is still partly parser-like
Today:
- explicit structured blocks and SQL-like patterns are helpful for overrides

Gap:
- structured parsing should be optional assistive behavior, not the primary semantic contract

### 4) Validation is too shallow at metric-definition time
Gap:
- we need a dedicated validator/binder for context-derived metric proposals

### 5) Provenance is incomplete
Gap:
- persisted metrics should record whether they came from:
  - pure heuristic fallback
  - template
  - LLM proposal from `context_text`
  - validated SQL example from context

### 6) Chart and dashboard planning do not strongly prioritize context-derived KPIs
Gap:
- if business context explicitly emphasizes a KPI, chart selection should reflect that

---

## Target Behavior

If the user provides text like:

```text
Total production is calculated as:
ROUND((SUM(production_14_2kg) * 14.2 + SUM(production_19kg) * 19) / 1000, 0)

Use process_date as the canonical operational date.
Prefer charts for total production by day and month.
```

Then the deployment should:
1. understand that this is a business metric definition
2. propose a `total_production` metric for `lpg_plant_operations`
3. bind the formula to real columns
4. validate that `process_date` exists and fits the grain
5. persist the metric with provenance
6. prioritize `total_production` in chart and dashboard generation

Without requiring the user to provide machine-structured JSON.

---

## Scope

### In scope
- context-text-first metric interpretation
- LLM-based metric proposal from context
- validation and binding of proposed metrics
- provenance persistence
- context-aware chart/dashboard prioritization
- debug/observability for context-derived metric generation

### Out of scope
- full replacement of all deterministic fallbacks
- free-form SQL execution from user context without validation
- changing public conversation APIs

---

## Implementation Plan

### Phase 36.1: Make `context_text` First-Class in MetricAgent
- pass merged `context_text` explicitly into `MetricAgent` prompt inputs
- include:
  - schema summary
  - profiling summary
  - domain pack hints
  - glossary/ontology terms
- stop treating context as only an upstream `ContextAgent` side effect

Expected result:
- `MetricAgent` can propose metrics from business text directly

### Phase 36.2: LLM Metric Proposal Prompt
- add a dedicated metric proposal prompt for:
  - metric name
  - display name
  - business description
  - base table
  - formula / SQL expression
  - grain
  - time column
  - preferred dimensions
  - confidence
  - rationale
- require JSON-only output
- allow the LLM to use context text plus schema/profiling evidence

Expected result:
- metric generation becomes context-and-LLM-first instead of heuristic-first

### Phase 36.3: Metric Proposal Validator and Binder
- add a validator that checks:
  - table exists
  - referenced columns exist
  - aggregation is valid
  - grain is compatible with time column
  - preferred dimensions exist or can be mapped safely
  - formula can be qualified against the base table
- normalize accepted proposals into registry-ready metric artifacts
- reject invalid proposals explicitly

Expected result:
- no hallucinated context-derived metrics are persisted

### Phase 36.4: Provenance and Lineage for Context-Derived Metrics
- persist metadata such as:
  - `derivation_source`
  - `derivation_method`
  - `source_context_ids`
  - `has_inline_context_text`
  - `llm_rationale`
  - validation status
- include these in debug payloads and run artifacts

Expected result:
- each metric explains where it came from

### Phase 36.5: Hybrid Fallback Policy
- if LLM proposal succeeds and validates:
  - persist context-derived metrics first
- if LLM proposal partially succeeds:
  - merge valid proposals with deterministic fallback metrics
- if LLM proposal fails:
  - fall back to deterministic metric generation
- record which path was taken

Expected result:
- robustness without losing semantic quality

### Phase 36.6: Chart and Dashboard Prioritization from Context-Derived KPIs
- chart planning should prefer metrics whose provenance indicates:
  - `context_text` origin
  - higher semantic confidence
  - explicit KPI emphasis
- dashboard generation should surface those metrics first

Expected result:
- deployment dashboards reflect business context directly

### Phase 36.7: Observability and Debugging
- add logs for:
  - context-to-metric proposal prompt inputs
  - raw LLM metric proposal summary
  - validation accept/reject reasons
  - persisted metric provenance summary
  - dashboard metrics chosen because of context-derived priority
- optionally extend debug endpoints to show:
  - proposed metrics
  - rejected metrics
  - provenance

Expected result:
- easy diagnosis when business context is ignored or misinterpreted

---

## API Impact

### Existing API Contract
No breaking API changes are required.

`/workspace/deployments` already supports:
- optional `context_text`
- optional `context_ids`

That contract remains correct.

### Behavioral Changes
- `context_text` becomes a first-class semantic input for metric creation
- deployments with business context should produce better context-aligned metrics automatically
- persisted metric artifacts should carry context-derived provenance

### Optional Future Additions
Possible later additive APIs:
- metric proposal debug endpoint
- deployment semantic interpretation preview endpoint

These are not required for the first implementation pass.

---

## Storage / Artifact Changes

Likely additions to metric persistence metadata:
- `derivation_source`
- `derivation_method`
- `provenance_json`
- `validation_json`

Likely additions to agent artifacts:
- `ContextAgent.metric_intent_summary`
- `MetricAgent.context_metric_candidates`
- `MetricAgent.validation_results`

No legacy migration behavior is required if this is applied only to future deployments.

---

## Implementation Status

Implemented in this pass:
- Phase 36.1:
  - `MetricAgent` now receives and uses merged `context_text` directly during metric generation
- Phase 36.2:
  - added an LLM metric proposal step that reads:
    - `context_text`
    - schema summary
    - profiling summary
    - glossary hints
- Phase 36.3:
  - added validation and binding for LLM-proposed metric candidates:
    - base table must exist
    - referenced formula columns must exist
    - time column must exist if provided
    - preferred dimensions are normalized to valid columns
- Phase 36.4:
  - persisted metric rows now carry provenance-adjacent metadata through:
    - `source_type`
    - `change_reason`
    - `owner`
    - `version`
  - metric agent event artifacts also include accepted/rejected context metric diagnostics
- Phase 36.5:
  - hybrid fallback is now active:
    - validated context-LLM metrics are merged ahead of deterministic metrics
    - deterministic metric generation still runs if LLM proposals are absent or invalid
- Phase 36.6:
  - context-derived metrics now carry higher metric priority and flow into downstream chart/dashboard planning through the normal metric selection path
- Phase 36.7:
  - added logs for:
    - context metric prompt usage
    - candidate counts
    - accepted/rejected metric validation diagnostics

Partially implemented:
- provenance is persisted via existing registry fields and agent artifacts, but not yet via dedicated provenance JSON columns
- chart planner uses the improved metric priority, but does not yet surface a dedicated “chosen because context emphasized this KPI” explanation per chart
- structured parser-based metric overrides still exist as an assistive fallback alongside the new context-text-first LLM path

Not yet implemented:
- a dedicated public debug endpoint for context-derived metric proposal/validation review
- deeper semantic validation such as grain-conflict reasoning against model registries beyond current table/column/time validation

---

## Acceptance Criteria

1. A deployment with plain `context_text` can produce context-derived metrics without requiring structured input.
2. `MetricAgent` reads and uses `context_text` directly during metric proposal.
3. LLM-proposed metrics are validated against actual schema/profiling before persistence.
4. Invalid context-derived metrics are rejected and logged with reasons.
5. Valid context-derived metrics persist with provenance metadata.
6. Chart and dashboard generation prioritize validated context-derived KPI metrics over generic fallback metrics.
7. If LLM interpretation fails, deterministic fallback still produces a valid deployment.

---

## Test Plan

1. Provide plain text business context with a metric formula and a time-column instruction.
   Verify a validated metric is persisted with the expected base table, formula, and grain.

2. Provide context with an invalid column reference.
   Verify the metric proposal is rejected and does not persist.

3. Provide context with KPI emphasis but no formula.
   Verify the LLM can still prioritize the correct existing KPI column and persist it with valid metadata.

4. Run deployment without `context_text`.
   Verify deterministic fallback still works.

5. Verify dashboard output favors context-derived metrics when both context-derived and fallback metrics are available.

6. Verify debug logs and artifacts clearly show:
   - proposed metrics
   - accepted metrics
   - rejected metrics
   - provenance path

---

## Review Questions

Before implementation, we should review:
- how much freedom the LLM should have in proposing formulas
- whether SQL examples in `context_text` should be treated as strong evidence or only hints
- what validation strictness is required for first release
- whether provenance belongs in the metrics registry row, artifact payloads, or both
- whether chart prioritization should use only validated context-derived metrics or also context-weighted heuristic metrics

---

## Recommended Implementation Order

1. Phase 36.1: pass `context_text` directly into `MetricAgent`
2. Phase 36.2: add LLM metric proposal prompt
3. Phase 36.3: add metric proposal validator/binder
4. Phase 36.4: persist provenance
5. Phase 36.5: finalize fallback policy
6. Phase 36.6: prioritize context-derived KPIs in chart/dashboard generation
7. Phase 36.7: add observability and debug surfacing
