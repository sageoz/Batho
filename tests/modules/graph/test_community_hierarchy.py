"""Tests for T15 hierarchical communities: parent/level persistence + domain tier."""

from unittest.mock import MagicMock

import networkx as nx

from batho.core.schemas import RelationshipType
from batho.modules.graph.community import detect_communities
from batho.mcp.community_summaries import format_community_summary


class _SimpleEntity:
    def __init__(self, eid: str, file: str, name: str = "", metadata=None):
        self.id = eid
        self.file = file
        self.name = name or eid
        self.metadata = metadata or {}


class _SimpleRel:
    def __init__(self, source_id: str, target_id: str, rel_type=None):
        self.source_id = source_id
        self.target_id = target_id
        self.type = rel_type or RelationshipType.CALLS


def _make_graph(files: dict[str, list[str]], rels: list[tuple], metadata=None):
    graph = MagicMock()
    entities = {}
    for file_path, eids in files.items():
        for eid in eids:
            entities[eid] = _SimpleEntity(
                eid, file_path, metadata=(metadata or {}).get(eid)
            )
    graph.entities = entities
    graph.relationships = [_SimpleRel(*tuple(r)) for r in rels]
    graph._rels_by_endpoint = {}
    for rel in graph.relationships:
        graph._rels_by_endpoint.setdefault(rel.source_id, []).append(rel)
        graph._rels_by_endpoint.setdefault(rel.target_id, []).append(rel)
    graph.degree_by_endpoint = lambda eid: len(graph._rels_by_endpoint.get(eid, []))
    return graph


def _forced_split(monkeypatch):
    """Stub greedy_modularity: one giant community first, then a clean 2-way
    split, then each half un-splittable — produces parent+2children exactly."""
    calls = iter([
        [{"a1", "a2", "a3", "a4", "a5", "a6", "b1", "b2", "b3", "b4", "b5", "b6"}],
        [{"a1", "a2", "a3", "a4", "a5", "a6"}, {"b1", "b2", "b3", "b4", "b5", "b6"}],
        [{"a1", "a2", "a3", "a4", "a5", "a6"}],
        [{"b1", "b2", "b3", "b4", "b5", "b6"}],
    ])
    monkeypatch.setattr(
        nx.community,
        "greedy_modularity_communities",
        lambda g, weight="weight": next(calls),
    )


def _dumbbell():
    files = {"auth/x.py": [f"a{i}" for i in range(1, 7)],
             "pay/y.py": [f"b{i}" for i in range(1, 7)]}
    rels = (
        [(f"a{i}", f"a{j}") for i in range(1, 6) for j in range(i + 1, 7)]
        + [(f"b{i}", f"b{j}") for i in range(1, 6) for j in range(i + 1, 7)]
        + [("a1", "b1"), ("a2", "b2")]
    )
    return files, rels


class TestHierarchy:
    def test_split_emits_parent_and_children(self, monkeypatch):
        files, rels = _dumbbell()
        graph = _make_graph(files, rels)
        _forced_split(monkeypatch)
        comms = detect_communities(graph, {
            "enabled": True,
            "min_community_entities": 3,
            "max_community_fraction": 0.1,  # split_cap = 1 → always split
            "superhub_degree_percentile": 100.0,
        })
        assert len(comms) == 3
        parent = next(c for c in comms if c.parent_id is None)
        children = [c for c in comms if c.parent_id == parent.id]
        assert len(children) == 2
        assert parent.level == 0
        assert all(c.level == 1 for c in children)
        assert {e for c in children for e in c.member_entity_ids} <= set(
            parent.member_entity_ids
        )

    def test_no_split_flat_compat(self, monkeypatch):
        """No oversize comm → all rows level 0, parent_id None (old flat list)."""
        files = {"a/x.py": ["a1", "a2", "a3"]}
        rels = [("a1", "a2"), ("a2", "a3")]
        graph = _make_graph(files, rels)
        monkeypatch.setattr(
            nx.community, "greedy_modularity_communities",
            lambda g, weight="weight": [{"a1", "a2", "a3"}],
        )
        comms = detect_communities(graph, {
            "enabled": True, "min_community_entities": 3,
            "max_community_fraction": 0.5,  # split_cap=1 but only 1 part anyway
            "superhub_degree_percentile": 100.0,
        })
        assert len(comms) == 1
        assert comms[0].parent_id is None
        assert comms[0].level == 0

    def test_deterministic_ids(self, monkeypatch):
        files, rels = _dumbbell()
        graph = _make_graph(files, rels)
        sigs = []
        for _ in range(2):
            _forced_split(monkeypatch)
            comms = detect_communities(graph, {
                "enabled": True, "min_community_entities": 3,
                "max_community_fraction": 0.1,
                "superhub_degree_percentile": 100.0,
            })
            sigs.append(tuple(sorted(
                (c.id, c.parent_id, c.level, tuple(c.member_entity_ids))
                for c in comms
            )))
        assert sigs[0] == sigs[1]


class TestDomainGrouping:
    def _domain_graph(self):
        files = {
            "auth/x.py": ["a1", "a2", "a3", "a4"],
            "pay/y.py": ["p1", "p2", "p3", "p4"],
            "misc/z.py": ["u1", "u2"],
        }
        rels = (
            [("a1", "a2"), ("a2", "a3"), ("a3", "a4"), ("a1", "a4")]
            + [("p1", "p2"), ("p2", "p3"), ("p3", "p4"), ("p1", "p4")]
            + [("u1", "u2")]
        )
        metadata = {
            **{f"a{i}": {"bsg.domain": "auth"} for i in range(1, 5)},
            **{f"p{i}": {"bsg.domain": "billing"} for i in range(1, 5)},
        }
        return files, rels, metadata

    def test_domain_tier(self, monkeypatch):
        files, rels, metadata = self._domain_graph()
        graph = _make_graph(files, rels, metadata)
        comms = detect_communities(graph, {
            "enabled": True, "domain_grouping": True,
            "min_community_entities": 3,
            "superhub_degree_percentile": 100.0,
        })
        by_name = {c.name: c for c in comms}
        assert "auth" in by_name and "billing" in by_name
        auth_domain = by_name["auth"]
        assert auth_domain.level == 0 and auth_domain.parent_id is None
        auth_children = [c for c in comms if c.parent_id == auth_domain.id]
        assert auth_children
        assert all(c.level == 1 for c in auth_children)
        assert all(
            e.startswith("a") for c in auth_children for e in c.member_entity_ids
        )
        # untagged file → "(untagged)" domain
        untagged = next(c for c in comms if c.name == "(untagged)")
        assert untagged.level == 0

    def test_no_domain_config_is_flat(self, monkeypatch):
        files, rels, metadata = self._domain_graph()
        graph = _make_graph(files, rels, metadata)
        comms = detect_communities(graph, {
            "enabled": True, "min_community_entities": 3,
            "superhub_degree_percentile": 100.0,
        })
        assert all(c.level == 0 for c in comms)
        assert all(c.parent_id is None for c in comms)
        assert not any(c.name == "auth" for c in comms)


class TestOldBundleCompat:
    def test_summary_defaults_for_missing_columns(self):
        """Rows from a pre-T15 communities.ipc (no parent/level/llm cols)."""
        row = {
            "community_id": 3, "name": "foo", "entity_count": 5,
            "file_count": 2, "top_entities": ["x"], "description": "d",
            "file_paths": ["a/x.py"], "is_singleton": False,
            "heuristic_label": "Foo Label",
        }
        out = format_community_summary(row)
        assert out["parent_id"] is None
        assert out["level"] == 0
        assert out["name"] == "Foo Label"  # heuristic_label fallback

    def test_llm_label_precedence(self):
        row = {
            "community_id": 3, "name": "raw_name", "entity_count": 5,
            "file_count": 2, "top_entities": [], "description": "d",
            "file_paths": [], "is_singleton": False,
            "heuristic_label": "Heuristic", "llm_label": "LLM Name",
        }
        out = format_community_summary(row)
        assert out["name"] == "LLM Name"


class TestEmptyPartitionAndCrossSubtreeMerge:
    """COM-01 + COM-04 regressions."""

    def test_edge_free_domain_group_keeps_members(self, monkeypatch):
        """COM-01: a domain partition with no effective clustering edges
        (CONTAINS-only, weight 0) must still cover its entities — no
        zero-member row, no silently dropped members."""
        files = {
            "docs/x.py": ["d1", "d2", "d3"],
            "auth/y.py": ["a1", "a2", "a3", "a4"],
        }
        rels = [
            # docs group: CONTAINS only → weight 0 → no clusterable edges
            ("d1", "d2", RelationshipType.CONTAINS),
            ("d2", "d3", RelationshipType.CONTAINS),
            # auth group: real coupling
            ("a1", "a2"), ("a2", "a3"), ("a3", "a4"), ("a1", "a4"),
        ]
        metadata = {
            **{f"d{i}": {"bsg.domain": "docs"} for i in range(1, 4)},
            **{f"a{i}": {"bsg.domain": "auth"} for i in range(1, 5)},
        }
        graph = _make_graph(files, rels, metadata)
        comms = detect_communities(graph, {
            "enabled": True, "domain_grouping": True,
            "min_community_entities": 3,
            "superhub_degree_percentile": 100.0,
        })
        assert comms, "no communities emitted"
        assert all(c.member_entity_ids for c in comms), (
            "zero-member row emitted"
        )
        docs = next(c for c in comms if c.name == "docs")
        assert set(docs.member_entity_ids) == {"d1", "d2", "d3"}

    def test_cross_subtree_merge_attributes_to_absorber(self, monkeypatch):
        """COM-04: a small leaf merging into a leaf under a DIFFERENT subtree
        must attribute to the absorber's leaf — pre-fix, set-aliasing let
        whichever node iterated last win, so merged members landed under the
        wrong parent row."""
        a = [f"a{i}" for i in range(1, 7)]
        b = [f"b{i}" for i in range(1, 7)]
        c = ["c1", "c2"]
        files = {"x/f.py": a + b + c}
        rels = (
            [(a[i], a[j]) for i in range(5) for j in range(i + 1, 6)]
            + [(b[i], b[j]) for i in range(5) for j in range(i + 1, 6)]
            + [("c1", "b1"), ("c1", "b2"), ("c2", "b3")]
        )
        graph = _make_graph(files, rels)
        big = set(a + b + c)
        calls = iter([
            [big],
            [set(a + c), set(b)],
            [set(a), set(c)],
            [set(a)],
            [set(b)],
        ])
        monkeypatch.setattr(
            nx.community, "greedy_modularity_communities",
            lambda g, weight="weight": next(calls),
        )
        comms = detect_communities(graph, {
            "enabled": True, "min_community_entities": 3,
            "max_community_fraction": 0.1,  # split_cap = 1 → always split
            "superhub_degree_percentile": 100.0,
        })
        by_id = {cm.id: cm for cm in comms}
        # c's merged into b's leaf — the leaf row carrying them is b's.
        b_leaf = next(
            cm for cm in comms if "b1" in cm.member_entity_ids
        )
        assert "c1" in b_leaf.member_entity_ids
        assert "c2" in b_leaf.member_entity_ids
        # The interior row over the {a,c} subtree must NOT claim c's —
        # they attribute to b's leaf under the other subtree.
        a_leaf = next(
            cm for cm in comms
            if "a1" in cm.member_entity_ids and cm.level == 2
        )
        a_subtree = by_id[a_leaf.parent_id]
        assert set(a_subtree.member_entity_ids) == set(a)
        # Root still covers everyone.
        root = next(cm for cm in comms if cm.parent_id is None)
        assert set(root.member_entity_ids) == big
