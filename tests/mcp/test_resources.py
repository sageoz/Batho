"""Tests for MCP resources registration and content.

Scenario:
    The MCP server must provide resources for static/contextual data that
    agents can read via URI references, complementing tools and prompts.

Execution Flow:
    1. Create the FastMCP app via create_app().
    2. List all registered resources.
    3. Read each resource and verify content.

Expectations:
    - batho://schema resource is registered and returns valid JSON with entity_types.
    - batho://repos resource is registered and returns valid JSON with repos array.
"""

from __future__ import annotations

import asyncio
import json

import pytest


@pytest.fixture
def app():
    from batho.mcp.server import create_app
    return create_app()


@pytest.fixture
def app_with_artifact(built_artifact):
    from batho.mcp.server import create_app
    return create_app(root=str(built_artifact))


def test_resources_registered(app):
    """Verify batho://schema and batho://repos resources are registered."""
    resources = asyncio.run(app.list_resources())
    uris = {str(r.uri) for r in resources}

    assert "batho://schema" in uris
    assert "batho://repos" in uris


def test_schema_resource_content(app):
    """Verify batho://schema returns valid JSON with entity and relation types."""
    result = asyncio.run(app.read_resource("batho://schema"))

    content = result.contents[0].content if hasattr(result, "contents") else str(result)
    data = json.loads(content)

    assert "entity_types" in data
    assert "relation_types" in data
    assert "response_formats" in data
    assert "FUNCTION" in data["entity_types"]
    assert "CALLS" in data["relation_types"]
    assert "summary" in data["response_formats"]
    assert "concise" in data["response_formats"]
    assert "detailed" in data["response_formats"]


def test_schema_resource_change_kinds(app):
    """Verify batho://schema includes change_kinds for patch delta."""
    result = asyncio.run(app.read_resource("batho://schema"))

    content = result.contents[0].content if hasattr(result, "contents") else str(result)
    data = json.loads(content)

    assert "change_kinds" in data
    assert "added" in data["change_kinds"]
    assert "removed" in data["change_kinds"]
    assert "modified" in data["change_kinds"]
    assert "renamed" in data["change_kinds"]


def test_repos_resource_no_registry(app):
    """Verify batho://repos returns empty list when no registry configured."""
    result = asyncio.run(app.read_resource("batho://repos"))

    content = result.contents[0].content if hasattr(result, "contents") else str(result)
    data = json.loads(content)

    assert "repos" in data
    assert data["repos"] == []
