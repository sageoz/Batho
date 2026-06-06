"""Unit tests for StateRepairer — Arrow Bundle edition."""

from __future__ import annotations

from unittest.mock import MagicMock
import pytest

from batho.modules.integrity.repairers.state_repairer import StateRepairer
from batho.modules.integrity.models import Issue, Severity


def test_state_repairer_stuck_run():
    db = MagicMock()

    issue = Issue(
        type="stuck_run",
        severity=Severity.WARNING,
        table="runs",
        identifier={"run_uuid": "run-1"},
        description="Run is stuck",
        repair_strategy="fail_stuck_run",
    )

    repairer = StateRepairer(db)
    res = repairer.repair(issue)

    assert res.success is True
    db.fail_run.assert_called_once_with("run-1", error_message="Aborted by batho fix")
