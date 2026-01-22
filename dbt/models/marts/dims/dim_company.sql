-- dbt/models/marts/dims/dim_company.sql

SELECT DISTINCT
    company_name,
    psu_pvt
FROM {{ ref('stg_industry_performance_monthly') }}
WHERE company_name IS NOT NULL
