# Quantyx Core Services - Architecture v2
## Tellius-Fused, dbt-First Decision Intelligence Platform

This document defines Version 2 of the Quantyx architecture. It is built to
support productization, multi-domain onboarding, and Tellius-style decision
intelligence while remaining:

- dbt-first
- configuration-driven
- explainable
- scalable to Kinaxis/OMP-level planning

This is a platform architecture, not a customer-specific implementation.

---

## 1) Architectural principles

1. Contracts over code
   - Business meaning lives in YAML contracts, not Python logic.
2. dbt owns data truth
   - Joins, transformations, and correlations happen in dbt.
   - dbt manifests are generated automatically during onboarding (Phase O), stored in Postgres, and never require UI input.
3. AI reasons over semantics, not tables
   - The AI engine does not read raw schemas directly.
4. Explainability before optimization
   - Every answer is traceable to metrics, datasets, and queries.
5. Industry packs, not custom code
   - Domains are configurations, not forks.
6. Incremental path to planning
   - Analytics → Explain → Predict → Scenario → Optimize.

---

## 2) High-level system view

```
┌──────────────────────────────┐
│ Client / UI                  │
│ (Ask, Explore, Act)          │
└──────────────┬───────────────┘
               │
┌──────────────▼───────────────┐
│ API Layer                    │
│ (FastAPI, contracts only)    │
└──────────────┬───────────────┘
               │
┌──────────────▼───────────────┐
│ AI Decision Engine           │
│ (Resolve → Explain → Rank)   │
└──────────────┬───────────────┘
               │
┌──────────────▼───────────────┐
│ Semantic and Dataset Layer   │
│ (Metrics, Entities, Policies)│
└──────────────┬───────────────┘
               │
┌──────────────▼───────────────┐
│ Data Source Layer            │
│ (Postgres, Snowflake, etc.)  │
└──────────────┬───────────────┘
               │
┌──────────────▼───────────────┐
│ dbt                          │
│ (Facts, Dims, Wide Tables)   │
└──────────────────────────────┘
```

Automated dbt (Phase O):
- Connection scan triggers `dbt compile` in the backend.
- Manifests are stored in `public.quantyx_dbt_manifest` for schema and lineage reads.
- Per-tenant dbt config is resolved from `quantyx_dbt_config` or server defaults.

---

## 3) Repository structure (v2)

```
services/
├── api/
│   ├── main.py
│   ├── schemas.py
│   └── dependencies.py
│
├── ai/
│   ├── engine.py
│   │
│   ├── data_source/
│   │   ├── base.py
│   │   ├── postgres.py
│   │   └── factory.py
│   │
│   ├── semantic_layer/
│   │   ├── loaders/
│   │   │   ├── dataset_loader.py
│   │   │   ├── metric_loader.py
│   │   │   ├── entity_loader.py
│   │   │   └── policy_loader.py
│   │   │
│   │   ├── models.py
│   │   ├── catalog.py
│   │   └── lineage.py
│   │
│   ├── query_builder/
│   │   ├── resolver.py
│   │   ├── planner.py
│   │   └── sql_generator.py
│   │
│   ├── inference_engine/
│   │   ├── base.py
│   │   ├── variance_analysis.py
│   │   ├── driver_analysis.py
│   │   ├── anomaly_scan.py
│   │   ├── peer_comparison.py
│   │   └── pace_analysis.py
│   │
│   └── insight_ranking/
│       ├── scorer.py
│       └── prioritizer.py
│
contracts/
├── datasets/
├── metrics/
├── entities/
├── policies/
├── ontology/
│
dbt/
├── models/
│   ├── staging/
│   ├── marts/
│   └── intermediate/
│
tools/
└── generate.py
```

---

## 4) Industry packs (productization boundary)

An industry pack provides the minimum domain knowledge required for onboarding.
It is the only domain-specific input required to keep the core platform generic.

Each pack contains:
- Ontology (entities, hierarchies, canonical concepts)
- Dataset templates (curated views over dbt models)
- Metric archetypes (domain-safe metric templates)
- Policies (guardrails, exclusions, time windows)
- Dashboard presets (optional)

This enables consistent onboarding across industries without custom code.

---

## 5) Dataset layer (Tellius “Dataset” equivalent)

Datasets represent curated, governed business views over dbt models.

Example dataset contract (`contracts/datasets/*.yml`):
```yaml
name: sales_area_performance
domain: energy_distribution
source_model: fact_sales_area_performance

default_filters:
  - column: sbu_name
    operator: not_in
    values: ["Common", "Mumbai Ref"]

refresh_policy:
  type: daily
  owner: data_eng

certified: true
```

Why this matters:
- Separates physical dbt models from business-safe objects
- Enables browsing, ownership, certification (Tellius-style)

---

## 6) Semantic layer (business view)

### 6.1 Metrics (`contracts/metrics/*.yml`)
```yaml
name: sales_vs_target_achievement_pct
domain: energy_distribution
dataset: sales_area_performance

type: ratio
sql: actual_sales / target_sales

grain: sales_area, month
unit: percent
certified: true
owner: sales_ops
status: certified
```

### 6.2 Entities (`contracts/entities/*.yml`)
```yaml
name: sales_area
hierarchy:
  - zone
  - region
  - sales_area

join_key: sales_area_id
```

### 6.3 Policies (`contracts/policies/*.yml`)
```yaml
name: sbu_exclusion
applies_to: all
filter:
  column: sbu_name
  operator: not_in
  values: ["Common", "Mumbai Ref"]
```

---

## 7) Metric lifecycle (governance)

Metrics progress through a lifecycle to keep auto-generation safe:

- suggested → draft → certified → deprecated

Auto-generated metrics always start as **suggested**. Users can:
- edit SQL logic
- rename or re-describe
- certify or hide

This preserves automation while keeping human oversight.

---

## 8) Query resolution flow (Tellius-like)

User asks:
- “Why is production down in Plant A?”

Resolver:
- Identifies metric(s)
- Identifies entity scope
- Resolves dataset(s)

Planner:
- Builds query plan
- Selects safe joins (via entity graph)
- Chooses inference operators

SQL Generator:
- Enforces policies
- Adds time windows and limits
- Generates read-only SQL

Execution:
- Queries curated dbt marts only

---

## 9) Inference engine (Tellius “AI Insights” equivalent)

Insight operators (pluggable). All operators implement:

```python
class InsightOperator:
    def run(self, query_result, context) -> InsightResult
```

Built-in operators:
- Variance analysis (what changed)
- Driver analysis (why)
- Peer comparison
- Pace / target risk
- Anomaly scan

Standard insight output:
```json
{
  "insight_type": "driver_analysis",
  "headline": "Sales drop driven by Product X",
  "confidence": 0.82,
  "drivers": [...],
  "recommended_actions": [...]
}
```

---

## 10) Insight ranking and guidance

Insights are scored and ranked using:
- impact magnitude
- confidence
- business criticality
- policy severity

Top insights are returned to UI and optionally persisted to `insight_events`.

---

## 11) Cross-domain correlation (dbt-first)

Rule: dbt connects data; the semantic layer explains meaning.

- Cross-domain joins happen only in dbt
- Semantic layer references unified facts
- AI never invents joins

This guarantees correctness and scale.

---

## 12) Path to Kinaxis / OMP-level capability

Stage | Capability
--- | ---
v2 | Ask, Explain, Benchmark
v3 | Trend and anomaly operators
v4 | Scenario simulation
v5 | Constraint-based optimization
v6 | Closed-loop learning

The architecture does not change; only operators expand.

---

## 13) Why this matches the Tellius route

Tellius Concept | Quantyx v2 Equivalent
--- | ---
Data Module | DataSource + Dataset Layer
Business View | Semantic Contracts
Conversational Analytics | Resolver + Planner
AI Insights | Inference Engine
Guided Exploration | Insight Ranking
Workflows | insight_events

---

## 14) Final positioning

Quantyx is a decision intelligence platform that turns governed data into
explainable insights, scenarios, and decisions without black-box planning.

This is not BI. This is a productizable decision engine.

---

## End state

- HPCL is a domain pack
- IFFCO is a domain pack
- Logistics is a domain pack
- The core stays unchanged

---

### If you want next

1. Create sample industry packs (energy, manufacturing, logistics)
2. Write a product overview for external audiences
3. Define the Query IR schema for LLM reliability
4. Define v3/v4 operators (scenario and optimization)
