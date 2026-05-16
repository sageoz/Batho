from __future__ import annotations

import json
import urllib.parse
import urllib.request
from pathlib import Path

import pytest

from batho.bridge.http_api import BridgeAPIHandler, create_bridge_server
from batho.context.storage import register_artifact


def _make_ctn(tmp_path: Path) -> Path:
    ctn_dir = tmp_path / ".ctn"
    ctn_dir.mkdir(parents=True)
    (ctn_dir / "graph.json").write_text('{"nodes": [1]}', encoding="utf-8")
    register_artifact(ctn_dir, ctn_dir / "graph.json", "graph_json", producer="test")
    return ctn_dir


def test_handler_root_endpoint(tmp_path: Path) -> None:
    ctn_dir = _make_ctn(tmp_path)
    handler = BridgeAPIHandler(ctn_dir)
    body, status, headers = handler.dispatch("/api/v1/bridge/", {})
    assert status == 200
    data = json.loads(body)
    assert data["ok"] is True
    assert "endpoints" in data["data"]


def test_handler_indexes(tmp_path: Path) -> None:
    ctn_dir = _make_ctn(tmp_path)
    index_data = {
        "current_index_id": "idx_001",
        "indexes": {
            "idx_001": {
                "timestamp": "2026-05-13T00:00:00+00:00",
                "root": str(tmp_path),
                "file_count": 1,
            }
        },
    }
    (ctn_dir / "index.json").write_text(json.dumps(index_data), encoding="utf-8")

    handler = BridgeAPIHandler(ctn_dir)
    body, status, _ = handler.dispatch("/api/v1/bridge/indexes", {})
    assert status == 200
    data = json.loads(body)
    assert data["ok"] is True
    assert len(data["data"]) == 1


def test_handler_artifacts_list(tmp_path: Path) -> None:
    ctn_dir = _make_ctn(tmp_path)
    handler = BridgeAPIHandler(ctn_dir)
    body, status, _ = handler.dispatch("/api/v1/bridge/artifacts", {"type": ["graph_json"]})
    assert status == 200
    data = json.loads(body)
    assert data["ok"] is True
    assert len(data["data"]) == 1
    assert data["meta"]["artifact_type"] == "graph_json"


def test_handler_artifacts_unknown_type(tmp_path: Path) -> None:
    ctn_dir = _make_ctn(tmp_path)
    handler = BridgeAPIHandler(ctn_dir)
    body, status, _ = handler.dispatch("/api/v1/bridge/artifacts", {"type": ["unknown_type"]})
    assert status == 400
    data = json.loads(body)
    assert data["ok"] is False


def test_handler_artifact_content(tmp_path: Path) -> None:
    ctn_dir = _make_ctn(tmp_path)
    handler = BridgeAPIHandler(ctn_dir)
    body, status, _ = handler.dispatch(
        "/api/v1/bridge/artifacts/graph_json", {}
    )
    assert status == 200
    data = json.loads(body)
    assert data["ok"] is True
    assert data["data"] == {"nodes": [1]}


def test_handler_artifact_content_by_path(tmp_path: Path) -> None:
    ctn_dir = _make_ctn(tmp_path)
    handler = BridgeAPIHandler(ctn_dir)
    body, status, _ = handler.dispatch(
        "/api/v1/bridge/artifacts/graph_json/content", {"path": ["graph.json"]}
    )
    assert status == 200
    data = json.loads(body)
    assert data["ok"] is True
    assert data["data"] == {"nodes": [1]}


def test_handler_stats(tmp_path: Path) -> None:
    ctn_dir = _make_ctn(tmp_path)
    handler = BridgeAPIHandler(ctn_dir)
    body, status, _ = handler.dispatch("/api/v1/bridge/stats", {})
    assert status == 200
    data = json.loads(body)
    assert data["ok"] is True
    assert data["data"]["enabled"] is True


def test_handler_unknown_endpoint(tmp_path: Path) -> None:
    ctn_dir = _make_ctn(tmp_path)
    handler = BridgeAPIHandler(ctn_dir)
    body, status, _ = handler.dispatch("/api/v1/bridge/unknown", {})
    assert status == 404


def test_handler_patches_list(tmp_path: Path) -> None:
    ctn_dir = _make_ctn(tmp_path)
    patches_dir = ctn_dir / "patches"
    patches_dir.mkdir(parents=True)
    patches_index = {
        "schema_version": "1.0",
        "patches": [
            {
                "operation_id": "op_001",
                "timestamp": "2026-05-15T10:37:17.548341+00:00",
                "base_snapshot_id": "snap_base",
                "new_snapshot_id": "snap_new",
                "operation_type": "incremental_patch",
                "metrics": {
                    "token_size": 532,
                    "affected_files": 1,
                    "elapsed_seconds": 0.5985,
                    "added_files": 0,
                    "modified_files": 1,
                    "deleted_files": 0,
                },
            }
        ],
        "total_patches": 1,
        "last_updated": "2026-05-15T10:37:17.549292+00:00",
    }
    (patches_dir / "index.json").write_text(json.dumps(patches_index), encoding="utf-8")

    handler = BridgeAPIHandler(ctn_dir)
    body, status, _ = handler.dispatch("/api/v1/bridge/patches", {})
    assert status == 200
    data = json.loads(body)
    assert data["ok"] is True
    assert data["data"]["total_patches"] == 1
    assert len(data["data"]["patches"]) == 1
    assert data["data"]["patches"][0]["operation_id"] == "op_001"


def test_handler_patches_list_missing(tmp_path: Path) -> None:
    ctn_dir = _make_ctn(tmp_path)
    handler = BridgeAPIHandler(ctn_dir)
    body, status, _ = handler.dispatch("/api/v1/bridge/patches", {})
    assert status == 404
    data = json.loads(body)
    assert data["ok"] is False


def test_handler_patch_detail(tmp_path: Path) -> None:
    ctn_dir = _make_ctn(tmp_path)
    patches_dir = ctn_dir / "patches"
    patches_dir.mkdir(parents=True)

    op_id = "batho_a769490f06d0450481e99b78a9a4b752_20260515T103717548292Z"
    patch_detail = {
        "operation_id": op_id,
        "base_snapshot_id": "snap_base",
        "new_snapshot_id": "snap_new",
        "changes_applied": [
            {
                "path": "DESIGN.md",
                "change_type": "modified",
                "old_hash": "abc123",
                "new_hash": "def456",
                "file_size": 6684,
                "mtime": "2026-05-15T10:37:01.036299+00:00",
                "permissions": 33188,
                "is_symlink": False,
                "symlink_target": None,
            }
        ],
        "timestamp": "2026-05-15T10:37:17.548341+00:00",
        "operation_type": "incremental_patch",
        "metrics": {
            "token_size": 532,
            "affected_files": 1,
            "elapsed_seconds": 0.5985,
            "added_files": 0,
            "modified_files": 1,
            "deleted_files": 0,
        },
    }
    (patches_dir / f"patch_{op_id}.json").write_text(
        json.dumps(patch_detail), encoding="utf-8"
    )

    handler = BridgeAPIHandler(ctn_dir)
    body, status, _ = handler.dispatch(f"/api/v1/bridge/patches/{op_id}", {})
    assert status == 200
    data = json.loads(body)
    assert data["ok"] is True
    assert data["data"]["operation_id"] == op_id
    assert len(data["data"]["changes_applied"]) == 1
    assert data["data"]["changes_applied"][0]["path"] == "DESIGN.md"


def test_handler_patch_detail_not_found(tmp_path: Path) -> None:
    ctn_dir = _make_ctn(tmp_path)
    handler = BridgeAPIHandler(ctn_dir)
    body, status, _ = handler.dispatch("/api/v1/bridge/patches/nonexistent", {})
    assert status == 404
    data = json.loads(body)
    assert data["ok"] is False


def test_handler_snapshot_diff(tmp_path: Path) -> None:
    ctn_dir = _make_ctn(tmp_path)
    snapshots_dir = ctn_dir / "snapshots"
    snapshots_dir.mkdir(parents=True)

    base_id = "snap_base_001"
    new_id = "snap_new_001"

    base_snapshot = {
        "entities": [
            {"id": "ent_a", "hash": "hash_a1"},
            {"id": "ent_b", "hash": "hash_b1"},
            {"id": "ent_c", "hash": "hash_c1"},
        ],
        "files": [{"path": "a.py"}, {"path": "b.py"}, {"path": "c.py"}],
        "stats": {"loc_total": 100},
    }
    new_snapshot = {
        "entities": [
            {"id": "ent_a", "hash": "hash_a1"},
            {"id": "ent_b", "hash": "hash_b2"},
            {"id": "ent_d", "hash": "hash_d1"},
        ],
        "files": [{"path": "a.py"}, {"path": "b.py"}, {"path": "d.py"}],
        "stats": {"loc_total": 120},
    }

    (snapshots_dir / f"{base_id}.json").write_text(
        json.dumps(base_snapshot), encoding="utf-8"
    )
    (snapshots_dir / f"{new_id}.json").write_text(
        json.dumps(new_snapshot), encoding="utf-8"
    )

    handler = BridgeAPIHandler(ctn_dir)
    body, status, _ = handler.dispatch(
        "/api/v1/bridge/snapshots/diff",
        {"base": [base_id], "new": [new_id]},
    )
    assert status == 200
    data = json.loads(body)
    assert data["ok"] is True
    diff = data["data"]

    assert diff["entities"]["added"] == 1  # ent_d
    assert diff["entities"]["removed"] == 1  # ent_c
    assert diff["entities"]["modified"] == 1  # ent_b
    assert diff["entities"]["unchanged"] == 1  # ent_a
    assert "ent_d" in diff["entities"]["added_ids"]
    assert "ent_c" in diff["entities"]["removed_ids"]
    assert "ent_b" in diff["entities"]["modified_ids"]

    assert diff["files"]["base_count"] == 3
    assert diff["files"]["new_count"] == 3
    assert diff["files"]["delta"] == 0

    assert diff["loc"]["base"] == 100
    assert diff["loc"]["new"] == 120
    assert diff["loc"]["delta"] == 20


def test_handler_snapshot_diff_missing_params(tmp_path: Path) -> None:
    ctn_dir = _make_ctn(tmp_path)
    handler = BridgeAPIHandler(ctn_dir)
    body, status, _ = handler.dispatch("/api/v1/bridge/snapshots/diff", {})
    assert status == 400
    data = json.loads(body)
    assert data["ok"] is False


def test_handler_snapshot_diff_missing_snapshot(tmp_path: Path) -> None:
    ctn_dir = _make_ctn(tmp_path)
    handler = BridgeAPIHandler(ctn_dir)
    body, status, _ = handler.dispatch(
        "/api/v1/bridge/snapshots/diff",
        {"base": ["nonexistent"], "new": ["also_missing"]},
    )
    assert status == 404
    data = json.loads(body)
    assert data["ok"] is False


def test_handler_root_endpoint_includes_new_endpoints(tmp_path: Path) -> None:
    ctn_dir = _make_ctn(tmp_path)
    handler = BridgeAPIHandler(ctn_dir)
    body, status, headers = handler.dispatch("/api/v1/bridge/", {})
    assert status == 200
    data = json.loads(body)
    endpoints = data["data"]["endpoints"]
    assert "GET /patches" in endpoints
    assert "GET /patches/{operation_id}" in endpoints
    assert "GET /snapshots/diff?base=&new=" in endpoints


def test_standalone_server_lifecycle(tmp_path: Path) -> None:
    ctn_dir = _make_ctn(tmp_path)
    server = create_bridge_server(ctn_dir, host="127.0.0.1", port=0)
    port = server.server_address[1]
    server.timeout = 2

    import threading
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        url = f"http://127.0.0.1:{port}/api/v1/bridge/stats"
        with urllib.request.urlopen(url, timeout=3) as resp:
            assert resp.status == 200
            data = json.loads(resp.read())
            assert data["ok"] is True
    finally:
        server.shutdown()
