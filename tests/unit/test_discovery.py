"""Unit tests for CSV discovery and column mapping."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from automarket.ingestion.discovery import (
    EXCLUDED_FILES,
    INGESTIBLE_FILES,
    make_from_filename,
    map_columns,
)


class TestMakeFromFilename:
    def test_audi(self):
        assert make_from_filename(Path("audi.csv")) == "Audi"

    def test_bmw(self):
        assert make_from_filename(Path("bmw.csv")) == "BMW"

    def test_hyundi_maps_to_hyundai(self):
        assert make_from_filename(Path("hyundi.csv")) == "Hyundai"

    def test_merc_maps_to_mercedes(self):
        assert make_from_filename(Path("merc.csv")) == "Mercedes-Benz"

    def test_cclass_maps_to_mercedes(self):
        assert make_from_filename(Path("cclass.csv")) == "Mercedes-Benz"

    def test_focus_maps_to_ford(self):
        assert make_from_filename(Path("focus.csv")) == "Ford"

    def test_vw_maps_to_volkswagen(self):
        assert make_from_filename(Path("vw.csv")) == "Volkswagen"


class TestMapColumns:
    def test_schema_a_columns(self):
        """Standard 9-column schema (audi, bmw, ford, etc.)"""
        cols = [
            "model",
            "year",
            "price",
            "transmission",
            "mileage",
            "fuelType",
            "tax",
            "mpg",
            "engineSize",
        ]
        mapping = map_columns(cols)
        assert mapping["price"] == "price_gbp"
        assert mapping["mileage"] == "mileage_miles"
        assert mapping["fuelType"] == "fuel_type"
        assert mapping["engineSize"] == "engine_size_l"
        assert mapping["tax"] == "tax_gbp"
        assert mapping["mpg"] == "mpg"

    def test_schema_b_columns(self):
        """7-column schema (cclass, focus — no tax or mpg)"""
        cols = ["model", "year", "price", "transmission", "mileage", "fuelType", "engineSize"]
        mapping = map_columns(cols)
        assert "price" in mapping
        assert "tax" not in mapping
        assert "mpg" not in mapping

    def test_hyundi_tax_column_encoding_artefact(self):
        """hyundi.csv has 'tax(£)' or encoding-corrupt variant."""
        cols = [
            "model",
            "year",
            "price",
            "transmission",
            "mileage",
            "fuelType",
            "tax(£)",
            "mpg",
            "engineSize",
        ]
        mapping = map_columns(cols)
        assert mapping.get("tax(£)") == "tax_gbp"

    def test_unknown_column_not_mapped(self):
        cols = ["model", "some_unknown_column"]
        mapping = map_columns(cols)
        assert "some_unknown_column" not in mapping


class TestIngestibleFiles:
    def test_unclean_files_not_in_ingestible(self):
        assert "unclean cclass.csv" not in INGESTIBLE_FILES
        assert "unclean focus.csv" not in INGESTIBLE_FILES

    def test_unclean_files_in_excluded(self):
        assert "unclean cclass.csv" in EXCLUDED_FILES
        assert "unclean focus.csv" in EXCLUDED_FILES

    def test_excluded_has_reason(self):
        for fname, reason in EXCLUDED_FILES.items():
            assert reason, f"{fname} has no exclusion reason"
