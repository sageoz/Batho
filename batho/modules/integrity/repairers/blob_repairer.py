"""Blob Repairer."""

from __future__ import annotations

from typing import Any

from ..models import Issue, RepairResult


class BlobRepairer:
    """Repairer for corrupted zstd-compressed blobs."""

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
        """Delete corrupted file artifacts and update tracking to require re-indexing."""
        run_id = issue.identifier.get("run_id")
        file_id = issue.identifier.get("file_id")
        if run_id is None or file_id is None:
            return RepairResult(issue=issue, success=False, error="Missing run_id or file_id in identifier")

        try:
            with self.db.transaction() as conn:
                # 1. Delete from query_entities/relationships/dangling first if any cascades are missing
                conn.execute(
                    "DELETE FROM query_entities WHERE run_id = ? AND file_path = (SELECT val FROM string_dict WHERE id = ?)",
                    (run_id, file_id),
                )
                conn.execute(
                    "DELETE FROM query_relationships WHERE run_id = ? AND (source_id IN (SELECT entity_id FROM query_entities WHERE file_path = (SELECT val FROM string_dict WHERE id = ?)) OR target_id IN (SELECT entity_id FROM query_entities WHERE file_path = (SELECT val FROM string_dict WHERE id = ?)))",
                    (run_id, file_id, file_id),
                )
                # 2. Delete the artifact row
                cursor = conn.execute(
                    "DELETE FROM file_artifacts WHERE run_id = ? AND file_id = ?",
                    (run_id, file_id),
                )
                rows_deleted = cursor.rowcount
                # 3. Mark file as not indexed
                conn.execute(
                    "UPDATE file_tracking SET is_indexed = 0, last_run_id = NULL WHERE file_id = ?",
                    (file_id,),
                )
                conn.commit()
            return RepairResult(issue=issue, success=True, rows_affected=rows_deleted)
        except Exception as e:
            return RepairResult(issue=issue, success=False, error=str(e))

    def repair_run_artifact(self, issue: Issue) -> RepairResult:
        """Set corrupted column in run_artifacts to NULL."""
        run_id = issue.identifier.get("run_id")
        column = issue.identifier.get("column")
        if run_id is None or not column:
            return RepairResult(issue=issue, success=False, error="Missing run_id or column in identifier")

        # Allowlist columns dynamically from the database schema to prevent SQL injection
        try:
            with self.db.connection() as conn:
                cursor = conn.execute("PRAGMA table_info(run_artifacts)")
                columns_info = cursor.fetchall()
                allowed_columns = {row["name"] for row in columns_info}
        except Exception as e:
            return RepairResult(issue=issue, success=False, error=f"Failed to query database schema: {e}")

        # Exclude key/non-blob columns that must not be set to NULL
        forbidden_columns = {"run_id", "schema_version", "created_at"}
        if column not in allowed_columns or column in forbidden_columns:
            return RepairResult(issue=issue, success=False, error=f"Invalid or forbidden column name: {column}")

        try:
            with self.db.connection() as conn:
                cursor = conn.execute(
                    f"UPDATE run_artifacts SET {column} = NULL WHERE run_id = ?",
                    (run_id,),
                )
                rows_updated = cursor.rowcount
                conn.commit()
            return RepairResult(issue=issue, success=True, rows_affected=rows_updated)
        except Exception as e:
            return RepairResult(issue=issue, success=False, error=str(e))

    def repair_changelog(self, issue: Issue) -> RepairResult:
        """Delete corrupted changelog row."""
        row_id = issue.identifier.get("id")
        if row_id is None:
            return RepairResult(issue=issue, success=False, error="Missing id in identifier")

        try:
            with self.db.connection() as conn:
                cursor = conn.execute("DELETE FROM file_changelog WHERE id = ?", (row_id,))
                rows_deleted = cursor.rowcount
                conn.commit()
            return RepairResult(issue=issue, success=True, rows_affected=rows_deleted)
        except Exception as e:
            return RepairResult(issue=issue, success=False, error=str(e))
