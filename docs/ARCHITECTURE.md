# Architecture

See [`docs/ARCHITECTURE.md`](ARCHITECTURE.md) for the full data-flow diagram.

## Data Flow

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

One codebase, one dbt project, two targets.
Raw files are the source of truth — the warehouse is fully rebuildable from them.

## Layer Definitions

| Layer | Purpose |
|---|---|
| `raw` | Append-only. Written by Python. Never rewritten. |
| `staging` | Typed, normalised, deduped. One row per `event_id` or `(vin, decode_batch_id)`. |
| `core` | `dim_vehicle`, `fct_fleet_events`, `vin_decode_exceptions`. |
| `marts` | Analyst-facing. `mart_fleet_composition` (decode coverage by make). |
| `ops` | `pipeline_runs` — written by Python, not dbt. |

## Key Design Decisions

See [`docs/decisions/`](decisions/) for individual ADRs.
