"""Shared CLI utilities for batho CLI commands."""

from __future__ import annotations

from pathlib import Path


def find_workspace_with_db(start_path: Path) -> Path | None:
    """Find the nearest ancestor directory that contains an artifact database.

    Returns the directory path on success, None if not found walking to root.
    """
    from batho.storage.engine import artifact_filename

    current = start_path.resolve()

    while True:
        db_name = artifact_filename(current)
        if (current / db_name).exists():
            return current

        parent = current.parent
        if parent == current:
            break
        current = parent

    return None
