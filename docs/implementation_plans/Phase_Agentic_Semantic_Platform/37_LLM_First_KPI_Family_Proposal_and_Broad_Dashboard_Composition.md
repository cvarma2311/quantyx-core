# Phase 37: LLM-First KPI Family Proposal and Broad Dashboard Composition

## Objective
Make metric proposal, chart proposal, and dashboard composition LLM-first, while keeping deterministic validation after each stage. At the same time, enforce aligned KPI-family derivation for operational datasets so the system understands families such as:
- `total_production`
- `total_net_hours`
- `total_productivity`
- `normal_total_production`
- `normal_net_hours`
- `normal_productivity`
- `overtime_total_production`
- `overtime_net_hours`
- `overtime_productivity`

The immediate business goal is to stop producing semantically broken metrics like:
- `normal_total_production / overtime_net_hours`

and instead produce strong outputs such as:
- total production by day
- total production by month
- total productivity by day
- total productivity by month
- normal productivity by day
- overtime productivity by day
- total production by plant
- total production by zone
- total production by region
- total productivity by plant
- total productivity by zone
- total productivity by region

---

## Problem

Current behavior still has three architectural weaknesses:

### 1) Metric generation is not fully LLM-first
Even after Phase 36, the system still depends materially on:
- deterministic heuristic metric generation
- fallback token matching
- derived metric generation from shallow pattern matches

This can produce semantically wrong combinations when multiple related KPI families exist in the same table.

### 2) Chart and dashboard planning are only partly LLM-first
Current chart planning uses:
- deterministic candidate generation
- optional LLM reranking

This improves ordering, but not enough of the actual proposal semantics.

### 3) KPI-family alignment is not enforced
For example:
- `normal_total_production` should only pair with `normal_net_hours`
- `overtime_total_production` should only pair with `overtime_net_hours`
- `total_production` should only pair with `total_net_hours`

The platform currently lacks a first-class concept of aligned KPI families.

---

## Desired Architecture

### 1) Metric Proposal: LLM-First
Input to the metric proposal step:
- `context_text`
- schema graph
- profiling summary
- glossary and ontology
- domain pack hints

LLM should propose:
- direct KPI metrics from source columns
- derived KPI metrics from aligned numeric families
- business names and descriptions
- grain and time column
- preferred breakdowns

Deterministic validation then accepts or rejects the proposals.

### 2) Chart Proposal: LLM-First
Input to chart proposal:
- validated metric set
- available dimensions
- time columns
- profiling strength
- business context

LLM should propose:
- trend charts
- breakdown charts
- comparison charts
- optional share charts

Validators then reject:
- low-quality chart shapes
- invalid metric/dimension combinations
- semantically weak or duplicate charts

### 3) Dashboard Composition: LLM-First
Input to dashboard composition:
- validated chart candidates
- KPI priorities
- business context
- domain hints

LLM should propose a broader dashboard composition than the current narrow top-5 selection.

Validators then enforce:
- chart diversity
- KPI coverage
- operational relevance
- duplicate suppression

### 4) Deterministic Safety Remains Mandatory
LLM should propose, not directly persist or execute.

The deterministic layer must still validate:
- table existence
- column existence
- formula bindability
- family alignment
- time-grain compatibility
- chart shape validity
- dashboard composition sanity

---

## Scope

### In scope
- LLM-first metric proposal
- LLM-first chart proposal
- LLM-first dashboard composition
- aligned KPI-family derivation
- broader chart candidate generation
- stronger default dashboard ranking
- deterministic validation after each semantic stage

### Out of scope
- full conversation planner rewrite
- manual dashboard editing UX
- arbitrary user-authored SQL execution from context text

---

## KPI Family Model

This phase introduces a first-class concept of KPI families.

### Example family prefixes
- `total`
- `normal`
- `break`
- `overtime`

### Example family members
- production metric:
  - `total_production`
  - `normal_total_production`
  - `break_total_production`
  - `overtime_total_production`
- hours metric:
  - `total_net_hours`
  - `normal_net_hours`
  - `break_net_hours`
  - `overtime_net_hours`
- productivity metric:
  - direct source column if present
  - otherwise derived as aligned production/hours ratio within the same family

### Alignment rule
Only derive within the same family:
- `total_production / total_net_hours`
- `normal_total_production / normal_net_hours`
- `break_total_production / break_net_hours`
- `overtime_total_production / overtime_net_hours`

Never cross families.

---

## Implementation Plan

### Phase 37.1: LLM-First Metric Proposal
- make `MetricAgent` proposal LLM-first by default
- use deterministic heuristic metrics as fallback, not primary generation
- pass:
  - `context_text`
  - table names
  - all relevant column names
  - profiling summaries
  - glossary hints

Expected result:
- metric generation is driven by business meaning and table semantics first

### Phase 37.2: KPI Family Extraction and Alignment
- add deterministic family extraction for metric columns
- identify family prefixes such as:
  - `total`
  - `normal`
  - `break`
  - `overtime`
- derive ratio metrics only from aligned families
- prefer direct KPI columns if they already exist

Expected result:
- no more mismatched productivity formulas

### Phase 37.3: Deterministic Metric Validator Upgrade
- validate:
  - formula references
  - time column existence
  - preferred dimension existence
  - family alignment
  - grain consistency
- reject invalid or weak LLM metric proposals

Expected result:
- LLM-first does not compromise correctness

### Phase 37.4: LLM-First Chart Proposal
- add an LLM chart proposal step from:
  - validated metrics
  - dimension inventory
  - chart intent from context
  - profiling strength
- allow larger candidate generation than current narrow default set

Expected result:
- more semantically relevant chart candidates

### Phase 37.5: Chart Validator and Deduplication
- reject:
  - semantically duplicate charts
  - weak metric/dimension pairings
  - low-signal or low-quality dimensions
  - charts that do not fit KPI intent
- normalize chart groups such as:
  - trend
  - breakdown
  - comparison
  - share

Expected result:
- broader chart generation without quality collapse

### Phase 37.6: LLM-First Dashboard Composition
- compose dashboard from validated chart candidates
- prefer broader KPI coverage instead of early truncation to 5
- allow 8-12 strong charts when confidence is high

Expected result:
- dashboard becomes more analytically complete

### Phase 37.7: Dashboard Ranking and Coverage Rules
- enforce coverage goals such as:
  - time trends
  - plant/zone/region breakdowns
  - KPI family diversity
  - direct KPI columns preferred over derived substitutes when trusted

Expected result:
- default dashboards consistently contain the operational views users expect

### Phase 37.8: Observability
- add logs for:
  - LLM metric proposal inputs and outputs
  - family alignment decisions
  - chart proposal decisions
  - chart rejection reasons
  - dashboard composition decisions

Expected result:
- semantically explainable dashboard generation

---

## API Impact

No breaking API changes are required.

Behavior changes:
- deployments can produce more than 5 charts by default when confidence is high
- metrics, charts, and dashboards become more context-driven and semantically aligned
- dashboard outputs should include richer KPI coverage for operational domains

Optional future additions:
- dashboard composition debug endpoint
- metric-family debug endpoint

---

## Storage / Artifact Changes

Likely artifact additions:
- metric family metadata
- chart proposal diagnostics
- dashboard composition rationale

Likely persisted metric metadata additions:
- `family_name`
- `family_role`
- `derived_from_metrics`
- `derivation_method`

No legacy migration support is required if only future deployments use the new contract.

---

## Implementation Status

Implemented in this pass:
- Phase 37.1:
  - metric generation remains validation-backed and now flows from the Phase 36 context-text-first metric proposal path before heuristic fallback
- Phase 37.2:
  - added aligned KPI-family derivation for prefixes such as:
    - `total`
    - `normal`
    - `break`
    - `overtime`
  - direct family productivity columns are preferred when present
  - aligned derived productivity metrics are generated only within the same family
- Phase 37.3:
  - family-derived metrics now enter the existing validated metric pipeline with explicit source and lineage-style metadata
- Phase 37.4:
  - added an LLM chart proposal step over validated metrics and available dimensions
  - LLM chart proposals are normalized and validated before merging with deterministic candidates
- Phase 37.5:
  - chart selection now rejects duplicate breakdown/share coverage for the same metric and dimension keys
  - broader breakdown coverage is allowed while suppressing low-value near-duplicates
- Phase 37.6:
  - added an LLM dashboard composition step over chart candidates
  - dashboard composition can now retain a broader chart set instead of collapsing immediately to a narrow top-5
- Phase 37.7:
  - dashboard ranking now preserves broader KPI and breakdown coverage with less aggressive early truncation
- Phase 37.8:
  - added diagnostics for chart proposal and dashboard composition into agent artifacts/logs
  - added a public debug endpoint:
    - `/agentic/debug/proposals?run_id=...`
    - returns metric/chart/dashboard proposal diagnostics and selected artifact summaries

Partially implemented:
- Phase 37.7:
  - dashboard coverage is broader and more KPI-driven now, but coverage quotas are still mostly soft rather than fully policy-driven
- dedicated metric family metadata now persists through a structured `semantic_metadata` field, but downstream policy usage is still not comprehensive across every consumer

Not yet implemented:
- automated tests for the two-table LPG scope covering:
  - aligned KPI family derivation
  - chart proposal breadth
  - dashboard composition coverage

---

## Acceptance Criteria

1. Metric proposal is LLM-first and uses `context_text + schema + profiling`.
2. Direct KPI columns are preferred when they already exist and are semantically strong.
3. Derived productivity metrics are only produced from aligned KPI families.
4. Invalid family combinations are rejected deterministically.
5. Chart proposal is LLM-first over the validated metric set.
6. Default dashboards can produce a broader, high-quality chart set when confidence is high.
7. The two-table LPG scope produces expected outputs such as:
   - total production by day/month
   - total productivity by day/month
   - total production by plant/zone/region
   - total productivity by plant/zone/region
8. Observability clearly explains why metrics, charts, and dashboard slots were chosen.

---

## Test Plan

1. Deploy using only:
   - `lpg_plants`
   - `lpg_plant_operations`

2. Provide business context emphasizing:
   - total production
   - total productivity
   - process date
   - plant / zone / region

3. Verify metric set contains:
   - direct KPI columns if available
   - aligned derived productivity metrics only

4. Verify rejected metrics include any cross-family combinations.

5. Verify chart candidates include:
   - day trends
   - month trends
   - plant/zone/region breakdowns

6. Verify dashboard composition includes more than 5 charts when confidence is high and avoids low-value duplicates.

7. Verify logs show:
   - context metric proposal
   - family alignment
   - chart validation
   - dashboard composition rationale

---

## Review Questions

Before implementation, we should review:
- what the default max dashboard chart count should be under high confidence
- whether direct KPI source columns should always outrank derived variants
- whether chart diversity should be constrained by hard quotas or soft scoring
- how family metadata should be stored in registry rows vs run artifacts

---

## Recommended Implementation Order

1. Phase 37.1: LLM-first metric proposal
2. Phase 37.2: KPI family extraction and alignment
3. Phase 37.3: metric validator upgrade
4. Phase 37.4: LLM-first chart proposal
5. Phase 37.5: chart validator and deduplication
6. Phase 37.6: LLM-first dashboard composition
7. Phase 37.7: dashboard ranking and coverage rules
8. Phase 37.8: observability
