"""Tests for dual-output equivalence between content and structuredContent.

Scenario:
    The MCP tools return both markdown `content` and JSON `structuredContent`.
    Both must contain the same entities/edges, but content excludes internal
    fields like IDs while structuredContent includes everything.

Execution Flow:
    1. Create mock rows with known entity/relationship data.
    2. Call build_dual_output.
    3. Verify content contains entity names but not raw IDs.
    4. Verify structuredContent contains full node/edge dicts with IDs.

Expectations:
    - Entity names appear in both content and structuredContent.
    - structuredContent.nodes includes id, parent_id, metadata.
    - content markdown does not contain entity_id strings.
"""

from __future__ import annotations

from batho.mcp.graph_builder import build_dual_output


def test_entity_names_in_both_outputs():
    rows = [
        {"entity_id": "ent|func|main.py|0|10|1|5|main", "entity_type": "FUNCTION",
         "name": "main", "file_id": 1, "start_line": 1, "end_line": 5},
    ]
    file_paths = {1: "main.py"}

    markdown, structured = build_dual_output(rows, [], file_paths)
    assert "main" in markdown
    assert any(n["name"] == "main" for n in structured["graph"]["nodes"])


def test_structured_has_ids_content_does_not():
    eid = "ent|func|main.py|0|10|1|5|main"
    rows = [
        {"entity_id": eid, "entity_type": "FUNCTION", "name": "main", "file_id": 1, "start_line": 1, "end_line": 5},
    ]
    file_paths = {1: "main.py"}

    markdown, structured = build_dual_output(rows, [], file_paths)
    assert structured["graph"]["nodes"][0]["id"] == eid
    assert eid not in markdown


def test_edge_count_matches():
    rows = [
        {"entity_id": "e1", "entity_type": "FUNCTION", "name": "a", "file_id": 1, "start_line": 1, "end_line": 5},
        {"entity_id": "e2", "entity_type": "FUNCTION", "name": "b", "file_id": 1, "start_line": 6, "end_line": 10},
    ]
    rels = [
        {"source_id": "e1", "target_id": "e2", "relation_type": "CALLS"},
    ]
    file_paths = {1: "main.py"}

    _, structured = build_dual_output(rows, rels, file_paths)
    assert len(structured["graph"]["edges"]) == 1
    assert structured["graph"]["edges"][0]["relation_type"] == "CALLS"


def test_meta_fields_present():
    rows = [{"entity_id": "e1", "entity_type": "FUNCTION", "name": "a", "file_id": 1, "start_line": 1, "end_line": 5}]
    file_paths = {1: "main.py"}

    _, structured = build_dual_output(rows, [], file_paths)
    meta = structured["meta"]
    assert "total_nodes" in meta
    assert "total_edges" in meta
    assert "returned_nodes" in meta
    assert "returned_edges" in meta
    assert "artifact_generation" in meta
    assert "tokens_used" in meta
    assert "token_budget" in meta
