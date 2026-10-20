"""Normalization helpers — convert raw CSV values to canonical typed forms.

These functions are pure (no I/O) so they can be unit-tested in isolation.
They do NOT destroy original values; the staging dbt model preserves the
raw representation alongside the normalized form where relevant.
"""

from __future__ import annotations

import re

# ── String normalization ─────────────────────────────────────────────────────


def normalize_model(raw: str) -> str:
    """Strip leading/trailing whitespace from model name."""
    return raw.strip()


def normalize_make(raw: str) -> str:
    """Title-case the make, strip whitespace."""
    return raw.strip().title()


def normalize_fuel_type(raw: str) -> str:
    """Canonical fuel type: Petrol | Diesel | Hybrid | Electric | Other.

    Returns an empty string if raw is blank — the validator will catch it
    as a missing required field.
    """
    val = raw.strip()
    if not val:
        return ""
    titled = val.title()
    _MAP = {
        "Petrol": "Petrol",
        "Diesel": "Diesel",
        "Hybrid": "Hybrid",
        "Electric": "Electric",
        "Plugin Hybrid": "Hybrid",
        "Plug-In Hybrid": "Hybrid",
    }
    return _MAP.get(titled, "Other")


def normalize_transmission(raw: str) -> str:
    """Canonical transmission: Manual | Automatic | Semi-Auto | Other.

    Returns an empty string if raw is blank — the validator will catch it.
    """
    val = raw.strip()
    if not val:
        return ""
    _MAP = {
        "Manual": "Manual",
        "Automatic": "Automatic",
        "Semi-Auto": "Semi-Auto",
        "Semi Auto": "Semi-Auto",
    }
    return _MAP.get(val.title(), "Other")


# ── Numeric parsing ──────────────────────────────────────────────────────────


def parse_price(raw: str) -> int | None:
    """Parse price to integer GBP. Returns None if unparseable.

    Handles: '12500', '12,500', '£12,500', ' £12,500'
    """
    cleaned = re.sub(r"[£\$€,\s]", "", str(raw).strip())
    try:
        return int(float(cleaned))
    except (ValueError, TypeError):
        return None


def parse_year(raw: str) -> int | None:
    """Parse year to integer. Returns None if unparseable."""
    try:
        return int(str(raw).strip())
    except (ValueError, TypeError):
        return None


def parse_mileage(raw: str) -> int | None:
    """Parse mileage to integer miles. Handles comma-formatted values."""
    cleaned = re.sub(r"[,\s]", "", str(raw).strip())
    try:
        return int(float(cleaned))
    except (ValueError, TypeError):
        return None


def parse_float_field(raw: str | None) -> float | None:
    """Parse mpg or engine size to float. Returns None if missing/unparseable."""
    if raw is None or str(raw).strip() == "":
        return None
    try:
        return float(str(raw).strip().replace(",", ""))
    except (ValueError, TypeError):
        return None


def parse_tax(raw: str | None) -> int | None:
    """Parse annual road tax to integer GBP. Returns None if missing."""
    if raw is None or str(raw).strip() == "":
        return None
    cleaned = re.sub(r"[£\$€,\s]", "", str(raw).strip())
    try:
        return int(float(cleaned))
    except (ValueError, TypeError):
        return None
