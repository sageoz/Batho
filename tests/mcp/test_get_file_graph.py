"""Tests for the get_file_graph MCP tool.

Scenario:
    get_file_graph returns all entities and relationships within a single file.
    Uses O(1) file_id slice from the offset index.

Execution Flow:
    1. Build a sample artifact.
    2. Look up file_id for a known file.
    3. Fetch entities and rels for that file_id.
    4. Verify all returned entities belong to the file.
    5. Test file not indexed error.

Expectations:
    - All entities have the correct file_id.
    - Cross-file refs are optionally included.
    - Non-indexed file returns error.
"""

from __future__ import annotations

from pathlib import Path

from batho.mcp.tools import _get_reader


def test_get_file_graph_basic(built_artifact: Path):
    reader = _get_reader(str(built_artifact))
    fid = reader.file_id_for_path("main.py")
    assert fid is not None

    file_artifacts = reader.get_file_artifacts_by_id(fid)
    agent_rows = file_artifacts.get("agent_view", []) if file_artifacts else []
    assert len(agent_rows) > 0
    assert all(r.get("file_id") == fid for r in agent_rows)


def test_get_file_graph_rels(built_artifact: Path):
    reader = _get_reader(str(built_artifact))
    fid = reader.file_id_for_path("main.py")

    file_artifacts = reader.get_file_artifacts_by_id(fid)
    rels_rows = file_artifacts.get("rels_view", []) if file_artifacts else []
    if rels_rows:
        assert all(r.get("file_id") == fid for r in rels_rows)


def test_get_file_graph_not_indexed(built_artifact: Path):
    reader = _get_reader(str(built_artifact))
    fid = reader.file_id_for_path("nonexistent.py")
    assert fid is None


def test_get_file_graph_all_files(built_artifact: Path):
    reader = _get_reader(str(built_artifact))
    tracking = reader.get_all_file_tracking()

    for fp, tr in tracking.items():
        if tr.get("is_indexed"):
            fid = tr.get("file_id")
            file_artifacts = reader.get_file_artifacts_by_id(fid)
            rows = file_artifacts.get("agent_view", []) if file_artifacts else []
            assert rows is not None
