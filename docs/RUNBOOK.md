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

**dbt "schema raw does not exist"**
- The Python ingestion has not been run, or was run against a different DuckDB file
- Run ingestion first: `uv run python -m automarket.cli ingest ...`
