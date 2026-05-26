"""batho/storage/engine.py — Unified SQLite persistence engine.

Per-directory `artifact_<dirname>.batho` database.
All graph data, BSG payloads, context outputs, snapshots, and sync metadata
live in one ACID-compliant SQLite database per project.
"""

from __future__ import annotations

import hashlib
import importlib.resources
import json
import orjson
import re
import sqlite3
import sys
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator
import zstandard as zstd

from batho.utils.logging import get_logger

LOGGER = get_logger(__name__, component="storage_engine")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BATHO_DB_FILENAME = ".batho"
SCHEMA_VERSION = "batho-db.v7"
DEFAULT_PAGE_SIZE = 8192
DEFAULT_BUSY_TIMEOUT_MS = 5000

# Module-level cache
_DB_CACHE: dict[str, "BathoDatabase"] = {}
_DB_CACHE_LOCK = threading.RLock()


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
# Key Minification and Expansion (v4)
# ---------------------------------------------------------------------------

def _minify_entity(e: dict[str, Any]) -> dict[str, Any]:
    mini = {}
    if "id" in e:
        mini["id"] = e["id"]
    
    key_map = {
        "entity_type": "ty",
        "type": "ty",
        "name": "n",
        "file": "f",
        "start_line": "sl",
        "end_line": "el",
        "signature": "s",
        "parent_id": "p",
        "content_hash": "h",
        "ast_node_type": "an",
        "start_byte": "sb",
        "end_byte": "eb",
        "raw_content": "rc",
        "raw_bytes": "rb",
        "children_order": "co",
        "metadata": "m",
    }
    for k, v in key_map.items():
        if k in e and e[k] is not None:
            mini[v] = e[k]
            
    if "syntax_glue" in e and e["syntax_glue"]:
        sg = e["syntax_glue"]
        mini_sg = {}
        if "leading_whitespace" in sg:
            mini_sg["lw"] = sg["leading_whitespace"]
        if "trailing_whitespace" in sg:
            mini_sg["tw"] = sg["trailing_whitespace"]
        mini["sg"] = mini_sg
        
    return mini


def _expand_entity(mini: dict[str, Any]) -> dict[str, Any]:
    e = {}
    if "id" in mini:
        e["id"] = mini["id"]
        
    rev_map = {
        "ty": "entity_type",
        "n": "name",
        "f": "file",
        "sl": "start_line",
        "el": "end_line",
        "s": "signature",
        "p": "parent_id",
        "h": "content_hash",
        "an": "ast_node_type",
        "sb": "start_byte",
        "eb": "end_byte",
        "rc": "raw_content",
        "rb": "raw_bytes",
        "co": "children_order",
        "m": "metadata",
    }
    for k, v in rev_map.items():
        if k in mini:
            e[v] = mini[k]
            if v == "entity_type":
                e["type"] = mini[k]
            
    if "sg" in mini and mini["sg"]:
        sg = mini["sg"]
        e["syntax_glue"] = {
            "leading_whitespace": sg.get("lw", ""),
            "trailing_whitespace": sg.get("tw", ""),
        }
        e["leading_whitespace"] = sg.get("lw", "")
        e["trailing_whitespace"] = sg.get("tw", "")
        
    return e


def _minify_relationship(r: dict[str, Any]) -> dict[str, Any]:
    mini = {}
    if "id" in r:
        mini["id"] = r["id"]
    elif "relationship_id" in r:
        mini["id"] = r["relationship_id"]
        
    key_map = {
        "type": "rt",
        "relationship_type": "rt",
        "source_id": "s",
        "target_id": "t",
        "metadata": "m",
    }
    for k, v in key_map.items():
        if k in r and r[k] is not None:
            mini[v] = r[k]
    return mini


def _expand_relationship(mini: dict[str, Any]) -> dict[str, Any]:
    r = {}
    if "id" in mini:
        r["id"] = mini["id"]
        r["relationship_id"] = mini["id"]
        
    rev_map = {
        "rt": "type",
        "s": "source_id",
        "t": "target_id",
        "m": "metadata",
    }
    for k, v in rev_map.items():
        if k in mini:
            r[v] = mini[k]
    if "type" in r:
        r["relationship_type"] = r["type"]
    return r


def _minify_graph_payload(graph_data: dict[str, Any]) -> dict[str, Any]:
    mini = {}
    if "entities" in graph_data:
        mini["e"] = [_minify_entity(e) for e in graph_data["entities"]]
    if "relationships" in graph_data:
        mini["r"] = [_minify_relationship(r) for r in graph_data["relationships"]]
    return mini


def _expand_graph_payload(minified: dict[str, Any]) -> dict[str, Any]:
    expanded = {}
    if "e" in minified:
        expanded["entities"] = [_expand_entity(e) for e in minified["e"]]
    else:
        expanded["entities"] = []
    if "r" in minified:
        expanded["relationships"] = [_expand_relationship(r) for r in minified["r"]]
    else:
        expanded["relationships"] = []
    return expanded


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_database(repo_root: Path | str, *, db_path: Path | str | None = None) -> "BathoDatabase":
    """Get or create a BathoDatabase instance for a repository."""
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
    """Unified SQLite persistence engine for a single Batho project."""

    def __init__(self, db_path: Path, *, repo_root: Path | None = None) -> None:
        self._db_path = db_path.resolve()
        self._repo_root = (repo_root or db_path.parent).resolve()
        self._lock = threading.RLock()
        self._local = threading.local()
        self._closed = False
        self._initialized = False
        self._string_dict_cache: dict[str, int] = {}
        self._string_val_cache: dict[int, str] = {}
        self._cctx = zstd.ZstdCompressor(level=3)
        self._dctx = zstd.ZstdDecompressor()

        # Guard: Check schema version if file exists (schema mismatch guard)
        if self._db_path.exists() and self._db_path.stat().st_size > 0:
            try:
                conn = sqlite3.connect(str(self._db_path), timeout=5.0)
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    "SELECT value FROM db_meta WHERE key = 'schema_version'"
                ).fetchone()
                conn.close()
                if row:
                    val = row["value"]
                    if val != SCHEMA_VERSION:
                        raise RuntimeError(
                            f"Database schema mismatch. Found {val}, expected {SCHEMA_VERSION}. "
                            "Please rebuild the database using 'batho build --full'."
                        )
                else:
                    raise RuntimeError(
                        f"Database schema mismatch (missing schema version). "
                        "Please rebuild the database using 'batho build --full'."
                    )
            except sqlite3.OperationalError:
                raise RuntimeError(
                    f"Database schema mismatch (db_meta table missing). "
                    "Please rebuild the database using 'batho build --full'."
                )

        self._initialize()

    @property
    def path(self) -> Path:
        return self._db_path

    @property
    def repo_root(self) -> Path:
        return self._repo_root

    @property
    def exists(self) -> bool:
        return self._db_path.exists()

    def _get_connection(self) -> sqlite3.Connection:
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
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA temp_store = MEMORY")
        conn.execute(f"PRAGMA busy_timeout = {DEFAULT_BUSY_TIMEOUT_MS}")
        conn.execute("PRAGMA cache_size = -128000")  # Larger cache
        conn.execute("PRAGMA mmap_size = 30000000000")  # Enable memory-mapped I/O up to 30GB

        current_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        if current_mode.lower() != "wal":
            if sys.platform == "win32":
                conn.execute("PRAGMA journal_mode = DELETE")
            else:
                conn.execute("PRAGMA journal_mode = WAL")

        conn.execute("PRAGMA synchronous = NORMAL")

    @contextmanager
    def connection(self, *, read_only: bool = False) -> Iterator[sqlite3.Connection]:
        conn = self._get_connection()
        try:
            yield conn
        except Exception:
            conn.rollback()
            raise

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        conn = self._get_connection()
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def _initialize(self) -> None:
        if self._initialized:
            return

        try:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)

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
            
            repo_root_str = str(self._repo_root)
            conn.execute(
                "INSERT OR IGNORE INTO db_meta(key, value, updated_at) VALUES (?, ?, ?)",
                ("repo_root", repo_root_str, now),
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
        with self.connection(read_only=True) as conn:
            row = conn.execute(
                "SELECT value FROM db_meta WHERE key = ?", (key,)
            ).fetchone()
            return row["value"] if row else None

    def set_meta(self, key: str, value: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO db_meta(key, value, updated_at) VALUES (?, ?, ?)",
                (key, value, now),
            )
            conn.commit()

    # ------------------------------------------------------------------
    # String dictionary
    # ------------------------------------------------------------------

    def get_or_create_string_id(self, val: str) -> int:
        """Get or create the string ID for a value in string_dict."""
        if val in self._string_dict_cache:
            return self._string_dict_cache[val]

        with self.connection() as conn:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO string_dict(val) VALUES (?)",
                (val,),
            )
            if cursor.rowcount == 0:
                row = conn.execute(
                    "SELECT id FROM string_dict WHERE val = ?",
                    (val,),
                ).fetchone()
                sid = row["id"]
            else:
                sid = cursor.lastrowid
            conn.commit()
            self._string_dict_cache[val] = sid
            self._string_val_cache[sid] = val
            return sid

    def get_string_val(self, sid: int) -> str | None:
        """Get the string value for a string ID from string_dict."""
        if sid in self._string_val_cache:
            return self._string_val_cache[sid]

        with self.connection(read_only=True) as conn:
            row = conn.execute(
                "SELECT val FROM string_dict WHERE id = ?",
                (sid,),
            ).fetchone()
            val = row["val"] if row else None
            if val is not None:
                self._string_val_cache[sid] = val
                self._string_dict_cache[val] = sid
            return val

    # ------------------------------------------------------------------
    # Index Runs
    # ------------------------------------------------------------------

    def create_run(
        self,
        run_uuid: str,
        *,
        schema_version: str = "",
        root_path: str = "",
        git_commit: str | None = None,
        git_branch: str | None = None,
    ) -> int:
        """Register a new index run. Returns internal row ID."""
        now = datetime.now(timezone.utc).isoformat()
        root_path_str = root_path or str(self._repo_root)
        root_path_id = self.get_or_create_string_id(root_path_str)

        with self.connection() as conn:
            cursor = conn.execute(
                """INSERT INTO index_runs(
                    run_uuid, schema_version, started_at, status,
                    git_commit, git_branch, root_path_id
                ) VALUES (?, ?, ?, 'running', ?, ?, ?)""",
                (
                    run_uuid,
                    schema_version or SCHEMA_VERSION,
                    now,
                    git_commit,
                    git_branch,
                    root_path_id,
                ),
            )
            conn.commit()
            return cursor.lastrowid

    def get_run_internal_id(self, run_uuid: str) -> int | None:
        """Get the internal index_runs.id for a run_uuid."""
        with self.connection(read_only=True) as conn:
            row = conn.execute(
                "SELECT id FROM index_runs WHERE run_uuid = ?",
                (run_uuid,),
            ).fetchone()
            return row["id"] if row else None

    def complete_run(
        self,
        run_uuid: str,
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
                WHERE run_uuid = ?""",
                (now, entity_count, rel_count, file_count, duration_ms, run_uuid),
            )
            conn.commit()

    def fail_run(self, run_uuid: str, *, error_message: str = "") -> None:
        """Mark a run as failed."""
        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            conn.execute(
                """UPDATE index_runs SET
                    status = 'failed',
                    completed_at = ?,
                    error_message = ?
                WHERE run_uuid = ?""",
                (now, error_message, run_uuid),
            )
            conn.commit()

    def get_latest_run_id(self) -> str | None:
        """Get the run_uuid of the most recent completed run."""
        with self.connection(read_only=True) as conn:
            row = conn.execute(
                """SELECT run_uuid FROM index_runs
                WHERE status = 'completed'
                ORDER BY completed_at DESC LIMIT 1"""
            ).fetchone()
            return row["run_uuid"] if row else None

    def get_run(self, run_uuid: str) -> dict[str, Any] | None:
        """Get full run metadata."""
        with self.connection(read_only=True) as conn:
            row = conn.execute(
                "SELECT * FROM index_runs WHERE run_uuid = ?", (run_uuid,)
            ).fetchone()
            if row is None:
                return None
            run_dict = dict(row)
            if "root_path_id" in run_dict:
                run_dict["root_path"] = self.get_string_val(run_dict["root_path_id"])
            return run_dict

    def delete_run(self, run_uuid: str) -> None:
        """Delete a run and all cascaded data."""
        with self.connection() as conn:
            conn.execute("DELETE FROM index_runs WHERE run_uuid = ?", (run_uuid,))
            conn.commit()

    def get_entity_count(self, run_uuid: str) -> int:
        run = self.get_run(run_uuid)
        return run["entity_count"] if run else 0

    def get_relationship_count(self, run_uuid: str) -> int:
        run = self.get_run(run_uuid)
        return run["rel_count"] if run else 0

    # ------------------------------------------------------------------
    # File Artifacts
    # ------------------------------------------------------------------

    def insert_file_artifact(
        self,
        run_internal_id: int,
        file_path: str,
        content_hash: str,
        agent_view_data: dict[str, Any],
        storage_delta_data: dict[str, Any],
        relationships_data: list[dict[str, Any]],
    ) -> None:
        """Insert or replace a file artifact, compressing the three views individually."""
        file_id = self.get_or_create_string_id(file_path)

        # Minify payloads
        minified_agent = _minify_graph_payload(agent_view_data)
        minified_storage = _minify_graph_payload(storage_delta_data)
        minified_rels = [_minify_relationship(r) for r in relationships_data]

        # Serialize and encode
        agent_bytes = json.dumps(minified_agent, ensure_ascii=True).encode("utf-8")
        storage_bytes = json.dumps(minified_storage, ensure_ascii=True).encode("utf-8")
        rels_bytes = json.dumps(minified_rels, ensure_ascii=True).encode("utf-8")

        # Compress (level 3)
        cctx = zstd.ZstdCompressor(level=3)
        agent_blob = cctx.compress(agent_bytes)
        storage_blob = cctx.compress(storage_bytes)
        rels_blob = cctx.compress(rels_bytes)

        with self.connection() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO file_artifacts(
                    run_id, file_id, bsg_agent_view, bsg_storage_view, bsg_rel_view, content_hash
                ) VALUES (?, ?, ?, ?, ?, ?)""",
                (run_internal_id, file_id, agent_blob, storage_blob, rels_blob, content_hash),
            )
            conn.commit()

        # Update query_entities for fast search fallback
        entities = agent_view_data.get("entities", [])
        query_rows = []
        for e in entities:
            ent_id = e.get("id")
            ent_name = e.get("name")
            ent_type = e.get("type") or e.get("entity_type")
            ent_fqn = e.get("fqn")
            line = e.get("start_line") or e.get("line") or 1
            sig = e.get("signature")
            is_exp = e.get("is_exported") or 0
            if ent_id and ent_name and ent_type:
                query_rows.append((
                    ent_id,
                    run_internal_id,
                    ent_name,
                    ent_type,
                    ent_fqn,
                    file_path,
                    line,
                    sig,
                    is_exp,
                ))

        with self.transaction() as conn:
            conn.execute(
                "DELETE FROM query_entities WHERE run_id = ? AND file_path = ?",
                (run_internal_id, file_path),
            )
            if query_rows:
                conn.executemany(
                    """INSERT OR REPLACE INTO query_entities(
                        entity_id, run_id, entity_name, entity_type, fqn, file_path, line_number, signature, is_exported
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    query_rows,
                )
            conn.commit()

        # Update query_relationships and dangling_references
        unresolved_ids = {}
        for e in agent_view_data.get("entities", []):
            e_type = e.get("type") or e.get("entity_type")
            if e_type == "UNRESOLVED" or (isinstance(e_type, str) and e_type.upper() == "UNRESOLVED"):
                unresolved_ids[e.get("id")] = e.get("name")

        rel_rows = []
        dangling_rows = []
        for r in relationships_data:
            src_id = r.get("source_id")
            tgt_id = r.get("target_id")
            r_type = r.get("type") or r.get("relationship_type")
            meta = json.dumps(r.get("metadata") or {})
            
            if not src_id or not tgt_id or not r_type:
                continue
                
            if tgt_id in unresolved_ids:
                dangling_rows.append((
                    src_id,
                    unresolved_ids[tgt_id],
                    r_type,
                    run_internal_id
                ))
            else:
                rel_rows.append((
                    src_id,
                    tgt_id,
                    r_type,
                    run_internal_id,
                    meta
                ))

        with self.transaction() as conn:
            conn.execute(
                "DELETE FROM query_relationships WHERE run_id = ? AND source_id IN (SELECT entity_id FROM query_entities WHERE file_path = ?)",
                (run_internal_id, file_path),
            )
            conn.execute(
                "DELETE FROM dangling_references WHERE run_id = ? AND source_id IN (SELECT entity_id FROM query_entities WHERE file_path = ?)",
                (run_internal_id, file_path),
            )
            if rel_rows:
                conn.executemany(
                    """INSERT OR REPLACE INTO query_relationships(
                        source_id, target_id, relation_type, run_id, metadata_json
                    ) VALUES (?, ?, ?, ?, ?)""",
                    rel_rows,
                )
            if dangling_rows:
                conn.executemany(
                    """INSERT INTO dangling_references(
                        source_id, unresolved_target_name, relation_type, run_id
                    ) VALUES (?, ?, ?, ?)""",
                    dangling_rows,
                )
            conn.commit()

    def resolve_dangling_references(self, run_internal_id: int) -> int:
        """Perform a single lazy cross-file resolution JOIN to convert dangling references to query_relationships."""
        with self.transaction() as conn:
            # 1. Match dangling references to actual query_entities by name
            cursor = conn.execute(
                """INSERT OR IGNORE INTO query_relationships (source_id, target_id, relation_type, run_id)
                   SELECT d.source_id, e.entity_id, d.relation_type, d.run_id
                   FROM dangling_references d
                   JOIN query_entities e ON d.unresolved_target_name = e.entity_name AND d.run_id = e.run_id
                   WHERE d.run_id = ? AND e.entity_type != 'UNRESOLVED'""",
                (run_internal_id,)
            )
            resolved_count = cursor.rowcount
            # 2. Cleanup resolved/all dangling references for this run
            conn.execute(
                "DELETE FROM dangling_references WHERE run_id = ?",
                (run_internal_id,)
            )
            conn.commit()
            return resolved_count

    def insert_file_artifacts_batch(
        self,
        run_internal_id: int,
        batch_items: list[dict[str, Any]],
    ) -> None:
        """Insert or replace a batch of file artifacts in a single transaction to eliminate commit latency."""
        if not batch_items:
            return

        file_artifacts_rows = []
        query_entities_rows = []
        query_relationships_rows = []
        dangling_references_rows = []
        
        file_paths_to_delete = []

        cctx = zstd.ZstdCompressor(level=3)

        for item in batch_items:
            file_path = item["file_path"]
            content_hash = item["content_hash"]
            agent_view_data = item["agent_view_data"]
            storage_delta_data = item["storage_delta_data"]
            relationships_data = item["relationships_data"]

            file_id = self.get_or_create_string_id(file_path)
            file_paths_to_delete.append(file_path)

            # Minify payloads
            minified_agent = _minify_graph_payload(agent_view_data)
            minified_storage = _minify_graph_payload(storage_delta_data)
            minified_rels = [_minify_relationship(r) for r in relationships_data]

            # Serialize and encode
            agent_bytes = json.dumps(minified_agent, ensure_ascii=True).encode("utf-8")
            storage_bytes = json.dumps(minified_storage, ensure_ascii=True).encode("utf-8")
            rels_bytes = json.dumps(minified_rels, ensure_ascii=True).encode("utf-8")

            # Compress
            agent_blob = cctx.compress(agent_bytes)
            storage_blob = cctx.compress(storage_bytes)
            rels_blob = cctx.compress(rels_bytes)

            file_artifacts_rows.append((
                run_internal_id, file_id, agent_blob, storage_blob, rels_blob, content_hash
            ))

            # Query Entities
            entities = agent_view_data.get("entities", [])
            for e in entities:
                ent_id = e.get("id")
                ent_name = e.get("name")
                ent_type = e.get("type") or e.get("entity_type")
                ent_fqn = e.get("fqn")
                line = e.get("start_line") or e.get("line") or 1
                sig = e.get("signature")
                is_exp = e.get("is_exported") or 0
                if ent_id and ent_name and ent_type:
                    query_entities_rows.append((
                        ent_id, run_internal_id, ent_name, ent_type, ent_fqn, file_path, line, sig, is_exp
                    ))

            # Unresolved IDs
            unresolved_ids = {}
            for e in agent_view_data.get("entities", []):
                e_type = e.get("type") or e.get("entity_type")
                if e_type == "UNRESOLVED" or (isinstance(e_type, str) and e_type.upper() == "UNRESOLVED"):
                    unresolved_ids[e.get("id")] = e.get("name")

            # Relationships
            for r in relationships_data:
                src_id = r.get("source_id")
                tgt_id = r.get("target_id")
                r_type = r.get("type") or r.get("relationship_type")
                meta = json.dumps(r.get("metadata") or {})
                
                if not src_id or not tgt_id or not r_type:
                    continue
                    
                if tgt_id in unresolved_ids:
                    dangling_references_rows.append((
                        src_id, unresolved_ids[tgt_id], r_type, run_internal_id
                    ))
                else:
                    query_relationships_rows.append((
                        src_id, tgt_id, r_type, run_internal_id, meta
                    ))

        # Single transaction for all database insertions
        with self.transaction() as conn:
            # 1. Insert File Artifacts
            conn.executemany(
                """INSERT OR REPLACE INTO file_artifacts(
                    run_id, file_id, bsg_agent_view, bsg_storage_view, bsg_rel_view, content_hash
                ) VALUES (?, ?, ?, ?, ?, ?)""",
                file_artifacts_rows,
            )

            # 2. Update query_entities
            for file_path in file_paths_to_delete:
                conn.execute(
                    "DELETE FROM query_entities WHERE run_id = ? AND file_path = ?",
                    (run_internal_id, file_path),
                )
            if query_entities_rows:
                conn.executemany(
                    """INSERT OR REPLACE INTO query_entities(
                        entity_id, run_id, entity_name, entity_type, fqn, file_path, line_number, signature, is_exported
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    query_entities_rows,
                )

            # 3. Update query_relationships and dangling_references
            for file_path in file_paths_to_delete:
                conn.execute(
                    "DELETE FROM query_relationships WHERE run_id = ? AND source_id IN (SELECT entity_id FROM query_entities WHERE file_path = ?)",
                    (run_internal_id, file_path),
                )
                conn.execute(
                    "DELETE FROM dangling_references WHERE run_id = ? AND source_id IN (SELECT entity_id FROM query_entities WHERE file_path = ?)",
                    (run_internal_id, file_path),
                )
            if query_relationships_rows:
                conn.executemany(
                    """INSERT OR REPLACE INTO query_relationships(
                        source_id, target_id, relation_type, run_id, metadata_json
                    ) VALUES (?, ?, ?, ?, ?)""",
                    query_relationships_rows,
                )
            if dangling_references_rows:
                conn.executemany(
                    """INSERT INTO dangling_references(
                        source_id, unresolved_target_name, relation_type, run_id
                    ) VALUES (?, ?, ?, ?)""",
                    dangling_references_rows,
                )
            conn.commit()

    def get_file_artifacts(
        self,
        run_internal_id: int,
        include_storage: bool = False,
        include_relationships: bool = True,
    ) -> list[dict[str, Any]]:
        """Retrieve and decompress file artifacts for a run."""
        cols = ["file_id", "content_hash", "bsg_agent_view"]
        if include_storage:
            cols.append("bsg_storage_view")
        if include_relationships:
            cols.append("bsg_rel_view")

        cols_str = ", ".join(cols)
        query = f"SELECT {cols_str} FROM file_artifacts WHERE run_id = ?"

        dctx = zstd.ZstdDecompressor()
        results = []

        with self.connection(read_only=True) as conn:
            rows = conn.execute(query, (run_internal_id,)).fetchall()
            for row in rows:
                file_path = self.get_string_val(row["file_id"])
                if not file_path:
                    continue

                content_hash = row["content_hash"]

                # 1. Load agent view
                agent_blob = row["bsg_agent_view"]
                if agent_blob:
                    agent_decompressed = dctx.decompress(agent_blob)
                    agent_minified = json.loads(agent_decompressed.decode("utf-8"))
                    agent_data = _expand_graph_payload(agent_minified)
                else:
                    agent_data = {"entities": [], "relationships": []}

                entities_list = agent_data.get("entities", [])
                entities_by_id = {e["id"]: e for e in entities_list if "id" in e}

                # 2. Load storage view
                if include_storage:
                    storage_blob = row["bsg_storage_view"]
                    if storage_blob:
                        storage_decompressed = dctx.decompress(storage_blob)
                        storage_minified = json.loads(storage_decompressed.decode("utf-8"))
                        storage_data = _expand_graph_payload(storage_minified)
                        
                        storage_entities = storage_data.get("entities", [])
                        for se in storage_entities:
                            ent_id = se.get("id")
                            if ent_id in entities_by_id:
                                ae = entities_by_id[ent_id]
                                for k, v in se.items():
                                    if k != "id" and v is not None:
                                        ae[k] = v
                                if "syntax_glue" in se and se["syntax_glue"]:
                                    sg = se["syntax_glue"]
                                    if "leading_whitespace" in sg:
                                        ae["leading_whitespace"] = sg["leading_whitespace"]
                                    if "trailing_whitespace" in sg:
                                        ae["trailing_whitespace"] = sg["trailing_whitespace"]

                # 3. Load relationships
                rels_list = []
                if include_relationships:
                    rels_blob = row["bsg_rel_view"]
                    if rels_blob:
                        rels_decompressed = dctx.decompress(rels_blob)
                        rels_minified = json.loads(rels_decompressed.decode("utf-8"))
                        rels_list = [_expand_relationship(r) for r in rels_minified]

                results.append({
                    "file_path": file_path,
                    "content_hash": content_hash,
                    "graph": {
                        "entities": entities_list,
                        "relationships": rels_list,
                    }
                })

        return results

    # ------------------------------------------------------------------
    # SQLite Search fallback
    # ------------------------------------------------------------------

    def search_entities(
        self,
        run_uuid: str,
        query: str,
        *,
        kinds: list[str] | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Search entities in query_entities by name (exact or prefix or FQN match)."""
        run_internal_id = self.get_run_internal_id(run_uuid)
        if run_internal_id is None:
            return []

        conditions = ["run_id = ?"]
        params: list[Any] = [run_internal_id]

        if "." in query:
            conditions.append("fqn = ?")
            params.append(query)
        else:
            conditions.append("(entity_name = ? OR entity_name LIKE ?)")
            params.append(query)
            params.append(query + "%")

        if kinds:
            placeholders = ",".join("?" * len(kinds))
            conditions.append(f"entity_type IN ({placeholders})")
            params.extend(kinds)

        params.append(limit)
        where_clause = " AND ".join(conditions)

        sql = f"""
            SELECT entity_id, entity_name, entity_type, file_path, line_number, signature, fqn
            FROM query_entities
            WHERE {where_clause}
            LIMIT ?
        """

        with self.connection(read_only=True) as conn:
            rows = conn.execute(sql, params).fetchall()
            results = []
            for r in rows:
                results.append({
                    "id": r["entity_id"],
                    "name": r["entity_name"],
                    "kind": r["entity_type"],
                    "file": r["file_path"],
                    "line": r["line_number"],
                    "signature": r["signature"],
                    "fqn": r["fqn"],
                })
            return results

    # ------------------------------------------------------------------
    # File Tracking
    # ------------------------------------------------------------------

    def upsert_file_tracking(self, records: list[dict[str, Any]]) -> int:
        """Bulk upsert file tracking records."""
        if not records:
            return 0

        now = datetime.now(timezone.utc).isoformat()
        rows_to_insert = []
        for r in records:
            file_id = self.get_or_create_string_id(r["file_path"])
            rows_to_insert.append((
                file_id,
                r["content_hash"],
                r["mtime"],
                r["size"],
                int(r.get("is_indexed", 0)),
                r.get("last_run_id"),
                now,
                r.get("encoding", "utf-8"),
            ))

        with self.transaction() as conn:
            conn.executemany(
                """INSERT OR REPLACE INTO file_tracking(
                    file_id, content_hash, mtime, size, is_indexed,
                    last_run_id, updated_at, encoding
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                rows_to_insert,
            )
        return len(records)

    def get_file_tracking(self, file_path: str) -> dict[str, Any] | None:
        """Get tracking data for a single file."""
        with self.connection(read_only=True) as conn:
            row = conn.execute(
                """SELECT ft.*, sd.val as file_path 
                   FROM file_tracking ft 
                   JOIN string_dict sd ON ft.file_id = sd.id 
                   WHERE sd.val = ?""", 
                (file_path,)
            ).fetchone()
            return dict(row) if row else None

    def get_all_file_tracking(self) -> dict[str, dict[str, Any]]:
        """Get all file tracking records mapped by file_path."""
        with self.connection(read_only=True) as conn:
            rows = conn.execute(
                """SELECT ft.*, sd.val as file_path 
                   FROM file_tracking ft
                   JOIN string_dict sd ON ft.file_id = sd.id"""
            ).fetchall()
            return {row["file_path"]: dict(row) for row in rows}

    def get_all_file_hashes(self) -> dict[str, str]:
        """Get all file_path -> content_hash mappings."""
        with self.connection(read_only=True) as conn:
            rows = conn.execute(
                """SELECT sd.val as file_path, ft.content_hash 
                   FROM file_tracking ft
                   JOIN string_dict sd ON ft.file_id = sd.id"""
            ).fetchall()
            return {row["file_path"]: row["content_hash"] for row in rows}

    def get_unindexed_files(self) -> dict[str, str]:
        """Get unindexed file_path -> content_hash mappings."""
        with self.connection(read_only=True) as conn:
            rows = conn.execute(
                """SELECT sd.val as file_path, ft.content_hash 
                   FROM file_tracking ft
                   JOIN string_dict sd ON ft.file_id = sd.id
                   WHERE ft.is_indexed = 0"""
            ).fetchall()
            return {row["file_path"]: row["content_hash"] for row in rows}

    def delete_file_tracking(self, file_path: str) -> None:
        """Remove a file from tracking."""
        with self.connection() as conn:
            conn.execute(
                """DELETE FROM file_tracking 
                   WHERE file_id = (SELECT id FROM string_dict WHERE val = ?)""", 
                (file_path,)
            )
            conn.commit()

    # ------------------------------------------------------------------
    # Run Artifacts (Enterprise Metrics & Context)
    # ------------------------------------------------------------------

    def finalize_run_artifacts(self, run_internal_id: int, artifacts: dict) -> None:
        """Insert or update a row in the run_artifacts table, compressing dicts with zstd."""
        def _compress(val: dict | None) -> bytes | None:
            if val is None:
                return None
            serialized = json.dumps(val, ensure_ascii=True).encode("utf-8")
            return self._cctx.compress(serialized)

        context_overview = _compress(artifacts.get("context_overview"))
        telemetry_metrics = _compress(artifacts.get("telemetry_metrics"))
        structural_metrics = _compress(artifacts.get("structural_metrics"))
        security_audit = _compress(artifacts.get("security_audit"))
        artifact_payload = _compress(artifacts.get("artifact_payload"))
        delta_stats = _compress(artifacts.get("delta_stats"))
        
        with self.transaction() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO run_artifacts (
                    run_id, context_overview, telemetry_metrics, structural_metrics,
                    security_audit, artifact_payload, delta_stats
                ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_internal_id,
                    context_overview,
                    telemetry_metrics,
                    structural_metrics,
                    security_audit,
                    artifact_payload,
                    delta_stats
                )
            )
            conn.commit()

    def get_run_artifacts(self, run_internal_id: int) -> dict | None:
        """Retrieve and decompress all 6 columns for a run."""
        query = """SELECT context_overview, telemetry_metrics, structural_metrics,
                          security_audit, artifact_payload, delta_stats, schema_version, created_at
                   FROM run_artifacts WHERE run_id = ?"""
        with self.connection(read_only=True) as conn:
            row = conn.execute(query, (run_internal_id,)).fetchone()
            if not row:
                return None
            
            def _decompress(blob: bytes | None) -> dict | None:
                if not blob:
                    return None
                decompressed = self._dctx.decompress(blob)
                return json.loads(decompressed.decode("utf-8"))
            
            return {
                "run_id": run_internal_id,
                "context_overview": _decompress(row["context_overview"]),
                "telemetry_metrics": _decompress(row["telemetry_metrics"]),
                "structural_metrics": _decompress(row["structural_metrics"]),
                "security_audit": _decompress(row["security_audit"]),
                "artifact_payload": _decompress(row["artifact_payload"]),
                "delta_stats": _decompress(row["delta_stats"]),
                "schema_version": row["schema_version"],
                "created_at": row["created_at"],
            }

    def get_agent_entities_for_file(self, run_internal_id: int, file_path: str) -> list[dict[str, Any]]:
        """Fetch + decompress only bsg_agent_view for one file. Returns list[dict]."""
        with self.connection(read_only=True) as conn:
            row = conn.execute(
                """SELECT bsg_agent_view FROM file_artifacts
                WHERE run_id = ? AND file_id = (SELECT id FROM string_dict WHERE val = ?)""",
                (run_internal_id, file_path),
            ).fetchone()
            if not row or not row["bsg_agent_view"]:
                return []
            dctx = zstd.ZstdDecompressor()
            decompressed = dctx.decompress(row["bsg_agent_view"])
            minified = json.loads(decompressed.decode("utf-8"))
            expanded = _expand_graph_payload(minified)
            return expanded.get("entities", [])

    def bulk_get_or_create_string_ids(self, strings: list[str]) -> dict[str, int]:
        """Batch-resolve strings to string_dict IDs in one SELECT + one INSERT."""
        result: dict[str, int] = {}
        if not strings:
            return result

        # Check cache first
        missing_from_cache = []
        for s in strings:
            if s in self._string_dict_cache:
                result[s] = self._string_dict_cache[s]
            else:
                missing_from_cache.append(s)

        if not missing_from_cache:
            return result

        with self.transaction() as conn:
            placeholders = ",".join("?" * len(missing_from_cache))
            existing = conn.execute(
                f"SELECT id, val FROM string_dict WHERE val IN ({placeholders})",
                missing_from_cache,
            ).fetchall()
            for row in existing:
                result[row["val"]] = row["id"]
                self._string_dict_cache[row["val"]] = row["id"]

            still_missing = [s for s in missing_from_cache if s not in result]
            if still_missing:
                conn.executemany(
                    "INSERT OR IGNORE INTO string_dict(val) VALUES (?)",
                    [(s,) for s in still_missing],
                )
                new_placeholders = ",".join("?" * len(still_missing))
                new_ids = conn.execute(
                    f"SELECT id, val FROM string_dict WHERE val IN ({new_placeholders})",
                    still_missing,
                ).fetchall()
                for row in new_ids:
                    result[row["val"]] = row["id"]
                    self._string_dict_cache[row["val"]] = row["id"]

        return result

    def record_file_changelog(self, run_id: int, base_run_id: int, diffs: list[NodeDiff]) -> None:
        """Group NodeDiffs by file, compress as orjson blob, bulk-insert one row per file."""
        if not diffs:
            return

        from collections import defaultdict
        by_file: dict[str, list] = defaultdict(list)
        for d in diffs:
            by_file[d.file_path].append(d)

        file_id_map = self.bulk_get_or_create_string_ids(list(by_file.keys()))

        rows: list[tuple] = []
        for file_path, file_diffs in by_file.items():
            file_id = file_id_map[file_path]
            array = [d.to_dict() for d in file_diffs]
            entity_index = " ".join({d.entity_id for d in file_diffs})
            blob = self._cctx.compress(orjson.dumps(array))
            rows.append((run_id, base_run_id, file_id, entity_index, blob))

        with self.transaction() as conn:
            conn.executemany(
                """INSERT OR REPLACE INTO file_changelog
                    (run_id, base_run_id, file_id, entity_index, node_changes)
                    VALUES (?, ?, ?, ?, ?)""",
                rows,
            )
            conn.commit()

    def get_file_node_history(self, entity_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
        """Cross-run query using FTS5 to filter blobs, then decompress matching entries."""
        sql = """
            SELECT fc.run_id, fc.base_run_id, fc.node_changes,
                   r.run_uuid, base_r.run_uuid AS base_run_uuid
            FROM file_changelog_fts fts
            JOIN file_changelog fc ON fts.rowid = fc.id
            JOIN index_runs r ON fc.run_id = r.id
            JOIN index_runs base_r ON fc.base_run_id = base_r.id
            WHERE fts.entity_index MATCH ?
            ORDER BY r.completed_at ASC, fc.run_id ASC
            LIMIT ?
        """
        results = []
        with self.connection(read_only=True) as conn:
            rows = conn.execute(sql, (f'"{entity_id}"', limit)).fetchall()
            for row in rows:
                blob = row["node_changes"]
                if not blob:
                    continue
                changes = orjson.loads(self._dctx.decompress(blob))
                for entry in changes:
                    if entry.get("entity_id") == entity_id:
                        results.append({
                            "run_id": row["run_id"],
                            "base_run_id": row["base_run_id"],
                            "run_uuid": row["run_uuid"],
                            "base_run_uuid": row["base_run_uuid"],
                            "entity_id": entry["entity_id"],
                            "entity_name": entry["entity_name"],
                            "entity_type": entry["entity_type"],
                            "change_kind": entry["change_kind"],
                            "changed_fields": entry["changed_fields"],
                            "old_hash": entry["old_hash"],
                            "new_hash": entry["new_hash"],
                        })
        return results

    def get_run_file_changelog(self, run_uuid: str) -> list[dict[str, Any]]:
        """All node diffs for a specific run: decompress per-file blobs and flatten."""
        sql = """
            SELECT fc.run_id, fc.base_run_id, fc.node_changes,
                   file_dict.val AS file_path,
                   base_r.run_uuid AS base_run_uuid
            FROM file_changelog fc
            JOIN index_runs r ON fc.run_id = r.id
            JOIN index_runs base_r ON fc.base_run_id = base_r.id
            JOIN string_dict file_dict ON fc.file_id = file_dict.id
            WHERE r.run_uuid = ?
        """
        results = []
        with self.connection(read_only=True) as conn:
            rows = conn.execute(sql, (run_uuid,)).fetchall()
            for row in rows:
                blob = row["node_changes"]
                if not blob:
                    continue
                changes = orjson.loads(self._dctx.decompress(blob))
                for entry in changes:
                    results.append({
                        "run_id": row["run_id"],
                        "base_run_id": row["base_run_id"],
                        "run_uuid": run_uuid,
                        "base_run_uuid": row["base_run_uuid"],
                        "entity_id": entry["entity_id"],
                        "entity_name": entry["entity_name"],
                        "file_path": row["file_path"],
                        "entity_type": entry["entity_type"],
                        "change_kind": entry["change_kind"],
                        "changed_fields": entry["changed_fields"],
                        "old_hash": entry["old_hash"],
                        "new_hash": entry["new_hash"],
                    })
        return results

    def prune_file_changelog(self, max_runs: int) -> None:
        """Delete file_changelog entries older than the N most recent completed runs.
        FTS5 sync triggers automatically clean up file_changelog_fts on DELETE.
        Called at end of run_patch.
        """
        with self.transaction() as conn:
            conn.execute(
                """DELETE FROM file_changelog
                WHERE run_id NOT IN (
                    SELECT id FROM index_runs
                    WHERE status = 'completed'
                    ORDER BY completed_at DESC
                    LIMIT ?
                )""",
                (max_runs,),
            )
            conn.commit()

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    def vacuum(self) -> None:
        with self.connection() as conn:
            conn.execute("PRAGMA incremental_vacuum")

    def full_vacuum(self) -> None:
        with self.connection() as conn:
            conn.execute("VACUUM")

    def integrity_check(self) -> list[str]:
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

            try:
                stats["file_size_bytes"] = self._db_path.stat().st_size
            except OSError:
                stats["file_size_bytes"] = 0

            for table in [
                "index_runs", "file_artifacts",
                "file_tracking", "run_artifacts", "query_entities"
            ]:
                try:
                    row = conn.execute(f"SELECT COUNT(*) as cnt FROM {table}").fetchone()
                    stats[f"{table}_count"] = row["cnt"] if row else 0
                except sqlite3.OperationalError:
                    stats[f"{table}_count"] = 0

            stats["schema_version"] = self.get_meta("schema_version")
            return stats

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        with _DB_CACHE_LOCK:
            with self._lock:
                self._closed = True
                if hasattr(self._local, "conn") and self._local.conn is not None:
                    self._local.conn.close()
                    self._local.conn = None

    def __repr__(self) -> str:
        return f"BathoDatabase(path={self._db_path!s})"
