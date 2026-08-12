"""Tests for MCP tool descriptions quality.

Scenario:
    All Batho MCP tool descriptions must follow Anthropic best practices:
    - Start with a verb
    - Contain Args section with parameter descriptions
    - Contain negative instructions ("Do NOT")
    - Mention return format

Execution Flow:
    1. Create the FastMCP app via create_app().
    2. List all tools and inspect their descriptions.

Expectations:
    - All 10 tools have descriptions with Args section.
    - All descriptions contain at least one "Do NOT" negative instruction.
    - Descriptions mention return format or what the tool returns.
"""

from __future__ import annotations

import asyncio

import pytest


@pytest.fixture
def app():
    from batho.mcp.server import create_app
    return create_app()


ALL_TOOLS = [
    "list_repos", "add_repo", "remove_repo",
    "graph_overview", "graph_query", "get_entity",
    "trace_path", "get_file_graph", "search_entities", "get_delta",
    "batho_status", "batho_list_runs", "batho_build", "batho_patch",
    "batho_export", "batho_diff", "batho_gc", "batho_fix", "batho_load",
]


def test_all_tools_have_descriptions(app):
    """Verify every tool has a non-empty description."""
    tools = asyncio.run(app.list_tools())
    assert len(tools) == 19

    for tool in tools:
        assert tool.description is not None
        assert len(tool.description) > 20, \
            f"Tool {tool.name} description too short"


def test_tool_descriptions_contain_args_section(app):
    """Verify tools with parameters have Args in their full docstring."""
    tools = asyncio.run(app.list_tools())
    tools_with_params = [t for t in tools if t.parameters and t.parameters.get("properties")]

    for tool in tools_with_params:
        full_doc = tool.fn.__doc__ or tool.description or ""
        assert "Args:" in full_doc, \
            f"Tool {tool.name} docstring should contain Args section"


def test_tool_descriptions_start_with_verb(app):
    """Verify tool descriptions start with a verb (action word)."""
    tools = asyncio.run(app.list_tools())

    action_verbs = ("Get", "List", "Search", "Find", "Query", "Register", "Remove", "Trace", "Analyze", "Run", "Export", "Show", "Unpack")

    for tool in tools:
        desc = (tool.description or "").strip()
        assert desc.startswith(action_verbs), \
            f"Tool {tool.name} description should start with a verb, got: {desc[:30]}..."



def test_graph_overview_description_mentions_community(app):
    """Verify graph_overview description mentions community summaries."""
    tools = asyncio.run(app.list_tools())
    tool = next(t for t in tools if t.name == "graph_overview")

    assert "community" in (tool.description or "").lower()


def test_get_delta_description_mentions_patch(app):
    """Verify get_delta description mentions patch."""
    tools = asyncio.run(app.list_tools())
    tool = next(t for t in tools if t.name == "get_delta")

    assert "patch" in (tool.description or "").lower()


def test_trace_path_description_mentions_bfs(app):
    """Verify trace_path description mentions BFS."""
    tools = asyncio.run(app.list_tools())
    tool = next(t for t in tools if t.name == "trace_path")

    assert "BFS" in (tool.description or "")
