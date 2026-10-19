"""Unit tests for the simulation module."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import pytest
from automarket.simulation.snapshots import simulate_snapshots, SimulationConfig
from datetime import date


def _sample_rows(n=10):
    return [
        {
            "row_id": f"abc{i:04d}", "source_file": "ford.csv",
            "make": "Ford", "model": "Fiesta", "registration_year": 2018,
            "price_gbp": 8000 + i * 100, "mileage_miles": 25000 + i * 500,
            "fuel_type": "Petrol", "transmission": "Manual",
            "engine_size_l": 1.0, "tax_gbp": 150, "mpg": 55.4,
        }
        for i in range(n)
    ]


class TestSimulateSnapshots:
    def test_output_row_count(self):
        rows = _sample_rows(5)
        cfg = SimulationConfig(seed=42, weeks=4, sample_size=None)
        snapshots = simulate_snapshots(rows, cfg)
        # 5 listings × 4 weeks = 20 rows
        assert len(snapshots) == 20

    def test_all_rows_marked_is_simulated(self):
        rows = _sample_rows(5)
        snapshots = simulate_snapshots(rows)
        assert all(r["is_simulated"] is True for r in snapshots)

    def test_observation_date_present(self):
        rows = _sample_rows(3)
        snapshots = simulate_snapshots(rows)
        assert all("observation_date" in r for r in snapshots)

    def test_simulated_price_positive(self):
        rows = _sample_rows(10)
        snapshots = simulate_snapshots(rows)
        assert all(r["simulated_price_gbp"] > 0 for r in snapshots)

    def test_deterministic_with_same_seed(self):
        rows = _sample_rows(10)
        cfg = SimulationConfig(seed=99)
        s1 = simulate_snapshots(rows, cfg)
        s2 = simulate_snapshots(rows, cfg)
        assert [r["simulated_price_gbp"] for r in s1] == [r["simulated_price_gbp"] for r in s2]

    def test_different_seeds_differ(self):
        rows = _sample_rows(10)
        s1 = simulate_snapshots(rows, SimulationConfig(seed=1))
        s2 = simulate_snapshots(rows, SimulationConfig(seed=2))
        prices1 = [r["simulated_price_gbp"] for r in s1]
        prices2 = [r["simulated_price_gbp"] for r in s2]
        assert prices1 != prices2

    def test_sample_size_limits_rows(self):
        rows = _sample_rows(100)
        cfg = SimulationConfig(seed=42, weeks=1, sample_size=10)
        snapshots = simulate_snapshots(rows, cfg)
        assert len(snapshots) == 10

    def test_start_date_respected(self):
        rows = _sample_rows(2)
        cfg = SimulationConfig(seed=42, start_date=date(2024, 6, 1), weeks=2)
        snapshots = simulate_snapshots(rows, cfg)
        dates = sorted({r["observation_date"] for r in snapshots})
        assert dates[0] == "2024-06-01"

    def test_source_fields_preserved(self):
        rows = _sample_rows(3)
        snapshots = simulate_snapshots(rows)
        for snap in snapshots:
            assert snap["make"] == "Ford"
            assert snap["source_file"] == "ford.csv"
