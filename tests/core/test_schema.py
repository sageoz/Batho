"""Tests for batho.context.schema module."""
from __future__ import annotations

import pytest

from batho.context.schema import (
    Entity,
    EntityType,
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

    def test_from_dict_roundtrip(self, sample_entity):
        d = sample_entity.to_dict()
        restored = Entity.from_dict(d)
        assert restored.id == sample_entity.id
        assert restored.name == sample_entity.name
        assert restored.type == sample_entity.type

    def test_str(self, sample_entity):
        s = str(sample_entity)
        assert "my_func" in s
        assert "function" in s.lower()

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
