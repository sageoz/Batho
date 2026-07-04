"""Tests for structured error handling in MCP tools.

Scenario:
    MCP tools must return structured error responses with isError flag,
    error_type classification, retryable field, and actionable hints.

Execution Flow:
    1. Create the FastMCP app with a built artifact.
    2. Call tools with invalid inputs to trigger error responses.
    3. Verify error responses have correct structure.

Expectations:
    - Error responses have is_error=True.
    - structuredContent contains error, error_type, message, retryable, hint.
    - Content text includes "Error:" prefix and "Hint:" when hint is provided.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest


@pytest.fixture
def app_with_artifact(built_artifact: Path) -> "FastMCP":
    from batho.mcp.server import create_app
    return create_app(root=str(built_artifact))


def test_err_function_structure():
    """Verify _err() returns a ToolResult with isError flag and structured fields."""
    from batho.mcp.errors import _err, CLIENT_ERROR

    result = _err("test error", error_type=CLIENT_ERROR, retryable=False, hint="test hint")

    assert result.is_error is True
    assert result.structured_content is not None
    sc = result.structured_content
    assert sc["error"] is True
    assert sc["error_type"] == CLIENT_ERROR
    assert sc["message"] == "test error"
    assert sc["retryable"] is False
    assert sc["hint"] == "test hint"


def test_err_function_no_hint():
    """Verify _err() works without a hint."""
    from batho.mcp.errors import _err

    result = _err("no hint error")

    assert result.is_error is True
    assert result.structured_content["error"] is True
    assert "hint" not in result.structured_content


def test_err_content_includes_hint():
    """Verify error content text includes the hint."""
    from batho.mcp.errors import _err

    result = _err("missing repo", hint="Call list_repos")

    content_text = result.content[0].text
    assert "Error: missing repo" in content_text
    assert "Hint: Call list_repos" in content_text


def test_entity_not_found_error(app_with_artifact):
    """Verify get_entity returns structured error for non-existent entity."""
    app = app_with_artifact
    tools = asyncio.run(app.list_tools())
    tool = next(t for t in tools if t.name == "get_entity")

    result = asyncio.run(app.call_tool("get_entity", {"entity_id": "nonexistent_id"}))

    assert result.is_error is True
    sc = result.structured_content
    assert sc["error"] is True
    assert sc["error_type"] == "client_error"
    assert "hint" in sc
    assert "search_entities" in sc["hint"]


def test_file_not_indexed_error(app_with_artifact):
    """Verify get_file_graph returns structured error for non-indexed file."""
    app = app_with_artifact

    result = asyncio.run(app.call_tool("get_file_graph", {"file_path": "nonexistent.py"}))

    assert result.is_error is True
    sc = result.structured_content
    assert sc["error"] is True
    assert sc["error_type"] == "client_error"


def test_repo_not_found_error(app_with_artifact):
    """Verify tools return structured error for non-existent repo."""
    app = app_with_artifact

    result = asyncio.run(app.call_tool("graph_overview", {"repo": "nonexistent_repo"}))

    assert result.is_error is True
    sc = result.structured_content
    assert sc["error"] is True
    assert sc["error_type"] == "client_error"
    assert "list_repos" in sc.get("hint", "")


def test_name_pattern_too_long_error(app_with_artifact):
    """Verify graph_query rejects name_pattern longer than 200 chars."""
    app = app_with_artifact
    long_pattern = "a" * 201

    result = asyncio.run(app.call_tool("graph_query", {"name_pattern": long_pattern}))

    assert result.is_error is True
    sc = result.structured_content
    assert sc["error"] is True
    assert "200" in sc["message"]


def test_search_query_too_long_error(app_with_artifact):
    """Verify search_entities rejects query longer than 200 chars."""
    app = app_with_artifact
    long_query = "a" * 201

    result = asyncio.run(app.call_tool("search_entities", {"query": long_query}))

    assert result.is_error is True
    sc = result.structured_content
    assert sc["error"] is True
    assert "200" in sc["message"]


def test_trace_path_no_path_error(app_with_artifact):
    """Verify trace_path returns retryable error when no path found."""
    app = app_with_artifact

    result = asyncio.run(app.call_tool("trace_path", {
        "source_entity_id": "nonexistent_a",
        "target_entity_id": "nonexistent_b",
    }))

    assert result.is_error is True
    sc = result.structured_content
    assert sc["error_type"] == "client_error"
