import os
import sqlite3
import threading
from pathlib import Path
from typing import Any
from datetime import datetime, timezone

from batho.bridge_core.deps import WorkspaceDeps, SnapshotCache, load_workspace_deps
from batho.context.codegraph import InMemoryGraph
from batho.storage.engine import get_database, artifact_filename
from batho.utils.logging import get_logger

LOGGER = get_logger(__name__, component="bridge_core.global_registry")


def resolve_global_db_path(repo_root: Path | None = None) -> Path:
    """Resolve global.batho database path based on env, config, or default."""
    env_path = os.getenv("BATHO_GLOBAL_DB")
    if env_path:
        return Path(env_path).resolve()
        
    try:
        from batho.config import get_config_cached, set_active_root
        if repo_root:
            set_active_root(repo_root)
        config = get_config_cached()
        if config and isinstance(config, dict):
            paths = config.get("paths", {})
            global_db_path = paths.get("global_db_path")
            if global_db_path:
                p = Path(global_db_path)
                if not p.is_absolute() and repo_root:
                    return (repo_root / p).resolve()
                return p.resolve()
    except Exception:
        pass
        
    return Path("~/.batho/global.batho").expanduser().resolve()



class GlobalPlatformDeps:
    """Central registry managing global.batho database and loaded workspaces."""
    
    def __init__(self, global_db_path: Path):
        self.global_db_path = Path(global_db_path).resolve()
        self.global_db = self._init_global_db(self.global_db_path)
        self.workspace_cache = {}  # repo_id -> SnapshotCache
        self._lock = threading.RLock()
        
    def _init_global_db(self, path: Path) -> sqlite3.Connection:
        """Initialize global.batho with schema and WAL mode."""
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        
        # Apply pragmas
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA foreign_keys = ON")
        
        # Load and execute schema
        schema_path = Path(__file__).parent.parent / "storage" / "global_schema.sql"
        if schema_path.exists():
            schema_sql = schema_path.read_text(encoding="utf-8")
            conn.executescript(schema_sql)
        else:
            raise FileNotFoundError(f"Global schema not found at {schema_path}")
            
        conn.commit()
        return conn
        
    def register_workspace(self, repo_name: str, repo_path: Path, origin_url: str | None = None) -> int:
        """Register a new workspace in global registry."""
        repo_path = Path(repo_path).resolve()
        now = datetime.now(timezone.utc).isoformat()
        
        with self._lock:
            # Check if workspace already registered
            row = self.global_db.execute(
                "SELECT repo_id FROM workspaces WHERE repo_name = ?",
                (repo_name,)
            ).fetchone()
            
            if row:
                repo_id = row["repo_id"]
                # Update existing workspace path/origin_url
                self.global_db.execute(
                    """UPDATE workspaces 
                       SET repo_path = ?, origin_url = ?, last_synced_at = ?, is_active = 1
                       WHERE repo_id = ?""",
                    (str(repo_path), origin_url, now, repo_id)
                )
                self.global_db.commit()
                LOGGER.info("workspace_updated", repo_name=repo_name, repo_id=repo_id)
                return repo_id
            else:
                cursor = self.global_db.execute(
                    """INSERT INTO workspaces (repo_name, repo_path, origin_url, registered_at, last_synced_at, is_active)
                       VALUES (?, ?, ?, ?, ?, 1)""",
                    (repo_name, str(repo_path), origin_url, now, now)
                )
                self.global_db.commit()
                repo_id = cursor.lastrowid
                LOGGER.info("workspace_registered", repo_name=repo_name, repo_id=repo_id)
                return repo_id
                
    def register_artifact(self, repo_id: int, artifact_path: Path) -> None:
        """Register a .batho artifact and extract public symbols."""
        artifact_path = Path(artifact_path).resolve()
        now = datetime.now(timezone.utc).isoformat()
        
        with self._lock:
            # Fetch workspace path
            row_ws = self.global_db.execute(
                "SELECT repo_path FROM workspaces WHERE repo_id = ?",
                (repo_id,)
            ).fetchone()
            if not row_ws:
                raise ValueError(f"Workspace with repo_id {repo_id} not registered")
                
            workspace_path = Path(row_ws["repo_path"])
            
            # Load local DB and latest run to get entities, files
            db = get_database(workspace_path, db_path=artifact_path)
            latest_run_id = db.get_latest_run_id()
            if not latest_run_id:
                LOGGER.warning("artifact_registration_skipped_no_runs", repo_id=repo_id, artifact_path=str(artifact_path))
                return
                
            run_info = db.get_run(latest_run_id)
            entity_count = run_info.get("entity_count", 0) if run_info else 0
            file_count = run_info.get("file_count", 0) if run_info else 0
            
            # Update/Insert into artifacts table
            self.global_db.execute(
                """INSERT OR REPLACE INTO artifacts (repo_id, artifact_path, latest_run_id, last_synced_at, entity_count, file_count)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (repo_id, str(artifact_path), latest_run_id, now, entity_count, file_count)
            )
            
            # Delete old symbols for this repo
            self.global_db.execute("DELETE FROM global_symbols WHERE repo_id = ?", (repo_id,))
            
            # Load graph to extract public symbols
            deps = load_workspace_deps(workspace_path, run_id=latest_run_id)
            
            # Extract and insert public symbols
            public_symbols = self._extract_public_symbols(repo_id, latest_run_id, deps.graph)
            if public_symbols:
                self.global_db.executemany(
                    """INSERT INTO global_symbols (symbol_name, symbol_type, repo_id, run_id, file_path, line_number, is_exported, fqn)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    [
                        (s["symbol_name"], s["symbol_type"], s["repo_id"], s["run_id"], s["file_path"], s["line_number"], s["is_exported"], s["fqn"])
                        for s in public_symbols
                    ]
                )
            
            self.global_db.commit()
            LOGGER.info("artifact_registered", repo_id=repo_id, symbols_indexed=len(public_symbols))
            
            # Rebuild cross-repo edges incrementally/fleet-wide
            try:
                self.rebuild_cross_repo_edges()
            except Exception as e:
                LOGGER.warning("rebuild_edges_failed_during_registration", repo_id=repo_id, error=str(e))
            
    def _extract_public_symbols(self, repo_id: int, run_id: str, graph: InMemoryGraph) -> list[dict]:
        """Extract exported symbols from graph for global index."""
        public_symbols = []
        target_types = {"FUNCTION", "CLASS", "INTERFACE", "STRUCT", "ENUM", "TRAIT", "TYPE_ALIAS"}
        
        for entity in graph.entities.values():
            # Simple heuristic: ignore private symbols (starting with _)
            if entity.name.startswith("_"):
                continue
                
            entity_type_str = entity.type.name if hasattr(entity.type, "name") else str(entity.type)
            if entity_type_str in target_types:
                public_symbols.append({
                    "symbol_name": entity.name,
                    "symbol_type": entity_type_str,
                    "repo_id": repo_id,
                    "run_id": run_id,
                    "file_path": entity.file,
                    "line_number": entity.start_line,
                    "is_exported": 1,
                    "fqn": entity.fqn or entity.name,
                })
        return public_symbols
        
    def get_workspace_deps(self, repo_id: int, run_id: str | None = None) -> WorkspaceDeps:
        """Get WorkspaceDeps for a workspace, using SnapshotCache."""
        with self._lock:
            # Query workspace path
            row = self.global_db.execute(
                "SELECT repo_path FROM workspaces WHERE repo_id = ?",
                (repo_id,)
            ).fetchone()
            if not row:
                raise ValueError(f"Workspace with repo_id {repo_id} not found")
                
            repo_path = Path(row["repo_path"])
            
            # Get/create cache
            if repo_id not in self.workspace_cache:
                self.workspace_cache[repo_id] = SnapshotCache()
            cache = self.workspace_cache[repo_id]
            
            if run_id is None:
                # Query local database latest run
                db = get_database(repo_path)
                run_id = db.get_latest_run_id()
                if not run_id:
                    raise ValueError(f"No completed runs found in database at {repo_path}")
                    
            return cache.get(repo_path, run_id)
            
    def search_symbols_global(self, query: str, symbol_type: str | None = None) -> list[dict]:
        """Search global_symbols table across all workspaces."""
        with self._lock:
            sql = """SELECT s.*, w.repo_name, w.repo_path 
                     FROM global_symbols s 
                     JOIN workspaces w ON s.repo_id = w.repo_id 
                     WHERE s.symbol_name LIKE ?"""
            params = [f"%{query}%"]
            if symbol_type:
                sql += " AND s.symbol_type = ?"
                params.append(symbol_type.upper())
            rows = self.global_db.execute(sql, params).fetchall()
            return [dict(r) for r in rows]
            
    def get_cross_repo_impact(self, repo_id: int, symbol_name: str) -> list[dict]:
        """Find downstream dependencies using cross_repo_edges."""
        with self._lock:
            sql = """SELECT e.*, w_src.repo_name AS source_repo_name, w_tgt.repo_name AS target_repo_name
                     FROM cross_repo_edges e
                     JOIN workspaces w_src ON e.source_repo_id = w_src.repo_id
                     JOIN workspaces w_tgt ON e.target_repo_id = w_tgt.repo_id
                     WHERE e.target_repo_id = ? AND e.target_symbol = ?"""
            rows = self.global_db.execute(sql, (repo_id, symbol_name)).fetchall()
            return [dict(r) for r in rows]
            
    def get_fleet_overview(self) -> dict:
        """Return fleet-wide metrics and dependency graph."""
        with self._lock:
            workspaces = [
                dict(w) for w in self.global_db.execute("SELECT * FROM workspaces WHERE is_active = 1").fetchall()
            ]
            edges = [
                dict(e) for e in self.global_db.execute("SELECT * FROM cross_repo_edges").fetchall()
            ]
            
            total_repos = len(workspaces)
            total_symbols = self.global_db.execute("SELECT COUNT(*) FROM global_symbols").fetchone()[0]
            total_files = self.global_db.execute("SELECT SUM(file_count) FROM artifacts").fetchone()[0] or 0
            
            return {
                "workspaces": workspaces,
                "edges": edges,
                "metrics": {
                    "total_repositories": total_repos,
                    "total_symbols": total_symbols,
                    "total_files": total_files,
                }
            }
            
    def rebuild_cross_repo_edges(self) -> None:
        """Re-evaluate all relationships across all registered workspaces to detect cross-repo edges."""
        with self._lock:
            self.global_db.execute("DELETE FROM cross_repo_edges")
            self.global_db.commit()
            
            workspaces = self.global_db.execute("SELECT repo_id, repo_path FROM workspaces WHERE is_active = 1").fetchall()
            for ws in workspaces:
                repo_id = ws["repo_id"]
                repo_path = Path(ws["repo_path"])
                try:
                    deps = self.get_workspace_deps(repo_id)
                    self._detect_and_insert_cross_repo_edges(repo_id, deps.graph)
                except Exception as e:
                    LOGGER.warning("cross_repo_edge_detection_failed", repo_id=repo_id, error=str(e))

    def _detect_and_insert_cross_repo_edges(self, repo_id: int, graph: InMemoryGraph) -> None:
        """Helper to scan graph and insert cross repo edges into registry database."""
        from batho.context.schema import RelationshipType
        target_rel_types = {
            RelationshipType.IMPORTS,
            RelationshipType.CALLS,
            RelationshipType.INHERITS,
            RelationshipType.IMPLEMENTS,
            RelationshipType.USES,
            RelationshipType.REFERENCES
        }
        
        discovered_edges = []
        timestamp = datetime.now(timezone.utc).isoformat()
        
        for r in graph.relationships:
            if r.type not in target_rel_types:
                continue
                
            src = graph.get_entity(r.source_id)
            tgt = graph.get_entity(r.target_id)
            
            if not src or not tgt:
                continue
                
            # Search if target name is exported by any other repo
            matches = self.global_db.execute(
                "SELECT repo_id, symbol_name, symbol_type, fqn FROM global_symbols WHERE repo_id != ? AND symbol_name = ? AND is_exported = 1",
                (repo_id, tgt.name)
            ).fetchall()
            
            for m in matches:
                target_repo_id = m["repo_id"]
                target_symbol = m["symbol_name"]
                
                confidence = 0.8
                
                # Check if FQN matching raises confidence
                if src.fqn and m["fqn"] and (m["fqn"] in src.fqn or src.fqn in m["fqn"]):
                    confidence = 1.0
                    
                discovered_edges.append((
                    repo_id,
                    target_repo_id,
                    r.type.name,
                    src.name,
                    target_symbol,
                    confidence,
                    timestamp
                ))
                
        if discovered_edges:
            self.global_db.executemany(
                """INSERT OR IGNORE INTO cross_repo_edges (
                    source_repo_id, target_repo_id, dependency_type,
                    source_symbol, target_symbol, confidence_score, discovered_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                discovered_edges
            )
            self.global_db.commit()
