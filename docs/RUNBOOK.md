# Runbook

Symptoms, causes, and fixes for known failure modes.
_Each entry corresponds to a test in the integration suite._

---

## RB-01 — `make demo` fails with missing env var

**Symptom:** `EnvironmentError: Required environment variable 'X' is not set.`
**Cause:** `.env` file missing or incomplete.
**Fix:** `cp .env.example .env` then fill required values.

---

## RB-02 — vPIC API rate-limited (HTTP 429 or connection timeout)

**Symptom:** Run stalls or logs `api_failed` for many chunks.
**Cause:** Too many requests too quickly, or NHTSA maintenance.
**Fix:**
1. Increase `VPIC_RATE_SLEEP_S` in `.env`.
2. Use `--resume` — completed chunks are skipped automatically.
3. Run with `--fixture-decodes` to use recorded responses (no network).

---

## RB-03 — DuckDB file locked

**Symptom:** `duckdb.IOException: Could not open database file`
**Cause:** Another process (e.g., a previous crashed run) holds the lock.
**Fix:** Find and kill the other process, or `make clean` to reset the warehouse.

---

## RB-04 — Incremental run adds duplicate rows

**Symptom:** Row counts grow unexpectedly after re-running the same batch.
**Cause:** Idempotency guard bypassed (e.g., manifest hash not stored correctly).
**Fix:** Run `make full-refresh`. Then check `data/run_log.json` for failed load steps.

---

## RB-05 — dbt build fails with "relation does not exist"

**Symptom:** `dbt build` errors on a staging or core model.
**Cause:** Raw tables not yet loaded (Python load step must run first).
**Fix:** Run `vinpipe run` to load data, then `make dbt-build`.

---

## RB-06 — Snowflake credits exceeded

**Symptom:** Warehouse suspended, queries fail with `RESOURCE_MONITOR` error.
**Cause:** Resource monitor credit quota hit.
**Fix:** Log in to Snowflake console → Account → Resource Monitors → reset or raise VINPIPE_MONITOR quota. Then re-run manually.

---

## RB-07 — Kill and resume leaves partial batch

**Symptom:** Row counts inconsistent after a killed run and `--resume`.
**Cause:** Load step died mid-transaction.
**Fix:** The idempotent loader uses a delete-then-insert transaction — a partial load leaves no rows for that batch. Simply run with `--resume`.

---

_Add new entries here as new failure modes are discovered and tested (E6-05)._
