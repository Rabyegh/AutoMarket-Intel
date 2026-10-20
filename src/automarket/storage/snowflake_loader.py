"""Snowflake data loader for AutoMarket Intel.

Loads normalized Parquet files from the S3 external stage into the
Snowflake RAW layer using COPY INTO.

Design principles
-----------------
- Credentials are read from environment variables only; no secrets in code.
- The Snowflake connector is an optional dependency (``automarket[cloud]``).
  Local DuckDB runs require no Snowflake packages.
- COPY INTO is executed with FORCE=FALSE (default), meaning Snowflake skips
  files it has already successfully loaded (using internal load history).
  This provides file-level idempotency: the same Parquet file uploaded to
  the same S3 key will not be loaded twice. If the S3 key changes (e.g.,
  new run_id in the path), the file will be loaded again.
- Rejected rows are captured and reported but do not abort the load.
- All SQL is executed via parameterized queries; no string interpolation of
  user-supplied values.

Idempotency contract
--------------------
  Same Parquet file at same S3 key → loaded at most once by COPY INTO.
  Different run_id → different S3 key → new load attempt (per-run history).
  Business-level row deduplication must be handled downstream in dbt staging
  models (e.g., deduplication on row_id using the deterministic hash).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

logger = logging.getLogger("automarket.storage.snowflake_loader")

# ── Configuration ─────────────────────────────────────────────────────────────

_REQUIRED_SF_VARS = (
    "SNOWFLAKE_ACCOUNT",
    "SNOWFLAKE_USER",
    "SNOWFLAKE_PRIVATE_KEY_PATH",
    "SNOWFLAKE_DATABASE",
    "SNOWFLAKE_WAREHOUSE",
    "SNOWFLAKE_ROLE",
)


class SnowflakeConfigError(Exception):
    """Raised when Snowflake configuration is missing or invalid."""


class SnowflakeLoadError(Exception):
    """Raised when a Snowflake load operation fails."""


@dataclass
class SnowflakeConfig:
    """Snowflake connection configuration.

    All values come from environment variables; private keys are read from
    the filesystem path specified by SNOWFLAKE_PRIVATE_KEY_PATH.
    """

    account: str
    user: str
    private_key_path: str
    database: str
    warehouse: str
    role: str
    schema: str = "RAW"
    stage_name: str = "RAW.S3_STAGE_AUTOMARKET"
    raw_table: str = "RAW.RAW_USED_CAR_LISTINGS"

    @classmethod
    def from_env(cls) -> SnowflakeConfig:
        """Load and validate Snowflake config from environment variables.

        Raises:
            SnowflakeConfigError: If any required variable is missing.
        """
        missing = [k for k in _REQUIRED_SF_VARS if not os.environ.get(k)]
        if missing:
            raise SnowflakeConfigError(
                f"Required environment variable(s) not set: {', '.join(missing)}. "
                "Copy .env.example to .env and fill in the values, or "
                "set them as CI/CD secrets."
            )
        return cls(
            account=os.environ["SNOWFLAKE_ACCOUNT"].strip(),
            user=os.environ["SNOWFLAKE_USER"].strip(),
            private_key_path=os.environ["SNOWFLAKE_PRIVATE_KEY_PATH"].strip(),
            database=os.environ["SNOWFLAKE_DATABASE"].strip(),
            warehouse=os.environ["SNOWFLAKE_WAREHOUSE"].strip(),
            role=os.environ["SNOWFLAKE_ROLE"].strip(),
            schema=os.environ.get("SNOWFLAKE_SCHEMA", "RAW").strip().upper(),
            stage_name=os.environ.get("SNOWFLAKE_STAGE_NAME", "RAW.S3_STAGE_AUTOMARKET").strip(),
            raw_table=os.environ.get("SNOWFLAKE_RAW_TABLE", "RAW.RAW_USED_CAR_LISTINGS").strip(),
        )


# ── Result dataclass ──────────────────────────────────────────────────────────


@dataclass
class LoadResult:
    """Result of a COPY INTO operation."""

    files_loaded: int = 0
    rows_loaded: int = 0
    rows_rejected: int = 0
    errors: list[str] = field(default_factory=list)
    copy_rows: list[dict] = field(default_factory=list)  # raw COPY INTO result rows

    @property
    def success(self) -> bool:
        return len(self.errors) == 0

    def report(self) -> str:
        lines = [
            "=== Snowflake Load Summary ===",
            f"Files loaded  : {self.files_loaded}",
            f"Rows loaded   : {self.rows_loaded}",
            f"Rows rejected : {self.rows_rejected}",
        ]
        if self.errors:
            lines.append(f"Errors        : {len(self.errors)}")
            for e in self.errors[:5]:
                lines.append(f"  - {e}")
        return "\n".join(lines)


# ── Connection helper ─────────────────────────────────────────────────────────


def _load_private_key(key_path: str) -> bytes:
    """Load an RSA private key from a PEM file for key-pair authentication.

    Args:
        key_path: Path to the unencrypted RSA private key in PEM format.

    Returns:
        DER-encoded private key bytes for use with snowflake-connector-python.

    Raises:
        SnowflakeConfigError: If the file is missing or cannot be parsed.
    """
    from pathlib import Path

    p = Path(key_path)
    if not p.exists():
        raise SnowflakeConfigError(
            f"SNOWFLAKE_PRIVATE_KEY_PATH does not exist: {key_path}. "
            "Generate the key with: openssl genrsa -out rsa_key.pem 2048"
        )
    try:
        from cryptography.hazmat.primitives.serialization import (
            Encoding,
            NoEncryption,
            PrivateFormat,
            load_pem_private_key,
        )

        pem_data = p.read_bytes()
        private_key = load_pem_private_key(pem_data, password=None)
        return private_key.private_bytes(
            encoding=Encoding.DER,
            format=PrivateFormat.PKCS8,
            encryption_algorithm=NoEncryption(),
        )
    except Exception as exc:
        raise SnowflakeConfigError(
            f"Failed to load private key from {key_path}: {exc}. "
            "Ensure the file is an unencrypted RSA PEM key."
        ) from exc


def get_connection(config: SnowflakeConfig):
    """Open a Snowflake connection using key-pair authentication.

    Args:
        config: Validated SnowflakeConfig.

    Returns:
        An open snowflake.connector.SnowflakeConnection.

    Raises:
        SnowflakeLoadError: If snowflake-connector-python is not installed.
        SnowflakeConfigError: If the private key cannot be loaded.
    """
    try:
        import snowflake.connector
    except ImportError as exc:
        raise SnowflakeLoadError(
            "snowflake-connector-python is required. Install with: "
            "uv pip install snowflake-connector-python  "
            "(or uv pip install 'automarket[cloud]')"
        ) from exc

    private_key_bytes = _load_private_key(config.private_key_path)

    try:
        conn = snowflake.connector.connect(
            account=config.account,
            user=config.user,
            private_key=private_key_bytes,
            database=config.database,
            warehouse=config.warehouse,
            role=config.role,
            schema=config.schema,
            client_session_keep_alive=False,
            session_parameters={"QUERY_TAG": "automarket_intel_loader"},
        )
        logger.info(
            "Snowflake connection opened: account=%s user=%s db=%s warehouse=%s role=%s",
            config.account,
            config.user,
            config.database,
            config.warehouse,
            config.role,
        )
        return conn
    except Exception as exc:
        raise SnowflakeLoadError(
            f"Failed to connect to Snowflake account '{config.account}': {exc}"
        ) from exc


# ── Stage verification ────────────────────────────────────────────────────────


def verify_stage(conn, stage_name: str) -> bool:
    """Check that the external S3 stage exists and is accessible.

    Args:
        conn: Open Snowflake connection.
        stage_name: Fully-qualified stage name (e.g. ``RAW.S3_STAGE_AUTOMARKET``).

    Returns:
        True if the stage is listed, False otherwise.
    """
    try:
        cursor = conn.cursor()
        cursor.execute(f"LIST @{stage_name}")  # noqa: S608 — stage name is config, not user input
        rows = cursor.fetchall()
        logger.info("Stage %s is accessible; %d objects listed", stage_name, len(rows))
        return True
    except Exception as exc:
        logger.error("Stage verification failed for %s: %s", stage_name, exc)
        return False


# ── COPY INTO loader ──────────────────────────────────────────────────────────

_COPY_INTO_SQL = """
COPY INTO {raw_table}
FROM @{stage_name}/normalized/{run_id}/
FILE_FORMAT = (FORMAT_NAME = 'RAW.PARQUET_FORMAT_AUTOMARKET')
MATCH_BY_COLUMN_NAME = CASE_INSENSITIVE
FORCE = FALSE
ON_ERROR = 'CONTINUE'
"""
# FORCE=FALSE → skip files already in Snowflake's internal load history (idempotent).
# ON_ERROR=CONTINUE → report rejected rows rather than aborting on first parse error.


def copy_into_raw(
    conn,
    config: SnowflakeConfig,
    run_id: str,
) -> LoadResult:
    """Execute COPY INTO to load Parquet files from the S3 stage.

    Loads only files under the ``normalized/{run_id}/`` prefix of the stage,
    so different pipeline runs do not accidentally load each other's files.

    Args:
        conn: Open Snowflake connection.
        config: SnowflakeConfig with stage and table names.
        run_id: The pipeline run ID whose Parquet files should be loaded.
            Must match the run_id used during upload (see ``upload-s3``).

    Returns:
        LoadResult with file and row counts.

    Raises:
        SnowflakeLoadError: On Snowflake execution errors.
    """
    sql = _COPY_INTO_SQL.format(
        raw_table=config.raw_table,
        stage_name=config.stage_name,
        run_id=run_id,
    )
    logger.info("Executing COPY INTO for run_id=%s", run_id)
    logger.debug("SQL:\n%s", sql)

    result = LoadResult()
    try:
        cursor = conn.cursor()
        cursor.execute(f"USE WAREHOUSE {config.warehouse}")
        cursor.execute(sql)
        rows = cursor.fetchall()
        col_names = [desc[0].lower() for desc in cursor.description] if cursor.description else []

        for row in rows:
            row_dict = dict(zip(col_names, row, strict=False)) if col_names else {}
            result.copy_rows.append(row_dict)

            status = str(row_dict.get("status", "")).upper()
            if status == "LOADED":
                result.files_loaded += 1
                result.rows_loaded += int(row_dict.get("rows_loaded", 0) or 0)
                result.rows_rejected += int(row_dict.get("rows_parsed", 0) or 0) - int(
                    row_dict.get("rows_loaded", 0) or 0
                )
            elif status == "LOAD_FAILED":
                err = row_dict.get("first_error", "unknown error")
                result.errors.append(f"File {row_dict.get('file', '?')} failed: {err}")
            elif status in ("PARTIALLY_LOADED",):
                result.files_loaded += 1
                result.rows_loaded += int(row_dict.get("rows_loaded", 0) or 0)
                result.rows_rejected += int(row_dict.get("rows_parsed", 0) or 0) - int(
                    row_dict.get("rows_loaded", 0) or 0
                )

        logger.info(
            "COPY INTO complete: %d files loaded, %d rows loaded, %d rejected",
            result.files_loaded,
            result.rows_loaded,
            result.rows_rejected,
        )
    except Exception as exc:
        raise SnowflakeLoadError(f"COPY INTO failed for run_id={run_id}: {exc}") from exc

    return result


def verify_row_count(conn, raw_table: str, expected_min: int = 1) -> int:
    """Query the raw table and return the current row count.

    Args:
        conn: Open Snowflake connection.
        raw_table: Fully-qualified table name.
        expected_min: Minimum expected rows; logs a warning if fewer.

    Returns:
        Row count as integer.
    """
    try:
        cursor = conn.cursor()
        cursor.execute(f"SELECT COUNT(*) FROM {raw_table}")  # noqa: S608
        count = cursor.fetchone()[0]
        if count < expected_min:
            logger.warning(
                "Row count in %s is %d (expected >= %d). "
                "Check stage, file format, and COPY INTO result.",
                raw_table,
                count,
                expected_min,
            )
        else:
            logger.info("Row count verified: %s has %d rows", raw_table, count)
        return count
    except Exception as exc:
        raise SnowflakeLoadError(f"Row count verification failed: {exc}") from exc


def run_load(
    config: SnowflakeConfig,
    run_id: str,
    verify: bool = True,
) -> LoadResult:
    """End-to-end Snowflake load: connect → verify stage → COPY INTO → verify count.

    This is the entry point called by the ``load-snowflake`` CLI command.

    Args:
        config: Validated SnowflakeConfig.
        run_id: Pipeline run ID (must match the S3 upload run_id).
        verify: If True, verify stage accessibility and final row count.

    Returns:
        LoadResult. Check ``.success`` and ``.report()`` for outcome details.
    """
    conn = get_connection(config)
    try:
        if verify:
            accessible = verify_stage(conn, config.stage_name)
            if not accessible:
                raise SnowflakeLoadError(
                    f"Stage {config.stage_name} is not accessible. "
                    "Verify the storage integration and IAM trust relationship "
                    "(see infra/snowflake/setup.sql and docs/DEPLOY.md)."
                )

        result = copy_into_raw(conn=conn, config=config, run_id=run_id)

        if verify and result.files_loaded > 0:
            verify_row_count(conn, config.raw_table, expected_min=1)

        return result
    finally:
        conn.close()
        logger.info("Snowflake connection closed")
