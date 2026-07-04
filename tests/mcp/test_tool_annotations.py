"""Tests for MCP tool annotations.

Scenario:
    All Batho MCP tools must have proper ToolAnnotations set:
    - Read-only tools: readOnlyHint=True, destructiveHint=False
    - Mutating tools (add_repo, remove_repo): destructiveHint=True

Execution Flow:
    1. Create the FastMCP app via create_app().
    2. List all tools and check their annotations.

Expectations:
    - All 10 tools have annotations set.
    - 8 read-only tools have readOnlyHint=True.
    - 2 mutating tools (add_repo, remove_repo) have destructiveHint=True.
"""

from __future__ import annotations

import asyncio

import pytest


@pytest.fixture
def app():
    from batho.mcp.server import create_app
    return create_app()


READ_ONLY_TOOLS = [
    "list_repos",
    "graph_overview",
    "graph_query",
    "get_entity",
    "trace_path",
    "get_file_graph",
    "search_entities",
    "get_delta",
]

MUTATING_TOOLS = ["add_repo", "remove_repo"]


def test_all_tools_have_annotations(app):
    """Verify every registered tool has annotations set."""
    tools = asyncio.run(app.list_tools())

    for tool in tools:
        assert tool.annotations is not None, f"Tool {tool.name} has no annotations"


def test_read_only_tools_have_read_only_hint(app):
    """Verify read-only tools have readOnlyHint=True."""
    tools = asyncio.run(app.list_tools())
    tool_map = {t.name: t for t in tools}

    for name in READ_ONLY_TOOLS:
        assert name in tool_map, f"Tool {name} not found"
        annotations = tool_map[name].annotations
        assert annotations.readOnlyHint is True, \
            f"Tool {name} should have readOnlyHint=True"


def test_read_only_tools_have_destructive_false(app):
    """Verify read-only tools have destructiveHint=False."""
    tools = asyncio.run(app.list_tools())
    tool_map = {t.name: t for t in tools}

    for name in READ_ONLY_TOOLS:
        annotations = tool_map[name].annotations
        assert annotations.destructiveHint is False, \
            f"Tool {name} should have destructiveHint=False"


def test_mutating_tools_have_destructive_hint(app):
    """Verify add_repo and remove_repo have destructiveHint=True."""
    tools = asyncio.run(app.list_tools())
    tool_map = {t.name: t for t in tools}

    for name in MUTATING_TOOLS:
        assert name in tool_map, f"Tool {name} not found"
        annotations = tool_map[name].annotations
        assert annotations.destructiveHint is True, \
            f"Tool {name} should have destructiveHint=True"


def test_mutating_tools_have_read_only_false(app):
    """Verify mutating tools have readOnlyHint=False."""
    tools = asyncio.run(app.list_tools())
    tool_map = {t.name: t for t in tools}

    for name in MUTATING_TOOLS:
        annotations = tool_map[name].annotations
        assert annotations.readOnlyHint is False, \
            f"Tool {name} should have readOnlyHint=False"


def test_all_tools_have_open_world_false(app):
    """Verify all tools have openWorldHint=False (closed system)."""
    tools = asyncio.run(app.list_tools())

    for tool in tools:
        annotations = tool.annotations
        assert annotations.openWorldHint is False, \
            f"Tool {tool.name} should have openWorldHint=False"
