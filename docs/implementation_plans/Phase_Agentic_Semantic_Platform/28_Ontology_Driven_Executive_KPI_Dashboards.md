# Phase 28: Ontology-Driven Executive KPI Dashboards

## Objective
Stop generating low-value charts (for example `SUM(code)`/`SUM(id)`), and move to ontology-driven, business-meaningful KPI dashboards with strong measure-vs-dimension guardrails.

---

## Problem Statement
Current chart generation is technically valid but often semantically weak:
- Code/identifier columns are treated as measures because they are numeric.
- Metric generation defaults to generic `sum_<column>` patterns.
- Chart planner picks first numeric columns per table, causing non-executive dashboards.
- Derived metrics can be degraded during SQL generation if formula semantics are not preserved.

Observed examples from run output include sums over distributor/payment codes, which provide no business value.

---

## Scope
1. Column semantic-role classification (`measure`, `code/id`, `dimension`, `time`, `status`).
2. KPI metric generation policy that prefers ontology + domain templates.
3. Chart planner constraints to ensure only valid business measures are charted.
4. SQL generation safeguards to preserve formula metrics and prevent fallback `SUM(code)`.
5. Quality gates and observability for dashboard semantic quality.

Out of scope:
- Multi-language narrative generation.
- Full redesign of dashboard UI rendering components.

---

## Target Outcome
Each generated dashboard must answer executive questions like:
- How is throughput changing?
- Where are backlog/failures concentrated?
- What is plant/product productivity and utilization?
- What regions/products are driving variation?

No chart should aggregate IDs/codes or identifier surrogates.

---

## Design Principles
1. Ontology-first, not datatype-first.
2. Template-first metrics, heuristic fallback only when validated.
3. Deterministic guardrails before LLM narration.
4. Every chart must map to an explicit KPI intent.
5. Reject bad charts early; do not persist semantic noise.

---

## Architecture Changes

## 1) Semantic Role Classifier (new shared utility)
Add role classification for each column using:
- column name patterns (`_id`, `_code`, `code`, `identifier`, etc.)
- distinct ratio / uniqueness ratio
- ontology entity-type mapping
- optional sample-value heuristics

Output example:
```json
{
  "column": "PaymentErrorCode",
  "semantic_role": "identifier_code",
  "eligible_measure": false,
  "reason": "code_like_name + high_cardinality"
}
```

## 2) Metric Agent Refactor
Replace broad `sum_<numeric>` behavior with:
- **Tier 1**: domain pack metric templates (`packs/<domain>/metric_templates.yml`)
- **Tier 2**: validated derived metrics (rates, productivity, utilization)
- **Tier 3**: constrained fallback sums only for additive business measures

Hard exclusions:
- `_id`, `_code`, keys, surrogate IDs, or columns classified as identifiers.

## 3) Chart Planner Refactor
Chart candidate creation must use only approved metric defs.
- Do not infer metric from `numeric_columns[0]`.
- Require metric intent: `volume`, `rate`, `productivity`, `utilization`, `backlog`, `quality`.
- Require dimension compatibility (category/time/grain) with ontology hints.

## 4) Dashboard SQL Builder Safeguards
When chart has metric formula, preserve formula execution path.
- Prefer `metric_expr` from metric registry/spec.
- Do not fallback to `SUM(metric_column)` for rejected roles.
- Emit explicit skip reason: `invalid_metric_role`.

## 5) Quality Gate Agent Enhancements
Add semantic KPI quality checks:
- Block metric names matching `sum_.*(id|code)$`
- Block charts if measure role is not `measure_additive|measure_ratio`
- Require dashboard to include minimum KPI mix:
  - at least 1 trend
  - at least 1 breakdown
  - at least 1 rate/productivity/quality signal

---

## Data Contract Updates

## Metric definition payload
Add fields:
- `semantic_role`
- `metric_intent`
- `measure_confidence`
- `is_executive_kpi`

Example:
```json
{
  "metric_name": "rejection_rate_pct",
  "formula": "SUM(cs_rejection) / NULLIF(SUM(cs_handled),0)",
  "base_table": "lpg_plant_operations",
  "metric_type": "rate",
  "metric_intent": "quality",
  "semantic_role": "measure_ratio",
  "is_executive_kpi": true,
  "measure_confidence": 0.93
}
```

## Chart payload
Ensure payload includes:
- `metric_name`
- `metric_intent`
- `semantic_validation.status`
- `semantic_validation.reason`

---

## API/Stream Behavior Changes
No breaking endpoint changes required, but response artifacts must include semantic validation metadata.

Affected outputs:
- agent run stream events
- `/agentic/runs/{run_id}/chat`
- dashboard spec chart objects
- chart request/query payloads

Add artifact snippets:
```json
{
  "metric_name": "PaymentErrorCode",
  "semantic_validation": {
    "status": "rejected",
    "reason": "identifier_code is not aggregatable"
  }
}
```

---

## Implementation Phases

### Phase 28.1: Role Classification + Guardrails
- Add column semantic role classifier utility.
- Integrate into profiling output.
- Add hard deny-list for identifier/code aggregation.

Code areas:
- `services/ai/agentic_agents.py`
- `services/ai/agentic_orchestrator.py`

### Phase 28.2: Metric Generation Overhaul
- Refactor metric generation to template-first + validated fallback.
- Add metric intent tagging and confidence.
- Persist richer metric metadata in events/artifacts.

Code areas:
- `services/ai/agentic_agents.py`
- `packs/*/metric_templates.yml`

### Phase 28.3: Chart Planning and SQL Safety
- Planner uses only approved metric defs.
- SQL builder preserves formulas and blocks invalid fallback sums.
- Add explicit skip telemetry for invalid metrics.

Code areas:
- `services/ai/agentic_agents.py`
- `services/ai/agentic_orchestrator.py`

### Phase 28.4: Quality Gates + Regression Coverage
- Enforce KPI composition rules.
- Add tests for negative cases (`SUM(code)`, `SUM(id)`) and positive KPI cases.
- Add observability counters.

Code areas:
- `services/ai/agentic_orchestrator.py`
- `tests/` additions

---

## Acceptance Criteria
1. Zero generated charts contain `SUM(<id/code column>)`.
2. At least 80% of generated charts map to explicit KPI intents.
3. Dashboard includes trend + breakdown + quality/productivity signal.
4. `/chat` replay and stream outputs include semantic validation metadata.
5. Regression tests fail if code/id aggregation reappears.

---

## Rollout Strategy
1. Ship guardrails first in soft mode (`warn_only=true`) for one release cycle.
2. Capture rejected metric telemetry and tune patterns.
3. Enable hard-block mode for production.
4. Backfill existing dashboard specs with revalidation status on refresh.

---

## Risks and Mitigations
- Risk: over-blocking valid numeric business fields.
  - Mitigation: allowlist per domain pack (`measure_allowlist`).
- Risk: reduced chart count on sparse schemas.
  - Mitigation: fallback to validated count/rate metrics.
- Risk: drift across domains.
  - Mitigation: domain-specific metric templates + ontology entity mappings.

---

## Suggested Next Implementation Order
1. Phase 28.1 (classifier + hard deny list)
2. Phase 28.3 (SQL safety to stop wrong outputs immediately)
3. Phase 28.2 (template-first KPI enrichment)
4. Phase 28.4 (quality gates + tests + telemetry)
