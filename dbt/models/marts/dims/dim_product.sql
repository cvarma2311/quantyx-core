-- dbt/models/marts/dims/dim_product.sql

WITH products AS (
    SELECT product_name FROM {{ ref('stg_hpcl_sales_daily') }}
    UNION ALL
    SELECT product_name FROM {{ ref('stg_hpcl_monthly_targets') }}
    UNION ALL
    SELECT product_name FROM {{ ref('stg_industry_performance_monthly') }}
)

SELECT DISTINCT
    TRIM(product_name) AS product_name
FROM products
WHERE product_name IS NOT NULL
