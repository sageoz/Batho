from __future__ import annotations
import hashlib
import msgpack
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

class ResolutionCache:
    """
    Flat-file msgpack cache for indexed dependency symbols.
    Keyed by (package_name, version, manager) hash.
    Stored in the project's unified cache directory.
    """
    
    def __init__(self, cache_dir: Path):
        self.cache_dir = cache_dir
        self.dep_dir = cache_dir / "dep"
        self.index_file = cache_dir / "dep_manifests.idx"
        self._manifest_index: Dict[str, Any] = {}
        self._ensure_dirs()
        self._load_index()

    def _ensure_dirs(self):
        self.dep_dir.mkdir(parents=True, exist_ok=True)

    def _load_index(self):
        if self.index_file.exists():
            try:
                with open(self.index_file, "rb") as f:
                    self._manifest_index = msgpack.unpackb(f.read()) or {}
            except Exception:
                self._manifest_index = {}

    def _save_index(self):
        try:
            with open(self.index_file, "wb") as f:
                f.write(msgpack.packb(self._manifest_index))
        except Exception:
            pass

    def get_symbols(self, pkg: str, version: str, manager: str) -> Dict[str, List[str]] | None:
        """Retrieve cached symbols for a package."""
        pkg_hash = self._compute_pkg_hash(pkg, version, manager)
        cache_file = self.dep_dir / f"{pkg_hash}.msgpack"
        
        if cache_file.exists():
            try:
                with open(cache_file, "rb") as f:
                    return msgpack.unpackb(f.read())
            except Exception:
                pass
        return None

    def put_symbols(self, pkg: str, version: str, manager: str, symbols: Dict[str, List[str]]) -> None:
        """Store symbols for a package in the cache."""
        pkg_hash = self._compute_pkg_hash(pkg, version, manager)
        cache_file = self.dep_dir / f"{pkg_hash}.msgpack"
        
        try:
            with open(cache_file, "wb") as f:
                f.write(msgpack.packb(symbols))
        except Exception:
            pass

    def is_manifest_stale(self, file_path: str, current_hash: str) -> bool:
        """Check if a manifest file has changed since it was last indexed."""
        entry = self._manifest_index.get(file_path)
        if not entry:
            return True
        return entry.get("hash") != current_hash

    def mark_manifest_indexed(self, file_path: str, file_hash: str) -> None:
        """Record that a manifest has been indexed with its current hash."""
        self._manifest_index[file_path] = {
            "hash": file_hash,
            "indexed_at": os.times().elapsed if hasattr(os, "times") else 0.0
        }
        self._save_index()

    def get_project_metadata(self, manifest_path: str, manifest_hash: str) -> Dict[str, str] | None:
        """Retrieve cached project metadata if manifest hasn't changed."""
        cache_file = self.cache_dir / "project_metadata.msgpack"
        if not cache_file.exists():
            return None
        try:
            with open(cache_file, "rb") as f:
                data = msgpack.unpackb(f.read())
            entry = data.get(manifest_path)
            if entry and entry.get("hash") == manifest_hash:
                return entry.get("metadata")
        except Exception:
            pass
        return None

    def put_project_metadata(self, manifest_path: str, manifest_hash: str, metadata: Dict[str, str]) -> None:
        """Store project metadata keyed by manifest path and hash."""
        cache_file = self.cache_dir / "project_metadata.msgpack"
        data = {}
        if cache_file.exists():
            try:
                with open(cache_file, "rb") as f:
                    data = msgpack.unpackb(f.read()) or {}
            except Exception:
                pass
        data[manifest_path] = {"hash": manifest_hash, "metadata": metadata}
        try:
            with open(cache_file, "wb") as f:
                f.write(msgpack.packb(data))
        except Exception:
            pass

    def _compute_pkg_hash(self, pkg: str, version: str, manager: str) -> str:
        """Deterministic hash for a package identity."""
        key = f"{pkg}:{version}:{manager}"
        return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
