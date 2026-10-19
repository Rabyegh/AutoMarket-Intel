{{
    config(
        materialized='table',
        description='Pricing deviations — each listing compared against its peer-group median asking price.'
    )
}}

/*
  mart_pricing_deviations
  -----------------------
  Joins each individual listing to its peer-group benchmark from
  mart_comparable_prices, and computes the deviation from the median.

  Deviation interpretation:
  - price_vs_median_gbp > 0: listing is priced ABOVE the peer median
  - price_vs_median_gbp < 0: listing is priced BELOW the peer median
  - pct_vs_median > 0: % premium above median
  - pct_vs_median < 0: % discount below median

  Important caveats:
  - These are asking prices, NOT transaction prices.
  - A listing priced above the median is not necessarily overpriced;
    it may differ in trim level, condition, or features not captured here.
  - Listings in small peer groups (is_small_peer_group = True) should be
    interpreted with caution — the benchmark is less reliable.
*/

WITH listings AS (
    SELECT * FROM {{ ref('fct_listing_snapshot') }}
),

benchmarks AS (
    SELECT
        make,
        model,
        registration_year,
        fuel_type,
        transmission,
        median_asking_price_gbp,
        peer_group_size,
        is_small_peer_group
    FROM {{ ref('mart_comparable_prices') }}
)

SELECT
    l.listing_id,
    l.source_file,
    l.make,
    l.model,
    l.registration_year,
    l.fuel_type,
    l.transmission,
    l.engine_size_l,
    l.mileage_miles,
    l.asking_price_gbp,

    b.median_asking_price_gbp                                          AS peer_median_price_gbp,
    b.peer_group_size,
    b.is_small_peer_group,

    l.asking_price_gbp - b.median_asking_price_gbp                     AS price_vs_median_gbp,
    ROUND(
        100.0 * (l.asking_price_gbp - b.median_asking_price_gbp)
        / NULLIF(b.median_asking_price_gbp, 0),
        1
    )                                                                  AS pct_vs_median

FROM listings l
LEFT JOIN benchmarks b
    ON  l.make              = b.make
    AND l.model             = b.model
    AND l.registration_year = b.registration_year
    AND l.fuel_type         = b.fuel_type
    AND l.transmission      = b.transmission
