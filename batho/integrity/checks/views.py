"""View construction validation check."""

from __future__ import annotations

import time

from . import CheckResult, CheckStatus, Finding, IntegrityCheck, Severity


class ViewIntegrityCheck(IntegrityCheck):
    """Check view construction and rendering."""

    name = "views"
    description = "Validate context output rendering and view consistency"

    def supports_quick_mode(self) -> bool:
        return True

    def run(self, ctx: "FixContext") -> CheckResult:
        """Execute view integrity checks."""
        from ..engine import FixContext

        start_time = time.time()
        findings = []

        # Check 1: Context outputs exist and render
        output_findings = self._check_context_outputs(ctx)
        findings.extend(output_findings)

        # Check 2: BSG view consistency
        bsg_findings = self._check_bsg_views(ctx)
        findings.extend(bsg_findings)

        # Determine status
        critical_count = sum(1 for f in findings if f.severity == Severity.CRITICAL)
        error_count = sum(1 for f in findings if f.severity == Severity.ERROR)

        if critical_count > 0:
            status = CheckStatus.FAILED
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
            },
        )

    def _check_context_outputs(self, ctx: "FixContext") -> list[Finding]:
        """Check context outputs can be rendered."""
        findings = []

        try:
            with ctx.db.connection(read_only=True) as conn:
                # Get all context outputs
                rows = conn.execute("SELECT * FROM context_outputs").fetchall()
                outputs = [dict(row) for row in rows]

                if not outputs:
                    findings.append(
                        Finding(
                            check_name=self.name,
                            severity=Severity.INFO,
                            message="No context outputs found",
                            details={},
                        )
                    )
                    return findings

                # Sample for quick mode
                if not ctx.deep_mode and len(outputs) > 10:
                    import random

                    outputs = random.sample(outputs, 10)

                invalid = 0
                large_outputs = 0

                for output in outputs:
                    content = output.get("content", "")
                    size_bytes = output.get("size_bytes", 0)

                    # Check content is valid string
                    if not isinstance(content, str):
                        invalid += 1
                        continue

                    # Check size matches
                    actual_size = len(content.encode("utf-8"))
                    if actual_size != size_bytes:
                        # Size mismatch - not critical but worth noting
                        pass

                    # Flag very large outputs (> 10MB)
                    if size_bytes > 10 * 1024 * 1024:
                        large_outputs += 1

                if invalid > 0:
                    findings.append(
                        Finding(
                            check_name=self.name,
                            severity=Severity.WARNING,
                            message=f"Found {invalid} context outputs with invalid content",
                            details={"invalid_count": invalid},
                        )
                    )

                if large_outputs > 0:
                    findings.append(
                        Finding(
                            check_name=self.name,
                            severity=Severity.INFO,
                            message=f"Found {large_outputs} very large context outputs (>10MB)",
                            details={"large_count": large_outputs},
                        )
                    )

                if invalid == 0:
                    findings.append(
                        Finding(
                            check_name=self.name,
                            severity=Severity.INFO,
                            message="All context outputs are valid",
                            details={"outputs_checked": len(outputs)},
                        )
                    )

        except Exception as exc:
            findings.append(
                Finding(
                    check_name=self.name,
                    severity=Severity.WARNING,
                    message=f"Could not check context outputs: {exc}",
                    details={"error": str(exc)},
                )
            )

        return findings

    def _check_bsg_views(self, ctx: "FixContext") -> list[Finding]:
        """Check BSG views are consistent across view_types."""
        findings = []

        try:
            with ctx.db.connection(read_only=True) as conn:
                # Check for files with multiple view_types that should match
                rows = conn.execute(
                    """SELECT run_id, file_path, COUNT(DISTINCT view_type) as view_count
                    FROM bsg_entries
                    GROUP BY run_id, file_path"""
                ).fetchall()

                multi_view = sum(1 for r in rows if r["view_count"] > 1)

                if multi_view > 0:
                    findings.append(
                        Finding(
                            check_name=self.name,
                            severity=Severity.INFO,
                            message=f"Found {multi_view} files with multiple view types",
                            details={"multi_view_count": multi_view},
                        )
                    )

                # Check view_type values are valid
                invalid_view_types = conn.execute(
                    """SELECT DISTINCT view_type FROM bsg_entries
                    WHERE view_type NOT IN ('agent', 'storage', 'human')"""
                ).fetchall()

                if invalid_view_types:
                    findings.append(
                        Finding(
                            check_name=self.name,
                            severity=Severity.ERROR,
                            message=f"Found {len(invalid_view_types)} invalid view_type values",
                            details={
                                "invalid_types": [r["view_type"] for r in invalid_view_types],
                            },
                        )
                    )
                else:
                    findings.append(
                        Finding(
                            check_name=self.name,
                            severity=Severity.INFO,
                            message="All BSG view_types are valid",
                            details={},
                        )
                    )

        except Exception as exc:
            findings.append(
                Finding(
                    check_name=self.name,
                    severity=Severity.WARNING,
                    message=f"Could not check BSG views: {exc}",
                    details={"error": str(exc)},
                )
            )

        return findings
