"""
backend/context/unified_cache.py — Unified SQLite cache for AST and file tracking.

Consolidates AST entity caching and file hash tracking into a single cache.db.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from batho.context.schema import Entity, Relationship
from batho.utils.logging import get_logger

logger = get_logger(__name__, component="cache")


class BathoCache:
    """Unified cache service for AST entries and file tracking."""

    def __init__(self, cache_path: str = ".ctn/local/cache.db") -> None:
        self._path = Path(cache_path).resolve()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._local = threading.local()
        self.logger = get_logger(__name__, component="cache")
        self._initialize_db()
        self._migrate_schema()

    def _get_connection(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(
                self._path, check_same_thread=False, timeout=30.0
            )
            self._local.conn.row_factory = sqlite3.Row
        return self._local.conn

    def _initialize_db(self) -> None:
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS cache_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS ast_entries (
                    file_hash TEXT PRIMARY KEY,
                    file_path TEXT NOT NULL,
                    entities TEXT NOT NULL,
                    relationships TEXT,
                    mtime REAL NOT NULL,
                    size INTEGER NOT NULL,
                    cached_at TEXT NOT NULL,
                    ttl_days INTEGER DEFAULT 30
                )
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS ast_idx_file_path
                ON ast_entries(file_path)
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS ast_idx_cached_at
                ON ast_entries(cached_at)
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS file_tracking (
                    file_path TEXT PRIMARY KEY,
                    content_hash TEXT NOT NULL,
                    mtime REAL NOT NULL,
                    size INTEGER NOT NULL,
                    is_indexed INTEGER DEFAULT 0,
                    updated_at TEXT NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS ft_idx_content_hash
                ON file_tracking(content_hash)
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS ft_idx_is_indexed
                ON file_tracking(is_indexed)
                """
            )
            now = datetime.now(timezone.utc).isoformat()
            cursor.execute(
                """
                INSERT OR IGNORE INTO cache_metadata (key, value, updated_at)
                VALUES (?, ?, ?)
                """,
                ("schema_version", "1", now),
            )
            conn.commit()
            self.logger.debug("cache_initialized", cache_path=str(self._path))

    def _migrate_schema(self) -> None:
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(ast_entries)")
            ast_columns = {row[1] for row in cursor.fetchall()}
            if "relationships" not in ast_columns:
                cursor.execute(
                    "ALTER TABLE ast_entries ADD COLUMN relationships TEXT"
                )
            if "ttl_days" not in ast_columns:
                cursor.execute(
                    "ALTER TABLE ast_entries ADD COLUMN ttl_days INTEGER DEFAULT 30"
                )
            cursor.execute("PRAGMA table_info(file_tracking)")
            file_columns = {row[1] for row in cursor.fetchall()}
            if "is_indexed" not in file_columns:
                cursor.execute(
                    "ALTER TABLE file_tracking ADD COLUMN is_indexed INTEGER DEFAULT 0"
                )
            conn.commit()

    @staticmethod
    def _parse_timestamp(value: str) -> datetime:
        try:
            ts = datetime.fromisoformat(value)
        except ValueError:
            return datetime.now(timezone.utc)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts

    # ------------------------------------------------------------------
    # AST cache methods
    # ------------------------------------------------------------------

    def get_ast(self, file_hash: str) -> tuple[list[Entity], list[Relationship]] | None:
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT entities, relationships, cached_at, ttl_days
                FROM ast_entries
                WHERE file_hash = ?
                """,
                (file_hash,),
            )
            row = cursor.fetchone()
            if row is None:
                return None

            cached_at = self._parse_timestamp(row["cached_at"])
            ttl_days = row["ttl_days"] or 30
            if cached_at + timedelta(days=ttl_days) < datetime.now(timezone.utc):
                cursor.execute(
                    "DELETE FROM ast_entries WHERE file_hash = ?", (file_hash,)
                )
                conn.commit()
                return None

            try:
                entities_data = json.loads(row["entities"])
                entities = [Entity.from_dict(e) for e in entities_data]
                rel_data = json.loads(row["relationships"] or "[]")
                relationships = [Relationship.from_dict(r) for r in rel_data]
                return entities, relationships
            except (json.JSONDecodeError, TypeError) as exc:
                self.logger.warning(
                    "cache_deserialize_failed", file_hash=file_hash, error=str(exc)
                )
                cursor.execute(
                    "DELETE FROM ast_entries WHERE file_hash = ?", (file_hash,)
                )
                conn.commit()
                return None

    def set_ast(
        self,
        file_hash: str,
        file_path: str,
        entities: list[Entity],
        relationships: list[Relationship],
        mtime: float,
        size: int,
        ttl_days: int = 30,
    ) -> None:
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            entities_json = json.dumps([e.to_dict() for e in entities])
            relationships_json = json.dumps([r.to_dict() for r in relationships])
            cached_at = datetime.now(timezone.utc).isoformat()
            cursor.execute(
                """
                INSERT OR REPLACE INTO ast_entries
                (file_hash, file_path, entities, relationships, mtime, size, cached_at, ttl_days)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    file_hash,
                    file_path,
                    entities_json,
                    relationships_json,
                    mtime,
                    size,
                    cached_at,
                    ttl_days,
                ),
            )
            conn.commit()

    def delete_ast(self, file_hash: str) -> None:
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM ast_entries WHERE file_hash = ?", (file_hash,))
            conn.commit()

    def delete_ast_by_path(self, file_path: str) -> int:
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM ast_entries WHERE file_path = ?", (file_path,))
            deleted = cursor.rowcount
            conn.commit()
            return deleted

    def delete_ast_by_pattern(self, pattern: str) -> int:
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM ast_entries WHERE file_path GLOB ?", (pattern,)
            )
            deleted = cursor.rowcount
            conn.commit()
            return deleted

    def clear_ast_cache(self, older_than_days: int | None = None) -> int:
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            if older_than_days is None:
                cursor.execute("DELETE FROM ast_entries")
            else:
                cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)
                cursor.execute(
                    "DELETE FROM ast_entries WHERE cached_at < ?",
                    (cutoff.isoformat(),),
                )
            deleted = cursor.rowcount
            conn.commit()
            return deleted

    def cleanup_expired_cache(self) -> int:
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                DELETE FROM ast_entries
                WHERE datetime(cached_at) < datetime('now', '-' || ttl_days || ' days')
                """
            )
            deleted = cursor.rowcount
            conn.commit()
            return deleted

    def enforce_max_size(self, max_size_mb: int) -> int:
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT SUM(LENGTH(entities)) as total_size FROM ast_entries"
            )
            total_size_result = cursor.fetchone()["total_size"]
            total_size_mb = (
                (total_size_result / (1024 * 1024)) if total_size_result else 0
            )
            if total_size_mb <= max_size_mb:
                return 0

            target_size_mb = max_size_mb * 0.9
            bytes_to_remove = int((total_size_mb - target_size_mb) * 1024 * 1024)
            deleted_count = 0
            bytes_removed = 0

            cursor.execute(
                """
                SELECT file_hash, LENGTH(entities) as size
                FROM ast_entries
                ORDER BY cached_at ASC
                """
            )
            rows = cursor.fetchall()
            for row in rows:
                if bytes_removed >= bytes_to_remove:
                    break
                cursor.execute(
                    "DELETE FROM ast_entries WHERE file_hash = ?", (row["file_hash"],)
                )
                deleted_count += 1
                bytes_removed += row["size"]

            conn.commit()
            return deleted_count

    # ------------------------------------------------------------------
    # File tracking methods
    # ------------------------------------------------------------------

    def get_file_hash(self, file_path: str) -> str | None:
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT content_hash FROM file_tracking WHERE file_path = ?",
                (file_path,),
            )
            row = cursor.fetchone()
            return row["content_hash"] if row else None

    def set_file_hash(
        self,
        file_path: str,
        content_hash: str,
        mtime: float,
        size: int,
        is_indexed: bool = False,
    ) -> None:
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            now = datetime.now(timezone.utc).isoformat()
            cursor.execute(
                """
                INSERT OR REPLACE INTO file_tracking
                (file_path, content_hash, mtime, size, is_indexed, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (file_path, content_hash, mtime, size, int(is_indexed), now),
            )
            conn.commit()

    def delete_file_hash(self, file_path: str) -> None:
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM file_tracking WHERE file_path = ?", (file_path,))
            conn.commit()

    def get_all_file_hashes(self) -> dict[str, str]:
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT file_path, content_hash FROM file_tracking")
            return {row["file_path"]: row["content_hash"] for row in cursor.fetchall()}

    def get_unindexed_files(self) -> dict[str, str]:
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT file_path, content_hash
                FROM file_tracking
                WHERE is_indexed = 0
                """
            )
            return {row["file_path"]: row["content_hash"] for row in cursor.fetchall()}

    def save_all(
        self, file_hashes: dict[str, str], root: Path, is_indexed: bool = False
    ) -> None:
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()

            existing_indexed = {}
            cursor.execute("SELECT file_path, is_indexed FROM file_tracking")
            for row in cursor.fetchall():
                existing_indexed[row["file_path"]] = row["is_indexed"]

            logger.debug(
                "save_all_preserving_indexed",
                total_files=len(file_hashes),
                existing_indexed_count=len(existing_indexed),
                is_indexed_param=is_indexed,
            )

            cursor.execute("DELETE FROM file_tracking")
            now = datetime.now(timezone.utc).isoformat()
            indexed_count = 0
            for file_path, content_hash in file_hashes.items():
                full_path = root / file_path
                try:
                    stat = full_path.stat()
                except OSError as exc:
                    logger.warning(
                        "file_hash_save_skipped", path=file_path, error=str(exc)
                    )
                    continue
                was_indexed = existing_indexed.get(file_path, 0)
                final_indexed = was_indexed if was_indexed else int(is_indexed)
                if final_indexed:
                    indexed_count += 1
                cursor.execute(
                    """
                    INSERT INTO file_tracking
                    (file_path, content_hash, mtime, size, is_indexed, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        file_path,
                        content_hash,
                        stat.st_mtime,
                        stat.st_size,
                        final_indexed,
                        now,
                    ),
                )
            conn.commit()
            logger.debug(
                "save_all_complete",
                total_inserted=len(file_hashes),
                indexed_preserved=indexed_count,
            )

    def load_all(self) -> dict[str, str]:
        return self.get_all_file_hashes()

    # ------------------------------------------------------------------
    # Cache management
    # ------------------------------------------------------------------

    def get_stats(self) -> dict[str, Any]:
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) as count FROM ast_entries")
            ast_count = cursor.fetchone()["count"]
            cursor.execute(
                "SELECT SUM(LENGTH(entities)) as total_size FROM ast_entries"
            )
            ast_size = cursor.fetchone()["total_size"]
            ast_size_mb = (ast_size / (1024 * 1024)) if ast_size else 0
            cursor.execute(
                "SELECT MIN(cached_at) as oldest, MAX(cached_at) as newest FROM ast_entries"
            )
            dates = cursor.fetchone()
            cursor.execute("SELECT COUNT(*) as count FROM file_tracking")
            file_count = cursor.fetchone()["count"]
            cursor.execute(
                "SELECT COUNT(*) as count FROM file_tracking WHERE is_indexed = 1"
            )
            indexed_count = cursor.fetchone()["count"]
            cursor.execute(
                "SELECT COUNT(*) as count FROM file_tracking WHERE is_indexed = 0"
            )
            unindexed_count = cursor.fetchone()["count"]
            return {
                "ast_entry_count": ast_count,
                "ast_total_size_mb": round(ast_size_mb, 2),
                "ast_oldest_entry": dates["oldest"],
                "ast_newest_entry": dates["newest"],
                "file_tracking_count": file_count,
                "indexed_files": indexed_count,
                "unindexed_files": unindexed_count,
                "cache_path": str(self._path),
            }

    def vacuum(self) -> None:
        with self._lock:
            conn = self._get_connection()
            conn.execute("VACUUM")
            conn.commit()

    def close(self) -> None:
        with self._lock:
            if hasattr(self._local, "conn") and self._local.conn is not None:
                self._local.conn.close()
                self._local.conn = None
