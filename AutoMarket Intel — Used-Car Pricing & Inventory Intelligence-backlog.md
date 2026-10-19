# VIN Fleet Enrichment Pipeline: Project Plan and Backlog

Solo, part-time, ~7-8 weeks. Sizes are relative (S/M/L), not hour estimates.

## 1. Executive summary and business objective

**Problem.** A fleet operator receives vehicle event feeds (service, inspection, fault, registration) keyed by VIN. Without decoded vehicle attributes, analysts cannot answer basic questions: which makes, model years, body classes and fuel types generate the most events, and how many events belong to vehicles we cannot identify.

**What the project delivers.** A small, reproducible batch pipeline that ingests VIN-keyed events, enriches distinct VINs through NHTSA vPIC, models the result (DuckDB locally, Snowflake as a deployed target), and publishes trusted marts, with a quarantine for VINs vPIC cannot decode.

**Measurable outcomes** (targets are set after the Week 2 baseline, not guessed now):

| Metric | Why it matters |
|---|---|
| Event decode coverage = events on vehicles with clean or partial decode / all events | The business value |
| Unmatched VIN count and reason breakdown | Shows exceptions are visible rather than dropped |
| Rerun determinism: same inputs give identical mart checksums | Proves reproducibility |
| Late-data correction: a late batch changes marts correctly in one run | Proves incremental correctness |
| Recovery: a run killed mid-way completes via `--resume` with no duplicates | Proves failure handling |
| Snowflake credits per full run, under a stated cap | Proves cost control |

## 2. Assumptions, constraints, and technical decisions

**Assumptions (change these and the plan changes):**
- A1. The event feed is **synthetic**, generated from a seed. No real fleet data exists. This also avoids privacy issues.
- A2. vPIC is the only external source. Enrichment uses the **public vPIC API** (decode batch endpoint, documented at 50 VINs per request, subject to automated rate control). The standalone vPIC database (MS SQL Server and PostgreSQL formats, decode-only) is an optional later swap. **Verify both facts against NHTSA's current docs in task E2-01** before depending on them.
- A3. Data volume stays small (~5k vehicles, ~50-100k events per full run). Nothing here needs Spark or a streaming system.
- A4. Scheduling is "run on demand or via GitHub Actions". No orchestrator in the MVP.

**Decisions and trade-offs:**

| Decision | Choice | Trade-off |
|---|---|---|
| Language/tooling | Python (`uv`, `ruff`, `pytest`) + dbt-core | dbt gives tests, lineage and incremental logic for free, but adds a dependency |
| Local warehouse | DuckDB via `dbt-duckdb` | Fast, free, but dialect differs from Snowflake in places (see section 9) |
| Cloud | S3 (raw archive) + Snowflake (marts) | Both are P1. MVP is fully local |
| JSON handling | Flatten vPIC JSON to typed columns **in Python at load time**, keep raw JSON on disk | Avoids DuckDB and Snowflake JSON-function divergence in SQL |
| Orchestration | Makefile + CLI + GitHub Actions | No scheduler UI, which is fine for one daily batch |
| Incremental strategy | `delete+insert` on a unique key, for both engines | Slightly less elegant than `merge`, but identical behaviour on both |
| Raw storage | Append-only files plus manifest with SHA-256 | More files, but raw is never rewritten |

**Honest risk on synthetic VINs:** vPIC decodes by pattern matching on VIN positions. Random VINs with valid check digits will often decode only partially (manufacturer, year, plant) and fail pattern lookup. That is useful for testing unmatched handling but poor for rich attributes. Task E1-04 measures this early and mixes in a small set of documented example VINs if needed.

## 3. Architecture overview and data flow

```
synth generator (seeded)
   -> raw/fleet_events/batch_id=<id>/part.parquet + manifest.json
   -> extract distinct new VINs not yet decoded
   -> vPIC client (chunks of 50, retry, checkpoint per chunk)
   -> raw/vpic/batch_id=<id>/chunk_NNN.json (request + response + timestamp)
   -> flatten to typed rows
   -> DuckDB schema `raw` (append-only, _batch_id, _loaded_at, _file_sha256)
   -> dbt: staging (type, normalize, dedup) -> core (dim/fct/exceptions) -> marts
   -> dbt tests + reconciliation checks -> run log
   -> [P1] same raw files in S3 -> Snowflake raw -> same dbt project, target=snowflake
```

One codebase, one dbt project, two targets. Raw files are the source of truth and the warehouse is rebuildable from them.

## 4. Proposed repository structure

```
vin-fleet-pipeline/
  README.md  Makefile  pyproject.toml  uv.lock  .env.example  .gitignore
  .github/workflows/ci.yml  nightly_snowflake.yml
  docs/ ARCHITECTURE.md  SOURCES.md  CONTRACTS.md  RUNBOOK.md  DEPLOY.md  decisions/
  contracts/ fleet_events.v1.yaml  vpic_decode.v1.yaml
  src/vinpipe/
    cli.py  config.py  logging.py  runlog.py
    synth/        # seeded generator, VIN check-digit logic
    ingest/       # landing writer, manifest, idempotent loader
    vpic/         # client, parser, status classifier
    quality/      # reconciliation checks, contract validation
  dbt/
    models/staging  models/core  models/marts
    macros/       # portability helpers
    tests/        # singular tests
  tests/ unit/  integration/  fixtures/vpic/   # recorded real responses
  infra/snowflake/  # setup SQL: role, warehouse, resource monitor
  data/            # gitignored: raw/, warehouse.duckdb
```

## 5. Data contracts and initial model definitions

**Contract `fleet_events.v1`** (validated in Python before load; version bumps are explicit):

| Column | Type | Rule |
|---|---|---|
| event_id | string | SHA-256 of `source_system|vin_norm|event_type|event_ts|odometer_km`; unique per batch |
| source_system | string | not null |
| vin | string | as received, never modified in raw |
| event_type | string | one of service, inspection, fault, registration |
| event_ts | timestamp (UTC) | not null, not in the future |
| odometer_km | int | nullable, >= 0 |
| batch_id | string | deterministic, see E1-02 |
| ingested_at | timestamp (UTC) | set by loader |

**Contract `vpic_decode.v1`** (typed flatten of vPIC's flat decode response; **verify field names against a live response in E2-01**): vin_requested, decode_batch_id, requested_at, http_status, error_code, error_text, make, model, model_year, body_class, vehicle_type, fuel_type_primary, engine_cylinders, displacement_l, drive_type, manufacturer, plant_country, raw_ref.

**Schema evolution rule.** Additive changes are allowed. vPIC returns many variables, but staging selects a pinned list. A drift check logs new or missing keys and warns on additions, and fails on the removal of any contracted field. Breaking changes require `v2` and a decision record.

**Stable keys**
- `vehicle_key` = uppercase, trimmed VIN. It is never a surrogate that depends on load order.
- `event_id` = content hash (above).
- Decode identity = `(vehicle_key, decode_batch_id)`. The current decode is the latest successful one.

**Models**

| Layer | Model | Notes |
|---|---|---|
| raw | `raw_fleet_events`, `raw_vpic_decodes` | append-only, loaded by Python |
| staging | `stg_fleet_events` | typed, VIN normalized, dedup by `event_id` (latest ingest wins) |
| staging | `stg_vpic_decodes` | one current row per VIN |
| core | `dim_vehicle` | decoded attributes plus `decode_status`, first/last seen |
| core | `fct_fleet_events` | one row per event, FK to vehicle |
| core | `vin_decode_exceptions` | quarantine, with reason |
| marts | `mart_fleet_composition` | by make, model year, body class: vehicles, events, decode_clean_rate |
| ops | `pipeline_runs` | written by Python: run_id, step, status, counts, duration |

**Decode status classes** (derive the mapping from real vPIC error codes in E2-04; don't assume): `invalid_format` (local check fails before any API call), `check_digit_fail`, `decoded_partial`, `no_match`, `api_failed` (retryable, not a data verdict), `decoded_clean`.

## 6. Epics and complete prioritized backlog

Priority: **P0** = MVP (local, end of Week 4). **P1** = cloud and hardening. **P2** = optional.

### E0. Foundation
| ID | Task | Pri | Size | Depends | Acceptance |
|---|---|---|---|---|---|
| E0-01 | Repo scaffold: uv, ruff, pytest, Makefile (`lint test demo`), `.gitignore` | P0 | S | none | `make lint test` passes on empty project |
| E0-02 | Config module reading env vars; `.env.example`; no secrets in code | P0 | S | E0-01 | App runs with only `.env`; missing var gives clear error |
| E0-03 | Structured JSON logging with `run_id` | P0 | S | E0-01 | Every log line carries run_id and step |
| E0-04 | ADR template; record decisions from section 2 | P1 | S | E0-01 | 5+ short ADRs committed |

### E1. Synthetic data and raw layer
| ID | Task | Pri | Size | Depends | Acceptance |
|---|---|---|---|---|---|
| E1-01 | VIN generator with valid check digit; seeded event generator with configurable duplicate, invalid-VIN and late-event rates | P0 | M | E0-01 | Same seed gives byte-identical parquet; unit tests on check digit |
| E1-02 | Landing writer: batch dir, manifest (row count, SHA-256, schema, seed), deterministic `batch_id` | P0 | M | E1-01 | Rerun with same inputs writes nothing new and logs "skipped" |
| E1-03 | Idempotent loader to DuckDB `raw`: skip if manifest hash already loaded, else delete-by-batch then insert in one transaction | P0 | M | E1-02 | Running load twice leaves row counts unchanged; killed mid-load leaves no partial batch |
| E1-04 | **Spike:** decode ~200 generated VINs; record clean/partial/fail rates; decide on example-VIN mix | P0 | S | E2-02 | Written finding in `docs/SOURCES.md`; synth config updated |
| E1-05 | Raw immutability guard: read-only permissions after write; test that rewrite is refused | P1 | S | E1-02 | Test fails if code overwrites an existing raw file |

### E2. vPIC enrichment
| ID | Task | Pri | Size | Depends | Acceptance |
|---|---|---|---|---|---|
| E2-01 | Read vPIC docs: confirm batch size, rate behaviour, response fields, error codes; record in `docs/SOURCES.md` with URLs and date | P0 | S | none | Doc lists confirmed facts and open questions |
| E2-02 | Capture ~50 real decode responses as committed fixtures (varied: clean, partial, invalid) | P0 | S | E2-01 | Fixtures in `tests/fixtures/vpic/`; CI never calls NHTSA |
| E2-03 | Client: chunk by 50, polite pacing, identifying User-Agent, exponential backoff with jitter, per-chunk raw JSON checkpoint | P0 | M | E2-01 | Killed run resumes by skipping completed chunks |
| E2-04 | Parser plus status classifier (error codes to status classes) with unit tests from fixtures | P0 | M | E2-02 | Every fixture classified; unknown codes land in `no_match` with a warning |
| E2-05 | Decode only **new** VINs (not in current decode table); `--redecode` flag for forced refresh | P0 | S | E2-03 | Second run makes zero API calls |
| E2-06 | Quarantine model `vin_decode_exceptions` with reason and retry count | P0 | S | E2-04, E3-01 | clean + exceptions = distinct input VINs (singular test) |
| E2-07 | Dead-letter handling: chunk failing N times is recorded, run continues, summary flags it | P1 | S | E2-03 | Simulated failure produces dead-letter row and non-zero exit warning |

### E3. Transform and marts (dbt)
| ID | Task | Pri | Size | Depends | Acceptance |
|---|---|---|---|---|---|
| E3-01 | dbt project with duckdb target; sources; staging models with dedup via window function | P0 | M | E1-03 | `dbt build` green on one batch |
| E3-02 | `dim_vehicle`, `fct_fleet_events` | P0 | M | E3-01, E2-04 | Unique and not-null keys tested; FK relationship test |
| E3-03 | `mart_fleet_composition` and the first analytical result (decode coverage by make) | P0 | S | E3-02 | Result matches a hand-computed expectation on the tiny fixture |
| E3-04 | Portability macros and a banned-constructs lint (see section 9) | P1 | S | E3-01 | CI grep rejects listed DuckDB-only syntax |

### E4. Incremental processing and late data
| ID | Task | Pri | Size | Depends | Acceptance |
|---|---|---|---|---|---|
| E4-01 | Incremental `fct_fleet_events`: unique key `event_id`, strategy delete+insert, driven by `_batch_id` watermark (**not** `event_ts`) | P0 | M | E3-02 | Second batch adds only new events |
| E4-02 | Late-arriving events scenario: batch containing events older than prior batches lands in correct partition and mart updates | P0 | M | E4-01 | Integration test: marts equal a full rebuild |
| E4-03 | Late-arriving decode: VIN seen in events before its decode succeeds; status upgrades from `api_failed` to decoded on retry | P1 | M | E2-06, E4-01 | Test: coverage rises after retry; no duplicate vehicles |
| E4-04 | `full-refresh` command and equivalence test (incremental result equals full rebuild) | P0 | S | E4-02 | Checksum comparison in CI |

### E5. Quality and testing
| ID | Task | Pri | Size | Depends | Acceptance |
|---|---|---|---|---|---|
| E5-01 | Unit test suite for VIN logic, hashing, chunking, parser | P0 | M | E1-01, E2-04 | Runs in seconds, no network |
| E5-02 | dbt tests: unique, not_null, accepted_values, relationships | P0 | S | E3-02 | All pass; deliberately broken data fails them |
| E5-03 | Reconciliation checks: raw rows to staged rows to fact rows (dedup count explained) | P0 | M | E3-02 | Check outputs a table; mismatch fails the run |
| E5-04 | Contract validation before load (pyarrow schema + value rules); rejects bad batch without partial load | P0 | M | E1-02 | Bad-schema fixture rejected, logged, raw untouched |
| E5-05 | Schema drift test: extra and missing vPIC keys | P1 | S | E2-04 | Extra key warns; missing contracted key fails |
| E5-06 | End-to-end integration test on tiny seed with fixtures: run twice, compare mart checksum | P0 | M | E4-02 | Part of `make test`; no network |
| E5-07 | Source freshness check on raw tables | P1 | S | E3-01 | Stale source flagged in run summary |

### E6. Observability and recovery
| ID | Task | Pri | Size | Depends | Acceptance |
|---|---|---|---|---|---|
| E6-01 | `pipeline_runs` table: one row per step with status, counts, duration, error | P0 | M | E0-03 | Failed step recorded with message |
| E6-02 | End-of-run summary (rows in/out, duplicates dropped, decode statuses, API calls, checks) | P0 | S | E6-01 | Printed and written to `docs/` or artifact |
| E6-03 | `--resume`: re-run skips steps and chunks already completed for the same `run_id` | P0 | M | E6-01, E2-03 | Kill-and-resume integration test passes |
| E6-04 | Failure notification via GitHub Actions failure emails only | P1 | S | E8-01 | Failing scheduled run triggers notification |
| E6-05 | Runbook: symptoms, causes, fixes for each known failure | P1 | M | E6-03 | Each failure mode in tests has a runbook entry |

### E7. Cloud, cost and secrets (all P1; start only after P0 is demoable)
| ID | Task | Pri | Size | Depends | Acceptance |
|---|---|---|---|---|---|
| E7-01 | S3 bucket for raw: versioning on, block public access, same key layout as local | P1 | S | E1-02 | Raw sync is idempotent; hashes match |
| E7-02 | AWS auth for CI via OIDC role with least privilege (no long-lived keys) | P1 | M | E7-01 | CI uploads without stored access keys |
| E7-03 | Snowflake setup SQL: dedicated role, X-Small warehouse, `AUTO_SUSPEND` 60s, **resource monitor with a hard quota that suspends**, transient schemas | P1 | M | none | Setup script is rerunnable; monitor visible in account |
| E7-04 | Snowflake key-pair auth for the service user; keys outside repo; `.env.example` documents vars | P1 | S | E7-03 | No secret in git history (scan passes) |
| E7-05 | Load raw to Snowflake from parquet; same idempotency rule as DuckDB | P1 | M | E7-03, E1-03 | Double load leaves counts unchanged |
| E7-06 | dbt `snowflake` target; run on tiny data | P1 | M | E7-05, E3-04 | `dbt build` green on Snowflake |
| E7-07 | Parity test: mart row counts and aggregate checksums equal across DuckDB and Snowflake | P1 | M | E7-06 | Mismatch fails the nightly job |
| E7-08 | Cost guardrails: query tags per run, credits-used report in run summary, Snowflake runs manual or weekly only | P1 | S | E7-06 | Summary shows credits for the run |
| E7-09 | Secret scanning in pre-commit and CI | P1 | S | E0-01 | Planted fake secret is caught |

### E8. CI/CD and documentation
| ID | Task | Pri | Size | Depends | Acceptance |
|---|---|---|---|---|---|
| E8-01 | CI: lint, unit, integration (DuckDB + fixtures), `dbt build` on every PR | P0 | M | E5-06 | Green badge; no network and no secrets needed |
| E8-02 | `make demo`: one command from clean checkout to mart | P0 | S | E5-06 | Works on a fresh clone |
| E8-03 | README with architecture, results, metrics, how to reproduce | P0 | M | E8-02 | A stranger can reproduce the result |
| E8-04 | `docs/SOURCES.md`: vPIC terms and attribution, rate behaviour, what the repo does not redistribute, synthetic-data statement. **Check NHTSA's current terms rather than assuming a license.** | P0 | S | E2-01 | Reviewed against NHTSA pages, dated |
| E8-05 | `nightly_snowflake.yml` (manual dispatch plus weekly schedule) using repo secrets | P1 | M | E7-07 | Runs without exposing secrets in logs |
| E8-06 | `docs/DEPLOY.md`: environments, secrets list, bootstrap steps, rollback (rebuild from raw) | P1 | M | E8-05 | Another person could deploy from it |

### E9. Optional extensions (P2, value stated first)
| ID | Task | Value if done | Cost / why optional |
|---|---|---|---|
| E9-01 | Terraform for S3 and Snowflake objects | Reproducible infra, strong portfolio signal | New tool plus state; setup SQL (E7-03) already works |
| E9-02 | Swap API for standalone vPIC database | No rate limits, pinned decode version | Needs restoring SQL Server or Postgres dump; decode-only, not worth it at this volume |
| E9-03 | NHTSA recalls enrichment | Second source with a real join and business question | New source to contract, test and license-check |
| E9-04 | Dagster or Airflow | Scheduling UI, retries | One daily batch is covered by Actions; heavy for solo work |
| E9-05 | Streamlit or static dashboard | Easier demo | Marts plus README tables already demonstrate results |
| E9-06 | Dockerfile / devcontainer | Environment parity | `uv.lock` already pins deps |
| E9-07 | Great Expectations or Soda | Richer data-quality UI | dbt tests plus E5-03 cover the need |

### Requirement traceability

| Requirement | Tasks |
|---|---|
| Idempotency, safe reruns | E1-02, E1-03, E2-05, E6-03, E7-05 |
| Immutable raw, reproducibility | E1-02, E1-05, E5-06, E8-02 |
| Incremental, late data | E4-01 to E4-04 |
| Schema evolution, contracts | E5-04, E5-05, section 5 |
| Stable keys, dedup | E3-01, E3-02, section 5 |
| Unmatched vPIC records | E2-04, E2-06, E2-07, E4-03 |
| Unit, integration, data tests | E5-01 to E5-07 |
| Logging, observability, recovery | E0-03, E6-01 to E6-05 |
| Secrets | E0-02, E7-02, E7-04, E7-09 |
| Snowflake cost | E7-03, E7-08 |
| Licensing, responsible use | E2-03 (pacing, User-Agent), E8-04 |
| Reproducible synthetic data | E1-01, E1-04 |
| DuckDB/Snowflake compatibility | E3-04, E7-06, E7-07 |
| CI/CD, deployment docs | E8-01, E8-05, E8-06 |

## 7. Detailed task dependencies

**Critical path (P0):**
`E0-01 -> E1-01 -> E1-02 -> E1-03 -> E3-01 -> E3-02 -> E3-03` is the thin slice.
`E2-01 -> E2-02 -> E2-04 -> E2-06` and `E2-03 -> E2-05` feed `E3-02`.
`E3-02 -> E4-01 -> E4-02 -> E5-06 -> E8-01` closes the MVP.

**Parallelizable:** E2-01 and E2-02 (docs and fixtures) can start in Week 1 alongside E1. E5-01 grows with each module. E8-04 can be written any time after E2-01.

**P1 chain:** `E7-03 -> E7-05 -> E7-06 -> E7-07 -> E8-05`. E7-03 has no code dependency, so create the Snowflake trial account in Week 3 to absorb any delay.

## 8. Week-by-week implementation roadmap

| Week | Focus | Exit criterion |
|---|---|---|
| 1 | **Milestone 1 (thin slice).** E0-01 to E0-03, E1-01 to E1-03, E2-01, E2-02, E3-01 to E3-03 using fixture decodes, E5-02, E8-02. One batch, local transform, one tested result, `make demo` reproducible. | Demo runs twice with identical mart checksum |
| 2 | Live vPIC client, parser, classifier, quarantine: E2-03 to E2-06, E1-04, E5-01. Set the coverage baseline and targets. | Second run makes zero API calls; clean + exceptions = input VINs |
| 3 | Incremental and late data: E4-01 to E4-04, E5-03, E5-04, E8-01 (CI). Create the Snowflake trial account. | CI green; incremental equals full rebuild |
| 4 | Observability and recovery: E6-01 to E6-03, E5-06, E8-03, E8-04. **MVP complete and demoable.** | Kill-and-resume test passes; README reproduces results |
| 5 | AWS/Snowflake: E7-01 to E7-04, E7-09, E3-04. | Setup scripts rerunnable; cost monitor active |
| 6 | Snowflake path: E7-05 to E7-08, E5-05, E2-07, E4-03. | Parity test passes on tiny data |
| 7 | Hardening and docs: E8-05, E8-06, E6-04, E6-05, E5-07, E1-05, E0-04. | Docs let someone else run and deploy |
| 8 | Buffer, polish, final metrics in README. Pick at most one P2 item **only if** P0 and P1 are fully green. | Project demoable end to end |

## 9. Testing and acceptance strategy

**Layers**
- **Unit** (fast, no network): VIN normalization and check digit, key hashing, chunking, parser, status classifier.
- **Integration** (DuckDB, recorded vPIC fixtures, tiny seed): full run twice with identical checksums; late batch; killed-and-resumed run; schema-drift fixture; unmatched VIN handling.
- **Data tests** (dbt plus reconciliation): uniqueness, not null, accepted values, relationships, raw to staging to fact row accounting, quarantine plus clean equals input.

**Reproducibility.** Seeded generation, locked dependencies (`uv.lock`), recorded fixtures, deterministic batch IDs, and no wall-clock values inside hashed or checksummed data.

**DuckDB and Snowflake compatibility**
- Use dbt cross-database macros for date math and hashing. Use `QUALIFY` and window functions, which both support.
- Avoid in models: DuckDB list comprehensions, `EXCLUDE`/`COLUMNS(*)`, reading files directly from SQL; and Snowflake `FLATTEN`, VARIANT path syntax.
- Flatten JSON in Python, so SQL only sees typed columns.
- Use lowercase unquoted identifiers (Snowflake uppercases unquoted names), explicit `timestamp_ntz` in UTC, `decimal` rather than float for aggregates, and explicit `ORDER BY ... NULLS` where order matters.
- E3-04 greps for banned constructs on every PR. E7-07 compares aggregate checksums across engines.

**Acceptance for the MVP:** E8-02 works from a fresh clone, CI is green offline, the coverage metric and unmatched breakdown are in the README, and kill-and-resume plus late-data tests pass.

## 10. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Synthetic VINs mostly fail vPIC pattern decode | Poor attribute richness | E1-04 spike; mix documented example VINs; unmatched handling is still demonstrated |
| vPIC rate control or outage | Blocked live runs | Chunk checkpoints, backoff, fixtures for all tests, raw responses cached forever |
| vPIC fields or error codes differ from assumptions | Wrong classifier | E2-01 and E2-02 come first; classifier built from real responses |
| Snowflake setup delayed or costly | P1 slips | Section 11 contingency; DuckDB-only MVP is complete on its own |
| Scope creep into P2 tools | MVP late | P2 items have stated value and are gated behind green P0/P1 |
| Dialect drift between engines | Late surprises | E3-04 lint, parity test, tiny Snowflake run from Week 5 |
| Secrets leaked | Security | `.env` ignored, OIDC and key-pair auth, scanning in E7-09 |
| Overrunning on perfectionism | Schedule | Week 4 is a hard MVP checkpoint |

## 11. Definition of Done

A task is done when:
1. It meets its acceptance column.
2. It has tests at the right layer, and `make lint test` passes.
3. A rerun of the affected step is safe and idempotent.
4. It logs a `run_id` and records its status in `pipeline_runs` where applicable.
5. Contracts, docs or runbook entries are updated if behaviour changed.
6. No secrets, no raw data overwrites, no network calls in tests.
7. CI is green.

## 12. MVP versus optional extensions

**MVP (P0, end of Week 4):** fully local. Seeded synthetic events, immutable raw landing, live vPIC decode with quarantine, dbt models on DuckDB, incremental and late-data handling, tests, run log, resume, CI, reproducible `make demo`, README with metrics.

**P1:** S3 raw archive, Snowflake target with cost guardrails, parity test, nightly or manual deploy workflow, deployment docs, runbook, drift tests.

**P2 / postpone:** Terraform, standalone vPIC database, recalls enrichment, orchestrator, dashboard, Docker, extra quality frameworks. Also postpone: streaming, SCD2 history for vehicles (vPIC attributes rarely change per VIN), multi-environment promotion, performance tuning, real data.

**Contingency**
- **Snowflake delayed:** stay on DuckDB; keep E7-03 SQL and the dbt target written but untested, and say so honestly in the README.
- **Snowflake cost restrictive:** run only manually or weekly on the tiny dataset; keep the resource monitor and X-Small warehouse; as a last resort, drop the cloud run and keep recorded parity-test output.
- **AWS delayed:** the local raw directory already uses S3-style keys, so syncing later is a copy. Snowflake can load from local files via a stage in the meantime.

## 13. Recommended first five tasks

1. **E0-01** Scaffold the repo (uv, ruff, pytest, Makefile, `.gitignore`).
2. **E2-01 + E2-02** Read the vPIC docs, record the confirmed facts, capture ~50 real decode responses as fixtures (parallel, 1-2 sittings).
3. **E1-01** Seeded VIN and event generator with check-digit logic and unit tests.
4. **E1-02 + E1-03** Landing writer with manifest and deterministic batch ID, then the idempotent DuckDB loader.
5. **E3-01 to E3-03** dbt project: staging, `dim_vehicle`, `fct_fleet_events`, `mart_fleet_composition`, then wire `make demo` (E8-02) and assert a stable mart checksum across two runs.

Start with task 1. Task 2 can happen in parallel since it needs no code.
