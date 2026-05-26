"""Context handlers — Cursor position and context amnesia analysis.

Provides context extraction at specific file/line positions and
analyzes what context would be missed by LLM token budget constraints.
"""

from __future__ import annotations

from typing import Any

from batho.bridge_core.deps import WorkspaceDeps
from batho.bridge_core.services.amnesia import ContextAmnesiaAnalyzer
from batho.utils.logging import get_logger

LOGGER = get_logger(__name__, component="bridge_core.handlers.context")


def handle_context_at_position(deps: WorkspaceDeps, params: dict) -> dict:
    """Handle GET /api/context
    
    Get context for a specific cursor position (file + line).
    
    Args:
        deps: Workspace dependencies (contains projections engine)
        params: Query parameters:
            - file: File path (required)
            - line: Line number (required)
            
    Returns:
        dict with enclosing_entity, parent_scope, immediate_deps
    """
    file_path = params.get("file")
    line_str = params.get("line")
    
    if not file_path:
        return {
            "ok": False,
            "error": "Missing required parameter: file",
            "data": {},
        }
    
    if not line_str:
        return {
            "ok": False,
            "error": "Missing required parameter: line",
            "data": {},
        }
    
    try:
        line_number = int(line_str)
    except ValueError:
        return {
            "ok": False,
            "error": f"Invalid line number: {line_str}",
            "data": {},
        }
    
    try:
        result = deps.projections.get_context_at_position(file_path, line_number)
        return {
            "ok": True,
            "data": result,
        }
    except Exception as e:
        LOGGER.error("context_error", error=str(e), file=file_path, line=line_number)
        return {
            "ok": False,
            "error": str(e),
            "data": {"file": file_path, "line": line_number, "enclosing_entity": None},
        }


def handle_context_amnesia(deps: WorkspaceDeps, params: dict) -> dict:
    """Handle POST /api/v2/context/amnesia
    
    Analyze context amnesia — what entities would be missed due to LLM token budget.
    
    This is the "Cure for Context Amnesia" USP feature that shows which
    dependencies are outside the LLM's context window.
    
    Args:
        deps: Workspace dependencies (contains graph)
        params: Request body:
            - node_id: Center node to analyze (required)
            - budget: Token budget in tokens (default: 4000)
            
    Returns:
        dict with within_reach, amnesia_zone, critical_misses
    """
    node_id = params.get("node_id")
    if not node_id:
        return {
            "ok": False,
            "error": "Missing required parameter: node_id",
            "data": {},
        }
    
    budget = int(params.get("budget", 4000))
    
    try:
        # Use ContextAmnesiaAnalyzer
        analyzer = ContextAmnesiaAnalyzer(deps.graph)
        analysis = analyzer.analyze(node_id, context_limit=budget)
        
        return {
            "ok": True,
            "data": {
                "center_node": analysis.center_node,
                "within_reach": analysis.within_reach,
                "amnesia_zone": analysis.amnesia_zone,
                "critical_misses": analysis.critical_misses,
                "coverage_percent": analysis.coverage_percent,
                "budget_tokens": budget,
            },
        }
    except Exception as e:
        LOGGER.error("context_amnesia_error", error=str(e), node_id=node_id)
        return {
            "ok": False,
            "error": str(e),
            "data": {
                "center_node": node_id,
                "within_reach": [],
                "amnesia_zone": [],
                "critical_misses": [],
                "coverage_percent": 0,
            },
        }


__all__ = [
    "handle_context_at_position",
    "handle_context_amnesia",
]
