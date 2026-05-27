"""Unit tests for BlobIntegrityChecker."""

from __future__ import annotations

from unittest.mock import MagicMock
import pytest

from batho.integrity.checkers.blob_checker import BlobIntegrityChecker
from batho.integrity.models import CheckStatus, Severity


def test_blob_checker_passed():
    db = MagicMock()
    conn = MagicMock()
    conn.execute.return_value.fetchall.side_effect = [
        [],  # file_artifacts
        [],  # run_artifacts
        [],  # file_changelog
    ]
    db.connection.return_value.__enter__.return_value = conn

    checker = BlobIntegrityChecker(db, dry_run=True)
    report = checker.run()

    assert report.phase == "blobs"
    assert report.status == CheckStatus.PASSED
    assert len(report.issues) == 0


def test_blob_checker_corrupt():
    db = MagicMock()
    conn = MagicMock()
    # Return file_artifacts with an invalid blob (missing valid zstd header)
    conn.execute.return_value.fetchall.side_effect = [
        [(1, 1, b"invalid_zstd_blob", b"abc", b"def")],  # file_artifacts
        [],  # run_artifacts
        [],  # file_changelog
    ]
    db.connection.return_value.__enter__.return_value = conn

    checker = BlobIntegrityChecker(db, dry_run=True)
    report = checker.run()

    assert report.status == CheckStatus.FAILED
    assert len(report.issues) == 1
    assert report.issues[0].type == "corrupt_file_artifact"
    assert report.issues[0].severity == Severity.ERROR
