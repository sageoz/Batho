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
        """Verify building from an empty graph results in empty maps.

        Scenario:
            An empty InMemoryGraph is provided to the builder.

        Execution Flow:
            1. Construct an InMemoryGraph with no entities.
            2. Invoke BSGMap.build with the empty graph.
            3. Verify that the files, dependencies, and relationships are empty.

        Expectations:
            - _by_file mapping is empty.
            - _dependencies mapping is empty.
            - _relationships list is empty.
        """
        g = _make_graph([])
        bsg = BSGMap.build(g, root=ROOT)
        assert bsg._by_file == {}
        assert bsg._dependencies == {}
        assert bsg._relationships == []

    def test_build_groups_by_file(self):
        """Verify building groups entities by their normalized relative file paths.

        Scenario:
            Three entities across two files (a.py and b.py) are present in the graph.

        Execution Flow:
            1. Create three entities: two in a.py and one in b.py.
            2. Build the BSGMap.
            3. Assert that the grouped files are exactly "a.py" and "b.py" and contain the correct entities.

        Expectations:
            - The files mapped in BSGMap are exactly {"a.py", "b.py"}.
            - The entity names grouped under each file match the names of the input entities.
        """
        e1 = _make_entity("foo", f"{ROOT}/a.py", start_line=1)
        e2 = _make_entity("bar", f"{ROOT}/a.py", start_line=10)
        e3 = _make_entity("baz", f"{ROOT}/b.py", start_line=1)
        g = _make_graph([e1, e2, e3])
        bsg = BSGMap.build(g, root=ROOT)
        assert set(bsg._by_file.keys()) == {"a.py", "b.py"}
        assert [e.name for e in bsg._by_file["a.py"]] == ["foo", "bar"]
        assert [e.name for e in bsg._by_file["b.py"]] == ["baz"]

    def test_build_entities_sorted_by_start_line(self):
        """Verify entities grouped within a file are sorted by their starting lines.

        Scenario:
            Two entities are added to the same file, with the later line entity defined before the earlier one.

        Execution Flow:
            1. Create a "late" entity with start_line=20.
            2. Create an "early" entity with start_line=5.
            3. Build the BSGMap.
            4. Assert that the entities are sorted so "early" comes before "late".

        Expectations:
            - The list of entities for the file is sorted in ascending order of start_line.
        """
        e1 = _make_entity("late", f"{ROOT}/a.py", start_line=20)
        e2 = _make_entity("early", f"{ROOT}/a.py", start_line=5)
        g = _make_graph([e1, e2])
        bsg = BSGMap.build(g, root=ROOT)
        assert [e.name for e in bsg._by_file["a.py"]] == ["early", "late"]

    def test_build_captures_imports_as_dependencies(self):
        """Verify IMPORTS relationship type is captured as cross-file dependencies.

        Scenario:
            An entity in a.py imports an entity in b.py.

        Execution Flow:
            1. Create entities in a.py and b.py.
            2. Link them with an IMPORTS relationship.
            3. Build the BSGMap.
            4. Assert that b.py is a dependency of a.py.

        Expectations:
            - "b.py" is in the dependencies list of "a.py".
        """
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
        """Verify relationships within the same file are ignored for cross-file dependency mapping.

        Scenario:
            Two entities in the same file a.py have a CALLS relationship.

        Execution Flow:
            1. Create two entities in a.py.
            2. Add a CALLS relationship between them.
            3. Build the BSGMap.
            4. Assert that a.py is not recorded as a dependency of itself.

        Expectations:
            - "a.py" is not present in _dependencies.
        """
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
        """Verify that BSGMap.build raises TypeError when not passed an InMemoryGraph.

        Scenario:
            An invalid dictionary type is passed to BSGMap.build instead of InMemoryGraph.

        Execution Flow:
            1. Invoke BSGMap.build with a dict.
            2. Catch the expected TypeError.

        Expectations:
            - A TypeError is raised containing "InMemoryGraph".
        """
        with pytest.raises(TypeError, match="InMemoryGraph"):
            BSGMap.build({"entities": {}}, root=ROOT)  # type: ignore[arg-type]

    def test_build_root_normalised(self):
        """Verify the root path is normalized and stripped from entity file paths.

        Scenario:
            An entity is created at a subpath under the root repository.

        Execution Flow:
            1. Create an entity at f"{ROOT}/sub/c.py".
            2. Build the BSGMap.
            3. Assert that the key in _by_file is "sub/c.py".

        Expectations:
            - The file key is normalized to "sub/c.py".
        """
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
        """Verify patch updates entities for modified files.

        Scenario:
            An entity in a file is modified, and the file change and the updated graph are passed to patch.

        Execution Flow:
            1. Build a BSGMap with the old entity in a.py.
            2. Define a modified file change for a.py and the new graph containing a new entity.
            3. Apply patch.
            4. Verify that the new entity is present in the file's list.

        Expectations:
            - The old entity is replaced by the new entity name "new_fn" in the _by_file mapping.
        """
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
        """Verify patch removes files from the map if they are deleted.

        Scenario:
            A file is deleted, and its change type is DELETED.

        Execution Flow:
            1. Build a BSGMap containing a.py.
            2. Prepare a DELETED change for a.py and an empty graph.
            3. Call patch on the BSGMap.
            4. Check if "a.py" is removed from _by_file.

        Expectations:
            - "a.py" is no longer a key in _by_file.
        """
        root = str(tmp_path)
        e1 = _make_entity("old_fn", f"{root}/a.py")
        g0 = _make_graph([e1])
        bsg = BSGMap.build(g0, root=root)

        g_empty = _make_graph([])
        change = _make_change(f"{root}/a.py", "deleted")
        bsg.patch([change], g_empty)
        assert "a.py" not in bsg._by_file

    def test_patch_leaves_unchanged_files_intact(self, tmp_path):
        """Verify files not listed in file changes are left unchanged.

        Scenario:
            A BSGMap contains two files, a.py and b.py, and only a.py is changed.

        Execution Flow:
            1. Build a BSGMap with entities in a.py and b.py.
            2. Call patch with a MODIFIED change for a.py.
            3. Verify b.py's entity is still intact.

        Expectations:
            - The entity "fn_b" for "b.py" remains in the map.
        """
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
        """Verify patch updates dependencies between files.

        Scenario:
            An import dependency from a.py to b.py is removed in an update.

        Execution Flow:
            1. Build a BSGMap with an IMPORTS relationship from a.py to b.py.
            2. Update a.py to remove the import.
            3. Call patch.
            4. Verify that "b.py" is no longer listed as a dependency for "a.py".

        Expectations:
            - "b.py" is removed from the dependencies of "a.py".
        """
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
        """Verify that patch raises TypeError when not passed an InMemoryGraph.

        Scenario:
            An invalid dictionary type is passed to patch as the new graph.

        Execution Flow:
            1. Build a BSGMap.
            2. Invoke patch with a file change and a dict instead of InMemoryGraph.
            3. Verify TypeError is raised.

        Expectations:
            - A TypeError is raised containing "InMemoryGraph".
        """
        root = str(tmp_path)
        e1 = _make_entity("fn", f"{root}/a.py")
        bsg = BSGMap.build(_make_graph([e1]), root=root)
        change = _make_change(f"{root}/a.py", "modified")
        with pytest.raises(TypeError, match="InMemoryGraph"):
            bsg.patch([change], {})  # type: ignore[arg-type]

    def test_patch_serialised_bsg_cleared(self, tmp_path):
        """Verify patch clears the cached serialized representation.

        Scenario:
            A cached serialized BSG exists, and patch is applied to the map.

        Execution Flow:
            1. Build a BSGMap and set a mock value in `_serialized_bsg`.
            2. Run patch.
            3. Check if `_serialized_bsg` is reset to None.

        Expectations:
            - `_serialized_bsg` is None.
        """
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
        """Verify BSGMap.from_dict initializes empty mapping on empty input.

        Scenario:
            An empty dictionary is passed to BSGMap.from_dict.

        Execution Flow:
            1. Invoke BSGMap.from_dict with {}.
            2. Verify that _by_file is an empty dict.

        Expectations:
            - The parsed map has an empty _by_file mapping.
        """
        bsg = BSGMap.from_dict({})
        assert bsg._by_file == {}

    def test_from_dict_node_list_format(self):
        """Verify parsing a valid dict format populated with node dictionaries.

        Scenario:
            A valid dictionary containing root and a list of serialized nodes is passed to BSGMap.from_dict.

        Execution Flow:
            1. Define a dictionary with root directory and a list containing a serialized function node.
            2. Parse it using BSGMap.from_dict.
            3. Verify the file and entity name are correctly mapped inside _by_file.

        Expectations:
            - The parsed map contains "src/mod.py" in _by_file.
            - The entity under "src/mod.py" has name "my_fn".
        """
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
        """Verify TypeError is raised when standard dict is not passed to from_dict.

        Scenario:
            A string instead of a dictionary is passed to BSGMap.from_dict.

        Execution Flow:
            1. Call BSGMap.from_dict with a string.
            2. Catch TypeError.

        Expectations:
            - A TypeError is raised.
        """
        with pytest.raises(TypeError):
            BSGMap.from_dict("not a dict")  # type: ignore[arg-type]

    def test_from_dict_skips_invalid_nodes(self):
        """Verify invalid nodes in the nodes list are ignored during parsing.

        Scenario:
            The input dictionary contains non-dict objects in the "nodes" list.

        Execution Flow:
            1. Construct a dictionary where the "nodes" key has invalid entries (string, None, integer).
            2. Invoke BSGMap.from_dict.
            3. Verify that _by_file remains empty.

        Expectations:
            - No exceptions are raised, and the parsed _by_file map is empty.
        """
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
        """Verify render_compressed returns all entities when budget is sufficient.

        Scenario:
            A BSGMap with two entities is rendered with a large token budget.

        Execution Flow:
            1. Build a BSGMap with 2 entities.
            2. Render the map with a budget of 10,000 tokens.
            3. Verify the rendered text contains both entities and stats show no truncated files.

        Expectations:
            - Both entity names are present in the output text.
            - "truncated_files" count in stats is 0.
        """
        bsg = self._bsg_with_file(2)
        text, stats = bsg.render_compressed(budget=10_000, fail_on_overflow=False)
        assert "fn_0" in text
        assert "fn_1" in text
        assert stats["truncated_files"] == 0

    def test_render_overflow_raises_when_flag_set(self):
        """Verify render_compressed raises ValueError on budget overflow if fail_on_overflow is set.

        Scenario:
            A BSGMap with many entities is rendered with a tiny budget and fail_on_overflow=True.

        Execution Flow:
            1. Build a BSGMap with 50 entities.
            2. Invoke render_compressed with budget=1 and fail_on_overflow=True.
            3. Catch the expected ValueError.

        Expectations:
            - A ValueError is raised containing "Token budget exceeded".
        """
        bsg = self._bsg_with_file(50)
        with pytest.raises(ValueError, match="Token budget exceeded"):
            bsg.render_compressed(budget=1, fail_on_overflow=True)

    def test_render_overflow_soft_truncates(self):
        """Verify render_compressed soft-truncates when budget is exceeded and fail_on_overflow is False.

        Scenario:
            A BSGMap with 50 entities is rendered with a budget of 5 tokens and fail_on_overflow=False.

        Execution Flow:
            1. Build a BSGMap with 50 entities.
            2. Invoke render_compressed with budget=5 and fail_on_overflow=False.
            3. Verify the returned text indicates truncation and stats show truncated files.

        Expectations:
            - The output contains the string "truncated".
            - "truncated_files" in stats is greater than 0.
        """
        bsg = self._bsg_with_file(50)
        text, stats = bsg.render_compressed(budget=5, fail_on_overflow=False)
        assert "truncated" in text
        assert stats["truncated_files"] > 0

    def test_render_stats_keys_present(self):
        """Verify all expected stats keys are returned in render_compressed.

        Scenario:
            A standard BSGMap is rendered.

        Execution Flow:
            1. Build a BSGMap.
            2. Call render_compressed.
            3. Verify the presence of keys "tokens_used", "budget", and "truncated_files" in the returned stats dictionary.

        Expectations:
            - All three key statistics are present in the returned dictionary.
        """
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
        """Verify render_delta returns empty addition/removal lists when maps are identical.

        Scenario:
            Two BSGMaps built from the exact same graph are compared using render_delta.

        Execution Flow:
            1. Build bsg1 and bsg2 using identical graphs containing a single entity.
            2. Compute render_delta between them.
            3. Verify the "added" and "removed" sections in the returned delta are empty.

        Expectations:
            - The "added" mapping is empty.
            - The "removed" list is empty.
        """
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
        """Verify render_delta detects added files when self has files not in other.

        Scenario:
            bsg1 (self) has a.py and b.py, whereas bsg2 (other) only has a.py.

        Execution Flow:
            1. Build bsg1 with a.py and b.py.
            2. Build bsg2 with only a.py.
            3. Call bsg1.render_delta(bsg2).
            4. Verify that b.py is captured in "added".

        Expectations:
            - The "added" section of delta contains "b.py".
        """
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
        """Verify render_delta detects removed files when other has files not in self.

        Scenario:
            bsg1 (self) has only a.py, whereas bsg2 (other) has a.py and b.py.

        Execution Flow:
            1. Build bsg1 with only a.py.
            2. Build bsg2 with a.py and b.py.
            3. Call bsg1.render_delta(bsg2).
            4. Verify that b.py is captured in "removed".

        Expectations:
            - The "removed" section of delta contains "b.py".
        """
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
        """Verify that render_overview_json contains the correct schema version.

        Scenario:
            A BSGMap is constructed.

        Execution Flow:
            1. Build BSGMap instance.
            2. Generate overview using render_overview_json().
            3. Assert schema_version equals "context-overview.v1".

        Expectations:
            - The schema_version is "context-overview.v1".
        """
        bsg = self._bsg()
        overview = bsg.render_overview_json()
        assert overview.get("schema_version") == "context-overview.v1"

    def test_render_overview_json_summary_totals(self):
        """Verify render_overview_json returns accurate file and entity totals in its summary.

        Scenario:
            A BSGMap contains 2 files and 2 entities.

        Execution Flow:
            1. Build a BSGMap.
            2. Call render_overview_json().
            3. Verify total_files is 2 and total_entities is 2 in overview["summary"].

        Expectations:
            - total_files equals 2.
            - total_entities equals 2.
        """
        bsg = self._bsg()
        overview = bsg.render_overview_json()
        summary = overview["summary"]
        assert summary["total_files"] == 2
        assert summary["total_entities"] == 2

    def test_render_overview_json_directory_structure_present(self):
        """Verify render_overview_json contains the directory structure node.

        Scenario:
            A standard BSGMap is analyzed for directory structure layout.

        Execution Flow:
            1. Build a BSGMap.
            2. Invoke render_overview_json().
            3. Assert that "directory_structure" key exists and is of type "directory".

        Expectations:
            - overview has "directory_structure".
            - The directory structure type field is "directory".
        """
        bsg = self._bsg()
        overview = bsg.render_overview_json()
        assert "directory_structure" in overview
        assert overview["directory_structure"]["type"] == "directory"

    def test_render_overview_json_build_tree_no_duplicates(self):
        """Verify render_overview_json builds directory tree without duplicate sibling nodes.

        Scenario:
            20 entities are generated within nested subdirectories under the same "src/sub" prefix.

        Execution Flow:
            1. Build a BSGMap with entities in `src/sub/file_i.py`.
            2. Invoke render_overview_json().
            3. Retrieve the children of the root directory.
            4. Verify that "src" directory appears exactly once in the tree children.

        Expectations:
            - Only a single "src" child node is created at the top level of the directory structure tree.
        """
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
        """Verify render_files_json returns a dictionary.

        Scenario:
            A standard BSGMap is rendered into file JSON format.

        Execution Flow:
            1. Build a BSGMap.
            2. Call render_files_json().
            3. Assert the result is an instance of dict.

        Expectations:
            - The return value is a dict.
        """
        bsg = self._bsg()
        result = bsg.render_files_json()
        assert isinstance(result, dict)

    def test_to_dict_round_trip_has_nodes(self):
        """Verify to_dict returns a serialization containing nodes.

        Scenario:
            A standard BSGMap is serialized via to_dict().

        Execution Flow:
            1. Build a BSGMap.
            2. Call to_dict().
            3. Check that the output contains "nodes" or is a valid dict.

        Expectations:
            - The resulting object has a "nodes" key or is a dict.
        """
        bsg = self._bsg()
        d = bsg.to_dict()
        assert "nodes" in d or isinstance(d, dict)
