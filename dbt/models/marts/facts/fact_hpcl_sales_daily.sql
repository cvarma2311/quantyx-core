-- dbt/models/marts/facts/fact_hpcl_sales_daily.sql

SELECT
    sales_date,
    fiscal_year,
    month_name,
    day_of_month,
    sbu_name,
    zone_name,
    region_name,
    sales_area_name,
    product_name,
    sales_tmt,
    sales_kg
FROM {{ ref('stg_hpcl_sales_daily') }}
