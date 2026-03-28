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
from pathlib import Path
from typing import Union


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


def compute_string_hash(content: str, encoding: str = "utf-8", truncate: int | None = None) -> str:
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
    Compute SHA256 hash of file contents using chunked reading.

    Efficiently handles large files by reading in chunks.

    Args:
        filepath: Path to file
        chunk_size: Size of chunks to read (default: 8KB)

    Returns:
        Hexadecimal hash string, or None if file cannot be read
    """
    try:
        sha256_hash = hashlib.sha256()
        with open(filepath, "rb") as f:
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
