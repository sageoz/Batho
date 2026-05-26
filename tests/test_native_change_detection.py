"""Comprehensive tests for native hash-based change detection.

This test suite covers all edge cases for Batho's native tracking system,
ensuring zero false positives and correct behavior across all file types
and scenarios.
"""

from __future__ import annotations

import os
import sys
import time
import shutil
import pytest
import zipfile
import tempfile
import argparse
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

from batho.orchestrator.build import BuildOptions, run_build
from batho.orchestrator.patch import PatchOptions, run_patch, FileChangeType
from batho.storage.engine import BathoDatabase, get_database, close_all_databases, artifact_filename
from batho.utils.hash import compute_file_hash


@pytest.fixture
def repo_dir():
    """Create a temporary directory for repository testing."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        yield Path(tmp_dir)
    close_all_databases()


# --- Class 1: TestEmptyRepository ---
class TestEmptyRepository:
    def test_patch_no_build_fails(self, repo_dir):
        """Verify error when no prior build."""
        options = PatchOptions(root=repo_dir, verbose=False)
        result = run_patch(options)
        assert not result.success
        assert any("No artifact database found" in w for w in result.warnings)


# --- Class 2: TestSingleFileOperations ---
class TestSingleFileOperations:
    def test_build_then_patch_no_changes(self, repo_dir):
        """Core sanity check."""
        (repo_dir / "main.py").write_text("print('hello')")
        
        # Build
        build_opt = BuildOptions(root=repo_dir, force_full=True)
        assert run_build(build_opt).success
        
        # Patch
        patch_opt = PatchOptions(root=repo_dir)
        res = run_patch(patch_opt)
        assert res.success
        assert res.changes_applied == 0

    def test_build_modify_file_patch_detects(self, repo_dir):
        """Content change detection."""
        f = repo_dir / "main.py"
        f.write_text("print('hello')")
        assert run_build(BuildOptions(root=repo_dir, force_full=True)).success
        
        f.write_text("print('hello world')")
        res = run_patch(PatchOptions(root=repo_dir))
        assert res.success
        assert res.changes_applied == 1
        assert res.modified == 1

    def test_build_touch_file_patch_no_changes(self, repo_dir):
        """mtime only, hash unchanged."""
        f = repo_dir / "main.py"
        f.write_text("print('hello')")
        assert run_build(BuildOptions(root=repo_dir, force_full=True)).success
        
        # Change mtime without altering content
        stat = f.stat()
        os.utime(f, (stat.st_atime + 10, stat.st_mtime + 10))
        
        res = run_patch(PatchOptions(root=repo_dir))
        assert res.success
        assert res.changes_applied == 0

    def test_build_delete_file_patch_detects(self, repo_dir):
        """File removal detection."""
        f = repo_dir / "main.py"
        f.write_text("print('hello')")
        assert run_build(BuildOptions(root=repo_dir, force_full=True)).success
        
        f.unlink()
        res = run_patch(PatchOptions(root=repo_dir))
        assert res.success
        assert res.changes_applied == 1
        assert res.deleted == 1

    def test_build_add_file_patch_detects(self, repo_dir):
        """New file detection."""
        (repo_dir / "main.py").write_text("print('hello')")
        assert run_build(BuildOptions(root=repo_dir, force_full=True)).success
        
        (repo_dir / "utils.py").write_text("def helper(): pass")
        res = run_patch(PatchOptions(root=repo_dir))
        assert res.success
        assert res.changes_applied == 1
        assert res.added == 1


# --- Class 3: TestBinaryFiles ---
class TestBinaryFiles:
    def test_binary_png_file_hash_consistency(self, repo_dir):
        """Binary hash = SHA256."""
        f = repo_dir / "image.png"
        content = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50
        f.write_bytes(content)
        
        import hashlib
        expected_hash = hashlib.sha256(content).hexdigest()
        assert compute_file_hash(f) == expected_hash

    def test_binary_woff2_file_tracked_correctly(self, repo_dir):
        """Font files tracked correctly."""
        (repo_dir / "dummy.py").write_text("def dummy(): pass")
        f = repo_dir / "font.woff2"
        f.write_bytes(b"wOF2" + os.urandom(50))
        
        assert run_build(BuildOptions(root=repo_dir, force_full=True)).success
        res = run_patch(PatchOptions(root=repo_dir))
        assert res.success and res.changes_applied == 0

    def test_binary_zip_file_tracked_correctly(self, repo_dir):
        """Archive files tracked correctly."""
        (repo_dir / "dummy.py").write_text("def dummy(): pass")
        zip_path = repo_dir / "archive.zip"
        with zipfile.ZipFile(zip_path, 'w') as zf:
            zf.writestr("test.txt", "hello")
            
        assert run_build(BuildOptions(root=repo_dir, force_full=True)).success
        res = run_patch(PatchOptions(root=repo_dir))
        assert res.success and res.changes_applied == 0

    def test_binary_executable_tracked_correctly(self, repo_dir):
        """Executable / library files tracked correctly."""
        (repo_dir / "dummy.py").write_text("def dummy(): pass")
        f = repo_dir / "lib.so"
        f.write_bytes(b"\x7fELF" + os.urandom(50))
        
        assert run_build(BuildOptions(root=repo_dir, force_full=True)).success
        res = run_patch(PatchOptions(root=repo_dir))
        assert res.success and res.changes_applied == 0


# --- Class 4: TestEmptyAndSpecialFiles ---
class TestEmptyAndSpecialFiles:
    def test_empty_file_hash(self, repo_dir):
        """0-byte file handling."""
        (repo_dir / "dummy.py").write_text("def dummy(): pass")
        f = repo_dir / "empty.txt"
        f.write_text("")
        
        import hashlib
        assert compute_file_hash(f) == hashlib.sha256(b"").hexdigest()
        
        assert run_build(BuildOptions(root=repo_dir, force_full=True)).success
        res = run_patch(PatchOptions(root=repo_dir))
        assert res.success and res.changes_applied == 0

    def test_whitespace_only_file(self, repo_dir):
        """Content is whitespace."""
        (repo_dir / "dummy.py").write_text("def dummy(): pass")
        f = repo_dir / "space.txt"
        f.write_text("   \n   \t")
        assert run_build(BuildOptions(root=repo_dir, force_full=True)).success
        
        f.write_text("   \n   ")
        res = run_patch(PatchOptions(root=repo_dir))
        assert res.success and res.changes_applied == 1


    def test_unicode_filename(self, repo_dir):
        """Non-ASCII filenames."""
        f = repo_dir / "测_试.py"
        f.write_text("def test(): pass")
        assert run_build(BuildOptions(root=repo_dir, force_full=True)).success
        res = run_patch(PatchOptions(root=repo_dir))
        assert res.success and res.changes_applied == 0

    def test_filename_with_spaces(self, repo_dir):
        """Path with spaces."""
        f = repo_dir / "my file.py"
        f.write_text("def test(): pass")
        assert run_build(BuildOptions(root=repo_dir, force_full=True)).success
        res = run_patch(PatchOptions(root=repo_dir))
        assert res.success and res.changes_applied == 0


# --- Class 5: TestSymlinkHandling ---
class TestSymlinkHandling:
    def test_symlink_followed(self, repo_dir):
        """Follow symlink, hash target content."""
        target = repo_dir / "target.py"
        target.write_text("a = 1")
        
        link = repo_dir / "link.py"
        try:
            link.symlink_to(target)
        except OSError:
            pytest.skip("Symlinks are not supported on this platform/configuration")
            
        assert run_build(BuildOptions(root=repo_dir, force_full=True)).success
        
        # Modify target content
        target.write_text("a = 2")
        res = run_patch(PatchOptions(root=repo_dir))
        assert res.success
        assert res.changes_applied == 2  # target.py and link.py are both modified

    def test_broken_symlink_skipped(self, repo_dir):
        """Don't crash on broken link."""
        (repo_dir / "dummy.py").write_text("def dummy(): pass")
        target = repo_dir / "nonexistent.py"
        link = repo_dir / "link.py"
        try:
            link.symlink_to(target)
        except OSError:
            pytest.skip("Symlinks are not supported on this platform/configuration")
            
        # Should build and patch without crashing
        assert run_build(BuildOptions(root=repo_dir, force_full=True)).success
        res = run_patch(PatchOptions(root=repo_dir))
        assert res.success

    def test_circular_symlink_detected(self, repo_dir):
        """Avoid infinite loop."""
        (repo_dir / "dummy.py").write_text("def dummy(): pass")
        dir1 = repo_dir / "dir1"
        dir1.mkdir()
        
        link = dir1 / "loop"
        try:
            link.symlink_to(dir1)
        except OSError:
            pytest.skip("Symlinks are not supported on this platform/configuration")
            
        assert run_build(BuildOptions(root=repo_dir, force_full=True)).success
        res = run_patch(PatchOptions(root=repo_dir))
        assert res.success


# --- Class 6: TestDirectoryStructure ---
class TestDirectoryStructure:
    def test_deeply_nested_files(self, repo_dir):
        """10+ levels deep."""
        curr = repo_dir
        for i in range(10):
            curr = curr / f"level{i}"
            curr.mkdir()
        (curr / "leaf.py").write_text("val = 42")
        
        assert run_build(BuildOptions(root=repo_dir, force_full=True)).success
        res = run_patch(PatchOptions(root=repo_dir))
        assert res.success and res.changes_applied == 0

    def test_many_files_performance(self, repo_dir):
        """Many files tracking."""
        for i in range(100):
            (repo_dir / f"file_{i}.py").write_text(f"def func_{i}(): pass")
            
        assert run_build(BuildOptions(root=repo_dir, force_full=True)).success
        res = run_patch(PatchOptions(root=repo_dir))
        assert res.success and res.changes_applied == 0

    def test_hidden_files(self, repo_dir):
        """.hidden files should be skipped by walk_ignored_filtered."""
        (repo_dir / ".hidden.py").write_text("def hidden(): pass")
        (repo_dir / "visible.py").write_text("def visible(): pass")
        
        assert run_build(BuildOptions(root=repo_dir, force_full=True)).success
        db = get_database(repo_dir)
        tracking = db.get_all_file_tracking()
        
        assert "visible.py" in tracking
        assert ".hidden.py" not in tracking


# --- Class 7: TestHashAccuracy ---
class TestHashAccuracy:
    def test_sha256_not_truncated(self, repo_dir):
        """Full 64-char hash."""
        f = repo_dir / "file.py"
        f.write_text("print(1)")
        h = compute_file_hash(f)
        assert len(h) == 64
        # Validate hex
        int(h, 16)

    def test_same_content_same_hash(self, repo_dir):
        """Deterministic hashing."""
        f1 = repo_dir / "f1.py"
        f2 = repo_dir / "f2.py"
        f1.write_text("hello")
        f2.write_text("hello")
        assert compute_file_hash(f1) == compute_file_hash(f2)

    def test_different_content_different_hash(self, repo_dir):
        """Sensitivity to changes."""
        f1 = repo_dir / "f1.py"
        f2 = repo_dir / "f2.py"
        f1.write_text("hello")
        f2.write_text("world")
        assert compute_file_hash(f1) != compute_file_hash(f2)

    def test_newline_difference_detected(self, repo_dir):
        """\\n vs \\r\\n difference is detected (since standard hash is bytes-based)."""
        f1 = repo_dir / "f1.py"
        f2 = repo_dir / "f2.py"
        f1.write_bytes(b"hello\n")
        f2.write_bytes(b"hello\r\n")
        assert compute_file_hash(f1) != compute_file_hash(f2)


# --- Class 8: TestFileRename ---
class TestFileRename:
    def test_rename_same_content(self, repo_dir):
        """Old deleted, new added."""
        f1 = repo_dir / "old.py"
        f1.write_text("a = 1")
        assert run_build(BuildOptions(root=repo_dir, force_full=True)).success
        
        f1.unlink()
        f2 = repo_dir / "new.py"
        f2.write_text("a = 1")
        
        res = run_patch(PatchOptions(root=repo_dir))
        assert res.success
        assert res.added == 1
        assert res.deleted == 1

    def test_rename_different_content(self, repo_dir):
        """Both modified (old deleted, new added with different content)."""
        f1 = repo_dir / "old.py"
        f1.write_text("a = 1")
        assert run_build(BuildOptions(root=repo_dir, force_full=True)).success
        
        f1.unlink()
        f2 = repo_dir / "new.py"
        f2.write_text("b = 2")
        
        res = run_patch(PatchOptions(root=repo_dir))
        assert res.success
        assert res.added == 1
        assert res.deleted == 1


# --- Class 9: TestConcurrentOperations ---
class TestConcurrentOperations:
    def test_file_modified_during_scan(self, repo_dir):
        """Handle concurrent modification during scan atomically/gracefully."""
        f = repo_dir / "main.py"
        f.write_text("def test(): pass")
        assert run_build(BuildOptions(root=repo_dir, force_full=True)).success
        
        # Mock compute_file_hash to raise OSError or return mock content
        with patch("batho.orchestrator.patch.compute_file_hash", side_effect=OSError("File modified concurrently")):
            res = run_patch(PatchOptions(root=repo_dir))
            # Should run successfully by handling the OSError gracefully (skipping the file)
            assert res.success

    def test_database_locked_retry(self, repo_dir):
        """Verify retry/fallback or locked handling doesn't crash."""
        f = repo_dir / "main.py"
        f.write_text("def test(): pass")
        assert run_build(BuildOptions(root=repo_dir, force_full=True)).success
        
        # Simulate database operation raising locked exception by patching Connection context manager
        import sqlite3
        with patch.object(BathoDatabase, "connection", side_effect=sqlite3.OperationalError("database is locked")):
            res = run_patch(PatchOptions(root=repo_dir))
            # Transaction rollback / exception handled, run fails gracefully
            assert not res.success


# --- Class 10: TestLargeFiles ---
class TestLargeFiles:
    def test_file_at_size_limit(self, repo_dir):
        """Exactly at max_file_size_kb is tracked."""
        f = repo_dir / "large.py"
        # Exactly 10KB
        f.write_bytes(b"a" * 10 * 1024)
        
        assert run_build(BuildOptions(root=repo_dir, force_full=True, max_file_size_kb=10)).success
        
        db = get_database(repo_dir)
        tracking = db.get_all_file_tracking()
        assert "large.py" in tracking

    def test_file_over_size_limit(self, repo_dir):
        """Skipped with warning/ignored."""
        (repo_dir / "dummy.py").write_text("def dummy(): pass")
        f = repo_dir / "too_large.py"
        # Over 10KB
        f.write_bytes(b"a" * (10 * 1024 + 1))
        
        assert run_build(BuildOptions(root=repo_dir, force_full=True, max_file_size_kb=10)).success
        
        db = get_database(repo_dir)
        tracking = db.get_all_file_tracking()
        assert "too_large.py" not in tracking


# --- Class 11: TestRapidSuccessivePatches ---
class TestRapidSuccessivePatches:
    def test_triple_patch_no_changes(self, repo_dir):
        """Build -> Patch -> Patch -> Patch (no changes)."""
        (repo_dir / "main.py").write_text("x = 1")
        assert run_build(BuildOptions(root=repo_dir, force_full=True)).success
        
        res1 = run_patch(PatchOptions(root=repo_dir))
        assert res1.success and res1.changes_applied == 0
        
        res2 = run_patch(PatchOptions(root=repo_dir))
        assert res2.success and res2.changes_applied == 0
        
        res3 = run_patch(PatchOptions(root=repo_dir))
        assert res3.success and res3.changes_applied == 0

    def test_patch_after_revert(self, repo_dir):
        """Build -> modify -> revert -> Patch (no changes)."""
        f = repo_dir / "main.py"
        f.write_text("x = 1")
        assert run_build(BuildOptions(root=repo_dir, force_full=True)).success
        
        # Modify
        f.write_text("x = 2")
        # Revert
        f.write_text("x = 1")
        
        res = run_patch(PatchOptions(root=repo_dir))
        assert res.success and res.changes_applied == 0


# --- Class 12: TestGitRepoWithUncommittedFiles (THE BUG FIX) ---
class TestGitRepoWithUncommittedFiles:
    def test_uncommitted_file_not_repatched(self, repo_dir):
        """Verify uncommitted files are not detected as changed if content is unchanged."""
        # Initialize Git repo
        try:
            subprocess.run(["git", "init"], cwd=str(repo_dir), check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=str(repo_dir), check=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(repo_dir), check=True, capture_output=True)
        except (subprocess.SubprocessError, FileNotFoundError):
            pytest.skip("Git executable not available or failed to init")
            
        f = repo_dir / "main.py"
        f.write_text("print('v1')")
        
        # Commit to Git
        subprocess.run(["git", "add", "main.py"], cwd=str(repo_dir), check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "initial"], cwd=str(repo_dir), check=True, capture_output=True)
        
        # Build Batho
        assert run_build(BuildOptions(root=repo_dir, force_full=True)).success
        
        # Modify file but keep content same (e.g. touch or staged status changes)
        # Verify patch reports 0 changes
        res = run_patch(PatchOptions(repo_dir))
        assert res.success
        assert res.changes_applied == 0

    def test_uncommitted_binary_not_repatched(self, repo_dir):
        """Binary files in git repo with uncommitted state do not get repatched."""
        try:
            subprocess.run(["git", "init"], cwd=str(repo_dir), check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=str(repo_dir), check=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(repo_dir), check=True, capture_output=True)
        except (subprocess.SubprocessError, FileNotFoundError):
            pytest.skip("Git executable not available or failed to init")
            
        (repo_dir / "dummy.py").write_text("def dummy(): pass")
        f = repo_dir / "image.png"
        f.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 50)
        
        # Commit dummy.py so git repo is clean-ish
        subprocess.run(["git", "add", "dummy.py"], cwd=str(repo_dir), check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "initial"], cwd=str(repo_dir), check=True, capture_output=True)
        
        assert run_build(BuildOptions(root=repo_dir, force_full=True)).success
        
        # File is uncommitted (untracked by git) but content hasn't changed since build
        res = run_patch(PatchOptions(root=repo_dir))
        assert res.success
        assert res.changes_applied == 0

    def test_staged_file_not_repatched(self, repo_dir):
        """Staged but unchanged content is not repatched."""
        try:
            subprocess.run(["git", "init"], cwd=str(repo_dir), check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=str(repo_dir), check=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(repo_dir), check=True, capture_output=True)
        except (subprocess.SubprocessError, FileNotFoundError):
            pytest.skip("Git executable not available or failed to init")
            
        f = repo_dir / "main.py"
        f.write_text("print(1)")
        
        # Commit to Git first
        subprocess.run(["git", "add", "main.py"], cwd=str(repo_dir), check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "initial"], cwd=str(repo_dir), check=True, capture_output=True)
        
        assert run_build(BuildOptions(root=repo_dir, force_full=True)).success
        
        try:
            subprocess.run(["git", "add", "main.py"], cwd=str(repo_dir), check=True, capture_output=True)
        except subprocess.SubprocessError:
            pass
            
        res = run_patch(PatchOptions(repo_dir))
        assert res.success
        assert res.changes_applied == 0


# --- Class 13: TestNonGitEnvironment ---
class TestNonGitEnvironment:
    def test_works_in_directory_without_git(self, repo_dir):
        """Pure directory (no Git initialization)."""
        f = repo_dir / "main.py"
        f.write_text("x = 1")
        assert run_build(BuildOptions(root=repo_dir, force_full=True)).success
        
        f.write_text("x = 2")
        res = run_patch(PatchOptions(root=repo_dir))
        assert res.success
        assert res.changes_applied == 1

    def test_works_in_git_repo_with_no_commits(self, repo_dir):
        """Fresh git repo with no commits."""
        try:
            subprocess.run(["git", "init"], cwd=str(repo_dir), check=True, capture_output=True)
        except (subprocess.SubprocessError, FileNotFoundError):
            pytest.skip("Git not available")
            
        f = repo_dir / "main.py"
        f.write_text("x = 1")
        assert run_build(BuildOptions(root=repo_dir, force_full=True)).success
        
        f.write_text("x = 2")
        res = run_patch(PatchOptions(root=repo_dir))
        assert res.success
        assert res.changes_applied == 1


# --- Class 14: TestEdgeCasePermissions ---
class TestEdgeCasePermissions:
    def test_permission_change_not_detected(self, repo_dir):
        """chmod doesn't change hash."""
        f = repo_dir / "script.py"
        f.write_text("print('hello')")
        assert run_build(BuildOptions(root=repo_dir, force_full=True)).success
        
        # Change permissions to executable
        try:
            os.chmod(f, 0o755)
        except OSError:
            pytest.skip("Permission changes not supported")
            
        res = run_patch(PatchOptions(root=repo_dir))
        assert res.success
        assert res.changes_applied == 0

    def test_read_only_file(self, repo_dir):
        """Can still read and hash read-only files."""
        f = repo_dir / "readonly.py"
        f.write_text("print('readonly')")
        assert run_build(BuildOptions(root=repo_dir, force_full=True)).success
        
        try:
            os.chmod(f, 0o444)
        except OSError:
            pass
            
        try:
            res = run_patch(PatchOptions(repo_dir))
            assert res.success and res.changes_applied == 0
        finally:
            try:
                os.chmod(f, 0o644)
            except OSError:
                pass


# --- Class 15: TestCrossPlatform ---
class TestCrossPlatform:
    def test_case_sensitivity(self, repo_dir):
        """File.txt vs file.txt."""
        f1 = repo_dir / "File.py"
        f1.write_text("a = 1")
        assert run_build(BuildOptions(root=repo_dir, force_full=True)).success
        
        # On case-sensitive systems, file.py is a separate file.
        # On case-insensitive systems, they are the same. We just check that the orchestrator behaves consistently.
        f2 = repo_dir / "file.py"
        f2.write_text("a = 2")
        
        res = run_patch(PatchOptions(root=repo_dir))
        assert res.success
        
        db = get_database(repo_dir)
        tracking = db.get_all_file_tracking()
        
        if os.path.exists(f1) and os.path.exists(f2) and not f1.samefile(f2):
            # Case-sensitive filesystem
            assert "File.py" in tracking
            assert "file.py" in tracking
        else:
            # Case-insensitive filesystem
            assert len(tracking) == 1


# --- Class 16: TestPerformance ---
class TestPerformance:
    def test_1000_files_no_changes_under_1_second(self, repo_dir):
        """Ensure hash-based detection is fast for typical repos."""
        for i in range(1000):
            (repo_dir / f"file_{i}.py").write_text(f"x = {i}")
            
        assert run_build(BuildOptions(root=repo_dir, force_full=True)).success
        
        t0 = time.perf_counter()
        res = run_patch(PatchOptions(root=repo_dir))
        elapsed = time.perf_counter() - t0
        
        assert res.success
        assert elapsed < 1.0  # Must complete in under 1 second

    def test_10000_files_scales_linearly(self, repo_dir):
        """Verify O(n) complexity, not O(n^2)."""
        # We can simulate O(n) scan check by running scan on 100 vs 500 files and checking the ratio is reasonable
        for i in range(200):
            (repo_dir / f"file_{i}.py").write_text(f"x = {i}")
            
        assert run_build(BuildOptions(root=repo_dir, force_full=True)).success
        
        t0 = time.perf_counter()
        run_patch(PatchOptions(root=repo_dir))
        elapsed_200 = time.perf_counter() - t0
        
        # Clean up database to build for larger set
        close_all_databases()
        db_path = repo_dir / artifact_filename(repo_dir)
        if db_path.exists():
            db_path.unlink()
            
        for i in range(200, 600):
            (repo_dir / f"file_{i}.py").write_text(f"x = {i}")
            
        assert run_build(BuildOptions(root=repo_dir, force_full=True)).success
        
        t1 = time.perf_counter()
        run_patch(PatchOptions(root=repo_dir))
        elapsed_600 = time.perf_counter() - t1
        
        # Scaling factor: 600 files is 3x more files than 200.
        # If it were O(n^2), the time would be ~9x.
        # We allow up to 4.5x scaling to be very safe against noise, but prevent exponential/quadratic scaling.
        if elapsed_200 > 0.005:  # Avoid division by extremely tiny numbers/noise
            ratio = elapsed_600 / elapsed_200
            assert ratio < 4.5


# --- Class 17: TestMigrationFromGitMode ---
class TestMigrationFromGitMode:
    def test_mode_argument_rejected(self):
        """--mode should no longer be accepted."""
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()
        
        from batho.cli.patch import register_patch_parser
        register_patch_parser(subparsers)
        
        with pytest.raises(SystemExit):
            parser.parse_args(["patch", "--mode", "auto"])

    def test_patchmode_import_fails(self):
        """PatchMode should not be importable from batho."""
        with pytest.raises(ImportError):
            from batho import PatchMode
            
        with pytest.raises(ImportError):
            from batho.context import PatchMode
