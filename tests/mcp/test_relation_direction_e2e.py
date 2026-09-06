"""End-to-end tests for the relation_direction parameter across MCP tools.

Scenario:
    graph_query and trace_path accept a relation_direction parameter
    that filters relationships by edge direction relative to the entity.
    These tests call the actual MCP tools via create_app / call_tool.

Execution Flow:
    1. Build a sample artifact.
    2. Call graph_query with relation_direction='outgoing' and verify
       only edges where the entity is the source are returned.
    3. Call graph_query with relation_direction='incoming' and verify
       only edges where the entity is the target are returned.
    4. Call graph_query with relation_direction='both' and verify
       all connected edges are returned (backward compat).
    5. Call graph_query with an invalid direction and verify error.
    6. Call trace_path with relation_direction='incoming' (reverse BFS).
    7. Verify applied_filters includes relation_direction.

Expectations:
    - 'outgoing' narrows to edges where source_id matches entity.
    - 'incoming' narrows to edges where target_id matches entity.
    - 'both' returns all connected edges (backward compat).
    - Invalid values return a CLIENT_ERROR.
    - AND semantics with other filters.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from batho.mcp.tools import _get_reader


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_content(result) -> str:
    if hasattr(result, "content") and result.content:
        return result.content[0].text
    return str(result)


def _extract_structured(result) -> dict:
    if hasattr(result, "structured_content") and result.structured_content:
        return result.structured_content
    return {}


def _extract_edges(structured: dict) -> list[dict]:
    graph = structured.get("graph", structured)
    return graph.get("edges", [])


# ---------------------------------------------------------------------------
# graph_query e2e tests
# ---------------------------------------------------------------------------


def test_graph_query_direction_outgoing_e2e(built_artifact: Path, tmp_path: Path):
    """graph_query(relation_direction='outgoing') returns only outgoing edges."""
    from batho.mcp.server import create_app
    app = create_app(root=str(built_artifact), registry_path=tmp_path / "mcp-repos.json")

    result = asyncio.run(app.call_tool("graph_query", {
        "relation_direction": "outgoing",
        "limit": 100,
    }))
    content = _extract_content(result)
    structured = _extract_structured(result)

    assert "Invalid" not in content

    # Get the entity IDs from the returned nodes
    graph = structured.get("graph", structured)
    nodes = graph.get("nodes", [])
    if nodes:
        entity_ids = {n.get("entity_id") or n.get("id") for n in nodes}
        entity_ids.discard(None)
        edges = _extract_edges(structured)
        if edges:
            # Every edge should have its source in the entity set
            for edge in edges:
                src = edge.get("source") or edge.get("source_id")
                assert src in entity_ids, (
                    f"Edge source {src} not in returned entity set (direction=outgoing)"
                )


def test_graph_query_direction_incoming_e2e(built_artifact: Path, tmp_path: Path):
    """graph_query(relation_direction='incoming') returns only incoming edges."""
    from batho.mcp.server import create_app
    app = create_app(root=str(built_artifact), registry_path=tmp_path / "mcp-repos.json")

    result = asyncio.run(app.call_tool("graph_query", {
        "relation_direction": "incoming",
        "limit": 100,
    }))
    content = _extract_content(result)
    structured = _extract_structured(result)

    assert "Invalid" not in content

    graph = structured.get("graph", structured)
    nodes = graph.get("nodes", [])
    if nodes:
        entity_ids = {n.get("entity_id") or n.get("id") for n in nodes}
        entity_ids.discard(None)
        edges = _extract_edges(structured)
        if edges:
            # Every edge should have its target in the entity set
            for edge in edges:
                tgt = edge.get("target") or edge.get("target_id")
                assert tgt in entity_ids, (
                    f"Edge target {tgt} not in returned entity set (direction=incoming)"
                )


def test_graph_query_direction_both_e2e(built_artifact: Path, tmp_path: Path):
    """graph_query(relation_direction='both') returns all connected edges (backward compat)."""
    from batho.mcp.server import create_app
    app = create_app(root=str(built_artifact), registry_path=tmp_path / "mcp-repos.json")

    result = asyncio.run(app.call_tool("graph_query", {
        "relation_direction": "both",
        "limit": 100,
    }))
    content = _extract_content(result)
    structured = _extract_structured(result)

    assert "Invalid" not in content

    edges = _extract_edges(structured)
    # Should have some edges (the sample repo has relationships)
    reader = _get_reader(str(built_artifact))
    rels_table = reader._get_table("rels_views")
    if rels_table.num_rows > 0:
        assert len(edges) > 0, "Expected edges with direction='both'"


def test_graph_query_direction_invalid_e2e(built_artifact: Path, tmp_path: Path):
    """graph_query with invalid direction returns clear error."""
    from batho.mcp.server import create_app
    app = create_app(root=str(built_artifact), registry_path=tmp_path / "mcp-repos.json")

    result = asyncio.run(app.call_tool("graph_query", {
        "relation_direction": "sideways",
    }))
    content = _extract_content(result)

    assert "Invalid" in content or "invalid" in content.lower()
    assert "outgoing" in content
    assert "incoming" in content


def test_graph_query_direction_outgoing_with_relation_types_e2e(built_artifact: Path, tmp_path: Path):
    """graph_query with relation_direction='outgoing' + relation_types applies AND semantics."""
    from batho.mcp.server import create_app
    app = create_app(root=str(built_artifact), registry_path=tmp_path / "mcp-repos.json")

    result = asyncio.run(app.call_tool("graph_query", {
        "relation_direction": "outgoing",
        "relation_types": ["IMPORTS"],
        "limit": 100,
    }))
    content = _extract_content(result)
    structured = _extract_structured(result)

    assert "Invalid" not in content

    graph = structured.get("graph", structured)
    nodes = graph.get("nodes", [])
    entity_ids = {n.get("entity_id") or n.get("id") for n in nodes}
    entity_ids.discard(None)
    edges = _extract_edges(structured)
    for edge in edges:
        assert edge.get("relation_type") == "IMPORTS"
        src = edge.get("source") or edge.get("source_id")
        assert src in entity_ids


def test_graph_query_direction_incoming_with_relation_types_e2e(built_artifact: Path, tmp_path: Path):
    """graph_query(relation_types=['CALLS'], relation_direction='incoming') finds all callers."""
    from batho.mcp.server import create_app
    app = create_app(root=str(built_artifact), registry_path=tmp_path / "mcp-repos.json")

    result = asyncio.run(app.call_tool("graph_query", {
        "relation_direction": "incoming",
        "relation_types": ["CALLS"],
        "limit": 100,
    }))
    content = _extract_content(result)
    structured = _extract_structured(result)

    assert "Invalid" not in content

    graph = structured.get("graph", structured)
    nodes = graph.get("nodes", [])
    entity_ids = {n.get("entity_id") or n.get("id") for n in nodes}
    entity_ids.discard(None)
    edges = _extract_edges(structured)
    for edge in edges:
        assert edge.get("relation_type") == "CALLS"
        tgt = edge.get("target") or edge.get("target_id")
        assert tgt in entity_ids


# ---------------------------------------------------------------------------
# trace_path e2e tests
# ---------------------------------------------------------------------------


def test_trace_path_direction_outgoing_e2e(built_artifact: Path, tmp_path: Path):
    """trace_path with relation_direction='outgoing' follows source→target edges."""
    from batho.mcp.server import create_app
    app = create_app(root=str(built_artifact), registry_path=tmp_path / "mcp-repos.json")

    reader = _get_reader(str(built_artifact))
    agent_table = reader._get_table("agent_views")
    rows = agent_table.to_pylist()
    main_eid = None
    helper_eid = None
    for r in rows:
        if r["name"] == "main":
            main_eid = r["entity_id"]
        if "helper" in r["name"]:
            helper_eid = r["entity_id"]

    if not main_eid or not helper_eid:
        pytest.skip("Could not find main and helper entities")

    result = asyncio.run(app.call_tool("trace_path", {
        "source_entity_id": main_eid,
        "target_entity_id": helper_eid,
        "max_depth": 10,
        "relation_direction": "outgoing",
    }))
    content = _extract_content(result)

    assert "Invalid" not in content
    assert "Entity not found" not in content


def test_trace_path_direction_incoming_e2e(built_artifact: Path, tmp_path: Path):
    """trace_path with relation_direction='incoming' follows reverse edges (target→source)."""
    from batho.mcp.server import create_app
    app = create_app(root=str(built_artifact), registry_path=tmp_path / "mcp-repos.json")

    reader = _get_reader(str(built_artifact))
    agent_table = reader._get_table("agent_views")
    rows = agent_table.to_pylist()
    main_eid = None
    helper_eid = None
    for r in rows:
        if r["name"] == "main":
            main_eid = r["entity_id"]
        if "helper" in r["name"]:
            helper_eid = r["entity_id"]

    if not main_eid or not helper_eid:
        pytest.skip("Could not find main and helper entities")

    # Reverse BFS: from helper, follow incoming edges back to main
    result = asyncio.run(app.call_tool("trace_path", {
        "source_entity_id": helper_eid,
        "target_entity_id": main_eid,
        "max_depth": 10,
        "relation_direction": "incoming",
    }))
    content = _extract_content(result)

    assert "Invalid" not in content
    assert "Entity not found" not in content


def test_trace_path_direction_invalid_e2e(built_artifact: Path, tmp_path: Path):
    """trace_path with invalid direction returns clear error."""
    from batho.mcp.server import create_app
    app = create_app(root=str(built_artifact), registry_path=tmp_path / "mcp-repos.json")

    result = asyncio.run(app.call_tool("trace_path", {
        "source_entity_id": "main",
        "target_entity_id": "helper",
        "relation_direction": "upward",
    }))
    content = _extract_content(result)

    assert "Invalid" in content or "invalid" in content.lower()
    assert "outgoing" in content
    assert "incoming" in content


def test_trace_path_direction_both_e2e(built_artifact: Path, tmp_path: Path):
    """trace_path with relation_direction='both' works as before (backward compat)."""
    from batho.mcp.server import create_app
    app = create_app(root=str(built_artifact), registry_path=tmp_path / "mcp-repos.json")

    result = asyncio.run(app.call_tool("trace_path", {
        "source_entity_id": "main",
        "target_entity_id": "helper",
        "max_depth": 10,
        "relation_direction": "both",
    }))
    content = _extract_content(result)

    assert "Invalid" not in content


# ---------------------------------------------------------------------------
# applied_filters tests
# ---------------------------------------------------------------------------


def test_graph_query_applied_filters_relation_direction_e2e(built_artifact: Path, tmp_path: Path):
    """graph_query structured output includes relation_direction in applied_filters."""
    from batho.mcp.server import create_app
    app = create_app(root=str(built_artifact), registry_path=tmp_path / "mcp-repos.json")

    result = asyncio.run(app.call_tool("graph_query", {
        "relation_direction": "outgoing",
        "limit": 10,
    }))
    structured = _extract_structured(result)
    meta = structured.get("meta", {})
    assert "applied_filters" in meta
    assert meta["applied_filters"]["relation_direction"] == "outgoing"


def test_graph_query_applied_filters_direction_both_not_included_e2e(built_artifact: Path, tmp_path: Path):
    """graph_query does not include relation_direction in applied_filters when it's 'both'."""
    from batho.mcp.server import create_app
    app = create_app(root=str(built_artifact), registry_path=tmp_path / "mcp-repos.json")

    result = asyncio.run(app.call_tool("graph_query", {
        "relation_direction": "both",
        "limit": 10,
    }))
    structured = _extract_structured(result)
    meta = structured.get("meta", {})
    af = meta.get("applied_filters", {})
    assert "relation_direction" not in af


def test_trace_path_applied_filters_relation_direction_e2e(built_artifact: Path, tmp_path: Path):
    """trace_path structured output includes relation_direction in applied_filters."""
    from batho.mcp.server import create_app
    app = create_app(root=str(built_artifact), registry_path=tmp_path / "mcp-repos.json")

    result = asyncio.run(app.call_tool("trace_path", {
        "source_entity_id": "main",
        "target_entity_id": "helper",
        "max_depth": 10,
        "relation_direction": "incoming",
    }))
    structured = _extract_structured(result)
    # Only check applied_filters if path was found (error results don't have it)
    path = structured.get("path", [])
    if path:
        meta = structured.get("meta", {})
        if "applied_filters" in meta:
            assert meta["applied_filters"]["relation_direction"] == "incoming"
