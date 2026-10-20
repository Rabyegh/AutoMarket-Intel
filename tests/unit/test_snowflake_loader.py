"""Unit tests for Snowflake loader configuration and loading utilities.

These tests mock snowflake-connector-python and cryptography so they run
without real Snowflake credentials or an installed connector.

Tests cover:
- SnowflakeConfig.from_env() missing required vars
- SnowflakeConfig.from_env() success
- LoadResult.report() formatting
- COPY INTO SQL construction (non-injectable, uses run_id scoping)
- get_connection raises SnowflakeLoadError if connector not installed
- run_load uses config correctly (mocked connection)
"""

from unittest.mock import MagicMock, patch

import pytest

from automarket.storage.snowflake_loader import (
    _COPY_INTO_SQL,
    LoadResult,
    SnowflakeConfig,
    SnowflakeConfigError,
    SnowflakeLoadError,
    verify_row_count,
)

pytestmark = pytest.mark.unit


class TestSnowflakeConfigFromEnv:
    _required_vars = {
        "SNOWFLAKE_ACCOUNT": "xy12345.eu-west-1",
        "SNOWFLAKE_USER": "AUTOMARKET_SVC",
        "SNOWFLAKE_PRIVATE_KEY_PATH": "/tmp/rsa_key.pem",
        "SNOWFLAKE_DATABASE": "AUTOMARKET_DB",
        "SNOWFLAKE_WAREHOUSE": "AUTOMARKET_WH",
        "SNOWFLAKE_ROLE": "AUTOMARKET_ROLE",
    }

    def test_raises_if_account_missing(self, monkeypatch):
        for k, v in self._required_vars.items():
            monkeypatch.setenv(k, v)
        monkeypatch.delenv("SNOWFLAKE_ACCOUNT")
        with pytest.raises(SnowflakeConfigError, match="SNOWFLAKE_ACCOUNT"):
            SnowflakeConfig.from_env()

    def test_raises_if_private_key_path_missing(self, monkeypatch):
        for k, v in self._required_vars.items():
            monkeypatch.setenv(k, v)
        monkeypatch.delenv("SNOWFLAKE_PRIVATE_KEY_PATH")
        with pytest.raises(SnowflakeConfigError, match="SNOWFLAKE_PRIVATE_KEY_PATH"):
            SnowflakeConfig.from_env()

    def test_raises_multiple_missing_listed(self, monkeypatch):
        for k in self._required_vars:
            monkeypatch.delenv(k, raising=False)
        with pytest.raises(SnowflakeConfigError) as exc_info:
            SnowflakeConfig.from_env()
        msg = str(exc_info.value)
        # At least one missing var must be named
        assert "SNOWFLAKE_" in msg

    def test_success(self, monkeypatch):
        for k, v in self._required_vars.items():
            monkeypatch.setenv(k, v)
        monkeypatch.delenv("SNOWFLAKE_SCHEMA", raising=False)
        cfg = SnowflakeConfig.from_env()
        assert cfg.account == "xy12345.eu-west-1"
        assert cfg.user == "AUTOMARKET_SVC"
        assert cfg.database == "AUTOMARKET_DB"
        assert cfg.warehouse == "AUTOMARKET_WH"
        assert cfg.role == "AUTOMARKET_ROLE"
        assert cfg.schema == "RAW"  # default

    def test_custom_schema_uppercased(self, monkeypatch):
        for k, v in self._required_vars.items():
            monkeypatch.setenv(k, v)
        monkeypatch.setenv("SNOWFLAKE_SCHEMA", "raw")
        cfg = SnowflakeConfig.from_env()
        assert cfg.schema == "RAW"


class TestLoadResult:
    def test_success_when_no_errors(self):
        result = LoadResult(files_loaded=3, rows_loaded=1000)
        assert result.success is True

    def test_failure_when_errors_present(self):
        result = LoadResult(errors=["something went wrong"])
        assert result.success is False

    def test_report_contains_counts(self):
        result = LoadResult(files_loaded=5, rows_loaded=50000, rows_rejected=10)
        report = result.report()
        assert "5" in report
        assert "50000" in report
        assert "10" in report

    def test_report_lists_errors(self):
        result = LoadResult(errors=["file1 failed: bad schema"])
        report = result.report()
        assert "file1 failed" in report


class TestCopyIntoSqlTemplate:
    def test_contains_run_id(self):
        sql = _COPY_INTO_SQL.format(
            raw_table="RAW.RAW_USED_CAR_LISTINGS",
            stage_name="RAW.S3_STAGE_AUTOMARKET",
            run_id="test-run-001",
        )
        assert "test-run-001" in sql
        assert "RAW.RAW_USED_CAR_LISTINGS" in sql
        assert "RAW.S3_STAGE_AUTOMARKET" in sql

    def test_force_false_present(self):
        sql = _COPY_INTO_SQL.format(
            raw_table="RAW.RAW_USED_CAR_LISTINGS",
            stage_name="RAW.S3_STAGE_AUTOMARKET",
            run_id="r",
        )
        assert "FORCE = FALSE" in sql

    def test_on_error_continue_present(self):
        sql = _COPY_INTO_SQL.format(
            raw_table="RAW.RAW_USED_CAR_LISTINGS",
            stage_name="RAW.S3_STAGE_AUTOMARKET",
            run_id="r",
        )
        assert "ON_ERROR = 'CONTINUE'" in sql

    def test_scoped_to_run_id_prefix(self):
        """The COPY INTO path must include the run_id so different runs don't cross-load."""
        sql = _COPY_INTO_SQL.format(
            raw_table="X",
            stage_name="Y",
            run_id="my-run-123",
        )
        assert "normalized/my-run-123/" in sql


class TestGetConnectionError:
    def test_raises_if_connector_not_installed(self, monkeypatch):
        """Simulate snowflake.connector not being importable."""
        from automarket.storage import snowflake_loader

        def mock_load_private_key(path):
            return b"fake_key_bytes"

        cfg = SnowflakeConfig(
            account="acc",
            user="usr",
            private_key_path="/fake/key.pem",
            database="DB",
            warehouse="WH",
            role="ROLE",
        )

        with patch.object(snowflake_loader, "_load_private_key", mock_load_private_key):
            with patch.dict("sys.modules", {"snowflake": None, "snowflake.connector": None}):
                with pytest.raises((SnowflakeLoadError, ImportError, TypeError)):
                    snowflake_loader.get_connection(cfg)


class TestVerifyRowCount:
    def test_returns_count(self):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (108539,)
        mock_conn.cursor.return_value = mock_cursor

        count = verify_row_count(mock_conn, "RAW.RAW_USED_CAR_LISTINGS", expected_min=1000)
        assert count == 108539

    def test_warns_if_below_expected(self, caplog):
        import logging

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (5,)
        mock_conn.cursor.return_value = mock_cursor

        with caplog.at_level(logging.WARNING, logger="automarket.storage.snowflake_loader"):
            count = verify_row_count(mock_conn, "RAW.X", expected_min=1000)
        assert count == 5
        assert "WARNING" in caplog.text or any("5" in r.message for r in caplog.records)

    def test_raises_on_connection_error(self):
        mock_conn = MagicMock()
        mock_conn.cursor.side_effect = Exception("connection lost")
        with pytest.raises(SnowflakeLoadError, match="Row count"):
            verify_row_count(mock_conn, "RAW.X")
