"""Blob Repairer — Arrow Bundle edition."""

from __future__ import annotations

from typing import Any

from ..models import Issue, RepairResult

_ALLOWED_RUN_ARTIFACT_COLUMNS = {
    "context_overview_json",
    "telemetry_json",
    "structural_json",
    "security_audit_json",
    "artifact_payload_json",
    "delta_stats_json",
}


class BlobRepairer:
    """Repairer for corrupted Arrow IPC data."""

    def __init__(self, db: Any):
        self.db = db

    def repair(self, issue: Issue) -> RepairResult:
        """Dispatch to appropriate repair strategy."""
        if issue.repair_strategy == "delete_corrupt_file_artifact":
            return self.repair_file_artifact(issue)
        elif issue.repair_strategy == "clear_corrupt_run_artifact":
            return self.repair_run_artifact(issue)
        elif issue.repair_strategy == "delete_corrupt_changelog":
            return self.repair_changelog(issue)
        else:
            return RepairResult(
                issue=issue,
                success=False,
                error=f"Unknown or unhandled repair strategy: {issue.repair_strategy}",
            )

    def repair_file_artifact(self, issue: Issue) -> RepairResult:
        """Mark the file as not indexed so it is re-processed on next patch."""
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

    def repair_run_artifact(self, issue: Issue) -> RepairResult:
        """Clear a specific JSON column in run_artifacts by nulling it out."""
        run_uuid = issue.identifier.get("run_uuid")
        column = issue.identifier.get("column")
        if not run_uuid or not column:
            return RepairResult(issue=issue, success=False, error="Missing run_uuid or column in identifier")

        if column not in _ALLOWED_RUN_ARTIFACT_COLUMNS:
            return RepairResult(issue=issue, success=False, error=f"Invalid or forbidden column name: {column!r}")

        try:
            import pyarrow.compute as pc
            from batho.modules.storage.arrow_bundle.schemas import RUN_ARTIFACTS_SCHEMA
            from batho.modules.storage.arrow_bundle.writer import write_simple_ipc, read_ipc_table

            table = read_ipc_table(self.db._active_or_empty("run_artifacts"))
            if table.num_rows == 0:
                return RepairResult(issue=issue, success=False, error="run_artifacts table is empty")

            rows = table.to_pylist()
            affected = 0
            for row in rows:
                if row.get("run_uuid") == run_uuid:
                    row[column] = None
                    affected += 1

            if affected == 0:
                return RepairResult(issue=issue, success=False, error=f"Run {run_uuid!r} not found in run_artifacts")

            tmp = self.db._artifact_dir / "run_artifacts.tmp.ipc"
            write_simple_ipc(rows, RUN_ARTIFACTS_SCHEMA, tmp)
            self.db._manager.commit_patch({"run_artifacts": tmp}, run_uuid)
            self.db._reader.invalidate("run_artifacts")
            return RepairResult(issue=issue, success=True, rows_affected=affected)
        except Exception as e:
            return RepairResult(issue=issue, success=False, error=str(e))

    def repair_changelog(self, issue: Issue) -> RepairResult:
        """Delete corrupted changelog rows for a given run_uuid."""
        run_uuid = issue.identifier.get("run_uuid")
        if not run_uuid:
            return RepairResult(issue=issue, success=False, error="Missing run_uuid in identifier")

        try:
            import pyarrow.compute as pc
            from batho.modules.storage.arrow_bundle.schemas import FILE_CHANGELOG_SCHEMA
            from batho.modules.storage.arrow_bundle.writer import write_simple_ipc, read_ipc_table

            table = read_ipc_table(self.db._active_or_empty("file_changelog"))
            if table.num_rows == 0:
                return RepairResult(issue=issue, success=True, rows_affected=0)

            original_count = table.num_rows
            mask = pc.invert(pc.equal(table.column("run_uuid"), run_uuid))
            filtered = table.filter(mask)
            deleted = original_count - filtered.num_rows

            tmp = self.db._artifact_dir / "file_changelog.tmp.ipc"
            import pyarrow as pa
            with pa.ipc.new_file(str(tmp), FILE_CHANGELOG_SCHEMA) as writer:
                writer.write_table(filtered)
            self.db._manager.commit_patch({"file_changelog": tmp}, run_uuid)
            self.db._reader.invalidate("file_changelog")
            return RepairResult(issue=issue, success=True, rows_affected=deleted)
        except Exception as e:
            return RepairResult(issue=issue, success=False, error=str(e))
