"""Query service backed by the unified .batho SQLite database (v2.0).

Loads compressed blobs from file_artifacts, decompresses them, and
filters in-memory. No legacy graph_entities/graph_relationships tables.
"""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from typing import Any

from batho.core.config import get_config_cached
from batho.modules.storage.sqlite_registry.engine import get_database
from batho.modules.compression.bsg_map.relativizer import PathRelativizer
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
        """Discard cached query results if run_uuid changes."""
        if self._loaded_run_id == run_uuid:
            return

        self._cache.clear()
        self._entities = []
        self._relationships = []
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

        self._ensure_loaded(run_uuid)
        run_internal_id = self._db.get_run_internal_id(run_uuid)
        if run_internal_id is None:
            return []

        # Find file paths containing this entity type
        with self._db.connection(read_only=True) as conn:
            rows = conn.execute(
                """SELECT DISTINCT file_path FROM query_entities
                   WHERE run_id = ? AND UPPER(entity_type) = ?""",
                (run_internal_id, normalized)
            ).fetchall()
            file_paths = [r["file_path"] for r in rows]

        results = []
        for file_path in file_paths:
            entities = self._db.get_agent_entities_for_file(run_internal_id, file_path)
            for e in entities:
                if str(e.get("entity_type", e.get("type", ""))).upper() == normalized:
                    e_copy = dict(e)
                    if "file" not in e_copy:
                        e_copy["file"] = file_path
                    results.append(e_copy)
                    if len(results) >= capped_limit:
                        break
            if len(results) >= capped_limit:
                break

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
        normalized_query_path = self._relativizer(file_path.strip())
        cache_key = ("entities_by_file", run_uuid, normalized_query_path, capped_limit)
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        self._ensure_loaded(run_uuid)
        run_internal_id = self._db.get_run_internal_id(run_uuid)
        if run_internal_id is None:
            return []

        # Find exact file_path in database by resolving path relativization
        with self._db.connection(read_only=True) as conn:
            rows = conn.execute(
                """SELECT sd.val AS file_path FROM file_artifacts fa
                   JOIN string_dict sd ON fa.file_id = sd.id
                   WHERE fa.run_id = ?""",
                (run_internal_id,)
            ).fetchall()
            db_file_path = None
            for r in rows:
                if self._relativizer(r["file_path"]) == normalized_query_path:
                    db_file_path = r["file_path"]
                    break

        results = []
        if db_file_path:
            entities = self._db.get_agent_entities_for_file(run_internal_id, db_file_path)
            for e in entities:
                e_copy = dict(e)
                if "file" not in e_copy:
                    e_copy["file"] = db_file_path
                results.append(e_copy)
            results = results[:capped_limit]

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
        run_internal_id = self._db.get_run_internal_id(run_uuid)
        if run_internal_id is None:
            return []

        import json
        with self._db.connection(read_only=True) as conn:
            rows = conn.execute(
                """SELECT source_id, target_id, relation_type, metadata_json
                   FROM query_relationships
                   WHERE run_id = ? AND UPPER(relation_type) = ?
                   LIMIT ?""",
                (run_internal_id, normalized, capped_limit)
            ).fetchall()
            
            results = []
            for r in rows:
                meta = {}
                if r["metadata_json"]:
                    try:
                        meta = json.loads(r["metadata_json"])
                    except Exception:
                        pass
                results.append({
                    "type": r["relation_type"],
                    "relationship_type": r["relation_type"],
                    "source_id": r["source_id"],
                    "target_id": r["target_id"],
                    "metadata": meta,
                })

        self._cache_set(cache_key, results)
        return results
