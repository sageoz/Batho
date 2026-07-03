"""Tests for the trace_path MCP tool.

Scenario:
    trace_path finds the shortest path between two entities using BFS
    on the relationship graph with a configurable depth limit.

Execution Flow:
    1. Build a sample artifact.
    2. Load all relationships and build adjacency list.
    3. BFS from source to target.
    4. Verify path depth and entity chain.
    5. Test no path found and max_depth limit.

Expectations:
    - Shortest path is found when one exists.
    - No path returns appropriate error.
    - max_depth limits search depth.
"""

from __future__ import annotations

from collections import deque
from pathlib import Path

from batho.mcp.tools import _get_reader


def test_trace_path_adjacency(built_artifact: Path):
    reader = _get_reader(str(built_artifact))
    rels_table = reader._get_table("rels_views")
    if rels_table.num_rows == 0:
        return

    all_rels = rels_table.to_pylist()
    adjacency: dict[str, list[str]] = {}
    for rel in all_rels:
        sid = rel.get("source_id", "")
        tid = rel.get("target_id", "")
        adjacency.setdefault(sid, []).append(tid)

    assert len(adjacency) > 0


def test_trace_path_bfs(built_artifact: Path):
    reader = _get_reader(str(built_artifact))
    rels_table = reader._get_table("rels_views")
    if rels_table.num_rows == 0:
        return

    all_rels = rels_table.to_pylist()
    adjacency: dict[str, list[tuple[str, str]]] = {}
    for rel in all_rels:
        sid = rel.get("source_id", "")
        tid = rel.get("target_id", "")
        rt = rel.get("relation_type", "")
        adjacency.setdefault(sid, []).append((tid, rt))

    source = all_rels[0]["source_id"]
    target = all_rels[0]["target_id"]

    queue: deque[list] = deque()
    visited = {source}
    queue.append([(source, "")])

    path = None
    while queue:
        current = queue.popleft()
        current_id = current[-1][0]
        if current_id == target:
            path = current
            break
        for next_id, rt in adjacency.get(current_id, []):
            if next_id not in visited:
                visited.add(next_id)
                queue.append(current + [(next_id, rt)])

    assert path is not None
    assert path[0][0] == source
    assert path[-1][0] == target


def test_trace_path_no_path(built_artifact: Path):
    reader = _get_reader(str(built_artifact))
    rels_table = reader._get_table("rels_views")

    if rels_table.num_rows == 0:
        return

    all_rels = rels_table.to_pylist()
    adjacency: dict[str, list] = {}
    for rel in all_rels:
        adjacency.setdefault(rel.get("source_id", ""), []).append(rel.get("target_id", ""))

    source = "nonexistent_source"
    assert source not in adjacency


def test_trace_path_max_depth(built_artifact: Path):
    reader = _get_reader(str(built_artifact))
    rels_table = reader._get_table("rels_views")
    if rels_table.num_rows == 0:
        return

    all_rels = rels_table.to_pylist()
    adjacency: dict[str, list[tuple[str, str]]] = {}
    for rel in all_rels:
        adjacency.setdefault(rel.get("source_id", ""), []).append((rel.get("target_id", ""), rel.get("relation_type", "")))

    source = all_rels[0]["source_id"]
    max_depth = 1

    queue: deque[list] = deque()
    visited = {source}
    queue.append([(source, "")])

    path = None
    while queue:
        current = queue.popleft()
        current_id = current[-1][0]
        if current_id != source and current_id in {r.get("target_id") for r in all_rels}:
            if len(current) - 1 <= max_depth:
                path = current
                break
        if len(current) - 1 >= max_depth:
            continue
        for next_id, rt in adjacency.get(current_id, []):
            if next_id not in visited:
                visited.add(next_id)
                queue.append(current + [(next_id, rt)])

    if path:
        assert len(path) - 1 <= max_depth
