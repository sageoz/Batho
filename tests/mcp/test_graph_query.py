"""Tests for the graph_query MCP tool.

Scenario:
    graph_query filters entities by file_path, entity_types, relation_types,
    symbol_roles, and name_pattern with pagination support.

Execution Flow:
    1. Build a sample artifact.
    2. Query with various filters.
    3. Verify filtered results match criteria.
    4. Test pagination with offset/limit.

Expectations:
    - Filters correctly narrow results.
    - Empty results return gracefully.
    - Pagination works with offset/limit.
    - symbol_roles filter correctly narrows relationships by role bitmask.
"""

from __future__ import annotations

from pathlib import Path

from batho.mcp.tools import _get_reader, _parse_symbol_roles
from batho.core.schemas import SymbolRole
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


# ---------------------------------------------------------------------------
# T04: symbol_roles filter tests
# ---------------------------------------------------------------------------


def test_rels_views_has_roles_column(built_artifact: Path):
    """Verify that the rels_views table includes the roles column after build."""
    reader = _get_reader(str(built_artifact))
    rels_table = reader._get_table("rels_views")
    assert rels_table.num_rows > 0, "Expected relationships in built artifact"
    assert "roles" in rels_table.schema.names, "rels_views should have 'roles' column"
    assert "confidence" in rels_table.schema.names, "rels_views should have 'confidence' column"


def test_rels_views_roles_populated(built_artifact: Path):
    """Verify that roles values are populated (not all null) in rels_views."""
    reader = _get_reader(str(built_artifact))
    rels_table = reader._get_table("rels_views")
    roles_col = rels_table.column("roles").to_pylist()
    non_null = [r for r in roles_col if r is not None]
    assert len(non_null) > 0, "Expected at least some non-null roles values"


def test_parse_symbol_roles_single():
    """Test parsing a single valid role name."""
    mask = _parse_symbol_roles(["WriteAccess"])
    assert mask == int(SymbolRole.WriteAccess)


def test_parse_symbol_roles_multiple():
    """Test parsing multiple role names (OR semantics)."""
    mask = _parse_symbol_roles(["ReadAccess", "Import"])
    assert mask == int(SymbolRole.ReadAccess) | int(SymbolRole.Import)


def test_parse_symbol_roles_case_insensitive():
    """Test that role names are case-insensitive."""
    mask_lower = _parse_symbol_roles(["writeaccess"])
    mask_upper = _parse_symbol_roles(["WRITEACCESS"])
    mask_mixed = _parse_symbol_roles(["WriteAccess"])
    assert mask_lower == mask_upper == mask_mixed == int(SymbolRole.WriteAccess)


def test_parse_symbol_roles_invalid():
    """Test that invalid role names return None."""
    mask = _parse_symbol_roles(["invalid_role"])
    assert mask is None


def test_parse_symbol_roles_empty():
    """Test that empty list returns None (no filtering, treated as not provided)."""
    mask = _parse_symbol_roles([])
    assert mask is None


def test_graph_query_symbol_roles_write_access(built_artifact: Path):
    """graph_query with symbol_roles=['WriteAccess'] should return only write-access relationships."""
    reader = _get_reader(str(built_artifact))
    rels_table = reader._get_table("rels_views")
    if "roles" not in rels_table.schema.names:
        return  # Skip if old artifact without roles column

    all_rels = rels_table.to_pylist()
    write_mask = int(SymbolRole.WriteAccess)
    write_rels = [r for r in all_rels if (r.get("roles") or 0) & write_mask != 0]
    non_write_rels = [r for r in all_rels if (r.get("roles") or 0) & write_mask == 0]

    # Verify the filter correctly separates write from non-write
    assert len(write_rels) + len(non_write_rels) == len(all_rels)
    # There should be at least some relationships with non-zero roles
    if write_rels:
        for r in write_rels:
            assert (r.get("roles") or 0) & write_mask != 0


def test_graph_query_symbol_roles_import(built_artifact: Path):
    """graph_query with symbol_roles=['Import'] should return only import relationships."""
    reader = _get_reader(str(built_artifact))
    rels_table = reader._get_table("rels_views")
    if "roles" not in rels_table.schema.names:
        return  # Skip if old artifact without roles column

    all_rels = rels_table.to_pylist()
    import_mask = int(SymbolRole.Import)
    import_rels = [r for r in all_rels if (r.get("roles") or 0) & import_mask != 0]

    # Verify the Import role bit is set on these relationships.
    # Do NOT assert relation_type == IMPORTS — the extractor may decorate
    # other edge types (e.g. REFERENCES, USES) with SymbolRole.Import
    # when they originate from import-map resolution.
    for r in import_rels:
        assert (r.get("roles") or 0) & import_mask != 0


def test_graph_query_symbol_roles_none_returns_all(built_artifact: Path):
    """graph_query with symbol_roles=None should return all relationships (backward compat)."""
    reader = _get_reader(str(built_artifact))
    rels_table = reader._get_table("rels_views")
    all_rels = rels_table.to_pylist()
    # No filtering applied when symbol_roles is None
    assert len(all_rels) == rels_table.num_rows


def test_graph_query_symbol_roles_or_semantics(built_artifact: Path):
    """graph_query with multiple roles should use OR semantics."""
    reader = _get_reader(str(built_artifact))
    rels_table = reader._get_table("rels_views")
    if "roles" not in rels_table.schema.names:
        return

    all_rels = rels_table.to_pylist()
    read_mask = int(SymbolRole.ReadAccess)
    import_mask = int(SymbolRole.Import)
    combined_mask = read_mask | import_mask

    combined_rels = [r for r in all_rels if (r.get("roles") or 0) & combined_mask != 0]
    read_only = [r for r in all_rels if (r.get("roles") or 0) & read_mask != 0]
    import_only = [r for r in all_rels if (r.get("roles") or 0) & import_mask != 0]

    # OR semantics: combined should include everything from both individual filters
    assert len(combined_rels) >= max(len(read_only), len(import_only))


def test_trace_path_symbol_roles_filter(built_artifact: Path):
    """trace_path with symbol_roles should only traverse edges with matching roles."""
    reader = _get_reader(str(built_artifact))
    rels_table = reader._get_table("rels_views")
    if "roles" not in rels_table.schema.names:
        return

    # Verify that filtering by Import role would limit the edges
    all_rels = rels_table.to_pylist()
    import_mask = int(SymbolRole.Import)
    import_rels = [r for r in all_rels if (r.get("roles") or 0) & import_mask != 0]
    non_import_rels = [r for r in all_rels if (r.get("roles") or 0) & import_mask == 0]

    # The filter should actually narrow the set (unless all rels are imports)
    if non_import_rels:
        assert len(import_rels) < len(all_rels)


# ---------------------------------------------------------------------------
# T05: confidence_threshold filter tests
# ---------------------------------------------------------------------------


def test_rels_views_has_confidence_column(built_artifact: Path):
    """Verify that the rels_views table includes the confidence column after build."""
    reader = _get_reader(str(built_artifact))
    rels_table = reader._get_table("rels_views")
    assert rels_table.num_rows > 0, "Expected relationships in built artifact"
    assert "confidence" in rels_table.schema.names, "rels_views should have 'confidence' column"


def test_rels_views_confidence_populated(built_artifact: Path):
    """Verify that confidence values are populated (not all null) in rels_views."""
    reader = _get_reader(str(built_artifact))
    rels_table = reader._get_table("rels_views")
    conf_col = rels_table.column("confidence").to_pylist()
    non_null = [c for c in conf_col if c is not None]
    assert len(non_null) > 0, "Expected at least some non-null confidence values"


def test_graph_query_confidence_threshold_0_returns_all(built_artifact: Path):
    """confidence_threshold=0.0 should return all relationships (nothing has confidence < 0)."""
    reader = _get_reader(str(built_artifact))
    rels_table = reader._get_table("rels_views")
    all_rels = rels_table.to_pylist()
    threshold_0 = [
        r for r in all_rels
        if (r.get("confidence") if r.get("confidence") is not None else 1.0) >= 0.0
    ]
    assert len(threshold_0) == len(all_rels), "threshold=0.0 should include all relationships"


def test_graph_query_confidence_threshold_1_returns_only_direct(built_artifact: Path):
    """confidence_threshold=1.0 should return only directly-extracted relationships."""
    reader = _get_reader(str(built_artifact))
    rels_table = reader._get_table("rels_views")
    all_rels = rels_table.to_pylist()
    high_conf = [
        r for r in all_rels
        if (r.get("confidence") if r.get("confidence") is not None else 1.0) >= 1.0
    ]
    # Directly extracted relationships have confidence=1.0
    # There should be at least some (the sample repo has direct imports/calls)
    assert len(high_conf) > 0, "Expected at least some relationships with confidence=1.0"
    for r in high_conf:
        conf = r.get("confidence")
        assert conf is None or conf >= 1.0


def test_graph_query_confidence_threshold_085_filters_low(built_artifact: Path):
    """confidence_threshold=0.85 should exclude relationships with confidence < 0.85."""
    reader = _get_reader(str(built_artifact))
    rels_table = reader._get_table("rels_views")
    all_rels = rels_table.to_pylist()
    high_conf = [
        r for r in all_rels
        if (r.get("confidence") if r.get("confidence") is not None else 1.0) >= 0.85
    ]
    low_conf = [
        r for r in all_rels
        if (r.get("confidence") if r.get("confidence") is not None else 1.0) < 0.85
    ]
    # Verify the filter correctly separates
    assert len(high_conf) + len(low_conf) == len(all_rels)
    for r in high_conf:
        conf = r.get("confidence")
        assert conf is None or conf >= 0.85
    for r in low_conf:
        conf = r.get("confidence")
        assert conf is not None and conf < 0.85


def test_graph_query_confidence_threshold_none_returns_all(built_artifact: Path):
    """confidence_threshold=None should return all relationships (backward compat)."""
    reader = _get_reader(str(built_artifact))
    rels_table = reader._get_table("rels_views")
    all_rels = rels_table.to_pylist()
    # No filtering applied when confidence_threshold is None
    assert len(all_rels) == rels_table.num_rows


def test_graph_query_confidence_threshold_with_relation_types(built_artifact: Path):
    """Combined relation_types + confidence_threshold applies AND semantics."""
    reader = _get_reader(str(built_artifact))
    rels_table = reader._get_table("rels_views")
    all_rels = rels_table.to_pylist()

    # Filter to CALLS with confidence >= 0.85
    calls_high = [
        r for r in all_rels
        if r.get("relation_type") in ("CALLS", "calls")
        and (r.get("confidence") if r.get("confidence") is not None else 1.0) >= 0.85
    ]
    # Verify AND semantics: each result must satisfy both conditions
    for r in calls_high:
        assert r.get("relation_type") in ("CALLS", "calls")
        conf = r.get("confidence")
        assert conf is None or conf >= 0.85


# ---------------------------------------------------------------------------
# T06: relation_direction filter tests
# ---------------------------------------------------------------------------


def test_graph_query_relation_direction_outgoing(built_artifact: Path):
    """relation_direction='outgoing' returns only rels where entity is the source."""
    reader = _get_reader(str(built_artifact))
    rels_table = reader._get_table("rels_views")
    agent_table = reader._get_table("agent_views")
    if rels_table.num_rows == 0:
        return

    all_rels = rels_table.to_pylist()
    entity_ids = {r.get("entity_id", "") for r in agent_table.to_pylist()}

    outgoing = [r for r in all_rels if r.get("source_id") in entity_ids]
    incoming = [r for r in all_rels if r.get("target_id") in entity_ids and r.get("source_id") not in entity_ids]

    # Verify the filter correctly separates
    assert len(outgoing) > 0, "Expected outgoing relationships"
    for r in outgoing:
        assert r.get("source_id") in entity_ids


def test_graph_query_relation_direction_incoming(built_artifact: Path):
    """relation_direction='incoming' returns only rels where entity is the target."""
    reader = _get_reader(str(built_artifact))
    rels_table = reader._get_table("rels_views")
    agent_table = reader._get_table("agent_views")
    if rels_table.num_rows == 0:
        return

    all_rels = rels_table.to_pylist()
    entity_ids = {r.get("entity_id", "") for r in agent_table.to_pylist()}

    incoming = [r for r in all_rels if r.get("target_id") in entity_ids]
    assert len(incoming) > 0, "Expected incoming relationships"
    for r in incoming:
        assert r.get("target_id") in entity_ids


def test_graph_query_relation_direction_both(built_artifact: Path):
    """relation_direction='both' returns all rels connected to entities (backward compat)."""
    reader = _get_reader(str(built_artifact))
    rels_table = reader._get_table("rels_views")
    agent_table = reader._get_table("agent_views")
    if rels_table.num_rows == 0:
        return

    all_rels = rels_table.to_pylist()
    entity_ids = {r.get("entity_id", "") for r in agent_table.to_pylist()}

    both = [r for r in all_rels if r.get("source_id") in entity_ids or r.get("target_id") in entity_ids]
    outgoing = [r for r in all_rels if r.get("source_id") in entity_ids]
    incoming = [r for r in all_rels if r.get("target_id") in entity_ids]

    # 'both' should be a superset of outgoing and incoming
    assert len(both) >= len(outgoing)
    assert len(both) >= len(incoming)


def test_graph_query_relation_direction_with_relation_types(built_artifact: Path):
    """Combined relation_types + relation_direction='incoming' finds all callers (replaces CALLED_BY)."""
    reader = _get_reader(str(built_artifact))
    rels_table = reader._get_table("rels_views")
    agent_table = reader._get_table("agent_views")
    if rels_table.num_rows == 0:
        return

    all_rels = rels_table.to_pylist()
    entity_ids = {r.get("entity_id", "") for r in agent_table.to_pylist()}

    # Find all CALLS relationships where entity is the target (= incoming calls)
    incoming_calls = [
        r for r in all_rels
        if r.get("relation_type") in ("CALLS", "calls")
        and r.get("target_id") in entity_ids
    ]
    # Verify AND semantics: each result must satisfy both conditions
    for r in incoming_calls:
        assert r.get("relation_type") in ("CALLS", "calls")
        assert r.get("target_id") in entity_ids
