from __future__ import annotations

import json
from pathlib import Path

import pytest

from batho.bridge.registry_client import ArtifactRegistryBridge
from batho.context.storage import register_artifact


def _make_registry(ctn_dir: Path) -> None:
    ctn_dir.mkdir(parents=True, exist_ok=True)
    (ctn_dir / "local" / "sync").mkdir(parents=True, exist_ok=True)


def test_list_artifact_types_empty(tmp_path: Path) -> None:
    ctn_dir = tmp_path / ".ctn"
    _make_registry(ctn_dir)
    bridge = ArtifactRegistryBridge(ctn_dir)
    assert bridge.list_artifact_types() == []


def test_list_artifact_types_with_entries(tmp_path: Path) -> None:
    ctn_dir = tmp_path / ".ctn"
    _make_registry(ctn_dir)
    (ctn_dir / "graph.json").write_text('{"nodes": []}', encoding="utf-8")
    (ctn_dir / "bsg.json").write_text('{"entities": []}', encoding="utf-8")

    register_artifact(ctn_dir, ctn_dir / "graph.json", "graph_json", producer="test")
    register_artifact(ctn_dir, ctn_dir / "bsg.json", "bsg_json", producer="test")

    bridge = ArtifactRegistryBridge(ctn_dir)
    types = bridge.list_artifact_types()
    assert "graph_json" in types
    assert "bsg_json" in types


def test_get_artifacts_by_type(tmp_path: Path) -> None:
    ctn_dir = tmp_path / ".ctn"
    _make_registry(ctn_dir)
    (ctn_dir / "graph.json").write_text('{"nodes": []}', encoding="utf-8")
    register_artifact(ctn_dir, ctn_dir / "graph.json", "graph_json", producer="test")

    bridge = ArtifactRegistryBridge(ctn_dir)
    records = bridge.get_artifacts_by_type("graph_json")
    assert len(records) == 1
    assert records[0].artifact_type == "graph_json"
    assert records[0].logical_path == "graph.json"


def test_get_artifact_by_logical_path(tmp_path: Path) -> None:
    ctn_dir = tmp_path / ".ctn"
    _make_registry(ctn_dir)
    (ctn_dir / "metrics.json").write_text('{"elapsed": 1.0}', encoding="utf-8")
    register_artifact(ctn_dir, ctn_dir / "metrics.json", "metrics_json", producer="test")

    bridge = ArtifactRegistryBridge(ctn_dir)
    record = bridge.get_artifact_by_logical_path("metrics.json")
    assert record is not None
    assert record.artifact_type == "metrics_json"

    missing = bridge.get_artifact_by_logical_path("nonexistent.json")
    assert missing is None


def test_get_latest_index(tmp_path: Path) -> None:
    ctn_dir = tmp_path / ".ctn"
    _make_registry(ctn_dir)
    index_data = {
        "current_index_id": "idx_123",
        "indexes": {
            "idx_123": {
                "timestamp": "2026-05-13T00:00:00+00:00",
                "root": str(tmp_path),
                "file_count": 10,
                "entity_count": 50,
                "relationship_count": 30,
                "repo_hash": "abc",
                "outputs": {"graph_json": ".ctn/idx_123/graph.json"},
            }
        },
    }
    (ctn_dir / "index.json").write_text(json.dumps(index_data), encoding="utf-8")

    bridge = ArtifactRegistryBridge(ctn_dir)
    latest = bridge.get_latest_index()
    assert latest is not None
    assert latest.index_id == "idx_123"
    assert latest.file_count == 10


def test_list_indexes(tmp_path: Path) -> None:
    ctn_dir = tmp_path / ".ctn"
    _make_registry(ctn_dir)
    index_data = {
        "current_index_id": "idx_a",
        "indexes": {
            "idx_a": {"timestamp": "2026-05-13T00:00:00+00:00", "root": str(tmp_path), "file_count": 1},
            "idx_b": {"timestamp": "2026-05-12T00:00:00+00:00", "root": str(tmp_path), "file_count": 2},
        },
    }
    (ctn_dir / "index.json").write_text(json.dumps(index_data), encoding="utf-8")

    bridge = ArtifactRegistryBridge(ctn_dir)
    entries, current_index_id, persistence_model, schema_version = bridge.list_indexes()
    assert len(entries) == 2
    ids = {e.index_id for e in entries}
    assert ids == {"idx_a", "idx_b"}
    assert current_index_id == "idx_a"
    assert persistence_model is None
    assert schema_version is None


def test_search_artifacts(tmp_path: Path) -> None:
    ctn_dir = tmp_path / ".ctn"
    _make_registry(ctn_dir)
    (ctn_dir / "graph.json").write_text('{}', encoding="utf-8")
    (ctn_dir / "bsg.json").write_text('{}', encoding="utf-8")
    register_artifact(ctn_dir, ctn_dir / "graph.json", "graph_json", producer="test")
    register_artifact(ctn_dir, ctn_dir / "bsg.json", "bsg_json", producer="test")

    bridge = ArtifactRegistryBridge(ctn_dir)
    results = bridge.search_artifacts("graph")
    assert len(results) == 1
    assert results[0].artifact_type == "graph_json"

    # Filter by type
    results = bridge.search_artifacts(".json", artifact_type="bsg_json")
    assert len(results) == 1
    assert results[0].artifact_type == "bsg_json"


def test_stats(tmp_path: Path) -> None:
    ctn_dir = tmp_path / ".ctn"
    _make_registry(ctn_dir)
    (ctn_dir / "graph.json").write_text('{}', encoding="utf-8")
    register_artifact(ctn_dir, ctn_dir / "graph.json", "graph_json", producer="test")

    bridge = ArtifactRegistryBridge(ctn_dir)
    stats = bridge.stats()
    assert stats.enabled is True
    assert stats.artifact_count >= 1
    assert "graph_json" in stats.artifact_types
