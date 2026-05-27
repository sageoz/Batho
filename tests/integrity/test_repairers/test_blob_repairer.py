"""Unit tests for BlobRepairer."""

from __future__ import annotations

from unittest.mock import MagicMock
import pytest

from batho.integrity.repairers.blob_repairer import BlobRepairer
from batho.integrity.models import Issue, Severity


def test_blob_repairer_delete_corrupt_file():
    db = MagicMock()
    conn = MagicMock()
    db.transaction.return_value.__enter__.return_value = conn

    issue = Issue(
        type="corrupt_file_artifact",
        severity=Severity.ERROR,
        table="file_artifacts",
        identifier={"run_id": 1, "file_id": 2},
        description="Corrupt blob",
        repair_strategy="delete_corrupt_file_artifact",
    )

    repairer = BlobRepairer(db)
    res = repairer.repair(issue)

    assert res.success is True
    assert conn.execute.called
