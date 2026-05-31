"""Tests for graph consistency helpers (cycles, orphan pruning)."""

from __future__ import annotations

from batho.core.schemas import Entity, EntityType, Relationship, RelationshipType
from batho.modules.graph.builder.codegraph import CodeGraphIndexer, InMemoryGraph


def _entity(entity_id: str, *, entity_type: EntityType = EntityType.MODULE) -> Entity:
    return Entity(
        type=entity_type,
        name=entity_id,
        file=f"{entity_id}.py",
        start_line=1,
        end_line=1,
        id_override=entity_id,
    )


def _rel(source_id: str, target_id: str, rel_type: RelationshipType) -> Relationship:
    return Relationship(source_id=source_id, target_id=target_id, type=rel_type)


def test_find_cycles_imports():
    graph = InMemoryGraph()
    graph.add_entities_batch([_entity("A"), _entity("B"), _entity("C")])
    graph.add_relationships_batch(
        [
            _rel("A", "B", RelationshipType.IMPORTS),
            _rel("B", "C", RelationshipType.IMPORTS),
            _rel("C", "A", RelationshipType.IMPORTS),
        ]
    )

    indexer = CodeGraphIndexer()
    cycles = indexer.find_cycles(graph, RelationshipType.IMPORTS)

    assert cycles
    assert any(set(cycle) == {"A", "B", "C"} for cycle in cycles)


def test_find_cycles_inherits_self_cycle():
    graph = InMemoryGraph()
    graph.add_entities_batch([_entity("Self")])
    graph.add_relationships_batch([
        _rel("Self", "Self", RelationshipType.INHERITS),
    ])

    indexer = CodeGraphIndexer()
    cycles = indexer.find_cycles(graph, RelationshipType.INHERITS)

    assert len(cycles) == 1
    assert cycles[0][0] == "Self"
    assert cycles[0][-1] == "Self"


def test_find_cycles_none():
    graph = InMemoryGraph()
    graph.add_entities_batch([_entity("A"), _entity("B")])
    graph.add_relationships_batch([
        _rel("A", "B", RelationshipType.IMPORTS),
    ])

    indexer = CodeGraphIndexer()
    cycles = indexer.find_cycles(graph, RelationshipType.IMPORTS)

    assert cycles == []


def test_orphan_pruning_keeps_entry_points():
    graph = InMemoryGraph()
    graph.add_entities_batch(
        [
            _entity("Entry", entity_type=EntityType.ENTRY_POINT),
            _entity("Orphan"),
            _entity("Parent"),
            _entity("Child"),
        ]
    )
    graph.add_relationships_batch([
        _rel("Parent", "Child", RelationshipType.CONTAINS),
    ])

    indexer = CodeGraphIndexer()
    pruned = indexer.prune_orphan_nodes(
        graph, keep_entry_points=True, keep_exports=False
    )

    assert pruned == 1
    assert "Orphan" not in graph.entities
    assert "Entry" in graph.entities
    assert "Parent" in graph.entities
    assert "Child" in graph.entities
    assert len(graph.relationships) == 1


def test_orphan_pruning_respects_keep_nodes():
    graph = InMemoryGraph()
    graph.add_entities_batch([_entity("Keep"), _entity("Drop")])

    indexer = CodeGraphIndexer()
    indexer.mark_keep_node("Keep")
    pruned = indexer.prune_orphan_nodes(
        graph, keep_entry_points=False, keep_exports=False
    )

    assert pruned == 1
    assert "Keep" in graph.entities
    assert "Drop" not in graph.entities
