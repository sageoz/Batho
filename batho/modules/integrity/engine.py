"""Core fix engine for orchestrating integrity checks and repairs."""

from __future__ import annotations

import time
import uuid
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import concurrent.futures

from batho.modules.storage.arrow_bundle.bundle import BathoBundle as BathoDatabase, get_bundle as get_database
from batho.utils.logging import get_logger
from .models import CheckReport, CheckStatus, Issue, RepairResult, Severity

LOGGER = get_logger(__name__, component="integrity")


@dataclass
class FixContext:
    """Context passed to all integrity checks."""

    root: Path
    db: BathoDatabase
    deep_mode: bool = False
    dry_run: bool = False
    audit_log: list[dict] = field(default_factory=list)
    run_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    # Cached data (lazy loaded)
    _index_runs: list[dict] | None = None
    _latest_run: dict | None = None

    def get_index_runs(self) -> list[dict]:
        """Get all index runs from bundle."""
        if self._index_runs is None:
            self._index_runs = self.db._reader.get_all_runs()
        return self._index_runs

    def get_latest_run(self) -> dict | None:
        """Get the most recent completed index run."""
        if self._latest_run is None:
            runs = self.get_index_runs()
            for run in runs:
                if run.get("status") == "completed":
                    self._latest_run = run
                    break
        return self._latest_run

    def log_audit(self, action: str, details: dict[str, Any]) -> None:
        """Log an audit entry."""
        entry = {
            "run_id": self.run_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "details": details,
        }
        self.audit_log.append(entry)
        LOGGER.info("audit_log_entry", **entry)

    def persist_audit_log(self) -> None:
        """Log audit entries (Arrow bundle has no writable audit table; log only)."""
        for entry in self.audit_log:
            LOGGER.info("audit_log_entry", **entry)
        self.audit_log.clear()


@dataclass
class FixSummary:
    """Summary of fix execution results."""

    checks_passed: int = 0
    checks_failed: int = 0
    checks_fixed: int = 0
    checks_skipped: int = 0
    findings_critical: int = 0
    findings_error: int = 0
    findings_warning: int = 0
    findings_info: int = 0
    repairs_attempted: int = 0
    repairs_successful: int = 0
    duration_ms: int = 0

    @property
    def total_checks(self) -> int:
        return self.checks_passed + self.checks_failed + self.checks_fixed + self.checks_skipped

    @property
    def total_findings(self) -> int:
        return (
            self.findings_critical
            + self.findings_error
            + self.findings_warning
            + self.findings_info
        )

    @property
    def exit_code(self) -> int:
        """Exit code: 0 = all good/fixed, 1 = unfixable issues, 2 = critical errors."""
        if self.findings_critical > 0:
            # Check if there are any unfixed critical issues
            return 2
        if self.findings_error > 0 and self.repairs_successful < self.repairs_attempted:
            return 1
        return 0


@dataclass
class FixResult:
    """Complete result from a fix execution."""

    started_at: str
    completed_at: str
    root: str
    bundle_dir: str
    mode: str
    summary: FixSummary
    check_results: list[CheckReport] = field(default_factory=list)
    repairs: list[RepairResult] = field(default_factory=list)


class FixEngine:
    """Orchestrates integrity checks and automatic repairs."""

    def __init__(
        self,
        root: Path,
        deep_mode: bool = False,
        dry_run: bool = False,
        target: str = "all",      # db, state, blobs, graph, all
        phase: int | None = None, # 1-4
        parallel: bool = False,
        verbose: bool = False,
    ):
        self.root = Path(root).resolve()
        self.deep_mode = deep_mode
        self.dry_run = dry_run
        self.target = target
        self.phase = phase
        self.parallel = parallel
        self.verbose = verbose

        # Lazy loaded
        self._db: BathoDatabase | None = None

    @property
    def db(self) -> BathoDatabase:
        """Get or create Arrow bundle handle."""
        if self._db is None:
            self._db = get_database(self.root)
        return self._db

    def run(self) -> FixResult:
        """Execute integrity verification and repair pipeline."""
        started_at = datetime.now(timezone.utc).isoformat()
        start_time = time.time()

        LOGGER.info(
            "fix_engine_start",
            root=str(self.root),
            deep_mode=self.deep_mode,
            dry_run=self.dry_run,
            target=self.target,
            phase=self.phase,
            parallel=self.parallel,
        )

        # Check bundle exists
        from batho.modules.storage.arrow_bundle import resolve_bundle_dir
        bundle_dir = resolve_bundle_dir(self.root)
        if not (bundle_dir / "meta.json").exists():
            raise FileNotFoundError(f"No artifact bundle found in {self.root}")

        ctx = FixContext(
            root=self.root,
            db=self.db,
            deep_mode=self.deep_mode,
            dry_run=self.dry_run,
        )

        # Instantiate checkers
        from .checkers.bundle_checker import BundleHealthChecker
        from .checkers.state_checker import StateConsistencyChecker
        from .checkers.blob_checker import BlobIntegrityChecker
        from .checkers.graph_checker import GraphSyncChecker

        c_db = BundleHealthChecker(self.db, self.dry_run)
        c_state = StateConsistencyChecker(self.db, self.dry_run)
        c_blobs = BlobIntegrityChecker(self.db, self.dry_run, self.deep_mode)
        c_graph = GraphSyncChecker(self.db, self.dry_run, self.deep_mode)

        # Filter which phases should run based on CLI target/phase flags
        scheduled: dict[int, Any] = {}

        # Mapping phase to checker
        all_phases = {
            1: ("bundle", c_db),
            2: ("state", c_state),
            3: ("blobs", c_blobs),
            4: ("graph", c_graph),
        }

        for p_num, (p_name, checker) in all_phases.items():
            run_this = False
            if self.phase is not None:
                if self.phase == p_num:
                    run_this = True
            else:
                if self.target == "all" or self.target == p_name:
                    run_this = True
            
            if run_this:
                scheduled[p_num] = (p_name, checker)

        check_reports: list[CheckReport] = []

        if self.parallel:
            # Concurrent execution (no fail-fast ordering constraints)
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future_to_phase = {
                    executor.submit(checker.run): p_num
                    for p_num, (_, checker) in scheduled.items()
                }
                results = {}
                for future in concurrent.futures.as_completed(future_to_phase):
                    p_num = future_to_phase[future]
                    try:
                        results[p_num] = future.result()
                    except Exception as e:
                        p_name = all_phases[p_num][0]
                        results[p_num] = CheckReport(
                            phase=p_name,
                            status=CheckStatus.FAILED,
                            issues=[
                                Issue(
                                    type="runner_error",
                                    severity=Severity.ERROR,
                                    table="arrow_bundle",
                                    identifier={},
                                    description=f"Phase execution crashed: {e}",
                                )
                            ],
                        )
                # Sort reports by phase number
                for p_num in sorted(scheduled.keys()):
                    check_reports.append(results[p_num])
        else:
            # Sequential execution with fail-fast requirements
            # 1. SQLiteHealthChecker (always first)
            p1_passed = True
            if 1 in scheduled:
                report = c_db.run()
                check_reports.append(report)
                if report.status == CheckStatus.FAILED:
                    p1_passed = False
            
            # 2. StateConsistencyChecker (only if Phase 1 passes)
            p2_passed = True
            if 2 in scheduled:
                if p1_passed:
                    report = c_state.run()
                    check_reports.append(report)
                    if report.status == CheckStatus.FAILED:
                        p2_passed = False
                else:
                    check_reports.append(CheckReport(phase="state", status=CheckStatus.SKIPPED))
                    p2_passed = False

            # 3. BlobIntegrityChecker (only if Phase 1 and 2 pass)
            p3_passed = True
            if 3 in scheduled:
                if p1_passed and p2_passed:
                    report = c_blobs.run()
                    check_reports.append(report)
                    if report.status == CheckStatus.FAILED:
                        p3_passed = False
                else:
                    check_reports.append(CheckReport(phase="blobs", status=CheckStatus.SKIPPED))
                    p3_passed = False

            # 4. GraphSyncChecker (only if Phase 3 passes)
            if 4 in scheduled:
                # If phase 3 is scheduled, check if it passed.
                # If phase 3 wasn't scheduled, but phase 1/2 passed, we can run it.
                phase_3_ok = p3_passed if (3 in scheduled) else (p1_passed and p2_passed)
                if phase_3_ok:
                    report = c_graph.run()
                    check_reports.append(report)
                else:
                    check_reports.append(CheckReport(phase="graph", status=CheckStatus.SKIPPED))

        # Log audit logs for completed checks and repairs
        for report in check_reports:
            ctx.log_audit(
                "check_completed",
                {
                    "check_name": report.phase,
                    "status": report.status.value,
                    "details_json": json.dumps({"issues_count": len(report.issues)}),
                },
            )
            for res in report.repairs:
                ctx.log_audit(
                    "repair_completed",
                    {
                        "check_name": res.issue.type,
                        "severity": res.issue.severity.value,
                        "message": res.issue.description,
                        "success": res.success,
                        "details_json": json.dumps({
                            "error": res.error,
                            "rows_affected": res.rows_affected,
                        }),
                    },
                )

        ctx.persist_audit_log()

        # Build summary
        summary = FixSummary()
        all_repairs = []
        for report in check_reports:
            if report.status == CheckStatus.PASSED:
                summary.checks_passed += 1
            elif report.status == CheckStatus.FAILED:
                summary.checks_failed += 1
            elif report.status == CheckStatus.FIXED:
                summary.checks_fixed += 1
            elif report.status == CheckStatus.SKIPPED:
                summary.checks_skipped += 1

            for issue in report.issues:
                if issue.severity == Severity.CRITICAL:
                    summary.findings_critical += 1
                elif issue.severity == Severity.ERROR:
                    summary.findings_error += 1
                elif issue.severity == Severity.WARNING:
                    summary.findings_warning += 1
                elif issue.severity == Severity.INFO:
                    summary.findings_info += 1

            for repair in report.repairs:
                all_repairs.append(repair)
                summary.repairs_attempted += 1
                if repair.success:
                    summary.repairs_successful += 1

        duration_ms = int((time.time() - start_time) * 1000)
        summary.duration_ms = duration_ms

        completed_at = datetime.now(timezone.utc).isoformat()

        return FixResult(
            started_at=started_at,
            completed_at=completed_at,
            root=str(self.root),
            bundle_dir=str(bundle_dir),
            mode="deep" if self.deep_mode else "quick",
            summary=summary,
            check_results=check_reports,
            repairs=all_repairs,
        )


__all__ = [
    "FixEngine",
    "FixContext",
    "FixResult",
    "FixSummary",
]
