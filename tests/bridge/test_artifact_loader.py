from __future__ import annotations

import json
from pathlib import Path

import pytest

from batho.bridge.artifact_loader import (
    ArtifactLoader,
    ArtifactNotFoundError,
    ArtifactParseError,
)
from batho.context.storage import register_artifact


def test_load_json_from_registry(tmp_path: Path) -> None:
    ctn_dir = tmp_path / ".ctn"
    ctn_dir.mkdir(parents=True)
    (ctn_dir / "graph.json").write_text('{"nodes": [1]}', encoding="utf-8")
    register_artifact(ctn_dir, ctn_dir / "graph.json", "graph_json", producer="test")

    loader = ArtifactLoader(ctn_dir)
    data = loader.load_json("graph_json")
    assert data == {"nodes": [1]}


def test_load_json_from_default_pattern(tmp_path: Path) -> None:
    ctn_dir = tmp_path / ".ctn"
    ctn_dir.mkdir(parents=True)
    # No registry entry — fallback to default pattern
    idx_dir = ctn_dir / "idx_001"
    idx_dir.mkdir()
    (idx_dir / "graph.json").write_text('{"nodes": [2]}', encoding="utf-8")

    index_data = {
        "current_index_id": "idx_001",
        "indexes": {
            "idx_001": {
                "timestamp": "2026-05-13T00:00:00+00:00",
                "root": str(tmp_path),
                "file_count": 1,
                "outputs": {"graph_json": ".ctn/idx_001/graph.json"},
            }
        },
    }
    (ctn_dir / "index.json").write_text(json.dumps(index_data), encoding="utf-8")

    loader = ArtifactLoader(ctn_dir)
    data = loader.load_json("graph_json")
    assert data == {"nodes": [2]}


def test_load_json_not_found(tmp_path: Path) -> None:
    ctn_dir = tmp_path / ".ctn"
    ctn_dir.mkdir(parents=True)
    loader = ArtifactLoader(ctn_dir)

    with pytest.raises(ArtifactNotFoundError) as exc_info:
        loader.load_json("graph_json")
    assert "graph_json" in str(exc_info.value)


def test_load_json_parse_error(tmp_path: Path) -> None:
    ctn_dir = tmp_path / ".ctn"
    ctn_dir.mkdir(parents=True)
    (ctn_dir / "graph.json").write_text("not json", encoding="utf-8")
    register_artifact(ctn_dir, ctn_dir / "graph.json", "graph_json", producer="test")

    loader = ArtifactLoader(ctn_dir)
    with pytest.raises(ArtifactParseError):
        loader.load_json("graph_json")


def test_load_artifact_by_record(tmp_path: Path) -> None:
    ctn_dir = tmp_path / ".ctn"
    ctn_dir.mkdir(parents=True)
    (ctn_dir / "metrics.json").write_text('{"elapsed": 2.0}', encoding="utf-8")
    register_artifact(ctn_dir, ctn_dir / "metrics.json", "metrics_json", producer="test")

    from batho.bridge.registry_client import ArtifactRegistryBridge

    bridge = ArtifactRegistryBridge(ctn_dir)
    record = bridge.get_artifact_by_logical_path("metrics.json")
    assert record is not None

    loader = ArtifactLoader(ctn_dir)
    content = loader.load_artifact(record)
    assert content.data == {"elapsed": 2.0}
    assert content.checksum_verified is True


def test_load_json_verify_checksum_disabled(tmp_path: Path) -> None:
    ctn_dir = tmp_path / ".ctn"
    ctn_dir.mkdir(parents=True)
    (ctn_dir / "graph.json").write_text('{"nodes": [1]}', encoding="utf-8")
    register_artifact(ctn_dir, ctn_dir / "graph.json", "graph_json", producer="test")

    loader = ArtifactLoader(ctn_dir)
    data = loader.load_json("graph_json", verify_checksum=False)
    assert data == {"nodes": [1]}
