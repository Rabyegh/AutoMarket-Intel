# Runbook — AutoMarket Intel

Operational reference for running and maintaining the local pipeline.

## Normal pipeline run (from scratch)

```bash
# 1. Ingest (all 11 CSV files → DuckDB raw.raw_used_car_listings)
uv run python -m automarket.cli ingest \
  --data-dir data/raw/used_cars \
  --duckdb-path data/warehouse.duckdb

# 2. Install dbt packages (one-time)
.venv\Scripts\python.exe -c "from dbt.cli.main import cli; cli()" \
  -- deps --project-dir dbt --profiles-dir dbt

# 3. Build dbt models
$env:DUCKDB_PATH=(Resolve-Path "data\warehouse.duckdb").Path
.venv\Scripts\python.exe -c "from dbt.cli.main import cli; cli()" \
  -- build --project-dir dbt --profiles-dir dbt --target duckdb

# 4. View quick report
uv run python -m automarket.cli report --duckdb-path data/warehouse.duckdb
```

## Full refresh (drop and reload)

```bash
uv run python -m automarket.cli ingest \
  --data-dir data/raw/used_cars \
  --duckdb-path data/warehouse.duckdb \
  --full-refresh

# Then rebuild dbt models
$env:DUCKDB_PATH=(Resolve-Path "data\warehouse.duckdb").Path
.venv\Scripts\python.exe -c "from dbt.cli.main import cli; cli()" \
  -- build --full-refresh --project-dir dbt --profiles-dir dbt --target duckdb
```

## Tests only

```bash
# All tests (unit + integration)
uv run pytest tests/ -v

# Unit only (fast, no I/O)
uv run pytest tests/unit -v

# Integration only (uses temp DuckDB)
uv run pytest tests/integration -v
```

## Linting

```bash
uv run ruff check src tests
uv run ruff format --check src tests
```

## Investigating quarantined records

```sql
-- Connect to DuckDB
-- duckdb data/warehouse.duckdb

SELECT rejection_reason, COUNT(*) AS n
FROM raw.raw_quarantine
GROUP BY rejection_reason
ORDER BY n DESC;

SELECT * FROM raw.raw_quarantine LIMIT 20;
```

## Adding a new source CSV file

1. Place the CSV in `data/raw/used_cars/`
2. Add the filename to `INGESTIBLE_FILES` in [`discovery.py`](../src/automarket/ingestion/discovery.py)
3. Add the make mapping to `MAKE_FROM_FILENAME`
4. Add column mapping if the file uses a different column name
5. Run ingestion with `--full-refresh`
6. Run `uv run pytest tests/` to verify

## Key file locations

| Path | Purpose |
|---|---|
| `data/raw/used_cars/` | Source CSV files (unchanged) |
| `data/warehouse.duckdb` | DuckDB warehouse (generated — not committed) |
| `data/run_log.jsonl` | Append-only pipeline run log |
| `dbt/target/` | dbt compilation artifacts (not committed) |
| `dbt/logs/` | dbt logs (not committed) |

## Common issues

**"No ingestible CSV files found"**
- Check that `data/raw/used_cars/` exists and contains the CSV files
- Confirm filenames match `INGESTIBLE_FILES` in `discovery.py`

**dbt cannot open DuckDB file**
- Set `DUCKDB_PATH` to the absolute path: `$env:DUCKDB_PATH=(Resolve-Path "data\warehouse.duckdb").Path`
- dbt resolves relative paths from its working directory, which may differ

**"Cannot open file ... warehouse.duckdb: locked"**
- Another process (e.g. DBeaver, Python REPL) has the file open
- Close other connections and retry

**dbt "schema raw does not exist"** (local DuckDB)
- The Python ingestion has not been run, or was run against a different DuckDB file
- Run ingestion first: `uv run python -m automarket.cli ingest ...`

**dbt "relation not found"** (Snowflake)
- Run `automarket load-snowflake <run_id>` to load RAW data first
- Verify `SNOWFLAKE_DATABASE` matches `AUTOMARKET_DB` in setup.sql

---

## Cloud pipeline runbook

### Manual cloud run

```bash
export RUN_ID="$(date +%Y%m%d)-manual-001"

# 1. Upload source CSVs + normalized Parquet to S3
uv run python -m automarket.cli upload-s3 \
  --data-dir data/raw/used_cars --run-id "$RUN_ID"

# 2. Load Parquet into Snowflake RAW (COPY INTO)
uv run python -m automarket.cli load-snowflake "$RUN_ID"

# 3. Build dbt on Snowflake
$env:SNOWFLAKE_DATABASE="AUTOMARKET_DB"
.venv\Scripts\python.exe -c "from dbt.cli.main import cli; cli()" `
  -- build --project-dir dbt --profiles-dir dbt --target snowflake
```

Or: `make cloud-pipeline RUN_ID=2026-10-20-001`

### Idempotent re-run

```bash
# Skip S3 objects that already exist
uv run python -m automarket.cli upload-s3 \
  --data-dir data/raw/used_cars --run-id "$RUN_ID" --skip-existing

# Snowflake: COPY INTO FORCE=FALSE skips already-loaded files automatically
uv run python -m automarket.cli load-snowflake "$RUN_ID"
```

### Diagnose failed S3 upload

- Check `AWS_DEFAULT_REGION` and `S3_RAW_BUCKET` are set
- Verify IAM: `s3:PutObject` on `arn:aws:s3:::<bucket>/raw/*`
- CI OIDC: confirm `AWS_OIDC_ROLE_ARN` secret and trust policy match GitHub repo

### Diagnose failed Snowflake load

- Verify stage: `LIST @RAW.S3_STAGE_AUTOMARKET;`
- Check integration: `DESC INTEGRATION S3_INT_AUTOMARKET;`
  → Confirm `STORAGE_AWS_IAM_USER_ARN` is in IAM trust policy
  → Confirm `STORAGE_AWS_EXTERNAL_ID` matches `sts:ExternalId` condition
- View load history in Snowflake:
  ```sql
  SELECT * FROM TABLE(INFORMATION_SCHEMA.COPY_HISTORY(
    TABLE_NAME=>'RAW_USED_CAR_LISTINGS',
    START_TIME=>DATEADD(hour,-24,CURRENT_TIMESTAMP())));
  ```

### Verify Snowflake row counts

```sql
SELECT COUNT(*) FROM AUTOMARKET_DB.RAW.RAW_USED_CAR_LISTINGS;
-- Expected: ~108,539

SELECT SOURCE_FILE, COUNT(*) FROM AUTOMARKET_DB.RAW.RAW_USED_CAR_LISTINGS
GROUP BY SOURCE_FILE ORDER BY SOURCE_FILE;
```

### Cloud file locations

| Path | Purpose |
|---|---|
| `infra/snowflake/setup.sql` | Snowflake bootstrap DDL (idempotent) |
| `infra/terraform/` | AWS S3 + IAM Terraform module |
| `.github/workflows/nightly_snowflake.yml` | Scheduled cloud CI workflow |
| `src/automarket/storage/s3.py` | S3 upload module |
| `src/automarket/storage/snowflake_loader.py` | Snowflake COPY INTO loader |
| `src/automarket/storage/serializer.py` | Parquet serializer |
