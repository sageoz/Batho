"""Unified artifact storage backed by the .batho SQLite database.

This module provides the persistence API for Batho — all graph data, BSG
payloads, context outputs, snapshots, and sync metadata are stored in the
single .batho database. No file-based JSON artifacts are used.

Public API (backward-compatible function signatures):
- get_database / get_artifact_registry  → BathoDatabase instance
- register_artifact / register_artifact_for_path → artifact registration
- persist_json / persist_text / persist_bytes → content + registration
- query_entities / query_relationships → graph queries
- rebuild_query_index → re-populate query indexes from graph payload
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from batho.config import get_config_cached
from batho.storage.engine import BathoDatabase, get_database
from batho.utils.logging import get_logger

LOGGER = get_logger(__name__, component="storage")

_DEFAULT_RETENTION_CLASS = "default"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=True, sort_keys=True)


def _schema_for_artifact_type(artifact_type: str) -> str:
    cfg = get_config_cached()
    if artifact_type == "graph_json":
        return str(cfg.get("graph_schema_version", "graph.v1"))
    if artifact_type == "bsg_json":
        return str(cfg.get("bsg_schema_version", "bsg.v1"))
    if artifact_type in {"snapshot_json"}:
        return str(cfg.get("snapshot_schema_version", "snapshot.v1"))
    if artifact_type == "index_metadata":
        return str(cfg.get("index_metadata_schema_version", "index-metadata.v1"))
    if artifact_type == "file_cache_sqlite":
        return str(cfg.get("file_cache_schema_version", "file-cache.v1"))
    if artifact_type == "evolution_ledger_json":
        return "evolution-ledger.v1"
    if artifact_type == "patch_audit_log_json":
        return "patch-audit-log.v1"
    if artifact_type == "rules_cache_binary":
        return "rules-cache.v1"
    if artifact_type == "interception_stats_json":
        return "interception-stats.v1"
    if artifact_type == "patch_operation_json":
        return "patch-operation.v1"
    if artifact_type == "patch_index_json":
        return "patch-index.v1"
    if artifact_type.startswith("context_"):
        return "context.v1"
    if artifact_type == "metrics_json":
        return "metrics.v1"
    return ""


def _build_artifact_id(
    artifact_type: str,
    logical_path: str,
    checksum: str,
    schema_version: str,
) -> str:
    payload = f"{artifact_type}:{logical_path}:{checksum}:{schema_version}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _resolve_db_path(root_or_db: Path | None = None) -> Path:
    """Resolve the .batho database path from a root directory or direct path."""
    if root_or_db is None:
        root_or_db = Path.cwd()
    resolved = Path(root_or_db).resolve()
    if resolved.suffix == ".batho":
        return resolved
    # Treat as repo root
    cfg = get_config_cached()
    db_name = cfg.get("paths", {}).get("db_path", ".batho")
    if not db_name or db_name == ".batho":
        from batho.storage.engine import artifact_filename
        return resolved / artifact_filename(resolved)
    return resolved / db_name


# ---------------------------------------------------------------------------
# Database access (replaces get_artifact_registry)
# ---------------------------------------------------------------------------


# Keep old name as alias for callers that imported ArtifactRegistry type
ArtifactRegistry = BathoDatabase


def get_artifact_registry(root_or_ctn_dir: Path | None = None) -> BathoDatabase:
    """Get the BathoDatabase for the given repo root (or legacy ctn_dir path).

    For backward compatibility: if a .ctn path is passed, the parent is used
    as repo_root.  New code should use get_database() directly.
    """
    if root_or_ctn_dir is None:
        root_or_ctn_dir = Path.cwd()

    resolved = Path(root_or_ctn_dir).resolve()

    # Legacy callers may pass .ctn dir — extract repo root
    if resolved.name in {".ctn", "ctn"}:
        resolved = resolved.parent

    return get_database(resolved)


def infer_ctn_dir_for_path(path: Path) -> Path | None:
    """Legacy compatibility: resolve repo root from any file under the project.

    Returns the repo root (not .ctn dir, which no longer exists).
    """
    resolved = Path(path).resolve()
    # Walk up looking for batho.yaml or artifact_*.batho file as repo markers
    for parent in [resolved] + list(resolved.parents):
        if (parent / "batho.yaml").exists():
            return parent
        if list(parent.glob("artifact_*.batho")):
            return parent
    return None


# ---------------------------------------------------------------------------
# Artifact Registration
# ---------------------------------------------------------------------------


def register_artifact(
    root_or_ctn_dir: Path,
    artifact_path: Path,
    artifact_type: str,
    *,
    producer: str = "unknown",
    metadata: dict[str, Any] | None = None,
    schema_version: str = "",
    retention_class: str = _DEFAULT_RETENTION_CLASS,
    run_id: str = "",
) -> bool:
    """Register an artifact in the .batho database."""
    db = get_artifact_registry(root_or_ctn_dir)

    path = Path(artifact_path).resolve()
    logical_path = path.name
    try:
        size_bytes = path.stat().st_size if path.exists() else 0
    except OSError:
        size_bytes = 0

    resolved_schema = schema_version or _schema_for_artifact_type(artifact_type)
    checksum = ""
    if path.exists():
        try:
            from batho.utils.hash import compute_file_hash
            checksum = compute_file_hash(path) or ""
        except Exception:
            pass

    artifact_id = _build_artifact_id(artifact_type, logical_path, checksum, resolved_schema)

    try:
        db.register_artifact(
            artifact_id,
            artifact_type=artifact_type,
            logical_path=logical_path,
            size_bytes=size_bytes,
            schema_version=resolved_schema,
            producer=producer,
            checksum=checksum,
            run_id=run_id or None,
            sync_status="pending" if metadata and metadata.get("cloud_sync_ready") else "local_only",
            retention_class=retention_class,
            metadata=metadata,
        )
        return True
    except Exception as exc:
        LOGGER.warning("register_artifact_failed", error=str(exc))
        return False


def register_artifact_for_path(
    artifact_path: Path,
    artifact_type: str,
    *,
    producer: str = "unknown",
    metadata: dict[str, Any] | None = None,
    schema_version: str = "",
    retention_class: str = _DEFAULT_RETENTION_CLASS,
    run_id: str = "",
) -> bool:
    """Register an artifact using auto-detected repo root."""
    root = infer_ctn_dir_for_path(artifact_path)
    if root is None:
        root = Path.cwd()
    return register_artifact(
        root,
        artifact_path,
        artifact_type,
        producer=producer,
        metadata=metadata,
        schema_version=schema_version,
        retention_class=retention_class,
        run_id=run_id,
    )


# ---------------------------------------------------------------------------
# Persist helpers (write content + register)
# ---------------------------------------------------------------------------


def persist_json(
    root_or_ctn_dir: Path,
    path: Path,
    payload: dict[str, Any],
    *,
    artifact_type: str,
    producer: str = "storage.persist",
    metadata: dict[str, Any] | None = None,
    schema_version: str = "",
    retention_class: str = _DEFAULT_RETENTION_CLASS,
    run_id: str = "",
) -> bool:
    """Write JSON to disk and register the artifact."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8"
    )
    tmp_path.replace(path)

    return register_artifact(
        root_or_ctn_dir,
        path,
        artifact_type,
        producer=producer,
        metadata=metadata,
        schema_version=schema_version,
        retention_class=retention_class,
        run_id=run_id,
    )


def persist_text(
    root_or_ctn_dir: Path,
    path: Path,
    content: str,
    *,
    artifact_type: str,
    producer: str = "storage.persist",
    metadata: dict[str, Any] | None = None,
    schema_version: str = "",
    retention_class: str = _DEFAULT_RETENTION_CLASS,
    run_id: str = "",
) -> bool:
    """Write text to disk and register the artifact."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(content, encoding="utf-8")
    tmp_path.replace(path)

    return register_artifact(
        root_or_ctn_dir,
        path,
        artifact_type,
        producer=producer,
        metadata=metadata,
        schema_version=schema_version,
        retention_class=retention_class,
        run_id=run_id,
    )


def persist_bytes(
    root_or_ctn_dir: Path,
    path: Path,
    content: bytes,
    *,
    artifact_type: str,
    producer: str = "storage.persist",
    metadata: dict[str, Any] | None = None,
    schema_version: str = "",
    retention_class: str = _DEFAULT_RETENTION_CLASS,
    run_id: str = "",
) -> bool:
    """Write bytes to disk and register the artifact."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_bytes(content)
    tmp_path.replace(path)

    return register_artifact(
        root_or_ctn_dir,
        path,
        artifact_type,
        producer=producer,
        metadata=metadata,
        schema_version=schema_version,
        retention_class=retention_class,
        run_id=run_id,
    )


# ---------------------------------------------------------------------------
# Graph Queries (now backed by graph_entities / graph_relationships tables)
# ---------------------------------------------------------------------------


def rebuild_query_index(
    root_or_ctn_dir: Path,
    index_id: str,
    graph_payload: dict[str, Any],
) -> dict[str, int]:
    """Rebuild query indexes from a graph payload dict.

    Inserts entities and relationships from the payload into the .batho DB
    under the given run_id (index_id).
    """
    db = get_artifact_registry(root_or_ctn_dir)

    entities_raw = graph_payload.get("entities", [])
    rels_raw = graph_payload.get("relationships", [])

    # Normalize entity dicts for insertion
    normalized_entities = []
    for e in entities_raw:
        if isinstance(e, dict):
            normalized_entities.append({
                "id": e.get("id", e.get("entity_id", "")),
                "type": e.get("type", e.get("entity_type", "")),
                "name": e.get("name", ""),
                "file": e.get("file", e.get("file_path", "")),
                "start_line": e.get("start_line", 0),
                "end_line": e.get("end_line", 0),
                "start_byte": e.get("start_byte", 0),
                "end_byte": e.get("end_byte", 0),
                "signature": e.get("signature"),
                "parent_id": e.get("parent_id"),
                "content_hash": e.get("content_hash", ""),
                "ast_node_type": e.get("ast_node_type"),
                "metadata": e.get("metadata", {}),
            })

    normalized_rels = []
    for r in rels_raw:
        if isinstance(r, dict):
            normalized_rels.append({
                "id": r.get("id", r.get("relationship_id", "")),
                "type": r.get("type", r.get("relationship_type", "")),
                "source_id": r.get("source_id", r.get("source", "")),
                "target_id": r.get("target_id", r.get("target", "")),
                "metadata": r.get("metadata", {}),
            })

    entity_count = db.insert_entities(index_id, normalized_entities)
    rel_count = db.insert_relationships(index_id, normalized_rels)

    return {"entities": entity_count, "relationships": rel_count}


def query_entities(
    root_or_ctn_dir: Path,
    *,
    index_id: str,
    entity_type: str | None = None,
    file_path: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Query graph entities from the .batho database."""
    db = get_artifact_registry(root_or_ctn_dir)
    results = db.query_entities(
        index_id,
        entity_type=entity_type,
        file_path=file_path,
        limit=limit,
    )
    # Re-map column names for callers expecting legacy format
    return [
        {
            "entity_id": r.get("entity_id", ""),
            "entity_type": r.get("entity_type", ""),
            "file_path": r.get("file_path", ""),
            "name": r.get("name", ""),
            "signature": r.get("signature"),
            "start_line": r.get("start_line", 0),
            "end_line": r.get("end_line", 0),
            "metadata_json": r.get("metadata_json", "{}"),
        }
        for r in results
    ]


def query_relationships(
    root_or_ctn_dir: Path,
    *,
    index_id: str,
    relationship_type: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Query graph relationships from the .batho database."""
    db = get_artifact_registry(root_or_ctn_dir)
    results = db.query_relationships(
        index_id,
        relationship_type=relationship_type,
        limit=limit,
    )
    # Re-map column names for callers expecting legacy format
    return [
        {
            "relationship_id": r.get("relationship_id", ""),
            "relationship_type": r.get("relationship_type", ""),
            "source_id": r.get("source_id", ""),
            "target_id": r.get("target_id", ""),
            "metadata_json": r.get("metadata_json", "{}"),
        }
        for r in results
    ]


# ---------------------------------------------------------------------------
# Sync helpers
# ---------------------------------------------------------------------------


def get_registry_stats(root_or_ctn_dir: Path) -> dict[str, Any]:
    """Get database statistics."""
    db = get_artifact_registry(root_or_ctn_dir)
    return db.get_stats()


def get_pending_artifacts(
    root_or_ctn_dir: Path,
    artifact_types: list[str] | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Get artifacts pending cloud sync."""
    db = get_artifact_registry(root_or_ctn_dir)
    return db.get_pending_artifacts(
        artifact_types=artifact_types, limit=limit or 100
    )


def get_failed_artifacts(
    root_or_ctn_dir: Path,
    max_retries: int = 3,
) -> list[dict[str, Any]]:
    """Get failed artifacts that haven't exceeded retry limit."""
    db = get_artifact_registry(root_or_ctn_dir)
    with db.connection(read_only=True) as conn:
        rows = conn.execute(
            """SELECT * FROM artifacts
            WHERE deleted = 0 AND sync_status = 'failed'
            AND retry_count < ?
            ORDER BY updated_at DESC""",
            (max_retries,),
        ).fetchall()
        return [dict(row) for row in rows]


def mark_sync_failed(
    root_or_ctn_dir: Path,
    artifact_id: str,
    error: str,
    retry_count: int = 0,
) -> bool:
    """Mark an artifact sync as failed."""
    db = get_artifact_registry(root_or_ctn_dir)
    try:
        db.mark_artifact_failed(artifact_id, error=error, retry_count=retry_count)
        return True
    except Exception:
        return False


def get_sync_summary(root_or_ctn_dir: Path) -> dict[str, Any]:
    """Get a summary of sync status counts."""
    db = get_artifact_registry(root_or_ctn_dir)
    with db.connection(read_only=True) as conn:
        rows = conn.execute(
            """SELECT sync_status, COUNT(*) as cnt
            FROM artifacts WHERE deleted = 0
            GROUP BY sync_status"""
        ).fetchall()
        return {row["sync_status"]: row["cnt"] for row in rows}


def compact_registry(
    root_or_ctn_dir: Path,
    *,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Run incremental vacuum on the database."""
    db = get_artifact_registry(root_or_ctn_dir)
    if not dry_run:
        db.vacuum()
    stats = db.get_stats()
    return {"file_size_bytes": stats.get("file_size_bytes", 0), "dry_run": dry_run}
