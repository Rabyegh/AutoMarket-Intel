"""Amazon S3 upload module for AutoMarket Intel.

Responsibilities
----------------
- Upload original source CSV files to the ``raw/used_cars/source/`` prefix.
- Upload normalized Parquet datasets to the ``raw/used_cars/normalized/`` prefix.
- Construct deterministic, collision-resistant object keys.
- Attach structured object metadata (run_id, schema_version, row_count, etc.).
- Log each upload with key, size, and ETag.
- Raise actionable errors for missing configuration, access denied, and
  network failures.

Security constraints
--------------------
- Configuration is read exclusively from environment variables (via Config).
- No credentials are ever logged or included in object metadata.
- Caller-supplied paths are validated before any upload begins; arbitrary
  local files cannot be uploaded accidentally.
- Objects are private by default (no ACL is set; the bucket policy controls
  access from Snowflake via a Storage Integration IAM role).

Object key layout
-----------------
source CSVs    →  {prefix}/source/{filename}
normalized     →  {prefix}/normalized/{run_id}/{source_file_stem}.parquet
manifests      →  {prefix}/manifests/{run_id}.json

The ``run_id`` is the same UUID-prefixed identifier used by the ingestion
pipeline's run log, ensuring traceability between local DuckDB runs and
cloud uploads.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("automarket.storage.s3")

# ── Configuration ─────────────────────────────────────────────────────────────

_REQUIRED_VARS = ("S3_RAW_BUCKET", "AWS_DEFAULT_REGION")


class S3ConfigError(Exception):
    """Raised when required S3 configuration is missing or invalid."""


class S3UploadError(Exception):
    """Raised when an S3 upload fails for any reason."""


@dataclass
class S3Config:
    """S3 configuration loaded from environment variables.

    Call ``S3Config.from_env()`` to construct and validate.
    Never store AWS credentials as attributes — boto3 resolves them from
    the standard credential chain (OIDC role, instance profile, ~/.aws/credentials).
    """

    bucket: str
    region: str
    raw_prefix: str = "raw/used_cars"

    @classmethod
    def from_env(cls) -> S3Config:
        """Load and validate S3 configuration from environment variables.

        Raises:
            S3ConfigError: If any required variable is missing or blank.
        """
        missing = [k for k in _REQUIRED_VARS if not os.environ.get(k)]
        if missing:
            raise S3ConfigError(
                f"Required environment variable(s) not set: {', '.join(missing)}. "
                "Copy .env.example to .env and fill in the values, or "
                "set them as CI/CD secrets."
            )

        bucket = os.environ["S3_RAW_BUCKET"].strip()
        region = os.environ["AWS_DEFAULT_REGION"].strip()
        raw_prefix = os.environ.get("S3_RAW_PREFIX", "raw/used_cars").strip().rstrip("/")

        if "/" in bucket or bucket.startswith("s3://"):
            raise S3ConfigError(
                f"S3_RAW_BUCKET should be a bare bucket name (e.g. 'my-bucket'), "
                f"not a URI or path. Got: '{bucket}'"
            )

        return cls(bucket=bucket, region=region, raw_prefix=raw_prefix)

    @property
    def source_prefix(self) -> str:
        return f"{self.raw_prefix}/source"

    @property
    def normalized_prefix(self) -> str:
        return f"{self.raw_prefix}/normalized"

    @property
    def manifest_prefix(self) -> str:
        return f"{self.raw_prefix}/manifests"


# ── Result dataclass ──────────────────────────────────────────────────────────


@dataclass
class UploadResult:
    """Summary of one object upload."""

    key: str
    bucket: str
    size_bytes: int
    etag: str = ""
    elapsed_s: float = 0.0
    skipped: bool = False  # True if object already exists and was not overwritten
    skip_reason: str = ""


@dataclass
class UploadSummary:
    """Aggregate result for an upload-s3 command run."""

    run_id: str
    bucket: str
    source_uploads: list[UploadResult] = field(default_factory=list)
    parquet_uploads: list[UploadResult] = field(default_factory=list)
    manifest_key: str = ""
    errors: list[str] = field(default_factory=list)

    @property
    def total_uploaded(self) -> int:
        return sum(1 for r in self.source_uploads + self.parquet_uploads if not r.skipped)

    @property
    def total_skipped(self) -> int:
        return sum(1 for r in self.source_uploads + self.parquet_uploads if r.skipped)

    @property
    def success(self) -> bool:
        return len(self.errors) == 0

    def report(self) -> str:
        lines = [
            "=== S3 Upload Summary ===",
            f"Run ID    : {self.run_id}",
            f"Bucket    : s3://{self.bucket}",
            f"Uploaded  : {self.total_uploaded} objects",
            f"Skipped   : {self.total_skipped} objects (already exist)",
        ]
        if self.manifest_key:
            lines.append(f"Manifest  : s3://{self.bucket}/{self.manifest_key}")
        if self.errors:
            lines.append(f"Errors    : {len(self.errors)}")
            for e in self.errors:
                lines.append(f"  - {e}")
        return "\n".join(lines)


# ── Key construction ──────────────────────────────────────────────────────────


def source_object_key(prefix: str, filename: str) -> str:
    """Build the S3 key for an original source CSV file.

    Key: ``{prefix}/source/{filename}``
    Keys are stable across runs for the same file, enabling Snowflake to
    detect already-loaded files via COPY INTO load history.

    Args:
        prefix: The configured raw prefix (e.g. ``raw/used_cars``).
        filename: Basename of the CSV file (e.g. ``audi.csv``).

    Returns:
        Full S3 object key string.
    """
    if not filename or "/" in filename or "\\" in filename:
        raise ValueError(
            f"filename must be a bare filename with no path separators, got: {filename!r}"
        )
    return f"{prefix}/source/{filename}"


def normalized_object_key(prefix: str, run_id: str, source_stem: str) -> str:
    """Build the S3 key for a normalized Parquet file.

    Key: ``{prefix}/normalized/{run_id}/{source_stem}.parquet``
    Each run_id produces its own Parquet objects; old runs are preserved
    until explicitly cleaned up. Snowflake's COPY INTO load history tracks
    which file+run combinations have already been loaded.

    Args:
        prefix: The configured raw prefix.
        run_id: Unique identifier for this pipeline execution.
        source_stem: Stem of the source CSV (e.g. ``audi`` from ``audi.csv``).

    Returns:
        Full S3 object key string.
    """
    safe_run_id = run_id.replace("/", "_").replace("..", "_")
    safe_stem = source_stem.replace("/", "_").replace("..", "_")
    return f"{prefix}/normalized/{safe_run_id}/{safe_stem}.parquet"


def manifest_object_key(prefix: str, run_id: str) -> str:
    """Build the S3 key for the run manifest JSON."""
    safe_run_id = run_id.replace("/", "_").replace("..", "_")
    return f"{prefix}/manifests/{safe_run_id}.json"


def file_sha256(path: Path, chunk_size: int = 65536) -> str:
    """Compute the SHA-256 hex digest of a file's contents."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(chunk_size):
            h.update(chunk)
    return h.hexdigest()


# ── S3 client helper ──────────────────────────────────────────────────────────


def _get_client(region: str):
    """Construct a boto3 S3 client.

    Credentials are resolved by boto3's standard chain:
      1. Environment variables (AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY)
      2. ~/.aws/credentials
      3. IAM instance profile / OIDC role (preferred for CI)

    Args:
        region: AWS region string.

    Raises:
        S3UploadError: If boto3 is not installed.
    """
    try:
        import boto3
        from botocore.config import Config as BotocoreConfig
    except ImportError as exc:
        raise S3UploadError(
            "boto3 is required for S3 uploads. Install it with: "
            "uv pip install boto3  (or uv pip install 'automarket[cloud]')"
        ) from exc

    return boto3.client(
        "s3",
        region_name=region,
        config=BotocoreConfig(
            retries={"max_attempts": 3, "mode": "adaptive"},
            connect_timeout=10,
            read_timeout=60,
        ),
    )


# ── Upload helpers ────────────────────────────────────────────────────────────


def _upload_bytes(
    client,
    bucket: str,
    key: str,
    data: bytes,
    content_type: str,
    metadata: dict[str, str],
    overwrite: bool = True,
) -> UploadResult:
    """Upload bytes to S3 and return an UploadResult.

    Args:
        client: boto3 S3 client.
        bucket: S3 bucket name.
        key: S3 object key.
        data: Bytes to upload.
        content_type: MIME content type.
        metadata: Object metadata dict (string → string; no credentials).
        overwrite: If False and the object exists, skip the upload.

    Returns:
        UploadResult describing the outcome.

    Raises:
        S3UploadError: On access denied, bucket not found, or network errors.
    """
    try:
        from botocore.exceptions import ClientError
    except ImportError as exc:
        raise S3UploadError("botocore is required (installed with boto3)") from exc

    if not overwrite:
        try:
            client.head_object(Bucket=bucket, Key=key)
            logger.debug("Skipping existing object: s3://%s/%s", bucket, key)
            return UploadResult(
                key=key,
                bucket=bucket,
                size_bytes=len(data),
                skipped=True,
                skip_reason="object already exists",
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] not in ("404", "NoSuchKey"):
                raise S3UploadError(
                    f"Error checking existence of s3://{bucket}/{key}: {exc}"
                ) from exc
            # 404 → object does not exist → proceed with upload

    t0 = time.monotonic()
    try:
        response = client.put_object(
            Bucket=bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
            Metadata={k: str(v)[:2048] for k, v in metadata.items()},
            ServerSideEncryption="AES256",
        )
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "Unknown")
        if code in ("AccessDenied", "403"):
            raise S3UploadError(
                f"Access denied uploading to s3://{bucket}/{key}. "
                "Verify that the IAM identity has s3:PutObject on this bucket."
            ) from exc
        if code in ("NoSuchBucket", "404"):
            raise S3UploadError(
                f"Bucket '{bucket}' does not exist or is not accessible. "
                "Create it first (see infra/terraform/ or docs/DEPLOY.md)."
            ) from exc
        raise S3UploadError(f"Upload failed for s3://{bucket}/{key}: [{code}] {exc}") from exc

    elapsed = time.monotonic() - t0
    etag = response.get("ETag", "").strip('"')
    logger.info(
        "Uploaded s3://%s/%s  (%d bytes, ETag=%s, %.2fs)",
        bucket,
        key,
        len(data),
        etag,
        elapsed,
    )
    return UploadResult(
        key=key,
        bucket=bucket,
        size_bytes=len(data),
        etag=etag,
        elapsed_s=elapsed,
    )


# ── Public API ────────────────────────────────────────────────────────────────


def upload_source_csv(
    client,
    config: S3Config,
    csv_path: Path,
    overwrite: bool = True,
) -> UploadResult:
    """Upload one original source CSV file to the source prefix.

    Args:
        client: boto3 S3 client (from ``_get_client``).
        config: Validated S3Config.
        csv_path: Absolute path to the CSV file.
        overwrite: If False, skip if the object already exists.

    Returns:
        UploadResult.

    Raises:
        ValueError: If csv_path does not exist or is not a regular file.
        S3UploadError: On upload failure.
    """
    if not csv_path.exists():
        raise ValueError(f"CSV file does not exist: {csv_path}")
    if not csv_path.is_file():
        raise ValueError(f"Expected a file, not a directory: {csv_path}")

    key = source_object_key(config.source_prefix, csv_path.name)
    data = csv_path.read_bytes()
    sha = hashlib.sha256(data).hexdigest()

    return _upload_bytes(
        client=client,
        bucket=config.bucket,
        key=key,
        data=data,
        content_type="text/csv",
        metadata={
            "source-file": csv_path.name,
            "sha256": sha,
            "content-type": "source-csv",
        },
        overwrite=overwrite,
    )


def upload_normalized_parquet(
    client,
    config: S3Config,
    run_id: str,
    source_stem: str,
    parquet_bytes: bytes,
    row_count: int,
    overwrite: bool = True,
) -> UploadResult:
    """Upload a normalized Parquet file to the normalized prefix.

    Args:
        client: boto3 S3 client.
        config: Validated S3Config.
        run_id: Pipeline run identifier (used in object key path).
        source_stem: Stem of the originating source file (e.g. ``audi``).
        parquet_bytes: Serialized Parquet bytes from ``records_to_parquet()``.
        row_count: Number of rows in the Parquet file (for metadata).
        overwrite: If False, skip if the object already exists.

    Returns:
        UploadResult.

    Raises:
        S3UploadError: On upload failure.
    """
    key = normalized_object_key(config.normalized_prefix, run_id, source_stem)
    sha = hashlib.sha256(parquet_bytes).hexdigest()

    return _upload_bytes(
        client=client,
        bucket=config.bucket,
        key=key,
        data=parquet_bytes,
        content_type="application/x-parquet",
        metadata={
            "source-file": f"{source_stem}.csv",
            "row-count": str(row_count),
            "sha256": sha,
            "run-id": run_id,
            "schema-version": "v1",
            "content-type": "normalized-parquet",
        },
        overwrite=overwrite,
    )


def upload_manifest(
    client,
    config: S3Config,
    run_id: str,
    manifest: dict[str, Any],
) -> UploadResult:
    """Upload a JSON run manifest to the manifests prefix.

    The manifest records the run_id, file list, row counts, and object keys,
    providing a machine-readable index of what was uploaded in this run.

    Args:
        client: boto3 S3 client.
        config: Validated S3Config.
        run_id: Pipeline run identifier.
        manifest: Dict to serialize as JSON.

    Returns:
        UploadResult.
    """
    key = manifest_object_key(config.manifest_prefix, run_id)
    data = json.dumps(manifest, indent=2, default=str).encode("utf-8")

    return _upload_bytes(
        client=client,
        bucket=config.bucket,
        key=key,
        data=data,
        content_type="application/json",
        metadata={"run-id": run_id, "content-type": "run-manifest"},
        overwrite=True,  # manifests are always overwritten (idempotent)
    )


def run_upload(
    config: S3Config,
    data_dir: Path,
    run_id: str,
    accepted_records: dict[str, list[dict]],  # source_stem → list of accepted rows
    *,
    upload_sources: bool = True,
    overwrite: bool = True,
) -> UploadSummary:
    """Perform the full upload sequence for one pipeline run.

    1. Upload each source CSV file.
    2. Serialize accepted rows to Parquet and upload per source file.
    3. Upload a JSON manifest summarizing the run.

    This function is the entry point called by the ``upload-s3`` CLI command.

    Args:
        config: Validated S3Config.
        data_dir: Directory containing source CSV files.
        run_id: Unique pipeline run identifier.
        accepted_records: Mapping from source file stem → list of accepted
            row dicts (from the ingestion pipeline).
        upload_sources: If True, upload the original source CSV files.
        overwrite: If False, skip objects that already exist in S3.

    Returns:
        UploadSummary describing the full upload outcome.
    """
    from automarket.storage.serializer import records_to_parquet

    summary = UploadSummary(run_id=run_id, bucket=config.bucket)
    client = _get_client(config.region)

    manifest_files: list[dict] = []

    for source_stem, records in accepted_records.items():
        csv_path = data_dir / f"{source_stem}.csv"

        # 1. Upload original source CSV
        if upload_sources:
            try:
                result = upload_source_csv(
                    client=client,
                    config=config,
                    csv_path=csv_path,
                    overwrite=overwrite,
                )
                summary.source_uploads.append(result)
                manifest_files.append(
                    {
                        "type": "source-csv",
                        "key": result.key,
                        "source_file": f"{source_stem}.csv",
                        "skipped": result.skipped,
                    }
                )
            except (ValueError, S3UploadError) as exc:
                msg = f"Source CSV upload failed for {source_stem}: {exc}"
                logger.error(msg)
                summary.errors.append(msg)

        # 2. Serialize and upload normalized Parquet
        if records:
            try:
                parquet_bytes = records_to_parquet(records)
                result = upload_normalized_parquet(
                    client=client,
                    config=config,
                    run_id=run_id,
                    source_stem=source_stem,
                    parquet_bytes=parquet_bytes,
                    row_count=len(records),
                    overwrite=overwrite,
                )
                summary.parquet_uploads.append(result)
                manifest_files.append(
                    {
                        "type": "normalized-parquet",
                        "key": result.key,
                        "source_file": f"{source_stem}.csv",
                        "row_count": len(records),
                        "skipped": result.skipped,
                    }
                )
            except (ValueError, S3UploadError) as exc:
                msg = f"Parquet upload failed for {source_stem}: {exc}"
                logger.error(msg)
                summary.errors.append(msg)
        else:
            logger.warning("No accepted records for %s.csv — skipping Parquet upload", source_stem)

    # 3. Upload manifest
    manifest = {
        "run_id": run_id,
        "bucket": config.bucket,
        "prefix": config.raw_prefix,
        "schema_version": "v1",
        "files": manifest_files,
        "total_source_files": len(accepted_records),
        "total_rows": sum(len(r) for r in accepted_records.values()),
    }
    try:
        result = upload_manifest(client=client, config=config, run_id=run_id, manifest=manifest)
        summary.manifest_key = result.key
    except S3UploadError as exc:
        msg = f"Manifest upload failed: {exc}"
        logger.error(msg)
        summary.errors.append(msg)

    return summary
