"""Search handler — Fuzzy entity search.

Provides trigram-based fuzzy search over entity names and FQNs.
"""

from __future__ import annotations

from typing import Any

from batho.bridge_core.deps import WorkspaceDeps
from batho.utils.logging import get_logger

LOGGER = get_logger(__name__, component="bridge_core.handlers.search")


def handle_search(deps: WorkspaceDeps, params: dict) -> dict:
    """Handle GET /api/v2/search
    
    Fuzzy search over entity names and FQNs.
    
    Args:
        deps: Workspace dependencies (contains search_engine)
        params: Query parameters:
            - q: Search query string (required)
            - kinds: Comma-separated entity type filters (optional)
            - limit: Max results (default: 50, max: 100)
            
    Returns:
        dict with keys: results, total, query
    """
    query = params.get("q")
    if not query:
        return {
            "ok": True,
            "data": {
                "results": [],
                "total": 0,
                "query": "",
            },
        }
    
    limit = min(int(params.get("limit", 50)), 100)
    
    kinds = None
    if "kinds" in params:
        kinds_str = params["kinds"]
        kinds = kinds_str.split(",") if isinstance(kinds_str, str) else kinds_str
    
    try:
        results = deps.search_engine.search(query, kinds=kinds, limit=limit)
        return {
            "ok": True,
            "data": {
                "results": results,
                "total": len(results),
                "query": query,
            },
        }
    except Exception as e:
        LOGGER.error("search_error", error=str(e), query=query)
        return {
            "ok": False,
            "error": str(e),
            "data": {
                "results": [],
                "total": 0,
                "query": query,
            },
        }


__all__ = ["handle_search"]
