"""Tests for batho_core.utils.encoding module."""
from __future__ import annotations

from pathlib import Path

import pytest

from batho_core.utils.encoding import (
    FALLBACK_ENCODINGS,
    decode_bytes_with_fallback,
    normalize_to_utf8,
    read_text_with_fallback,
)


# ---------------------------------------------------------------------------
# read_text_with_fallback
# ---------------------------------------------------------------------------

class TestReadTextWithFallback:

    def test_utf8_file(self, tmp_path: Path):
        f = tmp_path / "utf8.txt"
        f.write_text("hello world", encoding="utf-8")
        assert read_text_with_fallback(f) == "hello world"

    def test_latin1_fallback(self, tmp_path: Path):
        f = tmp_path / "latin1.txt"
        f.write_bytes("café résumé".encode("latin-1"))
        result = read_text_with_fallback(f, errors="replace")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_string_path(self, tmp_path: Path):
        f = tmp_path / "p.txt"
        f.write_text("data")
        assert read_text_with_fallback(str(f)) == "data"

    def test_nonexistent_file_raises(self):
        with pytest.raises(FileNotFoundError):
            read_text_with_fallback("/does/not/exist.txt")

    def test_custom_encodings(self, tmp_path: Path):
        f = tmp_path / "custom.txt"
        f.write_bytes("hello".encode("ascii"))
        result = read_text_with_fallback(f, encodings=["ascii"])
        assert result == "hello"

    def test_replace_strategy(self, tmp_path: Path):
        """Invalid bytes replaced with replacement character."""
        f = tmp_path / "bad.txt"
        f.write_bytes(b"\xff\xfe invalid bytes")
        result = read_text_with_fallback(f, errors="replace")
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# decode_bytes_with_fallback
# ---------------------------------------------------------------------------

class TestDecodeBytesWithFallback:

    def test_utf8_bytes(self):
        data = "hello".encode("utf-8")
        assert decode_bytes_with_fallback(data) == "hello"

    def test_latin1_bytes(self):
        data = "café".encode("latin-1")
        result = decode_bytes_with_fallback(data, errors="replace")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_empty_bytes(self):
        assert decode_bytes_with_fallback(b"") == ""

    def test_falls_back_to_latin1(self):
        """Final fallback to latin-1 should always succeed."""
        # 0x80-0xFF are valid in latin-1
        data = bytes(range(128, 256))
        result = decode_bytes_with_fallback(data)
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# normalize_to_utf8
# ---------------------------------------------------------------------------

class TestNormalizeToUtf8:

    def test_utf8_roundtrip(self):
        original = "hello world".encode("utf-8")
        result = normalize_to_utf8(original)
        assert result == original

    def test_latin1_to_utf8(self):
        data = "café".encode("latin-1")
        result = normalize_to_utf8(data)
        # Should be valid UTF-8 bytes
        decoded = result.decode("utf-8")
        assert isinstance(decoded, str)

    def test_empty_bytes(self):
        assert normalize_to_utf8(b"") == b""
