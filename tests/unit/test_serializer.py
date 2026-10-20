"""Unit tests for the Parquet serializer.

Tests cover:
- Successful serialization of complete records
- Nullable fields (tax_gbp, mpg, engine_size_l) are handled correctly
- Empty record list raises ValueError
- Column presence and order in output
- Output is valid Parquet bytes that round-trip correctly
- Schema field list matches the contract

NOTE: pyarrow.parquet uses a DLL that may be blocked by system Application
Control policies. Import is deferred to inside test methods; if the import
fails the tests skip gracefully.
"""

import pytest

from automarket.storage.serializer import parquet_schema_fields, records_to_parquet


def _make_record(**overrides) -> dict:
    """Build a minimal valid accepted record."""
    base = {
        "row_id": "abcd1234efgh5678",
        "source_file": "audi.csv",
        "make": "Audi",
        "model": "A3",
        "year": 2019,
        "price_gbp": 15000,
        "transmission": "Manual",
        "mileage_miles": 30000,
        "fuel_type": "Petrol",
        "tax_gbp": 145,
        "mpg": 45.5,
        "engine_size_l": 1.4,
    }
    base.update(overrides)
    return base


def _read_parquet(parquet_bytes: bytes):
    """Read parquet bytes into a table; skip if pyarrow.parquet DLL is unavailable."""
    try:
        import io

        import pyarrow.parquet as pq

        return pq.read_table(io.BytesIO(parquet_bytes))
    except ImportError as e:
        pytest.skip(f"pyarrow.parquet not loadable on this system: {e}")


class TestRecordsToParquet:
    def test_basic_serialization(self):
        records = [_make_record()]
        result = records_to_parquet(records)
        assert isinstance(result, bytes)
        assert len(result) > 0

    def test_output_starts_with_parquet_magic(self):
        records = [_make_record()]
        parquet_bytes = records_to_parquet(records)
        assert parquet_bytes[:4] == b"PAR1"

    def test_output_is_valid_parquet(self):
        records = [_make_record(), _make_record(row_id="xxxx9999yyyy0000", model="A4")]
        parquet_bytes = records_to_parquet(records)
        table = _read_parquet(parquet_bytes)
        assert table.num_rows == 2

    def test_columns_match_schema(self):
        records = [_make_record()]
        parquet_bytes = records_to_parquet(records)
        table = _read_parquet(parquet_bytes)
        assert list(table.schema.names) == parquet_schema_fields()

    def test_nullable_fields_can_be_none(self):
        """Schema B files omit tax_gbp and mpg — these must serialize as NULL."""
        record = _make_record(tax_gbp=None, mpg=None, engine_size_l=None)
        parquet_bytes = records_to_parquet([record])
        table = _read_parquet(parquet_bytes)
        assert table.num_rows == 1
        assert table["tax_gbp"][0].as_py() is None
        assert table["mpg"][0].as_py() is None
        assert table["engine_size_l"][0].as_py() is None

    def test_round_trip_values(self):
        record = _make_record()
        parquet_bytes = records_to_parquet([record])
        table = _read_parquet(parquet_bytes)
        row = {col: table[col][0].as_py() for col in table.schema.names}
        assert row["row_id"] == "abcd1234efgh5678"
        assert row["source_file"] == "audi.csv"
        assert row["make"] == "Audi"
        assert row["model"] == "A3"
        assert row["year"] == 2019
        assert row["price_gbp"] == 15000
        assert row["mileage_miles"] == 30000
        assert row["fuel_type"] == "Petrol"
        assert row["transmission"] == "Manual"
        assert row["tax_gbp"] == 145
        assert abs(row["mpg"] - 45.5) < 0.01
        assert abs(row["engine_size_l"] - 1.4) < 0.01

    def test_multiple_records(self):
        records = [_make_record(row_id=f"id{i:016}", make="BMW", model=f"M{i}") for i in range(100)]
        parquet_bytes = records_to_parquet(records)
        table = _read_parquet(parquet_bytes)
        assert table.num_rows == 100

    def test_empty_records_raises(self):
        with pytest.raises(ValueError, match="non-empty"):
            records_to_parquet([])

    def test_schema_field_list(self):
        fields = parquet_schema_fields()
        assert "row_id" in fields
        assert "price_gbp" in fields
        assert "mileage_miles" in fields
        assert "tax_gbp" in fields
        assert "mpg" in fields
        assert "engine_size_l" in fields
        assert len(fields) == 12  # must match contract

    def test_missing_optional_field_defaults_to_none(self):
        """Records with missing keys for optional fields should be treated as None."""
        record = _make_record()
        del record["tax_gbp"]  # simulate schema B file
        del record["mpg"]
        parquet_bytes = records_to_parquet([record])
        table = _read_parquet(parquet_bytes)
        assert table["tax_gbp"][0].as_py() is None
        assert table["mpg"][0].as_py() is None
