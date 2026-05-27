"""Unified cache service — pure in-memory implementation (v2.0).

AST caching and file snapshot operations are held in-memory only.
File tracking delegates to BathoDatabase for persistence.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from batho.context.schema import Entity, FileSnapshot, Relationship
from batho.storage.engine import get_database
from batho.utils.logging import get_logger

logger = get_logger(__name__, component="cache")


class BathoCache:
    """In-memory cache for AST results and file snapshots.

    File tracking (hashes, mtimes) delegates to BathoDatabase for
    cross-process persistence. AST and snapshot data is session-local.
    """

    def __init__(self, cache_path: str | None = None) -> None:
        self._db = None
        if cache_path:
            path = Path(cache_path).resolve()
            if path.suffix == ".batho":
                repo_root = path.parent
                db_path: Path | None = path
            elif path.is_file():
                repo_root = path.parent
                db_path = path
            else:
                repo_root = path
                db_path = None
            self._db = get_database(repo_root, db_path=db_path)
        self.logger = logger

        # In-memory stores (session-local, not persisted)
        self._ast: dict[str, tuple[list[Entity], list[Relationship]]] = {}
        self._snapshots: dict[str, FileSnapshot] = {}

    # ------------------------------------------------------------------
    # AST cache methods (in-memory)
    # ------------------------------------------------------------------

    def get_ast(self, file_hash: str) -> tuple[list[Entity], list[Relationship]] | None:
        return self._ast.get(file_hash)

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
        self._ast[file_hash] = (entities, relationships)

    def delete_ast(self, file_hash: str) -> None:
        self._ast.pop(file_hash, None)

    def delete_ast_by_path(self, file_path: str) -> int:
        """Delete AST entries by file path (exact match).
        
        In v2.0, AST cache is keyed by content hash. This method looks up
        the file's content hash from the database, then deletes the AST
        entry by that hash.
        
        Returns:
            1 if an entry was deleted, 0 otherwise.
        """
        # Look up content hash for the file path
        content_hash = self.get_file_hash(file_path)
        if content_hash:
            self.delete_ast(content_hash)
            return 1
        return 0

    def clear_ast_cache(self, older_than_days: int | None = None) -> int:
        count = len(self._ast)
        self._ast.clear()
        return count

    def invalidate_cache(self, pattern: str | None = None) -> None:
        self._ast.clear()
        self.logger.info("cache_invalidated", pattern=pattern or "*", deleted_count=0)

    # ------------------------------------------------------------------
    # File tracking methods (delegates to BathoDatabase)
    # ------------------------------------------------------------------

    def get_file_hash(self, file_path: str) -> str | None:
        if self._db is None:
            return None
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
        if self._db is None:
            return
        self._db.upsert_file_tracking([{
            "file_path": file_path,
            "content_hash": content_hash,
            "mtime": mtime,
            "size": size,
            "is_indexed": int(is_indexed),
            "last_run_id": None,
        }])

    def delete_file_hash(self, file_path: str) -> None:
        if self._db is None:
            return
        self._db.delete_file_tracking(file_path)

    def get_all_file_hashes(self) -> dict[str, str]:
        if self._db is None:
            return {}
        return self._db.get_all_file_hashes()

    def get_unindexed_files(self) -> dict[str, str]:
        if self._db is None:
            return {}
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
        if records and self._db is not None:
            self._db.upsert_file_tracking(records)

    def load_all(self) -> dict[str, str]:
        return self.get_all_file_hashes()

    # ------------------------------------------------------------------
    # File snapshot methods (in-memory)
    # ------------------------------------------------------------------

    def set_file_snapshot(self, snapshot: FileSnapshot) -> None:
        self._snapshots[snapshot.file_path] = snapshot

    def get_file_snapshot(self, file_path: str) -> FileSnapshot | None:
        return self._snapshots.get(file_path)

    def delete_file_snapshot(self, file_path: str) -> None:
        self._snapshots.pop(file_path, None)

    def get_all_file_snapshots(self) -> dict[str, FileSnapshot]:
        return dict(self._snapshots)

    # ------------------------------------------------------------------
    # Cache management
    # ------------------------------------------------------------------

    def get_stats(self) -> dict[str, Any]:
        db_stats = self._db.get_stats() if self._db is not None else {}
        return {
            "ast_entry_count": len(self._ast),
            "snapshot_count": len(self._snapshots),
            "file_tracking_count": db_stats.get("file_tracking_count", 0),
            "db_path": str(self._db.path) if self._db is not None else "",
        }


    def close(self) -> None:
        self._ast.clear()
        self._snapshots.clear()
