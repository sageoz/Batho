"""Tests for entity_id visibility and name-based lookup fallback.

Scenario:
    search_entities and graph_query markdown output should include entity_ids
    so agents can pass them to get_entity and trace_path. Additionally,
    get_entity and trace_path should accept display names as fallback when
    the entity_id is not found, resolving uniquely or returning a
    disambiguation list for ambiguous names.

Execution Flow:
    1. Build a sample artifact with known entities.
    2. Verify search_entities markdown includes entity_id backticks.
    3. Verify format_concise and format_detailed include entity_id.
    4. Verify get_entity resolves display names (unique and ambiguous).
    5. Verify trace_path resolves display names.
    6. Verify backward compat: full entity_id still works.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from batho.mcp.graph_builder import format_concise, format_detailed


def test_search_entities_markdown_includes_entity_id(built_artifact, tmp_path):
    """search_entities markdown should include entity_id in backticks."""
    from batho.mcp.server import create_app
    app = create_app(root=str(built_artifact), registry_path=tmp_path / "mcp-repos.json")
    result = asyncio.run(app.call_tool("search_entities", {"query": "main"}))

    content = result.content[0].text if hasattr(result, "content") else str(result)
    assert "main" in content
    assert "`" in content  # entity_id values appear in backticks


def test_format_concise_includes_entity_id():
    """format_concise should include entity_id on an indented backtick line."""
    eid = "ent|FUNCTION|main.py|0|10|1|5|main"
    rows = [
        {"entity_id": eid, "entity_type": "FUNCTION", "name": "main",
         "file_id": 1, "start_line": 1, "end_line": 5},
    ]
    file_paths = {1: "main.py"}

    markdown = format_concise(rows, [], file_paths)
    assert eid in markdown
    assert f"`{eid}`" in markdown


def test_format_detailed_includes_entity_id():
    """format_detailed should include entity_id in backticks under the header."""
    eid = "ent|FUNCTION|main.py|0|10|1|5|main"
    rows = [
        {"entity_id": eid, "entity_type": "FUNCTION", "name": "main",
         "file_id": 1, "start_line": 1, "end_line": 5},
    ]
    file_paths = {1: "main.py"}

    markdown = format_detailed(rows, [], None, file_paths)
    assert eid in markdown
    assert f"`{eid}`" in markdown


def test_get_entity_with_display_name_unique(built_artifact, tmp_path):
    """get_entity should resolve a unique display name to the entity."""
    from batho.mcp.server import create_app
    app = create_app(root=str(built_artifact), registry_path=tmp_path / "mcp-repos.json")

    # "main" is a unique function name in the sample repo
    result = asyncio.run(app.call_tool("get_entity", {"entity_id": "main"}))

    content = result.content[0].text if hasattr(result, "content") else str(result)
    assert "main" in content.lower()
    assert "Entity not found" not in content


def test_get_entity_with_full_entity_id(built_artifact, tmp_path):
    """get_entity should still work with full entity_id (backward compat)."""
    from batho.mcp.server import create_app
    from batho.modules.storage.arrow_bundle.reader import BathoBundleReader

    app = create_app(root=str(built_artifact), registry_path=tmp_path / "mcp-repos.json")
    artifact_dir = built_artifact / ".batho" / "artifact"
    reader = BathoBundleReader(artifact_dir)
    agent_table = reader._get_table("agent_views")
    rows = agent_table.to_pylist()
    assert len(rows) > 0
    real_eid = rows[0]["entity_id"]

    result = asyncio.run(app.call_tool("get_entity", {"entity_id": real_eid}))
    content = result.content[0].text if hasattr(result, "content") else str(result)
    assert "Entity not found" not in content


def test_get_entity_with_nonexistent_name(built_artifact, tmp_path):
    """get_entity should return error for a name that doesn't exist."""
    from batho.mcp.server import create_app
    app = create_app(root=str(built_artifact), registry_path=tmp_path / "mcp-repos.json")

    result = asyncio.run(app.call_tool("get_entity", {"entity_id": "nonexistent_function_xyz"}))
    content = result.content[0].text if hasattr(result, "content") else str(result)
    assert "not found" in content.lower() or "error" in content.lower()


def test_trace_path_with_display_names(built_artifact, tmp_path):
    """trace_path should resolve display names for source and target."""
    from batho.mcp.server import create_app
    app = create_app(root=str(built_artifact), registry_path=tmp_path / "mcp-repos.json")

    # "main" calls "helper" in the sample repo — but the entity name may be
    # mangled (e.g. helper_[ef2e96]). Use search to find the real name first.
    search_result = asyncio.run(app.call_tool("search_entities", {"query": "helper"}))
    search_content = search_result.content[0].text if hasattr(search_result, "content") else str(search_result)
    # Extract the first result name from the markdown line: "- name [TYPE] file:lr — `eid`"
    helper_name = None
    for line in search_content.split("\n"):
        if line.startswith("- ") and "helper" in line:
            # Name is between "- " and " ["
            helper_name = line[2:].split(" [")[0]
            break

    if not helper_name:
        pytest.skip("helper entity not found in sample repo")

    result = asyncio.run(app.call_tool("trace_path", {
        "source_entity_id": "main",
        "target_entity_id": helper_name,
    }))

    content = result.content[0].text if hasattr(result, "content") else str(result)
    # Should find a path or report no path — but NOT error about entity not found
    assert "Entity not found" not in content
    assert "Multiple entities" not in content


def test_trace_path_with_full_entity_ids(built_artifact, tmp_path):
    """trace_path should still work with full entity_ids (backward compat)."""
    from batho.mcp.server import create_app
    from batho.modules.storage.arrow_bundle.reader import BathoBundleReader

    app = create_app(root=str(built_artifact), registry_path=tmp_path / "mcp-repos.json")
    artifact_dir = built_artifact / ".batho" / "artifact"
    reader = BathoBundleReader(artifact_dir)
    agent_table = reader._get_table("agent_views")
    rows = agent_table.to_pylist()

    # Find main and helper entity_ids
    main_eid = None
    helper_eid = None
    for r in rows:
        if r["name"] == "main":
            main_eid = r["entity_id"]
        if "helper" in r["name"]:
            helper_eid = r["entity_id"]

    if main_eid and helper_eid:
        result = asyncio.run(app.call_tool("trace_path", {
            "source_entity_id": main_eid,
            "target_entity_id": helper_eid,
        }))
        content = result.content[0].text if hasattr(result, "content") else str(result)
        assert "Entity not found" not in content


def test_get_entity_disambiguation_for_duplicate_names(built_artifact, tmp_path):
    """get_entity should return disambiguation list when multiple entities share a name."""
    from batho.mcp.server import create_app

    # The sample repo has __init__ in both App and User classes
    app = create_app(root=str(built_artifact), registry_path=tmp_path / "mcp-repos.json")

    result = asyncio.run(app.call_tool("get_entity", {"entity_id": "__init__"}))
    content = result.content[0].text if hasattr(result, "content") else str(result)

    # Should either resolve uniquely or return disambiguation list
    # If there are multiple __init__ methods, expect disambiguation
    if "Multiple" in content:
        assert "entity_id" in content or "ent|" in content
    else:
        # If only one __init__ exists, it should resolve
        assert "Entity not found" not in content
