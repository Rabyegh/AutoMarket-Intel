"""Unit tests for validation rules."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import pytest
from automarket.ingestion.validation import validate_record, YEAR_MIN, YEAR_MAX


def _valid_row(**overrides):
    """Build a minimal valid row dict, with optional field overrides."""
    base = {
        "make": "Ford",
        "model": "Fiesta",
        "year": 2018,
        "price_gbp": 8000,
        "transmission": "Manual",
        "mileage_miles": 25000,
        "fuel_type": "Petrol",
        "engine_size_l": 1.0,
    }
    base.update(overrides)
    return base


class TestValidRecord:
    def test_valid_row_passes(self):
        result = validate_record(_valid_row())
        assert result.is_valid
        assert result.rejection_reason is None

    def test_valid_row_with_optional_nulls(self):
        row = _valid_row()
        row["tax_gbp"] = None
        row["mpg"] = None
        result = validate_record(row)
        assert result.is_valid


class TestMissingFields:
    def test_missing_make(self):
        result = validate_record(_valid_row(make=""))
        assert not result.is_valid
        assert "make is missing" in result.rejection_reason

    def test_missing_model(self):
        result = validate_record(_valid_row(model=""))
        assert not result.is_valid
        assert "model is missing" in result.rejection_reason

    def test_missing_fuel_type(self):
        result = validate_record(_valid_row(fuel_type=""))
        assert not result.is_valid
        assert "fuel_type is missing" in result.rejection_reason

    def test_missing_transmission(self):
        result = validate_record(_valid_row(transmission=""))
        assert not result.is_valid
        assert "transmission is missing" in result.rejection_reason


class TestYearValidation:
    def test_year_too_low(self):
        result = validate_record(_valid_row(year=1960))
        assert not result.is_valid
        assert "year" in result.rejection_reason

    def test_year_too_high(self):
        result = validate_record(_valid_row(year=2060))
        assert not result.is_valid
        assert "year" in result.rejection_reason

    def test_year_at_lower_bound(self):
        result = validate_record(_valid_row(year=YEAR_MIN))
        assert result.is_valid

    def test_year_at_upper_bound(self):
        result = validate_record(_valid_row(year=YEAR_MAX))
        assert result.is_valid

    def test_year_none_fails(self):
        result = validate_record(_valid_row(year=None))
        assert not result.is_valid


class TestPriceValidation:
    def test_price_too_low(self):
        result = validate_record(_valid_row(price_gbp=50))
        assert not result.is_valid
        assert "price_gbp" in result.rejection_reason

    def test_price_too_high(self):
        result = validate_record(_valid_row(price_gbp=600_000))
        assert not result.is_valid
        assert "price_gbp" in result.rejection_reason

    def test_price_none_fails(self):
        result = validate_record(_valid_row(price_gbp=None))
        assert not result.is_valid


class TestMileageValidation:
    def test_negative_mileage(self):
        result = validate_record(_valid_row(mileage_miles=-1))
        assert not result.is_valid
        assert "mileage_miles" in result.rejection_reason

    def test_mileage_too_high(self):
        result = validate_record(_valid_row(mileage_miles=600_000))
        assert not result.is_valid

    def test_zero_mileage_valid(self):
        result = validate_record(_valid_row(mileage_miles=0))
        assert result.is_valid

    def test_mileage_none_fails(self):
        result = validate_record(_valid_row(mileage_miles=None))
        assert not result.is_valid


class TestEngineSize:
    def test_implausible_engine_size_fails(self):
        result = validate_record(_valid_row(engine_size_l=15.0))
        assert not result.is_valid
        assert "engine_size_l" in result.rejection_reason

    def test_none_engine_size_ok(self):
        result = validate_record(_valid_row(engine_size_l=None))
        assert result.is_valid


class TestMultipleReasons:
    def test_multiple_failures_collected(self):
        result = validate_record(_valid_row(make="", year=1960, price_gbp=50))
        assert not result.is_valid
        assert len(result.reasons) >= 3
