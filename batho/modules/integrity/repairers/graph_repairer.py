"""Graph Repairer."""

from __future__ import annotations

from typing import Any

from ..models import Issue, RepairResult


class GraphRepairer:
    """Repairer for hypergraph synchronization and dangling reference issues."""

    def __init__(self, db: Any):
        self.db = db

    def repair(self, issue: Issue) -> RepairResult:
        """Dispatch to appropriate repair strategy."""
        if issue.repair_strategy == "resolve_dangling":
            return self.repair_dangling(issue)
        elif issue.repair_strategy == "delete_invalid_relationship":
            return self.repair_invalid_relationship(issue)
        else:
            return RepairResult(
                issue=issue,
                success=False,
                error=f"Unknown or unhandled repair strategy: {issue.repair_strategy}",
            )

    def repair_dangling(self, issue: Issue) -> RepairResult:
        """Resolve dangling references via the shared Arrow current/ store."""
        try:
            from batho.modules.storage.arrow_store.store import BsgScratchStore
            current_dir = self.db._repo_root / ".batho" / "bsg" / "current"
            if not current_dir.exists():
                return RepairResult(issue=issue, success=True, rows_affected=0)
            store = BsgScratchStore.from_run_dir(current_dir, run_internal_id=0)
            resolved_count = store.resolve_dangling(self.db)
            return RepairResult(issue=issue, success=True, rows_affected=resolved_count)
        except Exception as e:
            return RepairResult(issue=issue, success=False, error=str(e))

    def repair_invalid_relationship(self, issue: Issue) -> RepairResult:
        """Delete invalid relationship rows."""
        src_id = issue.identifier.get("source_id")
        tgt_id = issue.identifier.get("target_id")
        rel_type = issue.identifier.get("relation_type")
        run_id = issue.identifier.get("run_id")

        if any(v is None for v in (src_id, tgt_id, rel_type, run_id)):
            return RepairResult(issue=issue, success=False, error="Missing fields in relationship identifier")

        try:
            # Resolve src_id and tgt_id to keys
            src_key = self.db.bulk_get_or_create_entity_ids([src_id]).get(src_id)
            tgt_key = self.db.bulk_get_or_create_entity_ids([tgt_id]).get(tgt_id)
            if src_key is None or tgt_key is None:
                return RepairResult(issue=issue, success=True, rows_affected=0)

            with self.db.connection() as conn:
                cursor = conn.execute(
                    "DELETE FROM query_relationships WHERE source_key = ? AND target_key = ? AND relation_type = ? AND run_id = ?",
                    (src_key, tgt_key, rel_type, run_id),
                )
                rows_deleted = cursor.rowcount
                conn.commit()
            return RepairResult(issue=issue, success=True, rows_affected=rows_deleted)
        except Exception as e:
            return RepairResult(issue=issue, success=False, error=str(e))
