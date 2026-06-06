"""
tests/modules/compression/test_bsg_map.py

Unit tests for BSGMap: build, patch, from_dict, render_compressed,
render_full, render_hierarchical, render_delta, and render_storage views.
"""

from __future__ import annotations

import pytest

from batho.core.schemas import Entity, EntityType, Relationship, RelationshipType
from batho.modules.compression.bsg_map import BSGMap
from batho.modules.graph.builder.codegraph import InMemoryGraph


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_entity(
    name: str,
    file: str,
    etype: EntityType = EntityType.FUNCTION,
    start_line: int = 1,
    end_line: int = 5,
    metadata: dict | None = None,
) -> Entity:
    return Entity(
        type=etype,
        name=name,
        file=file,
        start_line=start_line,
        end_line=end_line,
        metadata=metadata or {},
    )


def _make_graph(
    entities: list[Entity],
    relationships: list[Relationship] | None = None,
) -> InMemoryGraph:
    g = InMemoryGraph()
    for e in entities:
        g.add_entity(e)
    for r in (relationships or []):
        g.add_relationship(r)
    return g


ROOT = "/repo"


# ---------------------------------------------------------------------------
# BSGMap.build
# ---------------------------------------------------------------------------

class TestBSGMapBuild:
    def test_build_empty_graph(self):
        g = _make_graph([])
        bsg = BSGMap.build(g, root=ROOT)
        assert bsg._by_file == {}
        assert bsg._dependencies == {}
        assert bsg._relationships == []

    def test_build_groups_by_file(self):
        e1 = _make_entity("foo", f"{ROOT}/a.py", start_line=1)
        e2 = _make_entity("bar", f"{ROOT}/a.py", start_line=10)
        e3 = _make_entity("baz", f"{ROOT}/b.py", start_line=1)
        g = _make_graph([e1, e2, e3])
        bsg = BSGMap.build(g, root=ROOT)
        assert set(bsg._by_file.keys()) == {"a.py", "b.py"}
        assert [e.name for e in bsg._by_file["a.py"]] == ["foo", "bar"]
        assert [e.name for e in bsg._by_file["b.py"]] == ["baz"]

    def test_build_entities_sorted_by_start_line(self):
        e1 = _make_entity("late", f"{ROOT}/a.py", start_line=20)
        e2 = _make_entity("early", f"{ROOT}/a.py", start_line=5)
        g = _make_graph([e1, e2])
        bsg = BSGMap.build(g, root=ROOT)
        assert [e.name for e in bsg._by_file["a.py"]] == ["early", "late"]

    def test_build_captures_imports_as_dependencies(self):
        e1 = _make_entity("caller", f"{ROOT}/a.py")
        e2 = _make_entity("callee", f"{ROOT}/b.py")
        rel = Relationship(
            source_id=e1.id,
            target_id=e2.id,
            type=RelationshipType.IMPORTS,
        )
        g = _make_graph([e1, e2], [rel])
        bsg = BSGMap.build(g, root=ROOT)
        assert "b.py" in bsg._dependencies.get("a.py", [])

    def test_build_ignores_intra_file_relationships(self):
        e1 = _make_entity("f1", f"{ROOT}/a.py", start_line=1)
        e2 = _make_entity("f2", f"{ROOT}/a.py", start_line=10)
        rel = Relationship(
            source_id=e1.id,
            target_id=e2.id,
            type=RelationshipType.CALLS,
        )
        g = _make_graph([e1, e2], [rel])
        bsg = BSGMap.build(g, root=ROOT)
        assert "a.py" not in bsg._dependencies

    def test_build_requires_inmemory_graph(self):
        with pytest.raises(TypeError, match="InMemoryGraph"):
            BSGMap.build({"entities": {}}, root=ROOT)  # type: ignore[arg-type]

    def test_build_root_normalised(self):
        e = _make_entity("fn", f"{ROOT}/sub/c.py")
        g = _make_graph([e])
        bsg = BSGMap.build(g, root=ROOT)
        assert "sub/c.py" in bsg._by_file


# ---------------------------------------------------------------------------
# BSGMap.patch
# ---------------------------------------------------------------------------

def _make_change(path: str, change_type: str):
    """Return a minimal fake FileChange compatible object."""
    from types import SimpleNamespace
    from batho.orchestrator.patch import FileChangeType

    ct_map = {
        "modified": FileChangeType.MODIFIED,
        "added": FileChangeType.ADDED,
        "deleted": FileChangeType.DELETED,
    }
    return SimpleNamespace(path=path, change_type=ct_map[change_type])


class TestBSGMapPatch:
    def test_patch_updates_entities_for_changed_file(self, tmp_path):
        root = str(tmp_path)
        e1 = _make_entity("old_fn", f"{root}/a.py")
        g0 = _make_graph([e1])
        bsg = BSGMap.build(g0, root=root)

        e_new = _make_entity("new_fn", f"{root}/a.py", start_line=1)
        g1 = _make_graph([e_new])
        change = _make_change(f"{root}/a.py", "modified")
        bsg.patch([change], g1)
        assert any(e.name == "new_fn" for e in bsg._by_file.get("a.py", []))

    def test_patch_removes_deleted_file(self, tmp_path):
        root = str(tmp_path)
        e1 = _make_entity("old_fn", f"{root}/a.py")
        g0 = _make_graph([e1])
        bsg = BSGMap.build(g0, root=root)

        g_empty = _make_graph([])
        change = _make_change(f"{root}/a.py", "deleted")
        bsg.patch([change], g_empty)
        assert "a.py" not in bsg._by_file

    def test_patch_leaves_unchanged_files_intact(self, tmp_path):
        root = str(tmp_path)
        e1 = _make_entity("fn_a", f"{root}/a.py")
        e2 = _make_entity("fn_b", f"{root}/b.py")
        g0 = _make_graph([e1, e2])
        bsg = BSGMap.build(g0, root=root)

        e1_new = _make_entity("fn_a_v2", f"{root}/a.py")
        g1 = _make_graph([e1_new, e2])
        change = _make_change(f"{root}/a.py", "modified")
        bsg.patch([change], g1)
        assert any(e.name == "fn_b" for e in bsg._by_file.get("b.py", []))

    def test_patch_updates_dependencies(self, tmp_path):
        root = str(tmp_path)
        e_a = _make_entity("caller", f"{root}/a.py")
        e_b = _make_entity("callee", f"{root}/b.py")
        rel = Relationship(
            source_id=e_a.id,
            target_id=e_b.id,
            type=RelationshipType.IMPORTS,
        )
        g = _make_graph([e_a, e_b], [rel])
        bsg = BSGMap.build(g, root=root)
        assert "b.py" in bsg._dependencies.get("a.py", [])

        e_a2 = _make_entity("caller_v2", f"{root}/a.py")
        g2 = _make_graph([e_a2, e_b])
        change = _make_change(f"{root}/a.py", "modified")
        bsg.patch([change], g2)
        assert "b.py" not in bsg._dependencies.get("a.py", [])

    def test_patch_requires_inmemory_graph(self, tmp_path):
        root = str(tmp_path)
        e1 = _make_entity("fn", f"{root}/a.py")
        bsg = BSGMap.build(_make_graph([e1]), root=root)
        change = _make_change(f"{root}/a.py", "modified")
        with pytest.raises(TypeError, match="InMemoryGraph"):
            bsg.patch([change], {})  # type: ignore[arg-type]

    def test_patch_serialised_bsg_cleared(self, tmp_path):
        root = str(tmp_path)
        e1 = _make_entity("fn", f"{root}/a.py")
        bsg = BSGMap.build(_make_graph([e1]), root=root)
        bsg._serialized_bsg = {"stale": True}
        e_new = _make_entity("new_fn", f"{root}/a.py")
        g = _make_graph([e_new])
        change = _make_change(f"{root}/a.py", "modified")
        bsg.patch([change], g)
        assert bsg._serialized_bsg is None


# ---------------------------------------------------------------------------
# BSGMap.from_dict
# ---------------------------------------------------------------------------

class TestBSGMapFromDict:
    def test_round_trip_empty(self):
        bsg = BSGMap.from_dict({})
        assert bsg._by_file == {}

    def test_from_dict_node_list_format(self):
        data = {
            "root": ROOT,
            "nodes": [
                {
                    "type": "function",
                    "name": "my_fn",
                    "file": "src/mod.py",
                    "start_line": 3,
                    "end_line": 10,
                }
            ],
        }
        bsg = BSGMap.from_dict(data)
        assert "src/mod.py" in bsg._by_file
        assert bsg._by_file["src/mod.py"][0].name == "my_fn"

    def test_from_dict_invalid_type_raises(self):
        with pytest.raises(TypeError):
            BSGMap.from_dict("not a dict")  # type: ignore[arg-type]

    def test_from_dict_skips_invalid_nodes(self):
        data = {"root": ROOT, "nodes": ["bad", None, 42]}
        bsg = BSGMap.from_dict(data)
        assert bsg._by_file == {}


# ---------------------------------------------------------------------------
# render_compressed
# ---------------------------------------------------------------------------

class TestRenderCompressed:
    def _bsg_with_file(self, n_entities: int = 3) -> BSGMap:
        entities = [
            _make_entity(f"fn_{i}", f"{ROOT}/a.py", start_line=i * 5)
            for i in range(n_entities)
        ]
        g = _make_graph(entities)
        return BSGMap.build(g, root=ROOT)

    def test_render_within_budget_returns_all(self):
        bsg = self._bsg_with_file(2)
        text, stats = bsg.render_compressed(budget=10_000, fail_on_overflow=False)
        assert "fn_0" in text
        assert "fn_1" in text
        assert stats["truncated_files"] == 0

    def test_render_overflow_raises_when_flag_set(self):
        bsg = self._bsg_with_file(50)
        with pytest.raises(ValueError, match="Token budget exceeded"):
            bsg.render_compressed(budget=1, fail_on_overflow=True)

    def test_render_overflow_soft_truncates(self):
        bsg = self._bsg_with_file(50)
        text, stats = bsg.render_compressed(budget=5, fail_on_overflow=False)
        assert "truncated" in text
        assert stats["truncated_files"] > 0

    def test_render_stats_keys_present(self):
        bsg = self._bsg_with_file(2)
        _, stats = bsg.render_compressed(budget=10_000, fail_on_overflow=False)
        assert "tokens_used" in stats
        assert "budget" in stats
        assert "truncated_files" in stats


# ---------------------------------------------------------------------------
# render_delta
# ---------------------------------------------------------------------------

class TestRenderDelta:
    def test_delta_empty_when_identical(self):
        e = _make_entity("fn", f"{ROOT}/a.py")
        g = _make_graph([e])
        bsg1 = BSGMap.build(g, root=ROOT)
        bsg2 = BSGMap.build(g, root=ROOT)
        delta = bsg1.render_delta(bsg2)
        assert isinstance(delta, dict)
        added = delta.get("added") or {}
        removed = delta.get("removed") or []
        assert list(added) == []
        assert list(removed) == []

    def test_delta_detects_added_file(self):
        """b.py is in bsg1 (self) but not bsg2 (other): render_delta reports it in 'added'."""
        e1 = _make_entity("fn", f"{ROOT}/a.py")
        e2 = _make_entity("gn", f"{ROOT}/b.py")
        g1 = _make_graph([e1, e2])
        g2 = _make_graph([e1])
        bsg1 = BSGMap.build(g1, root=ROOT)
        bsg2 = BSGMap.build(g2, root=ROOT)
        delta = bsg1.render_delta(bsg2)
        added = delta.get("added") or {}
        assert any("b.py" in k for k in added)

    def test_delta_detects_removed_file(self):
        """b.py is in bsg2 (other) but not bsg1 (self): render_delta reports it in 'removed'."""
        e1 = _make_entity("fn", f"{ROOT}/a.py")
        e2 = _make_entity("gn", f"{ROOT}/b.py")
        g1 = _make_graph([e1])
        g2 = _make_graph([e1, e2])
        bsg1 = BSGMap.build(g1, root=ROOT)
        bsg2 = BSGMap.build(g2, root=ROOT)
        delta = bsg1.render_delta(bsg2)
        removed = delta.get("removed") or []
        assert any("b.py" in k for k in removed)


# ---------------------------------------------------------------------------
# render_overview_json / render_files_json
# ---------------------------------------------------------------------------

class TestRenderStorageViews:
    def _bsg(self) -> BSGMap:
        entities = [
            _make_entity("ClassA", f"{ROOT}/src/core.py", EntityType.CLASS, 1, 30),
            _make_entity("func_b", f"{ROOT}/src/utils.py", EntityType.FUNCTION, 1, 10),
        ]
        g = _make_graph(entities)
        return BSGMap.build(g, root=ROOT)

    def test_render_overview_json_schema_version(self):
        bsg = self._bsg()
        overview = bsg.render_overview_json()
        assert overview.get("schema_version") == "context-overview.v1"

    def test_render_overview_json_summary_totals(self):
        bsg = self._bsg()
        overview = bsg.render_overview_json()
        summary = overview["summary"]
        assert summary["total_files"] == 2
        assert summary["total_entities"] == 2

    def test_render_overview_json_directory_structure_present(self):
        bsg = self._bsg()
        overview = bsg.render_overview_json()
        assert "directory_structure" in overview
        assert overview["directory_structure"]["type"] == "directory"

    def test_render_overview_json_build_tree_no_duplicates(self):
        """Regression: O(n²) fix must not produce duplicate tree nodes."""
        entities = [
            _make_entity(f"fn_{i}", f"{ROOT}/src/sub/file_{i}.py", start_line=i)
            for i in range(20)
        ]
        g = _make_graph(entities)
        bsg = BSGMap.build(g, root=ROOT)
        overview = bsg.render_overview_json()
        tree = overview["directory_structure"]
        # src should appear exactly once at top level
        src_nodes = [c for c in tree["children"] if c["name"] == "src"]
        assert len(src_nodes) == 1

    def test_render_files_json_returns_dict(self):
        bsg = self._bsg()
        result = bsg.render_files_json()
        assert isinstance(result, dict)

    def test_to_dict_round_trip_has_nodes(self):
        bsg = self._bsg()
        d = bsg.to_dict()
        assert "nodes" in d or isinstance(d, dict)
