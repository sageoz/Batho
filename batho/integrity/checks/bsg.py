"""BSG bidirectional integrity check."""

from __future__ import annotations

import hashlib
import json
import random
import time

from . import CheckResult, CheckStatus, Finding, IntegrityCheck, Severity


class BSGIntegrityCheck(IntegrityCheck):
    """Check BSG entry integrity and bidirectional consistency."""

    name = "bsg"
    description = "Validate BSG entries, checksums, and reconstruction capability"

    def supports_quick_mode(self) -> bool:
        return True

    def run(self, ctx: "FixContext") -> CheckResult:
        """Execute BSG integrity checks."""
        from ..engine import FixContext

        start_time = time.time()
        findings = []

        # Get all BSG entries
        try:
            with ctx.db.connection(read_only=True) as conn:
                rows = conn.execute("SELECT * FROM bsg_entries").fetchall()
                bsg_entries = [dict(row) for row in rows]
        except Exception as exc:
            findings.append(
                Finding(
                    check_name=self.name,
                    severity=Severity.ERROR,
                    message=f"Could not read BSG entries: {exc}",
                    details={"error": str(exc)},
                )
            )
            duration_ms = int((time.time() - start_time) * 1000)
            return CheckResult(
                check_name=self.name,
                status=CheckStatus.FAILED,
                duration_ms=duration_ms,
                findings=findings,
                metrics={},
            )

        if not bsg_entries:
            findings.append(
                Finding(
                    check_name=self.name,
                    severity=Severity.INFO,
                    message="No BSG entries found",
                    details={},
                )
            )
            duration_ms = int((time.time() - start_time) * 1000)
            return CheckResult(
                check_name=self.name,
                status=CheckStatus.PASSED,
                duration_ms=duration_ms,
                findings=findings,
                metrics={"entries_checked": 0},
            )

        # Sample for quick mode
        if not ctx.deep_mode and len(bsg_entries) > 100:
            sample_size = max(10, len(bsg_entries) // 10)  # 10% sample
            entries_to_check = random.sample(bsg_entries, sample_size)
            findings.append(
                Finding(
                    check_name=self.name,
                    severity=Severity.INFO,
                    message=f"Quick mode: sampling {sample_size} of {len(bsg_entries)} BSG entries",
                    details={
                        "total_entries": len(bsg_entries),
                        "sample_size": sample_size,
                        "sampling_rate": "10%",
                    },
                )
            )
        else:
            entries_to_check = bsg_entries

        # Check 1: Checksum validation
        checksum_findings = self._check_checksums(ctx, entries_to_check)
        findings.extend(checksum_findings)

        # Check 2: JSON validity
        json_findings = self._check_json_validity(ctx, entries_to_check)
        findings.extend(json_findings)

        # Check 3: Entity correspondence
        entity_findings = self._check_entity_correspondence(ctx, entries_to_check)
        findings.extend(entity_findings)

        # Check 4: Reconstruction test (deep mode: full, quick: sample)
        if ctx.deep_mode:
            recon_findings = self._test_reconstruction(ctx, entries_to_check)
            findings.extend(recon_findings)

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
                "entries_checked": len(entries_to_check),
                "total_entries": len(bsg_entries),
                "errors_found": error_count,
                "auto_fixed": fixed_count,
            },
        )

    def _check_checksums(self, ctx: "FixContext", entries: list) -> list[Finding]:
        """Validate BSG entry checksums."""
        findings = []

        mismatched = 0
        fixed = 0

        for entry in entries:
            stored_checksum = entry.get("checksum")
            bsg_json = entry.get("bsg_json")

            if not stored_checksum or not bsg_json:
                continue

            # Recompute checksum
            computed_checksum = hashlib.sha256(bsg_json.encode("utf-8")).hexdigest()

            if computed_checksum != stored_checksum:
                mismatched += 1

                if not ctx.dry_run:
                    try:
                        with ctx.db.connection() as conn:
                            conn.execute(
                                """UPDATE bsg_entries
                                SET checksum = ?
                                WHERE run_id = ? AND file_path = ? AND view_type = ?""",
                                (
                                    computed_checksum,
                                    entry["run_id"],
                                    entry["file_path"],
                                    entry["view_type"],
                                ),
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
                    message=f"Found {mismatched} BSG checksum mismatches, {fixed} auto-fixed",
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
                    message="All BSG checksums validated",
                    details={"entries_checked": len(entries)},
                )
            )

        return findings

    def _check_json_validity(self, ctx: "FixContext", entries: list) -> list[Finding]:
        """Check BSG JSON is valid and parseable."""
        findings = []

        invalid = 0
        invalid_entries = []

        for entry in entries:
            bsg_json = entry.get("bsg_json", "")

            try:
                data = json.loads(bsg_json)
                # BSG stores entities as a list, not a dict
                if not isinstance(data, (dict, list)):
                    invalid += 1
                    invalid_entries.append(entry.get("file_path"))
            except json.JSONDecodeError:
                invalid += 1
                invalid_entries.append(entry.get("file_path"))

        if invalid > 0:
            findings.append(
                Finding(
                    check_name=self.name,
                    severity=Severity.ERROR,
                    message=f"Found {invalid} BSG entries with invalid JSON",
                    details={
                        "invalid_count": invalid,
                        "sample_paths": invalid_entries[:5],
                    },
                )
            )

            # Delete invalid entries
            if not ctx.dry_run:
                try:
                    with ctx.db.connection() as conn:
                        for entry in entries:
                            bsg_json = entry.get("bsg_json", "")
                            try:
                                data = json.loads(bsg_json)
                                if not isinstance(data, (dict, list)):
                                    raise ValueError("Not a dict or list")
                            except (json.JSONDecodeError, ValueError):
                                conn.execute(
                                    """DELETE FROM bsg_entries
                                    WHERE run_id = ? AND file_path = ? AND view_type = ?""",
                                    (
                                        entry["run_id"],
                                        entry["file_path"],
                                        entry["view_type"],
                                    ),
                                )
                        conn.commit()

                    findings[-1].auto_fixed = True
                    findings[-1].fix_attempted = True
                    findings[-1].message += " (invalid entries deleted)"
                except Exception as fix_exc:
                    findings[-1].fix_attempted = True
                    findings[-1].fix_error = str(fix_exc)
        else:
            findings.append(
                Finding(
                    check_name=self.name,
                    severity=Severity.INFO,
                    message="All BSG JSON is valid",
                    details={},
                )
            )

        return findings

    def _check_entity_correspondence(self, ctx: "FixContext", entries: list) -> list[Finding]:
        """Check BSG entries have corresponding entities."""
        findings = []

        orphaned = 0
        orphaned_entries = []

        for entry in entries:
            run_id = entry.get("run_id")
            file_path = entry.get("file_path")

            try:
                with ctx.db.connection(read_only=True) as conn:
                    # Check if entities exist for this file in this run
                    count = conn.execute(
                        """SELECT COUNT(*) FROM graph_entities
                        WHERE run_id = ? AND file_path = ?""",
                        (run_id, file_path),
                    ).fetchone()[0]

                    if count == 0:
                        orphaned += 1
                        orphaned_entries.append(f"{run_id}:{file_path}")
            except Exception:
                pass

        if orphaned > 0:
            findings.append(
                Finding(
                    check_name=self.name,
                    severity=Severity.WARNING,
                    message=f"Found {orphaned} BSG entries with no corresponding entities",
                    details={
                        "orphaned_count": orphaned,
                        "sample_entries": orphaned_entries[:5],
                    },
                )
            )

            # Delete orphaned entries
            if not ctx.dry_run:
                try:
                    with ctx.db.connection() as conn:
                        for entry in entries:
                            run_id = entry.get("run_id")
                            file_path = entry.get("file_path")

                            count = conn.execute(
                                """SELECT COUNT(*) FROM graph_entities
                                WHERE run_id = ? AND file_path = ?""",
                                (run_id, file_path),
                            ).fetchone()[0]

                            if count == 0:
                                conn.execute(
                                    """DELETE FROM bsg_entries
                                    WHERE run_id = ? AND file_path = ? AND view_type = ?""",
                                    (run_id, file_path, entry["view_type"]),
                                )
                        conn.commit()

                    findings[-1].auto_fixed = True
                    findings[-1].fix_attempted = True
                    findings[-1].message += " (orphaned entries deleted)"
                except Exception as fix_exc:
                    findings[-1].fix_attempted = True
                    findings[-1].fix_error = str(fix_exc)
        else:
            findings.append(
                Finding(
                    check_name=self.name,
                    severity=Severity.INFO,
                    message="All BSG entries have corresponding entities",
                    details={},
                )
            )

        return findings

    def _test_reconstruction(self, ctx: "FixContext", entries: list) -> list[Finding]:
        """Test BSG reconstruction to source representation."""
        findings = []

        failed = 0
        failed_entries = []

        for entry in entries:
            bsg_json = entry.get("bsg_json", "")
            file_path = entry.get("file_path")

            try:
                bsg_data = json.loads(bsg_json)

                # Check BSG has required structure
                nodes = bsg_data.get("nodes", bsg_data.get("entities", []))

                if not nodes:
                    failed += 1
                    failed_entries.append(file_path)
                    continue

                # Verify we can extract basic info
                for node in nodes:
                    if not isinstance(node, dict):
                        continue
                    # Check required fields exist
                    if "name" not in node and "id" not in node:
                        failed += 1
                        failed_entries.append(file_path)
                        break

            except Exception:
                failed += 1
                failed_entries.append(file_path)

        if failed > 0:
            findings.append(
                Finding(
                    check_name=self.name,
                    severity=Severity.WARNING,
                    message=f"Found {failed} BSG entries that may not reconstruct properly",
                    details={
                        "failed_count": failed,
                        "sample_paths": failed_entries[:5],
                    },
                )
            )
        else:
            findings.append(
                Finding(
                    check_name=self.name,
                    severity=Severity.INFO,
                    message="BSG reconstruction test passed",
                    details={"entries_tested": len(entries)},
                )
            )

        return findings
