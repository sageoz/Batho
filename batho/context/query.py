"""Persistent query service for Phase 3 query optimization.

The service prefers SQLite query indexes persisted in the artifact registry and
falls back to in-memory filtering over graph.json when indexes are unavailable.
"""

from __future__ import annotations

import json
from collections import OrderedDict
from pathlib import Path
from typing import Any

from batho.config import get_config_cached
from batho.context.mmap_storage import load_json_with_optional_mmap
from batho.context.storage import query_entities as query_entities_from_registry
from batho.context.storage import (
    query_relationships as query_relationships_from_registry,
)
from batho.context.storage import (
    rebuild_query_index,
)
from batho.utils.logging import get_logger

LOGGER = get_logger(__name__, component="query_service")


class QueryService:
    """SQLite-index-first query interface with in-memory fallback."""

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
        storage_cfg = bsg_cfg.get("storage", {}) if isinstance(bsg_cfg, dict) else {}

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

        self.mmap_enabled = bool(storage_cfg.get("mmap_enabled", False))
        mmap_min_size_mb = int(storage_cfg.get("mmap_min_size_mb", 8))
        self.mmap_min_size_bytes = max(1, mmap_min_size_mb) * 1024 * 1024

        self._cache: OrderedDict[tuple[Any, ...], list[dict[str, Any]]] = OrderedDict()

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

    def _index_metadata(self) -> dict[str, Any]:
        index_path = self.ctn_dir / "index.json"
        if not index_path.exists():
            return {}
        try:
            return load_json_with_optional_mmap(
                index_path,
                mmap_enabled=self.mmap_enabled,
                min_size_bytes=self.mmap_min_size_bytes,
            )
        except (json.JSONDecodeError, OSError, ValueError):
            return {}

    def _resolve_index_id(self) -> str | None:
        if self.index_id:
            return self.index_id
        metadata = self._index_metadata()
        current = metadata.get("current_index_id")
        if not current:
            return None
        return str(current)

    def _graph_payload(self, index_id: str) -> dict[str, Any]:
        graph_path = self.ctn_dir / index_id / "graph.json"
        if not graph_path.exists():
            return {}

        try:
            return load_json_with_optional_mmap(
                graph_path,
                mmap_enabled=self.mmap_enabled,
                min_size_bytes=self.mmap_min_size_bytes,
            )
        except (json.JSONDecodeError, OSError, ValueError):
            LOGGER.warning("query_graph_load_failed", path=str(graph_path))
            return {}

    def rebuild_indexes(self) -> dict[str, int]:
        index_id = self._resolve_index_id()
        if not index_id:
            return {"entities_indexed": 0, "relationships_indexed": 0}

        payload = self._graph_payload(index_id)
        if not payload:
            return {"entities_indexed": 0, "relationships_indexed": 0}

        return rebuild_query_index(self.ctn_dir, index_id, payload)

    @staticmethod
    def _iter_entities(payload: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
        result: list[tuple[str, dict[str, Any]]] = []
        entities_by_id = payload.get("entities_by_id")
        if isinstance(entities_by_id, dict):
            for key, raw in entities_by_id.items():
                if not isinstance(raw, dict):
                    continue
                entity_id = str(raw.get("id") or key)
                result.append((entity_id, raw))
            return result

        entities = payload.get("entities")
        if isinstance(entities, list):
            for raw in entities:
                if not isinstance(raw, dict):
                    continue
                entity_id = str(raw.get("id") or "")
                if not entity_id:
                    continue
                result.append((entity_id, raw))
        return result

    @staticmethod
    def _iter_relationships(payload: dict[str, Any]) -> list[dict[str, Any]]:
        relationships = payload.get("relationships")
        if not isinstance(relationships, list):
            return []
        return [raw for raw in relationships if isinstance(raw, dict)]

    def entities_by_type(
        self,
        entity_type: str,
        *,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        index_id = self._resolve_index_id()
        if not index_id:
            return []

        normalized = entity_type.strip().lower()
        capped_limit = max(1, int(limit))
        cache_key = ("entities_by_type", index_id, normalized, capped_limit)
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        rows = query_entities_from_registry(
            self.ctn_dir,
            index_id=index_id,
            entity_type=normalized,
            limit=capped_limit,
        )
        if rows:
            self._cache_set(cache_key, rows)
            return rows

        payload = self._graph_payload(index_id)
        fallback: list[dict[str, Any]] = []
        for entity_id, raw in self._iter_entities(payload):
            raw_type = str(raw.get("type") or "").strip().lower()
            if raw_type != normalized:
                continue
            metadata = (
                raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
            )
            fallback.append(
                {
                    "entity_id": entity_id,
                    "entity_type": raw_type,
                    "file_path": str(raw.get("file") or ""),
                    "name": str(raw.get("name") or ""),
                    "signature": raw.get("signature"),
                    "metadata": metadata,
                }
            )
            if len(fallback) >= capped_limit:
                break

        self._cache_set(cache_key, fallback)
        return fallback

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

        rows = query_entities_from_registry(
            self.ctn_dir,
            index_id=index_id,
            file_path=normalized_path,
            limit=capped_limit,
        )
        if rows:
            self._cache_set(cache_key, rows)
            return rows

        payload = self._graph_payload(index_id)
        fallback: list[dict[str, Any]] = []
        for entity_id, raw in self._iter_entities(payload):
            raw_file = str(raw.get("file") or "")
            if raw_file != normalized_path:
                continue
            raw_type = str(raw.get("type") or "").strip().lower()
            metadata = (
                raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
            )
            fallback.append(
                {
                    "entity_id": entity_id,
                    "entity_type": raw_type,
                    "file_path": raw_file,
                    "name": str(raw.get("name") or ""),
                    "signature": raw.get("signature"),
                    "metadata": metadata,
                }
            )
            if len(fallback) >= capped_limit:
                break

        self._cache_set(cache_key, fallback)
        return fallback

    def relationships_by_type(
        self,
        relationship_type: str,
        *,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        index_id = self._resolve_index_id()
        if not index_id:
            return []

        normalized = relationship_type.strip().lower()
        capped_limit = max(1, int(limit))
        cache_key = ("relationships_by_type", index_id, normalized, capped_limit)
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        rows = query_relationships_from_registry(
            self.ctn_dir,
            index_id=index_id,
            relationship_type=normalized,
            limit=capped_limit,
        )
        if rows:
            self._cache_set(cache_key, rows)
            return rows

        payload = self._graph_payload(index_id)
        fallback: list[dict[str, Any]] = []
        for raw in self._iter_relationships(payload):
            raw_type = str(raw.get("type") or "").strip().lower()
            if raw_type != normalized:
                continue
            metadata = (
                raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
            )
            fallback.append(
                {
                    "relationship_id": str(raw.get("id") or ""),
                    "relationship_type": raw_type,
                    "source_id": str(raw.get("source_id") or ""),
                    "target_id": str(raw.get("target_id") or ""),
                    "metadata": metadata,
                }
            )
            if len(fallback) >= capped_limit:
                break

        self._cache_set(cache_key, fallback)
        return fallback
