"""Unified artifact storage backed by the .batho SQLite database (v2.0).

Public API:
- get_database  → BathoDatabase instance
"""

from __future__ import annotations

from batho.storage.engine import BathoDatabase, get_database, resolve_db_path

__all__ = ["BathoDatabase", "get_database", "resolve_db_path"]
