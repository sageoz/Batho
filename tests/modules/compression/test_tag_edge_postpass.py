"""Tests for T04 tag-driven edge derivation (batho-calibrate).

Covers the derivation layer inside `_derive_semantic_relations`:
- `bsg.edge_hints` metadata -> annotation edges (annotation-types-only,
  capped, unresolvable-safe)
- `bsg.semantic_family` -> SEMANTICALLY_SIMILAR_TO (directory-bounded, top-K)
- TESTED_BY (test naming conventions + import/call affinity)
- Rationale residual (`bsg.rationale` -> enclosing/nearest symbol, deduped
  against extractor-emitted RATIONALE_FOR edges)
- Annotation-class exclusion from community clustering input
- Determinism
"""

from __future__ import annotations

from batho.modules.graph import InMemoryGraph
from batho.modules.graph.community import _CLUSTERING_RELATIONS
from batho.modules.compression.rules import _derive_semantic_relations
from batho.core.schemas import (
    ANNOTATION_RELATIONS,
    Entity,
    EntityType,
    Relationship,
    RelationshipType,
)


def _ent(
    etype: EntityType,
    name: str,
    file: str,
    start: int,
    end: int,
    metadata: dict | None = None,
    signature: str | None = None,
    id_override: str | None = None,
) -> Entity:
    return Entity(
        type=etype,
        name=name,
        file=file,
        start_line=start,
        end_line=end,
        metadata=metadata or {},
        signature=signature,
        id_override=id_override,
    )


def _edges(graph: InMemoryGraph) -> dict[tuple[str, str, str], Relationship]:
    return {
        (r.source_id, r.target_id, r.type.name): r
        for r in _derive_semantic_relations(graph)
    }


def _graph(*entities: Entity, rels: list[Relationship] | None = None) -> InMemoryGraph:
    return InMemoryGraph(
        entities={e.id: e for e in entities},
        relationships=rels or [],
    )


# ---------------------------------------------------------------------------
# bsg.edge_hints
# ---------------------------------------------------------------------------


def test_edge_hint_by_entity_id():
    src = _ent(
        EntityType.FUNCTION, "hinter", "a/x.py", 1, 3,
        metadata={"bsg.edge_hints": [{"type": "TESTED_BY", "target_entity_id": "t1"}]},
    )
    tgt = _ent(EntityType.CLASS, "Thing", "a/x.py", 10, 20, id_override="t1")
    rels = _edges(_graph(src, tgt))

    rel = rels.get((src.id, "t1", "TESTED_BY"))
    assert rel is not None
    assert rel.metadata["edge_class"] == "annotation"
    assert rel.metadata["source"] == "tag_postpass"
    assert rel.metadata["reason"] == "edge_hint"
    assert 0.0 < rel.confidence < 1.0


def test_edge_hint_by_fqn_and_name_pattern():
    src = _ent(
        EntityType.FUNCTION, "h", "a/h.py", 1, 2,
        metadata={
            "bsg.edge_hints": [
                {"type": "REFERS_TO", "target_fqn": "GraphService"},
                {"type": "REFERS_TO", "target_name_pattern": "auth*"},
            ]
        },
    )
    t1 = _ent(EntityType.CLASS, "GraphService", "a/s.py", 1, 5)  # fqn == name for CLASS
    t2 = _ent(EntityType.FUNCTION, "AuthHelper", "a/s.py", 10, 12)
    rels = _edges(_graph(src, t1, t2))

    assert (src.id, t1.id, "REFERS_TO") in rels
    assert (src.id, t2.id, "REFERS_TO") in rels


def test_edge_hint_rejects_structural_type():
    src = _ent(
        EntityType.FUNCTION, "h", "a/h.py", 1, 2,
        metadata={"bsg.edge_hints": [{"type": "CALLS", "target_entity_id": "t1"}]},
    )
    tgt = _ent(EntityType.CLASS, "Thing", "a/x.py", 1, 5, id_override="t1")
    rels = _edges(_graph(src, tgt))
    assert not rels


def test_edge_hint_unresolvable_skipped():
    src = _ent(
        EntityType.FUNCTION, "h", "a/h.py", 1, 2,
        metadata={
            "bsg.edge_hints": [
                {"type": "REFERS_TO", "target_entity_id": "ghost"},
                {"type": "REFERS_TO", "target_fqn": "No.Such.Symbol"},
                {"type": "REFERS_TO", "target_name_pattern": "zzz*"},
                {"type": "REFERS_TO"},  # no target at all
                "not-a-dict",
            ]
        },
    )
    tgt = _ent(EntityType.CLASS, "Thing", "a/x.py", 1, 5)
    rels = _edges(_graph(src, tgt))
    assert not rels


def test_edge_hint_per_source_cap():
    hints = [
        {"type": "REFERS_TO", "target_entity_id": f"t{i}"}
        for i in range(60)
    ]
    src = _ent(
        EntityType.FUNCTION, "h", "a/h.py", 1, 2,
        metadata={"bsg.edge_hints": hints},
    )
    targets = [_ent(EntityType.VARIABLE, f"v{i}", "a/x.py", 1, 1, id_override=f"t{i}") for i in range(60)]
    rels = _edges(_graph(src, *targets))
    assert 0 < len(rels) <= 50


def test_edge_hint_custom_confidence_clamped():
    src = _ent(
        EntityType.FUNCTION, "h", "a/h.py", 1, 2,
        metadata={"bsg.edge_hints": [{"type": "TESTED_BY", "target_entity_id": "t1", "confidence": 5.0}]},
    )
    tgt = _ent(EntityType.CLASS, "Thing", "a/x.py", 1, 5, id_override="t1")
    rel = _edges(_graph(src, tgt))[(src.id, "t1", "TESTED_BY")]
    assert rel.confidence <= 0.95


# ---------------------------------------------------------------------------
# bsg.semantic_family -> SEMANTICALLY_SIMILAR_TO
# ---------------------------------------------------------------------------


def test_family_similarity_same_dir():
    fam = {"bsg.semantic_family": "repo"}
    e1 = _ent(EntityType.CLASS, "GraphRepo", "svc/r1.py", 1, 5, metadata=dict(fam))
    e2 = _ent(EntityType.CLASS, "UserRepo", "svc/r2.py", 1, 5, metadata=dict(fam))
    e3 = _ent(EntityType.CLASS, "BillingRepo", "svc/r3.py", 1, 5, metadata=dict(fam))
    other_dir = _ent(EntityType.CLASS, "InfraRepo", "other/r4.py", 1, 5, metadata=dict(fam))
    rels = _edges(_graph(e1, e2, e3, other_dir))

    sim_edges = {
        k: r for k, r in rels.items()
        if k[2] == "SEMANTICALLY_SIMILAR_TO"
    }
    assert sim_edges  # at least one pair
    assert all(r.confidence == 0.80 for r in sim_edges.values())
    assert all(r.metadata["edge_class"] == "annotation" for r in sim_edges.values())
    # directory bound: other_dir never appears in a similarity edge
    involved = {s for s, _t, _ty in sim_edges} | {t for _s, t, _ty in sim_edges}
    assert other_dir.id not in involved


def test_family_degree_cap():
    fam = {"bsg.semantic_family": "repo"}
    ents = [
        _ent(EntityType.CLASS, f"Repo{i}Repo", f"svc/r{i}.py", 1, 5, metadata=dict(fam))
        for i in range(8)
    ]
    rels = _edges(_graph(*ents))
    degree: dict[str, int] = {}
    for s, t, ty in rels:
        if ty != "SEMANTICALLY_SIMILAR_TO":
            continue
        degree[s] = degree.get(s, 0) + 1
        degree[t] = degree.get(t, 0) + 1
    assert degree
    assert all(d <= 5 for d in degree.values())


def test_usn_tag_family_lower_confidence():
    tag = {"bsg.usn": ["semantic_family"]}
    e1 = _ent(EntityType.CLASS, "GraphRepo", "svc/r1.py", 1, 5, metadata=dict(tag))
    e2 = _ent(EntityType.CLASS, "UserRepo", "svc/r2.py", 1, 5, metadata=dict(tag))
    rels = _edges(_graph(e1, e2))
    sim = [r for r in rels.values() if r.type.name == "SEMANTICALLY_SIMILAR_TO"]
    assert sim and all(r.confidence == 0.65 for r in sim)


# ---------------------------------------------------------------------------
# TESTED_BY
# ---------------------------------------------------------------------------


def test_tested_by_name_only():
    test_fn = _ent(EntityType.FUNCTION, "test_compute", "tests/test_x.py", 1, 5)
    prod = _ent(EntityType.FUNCTION, "compute", "src/x.py", 1, 5)
    rels = _edges(_graph(test_fn, prod))
    rel = rels.get((test_fn.id, prod.id, "TESTED_BY"))
    assert rel is not None
    assert rel.confidence == 0.65  # name-affinity only, no existing edge


def test_tested_by_with_call_affinity():
    test_fn = _ent(EntityType.FUNCTION, "test_compute", "tests/test_x.py", 1, 5)
    prod = _ent(EntityType.FUNCTION, "compute", "src/x.py", 1, 5)
    calls = Relationship(
        source_id=test_fn.id, target_id=prod.id, type=RelationshipType.CALLS
    )
    rels = _edges(_graph(test_fn, prod, rels=[calls]))
    rel = rels.get((test_fn.id, prod.id, "TESTED_BY"))
    assert rel is not None
    assert rel.confidence == 0.85


def test_no_test_to_test_edges():
    t1 = _ent(EntityType.FUNCTION, "test_alpha", "tests/test_a.py", 1, 5)
    t2 = _ent(EntityType.FUNCTION, "test_beta", "tests/test_b.py", 1, 5)
    helper = _ent(EntityType.FUNCTION, "alpha", "src/a.py", 1, 5)
    rels = _edges(_graph(t1, t2, helper))
    tested = {(s, t) for s, t, ty in rels if ty == "TESTED_BY"}
    assert (t1.id, t2.id) not in tested
    assert (t2.id, t1.id) not in tested
    assert (t1.id, helper.id) in tested  # t1 covers "alpha"


# ---------------------------------------------------------------------------
# Rationale residual
# ---------------------------------------------------------------------------


def test_rationale_residual_enclosing():
    fn = _ent(EntityType.FUNCTION, "service_call", "a/s.py", 10, 50)
    note = _ent(
        EntityType.COMMENT_BLOCK, "design note", "a/s.py", 20, 22,
        metadata={"bsg.rationale": True},
    )
    rels = _edges(_graph(fn, note))
    rel = rels.get((note.id, fn.id, "RATIONALE_FOR"))
    assert rel is not None
    assert rel.confidence == 0.75
    assert rel.metadata["edge_class"] == "annotation"


def test_rationale_residual_nearest_following():
    note = _ent(
        EntityType.COMMENT_BLOCK, "header note", "a/s.py", 1, 3,
        metadata={"bsg.rationale": True},
    )
    fn = _ent(EntityType.FUNCTION, "service_call", "a/s.py", 10, 50)
    rels = _edges(_graph(note, fn))
    assert (note.id, fn.id, "RATIONALE_FOR") in rels


def test_rationale_residual_dedup_vs_extracted():
    fn = _ent(EntityType.FUNCTION, "service_call", "a/s.py", 10, 50)
    note = _ent(
        EntityType.COMMENT_BLOCK, "why note", "a/s.py", 20, 22,
        metadata={"bsg.rationale": True},
    )
    extracted = Relationship(
        source_id=note.id, target_id=fn.id, type=RelationshipType.RATIONALE_FOR
    )
    rels = _edges(_graph(fn, note, rels=[extracted]))
    assert (note.id, fn.id, "RATIONALE_FOR") not in rels  # no duplicate emitted


def test_rationale_usn_tag_trigger():
    fn = _ent(EntityType.FUNCTION, "service_call", "a/s.py", 10, 50)
    note = _ent(
        EntityType.COMMENT_BLOCK, "note", "a/s.py", 20, 22,
        metadata={"bsg.usn": ["rationale"]},
    )
    rels = _edges(_graph(fn, note))
    assert (note.id, fn.id, "RATIONALE_FOR") in rels


# ---------------------------------------------------------------------------
# Cross-cutting
# ---------------------------------------------------------------------------


def test_quarantined_entities_never_get_derived_edges():
    fam = {"bsg.semantic_family": "repo"}
    e1 = _ent(EntityType.CLASS, "GraphRepo", "svc/r1.py", 1, 5, metadata=dict(fam))
    ghost = _ent(
        EntityType.EXTERNAL_SYMBOL, "RepoStub", "svc/r2.py", 1, 5,
        metadata={**fam, "bsg.quarantined": True},
    )
    test_fn = _ent(EntityType.FUNCTION, "test_compute", "tests/test_x.py", 1, 5)
    ghost_target = _ent(
        EntityType.FUNCTION, "compute", "src/x.py", 1, 5,
        metadata={"bsg.noise": True},
    )
    note = _ent(
        EntityType.COMMENT_BLOCK, "note", "a/q.py", 1, 2,
        metadata={"bsg.rationale": True, "bsg.quarantined": True},
    )
    fn = _ent(EntityType.FUNCTION, "svc", "a/q.py", 5, 30)
    rels = _edges(_graph(e1, ghost, test_fn, ghost_target, note, fn))

    involved = {s for s, _t, _ty in rels} | {t for _s, t, _ty in rels}
    assert ghost.id not in involved      # no similarity edges to quarantined
    assert ghost_target.id not in involved  # no TESTED_BY to quarantined target
    assert note.id not in involved       # quarantined comment emits nothing


def test_annotation_types_excluded_from_clustering():
    for t in ANNOTATION_RELATIONS:
        assert t not in _CLUSTERING_RELATIONS
    assert {RelationshipType.SEMANTICALLY_SIMILAR_TO, RelationshipType.TESTED_BY,
            RelationshipType.REFERS_TO, RelationshipType.RATIONALE_FOR} <= set(ANNOTATION_RELATIONS)


def test_zero_cost_without_tags():
    e1 = _ent(EntityType.FUNCTION, "foo", "a/x.py", 1, 5)
    e2 = _ent(EntityType.FUNCTION, "bar", "a/x.py", 10, 15)
    rels = _edges(_graph(e1, e2))
    assert not rels


def test_determinism():
    fam = {"bsg.semantic_family": "repo"}
    ents = [
        _ent(EntityType.CLASS, "GraphRepo", "svc/r1.py", 1, 5, metadata=dict(fam)),
        _ent(EntityType.CLASS, "UserRepo", "svc/r2.py", 1, 5, metadata=dict(fam)),
        _ent(EntityType.FUNCTION, "test_compute", "tests/test_x.py", 1, 5),
        _ent(EntityType.FUNCTION, "compute", "src/x.py", 1, 5),
        _ent(EntityType.COMMENT_BLOCK, "note", "src/x.py", 2, 3, metadata={"bsg.rationale": True}),
    ]
    first = set(_edges(_graph(*ents)))
    second = set(_edges(_graph(*ents)))
    assert first == second


# ---------------------------------------------------------------------------
# RUL-03: explicit bsg.semantic_family edges carry plugin_family_tag reason
# ---------------------------------------------------------------------------


def test_family_reason_metadata_keyed_bucket():
    """A `bsg.semantic_family`-keyed pair must stamp reason
    'plugin_family_tag' — the edge_type-keyed registry lookup previously
    returned the last SEMANTICALLY_SIMILAR_TO row ('family_tag_no_key')."""
    fam = {"bsg.semantic_family": "repo"}
    a = _ent(EntityType.CLASS, "AlphaRepo", "d/a.py", 1, 3, metadata=dict(fam))
    b = _ent(EntityType.CLASS, "BetaRepo", "d/b.py", 1, 3, metadata=dict(fam))
    rels = _edges(_graph(a, b))
    sim = [r for r in rels.values() if r.type.name == "SEMANTICALLY_SIMILAR_TO"]
    assert sim, "expected at least one family edge"
    assert all(r.metadata["reason"] == "plugin_family_tag" for r in sim)
    assert all(r.confidence == 0.80 for r in sim)


def test_family_reason_usn_tag_bucket():
    """USN-tag 'semantic_family' (no bsg key) keeps the lower tier
    'family_tag_no_key' + 0.65 confidence."""
    tag = {"bsg.usn": ["semantic_family"]}
    a = _ent(EntityType.CLASS, "AlphaRepo", "d/a.py", 1, 3, metadata=dict(tag))
    b = _ent(EntityType.CLASS, "BetaRepo", "d/b.py", 1, 3, metadata=dict(tag))
    rels = _edges(_graph(a, b))
    sim = [r for r in rels.values() if r.type.name == "SEMANTICALLY_SIMILAR_TO"]
    assert sim
    assert all(r.metadata["reason"] == "family_tag_no_key" for r in sim)
    assert all(r.confidence == 0.65 for r in sim)


# ---------------------------------------------------------------------------
# RUL-04: quarantine guards on pass-1 (edge_hints source AND target)
# ---------------------------------------------------------------------------


def test_edge_hint_quarantined_source_emits_nothing():
    src = _ent(
        EntityType.FUNCTION, "h", "a/h.py", 1, 2,
        metadata={
            "bsg.noise": True,
            "bsg.edge_hints": [{"type": "TESTED_BY", "target_entity_id": "t1"}],
        },
    )
    tgt = _ent(EntityType.CLASS, "Thing", "a/x.py", 1, 5, id_override="t1")
    assert not _edges(_graph(src, tgt))


def test_edge_hint_to_unresolved_target_emits_nothing():
    src = _ent(
        EntityType.FUNCTION, "h", "a/h.py", 1, 2,
        metadata={
            "bsg.edge_hints": [
                {"type": "TESTED_BY", "target_entity_id": "unresolved:a/x.py::ghost"}
            ]
        },
    )
    ghost = _ent(
        EntityType.EXTERNAL_SYMBOL, "ghost", "a/x.py", 1, 1,
        id_override="unresolved:a/x.py::ghost",
    )
    assert not _edges(_graph(src, ghost))


# ---------------------------------------------------------------------------
# RUL-05: .test/.spec anchored to a full dot-segment
# ---------------------------------------------------------------------------


def test_testdata_and_specular_not_test_artifacts():
    """`foo.testdata` / `a.specular` contain '.test'/'.spec' as substrings but
    are not test files — they must not mint TESTED_BY onto `foo`/`a`."""
    fake_test = _ent(
        EntityType.FUNCTION, "helper", "pkg/foo.testdata.py", 1, 3
    )
    target = _ent(EntityType.FUNCTION, "foo", "pkg/foo.py", 1, 3)
    rels = _edges(_graph(fake_test, target))
    assert not any(r.type.name == "TESTED_BY" for r in rels.values())

    fake_spec = _ent(EntityType.FUNCTION, "helper2", "pkg/a.specular.py", 1, 3)
    target2 = _ent(EntityType.FUNCTION, "a", "pkg/a.py", 1, 3)
    rels2 = _edges(_graph(fake_spec, target2))
    assert not any(r.type.name == "TESTED_BY" for r in rels2.values())


def test_true_test_and_spec_markers_still_match():
    """Anchored forms still classify: `foo.test` stem suffix and
    `foo.test.util` infix both yield base `foo`."""
    real = _ent(EntityType.FUNCTION, "helper", "pkg/foo.test.py", 1, 3)
    target = _ent(EntityType.FUNCTION, "foo", "pkg/foo.py", 1, 3)
    rels = _edges(_graph(real, target))
    assert any(
        r.type.name == "TESTED_BY" and r.target_id == target.id
        for r in rels.values()
    )
