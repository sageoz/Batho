"""Spatial handlers - Viewport-based geometry serving.

Provides endpoints for:
- Layout computation (POST /api/v2/spatial/layout)
- Viewport queries (GET /api/v2/spatial/viewport)
- Quadtree metadata (GET /api/v2/spatial/quadtree)
- Binary geometry streaming (GET /api/v2/spatial/viewport.bin)
"""

from __future__ import annotations

from typing import Any, Literal

from batho.bridge_core.deps import WorkspaceDeps
from batho.utils.logging import get_logger

LOGGER = get_logger(__name__, component="bridge_core.handlers.spatial")


def handle_spatial_layout(deps: WorkspaceDeps, params: dict) -> dict:
    """Handle POST /api/v2/spatial/layout
    
    Compute deterministic layout using igraph.
    
    Args:
        deps: Workspace dependencies (contains spatial engine)
        params: Query parameters (optional: layer, algorithm, seed)
        
    Returns:
        dict with layout stats and node count
    """
    layer = params.get("layer", "L1")
    algorithm = params.get("algorithm", "kamada_kawai")
    seed = int(params.get("seed", 42))
    
    # Validate layer
    if layer not in ("L1", "L2", "L3"):
        return {
            "ok": False,
            "error": f"Invalid layer: {layer}. Must be L1, L2, or L3",
        }
    
    # Validate algorithm
    valid_algorithms = ("kamada_kawai", "fruchterman_reingold", "lgl", "drl")
    if algorithm not in valid_algorithms:
        return {
            "ok": False,
            "error": f"Invalid algorithm: {algorithm}. Must be one of {valid_algorithms}",
        }
    
    try:
        result = deps.spatial.compute_layout(
            layer=layer,  # type: ignore
            algorithm=algorithm,  # type: ignore
            seed=seed,
        )
        return result
    except Exception as e:
        LOGGER.error("spatial_layout_error", error=str(e), layer=layer)
        return {
            "ok": False,
            "error": str(e),
        }


def handle_spatial_viewport(deps: WorkspaceDeps, params: dict) -> dict:
    """Handle GET /api/v2/spatial/viewport
    
    Get geometry for viewport bounding box.
    
    Query params:
        x: Viewport center X (required)
        y: Viewport center Y (required)
        width: Viewport width (required)
        height: Viewport height (required)
        zoom: Zoom level (default: 1.0)
        layer: Which layer (default: L1)
        
    Returns:
        dict with nodes, edges, and bounds
    """
    # Required params
    try:
        x = float(params.get("x", 0))
        y = float(params.get("y", 0))
        width = float(params.get("width", 1000))
        height = float(params.get("height", 1000))
    except (TypeError, ValueError) as e:
        return {
            "ok": False,
            "error": f"Invalid numeric parameters: {e}",
        }
    
    # Optional params
    zoom = float(params.get("zoom", 1.0))
    layer = params.get("layer", "L1")
    
    # Validate layer
    if layer not in ("L1", "L2", "L3"):
        return {
            "ok": False,
            "error": f"Invalid layer: {layer}",
        }
    
    try:
        result = deps.spatial.get_viewport(
            x=x,
            y=y,
            width=width,
            height=height,
            zoom=zoom,
            layer=layer,  # type: ignore
        )
        
        # Convert SpatialNode/SpatialEdge to serializable dicts
        if result.get("ok"):
            result["nodes"] = [
                {
                    "id": n.id,
                    "x": n.x,
                    "y": n.y,
                    "size": n.size,
                    "type": n.node_type,
                    "metadata": n.metadata,
                }
                for n in result["nodes"]
            ]
            result["edges"] = [
                {
                    "source": e.source,
                    "target": e.target,
                    "weight": e.weight,
                }
                for e in result["edges"]
            ]
        
        return result
    except Exception as e:
        LOGGER.error("spatial_viewport_error", error=str(e), x=x, y=y)
        return {
            "ok": False,
            "error": str(e),
        }


def handle_spatial_viewport_binary(deps: WorkspaceDeps, params: dict) -> bytes:
    """Handle GET /api/v2/spatial/viewport.bin
    
    Get binary msgpack-encoded geometry for viewport.
    
    Query params: Same as handle_spatial_viewport
    
    Returns:
        Binary msgpack bytes (not JSON response)
    """
    # Required params
    try:
        x = float(params.get("x", 0))
        y = float(params.get("y", 0))
        width = float(params.get("width", 1000))
        height = float(params.get("height", 1000))
    except (TypeError, ValueError):
        # Return binary error
        import msgpack
        return msgpack.packb({"ok": False, "error": "Invalid numeric parameters"})
    
    zoom = float(params.get("zoom", 1.0))
    layer = params.get("layer", "L1")
    
    try:
        binary_data = deps.spatial.encode_viewport_binary(
            x=x,
            y=y,
            width=width,
            height=height,
            zoom=zoom,
            layer=layer,  # type: ignore
        )
        return binary_data
    except Exception as e:
        LOGGER.error("spatial_viewport_binary_error", error=str(e))
        import msgpack
        return msgpack.packb({"ok": False, "error": str(e)})


def handle_spatial_quadtree(deps: WorkspaceDeps, params: dict) -> dict:
    """Handle GET /api/v2/spatial/quadtree
    
    Get quadtree structure metadata.
    
    Returns:
        dict with quadtree depth, bounds, item count
    """
    try:
        result = deps.spatial.get_quadtree_metadata()
        return result
    except Exception as e:
        LOGGER.error("spatial_quadtree_error", error=str(e))
        return {
            "ok": False,
            "error": str(e),
        }


def handle_spatial_node_position(deps: WorkspaceDeps, params: dict) -> dict:
    """Handle GET /api/v2/spatial/node-position
    
    Get coordinates for a specific node.
    
    Query params:
        node_id: Node identifier (required)
        
    Returns:
        dict with x, y coordinates
    """
    node_id = params.get("node_id")
    if not node_id:
        return {
            "ok": False,
            "error": "Missing required parameter: node_id",
        }
    
    try:
        position = deps.spatial.get_node_position(node_id)
        if position is None:
            return {
                "ok": False,
                "error": f"Node not found: {node_id}",
            }
        
        return {
            "ok": True,
            "node_id": node_id,
            "x": position[0],
            "y": position[1],
        }
    except Exception as e:
        LOGGER.error("spatial_node_position_error", error=str(e), node_id=node_id)
        return {
            "ok": False,
            "error": str(e),
        }


__all__ = [
    "handle_spatial_layout",
    "handle_spatial_viewport",
    "handle_spatial_viewport_binary",
    "handle_spatial_quadtree",
    "handle_spatial_node_position",
]
