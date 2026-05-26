"""BSG handlers — Bidirectional Sync Graph rule evaluation.

Provides policy evaluation, plugin catalog, and rule management.
"""

from __future__ import annotations

from typing import Any

from batho.bridge_core.deps import WorkspaceDeps
from batho.utils.logging import get_logger

LOGGER = get_logger(__name__, component="bridge_core.handlers.bsg")


def handle_bsg_evaluate(deps: WorkspaceDeps, params: dict) -> dict:
    """Handle POST /api/v2/bsg/evaluate
    
    Evaluate BSG rules against the graph.
    
    Args:
        deps: Workspace dependencies (contains bsg_manager)
        params: Request body (optional: file_path to limit to one file)
        
    Returns:
        dict with compliance score and violations
    """
    if deps.bsg_manager is None:
        return {
            "ok": False,
            "error": "BSG data not available for this workspace",
            "data": {"compliant": True, "score": 100, "violations": []},
        }
    
    file_path = params.get("file_path")
    
    try:
        if file_path:
            gaps = deps.bsg_manager.evaluate_for_file(file_path)
        else:
            gaps = deps.bsg_manager.evaluate_all()
        
        violations = [
            {
                "rule": g.rule,
                "severity": g.severity,
                "file": g.file,
                "line": g.line,
                "message": g.message,
                "remediation": g.remediation,
            }
            for g in gaps
        ]
        
        errors = sum(1 for v in violations if v["severity"] == "error")
        score = max(0, 100 - (errors * 10))
        
        return {
            "ok": True,
            "data": {
                "compliant": errors == 0,
                "score": score,
                "violations": violations,
                "total_violations": len(violations),
            },
        }
    except Exception as e:
        LOGGER.error("bsg_evaluate_error", error=str(e))
        return {
            "ok": False,
            "error": str(e),
            "data": {"compliant": False, "score": 0, "violations": []},
        }


def handle_bsg_plugins(deps: WorkspaceDeps, params: dict) -> dict:
    """Handle GET /api/v2/bsg/plugins
    
    Return BSG plugin catalog with current stats.
    
    Args:
        deps: Workspace dependencies
        params: Query parameters (none currently)
        
    Returns:
        dict with plugins list and totals
    """
    if deps.bsg_manager is None:
        return {
            "ok": True,
            "data": {
                "plugins": [],
                "total_rules": 0,
                "total_hits": 0,
            },
        }
    
    try:
        # Evaluate all to populate hits
        deps.bsg_manager.evaluate_all()
        plugins = deps.bsg_manager.get_plugins_catalog()
        
        return {
            "ok": True,
            "data": {
                "plugins": [
                    {
                        "plugin_id": p.plugin_id,
                        "category": p.category,
                        "version": p.version,
                        "rules_count": p.rules_count,
                        "hits": p.hits,
                    }
                    for p in plugins
                ],
                "total_rules": sum(p.rules_count for p in plugins),
                "total_hits": sum(p.hits for p in plugins),
            },
        }
    except Exception as e:
        LOGGER.error("bsg_plugins_error", error=str(e))
        return {
            "ok": False,
            "error": str(e),
            "data": {"plugins": [], "total_rules": 0, "total_hits": 0},
        }


def handle_bsg_rules(deps: WorkspaceDeps, params: dict) -> dict:
    """Handle GET /api/v2/bsg/rules
    
    Return BSG rules with execution statistics.
    
    Args:
        deps: Workspace dependencies
        params: Query parameters (optional: plugin, severity filters)
        
    Returns:
        dict with rules list and filters applied
    """
    if deps.bsg_manager is None:
        return {
            "ok": True,
            "data": {
                "rules": [],
                "total": 0,
                "filters_applied": None,
            },
        }
    
    filters = {}
    if "plugin" in params:
        filters["plugin"] = params["plugin"]
    if "severity" in params:
        filters["severity"] = params["severity"]
    
    try:
        deps.bsg_manager.evaluate_all()
        rules = deps.bsg_manager.get_rules_with_stats(filters if filters else None)
        
        return {
            "ok": True,
            "data": {
                "rules": rules,
                "total": len(rules),
                "filters_applied": filters if filters else None,
            },
        }
    except Exception as e:
        LOGGER.error("bsg_rules_error", error=str(e))
        return {
            "ok": False,
            "error": str(e),
            "data": {"rules": [], "total": 0},
        }


def handle_bsg_gaps(deps: WorkspaceDeps, params: dict) -> dict:
    """Handle GET /api/v2/bsg/gaps
    
    Return policy gaps (violations) found in the codebase.
    
    Args:
        deps: Workspace dependencies
        params: Query parameters (optional: file filter)
        
    Returns:
        dict with gaps list and severity breakdown
    """
    if deps.bsg_manager is None:
        return {
            "ok": True,
            "data": {
                "gaps": [],
                "total": 0,
                "by_severity": {"error": 0, "warning": 0, "info": 0},
            },
        }
    
    file_path = params.get("file")
    
    try:
        if file_path:
            gaps = deps.bsg_manager.evaluate_for_file(file_path)
        else:
            gaps = deps.bsg_manager.evaluate_all()
        
        by_severity = {"error": 0, "warning": 0, "info": 0}
        for gap in gaps:
            sev = gap.severity
            by_severity[sev] = by_severity.get(sev, 0) + 1
        
        return {
            "ok": True,
            "data": {
                "gaps": [
                    {
                        "rule": g.rule,
                        "severity": g.severity,
                        "file": g.file,
                        "line": g.line,
                        "message": g.message,
                        "remediation": g.remediation,
                    }
                    for g in gaps
                ],
                "total": len(gaps),
                "by_severity": by_severity,
            },
        }
    except Exception as e:
        LOGGER.error("bsg_gaps_error", error=str(e))
        return {
            "ok": False,
            "error": str(e),
            "data": {"gaps": [], "total": 0, "by_severity": {"error": 0, "warning": 0, "info": 0}},
        }


__all__ = [
    "handle_bsg_evaluate",
    "handle_bsg_plugins",
    "handle_bsg_rules",
    "handle_bsg_gaps",
]
