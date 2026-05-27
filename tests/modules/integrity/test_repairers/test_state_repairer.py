"""Unit tests for StateRepairer."""

from __future__ import annotations

from unittest.mock import MagicMock
import pytest

from batho.modules.integrity.repairers.state_repairer import StateRepairer
from batho.modules.integrity.models import Issue, Severity


def test_state_repairer_stuck_run():
    db = MagicMock()
    conn = MagicMock()
    db.connection.return_value.__enter__.return_value = conn

    issue = Issue(
        type="stuck_run",
        severity=Severity.WARNING,
        table="index_runs",
        identifier={"run_uuid": "run-1"},
        description="Run is stuck",
        repair_strategy="fail_stuck_run",
    )

    repairer = StateRepairer(db)
    res = repairer.repair(issue)

    assert res.success is True
    assert conn.execute.called
