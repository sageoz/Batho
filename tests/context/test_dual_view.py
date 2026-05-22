"""Tests for Phase 4 — Dual-View BSGMap (Storage & Agent views).

Covers:
- BSGViewType enum
- render_storage_view() — raw_content, snapshots, metadata
- render_agent_view() — SYNTAX_GLUE filtering, token budget, truncation
- File snapshot add/get roundtrip
- reconstruct_file() and verify_file_integrity() delegation
"""

from __future__ import annotations

import hashlib

import pytest

from batho.context.bsg_map import BSGMap
from batho.context.schema import (
    BSGViewType,
    Entity,
    EntityType,
    FileSnapshot,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_entity(
    type_: EntityType,
    name: str,
    file: str,
    start_line: int,
    end_line: int,
    start_byte: int = 0,
    end_byte: int = 0,
    raw_content: str | None = None,
    metadata: dict | None = None,
) -> Entity:
    content = raw_content or ""
    h = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return Entity(
        type=type_,
        name=name,
        file=file,
        start_line=start_line,
        end_line=end_line,
        start_byte=start_byte,
        end_byte=end_byte,
        raw_content=content or None,
        content_hash=h if content else "",
        metadata=metadata or {},
    )


@pytest.fixture
def empty_bsg_map() -> BSGMap:
    """A BSGMap with no files."""
    return BSGMap(
        _root="/tmp/test",
        _by_file={},
        _dependencies={},
    )


@pytest.fixture
def sample_bsg_map() -> BSGMap:
    """A BSGMap with source files, one containing SYNTAX_GLUE entities."""
    return BSGMap(
        _root="/tmp/test-repo",
        _by_file={
            "src/app.py": [
                _make_entity(
                    EntityType.FUNCTION,
                    "main",
                    "src/app.py",
                    1, 10,
                    start_byte=0, end_byte=200,
                    raw_content="def main():\n    pass\n",
                ),
                _make_entity(
                    EntityType.CLASS,
                    "App",
                    "src/app.py",
                    12, 30,
                    start_byte=200, end_byte=500,
                    raw_content="class App:\n    def run(self):\n        pass\n",
                ),
            ],
            "src/utils.py": [
                _make_entity(
                    EntityType.FUNCTION,
                    "helper",
                    "src/utils.py",
                    1, 5,
                    start_byte=0, end_byte=80,
                    raw_content="def helper():\n    return 42\n",
                ),
            ],
            "src/gaps.py": [
                _make_entity(
                    EntityType.SYNTAX_GLUE,
                    "leading_ws",
                    "src/gaps.py",
                    1, 1,
                    start_byte=0, end_byte=10,
                    raw_content="\n\n\n\n\n\n\n\n\n\n",
                ),
                _make_entity(
                    EntityType.FUNCTION,
                    "do_stuff",
                    "src/gaps.py",
                    3, 8,
                    start_byte=10, end_byte=100,
                    raw_content="def do_stuff():\n    return 1\n",
                ),
                _make_entity(
                    EntityType.SYNTAX_GLUE,
                    "trailing_ws",
                    "src/gaps.py",
                    9, 10,
                    start_byte=100, end_byte=120,
                    raw_content="\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n",
                ),
            ],
        },
        _dependencies={
            "src/app.py": ["import:./utils.py"],
        },
    )


# ---------------------------------------------------------------------------
# Tests: BSGViewType
# ---------------------------------------------------------------------------


class TestBSGViewType:
    def test_enum_values_exist(self) -> None:
        assert BSGViewType.STORAGE is not None
        assert BSGViewType.AGENT is not None
        assert BSGViewType.HUMAN is not None

    def test_enum_str(self) -> None:
        assert str(BSGViewType.STORAGE) == "storage"
        assert str(BSGViewType.AGENT) == "agent"
        assert str(BSGViewType.HUMAN) == "human"

    def test_enum_members_count(self) -> None:
        assert len(BSGViewType) == 3


# ---------------------------------------------------------------------------
# Tests: File snapshot management
# ---------------------------------------------------------------------------


class TestFileSnapshots:
    def test_add_and_get_snapshot(self, sample_bsg_map: BSGMap) -> None:
        snapshot = FileSnapshot(
            file_path="src/app.py",
            file_hash="abc123",
            file_size=500,
            encoding="utf-8",
            entity_ids=["id1", "id2"],
        )
        sample_bsg_map.add_file_snapshot("src/app.py", snapshot)

        retrieved = sample_bsg_map.get_file_snapshot("src/app.py")
        assert retrieved is not None
        assert retrieved.file_path == "src/app.py"
        assert retrieved.file_hash == "abc123"
        assert retrieved.file_size == 500
        assert retrieved.entity_ids == ["id1", "id2"]

    def test_get_snapshot_missing(self, empty_bsg_map: BSGMap) -> None:
        assert empty_bsg_map.get_file_snapshot("nonexistent.py") is None

    def test_add_snapshot_invalidates_cache(self, sample_bsg_map: BSGMap) -> None:
        assert sample_bsg_map._view_cache_dirty is True

        snapshot = FileSnapshot(file_path="src/app.py", file_hash="abc")
        sample_bsg_map.add_file_snapshot("src/app.py", snapshot)

        assert sample_bsg_map._view_cache_dirty is True


# ---------------------------------------------------------------------------
# Tests: Storage view
# ---------------------------------------------------------------------------


class TestRenderStorageView:
    def test_storage_view_structure(self, sample_bsg_map: BSGMap) -> None:
        result = sample_bsg_map.render_storage_view()

        assert result["view_type"] == "storage"
        assert result["includes_raw_content"] is True
        assert result["includes_syntax_glue"] is True
        assert "schema_version" in result
        assert "generated_at" in result
        assert "files" in result

    def test_storage_view_entity_count(self, sample_bsg_map: BSGMap) -> None:
        result = sample_bsg_map.render_storage_view()

        # 3 files: app.py (2 entities) + utils.py (1) + gaps.py (3)
        assert result["entity_count"] == 6
        assert result["file_count"] == 3

    def test_storage_view_includes_raw_content(self, sample_bsg_map: BSGMap) -> None:
        result = sample_bsg_map.render_storage_view()

        for file_entry in result["files"]:
            for entity in file_entry["entities"]:
                assert "raw_content" in entity
                if entity["type"] != "SYNTAX_GLUE":
                    assert entity["raw_content"] is not None

    def test_storage_view_with_file_paths_filter(self, sample_bsg_map: BSGMap) -> None:
        result = sample_bsg_map.render_storage_view(file_paths=["src/app.py"])

        assert result["entity_count"] == 2
        assert result["file_count"] == 1
        assert result["files"][0]["file_path"] == "src/app.py"

    def test_storage_view_with_snapshots(self, sample_bsg_map: BSGMap) -> None:
        snapshot = FileSnapshot(
            file_path="src/app.py",
            file_hash="def456",
            file_size=500,
            encoding="utf-8",
        )
        sample_bsg_map.add_file_snapshot("src/app.py", snapshot)

        result = sample_bsg_map.render_storage_view()
        assert result["snapshot_count"] == 1

        app_entry = next(
            f for f in result["files"] if f["file_path"] == "src/app.py"
        )
        assert "snapshot" in app_entry
        assert app_entry["snapshot"]["file_hash"] == "def456"

    def test_storage_view_empty_map(self, empty_bsg_map: BSGMap) -> None:
        result = empty_bsg_map.render_storage_view()

        assert result["entity_count"] == 0
        assert result["file_count"] == 0
        assert result["files"] == []

    def test_storage_view_syntax_glue_present(self, sample_bsg_map: BSGMap) -> None:
        result = sample_bsg_map.render_storage_view()

        gaps_file = next(f for f in result["files"] if f["file_path"] == "src/gaps.py")
        types = [e["type"] for e in gaps_file["entities"]]
        assert "SYNTAX_GLUE" in types


# ---------------------------------------------------------------------------
# Tests: Agent view
# ---------------------------------------------------------------------------


class TestRenderAgentView:
    def test_agent_view_structure(self, sample_bsg_map: BSGMap) -> None:
        view_dict, stats = sample_bsg_map.render_agent_view()

        assert view_dict["view_type"] == "agent"
        assert view_dict["includes_raw_content"] is False
        assert "schema_version" in view_dict
        assert "generated_at" in view_dict
        assert "files" in view_dict

    def test_agent_view_excludes_syntax_glue(self, sample_bsg_map: BSGMap) -> None:
        view_dict, stats = sample_bsg_map.render_agent_view()

        # gaps.py had 3 entities (2 SYNTAX_GLUE + 1 FUNCTION)
        # After filtering: only 1 entity from gaps.py remains
        gaps_file = next(
            (f for f in view_dict["files"] if f["file_path"] == "src/gaps.py"),
            None,
        )
        assert gaps_file is not None
        assert gaps_file["entity_count"] == 1
        assert gaps_file["entities"][0]["type"] == "FUNCTION"

    def test_agent_view_no_token_budget(self, sample_bsg_map: BSGMap) -> None:
        view_dict, stats = sample_bsg_map.render_agent_view()

        # all non-glue entities: app.py (2) + utils.py (1) + gaps.py (1) = 4
        assert view_dict["entity_count"] == 4
        assert stats["truncated"] is False

    def test_agent_view_with_token_budget(self, sample_bsg_map: BSGMap) -> None:
        # Very small budget should cause truncation
        view_dict, stats = sample_bsg_map.render_agent_view(token_budget=1)

        assert stats["token_budget"] == 1
        assert stats["tokens_used"] <= 1
        assert stats["truncated"] is True

    def test_agent_view_compression_ratio(self, sample_bsg_map: BSGMap) -> None:
        view_dict, stats = sample_bsg_map.render_agent_view()

        # 6 total entities -> 4 agent entities = 4/6 = 0.6667
        assert stats["compression_ratio"] == pytest.approx(0.6667, abs=0.01)
        assert view_dict["compression_ratio"] == pytest.approx(0.6667, abs=0.01)

    def test_agent_view_large_docstring_truncated(self) -> None:
        """Verify large docstrings are truncated by default."""
        long_doc = "A" * 500
        entity = _make_entity(
            EntityType.FUNCTION,
            "doc_func",
            "src/doc.py",
            1, 5,
            start_byte=0, end_byte=100,
            raw_content="def doc_func():\n    pass",
            metadata={"docstring": long_doc},
        )
        bsg_map = BSGMap(
            _root="/tmp/test",
            _by_file={"src/doc.py": [entity]},
        )

        view_dict, stats = bsg_map.render_agent_view()
        doc_file = view_dict["files"][0]
        doc_meta = doc_file["entities"][0]["metadata"]
        assert len(doc_meta["docstring"]) <= 203  # 200 + "..."


    def test_agent_view_empty_map(self, empty_bsg_map: BSGMap) -> None:
        view_dict, stats = empty_bsg_map.render_agent_view()

        assert view_dict["entity_count"] == 0
        assert view_dict["file_count"] == 0
        assert stats["compression_ratio"] == 1.0
        assert stats["truncated"] is False

    def test_agent_view_returns_tuple(self, sample_bsg_map: BSGMap) -> None:
        result = sample_bsg_map.render_agent_view()

        assert isinstance(result, tuple)
        assert len(result) == 2
        assert "view_type" in result[0]
        assert "token_budget" in result[1]


# ---------------------------------------------------------------------------
# Tests: Reconstruction delegation
# ---------------------------------------------------------------------------


class TestReconstructFromMap:
    def test_reconstruct_file_unknown_path(self, sample_bsg_map: BSGMap) -> None:
        with pytest.raises(ValueError, match="No entities found"):
            sample_bsg_map.reconstruct_file("unknown.py")

    def test_reconstruct_file_no_snapshot(self, sample_bsg_map: BSGMap) -> None:
        """Should attempt reconstruction even without a snapshot (hash=None)."""
        result = sample_bsg_map.reconstruct_file("src/utils.py")
        assert result.file_path == "src/utils.py"
        assert result.entity_count == 1
        assert result.reconstructed_content is not None

    def test_reconstruct_file_missing_raw_content(self, sample_bsg_map: BSGMap) -> None:
        """Add an entity with no raw_content; should fail."""
        bad_entity = _make_entity(
            EntityType.VARIABLE,
            "broken",
            "src/broken.py",
            1, 1,
            start_byte=0, end_byte=10,
            raw_content=None,
        )
        bad_map = BSGMap(
            _root="/tmp/test",
            _by_file={"src/broken.py": [bad_entity]},
        )
        with pytest.raises(Exception):
            bad_map.reconstruct_file("src/broken.py")

    def test_verify_integrity_no_snapshot(self, sample_bsg_map: BSGMap) -> None:
        """verify_file_integrity should report no snapshot."""
        result = sample_bsg_map.verify_file_integrity("src/utils.py")
        assert result["verified"] is False
        assert "No snapshot" in result["errors"][0]

    def test_verify_integrity_with_snapshot(self, sample_bsg_map: BSGMap) -> None:
        """With a snapshot matching entities, verification succeeds."""
        snapshot = FileSnapshot(
            file_path="src/utils.py",
            file_hash=hashlib.sha256(
                b"def helper():\n    return 42\n"
            ).hexdigest(),
            file_size=80,
            encoding="utf-8",
            entity_ids=["helper_id"],
        )
        sample_bsg_map.add_file_snapshot("src/utils.py", snapshot)
        # The entity's raw_content matches the snapshot hash content
        result = sample_bsg_map.verify_file_integrity("src/utils.py")
        assert result["hash_match"] is True
        assert result["verified"] is True

    def test_verify_integrity_with_wrong_snapshot(self, sample_bsg_map: BSGMap) -> None:
        """With a non-matching snapshot hash, integrity should fail."""
        snapshot = FileSnapshot(
            file_path="src/utils.py",
            file_hash="0000000000000000000000000000000000000000000000000000000000000000",
            file_size=80,
            encoding="utf-8",
            entity_ids=["helper_id"],
        )
        sample_bsg_map.add_file_snapshot("src/utils.py", snapshot)
        result = sample_bsg_map.verify_file_integrity("src/utils.py")
        assert result["hash_match"] is False

    def test_verify_integrity_unknown_file(self, sample_bsg_map: BSGMap) -> None:
        result = sample_bsg_map.verify_file_integrity("unknown.py")
        assert result["verified"] is False
        assert "No snapshot" in result["errors"][0]


# ---------------------------------------------------------------------------
# Tests: Backward compatibility
# ---------------------------------------------------------------------------


class TestBackwardCompatibility:
    def test_render_json_unchanged(self, sample_bsg_map: BSGMap) -> None:
        """Existing render_json should still work without any view_type key."""
        result = sample_bsg_map.render_json()
        assert "view_type" not in result
        assert "nodes" in result
        assert "edges" in result

    def test_render_compressed_unchanged(self, sample_bsg_map: BSGMap) -> None:
        """Existing render_compressed should still work."""
        text, stats = sample_bsg_map.render_compressed(budget=10000)
        assert isinstance(text, str)
        assert "tokens_used" in stats

    def test_from_dict_preserves_bidirectional_attributes(self) -> None:
        """BSGMap.from_dict should preserve all bidirectional and AST attributes and decode hex raw_bytes."""
        raw_bytes_hex = b"print('hello')".hex()
        data = {
            "root": "/tmp/test",
            "nodes": [
                {
                    "id": "function:hello:src/app.py:5",
                    "type": "FUNCTION",
                    "name": "hello",
                    "file": "src/app.py",
                    "start_line": 5,
                    "end_line": 10,
                    "start_byte": 100,
                    "end_byte": 114,
                    "signature": "def hello()",
                    "metadata": {"docstring": "greeting"},
                    "parent_id": "class:App:src/app.py:1",
                    "raw_content": "print('hello')",
                    "raw_bytes": raw_bytes_hex,
                    "content_hash": "hash123",
                    "leading_whitespace": "  ",
                    "trailing_whitespace": "\n",
                    "ast_node_type": "FunctionDef",
                    "children_order": ["child1", "child2"],
                }
            ],
            "edges": [],
        }

        reconstructed_map = BSGMap.from_dict(data)
        entities = reconstructed_map._by_file["src/app.py"]
        assert len(entities) == 1
        entity = entities[0]

        assert entity.type == EntityType.FUNCTION
        assert entity.name == "hello"
        assert entity.file == "src/app.py"
        assert entity.start_line == 5
        assert entity.end_line == 10
        assert entity.start_byte == 100
        assert entity.end_byte == 114
        assert entity.signature == "def hello()"
        assert entity.metadata == {"docstring": "greeting"}
        assert entity.parent_id == "class:App:src/app.py:1"
        assert entity.raw_content == "print('hello')"
        assert entity.raw_bytes == b"print('hello')"
        assert entity.content_hash == "hash123"
        assert entity.leading_whitespace == "  "
        assert entity.trailing_whitespace == "\n"
        assert entity.ast_node_type == "FunctionDef"
        assert entity.children_order == ["child1", "child2"]


class TestBidirectionalEnrichment:
    def test_bidirectional_attributes_enrichment(self) -> None:
        """Verify that _enrich_cached_entities resolves containment hierarchy and whitespace."""
        from batho.context.pipeline import _enrich_cached_entities

        # Create parent and child entities (simulating cache loading)
        parent = Entity(
            type=EntityType.CLASS,
            name="Container",
            file="src/test.py",
            start_line=1,
            end_line=3,
            start_byte=0,
            end_byte=54,
        )
        child = Entity(
            type=EntityType.FUNCTION,
            name="inside",
            file="src/test.py",
            start_line=2,
            end_line=3,
            start_byte=21,
            end_byte=54,
            ast_node_type="function_definition",
        )

        content = b"class Container:\n    def inside(self):\n        pass\n"
        # Run enrichment
        enriched = _enrich_cached_entities([parent, child], content, "src/test.py")

        assert len(enriched) == 2
        p_enriched = next(e for e in enriched if e.name == "Container")
        c_enriched = next(e for e in enriched if e.name == "inside")

        # parent-child hierarchy
        assert c_enriched.parent_id == p_enriched.id
        assert p_enriched.children_order == [c_enriched.id]

        # leading/trailing whitespaces
        assert p_enriched.leading_whitespace == ""
        assert p_enriched.trailing_whitespace == ""
        assert c_enriched.leading_whitespace == "\n    "
        assert c_enriched.trailing_whitespace == ""
        assert c_enriched.ast_node_type == "function_definition"

    def test_whitespace_no_double_counting(self) -> None:
        """Verify that adjacent sibling entities partition the whitespace between them without overlap."""
        from batho.context.pipeline import _enrich_cached_entities
        from batho.context.schema import Entity, EntityType

        e1 = Entity(
            type=EntityType.FUNCTION,
            name="first",
            file="src/test.py",
            start_line=1,
            end_line=2,
            start_byte=0,
            end_byte=12,
        )
        e2 = Entity(
            type=EntityType.FUNCTION,
            name="second",
            file="src/test.py",
            start_line=4,
            end_line=5,
            start_byte=19,
            end_byte=32,
        )

        # 0..12: "def first():"
        # 12..19: "\n\n\n    "
        # 19..32: "def second():"
        content = b"def first():\n\n\n    def second():"
        enriched = _enrich_cached_entities([e1, e2], content, "src/test.py")

        assert len(enriched) == 2
        e1_enriched = next(e for e in enriched if e.name == "first")
        e2_enriched = next(e for e in enriched if e.name == "second")

        # e2 should own all of the gap whitespace in its leading_whitespace
        assert e2_enriched.leading_whitespace == "\n\n\n    "
        # e1 should have NO trailing_whitespace from that gap
        assert e1_enriched.trailing_whitespace == ""

    def test_reconstructor_coverage_calculation(self) -> None:
        """Verify that reconstructor computes byte coverage using union of intervals, not exceeding 100%."""
        from batho.context.reconstructor import FileReconstructor
        from batho.context.schema import Entity, EntityType

        # Create two overlapping entities
        e1 = Entity(
            type=EntityType.CLASS,
            name="Container",
            file="src/test.py",
            start_line=1,
            end_line=3,
            start_byte=0,
            end_byte=30,
            raw_content="class Container:\n    pass\n",
        )
        e2 = Entity(
            type=EntityType.FUNCTION,
            name="method",
            file="src/test.py",
            start_line=2,
            end_line=3,
            start_byte=10,
            end_byte=25,
            raw_content="    pass\n",
        )

        reconstructor = FileReconstructor()
        result = reconstructor.reconstruct_file(
            file_path="src/test.py",
            entities=[e1, e2],
            original_content="class Container:\n    pass\n",
        )

        assert result.success is True
        assert result.byte_coverage == 1.0  # Union covers the entire file


