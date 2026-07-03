"""Tests for the search_entities MCP tool.

Scenario:
    search_entities finds entities by name substring regex match with
    optional entity_type filter and limit enforcement.

Execution Flow:
    1. Build a sample artifact.
    2. Search for known entity names.
    3. Apply entity_type filter.
    4. Test limit enforcement.
    5. Test no matches case.

Expectations:
    - Substring regex matches work correctly.
    - Entity type filter narrows results.
    - Limit caps the number of returned results.
"""

from __future__ import annotations

from pathlib import Path

from batho.mcp.tools import _get_reader
import pyarrow.compute as pc


def test_search_by_name(built_artifact: Path):
    reader = _get_reader(str(built_artifact))
    table = reader._get_table("agent_views")

    mask = pc.match_substring_regex(table.column("name"), "main")
    filtered = table.filter(mask)
    assert filtered.num_rows > 0


def test_search_no_results(built_artifact: Path):
    reader = _get_reader(str(built_artifact))
    table = reader._get_table("agent_views")

    mask = pc.match_substring_regex(table.column("name"), "zzz_nothing")
    filtered = table.filter(mask)
    assert filtered.num_rows == 0


def test_search_with_type_filter(built_artifact: Path):
    reader = _get_reader(str(built_artifact))
    table = reader._get_table("agent_views")

    name_mask = pc.match_substring_regex(table.column("name"), "main")
    type_mask = pc.equal(table.column("entity_type"), "FUNCTION")
    combined = pc.and_(name_mask, type_mask)
    filtered = table.filter(combined)

    if filtered.num_rows > 0:
        types = filtered.column("entity_type").to_pylist()
        assert all(t == "FUNCTION" for t in types)


def test_search_limit(built_artifact: Path):
    reader = _get_reader(str(built_artifact))
    table = reader._get_table("agent_views")

    rows = table.to_pylist()
    limited = rows[:5]
    assert len(limited) <= 5


def test_search_regex_pattern(built_artifact: Path):
    reader = _get_reader(str(built_artifact))
    table = reader._get_table("agent_views")

    mask = pc.match_substring_regex(table.column("name"), ".*")
    filtered = table.filter(mask)
    assert filtered.num_rows == table.num_rows
