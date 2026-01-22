-- dbt/models/staging/stg_hpcl_sales_daily.sql

WITH source_data AS (
    SELECT
        "SBU_Name" AS sbu_name,
        "Zone_Name" AS zone_name,
        "Region_Name" AS region_name,
        "SalesArea_Name" AS sales_area_name,
        "ProductName" AS product_name,
        fiscal_year AS fiscal_year,
        month_name AS month_name,
        "DAY_ID" AS day_id,
        "NETWEIGHT_TMT" AS netweight_tmt,
        "NETWEIGHT_KG" AS netweight_kg
    FROM {{ source('hpcl_raw_data', 'MOM_DAY_LEVEL_DATA') }}
),

renamed_casted AS (
    SELECT
        sbu_name,
        zone_name,
        region_name,
        sales_area_name,
        product_name,
        regexp_replace(fiscal_year, '[^0-9-]', '', 'g') AS fiscal_year,
        month_name,
        EXTRACT(DAY FROM day_id)::INT AS day_of_month,
        CAST(netweight_tmt AS NUMERIC(18, 2)) AS sales_tmt,
        CAST(netweight_kg AS NUMERIC(18, 2)) AS sales_kg,
        day_id::DATE AS sales_date
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
