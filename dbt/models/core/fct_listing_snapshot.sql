{{
    config(
        materialized='table',
        description='Fact table of individual used-car listing records with vehicle_key FK.'
    )
}}

/*
  fct_listing_snapshot
  ----------------------
  One row per source listing record (from stg_used_car_listings) joined
  to the vehicle dimension.

  Limitation: This dataset is a single static snapshot. The name
  "snapshot" is aspirational — it reflects the intended architecture for
  repeated observations. In the current dataset, each row represents one
  observed listing from one source file; there are no repeated timestamps.

  Do NOT treat rows with the same vehicle_key from different source_files
  as separate time-series observations — the source files may overlap.
*/

SELECT
    l.row_id                         AS listing_id,
    l.source_file,
    l.vehicle_key,
    l.make,
    l.model,
    l.registration_year,
    l.fuel_type,
    l.transmission,
    l.engine_size_l,
    l.asking_price_gbp,
    l.mileage_miles,
    l.annual_tax_gbp,
    l.mpg,

    -- Age of vehicle at time of snapshot (using 2024 as reference — no real dates)
    (2024 - l.registration_year)     AS vehicle_age_years

FROM {{ ref('stg_used_car_listings') }} l
