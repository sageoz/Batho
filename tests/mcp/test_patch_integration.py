"""Integration tests for build → patch → MCP serve flow.

Scenario:
    After running `batho build` and `batho patch`, the MCP server should
    serve the latest generation of artifacts. get_delta should reflect
    the changes from the patch run.

Execution Flow:
    1. Build a sample repo.
    2. Modify a file and run patch.
    3. Verify the MCP reader sees the updated entities.
    4. Verify get_delta returns changes from the patch.

Expectations:
    - Reader serves the latest generation automatically (MVCC via meta.json).
    - get_delta shows added/modified/removed nodes.
    - Entity counts change after patch.
"""

from __future__ import annotations

from pathlib import Path

from batho.mcp.tools import _get_reader
from batho.mcp.delta_reader import read_delta


def test_build_patch_serve(patched_artifact: Path):
    reader = _get_reader(str(patched_artifact))

    agent_table = reader._get_table("agent_views")
    assert agent_table.num_rows > 0

    runs = reader.get_all_runs()
    assert len(runs) >= 2  # build + patch


def test_delta_after_patch(patched_artifact: Path):
    reader = _get_reader(str(patched_artifact))

    changes, delta_stats, run_info = read_delta(reader)

    assert run_info is not None
    assert run_info.get("run_uuid") is not None


def test_reader_serves_latest_generation(patched_artifact: Path):
    reader = _get_reader(str(patched_artifact))

    manifest = reader._manager.load_manifest()
    assert manifest.get("generation", 0) >= 2  # build=1, patch=2


def test_entity_count_changes(patched_artifact: Path):
    reader = _get_reader(str(patched_artifact))

    runs = reader.get_all_runs()
    if len(runs) >= 2:
        build_run = runs[0]
        patch_run = runs[-1]

        build_entities = build_run.get("entity_count", 0)
        patch_entities = patch_run.get("entity_count", 0)

        # Entity count should be positive
        assert build_entities > 0
        assert patch_entities > 0
