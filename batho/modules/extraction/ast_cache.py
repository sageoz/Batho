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
import logging
import os
import time
from pathlib import Path
from typing import Any

import msgpack

from batho.core.schemas import Entity, Relationship

logger = logging.getLogger(__name__)


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
        self._ensure_dirs()

    def _ensure_dirs(self) -> None:
        self.ast_dir.mkdir(parents=True, exist_ok=True)

    def _load_manifest_for_gc(self) -> dict[str, Any]:
        """Load manifest only when needed for GC operations."""
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
        """Save manifest for GC operations. Called infrequently."""
        if self._manifest_index is None:
            return
        index_file = self.cache_dir / "ast_manifests.idx"
        try:
            with open(index_file, "wb") as f:
                f.write(msgpack.packb(self._manifest_index))
        except Exception as e:
            logger.debug("ast_cache_manifest_save_failed", error=str(e))

    def _compute_key(self, file_path: str, content_hash: str, variant: str) -> str:
        key = f"{file_path}:{content_hash}:{variant}"
        return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]

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
            logger.debug("ast_cache_read_failed", file=file_path, error=str(e))
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

        logger.debug("ast_cache_hit", file=file_path, variant=variant or "")
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
        # Unique temp file per process to avoid collisions in multiprocessing
        tmp_file = self.ast_dir / f"{cache_hash}.tmp.{os.getpid()}"

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

        try:
            # Atomic write: write to temp file, then replace
            with open(tmp_file, "wb") as f:
                f.write(msgpack.packb(payload))
            os.replace(tmp_file, cache_file)  # Atomic operation
            logger.debug("ast_cache_write", file=file_path, variant=variant or "")
        except Exception as e:
            logger.debug("ast_cache_write_failed", file=file_path, error=str(e))
            # Clean up temp file if it exists
            try:
                if tmp_file.exists():
                    tmp_file.unlink()
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

        Iterates through all cache files, reads their embedded metadata,
        and deletes files matching the given file_path.

        Returns:
            Number of cache files deleted.
        """
        deleted_count = 0

        # Iterate through all cache files and delete matching ones
        for cache_file in self.ast_dir.glob("*.msgpack"):
            try:
                with open(cache_file, "rb") as f:
                    data = msgpack.unpackb(f.read())

                if data.get("file_path") == file_path:
                    try:
                        cache_file.unlink()
                        deleted_count += 1
                        logger.debug("ast_cache_deleted", file=file_path, cache_file=str(cache_file))
                    except OSError as e:
                        logger.debug("ast_cache_delete_failed", file=file_path, cache_file=str(cache_file), error=str(e))
            except Exception as e:
                # Skip files that can't be read (corrupted, etc.)
                logger.debug("ast_cache_read_failed_during_delete", cache_file=str(cache_file), error=str(e))
                continue

        # Also update manifest if loaded
        if self._manifest_index is not None:
            self._manifest_index.pop(file_path, None)
            self._save_manifest_for_gc()

        return deleted_count

    def delete_by_path_prefix(self, path_prefix: str) -> int:
        """Delete all AST entries whose file path starts with the given prefix.

        Returns the number of entries deleted from the manifest.
        Actual cache files are cleaned up lazily by GC.
        """
        manifest = self._load_manifest_for_gc()
        keys_to_delete = [
            k for k in manifest if k.startswith(path_prefix)
        ]
        for key in keys_to_delete:
            manifest.pop(key, None)
        if keys_to_delete:
            self._save_manifest_for_gc()
        return len(keys_to_delete)

    def clear(self) -> None:
        """Clear all cached AST entries."""
        for f in self.ast_dir.glob("*.msgpack"):
            try:
                f.unlink()
            except OSError:
                pass
        # Also clear manifest if loaded
        if self._manifest_index is not None:
            self._manifest_index.clear()
            self._save_manifest_for_gc()
