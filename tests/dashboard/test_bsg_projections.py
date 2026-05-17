"""Tests for `batho/dashboard/assets/js/bsg-projections.js`.

The module is plain ES-module JavaScript consumed by the dashboard SPA.
Rather than reimplement the projections in Python, we drive the real
module via Node and assert on the structured JSON it returns. The harness
script lives in ``_run_projections.mjs``.

The tests are skipped when ``node`` is not on ``PATH`` (matching the
existing performance test pattern).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

HARNESS = Path(__file__).parent / "_run_projections.mjs"


def _node_available() -> bool:
    return shutil.which("node") is not None


pytestmark = pytest.mark.skipif(
    not _node_available(), reason="node interpreter not available"
)


def _run(fixture: dict, tmp_path: Path) -> list[dict]:
    payload = tmp_path / "fixture.json"
    payload.write_text(json.dumps(fixture), encoding="utf-8")
    result = subprocess.run(
        ["node", str(HARNESS), str(payload)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"node harness failed: stderr={result.stderr!r} stdout={result.stdout!r}"
    )
    return json.loads(result.stdout)


def _basic_bsg() -> dict:
    """Three files with mixed edges. Mirrors the camelized shape produced by
    `ctn-loader.normalize` plus a snake_case `indexes` block so we exercise
    the snake/camel fallback paths in the projections module.
    """
    nodes = [
        {"id": "a1", "type": "FUNCTION", "name": "login", "file": "src/auth/login.py", "language": "python", "serviceTag": "auth", "category": "SOURCE"},
        {"id": "a2", "type": "CLASS", "name": "AuthToken", "file": "src/auth/login.py", "language": "python", "serviceTag": "auth", "category": "SOURCE"},
        {"id": "b1", "type": "FUNCTION", "name": "hash", "file": "src/auth/crypto.py", "language": "python", "serviceTag": "auth", "category": "SOURCE"},
        {"id": "b2", "type": "FUNCTION", "name": "verify", "file": "src/auth/crypto.py", "language": "python", "serviceTag": "auth", "category": "SOURCE"},
        {"id": "c1", "type": "FUNCTION", "name": "render", "file": "src/web/views.py", "language": "python", "serviceTag": "web", "category": "SOURCE"},
    ]
    edges = [
        {"id": "e1", "source_id": "a1", "target_id": "b1", "type": "CALLS"},
        {"id": "e2", "source_id": "a1", "target_id": "b2", "type": "CALLS"},
        {"id": "e3", "source_id": "a2", "target_id": "b1", "type": "USES"},
        {"id": "e4", "source_id": "c1", "target_id": "a1", "type": "CALLS"},
        # Intra-file edge in src/auth/login.py
        {"id": "e5", "source_id": "a2", "target_id": "a1", "type": "DEFINES"},
        # Intra-file in src/auth/crypto.py
        {"id": "e6", "source_id": "b2", "target_id": "b1", "type": "CALLS"},
    ]
    indexes = {
        "nodes_by_file": {
            "src/auth/login.py": ["a1", "a2"],
            "src/auth/crypto.py": ["b1", "b2"],
            "src/web/views.py": ["c1"],
        },
        "inbound_edges": {
            "a1": ["e4", "e5"],
            "b1": ["e1", "e3", "e6"],
            "b2": ["e2"],
        },
        "outbound_edges": {
            "a1": ["e1", "e2"],
            "a2": ["e3", "e5"],
            "b2": ["e6"],
            "c1": ["e4"],
        },
    }
    return {"nodes": nodes, "edges": edges, "indexes": indexes}


def test_build_file_graph_aggregates_edges(tmp_path: Path) -> None:
    bsg = _basic_bsg()
    _out = _run(
        {"bsg": bsg, "calls": [{"fn": "buildFileGraph"}]}, tmp_path
    )
    result = _out[0]["result"]

    assert sorted(n["id"] for n in result["nodes"]) == [
        "src/auth/crypto.py",
        "src/auth/login.py",
        "src/web/views.py",
    ]

    login_node = next(n for n in result["nodes"] if n["id"] == "src/auth/login.py")
    assert login_node["nodeCount"] == 2
    assert login_node["language"] == "python"
    assert login_node["serviceTag"] == "auth"
    assert login_node["types"] == {"FUNCTION": 1, "CLASS": 1}

    # Inter-file edges only: login→crypto (3 underlying), web→login (1).
    edge_map = {(e["source"], e["target"]): e for e in result["edges"]}
    assert (login_node["id"], "src/auth/crypto.py") in edge_map
    assert (login_node["id"], "src/auth/crypto.py") in edge_map
    login_to_crypto = edge_map[(login_node["id"], "src/auth/crypto.py")]
    assert login_to_crypto["weight"] == 3
    assert login_to_crypto["types"] == {"CALLS": 2, "USES": 1}

    web_to_login = edge_map[("src/web/views.py", login_node["id"])]
    assert web_to_login["weight"] == 1
    assert web_to_login["types"] == {"CALLS": 1}

    # Intra-file edges (e5, e6) must NOT appear in L1.
    assert all(e["source"] != e["target"] for e in result["edges"])


def test_build_file_subgraph_only_intra_file_edges(tmp_path: Path) -> None:
    bsg = _basic_bsg()
    _out = _run(
        {
            "bsg": bsg,
            "calls": [
                {"fn": "buildFileSubgraph", "file": "src/auth/login.py"},
            ],
        },
        tmp_path,
    )
    result = _out[0]["result"]

    assert sorted(n["id"] for n in result["nodes"]) == ["a1", "a2"]
    assert [e["id"] for e in result["edges"]] == ["e5"]
    assert result["file"] == "src/auth/login.py"


def test_build_neighborhood_uses_edge_indexes(tmp_path: Path) -> None:
    bsg = _basic_bsg()
    _out = _run(
        {
            "bsg": bsg,
            "calls": [{"fn": "buildNeighborhood", "nodeId": "a1"}],
        },
        tmp_path,
    )
    result = _out[0]["result"]

    assert result["center"] == "a1"
    # a1 connects to b1 (e1), b2 (e2), itself via e5 from a2, and from c1 via e4.
    assert sorted(n["id"] for n in result["nodes"]) == ["a1", "a2", "b1", "b2", "c1"]
    assert sorted(e["id"] for e in result["edges"]) == ["e1", "e2", "e4", "e5"]


def test_build_neighborhood_falls_back_when_indexes_missing(tmp_path: Path) -> None:
    bsg = _basic_bsg()
    bsg.pop("indexes")
    _out = _run(
        {
            "bsg": bsg,
            "calls": [{"fn": "buildNeighborhood", "nodeId": "b1"}],
        },
        tmp_path,
    )
    result = _out[0]["result"]

    # b1 is target of e1 (a1), e3 (a2), e6 (b2). No outbound edges.
    assert result["center"] == "b1"
    assert sorted(n["id"] for n in result["nodes"]) == ["a1", "a2", "b1", "b2"]
    assert sorted(e["id"] for e in result["edges"]) == ["e1", "e3", "e6"]


def test_build_file_subgraph_falls_back_when_index_missing(tmp_path: Path) -> None:
    bsg = _basic_bsg()
    bsg.pop("indexes")
    _out = _run(
        {
            "bsg": bsg,
            "calls": [{"fn": "buildFileSubgraph", "file": "src/auth/crypto.py"}],
        },
        tmp_path,
    )
    result = _out[0]["result"]

    assert sorted(n["id"] for n in result["nodes"]) == ["b1", "b2"]
    assert [e["id"] for e in result["edges"]] == ["e6"]


def test_unknown_node_returns_empty(tmp_path: Path) -> None:
    bsg = _basic_bsg()
    _out = _run(
        {
            "bsg": bsg,
            "calls": [{"fn": "buildNeighborhood", "nodeId": "does-not-exist"}],
        },
        tmp_path,
    )
    result = _out[0]["result"]
    assert result == {"nodes": [], "edges": [], "center": "does-not-exist"}
