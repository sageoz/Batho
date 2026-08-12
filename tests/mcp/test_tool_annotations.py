"""Tests for MCP tool annotations.

Scenario:
    All Batho MCP tools must have proper ToolAnnotations set:
    - Read-only tools: readOnlyHint=True, destructiveHint=False
    - Mutating tools (add_repo, remove_repo, build/patch/gc/fix/load, export): destructiveHint=True

Execution Flow:
    1. Create the FastMCP app via create_app().
    2. List all tools and check their annotations.

Expectations:
    - All 19 tools have annotations set.
    - 11 read-only tools have readOnlyHint=True.
    - 8 mutating tools have destructiveHint=True.
    - batho_export is mutating because it writes the export output to disk.
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
    "batho_status",
    "batho_list_runs",
    "batho_diff",
]

MUTATING_TOOLS = [
    "add_repo",
    "remove_repo",
    "batho_build",
    "batho_patch",
    "batho_gc",
    "batho_fix",
    "batho_load",
    "batho_export",
]


def test_all_tools_have_annotations(app):
    """Verify every registered tool has annotations set."""
    tools = asyncio.run(app.list_tools())
    assert len(tools) == 19, f"Expected 19 tools, got {len(tools)}"

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
    """Verify mutating tools have destructiveHint=True."""
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


def test_open_world_tools_annotations(app):
    """Verify tools with openWorldHint=True."""
    tools = asyncio.run(app.list_tools())
    tool_map = {t.name: t for t in tools}

    open_world_expected = {"batho_build", "batho_patch", "batho_export"}
    for name, tool in tool_map.items():
        if name in open_world_expected:
            assert tool.annotations.openWorldHint is True, f"Tool {name} should have openWorldHint=True"
        else:
            assert tool.annotations.openWorldHint is False, f"Tool {name} should have openWorldHint=False"

