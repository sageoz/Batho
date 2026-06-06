"""Unit tests for GraphSyncChecker."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from batho.modules.integrity.checkers.graph_checker import GraphSyncChecker
from batho.modules.integrity.models import CheckStatus, Severity


def test_graph_checker_passed_no_store(tmp_path):
    """No bsg/current/ dir → checker passes with zero issues."""
    db = MagicMock()
    db._repo_root = tmp_path

    checker = GraphSyncChecker(db, dry_run=True, deep=False)
    report = checker.run()

    assert report.phase == "graph"
    assert report.status == CheckStatus.PASSED
    assert len(report.issues) == 0


def test_graph_checker_passed_empty_dangling(tmp_path):
    """bsg/current/ exists with empty dangling file → no issues."""
    from batho.modules.storage.arrow_store import BsgScratchStore

    db = MagicMock()
    db._repo_root = tmp_path

    batho_dir = tmp_path / ".batho"
    store = BsgScratchStore(run_uuid="run-1", batho_dir=batho_dir, run_internal_id=1)
    store.compact()

    checker = GraphSyncChecker(db, dry_run=True, deep=False)
    report = checker.run()

    assert report.status == CheckStatus.PASSED
    assert len(report.issues) == 0


def test_graph_checker_dangling(tmp_path):
    """bsg/current/ with dangling rows → WARNING issue reported."""
    from batho.modules.storage.arrow_store import BsgScratchStore

    db = MagicMock()
    db._repo_root = tmp_path

    batho_dir = tmp_path / ".batho"
    store = BsgScratchStore(run_uuid="run-1", batho_dir=batho_dir, run_internal_id=1)
    keys = store.bulk_get_or_create_entity_keys(["eid:src"])
    store.append_dangling([(keys["eid:src"], "SomeTarget", "CALLS", 1)])
    store.compact()

    checker = GraphSyncChecker(db, dry_run=True, deep=False)
    report = checker.run()

    assert report.status == CheckStatus.FAILED
    assert len(report.issues) == 1
    assert report.issues[0].type == "resolvable_dangling_reference"
    assert report.issues[0].severity == Severity.WARNING

