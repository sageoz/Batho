"""Unified cache service — disk-persistent AST cache (v3.0).

AST caching delegates to AstCache (flat-file msgpack on disk).
File tracking delegates to BathoBundle for persistence.
File snapshots remain in-memory (session-local).
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import threading
from pathlib import Path
from typing import Any

from batho.core.schemas import Entity, FileSnapshot, Relationship
from batho.modules.storage.arrow_bundle.bundle import get_bundle
from batho.utils.logging import get_logger

logger = get_logger(__name__, component="cache")


CACHE_SCHEMA_VERSION = "v3"


def build_ast_cache_variant(
    *,
    include_gaps: bool,
    parsing_config: dict[str, Any] | None = None,
) -> str:
    """Return a stable variant key for AST cache entries."""
    payload = {
        "schema_version": CACHE_SCHEMA_VERSION,
        "include_gaps": bool(include_gaps),
        "parsing": parsing_config or {},
    }
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:12]


class BathoCache:
    """Cache service with disk-persistent AST and Arrow Bundle file tracking.

    AST results are stored in AstCache (flat-file msgpack) for cross-session
    persistence and reduced memory usage. File snapshots remain in-memory.
    File tracking (hashes, mtimes) delegates to BathoBundle.
    """

    def __init__(
        self,
        cache_path: str | None = None,
        repo_root: Path | str | None = None,
        ast_cache_dir: Path | str | None = None,
    ) -> None:
        self._db = None
        self._repo_root = Path(repo_root).resolve() if repo_root else None
        if cache_path:
            path = Path(cache_path).resolve()
            # cache_path may be bundle_dir or repo_root; derive repo root
            if path.is_dir():
                bundle_root = path.parent if path.name in ("artifact",) else path
            else:
                bundle_root = path.parent
            self._db = get_bundle(bundle_root)
            if not self._repo_root and self._db is not None:
                self._repo_root = self._db.repo_root
        self.logger = logger

        # Disk-persistent AST cache
        self._ast_cache = None
        if ast_cache_dir is not None:
            from batho.modules.extraction.ast_cache import AstCache
            self._ast_cache = AstCache(Path(ast_cache_dir))

        # In-memory file snapshots (session-local)
        self._lock = threading.Lock()
        self._snapshots: dict[str, FileSnapshot] = {}

    # ------------------------------------------------------------------
    # AST cache methods (delegates to AstCache)
    # ------------------------------------------------------------------

    def get_ast(
        self, file_path: str, file_hash: str, variant: str | None = None
    ) -> tuple[list[Entity], list[Relationship]] | None:
        if self._ast_cache is None:
            return None
        return self._ast_cache.get_ast(file_path, file_hash, variant)

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
        if self._ast_cache is None:
            return
        self._ast_cache.set_ast(
            file_path, file_hash, variant, entities, relationships, mtime, size, ttl_days
        )

    def delete_ast(
        self, file_path: str, file_hash: str, variant: str | None = None
    ) -> None:
        if self._ast_cache is None:
            return
        self._ast_cache.delete_ast(file_path)

    def delete_ast_by_path(self, file_path: str) -> int:
        """Delete AST entries for a file path across all cache variants."""
        if self._ast_cache is None:
            return 0
        return self._ast_cache.delete_ast(file_path)

    def clear_ast_cache(self, older_than_days: int | None = None) -> int:
        if self._ast_cache is None:
            return 0
        return self._ast_cache.clear(older_than_days)

    def invalidate_cache(self, pattern: str | None = None) -> None:
        if self._ast_cache is None:
            return
        if pattern is None or pattern in ("*", "**", ""):
            self._ast_cache.clear()
            self.logger.info("cache_invalidated", pattern="*", deleted_count=-1)
            return
        # Prefix glob: e.g. "src/" or "src/**"
        prefix = pattern.rstrip("*").rstrip("/")
        if "*" not in pattern and "?" not in pattern:
            # Exact file path — delete single entry
            deleted = self._ast_cache.delete_ast(pattern)
        elif pattern.endswith(("/**", "/*")) or pattern == prefix + "/":
            # Directory prefix pattern
            deleted = self._ast_cache.delete_by_path_prefix(prefix + "/")
        else:
            # Generic fnmatch pattern — scan manifest and delete matching entries.
            # The entire read+delete sequence is kept inside _lock_manifest to prevent
            # a TOCTOU race where a freshly written entry could be deleted after the
            # manifest snapshot but before the per-file delete acquires the lock.
            deleted = 0
            with self._ast_cache._lock_manifest():
                manifest = self._ast_cache._load_manifest_for_gc()
                matching = [k for k in list(manifest) if fnmatch.fnmatch(k, pattern)]
                for file_path in matching:
                    cache_hashes = manifest.pop(file_path, [])
                    for cache_hash in cache_hashes:
                        cache_file = self._ast_cache.ast_dir / f"{cache_hash}.msgpack"
                        try:
                            if cache_file.exists():
                                cache_file.unlink()
                                deleted += 1
                        except OSError:
                            pass
                if matching:
                    self._ast_cache._save_manifest_for_gc()
        self.logger.info("cache_invalidated", pattern=pattern, deleted_count=deleted)

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
        rows = self._db.get_unindexed_files_with_details()
        return {r["file_path"]: r["content_hash"] for r in rows}

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
        with self._lock:
            self._snapshots.pop(snapshot.file_path, None)
            self._snapshots[snapshot.file_path] = snapshot
            if len(self._snapshots) > 1000:
                first_key = next(iter(self._snapshots))
                self._snapshots.pop(first_key, None)

    def get_file_snapshot(self, file_path: str) -> FileSnapshot | None:
        with self._lock:
            snapshot = self._snapshots.get(file_path)
            if snapshot is not None:
                self._snapshots.pop(file_path)
                self._snapshots[file_path] = snapshot
            return snapshot

    def delete_file_snapshot(self, file_path: str) -> None:
        with self._lock:
            self._snapshots.pop(file_path, None)

    def get_all_file_snapshots(self) -> dict[str, FileSnapshot]:
        with self._lock:
            return dict(self._snapshots)

    # ------------------------------------------------------------------
    # Cache management
    # ------------------------------------------------------------------

    def get_stats(self) -> dict[str, Any]:
        db_stats = self._db.get_stats() if self._db is not None else {}
        tables = db_stats.get("tables", {})
        tracking_rows = tables.get("file_tracking", {}).get("rows", 0)
        with self._lock:
            snapshot_count = len(self._snapshots)
        return {
            "ast_cache_enabled": self._ast_cache is not None,
            "snapshot_count": snapshot_count,
            "file_tracking_count": tracking_rows,
            "bundle_dir": str(self._db.artifact_dir) if self._db is not None else "",
        }


    def __enter__(self) -> "BathoCache":
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit - ensures database is closed."""
        self.close()
        return False

    def close(self) -> None:
        with self._lock:
            self._snapshots.clear()
            if self._ast_cache is not None:
                self._ast_cache._manifest_index = None
                self._ast_cache = None
        # Note: Do NOT close self._db here - it's shared via _DB_CACHE in engine.py
        # and may be used by other components (e.g., patch operations after build)
