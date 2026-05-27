"""State Repairer."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..models import Issue, RepairResult


class StateRepairer:
    """Repairer for relational consistency issues."""

    def __init__(self, db: Any):
        self.db = db

    def repair(self, issue: Issue) -> RepairResult:
        """Dispatch to appropriate repair strategy."""
        if issue.repair_strategy == "fail_stuck_run":
            return self.repair_stuck_run(issue)
        elif issue.repair_strategy == "delete_orphaned_string":
            return self.repair_orphaned_string(issue)
        elif issue.repair_strategy == "reset_file_tracking":
            return self.repair_tracking_desync(issue)
        else:
            return RepairResult(
                issue=issue,
                success=False,
                error=f"Unknown or unhandled repair strategy: {issue.repair_strategy}",
            )

    def repair_stuck_run(self, issue: Issue) -> RepairResult:
        """Mark stuck run as failed."""
        run_uuid = issue.identifier.get("run_uuid")
        if not run_uuid:
            return RepairResult(issue=issue, success=False, error="Missing run_uuid in identifier")

        try:
            now = datetime.now(timezone.utc).isoformat()
            with self.db.connection() as conn:
                conn.execute(
                    """UPDATE index_runs
                       SET status = 'failed',
                           completed_at = ?,
                           error_message = 'Aborted by batho fix'
                       WHERE run_uuid = ?""",
                    (now, run_uuid),
                )
                conn.commit()
            return RepairResult(issue=issue, success=True, rows_affected=1)
        except Exception as e:
            return RepairResult(issue=issue, success=False, error=str(e))

    def repair_orphaned_string(self, issue: Issue) -> RepairResult:
        """Delete orphaned string from string_dict and run incremental_vacuum."""
        string_id = issue.identifier.get("id")
        if string_id is None:
            return RepairResult(issue=issue, success=False, error="Missing string id in identifier")

        try:
            with self.db.connection() as conn:
                cursor = conn.execute("DELETE FROM string_dict WHERE id = ?", (string_id,))
                rows_deleted = cursor.rowcount
                conn.execute("PRAGMA incremental_vacuum")
                conn.commit()
            return RepairResult(issue=issue, success=True, rows_affected=rows_deleted)
        except Exception as e:
            return RepairResult(issue=issue, success=False, error=str(e))

    def repair_tracking_desync(self, issue: Issue) -> RepairResult:
        """Reset is_indexed flags in file_tracking for desynced files."""
        file_id = issue.identifier.get("file_id")
        if file_id is None:
            return RepairResult(issue=issue, success=False, error="Missing file_id in identifier")

        try:
            with self.db.connection() as conn:
                cursor = conn.execute(
                    "UPDATE file_tracking SET is_indexed = 0, last_run_id = NULL WHERE file_id = ?",
                    (file_id,),
                )
                rows_updated = cursor.rowcount
                conn.commit()
            return RepairResult(issue=issue, success=True, rows_affected=rows_updated)
        except Exception as e:
            return RepairResult(issue=issue, success=False, error=str(e))
