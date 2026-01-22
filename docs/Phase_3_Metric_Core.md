# Phase 3: Metric Core (HPCL Sales)

This guide documents the exact steps we followed to complete Phase 3 from
`artifacts/implementation_plan.md`, with the rationale for each step.

Goal: define a small, governed catalog of core metrics that reference the
marts layer from Phase 2. These metrics become the single source of truth
for analytics, AI Q&A, and dashboards.

---

## 1) Create the metric catalog

Why: a central metric catalog prevents KPI drift and ensures every team uses
consistent definitions and logic.

File created:
- `contracts/metrics/core_metrics.yml`

This file includes:
- Domain metadata (name, description)
- Canonical dimensions used for slicing
- Metrics defined over marts facts

---

## 2) Dimensions defined

Why: metrics should explicitly declare which dimensions are safe to use, to
avoid invalid joins or ambiguous logic.

Dimensions in the catalog include:
- Date: `date_day`, `month_name`, `fiscal_year`, `calendar_quarter`
- Location: `sbu_name`, `zone_name`, `region_name`, `sales_area_name`
- Product: `product_name`
- Industry: `state_name`, `company_name`, `psu_pvt`

Each dimension is mapped to a marts column via `sql`.

---

## 3) Core metrics defined

Why: keep the metric core small (10–15) and focused on the MVP business
questions: actual vs target, pace, and industry comparisons.

Metrics added:
- `total_sales_volume_tmt`
- `total_sales_volume_kg`
- `target_sales_tmt`
- `sales_vs_target_achievement_pct`
- `required_run_rate_mmt`
- `current_run_rate_mmt`
- `pending_days`
- `industry_sales_tmt`
- `market_share_pct`
- `hpcl_vs_company_sales_diff_tmt`
- `hpcl_vs_company_sales_ratio`

Each metric includes:
- Description
- Aggregation type (sum/average/ratio)
- SQL expression referencing marts tables
- Grain (day/month)
- Allowed dimensions

---

## 4) Notes and guardrails

- All metrics are based on marts tables, not raw sources.
- Mandatory SBU exclusions are already enforced upstream in staging.
- The achievement metric uses a monthly rollup of actuals to ensure grain
  alignment with targets (`fact_hpcl_sales_monthly_actuals`).
- If you add new metrics, follow the same pattern: clear description,
  explicit grain, explicit dimension list, and SQL only from marts.

---

## 5) Sample business questions → metrics

Use these mappings to validate the catalog:

- "How am I performing vs target by region this month?"
  - Metrics: `sales_vs_target_achievement_pct`
  - Dimensions: `region_name`, `month_name`, `fiscal_year`

- "What is the current run-rate vs required run-rate for Tenali?"
  - Metrics: `current_run_rate_mmt`, `required_run_rate_mmt`
  - Dimensions: `sales_area_name`, `month_name`, `fiscal_year`

- "How are we performing vs industry for MS in UP?"
  - Metrics: `market_share_pct`, `industry_sales_tmt`
  - Dimensions: `product_name`, `state_name`, `month_name`, `fiscal_year`

- "How is HPCL doing vs BPCL for MS this quarter?"
  - Metrics: `industry_sales_tmt`, `hpcl_vs_company_sales_diff_tmt`, `hpcl_vs_company_sales_ratio`
  - Dimensions: `product_name`, `calendar_quarter`, `fiscal_year`, `company_name`

---

## 6) Query templates

Use these templates when the user asks for HPCL vs a competitor. They ensure
the competitor side does not accidentally include all non-HPCL companies.

### 6.1 HPCL vs competitor (month)

Filters:
- `company_name IN ('HPCL', '<COMPETITOR>')`
- `product_name = '<PRODUCT>'`
- `month_name = '<MONTH>'`
- `fiscal_year = '<FY>'`
- optional `state_name = '<STATE>'`

Metrics:
- `industry_sales_tmt`
- `hpcl_vs_company_sales_diff_tmt`
- `hpcl_vs_company_sales_ratio`

Group by:
- `company_name`

### 6.2 HPCL vs competitor (quarter)

Filters:
- `company_name IN ('HPCL', '<COMPETITOR>')`
- `product_name = '<PRODUCT>'`
- `calendar_quarter = <Q>`
- `fiscal_year = '<FY>'`
- optional `state_name = '<STATE>'`

Metrics:
- `industry_sales_tmt`
- `hpcl_vs_company_sales_diff_tmt`
- `hpcl_vs_company_sales_ratio`

Group by:
- `company_name`

---

## 7) Next steps

- Confirm canonical company naming for HPCL (used in `market_share_pct`).

Next: Phase 4 (AI Query Engine).
