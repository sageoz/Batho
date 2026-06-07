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
import threading
from pathlib import Path
from typing import Any, Union

from batho.core.config import get_config_cached
from batho.utils.encoding import normalize_to_utf8
from batho.utils.hash import _is_binary, compute_bytes_hash
from batho.utils.logging import get_logger

LOGGER = get_logger(__name__)

_UMASK_LOCK = threading.Lock()


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
                "file_too_large",
                filepath=filepath_str,
                size=size,
                limit=max_size_kb * 1024,
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
        return bytes_content.decode(encoding, errors="strict")
    except UnicodeDecodeError:
        # Use the encoding utility's fallback mechanism
        from batho.utils.encoding import decode_bytes_with_fallback

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
    tmp_path = None

    try:
        # Ensure parent directory exists
        if ensure_parent:
            path.parent.mkdir(parents=True, exist_ok=True)

        # Prepare content
        if is_json:
            if isinstance(content, dict):
                text_content = json.dumps(content, indent=indent, ensure_ascii=False)
            else:
                text_content = json.dumps(
                    json.loads(content), indent=indent, ensure_ascii=False
                )
            bytes_content = text_content.encode(encoding)
        elif isinstance(content, bytes):
            bytes_content = content
        else:
            bytes_content = str(content).encode(encoding)

        # Check target permissions to preserve them or apply default mode using umask
        original_mode = None
        if path.exists():
            try:
                original_mode = path.stat().st_mode & 0o7777
            except OSError:
                pass
        else:
            try:
                with _UMASK_LOCK:
                    current_umask = os.umask(0)
                    os.umask(current_umask)
                    original_mode = 0o666 & ~current_umask
            except Exception:
                original_mode = 0o666

        # Write to temporary file
        import tempfile
        fd, tmp_path_str = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
        tmp_path = Path(tmp_path_str)
        
        with os.fdopen(fd, 'wb') as f:
            f.write(bytes_content)

        if original_mode is not None:
            try:
                os.chmod(tmp_path_str, original_mode)
            except OSError:
                pass

        # Atomic rename
        tmp_path.replace(path)
        tmp_path = None

        LOGGER.debug("file_written_atomically", path=str(path))
        return True

    except (OSError, json.JSONDecodeError, TypeError) as exc:
        LOGGER.warning("atomic_write_failed", path=str(path), error=str(exc))
        # Clean up temp file if it exists
        if tmp_path is not None:
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except OSError as cleanup_exc:
                LOGGER.debug(
                    "temp_file_cleanup_failed",
                    temp_path=str(tmp_path),
                    error=str(cleanup_exc),
                )
        return False


# Legacy wrappers removed in v2.0 - use read_file_bytes directly
