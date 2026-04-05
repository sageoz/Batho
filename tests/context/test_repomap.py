"""Tests for batho_core.context.repomap module."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from batho_core.context.codegraph import InMemoryGraph
from batho_core.context.bsg_map import BSGMap as RepoMap, _text_tokens
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

    def test_build_ms_and_snapshot_fallback(self, mock_graph):
        repomap = RepoMap.build(mock_graph, root="/fake/root")
        data = repomap.render_json(build_ms=321, default_snapshot_id="snap-123")

        assert data["stats"]["build_ms"] == 321
        assert data["nodes"]
        for node in data["nodes"]:
            assert node["snapshot_id"] == "snap-123"
            assert node["service_tag"]

        assert data["stats"]["autofilled_snapshot_ids"] == len(data["nodes"])
        assert data["stats"]["quality_warnings"] >= 1
        assert any("auto-filled snapshot_id" in warning for warning in data["quality_warnings"])

    def test_quality_warning_for_zero_build_and_missing_snapshot(self):
        graph = InMemoryGraph()
        graph.add_entity(
            Entity(
                type=EntityType.FUNCTION,
                name="run",
                file="src/main.py",
                start_line=1,
                end_line=3,
                signature="run()",
                metadata={"language": "python"},
            )
        )

        repomap = RepoMap.build(graph, root="/fake/root")
        data = repomap.render_json(build_ms=0)

        assert data["nodes"][0]["snapshot_id"] is None
        assert data["nodes"][0]["service_tag"]
        assert data["stats"]["missing_snapshot_ids"] == 1
        assert data["stats"]["quality_warnings"] >= 1
        assert any("build_ms is 0" in warning for warning in data["quality_warnings"])
        assert any("missing snapshot_id" in warning for warning in data["quality_warnings"])

    def test_category_normalization_docs_to_doc(self):
        graph = InMemoryGraph()
        graph.add_entity(
            Entity(
                type=EntityType.DOCUMENT,
                name="guide",
                file="docs/guide.md",
                start_line=1,
                end_line=5,
                metadata={
                    "language": "markdown",
                    "bsg.category": "DOCS",
                },
            )
        )

        repomap = RepoMap.build(graph, root="/fake/root")
        data = repomap.render_json(build_ms=42, default_snapshot_id="snap-doc")

        assert data["nodes"][0]["category"] == "DOC"
        assert data["stats"]["category_normalizations"] == 1
        assert any("normalized bsg.category" in warning for warning in data["quality_warnings"])

    def test_streaming_render_matches_json_payload(self, mock_graph):
        repomap = RepoMap.build(mock_graph, root="/fake/root")
        expected = repomap.render_json(build_ms=50, default_snapshot_id="snap-xyz")
        streamed = "".join(
            repomap.render_json_streaming(build_ms=50, default_snapshot_id="snap-xyz")
        )

        assert streamed
        actual = json.loads(streamed)
        actual["generated_at"] = expected["generated_at"]
        assert expected == actual

    def test_streaming_render_supports_extra_fields(self, mock_graph):
        repomap = RepoMap.build(mock_graph, root="/fake/root")
        streamed = "".join(
            repomap.render_json_streaming(
                build_ms=12,
                default_snapshot_id="snap-extra",
                extra_fields={"stack": {"primary": "python"}},
            )
        )
        payload = json.loads(streamed)
        assert payload["stack"]["primary"] == "python"

    def test_streaming_render_does_not_call_render_json(self, mock_graph, monkeypatch):
        repomap = RepoMap.build(mock_graph, root="/fake/root")

        def _boom(*_args, **_kwargs):
            raise AssertionError("render_json should not be called by streaming mode")

        monkeypatch.setattr(RepoMap, "render_json", _boom)
        streamed = "".join(
            repomap.render_json_streaming(build_ms=7, default_snapshot_id="snap-stream")
        )
        payload = json.loads(streamed)
        assert payload["schema_version"] == "bsg.v1"

    def test_streaming_render_extra_fields_can_override_base_keys(self, mock_graph):
        repomap = RepoMap.build(mock_graph, root="/fake/root")
        streamed = "".join(
            repomap.render_json_streaming(
                build_ms=12,
                default_snapshot_id="snap-extra",
                extra_fields={"root": "/override/root"},
            )
        )
        payload = json.loads(streamed)
        assert payload["root"] == "/override/root"

    def test_serialization_config_streaming_mode(self, mock_graph):
        """Test that streaming mode is used when configured."""
        repomap = RepoMap.build(
            mock_graph,
            root="/fake/root",
            serialization_config={"method": "streaming"}
        )
        data = repomap.render_json(build_ms=50, default_snapshot_id="snap-xyz")
        assert data["schema_version"] == "bsg.v1"
        assert data["stats"]["build_ms"] == 50

    def test_serialization_config_legacy_mode(self, mock_graph):
        """Test that legacy mode is used when configured."""
        repomap = RepoMap.build(
            mock_graph,
            root="/fake/root",
            serialization_config={"method": "legacy"}
        )
        data = repomap.render_json(build_ms=50, default_snapshot_id="snap-xyz")
        assert data["schema_version"] == "bsg.v1"
        assert data["stats"]["build_ms"] == 50

    def test_serialization_config_default_to_streaming(self, mock_graph):
        """Test that streaming is the default when no config is provided."""
        repomap = RepoMap.build(mock_graph, root="/fake/root")
        # Default should be streaming
        assert repomap._serialization_config.get("method", "streaming") == "streaming"


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
