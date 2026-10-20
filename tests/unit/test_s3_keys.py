"""Unit tests for S3 object key construction.

These tests are pure (no I/O, no network) and cover:
- Key generation for source CSVs
- Key generation for normalized Parquet files
- Key generation for manifests
- Input validation (filenames with separators, empty strings)
- Determinism: same inputs → same key
"""

import pytest

from automarket.storage.s3 import (
    manifest_object_key,
    normalized_object_key,
    source_object_key,
)

PREFIX = "raw/used_cars"
RUN_ID = "abc12345"


class TestSourceObjectKey:
    def test_standard_filename(self):
        key = source_object_key(PREFIX, "audi.csv")
        assert key == "raw/used_cars/source/audi.csv"

    def test_different_filenames_produce_different_keys(self):
        k1 = source_object_key(PREFIX, "audi.csv")
        k2 = source_object_key(PREFIX, "bmw.csv")
        assert k1 != k2

    def test_deterministic(self):
        k1 = source_object_key(PREFIX, "audi.csv")
        k2 = source_object_key(PREFIX, "audi.csv")
        assert k1 == k2

    def test_all_ingestible_files(self):
        files = [
            "audi.csv",
            "bmw.csv",
            "ford.csv",
            "hyundi.csv",
            "merc.csv",
            "skoda.csv",
            "toyota.csv",
            "vauxhall.csv",
            "vw.csv",
            "cclass.csv",
            "focus.csv",
        ]
        keys = [source_object_key(PREFIX, f) for f in files]
        # All keys are unique
        assert len(set(keys)) == len(files)
        # All contain the source prefix
        for key in keys:
            assert "source/" in key

    def test_rejects_path_separator_in_filename(self):
        with pytest.raises(ValueError, match="path separators"):
            source_object_key(PREFIX, "subdir/audi.csv")

    def test_rejects_empty_filename(self):
        with pytest.raises(ValueError, match="path separators"):
            source_object_key(PREFIX, "")


class TestNormalizedObjectKey:
    def test_standard_inputs(self):
        key = normalized_object_key(PREFIX, RUN_ID, "audi")
        assert key == "raw/used_cars/normalized/abc12345/audi.parquet"

    def test_deterministic(self):
        k1 = normalized_object_key(PREFIX, RUN_ID, "audi")
        k2 = normalized_object_key(PREFIX, RUN_ID, "audi")
        assert k1 == k2

    def test_different_run_ids_produce_different_keys(self):
        k1 = normalized_object_key(PREFIX, "run-001", "audi")
        k2 = normalized_object_key(PREFIX, "run-002", "audi")
        assert k1 != k2

    def test_different_stems_produce_different_keys(self):
        k1 = normalized_object_key(PREFIX, RUN_ID, "audi")
        k2 = normalized_object_key(PREFIX, RUN_ID, "bmw")
        assert k1 != k2

    def test_sanitizes_run_id_slash(self):
        key = normalized_object_key(PREFIX, "run/dangerous", "audi")
        # Should not contain double slashes from the run_id
        assert "run/dangerous" not in key
        assert "run_dangerous" in key or "audi.parquet" in key

    def test_sanitizes_run_id_dotdot(self):
        key = normalized_object_key(PREFIX, "../../etc/passwd", "audi")
        assert ".." not in key

    def test_parquet_extension(self):
        key = normalized_object_key(PREFIX, RUN_ID, "bmw")
        assert key.endswith(".parquet")

    def test_all_stems(self):
        stems = [
            "audi",
            "bmw",
            "ford",
            "hyundi",
            "merc",
            "skoda",
            "toyota",
            "vauxhall",
            "vw",
            "cclass",
            "focus",
        ]
        keys = [normalized_object_key(PREFIX, RUN_ID, s) for s in stems]
        assert len(set(keys)) == len(stems)


class TestManifestObjectKey:
    def test_standard(self):
        key = manifest_object_key(PREFIX, RUN_ID)
        assert key == "raw/used_cars/manifests/abc12345.json"

    def test_deterministic(self):
        k1 = manifest_object_key(PREFIX, RUN_ID)
        k2 = manifest_object_key(PREFIX, RUN_ID)
        assert k1 == k2

    def test_different_run_ids_differ(self):
        k1 = manifest_object_key(PREFIX, "run-a")
        k2 = manifest_object_key(PREFIX, "run-b")
        assert k1 != k2
