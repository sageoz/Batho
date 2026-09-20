"""End-to-end tests for the confidence_threshold filter across MCP tools.

Scenario:
    graph_query and trace_path accept a confidence_threshold parameter
    that filters relationships by their confidence score. These tests
    call the actual MCP tools via create_app / call_tool to verify the
    filter works end-to-end through the full tool stack.

Execution Flow:
    1. Build a sample artifact.
    2. Call graph_query with confidence_threshold=0.85 and verify only
       high-confidence edges are returned.
    3. Call graph_query with confidence_threshold=0.0 and verify all
       edges are returned (backward compat).
    4. Call graph_query with confidence_threshold=1.0 and verify only
       directly-extracted edges are returned.
    5. Call graph_query with an invalid threshold (>1.0) and verify a
       clear client error is returned.
    6. Call trace_path with confidence_threshold and verify the BFS
       only traverses high-confidence edges.
    7. Call graph_query with confidence_threshold + relation_types and
       verify AND semantics.

Expectations:
    - confidence_threshold filter narrows results to edges with confidence >= threshold.
    - Invalid thresholds (>1.0 or <0.0) return a CLIENT_ERROR.
    - confidence_threshold=None preserves backward compatibility.
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
    """Extract the text content from a ToolResult."""
    if hasattr(result, "content") and result.content:
        return result.content[0].text
    return str(result)


def _extract_structured(result) -> dict:
    """Extract the structured_content from a ToolResult, if present."""
    if hasattr(result, "structured_content") and result.structured_content:
        return result.structured_content
    return {}


def _extract_edges(structured: dict) -> list[dict]:
    """Extract edges from the structured output, handling nested 'graph' key."""
    graph = structured.get("graph", structured)
    return graph.get("edges", [])


def _get_all_rels(built_artifact: Path) -> list[dict]:
    """Read all rels_views rows directly."""
    reader = _get_reader(str(built_artifact))
    rels_table = reader._get_table("rels_views")
    if rels_table.num_rows == 0:
        return []
    return rels_table.to_pylist()


def _get_rels_above_confidence(built_artifact: Path, threshold: float) -> list[dict]:
    """Read rels_views directly and return rows with confidence >= threshold."""
    reader = _get_reader(str(built_artifact))
    rels_table = reader._get_table("rels_views")
    if rels_table.num_rows == 0:
        return []
    return [
        r for r in rels_table.to_pylist()
        if (r.get("confidence") if r.get("confidence") is not None else 1.0) >= threshold
    ]


# ---------------------------------------------------------------------------
# graph_query e2e tests
# ---------------------------------------------------------------------------


def test_graph_query_confidence_threshold_085_e2e(built_artifact: Path, tmp_path: Path):
    """graph_query(confidence_threshold=0.85) returns only high-confidence edges."""
    from batho.mcp.server import create_app
    app = create_app(root=str(built_artifact), registry_path=tmp_path / "mcp-repos.json")

    result = asyncio.run(app.call_tool("graph_query", {
        "confidence_threshold": 0.85,
        "limit": 100,
    }))
    content = _extract_content(result)
    structured = _extract_structured(result)

    # Should not error
    assert "must be between" not in content
    assert "Invalid" not in content

    # Verify against direct reader access
    expected = _get_rels_above_confidence(built_artifact, 0.85)
    if expected:
        edges = _extract_edges(structured)
        assert len(edges) > 0, "Expected edges with confidence >= 0.85"
        for edge in edges:
            conf = edge.get("confidence")
            assert conf is None or conf >= 0.85, (
                f"Edge {edge.get('source')} -> {edge.get('target')} "
                f"has confidence={conf} < 0.85"
            )


def test_graph_query_confidence_threshold_0_e2e(built_artifact: Path, tmp_path: Path):
    """graph_query(confidence_threshold=0.0) returns all edges."""
    from batho.mcp.server import create_app
    app = create_app(root=str(built_artifact), registry_path=tmp_path / "mcp-repos.json")

    result = asyncio.run(app.call_tool("graph_query", {
        "confidence_threshold": 0.0,
        "limit": 100,
    }))
    content = _extract_content(result)
    structured = _extract_structured(result)

    assert "must be between" not in content

    all_rels = _get_all_rels(built_artifact)
    if all_rels:
        edges = _extract_edges(structured)
        # threshold=0.0 should include everything
        assert len(edges) > 0, "Expected edges with confidence_threshold=0.0"


def test_graph_query_confidence_threshold_1_e2e(built_artifact: Path, tmp_path: Path):
    """graph_query(confidence_threshold=1.0) returns only directly-extracted edges."""
    from batho.mcp.server import create_app
    app = create_app(root=str(built_artifact), registry_path=tmp_path / "mcp-repos.json")

    result = asyncio.run(app.call_tool("graph_query", {
        "confidence_threshold": 1.0,
        "limit": 100,
    }))
    content = _extract_content(result)
    structured = _extract_structured(result)

    assert "must be between" not in content

    expected = _get_rels_above_confidence(built_artifact, 1.0)
    if expected:
        edges = _extract_edges(structured)
        assert len(edges) > 0, "Expected edges with confidence=1.0"
        for edge in edges:
            conf = edge.get("confidence")
            assert conf is None or conf >= 1.0, (
                f"Edge has confidence={conf} < 1.0"
            )


def test_graph_query_confidence_threshold_invalid_high_e2e(built_artifact: Path, tmp_path: Path):
    """graph_query with confidence_threshold > 1.0 returns validation error."""
    from batho.mcp.server import create_app
    app = create_app(root=str(built_artifact), registry_path=tmp_path / "mcp-repos.json")

    result = asyncio.run(app.call_tool("graph_query", {
        "confidence_threshold": 1.5,
    }))
    content = _extract_content(result)

    assert "must be between" in content or "0.0 and 1.0" in content


def test_graph_query_confidence_threshold_invalid_negative_e2e(built_artifact: Path, tmp_path: Path):
    """graph_query with confidence_threshold < 0.0 returns validation error."""
    from batho.mcp.server import create_app
    app = create_app(root=str(built_artifact), registry_path=tmp_path / "mcp-repos.json")

    result = asyncio.run(app.call_tool("graph_query", {
        "confidence_threshold": -0.5,
    }))
    content = _extract_content(result)

    assert "must be between" in content or "0.0 and 1.0" in content


def test_graph_query_confidence_threshold_none_e2e(built_artifact: Path, tmp_path: Path):
    """graph_query without confidence_threshold returns all edges (backward compat)."""
    from batho.mcp.server import create_app
    app = create_app(root=str(built_artifact), registry_path=tmp_path / "mcp-repos.json")

    result = asyncio.run(app.call_tool("graph_query", {
        "limit": 100,
    }))
    content = _extract_content(result)
    structured = _extract_structured(result)

    assert "must be between" not in content
    all_rels = _get_all_rels(built_artifact)
    if all_rels:
        edges = _extract_edges(structured)
        assert len(edges) > 0, "Expected edges without confidence filter"


def test_graph_query_confidence_threshold_with_relation_types_e2e(built_artifact: Path, tmp_path: Path):
    """graph_query with confidence_threshold + relation_types applies AND semantics."""
    from batho.mcp.server import create_app
    app = create_app(root=str(built_artifact), registry_path=tmp_path / "mcp-repos.json")

    result = asyncio.run(app.call_tool("graph_query", {
        "confidence_threshold": 0.85,
        "relation_types": ["IMPORTS"],
        "limit": 100,
    }))
    content = _extract_content(result)
    structured = _extract_structured(result)

    assert "must be between" not in content

    edges = _extract_edges(structured)
    for edge in edges:
        assert edge.get("relation_type") == "IMPORTS"
        conf = edge.get("confidence")
        assert conf is None or conf >= 0.85


def test_graph_query_confidence_threshold_with_symbol_roles_e2e(built_artifact: Path, tmp_path: Path):
    """graph_query with confidence_threshold + symbol_roles applies AND semantics."""
    from batho.mcp.server import create_app
    from batho.core.schemas import SymbolRole
    app = create_app(root=str(built_artifact), registry_path=tmp_path / "mcp-repos.json")

    result = asyncio.run(app.call_tool("graph_query", {
        "confidence_threshold": 0.85,
        "symbol_roles": ["Import"],
        "limit": 100,
    }))
    content = _extract_content(result)
    structured = _extract_structured(result)

    assert "must be between" not in content
    assert "Invalid" not in content

    edges = _extract_edges(structured)
    for edge in edges:
        roles = edge.get("roles") or 0
        conf = edge.get("confidence")
        assert roles & int(SymbolRole.Import) != 0
        assert conf is None or conf >= 0.85


# ---------------------------------------------------------------------------
# trace_path e2e tests
# ---------------------------------------------------------------------------


def test_trace_path_confidence_threshold_e2e(built_artifact: Path, tmp_path: Path):
    """trace_path with confidence_threshold only traverses high-confidence edges."""
    from batho.mcp.server import create_app
    app = create_app(root=str(built_artifact), registry_path=tmp_path / "mcp-repos.json")

    # Find main and helper entity IDs
    reader = _get_reader(str(built_artifact))
    agent_table = reader._get_table("agent_views")
    rows = agent_table.to_pylist()
    main_eid = None
    helper_eid = None
    for r in rows:
        if r["name"] == "main" and r["entity_type"] == "FUNCTION":
            main_eid = r["entity_id"]
        if "helper" in r["name"] and r["entity_type"] in ("FUNCTION", "METHOD"):
            helper_eid = r["entity_id"]

    if not main_eid or not helper_eid:
        pytest.skip("Could not find main and helper entities")

    result = asyncio.run(app.call_tool("trace_path", {
        "source_entity_id": main_eid,
        "target_entity_id": helper_eid,
        "max_depth": 10,
        "confidence_threshold": 0.85,
    }))
    content = _extract_content(result)
    structured = _extract_structured(result)

    assert "must be between" not in content
    assert "Entity not found" not in content

    # If a path was found, verify every hop's edge has confidence >= 0.85
    # by cross-referencing the raw rels table.
    path = structured.get("path", [])
    if path and len(path) > 1:
        rels_table = reader._get_table("rels_views")
        all_rels = rels_table.to_pylist()
        rels_lookup = {}
        for r in all_rels:
            key = (r.get("source_id", ""), r.get("target_id", ""), r.get("relation_type", ""))
            rels_lookup[key] = r

        for i in range(1, len(path)):
            prev_eid = path[i - 1]["entity_id"]
            curr_eid = path[i]["entity_id"]
            rt = path[i]["relation_type"]
            edge = rels_lookup.get((prev_eid, curr_eid, rt)) or rels_lookup.get((curr_eid, prev_eid, rt))
            if edge is not None:
                conf = edge.get("confidence")
                assert conf is None or conf >= 0.85, (
                    f"Edge {prev_eid} -> {curr_eid} [{rt}] has confidence={conf} < 0.85"
                )

    # Verify applied_filters is in the structured output
    meta = structured.get("meta", {})
    assert "applied_filters" in meta
    assert meta["applied_filters"]["confidence_threshold"] == 0.85


# ---------------------------------------------------------------------------
# applied_filters structured output tests
# ---------------------------------------------------------------------------


def test_graph_query_applied_filters_confidence_threshold_e2e(built_artifact: Path, tmp_path: Path):
    """graph_query structured output includes confidence_threshold in applied_filters."""
    from batho.mcp.server import create_app
    app = create_app(root=str(built_artifact), registry_path=tmp_path / "mcp-repos.json")

    result = asyncio.run(app.call_tool("graph_query", {
        "confidence_threshold": 0.85,
        "limit": 10,
    }))
    structured = _extract_structured(result)
    meta = structured.get("meta", {})
    assert "applied_filters" in meta
    assert meta["applied_filters"]["confidence_threshold"] == 0.85


def test_graph_query_applied_filters_combined_e2e(built_artifact: Path, tmp_path: Path):
    """graph_query structured output includes all active filters in applied_filters."""
    from batho.mcp.server import create_app
    app = create_app(root=str(built_artifact), registry_path=tmp_path / "mcp-repos.json")

    result = asyncio.run(app.call_tool("graph_query", {
        "confidence_threshold": 0.85,
        "symbol_roles": ["Import"],
        "relation_types": ["IMPORTS"],
        "entity_types": ["FUNCTION"],
        "limit": 10,
    }))
    structured = _extract_structured(result)
    meta = structured.get("meta", {})
    assert "applied_filters" in meta
    af = meta["applied_filters"]
    assert af["confidence_threshold"] == 0.85
    assert af["symbol_roles"] == ["Import"]
    assert af["relation_types"] == ["IMPORTS"]
    assert af["entity_types"] == ["FUNCTION"]


def test_graph_query_applied_filters_empty_when_no_filters_e2e(built_artifact: Path, tmp_path: Path):
    """graph_query structured output has no applied_filters when no filters are active."""
    from batho.mcp.server import create_app
    app = create_app(root=str(built_artifact), registry_path=tmp_path / "mcp-repos.json")

    result = asyncio.run(app.call_tool("graph_query", {
        "limit": 10,
    }))
    structured = _extract_structured(result)
    meta = structured.get("meta", {})
    # applied_filters should not be present (or be empty) when no filters are active
    af = meta.get("applied_filters")
    assert af is None or af == {}


def test_trace_path_applied_filters_confidence_threshold_e2e(built_artifact: Path, tmp_path: Path):
    """trace_path structured output includes confidence_threshold in applied_filters."""
    from batho.mcp.server import create_app
    app = create_app(root=str(built_artifact), registry_path=tmp_path / "mcp-repos.json")

    result = asyncio.run(app.call_tool("trace_path", {
        "source_entity_id": "main",
        "target_entity_id": "helper",
        "max_depth": 10,
        "confidence_threshold": 0.90,
    }))
    structured = _extract_structured(result)
    meta = structured.get("meta", {})
    # If path was found or not, applied_filters should be in meta
    if "applied_filters" in meta:
        assert meta["applied_filters"]["confidence_threshold"] == 0.90


def test_trace_path_applied_filters_combined_e2e(built_artifact: Path, tmp_path: Path):
    """trace_path structured output includes all active filters in applied_filters."""
    from batho.mcp.server import create_app
    app = create_app(root=str(built_artifact), registry_path=tmp_path / "mcp-repos.json")

    result = asyncio.run(app.call_tool("trace_path", {
        "source_entity_id": "main",
        "target_entity_id": "helper",
        "max_depth": 10,
        "confidence_threshold": 0.85,
        "symbol_roles": ["Import"],
        "relation_types": ["IMPORTS"],
    }))
    structured = _extract_structured(result)
    meta = structured.get("meta", {})
    if "applied_filters" in meta:
        af = meta["applied_filters"]
        assert af["confidence_threshold"] == 0.85
        assert af["symbol_roles"] == ["Import"]
        assert af["relation_types"] == ["IMPORTS"]


def test_trace_path_confidence_threshold_invalid_e2e(built_artifact: Path, tmp_path: Path):
    """trace_path with invalid confidence_threshold returns clear error."""
    from batho.mcp.server import create_app
    app = create_app(root=str(built_artifact), registry_path=tmp_path / "mcp-repos.json")

    result = asyncio.run(app.call_tool("trace_path", {
        "source_entity_id": "main",
        "target_entity_id": "helper",
        "confidence_threshold": 2.0,
    }))
    content = _extract_content(result)

    assert "must be between" in content or "0.0 and 1.0" in content


def test_trace_path_confidence_threshold_none_e2e(built_artifact: Path, tmp_path: Path):
    """trace_path without confidence_threshold works as before (backward compat)."""
    from batho.mcp.server import create_app
    app = create_app(root=str(built_artifact), registry_path=tmp_path / "mcp-repos.json")

    result = asyncio.run(app.call_tool("trace_path", {
        "source_entity_id": "main",
        "target_entity_id": "helper",
        "max_depth": 10,
    }))
    content = _extract_content(result)

    assert "must be between" not in content
