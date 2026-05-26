"""Batho Bridge Core — Single-workspace API server for graph queries.

This is the new, simplified bridge architecture that replaces the complex
WorkspaceManager-based multi-workspace system with a single-workspace,
storage-v2 native implementation.

Usage:
    from batho.bridge_core import WorkspaceDeps, load_workspace_deps
    
    deps = load_workspace_deps(Path("/path/to/repo"))
    result = handle_hypergraph_l1(deps, {"languages": ["python"]})
"""

from batho.bridge_core.deps import WorkspaceDeps, load_workspace_deps
from batho.bridge_core.server import BridgeServer

__version__ = "2.0.0"

__all__ = [
    "WorkspaceDeps",
    "load_workspace_deps",
    "BridgeServer",
]
