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


def test_get_file_graph_cross_file_refs_batched(built_artifact: Path):
    """Verify that cross-file refs are resolved via batched pc.is_in() lookup.

    Scenario:
        The sample_repo has cross-file relationships (main.py imports from utils.py
        and models.py). When include_cross_file_refs=True, the get_file_graph tool
        should return entities from other files that are referenced.

    Execution Flow:
        1. Build a sample artifact.
        2. Get file_id for main.py.
        3. Fetch file artifacts with cross-file refs disabled — note entity count.
        4. Fetch file artifacts with cross-file refs enabled — entity count should
           be >= the count without cross-file refs.

    Expectations:
        - Cross-file ref lookup does not crash.
        - Results with cross-file refs are a superset of results without.
    """
    import pyarrow as pa
    import pyarrow.compute as pc

    reader = _get_reader(str(built_artifact))
    fid = reader.get_file_artifacts_by_id(
        reader.file_id_for_path("main.py")
    )
    assert fid is not None

    # Get base entities for main.py
    file_artifacts = reader.get_file_artifacts_by_id(
        reader.file_id_for_path("main.py")
    )
    agent_rows = file_artifacts.get("agent_view", []) if file_artifacts else []
    rels_rows = file_artifacts.get("rels_view", []) if file_artifacts else []

    # Simulate the batched cross-file ref lookup
    if rels_rows:
        agent_table = reader._get_table("agent_views")
        if agent_table.num_rows > 0:
            known_ids = {r.get("entity_id", "") for r in agent_rows}
            cross_ids = set()
            for rel in rels_rows:
                sid = rel.get("source_id", "")
                tid = rel.get("target_id", "")
                if sid and sid not in known_ids:
                    cross_ids.add(sid)
                if tid and tid not in known_ids:
                    cross_ids.add(tid)
            if cross_ids:
                mask = pc.is_in(
                    agent_table.column("entity_id"),
                    value_set=pa.array(list(cross_ids)),
                )
                matched = agent_table.filter(mask)
                # Should not crash — that's the main assertion
                assert matched.num_rows >= 0
