"""Dependency injection for bridge_core — single workspace container.

This module provides the WorkspaceDeps dataclass which encapsulates all
per-workspace dependencies (graph, engines, managers) for handler functions.

Unlike the old WorkspaceManager with LRU pools and async complexity,
this is a simple synchronous container instantiated once per process.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from batho.bridge_core.global_registry import GlobalPlatformDeps

from batho.context.codegraph import InMemoryGraph
from batho.context.graph_cache import load_cached_graph
from batho.storage.engine import get_database
from batho.utils.logging import get_logger

LOGGER = get_logger(__name__, component="bridge_core.deps")


def _load_graph_from_database(db: Any, run_id: str) -> InMemoryGraph | None:
    """Load graph using the existing graph_cache API.
    
    This uses the well-tested load_cached_graph function which handles
    decompression, key expansion, and entity file path injection.
    
    Args:
        db: BathoDatabase instance
        run_id: Run UUID
        
    Returns:
        InMemoryGraph or None if loading fails
    """
    from batho.context.graph_cache import load_graph_payload
    
    payload = load_graph_payload(db._repo_root, run_id)
    if payload is None:
        return None
    
    # Convert entities list to entities_by_id dict
    # Map entity_type -> type for Entity schema compatibility
    entities_by_id = {}
    for e in payload.get("entities", []):
        # Copy entity and map entity_type to type
        entity_dict = dict(e)
        if "entity_type" in entity_dict:
            entity_dict["type"] = entity_dict.pop("entity_type")
        entities_by_id[entity_dict.get("id")] = entity_dict
    
    return InMemoryGraph.from_dict({
        "entities_by_id": entities_by_id,
        "relationships": payload.get("relationships", [])
    })


@dataclass
class WorkspaceDeps:
    """Container for all workspace-scoped dependencies.
    
    This is instantiated once per bridge server process and passed to
    all handler functions. All fields are initialized synchronously.
    
    Attributes:
        repo_root: Absolute path to repository root
        graph: Loaded InMemoryGraph with all entities and relationships
        search_engine: Fuzzy search engine over graph entities
        projections: Graph projection engine for L1/L2/L3 views
        spatial: Spatial engine for WebGL layout and viewport culling
        bsg_manager: BSG rule evaluation manager (may be None if no BSG data)
        telemetry: Green telemetry tracker for energy metrics
        run_id: UUID of the index run snapshot
        git_commit: Git commit hash (or None)
        timestamp: Creation/completion timestamp of this snapshot
    """
    repo_root: Path
    graph: InMemoryGraph
    search_engine: Any  # GraphSearchEngine
    projections: Any  # GraphProjectionEngine
    spatial: Any  # SpatialEngine
    bsg_manager: Any | None  # BSGMemoryManager
    telemetry: Any  # GreenTelemetry
    run_id: str = ""
    git_commit: str | None = None
    timestamp: str = ""


def load_workspace_deps(
    repo_root: Path,
    run_id: str | None = None,
    commit_sha: str | None = None
) -> WorkspaceDeps:
    """Load all workspace dependencies from storage v2.0.
    
    This is the primary entry point for initializing a workspace.
    It loads the graph from compressed blobs and initializes all
    engines and managers synchronously.
    
    Args:
        repo_root: Path to repository root (where artifact database lives)
        run_id: Optional snapshot run ID. If neither run_id nor commit_sha is provided, defaults to latest.
        commit_sha: Optional git commit hash to resolve to a run ID.
        
    Returns:
        WorkspaceDeps with all dependencies initialized
        
    Raises:
        FileNotFoundError: If no artifact database exists
        ValueError: If graph cannot be loaded
    """
    from batho.bridge_core.services.graph_projections import GraphProjectionEngine
    from batho.bridge_core.services.search_engine import GraphSearchEngine
    from batho.bridge_core.services.bsg_manager import BSGMemoryManager
    from batho.bridge_core.services.green_telemetry import GreenTelemetry
    from batho.storage.engine import artifact_filename
    
    repo_root = repo_root.resolve()
    
    # Check for artifact database using storage engine naming convention
    db_name = artifact_filename(repo_root)
    db_path = repo_root / db_name
    
    if not db_path.exists():
        raise FileNotFoundError(
            f"No artifact database found at {repo_root}. "
            f"Expected {db_name}. "
            f"Run 'batho build' first."
        )
    
    # Get database and resolve target run
    db = get_database(repo_root)
    
    if run_id is not None:
        target_run_id = run_id
    elif commit_sha is not None:
        target_run_id = resolve_commit_to_run_id(db, commit_sha)
        if not target_run_id:
            raise ValueError(f"Commit SHA {commit_sha} could not be resolved to a completed run")
    else:
        target_run_id = db.get_latest_run_id()
    
    if not target_run_id:
        raise ValueError(f"No completed runs found in database at {repo_root}")
        
    run_info = db.get_run(target_run_id)
    if not run_info:
        raise ValueError(f"Run {target_run_id} not found in database at {repo_root}")
    
    LOGGER.info("loading_workspace", repo_root=str(repo_root), run_id=target_run_id)
    
    # Load graph from compressed blobs using database directly
    graph = _load_graph_from_database(db, target_run_id)
    if not graph:
        raise ValueError(f"Failed to load graph for run {target_run_id}")
    
    LOGGER.info(
        "graph_loaded",
        entities=len(graph.entities),
        relationships=len(graph.relationships),
    )
    
    # Initialize spatial engine (WebGL layout) first - needed by projections
    from batho.bridge_core.services.spatial_engine import SpatialEngine
    spatial = SpatialEngine(graph)
    
    # Initialize other engines
    search_engine = GraphSearchEngine(graph, db=db, run_id=target_run_id)
    projections = GraphProjectionEngine(graph, spatial_engine=spatial)
    telemetry = GreenTelemetry()
    
    # Load BSG blobs if available (skip on error)
    try:
        bsg_manager = _load_bsg_manager(repo_root, graph, target_run_id, db)
    except Exception as e:
        LOGGER.warning("bsg_manager_load_skipped", error=str(e))
        bsg_manager = None
        
    git_commit = run_info.get("git_commit")
    timestamp = run_info.get("completed_at") or run_info.get("started_at") or ""
    
    return WorkspaceDeps(
        repo_root=repo_root,
        graph=graph,
        search_engine=search_engine,
        projections=projections,
        spatial=spatial,
        bsg_manager=bsg_manager,
        telemetry=telemetry,
        run_id=target_run_id,
        git_commit=git_commit,
        timestamp=timestamp,
    )


def _load_bsg_manager(
    repo_root: Path,
    graph: InMemoryGraph,
    run_id: str,
    db: Any
) -> Any | None:
    """Load BSG manager from database blobs.
    
    Args:
        repo_root: Repository root path
        graph: Loaded graph
        run_id: Run UUID
        db: Database instance
        
    Returns:
        BSGMemoryManager or None if no BSG data
    """
    from batho.bridge_core.services.bsg_manager import BSGMemoryManager
    
    try:
        run_internal_id = db.get_run_internal_id(run_id)
        if run_internal_id is None:
            LOGGER.debug("no_bsg_data", reason="run_internal_id_not_found")
            return None
        
        # Get BSG blobs from file_artifacts
        conn = db._get_connection()
        try:
            rows = conn.execute(
                "SELECT bsg_storage_view FROM file_artifacts WHERE run_id = ? AND bsg_storage_view IS NOT NULL",
                (run_internal_id,)
            ).fetchall()
            
            # Collect raw blobs for from_blobs (which handles decompression)
            blobs = []
            for row in rows:
                blob = row["bsg_storage_view"]
                if blob:
                    blobs.append(blob)
            
            if not blobs:
                LOGGER.debug("no_bsg_data", reason="no_blobs_found")
                return None
            
            bsg_manager = BSGMemoryManager.from_blobs(graph, blobs)
            LOGGER.info("bsg_loaded", blob_count=len(blobs))
            return bsg_manager
            
        finally:
            # Connection is managed by database
            pass
            
    except Exception as e:
        LOGGER.warning("bsg_load_failed", error=str(e))
        return None


import contextvars
from contextvars import ContextVar
from collections import OrderedDict

current_deps: ContextVar[WorkspaceDeps] = ContextVar("current_deps")
global_deps_var: ContextVar[GlobalPlatformDeps] = ContextVar("global_deps")


def get_global_deps() -> GlobalPlatformDeps:
    """Get current global platform deps from context.
    
    Returns:
        GlobalPlatformDeps instance
        
    Raises:
        RuntimeError: If global deps have not been set
    """
    try:
        val = global_deps_var.get()
        if val is None:
            raise RuntimeError("No global platform deps available. Server not started with global DB?")
        return val
    except LookupError:
        raise RuntimeError("No global platform deps available. Server not started with global DB?")


def set_global_deps(deps: GlobalPlatformDeps) -> None:
    """Set global platform deps in context-local storage.
    
    Args:
        deps: GlobalPlatformDeps to set
    """
    global_deps_var.set(deps)



def get_current_deps() -> WorkspaceDeps:
    """Get current workspace deps from server context.
    
    This is used by handlers to access the deps when called via MCP/HTTP.
    The server sets this when starting up.
    
    Returns:
        Current WorkspaceDeps instance
        
    Raises:
        RuntimeError: If no deps have been set (server not started)
    """
    try:
        val = current_deps.get()
        if val is None:
            raise RuntimeError("No workspace deps available. Server not started?")
        return val
    except LookupError:
        raise RuntimeError("No workspace deps available. Server not started?")


def set_current_deps(deps: WorkspaceDeps) -> None:
    """Set current workspace deps in context-local storage.
    
    Called by the server when it starts up to make deps available
    to handlers.
    
    Args:
        deps: WorkspaceDeps to set as current
    """
    current_deps.set(deps)


class SnapshotCache:
    """LRU cache for run_id -> WorkspaceDeps mappings."""
    
    def __init__(self, max_size: int = 10):
        self.max_size = max_size
        self._cache: OrderedDict[str, WorkspaceDeps] = OrderedDict()
        self._lock = threading.Lock()
        
    def get(self, repo_root: Path, run_id: str) -> WorkspaceDeps:
        """Get snapshot WorkspaceDeps from cache, or load and cache it.
        
        Uses double-checked locking to ensure thread-safety.
        """
        # First check (lock-free)
        if run_id in self._cache:
            LOGGER.info("snapshot_cache_hit", run_id=run_id)
            with self._lock:
                if run_id in self._cache:
                    deps = self._cache.pop(run_id)
                    self._cache[run_id] = deps
                    return deps
                    
        # Miss - acquire lock
        with self._lock:
            # Double check
            if run_id in self._cache:
                LOGGER.info("snapshot_cache_hit_double_check", run_id=run_id)
                deps = self._cache.pop(run_id)
                self._cache[run_id] = deps
                return deps
                
            LOGGER.info("snapshot_cache_miss", run_id=run_id)
            deps = load_workspace_deps(repo_root, run_id=run_id)
            
            # Cache it
            self._cache[run_id] = deps
            
            # Evict if full
            if len(self._cache) > self.max_size:
                evicted_id, _ = self._cache.popitem(last=False)
                LOGGER.info("snapshot_cache_evict", run_id=evicted_id)
                
            return deps


def resolve_commit_to_run_id(db: Any, commit_sha: str) -> str | None:
    """Query index_runs table for git_commit match (exact or prefix)."""
    with db.connection(read_only=True) as conn:
        # Try exact match first
        row = conn.execute(
            "SELECT run_uuid FROM index_runs WHERE git_commit = ? AND status = 'completed' ORDER BY completed_at DESC LIMIT 1",
            (commit_sha,)
        ).fetchone()
        if row:
            return row["run_uuid"]
            
        # Try prefix match (at least 7 chars)
        if len(commit_sha) >= 7:
            row = conn.execute(
                "SELECT run_uuid FROM index_runs WHERE git_commit LIKE ? AND status = 'completed' ORDER BY completed_at DESC LIMIT 1",
                (f"{commit_sha}%",)
            ).fetchone()
            if row:
                return row["run_uuid"]
                
        return None


def get_snapshot_lineage(db: Any, run_id: str) -> list[dict[str, Any]]:
    """Return ordered list of completed runs from base to current."""
    with db.connection(read_only=True) as conn:
        rows = conn.execute(
            """SELECT run_uuid, completed_at, git_commit 
               FROM index_runs 
               WHERE status = 'completed' 
               ORDER BY completed_at ASC"""
        ).fetchall()
        
        lineage = []
        for r in rows:
            lineage.append({
                "run_id": r["run_uuid"],
                "git_commit": r["git_commit"],
                "timestamp": r["completed_at"],
            })
            if r["run_uuid"] == run_id:
                break
        return lineage


def get_previous_snapshot(db: Any, run_id: str) -> dict[str, Any] | None:
    """Get the chronologically previous completed run in the chain."""
    with db.connection(read_only=True) as conn:
        curr_row = conn.execute(
            "SELECT completed_at FROM index_runs WHERE run_uuid = ?",
            (run_id,)
        ).fetchone()
        if not curr_row or not curr_row["completed_at"]:
            return None
            
        prev_row = conn.execute(
            """SELECT run_uuid, completed_at, git_commit 
               FROM index_runs 
               WHERE status = 'completed' AND completed_at < ? 
               ORDER BY completed_at DESC LIMIT 1""",
            (curr_row["completed_at"],)
        ).fetchone()
        if prev_row:
            return {
                "run_id": prev_row["run_uuid"],
                "git_commit": prev_row["git_commit"],
                "timestamp": prev_row["completed_at"],
            }
        return None


def get_next_snapshot(db: Any, run_id: str) -> dict[str, Any] | None:
    """Get the chronologically next completed run in the chain."""
    with db.connection(read_only=True) as conn:
        curr_row = conn.execute(
            "SELECT completed_at FROM index_runs WHERE run_uuid = ?",
            (run_id,)
        ).fetchone()
        if not curr_row or not curr_row["completed_at"]:
            return None
            
        next_row = conn.execute(
            """SELECT run_uuid, completed_at, git_commit 
               FROM index_runs 
               WHERE status = 'completed' AND completed_at > ? 
               ORDER BY completed_at ASC LIMIT 1""",
            (curr_row["completed_at"],)
        ).fetchone()
        if next_row:
            return {
                "run_id": next_row["run_uuid"],
                "git_commit": next_row["git_commit"],
                "timestamp": next_row["completed_at"],
            }
        return None


def list_all_snapshots(db: Any) -> list[dict[str, Any]]:
    """Return all completed runs with metadata."""
    with db.connection(read_only=True) as conn:
        rows = conn.execute(
            """SELECT run_uuid, completed_at, git_commit, git_branch, entity_count, rel_count, file_count
               FROM index_runs
               WHERE status = 'completed'
               ORDER BY completed_at DESC"""
        ).fetchall()
        return [
            {
                "run_id": r["run_uuid"],
                "git_commit": r["git_commit"],
                "git_branch": r["git_branch"],
                "timestamp": r["completed_at"],
                "entity_count": r["entity_count"],
                "relationship_count": r["rel_count"],
                "file_count": r["file_count"],
            }
            for r in rows
        ]
