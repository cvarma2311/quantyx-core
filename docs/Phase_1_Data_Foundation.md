# Phase 1: Data Foundation (HPCL Sales)

This guide documents the exact steps we followed to complete Phase 1 from
`artifacts/implementation_plan.md`, with the rationale for each step.

Goal: create clean, trustworthy staging models in dbt for HPCL sales, targets,
and industry performance, and validate them with tests.

---

## 1) Configure dbt sources (database + schema)

Why: dbt sources must point at the actual raw tables in the correct database
and schema. If these are wrong, model runs will fail with missing relations.

Update `dbt/models/sources.yml`:
- `database: hpcl_ceg`
- `schema: public`
- Industry table name is lowercase: `industry_performance`

---

## 2) Set local dbt profile and environment variables

Why: dbt connects using `~/.dbt/profiles.yml`. Keeping credentials outside
repo files avoids committing secrets while enabling local development.

Update `~/.dbt/profiles.yml` with your actual connection:
```yaml
quantyx_core_services:
  outputs:
    dev:
      type: postgres
      host: <DB_HOST>
      port: 5432
      user: <DB_USER>
      password: <DB_PASSWORD>
      dbname: <DB_NAME>
      schema: public
      threads: 1
  target: dev
```

Optional `.env` for local tooling (do not commit secrets):
```env
DB_HOST=<DB_HOST>
DB_PORT=5432
DB_NAME=<DB_NAME>
DB_USER=<DB_USER>
DB_PASSWORD=<DB_PASSWORD>
DB_SCHEMA=public
```

---

## 3) Remove example dbt models

Why: the default dbt example models (`my_first_dbt_model`,
`my_second_dbt_model`) are not part of the HPCL domain and their tests fail
if the tables do not exist.

Command:
```bash
rm -rf dbt/models/example
```

---

## 4) Align staging models with actual raw columns

Why: the raw tables use column names that differ from the initial live
models (e.g., `SBU_Name` vs `SBU`). Mismatched columns cause model failures.
The official column definitions are in `artifacts/HPCL- Sales Schema and Parameters.pdf`.

Key mappings:

### 4.1 `stg_hpcl_sales_daily.sql`
Source table: `public."MOM_DAY_LEVEL_DATA"`

- `SBU_Name` -> `sbu_name`
- `Zone_Name` -> `zone_name`
- `Region_Name` -> `region_name`
- `SalesArea_Name` -> `sales_area_name`
- `ProductName` -> `product_name`
- `fiscal_year` (text) -> `fiscal_year`
- `month_name` -> `month_name`
- `DAY_ID` (date) -> `sales_date`
- `day_of_month` derived from `DAY_ID`

Mandatory filter (per PDF):
```sql
WHERE sbu_name IS NOT NULL
  AND sbu_name != '0'
  AND sbu_name NOT IN ('Common','Mumbai Ref','Renewable Energy','Visakh Ref')
```

### 4.2 `stg_hpcl_monthly_targets.sql`
Source table: `public."M60_LEVEL_METADATA"`

- `SBU_Name` -> `sbu_name`
- `SalesArea_Name` -> `sales_area_name`
- `ProductName` -> `product_name`
- `month_name` -> `month_name`
- `fiscal_year` (text) -> `fiscal_year`
- `year_monthname` (timestamp) -> `target_month`
- `TARGET_QTY_TMT` -> `target_qty_tmt`
- `Rate_Per_Day_Required_MMT` -> `rate_per_day_required_mmt`
- `Rate_per_day_current_MMT` -> `rate_per_day_current_mmt`
- `Pending_Days` -> `pending_days`
- `Act_Tgt_Achievement` -> `act_tgt_achievement`

Same mandatory SBU filter applies here.

### 4.3 `stg_industry_performance_monthly.sql`
Source table: `public.industry_performance`

Columns used:
- `company_name`, `psu_pvt`, `productname`, `statename`, `month_name`,
  `fiscal_year`, `netweight_tmt`

Because `fiscal_year` is like `2024-2025` and `month_name` is abbreviated
(e.g., `APR`), we normalize and compute `performance_month`:
- For Apr-Dec: use the first year in `fiscal_year`
- For Jan-Mar: use the second year in `fiscal_year`

---

## 5) Add staging tests

Why: tests give fast feedback on data quality and alert you when raw data
violates expectations.

File: `dbt/models/staging/schema.yml`

Initial tests added:
- `not_null` on core dimensions and dates.
- We relaxed tests for columns that are legitimately nullable in raw data
  (e.g., `zone_name`, `product_name` in `stg_hpcl_sales_daily`).

If more columns are nullable in practice, remove their `not_null` tests.

---

## 6) Run dbt models and tests

Why: validate that models compile, run, and tests pass against the real data.

From the `dbt/` directory:
```bash
# Build staging models only
DBT_PROFILES_DIR=~/.dbt dbt run --select stg_hpcl_sales_daily stg_hpcl_monthly_targets stg_industry_performance_monthly

# Run tests only on staging
DBT_PROFILES_DIR=~/.dbt dbt test --select stg_hpcl_sales_daily stg_hpcl_monthly_targets stg_industry_performance_monthly
```

If dbt still runs stale tests:
```bash
dbt clean
```

---

## 7) Troubleshooting

- Missing relation errors usually mean the model did not run yet; run `dbt run` first.
- Column errors mean the raw schema does not match the model; update column mappings.
- If `performance_month` is null for `industry_performance`, confirm that
  `month_name` uses 3-letter abbreviations and `fiscal_year` follows `YYYY-YYYY`.

---

## 8) What Phase 1 completes

You now have:
- dbt sources pointing to real raw tables
- Staging models for sales, targets, and industry performance
- Guardrail filters applied (mandatory SBU exclusions)
- Staging tests with appropriate null expectations

Next: Phase 2 (marts: dims and facts).
