"""Integration tests for the ingestion pipeline using real CSV fixtures.

These tests use real (small) CSV fixtures that match the actual source schema,
and a temporary DuckDB database. They do not require any network or cloud access.
"""

import sys
import csv
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import pytest
import duckdb

from automarket.ingestion.pipeline import run_ingestion, read_and_normalize


# ── Fixtures ────────────────────────────────────────────────────────────────

VALID_ROWS = [
    {"model": " Fiesta", "year": "2018", "price": "8000", "transmission": "Manual",
     "mileage": "25000", "fuelType": "Petrol", "tax": "150", "mpg": "55.4", "engineSize": "1.0"},
    {"model": " Focus", "year": "2019", "price": "12000", "transmission": "Automatic",
     "mileage": "15000", "fuelType": "Diesel", "tax": "130", "mpg": "60.1", "engineSize": "1.5"},
    {"model": " Kuga", "year": "2017", "price": "15000", "transmission": "Manual",
     "mileage": "40000", "fuelType": "Petrol", "tax": "165", "mpg": "45.0", "engineSize": "2.0"},
]

INVALID_ROWS = [
    # price too low
    {"model": " Ka", "year": "2015", "price": "50", "transmission": "Manual",
     "mileage": "60000", "fuelType": "Petrol", "tax": "145", "mpg": "55.0", "engineSize": "1.0"},
    # year out of range
    {"model": " Galaxy", "year": "2060", "price": "9000", "transmission": "Automatic",
     "mileage": "30000", "fuelType": "Diesel", "tax": "150", "mpg": "50.0", "engineSize": "2.0"},
    # missing fuel type (empty string — must be rejected after normalization fix)
    {"model": " Puma", "year": "2020", "price": "18000", "transmission": "Manual",
     "mileage": "5000", "fuelType": "", "tax": "150", "mpg": "55.0", "engineSize": "1.0"},
]

FIELDNAMES = ["model", "year", "price", "transmission", "mileage",
              "fuelType", "tax", "mpg", "engineSize"]


def write_fixture_csv(path: Path, rows: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


@pytest.fixture
def fixture_csv_dir(tmp_path):
    """Create a temporary data dir with a ford.csv fixture."""
    write_fixture_csv(tmp_path / "ford.csv", VALID_ROWS + INVALID_ROWS)
    return tmp_path


@pytest.fixture
def valid_only_csv_dir(tmp_path):
    """Create a temporary data dir with only valid rows."""
    write_fixture_csv(tmp_path / "ford.csv", VALID_ROWS)
    return tmp_path


@pytest.fixture
def tmp_db(tmp_path):
    return tmp_path / "test_warehouse.duckdb"


# ── Tests ────────────────────────────────────────────────────────────────────

class TestReadAndNormalize:
    def test_accepts_valid_rows(self, valid_only_csv_dir):
        path = valid_only_csv_dir / "ford.csv"
        accepted, rejected = read_and_normalize(path)
        assert len(accepted) == len(VALID_ROWS)
        assert len(rejected) == 0

    def test_rejects_invalid_rows(self, fixture_csv_dir):
        path = fixture_csv_dir / "ford.csv"
        accepted, rejected = read_and_normalize(path)
        assert len(accepted) == len(VALID_ROWS)
        assert len(rejected) == len(INVALID_ROWS)

    def test_rejected_rows_have_reason(self, fixture_csv_dir):
        path = fixture_csv_dir / "ford.csv"
        _, rejected = read_and_normalize(path)
        for row in rejected:
            assert "rejection_reason" in row
            assert row["rejection_reason"]

    def test_make_inferred_from_filename(self, valid_only_csv_dir):
        path = valid_only_csv_dir / "ford.csv"
        accepted, _ = read_and_normalize(path)
        assert all(r["make"] == "Ford" for r in accepted)

    def test_model_stripped(self, valid_only_csv_dir):
        path = valid_only_csv_dir / "ford.csv"
        accepted, _ = read_and_normalize(path)
        assert all(not r["model"].startswith(" ") for r in accepted)

    def test_source_file_set(self, valid_only_csv_dir):
        path = valid_only_csv_dir / "ford.csv"
        accepted, _ = read_and_normalize(path)
        assert all(r["source_file"] == "ford.csv" for r in accepted)

    def test_row_id_deterministic(self, valid_only_csv_dir):
        """Running twice on the same file gives identical row IDs."""
        path = valid_only_csv_dir / "ford.csv"
        a1, _ = read_and_normalize(path)
        a2, _ = read_and_normalize(path)
        assert [r["row_id"] for r in a1] == [r["row_id"] for r in a2]


class TestRunIngestion:
    def test_ingestion_loads_accepted_rows(self, fixture_csv_dir, tmp_db):
        stats = run_ingestion(fixture_csv_dir, tmp_db)
        assert stats.rows_accepted == len(VALID_ROWS)
        assert stats.rows_rejected == len(INVALID_ROWS)

        con = duckdb.connect(str(tmp_db))
        count = con.execute("SELECT COUNT(*) FROM raw.raw_used_car_listings").fetchone()[0]
        quarantine_count = con.execute("SELECT COUNT(*) FROM raw.raw_quarantine").fetchone()[0]
        con.close()

        assert count == len(VALID_ROWS)
        assert quarantine_count == len(INVALID_ROWS)

    def test_ingestion_idempotent(self, fixture_csv_dir, tmp_db):
        """Running ingestion twice should not duplicate rows."""
        run_ingestion(fixture_csv_dir, tmp_db)
        run_ingestion(fixture_csv_dir, tmp_db)

        con = duckdb.connect(str(tmp_db))
        count = con.execute("SELECT COUNT(*) FROM raw.raw_used_car_listings").fetchone()[0]
        con.close()

        assert count == len(VALID_ROWS)

    def test_full_refresh_clears_and_reloads(self, fixture_csv_dir, tmp_db):
        run_ingestion(fixture_csv_dir, tmp_db)
        run_ingestion(fixture_csv_dir, tmp_db, full_refresh=True)

        con = duckdb.connect(str(tmp_db))
        count = con.execute("SELECT COUNT(*) FROM raw.raw_used_car_listings").fetchone()[0]
        con.close()

        assert count == len(VALID_ROWS)

    def test_no_ingestible_files_returns_zero(self, tmp_path, tmp_db):
        # Write only unclean files (excluded)
        (tmp_path / "unclean cclass.csv").write_text("junk")
        stats = run_ingestion(tmp_path, tmp_db)
        assert stats.rows_accepted == 0
        assert stats.files_processed == 0

    def test_stats_files_discovered(self, fixture_csv_dir, tmp_db):
        stats = run_ingestion(fixture_csv_dir, tmp_db)
        assert stats.files_discovered == 1
        assert stats.files_processed == 1

    def test_rejection_reasons_tracked(self, fixture_csv_dir, tmp_db):
        stats = run_ingestion(fixture_csv_dir, tmp_db)
        assert stats.rows_rejected == len(INVALID_ROWS)
        assert len(stats.rejection_reasons) > 0
