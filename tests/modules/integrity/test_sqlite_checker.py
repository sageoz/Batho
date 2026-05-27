"""Unit tests for SQLiteHealthChecker."""

from __future__ import annotations

from unittest.mock import MagicMock
import pytest
import sqlite3

from batho.modules.integrity.checkers.sqlite_checker import SQLiteHealthChecker
from batho.modules.integrity.models import CheckStatus, Severity


def test_sqlite_checker_passed():
    db = MagicMock()
    conn = MagicMock()
    # Mock schema version, foreign_keys
    conn.execute.return_value.fetchone.side_effect = [
        ("batho-db.v1",),  # schema version
        (1,),  # foreign keys
    ]
    # Mock db_meta query for schema_version check
    conn.execute.return_value.fetchone.side_effect = [
        ("batho-db.v1",),  # db_meta schema_version
        (1,),  # foreign keys
    ]
    # Mock integrity_check, foreign_key_check
    conn.execute.return_value.fetchall.side_effect = [
        [("ok",)],  # integrity check
        [],  # foreign key check
    ]
    db.connection.return_value.__enter__.return_value = conn

    checker = SQLiteHealthChecker(db, dry_run=True)
    report = checker.run()

    assert report.phase == "db"
    assert report.status == CheckStatus.PASSED
    assert len(report.issues) == 0


def test_sqlite_checker_corrupt():
    db = MagicMock()
    conn = MagicMock()
    conn.execute.return_value.fetchone.side_effect = [
        ("batho-db.v1",),  # schema version
        (1,),  # foreign keys
    ]
    # Mock db_meta query for schema_version check
    conn.execute.return_value.fetchone.side_effect = [
        ("batho-db.v1",),  # db_meta schema_version
        (1,),  # foreign keys
    ]
    conn.execute.return_value.fetchall.side_effect = [
        [("database disk image is malformed",)],  # integrity check
        [],  # foreign key check
    ]
    db.connection.return_value.__enter__.return_value = conn

    checker = SQLiteHealthChecker(db, dry_run=True)
    report = checker.run()

    assert report.status == CheckStatus.FAILED
    assert len(report.issues) == 1
    assert report.issues[0].type == "database_corruption"
    assert report.issues[0].severity == Severity.CRITICAL
