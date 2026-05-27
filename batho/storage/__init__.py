"""batho.storage — Unified SQLite-backed persistence engine.

This package provides the single-file `.batho` database that replaces the
legacy `.ctn` directory of JSON artifacts. All graph data, BSG payloads,
context outputs, snapshots, and sync metadata live in one ACID-compliant
SQLite database per project.
"""

from batho.storage.engine import BathoDatabase, get_database, resolve_db_path

__all__ = ["BathoDatabase", "get_database", "resolve_db_path"]
