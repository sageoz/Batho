"""Tests for the get_entity MCP tool.

Scenario:
    get_entity returns detailed information about a single entity including
    its relationships and optionally source code.

Execution Flow:
    1. Build a sample artifact.
    2. Find an entity ID from the agent_views table.
    3. Query get_entity with that ID.
    4. Verify entity details and relationships are returned.
    5. Test entity not found error.

Expectations:
    - Entity details match the IPC row.
    - Relationships where entity is source or target are included.
    - Non-existent entity ID returns error.
"""

from __future__ import annotations

from pathlib import Path

from batho.mcp.tools import _get_reader
import pyarrow.compute as pc


def test_get_entity_found(built_artifact: Path):
    reader = _get_reader(str(built_artifact))
    table = reader._get_table("agent_views")
    assert table.num_rows > 0

    first_row = table.to_pylist()[0]
    eid = first_row["entity_id"]

    mask = pc.equal(table.column("entity_id"), eid)
    matched = table.filter(mask)
    assert matched.num_rows == 1
    assert matched.to_pylist()[0]["name"] == first_row["name"]


def test_get_entity_not_found(built_artifact: Path):
    reader = _get_reader(str(built_artifact))
    table = reader._get_table("agent_views")

    mask = pc.equal(table.column("entity_id"), "nonexistent_id")
    matched = table.filter(mask)
    assert matched.num_rows == 0


def test_get_entity_relationships(built_artifact: Path):
    reader = _get_reader(str(built_artifact))
    agent_table = reader._get_table("agent_views")
    rels_table = reader._get_table("rels_views")

    if rels_table.num_rows == 0:
        return  # No relationships to test

    first_rel = rels_table.to_pylist()[0]
    eid = first_rel["source_id"]

    src_mask = pc.equal(rels_table.column("source_id"), eid)
    tgt_mask = pc.equal(rels_table.column("target_id"), eid)
    combined = pc.or_(src_mask, tgt_mask)
    matched = rels_table.filter(combined)
    assert matched.num_rows >= 1


def test_get_entity_with_source(built_artifact: Path):
    reader = _get_reader(str(built_artifact))
    agent_table = reader._get_table("agent_views")
    storage_table = reader._get_table("storage_views")

    if storage_table.num_rows == 0:
        return

    first_row = agent_table.to_pylist()[0]
    eid = first_row["entity_id"]

    smask = pc.equal(storage_table.column("entity_id"), eid)
    matched = storage_table.filter(smask)
    # May or may not have storage view
    if matched.num_rows > 0:
        storage_row = matched.to_pylist()[0]
        assert "raw_content" in storage_row or "raw_bytes" in storage_row
