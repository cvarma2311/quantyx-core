# quantyx-core-services: Phased Implementation Plan (MVP)

## Introduction

This document provides a detailed, step-by-step implementation plan to build the `quantyx-core-services` Ops Intelligence platform. The plan is structured in phases, following the high-level outline in `MVP.md`.

The initial focus is on the **HPCL Sales Performance & Industry Comparison** use case, as described in `docs/MVP_HPCL_SALES_AND_INDUSTRY.md`. However, the architecture and processes are designed to be generic and scalable to other domains and use cases.

---

## Phase 1: Data Foundation (HPCL Sales)

**Goal:** Create clean, trustworthy, and tested analytics base tables from the raw HPCL source data using dbt.

### Step 1.1: Initialize dbt Project & Sources

1.  **Initialize dbt Project:** A dbt project named `quantyx_core_services` should already be initialized from the prerequisites setup.
2.  **Define Sources:** In `dbt/models/sources.yml`, declare the three raw HPCL tables:
    -   `MOM_DAY_LEVEL_DATA` (actual sales)
    -   `M60_LEVEL_METADATA` (targets)
    -   `INDUSTRY_PERFORMANCE` (industry data)
    For each source, define the table name and add descriptions.

### Step 1.2: Create Staging Models

Create a `stg_*.sql` model for each source table in `dbt/models/staging/`.

1.  **`stg_hpcl_sales_daily.sql`** (from `MOM_DAY_LEVEL_DATA`):
    -   Select and rename columns for clarity (e.g., `NETWEIGHT_TMT` -> `sales_tmt`).
    -   Apply the **mandatory SBU filter** as defined in the use case document.
    -   Cast data types (e.g., dates, numbers).
    -   Normalize timestamps if necessary.

2.  **`stg_hpcl_monthly_targets.sql`** (from `M60_LEVEL_METADATA`):
    -   Select and rename columns (e.g., `TARGET_QTY_TMT` -> `target_tmt`).
    -   Also apply the SBU filter.
    -   Cast data types.

3.  **`stg_industry_performance_monthly.sql`** (from `INDUSTRY_PERFORMANCE`):
    -   Select and rename columns.
    -   Cast data types.
    -   Standardize company names if needed (e.g., 'HPCL' vs 'HINDUSTAN PETROLEUM CORPORATION LTD').

### Step 1.3: Add dbt Tests

-   For all staging models, add `not_null` and `unique` tests on primary keys.
-   Add `accepted_values` tests for columns with known enumerations (e.g., `SBU_Name`).
-   Add relationship tests to ensure join keys between the tables are valid.

---

## Phase 2: Analytics Marts (HPCL Sales)

**Goal:** Create a performant and intuitive analytics layer of fact and dimension tables.

### Step 2.1: Create Dimension Models

Create dimension tables in `dbt/models/marts/dims/`.

1.  **`dim_date.sql`**: A comprehensive date dimension, built from the dates in the source data. Should include fiscal year, month, day, day of week, etc.
2.  **`dim_product.sql`**: A dimension for all products, created by taking the distinct products from the source tables.
3.  **`dim_location.sql`**: A dimension for the sales hierarchy (SBU, Zone, Region, Sales Area).
4.  **`dim_company.sql`**: A dimension for company names from the industry data.

### Step 2.2: Create Fact Models

Create fact tables in `dbt/models/marts/facts/`.

1.  **`fact_hpcl_sales_daily.sql`**:
    -   **Grain:** One row per Product per Sales Area per Day.
    -   **Columns:**
        -   Foreign keys to `dim_date`, `dim_product`, `dim_location`.
        -   Measures: `sales_tmt`, `sales_kg`.
    -   **Logic:** Joins `stg_hpcl_sales_daily` with the dimension tables.

2.  **`fact_hpcl_sales_monthly_targets.sql`**:
    -   **Grain:** One row per Product per Sales Area per Month.
    -   **Columns:**
        -   Foreign keys to `dim_date` (at month level), `dim_product`, `dim_location`.
        -   Measures: `target_tmt`, `rate_per_day_required`, `rate_per_day_current`.
    -   **Logic:** Joins `stg_hpcl_monthly_targets` with the dimension tables.

3.  **`fact_industry_performance_monthly.sql`**:
    -   **Grain:** One row per Product per State per Company per Month.
    -   **Columns:**
        -   Foreign keys to `dim_date` (at month level), `dim_product`, `dim_company`.
        -   Measures: `industry_sales_tmt`.
    -   **Logic:** Joins `stg_industry_performance_monthly` with the dimension tables.

---

## Phase 3: Metric Core (HPCL Sales)

**Goal:** Define a governed, reusable set of core metrics in a central catalog.

### Step 3.1: Create Metric Catalog

Create a YAML file `contracts/metrics/core_metrics.yml` to define the metrics.

**Example Metrics:**
-   **`total_sales_volume`**:
    -   **Business Meaning:** Total sales quantity in TMT.
    -   **Calculation:** `SUM(sales_tmt)` from `fact_hpcl_sales_daily`.
    -   **Grain:** Day, Product, Location.
-   **`sales_vs_target_achievement_pct`**:
    -   **Business Meaning:** Percentage of sales target achieved.
    -   **Calculation:** `SUM(sales_tmt) / SUM(target_tmt)`.
    -   **Grain:** Month, Product, Location.
-   **`required_run_rate`**:
    -   **Business Meaning:** The daily sales rate required to meet the monthly target.
    -   **Calculation:** Average of `rate_per_day_required`.
    -   **Grain:** Month, Product, Location.
-   **`market_share_pct`**:
    -   **Business Meaning:** HPCL's share of total industry sales for a given product and state.
    -   **Calculation:** `(HPCL Sales) / (Total Industry Sales)`.
    -   **Grain:** Month, Product, State.
-   **`hpcl_growth_vs_industry_growth_pct`**:
    -   **Business Meaning:** Comparison of HPCL's sales growth to the overall industry growth.
    -   **Calculation:** `(HPCL Growth %) - (Industry Growth %)`.
    -   **Grain:** Month, Product, State.

---

## Phase 4: AI Query Engine (HPCL Sales)

**Goal:** Build the Python-based service that can answer natural language questions using the dbt models and metric catalog.

1.  **Setup FastAPI Service:** Create the main API application in `services/api/main.py`.
2.  **Schema Introspection:** Write a module that can connect to the Postgres database and read the schema of the dbt-generated `fact_*` and `dim_*` tables.
3.  **Metric Resolver:** Implement `services/ai/metric_resolver.py`. This service will parse an incoming natural language question, identify the core metric(s) needed from `core_metrics.yml`, and determine the required dimensions and filters.
4.  **SQL Guard & Generation:** Implement `services/ai/sql_guard.py`. This is a critical component that will:
    -   Generate a safe, read-only SQL query based on the resolved metric and dimensions.
    -   **Enforce the mandatory SBU filter** at the query level as a final safeguard.
    -   Enforce `LIMIT` and timeouts on all queries.
5.  **Query Execution:** Write a module to execute the generated SQL against the Postgres database.

---

## Phase 5: Inference & Actions (HPCL Sales)

**Goal:** Go beyond simple Q&A to provide proactive insights and recommendations.

1.  **Contribution Analysis:** Implement logic to answer "Why is sales down?". This involves breaking down the main metric (e.g., `sales_vs_target_achievement_pct`) by different dimensions (product, region, etc.) to find the biggest contributors to the decline.
2.  **Pace Analysis:** Implement a service to compare `current_run_rate` vs `required_run_rate` and flag areas at risk of missing their targets.
3.  **Action Engine:** Create a simple rules-based engine in `services/ai/actions.py`.
    -   **Rule 1:** If a Sales Area's `sales_vs_target_achievement_pct` is below a certain threshold by mid-month, generate an "At Risk" insight.
    -   **Rule 2:** If HPCL's market share for a key product drops for two consecutive months, generate an "Investigate Market Share" insight.
4.  **Persist Insights:** Store the generated insights in an `insight_events` table in Postgres.

---

## Phase 6: UI & Adoption (HPCL Sales)

**Goal:** Build a simple and effective user interface for business users to consume the insights.

1.  **Executive Dashboard:** Create a high-level dashboard showing overall sales vs target, pace, and key KPIs.
2.  **Drilldown Dashboard:** Build a dashboard that allows users to drill down from SBU to Zone, Region, and Sales Area to investigate performance.
3.  **Ask-the-Data UI:** Create a simple single-page web application with a text box where users can type their questions. The UI will display the tabular results, the explanation, and the recommended action returned by the API.

---

## Scaling to Other Domains

This implementation plan is designed for scalability. To onboard a new domain (e.g., Logistics, Manufacturing):

1.  **Phase 1 (Data):**
    -   Define the new raw data sources in `sources.yml`.
    -   Create new staging models with the specific business logic and filters for that domain.
2.  **Phase 2 (Marts):**
    -   Create new fact and dimension tables relevant to the new domain.
3.  **Phase 3 (Metrics):**
    -   Define a new set of core metrics for the new domain in `core_metrics.yml` (or a new file).
4.  **Phases 4-6 (AI & UI):**
    -   The core AI query engine, inference logic, and UI components are designed to be generic. They will automatically adapt to the new tables and metrics, requiring minimal changes. The main effort will be in defining new dashboards and potential new inference rules.
