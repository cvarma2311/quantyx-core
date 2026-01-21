# Helios Ops Intelligence — Post-MVP Roadmap (No MindsDB)

This roadmap extends the MVP into planning, forecasting, anomaly detection, and optimization
**without using MindsDB**. Everything is built as first-party modules around Postgres + dbt.

---

## 0) MVP Baseline (Assumed Complete)

MVP delivers:
- Postgres as source of truth (raw tables remain untouched)
- dbt staging (`stg_*`) + marts (`fact_*`, `dim_*`) built in Postgres
- Small governed metric core (10–15 metrics)
- AI Q&A: NL → metric resolver → safe SQL → results
- Lightweight inference (period comparisons + top drivers)
- Rules-based actions written to `insight_events`
- Dashboard + Ask-the-Data panel

Post-MVP goal:
- Add **predictive + prescriptive** layers incrementally, safely, and explainably.

---

## Phase 7 — Observability, Performance, and Reliability Hardening

### Goals
- Make the system stable under real usage
- Make AI answers auditable and reproducible
- Improve query performance on marts

### Key Deliverables
1. Query logging tables
   - `query_audit`: question, resolved metrics, SQL hash, execution time, rowcount
2. Safety guardrails improvements
   - enforced time window
   - enforced LIMIT
   - denylist patterns (cross join, unbounded scans)
3. Performance tuning
   - indexes on high-usage marts
   - materialized views for heavy joins (optional)
4. Release discipline
   - versioned prompt templates
   - versioned metric definitions

### Outcome
Auditable, fast, repeatable analytics and AI Q&A.

---

## Phase 8 — First-Party Forecasting (No MindsDB)

### Goal
Generate operational forecasts from marts and store them in Postgres as first-class data.

### What We Build
1. Forecast worker (scheduled job)
   - runs daily/hourly depending on needs
2. Forecast models (start simple, iterate)
   - baseline: moving average / exponential smoothing (ETS)
   - step-up: SARIMAX / ARIMA (statsmodels)
   - optional: Prophet (business-friendly seasonality)
3. Forecast storage
   - `forecast_results` table

### Suggested Tables
- `forecast_results`
  - `forecast_id`, `entity_type`, `entity_id`, `metric_key`
  - `ds` (date), `yhat`, `yhat_lower`, `yhat_upper`
  - `model_name`, `model_version`, `trained_at`, `data_window`

### Outcome
You can answer:
- “What will Tenali RO sales look like next week?”
- “Where is stockout risk likely to rise?”

---

## Phase 9 — First-Party Anomaly Detection (No MindsDB)

### Goal
Detect unusual behavior (loss spikes, delay spikes, sales dips) and turn it into events.

### What We Build
1. Anomaly worker (scheduled job)
2. Detection methods (start robust)
   - rolling z-score on residuals
   - IQR outlier detection
   - seasonal baseline + deviation thresholds
3. Persist anomalies as events
   - write to `insight_events` with type = `anomaly`

### Output Pattern
- anomaly detected → “what changed” + “where” + “confidence” + supporting stats
- link anomaly to affected entity (RO, depot, route, lorry)

### Outcome
Exceptions become automatic inputs to operations.

---

## Phase 10 — Scenario Planning (Mini-Kinaxis Without Kinaxis)

### Goal
Support “what-if” planning by storing assumptions and recomputing impacts.

### What We Build
1. Scenario model
   - baseline + named scenarios
2. Scenario inputs
   - demand multiplier by region/product
   - capacity changes by depot
   - lead time changes
   - fleet availability changes
3. Scenario outputs
   - projected inventory cover
   - projected service levels
   - projected delays

### Tables
- `scenario`
  - `scenario_id`, `name`, `description`, `status`, `created_by`, `created_at`
- `scenario_inputs`
  - `scenario_id`, `entity_type`, `entity_id`, `parameter`, `value`
- `scenario_outputs`
  - `scenario_id`, `metric_key`, `entity_type`, `entity_id`, `ds`, `value`, `computed_at`

### Outcome
You can answer:
- “If depot capacity drops 15%, where do we see stockouts?”
- “If we shift 2 tankers to Tenali cluster, what improves and what worsens?”

---

## Phase 11 — Optimization (Mini-OMP Without OMP)

### Goal
Add prescriptive optimization for 1–2 high-ROI problems using open-source solvers.

### Tools
- OR-Tools (routing/assignment)
- Pyomo (linear/integer programming)

### Start With One Optimization Problem
Pick ONE:
1. Fleet-to-route assignment
   - objective: minimize cost + SLA penalties
   - constraints: lorry capacity, delivery windows, driver hours
2. Replenishment allocation
   - objective: minimize stockout risk + transport cost
   - constraints: depot throughput, safety stock, lead times

### Outputs
- recommended assignments / schedules
- cost vs SLA trade-off
- constraint violations when infeasible
- stored as a plan artifact

### Tables
- `optimization_run`
- `optimization_input_snapshot`
- `optimization_output_plan`

### Outcome
You can answer:
- “What is the lowest-cost plan that meets service targets?”
- “Which constraints are binding and causing delays?”

---

## Phase 12 — Closed-Loop Learning

### Goal
Track whether actions worked and learn over time.

### What We Build
1. Action acceptance tracking
   - `action_feedback` table: accepted/rejected, reason, timestamp
2. Impact measurement
   - post-action KPI comparison window
3. Threshold tuning suggestions
   - propose new thresholds based on historical false positives/negatives

### Outcome
The system becomes smarter about what actions actually help.

---

## Phase 13 — Governance & Enterprise Readiness

### Goal
Be audit-ready and customer-ready.

### Deliverables
- RBAC and column masking (where needed)
- audit trails for AI answers and data used
- explainability logs + citations to facts (SQL query IDs)
- metric versioning and deprecation flow

### Outcome
Trust + defensibility for enterprise customers.

---

## Phase 14 — Productization

### Goal
Make it sellable.

### Deliverables
- multi-tenancy (schema-per-tenant or row-level)
- onboarding automation (db introspection + dbt bootstrap)
- configuration-driven metric packs by domain
- usage metering and rate limiting
- packaging (Docker images + deploy scripts)

### Outcome
Helios becomes a commercial product, not just an internal tool.

---

## Guiding Rule

Do not jump phases:
- analytics before forecasting
- forecasting before scenarios
- scenarios before optimization
- optimization before automation

Build explainable and auditable at every step.

---

## Immediate Next Steps (Post-MVP)
- [ ] Create `forecast_results` + implement first forecast worker (ETS baseline)
- [ ] Create `anomaly_events` (or use `insight_events`) + implement anomaly worker
- [ ] Add scenario tables + baseline scenario computation
- [ ] Choose 1 optimization problem + implement OR-Tools prototype
