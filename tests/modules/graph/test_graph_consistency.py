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
    """Verify that cyclic import relationships are detected in the graph.

    Scenario:
        Three entities form an import cycle (A imports B, B imports C, C imports A).
        The cycle detector must identify this closed loop.

    Execution Flow:
        1. Create an in-memory graph with entities A, B, and C.
        2. Add IMPORTS relationships forming a cycle.
        3. Invoke find_cycles on the graph.
        4. Assert that at least one cycle is found containing all three entities.

    Expectations:
        - Cyclic import chains are correctly identified and returned.
    """
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
    """Verify that a self-inheritance loop is detected as a cycle.

    Scenario:
        A single entity inherits from itself, forming a trivial one-node cycle.

    Execution Flow:
        1. Create a graph with a single entity "Self".
        2. Add an INHERITS relationship from "Self" to itself.
        3. Run find_cycles for INHERITS relationships.
        4. Assert exactly one cycle is found, starting and ending at "Self".

    Expectations:
        - Self-referential inheritance is correctly flagged as a cycle.
    """
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
    """Verify that an acyclic graph returns an empty cycle list.

    Scenario:
        Two entities have a one-way relationship (A imports B) with no back-edge.
        No cycle should exist.

    Execution Flow:
        1. Create a graph with entities A and B.
        2. Add a single IMPORTS relationship from A to B.
        3. Run find_cycles.
        4. Assert the result is an empty list.

    Expectations:
        - Acyclic import chains do not produce false-positive cycle detections.
    """
    graph = InMemoryGraph()
    graph.add_entities_batch([_entity("A"), _entity("B")])
    graph.add_relationships_batch([
        _rel("A", "B", RelationshipType.IMPORTS),
    ])

    indexer = CodeGraphIndexer()
    cycles = indexer.find_cycles(graph, RelationshipType.IMPORTS)

    assert cycles == []


def test_orphan_pruning_keeps_entry_points():
    """Verify that orphan pruning preserves entry points and connected subgraphs.

    Scenario:
        A graph contains an entry point, an isolated orphan, and a parent-child pair.
        Pruning should remove only the orphan while keeping everything else.

    Execution Flow:
        1. Add Entry (ENTRY_POINT), Orphan (isolated), Parent, and Child to the graph.
        2. Add a CONTAINS relationship between Parent and Child.
        3. Run prune_orphan_nodes with keep_entry_points=True.
        4. Assert exactly one node was pruned (Orphan).
        5. Assert Entry, Parent, and Child remain in the graph.

    Expectations:
        - Entry points are never pruned.
        - Connected subgraphs are preserved.
        - Only truly orphaned nodes are removed.
    """
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
    """Verify that explicitly marked keep nodes are preserved during orphan pruning.

    Scenario:
        Two isolated entities exist. One is marked as a keep node, the other is not.
        Only the unmarked entity should be pruned.

    Execution Flow:
        1. Add entities "Keep" and "Drop" to the graph.
        2. Mark "Keep" via mark_keep_node.
        3. Run prune_orphan_nodes with keep_entry_points=False and keep_exports=False.
        4. Assert exactly one node is pruned.
        5. Assert "Keep" remains and "Drop" is removed.

    Expectations:
        - Manually marked keep nodes survive orphan pruning regardless of other flags.
    """
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
