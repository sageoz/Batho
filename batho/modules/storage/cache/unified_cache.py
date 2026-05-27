"""Unified cache service — pure in-memory implementation (v2.0).

AST caching and file snapshot operations are held in-memory only.
File tracking delegates to BathoDatabase for persistence.
"""

from __future__ import annotations

from pathlib import Path
import hashlib
import json
import time
from typing import Any

from batho.core.schemas import Entity, FileSnapshot, Relationship
from batho.modules.storage.sqlite_registry.engine import get_database
from batho.utils.logging import get_logger

logger = get_logger(__name__, component="cache")


def build_ast_cache_variant(
    *,
    include_gaps: bool,
    parsing_config: dict[str, Any] | None = None,
) -> str:
    """Return a stable variant key for AST cache entries."""
    payload = {
        "include_gaps": bool(include_gaps),
        "parsing": parsing_config or {},
    }
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:12]


class BathoCache:
    """In-memory cache for AST results and file snapshots.

    File tracking (hashes, mtimes) delegates to BathoDatabase for
    cross-process persistence. AST and snapshot data is session-local.
    """

    def __init__(self, cache_path: str | None = None, repo_root: Path | str | None = None) -> None:
        self._db = None
        self._repo_root = Path(repo_root).resolve() if repo_root else None
        if cache_path:
            path = Path(cache_path).resolve()
            if path.suffix == ".batho":
                db_repo_root = path.parent
                db_path: Path | None = path
            elif path.is_file():
                db_repo_root = path.parent
                db_path = path
            else:
                db_repo_root = path
                db_path = None
            self._db = get_database(db_repo_root, db_path=db_path)
            if not self._repo_root and self._db is not None:
                self._repo_root = self._db.repo_root
        self.logger = logger

        # In-memory stores (session-local, not persisted)
        self._ast: dict[
            tuple[str, str, str],
            tuple[list[Entity], list[Relationship], float | None],
        ] = {}
        self._snapshots: dict[str, FileSnapshot] = {}

    # ------------------------------------------------------------------
    # AST cache methods (in-memory)
    # ------------------------------------------------------------------

    def _purge_expired(self) -> None:
        now = time.time()
        expired = []
        for key, value in self._ast.items():
            if len(value) < 3:
                continue
            if value[2] is not None and value[2] <= now:
                expired.append(key)
        for key in expired:
            self._ast.pop(key, None)

    def _normalize_ast_path(self, file_path: str) -> str:
        path = Path(file_path)
        repo_root = None
        if self._db is not None:
            repo_root = self._db.repo_root
        elif getattr(self, "_repo_root", None) is not None:
            repo_root = self._repo_root

        if not path.is_absolute() and repo_root is not None:
            path = repo_root / path
        try:
            return str(path.resolve())
        except OSError:
            return str(path)

    def _ast_key(
        self, file_path: str, file_hash: str, variant: str | None = None
    ) -> tuple[str, str, str]:
        return (self._normalize_ast_path(file_path), file_hash, variant or "")

    def get_ast(
        self, file_path: str, file_hash: str, variant: str | None = None
    ) -> tuple[list[Entity], list[Relationship]] | None:
        self._purge_expired()
        entry = self._ast.get(self._ast_key(file_path, file_hash, variant))
        if entry is None:
            return None
        if len(entry) >= 2:
            return entry[0], entry[1]
        return None

    def set_ast(
        self,
        file_path: str,
        file_hash: str,
        entities: list[Entity],
        relationships: list[Relationship],
        mtime: float,
        size: int,
        ttl_days: int = 30,
        variant: str | None = None,
    ) -> None:
        expires_at = None
        if ttl_days > 0:
            expires_at = time.time() + (ttl_days * 86400)
        self._ast[self._ast_key(file_path, file_hash, variant)] = (
            entities,
            relationships,
            expires_at,
        )

    def delete_ast(
        self, file_path: str, file_hash: str, variant: str | None = None
    ) -> None:
        self._ast.pop(self._ast_key(file_path, file_hash, variant), None)

    def delete_ast_by_path(self, file_path: str) -> int:
        """Delete AST entries for a file path across all cache variants."""
        normalized_paths = {file_path, self._normalize_ast_path(file_path)}
        if self._db is not None:
            try:
                if not Path(file_path).is_absolute():
                    normalized_paths.add(str((self._db.repo_root / file_path).resolve()))
            except OSError:
                pass

        keys_to_delete = [
            key for key in self._ast.keys() if key[0] in normalized_paths
        ]
        for key in keys_to_delete:
            self._ast.pop(key, None)
        return len(keys_to_delete)

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
            "mtime_ns": int(mtime * 1e9),
            "inode": None,
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
                "mtime_ns": getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1e9)),
                "inode": getattr(stat, "st_ino", None),
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
        self._purge_expired()
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
        # Note: Do NOT close self._db here - it's shared via _DB_CACHE in engine.py
        # and may be used by other components (e.g., patch operations after build)
