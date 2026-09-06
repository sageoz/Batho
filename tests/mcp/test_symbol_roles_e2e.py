"""End-to-end tests for the symbol_roles filter across MCP tools.

Scenario:
    graph_query, search_entities, and trace_path accept a symbol_roles
    parameter that filters relationships by SymbolRole bitmask. These
    tests call the actual MCP tools via create_app / call_tool to verify
    the filter works end-to-end through the full tool stack.

Execution Flow:
    1. Build a sample artifact.
    2. Call graph_query with symbol_roles=["Import"] and verify only
       import-role edges are returned.
    3. Call graph_query with symbol_roles=["WriteAccess"] and verify
       only write-access edges are returned.
    4. Call graph_query with an invalid role name and verify a clear
       client error is returned.
    5. Call search_entities with symbol_roles and verify only entities
       participating in matching-role relationships are returned.
    6. Call trace_path with symbol_roles and verify the BFS only
       traverses edges with matching roles.
    7. Call graph_query with symbol_roles=None and verify backward
       compatibility (all edges returned).

Expectations:
    - symbol_roles filter narrows results to edges with matching role bits.
    - Invalid role names return a CLIENT_ERROR with the valid role list.
    - symbol_roles=None preserves backward compatibility.
    - OR semantics: multiple roles match if ANY bit is set.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from batho.core.schemas import SymbolRole
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


def _extract_nodes(structured: dict) -> list[dict]:
    """Extract nodes from the structured output, handling nested 'graph' key."""
    graph = structured.get("graph", structured)
    return graph.get("nodes", [])


def _get_rels_with_roles(built_artifact: Path, role_bit: int) -> list[dict]:
    """Read rels_views directly and return rows matching the given role bit."""
    reader = _get_reader(str(built_artifact))
    rels_table = reader._get_table("rels_views")
    if rels_table.num_rows == 0 or "roles" not in rels_table.schema.names:
        return []
    return [
        r for r in rels_table.to_pylist()
        if (r.get("roles") or 0) & role_bit != 0
    ]


def _get_all_rels(built_artifact: Path) -> list[dict]:
    """Read all rels_views rows directly."""
    reader = _get_reader(str(built_artifact))
    rels_table = reader._get_table("rels_views")
    if rels_table.num_rows == 0:
        return []
    return rels_table.to_pylist()


# ---------------------------------------------------------------------------
# graph_query e2e tests
# ---------------------------------------------------------------------------


def test_graph_query_symbol_roles_import_e2e(built_artifact: Path, tmp_path: Path):
    """graph_query(symbol_roles=['Import']) returns only import-role edges."""
    from batho.mcp.server import create_app
    app = create_app(root=str(built_artifact), registry_path=tmp_path / "mcp-repos.json")

    result = asyncio.run(app.call_tool("graph_query", {
        "symbol_roles": ["Import"],
        "limit": 100,
    }))
    content = _extract_content(result)
    structured = _extract_structured(result)

    # Should not error
    assert "Invalid" not in content
    assert "requires a rebuilt artifact" not in content

    # Verify against direct reader access
    expected_import_rels = _get_rels_with_roles(built_artifact, int(SymbolRole.Import))
    if expected_import_rels:
        # The tool should have returned some edges
        edges = _extract_edges(structured)
        assert len(edges) > 0, "Expected edges with Import role"
        # Every returned edge should have the Import bit set
        for edge in edges:
            roles = edge.get("roles") or 0
            assert roles & int(SymbolRole.Import) != 0, (
                f"Edge {edge.get('source_id')} -> {edge.get('target_id')} "
                f"does not have Import role bit set (roles={roles})"
            )


def test_graph_query_symbol_roles_write_access_e2e(built_artifact: Path, tmp_path: Path):
    """graph_query(symbol_roles=['WriteAccess']) returns only write-access edges."""
    from batho.mcp.server import create_app
    app = create_app(root=str(built_artifact), registry_path=tmp_path / "mcp-repos.json")

    result = asyncio.run(app.call_tool("graph_query", {
        "symbol_roles": ["WriteAccess"],
        "limit": 100,
    }))
    content = _extract_content(result)
    structured = _extract_structured(result)

    assert "Invalid" not in content

    expected_write_rels = _get_rels_with_roles(built_artifact, int(SymbolRole.WriteAccess))
    if expected_write_rels:
        edges = _extract_edges(structured)
        assert len(edges) > 0, "Expected edges with WriteAccess role"
        for edge in edges:
            roles = edge.get("roles") or 0
            assert roles & int(SymbolRole.WriteAccess) != 0, (
                f"Edge does not have WriteAccess role bit set (roles={roles})"
            )


def test_graph_query_symbol_roles_case_insensitive_e2e(built_artifact: Path, tmp_path: Path):
    """graph_query(symbol_roles=['import']) works case-insensitively."""
    from batho.mcp.server import create_app
    app = create_app(root=str(built_artifact), registry_path=tmp_path / "mcp-repos.json")

    result = asyncio.run(app.call_tool("graph_query", {
        "symbol_roles": ["import"],
        "limit": 100,
    }))
    content = _extract_content(result)
    assert "Invalid" not in content
    assert "requires a rebuilt artifact" not in content


def test_graph_query_symbol_roles_invalid_e2e(built_artifact: Path, tmp_path: Path):
    """graph_query with invalid role name returns a clear client error."""
    from batho.mcp.server import create_app
    app = create_app(root=str(built_artifact), registry_path=tmp_path / "mcp-repos.json")

    result = asyncio.run(app.call_tool("graph_query", {
        "symbol_roles": ["NonExistentRole"],
    }))
    content = _extract_content(result)

    assert "Invalid" in content or "invalid" in content.lower()
    # Should list valid roles
    assert "WriteAccess" in content or "ReadAccess" in content
    assert "Import" in content


def test_graph_query_symbol_roles_none_e2e(built_artifact: Path, tmp_path: Path):
    """graph_query without symbol_roles returns all edges (backward compat)."""
    from batho.mcp.server import create_app
    app = create_app(root=str(built_artifact), registry_path=tmp_path / "mcp-repos.json")

    result = asyncio.run(app.call_tool("graph_query", {
        "limit": 100,
    }))
    content = _extract_content(result)
    structured = _extract_structured(result)

    assert "Invalid" not in content
    # Should return some edges (the sample repo has relationships)
    all_rels = _get_all_rels(built_artifact)
    if all_rels:
        edges = _extract_edges(structured)
        assert len(edges) > 0, "Expected edges without role filter"


def test_graph_query_symbol_roles_or_semantics_e2e(built_artifact: Path, tmp_path: Path):
    """graph_query with multiple roles uses OR semantics."""
    from batho.mcp.server import create_app
    app = create_app(root=str(built_artifact), registry_path=tmp_path / "mcp-repos.json")

    combined_mask = int(SymbolRole.Import) | int(SymbolRole.ReadAccess)

    result = asyncio.run(app.call_tool("graph_query", {
        "symbol_roles": ["Import", "ReadAccess"],
        "limit": 100,
    }))
    content = _extract_content(result)
    structured = _extract_structured(result)

    assert "Invalid" not in content

    expected = _get_rels_with_roles(built_artifact, combined_mask)
    if expected:
        edges = _extract_edges(structured)
        assert len(edges) > 0
        for edge in edges:
            roles = edge.get("roles") or 0
            assert roles & combined_mask != 0, (
                f"Edge does not match either Import or ReadAccess (roles={roles})"
            )


def test_graph_query_symbol_roles_with_entity_types_e2e(built_artifact: Path, tmp_path: Path):
    """graph_query with symbol_roles + entity_types applies AND semantics."""
    from batho.mcp.server import create_app
    app = create_app(root=str(built_artifact), registry_path=tmp_path / "mcp-repos.json")

    result = asyncio.run(app.call_tool("graph_query", {
        "symbol_roles": ["Import"],
        "entity_types": ["FUNCTION"],
        "limit": 100,
    }))
    content = _extract_content(result)
    structured = _extract_structured(result)

    assert "Invalid" not in content

    # If there are results, nodes should all be FUNCTION type
    nodes = _extract_nodes(structured)
    for node in nodes:
        assert node.get("entity_type") == "FUNCTION" or node.get("type") == "FUNCTION"


# ---------------------------------------------------------------------------
# search_entities e2e tests
# ---------------------------------------------------------------------------


def test_search_entities_symbol_roles_e2e(built_artifact: Path, tmp_path: Path):
    """search_entities with symbol_roles returns only entities in matching-role edges."""
    from batho.mcp.server import create_app
    app = create_app(root=str(built_artifact), registry_path=tmp_path / "mcp-repos.json")

    result = asyncio.run(app.call_tool("search_entities", {
        "query": ".*",
        "symbol_roles": ["Import"],
        "limit": 100,
    }))
    content = _extract_content(result)
    structured = _extract_structured(result)

    assert "Invalid" not in content
    assert "requires a rebuilt artifact" not in content

    # Get the expected entity IDs from direct reader access
    import_rels = _get_rels_with_roles(built_artifact, int(SymbolRole.Import))
    if import_rels:
        expected_ids = set()
        for r in import_rels:
            expected_ids.add(r.get("source_id", ""))
            expected_ids.add(r.get("target_id", ""))
        expected_ids.discard("")

        results = structured.get("results", [])
        if results:
            returned_ids = {r.get("entity_id") for r in results}
            # Every returned entity should be in the expected set
            assert returned_ids.issubset(expected_ids), (
                f"search_entities returned entities not in Import-role edge set: "
                f"{returned_ids - expected_ids}"
            )


def test_search_entities_symbol_roles_invalid_e2e(built_artifact: Path, tmp_path: Path):
    """search_entities with invalid role returns clear error."""
    from batho.mcp.server import create_app
    app = create_app(root=str(built_artifact), registry_path=tmp_path / "mcp-repos.json")

    result = asyncio.run(app.call_tool("search_entities", {
        "query": "main",
        "symbol_roles": ["BogusRole"],
    }))
    content = _extract_content(result)

    assert "Invalid" in content or "invalid" in content.lower()
    assert "Import" in content


def test_search_entities_symbol_roles_none_e2e(built_artifact: Path, tmp_path: Path):
    """search_entities without symbol_roles returns all matches (backward compat)."""
    from batho.mcp.server import create_app
    app = create_app(root=str(built_artifact), registry_path=tmp_path / "mcp-repos.json")

    result = asyncio.run(app.call_tool("search_entities", {
        "query": "main",
    }))
    content = _extract_content(result)

    assert "Invalid" not in content
    assert "main" in content.lower()


# ---------------------------------------------------------------------------
# trace_path e2e tests
# ---------------------------------------------------------------------------


def test_trace_path_symbol_roles_e2e(built_artifact: Path, tmp_path: Path):
    """trace_path with symbol_roles only traverses edges with matching roles."""
    from batho.mcp.server import create_app
    app = create_app(root=str(built_artifact), registry_path=tmp_path / "mcp-repos.json")

    # Find two entity IDs that have a path between them
    reader = _get_reader(str(built_artifact))
    agent_table = reader._get_table("agent_views")
    rows = agent_table.to_pylist()
    assert len(rows) >= 2

    # Find main and helper entity IDs
    main_eid = None
    helper_eid = None
    for r in rows:
        if r["name"] == "main":
            main_eid = r["entity_id"]
        if "helper" in r["name"]:
            helper_eid = r["entity_id"]

    if not main_eid or not helper_eid:
        pytest.skip("Could not find main and helper entities in sample repo")

    # First, trace without role filter to confirm a path exists
    result_no_filter = asyncio.run(app.call_tool("trace_path", {
        "source_entity_id": main_eid,
        "target_entity_id": helper_eid,
        "max_depth": 10,
    }))
    content_no_filter = _extract_content(result_no_filter)
    structured_no_filter = _extract_structured(result_no_filter)

    # If there's a path without filter, test with Import role filter
    # (main imports helper, so Import-filtered path should work if it exists)
    result_with_filter = asyncio.run(app.call_tool("trace_path", {
        "source_entity_id": main_eid,
        "target_entity_id": helper_eid,
        "max_depth": 10,
        "symbol_roles": ["Import"],
    }))
    content_with_filter = _extract_content(result_with_filter)
    structured_with_filter = _extract_structured(result_with_filter)

    # Should not error
    assert "Invalid" not in content_with_filter
    assert "requires a rebuilt artifact" not in content_with_filter
    assert "Entity not found" not in content_with_filter

    # If a path was found with the Import filter, verify every hop's edge
    # has the Import role bit set by cross-referencing the raw rels table.
    path_with_filter = structured_with_filter.get("path", [])
    if path_with_filter and len(path_with_filter) > 1:
        import_mask = int(SymbolRole.Import)
        rels_table = reader._get_table("rels_views")
        all_rels = rels_table.to_pylist()
        rels_lookup = {}
        for r in all_rels:
            key = (r.get("source_id", ""), r.get("target_id", ""), r.get("relation_type", ""))
            rels_lookup[key] = r

        for i in range(1, len(path_with_filter)):
            prev_eid = path_with_filter[i - 1]["entity_id"]
            curr_eid = path_with_filter[i]["entity_id"]
            rt = path_with_filter[i]["relation_type"]
            # Look up the edge in both directions
            edge = rels_lookup.get((prev_eid, curr_eid, rt)) or rels_lookup.get((curr_eid, prev_eid, rt))
            if edge is not None:
                roles = edge.get("roles") or 0
                assert roles & import_mask != 0, (
                    f"Edge {prev_eid} -> {curr_eid} [{rt}] does not have Import role "
                    f"(roles={roles})"
                )

    # Verify applied_filters is in the structured output (only when path found,
    # since "No path found" returns an error result without structured metadata)
    path_with_filter = structured_with_filter.get("path", [])
    if path_with_filter:
        meta = structured_with_filter.get("meta", {})
        assert "applied_filters" in meta
        assert meta["applied_filters"]["symbol_roles"] == ["Import"]


def test_trace_path_symbol_roles_invalid_e2e(built_artifact: Path, tmp_path: Path):
    """trace_path with invalid role returns clear error."""
    from batho.mcp.server import create_app
    app = create_app(root=str(built_artifact), registry_path=tmp_path / "mcp-repos.json")

    result = asyncio.run(app.call_tool("trace_path", {
        "source_entity_id": "main",
        "target_entity_id": "helper",
        "symbol_roles": ["FakeRole"],
    }))
    content = _extract_content(result)

    assert "Invalid" in content or "invalid" in content.lower()
    assert "Import" in content


def test_trace_path_symbol_roles_none_e2e(built_artifact: Path, tmp_path: Path):
    """trace_path without symbol_roles works as before (backward compat)."""
    from batho.mcp.server import create_app
    app = create_app(root=str(built_artifact), registry_path=tmp_path / "mcp-repos.json")

    result = asyncio.run(app.call_tool("trace_path", {
        "source_entity_id": "main",
        "target_entity_id": "helper",
        "max_depth": 10,
    }))
    content = _extract_content(result)

    assert "Invalid" not in content
    # Should either find a path or report no path — but not error about roles
    assert "requires a rebuilt artifact" not in content


# ---------------------------------------------------------------------------
# Combined filter e2e test
# ---------------------------------------------------------------------------


def test_graph_query_symbol_roles_with_relation_types_e2e(built_artifact: Path, tmp_path: Path):
    """graph_query with symbol_roles + relation_types applies AND semantics."""
    from batho.mcp.server import create_app
    app = create_app(root=str(built_artifact), registry_path=tmp_path / "mcp-repos.json")

    result = asyncio.run(app.call_tool("graph_query", {
        "symbol_roles": ["Import"],
        "relation_types": ["IMPORTS"],
        "limit": 100,
    }))
    content = _extract_content(result)
    structured = _extract_structured(result)

    assert "Invalid" not in content

    # If there are edges, they should be both Import-role AND IMPORTS-type
    edges = _extract_edges(structured)
    for edge in edges:
        assert edge.get("relation_type") == "IMPORTS"
        roles = edge.get("roles") or 0
        assert roles & int(SymbolRole.Import) != 0


# ---------------------------------------------------------------------------
# applied_filters structured output tests
# ---------------------------------------------------------------------------


def test_graph_query_applied_filters_symbol_roles_e2e(built_artifact: Path, tmp_path: Path):
    """graph_query structured output includes symbol_roles in applied_filters."""
    from batho.mcp.server import create_app
    app = create_app(root=str(built_artifact), registry_path=tmp_path / "mcp-repos.json")

    result = asyncio.run(app.call_tool("graph_query", {
        "symbol_roles": ["Import"],
        "limit": 10,
    }))
    structured = _extract_structured(result)
    meta = structured.get("meta", {})
    assert "applied_filters" in meta
    assert meta["applied_filters"]["symbol_roles"] == ["Import"]


def test_graph_query_applied_filters_empty_when_no_filters_e2e(built_artifact: Path, tmp_path: Path):
    """graph_query structured output has no applied_filters when no filters are active."""
    from batho.mcp.server import create_app
    app = create_app(root=str(built_artifact), registry_path=tmp_path / "mcp-repos.json")

    result = asyncio.run(app.call_tool("graph_query", {
        "limit": 10,
    }))
    structured = _extract_structured(result)
    meta = structured.get("meta", {})
    af = meta.get("applied_filters")
    assert af is None or af == {}
