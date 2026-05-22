"""Tests for batho.context.schema module."""
from __future__ import annotations

import pytest

from batho.utils.hash import compute_bytes_hash

from batho.context.schema import (
    Entity,
    EntityType,
    FileSnapshot,
    ReconstructionResult,
    Relationship,
    RelationshipType,
)


# ---------------------------------------------------------------------------
# EntityType
# ---------------------------------------------------------------------------

class TestEntityType:

    def test_all_members(self):
        expected = {
            "FUNCTION", "METHOD", "CLASS", "MODULE", "STRUCT", "INTERFACE",
            "FIELD", "ENUM", "TRAIT", "TYPE_ALIAS", "CONSTANT", "NAMESPACE",
            "VARIABLE", "PROPERTY", "ENTRY_POINT",
            "SETTING", "SECTION", "ELEMENT", "ATTRIBUTE", "DOCUMENT",
            "SYNTAX_GLUE", "GLOBAL_STATEMENT", "IMPORT_BLOCK", "COMMENT_BLOCK",
        }
        actual = {e.name for e in EntityType}
        assert expected.issubset(actual)

    def test_str_lowercase(self):
        assert str(EntityType.FUNCTION) == "function"
        assert str(EntityType.CLASS) == "class"


# ---------------------------------------------------------------------------
# RelationshipType
# ---------------------------------------------------------------------------

class TestRelationshipType:

    def test_all_members(self):
        expected = {
            "CALLS", "IMPORTS", "INHERITS", "IMPLEMENTS", "USES",
            "CONTAINS", "REFERENCES", "DEFINES",
            "WRAPPED_BY", "DEPENDS_ON_API", "REFERENCED_IN", "CLEANED_BY", "CONTAINED_WITHIN",
            "HAS_ATTRIBUTE", "LINKS_TO", "IMPORTS_STYLE",
        }
        actual = {r.name for r in RelationshipType}
        assert expected.issubset(actual)

    def test_str_lowercase(self):
        assert str(RelationshipType.CALLS) == "calls"


# ---------------------------------------------------------------------------
# Entity
# ---------------------------------------------------------------------------

class TestEntity:

    @pytest.fixture
    def sample_entity(self):
        return Entity(
            type=EntityType.FUNCTION,
            name="my_func",
            file="src/main.py",
            start_line=10,
            end_line=20,
            start_byte=100,
            end_byte=300,
            signature="my_func(a, b) -> int",
            metadata={"language": "python"},
        )

    def test_computed_id(self, sample_entity):
        assert len(sample_entity.id) == 16
        assert isinstance(sample_entity.id, str)

    def test_id_deterministic(self, sample_entity):
        e2 = Entity(
            type=EntityType.FUNCTION,
            name="my_func",
            file="src/main.py",
            start_line=10,
            end_line=20,
        )
        assert sample_entity.id == e2.id

    def test_frozen_model(self, sample_entity):
        with pytest.raises(Exception):
            sample_entity.name = "other"

    def test_to_dict(self, sample_entity):
        d = sample_entity.to_dict()
        assert d["id"] == sample_entity.id
        assert d["type"] == "FUNCTION"
        assert d["name"] == "my_func"
        assert d["file"] == "src/main.py"
        assert d["start_line"] == 10
        assert "raw_content" not in d

    def test_to_dict_storage_view(self):
        entity = Entity(
            type=EntityType.FUNCTION,
            name="with_content",
            file="src/main.py",
            start_line=1,
            end_line=1,
            start_byte=0,
            end_byte=3,
            raw_content="abc",
            content_hash="",
            leading_whitespace="",
            trailing_whitespace="\n",
            ast_node_type="FunctionDef",
            children_order=["a", "b"],
        )
        d = entity.to_dict(view="storage")
        assert d["raw_content"] == "abc"
        assert d["ast_node_type"] == "FunctionDef"
        assert d["children_order"] == ["a", "b"]

    def test_from_dict_roundtrip(self, sample_entity):
        d = sample_entity.to_dict()
        restored = Entity.from_dict(d)
        assert restored.id == sample_entity.id
        assert restored.name == sample_entity.name
        assert restored.type == sample_entity.type

    def test_from_dict_roundtrip_storage_view(self):
        entity = Entity(
            type=EntityType.FUNCTION,
            name="with_content",
            file="src/main.py",
            start_line=1,
            end_line=1,
            start_byte=0,
            end_byte=3,
            raw_content="abc",
            content_hash=compute_bytes_hash(b"abc"),
            children_order=["a"],
        )
        d = entity.to_dict(view="storage")
        restored = Entity.from_dict(d)
        assert restored.raw_content == "abc"
        assert restored.children_order == ["a"]

    def test_str(self, sample_entity):
        s = str(sample_entity)
        assert "my_func" in s
        assert "function" in s.lower()

    def test_compute_content_hash(self):
        entity = Entity(
            type=EntityType.FUNCTION,
            name="hash_me",
            file="src/main.py",
            start_line=1,
            end_line=1,
            raw_content="abc",
        )
        assert entity.compute_content_hash() == compute_bytes_hash(b"abc")

    def test_validate_coverage(self):
        entity = Entity(
            type=EntityType.FUNCTION,
            name="coverage",
            file="src/main.py",
            start_line=1,
            end_line=1,
            start_byte=0,
            end_byte=3,
            raw_content="abc",
        )
        assert entity.validate_coverage() is True

    def test_validate_coverage_missing_raw_content(self):
        entity = Entity(
            type=EntityType.FUNCTION,
            name="coverage",
            file="src/main.py",
            start_line=1,
            end_line=1,
        )
        # validate_coverage now returns False for missing raw_content instead of raising
        assert entity.validate_coverage() is False

    def test_validate_coverage_with_raw_bytes(self):
        """validate_coverage prefers raw_bytes for accurate byte length.

        This tests the fix for files with invalid UTF-8 characters where
        encoding raw_content would introduce replacement characters and
        inflate the byte length.
        """
        # Create content with invalid UTF-8 bytes
        raw_bytes = b"hello \xff\xfe world"  # invalid UTF-8
        # When decoded with errors='replace', replacement characters are added
        raw_content = raw_bytes.decode("utf-8", errors="replace")
        
        entity = Entity(
            type=EntityType.FUNCTION,
            name="coverage",
            file="src/main.py",
            start_line=1,
            end_line=1,
            start_byte=0,
            end_byte=len(raw_bytes),
            raw_content=raw_content,
            raw_bytes=raw_bytes,
        )
        
        # validate_coverage should use raw_bytes for accurate byte length
        assert entity.validate_coverage() is True

    def test_hash_and_eq(self):
        e1 = Entity(type=EntityType.FUNCTION, name="f", file="a.py", start_line=1, end_line=2)
        e2 = Entity(type=EntityType.FUNCTION, name="f", file="a.py", start_line=1, end_line=2)
        assert e1 == e2
        assert hash(e1) == hash(e2)

    def test_not_eq_different(self):
        e1 = Entity(type=EntityType.FUNCTION, name="f", file="a.py", start_line=1, end_line=2)
        e2 = Entity(type=EntityType.FUNCTION, name="g", file="a.py", start_line=1, end_line=2)
        assert e1 != e2

    def test_eq_not_implemented_for_non_entity(self):
        e = Entity(type=EntityType.FUNCTION, name="f", file="a.py", start_line=1, end_line=2)
        assert e != "not an entity"


# ---------------------------------------------------------------------------
# Relationship
# ---------------------------------------------------------------------------

class TestRelationship:

    @pytest.fixture
    def sample_rel(self):
        return Relationship(
            source_id="abc123",
            target_id="def456",
            type=RelationshipType.CALLS,
            metadata={"line_number": 15},
        )

    def test_computed_id(self, sample_rel):
        assert len(sample_rel.id) == 16

    def test_to_dict(self, sample_rel):
        d = sample_rel.to_dict()
        assert d["source_id"] == "abc123"
        assert d["target_id"] == "def456"
        assert d["type"] == "CALLS"

    def test_from_dict_roundtrip(self, sample_rel):
        d = sample_rel.to_dict()
        restored = Relationship.from_dict(d)
        assert restored.id == sample_rel.id
        assert restored.type == sample_rel.type

    def test_str(self, sample_rel):
        s = str(sample_rel)
        assert "abc123" in s
        assert "calls" in s

    def test_frozen_model(self, sample_rel):
        with pytest.raises(Exception):
            sample_rel.source_id = "other"

    def test_hash_and_eq(self):
        r1 = Relationship(source_id="a", target_id="b", type=RelationshipType.IMPORTS)
        r2 = Relationship(source_id="a", target_id="b", type=RelationshipType.IMPORTS)
        assert r1 == r2
        assert hash(r1) == hash(r2)


# ---------------------------------------------------------------------------
# Reconstruction models
# ---------------------------------------------------------------------------


class TestReconstructionModels:

    def test_file_snapshot_defaults(self):
        snap = FileSnapshot()
        assert snap.entity_ids == []
        assert snap.gap_sections == []

    def test_reconstruction_result_defaults(self):
        result = ReconstructionResult()
        assert result.success is False
        assert result.errors == []
