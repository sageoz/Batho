"""FS browse handler — Safe directory browsing for workspace picker.

Provides secure directory browsing with path traversal protection
for the dashboard workspace selection UI.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from batho.bridge_core.deps import WorkspaceDeps
from batho.utils.logging import get_logger

LOGGER = get_logger(__name__, component="bridge_core.handlers.fs")

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
            is_workspace = False

            if is_dir:
                try:
                    is_workspace = bool(list(item.glob("artifact_*.batho")))
                except OSError:
                    pass

            entries.append({
                "name": name,
                "path": str(item),
                "is_dir": is_dir,
                "is_ctn": is_workspace,
                "is_workspace": is_workspace,
            })
        except (PermissionError, OSError):
            continue

    entries.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))

    return entries


def handle_fs_browse(deps: WorkspaceDeps, params: dict) -> dict:
    """Handle GET /api/v2/fs/browse

    Returns directory listing with safety checks.

    Args:
        deps: Workspace dependencies
        params: Query parameters (required: path)

    Returns:
        dict with keys: entries, path
    """
    path = params.get("path")
    if not path:
        return {
            "ok": False,
            "error": "Missing required parameter: path",
            "data": {},
        }

    try:
        entries = browse_directory(path)
        return {
            "ok": True,
            "data": {
                "entries": entries,
                "path": path,
            },
        }
    except PermissionError as e:
        LOGGER.warning("fs_browse_permission_denied", path=path, error=str(e))
        return {
            "ok": False,
            "error": str(e),
            "data": {},
        }
    except FileNotFoundError as e:
        LOGGER.warning("fs_browse_not_found", path=path, error=str(e))
        return {
            "ok": False,
            "error": str(e),
            "data": {},
        }
    except NotADirectoryError as e:
        LOGGER.warning("fs_browse_not_directory", path=path, error=str(e))
        return {
            "ok": False,
            "error": str(e),
            "data": {},
        }
    except Exception as e:
        LOGGER.error("fs_browse_error", error=str(e), path=path)
        return {
            "ok": False,
            "error": str(e),
            "data": {},
        }


__all__ = [
    "handle_fs_browse",
    "browse_directory",
]
