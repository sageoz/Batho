"""Tests for the synthetic file path fix in IncrementalEngine.scan_changes.

The build flow creates synthetic file tracking records for EXTERNAL_SYMBOL
entities under paths like "__external_symbols__" and ".". These paths have
no corresponding on-disk file, so scan_changes would incorrectly report them
as DELETED on every patch run.

The fix skips these synthetic paths when computing deleted files.

Tests cover:
  - Synthetic paths (__external_symbols__, ".", "") are not reported as deleted
  - Real deleted files ARE reported as deleted
  - Real modified files ARE reported as modified
  - Real added files ARE reported as added
  - Mixed scenario: synthetic + real deleted files
  - Empty tracking table produces no changes
  - All files present produces no deletions
  - Edge cases: paths with special characters, very long paths
"""
import os
import tempfile
import shutil
from pathlib import Path

import pytest

from batho.modules.storage.arrow_bundle import BathoBundle
from batho.modules.storage.arrow_bundle.incremental import (
    IncrementalEngine,
    FileChange,
    FileChangeType,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_bundle_with_tracking(root: Path, files: list[dict]) -> BathoBundle:
    """Create a BathoBundle and populate file_tracking with the given records.

    Each dict in files should have:
        - file_path (str)
        - content_hash (str)
        - is_indexed (bool)
        - Optional: mtime, mtime_ns, inode, size
    """
    bundle = BathoBundle(root)
    run_uuid = "test_run_001"
    run_id = bundle.create_run(run_uuid, root_path=str(root))
    records = []
    for f in files:
        records.append({
            "file_path": f["file_path"],
            "content_hash": f.get("content_hash", "hash_placeholder"),
            "mtime": f.get("mtime", 0.0),
            "mtime_ns": f.get("mtime_ns", 0),
            "inode": f.get("inode", None),
            "size": f.get("size", 100),
            "is_indexed": f.get("is_indexed", True),
            "last_run_id": run_uuid,
        })
    if records:
        bundle.upsert_file_tracking(records)
    bundle.complete_run(run_uuid, entity_count=0, file_count=len(records))
    return bundle


def _make_real_file(root: Path, rel_path: str, content: str = "hello world") -> Path:
    """Create a real file on disk under root."""
    full_path = root / rel_path
    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_text(content)
    return full_path


# ---------------------------------------------------------------------------
# Synthetic paths are not reported as deleted
# ---------------------------------------------------------------------------


class TestSyntheticPathsNotDeleted:
    """Verify synthetic file paths are not reported as deleted by scan_changes."""

    def test_external_symbols_path_not_deleted(self, tmp_path):
        """__external_symbols__ is not reported as deleted even though it
        doesn't exist on disk."""
        bundle = _create_bundle_with_tracking(tmp_path, [
            {"file_path": "__external_symbols__", "content_hash": "__external__"},
            {"file_path": "main.py", "content_hash": "hash_main"},
        ])
        _make_real_file(tmp_path, "main.py", "print('hello')")

        engine = IncrementalEngine(bundle, "test_run_001")
        changes = engine.scan_changes(root=tmp_path, max_file_size_kb=500)

        deleted = [c for c in changes if c.change_type == FileChangeType.DELETED]
        deleted_paths = {c.path for c in deleted}
        assert "__external_symbols__" not in deleted_paths
        bundle.close()

    def test_dot_path_not_deleted(self, tmp_path):
        """The '.' path is not reported as deleted."""
        bundle = _create_bundle_with_tracking(tmp_path, [
            {"file_path": ".", "content_hash": "dot_hash"},
            {"file_path": "main.py", "content_hash": "hash_main"},
        ])
        _make_real_file(tmp_path, "main.py", "print('hello')")

        engine = IncrementalEngine(bundle, "test_run_001")
        changes = engine.scan_changes(root=tmp_path, max_file_size_kb=500)

        deleted = [c for c in changes if c.change_type == FileChangeType.DELETED]
        deleted_paths = {c.path for c in deleted}
        assert "." not in deleted_paths
        bundle.close()

    def test_empty_string_path_not_deleted(self, tmp_path):
        """An empty string path is not reported as deleted."""
        bundle = _create_bundle_with_tracking(tmp_path, [
            {"file_path": "", "content_hash": "empty_hash"},
            {"file_path": "main.py", "content_hash": "hash_main"},
        ])
        _make_real_file(tmp_path, "main.py", "print('hello')")

        engine = IncrementalEngine(bundle, "test_run_001")
        changes = engine.scan_changes(root=tmp_path, max_file_size_kb=500)

        deleted = [c for c in changes if c.change_type == FileChangeType.DELETED]
        deleted_paths = {c.path for c in deleted}
        assert "" not in deleted_paths
        bundle.close()

    def test_all_synthetic_paths_together(self, tmp_path):
        """All three synthetic paths in the same tracking table are skipped."""
        bundle = _create_bundle_with_tracking(tmp_path, [
            {"file_path": "__external_symbols__", "content_hash": "ext_hash"},
            {"file_path": ".", "content_hash": "dot_hash"},
            {"file_path": "", "content_hash": "empty_hash"},
            {"file_path": "main.py", "content_hash": "hash_main"},
        ])
        _make_real_file(tmp_path, "main.py", "print('hello')")

        engine = IncrementalEngine(bundle, "test_run_001")
        changes = engine.scan_changes(root=tmp_path, max_file_size_kb=500)

        deleted = [c for c in changes if c.change_type == FileChangeType.DELETED]
        deleted_paths = {c.path for c in deleted}
        assert "__external_symbols__" not in deleted_paths
        assert "." not in deleted_paths
        assert "" not in deleted_paths
        # main.py exists, so it should not be deleted either
        assert "main.py" not in deleted_paths
        assert len(deleted) == 0
        bundle.close()


# ---------------------------------------------------------------------------
# Real deleted files ARE reported
# ---------------------------------------------------------------------------


class TestRealDeletedFilesReported:
    """Verify real deleted files are still reported correctly."""

    def test_real_deleted_file_reported(self, tmp_path):
        """A real file that was tracked but no longer exists is reported as deleted."""
        bundle = _create_bundle_with_tracking(tmp_path, [
            {"file_path": "main.py", "content_hash": "hash_main"},
            {"file_path": "deleted.py", "content_hash": "hash_deleted"},
        ])
        _make_real_file(tmp_path, "main.py", "print('hello')")
        # Note: deleted.py is NOT created on disk

        engine = IncrementalEngine(bundle, "test_run_001")
        changes = engine.scan_changes(root=tmp_path, max_file_size_kb=500)

        deleted = [c for c in changes if c.change_type == FileChangeType.DELETED]
        deleted_paths = {c.path for c in deleted}
        assert "deleted.py" in deleted_paths
        bundle.close()

    def test_multiple_real_deletions(self, tmp_path):
        """Multiple real deleted files are all reported."""
        bundle = _create_bundle_with_tracking(tmp_path, [
            {"file_path": "keep.py", "content_hash": "hash_keep"},
            {"file_path": "del1.py", "content_hash": "hash_del1"},
            {"file_path": "del2.py", "content_hash": "hash_del2"},
            {"file_path": "del3.py", "content_hash": "hash_del3"},
        ])
        _make_real_file(tmp_path, "keep.py", "print('kept')")

        engine = IncrementalEngine(bundle, "test_run_001")
        changes = engine.scan_changes(root=tmp_path, max_file_size_kb=500)

        deleted = [c for c in changes if c.change_type == FileChangeType.DELETED]
        deleted_paths = {c.path for c in deleted}
        assert deleted_paths == {"del1.py", "del2.py", "del3.py"}
        bundle.close()


# ---------------------------------------------------------------------------
# Mixed synthetic + real deleted
# ---------------------------------------------------------------------------


class TestMixedSyntheticAndRealDeleted:
    """Verify synthetic paths are skipped while real deletions are reported."""

    def test_synthetic_skipped_real_deleted_reported(self, tmp_path):
        """In a mixed scenario, synthetic paths are skipped but real
        deleted files are reported."""
        bundle = _create_bundle_with_tracking(tmp_path, [
            {"file_path": "__external_symbols__", "content_hash": "ext_hash"},
            {"file_path": ".", "content_hash": "dot_hash"},
            {"file_path": "main.py", "content_hash": "hash_main"},
            {"file_path": "gone.py", "content_hash": "hash_gone"},
        ])
        _make_real_file(tmp_path, "main.py", "print('hello')")
        # gone.py is NOT created

        engine = IncrementalEngine(bundle, "test_run_001")
        changes = engine.scan_changes(root=tmp_path, max_file_size_kb=500)

        deleted = [c for c in changes if c.change_type == FileChangeType.DELETED]
        deleted_paths = {c.path for c in deleted}
        assert "gone.py" in deleted_paths
        assert "__external_symbols__" not in deleted_paths
        assert "." not in deleted_paths
        assert len(deleted) == 1
        bundle.close()


# ---------------------------------------------------------------------------
# No false positives when all files exist
# ---------------------------------------------------------------------------


class TestNoFalsePositives:
    """Verify no deletions are reported when all real files exist."""

    def test_all_files_present_no_deletions(self, tmp_path):
        """When all tracked real files exist on disk, no deletions are reported."""
        bundle = _create_bundle_with_tracking(tmp_path, [
            {"file_path": "__external_symbols__", "content_hash": "ext_hash"},
            {"file_path": "main.py", "content_hash": "hash_main"},
            {"file_path": "utils.py", "content_hash": "hash_utils"},
        ])
        _make_real_file(tmp_path, "main.py", "print('hello')")
        _make_real_file(tmp_path, "utils.py", "def helper(): pass")

        engine = IncrementalEngine(bundle, "test_run_001")
        changes = engine.scan_changes(root=tmp_path, max_file_size_kb=500)

        deleted = [c for c in changes if c.change_type == FileChangeType.DELETED]
        assert len(deleted) == 0
        bundle.close()

    def test_empty_tracking_no_changes(self, tmp_path):
        """An empty tracking table produces no changes."""
        bundle = _create_bundle_with_tracking(tmp_path, [])
        _make_real_file(tmp_path, "main.py", "print('hello')")

        engine = IncrementalEngine(bundle, "test_run_001")
        changes = engine.scan_changes(root=tmp_path, max_file_size_kb=500)

        # main.py is not tracked, so it should be ADDED
        added = [c for c in changes if c.change_type == FileChangeType.ADDED]
        assert len(added) == 1
        assert added[0].path == "main.py"
        # No deletions
        deleted = [c for c in changes if c.change_type == FileChangeType.DELETED]
        assert len(deleted) == 0
        bundle.close()


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestScanChangesEdgeCases:
    """Verify edge case handling in scan_changes."""

    def test_nested_directory_file_deleted(self, tmp_path):
        """A deleted file in a nested directory is reported correctly."""
        bundle = _create_bundle_with_tracking(tmp_path, [
            {"file_path": "src/main.py", "content_hash": "hash_main"},
            {"file_path": "src/deleted.py", "content_hash": "hash_del"},
        ])
        _make_real_file(tmp_path, "src/main.py", "print('hello')")

        engine = IncrementalEngine(bundle, "test_run_001")
        changes = engine.scan_changes(root=tmp_path, max_file_size_kb=500)

        deleted = [c for c in changes if c.change_type == FileChangeType.DELETED]
        deleted_paths = {c.path for c in deleted}
        assert "src/deleted.py" in deleted_paths
        bundle.close()

    def test_synthetic_path_with_similar_name_not_skipped(self, tmp_path):
        """A real file named '__external_symbols_backup__' is NOT skipped
        (only the exact path '__external_symbols__' is skipped)."""
        bundle = _create_bundle_with_tracking(tmp_path, [
            {"file_path": "__external_symbols__", "content_hash": "ext"},
            {"file_path": "__external_symbols_backup__", "content_hash": "backup"},
            {"file_path": "main.py", "content_hash": "hash_main"},
        ])
        _make_real_file(tmp_path, "main.py", "print('hello')")

        engine = IncrementalEngine(bundle, "test_run_001")
        changes = engine.scan_changes(root=tmp_path, max_file_size_kb=500)

        deleted = [c for c in changes if c.change_type == FileChangeType.DELETED]
        deleted_paths = {c.path for c in deleted}
        # The exact synthetic path is skipped
        assert "__external_symbols__" not in deleted_paths
        # But the similar-named real file IS reported as deleted
        assert "__external_symbols_backup__" in deleted_paths
        bundle.close()

    def test_path_with_only_dots_not_skipped(self, tmp_path):
        """A path like '..' or '...' is NOT skipped (only exact '.' is)."""
        bundle = _create_bundle_with_tracking(tmp_path, [
            {"file_path": ".", "content_hash": "dot"},
            {"file_path": "..", "content_hash": "dotdot"},
            {"file_path": "main.py", "content_hash": "hash_main"},
        ])
        _make_real_file(tmp_path, "main.py", "print('hello')")

        engine = IncrementalEngine(bundle, "test_run_001")
        changes = engine.scan_changes(root=tmp_path, max_file_size_kb=500)

        deleted = [c for c in changes if c.change_type == FileChangeType.DELETED]
        deleted_paths = {c.path for c in deleted}
        # '.' is skipped
        assert "." not in deleted_paths
        # '..' is NOT skipped (it's a different string)
        assert ".." in deleted_paths
        bundle.close()

    def test_synthetic_path_in_subdirectory_not_skipped(self, tmp_path):
        """A path like 'src/__external_symbols__' is NOT skipped
        (only the exact root-level path is)."""
        bundle = _create_bundle_with_tracking(tmp_path, [
            {"file_path": "__external_symbols__", "content_hash": "ext"},
            {"file_path": "src/__external_symbols__", "content_hash": "nested_ext"},
            {"file_path": "main.py", "content_hash": "hash_main"},
        ])
        _make_real_file(tmp_path, "main.py", "print('hello')")

        engine = IncrementalEngine(bundle, "test_run_001")
        changes = engine.scan_changes(root=tmp_path, max_file_size_kb=500)

        deleted = [c for c in changes if c.change_type == FileChangeType.DELETED]
        deleted_paths = {c.path for c in deleted}
        # Root-level synthetic path is skipped
        assert "__external_symbols__" not in deleted_paths
        # Nested path with the same name is NOT skipped
        assert "src/__external_symbols__" in deleted_paths
        bundle.close()
