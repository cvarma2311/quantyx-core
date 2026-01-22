-- dbt/models/marts/dims/dim_date.sql

WITH date_spine AS (
    SELECT sales_date AS date_day, fiscal_year, month_name
    FROM {{ ref('stg_hpcl_sales_daily') }}
    WHERE sales_date IS NOT NULL

    UNION ALL

    SELECT target_month AS date_day, fiscal_year, month_name
    FROM {{ ref('stg_hpcl_monthly_targets') }}
    WHERE target_month IS NOT NULL

    UNION ALL

    SELECT performance_month AS date_day, fiscal_year, month_name
    FROM {{ ref('stg_industry_performance_monthly') }}
    WHERE performance_month IS NOT NULL
),

normalized AS (
    SELECT
        date_day::DATE AS date_day,
        MAX(fiscal_year) AS fiscal_year,
        MAX(INITCAP(TRIM(month_name))) AS month_name
    FROM date_spine
    GROUP BY date_day
)

SELECT
    date_day,
    fiscal_year,
    month_name,
    EXTRACT(YEAR FROM date_day)::INT AS calendar_year,
    EXTRACT(MONTH FROM date_day)::INT AS calendar_month,
    EXTRACT(DAY FROM date_day)::INT AS day_of_month,
    TO_CHAR(date_day, 'DY') AS day_name
FROM normalized
