"""AST cache and file tracking integrity check."""

from __future__ import annotations

import time
from datetime import datetime, timezone

from . import CheckResult, CheckStatus, Finding, IntegrityCheck, Severity


class CacheIntegrityCheck(IntegrityCheck):
    """Check AST cache and file tracking integrity."""

    name = "cache"
    description = "Validate AST cache entries and file tracking consistency"

    def supports_quick_mode(self) -> bool:
        return True

    def run(self, ctx: "FixContext") -> CheckResult:
        """Execute cache integrity checks."""
        from ..engine import FixContext

        start_time = time.time()
        findings = []

        # Check 1: AST cache integrity
        cache_findings = self._check_ast_cache(ctx)
        findings.extend(cache_findings)

        # Check 2: File tracking integrity
        tracking_findings = self._check_file_tracking(ctx)
        findings.extend(tracking_findings)

        # Determine status
        critical_count = sum(1 for f in findings if f.severity == Severity.CRITICAL)
        error_count = sum(1 for f in findings if f.severity == Severity.ERROR)
        fixed_count = sum(1 for f in findings if f.auto_fixed)

        if critical_count > 0:
            status = CheckStatus.FAILED
        elif error_count > 0 and fixed_count == error_count:
            status = CheckStatus.FIXED
        elif error_count > 0:
            status = CheckStatus.FAILED
        else:
            status = CheckStatus.PASSED

        duration_ms = int((time.time() - start_time) * 1000)

        return CheckResult(
            check_name=self.name,
            status=status,
            duration_ms=duration_ms,
            findings=findings,
            metrics={
                "errors_found": error_count,
                "auto_fixed": fixed_count,
            },
        )

    def _check_ast_cache(self, ctx: "FixContext") -> list[Finding]:
        """Check AST cache entries for validity and expiration."""
        findings = []

        try:
            with ctx.db.connection(read_only=True) as conn:
                # Count total entries
                total = conn.execute("SELECT COUNT(*) FROM ast_cache").fetchone()[0]

                if total == 0:
                    findings.append(
                        Finding(
                            check_name=self.name,
                            severity=Severity.INFO,
                            message="No AST cache entries found",
                            details={},
                        )
                    )
                    return findings

                # Check for expired entries
                expired = conn.execute(
                    """SELECT COUNT(*) FROM ast_cache
                    WHERE datetime(cached_at) < datetime('now', '-' || ttl_days || ' days')"""
                ).fetchone()[0]

                if expired > 0:
                    findings.append(
                        Finding(
                            check_name=self.name,
                            severity=Severity.WARNING,
                            message=f"Found {expired} expired AST cache entries",
                            details={"expired_count": expired, "total": total},
                        )
                    )

                    # Clear expired entries
                    if not ctx.dry_run:
                        try:
                            with ctx.db.connection() as repair_conn:
                                repair_conn.execute(
                                    """DELETE FROM ast_cache
                                    WHERE datetime(cached_at) < datetime('now', '-' || ttl_days || ' days')"""
                                )
                                repair_conn.commit()

                            findings[-1].auto_fixed = True
                            findings[-1].fix_attempted = True
                            findings[-1].message += " (expired entries cleared)"
                        except Exception as fix_exc:
                            findings[-1].fix_attempted = True
                            findings[-1].fix_error = str(fix_exc)

                # Validate JSON in cache entries (deep mode)
                if ctx.deep_mode:
                    import json

                    invalid = []
                    rows = conn.execute(
                        "SELECT file_hash, entities_json FROM ast_cache"
                    ).fetchall()

                    for row in rows:
                        try:
                            data = json.loads(row["entities_json"])
                            if not isinstance(data, list):
                                invalid.append(row["file_hash"])
                        except json.JSONDecodeError:
                            invalid.append(row["file_hash"])

                    if invalid:
                        findings.append(
                            Finding(
                                check_name=self.name,
                                severity=Severity.ERROR,
                                message=f"Found {len(invalid)} AST cache entries with invalid JSON",
                                details={
                                    "invalid_count": len(invalid),
                                    "sample_hashes": invalid[:5],
                                },
                            )
                        )

                        # Delete invalid entries
                        if not ctx.dry_run:
                            try:
                                with ctx.db.connection() as repair_conn:
                                    for file_hash in invalid:
                                        repair_conn.execute(
                                            "DELETE FROM ast_cache WHERE file_hash = ?",
                                            (file_hash,),
                                        )
                                    repair_conn.commit()

                                findings[-1].auto_fixed = True
                                findings[-1].fix_attempted = True
                                findings[-1].message += " (invalid entries deleted)"
                            except Exception as fix_exc:
                                findings[-1].fix_attempted = True
                                findings[-1].fix_error = str(fix_exc)

                if not any(f.severity in (Severity.ERROR, Severity.WARNING) for f in findings):
                    findings.append(
                        Finding(
                            check_name=self.name,
                            severity=Severity.INFO,
                            message="AST cache integrity validated",
                            details={"total_entries": total},
                        )
                    )

        except Exception as exc:
            findings.append(
                Finding(
                    check_name=self.name,
                    severity=Severity.WARNING,
                    message=f"Could not check AST cache: {exc}",
                    details={"error": str(exc)},
                )
            )

        return findings

    def _check_file_tracking(self, ctx: "FixContext") -> list[Finding]:
        """Check file tracking consistency with filesystem."""
        findings = []

        try:
            with ctx.db.connection(read_only=True) as conn:
                # Count total tracked files
                total = conn.execute("SELECT COUNT(*) FROM file_tracking").fetchone()[0]

                if total == 0:
                    findings.append(
                        Finding(
                            check_name=self.name,
                            severity=Severity.INFO,
                            message="No file tracking entries found",
                            details={},
                        )
                    )
                    return findings

                # Quick mode: sample 100 files
                if ctx.deep_mode:
                    rows = conn.execute(
                        "SELECT file_path, content_hash, mtime, size FROM file_tracking"
                    ).fetchall()
                else:
                    # Sample for quick check
                    rows = conn.execute(
                        """SELECT file_path, content_hash, mtime, size FROM file_tracking
                        ORDER BY updated_at DESC LIMIT 100"""
                    ).fetchall()

                missing_files = 0
                hash_mismatches = 0

                for row in rows:
                    file_path = ctx.root / row["file_path"]

                    if not file_path.exists():
                        missing_files += 1
                        continue

                    # Check mtime and size (deep mode only)
                    if ctx.deep_mode:
                        try:
                            stat = file_path.stat()
                            stored_mtime = row["mtime"]
                            stored_size = row["size"]

                            if abs(stat.st_mtime - stored_mtime) > 1 or stat.st_size != stored_size:
                                # File has changed, hash should differ
                                from batho.utils.hash import compute_file_hash

                                actual_hash = compute_file_hash(file_path)
                                if actual_hash != row["content_hash"]:
                                    hash_mismatches += 1
                        except Exception:
                            pass

                if missing_files > 0:
                    findings.append(
                        Finding(
                            check_name=self.name,
                            severity=Severity.WARNING,
                            message=f"Found {missing_files} tracked files that no longer exist",
                            details={"missing_count": missing_files, "sampled": len(rows)},
                        )
                    )

                    # Remove missing files from tracking
                    if not ctx.dry_run and ctx.deep_mode:
                        try:
                            with ctx.db.connection() as repair_conn:
                                for row in rows:
                                    file_path = ctx.root / row["file_path"]
                                    if not file_path.exists():
                                        repair_conn.execute(
                                            "DELETE FROM file_tracking WHERE file_path = ?",
                                            (row["file_path"],),
                                        )
                                repair_conn.commit()

                            findings[-1].auto_fixed = True
                            findings[-1].fix_attempted = True
                            findings[-1].message += " (missing files removed from tracking)"
                        except Exception as fix_exc:
                            findings[-1].fix_attempted = True
                            findings[-1].fix_error = str(fix_exc)

                if hash_mismatches > 0:
                    findings.append(
                        Finding(
                            check_name=self.name,
                            severity=Severity.INFO,
                            message=f"Found {hash_mismatches} files with content hash mismatches (expected - files modified)",
                            details={"mismatch_count": hash_mismatches},
                        )
                    )

                if not any(f.severity in (Severity.ERROR, Severity.WARNING) for f in findings):
                    findings.append(
                        Finding(
                            check_name=self.name,
                            severity=Severity.INFO,
                            message="File tracking integrity validated",
                            details={
                                "tracked_files": total,
                                "sampled": len(rows),
                            },
                        )
                    )

        except Exception as exc:
            findings.append(
                Finding(
                    check_name=self.name,
                    severity=Severity.WARNING,
                    message=f"Could not check file tracking: {exc}",
                    details={"error": str(exc)},
                )
            )

        return findings
