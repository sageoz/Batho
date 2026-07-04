"""Tests for MCP server instructions and tool registration.

Scenario:
    The MCP server must provide instructions text in the initialize response
    and register all 7 tools correctly.

Execution Flow:
    1. Create the FastMCP app via create_app().
    2. Verify instructions text is set.
    3. Verify all 7 tools are registered.

Expectations:
    - Instructions contain tool selection guidance.
    - All 7 tools (graph_overview, graph_query, get_entity, trace_path,
      get_file_graph, search_entities, get_delta) are registered.
"""

from __future__ import annotations


def test_instructions_content():
    from batho.mcp.instructions import INSTRUCTIONS

    assert "Batho" in INSTRUCTIONS
    assert "graph_overview" in INSTRUCTIONS
    assert "get_delta" in INSTRUCTIONS
    assert "list_repos" in INSTRUCTIONS
    assert "add_repo" in INSTRUCTIONS
    assert "remove_repo" in INSTRUCTIONS


def test_create_app():
    from batho.mcp.server import create_app

    app = create_app()
    assert app.name == "batho"


def test_create_app_with_root():
    from batho.mcp.server import create_app

    app = create_app(root="/tmp")
    assert app.name == "batho"


def test_tool_registration():
    import asyncio
    from batho.mcp.server import create_app

    app = create_app()

    expected_tools = [
        "list_repos", "add_repo", "remove_repo",
        "graph_overview", "graph_query", "get_entity",
        "trace_path", "get_file_graph", "search_entities", "get_delta",
    ]

    tools = asyncio.run(app.list_tools())
    tool_names = [t.name for t in tools]

    for tool_name in expected_tools:
        assert tool_name in tool_names, f"Tool {tool_name} not registered"
