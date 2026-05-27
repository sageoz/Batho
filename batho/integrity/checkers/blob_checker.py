"""Blob Integrity Checker (Phase 3)."""

from __future__ import annotations

import time
from typing import Any
import sqlite3
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

    def check_file_artifacts(self, conn: sqlite3.Connection) -> list[Issue]:
        """Check all file artifacts views."""
        issues = []
        rows = conn.execute(
            "SELECT run_id, file_id, bsg_agent_view, bsg_storage_view, bsg_rel_view FROM file_artifacts"
        ).fetchall()

        for row in rows:
            run_id, file_id, agent_view, storage_view, rel_view = row
            views = {
                "bsg_agent_view": agent_view,
                "bsg_storage_view": storage_view,
                "bsg_rel_view": rel_view,
            }
            for view_name, blob in views.items():
                ok, err = self._check_blob(blob)
                if not ok:
                    issues.append(
                        Issue(
                            type="corrupt_file_artifact",
                            severity=Severity.ERROR,
                            table="file_artifacts",
                            identifier={"run_id": run_id, "file_id": file_id},
                            description=f"Corrupted blob '{view_name}' for run_id {run_id}, file_id {file_id}: {err}",
                            repair_strategy="delete_corrupt_file_artifact",
                        )
                    )
                    # Break to avoid duplicating issues for the same file artifact row
                    break
        return issues

    def check_run_artifacts(self, conn: sqlite3.Connection) -> list[Issue]:
        """Check all run artifacts views."""
        issues = []
        columns = [
            "context_overview",
            "telemetry_metrics",
            "structural_metrics",
            "security_audit",
            "artifact_payload",
            "delta_stats",
        ]
        query = f"SELECT run_id, {', '.join(columns)} FROM run_artifacts"
        rows = conn.execute(query).fetchall()

        for row in rows:
            run_id = row[0]
            for i, col in enumerate(columns, start=1):
                blob = row[i]
                ok, err = self._check_blob(blob)
                if not ok:
                    issues.append(
                        Issue(
                            type="corrupt_run_artifact",
                            severity=Severity.ERROR,
                            table="run_artifacts",
                            identifier={"run_id": run_id, "column": col},
                            description=f"Corrupted blob column '{col}' for run_id {run_id}: {err}",
                            repair_strategy="clear_corrupt_run_artifact",
                        )
                    )
        return issues

    def check_file_changelog(self, conn: sqlite3.Connection) -> list[Issue]:
        """Check file changelog node changes blobs."""
        issues = []
        rows = conn.execute("SELECT id, run_id, file_id, node_changes FROM file_changelog").fetchall()

        for row in rows:
            row_id, run_id, file_id, node_changes = row
            ok, err = self._check_blob(node_changes)
            if not ok:
                issues.append(
                    Issue(
                        type="corrupt_changelog",
                        severity=Severity.ERROR,
                        table="file_changelog",
                        identifier={"id": row_id},
                        description=f"Corrupted node_changes blob in file_changelog (ID {row_id}, run_id {run_id}, file_id {file_id}): {err}",
                        repair_strategy="delete_corrupt_changelog",
                    )
                )
        return issues

    def run(self) -> CheckReport:
        """Run all Phase 3 checks and apply repairs if not dry_run."""
        start_time = time.time()
        issues = []

        try:
            with self.db.connection() as conn:
                issues.extend(self.check_file_artifacts(conn))
                issues.extend(self.check_run_artifacts(conn))
                issues.extend(self.check_file_changelog(conn))
        except Exception as e:
            issues.append(
                Issue(
                    type="blob_check_error",
                    severity=Severity.ERROR,
                    table="sqlite_master",
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
