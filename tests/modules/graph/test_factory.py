"""Tests for the graph backend factory and auto-resolution heuristics."""

from __future__ import annotations

from pathlib import Path

import pytest

from batho.modules.graph.builder.arrow_graph import ArrowGraph
from batho.modules.graph.builder.codegraph import InMemoryGraph
from batho.modules.graph.builder.factory import (
    AVG_ENTITIES_PER_FILE,
    create_graph,
    resolve_graph_backend,
)


class TestCreateGraph:
    def test_create_graph_in_memory(self):
        graph = create_graph("in-memory")
        assert isinstance(graph, InMemoryGraph)

    def test_create_graph_arrow(self, tmp_path: Path):
        graph = create_graph("arrow", staging_dir=tmp_path / "staging")
        assert isinstance(graph, ArrowGraph)
        graph.close()

    def test_create_graph_arrow_requires_staging_dir(self):
        with pytest.raises(ValueError, match="staging_dir"):
            create_graph("arrow")

    def test_create_graph_arrow_config_overrides(self, tmp_path: Path):
        graph = create_graph(
            "arrow",
            staging_dir=tmp_path / "staging",
            arrow_config={"arrow_flush_rows": 123, "arrow_flush_bytes_mb": 2.5},
        )
        assert isinstance(graph, ArrowGraph)
        assert graph._flush_rows == 123
        assert graph._flush_bytes == int(2.5 * 1024 * 1024)
        graph.close()

    def test_create_graph_invalid_backend(self):
        with pytest.raises(ValueError, match="Unknown graph backend"):
            create_graph("sqlite")

    def test_create_graph_auto_must_be_resolved_first(self):
        with pytest.raises(ValueError, match="Unknown graph backend"):
            create_graph("auto")


class TestResolveGraphBackend:
    def test_auto_small_repo_uses_in_memory(self):
        resolved = resolve_graph_backend(
            "auto",
            candidate_count=100,
            estimated_entities=100 * AVG_ENTITIES_PER_FILE,
            auto_threshold_files=500,
            auto_threshold_entities=30_000,
        )
        assert resolved == "in-memory"

    def test_auto_large_file_count_uses_arrow(self):
        resolved = resolve_graph_backend(
            "auto",
            candidate_count=600,
            estimated_entities=10,
            auto_threshold_files=500,
            auto_threshold_entities=30_000,
        )
        assert resolved == "arrow"

    def test_auto_large_entity_estimate_uses_arrow(self):
        resolved = resolve_graph_backend(
            "auto",
            candidate_count=10,
            estimated_entities=50_000,
            auto_threshold_files=500,
            auto_threshold_entities=30_000,
        )
        assert resolved == "arrow"

    def test_auto_respects_custom_thresholds(self):
        resolved = resolve_graph_backend(
            "auto",
            candidate_count=50,
            estimated_entities=100,
            auto_threshold_files=10,
            auto_threshold_entities=30_000,
        )
        assert resolved == "arrow"

    def test_explicit_in_memory_passthrough(self):
        assert resolve_graph_backend("in-memory", 100_000, 10**9, 1, 1) == "in-memory"

    def test_explicit_arrow_passthrough(self):
        assert resolve_graph_backend("arrow", 1, 1, 500, 30_000) == "arrow"
