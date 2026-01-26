# Quantyx v2 Product Prerequisites

This document defines a repeatable onboarding model that works for any enterprise
(energy, manufacturing, logistics, retail) and aligns with the dbt + contracts +
Tellius-fused architecture.

The intent is to keep the architecture generic and productized, while allowing
industry-specific ontologies as a prerequisite input.

---

## 1) Product prerequisites (non-negotiable)

Before onboarding any new enterprise, the product must already include these
capabilities.

### A) Industry pack prerequisite (new)

Each industry must have a minimal pack before onboarding. The pack provides:
- Ontology (entities, hierarchies, canonical terms)
- Dataset templates (governed business views)
- Metric archetypes (domain-safe templates)
- Policies (guardrails, exclusions)

This is the only domain-specific input required. The core platform remains
unchanged across industries.

### B) Canonical operational ontology (product-level)

The platform must already understand a baseline, cross-industry ontology:
- Organizational units (plant, region, depot)
- Assets (line, vehicle, machine)
- Products (SKU, grade)
- Time (day, month, fiscal period)

Location:
- `contracts/ontology/core.yml`

Example:
```yaml
entity_types:
  organizational_unit:
    examples: [plant, region, sales_area]
  asset:
    examples: [production_line, vehicle]
  product:
    examples: [sku, grade]
```

### C) Measure classification system

The product must interpret numeric columns via built-in rules.

Pattern | Interpreted as
--- | ---
`*_qty`, `*_units` | quantity
`*_tmt`, `*_tons` | volume
`*_hours` | time
`*_amount`, `*_cost` | money
`*_count` | count

This is product logic, not customer config.

### D) Standard metric template library

Ship metric archetypes (not customer KPIs):
- actual
- change vs previous period
- cumulative (YTD)
- utilization
- achievement vs target
- variance contribution

### E) dbt as a hard prerequisite

The product assumes:
- clean grains
- explicit joins
- time dimensions
- additive measures

If a customer refuses dbt-level modeling, onboarding should fail gracefully.

---

## 2) Auto metric detection and correction (product behavior)

The platform must auto-detect candidate metrics and allow human correction.

- Auto-generated metrics start as `suggested`
- Users can edit SQL logic, rename, and certify
- Users can create new metrics manually
- Every change is audited

This balances automation and trust.

---

## 3) How metrics are automatically derived (actual flow)

### Step 1: Schema introspection (automatic)

System inspects:
- table names
- column names
- data types
- row counts
- cardinality
- null rates

Example output:
```json
{
  "table": "fact_production_daily",
  "numeric_columns": ["output_units", "downtime_hours"],
  "categorical_columns": ["plant_id", "line_id"],
  "time_columns": ["production_date"]
}
```

### Step 2: Measure detection (automatic)

From numeric columns, derive candidate measures:
```json
{
  "measure": "output_units",
  "physical_quantity": "quantity",
  "additive": true,
  "unit": "units"
}
```

Rules applied:
- numeric + high cardinality → measure
- name pattern → unit inference
- aggregation safety → additive vs semi-additive

### Step 3: Entity and grain detection (semi-automatic)

Detect:
- primary grain (date + org unit)
- entity candidates (plant_id, region_id)

Map to ontology types:
```json
{
  "column": "plant_id",
  "mapped_entity_type": "organizational_unit",
  "confidence": 0.92
}
```

If confidence < threshold, ask the user to confirm.

### Step 4: Time semantics detection (automatic + confirm)

Detect:
- date column
- grain (day/month)
- fiscal calendar hints (FY, fiscal_year)

Example:
```yaml
time:
  primary_grain: day
  calendar: fiscal
  fiscal_year_start: April
```

### Step 5: dbt bootstrap (automatic)

Generate:
- staging models
- dimension tables
- fact tables at clean grain

Metrics are never derived from raw tables.

### Step 6: Baseline metric generation (automatic)

For each additive measure, create baseline metrics:
```yaml
metrics:
  - actual_output_units
  - output_units_mom_change
  - output_units_yoy_change
  - output_units_ytd
```

These are correct, boring, and universally useful.

### Step 7: Target and capacity detection (conditional)

If schema includes `target_*`, `planned_*`, or `capacity_*`, generate:

Metric | Formula
--- | ---
achievement_pct | actual / target
gap | target - actual
utilization_pct | actual / capacity

### Step 8: Intent binding (automatic)

Bind metrics to question intents:

Intent | Metric / Operator
--- | ---
performance | actual_output_units
risk | achievement_pct
why | variance + driver analysis

This enables questions like “Why is production down?” without hand-built KPIs.

### Step 9: Suggested metrics (human-in-the-loop)

Auto-generated metrics start as:
```
certified: false
visibility: suggested
```

UI shows:
- suggested metrics
- confidence score
- editable names/descriptions

Human actions:
- certify
- rename
- hide

---

## 4) What the product should not require

- Writing SQL
- Designing KPIs upfront
- Deep business logic on day one
- Building dashboards before asking questions

---

## 5) What the product must require from the customer

Required:
- Clean dbt facts and dims
- Clear time column
- Stable primary grain
- One owner per domain

Optional (but powerful):
- Targets / plans
- Capacity limits
- Peer group labels

---

## 6) Why this works at enterprise scale

- Ontology is yours, not theirs
- Metrics are generated, not invented
- Humans validate, not build
- Baseline anchors trust
- Everything is explainable

This mirrors how Tellius scales and how you evolve toward Kinaxis/OMP.

---

## TL;DR

How metrics are derived:
```
Measures → Ontology → Templates → Baseline metrics → Derived KPIs → Intent binding
```

Product prerequisites:
- Industry pack prerequisite
- Canonical ontology
- Measure classification rules
- Metric archetypes
- dbt enforcement
- Suggested vs certified workflow
