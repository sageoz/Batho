"""Unit tests for BlobIntegrityChecker."""

from __future__ import annotations

from unittest.mock import MagicMock
import pytest

from batho.modules.integrity.checkers.blob_checker import BlobIntegrityChecker
from batho.modules.integrity.models import CheckStatus, Severity


def test_blob_checker_passed():
    """Verify that BlobIntegrityChecker passes when runs and file changelogs are valid.

    Scenario:
        A database mock provides one run with status "completed" and a file changelog matching that run.

    Execution Flow:
        1. Set up a MagicMock database returning a completed run and a matching changelog entry.
        2. Instantiate BlobIntegrityChecker in dry run mode.
        3. Execute the checker's run method.
        4. Assert that the phase is "blobs", status is CheckStatus.PASSED, and no issues are reported.

    Expectations:
        - The integrity check completes successfully.
        - Check status is PASSED with zero issues.
    """
    db = MagicMock()
    db._reader.get_all_runs.return_value = [
        {"run_uuid": "abc", "status": "completed"},
    ]
    db._reader.get_file_changelog_raw.return_value = [
        {"entity_id": "e1", "change_kind": "added", "run_uuid": "abc"},
    ]

    checker = BlobIntegrityChecker(db, dry_run=True)
    report = checker.run()

    assert report.phase == "blobs"
    assert report.status == CheckStatus.PASSED
    assert len(report.issues) == 0


def test_blob_checker_invalid_run_status():
    """Verify that BlobIntegrityChecker fails and reports issues when runs have invalid status.

    Scenario:
        A database mock provides a run with an invalid status "zombie" and an empty file changelog.

    Execution Flow:
        1. Set up a MagicMock database with a run having a "zombie" status.
        2. Instantiate BlobIntegrityChecker in dry run mode.
        3. Execute the checker's run method.
        4. Assert that the status is CheckStatus.FAILED, one issue of type "invalid_run_status" is reported with WARNING severity.

    Expectations:
        - The integrity check status is FAILED.
        - Exactly one WARNING level issue is returned, indicating the invalid run status.
    """
    db = MagicMock()
    db._reader.get_all_runs.return_value = [
        {"run_uuid": "xyz", "status": "zombie"},  # invalid status
    ]
    db._reader.get_file_changelog_raw.return_value = []

    checker = BlobIntegrityChecker(db, dry_run=True)
    report = checker.run()

    assert report.status == CheckStatus.FAILED
    assert len(report.issues) == 1
    assert report.issues[0].type == "invalid_run_status"
    assert report.issues[0].severity == Severity.WARNING
