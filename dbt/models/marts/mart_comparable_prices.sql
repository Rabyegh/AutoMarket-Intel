{{
    config(
        materialized='table',
        description='Asking-price benchmarks grouped by make, model, registration year, fuel type, and transmission.'
    )
}}

/*
  mart_comparable_prices
  ----------------------
  Provides asking-price statistics for groups of similar vehicles.

  Peer group definition:
    make + model + registration_year + fuel_type + transmission

  Engine size is intentionally excluded from the peer group because it is
  often missing and would fragment groups too aggressively. Analysts who
  need engine-specific benchmarks can filter this mart by engine_size_l.

  Statistics:
  - median_price: robust central tendency (preferred over mean for skewed pricing)
  - avg_price: arithmetic mean (can be skewed by outliers)
  - p25_price / p75_price: interquartile range
  - price_range: max - min (useful for detecting wide spreads)

  Limitation: These are ASKING prices, not transaction prices.
  Small peer groups (n < 5) are flagged — treat their statistics with caution.

  Min peer-group threshold: configurable via var('min_peer_group_size', 5).
*/

WITH listings AS (
    SELECT
        make,
        model,
        registration_year,
        fuel_type,
        transmission,
        engine_size_l,
        asking_price_gbp,
        mileage_miles
    FROM {{ ref('fct_listing_snapshot') }}
),

benchmarks AS (
    SELECT
        make,
        model,
        registration_year,
        fuel_type,
        transmission,

        COUNT(*)                                                            AS peer_group_size,
        ROUND(MEDIAN(asking_price_gbp))                                     AS median_asking_price_gbp,
        ROUND(AVG(asking_price_gbp))                                        AS avg_asking_price_gbp,
        ROUND(PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY asking_price_gbp)) AS p25_asking_price_gbp,
        ROUND(PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY asking_price_gbp)) AS p75_asking_price_gbp,
        MIN(asking_price_gbp)                                               AS min_asking_price_gbp,
        MAX(asking_price_gbp)                                               AS max_asking_price_gbp,
        MAX(asking_price_gbp) - MIN(asking_price_gbp)                       AS price_range_gbp,
        ROUND(AVG(mileage_miles))                                           AS avg_mileage_miles,
        peer_group_size < {{ var('min_peer_group_size', 5) }}               AS is_small_peer_group

    FROM listings
    GROUP BY make, model, registration_year, fuel_type, transmission
)

SELECT * FROM benchmarks
ORDER BY make, model, registration_year
