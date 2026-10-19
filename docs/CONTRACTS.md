# Data Contracts

See [`contracts/`](../contracts/) for YAML definitions.

## `fleet_events.v1`

Validated in Python before raw load. Version bumps are explicit ADRs.

| Column | Type | Rule |
|---|---|---|
| event_id | string | SHA-256 of `source_system\|vin_norm\|event_type\|event_ts\|odometer_km`; unique per batch |
| source_system | string | not null |
| vin | string | as received, never modified in raw |
| event_type | string | one of service, inspection, fault, registration |
| event_ts | timestamp (UTC) | not null, not in the future |
| odometer_km | int | nullable, >= 0 |
| batch_id | string | deterministic; SHA-256(seed\|batch_index) |
| ingested_at | timestamp (UTC) | set by loader at load time |

## `vpic_decode.v1`

Typed flatten of vPIC's flat decode response.
**Field names must be verified against a live response — see E2-01 / docs/SOURCES.md.**

Fields: `vin_requested`, `decode_batch_id`, `requested_at`, `http_status`, `error_code`, `error_text`, `make`, `model`, `model_year`, `body_class`, `vehicle_type`, `fuel_type_primary`, `engine_cylinders`, `displacement_l`, `drive_type`, `manufacturer`, `plant_country`, `raw_ref`.

## Decode Status Classes

| Status | Meaning |
|---|---|
| `invalid_format` | Local check fails before any API call |
| `check_digit_fail` | VIN check digit invalid |
| `decoded_partial` | Manufacturer/year decoded but not all attributes |
| `no_match` | vPIC pattern lookup returns no results |
| `api_failed` | Retryable HTTP/network error; not a data verdict |
| `decoded_clean` | All contracted attributes populated |

## Evolution Policy

- **Additive** changes (new optional fields): allowed without versioning.
- **Breaking** changes (field removal or type change): require `v2` contract and an ADR.
- **Drift check** runs on every load: warns on new vPIC keys, fails on removal of contracted field.
