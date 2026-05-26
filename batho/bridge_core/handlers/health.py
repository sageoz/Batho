"""Health check handlers — Server status and telemetry.

Provides standard health endpoints and green telemetry metrics.
"""

from __future__ import annotations

from typing import Any

from batho.bridge_core.deps import WorkspaceDeps


def handle_healthz(deps: WorkspaceDeps, params: dict) -> dict:
    """Handle GET /healthz
    
    Basic health check — is the server alive?
    
    Returns:
        dict with status: ok
    """
    return {
        "ok": True,
        "data": {
            "status": "ok",
            "graph_entities": len(deps.graph.entities),
            "graph_relationships": len(deps.graph.relationships),
        },
    }


def handle_readyz(deps: WorkspaceDeps, params: dict) -> dict:
    """Handle GET /readyz
    
    Readiness check — is the workspace loaded and ready?
    
    Returns:
        dict with status: ready or not_ready
    """
    graph_loaded = deps.graph is not None and len(deps.graph.entities) > 0
    
    return {
        "ok": True,
        "data": {
            "status": "ready" if graph_loaded else "not_ready",
            "graph_loaded": graph_loaded,
            "entity_count": len(deps.graph.entities) if deps.graph else 0,
        },
    }


def handle_metrics(deps: WorkspaceDeps, params: dict) -> dict:
    """Handle GET /metrics
    
    Return telemetry metrics including green energy estimates.
    
    Returns:
        dict with request stats and carbon estimates
    """
    telemetry_stats = deps.telemetry.get_stats()
    
    return {
        "ok": True,
        "data": {
            "requests": telemetry_stats,
            "graph": {
                "entities": len(deps.graph.entities),
                "relationships": len(deps.graph.relationships),
                "files": len(set(e.file for e in deps.graph.entities.values())),
            },
            "bsg": {
                "available": deps.bsg_manager is not None,
            },
        },
    }


__all__ = [
    "handle_healthz",
    "handle_readyz",
    "handle_metrics",
]
