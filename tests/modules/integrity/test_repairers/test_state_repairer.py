"""Unit tests for StateRepairer — Arrow Bundle edition."""

from __future__ import annotations

from unittest.mock import MagicMock
import pytest

from batho.modules.integrity.repairers.state_repairer import StateRepairer
from batho.modules.integrity.models import Issue, Severity


def test_state_repairer_stuck_run():
    """Verify that StateRepairer successfully updates the status of a stuck run to failed.

    Scenario:
        An issue with repair strategy 'fail_stuck_run' for a run with UUID 'run-1' is provided to the StateRepairer.

    Execution Flow:
        1. Set up a MagicMock database.
        2. Create an Issue instance with type 'stuck_run', repair strategy 'fail_stuck_run', and identifier {"run_uuid": "run-1"}.
        3. Instantiate StateRepairer with the mock database.
        4. Execute repairer.repair(issue).
        5. Assert that the repair result reports success as True.
        6. Verify that db.fail_run was called with 'run-1' and the abort message.

    Expectations:
        - The repair execution succeeds.
        - The database marks the stuck run as failed.
    """
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
