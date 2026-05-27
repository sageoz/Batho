"""Unit tests for SQLiteRepairer."""

from __future__ import annotations

from unittest.mock import MagicMock
import pytest

from batho.integrity.repairers.sqlite_repairer import SQLiteRepairer
from batho.integrity.models import Issue, Severity


def test_sqlite_repairer_pragma():
    db = MagicMock()
    conn = MagicMock()
    db.connection.return_value.__enter__.return_value = conn

    issue = Issue(
        type="invalid_pragma_fk",
        severity=Severity.ERROR,
        table="db_meta",
        identifier={},
        description="PRAGMA foreign_keys is not enabled.",
        repair_strategy="enable_foreign_keys",
    )

    repairer = SQLiteRepairer(db)
    res = repairer.repair(issue)

    assert res.success is True
    conn.execute.assert_called_with("PRAGMA foreign_keys = ON")
