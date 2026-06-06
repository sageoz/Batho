from __future__ import annotations
import hashlib
import logging
import msgpack
import os
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

class ResolutionCache:
    """
    Flat-file msgpack cache for indexed dependency symbols.
    Keyed by (package_name, version, manager) hash.
    Stored in the project's unified cache directory.
    
    Thread-safe with file locking support.
    """

    def __init__(self, cache_dir: Path):
        self.cache_dir = Path(cache_dir)
        self.dep_dir = self.cache_dir / "dep"
        self.index_file = self.cache_dir / "dep_manifests.idx"
        self._manifest_index: Dict[str, Any] = {}
        self._lock = threading.RLock()
        self._metadata_cache: Dict[str, Any] = {}
        self._metadata_loaded = False
        self._ensure_dirs()
        self._load_index()

    def _ensure_dirs(self):
        self.dep_dir.mkdir(parents=True, exist_ok=True)

    def _load_index(self):
        if self.index_file.exists():
            try:
                with open(self.index_file, "rb") as f:
                    self._manifest_index = msgpack.unpackb(f.read()) or {}
            except Exception as e:
                logger.debug(f"Failed to load manifest index: {e}")
                self._manifest_index = {}

    def _save_index(self):
        try:
            with open(self.index_file, "wb") as f:
                f.write(msgpack.packb(self._manifest_index))
        except Exception as e:
            logger.debug(f"Failed to save manifest index: {e}")

    def get_symbols(self, pkg: str, version: str, manager: str) -> Dict[str, List[str]] | None:
        """Retrieve cached symbols for a package."""
        pkg_hash = self._compute_pkg_hash(pkg, version, manager)
        cache_file = self.dep_dir / f"{pkg_hash}.msgpack"

        if cache_file.exists():
            try:
                with open(cache_file, "rb") as f:
                    return msgpack.unpackb(f.read())
            except Exception as e:
                logger.debug(f"Failed to read cache for {pkg}: {e}")
        return None

    def put_symbols(self, pkg: str, version: str, manager: str, symbols: Dict[str, List[str]]) -> None:
        """Store symbols for a package in the cache (thread-safe)."""
        with self._lock:
            pkg_hash = self._compute_pkg_hash(pkg, version, manager)
            cache_file = self.dep_dir / f"{pkg_hash}.msgpack"

            try:
                with open(cache_file, "wb") as f:
                    f.write(msgpack.packb(symbols))
            except Exception as e:
                logger.debug(f"Failed to write cache for {pkg}: {e}")

    def is_manifest_stale(self, file_path: str, current_hash: str) -> bool:
        """Check if a manifest file has changed since it was last indexed."""
        with self._lock:
            entry = self._manifest_index.get(file_path)
            if not entry:
                return True
            return entry.get("hash") != current_hash

    def mark_manifest_indexed(self, file_path: str, file_hash: str) -> None:
        """Record that a manifest has been indexed with its current hash."""
        with self._lock:
            self._manifest_index[file_path] = {
                "hash": file_hash,
                "indexed_at": os.times().elapsed if hasattr(os, "times") else 0.0
            }
            self._save_index()

    def _load_metadata_cache(self) -> Dict[str, Any]:
        """Lazy-load metadata cache into memory."""
        if self._metadata_loaded:
            return self._metadata_cache

        cache_file = self.cache_dir / "project_metadata.msgpack"
        if cache_file.exists():
            try:
                with open(cache_file, "rb") as f:
                    self._metadata_cache = msgpack.unpackb(f.read()) or {}
            except Exception as e:
                logger.debug(f"Failed to load metadata cache: {e}")
                self._metadata_cache = {}
        self._metadata_loaded = True
        return self._metadata_cache

    def get_project_metadata(self, manifest_path: str, manifest_hash: str) -> Dict[str, str] | None:
        """Retrieve cached project metadata if manifest hasn't changed."""
        with self._lock:
            data = self._load_metadata_cache()
            entry = data.get(manifest_path)
            if entry and entry.get("hash") == manifest_hash:
                return entry.get("metadata")
            return None

    def put_project_metadata(self, manifest_path: str, manifest_hash: str, metadata: Dict[str, str]) -> None:
        """Store project metadata keyed by manifest path and hash."""
        with self._lock:
            cache_file = self.cache_dir / "project_metadata.msgpack"
            data = self._load_metadata_cache()
            data[manifest_path] = {"hash": manifest_hash, "metadata": metadata}
            self._metadata_cache = data

            try:
                with open(cache_file, "wb") as f:
                    f.write(msgpack.packb(data))
            except Exception as e:
                logger.debug(f"Failed to write metadata cache: {e}")

    def _compute_pkg_hash(self, pkg: str, version: str, manager: str) -> str:
        """Deterministic hash for a package identity."""
        key = f"{pkg}:{version}:{manager}"
        return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
