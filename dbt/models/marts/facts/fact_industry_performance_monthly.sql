-- dbt/models/marts/facts/fact_industry_performance_monthly.sql

SELECT
    performance_month,
    fiscal_year,
    month_name,
    company_name,
    psu_pvt,
    product_name,
    state_name,
    industry_sales_tmt
FROM {{ ref('stg_industry_performance_monthly') }}
