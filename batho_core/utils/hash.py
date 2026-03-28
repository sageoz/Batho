"""
backend/utils/hash.py — Unified SHA256 hash computation utilities.

Provides consistent hash functions for:
- Content hashing (bytes and strings)
- File hashing (with chunked reading for large files)
- Entity and relationship ID generation (deterministic, truncated hashes)
"""

from __future__ import annotations

import functools
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Union

# Binary detection functions copied from file_io to avoid circular import
import math
from collections import Counter

_BINARY_MAGIC_BYTES: tuple[bytes, ...] = (
    b"\x00\x00\x01\xba",  # MPEG-2
    b"\x00\x00\x01\xb3",  # MPEG-1
    b"\x30\x26\xb2\x75\x8e\x66\xcf\x11",  # ASF/WMA
    b"\x24\x49\x44\x33",  # MP3
    b"\x66\x74\x79\x70\x69\x73\x6f\x6d",  # MP4
    b"\x52\x49\x46\x46\xff\xff\xff\xff\x57\x41\x56\x45",  # WAV
    b"\x89\x50\x4e\x47\x0d\x0a\x1a\x0a",  # PNG
    b"\xff\xd8\xff",  # JPEG
    b"\x47\x49\x46\x38",  # GIF
    b"\x42\x4d",  # BMP
    b"\x49\x49\x2a\x00",  # TIFF LE
    b"\x4d\x4d\x00\x2a",  # TIFF BE
    b"\x25\x50\x44\x46",  # PDF
    b"\x37\x7a\xbc\xaf\x27\x1c",  # 7z
    b"\x50\x4b\x03\x04",  # ZIP
    b"\x50\x4b\x05\x06",  # ZIP (empty)
    b"\x50\x4b\x07\x08",  # ZIP (spanned)
    b"\x52\x61\x72\x21\x1a\x07\x00",  # RAR 4.0
    b"\x52\x61\x72\x21\x1a\x07\x01\x00",  # RAR 5.0
    b"\x1f\x8b",  # GZIP
    b"\xfd\x37\x7a\x58\x5a\x00",  # XZ
    b"\x75\x73\x74\x61\x72\x00",  # TAR
    b"\x75\x73\x74\x61\x72\x20\x20\x00",  # TAR
)

_BINARY_ENTROPY_THRESHOLD = 7.30
_BINARY_ANALYSIS_WINDOW = 4096
_BINARY_NULL_BYTE_RATIO_THRESHOLD = 0.01


def _calculate_shannon_entropy(data: bytes) -> float:
    """Return Shannon entropy (0.0-8.0 bits/byte) for the given byte sample."""
    if not data:
        return 0.0

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


def compute_bytes_hash(content: bytes, truncate: int | None = None) -> str:
    """
    Compute SHA256 hash of bytes content.

    Args:
        content: Binary content to hash
        truncate: If provided, truncate hash to this many characters

    Returns:
        Hexadecimal hash string
    """
    hash_val = hashlib.sha256(content).hexdigest()
    return hash_val[:truncate] if truncate else hash_val


def compute_string_hash(
    content: str, encoding: str = "utf-8", truncate: int | None = None
) -> str:
    """
    Compute SHA256 hash of string content.

    Args:
        content: String content to hash
        encoding: Character encoding to use (default: utf-8)
        truncate: If provided, truncate hash to this many characters

    Returns:
        Hexadecimal hash string
    """
    return compute_bytes_hash(content.encode(encoding), truncate)


def compute_file_hash(filepath: Path | str, chunk_size: int = 8192) -> str | None:
    """
    Compute content-aware signature of file contents.

    For text files: SHA256 hash of contents.
    For binary files: size_mtime signature.
    Efficiently handles large files by reading in chunks.

    Args:
        filepath: Path to file
        chunk_size: Size of chunks to read (default: 8KB)

    Returns:
        Signature string, or None if file cannot be read
    """
    try:
        path = Path(filepath)
        stat = path.stat()
        size = stat.st_size
        mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
        with open(path, "rb") as f:
            first_chunk = f.read(min(1024, size))
            if _is_binary(first_chunk):
                return f"{size}_{mtime.isoformat()}"
            else:
                sha256_hash = hashlib.sha256(first_chunk)
                for chunk in iter(lambda: f.read(chunk_size), b""):
                    sha256_hash.update(chunk)
                return sha256_hash.hexdigest()
    except (IOError, OSError):
        return None


@functools.lru_cache(maxsize=1024)
def compute_file_hash_cached(filepath: str, mtime: float) -> str | None:
    """
    Cached version of compute_file_hash - use mtime to invalidate cache on file change.

    Args:
        filepath: Path to file (as string for cacheability)
        mtime: File modification time - changing this invalidates the cache

    Returns:
        Hexadecimal hash string, or None if file cannot be read
    """
    return compute_file_hash(filepath)


def generate_entity_id(entity_type: str, name: str, file: str, line: int) -> str:
    """
    Generate deterministic entity ID (16-char truncated hash).

    The ID is derived from entity attributes to ensure consistency
    across multiple runs on the same code.

    Args:
        entity_type: Type of entity (e.g., 'FUNCTION', 'CLASS')
        name: Entity name
        file: File path
        line: Line number

    Returns:
        16-character hexadecimal hash string
    """
    content = f"{entity_type}:{name}:{file}:{line}"
    return compute_string_hash(content, truncate=16)


def generate_relationship_id(source_id: str, target_id: str, rel_type: str) -> str:
    """
    Generate deterministic relationship ID (16-char truncated hash).

    The ID is derived from relationship attributes to ensure consistency
    across multiple runs on the same code.

    Args:
        source_id: Source entity ID
        target_id: Target entity ID
        rel_type: Relationship type (e.g., 'CALLS', 'IMPORTS')

    Returns:
        16-character hexadecimal hash string
    """
    content = f"{source_id}:{target_id}:{rel_type}"
    return compute_string_hash(content, truncate=16)
