.PHONY: install lint test ingest dbt-deps dbt-build dbt-test report demo simulate clean

# ── Developer setup ────────────────────────────────────────────────────────
install:
	uv pip install -e ".[dev]"

install-cloud:
	uv pip install -e ".[dev,cloud]"

lint:
	uv run ruff check src tests
	uv run ruff format --check src tests

format:
	uv run ruff format src tests
	uv run ruff check --fix src tests

# ── Tests ──────────────────────────────────────────────────────────────────
test:
	uv run pytest tests/unit tests/integration -v

test-unit:
	uv run pytest tests/unit -v

test-integration:
	uv run pytest tests/integration -v

# ── Pipeline ───────────────────────────────────────────────────────────────
ingest:
	uv run python -m automarket.cli ingest \
		--data-dir data/raw/used_cars \
		--duckdb-path data/warehouse.duckdb

ingest-fresh:
	uv run python -m automarket.cli ingest \
		--data-dir data/raw/used_cars \
		--duckdb-path data/warehouse.duckdb \
		--full-refresh

report:
	uv run python -m automarket.cli report \
		--duckdb-path data/warehouse.duckdb

# ── dbt ───────────────────────────────────────────────────────────────────
dbt-deps:
	cd dbt && uv run dbt deps

dbt-build:
	cd dbt && uv run dbt build --target duckdb

dbt-test:
	cd dbt && uv run dbt test --target duckdb

# ── End-to-end demo ───────────────────────────────────────────────────────
demo: ingest dbt-build report
	@echo ""
	@echo "==> Demo complete. DuckDB warehouse: data/warehouse.duckdb"
	@echo "==> Run 'make report' to see the analytical summary."

# ── Optional simulation ────────────────────────────────────────────────────
simulate:
	uv run python -m automarket.cli simulate \
		--duckdb-path data/warehouse.duckdb \
		--seed 42 \
		--weeks 8 \
		--sample-size 1000

# ── Cloud pipeline ─────────────────────────────────────────────────────────
# Requires: AWS credentials + SNOWFLAKE_* env vars (see .env.example)
# Set RUN_ID before each cloud run: make upload-s3 RUN_ID=myrun-001
RUN_ID ?= $(shell python -c "import uuid; print(str(uuid.uuid4())[:8])")

upload-s3:
	uv run python -m automarket.cli upload-s3 \
		--data-dir data/raw/used_cars \
		--run-id $(RUN_ID)

upload-s3-skip-existing:
	uv run python -m automarket.cli upload-s3 \
		--data-dir data/raw/used_cars \
		--run-id $(RUN_ID) \
		--skip-existing

load-snowflake:
	uv run python -m automarket.cli load-snowflake $(RUN_ID)

dbt-build-snowflake:
	cd dbt && uv run dbt build --target snowflake

dbt-test-snowflake:
	cd dbt && uv run dbt test --target snowflake

# Full cloud pipeline: upload → load → dbt
cloud-pipeline: upload-s3 load-snowflake dbt-build-snowflake
	@echo ""
	@echo "==> Cloud pipeline complete for RUN_ID=$(RUN_ID)"

# ── Housekeeping ───────────────────────────────────────────────────────────
clean:
	python -c "import os; [os.remove(f) for f in ['data/warehouse.duckdb', 'data/warehouse.duckdb.wal', 'data/run_log.jsonl'] if os.path.exists(f)]"
	-if exist dbt\target rmdir /s /q dbt\target
	-if exist dbt\logs rmdir /s /q dbt\logs
	-if exist dbt\dbt_packages rmdir /s /q dbt\dbt_packages
