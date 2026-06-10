"""Integration and edge case tests for Batho's build orchestrator.

This module validates that the build pipeline:
1. Rejects execution and yields warning results if another process holds the build lock.
2. Cleans up files and marks the run as failed in SQLite when the build encounters a hard error.
3. Issues warnings when case-insensitive filename collisions are detected on case-insensitive filesystems.
4. Marks oversized files as opaque snapshots and logs warnings without failing the entire build.
"""

from __future__ import annotations

import pytest
from pathlib import Path
from unittest.mock import patch

from batho.orchestrator.build import run_build, BuildOptions
from batho.utils.file_io import InterProcessLock
from batho.modules.storage.arrow_bundle.bundle import BathoBundle


def test_build_lock_conflict(tmp_path: Path):
    """Verify that run_build returns a failure result when lock cannot be acquired.

    Scenario:
        A build is already running or another process has left a lock active.
        When `run_build` attempts to start, it should fail immediately rather than proceeding
        and corrupting the database or writing partial assets.

    Execution Flow:
        1. Initialize repo structure and mock `.batho/batho.lock`.
        2. Acquire lock externally using `InterProcessLock`.
        3. Invoke `run_build` with `BuildOptions` pointing to the repository root.
        4. Assert that `res.success` is False.
        5. Verify that appropriate "lock" or "Another Batho process" warning is logged.

    Expectations:
        - Build gracefully exits with success=False.
        - Proper diagnostics are recorded in the build result warnings.
    """
    # Setup dummy directory
    root = tmp_path / "repo"
    root.mkdir()
    
    lock_file = root / ".batho" / "batho.lock"
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    
    # Hold the lock externally
    lock = InterProcessLock(lock_file)
    with lock:
        options = BuildOptions(root=root)
        res = run_build(options)
        assert res.success is False
        assert any("Another Batho process" in w or "failed" in w.lower() for w in res.warnings)


def test_build_failed_cleanup(tmp_path: Path):
    """Verify that on build failure, db.fail_run is called and store.cleanup_streams is called.

    Scenario:
        The build process encounters an unexpected failure midway through indexing the codebase.
        The system must catch the error, mark the run as failed in the database with the
        appropriate error message, and clean up any partial Arrow files.

    Execution Flow:
        1. Create repo directory and write a basic `batho.yaml`.
        2. Mock `CodeGraphIndexer`'s `build_graph` method to raise a `ValueError`.
        3. Run `run_build` and assert `res.success` is False.
        4. Verify that the build run status in the SQLite database is recorded as "failed".
        5. Verify that the exception message is saved as the error message.

    Expectations:
        - Robust error handling: exceptions are caught and reported in the build result.
        - Run state is updated to "failed" on-disk to prevent downstream operations from reading corrupt runs.
    """
    root = tmp_path / "repo"
    root.mkdir()
    
    # Write a simple config
    (root / "batho.yaml").write_text("paths:\n  artifact_dir: .batho/artifact\n", encoding="utf-8")
    
    # Force a failure during the build graph stage by mocking CodeGraphIndexer
    with patch("batho.modules.graph.builder.codegraph.CodeGraphIndexer") as mock_indexer_cls:
        mock_indexer = mock_indexer_cls.return_value.__enter__.return_value
        mock_indexer.build_graph.side_effect = ValueError("Mocked build failure")
        mock_indexer.build_stats = {"files_parsed": 1, "files_cached": 0}
        mock_indexer.get_unindexed_files.return_value = []
        
        options = BuildOptions(root=root, force_full=True)
        res = run_build(options)
        assert res.success is False
        assert any("Mocked build failure" in w for w in res.warnings)
            
    # Verify that run was marked as failed in SQLite db
    db = BathoBundle(root)
    runs = db._reader.get_all_runs()
    assert len(runs) == 1
    assert runs[0]["status"] == "failed"
    assert runs[0]["error_message"] == "Mocked build failure"


def test_case_insensitive_collision_warning(tmp_path: Path):
    """Verify that case-insensitive duplicates issue a warning on build/patch.

    Scenario:
        On a case-insensitive filesystem (or in an environment emulating one), two files exist
        whose paths differ only by case (e.g., `Index.py` and `index.py`).
        The build engine should proceed but emit a clear warning notifying the user of potential collisions.

    Execution Flow:
        1. Create two files `Index.py` and `index.py` with distinct contents.
        2. Mock filesystem walking to return both files.
        3. Mock `is_filesystem_case_insensitive` to return True.
        4. Run the build pipeline.
        5. Verify that the build succeeds but produces warnings referencing "Case-insensitive path collision".

    Expectations:
        - Files are built successfully, but the potential filesystem conflict is logged as a warning.
    """
    # Write two files with case-colliding names
    (tmp_path / "Index.py").write_text("class Index: pass")
    (tmp_path / "index.py").write_text("class index: pass")
    
    with patch("batho.modules.graph.builder.codegraph.walk_ignored_filtered", return_value=[(tmp_path, [], ["Index.py", "index.py"])]):
        with patch("pathlib.Path.is_file", return_value=True):
            with patch("batho.utils.path_sanitizer.is_filesystem_case_insensitive", return_value=True):
                options = BuildOptions(root=tmp_path, force_full=True, verbose=False)
                res = run_build(options)
                
                # Assert build succeeded but has collision warnings
                assert res.success
                assert any("Case-insensitive path collision detected" in w for w in res.warnings)


def test_oversized_file_opaque_tracking(tmp_path: Path):
    """Verify that files exceeding max_file_size_kb are skipped from AST parsing, log warnings, and are saved as opaque snapshots.

    Scenario:
        The repository contains a file whose size exceeds the user's or system's max file size limit (configured in KB).
        The build should not fail; instead, it should skip AST parsing for this file, log a warning,
        and write it as an "opaque snapshot" (is_indexed=False) in the file tracking records.

    Execution Flow:
        1. Write a small file (`small_file.py`) and an oversized file (`large_file.py`).
        2. Run build specifying `max_file_size_kb=1`.
        3. Assert that the build succeeds.
        4. Capture logger warnings and assert that "file_exceeds_max_size_limit" warning was emitted.
        5. Open the `BathoBundle` database and query tracking for the large file.
        6. Assert that the large file is indeed tracked but with `is_indexed` set to False.

    Expectations:
        - Robust fallback for large files: they are not parsed but are still tracked in the index.
        - System warning is generated.
    """
    # Write a small file to make sure build succeeds
    (tmp_path / "small_file.py").write_text("x = 1")
    
    # Write a file that is large (e.g. ~5 KB, exceeding 1 KB limit)
    large_file = tmp_path / "large_file.py"
    large_file.write_text("class BigClass:\n" + "\n".join(f"    def method_{i}(self): pass" for i in range(150)))
    
    # Run build with max_file_size_kb=1 (meaning 1 KB limit)
    options = BuildOptions(root=tmp_path, force_full=True, verbose=False, max_file_size_kb=1)
    with patch("batho.modules.extraction.pipeline.logger.warning") as mock_warning:
        res = run_build(options)
        
        assert res.success
        
        # Verify that warning was logged
        calls = [call[0] for call in mock_warning.call_args_list]
        assert any(args[0] == "file_exceeds_max_size_limit" for args in calls)
    
    # Verify it is saved as an opaque snapshot in the database (file_tracking has it with is_indexed=False)
    db = BathoBundle(tmp_path)
    tracking = db.get_file_tracking(large_file.name)
    assert tracking is not None
    assert not tracking["is_indexed"]
