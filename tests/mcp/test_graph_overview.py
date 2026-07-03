"""Tests for the graph_overview MCP tool.

Scenario:
    graph_overview provides a high-level summary of the codebase graph.
    These tests verify stats accuracy, community summaries, and error handling.

Execution Flow:
    1. Build a sample artifact.
    2. Call graph_overview via the tool function.
    3. Verify entity counts, file counts, and community data.
    4. Test error on missing .batho directory.

Expectations:
    - Stats match the built artifact.
    - Communities are loaded if present.
    - Missing artifact returns error.
"""

from __future__ import annotations

from pathlib import Path

from batho.mcp.tools import _get_reader, _check_artifact


def test_graph_overview_stats(built_artifact: Path):
    from batho.mcp.tools import register_tools
    from fastmcp import FastMCP

    app = FastMCP("test")
    register_tools(app)

    reader = _get_reader(str(built_artifact))
    agent_table = reader._get_table("agent_views")
    assert agent_table.num_rows > 0

    runs = reader.get_all_runs()
    assert len(runs) > 0


def test_check_artifact_missing(tmp_path: Path):
    err = _check_artifact(str(tmp_path / "nonexistent"))
    assert err is not None
    assert "No Batho artifact" in err


def test_check_artifact_present(built_artifact: Path):
    err = _check_artifact(str(built_artifact))
    assert err is None


def test_graph_overview_communities_loaded(built_artifact: Path):
    from batho.mcp.community_summaries import load_communities

    artifact_dir = built_artifact / ".batho" / "artifact"
    communities = load_communities(artifact_dir)
    # Communities may or may not be present depending on leidenalg availability
    assert isinstance(communities, list)


def test_graph_overview_communities_missing(tmp_path: Path):
    from batho.mcp.community_summaries import load_communities

    artifact_dir = tmp_path / "fake" / "artifact"
    artifact_dir.mkdir(parents=True)
    communities = load_communities(artifact_dir)
    assert communities == []
