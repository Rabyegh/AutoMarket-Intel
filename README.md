# AutoMarket Intel — Used-Car Pricing & Inventory Intelligence

> A reproducible batch pipeline that ingests VIN-keyed used-car events, enriches vehicle
> attributes through the NHTSA vPIC API, models the result in DuckDB (locally) and Snowflake
> (deployed), and publishes trusted analytical marts — with a quarantine for VINs vPIC cannot decode.

[![CI](https://github.com/Rabyegh/AutoMarket-Intel/actions/workflows/ci.yml/badge.svg)](https://github.com/Rabyegh/AutoMarket-Intel/actions/workflows/ci.yml)

---

## Table of Contents

1. [Business Objective](#1-business-objective)
2. [Dataset](#2-dataset)
3. [Architecture](#3-architecture)
4. [Repository Structure](#4-repository-structure)
5. [Quick Start](#5-quick-start)
6. [Pipeline Stages](#6-pipeline-stages)
7. [Data Models](#7-data-models)
8. [Key Design Decisions](#8-key-design-decisions)
9. [Testing](#9-testing)
10. [Metrics & Results](#10-metrics--results)
11. [Cloud Deployment (P1)](#11-cloud-deployment-p1)
12. [Roadmap](#12-roadmap)

---

## 1. Business Objective

A fleet operator receives vehicle event feeds (service, inspection, fault, registration) keyed
by VIN. Without decoded vehicle attributes, analysts cannot answer basic questions:

- Which makes, model years, body classes, and fuel types generate the most events?
- How many events belong to vehicles we cannot identify?

**This project delivers** a small, reproducible batch pipeline that answers those questions,
with full coverage metrics and an explicit quarantine for undecodable VINs.

### Measurable Outcomes

| Metric | Target (set after Week 2 baseline) |
|---|---|
| Event decode coverage | % of events on vehicles with clean or partial decode |
| Unmatched VIN breakdown | Count and reason by decode status class |
| Rerun determinism | Same inputs → identical mart checksums |
| Late-data correction | Late batch updates marts in one run |
| Kill-and-resume | Interrupted run completes with `--resume`, no duplicates |
| Snowflake credits per run | Under stated cap |

---

## 2. Dataset

The **used-car data** lives in `data/raw/used_cars/` and covers 11 makes:

| File | Make |
|---|---|
| `audi.csv` | Audi |
| `bmw.csv` | BMW |
| `cclass.csv` / `unclean cclass.csv` | Mercedes C-Class |
| `focus.csv` / `unclean focus.csv` | Ford Focus |
| `ford.csv` | Ford (all) |
| `hyundi.csv` | Hyundai |
| `merc.csv` | Mercedes |
| `skoda.csv` | Skoda |
| `toyota.csv` | Toyota |
| `vauxhall.csv` | Vauxhall |
| `vw.csv` | Volkswagen |

**Fleet event data is synthetic**, generated from a seeded random process to avoid privacy issues
and allow fully reproducible runs. See [`docs/SOURCES.md`](docs/SOURCES.md).

---

## 3. Architecture

```
synth generator (seeded)
   -> raw/fleet_events/batch_id=<id>/part.parquet + manifest.json
   -> extract distinct new VINs not yet decoded
   -> vPIC client (chunks of 50, retry, checkpoint per chunk)
   -> raw/vpic/batch_id=<id>/chunk_NNN.json
   -> flatten to typed rows
   -> DuckDB schema `raw`   (append-only, _batch_id, _loaded_at, _file_sha256)
   -> dbt: staging -> core (dim/fct/exceptions) -> marts
   -> dbt tests + reconciliation checks -> run log
   -> [P1] S3 raw archive -> Snowflake raw -> same dbt project, target=snowflake
```

One codebase · one dbt project · two targets. Raw files are the source of truth.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for more detail.

---

## 4. Repository Structure

```
AutoMarket Intel/
├── .github/workflows/
│   ├── ci.yml                   # Lint + unit + integration + dbt on every PR
│   └── nightly_snowflake.yml    # Manual dispatch + weekly Snowflake run
├── contracts/
│   ├── fleet_events.v1.yaml     # Validated before every raw load
│   └── vpic_decode.v1.yaml      # Typed vPIC response contract
├── data/
│   └── raw/used_cars/           # 13 CSV files (Audi, BMW, Ford…)
├── docs/
│   ├── ARCHITECTURE.md
│   ├── CONTRACTS.md
│   ├── DEPLOY.md
│   ├── RUNBOOK.md
│   ├── SOURCES.md
│   └── decisions/               # ADR records
├── dbt/
│   ├── models/
│   │   ├── staging/             # stg_fleet_events, stg_vpic_decodes
│   │   ├── core/                # dim_vehicle, fct_fleet_events, vin_decode_exceptions
│   │   └── marts/               # mart_fleet_composition
│   ├── macros/                  # Cross-database portability helpers
│   ├── tests/                   # Singular dbt tests
│   ├── dbt_project.yml
│   └── profiles.yml             # DuckDB (default) + Snowflake targets
├── infra/snowflake/
│   └── setup.sql                # Idempotent: role, warehouse, resource monitor, schemas
├── src/vinpipe/
│   ├── cli.py                   # `vinpipe run|load|sync-s3|parity-check`
│   ├── config.py                # Env-var config; clear error on missing vars
│   ├── logging.py               # Structured JSON logging (run_id, step on every line)
│   ├── runlog.py                # Append-only JSONL run log + resume support
│   ├── synth/                   # Seeded VIN + event generator (E1-01)
│   ├── ingest/                  # Landing writer + idempotent DuckDB loader (E1-02, E1-03)
│   ├── vpic/                    # vPIC client, parser, status classifier (E2-03, E2-04)
│   └── quality/                 # Reconciliation checks + contract validation (E5-03, E5-04)
├── tests/
│   ├── unit/                    # Fast, no network (E5-01)
│   ├── integration/             # DuckDB + recorded vPIC fixtures (E5-06)
│   └── fixtures/vpic/           # ~50 recorded real decode responses (E2-02)
├── .env.example
├── .gitignore
├── Makefile
└── pyproject.toml
```

---

## 5. Quick Start

### Prerequisites

- Python 3.11+
- [`uv`](https://github.com/astral-sh/uv): `pip install uv`

### Local setup

```bash
git clone https://github.com/Rabyegh/AutoMarket-Intel.git
cd "AutoMarket Intel"

# Install dependencies
uv sync

# Configure (no Snowflake or AWS needed for local runs)
cp .env.example .env
# Leave Snowflake/AWS vars blank for now

# Run the full demo (synthetic data, fixture decodes, no network)
make demo
```

### Available commands

```bash
make lint          # ruff check + format check
make test          # unit + integration tests
make demo          # end-to-end local run (seed=42, 2 batches)
make full-refresh  # drop + rebuild all models from raw
make dbt-build     # dbt build against DuckDB
make clean         # remove warehouse.duckdb and run logs
```

---

## 6. Pipeline Stages

| Stage | Task | Status |
|---|---|---|
| **E0** Foundation | uv, ruff, pytest, Makefile, config, logging | 🔲 Todo |
| **E1** Synthetic data + raw layer | VIN generator, landing writer, idempotent loader | 🔲 Todo |
| **E2** vPIC enrichment | API client, parser, status classifier, quarantine | 🔲 Todo |
| **E3** Transform & marts (dbt) | staging, dim_vehicle, fct_fleet_events, mart | 🔲 Todo |
| **E4** Incremental + late data | delete+insert strategy, late-batch test | 🔲 Todo |
| **E5** Quality & testing | unit, integration, data tests, reconciliation | 🔲 Todo |
| **E6** Observability & recovery | pipeline_runs table, run summary, --resume | 🔲 Todo |
| **E7** Cloud (P1) | S3 archive, Snowflake target, cost guardrails, parity test | 🔲 Todo |
| **E8** CI/CD & docs | GitHub Actions, README metrics, DEPLOY, RUNBOOK | 🔲 In Progress |

---

## 7. Data Models

| Layer | Model | Description |
|---|---|---|
| raw | `raw_fleet_events` | Append-only; loaded by Python |
| raw | `raw_vpic_decodes` | Append-only; loaded by Python |
| staging | `stg_fleet_events` | Typed, VIN-normalised, dedup by `event_id` |
| staging | `stg_vpic_decodes` | One current row per VIN |
| core | `dim_vehicle` | Decoded attributes + `decode_status`, first/last seen |
| core | `fct_fleet_events` | One row per event, FK to `dim_vehicle` |
| core | `vin_decode_exceptions` | Quarantine with reason and retry count |
| marts | `mart_fleet_composition` | By make, model year, body class: vehicles, events, decode_clean_rate |
| ops | `pipeline_runs` | Written by Python: run_id, step, status, counts, duration |

### Decode Status Classes

| Status | Meaning |
|---|---|
| `decoded_clean` | All contracted attributes populated |
| `decoded_partial` | Manufacturer/year decoded; not all attributes |
| `no_match` | vPIC pattern lookup returns no results |
| `check_digit_fail` | VIN check digit invalid |
| `invalid_format` | Rejected locally before any API call |
| `api_failed` | Retryable error; not a permanent data verdict |

---

## 8. Key Design Decisions

| Decision | Choice | Trade-off |
|---|---|---|
| Language/tooling | Python (uv, ruff, pytest) + dbt-core | dbt gives tests, lineage and incremental logic for free |
| Local warehouse | DuckDB via dbt-duckdb | Fast and free; dialect differs from Snowflake in places |
| Cloud target | S3 (raw archive) + Snowflake (marts) | P1 only; MVP is fully local |
| JSON handling | Flatten vPIC JSON to typed columns in Python at load time | Avoids DuckDB/Snowflake JSON-function divergence in SQL |
| Incremental strategy | `delete+insert` on unique key, for both engines | Identical behaviour on DuckDB and Snowflake |
| Raw storage | Append-only files + manifest with SHA-256 | Raw is never rewritten |
| Orchestration | Makefile + CLI + GitHub Actions | No scheduler UI; fine for one daily batch |

---

## 9. Testing

| Layer | Scope | Runs in |
|---|---|---|
| **Unit** | VIN logic, hashing, chunking, parser, classifier | < 1s, no network |
| **Integration** | Full run × 2 (checksum match), late batch, resume, schema drift | DuckDB + recorded fixtures |
| **Data (dbt)** | Unique, not-null, accepted values, relationships, row accounting | dbt test |

```bash
make test        # all layers
make dbt-test    # dbt tests only
```

CI (`.github/workflows/ci.yml`) runs all layers on every PR with no network and no secrets.

---

## 10. Metrics & Results

_This section will be populated after the Week 4 MVP milestone._

| Metric | Value |
|---|---|
| Total distinct VINs | TBD |
| Event decode coverage | TBD |
| Decoded clean | TBD |
| Decoded partial | TBD |
| No match / quarantined | TBD |
| Mart checksum (run 1 = run 2) | TBD |
| Full pipeline duration | TBD |

---

## 11. Cloud Deployment (P1)

See [`docs/DEPLOY.md`](docs/DEPLOY.md) for full bootstrap instructions.

**Summary:**
1. Run `infra/snowflake/setup.sql` with `ACCOUNTADMIN`.
2. Create S3 bucket with versioning and block-public-access.
3. Add GitHub repository secrets (Snowflake key-pair, AWS OIDC role).
4. Enable the nightly Snowflake workflow or trigger manually.

**Cost guardrails:** X-Small warehouse, `AUTO_SUSPEND = 60s`, resource monitor with a hard
credit quota that suspends the warehouse. Runs are manual or weekly-only.

---

## 12. Roadmap

See the full backlog in [`AutoMarket Intel — Used-Car Pricing & Inventory Intelligence-backlog.md`](AutoMarket%20Intel%20%E2%80%94%20Used-Car%20Pricing%20%26%20Inventory%20Intelligence-backlog.md).

**MVP (P0, Week 4):** Fully local. Seeded synthetic events, immutable raw landing, live vPIC
decode with quarantine, dbt models on DuckDB, incremental + late-data handling, tests, run log,
`--resume`, CI, reproducible `make demo`, README with metrics.

**P1:** S3 raw archive, Snowflake target with cost guardrails, parity test, nightly deploy
workflow, deployment docs, runbook, drift tests.

**P2 / Postponed:** Terraform, standalone vPIC DB, NHTSA recalls enrichment, Dagster/Airflow,
Streamlit dashboard, Docker/devcontainer, Great Expectations.

---

## License

_To be determined. See [`docs/SOURCES.md`](docs/SOURCES.md) for data source attributions._
