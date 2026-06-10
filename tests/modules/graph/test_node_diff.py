"""Unit tests for batho.modules.graph.diff_engine.node_diff — pure diff engine, no DB/IO."""

from __future__ import annotations

import pytest
from batho.modules.graph.diff_engine.node_diff import NodeDiff, diff_file_nodes, TRACKED_FIELDS


def _make_entity(
    eid: str,
    name: str,
    entity_type: str = "FUNCTION",
    start_line: int = 1,
    end_line: int = 10,
    signature: str | None = None,
    content_hash: str = "",
) -> dict:
    return {
        "id": eid,
        "name": name,
        "type": entity_type,
        "start_line": start_line,
        "end_line": end_line,
        "signature": signature,
        "content_hash": content_hash,
    }


FILE_PATH = "src/module.py"


class TestDiffFileNodesEmpty:
    def test_both_empty(self):
        """Verify that diffing two empty entity lists returns an empty result."""
        assert diff_file_nodes([], [], FILE_PATH) == []

    def test_old_empty_all_added(self):
        """Verify that all entities are reported as added when the old list is empty."""
        new = [_make_entity("a1", "foo", content_hash="aabbccdd")]
        result = diff_file_nodes([], new, FILE_PATH)
        assert len(result) == 1
        assert result[0].change_kind == "added"
        assert result[0].entity_id == "a1"
        assert result[0].new_hash == "aabbccdd"[:8]
        assert result[0].old_hash is None

    def test_new_empty_all_removed(self):
        """Verify that all entities are reported as removed when the new list is empty."""
        old = [_make_entity("r1", "bar", content_hash="11223344")]
        result = diff_file_nodes(old, [], FILE_PATH)
        assert len(result) == 1
        assert result[0].change_kind == "removed"
        assert result[0].entity_id == "r1"
        assert result[0].old_hash == "11223344"[:8]
        assert result[0].new_hash is None


class TestDiffFileNodesModified:
    def test_unchanged_hash_skipped(self):
        """Verify that entities with identical content hashes produce no diff."""
        e = _make_entity("e1", "func", content_hash="deadbeef")
        result = diff_file_nodes([e], [e], FILE_PATH)
        assert result == []

    def test_signature_change_detected(self):
        """Verify that a signature change is detected as a modification."""
        old = _make_entity("e1", "func", signature="(self)", content_hash="aaa")
        new = _make_entity("e1", "func", signature="(self, x: int)", content_hash="bbb")
        result = diff_file_nodes([old], [new], FILE_PATH)
        assert len(result) == 1
        d = result[0]
        assert d.change_kind == "modified"
        assert "signature" in d.changed_fields
        assert d.changed_fields["signature"] == ["(self)", "(self, x: int)"]
        assert d.old_hash == "aaa"[:8]
        assert d.new_hash == "bbb"[:8]

    def test_line_shift_detected(self):
        """Verify that line number changes are detected as modifications."""
        old = _make_entity("e1", "func", start_line=10, end_line=20, content_hash="aaa")
        new = _make_entity("e1", "func", start_line=15, end_line=25, content_hash="bbb")
        result = diff_file_nodes([old], [new], FILE_PATH)
        assert len(result) == 1
        d = result[0]
        assert d.change_kind == "modified"
        assert d.changed_fields["start_line"] == [10, 15]
        assert d.changed_fields["end_line"] == [20, 25]

    def test_empty_hash_does_deep_diff(self):
        """Verify that entities with empty content hashes trigger a deep field-level diff."""
        old = _make_entity("e1", "func", signature="(a)", content_hash="")
        new = _make_entity("e1", "func", signature="(b)", content_hash="")
        result = diff_file_nodes([old], [new], FILE_PATH)
        assert len(result) == 1
        assert result[0].change_kind == "modified"

    def test_no_tracked_field_change_no_diff(self):
        """Verify that differing content hashes without tracked field changes produce no diff."""
        old = _make_entity("e1", "func", content_hash="aaa")
        new = _make_entity("e1", "func", content_hash="bbb")
        result = diff_file_nodes([old], [new], FILE_PATH)
        assert result == []


class TestDiffFileNodesRename:
    def test_rename_by_content_hash(self):
        """Verify that an entity rename is detected when the content hash remains unchanged."""
        old = _make_entity("old_id", "foo", content_hash="cafecafe")
        new = _make_entity("new_id", "bar", content_hash="cafecafe")
        result = diff_file_nodes([old], [new], FILE_PATH)
        assert len(result) == 1
        d = result[0]
        assert d.change_kind == "renamed"
        assert d.entity_id == "new_id"
        assert d.changed_fields == {"old_id": "old_id"}
        assert d.old_hash == "cafecafe"[:8]

    def test_no_rename_when_hash_differs(self):
        """Verify that differing content hashes prevent a rename detection."""
        old = _make_entity("old_id", "foo", content_hash="aaaa")
        new = _make_entity("new_id", "bar", content_hash="bbbb")
        result = diff_file_nodes([old], [new], FILE_PATH)
        kinds = {d.change_kind for d in result}
        assert kinds == {"added", "removed"}

    def test_rename_with_ambiguous_hash_picks_first(self):
        """Verify that when multiple old entities share the new entity's hash, the first match is treated as a rename."""
        old1 = _make_entity("old1", "foo", content_hash="cafecafe")
        old2 = _make_entity("old2", "baz", content_hash="cafecafe")
        new = _make_entity("new1", "bar", content_hash="cafecafe")
        result = diff_file_nodes([old1, old2], [new], FILE_PATH)
        renamed = [d for d in result if d.change_kind == "renamed"]
        removed = [d for d in result if d.change_kind == "removed"]
        assert len(renamed) == 1
        assert len(removed) == 1


class TestDiffFileNodesFilePath:
    def test_file_path_propagated(self):
        """Verify that the file_path is propagated to all diff results."""
        old = _make_entity("e1", "func", content_hash="abc")
        new = _make_entity("e2", "func2", content_hash="def")
        result = diff_file_nodes([old], [new], "custom/path.py")
        for d in result:
            assert d.file_path == "custom/path.py"


class TestDiffFileNodesMixed:
    def test_mixed_scenario(self):
        """Verify that a mixed diff correctly identifies unchanged, modified, added, and removed entities."""
        common_unchanged = _make_entity("c1", "stable", content_hash="same")
        old_modified = _make_entity("m1", "changing", signature="(a)", content_hash="old_hash")
        new_modified = _make_entity("m1", "changing", signature="(a, b)", content_hash="new_hash")
        old_deleted = _make_entity("d1", "gone", content_hash="deadbeef")
        new_added = _make_entity("a1", "fresh", content_hash="cafebabe")

        old = [common_unchanged, old_modified, old_deleted]
        new = [common_unchanged, new_modified, new_added]

        result = diff_file_nodes(old, new, FILE_PATH)
        kinds = {d.change_kind for d in result}
        assert "modified" in kinds
        assert "removed" in kinds
        assert "added" in kinds
        modified = [d for d in result if d.change_kind == "modified"]
        assert len(modified) == 1
        assert "signature" in modified[0].changed_fields


class TestNodeDiffDataclass:
    def test_all_fields_present(self):
        """Verify that NodeDiff dataclass captures all expected fields."""
        d = NodeDiff(
            entity_id="abc",
            entity_name="foo",
            entity_type="FUNCTION",
            file_path="x.py",
            change_kind="added",
            changed_fields={},
            old_hash=None,
            new_hash="ab12cd34",
        )
        assert d.entity_id == "abc"
        assert d.change_kind == "added"
        assert d.new_hash == "ab12cd34"
