# Phase 2: Analytics Marts (HPCL Sales)

This guide documents the exact steps we followed to complete Phase 2 from
`artifacts/implementation_plan.md`, with the rationale for each step.

Goal: create dimension and fact tables on top of staging models so analytics
and downstream services can query a stable, well-modeled layer.

---

## 1) Configure marts materialization

Why: staging models should remain lightweight views, while marts should be
materialized as tables for performance and stability.

Update `dbt/dbt_project.yml`:
```yaml
models:
  quantyx_core_services:
    staging:
      +materialized: view
    marts:
      dims:
        +materialized: table
      facts:
        +materialized: table
```

---

## 2) Create dimension models

Why: dimensions provide clean, reusable lookup tables for consistent joins
across facts and future metrics.

### 2.1 `dim_date`
File: `dbt/models/marts/dims/dim_date.sql`

Built from all date fields in staging:
- `stg_hpcl_sales_daily.sales_date`
- `stg_hpcl_monthly_targets.target_month`
- `stg_industry_performance_monthly.performance_month`

Adds calendar attributes (year, month, day) for time grouping.

### 2.2 `dim_product`
File: `dbt/models/marts/dims/dim_product.sql`

Union distinct product names across all staging tables.

### 2.3 `dim_location`
File: `dbt/models/marts/dims/dim_location.sql`

Union distinct `(sbu_name, zone_name, region_name, sales_area_name)` from
HPCL sales + targets staging.

### 2.4 `dim_company`
File: `dbt/models/marts/dims/dim_company.sql`

Distinct `company_name` (from `comname`) and `psu_pvt` from industry staging.

---

## 3) Create fact models

Why: fact tables hold measures at defined grains and serve as the primary
analytics layer for metrics and dashboards.

### 3.1 `fact_hpcl_sales_daily`
File: `dbt/models/marts/facts/fact_hpcl_sales_daily.sql`

Grain: product × sales area × day.
Uses:
- sales date
- fiscal year / month
- sales metrics (TMT, KG)

### 3.2 `fact_hpcl_sales_monthly_targets`
File: `dbt/models/marts/facts/fact_hpcl_sales_monthly_targets.sql`

Grain: product × sales area × month.
Includes:
- monthly target
- required/current daily run rate
- pending days
- achievement percentage

### 3.3 `fact_industry_performance_monthly`
File: `dbt/models/marts/facts/fact_industry_performance_monthly.sql`

Grain: product × company × state × month.
Includes industry sales in TMT.

### 3.4 `fact_hpcl_sales_monthly_actuals`
File: `dbt/models/marts/facts/fact_hpcl_sales_monthly_actuals.sql`

Grain: product × sales area × month.
Aggregates daily actuals to month level for alignment with target metrics.

---

## 4) Add marts tests

Why: ensure core keys exist and marts are stable for downstream consumption.

File: `dbt/models/marts/schema.yml`

Tests added:
- `not_null` for primary date fields and core keys
- `unique` for `dim_date.date_day` and `dim_product.product_name`

If certain fields are legitimately nullable, remove or relax the tests.

---

## 5) Build and validate marts

Why: confirm models compile, build, and tests pass against real data.

From the `dbt/` directory:
```bash
# Build dims and facts
dbt run --select dim_date dim_product dim_location dim_company \
  fact_hpcl_sales_daily fact_hpcl_sales_monthly_targets fact_industry_performance_monthly

# Run marts tests
dbt test --select dim_date dim_product dim_location dim_company \
  fact_hpcl_sales_daily fact_hpcl_sales_monthly_targets fact_industry_performance_monthly
```

If dbt still references old schemas (after model changes):
```bash
dbt clean
```

---

## 6) Common issues we handled

- `zone_name` missing in targets: we added `Zone_Name` and `Region_Name` to
  `stg_hpcl_monthly_targets` because marts depend on those columns.
- Stale schema errors: resolved by rebuilding the staging model first and
  running `dbt clean` when needed.

---

## 7) What Phase 2 completes

You now have:
- Dimension tables for date, product, location, and company
- Fact tables for HPCL daily sales, monthly targets, and industry performance
- Verified tests for key columns

Next: Phase 3 (Metric Core).
