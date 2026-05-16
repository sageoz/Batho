"""Artifact registry bridge — queries the SQLite-backed artifact registry."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from batho.bridge.constants import ARTIFACT_RECORD_FIELDS, DEFAULT_PAGE_LIMIT
from batho.bridge.models import ArtifactRecord, IndexEntry, RegistryStats
from batho.context.storage import ArtifactRegistry, get_artifact_registry
from batho.utils.logging import get_logger

LOGGER = get_logger(__name__, component="bridge")


def _safe_json_loads(payload: str) -> dict[str, Any]:
    try:
        parsed = json.loads(payload)
    except (TypeError, json.JSONDecodeError):
        return {}
    if isinstance(parsed, dict):
        return parsed
    return {}


class ArtifactRegistryBridge:
    """Thin bridge over ``ArtifactRegistry`` with typed query methods."""

    def __init__(self, ctn_dir: Path) -> None:
        self.ctn_dir = ctn_dir.resolve()
        self._registry: ArtifactRegistry = get_artifact_registry(self.ctn_dir)

    @property
    def registry_path(self) -> Path:
        return self._registry.registry_path

    @property
    def enabled(self) -> bool:
        return bool(self._registry.enabled and self._registry._ready)

    def list_artifact_types(self) -> list[str]:
        """Return distinct artifact types present in the registry."""
        if not self.enabled:
            return []
        with self._registry._connect(row_factory=True) as conn:
            rows = conn.execute(
                "SELECT DISTINCT artifact_type FROM artifacts WHERE deleted = 0 ORDER BY artifact_type"
            ).fetchall()
        return [str(row["artifact_type"]) for row in rows]

    def get_artifacts_by_type(
        self, artifact_type: str, *, limit: int | None = None
    ) -> list[ArtifactRecord]:
        """Return active artifacts of the given type."""
        if not self.enabled:
            return []
        limit = limit if limit is not None else DEFAULT_PAGE_LIMIT
        with self._registry._connect(row_factory=True) as conn:
            rows = conn.execute(
                "SELECT artifact_id, content_id, artifact_type, logical_path, physical_path, "
                "checksum, size_bytes, schema_version, producer, run_id, sync_status, "
                "cloud_content_id, last_sync_at, sync_error, retry_count, retention_class, "
                "metadata_json, created_at, updated_at "
                "FROM artifacts WHERE deleted = 0 AND artifact_type = ? "
                "ORDER BY updated_at DESC LIMIT ?",
                (artifact_type, max(1, int(limit))),
            ).fetchall()
        return [_row_to_record(row) for row in rows]

    def get_artifact_by_logical_path(self, logical_path: str) -> ArtifactRecord | None:
        """Return the most recent active artifact by logical path."""
        if not self.enabled:
            return None
        with self._registry._connect(row_factory=True) as conn:
            row = conn.execute(
                "SELECT artifact_id, content_id, artifact_type, logical_path, physical_path, "
                "checksum, size_bytes, schema_version, producer, run_id, sync_status, "
                "cloud_content_id, last_sync_at, sync_error, retry_count, retention_class, "
                "metadata_json, created_at, updated_at "
                "FROM artifacts WHERE deleted = 0 AND logical_path = ? "
                "ORDER BY updated_at DESC LIMIT 1",
                (logical_path,),
            ).fetchone()
        if row is None:
            return None
        return _row_to_record(row)

    def get_latest_index(self) -> IndexEntry | None:
        """Read ``.ctn/index.json`` and return the current index entry."""
        index_path = self.ctn_dir / "index.json"
        if not index_path.exists():
            return None
        try:
            data = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            LOGGER.warning("index_json_read_failed", path=str(index_path), error=str(exc))
            return None

        current_index_id = data.get("current_index_id")
        indexes = data.get("indexes", {})
        entry = indexes.get(current_index_id) if current_index_id else None
        if not entry:
            return None

        return _dict_to_index_entry(current_index_id, entry)

    def list_indexes(self) -> list[IndexEntry]:
        """Return all index entries from ``.ctn/index.json``."""
        index_path = self.ctn_dir / "index.json"
        if not index_path.exists():
            return []
        try:
            data = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            LOGGER.warning("index_json_read_failed", path=str(index_path), error=str(exc))
            return []

        indexes = data.get("indexes", {})
        return [_dict_to_index_entry(idx_id, entry) for idx_id, entry in indexes.items()]

    def search_artifacts(self, query: str, artifact_type: str | None = None) -> list[ArtifactRecord]:
        """Fuzzy search on logical paths."""
        if not self.enabled:
            return []
        pattern = f"%{query}%"
        with self._registry._connect(row_factory=True) as conn:
            if artifact_type:
                rows = conn.execute(
                    "SELECT artifact_id, content_id, artifact_type, logical_path, physical_path, "
                    "checksum, size_bytes, schema_version, producer, run_id, sync_status, "
                    "cloud_content_id, last_sync_at, sync_error, retry_count, retention_class, "
                    "metadata_json, created_at, updated_at "
                    "FROM artifacts WHERE deleted = 0 AND artifact_type = ? AND logical_path LIKE ? "
                    "ORDER BY updated_at DESC LIMIT ?",
                    (artifact_type, pattern, DEFAULT_PAGE_LIMIT),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT artifact_id, content_id, artifact_type, logical_path, physical_path, "
                    "checksum, size_bytes, schema_version, producer, run_id, sync_status, "
                    "cloud_content_id, last_sync_at, sync_error, retry_count, retention_class, "
                    "metadata_json, created_at, updated_at "
                    "FROM artifacts WHERE deleted = 0 AND logical_path LIKE ? "
                    "ORDER BY updated_at DESC LIMIT ?",
                    (pattern, DEFAULT_PAGE_LIMIT),
                ).fetchall()
        return [_row_to_record(row) for row in rows]

    def stats(self) -> RegistryStats:
        """Return registry statistics."""
        raw = self._registry.stats()
        return RegistryStats(
            enabled=raw.get("enabled", False),
            registry_path=raw.get("registry_path", ""),
            backend=raw.get("backend", "sqlite"),
            artifact_count=raw.get("artifact_count", 0),
            deleted_artifact_count=raw.get("deleted_artifact_count", 0),
            content_blob_count=raw.get("content_blob_count", 0),
            artifact_types=raw.get("artifact_types", {}),
            sync_status=raw.get("sync_status", {}),
            db_size_bytes=raw.get("db_size_bytes", 0),
        )


def _row_to_record(row: sqlite3.Row) -> ArtifactRecord:
    metadata = _safe_json_loads(str(row["metadata_json"] or "{}"))
    return ArtifactRecord(
        artifact_id=str(row["artifact_id"]),
        artifact_type=str(row["artifact_type"]),
        logical_path=str(row["logical_path"]),
        physical_path=str(row["physical_path"]),
        checksum=str(row["checksum"] or ""),
        size_bytes=int(row["size_bytes"] or 0),
        schema_version=str(row["schema_version"] or ""),
        producer=str(row["producer"] or ""),
        run_id=str(row["run_id"] or ""),
        sync_status=str(row["sync_status"] or "local_only"),
        cloud_content_id=str(row["cloud_content_id"]) if row["cloud_content_id"] else None,
        last_sync_at=str(row["last_sync_at"]) if row["last_sync_at"] else None,
        sync_error=str(row["sync_error"]) if row["sync_error"] else None,
        retry_count=int(row["retry_count"] or 0),
        retention_class=str(row["retention_class"] or "default"),
        metadata=metadata,
        created_at=str(row["created_at"] or ""),
        updated_at=str(row["updated_at"] or ""),
    )


def _dict_to_index_entry(index_id: str, entry: dict[str, Any]) -> IndexEntry:
    return IndexEntry(
        index_id=index_id,
        timestamp=entry.get("timestamp", ""),
        root=entry.get("root", ""),
        file_count=entry.get("file_count", 0),
        entity_count=entry.get("entity_count", 0),
        relationship_count=entry.get("relationship_count", 0),
        repo_hash=entry.get("repo_hash", ""),
        staleness_score=entry.get("staleness_score", 1.0),
        stack=entry.get("stack", {}),
        outputs=entry.get("outputs", {}),
        stats=entry.get("stats", {}),
    )


__all__ = [
    "ArtifactRegistryBridge",
]
