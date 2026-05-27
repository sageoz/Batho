"""Integration tests for file changelog: engine methods + record_file_changelog."""

from __future__ import annotations

import orjson
from pathlib import Path

import pytest

from batho.modules.graph.diff_engine.node_diff import NodeDiff, diff_file_nodes
from batho.modules.storage.sqlite_registry.engine import BathoDatabase


@pytest.fixture()
def tmp_db(tmp_path: Path) -> BathoDatabase:
    db_path = tmp_path / "test.batho"
    db = BathoDatabase(db_path, repo_root=tmp_path)
    return db


def _make_run(db: BathoDatabase, git_commit: str | None = None) -> tuple[str, int]:
    import uuid
    run_uuid = f"test_{uuid.uuid4().hex[:8]}"
    internal_id = db.create_run(run_uuid, root_path="/tmp", git_commit=git_commit)
    db.complete_run(run_uuid, entity_count=0, rel_count=0, file_count=0, duration_ms=1)
    return run_uuid, internal_id


def _insert_agent_view(db: BathoDatabase, run_internal_id: int, file_path: str, entities: list[dict]) -> None:
    agent_view = {"entities": entities}
    db.insert_file_artifact(
        run_internal_id,
        file_path,
        "filehash",
        agent_view,
        {"entities": []},
        [],
    )


class TestGetAgentEntitiesForFile:
    def test_returns_empty_for_missing_file(self, tmp_db: BathoDatabase):
        _, run_id = _make_run(tmp_db)
        result = tmp_db.get_agent_entities_for_file(run_id, "nonexistent.py")
        assert result == []

    def test_returns_entities_for_existing_file(self, tmp_db: BathoDatabase):
        _, run_id = _make_run(tmp_db)
        entities = [
            {"id": "abc123", "name": "my_func", "type": "FUNCTION",
             "start_line": 1, "end_line": 10, "signature": "(x)", "content_hash": "deadbeef"},
        ]
        _insert_agent_view(tmp_db, run_id, "src/module.py", entities)
        result = tmp_db.get_agent_entities_for_file(run_id, "src/module.py")
        assert len(result) == 1
        assert result[0]["id"] == "abc123"
        assert result[0]["name"] == "my_func"


class TestRecordFileChangelog:
    def test_record_added_diff(self, tmp_db: BathoDatabase):
        _, base_id = _make_run(tmp_db)
        _, run_id = _make_run(tmp_db)

        diffs = [
            NodeDiff(
                entity_id="ent_001",
                entity_name="new_func",
                entity_type="FUNCTION",
                file_path="src/foo.py",
                change_kind="added",
                changed_fields={},
                old_hash=None,
                new_hash="cafecafe",
            )
        ]
        tmp_db.record_file_changelog(run_id, base_id, diffs)

        with tmp_db.connection(read_only=True) as conn:
            rows = conn.execute("SELECT * FROM file_changelog").fetchall()
        assert len(rows) == 1
        blob = rows[0]["node_changes"]
        assert blob is not None
        changes = orjson.loads(tmp_db._dctx.decompress(blob))
        assert len(changes) == 1
        assert changes[0]["change_kind"] == "added"
        assert changes[0]["new_hash"] == "cafecafe"
        assert changes[0]["old_hash"] is None

    def test_record_modified_diff_compresses_fields(self, tmp_db: BathoDatabase):
        _, base_id = _make_run(tmp_db)
        _, run_id = _make_run(tmp_db)

        diffs = [
            NodeDiff(
                entity_id="ent_002",
                entity_name="changed_func",
                entity_type="FUNCTION",
                file_path="src/bar.py",
                change_kind="modified",
                changed_fields={"signature": ["(a)", "(a, b)"], "start_line": [5, 7]},
                old_hash="aaaa1111",
                new_hash="bbbb2222",
            )
        ]
        tmp_db.record_file_changelog(run_id, base_id, diffs)

        with tmp_db.connection(read_only=True) as conn:
            row = conn.execute("SELECT node_changes FROM file_changelog").fetchone()

        assert row["node_changes"] is not None
        changes = orjson.loads(tmp_db._dctx.decompress(row["node_changes"]))
        assert len(changes) == 1
        assert changes[0]["changed_fields"]["signature"] == ["(a)", "(a, b)"]
        assert changes[0]["changed_fields"]["start_line"] == [5, 7]

    def test_record_noop_on_empty_diffs(self, tmp_db: BathoDatabase):
        _, base_id = _make_run(tmp_db)
        _, run_id = _make_run(tmp_db)
        tmp_db.record_file_changelog(run_id, base_id, [])
        with tmp_db.connection(read_only=True) as conn:
            count = conn.execute("SELECT COUNT(*) FROM file_changelog").fetchone()[0]
        assert count == 0

    def test_all_change_kinds_stored_correctly(self, tmp_db: BathoDatabase):
        _, base_id = _make_run(tmp_db)
        _, run_id = _make_run(tmp_db)

        diffs = [
            NodeDiff("id1", "added_func", "FUNCTION", "f.py", "added", {}, None, "aaaa1111"),
            NodeDiff("id2", "removed_func", "FUNCTION", "f.py", "removed", {}, "bbbb2222", None),
            NodeDiff("id3", "modified_func", "FUNCTION", "f.py", "modified",
                     {"start_line": [1, 2]}, "cccc3333", "dddd4444"),
            NodeDiff("id4", "renamed_func", "FUNCTION", "f.py", "renamed",
                     {"old_id": "id_old"}, "eeee5555", "eeee5555"),
        ]
        tmp_db.record_file_changelog(run_id, base_id, diffs)

        with tmp_db.connection(read_only=True) as conn:
            row = conn.execute("SELECT node_changes FROM file_changelog").fetchone()
        changes = orjson.loads(tmp_db._dctx.decompress(row["node_changes"]))
        kinds = sorted(c["change_kind"] for c in changes)
        assert kinds == ["added", "modified", "removed", "renamed"]


class TestGetRunFileChangelog:
    def test_returns_entries_for_run(self, tmp_db: BathoDatabase):
        base_uuid, base_id = _make_run(tmp_db)
        run_uuid, run_id = _make_run(tmp_db)

        diffs = [
            NodeDiff("ent_abc", "my_class", "CLASS", "src/x.py",
                     "added", {}, None, "ff001122"),
        ]
        tmp_db.record_file_changelog(run_id, base_id, diffs)

        result = tmp_db.get_run_file_changelog(run_uuid)
        assert len(result) == 1
        entry = result[0]
        assert entry["entity_id"] == "ent_abc"
        assert entry["change_kind"] == "added"
        assert entry["file_path"] == "src/x.py"
        assert entry["entity_type"] == "CLASS"
        assert entry["base_run_uuid"] == base_uuid
        assert entry["run_uuid"] == run_uuid

    def test_returns_empty_for_unknown_run(self, tmp_db: BathoDatabase):
        result = tmp_db.get_run_file_changelog("nonexistent_run")
        assert result == []


class TestGetFileNodeHistory:
    def test_history_ordered_chronologically(self, tmp_db: BathoDatabase):
        base_uuid, base_id = _make_run(tmp_db)
        run1_uuid, run1_id = _make_run(tmp_db)
        run2_uuid, run2_id = _make_run(tmp_db)

        diffs1 = [NodeDiff("ent_xyz", "evolving", "FUNCTION", "a.py",
                           "modified", {"signature": ["()", "(x)"]}, "old1", "new1")]
        tmp_db.record_file_changelog(run1_id, base_id, diffs1)

        diffs2 = [NodeDiff("ent_xyz", "evolving", "FUNCTION", "a.py",
                           "modified", {"signature": ["(x)", "(x, y)"]}, "new1", "new2")]
        tmp_db.record_file_changelog(run2_id, run1_id, diffs2)

        history = tmp_db.get_file_node_history("ent_xyz")
        assert len(history) == 2
        assert history[0]["run_uuid"] == run1_uuid
        assert history[1]["run_uuid"] == run2_uuid

    def test_returns_empty_for_unknown_entity(self, tmp_db: BathoDatabase):
        result = tmp_db.get_file_node_history("completely_unknown_id")
        assert result == []


class TestPruneFileChangelog:
    def test_prune_keeps_recent_runs(self, tmp_db: BathoDatabase):
        base_uuid, base_id = _make_run(tmp_db)
        run1_uuid, run1_id = _make_run(tmp_db)
        run2_uuid, run2_id = _make_run(tmp_db)
 
        diffs1 = [NodeDiff("e1", "f1", "FUNCTION", "x.py", "added", {}, None, "h1")]
        diffs2 = [NodeDiff("e2", "f2", "FUNCTION", "y.py", "added", {}, None, "h2")]
        tmp_db.record_file_changelog(run1_id, base_id, diffs1)
        tmp_db.record_file_changelog(run2_id, run1_id, diffs2)
 
        tmp_db.prune_file_changelog(max_runs=2)
 
        with tmp_db.connection(read_only=True) as conn:
            count = conn.execute("SELECT COUNT(*) FROM file_changelog").fetchone()[0]
        # Since base_id is pruned, diffs1 (referencing base_id) is cascade-deleted.
        # Only diffs2 remains (from run2_id to run1_id).
        assert count == 1
 
    def test_prune_deletes_old_entries(self, tmp_db: BathoDatabase):
        run0_uuid, run0_id = _make_run(tmp_db)
        run1_uuid, run1_id = _make_run(tmp_db)
        run2_uuid, run2_id = _make_run(tmp_db)
        run3_uuid, run3_id = _make_run(tmp_db)
 
        # run1 diff against run0 (both will be deleted since max_runs=2)
        tmp_db.record_file_changelog(
            run1_id, run0_id,
            [NodeDiff("e1", "func", "FUNCTION", "f.py", "added", {}, None, "hash")]
        )
        # run2 diff against run1 (run1 is deleted, so this will be cascade-deleted)
        tmp_db.record_file_changelog(
            run2_id, run1_id,
            [NodeDiff("e2", "func", "FUNCTION", "f.py", "added", {}, None, "hash")]
        )
        # run3 diff against run2 (both run2 and run3 are kept, so this is kept)
        tmp_db.record_file_changelog(
            run3_id, run2_id,
            [NodeDiff("e3", "func", "FUNCTION", "f.py", "added", {}, None, "hash")]
        )
 
        tmp_db.prune_file_changelog(max_runs=2)
 
        with tmp_db.connection(read_only=True) as conn:
            run_ids = [r[0] for r in conn.execute(
                "SELECT DISTINCT run_id FROM file_changelog"
            ).fetchall()]
        assert run1_id not in run_ids
        assert run2_id not in run_ids
        assert run3_id in run_ids


class TestDiffIntegration:
    def test_full_diff_cycle(self, tmp_db: BathoDatabase):
        """Build base run, patch with modified entities, verify changelog."""
        base_uuid, base_id = _make_run(tmp_db)

        base_entities = [
            {"id": "func_abc", "name": "process", "type": "FUNCTION",
             "start_line": 10, "end_line": 20, "signature": "(self, data)",
             "content_hash": "original_hash"},
        ]
        _insert_agent_view(tmp_db, base_id, "service.py", base_entities)

        run_uuid, run_id = _make_run(tmp_db)

        new_entities = [
            {"id": "func_abc", "name": "process", "type": "FUNCTION",
             "start_line": 10, "end_line": 22, "signature": "(self, data: list[str])",
             "content_hash": "modified_hash"},
        ]
        _insert_agent_view(tmp_db, run_id, "service.py", new_entities)

        old = tmp_db.get_agent_entities_for_file(base_id, "service.py")
        node_diffs = diff_file_nodes(old, new_entities, "service.py")
        assert len(node_diffs) == 1
        assert node_diffs[0].change_kind == "modified"
        assert "signature" in node_diffs[0].changed_fields
        assert "end_line" in node_diffs[0].changed_fields

        tmp_db.record_file_changelog(run_id, base_id, node_diffs)

        history = tmp_db.get_file_node_history("func_abc")
        assert len(history) == 1
        assert history[0]["change_kind"] == "modified"
        assert history[0]["changed_fields"]["end_line"] == [20, 22]

        changelog = tmp_db.get_run_file_changelog(run_uuid)
        assert len(changelog) == 1
        assert changelog[0]["entity_id"] == "func_abc"
