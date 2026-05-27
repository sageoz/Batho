"""Unit tests for GraphRepairer."""

from __future__ import annotations

from unittest.mock import MagicMock
import pytest

from batho.integrity.repairers.graph_repairer import GraphRepairer
from batho.integrity.models import Issue, Severity


def test_graph_repairer_resolve_dangling():
    db = MagicMock()
    db.resolve_dangling_references.return_value = 5

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

    assert res.success is True
    assert res.rows_affected == 5
    db.resolve_dangling_references.assert_called_with(1)
