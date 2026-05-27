"""Unit tests for GraphSyncChecker."""

from __future__ import annotations

from unittest.mock import MagicMock
import pytest

from batho.modules.integrity.checkers.graph_checker import GraphSyncChecker
from batho.modules.integrity.models import CheckStatus, Severity


def test_graph_checker_passed():
    db = MagicMock()
    conn = MagicMock()
    conn.execute.return_value.fetchall.side_effect = [
        [],  # dangling references
        [],  # invalid relationships
    ]
    db.connection.return_value.__enter__.return_value = conn

    checker = GraphSyncChecker(db, dry_run=True, deep=False)
    report = checker.run()

    assert report.phase == "graph"
    assert report.status == CheckStatus.PASSED
    assert len(report.issues) == 0


def test_graph_checker_dangling():
    db = MagicMock()
    conn = MagicMock()
    conn.execute.return_value.fetchall.side_effect = [
        [(1,)],  # dangling references (run_id)
        [],  # invalid relationships
    ]
    db.connection.return_value.__enter__.return_value = conn

    checker = GraphSyncChecker(db, dry_run=True, deep=False)
    report = checker.run()

    assert report.status == CheckStatus.FAILED
    assert len(report.issues) == 1
    assert report.issues[0].type == "resolvable_dangling_reference"
    assert report.issues[0].severity == Severity.WARNING


def test_graph_checker_pseudo_targets():
    db = MagicMock()
    conn = MagicMock()
    conn.execute.return_value.fetchall.side_effect = [
        [],  # dangling references (run_id)
        [
            ("source-1", "external:https://example.com", "link", 1),
            ("source-2", "real-invalid-target", "link", 1),
        ],  # invalid relationships query
    ]
    db.connection.return_value.__enter__.return_value = conn

    checker = GraphSyncChecker(db, dry_run=True, deep=False)
    report = checker.run()

    assert len(report.issues) == 1
    assert report.issues[0].type == "invalid_relationship"
    assert report.issues[0].identifier["target_id"] == "real-invalid-target"

