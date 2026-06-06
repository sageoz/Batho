"""Unit tests for BlobRepairer — Arrow Bundle edition."""

from __future__ import annotations

from unittest.mock import MagicMock
import pytest

from batho.modules.integrity.repairers.blob_repairer import BlobRepairer
from batho.modules.integrity.models import Issue, Severity


def test_blob_repairer_delete_corrupt_file():
    db = MagicMock()
    db.get_file_tracking.return_value = {
        "file_path": "src/foo.py",
        "content_hash": "abc123",
        "is_indexed": True,
        "last_run_uuid": "run-1",
        "size": 100,
        "mtime_ns": 0,
        "inode": None,
        "updated_at": "2024-01-01T00:00:00+00:00",
        "encoding": None,
    }
    db.upsert_file_tracking.return_value = 1

    issue = Issue(
        type="corrupt_file_artifact",
        severity=Severity.ERROR,
        table="agent_views",
        identifier={"file_path": "src/foo.py"},
        description="Corrupt blob",
        repair_strategy="delete_corrupt_file_artifact",
    )

    repairer = BlobRepairer(db)
    res = repairer.repair(issue)

    assert res.success is True
    db.get_file_tracking.assert_called_once_with("src/foo.py")
    db.upsert_file_tracking.assert_called_once()
