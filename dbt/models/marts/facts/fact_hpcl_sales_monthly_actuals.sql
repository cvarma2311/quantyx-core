-- dbt/models/marts/facts/fact_hpcl_sales_monthly_actuals.sql

WITH base AS (
    SELECT
        sales_date,
        fiscal_year,
        month_name,
        sbu_name,
        zone_name,
        region_name,
        sales_area_name,
        product_name,
        sales_tmt,
        sales_kg
    FROM {{ ref('fact_hpcl_sales_daily') }}
)

SELECT
    DATE_TRUNC('month', sales_date)::DATE AS month_start,
    fiscal_year,
    month_name,
    sbu_name,
    zone_name,
    region_name,
    sales_area_name,
    product_name,
    SUM(sales_tmt) AS sales_tmt,
    SUM(sales_kg) AS sales_kg
FROM base
WHERE sales_date IS NOT NULL
GROUP BY
    DATE_TRUNC('month', sales_date)::DATE,
    fiscal_year,
    month_name,
    sbu_name,
    zone_name,
    region_name,
    sales_area_name,
    product_name
