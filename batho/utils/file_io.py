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

        # Check target permissions to preserve them
        original_mode = None
        if path.exists():
            try:
                original_mode = path.stat().st_mode & 0o7777
            except OSError:
                pass

        # Write to temporary file with a unique name
        import uuid
        tmp_path = path.with_suffix(f".tmp.{os.getpid()}.{uuid.uuid4().hex[:8]}")
        
        with open(tmp_path, "wb") as f:
            f.write(bytes_content)

        if original_mode is not None:
            try:
                os.chmod(tmp_path, original_mode)
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





class InterProcessLock:
    """An advisory file lock to prevent concurrent build/patch runs on the same repository."""

    _acquired_paths: set[Path] = set()

    def __init__(self, lock_file_path: Path | str) -> None:
        self.lock_file_path = Path(lock_file_path).resolve()
        self.fd: Any = None

    def __enter__(self) -> InterProcessLock:
        try:
            import fcntl
            self.fd = open(self.lock_file_path, "w")
            try:
                fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                self.fd.close()
                self.fd = None
                raise RuntimeError("Another Batho process is already running on this repository.")
            except BaseException:
                self.fd.close()
                self.fd = None
                raise
        except ImportError:
            # Fallback for Windows
            try:
                import msvcrt
                self.fd = open(self.lock_file_path, "w")
                try:
                    msvcrt.locking(self.fd.fileno(), msvcrt.LK_NBLCK, 1)
                except (OSError, IOError):
                    self.fd.close()
                    self.fd = None
                    raise RuntimeError("Another Batho process is already running on this repository.")
                except BaseException:
                    self.fd.close()
                    self.fd = None
                    raise
            except ImportError:
                # Basic lock-file checking fallback if neither is available
                if self.lock_file_path.exists():
                    raise RuntimeError("Another Batho process is already running on this repository.")
                self.lock_file_path.touch()
        
        InterProcessLock._acquired_paths.add(self.lock_file_path)
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        InterProcessLock._acquired_paths.discard(self.lock_file_path)
        try:
            import fcntl
            if self.fd:
                try:
                    fcntl.flock(self.fd, fcntl.LOCK_UN)
                except Exception:
                    pass
                try:
                    self.fd.close()
                except Exception:
                    pass
                self.fd = None
        except ImportError:
            try:
                import msvcrt
                if self.fd:
                    try:
                        self.fd.seek(0)
                        msvcrt.locking(self.fd.fileno(), msvcrt.LK_UNLCK, 1)
                    except Exception:
                        pass
                    try:
                        self.fd.close()
                    except Exception:
                        pass
                    self.fd = None
            except ImportError:
                try:
                    if self.lock_file_path.exists():
                        self.lock_file_path.unlink()
                except Exception:
                    pass

    @classmethod
    def is_locked_by_other(cls, lock_file_path: Path | str) -> bool:
        try:
            path = Path(lock_file_path).resolve()
            if not path.exists():
                return False
            if path in cls._acquired_paths:
                return False
            lock = cls(path)
            with lock:
                return False
        except RuntimeError:
            return True
        except Exception:
            return False

