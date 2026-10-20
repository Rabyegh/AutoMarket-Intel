"""Validation rules for used-car listing records.

Each function returns (is_valid: bool, reason: str | None).
The caller collects all failing checks and assigns the record to the
quarantine table with a concatenated rejection reason string.

Validation is intentionally strict on critical fields (price, year,
mileage) and lenient on optional fields (mpg, tax, engine_size).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Validation bounds — can be overridden via Config
YEAR_MIN = 1970
YEAR_MAX = 2025
PRICE_MIN_GBP = 100
PRICE_MAX_GBP = 500_000
MILEAGE_MAX_MILES = 500_000


@dataclass
class ValidationResult:
    """Outcome of validating one record."""

    is_valid: bool
    reasons: list[str] = field(default_factory=list)

    @property
    def rejection_reason(self) -> str | None:
        return "; ".join(self.reasons) if self.reasons else None


def validate_record(row: dict[str, Any]) -> ValidationResult:
    """Apply all validation rules to a normalised row dict.

    Expected keys: make, model, year, price_gbp, transmission,
                   mileage_miles, fuel_type, engine_size_l.
    Optional keys: tax_gbp, mpg.

    Returns a ValidationResult with is_valid=False and a list of
    human-readable reasons if any critical check fails.
    """
    reasons: list[str] = []

    # ── make ────────────────────────────────────────────────────────────────
    if not _nonempty(row.get("make")):
        reasons.append("make is missing")

    # ── model ───────────────────────────────────────────────────────────────
    if not _nonempty(row.get("model")):
        reasons.append("model is missing")

    # ── year ────────────────────────────────────────────────────────────────
    year = _parse_int(row.get("year"))
    if year is None:
        reasons.append("year is not a valid integer")
    elif year < YEAR_MIN or year > YEAR_MAX:
        reasons.append(f"year {year} is outside acceptable range {YEAR_MIN}–{YEAR_MAX}")

    # ── price ───────────────────────────────────────────────────────────────
    price = _parse_int(row.get("price_gbp"))
    if price is None:
        reasons.append("price_gbp is not a valid integer")
    elif price < PRICE_MIN_GBP:
        reasons.append(f"price_gbp {price} is below minimum {PRICE_MIN_GBP}")
    elif price > PRICE_MAX_GBP:
        reasons.append(f"price_gbp {price} exceeds maximum {PRICE_MAX_GBP}")

    # ── mileage ─────────────────────────────────────────────────────────────
    mileage = _parse_int(row.get("mileage_miles"))
    if mileage is None:
        reasons.append("mileage_miles is not a valid integer")
    elif mileage < 0:
        reasons.append(f"mileage_miles {mileage} is negative")
    elif mileage > MILEAGE_MAX_MILES:
        reasons.append(f"mileage_miles {mileage} exceeds maximum {MILEAGE_MAX_MILES}")

    # ── fuel_type ───────────────────────────────────────────────────────────
    fuel = str(row.get("fuel_type", "")).strip()
    if not fuel:
        reasons.append("fuel_type is missing")

    # ── transmission ────────────────────────────────────────────────────────
    trans = str(row.get("transmission", "")).strip()
    if not trans:
        reasons.append("transmission is missing")

    # ── engine_size ─────────────────────────────────────────────────────────
    engine = _parse_float(row.get("engine_size_l"))
    if engine is not None and (engine < 0.0 or engine > 10.0):
        reasons.append(f"engine_size_l {engine} is implausible")

    return ValidationResult(is_valid=len(reasons) == 0, reasons=reasons)


# ── helpers ─────────────────────────────────────────────────────────────────


def _nonempty(val: Any) -> bool:
    return val is not None and str(val).strip() != ""


def _parse_int(val: Any) -> int | None:
    if val is None:
        return None
    try:
        return int(str(val).strip().replace(",", ""))
    except (ValueError, TypeError):
        return None


def _parse_float(val: Any) -> float | None:
    if val is None or str(val).strip() == "":
        return None
    try:
        return float(str(val).strip().replace(",", ""))
    except (ValueError, TypeError):
        return None
