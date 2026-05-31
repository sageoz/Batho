"""Tests for IncrementalGraphUpdater transactional rollback (BUG-03)."""

from __future__ import annotations

from collections import defaultdict

import pytest

from batho.core.schemas import (
    Entity,
    EntityType,
    GraphConsistencyError,
    Relationship,
    RelationshipType,
)
from batho.modules.graph.builder.codegraph import (
    InMemoryGraph,
    IncrementalGraphUpdater,
)


def _entity(entity_id: str, file: str = "f.py") -> Entity:
    return Entity(
        type=EntityType.FUNCTION,
        name=entity_id,
        file=file,
        start_line=1,
        end_line=1,
        id_override=entity_id,
    )


def _rel(source_id: str, target_id: str) -> Relationship:
    return Relationship(
        source_id=source_id, target_id=target_id, type=RelationshipType.CALLS
    )


class RaisingSet(set):
    """Set subclass that raises on discard() for a specific item."""

    def __init__(self, *args, bad_item: str = "", **kwargs):
        super().__init__(*args, **kwargs)
        self._bad_item = bad_item

    def discard(self, item):
        if item == self._bad_item:
            raise RuntimeError("boom")
        super().discard(item)


class RaisingList(list):
    """List subclass that raises on append()."""

    def append(self, item):
        raise RuntimeError("boom")


class TestRemoveEntitiesTransactionalRollback:
    """BUG-03: Graph must rollback to pre-mutation state on partial failure."""

    def test_rollback_restores_entities_on_exception(self):
        graph = InMemoryGraph()
        e1 = _entity("e1", file="test.py")
        e2 = _entity("e2", file="test.py")
        r1 = _rel("e1", "e2")

        graph.add_entity(e1)
        graph.add_entity(e2)
        graph.add_relationship(r1)

        original_entity_count = len(graph.entities)
        original_rel_count = len(graph.relationships)
        original_by_file = set(graph._by_file.get("test.py", set()))

        updater = IncrementalGraphUpdater()

        # Force an exception halfway through mutation by replacing the type
        # index set with one that raises on discard for e1.
        graph._by_type[e1.type] = RaisingSet(
            graph._by_type[e1.type], bad_item=e1.id
        )

        with pytest.raises(GraphConsistencyError):
            updater.remove_entities_for_file(graph, "test.py")

        # After rollback, graph must be exactly as it was before
        assert len(graph.entities) == original_entity_count
        assert len(graph.relationships) == original_rel_count
        assert set(graph._by_file.get("test.py", set())) == original_by_file
        assert "e1" in graph.entities
        assert "e2" in graph.entities
        assert any(r.id == r1.id for r in graph.relationships)

    def test_successful_removal_no_rollback_needed(self):
        graph = InMemoryGraph()
        e1 = _entity("e1", file="test.py")
        e2 = _entity("e2", file="other.py")
        r1 = _rel("e1", "e2")

        graph.add_entity(e1)
        graph.add_entity(e2)
        graph.add_relationship(r1)

        updater = IncrementalGraphUpdater()
        updater.remove_entities_for_file(graph, "test.py")

        assert "e1" not in graph.entities
        assert "e2" in graph.entities
        assert not any(r.source_id == "e1" for r in graph.relationships)

    def test_rollback_restores_secondary_indexes(self):
        graph = InMemoryGraph()
        e1 = _entity("e1", file="test.py")
        e1_type = e1.type

        graph.add_entity(e1)
        assert e1.id in graph._by_type[e1_type]

        updater = IncrementalGraphUpdater()

        # Make the mutation fail during _by_type discard to verify that
        # secondary indexes are restored during rollback.
        graph._by_type[e1.type] = RaisingSet(
            graph._by_type[e1.type], bad_item=e1.id
        )

        with pytest.raises(GraphConsistencyError):
            updater.remove_entities_for_file(graph, "test.py")

        assert "e1" in graph.entities
        assert e1.id in graph._by_file["test.py"]
        assert e1.id in graph._by_type[e1_type]

    def test_remove_nonexistent_file_is_noop(self):
        graph = InMemoryGraph()
        e1 = _entity("e1", file="exists.py")
        graph.add_entity(e1)

        updater = IncrementalGraphUpdater()
        updater.remove_entities_for_file(graph, "missing.py")

        assert "e1" in graph.entities
        assert len(graph.entities) == 1
