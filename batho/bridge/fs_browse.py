"""Safe directory browsing for the path picker UI."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


MAX_ENTRIES = 500
HIDDEN_PREFIXES = (".", "__", ".git", ".svn", ".hg")


ALLOWED_ROOTS = (
    Path.home(),
    Path("/tmp"),
)


def _is_safe_path(path: Path) -> bool:
    """Check if a path is within allowed roots."""
    try:
        resolved = path.resolve()
        return any(resolved == root or root in resolved.parents for root in ALLOWED_ROOTS)
    except (OSError, RuntimeError):
        return False


def browse_directory(root: str) -> list[dict[str, Any]]:
    """Browse a directory safely for the path picker.

    Args:
        root: Directory path to browse

    Returns:
        List of entries with name, path, is_dir, and is_ctn properties
    """
    root_path = Path(os.path.expanduser(root)).resolve()

    if not _is_safe_path(root_path):
        raise PermissionError(f"Access denied: {root} is outside allowed boundaries")

    if not root_path.exists():
        raise FileNotFoundError(f"Directory not found: {root}")
    if not root_path.is_dir():
        raise NotADirectoryError(f"Not a directory: {root}")

    entries = []

    try:
        items = list(root_path.iterdir())
    except PermissionError:
        raise PermissionError(f"Permission denied: {root}")

    for item in items[:MAX_ENTRIES]:
        name = item.name

        if name.startswith(HIDDEN_PREFIXES):
            continue

        try:
            is_dir = item.is_dir()
            is_ctn = False

            if is_dir:
                ctn_index = item / "index.json"
                ctn_sqlite = item / "artifact_registry.sqlite3"
                is_ctn = ctn_index.exists() or ctn_sqlite.exists()

            entries.append({
                "name": name,
                "path": str(item),
                "is_dir": is_dir,
                "is_ctn": is_ctn,
            })
        except (PermissionError, OSError):
            continue

    entries.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))

    return entries


__all__ = [
    "browse_directory",
    "MAX_ENTRIES",
]
