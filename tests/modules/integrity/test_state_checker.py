"""Unit tests for StateConsistencyChecker."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest
from pathlib import Path

from batho.modules.storage.arrow_bundle.bundle import BathoBundle
from batho.modules.integrity.checkers.state_checker import StateConsistencyChecker
from batho.modules.integrity.models import CheckStatus, Severity


def test_state_checker_passed():
    db = MagicMock()
    db._reader.get_all_runs.return_value = [
        {"run_uuid": "abc", "status": "completed", "started_at": "2024-01-01T00:00:00+00:00"},
    ]
    db.get_latest_run_id.return_value = "abc"
    db.get_all_file_tracking.return_value = {}

    checker = StateConsistencyChecker(db, dry_run=True)
    report = checker.run()

    assert report.phase == "state"
    assert report.status == CheckStatus.PASSED
    assert len(report.issues) == 0


def test_state_checker_stuck_runs():
    db = MagicMock()
    db._reader.get_all_runs.return_value = [
        {"run_uuid": "run-uuid-1", "status": "running", "started_at": "2020-01-01T00:00:00Z"},
    ]
    db.get_latest_run_id.return_value = "run-uuid-1"
    db.get_all_file_tracking.return_value = {}

    checker = StateConsistencyChecker(db, dry_run=True)
    report = checker.run()

    assert report.status == CheckStatus.FAILED
    assert len(report.issues) == 1
    assert report.issues[0].type == "stuck_run"
    assert report.issues[0].severity == Severity.WARNING


def test_crashed_run_recovery(tmp_path: Path):
    """Verify that a run that crashes (marked 'running' in db, but lock is released) is detected and failed/fixed.

    Scenario:
        A Batho build process crashes abruptly. On-disk, the active run remains in 'running' status.
        However, the lock is released because the process terminated.
        When checking integrity, the `StateConsistencyChecker` must detect this as a "stuck run"
        and automatically transition its status to 'failed' on-disk.

    Execution Flow:
        1. Initialize on-disk `BathoBundle` at `tmp_path`.
        2. Call `bundle.create_run` to save a run as 'running' in SQLite.
        3. Assert that database records it as 'running'.
        4. Mock `InterProcessLock.is_locked_by_other` to return False (simulating that the crashing process released the lock).
        5. Initialize `StateConsistencyChecker` and call `run()`.
        6. Assert that it flagged exactly 1 issue of type "stuck_run" and successfully executed exactly 1 repair.
        7. Assert that the SQLite run database status was cleanly updated to "failed".

    Expectations:
        - Stuck runs are identified because they are marked 'running' but do not hold the inter-process lock.
        - Autonomic healing: repaired automatically to prevent database locks or stale statuses.
    """
    bundle = BathoBundle(tmp_path)
    
    # 1. Create a run, which immediately flushes to disk as "running"
    run_uuid = "crash_run_123"
    internal_id = bundle.create_run(run_uuid, root_path=str(tmp_path))
    
    # Verify it is saved with 'running' status on disk
    runs = bundle._reader.get_all_runs()
    assert len(runs) == 1
    assert runs[0]["status"] == "running"
    
    # 2. Check stuck runs.
    # Since we are running in the same process, we mock is_locked_by_other to return False
    # representing that the process holding the lock has terminated (releasing the lock).
    with patch("batho.utils.file_io.InterProcessLock.is_locked_by_other", return_value=False):
        checker = StateConsistencyChecker(bundle, dry_run=False)
        report = checker.run()
        
        # Verify it flagged the stuck run
        assert len(report.issues) == 1
        assert report.issues[0].type == "stuck_run"
        
        # Verify that RepairEngine fixes it (marks as failed or deletes or fixes)
        assert len(report.repairs) == 1
        assert report.repairs[0].success is True
        
    # Verify that the run status has been updated to failed on disk
    runs = bundle._reader.get_all_runs()
    assert runs[0]["status"] == "failed"

