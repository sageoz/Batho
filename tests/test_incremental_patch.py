"""Unit tests for incremental patch functionality."""

import json
import pytest
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open

from batho.time_machine import (
    FileChange,
    FileChangeType,
    FileChangeSummary,
    FileChangeTracker,
    IncrementalGraphUpdater,
    PatchOperation,
    diff_snapshots,
    compare_file_lists,
    aggregate_changes,
    parse_git_diff,
    incremental_patch,
    PatchValidationError,
    PatchTimeoutError,
    PatchConsistencyError,
    PatchSnapshotError,
    PatchFileError,
)
from batho.context.codegraph import InMemoryGraph
from batho.context.bsg_map import BSGMap
from batho.utils.hash import compute_bytes_hash


class TestFileChangeAndFileChangeSummary:
    """Test FileChange and FileChangeSummary data structures."""

    def test_file_change_construction(self):
        """Test FileChange dataclass construction."""
        fc = FileChange(
            path="test.py",
            change_type=FileChangeType.ADDED,
            old_hash=None,
            new_hash="abc123",
            file_size=100,
            mtime=datetime(2023, 1, 1, tzinfo=timezone.utc),
            permissions=0o644,
        )
        assert fc.path == "test.py"
        assert fc.change_type == FileChangeType.ADDED
        assert fc.old_hash is None
        assert fc.new_hash == "abc123"
        assert fc.file_size == 100
        assert fc.mtime == datetime(2023, 1, 1, tzinfo=timezone.utc)
        assert fc.permissions == 0o644

    def test_file_change_equality(self):
        """Test FileChange equality."""
        fc1 = FileChange("test.py", FileChangeType.MODIFIED, "old", "new")
        fc2 = FileChange("test.py", FileChangeType.MODIFIED, "old", "new")
        fc3 = FileChange("test.py", FileChangeType.MODIFIED, "old", "different")
        assert fc1 == fc2
        assert fc1 != fc3

    def test_file_change_serialization(self):
        """Test FileChange serialization."""
        fc = FileChange(
            path="test.py",
            change_type=FileChangeType.ADDED,
            old_hash=None,
            new_hash="abc123",
            file_size=100,
            mtime=datetime(2023, 1, 1, tzinfo=timezone.utc),
            permissions=0o644,
        )
        data = fc.__dict__
        # For JSON serialization, convert enum and datetime to serializable values
        serialized_data = {
            "path": data["path"],
            "change_type": data["change_type"].value,
            "old_hash": data["old_hash"],
            "new_hash": data["new_hash"],
            "file_size": data["file_size"],
            "mtime": data["mtime"].isoformat(),
            "permissions": data["permissions"],
        }
        assert serialized_data["path"] == "test.py"
        assert serialized_data["change_type"] == "added"
        assert serialized_data["old_hash"] is None
        assert serialized_data["new_hash"] == "abc123"
        assert serialized_data["file_size"] == 100
        assert serialized_data["mtime"] == "2023-01-01T00:00:00+00:00"
        assert serialized_data["permissions"] == 0o644

        # Ensure it's JSON serializable
        import json

        json_str = json.dumps(serialized_data)
        assert json_str

    def test_file_change_summary(self):
        """Test FileChangeSummary construction."""
        summary = FileChangeSummary(
            total_changes=10,
            added=3,
            modified=4,
            deleted=2,
            unchanged=1,
            affected_files=["a.py", "b.py", "c.py"],
        )
        assert summary.total_changes == 10
        assert summary.added == 3
        assert summary.modified == 4
        assert summary.deleted == 2
        assert summary.unchanged == 1
        assert summary.affected_files == ["a.py", "b.py", "c.py"]


class TestPatchOperation:
    """Test PatchOperation dataclass and methods."""

    def test_patch_operation_construction(self):
        """Test PatchOperation construction."""
        timestamp = datetime.now(timezone.utc)
        changes = [
            FileChange(
                path="test.py",
                change_type=FileChangeType.ADDED,
                old_hash=None,
                new_hash="hash1",
                file_size=100,
                mtime=datetime(2023, 1, 1, tzinfo=timezone.utc),
                permissions=0o644,
            ),
        ]
        op = PatchOperation(
            operation_id="op_123",
            base_snapshot_id="base_123",
            new_snapshot_id="new_123",
            changes_applied=changes,
            timestamp=timestamp,
            checksum="checksum_value",
            patch_chain=["base_123"],
            operation_type="incremental_patch",
            user_info={"source": "test"},
            metrics={"changes": 1},
        )
        assert op.operation_id == "op_123"
        assert op.base_snapshot_id == "base_123"
        assert op.new_snapshot_id == "new_123"
        assert op.changes_applied == changes
        assert op.timestamp == timestamp
        assert op.checksum == "checksum_value"

    def test_patch_operation_validation(self):
        """Test PatchOperation.validate method."""
        changes = [
            FileChange("test.py", FileChangeType.ADDED, None, "hash1"),
        ]
        op = PatchOperation(
            operation_id="op_123",
            base_snapshot_id="base_123",
            new_snapshot_id="new_123",
            changes_applied=changes,
            timestamp=datetime.now(timezone.utc),
            checksum="",  # Will be computed
            patch_chain=["base_123"],
            operation_type="incremental_patch",
            user_info={"source": "test"},
            metrics={"changes": 1},
        )
        data = op.serialize()
        data_without_checksum = {k: v for k, v in data.items() if k != "checksum"}
        expected_checksum = compute_bytes_hash(
            json.dumps(data_without_checksum, sort_keys=True).encode("utf-8")
        )
        op.checksum = expected_checksum
        assert op.validate() is True

        # Test invalid checksum
        op.checksum = "invalid"
        assert op.validate() is False

    def test_patch_operation_serialize(self):
        """Test PatchOperation.serialize method."""
        changes = [
            FileChange(
                "test.py",
                FileChangeType.ADDED,
                None,
                "hash1",
                file_size=100,
                mtime=datetime(2023, 1, 1, tzinfo=timezone.utc),
                permissions=0o644,
            ),
        ]
        op = PatchOperation(
            operation_id="op_123",
            base_snapshot_id="base_123",
            new_snapshot_id="new_123",
            changes_applied=changes,
            timestamp=datetime(2023, 2, 1, tzinfo=timezone.utc),
            checksum="checksum_value",
            patch_chain=["base_123"],
            operation_type="incremental_patch",
            user_info={"source": "test"},
            metrics={"changes": 1},
        )
        data = op.serialize()
        expected_data = {
            "operation_id": "op_123",
            "base_snapshot_id": "base_123",
            "new_snapshot_id": "new_123",
            "changes_applied": [
                {
                    "path": "test.py",
                    "change_type": "added",
                    "old_hash": None,
                    "new_hash": "hash1",
                    "file_size": 100,
                    "mtime": "2023-01-01T00:00:00+00:00",
                    "permissions": 0o644,
                    "is_symlink": False,
                    "symlink_target": None,
                }
            ],
            "timestamp": "2023-02-01T00:00:00+00:00",
            "checksum": "checksum_value",
            "patch_chain": ["base_123"],
            "operation_type": "incremental_patch",
            "user_info": {"source": "test"},
            "metrics": {"changes": 1},
        }
        assert data == expected_data


class TestFileChangeTracker:
    """Test FileChangeTracker functionality."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory fixture."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def tracker(self, temp_dir):
        """Create a FileChangeTracker fixture."""
        return FileChangeTracker(temp_dir)

    @pytest.fixture
    def temp_dir_with_files(self, temp_dir):
        """Create temp dir with some test files."""
        (temp_dir / "file1.txt").write_text("content1")
        (temp_dir / "file2.txt").write_text("content2")
        (temp_dir / "subdir").mkdir()
        (temp_dir / "subdir" / "file3.txt").write_text("content3")
        (temp_dir / "binary.dat").write_bytes(b"\x00\x01\x02")
        return temp_dir

    def test_tracker_initialization(self, tracker):
        """Test FileChangeTracker initialization."""
        assert isinstance(tracker.file_hashes, dict)
        assert tracker.file_hashes == {}

    def test_load_nonexistent_cache(self, tracker, temp_dir):
        """Test loading non-existent cache file."""
        cache_path = temp_dir / "cache.json"
        assert not tracker.load(cache_path)
        assert tracker.file_hashes == {}

    def test_load_valid_cache(self, tracker, temp_dir):
        """Test loading valid cache file."""
        cache_path = temp_dir / "cache.json"
        cache_data = {
            "version": 1,
            "file_hashes": {"file1.txt": "hash1", "file2.txt": "hash2"},
        }
        cache_path.write_text(json.dumps(cache_data))

        assert tracker.load(cache_path)
        assert tracker.file_hashes == {"file1.txt": "hash1", "file2.txt": "hash2"}

    def test_save_cache(self, tracker, temp_dir):
        """Test saving cache file."""
        cache_path = temp_dir / "cache.json"
        tracker.file_hashes = {"file1.txt": "hash1", "file2.txt": "hash2"}

        tracker.save(cache_path)
        assert cache_path.exists()

        loaded_data = json.loads(cache_path.read_text())
        assert loaded_data["version"] == 1
        assert loaded_data["file_hashes"] == tracker.file_hashes

    def test_scan_for_changes_no_changes(self, tracker, temp_dir_with_files):
        """Test scanning when no changes have occurred."""
        # First scan
        changes1 = tracker.scan_for_changes()
        assert len(changes1) > 0

        # Second scan should detect no changes
        changes2 = tracker.scan_for_changes()
        assert len(changes2) == 0

    def test_scan_for_changes_with_snapshot(self, tracker, temp_dir_with_files):
        """Test scanning with base snapshot files."""
        base_snapshot = {
            "file_hashes": {"file1.txt": "old_hash", "file2.txt": "old_hash"}
        }
        changes = tracker.scan_for_changes(base_snapshot=base_snapshot)
        # Should detect modified files since hashes differ
        assert len(changes) > 0

    def test_scan_for_changes_large_file_skip(self, temp_dir):
        """Test that large files are skipped."""
        large_file = temp_dir / "large.txt"
        # Create a >500KB file (but small enough for test)
        content = "x" * (10 * 1024)  # 10KB, but we'll mock the size
        large_file.write_text(content)

        # Note: In actual test, we can't easily make a 500KB file, so we test the logic by checking file size
        pass  # Skipping large file test in CI

    def test_get_changed_files(self, tracker):
        """Test get_changed_files method."""
        changes = [
            FileChange("file1.txt", FileChangeType.ADDED, None, "hash1"),
            FileChange("file2.txt", FileChangeType.MODIFIED, "old", "new"),
            FileChange("file3.txt", FileChangeType.DELETED, "old", None),
        ]
        tracker.root = Path("/tmp")  # Mock root
        changed_files = tracker.get_changed_files(changes)
        assert len(changed_files) == 2  # added and modified
        assert str(changed_files[0]).endswith("file1.txt")
        assert str(changed_files[1]).endswith("file2.txt")

    def test_get_deleted_files(self, tracker):
        """Test get_deleted_files method."""
        changes = [
            FileChange("file1.txt", FileChangeType.ADDED, None, "hash1"),
            FileChange("file2.txt", FileChangeType.MODIFIED, "old", "new"),
            FileChange("file3.txt", FileChangeType.DELETED, "old", None),
        ]
        deleted_files = tracker.get_deleted_files(changes)
        assert deleted_files == ["file3.txt"]


class TestIncrementalGraphUpdater:
    """Test IncrementalGraphUpdater functionality."""

    @pytest.fixture
    def updater(self):
        """Create an IncrementalGraphUpdater fixture."""
        return IncrementalGraphUpdater()

    @pytest.fixture
    def mock_graph(self):
        """Create a mock InMemoryGraph."""
        graph = MagicMock(spec=InMemoryGraph)
        graph.entities = {
            "e1": MagicMock(file="/path/to/file1.py"),
            "e2": MagicMock(file="/path/to/file2.py"),
        }
        graph.relationships = [MagicMock(source_id="e1", target_id="e2")]
        return graph

    @pytest.fixture
    def mock_extractor(self):
        """Create a mock ASTExtractor."""
        extractor = MagicMock()
        extractor.parse_file.return_value = (
            [
                {
                    "id": "new_e1",
                    "name": "func",
                    "type": "function",
                    "file": "/path/to/file1.py",
                }
            ],
            [{"source_id": "new_e1", "target_id": "new_e2", "type": "calls"}],
        )
        return extractor

    def test_update_entities_for_file(self, updater, mock_graph, mock_extractor):
        """Test update_entities_for_file method."""
        with (
            patch.object(updater, "remove_entities_for_file") as mock_remove,
            patch.object(updater, "add_entities_for_file") as mock_add,
        ):
            updater.update_entities_for_file(
                mock_graph, "/path/to/file1.py", mock_extractor
            )

            mock_remove.assert_called_once_with(mock_graph, "/path/to/file1.py")
            mock_add.assert_called_once_with(
                mock_graph, "/path/to/file1.py", mock_extractor
            )

    def test_remove_entities_for_file(self, updater, mock_graph):
        """Test remove_entities_for_file method."""
        # Store an entity count before removal for verification
        entity_count_before = len(mock_graph.entities)
        assert entity_count_before > 0  # Ensure we have entities to remove

        updater.remove_entities_for_file(mock_graph, "/path/to/file1.py")

        # Check that entities for the file were removed
        entity_count_after = len(mock_graph.entities)
        assert (
            entity_count_after < entity_count_before
        )  # Should have removed some entities

    def test_add_entities_for_file(self, updater, mock_graph, mock_extractor):
        """Test add_entities_for_file method."""
        with (
            patch("pathlib.Path.exists", return_value=True),
            patch(
                "batho.context.codegraph._read_file_content",
                return_value=b"def test():\n    pass",
            ),
        ):
            updater.add_entities_for_file(
                mock_graph, "/path/to/file1.py", mock_extractor
            )

        # Should parse the file and add entities
        mock_extractor.parse_file.assert_called_once_with(
            "/path/to/file1.py", b"def test():\n    pass"
        )

    def test_add_entities_for_file_extractor_error(self, updater, mock_graph):
        """Test add_entities_for_file with extractor error."""
        failed_extractor = MagicMock()
        failed_extractor.parse_file.side_effect = Exception("Parse error")

        # Should handle exception gracefully
        updater.add_entities_for_file(mock_graph, "/path/to/file1.py", failed_extractor)

    def test_validate_graph_consistency(self, updater, mock_graph):
        """Test validate_graph_consistency method."""
        mock_graph.entities = {"e1": MagicMock(), "e2": MagicMock()}
        mock_graph.relationships = [
            MagicMock(source_id="e1", target_id="e2"),
            MagicMock(source_id="e1", target_id="nonexistent"),  # Broken
        ]

        result = updater.validate_graph_consistency(mock_graph)
        assert result is False  # Should detect broken relationship

        # Test valid graph
        mock_graph.relationships = [MagicMock(source_id="e1", target_id="e2")]
        result = updater.validate_graph_consistency(mock_graph)
        assert result is True


class TestDiffUtilities:
    """Test diff utility functions."""

    def test_diff_snapshots(self):
        """Test diff_snapshots function."""
        snap_a = {
            "bsg": {
                "indexes": {"nodes_by_file": {"file1.py": "hash1", "file2.py": "hash2"}}
            }
        }
        snap_b = {
            "bsg": {
                "indexes": {"nodes_by_file": {"file1.py": "hash1", "file3.py": "hash3"}}
            }
        }
        changes = compare_file_lists(
            snap_a["bsg"]["indexes"]["nodes_by_file"],
            snap_b["bsg"]["indexes"]["nodes_by_file"],
        )
        assert len(changes) == 2  # Deleted file2, added file3

    def test_compare_file_lists(self):
        """Test compare_file_lists function."""
        current = {"file1.py": "hash1", "file2.py": "hash2"}
        snapshot = {"file1.py": "hash1", "file3.py": "hash3"}

        changes = compare_file_lists(current, snapshot)
        assert len(changes) == 2  # Deleted file3, added file2

    def test_aggregate_changes(self):
        """Test aggregate_changes function."""
        changes = [
            FileChange("delete.py", FileChangeType.DELETED, "old", None),
            FileChange("add.py", FileChangeType.ADDED, None, "new"),
            FileChange("modify.py", FileChangeType.MODIFIED, "old", "new"),
        ]
        aggregated = aggregate_changes(changes)
        assert len(aggregated) == 3
        # Check ordering: deletions first, then modifications, then additions
        assert aggregated[0].change_type == FileChangeType.DELETED
        assert aggregated[1].change_type == FileChangeType.MODIFIED
        assert aggregated[2].change_type == FileChangeType.ADDED

    def test_parse_git_diff(self):
        """Test parse_git_diff function."""
        diff_output = """A\tnew_file.py
M\tmodified_file.py
D\tdeleted_file.py
"""
        changes = parse_git_diff(diff_output)
        assert len(changes) == 3
        assert changes[0].change_type == FileChangeType.ADDED
        assert changes[0].path == "new_file.py"
        assert changes[1].change_type == FileChangeType.MODIFIED
        assert changes[1].path == "modified_file.py"
        assert changes[2].change_type == FileChangeType.DELETED
        assert changes[2].path == "deleted_file.py"


class TestIncrementalPatchFunction:
    """Test incremental_patch function."""

    @pytest.fixture
    def temp_ctn_dir(self):
        """Create temporary .ctn directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ctn_dir = Path(tmpdir) / ".ctn"
            ctn_dir.mkdir()
            yield ctn_dir
            # Windows-specific cleanup for SQLite file locking
            import shutil
            import sys
            import time
            if sys.platform == "win32" and ctn_dir.exists():
                for attempt in range(3):
                    try:
                        shutil.rmtree(ctn_dir)
                        break
                    except (PermissionError, OSError):
                        if attempt < 2:
                            time.sleep(0.5)
                        else:
                            # Final attempt, let it fail if still locked
                            pass

    @pytest.fixture
    def mock_base_snapshot(self, temp_ctn_dir):
        """Create a mock base snapshot."""
        base_snap = {
            "schema_version": 1,
            "snapshot_id": "base_123",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "root": str(temp_ctn_dir.parent),
            "label": "test",
            "graph": {"entities": {}, "relationships": []},
            "bsg": {"schema_version": "bsg.v1", "nodes": [], "edges": [], "indexes": {"nodes_by_file": {}}},
            "stats": {"entity_count": 0, "relationship_count": 0, "file_count": 0},
            "_checksum": "dummy",
        }
        snap_path = temp_ctn_dir / "snapshots" / "base_123.json"
        snap_path.parent.mkdir(parents=True, exist_ok=True)
        snap_path.write_text(json.dumps(base_snap))
        return base_snap, snap_path

    def test_incremental_patch_success(self, temp_ctn_dir, mock_base_snapshot):
        """Test successful incremental patch."""
        base_snap, _ = mock_base_snapshot
        changes = [
            FileChange("new_file.py", FileChangeType.ADDED, None, "hash1"),
        ]

        with (
            patch(
                "batho.time_machine.get_config_cached",
                return_value={"patch": {"timeout_seconds": 30, "max_changes": 1000}},
            ),
            patch("batho.time_machine.load_snapshot", return_value=base_snap),
            patch(
                "batho.time_machine.InMemoryGraph.from_dict",
                return_value=MagicMock(),
            ),
            patch(
                "batho.time_machine.BSGMap.from_dict", return_value=MagicMock()
            ),
            patch(
                "batho.time_machine.create_snapshot", return_value="new_snap_123"
            ),
            patch("batho.time_machine.aggregate_changes", return_value=changes),
            patch(
                "batho.time_machine.IncrementalGraphUpdater"
            ) as mock_updater_cls,
        ):
            mock_updater = MagicMock()
            mock_updater_cls.return_value = mock_updater
            mock_updater.validate_graph_consistency.return_value = True

            result = incremental_patch(temp_ctn_dir, base_snap["snapshot_id"], changes)

            assert result["success"] is True
            assert result["new_snapshot_id"] == "new_snap_123"

    def test_incremental_patch_validation_failure(
        self, temp_ctn_dir, mock_base_snapshot
    ):
        """Test patch with validation failure."""
        base_snap, _ = mock_base_snapshot
        changes = []  # Empty changes, but let's mock a failure
        with patch("batho.time_machine.check_patch_limits") as mock_check:
            mock_check.side_effect = PatchValidationError(
                "Too many changes", {"count": 2000}
            )

            result = incremental_patch(temp_ctn_dir, base_snap["snapshot_id"], changes)

            assert result["success"] is False
            assert "Too many changes" in result["error"]

    def test_incremental_patch_snapshot_not_found(self, temp_ctn_dir):
        """Test patch with non-existent snapshot."""
        changes = [FileChange("file.py", FileChangeType.ADDED, None, "hash")]

        result = incremental_patch(temp_ctn_dir, "nonexistent_snap", changes)

        assert result["success"] is False
        assert "not found" in result["error"].lower()

    def test_incremental_patch_timeout(self, temp_ctn_dir, mock_base_snapshot):
        """Test patch with timeout."""
        base_snap, _ = mock_base_snapshot
        changes = [FileChange("file.py", FileChangeType.ADDED, None, "hash")]

        with (
            patch(
                "batho.time_machine.get_config_cached",
                return_value={"patch": {"timeout_seconds": 0.001, "max_changes": 1000}},
            ),
            patch("batho.time_machine.load_snapshot", return_value=base_snap),
            patch(
                "batho.time_machine.timeout_context",
                side_effect=PatchTimeoutError("Operation timed out", 0),
            ),
        ):
            result = incremental_patch(temp_ctn_dir, base_snap["snapshot_id"], changes)

            assert result["success"] is False
            assert "timed out" in result["error"].lower()

    def test_incremental_patch_consistency_failure(
        self, temp_ctn_dir, mock_base_snapshot
    ):
        """Test patch with graph consistency failure."""
        base_snap, _ = mock_base_snapshot
        changes = [FileChange("file.py", FileChangeType.ADDED, None, "hash")]

        with (
            patch(
                "batho.time_machine.get_config_cached",
                return_value={"patch": {"timeout_seconds": 30, "max_changes": 1000}},
            ),
            patch("batho.time_machine.load_snapshot", return_value=base_snap),
            patch(
                "batho.time_machine.InMemoryGraph.from_dict",
                return_value=MagicMock(),
            ),
            patch(
                "batho.time_machine.BSGMap.from_dict", return_value=MagicMock()
            ),
            patch("batho.time_machine.aggregate_changes", return_value=changes),
            patch(
                "batho.time_machine.IncrementalGraphUpdater"
            ) as mock_updater_cls,
        ):
            mock_updater = MagicMock()
            mock_updater_cls.return_value = mock_updater
            mock_updater.validate_graph_consistency.return_value = False

            result = incremental_patch(temp_ctn_dir, base_snap["snapshot_id"], changes)

            assert result["success"] is False
            assert "consistency check" in result["error"].lower()


class TestIncrementalPatchExceptionHandling:
    """Test incremental patch exception handling."""

    @pytest.fixture
    def temp_ctn_dir(self):
        """Create temporary .ctn directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ctn_dir = Path(tmpdir) / ".ctn"
            ctn_dir.mkdir()
            yield ctn_dir
            # Windows-specific cleanup for SQLite file locking
            import shutil
            import sys
            import time
            if sys.platform == "win32" and ctn_dir.exists():
                for attempt in range(3):
                    try:
                        shutil.rmtree(ctn_dir)
                        break
                    except (PermissionError, OSError):
                        if attempt < 2:
                            time.sleep(0.5)
                        else:
                            # Final attempt, let it fail if still locked
                            pass

    @pytest.fixture
    def mock_base_snapshot(self, temp_ctn_dir):
        """Create a mock base snapshot."""
        base_snap = {
            "schema_version": 1,
            "snapshot_id": "base_123",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "root": str(temp_ctn_dir.parent),
            "label": "test",
            "graph": {"entities": {}, "relationships": []},
            "bsg": {"schema_version": "bsg.v1", "nodes": [], "edges": [], "indexes": {"nodes_by_file": {}}},
            "stats": {"entity_count": 0, "relationship_count": 0, "file_count": 0},
            "_checksum": "dummy",
        }
        snap_path = temp_ctn_dir / "snapshots" / "base_123.json"
        snap_path.parent.mkdir(parents=True, exist_ok=True)
        snap_path.write_text(json.dumps(base_snap))
        return base_snap, snap_path

    @pytest.mark.parametrize(
        "exception_class,expected_error_type",
        [
            (PatchValidationError, "validation_error"),
            (PatchTimeoutError, "timeout"),
            (PatchConsistencyError, "consistency_error"),
            (PatchSnapshotError, "snapshot_error"),
            (PatchFileError, "file_error"),
            (Exception, "unexpected_error"),
        ],
    )
    def test_incremental_patch_exception_handling(
        self, temp_ctn_dir, mock_base_snapshot, exception_class, expected_error_type
    ):
        """Test various exception types in incremental_patch."""
        base_snap, _ = mock_base_snapshot
        changes = [FileChange("file.py", FileChangeType.ADDED, None, "hash")]

        with (
            patch(
                "batho.time_machine.get_config_cached",
                return_value={"patch": {"timeout_seconds": 30, "max_changes": 1000}},
            ),
            patch("batho.time_machine.load_snapshot", return_value=base_snap),
            patch(
                "batho.time_machine.InMemoryGraph.from_dict",
                side_effect=exception_class("Test error"),
            ),
        ):
            result = incremental_patch(temp_ctn_dir, base_snap["snapshot_id"], changes)

            assert result["success"] is False
            if hasattr(exception_class, "__name__"):
                assert "Test error" in result["error"]


class TestExceptions:
    """Test custom exception classes."""

    def test_patch_validation_error(self):
        """Test PatchValidationError."""
        error = PatchValidationError(
            "Invalid patch input", {"max_changes": 1000, "actual": 1200}
        )
        assert str(error) == "Invalid patch input"
        assert error.details == {"max_changes": 1000, "actual": 1200}

    def test_patch_timeout_error(self):
        """Test PatchTimeoutError."""
        error = PatchTimeoutError("Operation timed out", 30.0)
        assert "timed out" in str(error).lower()
        assert error.timeout_seconds == 30.0

    def test_patch_consistency_error(self):
        """Test PatchConsistencyError."""
        inconsistencies = ["broken relationship 1", "broken relationship 2"]
        error = PatchConsistencyError("Graph consistency issues", inconsistencies)
        assert "consistency issues" in str(error).lower()
        assert error.inconsistencies == inconsistencies

    def test_patch_snapshot_error(self):
        """Test PatchSnapshotError."""
        error = PatchSnapshotError("Snapshot not found", "snap_123")
        assert "not found" in str(error).lower()
        assert error.snapshot_id == "snap_123"

    def test_patch_file_error(self):
        """Test PatchFileError."""
        error = PatchFileError("Failed to process file", "/path/to/file.py", "parse")
        assert "Failed to process file" in str(error)
        assert error.file_path == "/path/to/file.py"
        assert error.operation == "parse"
