.PHONY: lint test demo full-refresh clean

# ── Developer helpers ──────────────────────────────────────
lint:
	uv run ruff check src tests
	uv run ruff format --check src tests

format:
	uv run ruff format src tests
	uv run ruff check --fix src tests

test:
	uv run pytest tests/unit -m unit
	uv run pytest tests/integration -m integration

# ── Pipeline ──────────────────────────────────────────────
demo:
	@echo "==> Running end-to-end demo (local, seeded, no network)..."
	uv run vinpipe run --seed 42 --batches 2 --env local --fixture-decodes
	@echo "==> Demo complete. Check data/warehouse.duckdb and docs/run_summary.md"

full-refresh:
	uv run vinpipe run --seed 42 --batches 2 --env local --fixture-decodes --full-refresh

resume:
	uv run vinpipe run --resume

# ── dbt ───────────────────────────────────────────────────
dbt-build:
	cd dbt && uv run dbt build --target duckdb

dbt-test:
	cd dbt && uv run dbt test --target duckdb

# ── Housekeeping ───────────────────────────────────────────
clean:
	rm -f data/warehouse.duckdb data/warehouse.duckdb.wal data/run_log.json
	rm -rf dbt/target dbt/logs
