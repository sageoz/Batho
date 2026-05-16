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
