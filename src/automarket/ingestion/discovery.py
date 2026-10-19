"""CSV discovery and schema normalization for used-car listing files.

The dataset contains two schema variants:

Schema A (9 columns, most files):
    model, year, price, transmission, mileage, fuelType, tax, mpg, engineSize

Schema B (7 columns — cclass.csv, focus.csv):
    model, year, price, transmission, mileage, fuelType, engineSize
    (no tax, no mpg)

Schema C (11 columns — unclean files, raw scrape format):
    model, year, price, transmission, mileage, fuel type, engine size,
    mileage2, fuel type2, engine size2, reference
    (price is GBP-formatted string; mileage is comma-formatted in mileage2)

The unclean files are kept as raw source references. They are NOT ingested
into the main pipeline because they contain duplicate, malformed data that
would require non-trivial reconciliation. Their existence is documented.

The `make` is inferred from the source filename (e.g. audi.csv → Audi).

Note: this dataset is a static snapshot. It does not contain listing
publication timestamps. The `source_file` column preserves provenance.
"""

from __future__ import annotations

import re
from pathlib import Path


# Mapping from normalized filename stem → canonical make name
MAKE_FROM_FILENAME: dict[str, str] = {
    "audi": "Audi",
    "bmw": "BMW",
    "ford": "Ford",
    "hyundi": "Hyundai",
    "merc": "Mercedes-Benz",
    "skoda": "Skoda",
    "toyota": "Toyota",
    "vauxhall": "Vauxhall",
    "vw": "Volkswagen",
    "cclass": "Mercedes-Benz",
    "focus": "Ford",
}

# Files to ingest (schema A + B). Unclean files are excluded by default.
INGESTIBLE_FILES: set[str] = {
    "audi.csv", "bmw.csv", "ford.csv", "hyundi.csv", "merc.csv",
    "skoda.csv", "toyota.csv", "vauxhall.csv", "vw.csv",
    "cclass.csv", "focus.csv",
}

# Files present in the dataset but excluded from the default pipeline
# with the reason documented here.
EXCLUDED_FILES: dict[str, str] = {
    "unclean cclass.csv": (
        "Raw scrape format with split columns, GBP-formatted price strings, "
        "and missing mileage in the primary column. Retained as source reference."
    ),
    "unclean focus.csv": (
        "Raw scrape format — same issues as 'unclean cclass.csv'."
    ),
}

# Canonical column names after normalization
CANONICAL_COLUMNS = [
    "source_file",
    "make",
    "model",
    "year",
    "price_gbp",
    "transmission",
    "mileage_miles",
    "fuel_type",
    "tax_gbp",          # nullable — not present in Schema B
    "mpg",              # nullable — not present in Schema B
    "engine_size_l",
]

# Raw column → canonical name mapping (handles both fuelType and fuel type etc.)
_COLUMN_MAP: dict[str, str] = {
    "model": "model",
    "year": "year",
    "price": "price_gbp",
    "transmission": "transmission",
    "mileage": "mileage_miles",
    "fueltype": "fuel_type",
    "fuel type": "fuel_type",
    "tax": "tax_gbp",
    "tax(£)": "tax_gbp",
    "tax(?)": "tax_gbp",   # encoding artefact from hyundi.csv
    "mpg": "mpg",
    "enginesize": "engine_size_l",
    "engine size": "engine_size_l",
}


def _normalize_col(raw: str) -> str:
    """Lower, strip, remove currency symbols and brackets, collapse spaces."""
    s = raw.strip().lower()
    s = re.sub(r"[£\$€\(\)]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def discover_files(data_dir: Path) -> list[Path]:
    """Return list of ingestible CSV files found in data_dir, sorted."""
    found = sorted(f for f in data_dir.glob("*.csv") if f.name in INGESTIBLE_FILES)
    return found


def make_from_filename(path: Path) -> str:
    """Infer the canonical make name from the CSV filename stem."""
    stem = path.stem.lower().replace(" ", "").replace("-", "")
    return MAKE_FROM_FILENAME.get(stem, path.stem.title())


def map_columns(raw_columns: list[str]) -> dict[str, str]:
    """Return {raw_col → canonical_col} for columns we recognise.

    Unknown columns are mapped to None (caller decides what to do).
    """
    mapping: dict[str, str] = {}
    for raw in raw_columns:
        key = _normalize_col(raw)
        # Handle hyundi.csv tax column with encoding artefact
        if key.startswith("tax"):
            key = "tax_gbp" if "tax" in key else key
            mapping[raw] = "tax_gbp"
            continue
        canonical = _COLUMN_MAP.get(key)
        if canonical:
            mapping[raw] = canonical
    return mapping
