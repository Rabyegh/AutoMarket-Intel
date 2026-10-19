"""Configuration — reads from environment variables only. No secrets in code."""

from __future__ import annotations

import os
from pathlib import Path


def _optional(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def _require(key: str) -> str:
    val = os.environ.get(key)
    if not val:
        raise EnvironmentError(
            f"Required environment variable '{key}' is not set. "
            "Copy .env.example to .env and fill in the values."
        )
    return val


class Config:
    """Project-wide configuration from environment variables."""

    # Pipeline
    env: str = _optional("PIPELINE_ENV", "local")
    run_log_path: Path = Path(_optional("RUN_LOG_PATH", "data/run_log.jsonl"))

    # Data
    raw_data_dir: Path = Path(_optional("RAW_DATA_DIR", "data/raw/used_cars"))
    duckdb_path: Path = Path(_optional("DUCKDB_PATH", "data/warehouse.duckdb"))

    # Year validation bounds
    min_year: int = int(_optional("MIN_LISTING_YEAR", "1970"))
    max_year: int = int(_optional("MAX_LISTING_YEAR", "2025"))

    # Price validation bounds (GBP)
    min_price: int = int(_optional("MIN_PRICE_GBP", "100"))
    max_price: int = int(_optional("MAX_PRICE_GBP", "500000"))

    # Mileage validation bounds
    max_mileage: int = int(_optional("MAX_MILEAGE_MILES", "500000"))

    # Simulation
    simulation_seed: int = int(_optional("SIMULATION_SEED", "42"))

    # Snowflake (optional — only required when env=snowflake)
    @staticmethod
    def snowflake_account() -> str:
        return _require("SNOWFLAKE_ACCOUNT")

    @staticmethod
    def snowflake_user() -> str:
        return _require("SNOWFLAKE_USER")

    @staticmethod
    def snowflake_private_key_path() -> Path:
        return Path(_require("SNOWFLAKE_PRIVATE_KEY_PATH"))


cfg = Config()
