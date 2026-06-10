"""Unit tests for GraphRepairer."""

from __future__ import annotations

from unittest.mock import MagicMock
import pytest

from batho.modules.integrity.repairers.graph_repairer import GraphRepairer
from batho.modules.integrity.models import Issue, Severity


def test_graph_repairer_resolve_dangling(tmp_path):
    """Verify that GraphRepairer handles resolving dangling references when the store is empty or missing.

    Scenario:
        An issue with repair strategy 'resolve_dangling' is provided, but no current storage directory exists.

    Execution Flow:
        1. Set up a MagicMock database pointing to a temporary path.
        2. Create an Issue instance with type 'resolvable_dangling_reference' and 'resolve_dangling' strategy.
        3. Instantiate GraphRepairer with the mock database.
        4. Execute repairer.repair(issue).
        5. Assert that the repair result reports success as True and rows_affected is 0.

    Expectations:
        - The repairer handles the missing current directory gracefully.
        - The operation succeeds with zero rows affected.
    """
    db = MagicMock()
    db._repo_root = tmp_path

    issue = Issue(
        type="resolvable_dangling_reference",
        severity=Severity.WARNING,
        table="dangling_references",
        identifier={"run_id": 1},
        description="Dangling reference",
        repair_strategy="resolve_dangling",
    )

    repairer = GraphRepairer(db)
    res = repairer.repair(issue)

    # current/ dir does not exist → returns 0 gracefully
    assert res.success is True
    assert res.rows_affected == 0
