-- dbt/models/marts/dims/dim_location.sql

WITH locations AS (
    SELECT sbu_name, zone_name, region_name, sales_area_name
    FROM {{ ref('stg_hpcl_sales_daily') }}

    UNION ALL

    SELECT sbu_name, zone_name, region_name, sales_area_name
    FROM {{ ref('stg_hpcl_monthly_targets') }}
)

SELECT DISTINCT
    sbu_name,
    zone_name,
    region_name,
    sales_area_name
FROM locations
WHERE sbu_name IS NOT NULL
