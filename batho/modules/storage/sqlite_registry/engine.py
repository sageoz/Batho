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
import msgpack
import zstandard as zstd

from batho.utils.logging import get_logger

LOGGER = get_logger(__name__, component="storage_engine")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# It aligns with config DEFAULT_DB_PATH from batho.core.config.models
# New code should use config values via get_config_cached()
SCHEMA_VERSION = "batho-db.v1"
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

    # Pass through any full keys that weren't mapped (handles precompiled blobs
    # that store full dicts instead of minified ones)
    mapped_keys = set(rev_map.keys()) | {"id", "sg"}
    for k, v in mini.items():
        if k not in mapped_keys and k not in e:
            e[k] = v

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
        "roles": "ro",
        "reference_start_byte": "rs",
        "reference_end_byte": "re",
        "definition_start_byte": "ds",
        "definition_end_byte": "de",
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
    elif "relationship_id" in mini:
        r["relationship_id"] = mini["relationship_id"]

    rev_map = {
        "rt": "type",
        "s": "source_id",
        "t": "target_id",
        "ro": "roles",
        "rs": "reference_start_byte",
        "re": "reference_end_byte",
        "ds": "definition_start_byte",
        "de": "definition_end_byte",
        "m": "metadata",
    }
    for k, v in rev_map.items():
        if k in mini:
            r[v] = mini[k]
    if "type" in r:
        r["relationship_type"] = r["type"]

    # Pass through any full keys that weren't mapped (handles precompiled blobs
    # that store full dicts instead of minified ones)
    mapped_keys = set(rev_map.keys()) | {"id", "relationship_id"}
    for k, v in mini.items():
        if k not in mapped_keys and k not in r:
            r[k] = v

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


def resolve_db_path_from_config(root: Path) -> Path | None:
    """Resolve db_path from config, returns None for {root} (use default behavior)."""
    try:
        from batho.core.config import _get_config_cached_for_root
        from batho.utils.path_sanitizer import sanitize_path, PathSecurityError
        cfg = _get_config_cached_for_root(root)
        db_path = cfg.get("paths", {}).get("db_path", "{root}")
        
        # {root} means use default behavior (artifact file in repo root)
        if db_path == "{root}" or not db_path:
            return None
        
        # Sanitize path to prevent escaping root
        try:
            resolved = sanitize_path(db_path, root, allow_absolute=True)
        except PathSecurityError as e:
            LOGGER.warning("unsafe_db_path_in_config", db_path=db_path, error=str(e))
            return None
        
        # If it is an existing directory, or has an empty suffix (e.g. '.batho'),
        # treat it as a directory and place the artifact filename inside it.
        if resolved.is_dir() or not resolved.suffix:
            resolved = resolved / artifact_filename(root)
            try:
                resolved = sanitize_path(resolved, root, allow_absolute=True)
            except PathSecurityError:
                return None
            
        return resolved
    except Exception:
        return None


def resolve_db_path(root: Path | str) -> Path:
    """Resolve the database path for the repository root using config or default behavior."""
    root_path = Path(root).resolve()
    config_path = resolve_db_path_from_config(root_path)
    if config_path is not None:
        return config_path
    return root_path / artifact_filename(root_path)


def get_database(repo_root: Path | str, *, db_path: Path | str | None = None) -> "BathoDatabase":
    """Get or create a BathoDatabase instance for a repository."""
    root = Path(repo_root).resolve()
    if db_path is not None:
        resolved_path = Path(db_path).resolve()
    else:
        resolved_path = resolve_db_path(root)

    key = f"{resolved_path}@{root}"
    with _DB_CACHE_LOCK:
        existing = _DB_CACHE.get(key)
        if existing is not None and not getattr(existing, "_closed", False):
            return existing
        db = BathoDatabase(resolved_path, repo_root=root)
        _DB_CACHE[key] = db
        return db




# ---------------------------------------------------------------------------
# BathoDatabase
# ---------------------------------------------------------------------------


class BathoDatabase:
    """Unified SQLite persistence engine for a single Batho project."""

    def __init__(self, db_path: Path, *, repo_root: Path | None = None) -> None:
        import os
        self._db_path = db_path.resolve()
        self._repo_root = (repo_root or db_path.parent).resolve()
        self._lock = threading.RLock()
        self._local = threading.local()
        self._pid = os.getpid()
        self._closed = False
        self._initialized = False
        self._all_connections: list[sqlite3.Connection] = []
        self._string_dict_cache: dict[str, int] = {}
        self._string_val_cache: dict[int, str] = {}
        self._entity_dict_cache: dict[str, int] = {}
        self._entity_val_cache: dict[int, str] = {}
        self._zstd_level = 3

        try:
            # Guard: Check schema version if file exists (schema mismatch guard)
            if self._db_path.exists() and self._db_path.stat().st_size > 0:
                conn = None
                try:
                    conn = sqlite3.connect(str(self._db_path), timeout=5.0)
                    conn.row_factory = sqlite3.Row
                    row = conn.execute(
                        "SELECT value FROM db_meta WHERE key = 'schema_version'"
                    ).fetchone()
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
                finally:
                    if conn is not None:
                        conn.close()

            self._initialize()
        except Exception:
            # Close any connections opened during failed initialization to prevent leaks
            for c in self._all_connections:
                try:
                    c.close()
                except Exception:
                    pass
            self._all_connections.clear()
            raise

    @property
    def path(self) -> Path:
        return self._db_path

    @property
    def repo_root(self) -> Path:
        return self._repo_root

    @property
    def exists(self) -> bool:
        return self._db_path.exists()

    def _check_pid(self) -> None:
        import os
        current_pid = os.getpid()
        if getattr(self, "_pid", None) != current_pid:
            self._local = threading.local()
            self._string_dict_cache.clear()
            self._string_val_cache.clear()
            self._entity_dict_cache.clear()
            self._entity_val_cache.clear()
            # Clear connections without calling conn.close() to prevent dropping advisory locks in the parent process.
            self._all_connections = []
            self._pid = current_pid
            self._lock = threading.RLock()

    @property
    def _cctx(self) -> zstd.ZstdCompressor:
        self._check_pid()
        if not hasattr(self._local, "cctx"):
            self._local.cctx = zstd.ZstdCompressor(level=self._zstd_level)
        return self._local.cctx

    @property
    def _dctx(self) -> zstd.ZstdDecompressor:
        self._check_pid()
        if not hasattr(self._local, "dctx"):
            self._local.dctx = zstd.ZstdDecompressor()
        return self._local.dctx

    def _get_connection(self) -> sqlite3.Connection:
        if self._closed:
            raise RuntimeError("BathoDatabase is closed")

        self._check_pid()

        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(
                str(self._db_path),
                check_same_thread=False,
                timeout=30.0,
                isolation_level=None,
            )
            conn.row_factory = sqlite3.Row
            self._apply_pragmas(conn)
            self._local.conn = conn
            with self._lock:
                self._all_connections.append(conn)
        return self._local.conn

    def _apply_pragmas(self, conn: sqlite3.Connection) -> None:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA temp_store = MEMORY")
        conn.execute(f"PRAGMA busy_timeout = {DEFAULT_BUSY_TIMEOUT_MS}")
        conn.execute("PRAGMA cache_size = -128000")  # Larger cache
        conn.execute("PRAGMA mmap_size = 30000000000")  # Enable memory-mapped I/O up to 30GB
        conn.execute("PRAGMA journal_size_limit = 67108864")

        current_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        if current_mode.lower() != "wal":
            if sys.platform == "win32":
                conn.execute("PRAGMA journal_mode = DELETE")
            else:
                conn.execute("PRAGMA journal_mode = WAL")

        conn.execute("PRAGMA synchronous = NORMAL")

    @contextmanager
    def connection(self, *, read_only: bool = False) -> Iterator[sqlite3.Connection]:
        if not read_only:
            self._lock.acquire()
        conn = None
        try:
            conn = self._get_connection()
            yield conn
            if not read_only:
                conn.commit()
        except Exception:
            if conn is not None:
                conn.rollback()
            raise
        finally:
            if not read_only:
                self._lock.release()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
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
            # Check if any parent component of resolved path exists as a file
            if self._db_path.parent.exists() and not self._db_path.parent.is_dir():
                raise RuntimeError(
                    f"Database path conflict: '{self._db_path.parent}' exists as a file but is expected to be a directory. "
                    "Please delete or rename this file to allow database creation."
                )
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
        self._check_pid()
        with self._lock:
            if val in self._string_dict_cache:
                return self._string_dict_cache[val]

            conn = self._get_connection()
            try:
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
            except Exception:
                conn.rollback()
                raise

            self._string_dict_cache[val] = sid
            self._string_val_cache[sid] = val
            return sid

    def get_string_val(self, sid: int) -> str | None:
        """Get the string value for a string ID from string_dict."""
        self._check_pid()
        with self._lock:
            if sid in self._string_val_cache:
                return self._string_val_cache[sid]

            conn = self._get_connection()
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
        self.ensure_query_tables_exist()
        file_id = self.get_or_create_string_id(file_path)

        # Minify payloads
        minified_agent = _minify_graph_payload(agent_view_data)
        minified_storage = _minify_graph_payload(storage_delta_data)
        minified_rels = [_minify_relationship(r) for r in relationships_data]

        # Serialize and encode using msgpack
        import msgpack
        agent_bytes = msgpack.packb(minified_agent)
        storage_bytes = msgpack.packb(minified_storage)
        rels_bytes = msgpack.packb(minified_rels)

        # Compress (level 3)
        cctx = zstd.ZstdCompressor(level=3)
        agent_blob = cctx.compress(agent_bytes)
        storage_blob = cctx.compress(storage_bytes)
        rels_blob = cctx.compress(rels_bytes)

        # Collect all entity IDs to resolve
        entity_ids = set()
        for e in agent_view_data.get("entities", []):
            ent_id = e.get("id")
            if ent_id:
                entity_ids.add(ent_id)
        for r in relationships_data:
            src_id = r.get("source_id")
            tgt_id = r.get("target_id")
            if src_id:
                entity_ids.add(src_id)
            if tgt_id:
                entity_ids.add(tgt_id)

        entity_keys = self.bulk_get_or_create_entity_ids(list(entity_ids))

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
                ent_key = entity_keys.get(ent_id)
                if ent_key is not None:
                    query_rows.append((
                        ent_key,
                        run_internal_id,
                        ent_name,
                        ent_type,
                        ent_fqn,
                        file_path,
                        line,
                        sig,
                        is_exp,
                    ))

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

            src_key = entity_keys.get(src_id)
            if src_key is None:
                continue
                
            if tgt_id in unresolved_ids:
                dangling_rows.append((
                    src_key,
                    unresolved_ids[tgt_id],
                    r_type,
                    run_internal_id
                ))
            else:
                tgt_key = entity_keys.get(tgt_id)
                if tgt_key is not None:
                    rel_rows.append((
                        src_key,
                        tgt_key,
                        r_type,
                        run_internal_id,
                        meta
                    ))

        # Execute everything inside a single transaction to guarantee atomicity and speed up commits
        with self.transaction() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO file_artifacts(
                    run_id, file_id, bsg_agent_view, bsg_storage_view, bsg_rel_view, content_hash
                ) VALUES (?, ?, ?, ?, ?, ?)""",
                (run_internal_id, file_id, agent_blob, storage_blob, rels_blob, content_hash),
            )

            conn.execute(
                "DELETE FROM query_relationships WHERE run_id = ? AND source_key IN (SELECT entity_key FROM query_entities WHERE run_id = ? AND file_path = ?)",
                (run_internal_id, run_internal_id, file_path),
            )
            conn.execute(
                "DELETE FROM dangling_references WHERE run_id = ? AND source_key IN (SELECT entity_key FROM query_entities WHERE run_id = ? AND file_path = ?)",
                (run_internal_id, run_internal_id, file_path),
            )

            conn.execute(
                "DELETE FROM query_entities WHERE run_id = ? AND file_path = ?",
                (run_internal_id, file_path),
            )
            if query_rows:
                conn.executemany(
                    """INSERT OR REPLACE INTO query_entities(
                        entity_key, run_id, entity_name, entity_type, fqn, file_path, line_number, signature, is_exported
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    query_rows,
                )
            if rel_rows:
                conn.executemany(
                    """INSERT OR REPLACE INTO query_relationships(
                        source_key, target_key, relation_type, run_id, metadata_json
                    ) VALUES (?, ?, ?, ?, ?)""",
                    rel_rows,
                )
            if dangling_rows:
                conn.executemany(
                    """INSERT INTO dangling_references(
                        source_key, unresolved_target_name, relation_type, run_id
                    ) VALUES (?, ?, ?, ?)""",
                    dangling_rows,
                )

    def resolve_dangling_references(self, run_internal_id: int) -> int:
        """Perform symbol resolution to convert dangling references to query_relationships."""
        from collections import defaultdict
        import re
        
        with self.transaction() as conn:
            dangling = conn.execute(
                """SELECT d.source_key, d.unresolved_target_name, d.relation_type,
                          (SELECT file_path FROM query_entities WHERE entity_key = d.source_key AND run_id = d.run_id) AS source_file
                   FROM dangling_references d
                   WHERE d.run_id = ?""",
                (run_internal_id,)
            ).fetchall()

            if not dangling:
                conn.execute("DELETE FROM dangling_references WHERE run_id = ?", (run_internal_id,))
                return 0

            entities = conn.execute(
                """SELECT qe.entity_key, ed.val AS entity_id, qe.entity_name, qe.file_path 
                   FROM query_entities qe
                   JOIN entity_dict ed ON qe.entity_key = ed.id
                   WHERE qe.run_id = ? AND qe.entity_type != 'UNRESOLVED'""",
                (run_internal_id,)
            ).fetchall()

            entities_by_name = defaultdict(list)
            entities_by_id = defaultdict(list)
            files_by_id = {}
            names_by_id = {}
            id_to_key = {}
            for e in entities:
                ekey = e["entity_key"]
                eid = e["entity_id"]
                ename = e["entity_name"]
                efile = e["file_path"]
                id_to_key[eid] = ekey
                files_by_id[eid] = efile
                names_by_id[eid] = ename
                entities_by_name[ename].append(eid)
                entities_by_id[eid].append(eid)
                if "." in ename:
                    entities_by_name[ename.split(".")[-1]].append(eid)

            def lookup_candidates(ref_text: str) -> list[str]:
                normalized = ref_text.strip().strip(",;")
                normalized = re.sub(r"\s+as\s+\w+$", "", normalized).strip()
                if len(normalized) >= 2 and normalized[0] == normalized[-1] and normalized[0] in {'"', "'", "`"}:
                    normalized = normalized[1:-1].strip()
                normalized = normalized.replace("::", ".").strip()
                if not normalized:
                    return []
                
                ordered = [normalized]
                if "/" in normalized:
                    tail = normalized.rsplit("/", 1)[-1]
                    ordered.append(tail)
                    if "." in tail:
                        ordered.append(tail.rsplit(".", 1)[0])
                if "." in normalized:
                    ordered.append(normalized.rsplit(".", 1)[-1])
                if ":" in normalized and not normalized.startswith(("http://", "https://")):
                    ordered.append(normalized.rsplit(":", 1)[-1])
                return ordered

            def shared_dir_depth(source: str, target: str) -> int:
                source_parts = Path(source).parts[:-1]
                target_parts = Path(target).parts[:-1]
                depth = 0
                for source_part, target_part in zip(source_parts, target_parts):
                    if source_part != target_part:
                        break
                    depth += 1
                return depth

            def choose_best(candidate_ids: list[str], source_file: str | None) -> str | None:
                if not candidate_ids:
                    return None
                if len(candidate_ids) == 1:
                    return candidate_ids[0]

                def score(entity_id: str) -> tuple[int, int, str]:
                    target_file = files_by_id.get(entity_id, "")
                    val_score = 0
                    if source_file and target_file:
                        if source_file == target_file:
                            val_score += 1000
                        val_score += shared_dir_depth(source_file, target_file) * 10
                    name_len = len(names_by_id.get(entity_id, ""))
                    return (val_score, -name_len, entity_id)

                return max(candidate_ids, key=score)

            rels_to_insert = []
            resolution_map = defaultdict(list)
            for d in dangling:
                src_key = d["source_key"]
                ref_name = d["unresolved_target_name"]
                rel_type = d["relation_type"]
                src_file = d["source_file"]

                target_ids = entities_by_id.get(ref_name)
                if not target_ids:
                    for cand in lookup_candidates(ref_name):
                        target_ids = entities_by_name.get(cand)
                        if target_ids:
                            break

                target_id = choose_best(target_ids, src_file) if target_ids else None
                if target_id:
                    tgt_key = id_to_key.get(target_id)
                    if tgt_key is not None:
                        rels_to_insert.append((src_key, tgt_key, rel_type, run_internal_id, "{}"))
                        
                        src_id = self.get_entity_val(src_key)
                        if src_id:
                            file_path = src_file
                            if not file_path:
                                if ":" in src_id:
                                    file_path = src_id.split(":")[-1]
                                else:
                                    file_path = src_id
                            resolution_map[file_path].append({
                                "source_id": src_id,
                                "relation_type": rel_type,
                                "unresolved_target": ref_name,
                                "resolved_target": target_id,
                            })

            resolved_count = 0
            if rels_to_insert:
                for rel in rels_to_insert:
                    cursor = conn.execute(
                        """INSERT OR IGNORE INTO query_relationships (source_key, target_key, relation_type, run_id, metadata_json)
                           VALUES (?, ?, ?, ?, ?)""",
                        rel
                    )
                    resolved_count += cursor.rowcount

            # Update bsg_rel_view blobs in file_artifacts with resolved target IDs
            if resolution_map:
                cctx = zstd.ZstdCompressor(level=3)
                dctx = zstd.ZstdDecompressor()
                for file_path, resolutions in resolution_map.items():
                    row = conn.execute(
                        """SELECT bsg_rel_view FROM file_artifacts 
                           WHERE run_id = ? AND file_id = (SELECT id FROM string_dict WHERE val = ?)""",
                        (run_internal_id, file_path)
                    ).fetchone()
                    if not row or not row["bsg_rel_view"]:
                        continue
                    
                    try:
                        rels_blob = row["bsg_rel_view"]
                        rels_decompressed = dctx.decompress(rels_blob)
                        rels_minified = msgpack.unpackb(rels_decompressed)
                        
                        updated = False
                        for rel in rels_minified:
                            # Map keys: 's' -> source_id, 'rt' -> relation_type, 't' -> target_id
                            r_src = rel.get("s")
                            r_type = rel.get("rt")
                            r_tgt = rel.get("t")
                            
                            for res in resolutions:
                                is_match = False
                                if r_src == res["source_id"] and r_type == res["relation_type"]:
                                    if r_tgt == res["unresolved_target"]:
                                        is_match = True
                                    elif isinstance(r_tgt, str) and r_tgt.startswith("unresolved:"):
                                        parts = r_tgt.split(":")
                                        if len(parts) >= 2 and parts[1] == res["unresolved_target"]:
                                            is_match = True
                                if is_match:
                                    rel["t"] = res["resolved_target"]
                                    updated = True
                                    break
                                    
                        if updated:
                            new_rels_bytes = msgpack.packb(rels_minified)
                            new_rels_blob = cctx.compress(new_rels_bytes)
                            conn.execute(
                                """UPDATE file_artifacts SET bsg_rel_view = ? 
                                   WHERE run_id = ? AND file_id = (SELECT id FROM string_dict WHERE val = ?)""",
                                (new_rels_blob, run_internal_id, file_path)
                            )
                    except Exception as e:
                        LOGGER.warning("failed_to_update_bsg_rel_view_blob", file_path=file_path, error=str(e))

            conn.execute("DELETE FROM dangling_references WHERE run_id = ?", (run_internal_id,))
            return resolved_count


    def _extract_name_from_entity_id(self, entity_id: str) -> str:
        """Extract the human-readable symbol name from an opaque entity ID."""
        # "batho pip myproject 0.1.0 src/foo.py#MyFunc()." -> "MyFunc"
        if "#" in entity_id:
            name = entity_id.rsplit("#", 1)[-1].rstrip("().")
            if name:
                return name
        if "/" in entity_id:
            return entity_id.rsplit("/", 1)[-1]
        return entity_id

    def insert_file_artifacts_batch(
        self,
        run_internal_id: int,
        batch_items: list[dict[str, Any]],
    ) -> None:
        """Insert or replace a batch of file artifacts in a single transaction to eliminate commit latency."""
        if not batch_items:
            return

        self.ensure_query_tables_exist()

        # Build set of all entity IDs in the entire batch upfront to prevent O(N^2) loop complexity
        entity_ids_in_batch = set()
        for b_item in batch_items:
            for e in b_item["agent_view_data"].get("entities", []):
                ent_id = e.get("id")
                if ent_id:
                    entity_ids_in_batch.add(ent_id)

        # Collect all entity IDs to resolve in one go
        entity_ids_to_resolve = set()
        for b_item in batch_items:
            for e in b_item["agent_view_data"].get("entities", []):
                ent_id = e.get("id")
                if ent_id:
                    entity_ids_to_resolve.add(ent_id)
            for r in b_item["relationships_data"]:
                src_id = r.get("source_id")
                tgt_id = r.get("target_id")
                if src_id:
                    entity_ids_to_resolve.add(src_id)
                if tgt_id:
                    entity_ids_to_resolve.add(tgt_id)

        # Bulk resolve all entity IDs to their integer keys
        entity_keys = self.bulk_get_or_create_entity_ids(list(entity_ids_to_resolve))

        # Pseudo-target prefixes that are valid external references
        PSEDUO_TARGET_PREFIXES = (
            "external:",
            "file:",
            "anchor:",
            "unresolved:",
            "symbol:",
            "image:",
            "import:",
            "stylesheet:",
            "resource:",
            "variable:",
        )

        file_artifacts_rows = []
        query_entities_rows = []
        query_relationships_rows = []
        dangling_references_rows = []
        
        file_paths_to_delete = []

        cctx = zstd.ZstdCompressor(level=3)

        # Resolve all file path IDs in ONE transaction to eliminate commit latency
        all_file_paths = [item["file_path"] for item in batch_items]
        resolved_ids = self.bulk_get_or_create_string_ids(all_file_paths)

        for item in batch_items:
            file_path = item["file_path"]
            content_hash = item["content_hash"]
            agent_view_data = item["agent_view_data"]
            storage_delta_data = item["storage_delta_data"]
            relationships_data = item["relationships_data"]

            file_id = resolved_ids[file_path]
            file_paths_to_delete.append(file_path)

            # Minify payloads
            minified_agent = _minify_graph_payload(agent_view_data)
            minified_storage = _minify_graph_payload(storage_delta_data)
            minified_rels = [_minify_relationship(r) for r in relationships_data]

            # Serialize and encode using msgpack
            import msgpack
            agent_bytes = msgpack.packb(minified_agent)
            storage_bytes = msgpack.packb(minified_storage)
            rels_bytes = msgpack.packb(minified_rels)

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
                    ent_key = entity_keys.get(ent_id)
                    if ent_key is not None:
                        query_entities_rows.append((
                            ent_key, run_internal_id, ent_name, ent_type, ent_fqn, file_path, line, sig, is_exp
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

                src_key = entity_keys.get(src_id)
                if src_key is None:
                    continue

                # Check if target is a pseudo-target (external reference)
                is_pseudo_target = any(tgt_id.startswith(prefix) for prefix in PSEDUO_TARGET_PREFIXES)

                if is_pseudo_target:
                    # Insert pseudo-target relationships directly (they're valid external refs)
                    tgt_key = entity_keys.get(tgt_id)
                    if tgt_key is not None:
                        query_relationships_rows.append((
                            src_key, tgt_key, r_type, run_internal_id, meta
                        ))
                elif tgt_id in unresolved_ids:
                    dangling_references_rows.append((
                        src_key, unresolved_ids[tgt_id], r_type, run_internal_id
                    ))
                elif tgt_id not in entity_ids_in_batch:
                    target_name = _extract_name_from_entity_id(tgt_id)
                    dangling_references_rows.append((
                        src_key, target_name, r_type, run_internal_id
                    ))
                else:
                    tgt_key = entity_keys.get(tgt_id)
                    if tgt_key is not None:
                        query_relationships_rows.append((
                            src_key, tgt_key, r_type, run_internal_id, meta
                        ))

        # Single transaction for all database insertions
        with self.transaction() as conn:
            # 1. Insert File Artifacts in chunks to prevent 999 param limit issues
            chunk_size_artifacts = 999 // 6
            for idx in range(0, len(file_artifacts_rows), chunk_size_artifacts):
                chunk = file_artifacts_rows[idx:idx + chunk_size_artifacts]
                conn.executemany(
                    """INSERT OR REPLACE INTO file_artifacts(
                        run_id, file_id, bsg_agent_view, bsg_storage_view, bsg_rel_view, content_hash
                    ) VALUES (?, ?, ?, ?, ?, ?)""",
                    chunk,
                )

            # 2. Update query_relationships and dangling_references (delete old first using old query_entities state)
            for file_path in file_paths_to_delete:
                conn.execute(
                    "DELETE FROM query_relationships WHERE run_id = ? AND source_key IN (SELECT entity_key FROM query_entities WHERE run_id = ? AND file_path = ?)",
                    (run_internal_id, run_internal_id, file_path),
                )
                conn.execute(
                    "DELETE FROM dangling_references WHERE run_id = ? AND source_key IN (SELECT entity_key FROM query_entities WHERE run_id = ? AND file_path = ?)",
                    (run_internal_id, run_internal_id, file_path),
                )

            # 3. Update query_entities
            for file_path in file_paths_to_delete:
                conn.execute(
                    "DELETE FROM query_entities WHERE run_id = ? AND file_path = ?",
                    (run_internal_id, file_path),
                )
            if query_entities_rows:
                chunk_size_entities = 999 // 9
                for idx in range(0, len(query_entities_rows), chunk_size_entities):
                    chunk = query_entities_rows[idx:idx + chunk_size_entities]
                    conn.executemany(
                        """INSERT OR REPLACE INTO query_entities(
                            entity_key, run_id, entity_name, entity_type, fqn, file_path, line_number, signature, is_exported
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        chunk,
                    )
            if query_relationships_rows:
                chunk_size_rels = 999 // 5
                for idx in range(0, len(query_relationships_rows), chunk_size_rels):
                    chunk = query_relationships_rows[idx:idx + chunk_size_rels]
                    conn.executemany(
                        """INSERT OR REPLACE INTO query_relationships(
                            source_key, target_key, relation_type, run_id, metadata_json
                        ) VALUES (?, ?, ?, ?, ?)""",
                        chunk,
                    )
            if dangling_references_rows:
                chunk_size_dangling = 999 // 4
                for idx in range(0, len(dangling_references_rows), chunk_size_dangling):
                    chunk = dangling_references_rows[idx:idx + chunk_size_dangling]
                    conn.executemany(
                        """INSERT INTO dangling_references(
                            source_key, unresolved_target_name, relation_type, run_id
                        ) VALUES (?, ?, ?, ?)""",
                        chunk,
                    )

    def _insert_precompiled_batch(
        self,
        run_internal_id: int,
        batch: list[dict[str, Any]],
    ) -> None:
        """
        Direct insertion of pre-compiled blobs.
        Bypasses minification loops - blobs already compressed.
        """
        if not batch:
            return

        with self.transaction() as conn:
            # Chunk to avoid SQLITE_MAX_VARIABLE_NUMBER (999)
            safe_chunk_size = 999 // 6  # = 166

            sql = """INSERT OR REPLACE INTO file_artifacts
                (run_id, file_id, bsg_agent_view, bsg_storage_view, bsg_rel_view, content_hash)
                VALUES (?, ?, ?, ?, ?, ?)"""

            for i in range(0, len(batch), safe_chunk_size):
                chunk = batch[i:i + safe_chunk_size]
                params = []
                for item in chunk:
                    params.append((
                        run_internal_id,
                        item["file_id"],
                        item["agent_blob"],
                        item["storage_blob"],
                        item["rels_blob"],
                        item["content_hash"]
                    ))
                conn.executemany(sql, params)

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
                    agent_minified = msgpack.unpackb(agent_decompressed)
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
                        storage_minified = msgpack.unpackb(storage_decompressed)
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
                        rels_minified = msgpack.unpackb(rels_decompressed)
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

        conditions = ["qe.run_id = ?"]
        params: list[Any] = [run_internal_id]

        if "." in query:
            conditions.append("qe.fqn = ?")
            params.append(query)
        else:
            conditions.append("(qe.entity_name = ? OR qe.entity_name LIKE ?)")
            params.append(query)
            params.append(query + "%")

        if kinds:
            placeholders = ",".join("?" * len(kinds))
            conditions.append(f"qe.entity_type IN ({placeholders})")
            params.extend(kinds)

        params.append(limit)
        where_clause = " AND ".join(conditions)

        sql = f"""
            SELECT ed.val AS entity_id, qe.entity_name, qe.entity_type, qe.file_path, qe.line_number, qe.signature, qe.fqn
            FROM query_entities qe
            JOIN entity_dict ed ON qe.entity_key = ed.id
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

        # Resolve all file path IDs in ONE transaction to eliminate commit latency
        all_file_paths = [r["file_path"] for r in records]
        resolved_ids = self.bulk_get_or_create_string_ids(all_file_paths)

        now = datetime.now(timezone.utc).isoformat()
        rows_to_insert = []
        for r in records:
            file_id = resolved_ids[r["file_path"]]
            rows_to_insert.append((
                file_id,
                r["content_hash"],
                r["mtime"],
                r.get("mtime_ns"),
                r.get("inode"),
                r["size"],
                int(r.get("is_indexed", 0)),
                r.get("last_run_id"),
                now,
                r.get("encoding", "utf-8"),
            ))

        with self.transaction() as conn:
            conn.executemany(
                """INSERT OR REPLACE INTO file_tracking(
                    file_id, content_hash, mtime, mtime_ns, inode, size, is_indexed,
                    last_run_id, updated_at, encoding
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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

    def get_unindexed_files_with_details(self) -> list[dict[str, Any]]:
        """Get unindexed files with full tracking details."""
        with self.connection(read_only=True) as conn:
            rows = conn.execute(
                """SELECT sd.val as file_path, ft.content_hash, ft.size, ft.encoding
                   FROM file_tracking ft
                   JOIN string_dict sd ON ft.file_id = sd.id
                   WHERE ft.is_indexed = 0"""
            ).fetchall()
            return [dict(row) for row in rows]

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

    def finalize_run_artifacts(self, run_internal_id: int, artifacts: dict, blob_config: dict | None = None) -> None:
        """Insert or update a row in the run_artifacts table, compressing dicts with zstd."""
        run_cfg = None
        if blob_config is not None:
            run_cfg = blob_config.get("run_artifacts")

        def _compress(key: str, val: dict | None) -> bytes | None:
            if run_cfg is not None and not run_cfg.get(key, True):
                return None
            if val is None:
                return None
            try:
                serialized = json.dumps(val, ensure_ascii=True, default=str).encode("utf-8")
                return self._cctx.compress(serialized)
            except Exception as e:
                LOGGER.error("finalize_run_artifacts_compression_failed", key=key, error=str(e))
                return None

        context_overview = _compress("context_overview", artifacts.get("context_overview"))
        telemetry_metrics = _compress("telemetry_metrics", artifacts.get("telemetry_metrics"))
        structural_metrics = _compress("structural_metrics", artifacts.get("structural_metrics"))
        security_audit = _compress("security_audit", artifacts.get("security_audit"))
        artifact_payload = _compress("artifact_payload", artifacts.get("artifact_payload"))
        delta_stats = _compress("delta_stats", artifacts.get("delta_stats"))
        
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
                try:
                    decompressed = self._dctx.decompress(blob)
                    return json.loads(decompressed.decode("utf-8"))
                except Exception as e:
                    LOGGER.error("get_run_artifacts_decompression_failed", error=str(e))
                    return None
            
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
            minified = msgpack.unpackb(decompressed)
            expanded = _expand_graph_payload(minified)
            return expanded.get("entities", [])

    def bulk_get_or_create_string_ids(self, strings: list[str]) -> dict[str, int]:
        """Batch-resolve strings to string_dict IDs in one SELECT + one INSERT."""
        self._check_pid()
        with self._lock:
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
                chunk_size = 900
                for idx in range(0, len(missing_from_cache), chunk_size):
                    chunk = missing_from_cache[idx:idx + chunk_size]
                    placeholders = ",".join("?" * len(chunk))
                    existing = conn.execute(
                        f"SELECT id, val FROM string_dict WHERE val IN ({placeholders})",
                        chunk,
                    ).fetchall()
                    for row in existing:
                        result[row["val"]] = row["id"]
                        self._string_dict_cache[row["val"]] = row["id"]
                        self._string_val_cache[row["id"]] = row["val"]

                still_missing = [s for s in missing_from_cache if s not in result]
                if still_missing:
                    for idx in range(0, len(still_missing), chunk_size):
                        chunk = still_missing[idx:idx + chunk_size]
                        conn.executemany(
                            "INSERT OR IGNORE INTO string_dict(val) VALUES (?)",
                            [(s,) for s in chunk],
                        )
                        new_placeholders = ",".join("?" * len(chunk))
                        new_ids = conn.execute(
                            f"SELECT id, val FROM string_dict WHERE val IN ({new_placeholders})",
                            chunk,
                        ).fetchall()
                        for row in new_ids:
                            result[row["val"]] = row["id"]
                            self._string_dict_cache[row["val"]] = row["id"]
                            self._string_val_cache[row["id"]] = row["val"]

            return result

    def bulk_get_or_create_entity_ids(self, entity_ids: list[str]) -> dict[str, int]:
        """Batch-resolve entity IDs to entity_dict IDs in one SELECT + one INSERT."""
        self._check_pid()
        with self._lock:
            result: dict[str, int] = {}
            if not entity_ids:
                return result

            # Check cache first
            missing_from_cache = []
            for s in entity_ids:
                if s in self._entity_dict_cache:
                    result[s] = self._entity_dict_cache[s]
                else:
                    missing_from_cache.append(s)

            if not missing_from_cache:
                return result

            with self.transaction() as conn:
                chunk_size = 900
                for idx in range(0, len(missing_from_cache), chunk_size):
                    chunk = missing_from_cache[idx:idx + chunk_size]
                    placeholders = ",".join("?" * len(chunk))
                    existing = conn.execute(
                        f"SELECT id, val FROM entity_dict WHERE val IN ({placeholders})",
                        chunk,
                    ).fetchall()
                    for row in existing:
                        result[row["val"]] = row["id"]
                        self._entity_dict_cache[row["val"]] = row["id"]
                        self._entity_val_cache[row["id"]] = row["val"]

                still_missing = [s for s in missing_from_cache if s not in result]
                if still_missing:
                    for idx in range(0, len(still_missing), chunk_size):
                        chunk = still_missing[idx:idx + chunk_size]
                        conn.executemany(
                            "INSERT OR IGNORE INTO entity_dict(val) VALUES (?)",
                            [(s,) for s in chunk],
                        )
                        new_placeholders = ",".join("?" * len(chunk))
                        new_ids = conn.execute(
                            f"SELECT id, val FROM entity_dict WHERE val IN ({new_placeholders})",
                            chunk,
                        ).fetchall()
                        for row in new_ids:
                            result[row["val"]] = row["id"]
                            self._entity_dict_cache[row["val"]] = row["id"]
                            self._entity_val_cache[row["id"]] = row["val"]

            return result

    def get_entity_val(self, eid: int) -> str | None:
        """Get the entity ID string for an entity ID from entity_dict."""
        self._check_pid()
        with self._lock:
            if eid in self._entity_val_cache:
                return self._entity_val_cache[eid]

            with self.connection(read_only=True) as conn:
                row = conn.execute(
                    "SELECT val FROM entity_dict WHERE id = ?",
                    (eid,),
                ).fetchone()
                val = row["val"] if row else None
                if val is not None:
                    self._entity_val_cache[eid] = val
                    self._entity_dict_cache[val] = eid
                return val

    def ensure_query_tables_exist(self) -> None:
        """Create query_entities, query_relationships, dangling_references, and entity_dict tables if they don't exist."""
        sql = """
        CREATE TABLE IF NOT EXISTS entity_dict (
            id   INTEGER PRIMARY KEY AUTOINCREMENT,
            val  TEXT UNIQUE NOT NULL
        );

        CREATE TABLE IF NOT EXISTS query_entities (
            entity_key      INTEGER NOT NULL REFERENCES entity_dict(id) ON DELETE CASCADE,
            run_id          INTEGER NOT NULL REFERENCES index_runs(id) ON DELETE CASCADE,
            entity_name     TEXT NOT NULL,
            entity_type     TEXT NOT NULL,
            fqn             TEXT,
            file_path       TEXT NOT NULL,
            line_number     INTEGER NOT NULL,
            signature       TEXT,
            is_exported     INTEGER DEFAULT 0,
            PRIMARY KEY (entity_key, run_id)
        ) WITHOUT ROWID;

        CREATE INDEX IF NOT EXISTS idx_entities_name ON query_entities(entity_name);
        CREATE INDEX IF NOT EXISTS idx_entities_name_prefix ON query_entities(entity_name COLLATE NOCASE);
        CREATE INDEX IF NOT EXISTS idx_entities_type ON query_entities(entity_type);
        CREATE INDEX IF NOT EXISTS idx_entities_fqn ON query_entities(fqn);
        CREATE INDEX IF NOT EXISTS idx_entities_run ON query_entities(run_id);

        CREATE TABLE IF NOT EXISTS query_relationships (
            source_key      INTEGER NOT NULL REFERENCES entity_dict(id) ON DELETE CASCADE,
            target_key      INTEGER NOT NULL REFERENCES entity_dict(id) ON DELETE CASCADE,
            relation_type   TEXT NOT NULL,
            run_id          INTEGER NOT NULL REFERENCES index_runs(id) ON DELETE CASCADE,
            metadata_json   TEXT DEFAULT '{}',
            PRIMARY KEY (source_key, target_key, relation_type, run_id)
        ) WITHOUT ROWID;

        CREATE INDEX IF NOT EXISTS idx_relationships_source ON query_relationships(source_key, run_id);
        CREATE INDEX IF NOT EXISTS idx_relationships_target ON query_relationships(target_key, run_id);

        CREATE TABLE IF NOT EXISTS dangling_references (
            source_key              INTEGER NOT NULL REFERENCES entity_dict(id) ON DELETE CASCADE,
            unresolved_target_name  TEXT NOT NULL,
            relation_type           TEXT NOT NULL,
            run_id                  INTEGER NOT NULL REFERENCES index_runs(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_dangling_run_name
            ON dangling_references(run_id, unresolved_target_name);
        """
        with self.transaction() as conn:
            conn.executescript(sql)
            conn.commit()

    def populate_query_tables_for_unchanged_files(
        self,
        run_internal_id: int,
        base_run_internal_id: int,
        changed_file_paths: set[str],
    ) -> None:
        """Populate query tables (query_entities, query_relationships, dangling_references)
        from file_artifacts bsg_agent_view and bsg_rel_view blobs of unchanged files from the base run.
        """
        self.ensure_query_tables_exist()
        
        # 1. Fetch all files from file_artifacts of base_run_internal_id on a read_only connection
        dctx = zstd.ZstdDecompressor()
        
        with self.connection(read_only=True) as conn:
            rows = conn.execute(
                """SELECT sd.val AS file_path, fa.bsg_agent_view, fa.bsg_rel_view 
                   FROM file_artifacts fa
                   JOIN string_dict sd ON fa.file_id = sd.id
                   WHERE fa.run_id = ?""",
                (base_run_internal_id,)
            ).fetchall()
            
        # 2. Extract and prepare rows for query_entities, query_relationships, dangling_references
        # Filter unchanged files in Python to prevent DDL/writes on read-only connection
        # and to avoid SQL variable limit issues.
        query_entities_rows = []
        query_relationships_rows = []
        dangling_references_rows = []
        
        # We need to collect all entity/string IDs to resolve them in bulk
        entity_ids_to_resolve = set()
        
        # Also store the unpacked data to process in a second pass
        unpacked_items = []
        
        for row in rows:
            file_path = row["file_path"]
            if file_path in changed_file_paths:
                continue
                
            agent_blob = row["bsg_agent_view"]
            rels_blob = row["bsg_rel_view"]
            
            entities = []
            if agent_blob:
                try:
                    agent_decompressed = dctx.decompress(agent_blob)
                    agent_minified = msgpack.unpackb(agent_decompressed)
                    agent_data = _expand_graph_payload(agent_minified)
                    entities = agent_data.get("entities", [])
                except Exception:
                    pass
                    
            rels = []
            if rels_blob:
                try:
                    rels_decompressed = dctx.decompress(rels_blob)
                    rels_minified = msgpack.unpackb(rels_decompressed)
                    rels = [_expand_relationship(r) for r in rels_minified]
                except Exception:
                    pass
            
            for e in entities:
                ent_id = e.get("id")
                if ent_id:
                    entity_ids_to_resolve.add(ent_id)
            for r in rels:
                src_id = r.get("source_id")
                tgt_id = r.get("target_id")
                if src_id:
                    entity_ids_to_resolve.add(src_id)
                if tgt_id:
                    entity_ids_to_resolve.add(tgt_id)
                    
            unpacked_items.append({
                "file_path": file_path,
                "entities": entities,
                "relationships": rels,
            })
            
        # Bulk resolve all entity IDs
        entity_keys = self.bulk_get_or_create_entity_ids(list(entity_ids_to_resolve))
        
        PSEDUO_TARGET_PREFIXES = (
            "external:", "file:", "anchor:", "unresolved:", "symbol:",
            "image:", "import:", "stylesheet:", "resource:", "variable:"
        )
        
        for item in unpacked_items:
            file_path = item["file_path"]
            entities = item["entities"]
            relationships = item["relationships"]
            
            # Entities
            for e in entities:
                ent_id = e.get("id")
                ent_name = e.get("name")
                ent_type = e.get("type") or e.get("entity_type")
                ent_fqn = e.get("fqn")
                line = e.get("start_line") or e.get("line") or 1
                sig = e.get("signature")
                is_exp = e.get("is_exported") or 0
                if ent_id and ent_name and ent_type:
                    ent_key = entity_keys.get(ent_id)
                    if ent_key is not None:
                        query_entities_rows.append((
                            ent_key, run_internal_id, ent_name, ent_type, ent_fqn, file_path, line, sig, is_exp
                        ))
                        
            # Unresolved IDs
            unresolved_ids = {}
            for e in entities:
                e_type = e.get("type") or e.get("entity_type")
                if e_type == "UNRESOLVED" or (isinstance(e_type, str) and e_type.upper() == "UNRESOLVED"):
                    unresolved_ids[e.get("id")] = e.get("name")
                    
            # Relationships
            for r in relationships:
                src_id = r.get("source_id")
                tgt_id = r.get("target_id")
                r_type = r.get("type") or r.get("relationship_type")
                meta = json.dumps(r.get("metadata") or {})
                
                if not src_id or not tgt_id or not r_type:
                    continue
                    
                src_key = entity_keys.get(src_id)
                if src_key is None:
                    continue
                    
                is_pseudo_target = any(tgt_id.startswith(prefix) for prefix in PSEDUO_TARGET_PREFIXES)
                
                if is_pseudo_target:
                    tgt_key = entity_keys.get(tgt_id)
                    if tgt_key is not None:
                        query_relationships_rows.append((
                            src_key, tgt_key, r_type, run_internal_id, meta
                        ))
                elif tgt_id in unresolved_ids:
                    dangling_references_rows.append((
                        src_key, unresolved_ids[tgt_id], r_type, run_internal_id
                    ))
                else:
                    tgt_key = entity_keys.get(tgt_id)
                    if tgt_key is not None:
                        query_relationships_rows.append((
                            src_key, tgt_key, r_type, run_internal_id, meta
                        ))
                    else:
                        dangling_references_rows.append((
                            src_key, tgt_id, r_type, run_internal_id
                        ))
                        
        # 3. Write in chunks
        with self.transaction() as conn:
            if query_entities_rows:
                chunk_size_entities = 999 // 9
                for idx in range(0, len(query_entities_rows), chunk_size_entities):
                    chunk = query_entities_rows[idx:idx + chunk_size_entities]
                    conn.executemany(
                        """INSERT OR REPLACE INTO query_entities(
                            entity_key, run_id, entity_name, entity_type, fqn, file_path, line_number, signature, is_exported
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        chunk,
                    )
            if query_relationships_rows:
                chunk_size_rels = 999 // 5
                for idx in range(0, len(query_relationships_rows), chunk_size_rels):
                    chunk = query_relationships_rows[idx:idx + chunk_size_rels]
                    conn.executemany(
                        """INSERT OR REPLACE INTO query_relationships(
                            source_key, target_key, relation_type, run_id, metadata_json
                        ) VALUES (?, ?, ?, ?, ?)""",
                        chunk,
                    )
            if dangling_references_rows:
                chunk_size_dangling = 999 // 4
                for idx in range(0, len(dangling_references_rows), chunk_size_dangling):
                    chunk = dangling_references_rows[idx:idx + chunk_size_dangling]
                    conn.executemany(
                        """INSERT INTO dangling_references(
                            source_key, unresolved_target_name, relation_type, run_id
                        ) VALUES (?, ?, ?, ?)""",
                        chunk,
                    )

    def cleanup_query_tables(self) -> None:
        """Drop query_entities, query_relationships, dangling_references, and entity_dict tables to save space, and run vacuum to reclaim space."""
        with self.transaction() as conn:
            conn.execute("DROP TABLE IF EXISTS query_entities")
            conn.execute("DROP TABLE IF EXISTS query_relationships")
            conn.execute("DROP TABLE IF EXISTS dangling_references")
            conn.execute("DROP TABLE IF EXISTS entity_dict")

        # Reclaim space outside transaction using autocommit mode
        with self.connection() as conn:
            old_isolation = conn.isolation_level
            conn.isolation_level = None
            try:
                conn.execute("PRAGMA incremental_vacuum").fetchall()
            finally:
                conn.isolation_level = old_isolation

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

    def get_file_node_history(
        self,
        entity_id: str,
        *,
        limit: int = 50,
        since_completed_at: str | None = None,
    ) -> list[dict[str, Any]]:
        """Cross-run query using FTS5 to filter blobs, then decompress matching entries."""
        sql = """
            SELECT fc.run_id, fc.base_run_id, fc.node_changes,
                   r.run_uuid, base_r.run_uuid AS base_run_uuid
            FROM file_changelog_fts fts
            JOIN file_changelog fc ON fts.rowid = fc.id
            JOIN index_runs r ON fc.run_id = r.id
            LEFT JOIN index_runs base_r ON fc.base_run_id = base_r.id
            WHERE fts.entity_index MATCH ?
        """
        params = [f'"{entity_id}"']
        if since_completed_at:
            sql += " AND r.completed_at >= ?"
            params.append(since_completed_at)
        sql += """
            ORDER BY r.completed_at ASC, fc.run_id ASC
            LIMIT ?
        """
        params.append(limit)

        results = []
        with self.connection(read_only=True) as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
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
            LEFT JOIN index_runs base_r ON fc.base_run_id = base_r.id
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
        """Delete file_changelog and index_runs entries older than the N most recent completed runs.
        SQLite CASCADE triggers automatically clean up all associated file_artifacts,
        run_artifacts, and query_entities when a run is deleted.
        FTS5 sync triggers automatically clean up file_changelog_fts on DELETE.
        Called at end of run_patch.
        """
        with self.transaction() as conn:
            conn.execute(
                """DELETE FROM index_runs
                WHERE status = 'completed' AND id NOT IN (
                    SELECT id FROM index_runs
                    WHERE status = 'completed'
                    ORDER BY completed_at DESC
                    LIMIT ?
                )""",
                (max_runs,),
            )
            conn.commit()
        self.vacuum()

    def delete_file_artifacts_for_run(self, run_internal_id: int) -> None:
        """Delete file artifacts for a run."""
        with self.connection() as conn:
            conn.execute("DELETE FROM file_artifacts WHERE run_id = ?", (run_internal_id,))
            conn.commit()

    def delete_run_artifacts_for_run(self, run_internal_id: int) -> None:
        """Delete run artifacts for a run."""
        with self.connection() as conn:
            conn.execute("DELETE FROM run_artifacts WHERE run_id = ?", (run_internal_id,))
            conn.commit()
            
    def delete_patches_for_run(self, run_uuid: str) -> None:
        """No-op: patches are not stored in database in v2.0."""
        pass

    def get_file_changelog_raw(self, rel_path: str, since: str | None = None) -> list[dict]:
        """Raw SQL bypass for diff performance. Returns decompressed node_changes."""
        sql = """
            SELECT fc.run_id, fc.base_run_id, fc.node_changes,
                   r.run_uuid, base_r.run_uuid AS base_run_uuid
            FROM file_changelog fc
            JOIN string_dict file_dict ON fc.file_id = file_dict.id
            JOIN index_runs r ON fc.run_id = r.id
            LEFT JOIN index_runs base_r ON fc.base_run_id = base_r.id
            WHERE file_dict.val = ?
        """
        params = [rel_path]
        if since:
            sql += """ AND r.completed_at >= (
                SELECT completed_at FROM index_runs WHERE run_uuid = ?
            )"""
            params.append(since)
            
        sql += " ORDER BY r.completed_at ASC, fc.run_id ASC"
        
        results = []
        with self.connection(read_only=True) as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
            for row in rows:
                blob = row["node_changes"]
                if not blob:
                    continue
                decompressed = self._dctx.decompress(blob)
                changes = orjson.loads(decompressed)
                for entry in changes:
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

    def drop_query_indexes(self) -> None:
        """Drop search indexes on query_entities and query_relationships for bulk insert speedup."""
        self.ensure_query_tables_exist()
        with self.connection() as conn:
            conn.execute("DROP INDEX IF EXISTS idx_entities_name")
            conn.execute("DROP INDEX IF EXISTS idx_entities_name_prefix")
            conn.execute("DROP INDEX IF EXISTS idx_entities_type")
            conn.execute("DROP INDEX IF EXISTS idx_entities_fqn")
            conn.execute("DROP INDEX IF EXISTS idx_entities_run")
            conn.execute("DROP INDEX IF EXISTS idx_relationships_source")
            conn.execute("DROP INDEX IF EXISTS idx_relationships_target")
            conn.commit()

    def recreate_query_indexes(self) -> None:
        """Recreate search indexes after bulk insert."""
        self.ensure_query_tables_exist()
        with self.connection() as conn:
            conn.execute("CREATE INDEX IF NOT EXISTS idx_entities_name ON query_entities(entity_name)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_entities_name_prefix ON query_entities(entity_name COLLATE NOCASE)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_entities_type ON query_entities(entity_type)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_entities_fqn ON query_entities(fqn)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_entities_run ON query_entities(run_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_relationships_source ON query_relationships(source_key, run_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_relationships_target ON query_relationships(target_key, run_id)")
            conn.commit()

    def vacuum(self) -> None:
        try:
            with self.connection() as conn:
                auto_vacuum = conn.execute("PRAGMA auto_vacuum").fetchone()[0]
                old_isolation = conn.isolation_level
                conn.isolation_level = None
                try:
                    if auto_vacuum == 2:  # INCREMENTAL
                        conn.execute("PRAGMA incremental_vacuum").fetchall()
                    else:
                        conn.execute("VACUUM")
                finally:
                    conn.isolation_level = old_isolation
        except sqlite3.OperationalError as exc:
            LOGGER.warning("vacuum_failed_database_busy", error=str(exc))

    def full_vacuum(self) -> None:
        with self.connection() as conn:
            conn.commit()
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
                for conn in self._all_connections:
                    try:
                        conn.close()
                    except Exception:
                        pass
                self._all_connections.clear()
                if hasattr(self._local, "conn"):
                    self._local.conn = None
                key = f"{self._db_path}@{self._repo_root}"
                _DB_CACHE.pop(key, None)

    def __repr__(self) -> str:
        return f"BathoDatabase(path={self._db_path!s})"
