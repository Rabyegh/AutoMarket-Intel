# Architecture

## Overview

AutoMarket Intel is a local-first batch pipeline that:
1. Reads UK used-car listing CSVs from `data/raw/used_cars/`
2. Normalises, validates, and loads them into DuckDB (`data/warehouse.duckdb`)
3. Runs dbt transformations to produce analytical marts
4. Exposes a CLI for ingestion, reporting, and optional simulation

## Component Diagram

```
data/raw/used_cars/
       │  (11 CSV files, static snapshot)
       ▼
src/automarket/ingestion/
  discovery.py     — find CSV files, map column names
  normalize.py     — pure normalization functions (no I/O)
  validation.py    — field-level validation with rejection reasons
  pipeline.py      — orchestrates: read → normalize → validate → load
       │
       ▼
DuckDB: data/warehouse.duckdb
  raw schema:
    raw_used_car_listings  (108,539 rows)
    raw_quarantine         (1 row — year=2060 anomaly in ford.csv)
       │
       ▼
dbt/models/
  staging/
    stg_used_car_listings  (view) — typed, normalised, vehicle_key added
    stg_rejected_listings  (table) — quarantine observability
  core/
    dim_vehicle            (table) — unique vehicle configurations
    fct_listing_snapshot   (table) — one row per listing
  marts/
    mart_comparable_prices   (table) — price benchmarks by peer group
    mart_pricing_deviations  (table) — each listing vs. peer median
    mart_inventory_summary   (table) — inventory counts by segment
```

## Key Design Decisions

### No VINs
The source dataset contains no VINs. The `vehicle_key` is a deterministic
SHA-256 surrogate derived from: `make + model + year + fuel_type + transmission + engine_size_l`.

### Asking prices, not transaction prices
Every mart column that refers to price uses `asking_price_gbp` or
`price_gbp` — never "sale price" or "transaction price".

### Idempotent ingestion
The pipeline deletes existing rows for each `source_file` before inserting,
so running it multiple times produces the same result.

### Deterministic row IDs
`row_id` is a 16-char SHA-256 hex hash of `source_file + row_index + model + year + price + mileage`.
Running ingestion on unchanged files produces the same row IDs.

### Schema layout in DuckDB
- Python writes to the `raw` schema
- dbt staging reads from `raw` and writes to `staging`
- dbt core reads from `staging` and writes to `core`
- dbt marts read from `core` and write to `marts`

### Static snapshot limitation
The dataset is a single static export. There are no listing publication dates.
The simulation component generates synthetic snapshots for demonstration purposes
only — all simulated rows have `is_simulated = True`.

## Source File Schema Variants

| Variant | Files | Columns | Notes |
|---|---|---|---|
| Schema A | audi, bmw, ford, hyundi, merc, skoda, toyota, vauxhall, vw | 9 | Full columns |
| Schema B | cclass, focus | 7 | No tax or mpg — NULLs in output |
| Excluded | unclean cclass, unclean focus | 11 | Raw scrape; not ingested |
