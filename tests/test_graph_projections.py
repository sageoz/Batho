"""Regression tests for GraphProjectionEngine performance changes.

Covers:
- build_level1 single-pass correctness and edge hardening
- build_level2 adjacency-index edge parity vs. brute-force scan
- _get_relationship_type lazy cache lifecycle and bidirectional coverage
"""
from __future__ import annotations

import pytest

from batho.bridge_core.services.graph_projections import GraphProjectionEngine
from batho.context.codegraph import InMemoryGraph
from batho.context.schema import Entity, EntityType, Relationship, RelationshipType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_entity(name: str, file: str, line: int = 1) -> Entity:
    return Entity(
        type=EntityType.FUNCTION,
        name=name,
        file=file,
        start_line=line,
        end_line=line + 5,
    )


def _make_rel(source: Entity, target: Entity, rel_type: RelationshipType = RelationshipType.CALLS) -> Relationship:
    return Relationship(source_id=source.id, target_id=target.id, type=rel_type)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def three_file_graph() -> InMemoryGraph:
    """Three files, two cross-file edges, two intra-file edges."""
    a = _make_entity("func_a1", "fileA.py", 1)
    b = _make_entity("func_a2", "fileA.py", 10)
    c = _make_entity("func_b1", "fileB.py", 1)
    d = _make_entity("func_c1", "fileC.py", 1)

    graph = InMemoryGraph()
    for e in [a, b, c, d]:
        graph.add_entity(e)

    # intra-file: A→A (should NOT appear in L1 cross-file edges)
    graph.add_relationship(_make_rel(a, b))
    # cross-file: A→B, A→C
    graph.add_relationship(_make_rel(a, c, RelationshipType.IMPORTS))
    graph.add_relationship(_make_rel(b, d, RelationshipType.CALLS))
    # mutual/bidirectional: B→C and C→B
    graph.add_relationship(_make_rel(c, d, RelationshipType.CALLS))
    graph.add_relationship(_make_rel(d, c, RelationshipType.CALLS))

    return graph


@pytest.fixture()
def engine(three_file_graph) -> GraphProjectionEngine:
    return GraphProjectionEngine(three_file_graph)


# ---------------------------------------------------------------------------
# build_level1 — single-pass correctness
# ---------------------------------------------------------------------------

class TestBuildLevel1:
    def test_node_count(self, engine):
        result = engine.build_level1()
        assert len(result["nodes"]) == 3

    def test_no_self_loop_edges(self, engine):
        result = engine.build_level1()
        for edge in result["edges"]:
            assert edge["source"] != edge["target"], "L1 must not contain self-loop edges"

    def test_cross_file_edges_present(self, engine):
        result = engine.build_level1()
        edge_pairs = {(e["source"], e["target"]) for e in result["edges"]}
        assert ("file:fileA.py", "file:fileB.py") in edge_pairs
        assert ("file:fileA.py", "file:fileC.py") in edge_pairs

    def test_weight_starts_at_one(self, engine):
        result = engine.build_level1()
        for edge in result["edges"]:
            assert edge["weight"] >= 1, "Edge weight must be at least 1 (never zero-init)"

    def test_types_dict_populated(self, engine):
        result = engine.build_level1()
        for edge in result["edges"]:
            assert isinstance(edge["types"], dict)
            assert len(edge["types"]) >= 1

    def test_cache_hit_returns_same_object(self, engine):
        r1 = engine.build_level1()
        r2 = engine.build_level1()
        assert r1 is r2, "_l1_cache should return the same object on second call"

    def test_stats_latency_present(self, engine):
        result = engine.build_level1()
        assert "latency_ms" in result["stats"]
        assert result["stats"]["latency_ms"] >= 0


# ---------------------------------------------------------------------------
# build_level2 — adjacency-index parity vs. brute-force
# ---------------------------------------------------------------------------

class TestBuildLevel2:
    def test_intra_file_edges_found(self, engine, three_file_graph):
        result = engine.build_level2("fileA.py")
        assert len(result["edges"]) == 1
        edge = result["edges"][0]
        # Both endpoints must belong to fileA.py
        assert edge["source"] in {e.id for e in three_file_graph.entities_by_file("fileA.py")}
        assert edge["target"] in {e.id for e in three_file_graph.entities_by_file("fileA.py")}

    def test_cross_file_edges_excluded(self, engine, three_file_graph):
        result = engine.build_level2("fileA.py")
        file_a_ids = {e.id for e in three_file_graph.entities_by_file("fileA.py")}
        for edge in result["edges"]:
            assert edge["source"] in file_a_ids
            assert edge["target"] in file_a_ids

    def test_parity_with_brute_force(self, three_file_graph):
        """Adjacency-index path must return identical edges as full relationship scan."""
        engine = GraphProjectionEngine(three_file_graph)
        result = engine.build_level2("fileA.py")
        adjacency_edges = {(e["source"], e["target"]) for e in result["edges"]}

        # Brute-force reference
        file_a_ids = {e.id for e in three_file_graph.entities_by_file("fileA.py")}
        brute_edges = set()
        for rel in three_file_graph.relationships:
            if rel.source_id in file_a_ids and rel.target_id in file_a_ids:
                brute_edges.add((rel.source_id, rel.target_id))

        assert adjacency_edges == brute_edges

    def test_empty_file_returns_no_edges(self, engine):
        result = engine.build_level2("nonexistent.py")
        assert result["edges"] == []
        assert result["nodes"] == []

    def test_edge_type_field_present(self, engine):
        result = engine.build_level2("fileA.py")
        for edge in result["edges"]:
            assert "type" in edge
            # rel.type.value from auto() Enum returns int; "unknown" fallback is str
            assert edge["type"] != "" and edge["type"] is not None


# ---------------------------------------------------------------------------
# _get_relationship_type — lazy cache lifecycle & bidirectional coverage
# ---------------------------------------------------------------------------

class TestEdgeTypeCache:
    def test_cache_is_none_before_first_call(self, engine):
        assert getattr(engine, '_edge_type_cache', None) is None

    def test_cache_populated_after_first_call(self, engine, three_file_graph):
        a = three_file_graph.entities_by_file("fileA.py")[0]
        b = three_file_graph.entities_by_file("fileB.py")[0]
        engine._get_relationship_type(a.id, b.id)
        assert engine._edge_type_cache is not None
        assert isinstance(engine._edge_type_cache, dict)

    def test_cache_keys_are_tuples(self, engine, three_file_graph):
        a = three_file_graph.entities_by_file("fileA.py")[0]
        b = three_file_graph.entities_by_file("fileB.py")[0]
        engine._get_relationship_type(a.id, b.id)
        for key in engine._edge_type_cache:
            assert isinstance(key, tuple)
            assert len(key) == 2

    def test_correct_type_returned(self, engine, three_file_graph):
        a_entities = three_file_graph.entities_by_file("fileA.py")
        b_entities = three_file_graph.entities_by_file("fileB.py")
        a = next(e for e in a_entities if e.name == "func_a1")
        b = b_entities[0]
        rel_type = engine._get_relationship_type(a.id, b.id)
        assert rel_type == RelationshipType.IMPORTS.value

    def test_unknown_returned_for_missing_edge(self, engine, three_file_graph):
        # func_a2 (fileA) has no outgoing edge to func_b1 (fileB) — only func_a1 does
        a2 = next(e for e in three_file_graph.entities.values() if e.name == "func_a2")
        b1 = next(e for e in three_file_graph.entities.values() if e.name == "func_b1")
        result = engine._get_relationship_type(a2.id, b1.id)
        assert result == "unknown"

    def test_bidirectional_edges_both_in_cache(self, engine, three_file_graph):
        engine._get_relationship_type("seed", "seed")  # trigger cache build
        c = three_file_graph.entities_by_file("fileC.py")[0]
        d = three_file_graph.entities_by_file("fileC.py")  # empty — use fileC/fileC
        # B(fileC) <-> C(fileC) are the mutual pair
        c_ent = next(e for e in three_file_graph.entities.values() if e.name == "func_c1")
        d_ent = next(e for e in three_file_graph.entities.values() if e.name == "func_c1" or e.file == "fileC.py")
        # Direct check: both (c→d) and (d→c) tuples must be in cache
        cache = engine._edge_type_cache
        c_id = next(e.id for e in three_file_graph.entities.values() if e.name == "func_c1")
        d_id = next(e.id for e in three_file_graph.entities.values() if e.name == "func_c1" or (e.file == "fileC.py" and e.name != "func_c1"))
        # fileC only has func_c1, fileB/fileC mutual pair: func_b1 <-> func_c1
        fb1 = next(e.id for e in three_file_graph.entities.values() if e.name == "func_b1")
        fc1 = next(e.id for e in three_file_graph.entities.values() if e.name == "func_c1")
        assert (fb1, fc1) in cache, "forward edge (func_b1 -> func_c1) must be in cache"
        assert (fc1, fb1) in cache, "reverse edge (func_c1 -> func_b1) must be in cache"

    def test_cache_reused_on_second_call(self, engine, three_file_graph):
        a = next(iter(three_file_graph.entities.values()))
        engine._get_relationship_type(a.id, a.id)
        cache_ref = engine._edge_type_cache
        engine._get_relationship_type(a.id, a.id)
        assert engine._edge_type_cache is cache_ref, "Cache must not be rebuilt on subsequent calls"
