"""Artifact registry consistency check."""

from __future__ import annotations

import time
from pathlib import Path

from . import CheckResult, CheckStatus, Finding, IntegrityCheck, Severity
from batho.utils.hash import compute_file_hash


class RegistryIntegrityCheck(IntegrityCheck):
    """Check artifact registry consistency."""

    name = "registry"
    description = "Validate artifact registry entries, checksums, and index_id references"

    def supports_quick_mode(self) -> bool:
        return True

    def run(self, ctx: "FixContext") -> CheckResult:
        """Execute registry integrity checks."""
        from ..engine import FixContext

        start_time = time.time()
        findings = []

        # Get artifacts to check
        artifacts = ctx.get_artifacts()

        if not artifacts:
            findings.append(
                Finding(
                    check_name=self.name,
                    severity=Severity.INFO,
                    message="No artifacts found in registry",
                    details={},
                )
            )
            duration_ms = int((time.time() - start_time) * 1000)
            return CheckResult(
                check_name=self.name,
                status=CheckStatus.PASSED,
                duration_ms=duration_ms,
                findings=findings,
                metrics={"artifacts_checked": 0},
            )

        # Sample artifacts for quick mode
        if not ctx.deep_mode and len(artifacts) > 100:
            import random

            artifacts_to_check = random.sample(artifacts, 100)
            findings.append(
                Finding(
                    check_name=self.name,
                    severity=Severity.INFO,
                    message=f"Quick mode: sampling 100 of {len(artifacts)} artifacts",
                    details={"total_artifacts": len(artifacts), "sample_size": 100},
                )
            )
        else:
            artifacts_to_check = artifacts

        # Check 1: Index ID resolution
        index_findings = self._check_index_ids(ctx, artifacts_to_check)
        findings.extend(index_findings)

        # Check 2: Checksum validation
        checksum_findings = self._check_checksums(ctx, artifacts_to_check)
        findings.extend(checksum_findings)

        # Check 3: Logical path validation
        path_findings = self._check_logical_paths(ctx, artifacts_to_check)
        findings.extend(path_findings)

        # Check 4: Duplicate artifact IDs (deep mode only)
        if ctx.deep_mode:
            dup_findings = self._check_duplicates(ctx, artifacts)
            findings.extend(dup_findings)

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
                "artifacts_checked": len(artifacts_to_check),
                "total_artifacts": len(artifacts),
                "errors_found": error_count,
                "auto_fixed": fixed_count,
            },
        )

    def _check_index_ids(self, ctx: "FixContext", artifacts: list) -> list[Finding]:
        """Check that index_id references resolve to valid runs."""
        findings = []

        # Get valid run IDs
        valid_run_ids = {run["run_id"] for run in ctx.get_index_runs()}

        orphaned_count = 0
        orphaned_artifacts = []

        for artifact in artifacts:
            run_id = artifact.get("run_id")
            if run_id and run_id not in valid_run_ids:
                orphaned_count += 1
                orphaned_artifacts.append(artifact.get("artifact_id"))

        if orphaned_count > 0:
            findings.append(
                Finding(
                    check_name=self.name,
                    severity=Severity.ERROR,
                    message=f"Found {orphaned_count} artifacts with invalid run_id references",
                    details={
                        "orphaned_count": orphaned_count,
                        "sample_orphans": orphaned_artifacts[:5],
                    },
                )
            )

            # Attempt repair: mark orphaned artifacts for re-indexing
            if not ctx.dry_run:
                try:
                    with ctx.db.connection() as conn:
                        for artifact_id in orphaned_artifacts:
                            conn.execute(
                                """UPDATE artifacts
                                SET sync_status = 'failed', sync_error = 'orphaned run_id'
                                WHERE artifact_id = ?""",
                                (artifact_id,),
                            )
                        conn.commit()

                    findings[-1].auto_fixed = True
                    findings[-1].fix_attempted = True
                    findings[-1].message += " (marked for re-indexing)"
                except Exception as fix_exc:
                    findings[-1].fix_attempted = True
                    findings[-1].fix_error = str(fix_exc)
        else:
            findings.append(
                Finding(
                    check_name=self.name,
                    severity=Severity.INFO,
                    message="All artifact run_id references are valid",
                    details={"artifacts_checked": len(artifacts)},
                )
            )

        return findings

    def _check_checksums(self, ctx: "FixContext", artifacts: list) -> list[Finding]:
        """Validate artifact checksums against actual files."""
        findings = []

        mismatched = 0
        fixed = 0
        missing_files = 0

        for artifact in artifacts:
            logical_path = artifact.get("logical_path")
            stored_checksum = artifact.get("checksum")

            if not logical_path or not stored_checksum:
                continue

            full_path = ctx.root / logical_path

            if not full_path.exists():
                missing_files += 1
                continue

            try:
                actual_checksum = compute_file_hash(full_path)

                if actual_checksum != stored_checksum:
                    mismatched += 1

                    if not ctx.dry_run:
                        try:
                            with ctx.db.connection() as conn:
                                conn.execute(
                                    """UPDATE artifacts
                                    SET checksum = ?, updated_at = datetime('now')
                                    WHERE artifact_id = ?""",
                                    (actual_checksum, artifact.get("artifact_id")),
                                )
                                conn.commit()
                            fixed += 1
                        except Exception:
                            pass

            except Exception:
                # Skip files we can't hash
                pass

        if mismatched > 0:
            findings.append(
                Finding(
                    check_name=self.name,
                    severity=Severity.ERROR if fixed < mismatched else Severity.WARNING,
                    message=f"Found {mismatched} checksum mismatches, {fixed} auto-fixed",
                    details={
                        "mismatched": mismatched,
                        "fixed": fixed,
                        "unfixed": mismatched - fixed,
                    },
                    auto_fixed=fixed == mismatched,
                    fix_attempted=not ctx.dry_run,
                    fix_error=None if fixed == mismatched else f"{mismatched - fixed} could not be fixed",
                )
            )
        else:
            findings.append(
                Finding(
                    check_name=self.name,
                    severity=Severity.INFO,
                    message="All artifact checksums validated",
                    details={"artifacts_checked": len(artifacts), "missing_files": missing_files},
                )
            )

        return findings

    def _check_logical_paths(self, ctx: "FixContext", artifacts: list) -> list[Finding]:
        """Check that logical paths are within repo boundaries."""
        findings = []

        invalid_paths = []

        for artifact in artifacts:
            logical_path = artifact.get("logical_path", "")

            # Check for path traversal
            if logical_path.startswith("..") or "/../" in logical_path:
                invalid_paths.append(artifact.get("artifact_id"))

            # Check if path is outside root
            full_path = ctx.root / logical_path
            try:
                full_path.resolve().relative_to(ctx.root.resolve())
            except ValueError:
                invalid_paths.append(artifact.get("artifact_id"))

        if invalid_paths:
            findings.append(
                Finding(
                    check_name=self.name,
                    severity=Severity.ERROR,
                    message=f"Found {len(invalid_paths)} artifacts with invalid logical paths",
                    details={"invalid_count": len(invalid_paths), "sample_ids": invalid_paths[:5]},
                )
            )
        else:
            findings.append(
                Finding(
                    check_name=self.name,
                    severity=Severity.INFO,
                    message="All artifact logical paths are valid",
                    details={},
                )
            )

        return findings

    def _check_duplicates(self, ctx: "FixContext", artifacts: list) -> list[Finding]:
        """Check for duplicate artifact IDs."""
        findings = []

        seen_ids = set()
        duplicates = []

        for artifact in artifacts:
            aid = artifact.get("artifact_id")
            if aid in seen_ids:
                duplicates.append(aid)
            else:
                seen_ids.add(aid)

        if duplicates:
            findings.append(
                Finding(
                    check_name=self.name,
                    severity=Severity.ERROR,
                    message=f"Found {len(duplicates)} duplicate artifact IDs",
                    details={"duplicate_count": len(duplicates), "sample_ids": duplicates[:5]},
                )
            )
        else:
            findings.append(
                Finding(
                    check_name=self.name,
                    severity=Severity.INFO,
                    message="No duplicate artifact IDs found",
                    details={},
                )
            )

        return findings
