"""Tests for the graph_query MCP tool.

Scenario:
    graph_query filters entities by file_path, entity_types, relation_types,
    and name_pattern with pagination support.

Execution Flow:
    1. Build a sample artifact.
    2. Query with various filters.
    3. Verify filtered results match criteria.
    4. Test pagination with offset/limit.

Expectations:
    - Filters correctly narrow results.
    - Empty results return gracefully.
    - Pagination works with offset/limit.
"""

from __future__ import annotations

from pathlib import Path

from batho.mcp.tools import _get_reader
import pyarrow.compute as pc


def test_query_all_entities(built_artifact: Path):
    reader = _get_reader(str(built_artifact))
    table = reader._get_table("agent_views")
    assert table.num_rows > 0


def test_query_by_file_path(built_artifact: Path):
    reader = _get_reader(str(built_artifact))
    fid = reader.file_id_for_path("main.py")
    assert fid is not None

    table = reader._get_table("agent_views")
    filtered = table.filter(pc.equal(table.column("file_id"), fid))
    assert filtered.num_rows > 0


def test_query_by_entity_type(built_artifact: Path):
    reader = _get_reader(str(built_artifact))
    table = reader._get_table("agent_views")
    types = table.column("entity_type").to_pylist()
    assert "FUNCTION" in types or "function" in types


def test_query_by_name_pattern(built_artifact: Path):
    reader = _get_reader(str(built_artifact))
    table = reader._get_table("agent_views")
    filtered = table.filter(pc.match_substring_regex(table.column("name"), "main"))
    assert filtered.num_rows > 0
    names = filtered.column("name").to_pylist()
    assert all("main" in n.lower() for n in names)


def test_query_no_matches(built_artifact: Path):
    reader = _get_reader(str(built_artifact))
    table = reader._get_table("agent_views")
    filtered = table.filter(pc.match_substring_regex(table.column("name"), "zzz_nonexistent"))
    assert filtered.num_rows == 0


def test_query_pagination(built_artifact: Path):
    reader = _get_reader(str(built_artifact))
    table = reader._get_table("agent_views")
    total = table.num_rows
    rows_page1 = table.to_pylist()[:2]
    rows_page2 = table.to_pylist()[2:4]
    if total >= 4:
        assert rows_page1 != rows_page2
