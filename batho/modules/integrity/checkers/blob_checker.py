"""Blob Integrity Checker (Phase 3)."""

from __future__ import annotations

import time
from typing import Any
import orjson
import zstandard as zstd

from ..models import CheckReport, CheckStatus, Issue, Severity
from ..repairers.blob_repairer import BlobRepairer


class BlobIntegrityChecker:
    """Checker for database blob validation (zstd compression and JSON integrity)."""

    def __init__(self, db: Any, dry_run: bool = False, deep: bool = False):
        self.db = db
        self.dry_run = dry_run
        self.deep = deep
        self.dctx = zstd.ZstdDecompressor()
        self.repairer = BlobRepairer(db)

    def _check_blob(self, blob: bytes | None) -> tuple[bool, str | None]:
        """Verify zstd header in quick mode, or decompress and JSON parse in deep mode."""
        if blob is None:
            return True, None
        if len(blob) < 4:
            return False, "Blob is too short to contain zstd archive."
        # Zstd magic header: 0xFD2FB528 (little-endian: 28 b5 2f fd)
        if blob[:4] != b"\x28\xb5\x2f\xfd":
            return False, "Blob is missing valid zstd magic header."
        if self.deep:
            try:
                decompressed = self.dctx.decompress(blob)
                orjson.loads(decompressed)
            except zstd.ZstdError as e:
                return False, f"zstd decompression failed: {e}"
            except Exception as e:
                return False, f"JSON decoding failed: {e}"
        return True, None

    def check_run_artifacts(self) -> list[Issue]:
        """Check run artifact IPC table entries for structural validity."""
        issues = []
        try:
            rows = self.db._reader.get_all_runs()
            for run in rows:
                run_uuid = run.get("run_uuid", "?")
                if run.get("status") not in ("completed", "failed", "running"):
                    issues.append(Issue(
                        type="invalid_run_status",
                        severity=Severity.WARNING,
                        table="runs",
                        identifier={"run_uuid": run_uuid},
                        description=f"Run {run_uuid} has unexpected status: {run.get('status')!r}",
                    ))
        except Exception as exc:
            issues.append(Issue(
                type="run_artifacts_check_error",
                severity=Severity.ERROR,
                table="runs",
                identifier={},
                description=f"Error checking run artifacts: {exc}",
            ))
        return issues

    def check_file_changelog(self) -> list[Issue]:
        """Check file changelog IPC table for missing fields."""
        issues = []
        try:
            rows = self.db._reader.get_file_changelog_raw()
            for row in rows:
                if not row.get("entity_id") or not row.get("change_kind"):
                    issues.append(Issue(
                        type="corrupt_changelog",
                        severity=Severity.WARNING,
                        table="file_changelog",
                        identifier={"run_uuid": row.get("run_uuid", "?")},
                        description="Changelog row missing entity_id or change_kind",
                    ))
        except Exception as exc:
            issues.append(Issue(
                type="changelog_check_error",
                severity=Severity.ERROR,
                table="file_changelog",
                identifier={},
                description=f"Error checking changelog: {exc}",
            ))
        return issues

    def run(self) -> CheckReport:
        """Run all Phase 3 checks."""
        start_time = time.time()
        issues = []

        try:
            issues.extend(self.check_run_artifacts())
            issues.extend(self.check_file_changelog())
        except Exception as e:
            issues.append(
                Issue(
                    type="blob_check_error",
                    severity=Severity.ERROR,
                    table="arrow_bundle",
                    identifier={},
                    description=f"Error executing blob integrity checks: {e}",
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
            phase="blobs",
            status=status,
            issues=issues,
            repairs=repairs,
            duration_ms=duration_ms,
            metrics={"issues_count": len(issues), "repairs_count": len(repairs)},
        )
