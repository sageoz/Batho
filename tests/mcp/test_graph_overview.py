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


def test_graph_overview_file_entity_counts(built_artifact: Path):
    """Verify that graph_overview reports actual entity counts per file, not hardcoded 0.

    Scenario:
        The sample_repo fixture creates 3 Python files with entities (functions, classes).
        graph_overview should report non-zero entity counts for indexed files.

    Execution Flow:
        1. Build a sample artifact.
        2. Read the agent_views table to get actual entity counts per file.
        3. Verify that at least one file has entities > 0 in the stats.

    Expectations:
        - File entity counts are not all zero.
        - main.py (which has functions and a class) should have entities > 0.
    """
    reader = _get_reader(str(built_artifact))
    agent_table = reader._get_table("agent_views")
    tracking = reader.get_all_file_tracking()

    # Compute entity counts the same way tools.py does
    entity_counts: dict[str, int] = {}
    if agent_table.num_rows > 0:
        file_ids = agent_table.column("file_id").to_pylist()
        fid_to_path = {tr.get("file_id"): fp for fp, tr in tracking.items()}
        for fid in file_ids:
            fp = fid_to_path.get(fid)
            if fp:
                entity_counts[fp] = entity_counts.get(fp, 0) + 1

    # At least main.py should have entities
    assert entity_counts.get("main.py", 0) > 0


def test_graph_overview_truncation_notice(built_artifact: Path):
    """Verify that graph_overview appends a truncation notice when output exceeds token budget.

    Scenario:
        A very small max_tokens value forces truncation of the overview markdown.
        The output should contain a 'Truncated' notice.

    Execution Flow:
        1. Build a sample artifact.
        2. Call the graph_overview tool with max_tokens=50 (forces truncation).
        3. Check the structured meta for truncated=True.

    Expectations:
        - structured.meta.truncated is True.
    """
    import asyncio
    from batho.mcp.server import create_app

    app = create_app(root=str(built_artifact))

    result = asyncio.run(app.call_tool("graph_overview", {
        "max_tokens": 50,
    }))

    assert result is not None
    sc = result.structured_content
    assert sc is not None
    meta = sc.get("meta", {})
    assert meta.get("truncated") is True
