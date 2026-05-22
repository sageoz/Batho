"""Optional mmap-backed readers for large persisted graph artifacts.

This adapter is intentionally conservative and always falls back to normal file
reads if mmap is disabled, unsupported, or fails at runtime.
"""

from __future__ import annotations

import json
import mmap
from pathlib import Path
from typing import Any

from batho.utils.logging import get_logger

LOGGER = get_logger(__name__, component="mmap_storage")


def read_bytes_with_optional_mmap(
    path: Path,
    *,
    mmap_enabled: bool,
    min_size_bytes: int,
) -> bytes:
    """Read bytes, optionally via mmap for larger files."""
    if not mmap_enabled:
        return path.read_bytes()

    try:
        size = path.stat().st_size
    except OSError:
        return path.read_bytes()

    if size < max(1, int(min_size_bytes)):
        return path.read_bytes()

    try:
        with path.open("rb") as handle:
            with mmap.mmap(
                handle.fileno(), length=0, access=mmap.ACCESS_READ
            ) as mapped:
                return mapped.read()
    except (OSError, ValueError) as exc:
        LOGGER.warning("mmap_read_fallback", path=str(path), error=str(exc))
        return path.read_bytes()


def read_text_with_optional_mmap(
    path: Path,
    *,
    mmap_enabled: bool,
    min_size_bytes: int,
) -> str:
    """Read UTF-8 text, optionally via mmap for larger files."""
    if not mmap_enabled:
        return path.read_text(encoding="utf-8")

    try:
        size = path.stat().st_size
    except OSError:
        return path.read_text(encoding="utf-8")

    if size < max(1, int(min_size_bytes)):
        return path.read_text(encoding="utf-8")

    try:
        with path.open("rb") as handle:
            with mmap.mmap(
                handle.fileno(), length=0, access=mmap.ACCESS_READ
            ) as mapped:
                return mapped.read().decode("utf-8")
    except (OSError, ValueError) as exc:
        LOGGER.warning("mmap_read_fallback", path=str(path), error=str(exc))
        return path.read_text(encoding="utf-8")


def load_json_with_optional_mmap(
    path: Path,
    *,
    mmap_enabled: bool,
    min_size_bytes: int,
) -> dict[str, Any]:
    """Load a JSON object from disk with optional mmap acceleration."""
    raw_bytes = read_bytes_with_optional_mmap(
        path,
        mmap_enabled=mmap_enabled,
        min_size_bytes=min_size_bytes,
    )
    payload = json.loads(raw_bytes)
    if isinstance(payload, dict):
        return payload
    return {}
