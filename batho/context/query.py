"""Query service backed by the unified .batho SQLite database.

All queries hit the graph_entities and graph_relationships tables directly.
No JSON file loading, no mmap, no in-memory fallback.
"""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from typing import Any

from batho.config import get_config_cached
from batho.context.storage import get_artifact_registry, query_entities, query_relationships
from batho.utils.logging import get_logger

LOGGER = get_logger(__name__, component="query_service")


class QueryService:
    """SQLite-backed query interface for graph data."""

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
        self._db = get_artifact_registry(self.ctn_dir)

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
        """Resolve the current run_id to query against."""
        if self.index_id:
            return self.index_id
        # Use the latest completed run
        return self._db.get_latest_run_id()

    def rebuild_indexes(self) -> dict[str, int]:
        """No-op: indexes are maintained automatically by the DB engine."""
        return {"entities_indexed": 0, "relationships_indexed": 0}

    def entities_by_type(
        self,
        entity_type: str,
        *,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        index_id = self._resolve_index_id()
        if not index_id:
            return []

        normalized = entity_type.strip().upper()
        capped_limit = max(1, int(limit))
        cache_key = ("entities_by_type", index_id, normalized, capped_limit)
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        rows = query_entities(
            self.ctn_dir,
            index_id=index_id,
            entity_type=normalized,
            limit=capped_limit,
        )
        self._cache_set(cache_key, rows)
        return rows

    def entities_by_file(
        self,
        file_path: str,
        *,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        index_id = self._resolve_index_id()
        if not index_id:
            return []

        normalized_path = file_path.strip()
        capped_limit = max(1, int(limit))
        cache_key = ("entities_by_file", index_id, normalized_path, capped_limit)
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        rows = query_entities(
            self.ctn_dir,
            index_id=index_id,
            file_path=normalized_path,
            limit=capped_limit,
        )
        self._cache_set(cache_key, rows)
        return rows

    def relationships_by_type(
        self,
        relationship_type: str,
        *,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        index_id = self._resolve_index_id()
        if not index_id:
            return []

        normalized = relationship_type.strip().upper()
        capped_limit = max(1, int(limit))
        cache_key = ("relationships_by_type", index_id, normalized, capped_limit)
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        rows = query_relationships(
            self.ctn_dir,
            index_id=index_id,
            relationship_type=normalized,
            limit=capped_limit,
        )
        self._cache_set(cache_key, rows)
        return rows
