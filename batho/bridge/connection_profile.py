"""
batho/bridge/connection_profile.py — Centralized SQLite pragma configuration.

Provides a single source of truth for SQLite connection tuning across all
Batho subsystems (artifact registry, query indexes, AST cache, bridge layer).

Design goals:
- Eliminate divergent pragma settings between connection_pool.py, storage.py,
  unified_cache.py, and cache_migration.py.
- Distinguish between read-mostly and read-write workloads.
- Distinguish between durability-critical (artifacts) and ephemeral (query
  indexes) data, allowing the latter to use synchronous=NORMAL while the
  former uses synchronous=FULL for crash safety.
- Bootstrap WAL mode at DB creation rather than re-executing PRAGMA on every
  connect.

Usage:
    from batho.bridge.connection_profile import (
        apply_reader_pragmas,
        apply_writer_pragmas,
        bootstrap_wal,
    )

    conn = sqlite3.connect(...)
    apply_writer_pragmas(conn, durability="full")
"""

from __future__ import annotations

import sqlite3
import sys
from typing import Literal

# ---------------------------------------------------------------------------
# Pragma constants
# ---------------------------------------------------------------------------

# Default mmap size: 64 MiB (matches connection_pool.py legacy behavior)
DEFAULT_MMAP_SIZE_BYTES: int = 64 * 1024 * 1024

# Cache size in pages (negative value = KiB). -8000 = 8 MiB cache.
DEFAULT_CACHE_SIZE_KIB: int = -8000

# Busy timeout: how long to wait for locked DB before raising error.
DEFAULT_BUSY_TIMEOUT_MS: int = 5000

# Durability mode for synchronous pragma.
#   "full"   → fsync on every commit; safest for canonical artifacts
#   "normal" → fsync on checkpoint only; safe for query indexes / caches
DurabilityMode = Literal["full", "normal", "off"]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def bootstrap_wal(conn: sqlite3.Connection) -> None:
    """
    Enable WAL journaling mode (one-shot bootstrap on DB creation).

    WAL is a database-level setting that persists. Calling this on first
    open is sufficient; subsequent connections inherit WAL automatically.

    On Windows, WAL is not used due to known file-locking issues with
    network shares; we fall back to the default DELETE journal mode.
    """
    if sys.platform == "win32":
        conn.execute("PRAGMA journal_mode=DELETE")
        return

    # Check current mode to avoid redundant mode-switch attempts
    # which can trigger exclusive locks.
    current_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    if current_mode.lower() != "wal":
        conn.execute("PRAGMA journal_mode=WAL")


def apply_reader_pragmas(
    conn: sqlite3.Connection,
    *,
    mmap_size: int = DEFAULT_MMAP_SIZE_BYTES,
    cache_size_kib: int = DEFAULT_CACHE_SIZE_KIB,
) -> None:
    """
    Apply read-optimized pragmas to a connection.

    Use for connections opened in read-only mode (`?mode=ro` URI). These
    pragmas optimize for query throughput by enabling memory-mapped I/O
    and a moderate page cache.

    Args:
        conn: Open SQLite connection.
        mmap_size: Bytes of file to mmap (default 64 MiB).
        cache_size_kib: Page cache size; negative = KiB (default -8000 = 8 MiB).
    """
    conn.execute("PRAGMA query_only=ON")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute(f"PRAGMA mmap_size={int(mmap_size)}")
    conn.execute(f"PRAGMA cache_size={int(cache_size_kib)}")


def apply_writer_pragmas(
    conn: sqlite3.Connection,
    *,
    durability: DurabilityMode = "normal",
    busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS,
) -> None:
    """
    Apply write-optimized pragmas to a connection.

    Use for connections that may execute INSERT / UPDATE / DELETE.

    Durability policy:
        - "full"   → synchronous=FULL — use for canonical artifacts and
                     content blobs where crash safety is critical.
        - "normal" → synchronous=NORMAL — use for query indexes, caches,
                     and other ephemeral / rebuildable tables.
        - "off"    → synchronous=OFF — use only for bulk import where
                     the writer can be safely retried on crash.

    Args:
        conn: Open SQLite connection.
        durability: Durability mode (see above).
        busy_timeout_ms: How long to wait when DB is locked (default 5000 ms).
    """
    sync_value = {"full": "FULL", "normal": "NORMAL", "off": "OFF"}[durability]
    conn.execute(f"PRAGMA synchronous={sync_value}")
    conn.execute(f"PRAGMA busy_timeout={int(busy_timeout_ms)}")
    conn.execute("PRAGMA temp_store=MEMORY")


def apply_full_profile(
    conn: sqlite3.Connection,
    *,
    durability: DurabilityMode = "normal",
    busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS,
    mmap_size: int = DEFAULT_MMAP_SIZE_BYTES,
    cache_size_kib: int = DEFAULT_CACHE_SIZE_KIB,
    bootstrap: bool = False,
) -> None:
    """
    Apply both reader and writer pragmas (without query_only) for a
    general-purpose connection that needs both read and write access.

    Args:
        conn: Open SQLite connection.
        durability: Durability mode (default "normal").
        busy_timeout_ms: Lock wait timeout in ms.
        mmap_size: mmap size in bytes.
        cache_size_kib: Page cache size in KiB (negative).
        bootstrap: When True, also bootstrap WAL journaling mode. Use only
                   on first open / DB creation.
    """
    if bootstrap:
        bootstrap_wal(conn)

    sync_value = {"full": "FULL", "normal": "NORMAL", "off": "OFF"}[durability]
    conn.execute(f"PRAGMA synchronous={sync_value}")
    conn.execute(f"PRAGMA busy_timeout={int(busy_timeout_ms)}")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute(f"PRAGMA mmap_size={int(mmap_size)}")
    conn.execute(f"PRAGMA cache_size={int(cache_size_kib)}")


__all__ = [
    "DurabilityMode",
    "DEFAULT_MMAP_SIZE_BYTES",
    "DEFAULT_CACHE_SIZE_KIB",
    "DEFAULT_BUSY_TIMEOUT_MS",
    "bootstrap_wal",
    "apply_reader_pragmas",
    "apply_writer_pragmas",
    "apply_full_profile",
]
