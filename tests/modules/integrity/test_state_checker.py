"""Unit tests for StateConsistencyChecker."""

from __future__ import annotations

from unittest.mock import MagicMock
import pytest

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
