"""Bridge Core Handlers — Pure function request handlers.

All handlers follow the signature:
    def handle_<name>(deps: WorkspaceDeps, params: dict) -> dict

This module exports the dispatch function which routes requests
to the appropriate handler based on method and path.
"""

from __future__ import annotations

from typing import Any, Callable

from batho.bridge_core.deps import WorkspaceDeps
from batho.bridge_core.handlers.graph import handle_hypergraph_l1, handle_hypergraph_l2, handle_hypergraph_l3
from batho.bridge_core.handlers.search import handle_search
from batho.bridge_core.handlers.bsg import handle_bsg_evaluate, handle_bsg_plugins, handle_bsg_rules, handle_bsg_gaps
from batho.bridge_core.handlers.context import handle_context_at_position, handle_context_amnesia
from batho.bridge_core.handlers.health import handle_healthz, handle_readyz, handle_metrics
from batho.bridge_core.handlers.file import handle_file_content
from batho.bridge_core.handlers.outline import handle_file_outline
from batho.bridge_core.handlers.fs import handle_fs_browse
from batho.bridge_core.services.snippets import handle_agent_snippet
from batho.bridge_core.handlers.fleet import handle_fleet_overview, handle_global_search, handle_fleet_impact
from batho.bridge_core.handlers.spatial import (
    handle_spatial_layout,
    handle_spatial_viewport,
    handle_spatial_quadtree,
    handle_spatial_node_position,
)


# Handler registry
GET_HANDLERS: dict[str, Callable[[WorkspaceDeps, dict], dict]] = {
    # Graph projections
    "/api/v2/hypergraph/level1": handle_hypergraph_l1,
    "/api/v2/hypergraph/level2": handle_hypergraph_l2,
    "/api/v2/hypergraph/level3": handle_hypergraph_l3,
    
    # Search
    "/api/v2/search": handle_search,
    
    # BSG
    "/api/v2/bsg/plugins": handle_bsg_plugins,
    "/api/v2/bsg/rules": handle_bsg_rules,
    "/api/v2/bsg/gaps": handle_bsg_gaps,
    
    # Context
    "/api/context": handle_context_at_position,
    
    # Health
    "/healthz": handle_healthz,
    "/readyz": handle_readyz,
    "/metrics": handle_metrics,
    

    
    # File service
    "/api/v2/file/content": handle_file_content,
    "/api/v2/file/outline": handle_file_outline,
    
    # FS browse
    "/api/v2/fs/browse": handle_fs_browse,
    
    # Agent snippets
    "/api/v2/snippets": handle_agent_snippet,
    
    # Fleet endpoints
    "/api/v1/fleet/overview": handle_fleet_overview,
    "/api/v1/search/global": handle_global_search,
    "/api/v1/fleet/impact": handle_fleet_impact,
    
    # Spatial / WebGL viewport endpoints
    "/api/v2/spatial/viewport": handle_spatial_viewport,
    "/api/v2/spatial/quadtree": handle_spatial_quadtree,
    "/api/v2/spatial/node-position": handle_spatial_node_position,
}

POST_HANDLERS: dict[str, Callable[[WorkspaceDeps, dict], dict]] = {
    # BSG evaluation (POST for complex queries)
    "/api/v2/bsg/evaluate": handle_bsg_evaluate,
    
    # Context amnesia (POST for complex analysis)
    "/api/v2/context/amnesia": handle_context_amnesia,
    
    # Spatial layout computation (POST for layout trigger)
    "/api/v2/spatial/layout": handle_spatial_layout,
}


def dispatch(method: str, path: str, deps: WorkspaceDeps | None = None, params: dict | None = None) -> dict:
    """Dispatch a request to the appropriate handler.
    
    Args:
        method: HTTP method (GET, POST)
        path: URL path
        deps: Workspace dependencies. If None, retrieves from contextvars context.
        params: Request parameters (query or body)
        
    Returns:
        Handler response dict
        
    Raises:
        KeyError: If no handler registered for path
    """
    if deps is None:
        from batho.bridge_core.deps import get_current_deps
        try:
            deps = get_current_deps()
        except RuntimeError:
            # Let deps remain None if we are calling a fleet endpoint
            if path not in ("/api/v1/fleet/overview", "/api/v1/search/global", "/api/v1/fleet/impact"):
                raise
        
    if params is None:
        params = {}
        
    handlers = GET_HANDLERS if method == "GET" else POST_HANDLERS
    
    # Normalize path
    if not path.startswith("/api/") and path != "/":
        # Try to match API paths
        for key in handlers:
            if key.endswith(path) or path.endswith(key.split("/")[-1]):
                path = key
                break
    
    if path not in handlers:
        raise KeyError(f"No handler registered for {method} {path}")
    
    handler = handlers[path]
    
    # Track with telemetry if deps has it
    if deps and hasattr(deps, "telemetry") and deps.telemetry:
        with deps.telemetry.track(handler.__name__):
            return handler(deps, params)
    else:
        return handler(deps, params)


def get_handler(method: str, path: str) -> Callable[[WorkspaceDeps, dict], dict] | None:
    """Get handler function for method/path without invoking.
    
    Args:
        method: HTTP method
        path: URL path
        
    Returns:
        Handler function or None if not found
    """
    handlers = GET_HANDLERS if method == "GET" else POST_HANDLERS
    return handlers.get(path)


__all__ = [
    "dispatch",
    "get_handler",
    "GET_HANDLERS",
    "POST_HANDLERS",
]
