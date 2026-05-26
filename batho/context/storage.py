"""Unified artifact storage backed by the .batho SQLite database (v2.0).

Public API:
- get_database  → BathoDatabase instance
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from batho.config import get_config_cached
from batho.storage.engine import BathoDatabase, get_database
from batho.utils.logging import get_logger

LOGGER = get_logger(__name__, component="storage")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=True, sort_keys=True)


def _resolve_db_path(root_or_db: Path | None = None) -> Path:
    """Resolve the .batho database path from a root directory or direct path."""
    if root_or_db is None:
        root_or_db = Path.cwd()
    resolved = Path(root_or_db).resolve()
    if resolved.suffix == ".batho":
        return resolved
    # Treat as repo root
    cfg = get_config_cached()
    db_name = cfg.get("paths", {}).get("db_path", ".batho")
    if not db_name or db_name == ".batho":
        from batho.storage.engine import artifact_filename
        return resolved / artifact_filename(resolved)
    return resolved / db_name


# ---------------------------------------------------------------------------
# Database access
# ---------------------------------------------------------------------------


def get_registry_stats(root: Path) -> dict[str, Any]:
    """Get database statistics."""
    db = get_database(root)
    return db.get_stats()
