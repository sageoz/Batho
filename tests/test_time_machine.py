"""Tests for batho_core.time_machine module."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from batho_core.context.codegraph import InMemoryGraph
from batho_core.context.repomap import RepoMap
from batho_core.context.schema import Entity, EntityType
from batho_core.time_machine import (
    compute_staleness,
    create_snapshot,
    diff_snapshots,
    generate_snapshot_id,
    list_snapshots,
    load_snapshot,
    webhook_stub,
    FileChangeTracker,
    FileChangeType,
    FileTrackingConfig,
)


# ---------------------------------------------------------------------------
# generate_snapshot_id
# ---------------------------------------------------------------------------


class TestGenerateSnapshotId:
    def test_format(self):
        sid = generate_snapshot_id()
        assert sid.startswith("batho_")
        assert "T" in sid  # timestamp portion

    def test_unique(self):
        a = generate_snapshot_id()
        b = generate_snapshot_id()
        assert a != b


# ---------------------------------------------------------------------------
# create_snapshot / load_snapshot / list_snapshots
# ---------------------------------------------------------------------------


class TestSnapshotLifecycle:
    def test_create_and_load(self, tmp_path: Path, mock_graph):
        ctn_dir = tmp_path / ".ctn"
        ctn_dir.mkdir()
        repomap = RepoMap.build(mock_graph, root=str(tmp_path))

        sid = create_snapshot(ctn_dir, tmp_path, mock_graph, repomap, label="test")
        assert sid.startswith("batho_")

        loaded = load_snapshot(ctn_dir, sid)
        assert loaded is not None
        assert loaded["snapshot_id"] == sid
        assert loaded["label"] == "test"

    def test_list_snapshots(self, tmp_path: Path, mock_graph):
        ctn_dir = tmp_path / ".ctn"
        ctn_dir.mkdir()
        repomap = RepoMap.build(mock_graph, root=str(tmp_path))

        create_snapshot(ctn_dir, tmp_path, mock_graph, repomap)
        create_snapshot(ctn_dir, tmp_path, mock_graph, repomap, label="second")

        snaps = list_snapshots(ctn_dir)
        assert len(snaps) == 2

    def test_load_missing_returns_none(self, tmp_path: Path):
        ctn_dir = tmp_path / ".ctn"
        ctn_dir.mkdir()
        assert load_snapshot(ctn_dir, "nonexistent_id") is None

    def test_load_corrupted_checksum_returns_none(self, tmp_path: Path):
        ctn_dir = tmp_path / ".ctn"
        ctn_dir.mkdir()
        snap_dir = ctn_dir / "snapshots"
        snap_dir.mkdir()
        snap_file = snap_dir / "bad_snap.json"
        snap_file.write_text(
            json.dumps(
                {
                    "snapshot_id": "bad_snap",
                    "_checksum": "invalidchecksum",
                    "data": "test",
                }
            )
        )
        assert load_snapshot(ctn_dir, "bad_snap") is None


# ---------------------------------------------------------------------------
# diff_snapshots
# ---------------------------------------------------------------------------


class TestDiffSnapshots:
    def test_same_snapshot(self, tmp_path: Path, mock_graph):
        ctn_dir = tmp_path / ".ctn"
        ctn_dir.mkdir()
        repomap = RepoMap.build(mock_graph, root=str(tmp_path))

        sid = create_snapshot(ctn_dir, tmp_path, mock_graph, repomap)
        snap = load_snapshot(ctn_dir, sid)

        diff = diff_snapshots(snap, snap)
        assert diff["entity_delta"] == 0
        assert diff["relationship_delta"] == 0
        assert diff["added_files"] == []
        assert diff["removed_files"] == []

    def test_diff_with_changes(self):
        a = {
            "stats": {"entity_count": 10, "relationship_count": 5},
            "repomap": {"files": {"a.py": [], "b.py": []}},
        }
        b = {
            "stats": {"entity_count": 15, "relationship_count": 8},
            "repomap": {"files": {"b.py": [], "c.py": []}},
        }
        diff = diff_snapshots(a, b)
        assert diff["entity_delta"] == 5
        assert diff["relationship_delta"] == 3
        assert "c.py" in diff["added_files"]
        assert "a.py" in diff["removed_files"]


# ---------------------------------------------------------------------------
# compute_staleness
# ---------------------------------------------------------------------------


class TestComputeStaleness:
    def test_no_previous_entry(self):
        assert compute_staleness(None, "hash1") == 1.0

    def test_same_hash_low_staleness(self):
        prev = {"repo_hash": "abc", "file_count": 10}
        score = compute_staleness(prev, "abc")
        assert score < 0.5

    def test_different_hash_higher_staleness(self):
        prev = {"repo_hash": "abc", "file_count": 10}
        score = compute_staleness(prev, "xyz")
        assert score >= 0.6

    def test_returns_float_in_range(self):
        prev = {
            "repo_hash": "abc",
            "file_count": 10,
            "timestamp": "2025-01-01T00:00:00+00:00",
        }
        score = compute_staleness(prev, "abc", {"files_parsed": 5, "errors": 0})
        assert 0.0 <= score <= 1.0


# ---------------------------------------------------------------------------
# webhook_stub
# ---------------------------------------------------------------------------


class TestWebhookStub:
    def test_returns_expected_keys(self):
        result = webhook_stub(
            {"event": "push", "repository": {"full_name": "user/repo"}}
        )
        assert result["event"] == "push"
        assert result["repo"] == "user/repo"
        assert result["status"] == "not_implemented"

    def test_missing_event(self):
        result = webhook_stub({})
        assert result["event"] == "unknown"


# ---------------------------------------------------------------------------
# FileChangeTracker
# ---------------------------------------------------------------------------


class TestFileChangeTracker:
    def test_single_file_change(self, tmp_path: Path):
        tracker = FileChangeTracker(tmp_path)
        test_file = tmp_path / "test.py"
        test_file.write_text("print('hello')")

        changes = tracker.scan_for_changes()

        added = [c for c in changes if c.change_type == FileChangeType.ADDED]
        assert len(added) == 1
        assert added[0].path == "test.py"
        assert added[0].new_hash is not None
        assert added[0].old_hash is None

    def test_modify_file(self, tmp_path: Path):
        cache_path = tmp_path / "hashes.json"
        test_file = tmp_path / "test.py"
        test_file.write_text("print('hello')")

        tracker = FileChangeTracker(tmp_path)
        tracker.scan_for_changes()
        tracker.save(cache_path)

        test_file.write_text("print('world')")

        tracker2 = FileChangeTracker(tmp_path)
        tracker2.load(cache_path)
        changes = tracker2.scan_for_changes()

        modified = [c for c in changes if c.change_type == FileChangeType.MODIFIED]
        assert len(modified) == 1
        assert modified[0].path == "test.py"

    def test_delete_file(self, tmp_path: Path):
        cache_path = tmp_path / "hashes.json"
        test_file = tmp_path / "test.py"
        test_file.write_text("print('hello')")

        tracker = FileChangeTracker(tmp_path)
        tracker.scan_for_changes()
        tracker.save(cache_path)

        test_file.unlink()

        tracker2 = FileChangeTracker(tmp_path)
        tracker2.load(cache_path)
        changes = tracker2.scan_for_changes()

        deleted = [c for c in changes if c.change_type == FileChangeType.DELETED]
        assert len(deleted) == 1
        assert deleted[0].path == "test.py"

    def test_no_changes(self, tmp_path: Path):
        cache_path = tmp_path / "hashes.json"
        test_file = tmp_path / "test.py"
        test_file.write_text("print('hello')")

        tracker = FileChangeTracker(tmp_path)
        tracker.scan_for_changes()
        tracker.save(cache_path)

        tracker2 = FileChangeTracker(tmp_path)
        tracker2.load(cache_path)
        changes = tracker2.scan_for_changes()

        tracked_files = [c for c in changes if c.path.endswith(".py")]
        assert len(tracked_files) == 0

    def test_multiple_files(self, tmp_path: Path):
        (tmp_path / "a.py").write_text("a = 1")
        (tmp_path / "b.py").write_text("b = 2")
        (tmp_path / "c.txt").write_text("hello")

        tracker = FileChangeTracker(tmp_path)
        changes = tracker.scan_for_changes()

        added = [c for c in changes if c.change_type == FileChangeType.ADDED]
        assert len(added) == 3

        changed_paths = tracker.get_changed_files(changes)
        assert len(changed_paths) == 3


class TestFileChangeTrackerEdgeCases:
    """Test edge cases for FileChangeTracker: symlinks, permissions, binaries."""

    def test_symlink_detection(self, tmp_path: Path):
        """Test that symlinks are properly detected and tracked."""
        tracker = FileChangeTracker(tmp_path)
        target_file = tmp_path / "target.txt"
        target_file.write_text("target content")
        symlink_file = tmp_path / "link.txt"
        symlink_file.symlink_to(target_file)

        changes = tracker.scan_for_changes()

        added = [c for c in changes if c.change_type == FileChangeType.ADDED]
        assert len(added) == 2  # target file and symlink

        symlink_change = next((c for c in added if c.is_symlink), None)
        assert symlink_change is not None
        assert symlink_change.symlink_target == "target.txt"

        # Verify hash follows symlink format
        assert symlink_change.new_hash.startswith("symlink:")

    def test_broken_symlink_handling(self, tmp_path: Path):
        """Test handling of broken symlinks."""
        tracker = FileChangeTracker(tmp_path)
        broken_symlink = tmp_path / "broken_link.txt"
        broken_symlink.symlink_to("nonexistent_target.txt")

        changes = tracker.scan_for_changes()

        added = [c for c in changes if c.change_type == FileChangeType.ADDED]
        assert len(added) == 1

        symlink_change = added[0]
        assert symlink_change.is_symlink
        assert symlink_change.new_hash == "symlink:broken"

    def test_large_file_skip(self, tmp_path: Path):
        """Test that very large files are skipped with custom size limit."""
        from batho_core.time_machine import FileTrackingConfig

        tracker = FileChangeTracker(tmp_path)
        large_file = tmp_path / "large.bin"
        # Create a file larger than default 500KB limit
        large_file.write_bytes(b"\x00" * (600 * 1024))  # 600KB

        config = FileTrackingConfig(max_file_size_kb=500)
        changes = tracker.scan_for_changes(config=config)

        # File should be skipped and not appear in changes
        added = [c for c in changes if c.change_type == FileChangeType.ADDED]
        filtered_paths = [c.path for c in added]
        assert "large.bin" not in filtered_paths

    def test_binary_file_warning(self, tmp_path: Path, caplog):
        """Test that large binary files trigger warnings."""
        from batho_core.time_machine import FileTrackingConfig

        tracker = FileChangeTracker(tmp_path)
        binary_file = tmp_path / "large_binary.bin"
        binary_file.write_bytes(b"\x00\x01\x02" * (200 * 1024))  # 600KB binary

        config = FileTrackingConfig(
            max_file_size_kb=1000, warn_binary_files=True, binary_size_threshold_kb=300
        )

        with caplog.at_level("WARNING"):
            changes = tracker.scan_for_changes(config=config)

        # Should have logged a warning for large binary file
        assert any(
            "large_binary_file_detected" in record.message for record in caplog.records
        )
        assert any("large_binary.bin" in record.message for record in caplog.records)

    def test_permission_error_logging(self, tmp_path: Path, caplog):
        """Test permission error handling and logging."""
        from batho_core.time_machine import FileTrackingConfig

        tracker = FileChangeTracker(tmp_path)
        no_perm_file = tmp_path / "no_perm.txt"
        no_perm_file.write_text("content")
        # Try to make file inaccessible (on systems that support it)
        try:
            no_perm_file.chmod(0)  # No permissions
        except OSError:
            pytest.skip("Cannot change file permissions")

        config = FileTrackingConfig(log_permission_errors=True)

        with caplog.at_level("WARNING"):
            changes = tracker.scan_for_changes(config=config)

        # Should have logged permission error
        assert any("file_access_error" in record.message for record in caplog.records)

        # Restore permissions for cleanup
        try:
            no_perm_file.chmod(0o644)
        except OSError:
            pass

    def test_mixed_text_binary_changes(self, tmp_path: Path):
        """Test tracking changes with both text and binary files."""
        tracker = FileChangeTracker(tmp_path)

        # Create initial files
        text_file = tmp_path / "code.py"
        text_file.write_text("print('hello')")
        binary_file = tmp_path / "data.bin"
        binary_file.write_bytes(b"\x00\x01\x02\x03")

        changes1 = tracker.scan_for_changes()
        assert len([c for c in changes1 if c.change_type == FileChangeType.ADDED]) == 2

        # Modify files
        text_file.write_text("print('world')")
        binary_file.write_bytes(b"\x04\x05\x06\x07")

        changes2 = tracker.scan_for_changes()

        modified = [c for c in changes2 if c.change_type == FileChangeType.MODIFIED]
        assert len(modified) == 2

        # Text file should have SHA hash
        text_change = next(c for c in modified if c.path == "code.py")
        assert text_change.new_hash is not None
        # Should not be size_mtime format
        assert "_" not in text_change.new_hash

        # Binary file should have size_mtime hash
        binary_change = next(c for c in modified if c.path == "data.bin")
        assert binary_change.new_hash is not None
        assert "_" in binary_change.new_hash  # size_mtime format
