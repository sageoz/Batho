from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from batho.bridge.mcp_server import create_mcp_server
from batho.context.storage import register_artifact


def _make_ctn(tmp_path: Path) -> Path:
    ctn_dir = tmp_path / ".ctn"
    ctn_dir.mkdir(parents=True)
    (ctn_dir / "graph.json").write_text('{"nodes": [1]}', encoding="utf-8")
    register_artifact(ctn_dir, ctn_dir / "graph.json", "graph_json", producer="test")
    return ctn_dir


def _call_tool_sync(mcp, tool_name: str, args: dict):
    """Helper to call an async MCP tool synchronously.

    FastMCP.call_tool returns a tuple (content_list, meta_dict).
    We return the content_list directly.
    """
    result = asyncio.run(mcp.call_tool(tool_name, args))
    if isinstance(result, tuple):
        return result[0]
    return result


def test_create_mcp_server(tmp_path: Path) -> None:
    ctn_dir = _make_ctn(tmp_path)
    mcp = create_mcp_server(ctn_dir)
    assert mcp is not None


def test_mcp_list_indexes(tmp_path: Path) -> None:
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

    mcp = create_mcp_server(ctn_dir)
    result = _call_tool_sync(mcp, "bridge_list_indexes", {})
    parsed = json.loads(result[0].text)
    assert len(parsed) == 1
    assert parsed[0]["index_id"] == "idx_001"


def test_mcp_get_artifact(tmp_path: Path) -> None:
    ctn_dir = _make_ctn(tmp_path)
    mcp = create_mcp_server(ctn_dir)
    result = _call_tool_sync(mcp, "bridge_get_artifact", {"artifact_type": "graph_json"})
    parsed = json.loads(result[0].text)
    assert parsed["ok"] is True
    assert parsed["data"] == {"nodes": [1]}


def test_mcp_get_artifact_unknown_type(tmp_path: Path) -> None:
    ctn_dir = _make_ctn(tmp_path)
    mcp = create_mcp_server(ctn_dir)
    result = _call_tool_sync(mcp, "bridge_get_artifact", {"artifact_type": "unknown_xyz"})
    parsed = json.loads(result[0].text)
    assert "error" in parsed


def test_mcp_search_artifacts(tmp_path: Path) -> None:
    ctn_dir = _make_ctn(tmp_path)
    mcp = create_mcp_server(ctn_dir)
    result = _call_tool_sync(mcp, "bridge_search_artifacts", {"query": "graph"})
    parsed = json.loads(result[0].text)
    assert len(parsed) == 1
    assert parsed[0]["artifact_type"] == "graph_json"


def test_mcp_get_stats(tmp_path: Path) -> None:
    ctn_dir = _make_ctn(tmp_path)
    mcp = create_mcp_server(ctn_dir)
    result = _call_tool_sync(mcp, "bridge_get_stats", {})
    parsed = json.loads(result[0].text)
    assert parsed["enabled"] is True
    assert parsed["artifact_count"] >= 1
