"""Unit tests for BlobIntegrityChecker."""

from __future__ import annotations

from unittest.mock import MagicMock
import pytest

from batho.modules.integrity.checkers.blob_checker import BlobIntegrityChecker
from batho.modules.integrity.models import CheckStatus, Severity


def test_blob_checker_passed():
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
