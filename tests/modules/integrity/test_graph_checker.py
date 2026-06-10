"""Unit tests for GraphSyncChecker."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from batho.modules.integrity.checkers.graph_checker import GraphSyncChecker
from batho.modules.integrity.models import CheckStatus, Severity


def test_graph_checker_passed_no_store(tmp_path):
    """Verify that GraphSyncChecker passes when the store directory does not exist.

    Scenario:
        The repository root has no .batho or bsg/current/ directory.

    Execution Flow:
        1. Set up a MagicMock database pointing to an empty temporary path.
        2. Instantiate GraphSyncChecker with deep=False and dry_run=True.
        3. Run the integrity checker.
        4. Assert that phase is "graph", status is CheckStatus.PASSED, and no issues are found.

    Expectations:
        - The checker passes gracefully when there is no storage folder.
        - Status is CheckStatus.PASSED.
    """
    db = MagicMock()
    db._repo_root = tmp_path

    checker = GraphSyncChecker(db, dry_run=True, deep=False)
    report = checker.run()

    assert report.phase == "graph"
    assert report.status == CheckStatus.PASSED
    assert len(report.issues) == 0


def test_graph_checker_passed_empty_dangling(tmp_path):
    """Verify that GraphSyncChecker passes when the store exists but has no dangling edges.

    Scenario:
        A BsgScratchStore is initialized and compacted, resulting in empty/no dangling references.

    Execution Flow:
        1. Set up a MagicMock database pointing to a temporary path.
        2. Initialize and compact a BsgScratchStore to simulate a clean state.
        3. Instantiate GraphSyncChecker and execute its run method.
        4. Assert that check status is CheckStatus.PASSED and issues count is 0.

    Expectations:
        - The checker passes successfully.
        - Status is PASSED, and no warnings are logged.
    """
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
    """Verify that GraphSyncChecker fails and warns when dangling edges are found in the scratch store.

    Scenario:
        A BsgScratchStore is populated with a dangling edge reference and then compacted.

    Execution Flow:
        1. Set up a MagicMock database pointing to a temporary path.
        2. Initialize a BsgScratchStore, create an entity key, append a dangling relationship, and compact.
        3. Instantiate GraphSyncChecker and call the run method.
        4. Assert that check status is CheckStatus.FAILED.
        5. Verify that exactly one issue of type "resolvable_dangling_reference" and WARNING severity is reported.

    Expectations:
        - The checker flags the dangling reference.
        - The check fails with a specific warning issue.
    """
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

