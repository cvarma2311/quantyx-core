-- dbt/models/marts/facts/fact_hpcl_sales_monthly_targets.sql

SELECT
    target_month,
    fiscal_year,
    month_name,
    sbu_name,
    zone_name,
    region_name,
    sales_area_name,
    product_name,
    target_qty_tmt,
    rate_per_day_required_mmt,
    rate_per_day_current_mmt,
    pending_days,
    act_tgt_achievement
FROM {{ ref('stg_hpcl_monthly_targets') }}
