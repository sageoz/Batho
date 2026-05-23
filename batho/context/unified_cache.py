"""Unified cache service delegating to the .batho SQLite database.

All AST caching, file tracking, and file snapshot operations are performed
against the unified BathoDatabase. No separate cache.db file is created.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from batho.context.schema import Entity, FileSnapshot, Relationship
from batho.storage.engine import BathoDatabase, get_database
from batho.utils.logging import get_logger

logger = get_logger(__name__, component="cache")


class BathoCache:
    """Unified cache service backed by the .batho database."""

    def __init__(self, cache_path: str = ".batho") -> None:
        # Resolve the database: cache_path is either a direct .batho file
        # or a repo root containing .batho
        path = Path(cache_path).resolve()
        if path.name == ".batho" or path.suffix == ".batho":
            repo_root = path.parent
        elif path.name == "cache.db":
            # Legacy callers passing .ctn/local/cache/cache.db — resolve repo root
            repo_root = path.parent.parent.parent.parent
        else:
            repo_root = path

        self._db = get_database(repo_root)
        self.logger = logger

    # ------------------------------------------------------------------
    # AST cache methods
    # ------------------------------------------------------------------

    def get_ast(self, file_hash: str) -> tuple[list[Entity], list[Relationship]] | None:
        row = self._db.get_ast_cache(file_hash)
        if row is None:
            return None

        try:
            entities_data = json.loads(row["entities_json"])
            entities = [Entity.from_dict(e) for e in entities_data]
            rel_data = json.loads(row.get("relationships_json") or "[]")
            relationships = [Relationship.from_dict(r) for r in rel_data]
            return entities, relationships
        except (json.JSONDecodeError, TypeError) as exc:
            self.logger.warning(
                "cache_deserialize_failed", file_hash=file_hash, error=str(exc)
            )
            self._db.delete_ast_cache(file_hash)
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
        entities_json = json.dumps([e.to_dict(view="agent") for e in entities])
        relationships_json = json.dumps([r.to_dict() for r in relationships])
        self._db.set_ast_cache(
            file_hash,
            file_path,
            entities_json,
            relationships_json,
            mtime,
            size,
            ttl_days=ttl_days,
        )

    def delete_ast(self, file_hash: str) -> None:
        self._db.delete_ast_cache(file_hash)

    def delete_ast_by_path(self, file_path: str) -> int:
        with self._db.connection() as conn:
            cursor = conn.execute(
                "DELETE FROM ast_cache WHERE file_path = ?", (file_path,)
            )
            conn.commit()
            return cursor.rowcount

    def delete_ast_by_pattern(self, pattern: str) -> int:
        with self._db.connection() as conn:
            cursor = conn.execute(
                "DELETE FROM ast_cache WHERE file_path GLOB ?", (pattern,)
            )
            conn.commit()
            return cursor.rowcount

    def clear_ast_cache(self, older_than_days: int | None = None) -> int:
        with self._db.connection() as conn:
            if older_than_days is None:
                cursor = conn.execute("DELETE FROM ast_cache")
            else:
                cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)
                cursor = conn.execute(
                    "DELETE FROM ast_cache WHERE cached_at < ?",
                    (cutoff.isoformat(),),
                )
            conn.commit()
            return cursor.rowcount

    def invalidate_cache(self, pattern: str | None = None) -> None:
        with self._db.connection() as conn:
            if pattern is None:
                cursor = conn.execute("DELETE FROM ast_cache")
            else:
                cursor = conn.execute(
                    "DELETE FROM ast_cache WHERE file_path GLOB ?", (pattern,)
                )
            deleted_count = cursor.rowcount
            conn.commit()
            self.logger.info(
                "cache_invalidated",
                pattern=pattern or "*",
                deleted_count=deleted_count,
            )

    def cleanup_expired_cache(self) -> int:
        return self._db.clear_expired_ast_cache()

    def enforce_max_size(self, max_size_mb: int) -> int:
        with self._db.connection() as conn:
            row = conn.execute(
                "SELECT SUM(LENGTH(entities_json)) as total_size FROM ast_cache"
            ).fetchone()
            total_size_bytes = row["total_size"] if row and row["total_size"] else 0
            total_size_mb = total_size_bytes / (1024 * 1024)

            if total_size_mb <= max_size_mb:
                return 0

            target_size_mb = max_size_mb * 0.9
            bytes_to_remove = int((total_size_mb - target_size_mb) * 1024 * 1024)

            rows = conn.execute(
                """SELECT file_hash, LENGTH(entities_json) as size
                FROM ast_cache ORDER BY cached_at ASC"""
            ).fetchall()

            evict_hashes: list[str] = []
            bytes_evicted = 0
            for r in rows:
                if bytes_evicted >= bytes_to_remove:
                    break
                evict_hashes.append(r["file_hash"])
                bytes_evicted += r["size"]

            if evict_hashes:
                placeholders = ",".join("?" * len(evict_hashes))
                conn.execute(
                    f"DELETE FROM ast_cache WHERE file_hash IN ({placeholders})",
                    evict_hashes,
                )
            conn.commit()
            return len(evict_hashes)

    # ------------------------------------------------------------------
    # File tracking methods
    # ------------------------------------------------------------------

    def get_file_hash(self, file_path: str) -> str | None:
        row = self._db.get_file_tracking(file_path)
        return row["content_hash"] if row else None

    def set_file_hash(
        self,
        file_path: str,
        content_hash: str,
        mtime: float,
        size: int,
        is_indexed: bool = False,
    ) -> None:
        self._db.upsert_file_tracking([{
            "file_path": file_path,
            "content_hash": content_hash,
            "mtime": mtime,
            "size": size,
            "is_indexed": int(is_indexed),
            "last_run_id": None,
        }])

    def delete_file_hash(self, file_path: str) -> None:
        self._db.delete_file_tracking(file_path)

    def get_all_file_hashes(self) -> dict[str, str]:
        return self._db.get_all_file_hashes()

    def get_unindexed_files(self) -> dict[str, str]:
        return self._db.get_unindexed_files()

    def save_all(
        self, file_hashes: dict[str, str], root: Path, is_indexed: bool = False
    ) -> None:
        records: list[dict[str, Any]] = []
        for file_path, content_hash in file_hashes.items():
            full_path = root / file_path
            try:
                stat = full_path.stat()
            except OSError:
                continue
            records.append({
                "file_path": file_path,
                "content_hash": content_hash,
                "mtime": stat.st_mtime,
                "size": stat.st_size,
                "is_indexed": int(is_indexed),
                "last_run_id": None,
            })
        if records:
            self._db.upsert_file_tracking(records)

    def load_all(self) -> dict[str, str]:
        return self.get_all_file_hashes()

    # ------------------------------------------------------------------
    # File snapshot methods
    # ------------------------------------------------------------------

    def set_file_snapshot(self, snapshot: FileSnapshot) -> None:
        self._db.set_file_snapshot({
            "file_path": snapshot.file_path,
            "file_hash": snapshot.file_hash,
            "file_size": snapshot.file_size,
            "encoding": snapshot.encoding,
            "entity_ids": snapshot.entity_ids,
            "gap_sections": snapshot.gap_sections,
            "shebang": snapshot.shebang,
            "encoding_declaration": snapshot.encoding_declaration,
            "file_level_comments": snapshot.file_level_comments,
        })

    def get_file_snapshot(self, file_path: str) -> FileSnapshot | None:
        row = self._db.get_file_snapshot(file_path)
        if row is None:
            return None
        return FileSnapshot(
            file_path=row["file_path"],
            file_hash=row["file_hash"],
            file_size=row["file_size"],
            encoding=row.get("encoding", "utf-8"),
            entity_ids=json.loads(row.get("entity_ids_json", "[]")),
            gap_sections=json.loads(row.get("gap_sections_json", "[]")),
            shebang=row.get("shebang"),
            encoding_declaration=row.get("encoding_declaration"),
            file_level_comments=json.loads(row.get("file_level_comments") or "[]"),
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
        )

    def delete_file_snapshot(self, file_path: str) -> None:
        with self._db.connection() as conn:
            conn.execute(
                "DELETE FROM file_snapshots WHERE file_path = ?", (file_path,)
            )
            conn.commit()

    def get_all_file_snapshots(self) -> dict[str, FileSnapshot]:
        raw = self._db.get_all_file_snapshots()
        result: dict[str, FileSnapshot] = {}
        for fp, row in raw.items():
            try:
                result[fp] = FileSnapshot(
                    file_path=row["file_path"],
                    file_hash=row["file_hash"],
                    file_size=row["file_size"],
                    encoding=row.get("encoding", "utf-8"),
                    entity_ids=json.loads(row.get("entity_ids_json", "[]")),
                    gap_sections=json.loads(row.get("gap_sections_json", "[]")),
                    shebang=row.get("shebang"),
                    encoding_declaration=row.get("encoding_declaration"),
                    file_level_comments=json.loads(row.get("file_level_comments") or "[]"),
                    created_at=row.get("created_at"),
                    updated_at=row.get("updated_at"),
                )
            except (json.JSONDecodeError, KeyError, TypeError) as exc:
                logger.warning(
                    "file_snapshot_deserialize_failed",
                    file_path=fp,
                    error=str(exc),
                )
        return result

    # ------------------------------------------------------------------
    # Cache management
    # ------------------------------------------------------------------

    def get_stats(self) -> dict[str, Any]:
        stats = self._db.get_stats()
        return {
            "ast_entry_count": stats.get("ast_cache_count", 0),
            "file_tracking_count": stats.get("file_tracking_count", 0),
            "file_snapshots_count": stats.get("file_snapshots_count", 0),
            "db_path": str(self._db.path),
        }

    def vacuum(self) -> None:
        self._db.vacuum()

    def close(self) -> None:
        self._db.close()
