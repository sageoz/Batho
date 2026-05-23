"""Snapshot chain integrity check."""

from __future__ import annotations

import time

from . import CheckResult, CheckStatus, Finding, IntegrityCheck, Severity


class SnapshotIntegrityCheck(IntegrityCheck):
    """Check snapshot chain integrity and consistency."""

    name = "snapshots"
    description = "Validate snapshot chain continuity, checksums, and parent references"

    def supports_quick_mode(self) -> bool:
        return True

    def run(self, ctx: "FixContext") -> CheckResult:
        """Execute snapshot integrity checks."""
        from ..engine import FixContext

        start_time = time.time()
        findings = []

        snapshots = ctx.get_snapshots()

        if not snapshots:
            findings.append(
                Finding(
                    check_name=self.name,
                    severity=Severity.INFO,
                    message="No snapshots found in database",
                    details={},
                )
            )
            duration_ms = int((time.time() - start_time) * 1000)
            return CheckResult(
                check_name=self.name,
                status=CheckStatus.PASSED,
                duration_ms=duration_ms,
                findings=findings,
                metrics={"snapshots_checked": 0},
            )

        # Check 1: Parent chain integrity
        chain_findings = self._check_chain_integrity(ctx, snapshots)
        findings.extend(chain_findings)

        # Check 2: Checksum validation
        checksum_findings = self._check_checksums(ctx, snapshots)
        findings.extend(checksum_findings)

        # Check 3: Duplicate snapshot IDs
        dup_findings = self._check_duplicates(ctx, snapshots)
        findings.extend(dup_findings)

        # Check 4: Patch operations integrity (deep mode)
        if ctx.deep_mode:
            patch_findings = self._check_patch_operations(ctx)
            findings.extend(patch_findings)

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
                "snapshots_checked": len(snapshots),
                "errors_found": error_count,
                "auto_fixed": fixed_count,
            },
        )

    def _check_chain_integrity(self, ctx: "FixContext", snapshots: list) -> list[Finding]:
        """Check snapshot parent chain is unbroken."""
        findings = []

        # Build snapshot lookup
        snapshot_ids = {s["snapshot_id"] for s in snapshots}

        # Check for orphaned snapshots (parent_id points to non-existent)
        orphaned = []
        circular = []

        for snapshot in snapshots:
            parent_id = snapshot.get("parent_id")
            if parent_id and parent_id not in snapshot_ids:
                orphaned.append(snapshot["snapshot_id"])

        # Check for circular references (deep mode)
        if ctx.deep_mode:
            for snapshot in snapshots:
                visited = set()
                current = snapshot["snapshot_id"]

                while current:
                    if current in visited:
                        circular.append(snapshot["snapshot_id"])
                        break
                    visited.add(current)

                    # Find parent
                    parent = None
                    for s in snapshots:
                        if s["snapshot_id"] == current:
                            parent = s.get("parent_id")
                            break
                    current = parent

        if orphaned:
            findings.append(
                Finding(
                    check_name=self.name,
                    severity=Severity.WARNING,
                    message=f"Found {len(orphaned)} orphaned snapshots (broken parent chain)",
                    details={
                        "orphaned_count": len(orphaned),
                        "sample_ids": orphaned[:5],
                    },
                )
            )

            # Clear broken parent references
            if not ctx.dry_run:
                try:
                    with ctx.db.connection() as conn:
                        for sid in orphaned:
                            conn.execute(
                                "UPDATE snapshots SET parent_id = NULL WHERE snapshot_id = ?",
                                (sid,),
                            )
                        conn.commit()

                    findings[-1].auto_fixed = True
                    findings[-1].fix_attempted = True
                    findings[-1].message += " (broken parent references cleared)"
                except Exception as fix_exc:
                    findings[-1].fix_attempted = True
                    findings[-1].fix_error = str(fix_exc)

        if circular:
            findings.append(
                Finding(
                    check_name=self.name,
                    severity=Severity.ERROR,
                    message=f"Found {len(circular)} circular snapshot references",
                    details={"circular_count": len(circular), "sample_ids": circular[:5]},
                )
            )

        if not orphaned and not circular:
            findings.append(
                Finding(
                    check_name=self.name,
                    severity=Severity.INFO,
                    message="Snapshot chain integrity validated",
                    details={"snapshots_checked": len(snapshots)},
                )
            )

        return findings

    def _check_checksums(self, ctx: "FixContext", snapshots: list) -> list[Finding]:
        """Validate snapshot checksums."""
        findings = []

        import json

        mismatched = 0
        fixed = 0

        for snapshot in snapshots:
            stored_checksum = snapshot.get("checksum")
            if not stored_checksum:
                continue

            # Reconstruct data for checksum
            data = {
                "snapshot_id": snapshot.get("snapshot_id"),
                "parent_id": snapshot.get("parent_id"),
                "created_at": snapshot.get("created_at"),
                "label": snapshot.get("label"),
                "git_commit": snapshot.get("git_commit"),
                "git_branch": snapshot.get("git_branch"),
                "root_path": snapshot.get("root_path"),
                "schema_version": snapshot.get("schema_version"),
                "stats": json.loads(snapshot.get("stats_json", "{}")),
            }

            import hashlib

            computed = hashlib.sha256(
                json.dumps(data, sort_keys=True).encode("utf-8")
            ).hexdigest()

            if computed != stored_checksum:
                mismatched += 1

                if not ctx.dry_run:
                    try:
                        with ctx.db.connection() as conn:
                            conn.execute(
                                "UPDATE snapshots SET checksum = ? WHERE snapshot_id = ?",
                                (computed, snapshot["snapshot_id"]),
                            )
                            conn.commit()
                        fixed += 1
                    except Exception:
                        pass

        if mismatched > 0:
            findings.append(
                Finding(
                    check_name=self.name,
                    severity=Severity.ERROR if fixed < mismatched else Severity.WARNING,
                    message=f"Found {mismatched} snapshot checksum mismatches, {fixed} auto-fixed",
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
                    message="All snapshot checksums validated",
                    details={},
                )
            )

        return findings

    def _check_duplicates(self, ctx: "FixContext", snapshots: list) -> list[Finding]:
        """Check for duplicate snapshot IDs."""
        findings = []

        seen_ids = set()
        duplicates = []

        for snapshot in snapshots:
            sid = snapshot.get("snapshot_id")
            if sid in seen_ids:
                duplicates.append(sid)
            else:
                seen_ids.add(sid)

        if duplicates:
            findings.append(
                Finding(
                    check_name=self.name,
                    severity=Severity.ERROR,
                    message=f"Found {len(duplicates)} duplicate snapshot IDs",
                    details={
                        "duplicate_count": len(duplicates),
                        "sample_ids": duplicates[:5],
                    },
                )
            )
        else:
            findings.append(
                Finding(
                    check_name=self.name,
                    severity=Severity.INFO,
                    message="No duplicate snapshot IDs found",
                    details={},
                )
            )

        return findings

    def _check_patch_operations(self, ctx: "FixContext") -> list[Finding]:
        """Check patch operations link valid snapshots."""
        findings = []

        try:
            with ctx.db.connection(read_only=True) as conn:
                # Get all patch operations
                rows = conn.execute("SELECT * FROM patch_operations").fetchall()
                operations = [dict(row) for row in rows]

                if not operations:
                    findings.append(
                        Finding(
                            check_name=self.name,
                            severity=Severity.INFO,
                            message="No patch operations found",
                            details={},
                        )
                    )
                    return findings

                # Get valid snapshot IDs
                snapshot_ids = {s["snapshot_id"] for s in ctx.get_snapshots()}

                invalid_ops = []

                for op in operations:
                    base_id = op.get("base_snapshot_id")
                    new_id = op.get("new_snapshot_id")

                    if base_id and base_id not in snapshot_ids:
                        invalid_ops.append(op["operation_id"])
                    if new_id and new_id not in snapshot_ids:
                        invalid_ops.append(op["operation_id"])

                if invalid_ops:
                    findings.append(
                        Finding(
                            check_name=self.name,
                            severity=Severity.WARNING,
                            message=f"Found {len(invalid_ops)} patch operations with invalid snapshot references",
                            details={
                                "invalid_count": len(invalid_ops),
                                "sample_ids": invalid_ops[:5],
                            },
                        )
                    )
                else:
                    findings.append(
                        Finding(
                            check_name=self.name,
                            severity=Severity.INFO,
                            message="All patch operations have valid snapshot references",
                            details={"operations_checked": len(operations)},
                        )
                    )

        except Exception as exc:
            findings.append(
                Finding(
                    check_name=self.name,
                    severity=Severity.WARNING,
                    message=f"Could not check patch operations: {exc}",
                    details={"error": str(exc)},
                )
            )

        return findings
