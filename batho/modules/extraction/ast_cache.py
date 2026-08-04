"""Disk-persistent AST cache for extracted entities and relationships.

Flat-file msgpack cache with atomic writes and self-describing entries.
Keyed by (filepath, content_hash, cache_variant). Stored in .batho/cache/ast/.

Thread-safe within a process, but designed for multiprocessing safety through:
- Atomic file writes (write to temp, then os.replace)
- Self-describing cache files (no central manifest needed for staleness checks)
- Each cache file contains its own metadata (file_path, content_hash, etc.)
"""

from __future__ import annotations

import hashlib
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

import msgpack

try:
    import fcntl
except ImportError:
    fcntl = None

try:
    import msvcrt
except ImportError:
    msvcrt = None

import contextlib

import structlog

from batho.core.schemas import Entity, Relationship

logger = structlog.get_logger(__name__)


class AstCache:
    """Disk-persistent msgpack cache for AST extraction results.

    Features:
    - Atomic file writes to prevent corruption on crash/termination
    - Self-describing cache files (metadata embedded in each file)
    - No central manifest for staleness checks (eliminates write contention)
    - Manifest only used for optional lazy garbage collection

    Design: Each cache file is independent and contains all metadata needed
    to verify its validity, eliminating the need for a shared manifest that
    would cause race conditions in multiprocessing environments.
    """

    def __init__(self, cache_dir: Path) -> None:
        self.cache_dir = Path(cache_dir)
        self.ast_dir = self.cache_dir / "ast"
        # Manifest is now only for lazy GC, not for hot-path staleness checks
        self._manifest_index: dict[str, Any] | None = None
        self._lock = threading.RLock()
        self._lock_file_path = self.cache_dir / "ast_manifests.lock"
        self._ensure_dirs()

    @contextlib.contextmanager
    def _lock_manifest(self):
        """Acquire both process-level file lock and thread lock.

        Order: file lock first (blocking I/O outside RLock), then RLock.
        This prevents holding the in-process RLock while blocked waiting
        for a cross-process flock, which would deadlock other threads.
        """
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        lock_file = None
        try:
            lock_file = open(self._lock_file_path, "w")
            try:
                if fcntl:
                    fcntl.flock(lock_file, fcntl.LOCK_EX)
                elif msvcrt:
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
            except Exception:
                lock_file.close()
                raise

            with self._lock:
                # Force reload of the manifest from disk
                self._manifest_index = None
                try:
                    yield
                finally:
                    pass
        finally:
            if lock_file is not None:
                try:
                    if fcntl:
                        fcntl.flock(lock_file, fcntl.LOCK_UN)
                    elif msvcrt:
                        lock_file.seek(0)
                        msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
                except Exception:
                    pass
                lock_file.close()

    def _ensure_dirs(self) -> None:
        self.ast_dir.mkdir(parents=True, exist_ok=True)

    def _load_manifest_for_gc(self) -> dict[str, Any]:
        """Load manifest only when needed for GC operations."""
        with self._lock:
            if self._manifest_index is not None:
                return self._manifest_index
            index_file = self.cache_dir / "ast_manifests.idx"
            if index_file.exists():
                try:
                    with open(index_file, "rb") as f:
                        self._manifest_index = msgpack.unpackb(f.read()) or {}
                except Exception as e:
                    logger.debug("ast_cache_manifest_load_failed", error=str(e))
                    self._manifest_index = {}
            else:
                self._manifest_index = {}
            return self._manifest_index

    def _save_manifest_for_gc(self) -> None:
        """Save manifest for GC operations atomically via temp file + replace."""
        with self._lock:
            if self._manifest_index is None:
                return
            index_file = self.cache_dir / "ast_manifests.idx"
            try:
                fd, tmp_path = tempfile.mkstemp(dir=self.cache_dir, prefix="ast_manifests.", suffix=".tmp")
                try:
                    with os.fdopen(fd, "wb") as f:
                        f.write(msgpack.packb(self._manifest_index))
                    os.replace(tmp_path, index_file)
                except Exception:
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass
                    raise
            except Exception as e:
                logger.debug("ast_cache_manifest_save_failed", error=str(e))

    def _compute_key(self, file_path: str, content_hash: str, variant: str) -> str:
        key = f"{file_path}:{content_hash}:{variant}"
        return hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]

    def _add_to_manifest(self, file_path: str, cache_hash: str, content_hash: str) -> None:
        with self._lock_manifest():
            try:
                manifest = self._load_manifest_for_gc()
                if file_path not in manifest:
                    manifest[file_path] = []
                
                # Identify and clean up stale cache files (different content_hash)
                updated_hashes = []
                for existing_hash in manifest[file_path]:
                    if existing_hash == cache_hash:
                        updated_hashes.append(existing_hash)
                        continue
                    
                    cache_file = self.ast_dir / f"{existing_hash}.msgpack"
                    if cache_file.exists():
                        try:
                            with open(cache_file, "rb") as f:
                                data = msgpack.unpackb(f.read())
                            if data.get("content_hash") != content_hash:
                                cache_file.unlink()
                                logger.debug("ast_cache_cleanup_stale", file_path=file_path, cache_file=str(cache_file))
                            else:
                                updated_hashes.append(existing_hash)
                        except Exception:
                            # Only delete if this is a stale/corrupt entry, never the
                            # freshly written cache_hash entry (already skipped above).
                            if existing_hash != cache_hash:
                                try:
                                    cache_file.unlink()
                                except OSError:
                                    pass
                
                if cache_hash not in updated_hashes:
                    updated_hashes.append(cache_hash)
                    
                manifest[file_path] = updated_hashes
                self._save_manifest_for_gc()
            except Exception as e:
                logger.debug("ast_cache_manifest_add_failed", file_path=file_path, error=str(e))

    def get_ast(
        self,
        file_path: str,
        content_hash: str,
        variant: str | None = None,
    ) -> tuple[list[Entity], list[Relationship]] | None:
        """Retrieve cached AST results for a file.

        Returns None if not cached, stale, or expired.
        Staleness is determined by reading metadata directly from the cache file,
        eliminating the need for a shared manifest that would cause race conditions.
        """
        cache_hash = self._compute_key(file_path, content_hash, variant or "")
        cache_file = self.ast_dir / f"{cache_hash}.msgpack"

        if not cache_file.exists():
            return None

        try:
            with open(cache_file, "rb") as f:
                data = msgpack.unpackb(f.read())
        except Exception as e:
            logger.debug("ast_cache_read_failed", file_path=file_path, error=str(e))
            return None

        # Check staleness directly from embedded metadata (no manifest needed)
        cached_file_path = data.get("file_path")
        cached_content_hash = data.get("content_hash")
        if cached_file_path != file_path or cached_content_hash != content_hash:
            # Hash collision or file rename - treat as stale
            return None

        # Check TTL
        expires_at = data.get("expires_at")
        if expires_at is not None and expires_at <= time.time():
            return None

        # Deserialize entities and relationships
        entities = [
            Entity.from_dict(e) for e in data.get("entities", [])
        ]
        rels_raw = data.get("relationships", [])
        relationships = []
        for r in rels_raw:
            if "type" in r and isinstance(r["type"], str):
                from batho.core.schemas import RelationshipType
                try:
                    r = dict(r)
                    r["type"] = RelationshipType[r["type"]]
                except KeyError:
                    continue
            relationships.append(Relationship(**r))

        logger.debug("ast_cache_hit", file_path=file_path, variant=variant or "")
        return entities, relationships

    def set_ast(
        self,
        file_path: str,
        content_hash: str,
        variant: str | None,
        entities: list[Entity],
        relationships: list[Relationship],
        mtime: float,
        size: int,
        ttl_days: int = 30,
    ) -> None:
        """Store AST results on disk using atomic write.

        Writes to a temporary file with a unique per-process name, then uses
        os.replace() for atomic renaming. This prevents corrupted cache files
        when workers crash or are terminated mid-write.
        """
        cache_hash = self._compute_key(file_path, content_hash, variant or "")
        cache_file = self.ast_dir / f"{cache_hash}.msgpack"

        expires_at = None
        if ttl_days > 0:
            expires_at = time.time() + (ttl_days * 86400)

        # Self-describing payload with all metadata needed for validation
        payload = {
            "file_path": file_path,  # Embedded for staleness detection
            "content_hash": content_hash,  # Embedded for staleness detection
            "entities": [e.to_dict(view="agent") for e in entities],
            "relationships": [r.to_dict() for r in relationships],
            "mtime": mtime,
            "size": size,
            "expires_at": expires_at,
        }

        # Atomic write: write to temp file, then replace
        import tempfile
        tmp_path = None
        try:
            fd, tmp_path_str = tempfile.mkstemp(dir=self.ast_dir, prefix=f"{cache_hash}.tmp.", suffix=".tmp")
            tmp_path = Path(tmp_path_str)
            with os.fdopen(fd, "wb") as f:
                f.write(msgpack.packb(payload))
            os.replace(tmp_path, cache_file)  # Atomic operation
            tmp_path = None
            logger.debug("ast_cache_write", file_path=file_path, variant=variant or "")
            self._add_to_manifest(file_path, cache_hash, content_hash)
        except Exception as e:
            logger.debug("ast_cache_write_failed", file_path=file_path, error=str(e))
            # Clean up temp file if it exists
            if tmp_path is not None:
                try:
                    if tmp_path.exists():
                        tmp_path.unlink()
                except OSError:
                    pass

    def is_stale(self, file_path: str, current_hash: str) -> bool:
        """Check if cached AST for a file is stale (content changed).

        Uses the cache file's embedded metadata directly, no manifest needed.
        """
        # Try to find any cache file for this path by checking with empty variant
        cache_hash = self._compute_key(file_path, current_hash, "")
        cache_file = self.ast_dir / f"{cache_hash}.msgpack"

        if not cache_file.exists():
            # No cache for current hash - definitely stale
            return True

        # File exists with matching hash - not stale
        return False

    def delete_ast(self, file_path: str) -> int:
        """Remove cached AST for a file from disk and manifest.

        Checks the manifest first to perform O(1) direct file deletion.
        Falls back to directory scan for legacy/untracked files.

        Returns:
            Number of cache files deleted.
        """
        deleted_count = 0
        with self._lock_manifest():
            manifest = self._load_manifest_for_gc()

            # O(1) deletion using manifest index
            if file_path in manifest:
                cache_hashes = manifest.pop(file_path, [])
                for cache_hash in cache_hashes:
                    cache_file = self.ast_dir / f"{cache_hash}.msgpack"
                    try:
                        if cache_file.exists():
                            cache_file.unlink()
                            deleted_count += 1
                            logger.debug("ast_cache_deleted", file_path=file_path, cache_file=str(cache_file))
                    except OSError as e:
                        logger.debug("ast_cache_delete_failed", file_path=file_path, cache_file=str(cache_file), error=str(e))
                self._save_manifest_for_gc()
                return deleted_count

            # Trust the manifest if the index file exists or manifest has other entries.
            # Bypasses expensive glob scans on non-cached paths.
            index_file = self.cache_dir / "ast_manifests.idx"
            if index_file.exists() or len(manifest) > 0:
                return 0

            # Fallback to directory scan
            for cache_file in self.ast_dir.glob("*.msgpack"):
                try:
                    with open(cache_file, "rb") as f:
                        data = msgpack.unpackb(f.read())

                    if data.get("file_path") == file_path:
                        try:
                            cache_file.unlink()
                            deleted_count += 1
                            logger.debug("ast_cache_deleted", file_path=file_path, cache_file=str(cache_file))
                        except OSError as e:
                            logger.debug("ast_cache_delete_failed", file_path=file_path, cache_file=str(cache_file), error=str(e))
                except Exception as e:
                    logger.debug("ast_cache_read_failed_during_delete", cache_file=str(cache_file), error=str(e))
                    continue

            return deleted_count

    def delete_by_path_prefix(self, path_prefix: str) -> int:
        """Delete all AST entries whose file path starts with the given prefix.

        Returns the number of entries deleted from the manifest and disk.
        """
        # Guard against empty, root, or path traversal prefix to prevent unintended bulk deletion
        if not path_prefix or path_prefix.strip() in ("", "/"):
            return 0

        deleted_count = 0
        with self._lock_manifest():
            manifest = self._load_manifest_for_gc()
            keys_to_delete = [
                k for k in manifest if k.startswith(path_prefix)
            ]
            
            for key in keys_to_delete:
                cache_hashes = manifest.pop(key, [])
                for cache_hash in cache_hashes:
                    cache_file = self.ast_dir / f"{cache_hash}.msgpack"
                    try:
                        if cache_file.exists():
                            cache_file.unlink()
                            deleted_count += 1
                    except OSError:
                        pass
            if keys_to_delete:
                self._save_manifest_for_gc()
            return deleted_count

    def clear(self, older_than_days: int | None = None) -> int:
        """Clear cached AST entries.

        If older_than_days is provided, only entries older than that (based on cache file mtime)
        are cleared. Otherwise, all entries are cleared.
        Returns the number of files deleted.
        """
        deleted_count = 0
        cutoff = None
        if older_than_days is not None:
            cutoff = time.time() - (older_than_days * 86400)

        with self._lock_manifest():
            manifest = self._load_manifest_for_gc()
            for f in self.ast_dir.glob("*.msgpack"):
                try:
                    stat = f.stat()
                    if cutoff is None or stat.st_mtime < cutoff:
                        f.unlink()
                        deleted_count += 1
                except OSError:
                    pass

            if cutoff is None:
                manifest.clear()
            else:
                for file_path in list(manifest.keys()):
                    updated_hashes = []
                    for cache_hash in manifest[file_path]:
                        cache_file = self.ast_dir / f"{cache_hash}.msgpack"
                        if cache_file.exists():
                            updated_hashes.append(cache_hash)
                    if updated_hashes:
                        manifest[file_path] = updated_hashes
                    else:
                        manifest.pop(file_path, None)

            self._save_manifest_for_gc()
        return deleted_count
