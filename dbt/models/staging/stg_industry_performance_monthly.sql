-- dbt/models/staging/stg_industry_performance_monthly.sql

WITH source_data AS (
    SELECT
        comname AS company_name,
        psu_pvt AS psu_pvt,
        productname AS product_name,
        statename AS state_name,
        month_name AS month_name,
        fiscal_year AS fiscal_year,
        netweight_tmt AS netweight_tmt
    FROM {{ source('hpcl_raw_data', 'industry_performance') }}
),

normalized AS (
    SELECT
        company_name,
        psu_pvt,
        product_name,
        state_name,
        month_name,
        regexp_replace(fiscal_year, '[^0-9-]', '', 'g') AS fiscal_year_clean,
        netweight_tmt
    FROM source_data
    WHERE company_name IS NOT NULL -- Assuming company_name is a key identifier
),

renamed_casted AS (
    SELECT
        company_name,
        psu_pvt,
        product_name,
        state_name,
        month_name,
        fiscal_year_clean AS fiscal_year,
        CAST(netweight_tmt AS NUMERIC(18, 2)) AS industry_sales_tmt,
        CASE
            WHEN fiscal_year_clean IS NULL OR fiscal_year_clean = '' THEN NULL
            WHEN upper(month_name) IN ('JAN', 'FEB', 'MAR')
                THEN split_part(fiscal_year_clean, '-', 2)
            ELSE split_part(fiscal_year_clean, '-', 1)
        END AS year_for_month
    FROM normalized
)

SELECT
    company_name,
    psu_pvt,
    product_name,
    state_name,
    month_name,
    fiscal_year,
    industry_sales_tmt,
    CASE
        WHEN year_for_month IS NULL OR year_for_month = '' THEN NULL
        ELSE TO_DATE(CONCAT(year_for_month, '-', INITCAP(month_name), '-01'), 'YYYY-Mon-DD')
    END AS performance_month
FROM renamed_casted
