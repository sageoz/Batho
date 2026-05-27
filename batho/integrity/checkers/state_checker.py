"""State Consistency Checker (Phase 2)."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any
import sqlite3

from ..models import CheckReport, CheckStatus, Issue, Severity
from ..repairers.state_repairer import StateRepairer


class StateConsistencyChecker:
    """Checker for relational database consistency and state anomalies."""

    def __init__(self, db: Any, dry_run: bool = False):
        self.db = db
        self.dry_run = dry_run
        self.repairer = StateRepairer(db)

    def check_stuck_runs(self, conn: sqlite3.Connection) -> list[Issue]:
        """Find runs that are marked 'running' but started more than 24 hours ago."""
        issues = []
        now = datetime.now(timezone.utc)
        threshold = now - timedelta(hours=24)

        rows = conn.execute(
            "SELECT id, run_uuid, started_at FROM index_runs WHERE status = 'running'"
        ).fetchall()

        for row in rows:
            run_id, run_uuid, started_at_str = row
            try:
                # Handle potential timezone offsets
                dt_str = started_at_str
                if dt_str.endswith("Z"):
                    dt_str = dt_str[:-1] + "+00:00"
                started_at = datetime.fromisoformat(dt_str)
                if started_at.tzinfo is None:
                    started_at = started_at.replace(tzinfo=timezone.utc)
            except Exception:
                # If timestamp is unparseable, mark it as stuck anyway
                started_at = threshold - timedelta(seconds=1)

            if started_at < threshold:
                issues.append(
                    Issue(
                        type="stuck_run",
                        severity=Severity.WARNING,
                        table="index_runs",
                        identifier={"run_uuid": run_uuid},
                        description=f"Run {run_uuid} has been 'running' since {started_at_str}.",
                        repair_strategy="fail_stuck_run",
                    )
                )
        return issues

    def check_string_dict_orphans(self, conn: sqlite3.Connection) -> list[Issue]:
        """Find strings with no referencing file_id or root_path_id."""
        issues = []
        query = """
            SELECT id, val FROM string_dict
            WHERE id NOT IN (SELECT root_path_id FROM index_runs)
              AND id NOT IN (SELECT file_id FROM file_artifacts)
              AND id NOT IN (SELECT file_id FROM file_tracking)
              AND id NOT IN (SELECT file_id FROM file_changelog)
        """
        rows = conn.execute(query).fetchall()
        for row in rows:
            sid, val = row
            issues.append(
                Issue(
                    type="orphaned_string",
                    severity=Severity.INFO,
                    table="string_dict",
                    identifier={"id": sid},
                    description=f"Orphaned string ID {sid}: '{val}'",
                    repair_strategy="delete_orphaned_string",
                )
            )
        return issues

    def check_file_tracking_consistency(self, conn: sqlite3.Connection) -> list[Issue]:
        """Verify file_tracking vs file_artifacts consistency."""
        issues = []
        query = """
            SELECT ft.file_id, sd.val, ft.last_run_id
            FROM file_tracking ft
            JOIN string_dict sd ON ft.file_id = sd.id
            WHERE ft.is_indexed = 1
              AND (
                  ft.file_id NOT IN (SELECT file_id FROM file_artifacts)
                  OR (
                      ft.last_run_id IS NOT NULL
                      AND NOT EXISTS (
                          SELECT 1 FROM file_artifacts fa
                          JOIN index_runs ir ON fa.run_id = ir.id
                          WHERE fa.file_id = ft.file_id AND ir.run_uuid = ft.last_run_id
                      )
                  )
              )
        """
        rows = conn.execute(query).fetchall()
        for row in rows:
            file_id, file_path, last_run_id = row
            issues.append(
                Issue(
                    type="tracking_desync",
                    severity=Severity.ERROR,
                    table="file_tracking",
                    identifier={"file_id": file_id},
                    description=f"File '{file_path}' (ID {file_id}) is marked indexed but has no artifacts in latest run.",
                    repair_strategy="reset_file_tracking",
                )
            )
        return issues

    def run(self) -> CheckReport:
        """Run all Phase 2 checks and apply repairs if not dry_run."""
        start_time = time.time()
        issues = []

        try:
            with self.db.connection() as conn:
                issues.extend(self.check_stuck_runs(conn))
                issues.extend(self.check_string_dict_orphans(conn))
                issues.extend(self.check_file_tracking_consistency(conn))
        except Exception as e:
            issues.append(
                Issue(
                    type="state_check_error",
                    severity=Severity.ERROR,
                    table="sqlite_master",
                    identifier={},
                    description=f"Error executing state consistency checks: {e}",
                )
            )

        repairs = []
        if not self.dry_run:
            for issue in issues:
                if issue.repair_strategy:
                    res = self.repairer.repair(issue)
                    repairs.append(res)

        status = CheckStatus.PASSED
        if issues:
            status = CheckStatus.FIXED if any(r.success for r in repairs) else CheckStatus.FAILED

        # If any unresolved critical or error issues remain, mark failed
        unresolved = [
            i for i in issues
            if not any(r.issue == i and r.success for r in repairs)
        ]
        if any(ui.severity in (Severity.CRITICAL, Severity.ERROR) for ui in unresolved):
            status = CheckStatus.FAILED

        duration_ms = int((time.time() - start_time) * 1000)
        return CheckReport(
            phase="state",
            status=status,
            issues=issues,
            repairs=repairs,
            duration_ms=duration_ms,
            metrics={"issues_count": len(issues), "repairs_count": len(repairs)},
        )
