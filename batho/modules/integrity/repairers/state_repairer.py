"""State Repairer — Arrow Bundle edition."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..models import Issue, RepairResult


class StateRepairer:
    """Repairer for relational consistency issues against Arrow Bundle."""

    def __init__(self, db: Any):
        self.db = db

    def repair(self, issue: Issue) -> RepairResult:
        """Dispatch to appropriate repair strategy."""
        if issue.repair_strategy == "fail_stuck_run":
            return self.repair_stuck_run(issue)
        elif issue.repair_strategy == "delete_orphaned_string":
            return RepairResult(issue=issue, success=True, rows_affected=0)
        elif issue.repair_strategy == "reset_file_tracking":
            return self.repair_tracking_desync(issue)
        else:
            return RepairResult(
                issue=issue,
                success=False,
                error=f"Unknown or unhandled repair strategy: {issue.repair_strategy}",
            )

    def repair_stuck_run(self, issue: Issue) -> RepairResult:
        """Mark stuck run as failed via BathoBundle.fail_run()."""
        run_uuid = issue.identifier.get("run_uuid")
        if not run_uuid:
            return RepairResult(issue=issue, success=False, error="Missing run_uuid in identifier")

        try:
            self.db.fail_run(run_uuid, error_message="Aborted by batho fix")
            return RepairResult(issue=issue, success=True, rows_affected=1)
        except Exception as e:
            return RepairResult(issue=issue, success=False, error=str(e))

    def repair_tracking_desync(self, issue: Issue) -> RepairResult:
        """Reset is_indexed flag for a desynced file path."""
        file_path = issue.identifier.get("file_path")
        if not file_path:
            return RepairResult(issue=issue, success=False, error="Missing file_path in identifier")

        try:
            tracking = self.db.get_file_tracking(file_path)
            if tracking is None:
                return RepairResult(issue=issue, success=False, error=f"No tracking record for {file_path!r}")
            tracking["is_indexed"] = False
            tracking["last_run_uuid"] = None
            self.db.upsert_file_tracking([tracking])
            return RepairResult(issue=issue, success=True, rows_affected=1)
        except Exception as e:
            return RepairResult(issue=issue, success=False, error=str(e))
