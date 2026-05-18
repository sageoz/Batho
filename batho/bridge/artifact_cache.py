"""Size-bounded LRU cache for parsed artifact JSON."""

from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

from batho.utils.logging import get_logger

LOGGER = get_logger(__name__, component="bridge.cache")


@dataclass(frozen=True)
class ArtifactCacheKey:
    """Unique key for artifact cache entries."""

    workspace_id: str
    artifact_type: str
    file_path: str
    file_mtime_ns: int
    file_size: int
    checksum: str

    def __hash__(self) -> int:
        return hash((
            self.workspace_id,
            self.artifact_type,
            self.file_path,
            self.file_mtime_ns,
            self.file_size,
            self.checksum,
        ))


@dataclass
class CacheStats:
    """Cache statistics."""

    total_bytes: int = 0
    total_entries: int = 0
    hits: int = 0
    misses: int = 0
    evictions: int = 0
    workspace_bytes: dict[str, int] = field(default_factory=dict)


class ArtifactCache:
    """Size-bounded LRU cache for parsed JSON artifacts."""

    def __init__(
        self,
        max_total_bytes: int,
        max_per_workspace_bytes: int,
    ):
        self._max_total_bytes = max_total_bytes
        self._max_per_workspace_bytes = max_per_workspace_bytes
        self._cache: OrderedDict[ArtifactCacheKey, tuple[dict, int]] = OrderedDict()
        self._lock = threading.RLock()
        self._stats = CacheStats()
        self._workspace_bytes: dict[str, int] = {}
        self._workspace_keys: dict[str, OrderedDict[ArtifactCacheKey, None]] = {}
        self._single_flight: dict[ArtifactCacheKey, threading.Event] = {}

    @property
    def max_total_bytes(self) -> int:
        return self._max_total_bytes

    @property
    def max_per_workspace_bytes(self) -> int:
        return self._max_per_workspace_bytes

    def get(self, key: ArtifactCacheKey) -> dict | None:
        """Get a cached artifact by key."""
        with self._lock:
            if key not in self._cache:
                self._stats.misses += 1
                return None

            self._cache.move_to_end(key)
            if key.workspace_id in self._workspace_keys:
                self._workspace_keys[key.workspace_id].move_to_end(key)

            self._stats.hits += 1
            return self._cache[key][0]

    def put(self, key: ArtifactCacheKey, value: dict, size_bytes: int) -> None:
        """Put an artifact into the cache."""
        with self._lock:
            if key in self._cache:
                old_size = self._cache[key][1]
                self._workspace_bytes[key.workspace_id] = max(0, self._workspace_bytes.get(key.workspace_id, 0) - old_size)
                self._stats.total_bytes = max(0, self._stats.total_bytes - old_size)

            self._cache[key] = (value, size_bytes)
            self._workspace_bytes[key.workspace_id] = self._workspace_bytes.get(key.workspace_id, 0) + size_bytes
            self._stats.total_bytes += size_bytes
            self._cache.move_to_end(key)

            if key.workspace_id not in self._workspace_keys:
                self._workspace_keys[key.workspace_id] = OrderedDict()
            self._workspace_keys[key.workspace_id][key] = None
            self._workspace_keys[key.workspace_id].move_to_end(key)

            self._evict_if_needed()
            self._stats.total_entries = len(self._cache)
            self._stats.workspace_bytes = dict(self._workspace_bytes)

    def _evict_if_needed(self) -> None:
        """Evict entries if cache exceeds size limits."""
        while self._stats.total_bytes > self._max_total_bytes and self._cache:
            self._evict_lru()

        for ws_id in list(self._workspace_bytes.keys()):
            while self._workspace_bytes.get(ws_id, 0) > self._max_per_workspace_bytes:
                ws_keys = self._workspace_keys.get(ws_id)
                if not ws_keys:
                    break
                key, _ = ws_keys.popitem(last=False)
                _, size = self._cache.pop(key)
                self._workspace_bytes[ws_id] -= size
                self._stats.total_bytes -= size
                self._stats.evictions += 1

    def _evict_lru(self) -> None:
        """Evict the least recently used entry."""
        if not self._cache:
            return
        key, (_, size) = self._cache.popitem(last=False)
        if key.workspace_id in self._workspace_keys:
            self._workspace_keys[key.workspace_id].pop(key, None)

        self._workspace_bytes[key.workspace_id] -= size
        self._stats.total_bytes -= size
        self._stats.evictions += 1

    def invalidate_workspace(self, workspace_id: str) -> int:
        """Invalidate all cache entries for a workspace."""
        with self._lock:
            ws_keys = self._workspace_keys.pop(workspace_id, OrderedDict())
            count = 0
            for key in ws_keys:
                if key in self._cache:
                    _, size = self._cache.pop(key)
                    self._workspace_bytes[workspace_id] -= size
                    self._stats.total_bytes -= size
                    count += 1
            self._stats.total_entries = len(self._cache)
            self._stats.workspace_bytes = dict(self._workspace_bytes)
            return count

    def stats(self) -> CacheStats:
        """Get cache statistics."""
        with self._lock:
            return CacheStats(
                total_bytes=self._stats.total_bytes,
                total_entries=self._stats.total_entries,
                hits=self._stats.hits,
                misses=self._stats.misses,
                evictions=self._stats.evictions,
                workspace_bytes=dict(self._workspace_bytes),
            )

    def acquire_single_flight(self, key: ArtifactCacheKey) -> bool:
        """Attempt to acquire single-flight for a key. Returns True if this caller should load."""
        with self._lock:
            if key in self._single_flight:
                return False
            event = threading.Event()
            self._single_flight[key] = event
            return True

    def release_single_flight(self, key: ArtifactCacheKey) -> None:
        """Release single-flight lock for a key."""
        with self._lock:
            event = self._single_flight.pop(key, None)
            if event:
                event.set()

    def wait_for_single_flight(self, key: ArtifactCacheKey) -> None:
        """Wait for another thread to finish loading this key."""
        with self._lock:
            event = self._single_flight.get(key)
        if event:
            event.wait()


__all__ = [
    "ArtifactCache",
    "ArtifactCacheKey",
    "CacheStats",
]
