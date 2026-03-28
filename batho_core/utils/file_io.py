"""
Unified file I/O utilities for Batho.

Provides consistent file reading and writing operations with:
- Size limits and binary detection
- Encoding normalization
- Atomic writes
- Error handling

This consolidates duplicate file operations from across the codebase.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Union

from batho_core.config import get_config_cached
from batho_core.utils.encoding import normalize_to_utf8
from batho_core.utils.hash import compute_bytes_hash
from batho_core.utils.logging import get_logger

LOGGER = get_logger(__name__)

# Binary detection constants (moved from codegraph.py)
_BINARY_MAGIC_BYTES: tuple[bytes, ...] = (
    b"\x7fELF",  # ELF executables
    b"\xca\xfe\xba\xbe",  # Java class files
    b"%PDF",  # PDF files
    b"PK\x03\x04",  # ZIP archives
    b"\x1f\x8b",  # GZIP
    b"Rar!",  # RAR
    b"\x89PNG",  # PNG
    b"\xff\xd8\xff",  # JPEG
    b"GIF87a",  # GIF
    b"GIF89a",  # GIF
    b"BM",  # BMP
    b"\x00\x00\x01\x00",  # ICO
)

_BINARY_ENTROPY_THRESHOLD = 7.30
_BINARY_ANALYSIS_WINDOW = 4096
_BINARY_NULL_BYTE_RATIO_THRESHOLD = 0.01


def _calculate_shannon_entropy(data: bytes) -> float:
    """Return Shannon entropy (0.0-8.0 bits/byte) for the given byte sample."""
    if not data:
        return 0.0

    import math
    from collections import Counter

    counts = Counter(data)
    total = len(data)
    entropy = 0.0

    for count in counts.values():
        p = count / total
        entropy -= p * math.log2(p)

    return entropy


def _is_binary(content: bytes) -> bool:
    """
    Detect binary content using layered checks.

    SECURITY:
    1) Magic-byte signatures for known binary formats.
    2) Null-byte ratio and entropy analysis for ambiguous/crafted files.
    """
    if not content:
        return False

    prefix = content[:16]
    if any(prefix.startswith(m) for m in _BINARY_MAGIC_BYTES):
        return True

    sample = content[:_BINARY_ANALYSIS_WINDOW]

    # Null bytes are a strong indicator of binary payloads.
    null_ratio = sample.count(0) / len(sample)
    if null_ratio >= _BINARY_NULL_BYTE_RATIO_THRESHOLD:
        return True

    # High entropy indicates likely binary content.
    if _calculate_shannon_entropy(sample) >= _BINARY_ENTROPY_THRESHOLD:
        return True

    return False


def read_file_bytes(
    filepath: Union[str, Path],
    max_size_kb: int | None = None,
    normalize_encoding: bool = True,
    detect_binary: bool = False,
) -> bytes | None:
    """
    Read file bytes with size limit and optional encoding normalization.

    Args:
        filepath: Path to the file to read.
        max_size_kb: Maximum file size in KB. Uses config default if None.
        normalize_encoding: If True, normalizes to UTF-8 with fallback handling.
        detect_binary: If True, returns None for binary files.

    Returns:
        Raw file bytes (normalized if requested), or None if:
        - File cannot be read
        - File exceeds size limit
        - File is binary (if detect_binary=True)
    """
    filepath_str = str(filepath)

    # Get size limit from config if not specified
    if max_size_kb is None:
        max_size_kb = get_config_cached()["indexer"]["max_file_size_kb"]

    try:
        size = os.path.getsize(filepath_str)
        if size > max_size_kb * 1024:
            LOGGER.debug(
                "file_too_large", filepath=filepath_str, size=size, limit=max_size_kb * 1024
            )
            return None  # Skip oversized files

        # Read raw bytes
        with open(filepath_str, "rb") as f:
            raw = f.read()

        # Binary detection if requested
        if detect_binary and _is_binary(raw):
            LOGGER.debug("binary_file_skipped", filepath=filepath_str)
            return None

        # Normalize to UTF-8 if requested
        if normalize_encoding:
            return normalize_to_utf8(raw)

        return raw

    except OSError as exc:
        LOGGER.debug("file_read_error", filepath=filepath_str, error=str(exc))
        return None


def read_file_text(
    filepath: Union[str, Path],
    max_size_kb: int | None = None,
    encoding: str = "utf-8",
    errors: str = "replace",
) -> str | None:
    """
    Read file as text with encoding fallback.

    Args:
        filepath: Path to the file to read.
        max_size_kb: Maximum file size in KB.
        encoding: Preferred encoding.
        errors: Error handling strategy.

    Returns:
        File content as string, or None if file cannot be read.
    """
    bytes_content = read_file_bytes(
        filepath, max_size_kb=max_size_kb, normalize_encoding=False, detect_binary=True
    )

    if bytes_content is None:
        return None

    try:
        return bytes_content.decode(encoding, errors=errors)
    except UnicodeDecodeError:
        # Use the encoding utility's fallback mechanism
        from batho_core.utils.encoding import decode_bytes_with_fallback

        return decode_bytes_with_fallback(bytes_content, errors=errors)


def write_atomically(
    path: Union[str, Path],
    content: Union[str, bytes, dict],
    *,
    is_json: bool = False,
    encoding: str = "utf-8",
    indent: int | None = 2,
    ensure_parent: bool = True,
) -> bool:
    """
    Write content to file atomically.

    Creates a temporary file, writes content, then renames to avoid partial writes.

    Args:
        path: Target file path.
        content: Content to write (string, bytes, or dict for JSON).
        is_json: If True, serializes content as JSON.
        encoding: Text encoding (used for string content).
        indent: JSON indentation level.
        ensure_parent: If True, creates parent directories.

    Returns:
        True if write succeeded, False otherwise.
    """
    path = Path(path)

    try:
        # Ensure parent directory exists
        if ensure_parent:
            path.parent.mkdir(parents=True, exist_ok=True)

        # Prepare content
        if is_json:
            if isinstance(content, dict):
                text_content = json.dumps(content, indent=indent, ensure_ascii=False)
            else:
                text_content = json.dumps(json.loads(content), indent=indent, ensure_ascii=False)
            bytes_content = text_content.encode(encoding)
        elif isinstance(content, bytes):
            bytes_content = content
        else:
            bytes_content = str(content).encode(encoding)

        # Write to temporary file
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_bytes(bytes_content)

        # Atomic rename
        tmp_path.replace(path)

        LOGGER.debug("file_written_atomically", path=str(path))
        return True

    except (OSError, json.JSONDecodeError, TypeError) as exc:
        LOGGER.warning("atomic_write_failed", path=str(path), error=str(exc))
        # Clean up temp file if it exists
        try:
            tmp_path = path.with_suffix(path.suffix + ".tmp")
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass
        return False


# Legacy compatibility functions
def _read_file_bytes(filepath: str, max_size_kb: int = 500) -> bytes | None:
    """Legacy wrapper for extractor.py compatibility."""
    return read_file_bytes(filepath, max_size_kb=max_size_kb, normalize_encoding=True)


def _read_file_content(filepath: str, max_size_kb: int | None = None) -> bytes | None:
    """Legacy wrapper for codegraph.py compatibility."""
    return read_file_bytes(filepath, max_size_kb=max_size_kb, detect_binary=True)
