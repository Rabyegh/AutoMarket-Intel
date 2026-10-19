{{
    config(
        materialized='table',
        description='Vehicle dimension — unique vehicle configurations observed across all listings.'
    )
}}

/*
  dim_vehicle
  -----------
  One row per unique combination of make, model, registration_year,
  fuel_type, transmission, and engine_size_l.

  Surrogate key: vehicle_key (SHA-256 hash of the above attributes).

  Limitations:
  - No VINs are present in the source dataset.
  - This key can collide for different trim levels or variant editions
    of the same model year, since those attributes are not in the source.
  - first_seen_price and last_seen_price are derived from source-file
    ordering, NOT from real listing timestamps.
*/

WITH deduped AS (
    SELECT
        vehicle_key,
        make,
        model,
        registration_year,
        fuel_type,
        transmission,
        engine_size_l,
        COUNT(*)                             AS listing_count,
        ROUND(AVG(asking_price_gbp))         AS avg_asking_price_gbp,
        MIN(asking_price_gbp)                AS min_asking_price_gbp,
        MAX(asking_price_gbp)                AS max_asking_price_gbp,
        ROUND(AVG(mileage_miles))            AS avg_mileage_miles,
        AVG(mpg)                             AS avg_mpg,
        AVG(annual_tax_gbp)                  AS avg_annual_tax_gbp
    FROM {{ ref('stg_used_car_listings') }}
    GROUP BY
        vehicle_key, make, model, registration_year,
        fuel_type, transmission, engine_size_l
)

SELECT * FROM deduped
