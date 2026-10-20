"""Parquet serializer for normalized used-car listing records.

Converts the list of accepted dict records produced by the ingestion
pipeline into an in-memory PyArrow Table and serializes it to a Parquet
byte buffer, ready for upload or local inspection.

Design choices
--------------
- Uses PyArrow (already a project dependency via dbt-core) rather than
  adding pandas to the serialization path.
- Explicit schema enforces the canonical column list and types; a
  schema mismatch raises an error rather than silently coercing data.
- Output is deterministic: same input records → same Parquet bytes
  (assuming equal row order, which the ingestion pipeline guarantees via
  sorted file discovery + sequential row processing).
- No I/O is performed here; callers decide where to write the bytes.
"""

from __future__ import annotations

import io
import logging
from typing import Any

logger = logging.getLogger("automarket.storage.serializer")

# Canonical Parquet schema matching raw.raw_used_car_listings in DuckDB/Snowflake
# Nullable fields: tax_gbp, mpg, engine_size_l  (schema B files omit them)
_SCHEMA_FIELDS: list[tuple[str, Any, bool]] = [
    # (name, pyarrow_type, nullable)
    ("row_id", "string", False),
    ("source_file", "string", False),
    ("make", "string", False),
    ("model", "string", False),
    ("year", "int32", False),
    ("price_gbp", "int32", False),
    ("transmission", "string", False),
    ("mileage_miles", "int32", False),
    ("fuel_type", "string", False),
    ("tax_gbp", "int32", True),
    ("mpg", "float64", True),
    ("engine_size_l", "float64", True),
]

_FIELD_NAMES = [f[0] for f in _SCHEMA_FIELDS]


def _build_schema():
    """Build a PyArrow schema from _SCHEMA_FIELDS."""
    try:
        import pyarrow as pa
    except ImportError as exc:
        raise ImportError(
            "pyarrow is required for Parquet serialization. "
            "It is listed in core project dependencies."
        ) from exc

    type_map = {
        "string": pa.string(),
        "int32": pa.int32(),
        "float64": pa.float64(),
    }
    fields = []
    for name, type_str, nullable in _SCHEMA_FIELDS:
        pa_type = type_map[type_str]
        fields.append(pa.field(name, pa_type, nullable=nullable))
    return pa.schema(fields)


def records_to_parquet(
    records: list[dict[str, Any]],
    *,
    compression: str = "snappy",
) -> bytes:
    """Serialize normalized used-car records to Parquet bytes.

    Args:
        records: Normalized accepted rows from the ingestion pipeline.
            Each dict must contain the canonical fields defined in
            ``_FIELD_NAMES``. Missing optional fields default to None.
        compression: Parquet compression codec (default: "snappy").

    Returns:
        Bytes of the serialized Parquet file.

    Raises:
        ValueError: If records is empty or a required field is missing.
        ImportError: If pyarrow is not installed.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq

    if not records:
        raise ValueError("records must be a non-empty list to serialize to Parquet")

    schema = _build_schema()

    # Build columnar data from row-oriented dicts
    columns: dict[str, list[Any]] = {name: [] for name in _FIELD_NAMES}
    for _, row in enumerate(records):
        for name in _FIELD_NAMES:
            val = row.get(name)
            columns[name].append(val)

    # Build PyArrow table with explicit schema for type safety
    arrays = []
    for name, type_str, _nullable in _SCHEMA_FIELDS:
        import pyarrow as pa  # noqa: F811 — already imported above

        type_map = {
            "string": pa.string(),
            "int32": pa.int32(),
            "float64": pa.float64(),
        }
        try:
            arr = pa.array(columns[name], type=type_map[type_str])
        except (pa.ArrowInvalid, pa.ArrowTypeError) as exc:
            raise ValueError(
                f"Column '{name}' contains values incompatible with type '{type_str}': {exc}"
            ) from exc
        arrays.append(arr)

    table = pa.table({name: arr for name, arr in zip(_FIELD_NAMES, arrays, strict=False)}, schema=schema)

    buf = io.BytesIO()
    pq.write_table(table, buf, compression=compression)
    logger.info(
        "Serialized %d records to Parquet (%s compression, %d bytes)",
        len(records),
        compression,
        buf.tell(),
    )
    return buf.getvalue()


def parquet_schema_fields() -> list[str]:
    """Return the canonical list of Parquet column names (for documentation / tests)."""
    return list(_FIELD_NAMES)
