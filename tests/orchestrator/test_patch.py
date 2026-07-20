"""Integration and edge case tests for Batho's patch orchestrator.

This module validates that the patch pipeline:
1. Rejects execution and yields warning results if another process holds the lock.
2. Prevents concurrent patch runs on the same repository.
"""

from __future__ import annotations

import pytest
from pathlib import Path

from batho.orchestrator.build import run_build, BuildOptions
from batho.orchestrator.patch import run_patch, PatchOptions
from batho.utils.file_io import InterProcessLock


def test_patch_lock_contention(tmp_path: Path):
    """Verify that concurrent patch runs fail immediately and gracefully with a lock conflict error.

    Scenario:
        The repository is initialized with a build. A process acquires and holds the repository's `.batho/batho.lock` file.
        While the lock is held, we trigger `run_patch`.
        The patch operation must fail gracefully immediately without corrupting the active on-disk indexes.

    Execution Flow:
        1. Initialize repo with a small python file.
        2. Run a full build to create the initial Batho bundle.
        3. Identify the lock file path: `.batho/batho.lock`.
        4. Acquire the lock via `InterProcessLock`.
        5. Within the lock context, make a modification to the file and execute `run_patch`.
        6. Assert that the patch result success is False.
        7. Verify that warnings about "already running" or "lock" are present in the patch result.

    Expectations:
        - Patch operations respect exclusive process-wide locking.
        - Failures are clean and prevent concurrent write contamination.
    """
    # First, run a build to create the initial bundle
    (tmp_path / "main.py").write_text("def hello(): pass")
    res = run_build(BuildOptions(root=tmp_path, force_full=True))
    assert res.success
    
    # Acquire the inter-process lock on the repository lock file path
    lock_file = tmp_path / ".batho" / "batho.lock"
    
    with InterProcessLock(lock_file):
        # With the lock held, try to run a patch
        (tmp_path / "main.py").write_text("def hello(): pass\n# modified")
        
        patch_res = run_patch(PatchOptions(root=tmp_path, verbose=False))
        assert patch_res.success is False
        assert any("already running" in w.lower() or "lock" in w.lower() for w in patch_res.warnings)


def test_patch_delete_only_no_crash(tmp_path: Path):
    """Verify that a patch run with only file deletions does not crash with NameError.

    Scenario:
        A repo is built with two files. One file is deleted, leaving no added/modified
        files — only a deletion. The patch must handle this gracefully without
        referencing an undefined `indexer` variable.

    Execution Flow:
        1. Create a repo with two Python files.
        2. Run a full build to create the initial Batho bundle.
        3. Delete one file (leaving the other unchanged).
        4. Run `run_patch` — must succeed without NameError.
        5. Delete the remaining file.
        6. Run `run_patch` again — must still succeed.

    Expectations:
        - Delete-only patch runs return PatchResult(success=True).
        - No NameError or AttributeError is raised.
    """
    (tmp_path / "main.py").write_text("def hello(): pass")
    (tmp_path / "utils.py").write_text("def helper(): pass")
    res = run_build(BuildOptions(root=tmp_path, force_full=True))
    assert res.success

    # Delete one file — patch should handle delete-only gracefully
    (tmp_path / "utils.py").unlink()
    patch_res = run_patch(PatchOptions(root=tmp_path, verbose=False))
    assert patch_res.success

    # Delete the remaining file — still delete-only
    (tmp_path / "main.py").unlink()
    patch_res = run_patch(PatchOptions(root=tmp_path, verbose=False))
    assert patch_res.success
