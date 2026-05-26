"""Graph projection handlers — L1/L2/L3 hypergraph views.

These handlers provide the core graph projection capabilities:
- L1: File-level aggregated graph
- L2: Intra-file symbol graph  
- L3: Node neighborhood with bidirectional emphasis
"""

from __future__ import annotations

from typing import Any

from batho.bridge_core.deps import WorkspaceDeps
from batho.utils.logging import get_logger

LOGGER = get_logger(__name__, component="bridge_core.handlers.graph")


def handle_hypergraph_l1(deps: WorkspaceDeps, params: dict) -> dict:
    """Handle GET /api/v2/hypergraph/level1
    
    Returns file-level aggregated graph showing cross-file dependencies.
    
    Args:
        deps: Workspace dependencies (contains projections engine)
        params: Query parameters (optional: languages, path filters)
        
    Returns:
        dict with keys: nodes, edges, stats
    """
    filters = {}
    if "languages" in params:
        filters["languages"] = params["languages"].split(",") if isinstance(params["languages"], str) else params["languages"]
    if "path" in params:
        filters["path"] = params["path"]
    
    try:
        result = deps.projections.build_level1(filters if filters else None)
        return {
            "ok": True,
            "data": result,
        }
    except Exception as e:
        LOGGER.error("hypergraph_l1_error", error=str(e))
        return {
            "ok": False,
            "error": str(e),
            "data": {"nodes": [], "edges": [], "stats": {"error": str(e)}},
        }


def handle_hypergraph_l2(deps: WorkspaceDeps, params: dict) -> dict:
    """Handle GET /api/v2/hypergraph/level2
    
    Returns intra-file symbol graph for detailed file view.
    
    Args:
        deps: Workspace dependencies
        params: Query parameters (required: file; optional: budget)
        
    Returns:
        dict with keys: nodes, edges, file, pagination
    """
    file_path = params.get("file")
    if not file_path:
        return {
            "ok": False,
            "error": "Missing required parameter: file",
            "data": {},
        }
    
    budget = int(params.get("budget", 2000))
    
    try:
        result = deps.projections.build_level2(file_path, budget=budget)
        return {
            "ok": True,
            "data": result,
        }
    except Exception as e:
        LOGGER.error("hypergraph_l2_error", error=str(e), file=file_path)
        return {
            "ok": False,
            "error": str(e),
            "data": {"nodes": [], "edges": [], "file": file_path},
        }


def handle_hypergraph_l3(deps: WorkspaceDeps, params: dict) -> dict:
    """Handle GET /api/v2/hypergraph/level3
    
    Returns node neighborhood with bidirectional emphasis (calls/called_by).
    
    Args:
        deps: Workspace dependencies
        params: Query parameters (required: node_id; optional: radius)
        
    Returns:
        dict with keys: center, outbound, inbound, bidirectional, all_neighbors
    """
    node_id = params.get("node_id")
    if not node_id:
        return {
            "ok": False,
            "error": "Missing required parameter: node_id",
            "data": {},
        }
    
    radius = min(int(params.get("radius", 1)), 3)
    
    try:
        result = deps.projections.build_level3(node_id, radius=radius)
        
        # Add metadata if center exists
        if "center" in result and result["center"]:
            center = deps.graph.get_entity(node_id)
            if center:
                result["center"]["metadata"] = {
                    "content_hash": getattr(center, "content_hash", None),
                    "type": getattr(center, "ast_node_type", getattr(center, "type", None)),
                    "signature": getattr(center, "signature", None),
                }
        
        return {
            "ok": True,
            "data": result,
        }
    except Exception as e:
        LOGGER.error("hypergraph_l3_error", error=str(e), node_id=node_id)
        return {
            "ok": False,
            "error": str(e),
            "data": {"error": str(e), "center_id": node_id},
        }


__all__ = [
    "handle_hypergraph_l1",
    "handle_hypergraph_l2",
    "handle_hypergraph_l3",
]
