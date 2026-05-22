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

from batho.context.schema import Entity, FileSnapshot, Relationship
from batho.utils.logging import get_logger

logger = get_logger(__name__, component="cache")


class BathoCache:
    """Unified cache service for AST entries and file tracking."""

    _global_init_lock = threading.Lock()

    def __init__(self, cache_path: str = ".ctn/local/cache/cache.db") -> None:
        self._path = Path(cache_path).resolve()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._local = threading.local()
        self.logger = get_logger(__name__, component="cache")
        with BathoCache._global_init_lock:
            self._initialize_db()
            self._migrate_schema()

    def _get_connection(self) -> sqlite3.Connection:
        """Return (or create) the per-thread SQLite connection with optimal PRAGMAs."""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            conn = sqlite3.connect(
                self._path, check_same_thread=False, timeout=30.0
            )
            conn.row_factory = sqlite3.Row
            # WAL mode allows concurrent reads alongside writes and is
            # significantly faster for write-heavy workloads (2-3× throughput).
            conn.execute("PRAGMA journal_mode=WAL")
            # NORMAL sync gives full crash safety with WAL (WAL itself is
            # already durable; only a power-cut during a checkpoint is risky,
            # which is acceptable for a local dev tool cache).
            conn.execute("PRAGMA synchronous=NORMAL")
            # 64 MB page cache — reduces I/O for large repos.
            conn.execute("PRAGMA cache_size=-65536")
            self._local.conn = conn
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
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS file_snapshots (
                    file_path TEXT PRIMARY KEY,
                    file_hash TEXT NOT NULL,
                    file_size INTEGER NOT NULL,
                    encoding TEXT DEFAULT 'utf-8',
                    entity_ids TEXT NOT NULL,
                    gap_sections TEXT NOT NULL,
                    shebang TEXT,
                    encoding_declaration TEXT,
                    file_level_comments TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS fs_idx_file_hash
                ON file_snapshots(file_hash)
                """
            )
            now = datetime.now(timezone.utc).isoformat()
            cursor.execute(
                """
                INSERT OR IGNORE INTO cache_metadata (key, value, updated_at)
                VALUES (?, ?, ?)
                """,
                ("schema_version", "2", now),
            )
            conn.commit()
            self.logger.debug("cache_initialized", cache_path=str(self._path))

    def _migrate_schema(self) -> None:
        """Apply incremental schema migrations."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()

            # Fetch ast_entries columns once — reuse for both migration checks
            # (previously called PRAGMA table_info twice, doubling the work).
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
            if "raw_content" not in ast_columns:
                cursor.execute(
                    "ALTER TABLE ast_entries ADD COLUMN raw_content BLOB"
                )
            if "content_hash" not in ast_columns:
                cursor.execute(
                    "ALTER TABLE ast_entries ADD COLUMN content_hash TEXT"
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
        """Parse an ISO-format timestamp string, falling back to *now* on error.

        A warning is logged when the fallback is used so that timestamp
        corruption does not silently mask TTL-expiry bugs.
        """
        try:
            ts = datetime.fromisoformat(value)
        except (ValueError, TypeError):
            logger.warning(
                "cache_timestamp_parse_failed",
                raw_value=str(value),
                fallback="datetime.now(utc)",
            )
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
            # Use agent view for cache to avoid storing raw_content/raw_bytes (storage view can be regenerated)
            entities_json = json.dumps([e.to_dict(view="agent") for e in entities])
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
                cursor.execute("DELETE FROM ast_entries")
                deleted_count = cursor.rowcount
                self.logger.info(
                    "cache_cleared_all",
                    deleted_count=deleted_count,
                )
            else:
                cursor.execute(
                    "DELETE FROM ast_entries WHERE file_path GLOB ?",
                    (pattern,),
                )
                deleted_count = cursor.rowcount
                self.logger.info(
                    "cache_cleared_pattern",
                    pattern=pattern,
                    deleted_count=deleted_count,
                )

            conn.commit()

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
        """Evict the oldest cached entries until the cache is within max_size_mb.

        Uses a single batched DELETE with a subquery to avoid the previous
        N+1 per-entry DELETE pattern.
        """
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

            # Collect hashes to evict (oldest-first) until bytes_to_remove is met.
            cursor.execute(
                """
                SELECT file_hash, LENGTH(entities) as size
                FROM ast_entries
                ORDER BY cached_at ASC
                """
            )
            rows = cursor.fetchall()
            evict_hashes: list[str] = []
            bytes_evicted = 0
            for row in rows:
                if bytes_evicted >= bytes_to_remove:
                    break
                evict_hashes.append(row["file_hash"])
                bytes_evicted += row["size"]

            if evict_hashes:
                # Single batched DELETE instead of N individual DELETEs.
                placeholders = ",".join("?" * len(evict_hashes))
                cursor.execute(
                    f"DELETE FROM ast_entries WHERE file_hash IN ({placeholders})",
                    evict_hashes,
                )

            conn.commit()
            return len(evict_hashes)

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
        """Upsert all file tracking records without a preceding DELETE.

        Uses ``INSERT OR REPLACE`` (upsert) to update existing records
        while preserving any records not in *file_hashes*.  This avoids the
        previous delete-then-reinsert pattern which could leave the table
        empty if the process crashed between the DELETE commit and the
        subsequent INSERTs.
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()

            # Preserve the is_indexed flag for files already tracked.
            cursor.execute("SELECT file_path, is_indexed FROM file_tracking")
            existing_indexed = {
                row["file_path"]: row["is_indexed"] for row in cursor.fetchall()
            }

            logger.debug(
                "save_all_upserting",
                total_files=len(file_hashes),
                existing_indexed_count=len(existing_indexed),
                is_indexed_param=is_indexed,
            )

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
                    INSERT OR REPLACE INTO file_tracking
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
                total_upserted=len(file_hashes),
                indexed_preserved=indexed_count,
            )

    def load_all(self) -> dict[str, str]:
        return self.get_all_file_hashes()

    # ------------------------------------------------------------------
    # File snapshot methods (Phase 5 - Storage Layer)
    # ------------------------------------------------------------------

    def set_file_snapshot(self, snapshot: FileSnapshot) -> None:
        """Store a file snapshot for reconstruction across index runs.

        Args:
            snapshot: The FileSnapshot to persist.
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            now = datetime.now(timezone.utc).isoformat()
            cursor.execute(
                """
                INSERT OR REPLACE INTO file_snapshots
                (file_path, file_hash, file_size, encoding, entity_ids, gap_sections,
                 shebang, encoding_declaration, file_level_comments, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot.file_path,
                    snapshot.file_hash,
                    snapshot.file_size,
                    snapshot.encoding,
                    json.dumps(snapshot.entity_ids),
                    json.dumps(snapshot.gap_sections),
                    snapshot.shebang,
                    snapshot.encoding_declaration,
                    json.dumps(snapshot.file_level_comments),
                    now,
                    now,
                ),
            )
            conn.commit()
            self.logger.debug(
                "file_snapshot_saved",
                file_path=snapshot.file_path,
                file_hash=snapshot.file_hash,
            )

    def get_file_snapshot(self, file_path: str) -> FileSnapshot | None:
        """Retrieve a stored file snapshot.

        Args:
            file_path: The file path to look up.

        Returns:
            The FileSnapshot if found, None otherwise.
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM file_snapshots WHERE file_path = ?",
                (file_path,),
            )
            row = cursor.fetchone()
            if row is None:
                return None

            return FileSnapshot(
                file_path=row["file_path"],
                file_hash=row["file_hash"],
                file_size=row["file_size"],
                encoding=row["encoding"],
                entity_ids=json.loads(row["entity_ids"]),
                gap_sections=json.loads(row["gap_sections"]),
                shebang=row["shebang"],
                encoding_declaration=row["encoding_declaration"],
                file_level_comments=json.loads(row["file_level_comments"] or "[]"),
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )

    def delete_file_snapshot(self, file_path: str) -> None:
        """Delete a stored file snapshot.

        Args:
            file_path: The file path of the snapshot to delete.
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM file_snapshots WHERE file_path = ?",
                (file_path,),
            )
            conn.commit()
            self.logger.debug(
                "file_snapshot_deleted",
                file_path=file_path,
            )

    def get_all_file_snapshots(self) -> dict[str, FileSnapshot]:
        """Retrieve all stored file snapshots in a single query.

        Previously used an N+1 pattern (SELECT file_path ... then one
        get_file_snapshot() per path).  Now fetches all rows in a single
        ``SELECT *`` and deserializes them in-process.
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM file_snapshots")
            rows = cursor.fetchall()

        result: dict[str, FileSnapshot] = {}
        for row in rows:
            try:
                snap = FileSnapshot(
                    file_path=row["file_path"],
                    file_hash=row["file_hash"],
                    file_size=row["file_size"],
                    encoding=row["encoding"],
                    entity_ids=json.loads(row["entity_ids"]),
                    gap_sections=json.loads(row["gap_sections"]),
                    shebang=row["shebang"],
                    encoding_declaration=row["encoding_declaration"],
                    file_level_comments=json.loads(row["file_level_comments"] or "[]"),
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                )
                result[row["file_path"]] = snap
            except (json.JSONDecodeError, KeyError, TypeError) as exc:
                logger.warning(
                    "file_snapshot_deserialize_failed",
                    file_path=row["file_path"],
                    error=str(exc),
                )
        return result

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
