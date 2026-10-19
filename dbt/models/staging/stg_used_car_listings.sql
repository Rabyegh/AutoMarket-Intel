{{
    config(
        materialized='view',
        description='Typed and standardised used-car listing records from the raw layer.'
    )
}}

/*
  stg_used_car_listings
  ---------------------
  Staging model: applies final typing, strips leading whitespace still present
  after Python normalization, and adds a vehicle_key surrogate for joining.

  Limitations:
  - This dataset is a static snapshot; observation_date is absent.
  - price_gbp is an asking price, NOT a transaction price.
  - No deduplication is applied at this stage because the source files have
    overlapping models (e.g. cclass.csv and merc.csv both contain C-Class).
    Deduplication intent must be documented explicitly if required downstream.
*/

SELECT
    row_id,
    source_file,
    make,
    TRIM(model)                                   AS model,
    year                                          AS registration_year,
    price_gbp                                     AS asking_price_gbp,
    transmission,
    mileage_miles,
    fuel_type,
    tax_gbp                                       AS annual_tax_gbp,
    mpg,
    engine_size_l,

    -- Surrogate vehicle dimension key (no VINs in this dataset)
    {{ dbt_utils.generate_surrogate_key(['make', 'model', 'year', 'fuel_type', 'transmission', 'engine_size_l']) }}
                                                  AS vehicle_key

FROM {{ source('raw', 'raw_used_car_listings') }}
