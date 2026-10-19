"""Configuration — reads from environment variables only. No secrets in code."""

from __future__ import annotations

import os
from pathlib import Path


def _require(key: str) -> str:
    val = os.environ.get(key)
    if not val:
        raise EnvironmentError(
            f"Required environment variable '{key}' is not set. "
            "Copy .env.example to .env and fill in the values."
        )
    return val


def _optional(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


class Config:
    """Centralised, validated config object built from env vars."""

    # Pipeline
    env: str = _optional("PIPELINE_ENV", "local")
    run_log_path: Path = Path(_optional("RUN_LOG_PATH", "data/run_log.json"))

    # vPIC
    vpic_base_url: str = _optional(
        "VPIC_BASE_URL", "https://vpic.nhtsa.dot.gov/api"
    )
    vpic_batch_size: int = int(_optional("VPIC_BATCH_SIZE", "50"))
    vpic_rate_sleep_s: float = float(_optional("VPIC_RATE_SLEEP_S", "1.0"))
    vpic_max_retries: int = int(_optional("VPIC_MAX_RETRIES", "3"))

    # DuckDB
    duckdb_path: Path = Path(_optional("DUCKDB_PATH", "data/warehouse.duckdb"))

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
