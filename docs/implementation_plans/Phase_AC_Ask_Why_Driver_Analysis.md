# Phase AC: Ask "Why" / Driver Analysis (NL → Root Cause)

Goal: extend Ask to answer **why/driver** questions end-to-end by running a
deterministic driver analysis pipeline on top of the semantic bindings defined
in Phase AB. This phase covers NL intent detection, driver decomposition,
baseline selection, and response contracts.

This is a continuation of Phase AB ("What" questions). It reuses the same
Ask API contract: **only `tenant_id` + `question`**.

---

## 1) Driver Question Examples

- "Why are sales down last week at Secunderabad BAY?"
- "What are the top drivers of sales in Secunderabad?"
- "Which products caused the drop in MS sales last month?"
- "Why did market share fall in Q2?"

---

## 2) Architecture Overview (Why/Driver Pipeline)

### 2.1 Pipeline stages
1) **Scope resolution**
   - Same as Phase AB (tenant → domain, scope defaults).

2) **NL preprocessing**
   - Detect intent = `why` or `driver`.
   - Normalize time phrases (e.g., "last week").
   - Extract target entity/location/value.

3) **Semantic parsing + binding**
   - Resolve metric(s), dimensions, entities, hierarchies (Phase AB rules).
   - Bind to dataset or flow node registry (Phase AA).

4) **Baseline selection**
   - If time range provided, select a comparison period:
     - prior period of equal length (default)
     - or explicit compare if question specifies (e.g., "vs last year")

5) **Driver dimension selection**
   - Use configured `driver_dimensions` for the metric (preferred).
   - Else infer from ontology + dataset columns:
     - product, channel, customer, region, time, etc.

6) **Driver decomposition**
   - Compute contribution by each driver dimension.
   - Return top N contributors and share/delta.

7) **Explain + response**
   - Return "why" explanation, driver list, and optional SQL.

---

## 2.2 LLM Usage (When Needed)
Use LLMs as a bounded assistive layer for:
- intent detection if keyword rules are insufficient
- driver dimension inference when no config is present
- candidate filtering for ambiguous entities/locations

LLM calls must return ranked candidates + confidence. If below threshold,
Ask returns an ambiguity error instead of guessing.

---

## 2.3 Low-Level Data + API Map (Why/Driver)

### 2.3.1 Inputs reused from Phase AB
Tables:
- `public.quantyx_metrics_registry` (metric definitions + metadata)
- `public.quantyx_entity_overrides` (scoped entity mappings)
- `public.quantyx_hierarchy_overrides` (scoped hierarchies)
- `public.quantyx_glossary_terms` (synonyms + abbreviations)
- `public.quantyx_flow_node_data_registry` (derived metric binding)
- `public.quantyx_context_scope_active` (active context selection, Phase AD)

APIs that populate:
- `/metrics`, `/metrics/suggested`, `/contracts/apply`
- `/context/ingest`, `/context/extract`, `/context/apply`
- `/onboard/map`, `/entities`, `/hierarchies`

### 2.3.2 Driver config inputs
Table/fields:
- `public.quantyx_metrics_registry.metadata.driver_dimensions`
- `public.quantyx_metrics_registry.metadata.default_time_grain`
- `public.quantyx_metrics_registry.metadata.default_compare`

### 2.3.3 Driver analysis outputs
Table (optional persistence):
- `public.quantyx_insight_events` (Phase F)
  - `insight_type`, `payload`, `created_at`

API:
- `/query` (Ask) returns driver response

---

## 3) Required Additions

### 3.1 Metric config (driver dimensions)
Extend metric registry to include:
```json
{
  "driver_dimensions": ["product_name", "channel", "customer_segment"],
  "default_time_grain": "week",
  "default_compare": "previous_period"
}
```

### 3.2 Driver analysis operator
Proposed module: `services/ai/driver_analysis.py`

Inputs:
- metric
- scope (tenant/domain/connection)
- time_range
- compare_range
- driver_dimensions[]
- filters

Outputs:
- driver list with contributions and deltas
- optional SQL (one query per driver or a combined query)

---

## 4) Example Walkthrough (Why Question)

Question:
> "Why are sales down last week at Secunderabad BAY?"

Assumptions:
- Today = 2026-02-19
- "last week" = 2026-02-09 to 2026-02-15
- baseline = 2026-02-02 to 2026-02-08

Step-by-step:
1) **Resolve scope**
   - Resolve tenant → domain + default scope.
2) **Detect intent**
   - `why` intent triggers driver analysis.
3) **Semantic binding**
   - metric = `total_sales_volume_tmt`
   - filter = `sales_area_name = "Secunderabad BAY"`
4) **Baseline**
   - compare to previous week.
5) **Driver dimension set**
   - use metric config: `[product_name, channel, customer_segment]`
6) **Driver computation**
   - compute delta by driver dimension
   - rank top negative contributors
7) **Response**
   - return ranked drivers + deltas + explanation

---

## 5) Response Contract (Why/Driver)

```json
{
  "metrics": ["total_sales_volume_tmt"],
  "dimensions": ["product_name"],
  "rows": [
    {"product_name": "Product A", "delta": -120.5, "share": 0.32},
    {"product_name": "Product B", "delta": -75.1, "share": 0.20}
  ],
  "explain": {
    "intent": "driver_analysis",
    "baseline": {"start": "2026-02-02", "end": "2026-02-08"},
    "current": {"start": "2026-02-09", "end": "2026-02-15"},
    "driver_dimensions": ["product_name", "channel", "customer_segment"]
  }
}
```

---

## 6) Acceptance Criteria

- Ask detects `why/driver` intent and routes to driver analysis.
- Baselines are deterministic and explainable.
- Driver dimensions are configurable per metric.
- Derived metrics use Phase AA registry bindings.
- Ask returns ranked drivers with deltas and explanation.

---

## 7) Open Questions

Sample driver questions to validate:
- "Why are sales down last week at Secunderabad BAY?"
- "What are the top drivers of sales in Secunderabad?"
- "Which products caused the drop in MS sales last month?"
- "Why did market share fall in Q2?"

Data model question:
- Multiple hierarchies per context are addressed in
  `docs/implementation_plans/Phase_AD_Multi_Context_Multi_Hierarchy.md`.
