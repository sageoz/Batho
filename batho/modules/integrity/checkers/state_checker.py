"""State Consistency Checker (Phase 2)."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any
from ..models import CheckReport, CheckStatus, Issue, Severity
from ..repairers.state_repairer import StateRepairer


class StateConsistencyChecker:
    """Checker for relational database consistency and state anomalies."""

    def __init__(self, db: Any, dry_run: bool = False):
        self.db = db
        self.dry_run = dry_run
        self.repairer = StateRepairer(db)

    def check_stuck_runs(self) -> list[Issue]:
        """Find runs that are marked 'running' but started more than 24 hours ago, or are stale due to process termination."""
        issues = []
        now = datetime.now(timezone.utc)
        threshold = now - timedelta(hours=24)

        # Check if another process is holding the workspace lock
        from batho.utils.file_io import InterProcessLock
        lock_file = self.db.repo_root / ".batho" / "batho.lock"
        is_locked_by_other = InterProcessLock.is_locked_by_other(lock_file)

        for run in self.db._reader.get_all_runs():
            if run.get("status") != "running":
                continue

            # If this is the active run in our current bundle instance, it is not stale
            if run.get("run_uuid") in [r["run_uuid"] for r in getattr(self.db, "_run_rows", [])]:
                continue

            started_at_str = run.get("started_at", "")
            try:
                dt_str = started_at_str
                if dt_str.endswith("Z"):
                    dt_str = dt_str[:-1] + "+00:00"
                started_at = datetime.fromisoformat(dt_str)
                if started_at.tzinfo is None:
                    started_at = started_at.replace(tzinfo=timezone.utc)
            except Exception:
                started_at = threshold - timedelta(seconds=1)

            if started_at < threshold or not is_locked_by_other:
                issues.append(Issue(
                    type="stuck_run",
                    severity=Severity.WARNING,
                    table="runs",
                    identifier={"run_uuid": run.get("run_uuid")},
                    description=f"Run {run.get('run_uuid')} has been 'running' since {started_at_str}.",
                    repair_strategy="fail_stuck_run",
                ))
        return issues

    def check_file_tracking_consistency(self) -> list[Issue]:
        """Spot-check: file_tracking entries with is_indexed=True have a known run."""
        issues = []
        latest_run_id = self.db.get_latest_run_id()
        if not latest_run_id:
            return issues
        tracking = self.db.get_all_file_tracking()
        for file_path, row in tracking.items():
            if row.get("is_indexed") and row.get("last_run_uuid") and row["last_run_uuid"] != latest_run_id:
                issues.append(Issue(
                    type="tracking_stale_run_ref",
                    severity=Severity.INFO,
                    table="file_tracking",
                    identifier={"file_path": file_path},
                    description=(
                        f"File '{file_path}' last indexed in {row['last_run_uuid']!r}, "
                        f"but current run is {latest_run_id!r}"
                    ),
                ))
        return issues

    def run(self) -> CheckReport:
        """Run all Phase 2 checks and apply repairs if not dry_run."""
        start_time = time.time()
        issues = []

        try:
            issues.extend(self.check_stuck_runs())
            issues.extend(self.check_file_tracking_consistency())
        except Exception as e:
            issues.append(Issue(
                type="state_check_error",
                severity=Severity.ERROR,
                table="arrow_bundle",
                identifier={},
                description=f"Error executing state consistency checks: {e}",
            ))

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
