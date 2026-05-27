"""Unit tests for StateConsistencyChecker."""

from __future__ import annotations

from unittest.mock import MagicMock
import pytest

from batho.modules.integrity.checkers.state_checker import StateConsistencyChecker
from batho.modules.integrity.models import CheckStatus, Severity


def test_state_checker_passed():
    db = MagicMock()
    conn = MagicMock()
    conn.execute.return_value.fetchall.side_effect = [
        [],  # stuck runs query
        [],  # orphaned string_dict query
        [],  # file tracking desync query
    ]
    db.connection.return_value.__enter__.return_value = conn

    checker = StateConsistencyChecker(db, dry_run=True)
    report = checker.run()

    assert report.phase == "state"
    assert report.status == CheckStatus.PASSED
    assert len(report.issues) == 0


def test_state_checker_stuck_runs():
    db = MagicMock()
    conn = MagicMock()
    conn.execute.return_value.fetchall.side_effect = [
        [(1, "run-uuid-1", "2020-01-01T00:00:00Z")],  # stuck runs query
        [],  # orphaned string_dict query
        [],  # file tracking desync query
    ]
    db.connection.return_value.__enter__.return_value = conn

    checker = StateConsistencyChecker(db, dry_run=True)
    report = checker.run()

    assert report.status == CheckStatus.FAILED
    assert len(report.issues) == 1
    assert report.issues[0].type == "stuck_run"
    assert report.issues[0].severity == Severity.WARNING
