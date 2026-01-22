-- dbt/models/staging/stg_hpcl_monthly_targets.sql

WITH source_data AS (
    SELECT
        fiscal_year AS fiscal_year,
        month_name AS month_name,
        year_monthname AS year_monthname,
        "ProductName" AS product_name,
        "SalesArea_Name" AS sales_area_name,
        "SBU_Name" AS sbu_name,
        "Zone_Name" AS zone_name,
        "Region_Name" AS region_name,
        "TARGET_QTY_TMT" AS target_qty_tmt,
        "Rate_Per_Day_Required_MMT" AS rate_per_day_required_mmt,
        "Rate_per_day_current_MMT" AS rate_per_day_current_mmt,
        "Pending_Days" AS pending_days,
        "Act_Tgt_Achievement" AS act_tgt_achievement
    FROM {{ source('hpcl_raw_data', 'M60_LEVEL_METADATA') }}
),

renamed_casted AS (
    SELECT
        regexp_replace(fiscal_year, '[^0-9-]', '', 'g') AS fiscal_year,
        month_name,
        year_monthname,
        product_name,
        sales_area_name,
        sbu_name,
        zone_name,
        region_name,
        CAST(target_qty_tmt AS NUMERIC(18, 2)) AS target_qty_tmt,
        CAST(rate_per_day_required_mmt AS NUMERIC(18, 2)) AS rate_per_day_required_mmt,
        CAST(rate_per_day_current_mmt AS NUMERIC(18, 2)) AS rate_per_day_current_mmt,
        CAST(pending_days AS INT) AS pending_days,
        CAST(act_tgt_achievement AS NUMERIC(5, 2)) AS act_tgt_achievement,
        -- year_monthname is already a timestamp (e.g., "June 2024")
        year_monthname::DATE AS target_month
    FROM source_data
    WHERE sbu_name IS NOT NULL
      AND sbu_name != '0'
      AND sbu_name NOT IN (
            'Common',
            'Mumbai Ref',
            'Renewable Energy',
            'Visakh Ref'
          )
      AND zone_name IS DISTINCT FROM '-'
)

SELECT * FROM renamed_casted
