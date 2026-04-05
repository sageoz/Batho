"""
backend/context/cache.py — SQLite-based AST entity cache.

Replaces the old file state cache with a more powerful cache that stores
actual extracted entities keyed by file content hash.

Features:
- SQLite-based storage in ~/.batho/ast_cache.db
- Thread-safe operations with connection pooling
- TTL-based expiration
- Size-based LRU eviction
- mtime and size validation for cache hits
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from batho.context.schema import Entity
from batho.utils.logging import get_logger

logger = get_logger(__name__, component="ast_cache")


# ---------------------------------------------------------------------------
# AST Cache
# ---------------------------------------------------------------------------


class ASTCache:
    """
    SQLite-based cache for AST entity extraction results.

    Stores extracted entities keyed by file content hash (SHA-256).
    Includes mtime and size validation to ensure cache hits are valid.
    """

    def __init__(self, cache_path: str = "~/.batho/ast_cache.db") -> None:
        """
        Initialize the AST cache.

        Args:
            cache_path: Path to the SQLite cache database (can include ~ for home dir).
        """
        self._path = Path(cache_path).expanduser().resolve()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._local = threading.local()
        self.logger = get_logger(__name__, component="ast_cache")
        self._initialize_db()

    def _get_connection(self) -> sqlite3.Connection:
        """
        Get a thread-local database connection.

        Each thread gets its own connection for thread safety.
        """
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(
                self._path, check_same_thread=False, timeout=30.0
            )
            self._local.conn.row_factory = sqlite3.Row
        return self._local.conn

    def _initialize_db(self) -> None:
        """Initialize the database schema if it doesn't exist."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS cache_entries (
                    file_hash TEXT PRIMARY KEY,
                    file_path TEXT NOT NULL,
                    entities TEXT NOT NULL,
                    mtime REAL NOT NULL,
                    size INTEGER NOT NULL,
                    cached_at TEXT NOT NULL,
                    ttl_days INTEGER DEFAULT 30
                )
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_file_path ON cache_entries(file_path)
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_cached_at ON cache_entries(cached_at)
                """
            )
            conn.commit()
            self.logger.debug(
                "cache_initialized",
                cache_path=str(self._path),
            )

    def file_hash(self, file_path: str, content: bytes) -> str:
        """
        Compute SHA-256 hash of file content.

        Reads in 64KB chunks for memory efficiency on large files.

        Args:
            file_path: Path to the file (for logging).
            content: File content as bytes.

        Returns:
            Hexadecimal SHA-256 hash.
        """
        hasher = hashlib.sha256()
        # Process in 64KB chunks
        chunk_size = 64 * 1024
        for i in range(0, len(content), chunk_size):
            chunk = content[i : i + chunk_size]
            hasher.update(chunk)
        return hasher.hexdigest()

    def get_cached_entities(
        self,
        file_path: str,
        content_hash: str,
        mtime: float,
        size: int,
    ) -> list[Entity] | None:
        """
        Retrieve cached entities for a file if cache hit and valid.

        Validates mtime and size before returning cached entities.

        Args:
            file_path: Path to the file.
            content_hash: SHA-256 hash of current file content.
            mtime: Current file modification time.
            size: Current file size in bytes.

        Returns:
            List of cached Entity objects if valid cache hit, None otherwise.
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT entities, mtime, size, cached_at, ttl_days
                FROM cache_entries
                WHERE file_hash = ?
                """,
                (content_hash,),
            )
            row = cursor.fetchone()

            if row is None:
                self.logger.debug(
                    "cache_miss",
                    file_path=file_path,
                    reason="hash_not_found",
                )
                return None

            # Check if entry has expired based on TTL
            cached_at = datetime.fromisoformat(row["cached_at"])
            ttl_days = row["ttl_days"]
            if cached_at + timedelta(days=ttl_days) < datetime.now(timezone.utc):
                self.logger.debug(
                    "cache_miss",
                    file_path=file_path,
                    reason="entry_expired",
                    cached_at=str(cached_at),
                    ttl_days=ttl_days,
                )
                # Delete expired entry
                cursor.execute(
                    "DELETE FROM cache_entries WHERE file_hash = ?",
                    (content_hash,),
                )
                conn.commit()
                return None

            # Validate mtime and size
            cached_mtime = row["mtime"]
            cached_size = row["size"]
            if abs(mtime - cached_mtime) > 1.0 or size != cached_size:
                self.logger.debug(
                    "cache_miss",
                    file_path=file_path,
                    reason="mtime_or_size_mismatch",
                    cached_mtime=cached_mtime,
                    current_mtime=mtime,
                    cached_size=cached_size,
                    current_size=size,
                )
                # Delete stale entry
                cursor.execute(
                    "DELETE FROM cache_entries WHERE file_hash = ?",
                    (content_hash,),
                )
                conn.commit()
                return None

            # Cache hit - deserialize entities
            try:
                entities_data = json.loads(row["entities"])
                entities = [Entity.from_dict(e) for e in entities_data]
                self.logger.debug(
                    "cache_hit",
                    file_path=file_path,
                    entity_count=len(entities),
                )
                return entities
            except (json.JSONDecodeError, TypeError) as e:
                self.logger.warning(
                    "cache_deserialize_failed",
                    file_path=file_path,
                    error=str(e),
                )
                # Delete corrupted entry
                cursor.execute(
                    "DELETE FROM cache_entries WHERE file_hash = ?",
                    (content_hash,),
                )
                conn.commit()
                return None

    def cache_entities(
        self,
        file_path: str,
        content_hash: str,
        entities: list[Entity],
        mtime: float,
        size: int,
        ttl_days: int = 30,
    ) -> None:
        """
        Cache extracted entities for a file.

        Args:
            file_path: Path to the file.
            content_hash: SHA-256 hash of file content.
            entities: List of Entity objects to cache.
            mtime: File modification time.
            size: File size in bytes.
            ttl_days: Time-to-live in days (default 30).
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()

            # Serialize entities to JSON
            entities_json = json.dumps([e.to_dict() for e in entities])
            cached_at = datetime.now(timezone.utc).isoformat()

            # Insert or replace
            cursor.execute(
                """
                INSERT OR REPLACE INTO cache_entries
                (file_hash, file_path, entities, mtime, size, cached_at, ttl_days)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    content_hash,
                    file_path,
                    entities_json,
                    mtime,
                    size,
                    cached_at,
                    ttl_days,
                ),
            )
            conn.commit()
            self.logger.debug(
                "cache_entities_stored",
                file_path=file_path,
                entity_count=len(entities),
            )

    def invalidate_cache(self, pattern: str | None = None) -> None:
        """
        Invalidate cache entries.

        If pattern is provided, only invalidate entries matching the pattern.
        If pattern is None, clear all entries.

        Args:
            pattern: Optional glob pattern to match file paths.
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()

            if pattern is None:
                # Clear all entries
                cursor.execute("DELETE FROM cache_entries")
                deleted_count = cursor.rowcount
                self.logger.info(
                    "cache_cleared_all",
                    deleted_count=deleted_count,
                )
            else:
                # Clear entries matching pattern
                cursor.execute(
                    "DELETE FROM cache_entries WHERE file_path GLOB ?",
                    (pattern,),
                )
                deleted_count = cursor.rowcount
                self.logger.info(
                    "cache_cleared_pattern",
                    pattern=pattern,
                    deleted_count=deleted_count,
                )

            conn.commit()

    def get_cache_stats(self) -> dict[str, Any]:
        """
        Get cache statistics.

        Returns:
            Dictionary with cache statistics including entry count,
            total size, hit rate (if tracked), etc.
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()

            # Get entry count
            cursor.execute("SELECT COUNT(*) as count FROM cache_entries")
            entry_count = cursor.fetchone()["count"]

            # Get total size (entities JSON size)
            cursor.execute("SELECT SUM(LENGTH(entities)) as total_size FROM cache_entries")
            total_size_result = cursor.fetchone()["total_size"]
            total_size_mb = (total_size_result / (1024 * 1024)) if total_size_result else 0

            # Get oldest and newest entries
            cursor.execute(
                "SELECT MIN(cached_at) as oldest, MAX(cached_at) as newest FROM cache_entries"
            )
            dates = cursor.fetchone()

            return {
                "entry_count": entry_count,
                "total_size_mb": round(total_size_mb, 2),
                "oldest_entry": dates["oldest"],
                "newest_entry": dates["newest"],
                "cache_path": str(self._path),
            }

    def cleanup_expired_cache(self) -> int:
        """
        Remove expired cache entries based on TTL.

        Returns:
            Number of entries removed.
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()

            # Find expired entries
            cursor.execute(
                """
                DELETE FROM cache_entries
                WHERE datetime(cached_at) < datetime('now', '-' || ttl_days || ' days')
                """
            )
            deleted_count = cursor.rowcount
            conn.commit()

            if deleted_count > 0:
                self.logger.info(
                    "cache_cleanup_expired",
                    deleted_count=deleted_count,
                )

            return deleted_count

    def enforce_max_size(self, max_size_mb: int) -> int:
        """
        Enforce maximum cache size by evicting oldest entries (LRU).

        Args:
            max_size_mb: Maximum cache size in megabytes.

        Returns:
            Number of entries removed.
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()

            # Get current total size
            cursor.execute("SELECT SUM(LENGTH(entities)) as total_size FROM cache_entries")
            total_size_result = cursor.fetchone()["total_size"]
            total_size_mb = (total_size_result / (1024 * 1024)) if total_size_result else 0

            if total_size_mb <= max_size_mb:
                return 0

            # Calculate how much to remove (remove 10% more than needed to avoid frequent evictions)
            target_size_mb = max_size_mb * 0.9
            bytes_to_remove = int((total_size_mb - target_size_mb) * 1024 * 1024)

            # Delete oldest entries until size is under limit
            deleted_count = 0
            bytes_removed = 0

            cursor.execute(
                """
                SELECT file_hash, LENGTH(entities) as size
                FROM cache_entries
                ORDER BY cached_at ASC
                """
            )
            rows = cursor.fetchall()

            for row in rows:
                if bytes_removed >= bytes_to_remove:
                    break
                cursor.execute(
                    "DELETE FROM cache_entries WHERE file_hash = ?",
                    (row["file_hash"],),
                )
                deleted_count += 1
                bytes_removed += row["size"]

            conn.commit()

            if deleted_count > 0:
                self.logger.info(
                    "cache_evicted_lru",
                    deleted_count=deleted_count,
                    bytes_removed_mb=round(bytes_removed / (1024 * 1024), 2),
                    target_size_mb=target_size_mb,
                )

            return deleted_count

    def close(self) -> None:
        """Close the database connection for the current thread."""
        with self._lock:
            if hasattr(self._local, "conn") and self._local.conn is not None:
                self._local.conn.close()
                self._local.conn = None
