"""Tests for token budget enforcement in graph_builder.

Scenario:
    Token budget truncation must activate when content exceeds the specified
    token limit, and the truncation metadata must be correctly reported.

Execution Flow:
    1. Generate content that exceeds a small token budget.
    2. Call build_dual_output with the small budget.
    3. Verify truncated flag is set and pagination hint appears.

Expectations:
    - truncated=True when content exceeds budget.
    - Pagination hint with next offset appears in truncated content.
    - meta.tokens_used does not exceed token_budget.
"""

from __future__ import annotations

from batho.mcp.graph_builder import build_dual_output, estimate_tokens, truncate_to_budget


def test_budget_not_exceeded():
    text = "short"
    result, truncated = truncate_to_budget(text, 100)
    assert not truncated
    assert result == text


def test_budget_exceeded_truncation():
    text = "x" * 1000
    result, truncated = truncate_to_budget(text, 5)
    assert truncated
    assert estimate_tokens(result) <= 5 + 5  # some slack for truncation hint


def test_dual_output_pagination_hint():
    rows = [
        {"entity_id": f"e{i}", "entity_type": "FUNCTION", "name": f"f{i}", "file_id": 1, "start_line": i, "end_line": i+1}
        for i in range(200)
    ]
    file_paths = {1: "main.py"}

    markdown, structured = build_dual_output(
        rows, [], file_paths,
        max_tokens=5, offset=0, limit=50,
    )
    assert structured["meta"]["truncated"] is True
    assert "offset=50" in markdown


def test_dual_output_no_truncation_large_budget():
    rows = [
        {"entity_id": "e1", "entity_type": "FUNCTION", "name": "main", "file_id": 1, "start_line": 1, "end_line": 5},
    ]
    file_paths = {1: "main.py"}

    _, structured = build_dual_output(
        rows, [], file_paths,
        max_tokens=25000,
    )
    assert structured["meta"]["truncated"] is False
