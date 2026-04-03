"""Tests for batho_core.context.repomap module."""
from __future__ import annotations

from pathlib import Path

import pytest

from batho_core.context.codegraph import InMemoryGraph
from batho_core.context.repomap import RepoMap, _text_tokens
from batho_core.context.schema import Entity, EntityType, Relationship, RelationshipType


# ---------------------------------------------------------------------------
# _text_tokens
# ---------------------------------------------------------------------------

class TestTextTokens:

    def test_non_empty(self):
        assert _text_tokens("hello world") >= 1

    def test_empty_string(self):
        assert _text_tokens("") == 1  # max(1, ...)

    def test_longer_text_more_tokens(self):
        assert _text_tokens("a" * 100) > _text_tokens("a" * 10)


# ---------------------------------------------------------------------------
# RepoMap.build
# ---------------------------------------------------------------------------

class TestRepoMapBuild:

    def test_build_from_graph(self, mock_graph):
        repomap = RepoMap.build(mock_graph, root="/fake/root")
        assert repomap.file_count > 0
        assert repomap.entity_count > 0

    def test_file_paths_relative(self, mock_graph):
        repomap = RepoMap.build(mock_graph, root="/fake/root")
        # Files in mock_graph are already relative, so they should stay as-is
        for filepath in repomap._by_file:
            assert not filepath.startswith("/")


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

class TestRenderFull:

    def test_contains_file_paths(self, mock_graph):
        repomap = RepoMap.build(mock_graph, root="/fake/root")
        output = repomap.render_full()
        assert "calculator.py" in output

    def test_contains_entity_names(self, mock_graph):
        repomap = RepoMap.build(mock_graph, root="/fake/root")
        output = repomap.render_full()
        assert "add" in output


class TestRenderCompressed:

    def test_respects_budget(self, mock_graph):
        repomap = RepoMap.build(mock_graph, root="/fake/root")
        text, stats = repomap.render_compressed(budget=10000, fail_on_overflow=False)
        assert stats["tokens_used"] <= 10000

    def test_overflow_raises(self, mock_graph):
        repomap = RepoMap.build(mock_graph, root="/fake/root")
        with pytest.raises(ValueError, match="Token budget exceeded"):
            repomap.render_compressed(budget=1, fail_on_overflow=True)

    def test_stats_keys(self, mock_graph):
        repomap = RepoMap.build(mock_graph, root="/fake/root")
        _, stats = repomap.render_compressed(budget=10000, fail_on_overflow=False)
        assert "tokens_used" in stats
        assert "budget" in stats
        assert "truncated_files" in stats


class TestRenderJson:

    def test_structure(self, mock_graph):
        repomap = RepoMap.build(mock_graph, root="/fake/root")
        data = repomap.render_json()
        assert "schema_version" in data
        assert data["schema_version"] == "bsg.v1"
        assert "nodes" in data
        assert "edges" in data
        assert "indexes" in data
        assert "stats" in data

    def test_files_have_entries(self, mock_graph):
        repomap = RepoMap.build(mock_graph, root="/fake/root")
        data = repomap.render_json()
        assert data["stats"]["total_files"] > 0
        for node_ids in data["indexes"]["nodes_by_file"].values():
            assert isinstance(node_ids, list)

    def test_inverse_edges_are_present(self, mock_graph):
        repomap = RepoMap.build(mock_graph, root="/fake/root")
        data = repomap.render_json()
        edge_types = {edge["type"] for edge in data["edges"]}
        assert "CALLS" in edge_types
        assert "CALLED_BY" in edge_types


class TestRenderHierarchical:

    def test_contains_folder_emoji(self, mock_graph):
        repomap = RepoMap.build(mock_graph, root="/fake/root")
        output = repomap.render_hierarchical()
        assert "📁" in output

    def test_contains_file_emoji(self, mock_graph):
        repomap = RepoMap.build(mock_graph, root="/fake/root")
        output = repomap.render_hierarchical()
        assert "📄" in output

    def test_tree_only_no_entities(self, mock_graph):
        repomap = RepoMap.build(mock_graph, root="/fake/root")
        output = repomap.render_tree_only()
        # Should still have file names but not entity signatures
        assert "📄" in output


# ---------------------------------------------------------------------------
# Properties / Diagnostics
# ---------------------------------------------------------------------------

class TestRepomapProperties:

    def test_file_count(self, mock_graph):
        repomap = RepoMap.build(mock_graph, root="/fake/root")
        assert repomap.file_count == 2  # calculator.py and utils.py

    def test_entity_count(self, mock_graph):
        repomap = RepoMap.build(mock_graph, root="/fake/root")
        assert repomap.entity_count == 4

    def test_estimate_tokens(self, mock_graph):
        repomap = RepoMap.build(mock_graph, root="/fake/root")
        assert repomap.estimate_tokens() > 0

    def test_estimate_tokens_empty(self):
        repomap = RepoMap(_root="", _by_file={})
        assert repomap.estimate_tokens() == 0

    def test_group_by_directory(self, mock_graph):
        repomap = RepoMap.build(mock_graph, root="/fake/root")
        grouped = repomap.group_by_directory()
        assert isinstance(grouped, dict)
        assert len(grouped) > 0
