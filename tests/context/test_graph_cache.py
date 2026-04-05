from __future__ import annotations

import json
from pathlib import Path

from batho.context.codegraph import InMemoryGraph
from batho.context.graph_cache import get_cached_graph_stats, load_cached_graph


def test_load_cached_graph_returns_none_when_graph_missing(tmp_path: Path) -> None:
    ctn_dir = tmp_path / ".ctn"
    ctn_dir.mkdir()

    graph = load_cached_graph(ctn_dir, "missing-index")
    assert graph is None


def test_load_cached_graph_deserializes_persisted_graph(tmp_path: Path) -> None:
    ctn_dir = tmp_path / ".ctn"
    idx_dir = ctn_dir / "idx1"
    idx_dir.mkdir(parents=True)

    expected = InMemoryGraph()
    (idx_dir / "graph.json").write_text(
        json.dumps(expected.to_dict(), ensure_ascii=False),
        encoding="utf-8",
    )

    loaded = load_cached_graph(ctn_dir, "idx1")
    assert loaded is not None
    assert isinstance(loaded, InMemoryGraph)
    assert loaded.to_dict() == expected.to_dict()


def test_get_cached_graph_stats_reads_current_index(tmp_path: Path) -> None:
    ctn_dir = tmp_path / ".ctn"
    idx_dir = ctn_dir / "idx-main"
    idx_dir.mkdir(parents=True)

    graph_payload = InMemoryGraph().to_dict()
    graph_path = idx_dir / "graph.json"
    graph_path.write_text(json.dumps(graph_payload), encoding="utf-8")

    (ctn_dir / "index.json").write_text(
        json.dumps({"current_index_id": "idx-main", "indexes": {}}),
        encoding="utf-8",
    )

    stats = get_cached_graph_stats(ctn_dir)
    assert stats["current_index_id"] == "idx-main"
    assert stats["graph_exists"] is True
    assert stats["graph_size_bytes"] == graph_path.stat().st_size
