"""Artifact registry bridge — queries the unified .batho database."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Callable

from batho.bridge.constants import ARTIFACT_RECORD_FIELDS, DEFAULT_PAGE_LIMIT
from batho.bridge.models import ArtifactRecord, IndexEntry, RegistryStats
from batho.context.storage import ArtifactRegistry, get_artifact_registry
from batho.utils.logging import get_logger

LOGGER = get_logger(__name__, component="bridge")


ConnectionFactory = Callable[[], sqlite3.Connection]


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

    def __init__(
        self,
        ctn_dir: Path,
        connection_factory: ConnectionFactory | None = None,
        pool: "ConnectionPool | None" = None,
    ) -> None:
        self.ctn_dir = ctn_dir.resolve()
        self._connection_factory = connection_factory
        self._pool = pool
        self._registry: ArtifactRegistry | None = None
        if connection_factory is None and pool is None:
            self._registry = get_artifact_registry(self.ctn_dir)

    def _get_connection(self) -> sqlite3.Connection:
        """Get a connection from BathoDatabase or legacy pool/factory."""
        if self._pool:
            return self._pool.acquire()
        if self._connection_factory:
            return self._connection_factory()
        if self._registry:
            return self._registry._get_connection()
        raise RuntimeError("No connection source available")

    def _release_connection(self, conn: sqlite3.Connection) -> None:
        """Release a connection back to the source."""
        if self._pool:
            self._pool.release(conn)
        # BathoDatabase connections are per-thread; do not close them.

    @property
    def registry_path(self) -> Path:
        if self._pool:
            return self._pool._db_path
        if self._registry:
            return self._registry.path
        from batho.storage.engine import artifact_filename
        return self.ctn_dir / artifact_filename(self.ctn_dir)

    @property
    def enabled(self) -> bool:
        if self._pool:
            return self.registry_path.exists()
        if self._connection_factory:
            return self.registry_path.exists()
        return bool(self._registry and self._registry.exists)

    def list_artifact_types(self) -> list[str]:
        """Return distinct artifact types present in the registry."""
        if not self.enabled:
            return []
        conn = self._get_connection()
        try:
            rows = conn.execute(
                "SELECT DISTINCT artifact_type FROM artifacts WHERE deleted = 0 ORDER BY artifact_type"
            ).fetchall()
            return [str(row["artifact_type"]) for row in rows]
        finally:
            self._release_connection(conn)

    def get_artifacts_by_type(
        self, artifact_type: str, *, limit: int | None = None
    ) -> list[ArtifactRecord]:
        """Return active artifacts of the given type."""
        if not self.enabled:
            return []
        limit = limit if limit is not None else DEFAULT_PAGE_LIMIT
        conn = self._get_connection()
        try:
            rows = conn.execute(
                "SELECT artifact_id, content_id, artifact_type, logical_path, "
                "checksum, size_bytes, schema_version, producer, run_id, sync_status, "
                "cloud_content_id, last_sync_at, sync_error, retry_count, retention_class, "
                "metadata_json, created_at, updated_at "
                "FROM artifacts WHERE deleted = 0 AND artifact_type = ? "
                "ORDER BY updated_at DESC LIMIT ?",
                (artifact_type, max(1, int(limit))),
            ).fetchall()
            return [_row_to_record(row) for row in rows]
        finally:
            self._release_connection(conn)

    def get_artifact_by_logical_path(self, logical_path: str) -> ArtifactRecord | None:
        """Return the most recent active artifact by logical path."""
        if not self.enabled:
            return None
        conn = self._get_connection()
        try:
            row = conn.execute(
                "SELECT artifact_id, content_id, artifact_type, logical_path, "
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
        finally:
            self._release_connection(conn)

    def get_latest_index(self) -> IndexEntry | None:
        """Get the latest completed index run from the .batho database."""
        if not self._registry:
            return None
        run_id = self._registry.get_latest_run_id()
        if not run_id:
            return None
        run = self._registry.get_run(run_id)
        if not run:
            return None
        return _run_to_index_entry(run)

    def list_indexes(self) -> tuple[list[IndexEntry], str, str | None, str | None]:
        """Return all completed index runs from the .batho database.

        Returns ``(entries, current_run_id, persistence_model, schema_version)``.
        """
        if not self._registry:
            return [], "", None, None
        conn = self._get_connection()
        rows = conn.execute(
            "SELECT * FROM index_runs WHERE status = 'completed' ORDER BY completed_at DESC"
        ).fetchall()
        current_run_id = self._registry.get_latest_run_id() or ""
        schema_version = self._registry.get_meta("schema_version")
        entries = [_run_to_index_entry(dict(row)) for row in rows]
        return entries, current_run_id, "unified_sqlite", schema_version

    def search_artifacts(self, query: str, artifact_type: str | None = None) -> list[ArtifactRecord]:
        """Fuzzy search on logical paths."""
        if not self.enabled:
            return []
        pattern = f"%{query}%"
        conn = self._get_connection()
        try:
            if artifact_type:
                rows = conn.execute(
                    "SELECT artifact_id, content_id, artifact_type, logical_path, "
                    "checksum, size_bytes, schema_version, producer, run_id, sync_status, "
                    "cloud_content_id, last_sync_at, sync_error, retry_count, retention_class, "
                    "metadata_json, created_at, updated_at "
                    "FROM artifacts WHERE deleted = 0 AND artifact_type = ? AND logical_path LIKE ? "
                    "ORDER BY updated_at DESC LIMIT ?",
                    (artifact_type, pattern, DEFAULT_PAGE_LIMIT),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT artifact_id, content_id, artifact_type, logical_path, "
                    "checksum, size_bytes, schema_version, producer, run_id, sync_status, "
                    "cloud_content_id, last_sync_at, sync_error, retry_count, retention_class, "
                    "metadata_json, created_at, updated_at "
                    "FROM artifacts WHERE deleted = 0 AND logical_path LIKE ? "
                    "ORDER BY updated_at DESC LIMIT ?",
                    (pattern, DEFAULT_PAGE_LIMIT),
                ).fetchall()
            return [_row_to_record(row) for row in rows]
        finally:
            self._release_connection(conn)

    def stats(self) -> RegistryStats:
        """Return registry statistics from .batho database."""
        if not self._registry:
            return RegistryStats(enabled=False)
        raw = self._registry.get_stats()
        return RegistryStats(
            enabled=self.enabled,
            registry_path=str(self.registry_path),
            backend="unified_sqlite",
            artifact_count=raw.get("artifacts_count", 0),
            db_size_bytes=raw.get("file_size_bytes", 0),
        )


def _row_to_record(row: sqlite3.Row) -> ArtifactRecord:
    metadata = _safe_json_loads(str(row["metadata_json"] or "{}"))
    return ArtifactRecord(
        artifact_id=str(row["artifact_id"]),
        artifact_type=str(row["artifact_type"]),
        logical_path=str(row["logical_path"]),
        physical_path="",  # No longer stored separately
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


def _run_to_index_entry(run: dict[str, Any]) -> IndexEntry:
    """Convert a DB index_runs row dict to an IndexEntry model."""
    return IndexEntry(
        index_id=run.get("run_id", ""),
        timestamp=run.get("completed_at") or run.get("started_at", ""),
        root=run.get("root_path", ""),
        file_count=run.get("file_count", 0),
        entity_count=run.get("entity_count", 0),
        relationship_count=run.get("relationship_count", 0),
        repo_hash=run.get("config_hash", ""),
        staleness_score=0.0,
        stack={},
        outputs={},
        stats={},
        metrics={},
        build={},
        schemas={"version": run.get("schema_version", "")},
        persistence={"model": "unified_sqlite"},
        snapshot_id="",
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
        metrics=entry.get("metrics", {}),
        build=entry.get("build", {}),
        schemas=entry.get("schemas", {}),
        persistence=entry.get("persistence", {}),
        snapshot_id=entry.get("snapshot_id", ""),
    )


__all__ = [
    "ArtifactRegistryBridge",
]
