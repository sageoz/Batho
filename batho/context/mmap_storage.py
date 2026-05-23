"""Legacy compatibility shim — mmap storage is dead.

All hot-path data now lives in the unified .batho SQLite database.
These functions remain only as simple file readers for callers that
still reference them during the transition. They will be deleted in
Phase 6 cleanup.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def read_bytes_with_optional_mmap(
    path: Path,
    *,
    mmap_enabled: bool = False,
    min_size_bytes: int = 0,
) -> bytes:
    """Read bytes from a file (mmap removed)."""
    return path.read_bytes()


def read_text_with_optional_mmap(
    path: Path,
    *,
    mmap_enabled: bool = False,
    min_size_bytes: int = 0,
) -> str:
    """Read UTF-8 text from a file (mmap removed)."""
    return path.read_text(encoding="utf-8")


def load_json_with_optional_mmap(
    path: Path,
    *,
    mmap_enabled: bool = False,
    min_size_bytes: int = 0,
) -> dict[str, Any]:
    """Load a JSON dict from a file (mmap removed)."""
    payload = json.loads(path.read_bytes())
    if isinstance(payload, dict):
        return payload
    return {}
