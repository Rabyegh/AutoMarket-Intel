# AutoMarket Intel — Used-Car Pricing & Inventory Intelligence

A local-first data engineering platform that ingests UK used-car listing data,
validates and normalises it, loads it into DuckDB, and builds analytical marts
for pricing benchmarks, pricing deviations, and inventory composition.

[![CI](https://github.com/Rabyegh/AutoMarket-Intel/actions/workflows/ci.yml/badge.svg)](https://github.com/Rabyegh/AutoMarket-Intel/actions/workflows/ci.yml)

---

## Table of Contents

1. [Business Problem](#1-business-problem)
2. [Architecture](#2-architecture)
3. [Data Source and Schema](#3-data-source-and-schema)
4. [Repository Structure](#4-repository-structure)
5. [Local Setup](#5-local-setup)
6. [Working Commands](#6-working-commands)
7. [Data Models](#7-data-models)
8. [Data Quality Rules](#8-data-quality-rules)
9. [Example Queries](#9-example-queries)
10. [Simulation](#10-simulation)
11. [Testing and CI](#11-testing-and-ci)
12. [Snowflake (Future)](#12-snowflake-future)
13. [Explicit Limitations](#13-explicit-limitations)

---

## 1. Business Problem

This platform answers questions about the UK used-car market using listing data:

- What is the typical asking price for a given make, model, year, mileage range, and fuel type?
- Which listings are priced above or below comparable vehicles?
- How do asking prices vary by vehicle configuration?
- Which vehicles appear repeatedly in observed inventory snapshots?
- What data-quality issues affect analytical reliability?

> **Important:** Asking prices are not transaction prices. A listing disappearing from the dataset
> does not confirm a sale. Static snapshot data does not establish real listing history.

---

## 2. Architecture

```
data/raw/used_cars/*.csv   (11 files, static UK listing snapshot)
          │
          ▼
  Python ingestion pipeline  (src/automarket/ingestion/)
  - Discover CSV files
  - Normalize column names and data types
  - Standardize make, model, fuel type, transmission
  - Validate required fields and value ranges
  - Split: accepted rows → DuckDB raw layer
            rejected rows → raw_quarantine table
          │
          ▼
  DuckDB (data/warehouse.duckdb)
  ├── raw.raw_used_car_listings   (108,539 accepted rows)
  └── raw.raw_quarantine          (rejected records with reasons)
          │
          ▼
  dbt transformations  (dbt/)
  ├── staging/  stg_used_car_listings, stg_rejected_listings
  ├── core/     dim_vehicle, fct_listing_snapshot
  └── marts/    mart_comparable_prices
                mart_pricing_deviations
                mart_inventory_summary
          │
          ▼
  Analytical queries / reports
```

**Local DuckDB** is the default and primary development path.
Snowflake is a documented optional future target — not yet validated end-to-end.

---

## 3. Data Source and Schema

**Source:** UK used-car listing CSVs (`data/raw/used_cars/`).

> **Provenance:** This dataset is publicly available from Kaggle (100,000 UK Used Car Data Set).
> Original files are kept unchanged. License should be verified at the source before redistribution.
> See [`docs/SOURCES.md`](docs/SOURCES.md).

| File | Make | Rows | Schema |
|---|---|---|---|
| `audi.csv` | Audi | 10,668 | A (9 cols) |
| `bmw.csv` | BMW | 10,781 | A |
| `ford.csv` | Ford | 17,965 | A |
| `hyundi.csv` | Hyundai | 4,860 | A |
| `merc.csv` | Mercedes-Benz | 13,119 | A |
| `skoda.csv` | Skoda | 6,267 | A |
| `toyota.csv` | Toyota | 6,738 | A |
| `vauxhall.csv` | Vauxhall | 13,632 | A |
| `vw.csv` | Volkswagen | 15,157 | A |
| `cclass.csv` | Mercedes-Benz C-Class | 3,899 | B (no tax/mpg) |
| `focus.csv` | Ford Focus | 5,454 | B |
| `unclean cclass.csv` | — | 4,006 | Excluded (raw scrape format) |
| `unclean focus.csv` | — | 5,604 | Excluded (raw scrape format) |

**Schema A columns:** `model`, `year`, `price` (GBP), `transmission`, `mileage`, `fuelType`, `tax`, `mpg`, `engineSize`

**Canonical field names after normalization:**

| Field | Type | Nullable | Notes |
|---|---|---|---|
| `row_id` | string | no | Deterministic 16-char hash |
| `source_file` | string | no | Original CSV filename |
| `make` | string | no | Inferred from filename |
| `model` | string | no | Stripped whitespace |
| `year` | integer | no | Registration year 1970–2025 |
| `price_gbp` | integer | no | Asking price in GBP |
| `transmission` | string | no | Manual / Automatic / Semi-Auto / Other |
| `mileage_miles` | integer | no | Odometer reading |
| `fuel_type` | string | no | Petrol / Diesel / Hybrid / Electric / Other |
| `tax_gbp` | integer | **yes** | Null for Schema B files |
| `mpg` | float | **yes** | Null for Schema B files |
| `engine_size_l` | float | yes | Litres |

**Ingestion results (current run):**
- Files processed: 11
- Rows read: 108,540
- Rows accepted: **108,539**
- Rows rejected: **1** (ford.csv row with year=2060 — data anomaly)

---

## 4. Repository Structure

```
AutoMarket Intel/
├── .github/workflows/
│   ├── ci.yml                        # Lint + unit + integration on every PR
│   └── nightly_snowflake.yml         # Optional: weekly Snowflake run
├── contracts/
│   └── used_car_listings.v1.yaml     # Data contract with schema and limitations
├── data/
│   └── raw/used_cars/                # 13 CSV files (source data, unchanged)
├── docs/
│   ├── ARCHITECTURE.md
│   ├── CONTRACTS.md
│   ├── DEPLOY.md
│   ├── RUNBOOK.md
│   └── SOURCES.md
├── dbt/
│   ├── models/
│   │   ├── staging/   stg_used_car_listings.sql, stg_rejected_listings.sql
│   │   ├── core/      dim_vehicle.sql, fct_listing_snapshot.sql
│   │   └── marts/     mart_comparable_prices.sql, mart_pricing_deviations.sql,
│   │                  mart_inventory_summary.sql
│   ├── packages.yml                  # dbt_utils dependency
│   ├── dbt_project.yml
│   └── profiles.yml                  # DuckDB (default) + Snowflake targets
├── infra/snowflake/
│   └── setup.sql                     # Idempotent Snowflake bootstrap SQL
├── src/automarket/
│   ├── cli.py                        # `automarket ingest|report|simulate`
│   ├── config.py                     # Env-var config with clear error messages
│   ├── logging_utils.py              # Structured JSON logging (run_id per line)
│   ├── runlog.py                     # Append-only JSONL run log
│   ├── ingestion/
│   │   ├── discovery.py              # CSV discovery, schema mapping
│   │   ├── normalize.py              # Pure normalization functions
│   │   ├── validation.py             # Field-level validation with rejection reasons
│   │   └── pipeline.py              # Orchestrates: read → normalize → validate → load
│   └── simulation/
│       └── snapshots.py              # Optional deterministic listing snapshot simulator
├── tests/
│   ├── unit/        test_normalize.py, test_validation.py,
│   │                test_discovery.py, test_simulation.py
│   └── integration/ test_pipeline.py
├── .env.example
├── .gitignore
├── Makefile
└── pyproject.toml
```

---

## 5. Local Setup

**Requirements:** Python 3.11+, `uv` (`pip install uv`)

```bash
git clone https://github.com/Rabyegh/AutoMarket-Intel.git
cd "AutoMarket Intel"

# Create virtual environment and install dependencies
uv venv .venv
uv pip install dbt-core dbt-duckdb ruff pytest pandas pyarrow duckdb pydantic rich typer

# Configure (no cloud credentials needed for local runs)
cp .env.example .env
```

---

## 6. Working Commands

All commands have been run and verified. They match the implementation.

```bash
# Run all tests (95 tests, ~5s)
uv run pytest tests/ -v

# Ingest CSV data into DuckDB (108,539 rows in ~4-5 min first time)
uv run python -m automarket.cli ingest --data-dir data/raw/used_cars --duckdb-path data/warehouse.duckdb

# Full refresh (drop and reload)
uv run python -m automarket.cli ingest --data-dir data/raw/used_cars --duckdb-path data/warehouse.duckdb --full-refresh

# Install dbt packages (run once)
.venv\Scripts\python.exe -c "from dbt.cli.main import cli; cli()" -- deps --project-dir dbt --profiles-dir dbt

# Build dbt models against DuckDB
.venv\Scripts\python.exe -c "from dbt.cli.main import cli; cli()" -- build --project-dir dbt --profiles-dir dbt --target duckdb

# Print quick analytical report from raw layer
uv run python -m automarket.cli report --duckdb-path data/warehouse.duckdb

# Optional: run historical simulation (1000 listings × 8 weekly snapshots)
uv run python -m automarket.cli simulate --duckdb-path data/warehouse.duckdb --seed 42 --weeks 8 --sample-size 1000

# Clean generated files
python -c "import os; [os.remove(f) for f in ['data/warehouse.duckdb'] if os.path.exists(f)]"
```

---

## 7. Data Models

### Transformation flow

```
raw_used_car_listings  ──►  stg_used_car_listings  ──►  dim_vehicle
                                                     └►  fct_listing_snapshot
                                                              │
                                               ┌─────────────┼─────────────┐
                                               ▼             ▼             ▼
                                    mart_comparable  mart_pricing   mart_inventory
                                       _prices       _deviations      _summary

raw_quarantine         ──►  stg_rejected_listings  (observability only)
```

### Model descriptions

| Model | Layer | Rows (approx.) | Description |
|---|---|---|---|
| `raw_used_car_listings` | raw | 108,539 | Accepted listings loaded by Python |
| `raw_quarantine` | raw | 1 | Rejected records with rejection reasons |
| `stg_used_car_listings` | staging | 108,539 | Typed, normalised, with vehicle_key |
| `stg_rejected_listings` | staging | 1 | Quarantined rows — observability only |
| `dim_vehicle` | core | ~15,000+ | Unique vehicle configurations |
| `fct_listing_snapshot` | core | 108,539 | One row per listing with FK to dim_vehicle |
| `mart_comparable_prices` | mart | ~20,000+ | Price benchmarks by peer group |
| `mart_pricing_deviations` | mart | 108,539 | Each listing vs. peer-group median |
| `mart_inventory_summary` | mart | ~20,000+ | Inventory counts by segment |

### Key design decisions

- **No VINs** — the dataset does not contain VINs; `vehicle_key` is a surrogate hash of make+model+year+fuel_type+transmission+engine_size.
- **Peer group** for comparable pricing: make + model + year + fuel_type + transmission. Groups with <5 listings are flagged as `is_small_peer_group = True`.
- **Asking prices only** — `price_gbp` and `asking_price_gbp` always refer to listing asking prices, never transaction prices.

---

## 8. Data Quality Rules

**Critical fields** (record rejected if invalid):
- `year`: must be integer, 1970–2025
- `price_gbp`: must be integer, £100–£500,000
- `mileage_miles`: must be integer, 0–500,000
- `fuel_type`: must be non-empty
- `make`, `model`, `transmission`: must be non-empty

**Optional fields** (null allowed):
- `tax_gbp`, `mpg` — absent in Schema B files (cclass.csv, focus.csv)
- `engine_size_l` — validated if present: must be 0–10 litres

**Excluded files** (not ingested):
- `unclean cclass.csv` — raw scrape format with split columns and GBP-formatted price strings
- `unclean focus.csv` — same issues

**Observed anomalies in real data:**
- 1 ford.csv row with `year=2060` (data entry error) — quarantined

---

## 9. Example Queries

Run these directly against `data/warehouse.duckdb`:

```sql
-- Average asking price by make (from mart)
SELECT make, listing_count, median_asking_price_gbp, avg_asking_price_gbp
FROM marts.mart_inventory_summary
GROUP BY make, listing_count, median_asking_price_gbp, avg_asking_price_gbp
ORDER BY listing_count DESC;

-- Ford Fiesta 2018 petrol manual asking prices
SELECT model, registration_year, fuel_type, transmission,
       median_asking_price_gbp, p25_asking_price_gbp, p75_asking_price_gbp,
       peer_group_size, is_small_peer_group
FROM marts.mart_comparable_prices
WHERE make = 'Ford' AND model = 'Fiesta'
  AND registration_year = 2018 AND fuel_type = 'Petrol' AND transmission = 'Manual';

-- Most underpriced listings (vs. peer median)
SELECT make, model, registration_year, fuel_type, mileage_miles,
       asking_price_gbp, peer_median_price_gbp, pct_vs_median
FROM marts.mart_pricing_deviations
WHERE NOT is_small_peer_group
ORDER BY pct_vs_median ASC
LIMIT 20;

-- Quarantined records
SELECT rejection_reason, COUNT(*) AS n
FROM raw.raw_quarantine
GROUP BY rejection_reason;
```

---

## 10. Simulation

The `simulate` command generates **reproducible but fictional** weekly listing snapshots
from the static dataset. All simulated rows have `is_simulated = True`.

```bash
uv run python -m automarket.cli simulate --seed 42 --weeks 8 --sample-size 1000
```

**Assumptions and limitations:**
- Observation dates are invented — not real publication dates.
- Price drift is a random walk — not based on observed market movements.
- A row with `is_active = False` does NOT confirm the vehicle was sold.
- `simulation_seed` is stored on each row for full reproducibility.
- Simulation output is stored in `simulated_snapshots` table — never mixed with source data.

---

## 11. Testing and CI

**Test results (95 tests, all passing):**

```
tests/unit/test_discovery.py     14 passed
tests/unit/test_normalize.py     27 passed
tests/unit/test_validation.py    17 passed
tests/unit/test_simulation.py     9 passed
tests/integration/test_pipeline.py  13 passed    (uses fixture CSVs + temp DuckDB)
```

**Run tests:**
```bash
uv run pytest tests/ -v
```

CI (`.github/workflows/ci.yml`) runs lint + unit + integration on every PR.
No network access and no cloud credentials are required.

---

## 12. Snowflake (Future)

The infrastructure SQL and dbt Snowflake profile are present but **not yet validated end-to-end**:

- `infra/snowflake/setup.sql` — idempotent: role, X-Small warehouse, resource monitor (credit cap), transient schemas
- `dbt/profiles.yml` — Snowflake target defined; uses key-pair auth
- `dbt/models/` — SQL written to be DuckDB/Snowflake-compatible (no DuckDB-specific syntax)

To use Snowflake: follow [`docs/DEPLOY.md`](docs/DEPLOY.md) and set the env vars in `.env.example`.

---

## 13. Explicit Limitations

| Limitation | Detail |
|---|---|
| Asking prices ≠ transaction prices | `price_gbp` is what sellers ask, not what buyers pay |
| Static snapshot, no timestamps | The CSV files contain no listing publication dates |
| No VINs | The dataset does not include VINs; vehicle_key is a surrogate |
| Make inferred from filename | The source CSVs have no `make` column |
| Unclean files excluded | `unclean *.csv` are retained but not ingested |
| Snowflake unverified | dbt Snowflake target is configured but not end-to-end tested |
| Simulation is not market data | Simulated events are clearly marked and isolated from source data |
| No real listing history | Without timestamps, time-series analytics require the simulation component |
| NHTSA vPIC removed | VIN decoding is no longer part of this project; the UK dataset has no VINs |
