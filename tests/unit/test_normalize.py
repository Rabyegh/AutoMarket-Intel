"""Unit tests for normalization functions."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import pytest

from automarket.ingestion.normalize import (
    normalize_fuel_type,
    normalize_model,
    normalize_transmission,
    parse_float_field,
    parse_mileage,
    parse_price,
    parse_tax,
    parse_year,
)


class TestNormalizeFuelType:
    def test_petrol(self):
        assert normalize_fuel_type("Petrol") == "Petrol"

    def test_diesel(self):
        assert normalize_fuel_type("Diesel") == "Diesel"

    def test_hybrid(self):
        assert normalize_fuel_type("Hybrid") == "Hybrid"

    def test_electric(self):
        assert normalize_fuel_type("Electric") == "Electric"

    def test_plugin_hybrid_maps_to_hybrid(self):
        assert normalize_fuel_type("Plugin Hybrid") == "Hybrid"

    def test_unknown_maps_to_other(self):
        assert normalize_fuel_type("Hydrogen") == "Other"

    def test_case_insensitive(self):
        assert normalize_fuel_type("petrol") == "Petrol"

    def test_whitespace_stripped(self):
        assert normalize_fuel_type("  Diesel  ") == "Diesel"


class TestNormalizeTransmission:
    def test_manual(self):
        assert normalize_transmission("Manual") == "Manual"

    def test_automatic(self):
        assert normalize_transmission("Automatic") == "Automatic"

    def test_semi_auto(self):
        assert normalize_transmission("Semi-Auto") == "Semi-Auto"

    def test_semi_auto_space(self):
        assert normalize_transmission("Semi Auto") == "Semi-Auto"

    def test_unknown_maps_to_other(self):
        assert normalize_transmission("CVT") == "Other"


class TestParsePrice:
    def test_integer_string(self):
        assert parse_price("12500") == 12500

    def test_comma_formatted(self):
        assert parse_price("12,500") == 12500

    def test_gbp_symbol(self):
        assert parse_price("£12,500") == 12500

    def test_gbp_with_space(self):
        assert parse_price(" £12,500") == 12500

    def test_invalid_returns_none(self):
        assert parse_price("n/a") is None

    def test_empty_returns_none(self):
        assert parse_price("") is None

    def test_float_rounds_to_int(self):
        assert parse_price("12500.99") == 12500


class TestParseYear:
    def test_valid_year(self):
        assert parse_year("2017") == 2017

    def test_old_year(self):
        assert parse_year("1997") == 1997

    def test_invalid_returns_none(self):
        assert parse_year("abc") is None

    def test_empty_returns_none(self):
        assert parse_year("") is None


class TestParseMileage:
    def test_plain_integer(self):
        assert parse_mileage("15735") == 15735

    def test_comma_formatted(self):
        assert parse_mileage("15,735") == 15735

    def test_zero(self):
        assert parse_mileage("0") == 0

    def test_invalid_returns_none(self):
        assert parse_mileage("unknown") is None


class TestParseFloatField:
    def test_mpg(self):
        assert parse_float_field("55.4") == pytest.approx(55.4)

    def test_engine_size(self):
        assert parse_float_field("1.4") == pytest.approx(1.4)

    def test_empty_string_returns_none(self):
        assert parse_float_field("") is None

    def test_none_returns_none(self):
        assert parse_float_field(None) is None


class TestNormalizeModel:
    def test_strips_leading_space(self):
        assert normalize_model(" A1") == "A1"

    def test_strips_trailing_space(self):
        assert normalize_model("A1 ") == "A1"

    def test_preserves_case(self):
        assert normalize_model(" C Class") == "C Class"


class TestParseTax:
    def test_plain_integer(self):
        assert parse_tax("150") == 150

    def test_none_returns_none(self):
        assert parse_tax(None) is None

    def test_empty_returns_none(self):
        assert parse_tax("") is None
