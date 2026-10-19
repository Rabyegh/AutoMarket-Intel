{{
    config(
        materialized='table',
        description='Quarantined records with rejection reasons — for data quality observability.'
    )
}}

/*
  stg_rejected_listings
  ----------------------
  All records that failed validation during ingestion.
  Useful for understanding data-quality issues in the source files.
  NOT used in any analytical mart.
*/

SELECT
    row_id,
    source_file,
    make,
    TRIM(model)         AS model,
    year,
    price_gbp,
    transmission,
    mileage_miles,
    fuel_type,
    engine_size_l,
    rejection_reason
FROM {{ source('raw', 'raw_quarantine') }}
