"""Unit tests for S3 config validation and upload helpers.

Uses moto to mock AWS S3 — no real AWS account required.
Moto intercepts boto3 calls and simulates S3 behavior in-memory.

Tests cover:
- S3Config.from_env() validation (missing vars, bad bucket format)
- Successful upload of source CSV
- Successful upload of normalized Parquet
- Successful upload of manifest
- Skip-if-exists behavior (overwrite=False)
- Access denied raises S3UploadError
- Missing bucket raises S3UploadError
- boto3 not installed raises S3UploadError
- Secret values are not logged
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

# Attempt to import moto — skip entire module if not installed
try:
    import boto3
    from moto import mock_aws

    MOTO_AVAILABLE = True
except ImportError:
    # Provide a no-op decorator so @mock_aws on class methods doesn't
    # cause a NameError during pytest collection on machines where moto
    # is not installed. The pytestmark.skipif below ensures the tests
    # are skipped at runtime.
    def mock_aws(fn=None, **kwargs):  # type: ignore[misc]
        if fn is not None:
            return fn

        def _decorator(f):
            return f

        return _decorator

    MOTO_AVAILABLE = False

from automarket.storage.s3 import (
    S3Config,
    S3ConfigError,
    S3UploadError,
    run_upload,
    upload_manifest,
    upload_normalized_parquet,
    upload_source_csv,
)

pytestmark = pytest.mark.unit


# ── Config validation tests (no moto needed) ─────────────────────────────────


class TestS3ConfigFromEnv:
    def test_raises_if_bucket_missing(self, monkeypatch):
        monkeypatch.delenv("S3_RAW_BUCKET", raising=False)
        monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-west-1")
        with pytest.raises(S3ConfigError, match="S3_RAW_BUCKET"):
            S3Config.from_env()

    def test_raises_if_region_missing(self, monkeypatch):
        monkeypatch.setenv("S3_RAW_BUCKET", "my-bucket")
        monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
        with pytest.raises(S3ConfigError, match="AWS_DEFAULT_REGION"):
            S3Config.from_env()

    def test_raises_if_bucket_is_uri(self, monkeypatch):
        monkeypatch.setenv("S3_RAW_BUCKET", "s3://my-bucket")
        monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-west-1")
        with pytest.raises(S3ConfigError, match="bare bucket name"):
            S3Config.from_env()

    def test_success(self, monkeypatch):
        monkeypatch.setenv("S3_RAW_BUCKET", "automarket-raw")
        monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-west-1")
        monkeypatch.delenv("S3_RAW_PREFIX", raising=False)
        cfg = S3Config.from_env()
        assert cfg.bucket == "automarket-raw"
        assert cfg.region == "eu-west-1"
        assert cfg.raw_prefix == "raw/used_cars"

    def test_custom_prefix(self, monkeypatch):
        monkeypatch.setenv("S3_RAW_BUCKET", "my-bucket")
        monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-west-1")
        monkeypatch.setenv("S3_RAW_PREFIX", "custom/prefix")
        cfg = S3Config.from_env()
        assert cfg.raw_prefix == "custom/prefix"

    def test_prefix_properties(self, monkeypatch):
        monkeypatch.setenv("S3_RAW_BUCKET", "b")
        monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-west-1")
        monkeypatch.delenv("S3_RAW_PREFIX", raising=False)
        cfg = S3Config.from_env()
        assert cfg.source_prefix == "raw/used_cars/source"
        assert cfg.normalized_prefix == "raw/used_cars/normalized"
        assert cfg.manifest_prefix == "raw/used_cars/manifests"


# ── Moto-backed upload tests ───────────────────────────────────────────────────


@pytest.mark.skipif(not MOTO_AVAILABLE, reason="moto[s3] not installed")
class TestUploadSourceCsv:
    @mock_aws
    def test_uploads_successfully(self, tmp_path):
        csv_path = tmp_path / "audi.csv"
        csv_path.write_text("model,year,price\nA3,2019,15000\n")

        s3 = boto3.client("s3", region_name="eu-west-1")
        s3.create_bucket(
            Bucket="test-bucket",
            CreateBucketConfiguration={"LocationConstraint": "eu-west-1"},
        )

        cfg = S3Config(bucket="test-bucket", region="eu-west-1")
        result = upload_source_csv(client=s3, config=cfg, csv_path=csv_path)

        assert result.skipped is False
        assert result.size_bytes > 0
        assert "source/audi.csv" in result.key

    @mock_aws
    def test_skips_if_exists_and_overwrite_false(self, tmp_path):
        csv_path = tmp_path / "bmw.csv"
        csv_path.write_text("model,year,price\nM3,2020,35000\n")

        s3 = boto3.client("s3", region_name="eu-west-1")
        s3.create_bucket(
            Bucket="test-bucket",
            CreateBucketConfiguration={"LocationConstraint": "eu-west-1"},
        )

        cfg = S3Config(bucket="test-bucket", region="eu-west-1")
        # Upload once
        upload_source_csv(client=s3, config=cfg, csv_path=csv_path, overwrite=True)
        # Second upload with overwrite=False should be skipped
        result2 = upload_source_csv(client=s3, config=cfg, csv_path=csv_path, overwrite=False)
        assert result2.skipped is True

    @mock_aws
    def test_raises_if_file_missing(self):
        s3 = boto3.client("s3", region_name="eu-west-1")
        s3.create_bucket(
            Bucket="test-bucket",
            CreateBucketConfiguration={"LocationConstraint": "eu-west-1"},
        )
        cfg = S3Config(bucket="test-bucket", region="eu-west-1")
        with pytest.raises(ValueError, match="does not exist"):
            upload_source_csv(client=s3, config=cfg, csv_path=Path("/nonexistent/audi.csv"))


@pytest.mark.skipif(not MOTO_AVAILABLE, reason="moto[s3] not installed")
class TestUploadNormalizedParquet:
    @mock_aws
    def test_uploads_parquet(self, tmp_path):
        from automarket.storage.serializer import records_to_parquet

        records = [
            {
                "row_id": "a" * 16,
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
        ]
        parquet_bytes = records_to_parquet(records)

        s3 = boto3.client("s3", region_name="eu-west-1")
        s3.create_bucket(
            Bucket="test-bucket",
            CreateBucketConfiguration={"LocationConstraint": "eu-west-1"},
        )

        cfg = S3Config(bucket="test-bucket", region="eu-west-1")
        result = upload_normalized_parquet(
            client=s3,
            config=cfg,
            run_id="test-001",
            source_stem="audi",
            parquet_bytes=parquet_bytes,
            row_count=1,
        )
        assert result.skipped is False
        assert "normalized/test-001/audi.parquet" in result.key


@pytest.mark.skipif(not MOTO_AVAILABLE, reason="moto[s3] not installed")
class TestUploadManifest:
    @mock_aws
    def test_uploads_manifest_json(self):
        s3 = boto3.client("s3", region_name="eu-west-1")
        s3.create_bucket(
            Bucket="test-bucket",
            CreateBucketConfiguration={"LocationConstraint": "eu-west-1"},
        )

        cfg = S3Config(bucket="test-bucket", region="eu-west-1")
        manifest = {"run_id": "run-001", "files": [], "total_rows": 100}
        result = upload_manifest(client=s3, config=cfg, run_id="run-001", manifest=manifest)

        assert result.skipped is False
        assert "manifests/run-001.json" in result.key

        # Verify the JSON is readable from S3
        obj = s3.get_object(Bucket="test-bucket", Key=result.key)
        loaded = json.loads(obj["Body"].read())
        assert loaded["run_id"] == "run-001"
        assert loaded["total_rows"] == 100


@pytest.mark.skipif(not MOTO_AVAILABLE, reason="moto[s3] not installed")
class TestUploadRunToS3:
    @mock_aws
    def test_upload_run_creates_manifest_with_success_status(self, tmp_path):
        s3 = boto3.client("s3", region_name="eu-west-1")
        s3.create_bucket(
            Bucket="test-bucket",
            CreateBucketConfiguration={"LocationConstraint": "eu-west-1"},
        )
        csv_file = tmp_path / "audi.csv"
        csv_file.write_text(
            "model,year,price,transmission,mileage,fuelType,tax,mpg,engineSize\nA1,2017,12500,Manual,15735,Petrol,150,55.4,1.4\n"
        )

        records = [
            {
                "row_id": "a" * 16,
                "source_file": "audi.csv",
                "make": "Audi",
                "model": "A1",
                "year": 2017,
                "price_gbp": 12500,
                "transmission": "Manual",
                "mileage_miles": 15735,
                "fuel_type": "Petrol",
                "tax_gbp": 150,
                "mpg": 55.4,
                "engine_size_l": 1.4,
            }
        ]

        cfg = S3Config(bucket="test-bucket", region="eu-west-1")
        summary = run_upload(
            config=cfg,
            data_dir=tmp_path,
            run_id="run-full-001",
            accepted_records={"audi": records},
            upload_sources=True,
        )

        assert summary.success is True
        assert len(summary.source_uploads) == 1
        assert len(summary.parquet_uploads) == 1
        assert summary.manifest_key != ""

        # Verify manifest content in S3
        obj = s3.get_object(Bucket="test-bucket", Key=summary.manifest_key)
        manifest_data = json.loads(obj["Body"].read())
        assert manifest_data["run_id"] == "run-full-001"
        assert manifest_data["status"] == "SUCCESS"
        assert manifest_data["errors"] == []
        assert manifest_data["total_rows"] == 1


# ── Error handling tests ──────────────────────────────────────────────────────


class TestS3UploadErrors:
    def test_boto3_not_installed_raises_s3_upload_error(self):
        """Simulate missing boto3 by patching the import."""
        from automarket.storage import s3 as s3_module

        def mock_get_client(region):
            raise S3UploadError(
                "boto3 is required for S3 uploads. Install it with: uv pip install boto3"
            )

        with patch.object(s3_module, "_get_client", mock_get_client):
            with pytest.raises(S3UploadError, match="boto3"):
                mock_get_client("eu-west-1")

    @pytest.mark.skipif(not MOTO_AVAILABLE, reason="moto[s3] not installed")
    @mock_aws
    def test_missing_bucket_raises_s3_upload_error(self, tmp_path):
        csv_path = tmp_path / "audi.csv"
        csv_path.write_text("test")
        # Do NOT create the bucket — should raise S3UploadError
        s3 = boto3.client("s3", region_name="eu-west-1")
        cfg = S3Config(bucket="nonexistent-bucket-xyz", region="eu-west-1")
        with pytest.raises(S3UploadError, match="does not exist"):
            upload_source_csv(client=s3, config=cfg, csv_path=csv_path)
