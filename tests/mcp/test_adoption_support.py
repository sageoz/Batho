"""Tests for MCP adoption support (T6).

Scenario:
    The server must steer agents toward Batho-first behavior:
    - Every tool description follows the USE when / DO NOT USE when template.
    - Dual-output tools declare outputSchema and their structuredContent
      validates against it.
    - Toolsets (mcp.toolsets) resolve to disabled/enabled sets with
      secure-by-default behavior unchanged.

Execution Flow:
    1. Create the FastMCP app via create_app() with all tools enabled.
    2. Inspect descriptions, annotations, and output schemas.
    3. Exercise toolset resolution via create_app() with config fixtures.

Expectations:
    - All 20 tool descriptions contain USE and DO NOT USE markers.
    - 8 dual-output tools declare outputSchema; sample structuredContent
      validates.
    - Query tools are read-only + idempotent; Tier-3 matrix holds.
    - Toolsets config gates admin tools; defaults unchanged when absent.
"""

from __future__ import annotations

import asyncio
import json

import pytest


@pytest.fixture
def app():
    from batho.mcp.server import create_app
    return create_app(disabled_tools=set())


ALL_TOOLS = [
    "list_repos", "add_repo", "remove_repo",
    "graph_overview", "graph_query", "get_entity",
    "trace_path", "get_file_graph", "file_connectivity", "search_entities",
    "get_delta", "batho_status", "batho_list_runs", "batho_diff",
    "batho_build", "batho_patch", "batho_export",
    "batho_gc", "batho_fix", "batho_load",
]

DUAL_OUTPUT_TOOLS = {
    "graph_overview", "graph_query", "get_entity", "trace_path",
    "get_file_graph", "file_connectivity", "search_entities", "get_delta",
}

QUERY_TOOLS = [
    "list_repos", "graph_overview", "graph_query", "get_entity",
    "trace_path", "get_file_graph", "file_connectivity", "search_entities",
    "get_delta", "batho_status", "batho_list_runs", "batho_diff",
]


def test_all_descriptions_have_use_marker(app):
    """Every tool description must contain a USE when trigger.

    "DO NOT USE" also contains "USE", so strip it before checking —
    otherwise a description that lost its positive USE clause still passes.
    """
    tools = asyncio.run(app.list_tools())
    assert len(tools) == 20
    for tool in tools:
        desc = tool.description or ""
        positive = desc.replace("DO NOT USE", "")
        assert "USE" in positive, f"Tool {tool.name} description missing USE marker"


def test_all_descriptions_have_do_not_use_marker(app):
    """Every tool description must contain a DO NOT USE when trigger."""
    tools = asyncio.run(app.list_tools())
    for tool in tools:
        desc = tool.description or ""
        assert "DO NOT USE" in desc, \
            f"Tool {tool.name} description missing DO NOT USE marker"


def test_all_descriptions_mention_return_shape(app):
    """Every tool description must summarize what it returns."""
    tools = asyncio.run(app.list_tools())
    for tool in tools:
        desc = tool.description or ""
        assert "Returns" in desc, \
            f"Tool {tool.name} description missing return-shape summary"


def test_query_tools_idempotent(app):
    """Tier-1/2 query tools must be read-only, non-destructive, idempotent."""
    tools = asyncio.run(app.list_tools())
    tool_map = {t.name: t for t in tools}
    for name in QUERY_TOOLS:
        ann = tool_map[name].annotations
        assert ann.readOnlyHint is True, f"{name} readOnlyHint"
        assert ann.destructiveHint is False, f"{name} destructiveHint"
        assert ann.idempotentHint is True, f"{name} idempotentHint"


def test_tier3_annotation_matrix(app):
    """Tier-3 annotations per the T6 matrix.

    Only batho_patch is idempotent (a second patch with no edits is a
    no-op). batho_build/export/fix perform real work per call — a new
    MVCC run, a written file, a repair pass — so they must not claim
    idempotency to hosts making auto-approval decisions.
    """
    tools = asyncio.run(app.list_tools())
    tool_map = {t.name: t for t in tools}

    for name in ("batho_gc", "batho_load"):
        assert tool_map[name].annotations.destructiveHint is True, name

    for name in ("batho_build", "batho_patch"):
        ann = tool_map[name].annotations
        assert ann.readOnlyHint is False, name

    assert tool_map["batho_patch"].annotations.idempotentHint is True
    for name in ("batho_build", "batho_export", "batho_fix"):
        assert tool_map[name].annotations.idempotentHint is not True, name


def test_dual_output_tools_declare_output_schema(app):
    """All dual-output tools must declare an outputSchema."""
    tools = asyncio.run(app.list_tools())
    tool_map = {t.name: t for t in tools}
    for name in DUAL_OUTPUT_TOOLS:
        schema = tool_map[name].output_schema
        assert schema, f"Tool {name} missing output_schema"
        assert schema.get("type") == "object", f"Tool {name} schema not object"
        assert "properties" in schema, f"Tool {name} schema has no properties"


def test_graph_output_schema_shape(app):
    """The shared graph output schema must match build_dual_output's shape."""
    from batho.mcp.tools import GRAPH_OUTPUT_SCHEMA

    assert set(GRAPH_OUTPUT_SCHEMA["properties"]) == {"graph", "meta"}
    graph_props = GRAPH_OUTPUT_SCHEMA["properties"]["graph"]["properties"]
    assert "nodes" in graph_props
    assert "edges" in graph_props


def test_structured_content_validates_against_schema():
    """Sample build_dual_output structured content must validate."""
    jsonschema = pytest.importorskip("jsonschema")

    from batho.mcp.graph_builder import build_dual_output
    from batho.mcp.tools import GRAPH_OUTPUT_SCHEMA

    agent_rows = [{
        "entity_id": "e1", "entity_type": "FUNCTION", "name": "foo",
        "file_id": 1, "start_line": 1, "end_line": 5,
    }]
    rels_rows = [{
        "source_id": "e1", "target_id": "e2", "relation_type": "CALLS",
    }]
    _, structured = build_dual_output(agent_rows, rels_rows, {1: "a.py"})

    jsonschema.validate(structured, GRAPH_OUTPUT_SCHEMA)


def test_get_delta_output_schema_validates():
    """Sample build_delta_structured content must validate against schema."""
    jsonschema = pytest.importorskip("jsonschema")

    from batho.mcp.delta_reader import build_delta_structured
    from batho.mcp.tools import GET_DELTA_OUTPUT_SCHEMA

    structured = build_delta_structured(
        [{"entity_id": "e1", "change_kind": "added"}],
        {"nodes_added": 1},
        {"run_uuid": "patch_1"},
    )
    jsonschema.validate(structured, GET_DELTA_OUTPUT_SCHEMA)

    # _inject_banner writes a top-level "meta" (staleness_banner) when the
    # watcher reports staleness — the key must be schema-declared
    # (issue 84a02db9ccc0).
    assert "meta" in GET_DELTA_OUTPUT_SCHEMA["properties"]
    structured["meta"] = {"staleness_banner": "stale"}
    jsonschema.validate(structured, GET_DELTA_OUTPUT_SCHEMA)


def test_toolsets_defined_and_partitioned():
    """Toolsets must cover all 20 tools exactly once."""
    from batho.mcp.tools import TOOLSETS

    all_members = set()
    for name, members in TOOLSETS.items():
        assert members, f"Toolset {name} is empty"
        overlap = all_members & members
        assert not overlap, f"Toolset {name} overlaps with earlier sets: {overlap}"
        all_members |= members
    assert len(all_members) == 20


def test_toolsets_default_disabled_unchanged():
    """Default disabled set must remain the secure-by-default Tier-3 subset."""
    from batho.mcp.tools import DEFAULT_DISABLED_TOOLS

    assert DEFAULT_DISABLED_TOOLS == {
        "batho_build", "batho_export", "batho_load", "batho_gc",
    }


def test_toolsets_config_resolution(tmp_path, monkeypatch):
    """mcp.toolsets must resolve to the expected disabled set."""
    from batho.mcp import server
    from batho.mcp.tools import TOOLSETS

    cfg = {
        "mcp": {
            "enabled": True,
            "toolsets": {"admin": True, "registry": False},
        }
    }
    monkeypatch.setattr(
        "batho.core.config.get_config_with_root", lambda root: cfg,
    )

    captured = {}

    def fake_register(app, **kwargs):
        captured["disabled_tools"] = kwargs.get("disabled_tools")
        captured["enabled_tools"] = kwargs.get("enabled_tools")

    monkeypatch.setattr(server, "register_tools", fake_register)
    monkeypatch.setattr(server, "register_prompts", lambda app: None)
    monkeypatch.setattr(server, "register_resources", lambda app, registry=None: None)

    server.create_app(root=str(tmp_path))

    disabled = captured["disabled_tools"]
    assert disabled is not None
    # admin: true → all admin tools enabled (removed from disabled set)
    assert not (disabled & TOOLSETS["admin"])
    # registry: false → registry tools disabled
    assert TOOLSETS["registry"] <= disabled
    # unlisted groups keep defaults — retrieval/diagnostics stay enabled
    assert not (disabled & TOOLSETS["retrieval"])
    assert not (disabled & TOOLSETS["diagnostics"])


def test_toolsets_absent_keeps_defaults(tmp_path, monkeypatch):
    """Without mcp.toolsets, disabled set stays None (register_tools default)."""
    from batho.mcp import server

    cfg = {"mcp": {"enabled": True, "tools": {}}}
    monkeypatch.setattr(
        "batho.core.config.get_config_with_root", lambda root: cfg,
    )

    captured = {}

    def fake_register(app, **kwargs):
        captured["disabled_tools"] = kwargs.get("disabled_tools")
        captured["enabled_tools"] = kwargs.get("enabled_tools")

    monkeypatch.setattr(server, "register_tools", fake_register)
    monkeypatch.setattr(server, "register_prompts", lambda app: None)
    monkeypatch.setattr(server, "register_resources", lambda app, registry=None: None)

    server.create_app(root=str(tmp_path))

    # No toolsets and no explicit lists → both stay None so register_tools
    # applies its own secure-by-default set.
    assert captured["disabled_tools"] is None
    assert captured["enabled_tools"] is None


def test_instructions_mention_skill_pack_flow():
    """Server instructions must mention the skill-pack flow and freshness."""
    from batho.mcp.instructions import INSTRUCTIONS

    assert "batho_status" in INSTRUCTIONS
    assert "batho-specs" in INSTRUCTIONS
    assert "batho-execute" in INSTRUCTIONS
    assert "batho-review" in INSTRUCTIONS
    # ≤500 tokens (rough proxy: 4 chars/token)
    assert len(INSTRUCTIONS) < 500 * 4 * 2  # generous bound
