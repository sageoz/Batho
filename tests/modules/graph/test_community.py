"""Tests for threshold-aware community detection."""

from unittest.mock import MagicMock

import pytest

from batho.modules.graph.community import _sample_graph_by_files, detect_communities


class _SimpleEntity:
    def __init__(self, eid: str, file: str, name: str = ""):
        self.id = eid
        self.file = file
        self.name = name or eid


class _SimpleRel:
    def __init__(self, source_id: str, target_id: str):
        self.source_id = source_id
        self.target_id = target_id


def _make_graph(files: dict[str, list[str]], rels: list[tuple[str, str]]):
    """Build a minimal graph-like object for community tests."""
    graph = MagicMock()
    entities = {}
    for file_path, eids in files.items():
        for eid in eids:
            entities[eid] = _SimpleEntity(eid, file_path)
    graph.entities = entities
    graph.relationships = [_SimpleRel(src, tgt) for src, tgt in rels]
    graph._rels_by_endpoint = {}
    for rel in graph.relationships:
        graph._rels_by_endpoint.setdefault(rel.source_id, []).append(rel)
        graph._rels_by_endpoint.setdefault(rel.target_id, []).append(rel)
    return graph


def test_sample_graph_by_files_keeps_whole_files_under_threshold():
    """Whole-file sampling keeps files intact until the threshold is crossed."""
    files = {
        "a.py": ["a1", "a2", "a3"],
        "b.py": ["b1", "b2"],
        "c.py": ["c1"],
    }
    rels = [("a1", "b1"), ("b2", "c1")]
    graph = _make_graph(files, rels)

    kept_ids, filtered_rels = _sample_graph_by_files(graph, 5)

    # a.py (3) + b.py (2) = 5 entities exactly
    assert kept_ids == {"a1", "a2", "a3", "b1", "b2"}
    assert len(filtered_rels) == 1
    assert filtered_rels[0].source_id == "a1"
    assert filtered_rels[0].target_id == "b1"


def test_detect_communities_disabled_by_config():
    """When enabled is False, detect_communities returns an empty list."""
    graph = _make_graph({"a.py": ["a1"]}, [])
    result = detect_communities(graph, {"enabled": False})
    assert result == []


def test_detect_communities_skips_above_threshold():
    """Graphs with more entities than skip_threshold should not run Leiden."""
    files = {f"f{i}.py": [f"e{i}"] for i in range(10)}
    graph = _make_graph(files, [])
    result = detect_communities(graph, {"skip_threshold": 5, "sample_threshold": 2})
    assert result == []


def test_detect_communities_samples_between_thresholds(monkeypatch):
    """Sampling is applied when entity count is between sample and skip thresholds."""
    files = {
        "big.py": ["b1", "b2", "b3", "b4"],
        "small.py": ["s1"],
    }
    rels = [("b1", "s1")]
    graph = _make_graph(files, rels)

    called = {"sampled": False}

    def fake_sample(g, threshold):
        called["sampled"] = True
        # Return only big.py entities/rels
        kept = {"b1", "b2", "b3", "b4"}
        filtered = [r for r in g.relationships if r.source_id in kept and r.target_id in kept]
        return kept, filtered

    monkeypatch.setattr("batho.modules.graph.community._sample_graph_by_files", fake_sample)

    # Mock out igraph/leidenalg so the test does not depend on optional deps
    monkeypatch.setitem(__import__("sys").modules, "igraph", MagicMock())
    monkeypatch.setitem(__import__("sys").modules, "leidenalg", MagicMock())

    detect_communities(graph, {"skip_threshold": 10, "sample_threshold": 2})
    assert called["sampled"]
