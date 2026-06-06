"""Arrow Bundle storage — pure Arrow IPC replacement for SQLite.

Public API:
  BathoBundle     — unified façade (replaces BathoDatabase)
  get_bundle      — cached factory (replaces get_database)
  resolve_bundle_dir — path resolver (replaces resolve_db_path)
"""

from .bundle import BathoBundle, get_bundle, resolve_bundle_dir

__all__ = ["BathoBundle", "get_bundle", "resolve_bundle_dir"]
