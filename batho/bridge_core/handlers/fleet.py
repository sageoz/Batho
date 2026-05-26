"""Fleet handlers — global registry and router API endpoints."""

from __future__ import annotations

from typing import Any
from batho.bridge_core.deps import get_global_deps, WorkspaceDeps
from batho.utils.logging import get_logger

LOGGER = get_logger(__name__, component="bridge_core.handlers.fleet")


def handle_fleet_overview(deps: WorkspaceDeps | None, params: dict) -> dict:
    """GET /api/v1/fleet/overview
    
    Returns:
        Fleet overview including workspaces, edges, and metrics.
    """
    try:
        global_deps = get_global_deps()
        overview = global_deps.get_fleet_overview()
        return {
            "ok": True,
            "data": overview
        }
    except Exception as e:
        LOGGER.error("handle_fleet_overview_error", error=str(e))
        return {
            "ok": False,
            "error": f"Failed to get fleet overview: {str(e)}"
        }


def handle_global_search(deps: WorkspaceDeps | None, params: dict) -> dict:
    """GET /api/v1/search/global
    
    Query Params:
        q or query: Search query
        type: Optional symbol type
    """
    query = params.get("q") or params.get("query")
    symbol_type = params.get("type") or params.get("symbol_type")
    
    if not query:
        return {
            "ok": False,
            "error": "Query parameter 'q' or 'query' is required"
        }
        
    try:
        global_deps = get_global_deps()
        results = global_deps.search_symbols_global(query, symbol_type)
        return {
            "ok": True,
            "data": {
                "results": results
            }
        }
    except Exception as e:
        LOGGER.error("handle_global_search_error", error=str(e))
        return {
            "ok": False,
            "error": f"Global search failed: {str(e)}"
        }


def handle_fleet_impact(deps: WorkspaceDeps | None, params: dict) -> dict:
    """GET /api/v1/fleet/impact
    
    Query Params:
        repo_id: ID of the workspace (int)
        symbol_name: Name of the symbol to analyze
    """
    repo_id_raw = params.get("repo_id")
    symbol_name = params.get("symbol_name")
    
    if not repo_id_raw or not symbol_name:
        return {
            "ok": False,
            "error": "Parameters 'repo_id' and 'symbol_name' are required"
        }
        
    try:
        repo_id = int(repo_id_raw)
    except (ValueError, TypeError):
        return {
            "ok": False,
            "error": "Parameter 'repo_id' must be an integer"
        }
        
    try:
        global_deps = get_global_deps()
        impact = global_deps.get_cross_repo_impact(repo_id, symbol_name)
        return {
            "ok": True,
            "data": {
                "impact": impact
            }
        }
    except Exception as e:
        LOGGER.error("handle_fleet_impact_error", error=str(e))
        return {
            "ok": False,
            "error": f"Impact analysis failed: {str(e)}"
        }
