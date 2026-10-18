"""Tests for threshold-aware community detection."""

from unittest.mock import MagicMock

from batho.core.schemas import RelationshipType
from batho.modules.graph.community import _sample_graph_by_files, detect_communities


class _SimpleEntity:
    def __init__(self, eid: str, file: str, name: str = ""):
        self.id = eid
        self.file = file
        self.name = name or eid


class _SimpleRel:
    def __init__(self, source_id: str, target_id: str, rel_type=None):
        self.source_id = source_id
        self.target_id = target_id
        self.type = rel_type or RelationshipType.CALLS


def _make_graph(files: dict[str, list[str]], rels: list[tuple]):
    """Build a minimal graph-like object for community tests.

    rels items are (src, tgt) or (src, tgt, RelationshipType).
    """
    graph = MagicMock()
    entities = {}
    for file_path, eids in files.items():
        for eid in eids:
            entities[eid] = _SimpleEntity(eid, file_path)
    graph.entities = entities
    graph.relationships = [
        _SimpleRel(*tuple(r)) for r in rels
    ]
    graph._rels_by_endpoint = {}
    for rel in graph.relationships:
        graph._rels_by_endpoint.setdefault(rel.source_id, []).append(rel)
        graph._rels_by_endpoint.setdefault(rel.target_id, []).append(rel)
    graph.degree_by_endpoint = lambda eid: len(graph._rels_by_endpoint.get(eid, []))
    return graph


def test_sample_graph_by_files_keeps_whole_files_under_threshold():
    """Whole-file sampling keeps files intact until the threshold is crossed."""
    files = {
        "a.py": ["a1", "a2", "a3"],
        "b.py": ["b1", "b2"],
        "c.py": ["c1"],
    }
    rels = [("a1", "b1"), ("b2", "c1")]
    graph = _make_graph(files, rels)

    kept_ids, filtered_rels = _sample_graph_by_files(graph, 5)

    # a.py (3) + b.py (2) = 5 entities exactly
    assert kept_ids == {"a1", "a2", "a3", "b1", "b2"}
    assert len(filtered_rels) == 1
    assert filtered_rels[0].source_id == "a1"
    assert filtered_rels[0].target_id == "b1"


def test_detect_communities_disabled_by_config():
    """When enabled is False, detect_communities returns an empty list."""
    graph = _make_graph({"a.py": ["a1"]}, [])
    result = detect_communities(graph, {"enabled": False})
    assert result == []


def test_detect_communities_skips_above_threshold():
    """Graphs with more entities than skip_threshold should not run community detection."""
    files = {f"f{i}.py": [f"e{i}"] for i in range(10)}
    graph = _make_graph(files, [])
    result = detect_communities(graph, {"skip_threshold": 5, "sample_threshold": 2})
    assert result == []


def test_detect_communities_samples_between_thresholds(monkeypatch):
    """Sampling is applied when entity count is between sample and skip thresholds."""
    files = {
        "big.py": ["b1", "b2", "b3", "b4"],
        "small.py": ["s1"],
    }
    rels = [("b1", "s1")]
    graph = _make_graph(files, rels)

    called = {"sampled": False}

    def fake_sample(g, threshold):
        called["sampled"] = True
        # Return only big.py entities/rels
        kept = {"b1", "b2", "b3", "b4"}
        filtered = [r for r in g.relationships if r.source_id in kept and r.target_id in kept]
        return kept, filtered

    monkeypatch.setattr("batho.modules.graph.community._sample_graph_by_files", fake_sample)

    # Mock out networkx so the test does not depend on optional deps
    monkeypatch.setitem(__import__("sys").modules, "networkx", MagicMock())

    detect_communities(graph, {"skip_threshold": 10, "sample_threshold": 2})
    assert called["sampled"]


def test_sampled_path_scans_relationships_once():
    """ff5104f331c0: when sampling kicks in, graph.relationships must be
    iterated exactly once — inside _sample_graph_by_files. The pre-fix code
    built a full `whitelisted` list first and then discarded it."""
    files = {f"f{i}.py": [f"e{i}a", f"e{i}b"] for i in range(3)}  # 6 entities
    rels = [("e0a", "e0b"), ("e1a", "e1b")]
    graph = _make_graph(files, rels)

    class _CountingRels(list):
        iter_count = 0

        def __iter__(self):
            self.iter_count += 1
            return super().__iter__()

    graph.relationships = _CountingRels(graph.relationships)

    detect_communities(graph, {"skip_threshold": 100, "sample_threshold": 3})

    assert graph.relationships.iter_count == 1


def test_sampled_path_drops_stub_edges():
    """The sampled branch must apply the same `unresolved:` stub filter as
    the non-sampled whitelist (kept_ids &= entity_ids_all + endpoint check)."""
    files = {"a.py": ["a1", "a2", "unresolved:x"], "b.py": ["b1", "b2"]}
    rels = [("a1", "unresolved:x"), ("a1", "a2")]
    graph = _make_graph(files, rels)
    communities = detect_communities(
        graph, {"skip_threshold": 100, "sample_threshold": 3}
    )
    all_members = {e for c in communities for e in c.member_entity_ids}
    assert "unresolved:x" not in all_members
    assert all_members == {"a1", "a2"}


def test_annotation_edges_excluded_from_clustering_input():
    """RATIONALE_FOR (T5) must not shape communities — a graph linked only by
    an annotation edge produces no communities at all."""
    files = {"a.py": ["a1", "a2"], "b.py": ["b1", "b2"]}
    # a1-a2 and b1-b2 linked structurally; a1-b1 only via RATIONALE_FOR.
    rels = [
        ("a1", "a2", RelationshipType.CALLS),
        ("b1", "b2", RelationshipType.CALLS),
        ("a1", "b1", RelationshipType.RATIONALE_FOR),
    ]
    graph = _make_graph(files, rels)
    communities = detect_communities(graph, {"skip_threshold": 1000, "sample_threshold": 1000})
    for comm in communities:
        members = set(comm.member_entity_ids)
        # the annotation bridge must not merge the two structural pairs
        assert not ({"a1", "a2"} & members and {"b1", "b2"} & members)


def test_annotation_only_graph_yields_no_communities():
    files = {"a.py": ["a1"], "b.py": ["b1"]}
    graph = _make_graph(files, [("a1", "b1", RelationshipType.RATIONALE_FOR)])
    assert detect_communities(graph, {}) == []


def test_sample_graph_drops_annotation_edges():
    files = {"a.py": ["a1"], "b.py": ["b1"]}
    rels = [
        ("a1", "b1", RelationshipType.RATIONALE_FOR),
        ("a1", "b1", RelationshipType.CALLS),
    ]
    graph = _make_graph(files, rels)
    kept_ids, filtered = _sample_graph_by_files(graph, 10)
    assert kept_ids == {"a1", "b1"}
    assert [r.type for r in filtered] == [RelationshipType.CALLS]


# ---------------------------------------------------------------------------
# T4: weighted input, isolate/super-hub policy, split/merge, connectivity
# ---------------------------------------------------------------------------


def test_zero_weight_edges_excluded_from_input():
    """CONTAINS (default weight 0) must not create clustering edges."""
    files = {"a.py": ["a1"], "b.py": ["b1"]}
    graph = _make_graph(files, [("a1", "b1", RelationshipType.CONTAINS)])
    assert detect_communities(graph, {}) == []


def test_weight_override_excludes_kind():
    """Config edge_weights can zero out an otherwise-structural kind."""
    files = {"a.py": ["a1"], "b.py": ["b1"]}
    graph = _make_graph(files, [("a1", "b1", RelationshipType.CALLS)])
    cfg = {"edge_weights": {"CALLS": 0.0}}
    assert detect_communities(graph, cfg) == []


def test_isolate_attached_to_file_community():
    """A degree-0 entity joins its containing file's majority community."""
    files = {"x.py": ["a1", "a2", "i1"], "y.py": ["b1", "b2"]}
    rels = [
        ("a1", "a2", RelationshipType.CALLS),
        ("b1", "b2", RelationshipType.CALLS),
    ]
    graph = _make_graph(files, rels)
    communities = detect_communities(graph, {"min_community_entities": 2})
    members = [set(c.member_entity_ids) for c in communities]
    assert any("i1" in m for m in members)
    # i1 attaches to the community that owns the rest of x.py
    assert any({"a1", "a2", "i1"} <= m for m in members)


def test_unattached_isolate_stays_out():
    """An isolate in a file with no clustered members stays unattached."""
    files = {"x.py": ["a1", "a2"], "solo.py": ["i9"]}
    graph = _make_graph(files, [("a1", "a2", RelationshipType.CALLS)])
    communities = detect_communities(graph, {"min_community_entities": 2})
    all_members = {e for c in communities for e in c.member_entity_ids}
    assert "i9" not in all_members


def test_superhub_dropped_and_reattached():
    """P50 cutoff drops the 4-degree hub before detection; it reattaches to
    the neighbor with max shared weight without merging the two clusters."""
    files = {"x.py": ["a1", "a2"], "y.py": ["b1", "b2"], "hub.py": ["hub"]}
    rels = [
        ("a1", "a2", RelationshipType.CALLS),
        ("b1", "b2", RelationshipType.CALLS),
        ("hub", "a1", RelationshipType.CALLS),
        ("hub", "a2", RelationshipType.CALLS),
        ("hub", "b1", RelationshipType.CALLS),
        ("hub", "b2", RelationshipType.CALLS),
    ]
    graph = _make_graph(files, rels)
    communities = detect_communities(
        graph,
        {"min_community_entities": 2, "superhub_degree_percentile": 50},
    )
    members = [set(c.member_entity_ids) for c in communities]
    assert len(members) == 2
    # hub reattaches to exactly one side — stronger shared weight wins
    assert sum("hub" in m for m in members) == 1


def test_small_community_merges_into_strongest_neighbor():
    files = {"x.py": ["a1", "a2"], "y.py": ["b1", "b2", "b3"]}
    rels = [
        ("a1", "a2", RelationshipType.CALLS),
        ("b1", "b2", RelationshipType.CALLS),
        ("b2", "b3", RelationshipType.CALLS),
        ("a1", "b1", RelationshipType.CALLS),
    ]
    graph = _make_graph(files, rels)
    communities = detect_communities(graph, {"min_community_entities": 3})
    merged = [set(c.member_entity_ids) for c in communities]
    # the 2-node community merges into the 3-node one via a1-b1
    assert len(merged) == 1
    assert merged[0] == {"a1", "a2", "b1", "b2", "b3"}


def test_unmergeable_small_community_flagged_singleton():
    files = {"x.py": ["a1", "a2"], "y.py": ["b1", "b2", "b3"]}
    rels = [
        ("a1", "a2", RelationshipType.CALLS),
        ("b1", "b2", RelationshipType.CALLS),
        ("b2", "b3", RelationshipType.CALLS),
    ]
    graph = _make_graph(files, rels)
    communities = detect_communities(graph, {"min_community_entities": 3})
    singletons = [c for c in communities if c.is_singleton]
    assert len(singletons) == 1
    assert set(singletons[0].member_entity_ids) == {"a1", "a2"}


def _naive_merge_reference(
    split_sets: list[set[str]], pair_weight: dict[tuple[str, str], float],
    min_size: int,
) -> list[set[str]]:
    """Pre-fix O(S×F×E) merge semantics, kept as the equivalence oracle for
    the indexed implementation (issue bed09fd99815)."""

    def shared(a: set[str], b: set[str]) -> float:
        return sum(
            w
            for (x, y), w in pair_weight.items()
            if (x in a and y in b) or (x in b and y in a)
        )

    large = [c for c in split_sets if len(c) >= min_size]
    small = sorted((c for c in split_sets if len(c) < min_size), key=len)
    final = [set(c) for c in large]
    singles: list[set[str]] = []
    for comm in small:
        best_idx, best_w = -1, 0.0
        for i, target in enumerate(final):
            w = shared(comm, target)
            if w > best_w:
                best_w, best_idx = w, i
        if best_idx >= 0:
            final[best_idx] |= comm
        else:
            singles.append(comm)
    final.extend(singles)
    return final


def test_merge_matches_naive_shared_weight_reference(monkeypatch):
    """The indexed merge must produce identical communities to the naive
    pairwise scan, including smallest-first ordering and merge chaining."""
    import networkx as nx

    files = {
        "x.py": ["x1", "x2", "x3"],
        "y.py": ["y1", "y2", "y3"],
        "p.py": ["p1", "p2"],
        "q.py": ["q1"],
        "r.py": ["r1", "r2"],
    }
    rels = [
        ("x1", "x2", RelationshipType.CALLS),
        ("x2", "x3", RelationshipType.CALLS),
        ("y1", "y2", RelationshipType.CALLS),
        ("y2", "y3", RelationshipType.CALLS),
        ("p1", "p2", RelationshipType.CALLS),
        ("p1", "x1", RelationshipType.CALLS),  # P→X weight 3
        ("p1", "y1", RelationshipType.READS),  # P→Y weight 1 → P merges into X
        ("q1", "r1", RelationshipType.CALLS),  # q only links to small r
        ("r1", "r2", RelationshipType.CALLS),
        ("r1", "y2", RelationshipType.READS),  # R→Y weight 1 → R merges into Y
    ]
    graph = _make_graph(files, rels)

    partition = [
        {"x1", "x2", "x3"},
        {"y1", "y2", "y3"},
        {"p1", "p2"},
        {"q1"},
        {"r1", "r2"},
    ]
    monkeypatch.setattr(
        nx.community,
        "greedy_modularity_communities",
        lambda g, weight=None: partition,
    )

    cfg = {
        "min_community_entities": 3,
        "superhub_degree_percentile": 100,
        "max_community_fraction": 1.0,
    }
    communities = detect_communities(graph, cfg)

    # Rebuild pair_weight exactly as detect_communities does (default weights,
    # confidence 1.0) and run the oracle over the same partition.
    weights = {"CALLS": 3.0, "READS": 1.0, "WRITES": 1.0, "IMPORTS": 2.0,
               "INHERITS": 3.0, "IMPLEMENTS": 3.0, "CONTAINS": 0.0}
    pair_weight: dict[tuple[str, str], float] = {}
    for rel in graph.relationships:
        kind_w = weights.get(rel.type.name, 0.0)
        if kind_w <= 0 or rel.source_id == rel.target_id:
            continue
        key = (rel.source_id, rel.target_id)
        if key[0] > key[1]:
            key = (key[1], key[0])
        pair_weight[key] = pair_weight.get(key, 0.0) + kind_w
    expected = _naive_merge_reference(partition, pair_weight, 3)

    got = sorted(
        frozenset(c.member_entity_ids) for c in communities
    )
    want = sorted(frozenset(s) for s in expected)
    assert got == want
    # q1 is unmergeable (its only neighbor r1 is small and processed later)
    # → flagged singleton, matching the reference ordering semantics.
    singles = [c for c in communities if c.is_singleton]
    assert [sorted(c.member_entity_ids) for c in singles] == [["q1"]]


def test_merge_pass_scales_with_edges_not_pairs():
    """Perf smoke for bed09fd99815: many small communities × many targets
    must complete promptly. The pre-fix scan was O(S × F × E); at this size
    that is ~10⁸ membership ops — the indexed pass is O(Σ degree)."""
    import time

    files: dict[str, list[str]] = {}
    rels: list[tuple] = []
    # 40 K5 cliques as merge targets
    for i in range(40):
        ids = [f"g{i}_{j}" for j in range(5)]
        files[f"big{i}.py"] = ids
        rels += [
            (ids[j], ids[k], RelationshipType.CALLS)
            for j in range(5)
            for k in range(j + 1, 5)
        ]
    # 300 small pairs, each weakly linked to one clique
    for i in range(300):
        a, b = f"s{i}a", f"s{i}b"
        files[f"small{i}.py"] = [a, b]
        rels.append((a, b, RelationshipType.CALLS))
        rels.append((a, f"g{i % 40}_0", RelationshipType.CALLS))

    graph = _make_graph(files, rels)
    start = time.monotonic()
    communities = detect_communities(graph, {"min_community_entities": 3})
    elapsed = time.monotonic() - start
    assert communities
    assert elapsed < 20.0


def test_detection_deterministic_same_input():
    files = {
        "x.py": ["a1", "a2", "a3"],
        "y.py": ["b1", "b2", "b3"],
    }
    rels = [
        ("a1", "a2", RelationshipType.CALLS),
        ("a2", "a3", RelationshipType.CALLS),
        ("b1", "b2", RelationshipType.CALLS),
        ("b2", "b3", RelationshipType.CALLS),
        ("a3", "b1", RelationshipType.READS),
    ]
    g1 = _make_graph(files, rels)
    g2 = _make_graph(files, rels)
    c1 = detect_communities(g1, {"min_community_entities": 2})
    c2 = detect_communities(g2, {"min_community_entities": 2})
    sig1 = [(sorted(c.member_entity_ids), c.heuristic_label) for c in c1]
    sig2 = [(sorted(c.member_entity_ids), c.heuristic_label) for c in c2]
    assert sig1 == sig2


def test_chained_superhub_follows_reattached_hub():
    """7bd9415b4301: member_of must record best_idx, not the stale loop var.

    h1 reattaches to comm A (three CALLS edges). h2's only *attached* path is
    through h1 (weighted 6 via edge multiplicity), so h2 must land in the same
    community as h1 — not wherever h1's last-iterated neighbor happens to sit.
    """
    files = {
        "a.py": ["a1", "a2", "a3"],
        "b.py": ["b1", "b2"],
        "x.py": ["x1", "x2"],
        "y.py": ["y1"],
        "z.py": ["z1"],
        "h1.py": ["h1"],
        "h2.py": ["h2"],
    }
    rels = [
        ("a1", "a2", RelationshipType.CALLS),
        ("a2", "a3", RelationshipType.CALLS),
        ("b1", "b2", RelationshipType.CALLS),
        ("x1", "x2", RelationshipType.CALLS),
        ("h1", "a1", RelationshipType.CALLS),
        ("h1", "a2", RelationshipType.CALLS),
        ("h1", "a3", RelationshipType.CALLS),
        ("h2", "h1", RelationshipType.CALLS),
        ("h2", "h1", RelationshipType.CALLS),  # multiplicity: weight 6 via h1
        ("h2", "x1", RelationshipType.CALLS),
        ("h2", "y1", RelationshipType.CALLS),
        ("h2", "z1", RelationshipType.CALLS),
        # h1's weakest tie is appended last so the stale loop var is idx(B)
        ("h1", "b1", RelationshipType.READS),
    ]
    graph = _make_graph(files, rels)
    communities = detect_communities(
        graph, {"min_community_entities": 2, "superhub_degree_percentile": 73}
    )
    members = [set(c.member_entity_ids) for c in communities]
    h1_comm = next(m for m in members if "h1" in m)
    assert "h2" in h1_comm  # follows its reattached hub, not a stale index
    assert {"a1", "a2", "a3", "h1", "h2"} <= h1_comm


def test_isolate_attaches_to_singleton_file_community():
    """59960875b22f: singletons are communities too — an isolate whose
    file-mates form an unmergeable singleton must join it, not drop."""
    files = {
        "s.py": ["s1", "s2", "i1"],   # i1 has no edges (isolate)
        "x.py": ["x1", "x2", "x3"],
    }
    rels = [
        ("s1", "s2", RelationshipType.CALLS),
        ("x1", "x2", RelationshipType.CALLS),
        ("x2", "x3", RelationshipType.CALLS),
    ]
    graph = _make_graph(files, rels)
    communities = detect_communities(graph, {"min_community_entities": 3})
    members = [set(c.member_entity_ids) for c in communities]
    assert {"s1", "s2", "i1"} in members


class TestEdgeConfidenceSemantics:
    """COM-07: an explicit confidence=0.0 edge carries zero clustering
    weight — the falsy-or default promoted it to 1.0, so a ghost bridge
    could drag an isolate into a community it doesn't belong to."""

    def _graph(self, conf):
        from batho.modules.graph import InMemoryGraph
        from batho.core.schemas import Entity, EntityType, Relationship, RelationshipType

        g = InMemoryGraph()
        # tight trio + an isolate (different file — rules out dir-attach)
        # linked only by the conf-param edge
        ents = [
            Entity(type=EntityType.FUNCTION, name=n,
                   file="b.py" if n == "ghost_link" else "a.py",
                   start_line=i, end_line=i + 1)
            for i, n in enumerate(["fa", "fb", "fc", "ghost_link"])
        ]
        for e in ents:
            g.add_entity(e)
        for a, b in ((0, 1), (1, 2), (0, 2)):
            g.add_relationship(Relationship(
                source_id=ents[a].id, target_id=ents[b].id,
                type=RelationshipType.CALLS, file="a.py"))
        g.add_relationship(Relationship(
            source_id=ents[3].id, target_id=ents[0].id,
            type=RelationshipType.CALLS, file="b.py", confidence=conf))
        return g, ents

    def test_zero_confidence_edge_carries_no_weight(self):
        from batho.modules.graph import detect_communities

        g, ents = self._graph(conf=0.0)
        comms = detect_communities(g, {"min_community_entities": 2})
        for c in comms:
            # the isolate must not ride a zero-weight edge into the trio
            if ents[3].id in c.member_entity_ids:
                assert {ents[0].id, ents[1].id, ents[2].id} - set(
                    c.member_entity_ids
                ), "zero-confidence edge attached the isolate to the trio"

    def test_full_confidence_edge_attaches_isolate(self):
        from batho.modules.graph import detect_communities

        g, ents = self._graph(conf=1.0)
        comms = detect_communities(g, {"min_community_entities": 2})
        joined = any(ents[3].id in c.member_entity_ids for c in comms
                     if len(c.member_entity_ids) > 1)
        assert joined, "full-weight edge should attach the isolate"


class TestGenericDirBlocklist:
    """COM-11: `generic_dir_blocklist: []` must mean "no blocklist" — the
    falsy-or silently restored defaults, so `src/` could never label."""

    def _graph(self):
        from batho.modules.graph import InMemoryGraph
        from batho.core.schemas import Entity, EntityType, Relationship, RelationshipType

        g = InMemoryGraph()
        ents = [
            Entity(type=EntityType.FUNCTION, name=f"fn_{i}", file="src/m.py",
                   start_line=i * 3, end_line=i * 3 + 2)
            for i in range(4)
        ]
        for e in ents:
            g.add_entity(e)
        for a, b in zip(ents, ents[1:]):
            g.add_relationship(Relationship(
                source_id=a.id, target_id=b.id,
                type=RelationshipType.CALLS, file="src/m.py"))
        return g

    def test_empty_blocklist_allows_src_label(self):
        from batho.modules.graph import detect_communities

        g = self._graph()
        comms = detect_communities(g, {
            "min_community_entities": 2,
            "generic_dir_blocklist": [],
        })
        labels = [c.heuristic_label for c in comms]
        assert "Src" in labels

    def test_default_blocklist_still_excludes_src(self):
        from batho.modules.graph import detect_communities

        g = self._graph()
        comms = detect_communities(g, {"min_community_entities": 2})
        labels = [c.heuristic_label for c in comms]
        assert "Src" not in labels
