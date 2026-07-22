"""Tests for the ArrowGraph columnar graph backend."""

from __future__ import annotations

import ast
from pathlib import Path

import pyarrow as pa
import pytest

from batho.core.schemas import (
    Entity,
    EntityType,
    Relationship,
    RelationshipType,
    SymbolRole,
)
from batho.modules.graph.builder.arrow_graph import ArrowGraph
from batho.modules.graph.builder.codegraph import InMemoryGraph
from batho.modules.graph.builder.protocol import GraphBackend


def _entity(
    name: str,
    file: str = "a.py",
    type: EntityType = EntityType.FUNCTION,
    start_line: int = 1,
    end_line: int = 5,
    parent_id: str | None = None,
    **kwargs,
) -> Entity:
    return Entity(
        type=type,
        name=name,
        file=file,
        start_line=start_line,
        end_line=end_line,
        parent_id=parent_id,
        **kwargs,
    )


@pytest.fixture
def staging(tmp_path: Path) -> Path:
    return tmp_path / "staging"


@pytest.fixture
def entities() -> list[Entity]:
    mod = _entity("mod", file="a.py", type=EntityType.MODULE, end_line=50,
                  signature="mod-sig", content_hash="hash-mod",
                  metadata={"role": "root"}, children_order=["c1", "c2"])
    fn = _entity("foo", file="a.py", type=EntityType.FUNCTION,
                 start_line=2, end_line=9, parent_id=mod.id,
                 signature="foo(x)", content_hash="hash-foo",
                 ast_node_type="function_def",
                 enclosing_start_byte=10, enclosing_end_byte=99)
    cls = _entity("Bar", file="b.py", type=EntityType.CLASS,
                  start_line=1, end_line=30, is_documentation=False)
    return [mod, fn, cls]


@pytest.fixture
def relationships(entities) -> list[Relationship]:
    mod, fn, cls = entities
    return [
        Relationship(
            source_id=mod.id, target_id=fn.id, type=RelationshipType.CONTAINS,
            roles=SymbolRole.Definition, confidence=0.95,
            reference_start_byte=10, reference_end_byte=20,
            metadata={"line_number": 2},
        ),
        Relationship(
            source_id=fn.id, target_id=cls.id, type=RelationshipType.CALLS,
            roles=SymbolRole.ReadAccess, confidence=0.7,
            definition_start_byte=1, definition_end_byte=5,
        ),
        Relationship(
            source_id=fn.id, target_id="external:os.path",
            type=RelationshipType.IMPORTS,
        ),
    ]


@pytest.fixture
def graph(staging, entities, relationships) -> ArrowGraph:
    g = ArrowGraph(staging_dir=staging, flush_rows=2, flush_bytes_mb=0.001)
    g.add_entities_batch(entities)
    g.add_relationships_batch(relationships)
    return g


# ---------------------------------------------------------------------------
# Phase 1/2: streaming + dict-backed behavior
# ---------------------------------------------------------------------------


def test_add_and_get_entity(graph, entities):
    mod = entities[0]
    got = graph.get_entity(mod.id)
    assert got is not None
    assert got.id == mod.id
    assert got.name == "mod"
    assert got.type == EntityType.MODULE
    assert graph.get_entity("missing") is None


def test_add_and_iterate_entities(graph, entities):
    ids = {e.id for e in graph.entities.values()}
    assert ids == {e.id for e in entities}
    assert set(graph.entities.keys()) == ids
    assert dict(graph.entities.items()).keys() == ids
    assert len(graph.entities) == len(entities) == len(graph)


def test_add_and_iterate_relationships(graph, relationships):
    rels = list(graph.relationships)
    assert len(rels) == len(relationships) == len(graph.relationships)
    assert {r.id for r in rels} == {r.id for r in relationships}


def test_relationship_dedup(graph, relationships):
    before = len(graph.relationships)
    graph.add_relationship(relationships[0])
    assert len(graph.relationships) == before


def test_streaming_flush(entities):
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        staging = Path(td) / "st"
        g = ArrowGraph(staging_dir=staging, flush_rows=2, flush_bytes_mb=100)
        g.add_entity(entities[0])
        # Not yet flushed (below row threshold).
        assert not (staging / "entities.stream.arrow").exists()
        g.add_entity(entities[1])
        # Threshold reached -> stream file written.
        assert (staging / "entities.stream.arrow").exists()
        g.close()


def test_load_stream_to_dicts_implicit(graph):
    # Read triggers implicit Phase-2 load (dicts materialized from streams).
    assert len(graph) == 3
    assert graph._entity_dicts is not None
    assert graph._rel_dicts is not None


def test_extras_json_roundtrip_pre_compact(graph, entities):
    mod, fn, _ = entities
    got_mod = graph.get_entity(mod.id)
    assert got_mod.signature == "mod-sig"
    assert got_mod.content_hash == "hash-mod"
    assert got_mod.metadata == {"role": "root"}
    assert got_mod.children_order == ["c1", "c2"]
    got_fn = graph.get_entity(fn.id)
    assert got_fn.ast_node_type == "function_def"
    assert got_fn.enclosing_start_byte == 10
    assert got_fn.enclosing_end_byte == 99
    assert got_fn.parent_id == mod.id


def test_update_entity_pre_compact(graph, entities):
    fn = entities[1]
    evolved = fn._evolve(name="foo2", file="z.py")
    graph.update_entity(fn.id, evolved)
    got = graph.get_entity(fn.id)
    assert got.name == "foo2"
    # Entity.id is content-computed: the stored entity carries the evolved id.
    assert got.id == evolved.id
    # Secondary indexes stay in sync (keyed by the update's entity_id).
    assert [e.id for e in graph.entities_by_file("z.py")] == [evolved.id]
    assert fn.id not in {e.id for e in graph.entities_by_file("a.py")}


def test_update_relationships_pre_compact(graph, relationships):
    # Stub-resolution pattern: full replacement.
    mod, fn, cls = (None, None, None)
    new_rel = Relationship(
        source_id=relationships[1].source_id,
        target_id=relationships[0].source_id,
        type=RelationshipType.USES,
    )
    graph.update_relationships([new_rel])
    assert len(graph.relationships) == 1
    assert list(graph.relationships)[0].type == RelationshipType.USES


def test_update_relationship_single(graph, relationships):
    target = relationships[0]
    updated = target._evolve(confidence=0.5)
    graph.update_relationship(updated)
    found = [r for r in graph.relationships if r.id == target.id]
    assert len(found) == 1
    assert found[0].confidence == 0.5


def test_remove_node_pre_compact(graph, entities):
    cls = entities[2]
    assert graph.remove_node(cls.id) is True
    assert cls.id not in graph
    assert graph.remove_node(cls.id) is False
    # The CALLS rel targeting cls is detached with the node.
    assert all(r.target_id != cls.id for r in graph.relationships)


def test_evict_file_graph(graph):
    graph.evict_file_graph("a.py")
    assert len(graph.entities_by_file("a.py")) == 0
    remaining = {e.file for e in graph.entities.values()}
    assert remaining == {"b.py"}


# ---------------------------------------------------------------------------
# Phase 3: compact + mmap + CSR/CSC
# ---------------------------------------------------------------------------


@pytest.fixture
def compacted(graph) -> ArrowGraph:
    graph.compact()
    return graph


def test_compact_preserves_entities(compacted, entities):
    assert len(compacted) == len(entities)
    for e in entities:
        got = compacted.get_entity(e.id)
        assert got is not None
        assert got.id == e.id
        # Reconstructed entities carry id_override (identity preserved); all
        # other serialized fields must roundtrip identically.
        got_payload = {**got.to_dict(view="storage"), "id_override": None}
        want_payload = {**e.to_dict(view="storage"), "id_override": None}
        assert got_payload == want_payload


def test_compact_preserves_identity_after_id_changing_update(graph, entities):
    """update_entity(old_id, evolved) must keep old_id resolvable post-compact.

    Semantic post-processing legitimately changes id components (type/name),
    and relationships extracted earlier still reference the original id —
    InMemoryGraph keeps that key forever, and ArrowGraph must match.
    """
    fn = entities[1]
    old_id = fn.id
    evolved = fn._evolve(type=EntityType.METHOD)  # type is part of the id
    assert evolved.id != old_id
    graph.update_entity(old_id, evolved)
    rel = Relationship(
        source_id=entities[0].id, target_id=old_id, type=RelationshipType.CONTAINS
    )
    graph.add_relationship(rel)
    graph.compact()

    got = graph.get_entity(old_id)
    assert got is not None, "old id must resolve after compact"
    assert got.type == EntityType.METHOD
    assert old_id in graph
    assert old_id in graph.get_all_nodes()
    # The relationship referencing old_id must survive CSR construction.
    assert old_id in graph.neighbors(entities[0].id, "out")
    assert entities[0].id in graph.neighbors(old_id, "in")
    assert any(r.target_id == old_id for r in graph.get_rels_by_endpoint(old_id))


def test_extras_json_roundtrip_post_compact(compacted, entities):
    mod, fn, _ = entities
    got = compacted.get_entity(mod.id)
    assert got.signature == "mod-sig"
    assert got.content_hash == "hash-mod"
    assert got.children_order == ["c1", "c2"]
    assert got.metadata == {"role": "root"}


def test_relationship_fields_roundtrip_post_compact(compacted):
    rels = {r.type: r for r in compacted.relationships}
    contains = rels[RelationshipType.CONTAINS]
    assert contains.roles == SymbolRole.Definition
    assert contains.confidence == 0.95
    assert contains.reference_start_byte == 10
    assert contains.reference_end_byte == 20
    assert contains.metadata.get("line_number") == 2
    calls = rels[RelationshipType.CALLS]
    assert calls.definition_start_byte == 1
    assert calls.confidence == 0.7


def test_csr_neighbors(compacted, entities):
    mod, fn, cls = entities
    assert set(compacted.neighbors(mod.id, "out")) == {fn.id}
    assert compacted.neighbors(mod.id, "in") == []
    assert set(compacted.neighbors(fn.id, "out")) == {cls.id, "external:os.path"}
    assert set(compacted.neighbors(fn.id, "in")) == {mod.id}
    assert set(compacted.neighbors(fn.id, "both")) == {mod.id, cls.id, "external:os.path"}
    assert compacted.neighbors("missing", "out") == []


def test_csr_edge_checks(compacted, entities):
    mod, fn, cls = entities
    assert compacted.has_outgoing_edges(mod.id) is True
    assert compacted.has_incoming_edges(mod.id) is False
    assert compacted.has_outgoing_edges(cls.id) is False
    assert compacted.has_incoming_edges(cls.id) is True
    assert compacted.has_outgoing_edges("missing") is False


def test_csr_external_endpoints(compacted, entities):
    # Relationships to non-entity targets remain reachable via neighbors.
    fn = entities[1]
    assert "external:os.path" in compacted.neighbors(fn.id, "out")


def test_entities_by_file_post_compact(compacted):
    assert {e.name for e in compacted.entities_by_file("a.py")} == {"mod", "foo"}
    assert [e.name for e in compacted.entities_by_file("b.py")] == ["Bar"]
    assert compacted.entities_by_file("nope.py") == []


def test_entities_by_type_post_compact(compacted):
    assert [e.name for e in compacted.entities_by_type(EntityType.CLASS)] == ["Bar"]
    assert len(compacted.entities_by_type(EntityType.MODULE)) == 1


def test_get_rels_by_endpoint_post_compact(compacted, entities):
    fn = entities[1]
    rels = compacted.get_rels_by_endpoint(fn.id)
    assert len(rels) == 3  # CONTAINS(in) + CALLS(out) + IMPORTS(out)
    assert compacted.get_rels_by_endpoint("missing") == []


def test_get_rels_by_endpoint_self_loop_parity(compacted, entities):
    """Self-loops appear twice (source+target), matching InMemoryGraph."""
    fn = entities[1]
    loop = Relationship(source_id=fn.id, target_id=fn.id, type=RelationshipType.CALLS)
    mem = InMemoryGraph()
    mem.add_entities_batch(entities)
    mem.add_relationship(loop)
    g = compacted  # already compacted; build a fresh one below for pre-compact too
    # Add to the compacted graph is disallowed; use a fresh graph instead.
    g2 = ArrowGraph(staging_dir=g._staging_dir.parent / "selfloop")
    g2.add_entities_batch(entities)
    g2.add_relationship(loop)
    mem_before = mem.get_rels_by_endpoint(fn.id)
    arrow_before = g2.get_rels_by_endpoint(fn.id)
    assert len(mem_before) == len(arrow_before) == 2
    assert mem.degree_by_endpoint(fn.id) == g2.degree_by_endpoint(fn.id) == 2
    g2.compact()
    assert len(g2.get_rels_by_endpoint(fn.id)) == 2
    assert g2.degree_by_endpoint(fn.id) == 2
    g2.close()


def test_root_entities_post_compact(compacted, entities):
    roots = {e.name for e in compacted.root_entities()}
    assert roots == {"mod", "Bar"}


def test_mutation_after_compact_raises(compacted, entities):
    with pytest.raises(RuntimeError):
        compacted.remove_node(entities[0].id)
    with pytest.raises(RuntimeError):
        compacted.update_entity(entities[0].id, entities[0])
    with pytest.raises(RuntimeError):
        compacted.add_entity(entities[0])


def test_dictionary_encoding(compacted):
    entity_type_field = compacted._entity_table.schema.field("entity_type")
    file_field = compacted._entity_table.schema.field("file")
    rel_type_field = compacted._rel_table.schema.field("rel_type")
    assert pa.types.is_dictionary(entity_type_field.type)
    assert pa.types.is_dictionary(file_field.type)
    assert pa.types.is_dictionary(rel_type_field.type)


def test_ipc_files_uncompressed_and_mmapable(compacted):
    # pa.memory_map requires uncompressed IPC; compact() already opened it.
    entity_path = compacted._staging_dir / "entities.arrow"
    assert entity_path.exists()
    with pa.memory_map(str(entity_path), "r") as mmap:
        table = pa.ipc.open_file(mmap).read_all()
    assert table.num_rows == 3


def test_stats(compacted):
    stats = compacted.stats()
    assert stats["entity_count"] == 3
    assert stats["relationship_count"] == 3
    assert stats["file_count"] == 2
    assert stats["total_entities"] == 3
    assert stats["total_relationships"] == 3


def test_to_dict_from_dict_roundtrip(compacted, tmp_path):
    data = compacted.to_dict()
    assert set(data["entities_by_id"].keys()) == set(compacted.get_all_nodes())
    assert len(data["relationships"]) == 3
    g2 = ArrowGraph.from_dict(data, staging_dir=tmp_path / "st2")
    assert set(g2.get_all_nodes()) == set(compacted.get_all_nodes())
    assert len(g2.relationships) == len(compacted.relationships)
    g2.close()


def test_close_releases_and_removes_staging(graph):
    graph.compact()
    staging = graph._staging_dir
    assert staging.exists()
    graph.close()
    assert not staging.exists()
    # Idempotent.
    graph.close()


def test_compact_idempotent(graph):
    graph.compact()
    table_before = graph._entity_table
    graph.compact()  # no-op
    assert graph._entity_table is table_before


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


def test_protocol_conformance(graph):
    assert isinstance(graph, GraphBackend)
    assert isinstance(InMemoryGraph(), GraphBackend)


def test_parity_with_inmemory(entities, relationships, tmp_path):
    """Same input -> equivalent public API results on both backends."""
    mem = InMemoryGraph()
    mem.add_entities_batch(entities)
    mem.add_relationships_batch(relationships)
    arrow = ArrowGraph(staging_dir=tmp_path / "st", flush_rows=5000)
    arrow.add_entities_batch(entities)
    arrow.add_relationships_batch(relationships)
    arrow.compact()

    assert set(mem.get_all_nodes()) == set(arrow.get_all_nodes())
    fn = entities[1]
    assert set(mem.neighbors(fn.id, "out")) == set(arrow.neighbors(fn.id, "out"))
    assert set(mem.neighbors(fn.id, "in")) == set(arrow.neighbors(fn.id, "in"))
    assert {r.id for r in mem.get_rels_by_endpoint(fn.id)} == {
        r.id for r in arrow.get_rels_by_endpoint(fn.id)
    }
    assert {e.id for e in mem.root_entities()} == {e.id for e in arrow.root_entities()}
    assert len(mem) == len(arrow)
    assert len(mem.relationships) == len(arrow.relationships)
    arrow.close()


# ---------------------------------------------------------------------------
# Regression: no private graph attribute access in consumer/build code
# ---------------------------------------------------------------------------


def test_no_private_access_regression():
    """Consumer and build-path code must not touch graph._ private attributes.

    IncrementalGraphUpdater is intentionally exempt (patch is in-memory only).
    """
    repo_root = Path(__file__).resolve().parents[3]

    # 1. Consumers: zero private access.
    consumer_files = [
        repo_root / "batho/modules/graph/community.py",
        repo_root / "batho/modules/compression/rules.py",
        repo_root / "batho/modules/compression/bsg_map/__init__.py",
    ]
    for path in consumer_files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr.startswith("_"):
                if isinstance(node.value, ast.Name) and node.value.id == "graph":
                    pytest.fail(f"{path}:{node.lineno} accesses graph.{node.attr}")

    # 2. codegraph.py: private access allowed only inside IncrementalGraphUpdater.
    codegraph = repo_root / "batho/modules/graph/builder/codegraph.py"
    source = codegraph.read_text(encoding="utf-8")
    tree = ast.parse(source)
    exempt_ranges: list[tuple[int, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "IncrementalGraphUpdater":
            exempt_ranges.append((node.lineno, node.end_lineno or node.lineno))
    lines = source.splitlines()
    for lineno, line in enumerate(lines, start=1):
        if "graph._" not in line:
            continue
        if any(start <= lineno <= end for start, end in exempt_ranges):
            continue
        pytest.fail(f"codegraph.py:{lineno} accesses private graph attr: {line.strip()}")
