# quantyx-core-services Ops Intelligence (MVP)

AI-native Operations Intelligence platform built on Postgres.
Designed to explain *what is happening, why it is happening, and what to do next* —
starting small and evolving into a full product.

---

## 1. Vision

quantyx-core-services Ops Intelligence is an AI-first analytics layer that sits on top of operational
databases (initially Postgres) and provides:

- Trusted analytics tables (facts & dimensions)
- A small, governed core of metrics
- Natural-language Q&A over operational data
- Root-cause analysis and actionable recommendations

This repository focuses on **building the foundation correctly**, not on replicating
every feature of tools like Denodo, Kinaxis, or OMP.

---

## 2. Guiding Principles

- **Raw data is sacred** – never mutate it
- **Small metric core** – define only what matters
- **AI derives the rest** – humans approve what becomes official
- **Explainability over black boxes**
- **Build once, reuse everywhere** (dashboards, AI, planners)

---

## 3. High-Level Architecture

Postgres (raw tables)
↓ dbt
Postgres (analytics schema: stg_, fact_, dim_*)
↓
Metric Catalog (YAML / table)
↓
AI Query & Insight Engine (read-only, guarded)
↓
Dashboards + Ask-the-Data UI


Optional later:
- Planning / scenario tools
- Optimization solvers
- External data sources (SAP, IoT, GPS)

---

## 4. Repository Structure

.
├── dbt/
│ ├── models/
│ │ ├── sources.yml
│ │ ├── staging/
│ │ │ ├── stg_deliveries.sql
│ │ │ ├── stg_trips.sql
│ │ │ └── schema.yml
│ │ └── marts/
│ │ ├── facts/
│ │ │ ├── fact_deliveries.sql
│ │ │ ├── fact_trips.sql
│ │ └── dims/
│ │ ├── dim_ro.sql
│ │ ├── dim_depot.sql
│ │ └── schema.yml
│ └── dbt_project.yml
│
├── contracts/
│ ├── metrics/
│ │ └── core_metrics.yml
│ └── prompts/
│ ├── metric_discovery.txt
│ ├── sql_generation.txt
│ └── explanation.txt
│
├── services/
│ ├── api/
│ │ └── main.py
│ ├── ai/
│ │ ├── metric_resolver.py
│ │ ├── sql_guard.py
│ │ ├── inference.py
│ │ └── actions.py
│ └── worker/
│ └── scheduler.py
│
├── ui/
│ ├── dashboard/
│ └── console/
│
├── infra/
│ └── docker/
│
└── docs/
├── roadmap.md
├── decisions.md
└── runbook.md


---

## 5. Development Phases

---

### Phase 1 — Data Foundation (Week 1)

#### Goal
Create clean, trustworthy analytics tables from raw Postgres data.

#### Steps
1. Identify the ~10 raw tables
2. Confirm:
   - Primary keys
   - Time columns
   - Join keys
3. Initialize dbt project
4. Declare all raw tables in `sources.yml`
5. Create `stg_*` models:
   - Explicit column selection
   - Type casting
   - Timestamp normalization
   - Status standardization
6. Add dbt tests:
   - `not_null`, `unique`
   - `accepted_values` for enums

#### Outcome
- Clean, predictable staging layer
- Raw data untouched
- Lineage documented

---

### Phase 2 — Analytics Marts (Week 1–2)

#### Goal
Create a minimal but powerful analytics surface.

#### Core Facts
- `fact_deliveries`
- `fact_trips`
- `fact_inventory_daily` (optional)

#### Core Dimensions
- `dim_retail_outlet`
- `dim_depot`
- `dim_product`
- `dim_lorry`

#### Rules
- Staging models → views
- Facts & dims → tables or incremental tables
- Facts must include:
  - clear grain
  - time column
  - foreign keys to dimensions

#### Outcome
- Dashboards and AI query marts, not raw tables
- Performance is predictable

---

### Phase 3 — Metric Core (Week 2)

#### Goal
Define **truth once**, reuse everywhere.

#### What to do
Create a small metric catalog (10–15 metrics only).

#### Example starter metrics
- daily_sales_volume
- on_time_delivery_pct
- avg_delivery_delay_minutes
- stockout_events_count
- inventory_days_of_cover
- loss_variance_pct
- lorry_utilization_pct
- failed_delivery_rate

#### Metric rules
Each metric must define:
- Grain (RO/day, depot/week, etc.)
- Allowed dimensions
- Business meaning
- Owner
- Status (`draft`, `approved`)

#### Outcome
- Stable numbers
- No KPI drift
- AI has anchors

---

### Phase 4 — AI Query Engine (Week 3)

#### Goal
Answer business questions safely using metrics + marts.

#### Core capabilities
1. Schema introspection (dbt docs / Postgres metadata)
2. Metric resolution:
   - Prefer approved metrics
   - Propose new ones if missing
3. SQL generation with guardrails:
   - Read-only
   - LIMIT enforced
   - Timeout enforced
   - Block dangerous joins
4. Query execution
5. Result formatting

#### Output contract
Every answer returns:
- Result
- Explanation (what changed, where)
- Drivers (ranked)
- Recommended actions
- SQL used (optional, for trust)

---

### Phase 5 — Inference & Actions (Week 3–4)

#### Inference (lightweight)
- Period-over-period comparisons
- Contribution analysis
- Simple anomaly detection (z-score / IQR)
- Confidence scoring

#### Action engine (rules-first)
Examples:
- If on_time_delivery_pct < 95% for 3 days → escalate depot ops
- If inventory_days_of_cover < 2 → expedite replenishment
- If loss_variance_pct spikes → investigate lorry/site

Persist actions in:
- `insight_events` table

---

### Phase 6 — UI & Adoption (Week 4)

#### Dashboards
- Executive overview
- Operations / exceptions

#### Ask-the-Data UI
- Single NL input
- Tabular output
- Explanation + recommended action
- Optional SQL toggle

---

## 6. Guardrails (Non-Negotiable)

- All AI queries are read-only
- Time window always required
- LIMIT always required
- Log:
  - user question
  - resolved metrics
  - SQL
  - runtime
- Prefer marts over raw tables
- No auto-publishing of metrics without approval

---

## 7. Definition of Done (MVP)

The MVP is successful when the system can reliably answer:

- Why is sales down at a specific retail outlet?
- Which depots are driving delivery delays?
- Where is stockout risk increasing?
- Which lorries are underutilized?
- Where is loss variance abnormal and recurring?

With:
- Clear explanation
- Supporting data
- Actionable recommendation

---

## 8. Future Roadmap (Product Direction)

- Multi-source ingestion (SAP, GPS, IoT)
- Semantic layer expansion (MetricFlow-like)
- Scenario simulation (Kinaxis-style)
- Optimization solvers (OMP-style)
- Role-based governance
- Multi-tenant onboarding

---

## 9. Philosophy

> Raw data gives flexibility  
> Metrics give trust  
> AI gives speed  
> Humans give judgment

Build slowly, correctly, and visibly.

---

## 10. Immediate Next Steps

- [ ] List raw tables + PKs + time columns
- [ ] Initialize dbt and sources.yml
- [ ] Create `stg_*` models + tests
- [ ] Build first two facts and core dims
- [ ] Define first 10 metrics
- [ ] Build AI query service with guardrails
- [ ] Add first dashboard and Ask-the-Data UI
