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
        """Verify that the graph rolls back to its original state when a partial mutation fails.

        Scenario:
            Two entities and a relationship are added to the graph. A forced exception is
            injected during the remove operation to simulate a mid-mutation failure.
            The graph must be fully restored to its pre-mutation state.

        Execution Flow:
            1. Add two entities and a relationship to the graph.
            2. Record the original entity count, relationship count, and by-file index.
            3. Replace the type index set with a RaisingSet that throws on discard for e1.
            4. Call remove_entities_for_file and assert GraphConsistencyError is raised.
            5. Assert the graph is restored: counts, indexes, and entities match the original state.

        Expectations:
            - All graph indexes (entities, relationships, by_file, by_type) are restored on rollback.
        """
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
        """Verify that a successful entity removal applies changes without triggering rollback.

        Scenario:
            Two entities from different files and a relationship between them are added.
            Removing entities for one file should cleanly delete only the targeted entities
            and their associated relationships.

        Execution Flow:
            1. Add e1 (test.py), e2 (other.py), and a relationship to the graph.
            2. Run remove_entities_for_file for "test.py".
            3. Assert e1 is removed, e2 remains, and no relationship from e1 exists.

        Expectations:
            - Successful removal deletes only the targeted file's entities and their relationships.
        """
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
        """Verify that secondary indexes (by_type, by_file) are restored during rollback.

        Scenario:
            An entity is added and indexed in secondary structures. A forced exception
            during removal must leave those secondary indexes intact after rollback.

        Execution Flow:
            1. Add an entity to the graph and assert it appears in _by_type.
            2. Replace the type index with a RaisingSet that raises on discard.
            3. Call remove_entities_for_file and assert GraphConsistencyError is raised.
            4. Assert the entity still exists and is present in both _by_file and _by_type.

        Expectations:
            - Secondary indexes are fully restored after a failed removal rollback.
        """
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
        """Verify that removing entities for a nonexistent file leaves the graph unchanged.

        Scenario:
            An entity exists in the graph under "exists.py". Attempting to remove entities
            for "missing.py" should be a no-op with no side effects.

        Execution Flow:
            1. Add an entity to the graph.
            2. Call remove_entities_for_file for "missing.py".
            3. Assert the entity still exists and the total entity count is unchanged.

        Expectations:
            - Removing a nonexistent file's entities is a safe no-op.
        """
        graph = InMemoryGraph()
        e1 = _entity("e1", file="exists.py")
        graph.add_entity(e1)

        updater = IncrementalGraphUpdater()
        updater.remove_entities_for_file(graph, "missing.py")

        assert "e1" in graph.entities
        assert len(graph.entities) == 1
