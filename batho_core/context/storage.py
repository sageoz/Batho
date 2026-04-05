"""CTN artifact persistence registry for generated outputs.

This module keeps current on-disk .ctn files unchanged while registering
artifact metadata in a SQLite registry for future cloud synchronization.

It also provides:
- one-time backfill and verify/repair helpers,
- retention cleanup APIs with dry-run support,
- persisted query indexes for common graph lookups,
- atomic persist wrappers that preserve strict compatibility.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
from typing import Any

from batho_core.config import get_config_cached
from batho_core.utils.file_io import write_atomically
from batho_core.utils.hash import compute_file_hash
from batho_core.utils.logging import get_logger

LOGGER = get_logger(__name__, component="ctn_storage")

_REGISTRY_SCHEMA_VERSION = "ctn-artifact-registry.v1"
_QUERY_INDEX_SCHEMA_VERSION = "ctn-query-index.v1"
_DEFAULT_REGISTRY_PATH = ".ctn/artifact_registry.db"
_DEFAULT_RETENTION_CLASS = "default"
_REGISTRY_CACHE: dict[str, "ArtifactRegistry"] = {}
_REGISTRY_CACHE_LOCK = Lock()


@dataclass(frozen=True)
class ArtifactDescriptor:
    artifact_type: str
    retention_class: str = _DEFAULT_RETENTION_CLASS
    schema_version: str = ""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_relative(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path.resolve())


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _json_dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=True, sort_keys=True)


def _safe_json_loads(payload: str) -> dict[str, Any]:
    try:
        parsed = json.loads(payload)
    except (TypeError, json.JSONDecodeError):
        return {}
    if isinstance(parsed, dict):
        return parsed
    return {}


def _safe_parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None

    text = value.strip()
    if not text:
        return None

    # Handle trailing Z emitted by some producers.
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"

    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


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


def describe_artifact(artifact_path: Path, ctn_dir: Path) -> ArtifactDescriptor:
    """Infer artifact type and retention class from an existing .ctn path."""
    logical = _safe_relative(artifact_path, ctn_dir).replace("\\", "/")

    if logical == "index.json":
        return ArtifactDescriptor("index_metadata", schema_version=_schema_for_artifact_type("index_metadata"))

    if logical == "file_cache.json":
        return ArtifactDescriptor("file_cache_sqlite", schema_version=_schema_for_artifact_type("file_cache_sqlite"))

    if logical == "file_hashes.json":
        return ArtifactDescriptor("file_hashes_json", schema_version="file-hashes.v1")

    if logical == "evolution_ledger.json":
        return ArtifactDescriptor(
            "evolution_ledger_json",
            schema_version=_schema_for_artifact_type("evolution_ledger_json"),
        )

    if logical == "patch_audit.log":
        return ArtifactDescriptor(
            "patch_audit_log_json",
            retention_class="patch",
            schema_version=_schema_for_artifact_type("patch_audit_log_json"),
        )

    if logical in {"rules_cache.pkl", "rules.cache.pkl"}:
        return ArtifactDescriptor(
            "rules_cache_binary",
            schema_version=_schema_for_artifact_type("rules_cache_binary"),
        )

    if logical == "interception_stats.json":
        return ArtifactDescriptor(
            "interception_stats_json",
            schema_version=_schema_for_artifact_type("interception_stats_json"),
        )

    if logical.startswith("snapshots/") and logical.endswith(".json"):
        return ArtifactDescriptor(
            "snapshot_json",
            retention_class="snapshot",
            schema_version=_schema_for_artifact_type("snapshot_json"),
        )

    if logical == "patches/index.json":
        return ArtifactDescriptor(
            "patch_index_json",
            retention_class="patch",
            schema_version=_schema_for_artifact_type("patch_index_json"),
        )

    if logical.startswith("patches/patch_") and logical.endswith(".json"):
        return ArtifactDescriptor(
            "patch_operation_json",
            retention_class="patch",
            schema_version=_schema_for_artifact_type("patch_operation_json"),
        )

    if logical.endswith("/graph.json"):
        return ArtifactDescriptor("graph_json", schema_version=_schema_for_artifact_type("graph_json"))

    if logical.endswith("/bsg.json"):
        return ArtifactDescriptor("bsg_json", schema_version=_schema_for_artifact_type("bsg_json"))

    if logical.endswith("/context/overview.md"):
        return ArtifactDescriptor("context_overview", retention_class="context", schema_version="context.v1")

    if logical.endswith("/context/architecture.md"):
        return ArtifactDescriptor("context_architecture", retention_class="context", schema_version="context.v1")

    if logical.endswith("/context/tests.md"):
        return ArtifactDescriptor("context_tests", retention_class="context", schema_version="context.v1")

    if logical.endswith("/context/docs.md"):
        return ArtifactDescriptor("context_docs", retention_class="context", schema_version="context.v1")

    if logical.endswith("/context/config.md"):
        return ArtifactDescriptor("context_config", retention_class="context", schema_version="context.v1")

    if "/context/" in logical and logical.endswith(".md"):
        return ArtifactDescriptor("context_markdown", retention_class="context", schema_version="context.v1")

    if logical.endswith("metrics.json"):
        return ArtifactDescriptor(
            "metrics_json",
            retention_class="metrics",
            schema_version=_schema_for_artifact_type("metrics_json"),
        )

    return ArtifactDescriptor("artifact_file", schema_version="artifact-file.v1")


def infer_ctn_dir_for_path(path: Path) -> Path | None:
    """Infer ctn_dir from an artifact path using configured ctn directory name."""
    cfg = get_config_cached()
    ctn_name = Path(str(cfg.get("paths", {}).get("ctn_dir", ".ctn"))).name

    resolved = path.resolve()
    if resolved.name == ctn_name and resolved.is_dir():
        return resolved

    for parent in resolved.parents:
        if parent.name == ctn_name:
            return parent

    return None


class ArtifactRegistry:
    """SQLite-backed artifact registry for durable .ctn outputs."""

    def __init__(self, ctn_dir: Path):
        self.ctn_dir = ctn_dir.resolve()
        cfg = get_config_cached().get("bsg", {}).get("storage", {})

        self.enabled = bool(cfg.get("enabled", True))
        self.backend = str(cfg.get("backend", "sqlite")).strip().lower()
        self.content_scope = str(cfg.get("content_scope", "durable")).strip().lower()
        self.cloud_sync_ready = bool(cfg.get("cloud_sync_ready", True))
        self.track_content_ids = bool(cfg.get("track_content_ids", True))
        retention_cfg = cfg.get("retention", {})
        self.retention_cfg = retention_cfg if isinstance(retention_cfg, dict) else {}
        self.registry_path = self._resolve_registry_path(
            str(cfg.get("registry_path", _DEFAULT_REGISTRY_PATH))
        )

        self._ready = False

        if not self.enabled:
            return

        if self.backend != "sqlite":
            LOGGER.warning("artifact_registry_backend_unsupported", backend=self.backend)
            self.enabled = False
            return

        self._initialize()

    @property
    def repo_root(self) -> Path:
        return self.ctn_dir.parent

    def _resolve_registry_path(self, configured_path: str) -> Path:
        candidate = Path(configured_path).expanduser()
        if candidate.is_absolute():
            return candidate
        return (self.repo_root / candidate).resolve()

    def _connect(self, *, row_factory: bool = False) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.registry_path), timeout=5)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        if row_factory:
            conn.row_factory = sqlite3.Row
        return conn

    def _migrate_schema(self, conn: sqlite3.Connection) -> None:
        columns = {
            str(row[1])
            for row in conn.execute("PRAGMA table_info(artifacts)").fetchall()
            if len(row) > 1
        }
        if "run_id" not in columns:
            conn.execute("ALTER TABLE artifacts ADD COLUMN run_id TEXT")
        if "sync_status" not in columns:
            conn.execute("ALTER TABLE artifacts ADD COLUMN sync_status TEXT")
        if "cloud_content_id" not in columns:
            conn.execute("ALTER TABLE artifacts ADD COLUMN cloud_content_id TEXT")
        if "last_sync_at" not in columns:
            conn.execute("ALTER TABLE artifacts ADD COLUMN last_sync_at TEXT")

    def _ensure_query_tables(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS query_entities (
                index_id TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                file_path TEXT NOT NULL,
                name TEXT NOT NULL,
                signature TEXT,
                metadata_json TEXT NOT NULL,
                PRIMARY KEY (index_id, entity_id)
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_query_entities_type ON query_entities(index_id, entity_type, name)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_query_entities_file ON query_entities(index_id, file_path, name)"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS query_relationships (
                index_id TEXT NOT NULL,
                relationship_id TEXT NOT NULL,
                relationship_type TEXT NOT NULL,
                source_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                PRIMARY KEY (index_id, relationship_id)
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_query_relationships_type ON query_relationships(index_id, relationship_type)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_query_relationships_source ON query_relationships(index_id, source_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_query_relationships_target ON query_relationships(index_id, target_id)"
        )

    def _initialize(self) -> None:
        try:
            self.registry_path.parent.mkdir(parents=True, exist_ok=True)
            with self._connect() as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS artifacts (
                        artifact_id TEXT PRIMARY KEY,
                        content_id TEXT,
                        artifact_type TEXT NOT NULL,
                        logical_path TEXT NOT NULL,
                        physical_path TEXT NOT NULL,
                        checksum TEXT,
                        size_bytes INTEGER NOT NULL,
                        schema_version TEXT NOT NULL,
                        producer TEXT NOT NULL,
                        run_id TEXT,
                        sync_status TEXT,
                        cloud_content_id TEXT,
                        last_sync_at TEXT,
                        retention_class TEXT NOT NULL,
                        metadata_json TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        deleted INTEGER NOT NULL DEFAULT 0
                    )
                    """
                )
                self._migrate_schema(conn)
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_artifacts_type ON artifacts(artifact_type, updated_at DESC)"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_artifacts_logical_path ON artifacts(logical_path, updated_at DESC)"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_artifacts_retention_class ON artifacts(retention_class, updated_at DESC)"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_artifacts_sync_status ON artifacts(sync_status, updated_at DESC)"
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS content_blobs (
                        content_id TEXT PRIMARY KEY,
                        checksum TEXT NOT NULL,
                        size_bytes INTEGER NOT NULL,
                        first_seen_at TEXT NOT NULL,
                        last_seen_at TEXT NOT NULL,
                        ref_count INTEGER NOT NULL DEFAULT 1
                    )
                    """
                )
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS registry_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
                )
                self._ensure_query_tables(conn)
                conn.execute(
                    "INSERT OR REPLACE INTO registry_meta(key, value) VALUES (?, ?)",
                    ("schema_version", _REGISTRY_SCHEMA_VERSION),
                )
                conn.execute(
                    "INSERT OR REPLACE INTO registry_meta(key, value) VALUES (?, ?)",
                    ("query_index_schema_version", _QUERY_INDEX_SCHEMA_VERSION),
                )
                conn.execute(
                    "INSERT OR REPLACE INTO registry_meta(key, value) VALUES (?, ?)",
                    ("ctn_dir", str(self.ctn_dir)),
                )
                conn.commit()
            self._ready = True
        except sqlite3.Error as exc:
            LOGGER.warning(
                "artifact_registry_init_failed",
                path=str(self.registry_path),
                error=str(exc),
            )
            self.enabled = False
            self._ready = False

    def _is_internal_registry_file(self, path: Path) -> bool:
        if path.resolve() == self.registry_path.resolve():
            return True

        suffix = path.name.lower()
        if suffix in {f"{self.registry_path.name}-wal", f"{self.registry_path.name}-shm"}:
            return True

        return False

    def _is_durable_artifact(self, path: Path) -> bool:
        if not _is_under(path, self.ctn_dir):
            return False

        if self._is_internal_registry_file(path):
            return False

        if self.content_scope == "all":
            return True

        name = path.name.lower()
        if name == "ctn.lock" or name.endswith(".tmp"):
            return False

        return True

    def _build_artifact_id(
        self,
        artifact_type: str,
        logical_path: str,
        checksum: str,
        schema_version: str,
    ) -> str:
        payload = f"{artifact_type}:{logical_path}:{checksum}:{schema_version}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def scan_durable_files(self) -> list[Path]:
        if not self.ctn_dir.exists() or not self.ctn_dir.is_dir():
            return []

        files: list[Path] = []
        for candidate in sorted(self.ctn_dir.rglob("*")):
            if not candidate.is_file():
                continue
            if not self._is_durable_artifact(candidate):
                continue
            files.append(candidate)
        return files

    def register_file(
        self,
        artifact_path: Path,
        artifact_type: str,
        *,
        producer: str = "unknown",
        metadata: dict[str, Any] | None = None,
        schema_version: str = "",
        retention_class: str = _DEFAULT_RETENTION_CLASS,
        run_id: str = "",
    ) -> bool:
        """Register a file artifact without changing its on-disk location."""
        if not self.enabled or not self._ready:
            return False

        path = artifact_path.resolve()
        if not path.exists() or not path.is_file():
            return False

        if not self._is_durable_artifact(path):
            return False

        # Keep logical paths scoped to .ctn for stable, portable artifact identifiers.
        logical_path = _safe_relative(path, self.ctn_dir)
        physical_path = str(path)
        checksum = compute_file_hash(path) or ""
        content_id = checksum if self.track_content_ids else ""

        try:
            size_bytes = path.stat().st_size
        except OSError:
            return False

        resolved_schema_version = schema_version or _schema_for_artifact_type(artifact_type)
        artifact_id = self._build_artifact_id(
            artifact_type=artifact_type,
            logical_path=logical_path,
            checksum=checksum,
            schema_version=resolved_schema_version,
        )

        payload = dict(metadata or {})
        if self.cloud_sync_ready:
            payload.setdefault("cloud_sync_ready", True)
        if run_id:
            payload.setdefault("run_id", run_id)

        sync_status = "pending" if self.cloud_sync_ready else "local_only"
        cloud_content_id = str(payload.get("cloud_content_id") or "") or None
        last_sync_at = str(payload.get("last_sync_at") or "") or None

        now = _utc_now_iso()

        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO artifacts(
                        artifact_id,
                        content_id,
                        artifact_type,
                        logical_path,
                        physical_path,
                        checksum,
                        size_bytes,
                        schema_version,
                        producer,
                        run_id,
                        sync_status,
                        cloud_content_id,
                        last_sync_at,
                        retention_class,
                        metadata_json,
                        created_at,
                        updated_at,
                        deleted
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                    ON CONFLICT(artifact_id) DO UPDATE SET
                        content_id=excluded.content_id,
                        artifact_type=excluded.artifact_type,
                        logical_path=excluded.logical_path,
                        physical_path=excluded.physical_path,
                        checksum=excluded.checksum,
                        size_bytes=excluded.size_bytes,
                        schema_version=excluded.schema_version,
                        producer=excluded.producer,
                        run_id=excluded.run_id,
                        sync_status=excluded.sync_status,
                        cloud_content_id=excluded.cloud_content_id,
                        last_sync_at=excluded.last_sync_at,
                        retention_class=excluded.retention_class,
                        metadata_json=excluded.metadata_json,
                        updated_at=excluded.updated_at,
                        deleted=0
                    """,
                    (
                        artifact_id,
                        content_id,
                        artifact_type,
                        logical_path,
                        physical_path,
                        checksum,
                        size_bytes,
                        resolved_schema_version,
                        producer,
                        run_id or None,
                        sync_status,
                        cloud_content_id,
                        last_sync_at,
                        retention_class,
                        _json_dumps(payload),
                        now,
                        now,
                    ),
                )
                if content_id:
                    conn.execute(
                        """
                        INSERT INTO content_blobs(
                            content_id,
                            checksum,
                            size_bytes,
                            first_seen_at,
                            last_seen_at,
                            ref_count
                        ) VALUES (?, ?, ?, ?, ?, 1)
                        ON CONFLICT(content_id) DO UPDATE SET
                            checksum=excluded.checksum,
                            size_bytes=excluded.size_bytes,
                            last_seen_at=excluded.last_seen_at
                        """,
                        (
                            content_id,
                            checksum,
                            size_bytes,
                            now,
                            now,
                        ),
                    )
                conn.commit()
            return True
        except sqlite3.Error as exc:
            LOGGER.warning(
                "artifact_registration_failed",
                artifact_type=artifact_type,
                artifact_path=str(path),
                error=str(exc),
            )
            return False

    def backfill_from_disk(
        self,
        *,
        producer: str = "storage.backfill",
        run_id: str = "",
    ) -> dict[str, Any]:
        """Register existing durable .ctn files without rewriting payload files."""
        summary = {
            "enabled": bool(self.enabled and self._ready),
            "scanned": 0,
            "registered": 0,
            "failed": 0,
        }
        if not self.enabled or not self._ready:
            return summary

        for artifact_path in self.scan_durable_files():
            summary["scanned"] += 1
            descriptor = describe_artifact(artifact_path, self.ctn_dir)
            ok = self.register_file(
                artifact_path,
                descriptor.artifact_type,
                producer=producer,
                metadata={"backfilled": True},
                schema_version=descriptor.schema_version,
                retention_class=descriptor.retention_class,
                run_id=run_id,
            )
            if ok:
                summary["registered"] += 1
            else:
                summary["failed"] += 1

        return summary

    def stats(self) -> dict[str, Any]:
        """Return storage registry and cloud-sync readiness statistics."""
        summary = {
            "enabled": bool(self.enabled and self._ready),
            "registry_path": str(self.registry_path),
            "backend": self.backend,
            "content_scope": self.content_scope,
            "cloud_sync_ready": self.cloud_sync_ready,
            "artifact_count": 0,
            "deleted_artifact_count": 0,
            "content_blob_count": 0,
            "query_entities_count": 0,
            "query_relationships_count": 0,
            "sync_status": {
                "pending": 0,
                "synced": 0,
                "conflict": 0,
                "local_only": 0,
            },
            "artifact_types": {},
            "db_size_bytes": 0,
        }
        if not self.enabled or not self._ready:
            return summary

        try:
            summary["db_size_bytes"] = int(self.registry_path.stat().st_size)
        except OSError:
            summary["db_size_bytes"] = 0

        with self._connect(row_factory=True) as conn:
            artifact_count = conn.execute(
                "SELECT COUNT(*) AS count FROM artifacts WHERE deleted = 0"
            ).fetchone()
            deleted_count = conn.execute(
                "SELECT COUNT(*) AS count FROM artifacts WHERE deleted = 1"
            ).fetchone()
            blob_count = conn.execute(
                "SELECT COUNT(*) AS count FROM content_blobs"
            ).fetchone()
            entity_count = conn.execute(
                "SELECT COUNT(*) AS count FROM query_entities"
            ).fetchone()
            relationship_count = conn.execute(
                "SELECT COUNT(*) AS count FROM query_relationships"
            ).fetchone()

            summary["artifact_count"] = int(artifact_count["count"] if artifact_count else 0)
            summary["deleted_artifact_count"] = int(deleted_count["count"] if deleted_count else 0)
            summary["content_blob_count"] = int(blob_count["count"] if blob_count else 0)
            summary["query_entities_count"] = int(entity_count["count"] if entity_count else 0)
            summary["query_relationships_count"] = int(
                relationship_count["count"] if relationship_count else 0
            )

            type_rows = conn.execute(
                """
                SELECT artifact_type, COUNT(*) AS count
                FROM artifacts
                WHERE deleted = 0
                GROUP BY artifact_type
                ORDER BY count DESC, artifact_type ASC
                """
            ).fetchall()
            summary["artifact_types"] = {
                str(row["artifact_type"]): int(row["count"])
                for row in type_rows
            }

            sync_rows = conn.execute(
                """
                SELECT COALESCE(sync_status, 'local_only') AS sync_status, COUNT(*) AS count
                FROM artifacts
                WHERE deleted = 0
                GROUP BY COALESCE(sync_status, 'local_only')
                """
            ).fetchall()
            sync_status = dict(summary["sync_status"])
            for row in sync_rows:
                key = str(row["sync_status"])
                sync_status[key] = int(row["count"])
            summary["sync_status"] = sync_status

        return summary

    def mark_synced(
        self,
        artifact_id: str,
        *,
        cloud_content_id: str,
        synced_at: str | None = None,
    ) -> bool:
        """Mark an artifact as synced for future cloud replication flows."""
        if not self.enabled or not self._ready:
            return False

        timestamp = synced_at or _utc_now_iso()
        with self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE artifacts
                SET sync_status = ?, cloud_content_id = ?, last_sync_at = ?, updated_at = ?
                WHERE artifact_id = ? AND deleted = 0
                """,
                ("synced", cloud_content_id, timestamp, timestamp, artifact_id),
            )
            conn.commit()
            return int(cur.rowcount) > 0

    def _active_artifacts(self) -> list[dict[str, Any]]:
        if not self.enabled or not self._ready:
            return []

        with self._connect(row_factory=True) as conn:
            rows = conn.execute(
                """
                SELECT
                    artifact_id,
                    artifact_type,
                    logical_path,
                    physical_path,
                    schema_version,
                    retention_class,
                    updated_at,
                    deleted
                FROM artifacts
                WHERE deleted = 0
                """
            ).fetchall()

        return [dict(row) for row in rows]

    def _mark_deleted(self, artifact_id: str) -> bool:
        if not self.enabled or not self._ready:
            return False

        now = _utc_now_iso()
        with self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE artifacts
                SET deleted = 1, updated_at = ?
                WHERE artifact_id = ? AND deleted = 0
                """,
                (now, artifact_id),
            )
            conn.commit()
            return int(cur.rowcount) > 0

    def verify(self, *, repair: bool = False, run_id: str = "") -> dict[str, Any]:
        """Verify registry consistency and optionally repair metadata drift."""
        report = {
            "enabled": bool(self.enabled and self._ready),
            "repair": repair,
            "scanned_durable": 0,
            "registered_active": 0,
            "missing_on_disk": 0,
            "unregistered_on_disk": 0,
            "repaired_registered": 0,
            "repaired_deleted": 0,
        }
        if not self.enabled or not self._ready:
            return report

        active_rows = self._active_artifacts()
        registered_paths = {str(Path(str(row["physical_path"])).resolve()) for row in active_rows}
        durable_paths = {str(path.resolve()) for path in self.scan_durable_files()}

        missing_rows = [
            row
            for row in active_rows
            if not Path(str(row["physical_path"])).exists()
        ]
        unregistered_paths = sorted(path for path in durable_paths if path not in registered_paths)

        report["scanned_durable"] = len(durable_paths)
        report["registered_active"] = len(active_rows)
        report["missing_on_disk"] = len(missing_rows)
        report["unregistered_on_disk"] = len(unregistered_paths)

        if not repair:
            return report

        for path_str in unregistered_paths:
            path = Path(path_str)
            descriptor = describe_artifact(path, self.ctn_dir)
            if self.register_file(
                path,
                descriptor.artifact_type,
                producer="storage.verify",
                metadata={"repaired": True},
                schema_version=descriptor.schema_version,
                retention_class=descriptor.retention_class,
                run_id=run_id,
            ):
                report["repaired_registered"] += 1

        for row in missing_rows:
            if self._mark_deleted(str(row["artifact_id"])):
                report["repaired_deleted"] += 1

        return report

    def _retention_limits(self) -> dict[str, Any]:
        retention_enabled = bool(self.retention_cfg.get("enabled", True))
        return {
            "enabled": retention_enabled,
            "snapshot_ttl_days": int(self.retention_cfg.get("snapshot_ttl_days", 90)),
            "patch_ttl_days": int(self.retention_cfg.get("patch_ttl_days", 90)),
            "metrics_ttl_days": int(self.retention_cfg.get("metrics_ttl_days", 30)),
            "context_ttl_days": int(self.retention_cfg.get("context_ttl_days", 90)),
            "max_snapshots": int(self.retention_cfg.get("max_snapshots", 500)),
            "max_patches": int(self.retention_cfg.get("max_patches", 5000)),
        }

    def cleanup(self, *, dry_run: bool = True) -> dict[str, Any]:
        """Apply retention policy to metadata and files under .ctn."""
        summary = {
            "enabled": bool(self.enabled and self._ready),
            "dry_run": dry_run,
            "retention_enabled": False,
            "candidates": 0,
            "deleted_metadata": 0,
            "deleted_files": 0,
            "errors": [],
        }
        if not self.enabled or not self._ready:
            return summary

        limits = self._retention_limits()
        summary["retention_enabled"] = bool(limits["enabled"])
        if not limits["enabled"]:
            return summary

        rows = self._active_artifacts()
        now = datetime.now(timezone.utc)

        ttl_by_class: dict[str, int] = {
            "snapshot": int(limits["snapshot_ttl_days"]),
            "patch": int(limits["patch_ttl_days"]),
            "metrics": int(limits["metrics_ttl_days"]),
            "context": int(limits["context_ttl_days"]),
        }

        candidates: dict[str, dict[str, Any]] = {}

        for row in rows:
            retention_class = str(row.get("retention_class") or _DEFAULT_RETENTION_CLASS)
            ttl_days = ttl_by_class.get(retention_class)
            if not ttl_days:
                continue
            updated_at = _safe_parse_iso(str(row.get("updated_at") or ""))
            if updated_at is None:
                continue
            if updated_at < (now - timedelta(days=ttl_days)):
                candidates[str(row["artifact_id"])] = row

        for retention_class, max_count in (
            ("snapshot", int(limits["max_snapshots"])),
            ("patch", int(limits["max_patches"])),
        ):
            class_rows = [
                row
                for row in rows
                if str(row.get("retention_class") or "") == retention_class
            ]
            class_rows.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
            for row in class_rows[max_count:]:
                candidates[str(row["artifact_id"])] = row

        candidate_rows = list(candidates.values())
        summary["candidates"] = len(candidate_rows)

        if dry_run:
            summary["candidate_paths"] = [str(row.get("logical_path") or "") for row in candidate_rows]
            return summary

        for row in candidate_rows:
            artifact_id = str(row.get("artifact_id") or "")
            physical_path = Path(str(row.get("physical_path") or ""))

            if physical_path.exists():
                try:
                    if _is_under(physical_path, self.ctn_dir) and self._is_durable_artifact(physical_path):
                        physical_path.unlink()
                        summary["deleted_files"] += 1
                except OSError as exc:
                    summary["errors"].append(
                        {
                            "artifact_id": artifact_id,
                            "path": str(physical_path),
                            "error": str(exc),
                        }
                    )

            if artifact_id and self._mark_deleted(artifact_id):
                summary["deleted_metadata"] += 1

        return summary

    def rebuild_query_indexes(
        self,
        index_id: str,
        graph_payload: dict[str, Any],
    ) -> dict[str, int]:
        """Build persisted query indexes for common graph lookups."""
        if not self.enabled or not self._ready:
            return {"entities_indexed": 0, "relationships_indexed": 0}

        entity_rows: list[tuple[str, str, str, str, str, str | None, str]] = []

        entities_by_id = graph_payload.get("entities_by_id")
        if isinstance(entities_by_id, dict):
            for key, raw in entities_by_id.items():
                if not isinstance(raw, dict):
                    continue
                entity_id = str(raw.get("id") or key)
                entity_type = str(raw.get("type") or "unknown").lower()
                file_path = str(raw.get("file") or "")
                name = str(raw.get("name") or "")
                signature_value = raw.get("signature")
                signature = str(signature_value) if signature_value is not None else None
                metadata_value = raw.get("metadata")
                metadata = metadata_value if isinstance(metadata_value, dict) else {}
                entity_rows.append(
                    (
                        index_id,
                        entity_id,
                        entity_type,
                        file_path,
                        name,
                        signature,
                        _json_dumps(metadata),
                    )
                )
        elif isinstance(graph_payload.get("entities"), list):
            for raw in graph_payload.get("entities", []):
                if not isinstance(raw, dict):
                    continue
                entity_id = str(raw.get("id") or "")
                if not entity_id:
                    continue
                entity_type = str(raw.get("type") or "unknown").lower()
                file_path = str(raw.get("file") or "")
                name = str(raw.get("name") or "")
                signature_value = raw.get("signature")
                signature = str(signature_value) if signature_value is not None else None
                metadata_value = raw.get("metadata")
                metadata = metadata_value if isinstance(metadata_value, dict) else {}
                entity_rows.append(
                    (
                        index_id,
                        entity_id,
                        entity_type,
                        file_path,
                        name,
                        signature,
                        _json_dumps(metadata),
                    )
                )

        relationship_rows: list[tuple[str, str, str, str, str, str]] = []
        for raw in graph_payload.get("relationships", []):
            if not isinstance(raw, dict):
                continue
            source_id = str(raw.get("source_id") or "")
            target_id = str(raw.get("target_id") or "")
            relationship_type = str(raw.get("type") or "unknown").lower()
            relationship_id = str(raw.get("id") or "")
            if not relationship_id:
                relationship_id = hashlib.sha256(
                    f"{source_id}:{target_id}:{relationship_type}".encode("utf-8")
                ).hexdigest()
            metadata_value = raw.get("metadata")
            metadata = metadata_value if isinstance(metadata_value, dict) else {}
            relationship_rows.append(
                (
                    index_id,
                    relationship_id,
                    relationship_type,
                    source_id,
                    target_id,
                    _json_dumps(metadata),
                )
            )

        try:
            with self._connect() as conn:
                conn.execute("DELETE FROM query_entities WHERE index_id = ?", (index_id,))
                conn.execute("DELETE FROM query_relationships WHERE index_id = ?", (index_id,))
                if entity_rows:
                    conn.executemany(
                        """
                        INSERT INTO query_entities(
                            index_id,
                            entity_id,
                            entity_type,
                            file_path,
                            name,
                            signature,
                            metadata_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        entity_rows,
                    )
                if relationship_rows:
                    conn.executemany(
                        """
                        INSERT INTO query_relationships(
                            index_id,
                            relationship_id,
                            relationship_type,
                            source_id,
                            target_id,
                            metadata_json
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        relationship_rows,
                    )
                conn.commit()
        except sqlite3.Error as exc:
            LOGGER.warning(
                "query_index_rebuild_failed",
                index_id=index_id,
                error=str(exc),
            )
            return {"entities_indexed": 0, "relationships_indexed": 0}

        return {
            "entities_indexed": len(entity_rows),
            "relationships_indexed": len(relationship_rows),
        }

    def query_entities(
        self,
        *,
        index_id: str,
        entity_type: str | None = None,
        file_path: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        if not self.enabled or not self._ready:
            return []

        clauses = ["index_id = ?"]
        params: list[Any] = [index_id]

        if entity_type:
            clauses.append("entity_type = ?")
            params.append(entity_type.strip().lower())

        if file_path:
            clauses.append("file_path = ?")
            params.append(file_path)

        query = (
            "SELECT entity_id, entity_type, file_path, name, signature, metadata_json "
            "FROM query_entities "
            f"WHERE {' AND '.join(clauses)} "
            "ORDER BY name ASC "
            "LIMIT ?"
        )
        params.append(max(1, int(limit)))

        with self._connect(row_factory=True) as conn:
            rows = conn.execute(query, tuple(params)).fetchall()

        result: list[dict[str, Any]] = []
        for row in rows:
            metadata_raw = str(row["metadata_json"] or "{}")
            try:
                metadata = json.loads(metadata_raw)
            except json.JSONDecodeError:
                metadata = {}
            result.append(
                {
                    "entity_id": str(row["entity_id"]),
                    "entity_type": str(row["entity_type"]),
                    "file_path": str(row["file_path"]),
                    "name": str(row["name"]),
                    "signature": row["signature"],
                    "metadata": metadata,
                }
            )
        return result

    def query_relationships(
        self,
        *,
        index_id: str,
        relationship_type: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        if not self.enabled or not self._ready:
            return []

        clauses = ["index_id = ?"]
        params: list[Any] = [index_id]

        if relationship_type:
            clauses.append("relationship_type = ?")
            params.append(relationship_type.strip().lower())

        query = (
            "SELECT relationship_id, relationship_type, source_id, target_id, metadata_json "
            "FROM query_relationships "
            f"WHERE {' AND '.join(clauses)} "
            "ORDER BY relationship_type ASC, relationship_id ASC "
            "LIMIT ?"
        )
        params.append(max(1, int(limit)))

        with self._connect(row_factory=True) as conn:
            rows = conn.execute(query, tuple(params)).fetchall()

        result: list[dict[str, Any]] = []
        for row in rows:
            metadata_raw = str(row["metadata_json"] or "{}")
            try:
                metadata = json.loads(metadata_raw)
            except json.JSONDecodeError:
                metadata = {}
            result.append(
                {
                    "relationship_id": str(row["relationship_id"]),
                    "relationship_type": str(row["relationship_type"]),
                    "source_id": str(row["source_id"]),
                    "target_id": str(row["target_id"]),
                    "metadata": metadata,
                }
            )
        return result


def get_artifact_registry(ctn_dir: Path) -> ArtifactRegistry:
    key = str(ctn_dir.resolve())
    with _REGISTRY_CACHE_LOCK:
        existing = _REGISTRY_CACHE.get(key)
        if existing is not None:
            return existing
        registry = ArtifactRegistry(ctn_dir)
        _REGISTRY_CACHE[key] = registry
        return registry


def register_artifact(
    ctn_dir: Path,
    artifact_path: Path,
    artifact_type: str,
    *,
    producer: str = "unknown",
    metadata: dict[str, Any] | None = None,
    schema_version: str = "",
    retention_class: str = _DEFAULT_RETENTION_CLASS,
    run_id: str = "",
) -> bool:
    """Register a durable artifact emitted under ctn_dir."""
    registry = get_artifact_registry(ctn_dir)
    return registry.register_file(
        artifact_path=artifact_path,
        artifact_type=artifact_type,
        producer=producer,
        metadata=metadata,
        schema_version=schema_version,
        retention_class=retention_class,
        run_id=run_id,
    )


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
    """Register an artifact by inferring ctn_dir from the provided path."""
    inferred_ctn = infer_ctn_dir_for_path(artifact_path)
    if inferred_ctn is None:
        return False

    return register_artifact(
        ctn_dir=inferred_ctn,
        artifact_path=artifact_path,
        artifact_type=artifact_type,
        producer=producer,
        metadata=metadata,
        schema_version=schema_version,
        retention_class=retention_class,
        run_id=run_id,
    )


def backfill_registry(
    ctn_dir: Path,
    *,
    producer: str = "storage.backfill",
    run_id: str = "",
) -> dict[str, Any]:
    registry = get_artifact_registry(ctn_dir)
    return registry.backfill_from_disk(producer=producer, run_id=run_id)


def verify_registry(
    ctn_dir: Path,
    *,
    repair: bool = False,
    run_id: str = "",
) -> dict[str, Any]:
    registry = get_artifact_registry(ctn_dir)
    return registry.verify(repair=repair, run_id=run_id)


def cleanup_registry(
    ctn_dir: Path,
    *,
    dry_run: bool = True,
) -> dict[str, Any]:
    registry = get_artifact_registry(ctn_dir)
    return registry.cleanup(dry_run=dry_run)


def get_registry_stats(ctn_dir: Path) -> dict[str, Any]:
    registry = get_artifact_registry(ctn_dir)
    return registry.stats()


def rebuild_query_index(
    ctn_dir: Path,
    index_id: str,
    graph_payload: dict[str, Any],
) -> dict[str, int]:
    registry = get_artifact_registry(ctn_dir)
    return registry.rebuild_query_indexes(index_id=index_id, graph_payload=graph_payload)


def query_entities(
    ctn_dir: Path,
    *,
    index_id: str,
    entity_type: str | None = None,
    file_path: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    registry = get_artifact_registry(ctn_dir)
    return registry.query_entities(
        index_id=index_id,
        entity_type=entity_type,
        file_path=file_path,
        limit=limit,
    )


def query_relationships(
    ctn_dir: Path,
    *,
    index_id: str,
    relationship_type: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    registry = get_artifact_registry(ctn_dir)
    return registry.query_relationships(
        index_id=index_id,
        relationship_type=relationship_type,
        limit=limit,
    )


def persist_json(
    ctn_dir: Path,
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
    write_atomically(path, payload, is_json=True)
    if not path.exists():
        return False
    return register_artifact(
        ctn_dir,
        path,
        artifact_type,
        producer=producer,
        metadata=metadata,
        schema_version=schema_version,
        retention_class=retention_class,
        run_id=run_id,
    )


def persist_text(
    ctn_dir: Path,
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
    write_atomically(path, content)
    if not path.exists():
        return False
    return register_artifact(
        ctn_dir,
        path,
        artifact_type,
        producer=producer,
        metadata=metadata,
        schema_version=schema_version,
        retention_class=retention_class,
        run_id=run_id,
    )


def persist_bytes(
    ctn_dir: Path,
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
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_bytes(content)
    tmp_path.replace(path)

    return register_artifact(
        ctn_dir,
        path,
        artifact_type,
        producer=producer,
        metadata=metadata,
        schema_version=schema_version,
        retention_class=retention_class,
        run_id=run_id,
    )
