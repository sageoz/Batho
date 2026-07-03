"""Tests for graph_builder.py — Arrow row → node/edge dict, markdown formatting, token budget.

Scenario:
    The graph_builder module converts IPC row dicts into dual output (markdown + JSON).
    These tests verify the conversion logic, formatting variants, token estimation,
    and budget truncation behavior.

Execution Flow:
    1. Create mock agent/rels/storage rows.
    2. Call format_concise, format_detailed, format_summary.
    3. Verify markdown structure and content.
    4. Test token estimation and truncation.

Expectations:
    - Markdown contains entity names, types, line ranges.
    - Concise format is shorter than detailed.
    - Token estimation is approximately len/4.
    - Truncation activates when budget exceeded.
"""

from __future__ import annotations

from batho.mcp.graph_builder import (
    estimate_tokens, truncate_to_budget,
    format_concise, format_detailed, format_summary,
    build_node_dict, build_edge_dict, build_meta,
    build_dual_output,
)


def test_estimate_tokens_basic():
    assert estimate_tokens("") == 0
    assert estimate_tokens("hello world") == 2  # 11 chars // 4 = 2


def test_truncate_within_budget():
    text = "short text"
    result, truncated = truncate_to_budget(text, 100)
    assert result == text
    assert truncated is False


def test_truncate_exceeds_budget():
    text = "a" * 1000
    result, truncated = truncate_to_budget(text, 10)
    assert truncated is True
    assert len(result) <= 40 + 100  # 10 tokens * 4 chars + some slack


def test_build_node_dict():
    agent_row = {
        "entity_id": "ent|func|main.py|0|10|1|5|main",
        "entity_type": "FUNCTION",
        "name": "main",
        "start_line": 1,
        "end_line": 5,
        "signature": "def main()",
        "is_exported": True,
        "fqn": "main",
    }
    node = build_node_dict(agent_row)
    assert node["id"] == "ent|func|main.py|0|10|1|5|main"
    assert node["type"] == "FUNCTION"
    assert node["name"] == "main"
    assert node["is_exported"] is True


def test_build_node_dict_with_storage():
    agent_row = {
        "entity_id": "ent|func|main.py|0|10|1|5|main",
        "entity_type": "FUNCTION",
        "name": "main",
        "start_line": 1,
        "end_line": 5,
        "signature": None,
        "is_exported": False,
        "fqn": None,
    }
    storage_row = {
        "entity_id": "ent|func|main.py|0|10|1|5|main",
        "parent_id": "ent|class|main.py|0|20|1|10|App",
        "start_byte": 0,
        "end_byte": 50,
    }
    node = build_node_dict(agent_row, storage_row)
    assert node["parent_id"] == "ent|class|main.py|0|20|1|10|App"
    assert node["start_byte"] == 0
    assert node["end_byte"] == 50


def test_build_edge_dict():
    rel_row = {
        "source_id": "ent|func|main.py|0|10|1|5|main",
        "target_id": "ent|func|utils.py|0|5|1|3|helper",
        "relation_type": "CALLS",
        "metadata_json": '{"line": 3}',
    }
    edge = build_edge_dict(rel_row)
    assert edge["source"] == "ent|func|main.py|0|10|1|5|main"
    assert edge["target"] == "ent|func|utils.py|0|5|1|3|helper"
    assert edge["relation_type"] == "CALLS"
    assert edge["metadata"] == {"line": 3}


def test_build_edge_dict_invalid_json():
    rel_row = {
        "source_id": "a",
        "target_id": "b",
        "relation_type": "CALLS",
        "metadata_json": "not json",
    }
    edge = build_edge_dict(rel_row)
    assert edge["metadata"] == {}


def test_build_meta():
    meta = build_meta(
        total_nodes=100, total_edges=50,
        returned_nodes=10, returned_edges=5,
        offset=0, limit=10, truncated=False,
        generation=3, tokens_used=500, token_budget=25000,
    )
    assert meta["total_nodes"] == 100
    assert meta["truncated"] is False
    assert meta["artifact_generation"] == 3


def test_format_concise_basic():
    agent_rows = [
        {"entity_id": "e1", "entity_type": "FUNCTION", "name": "main", "file_id": 1, "start_line": 1, "end_line": 5},
        {"entity_id": "e2", "entity_type": "CLASS", "name": "App", "file_id": 1, "start_line": 7, "end_line": 10},
    ]
    rels_rows = [
        {"source_id": "e1", "target_id": "e2", "relation_type": "CALLS"},
    ]
    file_paths = {1: "main.py"}

    result = format_concise(agent_rows, rels_rows, file_paths)
    assert "main" in result
    assert "App" in result
    assert "main.py" in result
    assert "2 entities" in result


def test_format_detailed_basic():
    agent_rows = [
        {"entity_id": "e1", "entity_type": "FUNCTION", "name": "main", "file_id": 1,
         "start_line": 1, "end_line": 5, "signature": "def main()", "is_exported": True, "fqn": "main"},
    ]
    rels_rows = []
    file_paths = {1: "main.py"}

    result = format_detailed(agent_rows, rels_rows, None, file_paths)
    assert "main" in result
    assert "FUNCTION" in result
    assert "Signature: def main()" in result
    assert "Exported: yes" in result


def test_format_summary_basic():
    stats = {
        "total_entities": 50,
        "total_relationships": 30,
        "total_files": 5,
        "relationship_breakdown": {"CALLS": 20, "IMPORTS": 10},
        "artifact_generation": 2,
    }
    result = format_summary(stats)
    assert "50 entities" in result
    assert "30 relationships" in result
    assert "5 files" in result
    assert "CALLS: 20" in result


def test_format_summary_with_communities():
    stats = {"total_entities": 100, "total_relationships": 50, "total_files": 10}
    communities = [
        {"name": "core", "entity_count": 30, "file_count": 5, "description": "Core module", "top_entities": ["main", "App"]},
    ]
    result = format_summary(stats, communities)
    assert "Community: core" in result
    assert "30 entities" in result
    assert "Core module" in result


def test_build_dual_output_concise():
    agent_rows = [
        {"entity_id": "e1", "entity_type": "FUNCTION", "name": "main", "file_id": 1, "start_line": 1, "end_line": 5},
    ]
    rels_rows = []
    file_paths = {1: "main.py"}

    markdown, structured = build_dual_output(
        agent_rows, rels_rows, file_paths,
        response_format="concise", max_tokens=25000,
    )
    assert "main" in markdown
    assert "nodes" in structured["graph"]
    assert len(structured["graph"]["nodes"]) == 1
    assert structured["meta"]["truncated"] is False


def test_build_dual_output_truncation():
    agent_rows = [
        {"entity_id": f"e{i}", "entity_type": "FUNCTION", "name": f"func_{i}", "file_id": 1, "start_line": i, "end_line": i+1}
        for i in range(100)
    ]
    file_paths = {1: "main.py"}

    markdown, structured = build_dual_output(
        agent_rows, [], file_paths,
        max_tokens=10,
    )
    assert structured["meta"]["truncated"] is True
    assert "Truncated" in markdown
