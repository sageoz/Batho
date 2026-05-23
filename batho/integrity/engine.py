"""Core fix engine for orchestrating integrity checks and repairs."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from batho.storage.engine import BathoDatabase, get_database
from batho.utils.logging import get_logger
from .checks import CheckStatus, Severity

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
    _artifacts: list[dict] | None = None
    _snapshots: list[dict] | None = None
    _latest_run: dict | None = None

    def get_index_runs(self) -> list[dict]:
        """Get all index runs from database."""
        if self._index_runs is None:
            with self.db.connection(read_only=True) as conn:
                rows = conn.execute(
                    "SELECT * FROM index_runs ORDER BY started_at DESC"
                ).fetchall()
                self._index_runs = [dict(row) for row in rows]
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

    def get_artifacts(self) -> list[dict]:
        """Get all non-deleted artifacts from registry."""
        if self._artifacts is None:
            with self.db.connection(read_only=True) as conn:
                rows = conn.execute(
                    "SELECT * FROM artifacts WHERE deleted = 0 ORDER BY updated_at DESC"
                ).fetchall()
                self._artifacts = [dict(row) for row in rows]
        return self._artifacts

    def get_snapshots(self) -> list[dict]:
        """Get all snapshots from database."""
        if self._snapshots is None:
            with self.db.connection(read_only=True) as conn:
                rows = conn.execute(
                    "SELECT * FROM snapshots ORDER BY created_at DESC"
                ).fetchall()
                self._snapshots = [dict(row) for row in rows]
        return self._snapshots

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
        """Persist audit log entries to database."""
        if not self.audit_log:
            return

        with self.db.connection() as conn:
            for entry in self.audit_log:
                conn.execute(
                    """INSERT INTO fix_audit_log (
                        log_id, run_id, timestamp, action, check_name,
                        severity, message, details_json, success
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        str(uuid.uuid4()),
                        entry["run_id"],
                        entry["timestamp"],
                        entry["action"],
                        entry["details"].get("check_name"),
                        entry["details"].get("severity"),
                        entry["details"].get("message"),
                        entry["details"].get("details_json", "{}"),
                        1 if entry["details"].get("success", True) else 0,
                    ),
                )
            conn.commit()
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
    db_path: str
    mode: str
    summary: FixSummary
    check_results: list[Any] = field(default_factory=list)
    repairs: list[Any] = field(default_factory=list)

    def get_findings_by_severity(self, severity: Severity) -> list[Any]:
        """Get all findings of a specific severity."""
        findings = []
        for check_result in self.check_results:
            for finding in check_result.findings:
                if finding.severity == severity:
                    findings.append(finding)
        return findings


class FixEngine:
    """Orchestrates integrity checks and automatic repairs."""

    def __init__(
        self,
        root: Path,
        deep_mode: bool = False,
        dry_run: bool = False,
        audit_log: bool = True,
        repair_only: list[str] | None = None,
    ):
        self.root = Path(root).resolve()
        self.deep_mode = deep_mode
        self.dry_run = dry_run
        self.audit_log_enabled = audit_log
        self.repair_only = repair_only

        # Lazy loaded
        self._db: BathoDatabase | None = None
        self._checks: list[Any] = []

    @property
    def db(self) -> BathoDatabase:
        """Get or create database connection."""
        if self._db is None:
            self._db = get_database(self.root)
        return self._db

    def _get_checks(self) -> list[Any]:
        """Get list of checks to run (filtered if repair_only specified)."""
        from .checks import (
            DatabaseIntegrityCheck,
            RegistryIntegrityCheck,
            IndexIntegrityCheck,
            BSGIntegrityCheck,
            SnapshotIntegrityCheck,
            CacheIntegrityCheck,
            ViewIntegrityCheck,
        )

        all_checks = [
            DatabaseIntegrityCheck(),
            RegistryIntegrityCheck(),
            IndexIntegrityCheck(),
            BSGIntegrityCheck(),
            SnapshotIntegrityCheck(),
            CacheIntegrityCheck(),
            ViewIntegrityCheck(),
        ]

        if self.repair_only:
            check_map = {c.name: c for c in all_checks}
            return [check_map[name] for name in self.repair_only if name in check_map]

        return all_checks

    def run(self) -> FixResult:
        """Execute all integrity checks and repairs."""
        started_at = datetime.now(timezone.utc).isoformat()
        start_time = time.time()

        LOGGER.info(
            "fix_engine_start",
            root=str(self.root),
            deep_mode=self.deep_mode,
            dry_run=self.dry_run,
        )

        # Check database exists
        from batho.storage.engine import artifact_filename
        db_path = self.root / artifact_filename(self.root)
        if not db_path.exists():
            # Try alternate naming
            candidates = list(self.root.glob("artifact_*.batho"))
            if not candidates:
                raise FileNotFoundError(f"No artifact database found in {self.root}")

        # Ensure audit log table exists
        self._ensure_audit_table()

        ctx = FixContext(
            root=self.root,
            db=self.db,
            deep_mode=self.deep_mode,
            dry_run=self.dry_run,
        )

        check_results = []
        repairs = []
        summary = FixSummary()

        try:
            checks = self._get_checks()

            for check in checks:
                check_start = time.time()
                result = check.run(ctx)
                result.duration_ms = int((time.time() - check_start) * 1000)

                check_results.append(result)

                # Update summary
                if result.status == CheckStatus.PASSED:
                    summary.checks_passed += 1
                elif result.status == CheckStatus.FIXED:
                    summary.checks_fixed += 1
                elif result.status == CheckStatus.FAILED:
                    summary.checks_failed += 1
                else:
                    summary.checks_skipped += 1

                # Count findings by severity
                for finding in result.findings:
                    if finding.severity.name == "CRITICAL":
                        summary.findings_critical += 1
                    elif finding.severity.name == "ERROR":
                        summary.findings_error += 1
                    elif finding.severity.name == "WARNING":
                        summary.findings_warning += 1
                    else:
                        summary.findings_info += 1

                    if finding.auto_fixed:
                        summary.repairs_attempted += 1
                        if finding.fix_error is None:
                            summary.repairs_successful += 1

                ctx.log_audit(
                    "check_completed",
                    {
                        "check_name": result.check_name,
                        "status": result.status.value,
                        "findings_count": len(result.findings),
                        "duration_ms": result.duration_ms,
                    },
                )

        except Exception as exc:
            LOGGER.error("fix_engine_error", error=str(exc))
            ctx.log_audit(
                "engine_error",
                {
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
            )

        finally:
            if self.audit_log_enabled:
                ctx.persist_audit_log()

        duration_ms = int((time.time() - start_time) * 1000)
        summary.duration_ms = duration_ms

        completed_at = datetime.now(timezone.utc).isoformat()

        LOGGER.info(
            "fix_engine_complete",
            duration_ms=duration_ms,
            checks_passed=summary.checks_passed,
            checks_failed=summary.checks_failed,
            repairs_attempted=summary.repairs_attempted,
        )

        return FixResult(
            started_at=started_at,
            completed_at=completed_at,
            root=str(self.root),
            db_path=str(self.db.path),
            mode="deep" if self.deep_mode else "quick",
            summary=summary,
            check_results=check_results,
            repairs=repairs,
        )

    def _ensure_audit_table(self) -> None:
        """Ensure the fix_audit_log table exists."""
        with self.db.connection() as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS fix_audit_log (
                    log_id          TEXT PRIMARY KEY NOT NULL,
                    run_id          TEXT NOT NULL,
                    timestamp       TEXT NOT NULL,
                    action          TEXT NOT NULL,
                    check_name      TEXT,
                    severity        TEXT,
                    message         TEXT,
                    details_json    TEXT NOT NULL DEFAULT '{}',
                    success         INTEGER NOT NULL DEFAULT 1
                ) WITHOUT ROWID"""
            )
            conn.commit()


__all__ = [
    "FixEngine",
    "FixContext",
    "FixResult",
    "FixSummary",
]
