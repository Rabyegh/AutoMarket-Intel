"""Core ingestion pipeline: reads CSVs, normalizes, validates, splits
accepted vs quarantined records, and loads into DuckDB.

Usage (via CLI):
    python -m automarket.ingestion.pipeline --data-dir data/raw/used_cars

This module is deterministic: running it twice on the same input data
produces the same result. It uses a delete-then-insert strategy in DuckDB
to ensure idempotency — running it again does not create duplicate rows.
"""

from __future__ import annotations

import csv
import hashlib
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("automarket")

from automarket.ingestion.discovery import (
    EXCLUDED_FILES,
    discover_files,
    make_from_filename,
    map_columns,
)
from automarket.ingestion.normalize import (
    normalize_fuel_type,
    normalize_make,
    normalize_model,
    normalize_transmission,
    parse_float_field,
    parse_mileage,
    parse_price,
    parse_tax,
    parse_year,
)
from automarket.ingestion.validation import validate_record


@dataclass
class IngestionStats:
    """Summary statistics produced by the ingestion pipeline."""

    files_discovered: int = 0
    files_processed: int = 0
    rows_read: int = 0
    rows_accepted: int = 0
    rows_rejected: int = 0
    rejection_reasons: dict[str, int] = field(default_factory=dict)
    duration_s: float = 0.0

    def report(self) -> str:
        lines = [
            "=== Ingestion Summary ===",
            f"Files discovered : {self.files_discovered}",
            f"Files processed  : {self.files_processed}",
            f"Rows read        : {self.rows_read}",
            f"Rows accepted    : {self.rows_accepted}",
            f"Rows rejected    : {self.rows_rejected}",
        ]
        if self.rejection_reasons:
            lines.append("Rejection reasons (top):")
            for reason, count in sorted(
                self.rejection_reasons.items(), key=lambda x: -x[1]
            )[:10]:
                lines.append(f"  {count:>6}  {reason}")
        lines.append(f"Duration         : {self.duration_s:.1f}s")
        return "\n".join(lines)


def _row_hash(source_file: str, row_index: int, row: dict[str, Any]) -> str:
    """Deterministic row identifier based on source file + position + key fields."""
    payload = f"{source_file}|{row_index}|{row.get('model','')}|{row.get('year','')}|{row.get('price_gbp','')}|{row.get('mileage_miles','')}"
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _normalize_row(
    raw_row: dict[str, str],
    col_map: dict[str, str],
    make: str,
    source_file: str,
    row_index: int,
) -> dict[str, Any]:
    """Convert a raw CSV row dict to a normalised record dict."""
    # Remap raw column names to canonical names
    remapped: dict[str, Any] = {}
    for raw_col, val in raw_row.items():
        canonical = col_map.get(raw_col)
        if canonical:
            remapped[canonical] = val.strip() if isinstance(val, str) else val

    return {
        "row_id": _row_hash(source_file, row_index, remapped),
        "source_file": source_file,
        "make": normalize_make(make),
        "model": normalize_model(remapped.get("model", "")),
        "year": parse_year(remapped.get("year", "")),
        "price_gbp": parse_price(remapped.get("price_gbp", "")),
        "transmission": normalize_transmission(remapped.get("transmission", "")),
        "mileage_miles": parse_mileage(remapped.get("mileage_miles", "")),
        "fuel_type": normalize_fuel_type(remapped.get("fuel_type", "")),
        "tax_gbp": parse_tax(remapped.get("tax_gbp")),
        "mpg": parse_float_field(remapped.get("mpg")),
        "engine_size_l": parse_float_field(remapped.get("engine_size_l")),
    }


def read_and_normalize(csv_path: Path) -> tuple[list[dict], list[dict]]:
    """Read a CSV file and return (accepted_rows, quarantined_rows).

    Each quarantined row includes a 'rejection_reason' field.
    Original source values are NOT modified; normalized values replace
    the raw values in the accepted output (raw is available via source_file).
    """
    make = make_from_filename(csv_path)
    source_file = csv_path.name
    accepted: list[dict] = []
    quarantined: list[dict] = []

    with open(csv_path, encoding="utf-8", errors="replace") as fh:
        reader = csv.DictReader(fh)
        col_map = map_columns(reader.fieldnames or [])

        for row_index, raw_row in enumerate(reader, start=1):
            normalized = _normalize_row(raw_row, col_map, make, source_file, row_index)
            result = validate_record(normalized)

            if result.is_valid:
                accepted.append(normalized)
            else:
                normalized["rejection_reason"] = result.rejection_reason
                quarantined.append(normalized)

    return accepted, quarantined


def run_ingestion(
    data_dir: Path,
    duckdb_path: Path,
    full_refresh: bool = False,
) -> IngestionStats:
    """Discover CSV files, read, normalize, validate, and load into DuckDB.

    Idempotency: each source_file's existing rows are deleted before
    inserting the current normalized output. Running twice produces the
    same row counts.

    Args:
        data_dir: directory containing used-car CSV files
        duckdb_path: path to DuckDB database file
        full_refresh: if True, drop and recreate both tables first

    Returns:
        IngestionStats with counts and duration
    """
    import duckdb

    start = time.time()
    stats = IngestionStats()

    csv_files = discover_files(data_dir)
    stats.files_discovered = len(csv_files)

    if not csv_files:
        logger.error("No ingestible CSV files found in %s", data_dir)
        return stats

    # Log excluded files
    for fname, reason in EXCLUDED_FILES.items():
        if (data_dir / fname).exists():
            logger.warning("Excluded from ingestion: %s — %s", fname, reason)

    # Collect all records
    all_accepted: list[dict] = []
    all_quarantined: list[dict] = []

    for csv_path in csv_files:
        logger.info("Reading %s", csv_path.name)
        try:
            accepted, quarantined = read_and_normalize(csv_path)
            all_accepted.extend(accepted)
            all_quarantined.extend(quarantined)
            stats.files_processed += 1
            stats.rows_read += len(accepted) + len(quarantined)
            stats.rows_accepted += len(accepted)
            stats.rows_rejected += len(quarantined)

            # Tally rejection reasons
            for row in quarantined:
                reason = row.get("rejection_reason", "unknown")
                # Split compound reasons for granular counts
                for part in str(reason).split(";"):
                    key = part.strip()
                    stats.rejection_reasons[key] = stats.rejection_reasons.get(key, 0) + 1

            logger.info(
                "  %s: %d accepted, %d rejected",
                csv_path.name, len(accepted), len(quarantined),
            )
        except Exception as exc:
            logger.error("Failed to read %s: %s", csv_path.name, exc)

    # ── Load into DuckDB ────────────────────────────────────────────────────
    duckdb_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(duckdb_path))

    if full_refresh:
        logger.info("Full refresh: dropping existing raw tables")
        con.execute("DROP TABLE IF EXISTS raw.raw_used_car_listings")
        con.execute("DROP TABLE IF EXISTS raw.raw_quarantine")
        con.execute("DROP SCHEMA IF EXISTS raw")

    # Create schema and tables if not exist
    con.execute("CREATE SCHEMA IF NOT EXISTS raw")
    con.execute("""
        CREATE TABLE IF NOT EXISTS raw.raw_used_car_listings (
            row_id          VARCHAR,
            source_file     VARCHAR,
            make            VARCHAR,
            model           VARCHAR,
            year            INTEGER,
            price_gbp       INTEGER,
            transmission    VARCHAR,
            mileage_miles   INTEGER,
            fuel_type       VARCHAR,
            tax_gbp         INTEGER,
            mpg             DOUBLE,
            engine_size_l   DOUBLE
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS raw.raw_quarantine (
            row_id           VARCHAR,
            source_file      VARCHAR,
            make             VARCHAR,
            model            VARCHAR,
            year             INTEGER,
            price_gbp        INTEGER,
            transmission     VARCHAR,
            mileage_miles    INTEGER,
            fuel_type        VARCHAR,
            tax_gbp          INTEGER,
            mpg              DOUBLE,
            engine_size_l    DOUBLE,
            rejection_reason VARCHAR
        )
    """)

    # Idempotent load: delete existing rows for each source_file, then insert
    processed_files = {r["source_file"] for r in all_accepted + all_quarantined}
    for source_file in processed_files:
        con.execute(
            "DELETE FROM raw.raw_used_car_listings WHERE source_file = ?", [source_file]
        )
        con.execute(
            "DELETE FROM raw.raw_quarantine WHERE source_file = ?", [source_file]
        )

    if all_accepted:
        con.executemany(
            """INSERT INTO raw.raw_used_car_listings VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )""",
            [
                (
                    r["row_id"], r["source_file"], r["make"], r["model"],
                    r["year"], r["price_gbp"], r["transmission"], r["mileage_miles"],
                    r["fuel_type"], r.get("tax_gbp"), r.get("mpg"), r.get("engine_size_l"),
                )
                for r in all_accepted
            ],
        )

    if all_quarantined:
        con.executemany(
            """INSERT INTO raw.raw_quarantine VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )""",
            [
                (
                    r["row_id"], r["source_file"], r["make"], r["model"],
                    r["year"], r.get("price_gbp"), r["transmission"], r.get("mileage_miles"),
                    r["fuel_type"], r.get("tax_gbp"), r.get("mpg"), r.get("engine_size_l"),
                    r.get("rejection_reason"),
                )
                for r in all_quarantined
            ],
        )

    con.close()

    stats.duration_s = round(time.time() - start, 2)
    logger.info("Ingestion complete: %d accepted, %d rejected in %.1fs",
                stats.rows_accepted, stats.rows_rejected, stats.duration_s)
    return stats
