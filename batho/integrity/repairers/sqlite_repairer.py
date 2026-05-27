"""SQLite Repairer."""

from __future__ import annotations

import os
from pathlib import Path
import sqlite3
from typing import Any

from ..models import Issue, RepairResult


class SQLiteRepairer:
    """Repairer for SQLite database health and settings."""

    def __init__(self, db: Any):
        self.db = db

    def repair(self, issue: Issue) -> RepairResult:
        """Dispatch to appropriate repair strategy."""
        if issue.repair_strategy == "enable_foreign_keys":
            return self.repair_pragma_settings(issue)
        elif issue.repair_strategy == "dump_and_restore":
            return self.repair_dump_and_restore(issue)
        elif issue.repair_strategy == "recommend_rebuild":
            return RepairResult(
                issue=issue,
                success=False,
                error="Please run 'batho build --full' to rebuild the schema and database.",
            )
        else:
            return RepairResult(
                issue=issue,
                success=False,
                error=f"Unknown or unhandled repair strategy: {issue.repair_strategy}",
            )

    def repair_pragma_settings(self, issue: Issue) -> RepairResult:
        """Enable foreign keys pragma."""
        try:
            with self.db.connection() as conn:
                conn.execute("PRAGMA foreign_keys = ON")
                conn.commit()
            return RepairResult(issue=issue, success=True, rows_affected=0)
        except Exception as e:
            return RepairResult(issue=issue, success=False, error=str(e))

    def repair_dump_and_restore(self, issue: Issue) -> RepairResult:
        """Recover corrupt SQLite database using iterdump."""
        db_path = Path(self.db.path)
        temp_db_path = db_path.with_suffix(".batho.recover")
        backup_db_path = db_path.with_suffix(".batho.bak")

        try:
            # 1. Close current database connections cached in the module
            from batho.storage.engine import _DB_CACHE
            # clear cache key for this path
            key = str(db_path.resolve())
            if key in _DB_CACHE:
                _DB_CACHE[key]._closed = True
                del _DB_CACHE[key]

            # 2. Open source connection
            src_conn = sqlite3.connect(str(db_path))
            
            # 3. Create temp db and dump into it
            if temp_db_path.exists():
                temp_db_path.unlink()

            dest_conn = sqlite3.connect(str(temp_db_path))
            
            # Run recovery dump
            for line in src_conn.iterdump():
                try:
                    dest_conn.execute(line)
                except sqlite3.Error:
                    # Ignore corrupted rows during recovery to salvage remaining data
                    pass
            
            dest_conn.commit()
            dest_conn.close()
            src_conn.close()

            # 4. Swap files
            if backup_db_path.exists():
                backup_db_path.unlink()
            
            db_path.rename(backup_db_path)
            temp_db_path.rename(db_path)

            return RepairResult(
                issue=issue,
                success=True,
                rows_affected=1,
            )
        except Exception as e:
            if temp_db_path.exists():
                try:
                    temp_db_path.unlink()
                except Exception:
                    pass
            return RepairResult(issue=issue, success=False, error=f"Dump and restore failed: {e}")
