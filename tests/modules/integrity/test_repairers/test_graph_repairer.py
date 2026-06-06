"""Unit tests for GraphRepairer."""

from __future__ import annotations

from unittest.mock import MagicMock
import pytest

from batho.modules.integrity.repairers.graph_repairer import GraphRepairer
from batho.modules.integrity.models import Issue, Severity


def test_graph_repairer_resolve_dangling(tmp_path):
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
