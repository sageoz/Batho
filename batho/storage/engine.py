"""batho/storage/engine.py — Unified SQLite persistence engine.

Per-directory `artifact_<dirname>.batho` database that replaces the legacy `.ctn` directory.
All graph data, BSG payloads, context outputs, snapshots, and sync metadata
live in one ACID-compliant SQLite database per project.

Usage:
    from batho.storage import get_database

    db = get_database(repo_root)
    with db.connection() as conn:
        conn.execute("SELECT ...")
"""

from __future__ import annotations

import hashlib
import importlib.resources
import json
import re
import sqlite3
import sys
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from batho.utils.logging import get_logger

LOGGER = get_logger(__name__, component="storage_engine")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BATHO_DB_FILENAME = ".batho"  # Legacy constant, use artifact_filename() instead
BATHO_CONFIG_DIR = ".batho-config"
SCHEMA_VERSION = "batho-db.v1"
DEFAULT_PAGE_SIZE = 8192
DEFAULT_BUSY_TIMEOUT_MS = 5000

# Module-level cache
_DB_CACHE: dict[str, "BathoDatabase"] = {}
_DB_CACHE_LOCK = threading.Lock()


def artifact_filename(root: Path) -> str:
    """Generate the artifact database filename for a repo root."""
    dirname = root.resolve().name
    sanitized = re.sub(r'[^a-z0-9_-]', '-', dirname.lower())
    sanitized = re.sub(r'-+', '-', sanitized).strip('-')
    if not sanitized or sanitized == 'default':
        path_hash = hashlib.sha256(str(root.resolve()).encode()).hexdigest()[:8]
        sanitized = f"default-{path_hash}"
    return f"artifact_{sanitized}.batho"


# ---------------------------------------------------------------------------
# Schema loader
# ---------------------------------------------------------------------------


def _load_schema_sql() -> str:
    """Load the schema SQL from the package resource."""
    schema_path = Path(__file__).parent / "schema.sql"
    return schema_path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_database(repo_root: Path | str, *, db_path: Path | str | None = None) -> "BathoDatabase":
    """Get or create a BathoDatabase instance for a repository.

    Args:
        repo_root: Path to the repository root.
        db_path: Optional override for the .batho file location.
                 If None, defaults to <repo_root>/artifact_<dirname>.batho.

    Returns:
        A cached BathoDatabase instance.
    """
    root = Path(repo_root).resolve()
    if db_path is not None:
        resolved_path = Path(db_path).resolve()
    else:
        resolved_path = root / artifact_filename(root)

    key = str(resolved_path)
    with _DB_CACHE_LOCK:
        existing = _DB_CACHE.get(key)
        if existing is not None and not getattr(existing, "_closed", False):
            return existing
        db = BathoDatabase(resolved_path, repo_root=root)
        _DB_CACHE[key] = db
        return db


def close_all_databases() -> None:
    """Close all cached database instances. Call on shutdown."""
    with _DB_CACHE_LOCK:
        for db in _DB_CACHE.values():
            db.close()
        _DB_CACHE.clear()


# ---------------------------------------------------------------------------
# BathoDatabase
# ---------------------------------------------------------------------------


class BathoDatabase:
    """Unified SQLite persistence engine for a single Batho project.

    Thread-safe. Uses WAL mode for concurrent read/write access.
    All tables are created on first open via schema.sql.
    """

    def __init__(self, db_path: Path, *, repo_root: Path | None = None) -> None:
        self._db_path = db_path.resolve()
        self._repo_root = (repo_root or db_path.parent).resolve()
        self._lock = threading.RLock()
        self._local = threading.local()
        self._closed = False
        self._initialized = False
        self._initialize()

    @property
    def path(self) -> Path:
        """Absolute path to the .batho database file."""
        return self._db_path

    @property
    def repo_root(self) -> Path:
        """Absolute path to the repository root."""
        return self._repo_root

    @property
    def exists(self) -> bool:
        """Whether the database file currently exists on disk."""
        return self._db_path.exists()

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def _get_connection(self) -> sqlite3.Connection:
        """Return (or create) a per-thread SQLite connection."""
        if self._closed:
            raise RuntimeError("BathoDatabase is closed")

        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(
                str(self._db_path),
                check_same_thread=False,
                timeout=30.0,
            )
            conn.row_factory = sqlite3.Row
            self._apply_pragmas(conn)
            self._local.conn = conn
        return self._local.conn

    def _apply_pragmas(self, conn: sqlite3.Connection) -> None:
        """Apply performance and durability pragmas."""
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA temp_store = MEMORY")
        conn.execute(f"PRAGMA busy_timeout = {DEFAULT_BUSY_TIMEOUT_MS}")
        conn.execute(f"PRAGMA cache_size = -8000")  # 8 MiB

        # WAL mode: set once, persists across connections
        current_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        if current_mode.lower() != "wal":
            if sys.platform == "win32":
                conn.execute("PRAGMA journal_mode = DELETE")
            else:
                conn.execute("PRAGMA journal_mode = WAL")

        conn.execute("PRAGMA synchronous = FULL")

    @contextmanager
    def connection(self, *, read_only: bool = False) -> Iterator[sqlite3.Connection]:
        """Acquire a database connection from the per-thread pool.

        Args:
            read_only: Hint that this connection will only SELECT.
                       Currently informational; may optimize in future.

        Yields:
            An open sqlite3.Connection with Row factory.
        """
        conn = self._get_connection()
        try:
            yield conn
        except Exception:
            conn.rollback()
            raise

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Context manager for an explicit transaction with auto-commit/rollback.

        Yields:
            An open sqlite3.Connection inside a BEGIN...COMMIT block.
        """
        conn = self._get_connection()
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    def _initialize(self) -> None:
        """Create schema tables if this is a fresh database."""
        if self._initialized:
            return

        try:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)

            # Set page size BEFORE any tables are created (must be on empty DB)
            if not self._db_path.exists():
                conn = sqlite3.connect(str(self._db_path), timeout=5)
                conn.execute(f"PRAGMA page_size = {DEFAULT_PAGE_SIZE}")
                conn.execute("PRAGMA auto_vacuum = INCREMENTAL")
                conn.close()

            conn = self._get_connection()
            schema_sql = _load_schema_sql()
            conn.executescript(schema_sql)

            # Seed metadata
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "INSERT OR IGNORE INTO db_meta(key, value, updated_at) VALUES (?, ?, ?)",
                ("schema_version", SCHEMA_VERSION, now),
            )
            conn.execute(
                "INSERT OR IGNORE INTO db_meta(key, value, updated_at) VALUES (?, ?, ?)",
                ("created_at", now, now),
            )
            conn.execute(
                "INSERT OR IGNORE INTO db_meta(key, value, updated_at) VALUES (?, ?, ?)",
                ("repo_root", str(self._repo_root), now),
            )
            conn.commit()
            self._initialized = True
            LOGGER.info(
                "database_initialized",
                path=str(self._db_path),
                schema_version=SCHEMA_VERSION,
            )
        except sqlite3.Error as exc:
            LOGGER.error(
                "database_init_failed",
                path=str(self._db_path),
                error=str(exc),
            )
            raise

    # ------------------------------------------------------------------
    # Metadata
    # ------------------------------------------------------------------

    def get_meta(self, key: str) -> str | None:
        """Get a value from db_meta."""
        with self.connection(read_only=True) as conn:
            row = conn.execute(
                "SELECT value FROM db_meta WHERE key = ?", (key,)
            ).fetchone()
            return row["value"] if row else None

    def set_meta(self, key: str, value: str) -> None:
        """Set a value in db_meta."""
        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO db_meta(key, value, updated_at) VALUES (?, ?, ?)",
                (key, value, now),
            )
            conn.commit()

    # ------------------------------------------------------------------
    # Index Runs
    # ------------------------------------------------------------------

    def create_run(
        self,
        run_id: str,
        *,
        schema_version: str = "",
        root_path: str = "",
        git_commit: str | None = None,
        git_branch: str | None = None,
        config_hash: str | None = None,
    ) -> None:
        """Register a new index run."""
        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            conn.execute(
                """INSERT INTO index_runs(
                    run_id, schema_version, started_at, status,
                    git_commit, git_branch, root_path, config_hash
                ) VALUES (?, ?, ?, 'running', ?, ?, ?, ?)""",
                (
                    run_id,
                    schema_version or SCHEMA_VERSION,
                    now,
                    git_commit,
                    git_branch,
                    root_path or str(self._repo_root),
                    config_hash,
                ),
            )
            conn.commit()

    def complete_run(
        self,
        run_id: str,
        *,
        entity_count: int = 0,
        rel_count: int = 0,
        file_count: int = 0,
        duration_ms: int | None = None,
    ) -> None:
        """Mark a run as completed with final stats."""
        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            conn.execute(
                """UPDATE index_runs SET
                    status = 'completed',
                    completed_at = ?,
                    entity_count = ?,
                    rel_count = ?,
                    file_count = ?,
                    duration_ms = ?
                WHERE run_id = ?""",
                (now, entity_count, rel_count, file_count, duration_ms, run_id),
            )
            conn.commit()

    def fail_run(self, run_id: str, *, error_message: str = "") -> None:
        """Mark a run as failed."""
        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            conn.execute(
                """UPDATE index_runs SET
                    status = 'failed',
                    completed_at = ?,
                    error_message = ?
                WHERE run_id = ?""",
                (now, error_message, run_id),
            )
            conn.commit()

    def get_latest_run_id(self) -> str | None:
        """Get the run_id of the most recent completed run."""
        with self.connection(read_only=True) as conn:
            row = conn.execute(
                """SELECT run_id FROM index_runs
                WHERE status = 'completed'
                ORDER BY completed_at DESC LIMIT 1"""
            ).fetchone()
            return row["run_id"] if row else None

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        """Get full run metadata."""
        with self.connection(read_only=True) as conn:
            row = conn.execute(
                "SELECT * FROM index_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            if row is None:
                return None
            return dict(row)

    def delete_run(self, run_id: str) -> None:
        """Delete a run and all cascaded data (entities, rels, BSG, context)."""
        with self.connection() as conn:
            conn.execute("DELETE FROM index_runs WHERE run_id = ?", (run_id,))
            conn.commit()

    # ------------------------------------------------------------------
    # Graph Entities (bulk operations)
    # ------------------------------------------------------------------

    def insert_entities(self, run_id: str, entities: list[dict[str, Any]]) -> int:
        """Bulk insert graph entities for a run.

        Args:
            run_id: The index run these entities belong to.
            entities: List of entity dicts with keys matching Entity.to_dict().

        Returns:
            Number of entities inserted.
        """
        if not entities:
            return 0

        with self.transaction() as conn:
            conn.executemany(
                """INSERT OR REPLACE INTO graph_entities(
                    run_id, entity_id, entity_type, name, file_path,
                    start_line, end_line, start_byte, end_byte,
                    signature, parent_id, content_hash, ast_node_type, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        run_id,
                        e["id"],
                        e["type"],
                        e["name"],
                        e["file"],
                        e["start_line"],
                        e["end_line"],
                        e.get("start_byte", 0),
                        e.get("end_byte", 0),
                        e.get("signature"),
                        e.get("parent_id"),
                        e.get("content_hash", ""),
                        e.get("ast_node_type"),
                        json.dumps(e.get("metadata", {}), ensure_ascii=True),
                    )
                    for e in entities
                ],
            )
        return len(entities)

    def insert_relationships(self, run_id: str, relationships: list[dict[str, Any]]) -> int:
        """Bulk insert graph relationships for a run.

        Args:
            run_id: The index run these relationships belong to.
            relationships: List of relationship dicts with keys matching Relationship.to_dict().

        Returns:
            Number of relationships inserted.
        """
        if not relationships:
            return 0

        with self.transaction() as conn:
            conn.executemany(
                """INSERT OR REPLACE INTO graph_relationships(
                    run_id, relationship_id, relationship_type,
                    source_id, target_id, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?)""",
                [
                    (
                        run_id,
                        r["id"],
                        r["type"],
                        r["source_id"],
                        r["target_id"],
                        json.dumps(r.get("metadata", {}), ensure_ascii=True),
                    )
                    for r in relationships
                ],
            )
        return len(relationships)

    # ------------------------------------------------------------------
    # Graph Queries
    # ------------------------------------------------------------------

    def query_entities(
        self,
        run_id: str,
        *,
        file_path: str | None = None,
        entity_type: str | None = None,
        name: str | None = None,
        parent_id: str | None = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        """Query graph entities with optional filters."""
        conditions = ["run_id = ?"]
        params: list[Any] = [run_id]

        if file_path is not None:
            conditions.append("file_path = ?")
            params.append(file_path)
        if entity_type is not None:
            conditions.append("entity_type = ?")
            params.append(entity_type)
        if name is not None:
            conditions.append("name = ?")
            params.append(name)
        if parent_id is not None:
            conditions.append("parent_id = ?")
            params.append(parent_id)

        params.append(limit)
        where = " AND ".join(conditions)

        with self.connection(read_only=True) as conn:
            rows = conn.execute(
                f"SELECT * FROM graph_entities WHERE {where} LIMIT ?",
                params,
            ).fetchall()
            return [dict(row) for row in rows]

    def query_relationships(
        self,
        run_id: str,
        *,
        source_id: str | None = None,
        target_id: str | None = None,
        relationship_type: str | None = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        """Query graph relationships with optional filters."""
        conditions = ["run_id = ?"]
        params: list[Any] = [run_id]

        if source_id is not None:
            conditions.append("source_id = ?")
            params.append(source_id)
        if target_id is not None:
            conditions.append("target_id = ?")
            params.append(target_id)
        if relationship_type is not None:
            conditions.append("relationship_type = ?")
            params.append(relationship_type)

        params.append(limit)
        where = " AND ".join(conditions)

        with self.connection(read_only=True) as conn:
            rows = conn.execute(
                f"SELECT * FROM graph_relationships WHERE {where} LIMIT ?",
                params,
            ).fetchall()
            return [dict(row) for row in rows]

    def get_entity_count(self, run_id: str) -> int:
        """Get total entity count for a run."""
        with self.connection(read_only=True) as conn:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM graph_entities WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            return row["cnt"] if row else 0

    def get_relationship_count(self, run_id: str) -> int:
        """Get total relationship count for a run."""
        with self.connection(read_only=True) as conn:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM graph_relationships WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            return row["cnt"] if row else 0

    # ------------------------------------------------------------------
    # BSG Entries
    # ------------------------------------------------------------------

    def insert_bsg_entries(self, run_id: str, entries: list[dict[str, Any]]) -> int:
        """Bulk insert BSG entries for a run.

        Args:
            run_id: The index run.
            entries: List of dicts with keys: file_path, view_type, bsg_json,
                     token_count, node_count, checksum.

        Returns:
            Number of entries inserted.
        """
        if not entries:
            return 0

        with self.transaction() as conn:
            conn.executemany(
                """INSERT OR REPLACE INTO bsg_entries(
                    run_id, file_path, view_type, bsg_json,
                    token_count, node_count, checksum
                ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        run_id,
                        e["file_path"],
                        e.get("view_type", "agent"),
                        e["bsg_json"],
                        e.get("token_count"),
                        e.get("node_count", 0),
                        e["checksum"],
                    )
                    for e in entries
                ],
            )
        return len(entries)

    def get_bsg_entry(
        self, run_id: str, file_path: str, view_type: str = "agent"
    ) -> dict[str, Any] | None:
        """Get a single BSG entry."""
        with self.connection(read_only=True) as conn:
            row = conn.execute(
                """SELECT * FROM bsg_entries
                WHERE run_id = ? AND file_path = ? AND view_type = ?""",
                (run_id, file_path, view_type),
            ).fetchone()
            return dict(row) if row else None

    def get_bsg_entries_for_run(
        self, run_id: str, *, view_type: str = "agent"
    ) -> list[dict[str, Any]]:
        """Get all BSG entries for a run."""
        with self.connection(read_only=True) as conn:
            rows = conn.execute(
                "SELECT * FROM bsg_entries WHERE run_id = ? AND view_type = ?",
                (run_id, view_type),
            ).fetchall()
            return [dict(row) for row in rows]

    # ------------------------------------------------------------------
    # File Tracking
    # ------------------------------------------------------------------

    def upsert_file_tracking(self, records: list[dict[str, Any]]) -> int:
        """Bulk upsert file tracking records.

        Args:
            records: List of dicts with keys: file_path, content_hash, mtime,
                     size, is_indexed, last_run_id.

        Returns:
            Number of records upserted.
        """
        if not records:
            return 0

        now = datetime.now(timezone.utc).isoformat()
        with self.transaction() as conn:
            conn.executemany(
                """INSERT OR REPLACE INTO file_tracking(
                    file_path, content_hash, mtime, size, is_indexed,
                    last_run_id, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        r["file_path"],
                        r["content_hash"],
                        r["mtime"],
                        r["size"],
                        int(r.get("is_indexed", 0)),
                        r.get("last_run_id"),
                        now,
                    )
                    for r in records
                ],
            )
        return len(records)

    def get_file_tracking(self, file_path: str) -> dict[str, Any] | None:
        """Get tracking data for a single file."""
        with self.connection(read_only=True) as conn:
            row = conn.execute(
                "SELECT * FROM file_tracking WHERE file_path = ?", (file_path,)
            ).fetchone()
            return dict(row) if row else None

    def get_all_file_hashes(self) -> dict[str, str]:
        """Get all file_path -> content_hash mappings."""
        with self.connection(read_only=True) as conn:
            rows = conn.execute(
                "SELECT file_path, content_hash FROM file_tracking"
            ).fetchall()
            return {row["file_path"]: row["content_hash"] for row in rows}

    def get_unindexed_files(self) -> dict[str, str]:
        """Get unindexed file_path -> content_hash mappings."""
        with self.connection(read_only=True) as conn:
            rows = conn.execute(
                "SELECT file_path, content_hash FROM file_tracking WHERE is_indexed = 0"
            ).fetchall()
            return {row["file_path"]: row["content_hash"] for row in rows}

    def delete_file_tracking(self, file_path: str) -> None:
        """Remove a file from tracking."""
        with self.connection() as conn:
            conn.execute(
                "DELETE FROM file_tracking WHERE file_path = ?", (file_path,)
            )
            conn.commit()

    # ------------------------------------------------------------------
    # AST Cache
    # ------------------------------------------------------------------

    def get_ast_cache(self, file_hash: str) -> dict[str, Any] | None:
        """Get cached AST data by file content hash."""
        with self.connection(read_only=True) as conn:
            row = conn.execute(
                "SELECT * FROM ast_cache WHERE file_hash = ?", (file_hash,)
            ).fetchone()
            if row is None:
                return None

            # Check TTL
            cached_at = row["cached_at"]
            ttl_days = row["ttl_days"]
            try:
                ts = datetime.fromisoformat(cached_at)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if ts + timedelta(days=ttl_days) < datetime.now(timezone.utc):
                    # Expired — delete and return None
                    conn.execute(
                        "DELETE FROM ast_cache WHERE file_hash = ?", (file_hash,)
                    )
                    conn.commit()
                    return None
            except (ValueError, TypeError):
                pass

            return dict(row)

    def set_ast_cache(
        self,
        file_hash: str,
        file_path: str,
        entities_json: str,
        relationships_json: str | None,
        mtime: float,
        size: int,
        ttl_days: int = 30,
    ) -> None:
        """Cache parsed AST data."""
        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO ast_cache(
                    file_hash, file_path, entities_json, relationships_json,
                    mtime, size, cached_at, ttl_days
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (file_hash, file_path, entities_json, relationships_json, mtime, size, now, ttl_days),
            )
            conn.commit()

    def delete_ast_cache(self, file_hash: str) -> None:
        """Delete a cached AST entry."""
        with self.connection() as conn:
            conn.execute("DELETE FROM ast_cache WHERE file_hash = ?", (file_hash,))
            conn.commit()

    def clear_expired_ast_cache(self) -> int:
        """Remove expired AST cache entries. Returns count deleted."""
        with self.connection() as conn:
            cursor = conn.execute(
                """DELETE FROM ast_cache
                WHERE datetime(cached_at) < datetime('now', '-' || ttl_days || ' days')"""
            )
            conn.commit()
            return cursor.rowcount

    # ------------------------------------------------------------------
    # File Snapshots
    # ------------------------------------------------------------------

    def set_file_snapshot(self, snapshot: dict[str, Any]) -> None:
        """Store a file snapshot for reconstruction."""
        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO file_snapshots(
                    file_path, file_hash, file_size, encoding,
                    entity_ids_json, gap_sections_json,
                    shebang, encoding_declaration, file_level_comments,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    snapshot["file_path"],
                    snapshot["file_hash"],
                    snapshot["file_size"],
                    snapshot.get("encoding", "utf-8"),
                    json.dumps(snapshot.get("entity_ids", []), ensure_ascii=True),
                    json.dumps(snapshot.get("gap_sections", []), ensure_ascii=True),
                    snapshot.get("shebang"),
                    snapshot.get("encoding_declaration"),
                    json.dumps(snapshot.get("file_level_comments", []), ensure_ascii=True),
                    now,
                    now,
                ),
            )
            conn.commit()

    def get_file_snapshot(self, file_path: str) -> dict[str, Any] | None:
        """Get a stored file snapshot."""
        with self.connection(read_only=True) as conn:
            row = conn.execute(
                "SELECT * FROM file_snapshots WHERE file_path = ?", (file_path,)
            ).fetchone()
            return dict(row) if row else None

    def get_all_file_snapshots(self) -> dict[str, dict[str, Any]]:
        """Get all file snapshots."""
        with self.connection(read_only=True) as conn:
            rows = conn.execute("SELECT * FROM file_snapshots").fetchall()
            return {row["file_path"]: dict(row) for row in rows}

    # ------------------------------------------------------------------
    # Snapshots (Time Machine)
    # ------------------------------------------------------------------

    def create_snapshot(self, snapshot: dict[str, Any]) -> None:
        """Insert a new time machine snapshot."""
        with self.connection() as conn:
            conn.execute(
                """INSERT INTO snapshots(
                    snapshot_id, parent_id, created_at, label,
                    git_commit, git_branch, root_path,
                    schema_version, stats_json, checksum
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    snapshot["snapshot_id"],
                    snapshot.get("parent_id"),
                    snapshot["created_at"],
                    snapshot.get("label", ""),
                    snapshot.get("git_commit"),
                    snapshot.get("git_branch"),
                    snapshot["root_path"],
                    snapshot["schema_version"],
                    json.dumps(snapshot.get("stats", {}), ensure_ascii=True),
                    snapshot["checksum"],
                ),
            )
            conn.commit()

    def list_snapshots(self) -> list[dict[str, Any]]:
        """List all snapshots ordered by creation time (newest first)."""
        with self.connection(read_only=True) as conn:
            rows = conn.execute(
                "SELECT * FROM snapshots ORDER BY created_at DESC"
            ).fetchall()
            return [dict(row) for row in rows]

    def get_snapshot(self, snapshot_id: str) -> dict[str, Any] | None:
        """Get a single snapshot by ID."""
        with self.connection(read_only=True) as conn:
            row = conn.execute(
                "SELECT * FROM snapshots WHERE snapshot_id = ?", (snapshot_id,)
            ).fetchone()
            return dict(row) if row else None

    # ------------------------------------------------------------------
    # Context Outputs
    # ------------------------------------------------------------------

    def set_context_output(
        self, run_id: str, output_type: str, content: str
    ) -> None:
        """Store a context output document."""
        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO context_outputs(
                    run_id, output_type, content, size_bytes, produced_at
                ) VALUES (?, ?, ?, ?, ?)""",
                (run_id, output_type, content, len(content.encode("utf-8")), now),
            )
            conn.commit()

    def get_context_output(self, run_id: str, output_type: str) -> str | None:
        """Get a context output document."""
        with self.connection(read_only=True) as conn:
            row = conn.execute(
                "SELECT content FROM context_outputs WHERE run_id = ? AND output_type = ?",
                (run_id, output_type),
            ).fetchone()
            return row["content"] if row else None

    # ------------------------------------------------------------------
    # Artifacts (Cloud Sync)
    # ------------------------------------------------------------------

    def register_artifact(
        self,
        artifact_id: str,
        *,
        artifact_type: str,
        logical_path: str,
        size_bytes: int,
        schema_version: str,
        producer: str,
        checksum: str | None = None,
        content_id: str | None = None,
        run_id: str | None = None,
        sync_status: str = "local_only",
        retention_class: str = "default",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Register an artifact in the sync registry."""
        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO artifacts(
                    artifact_id, content_id, artifact_type, logical_path,
                    checksum, size_bytes, schema_version, producer, run_id,
                    sync_status, retention_class, metadata_json,
                    created_at, updated_at, deleted
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)""",
                (
                    artifact_id,
                    content_id,
                    artifact_type,
                    logical_path,
                    checksum,
                    size_bytes,
                    schema_version,
                    producer,
                    run_id,
                    sync_status,
                    retention_class,
                    json.dumps(metadata or {}, ensure_ascii=True),
                    now,
                    now,
                ),
            )
            conn.commit()

    def get_pending_artifacts(
        self, *, artifact_types: list[str] | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Get artifacts pending cloud sync."""
        if artifact_types:
            placeholders = ",".join("?" * len(artifact_types))
            sql = f"""SELECT * FROM artifacts
                WHERE deleted = 0 AND sync_status = 'pending'
                AND artifact_type IN ({placeholders})
                ORDER BY updated_at DESC LIMIT ?"""
            params = artifact_types + [limit]
        else:
            sql = """SELECT * FROM artifacts
                WHERE deleted = 0 AND sync_status = 'pending'
                ORDER BY updated_at DESC LIMIT ?"""
            params = [limit]

        with self.connection(read_only=True) as conn:
            rows = conn.execute(sql, params).fetchall()
            return [dict(row) for row in rows]

    def mark_artifact_synced(
        self, artifact_id: str, *, cloud_content_id: str = ""
    ) -> None:
        """Mark an artifact as successfully synced."""
        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            conn.execute(
                """UPDATE artifacts SET
                    sync_status = 'synced',
                    cloud_content_id = ?,
                    last_sync_at = ?,
                    sync_error = NULL,
                    updated_at = ?
                WHERE artifact_id = ?""",
                (cloud_content_id, now, now, artifact_id),
            )
            conn.commit()

    def mark_artifact_failed(
        self, artifact_id: str, *, error: str = "", retry_count: int = 0
    ) -> None:
        """Mark an artifact sync as failed."""
        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            conn.execute(
                """UPDATE artifacts SET
                    sync_status = 'failed',
                    sync_error = ?,
                    retry_count = ?,
                    updated_at = ?
                WHERE artifact_id = ?""",
                (error, retry_count, now, artifact_id),
            )
            conn.commit()

    # Convenience aliases for cloud sync uploader compatibility
    def mark_synced(self, artifact_id: str, *, cloud_content_id: str = "") -> None:
        """Alias for mark_artifact_synced."""
        self.mark_artifact_synced(artifact_id, cloud_content_id=cloud_content_id)

    def mark_sync_failed(self, artifact_id: str, *, error: str = "", retry_count: int = 0) -> None:
        """Alias for mark_artifact_failed."""
        self.mark_artifact_failed(artifact_id, error=error, retry_count=retry_count)

    def get_failed_artifacts(self, *, max_retries: int = 3) -> list[dict[str, Any]]:
        """Get artifacts that failed sync and are below retry limit."""
        with self.connection(read_only=True) as conn:
            rows = conn.execute(
                """SELECT * FROM artifacts
                WHERE deleted = 0 AND sync_status = 'failed'
                AND retry_count < ?
                ORDER BY updated_at DESC""",
                (max_retries,),
            ).fetchall()
            return [dict(row) for row in rows]

    def get_sync_summary(self) -> dict[str, Any]:
        """Get counts by sync_status."""
        with self.connection(read_only=True) as conn:
            rows = conn.execute(
                """SELECT sync_status, COUNT(*) as cnt
                FROM artifacts WHERE deleted = 0
                GROUP BY sync_status"""
            ).fetchall()
            summary: dict[str, Any] = {"total": 0}
            for row in rows:
                summary[row["sync_status"]] = row["cnt"]
                summary["total"] += row["cnt"]
            return summary

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    def vacuum(self) -> None:
        """Run incremental auto-vacuum to reclaim space."""
        with self.connection() as conn:
            conn.execute("PRAGMA incremental_vacuum")

    def full_vacuum(self) -> None:
        """Run a full VACUUM (rebuilds the entire file)."""
        with self.connection() as conn:
            conn.execute("VACUUM")

    def integrity_check(self) -> list[str]:
        """Run PRAGMA integrity_check and return issues (empty = healthy)."""
        with self.connection(read_only=True) as conn:
            rows = conn.execute("PRAGMA integrity_check").fetchall()
            results = [row[0] for row in rows]
            if results == ["ok"]:
                return []
            return results

    def get_stats(self) -> dict[str, Any]:
        """Get database statistics."""
        with self.connection(read_only=True) as conn:
            stats: dict[str, Any] = {}

            # File size
            try:
                stats["file_size_bytes"] = self._db_path.stat().st_size
            except OSError:
                stats["file_size_bytes"] = 0

            # Table counts
            for table in [
                "index_runs", "graph_entities", "graph_relationships",
                "bsg_entries", "file_tracking", "ast_cache",
                "file_snapshots", "snapshots", "context_outputs", "artifacts",
            ]:
                row = conn.execute(f"SELECT COUNT(*) as cnt FROM {table}").fetchone()
                stats[f"{table}_count"] = row["cnt"] if row else 0

            stats["schema_version"] = self.get_meta("schema_version")
            return stats

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the database connection for this thread."""
        with _DB_CACHE_LOCK:
            with self._lock:
                self._closed = True
                if hasattr(self._local, "conn") and self._local.conn is not None:
                    self._local.conn.close()
                    self._local.conn = None

    def __repr__(self) -> str:
        return f"BathoDatabase(path={self._db_path!s})"
