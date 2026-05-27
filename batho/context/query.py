"""Query service backed by the unified .batho SQLite database (v2.0).

Loads compressed blobs from file_artifacts, decompresses them, and
filters in-memory. No legacy graph_entities/graph_relationships tables.
"""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from typing import Any

from batho.config import get_config_cached
from batho.storage.engine import get_database
from batho.context.bsg_map.relativizer import PathRelativizer
from batho.utils.logging import get_logger

LOGGER = get_logger(__name__, component="query_service")


class QueryService:
    """In-memory query interface over decompressed file artifact blobs."""

    def __init__(
        self,
        ctn_dir: Path,
        index_id: str | None = None,
        *,
        cache_enabled: bool | None = None,
        cache_size: int | None = None,
    ):
        cfg = get_config_cached()
        bsg_cfg = cfg.get("bsg", {}) if isinstance(cfg, dict) else {}
        query_cfg = bsg_cfg.get("query", {}) if isinstance(bsg_cfg, dict) else {}

        self.ctn_dir = ctn_dir.resolve()
        self.index_id = (index_id or "").strip() or None

        self.cache_enabled = (
            bool(query_cfg.get("cache_enabled", True))
            if cache_enabled is None
            else bool(cache_enabled)
        )
        self.cache_size = (
            int(query_cfg.get("cache_size", 256))
            if cache_size is None
            else max(1, int(cache_size))
        )

        self._cache: OrderedDict[tuple[Any, ...], list[dict[str, Any]]] = OrderedDict()
        self._db = get_database(self.ctn_dir)
        self._loaded_run_id: str | None = None
        self._entities: list[dict[str, Any]] = []
        self._relationships: list[dict[str, Any]] = []
        self._relativizer = PathRelativizer(str(self.ctn_dir))

    def _cache_get(self, key: tuple[Any, ...]) -> list[dict[str, Any]] | None:
        if not self.cache_enabled:
            return None
        value = self._cache.get(key)
        if value is None:
            return None
        self._cache.move_to_end(key)
        return value

    def _cache_set(self, key: tuple[Any, ...], value: list[dict[str, Any]]) -> None:
        if not self.cache_enabled:
            return
        self._cache[key] = value
        self._cache.move_to_end(key)
        while len(self._cache) > self.cache_size:
            self._cache.popitem(last=False)

    def _resolve_index_id(self) -> str | None:
        if self.index_id:
            return self.index_id
        return self._db.get_latest_run_id()

    def _ensure_loaded(self, run_uuid: str) -> None:
        """Load all file blobs for the run into memory if not already loaded.

        If run_uuid differs from the previously loaded run (e.g., a new patch
        completed), the in-memory data AND the query cache are both replaced so
        callers never see stale results from the previous run.
        """
        if self._loaded_run_id == run_uuid:
            return

        # A different run is now active — discard cached query results that were
        # keyed against the old run_uuid to prevent stale data from persisting.
        self._cache.clear()

        run_internal_id = self._db.get_run_internal_id(run_uuid)
        if run_internal_id is None:
            self._entities = []
            self._relationships = []
            self._loaded_run_id = run_uuid
            return

        artifacts = self._db.get_file_artifacts(run_internal_id)
        entities: list[dict[str, Any]] = []
        relationships: list[dict[str, Any]] = []
        for artifact in artifacts:
            graph = artifact.get("graph", {})
            file_path = artifact.get("file_path", "")
            for e in graph.get("entities", []):
                e_copy = dict(e)
                if "file" not in e_copy:
                    e_copy["file"] = file_path
                entities.append(e_copy)
            for r in graph.get("relationships", []):
                relationships.append(dict(r))

        self._entities = entities
        self._relationships = relationships
        self._loaded_run_id = run_uuid

    def entities_by_type(
        self,
        entity_type: str,
        *,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        run_uuid = self._resolve_index_id()
        if not run_uuid:
            return []

        normalized = entity_type.strip().upper()
        capped_limit = max(1, int(limit))
        cache_key = ("entities_by_type", run_uuid, normalized, capped_limit)
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        # NOTE: This loads ALL entities into memory before applying the limit.
        # For large repositories, this causes memory bloat. The cache key
        # includes the limit, causing different cache entries for different limits.
        # Consider: (1) true pagination in _ensure_loaded, or (2) streaming filters.
        self._ensure_loaded(run_uuid)
        results = [
            e for e in self._entities
            if str(e.get("entity_type", e.get("type", ""))).upper() == normalized
        ][:capped_limit]
        self._cache_set(cache_key, results)
        return results

    def entities_by_file(
        self,
        file_path: str,
        *,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        run_uuid = self._resolve_index_id()
        if not run_uuid:
            return []

        capped_limit = max(1, int(limit))
        # Relativize the input path before building the cache key so that
        # callers using absolute or relative forms of the same file share a
        # single cache entry instead of redundant per-form entries.
        normalized_query_path = self._relativizer(file_path.strip())
        cache_key = ("entities_by_file", run_uuid, normalized_query_path, capped_limit)
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        self._ensure_loaded(run_uuid)
        results = [
            e for e in self._entities
            if self._relativizer(e.get("file", e.get("file_path", ""))) == normalized_query_path
        ][:capped_limit]
        self._cache_set(cache_key, results)
        return results

    def relationships_by_type(
        self,
        relationship_type: str,
        *,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        run_uuid = self._resolve_index_id()
        if not run_uuid:
            return []

        normalized = relationship_type.strip().upper()
        capped_limit = max(1, int(limit))
        cache_key = ("relationships_by_type", run_uuid, normalized, capped_limit)
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        self._ensure_loaded(run_uuid)
        results = [
            r for r in self._relationships
            if str(r.get("type", r.get("relationship_type", ""))).upper() == normalized
        ][:capped_limit]
        self._cache_set(cache_key, results)
        return results
