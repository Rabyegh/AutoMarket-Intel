{{
    config(
        materialized='table',
        description='Inventory composition summary by make, model year, fuel type, and transmission.'
    )
}}

/*
  mart_inventory_summary
  ----------------------
  Aggregated inventory counts and price statistics by vehicle segment.
  Useful for answering "how is the observed inventory composed?" questions.

  Note: "inventory" here means the listings present in the static source
  snapshot. It does NOT represent live market inventory or change over time.
  Use the simulated_snapshots table for time-series demonstration.
*/

SELECT
    make,
    model,
    registration_year,
    fuel_type,
    transmission,

    COUNT(*)                                                              AS listing_count,
    ROUND(MEDIAN(asking_price_gbp))                                       AS median_asking_price_gbp,
    ROUND(AVG(asking_price_gbp))                                          AS avg_asking_price_gbp,
    MIN(asking_price_gbp)                                                 AS min_asking_price_gbp,
    MAX(asking_price_gbp)                                                 AS max_asking_price_gbp,
    ROUND(AVG(mileage_miles))                                             AS avg_mileage_miles,
    ROUND(AVG(CASE WHEN mpg IS NOT NULL THEN mpg END), 1)                 AS avg_mpg,
    ROUND(AVG(CASE WHEN annual_tax_gbp IS NOT NULL THEN annual_tax_gbp END)) AS avg_annual_tax_gbp,

    -- Pct of total listings this segment represents
    ROUND(
        100.0 * COUNT(*) / SUM(COUNT(*)) OVER (),
        2
    )                                                                     AS pct_of_total_listings

FROM {{ ref('fct_listing_snapshot') }}
GROUP BY make, model, registration_year, fuel_type, transmission
ORDER BY listing_count DESC
