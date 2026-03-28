"""Tests for batho_core.utils.hash module."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from batho_core.utils.hash import (
    compute_bytes_hash,
    compute_file_hash,
    compute_file_hash_cached,
    compute_string_hash,
    generate_entity_id,
    generate_relationship_id,
)


# ---------------------------------------------------------------------------
# compute_bytes_hash
# ---------------------------------------------------------------------------

class TestComputeBytesHash:

    def test_known_sha256(self):
        """SHA256 of empty bytes is well-known."""
        expected = hashlib.sha256(b"").hexdigest()
        assert compute_bytes_hash(b"") == expected

    def test_deterministic(self):
        data = b"hello world"
        assert compute_bytes_hash(data) == compute_bytes_hash(data)

    def test_different_inputs_differ(self):
        assert compute_bytes_hash(b"a") != compute_bytes_hash(b"b")

    def test_truncate(self):
        result = compute_bytes_hash(b"data", truncate=8)
        assert len(result) == 8

    def test_truncate_none(self):
        result = compute_bytes_hash(b"data", truncate=None)
        assert len(result) == 64  # full SHA-256 hex

    def test_truncate_zero(self):
        # truncate=0 is falsy so should return full hash
        result = compute_bytes_hash(b"data", truncate=0)
        assert len(result) == 64


# ---------------------------------------------------------------------------
# compute_string_hash
# ---------------------------------------------------------------------------

class TestComputeStringHash:

    def test_matches_bytes_hash(self):
        text = "hello"
        assert compute_string_hash(text) == compute_bytes_hash(text.encode("utf-8"))

    def test_custom_encoding(self):
        text = "café"
        result = compute_string_hash(text, encoding="latin-1")
        expected = compute_bytes_hash(text.encode("latin-1"))
        assert result == expected

    def test_truncate(self):
        assert len(compute_string_hash("x", truncate=16)) == 16


# ---------------------------------------------------------------------------
# compute_file_hash
# ---------------------------------------------------------------------------

class TestComputeFileHash:

    def test_real_file(self, tmp_path: Path):
        f = tmp_path / "test.txt"
        f.write_bytes(b"file content")
        result = compute_file_hash(f)
        assert result == hashlib.sha256(b"file content").hexdigest()

    def test_string_path(self, tmp_path: Path):
        f = tmp_path / "test.txt"
        f.write_bytes(b"data")
        assert compute_file_hash(str(f)) is not None

    def test_nonexistent_file(self):
        assert compute_file_hash("/nonexistent/path/file.txt") is None

    def test_large_file_chunked(self, tmp_path: Path):
        """Ensure chunked reading works on a file larger than chunk size."""
        f = tmp_path / "large.bin"
        data = os.urandom(20_000)  # > 8192 default chunk
        f.write_bytes(data)
        assert compute_file_hash(f) == hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# compute_file_hash_cached
# ---------------------------------------------------------------------------

class TestComputeFileHashCached:

    def test_caches_by_mtime(self, tmp_path: Path):
        f = tmp_path / "cached.txt"
        f.write_bytes(b"v1")
        mtime = f.stat().st_mtime
        r1 = compute_file_hash_cached(str(f), mtime)
        r2 = compute_file_hash_cached(str(f), mtime)
        assert r1 == r2

    def test_different_mtime_recomputes(self, tmp_path: Path):
        f = tmp_path / "cached.txt"
        f.write_bytes(b"v1")
        r1 = compute_file_hash_cached(str(f), 1.0)
        f.write_bytes(b"v2")
        r2 = compute_file_hash_cached(str(f), 2.0)
        assert r1 != r2


# ---------------------------------------------------------------------------
# generate_entity_id / generate_relationship_id
# ---------------------------------------------------------------------------

class TestIDGeneration:

    def test_entity_id_length(self):
        eid = generate_entity_id("FUNCTION", "foo", "main.py", 10)
        assert len(eid) == 16

    def test_entity_id_deterministic(self):
        a = generate_entity_id("CLASS", "Bar", "src/bar.py", 5)
        b = generate_entity_id("CLASS", "Bar", "src/bar.py", 5)
        assert a == b

    def test_entity_id_differs_for_different_inputs(self):
        a = generate_entity_id("FUNCTION", "foo", "a.py", 1)
        b = generate_entity_id("FUNCTION", "foo", "a.py", 2)
        assert a != b

    def test_relationship_id_length(self):
        rid = generate_relationship_id("src1", "tgt1", "CALLS")
        assert len(rid) == 16

    def test_relationship_id_deterministic(self):
        a = generate_relationship_id("s", "t", "IMPORTS")
        b = generate_relationship_id("s", "t", "IMPORTS")
        assert a == b

    def test_relationship_id_differs(self):
        a = generate_relationship_id("s", "t", "CALLS")
        b = generate_relationship_id("s", "t", "IMPORTS")
        assert a != b
