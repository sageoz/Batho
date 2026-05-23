"""Database-level integrity check for SQLite database."""

from __future__ import annotations

import time

from . import CheckResult, CheckStatus, Finding, IntegrityCheck, Severity


class DatabaseIntegrityCheck(IntegrityCheck):
    """Check SQLite database integrity, schema, and settings."""

    name = "database"
    description = "Validate SQLite database integrity, schema version, and pragmas"

    def supports_quick_mode(self) -> bool:
        return True

    def run(self, ctx: "FixContext") -> CheckResult:
        """Execute database integrity checks."""
        from ..engine import FixContext

        start_time = time.time()
        findings = []

        # Check 1: PRAGMA integrity_check
        integrity_result = self._check_integrity(ctx)
        findings.extend(integrity_result)

        # Check 2: Schema version
        schema_result = self._check_schema_version(ctx)
        findings.extend(schema_result)

        # Check 3: Foreign key constraints
        fk_result = self._check_foreign_keys(ctx)
        findings.extend(fk_result)

        # Check 4: Journal mode and pragmas (quick mode skips)
        if ctx.deep_mode:
            pragma_result = self._check_pragmas(ctx)
            findings.extend(pragma_result)

            # Check 5: Orphaned rows (deep mode only)
            orphaned_result = self._check_orphaned_rows(ctx)
            findings.extend(orphaned_result)

        # Determine status
        critical_count = sum(1 for f in findings if f.severity == Severity.CRITICAL)
        error_count = sum(1 for f in findings if f.severity == Severity.ERROR)

        if critical_count > 0:
            status = CheckStatus.FAILED
        elif error_count > 0:
            # Check if errors were auto-fixed
            fixed_count = sum(1 for f in findings if f.auto_fixed)
            if fixed_count == error_count:
                status = CheckStatus.FIXED
            else:
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
                "integrity_check": "passed" if not any(f.severity == Severity.CRITICAL for f in findings) else "failed",
                "checks_run": 5 if ctx.deep_mode else 3,
            },
        )

    def _check_integrity(self, ctx: "FixContext") -> list[Finding]:
        """Run PRAGMA integrity_check."""
        findings = []

        try:
            with ctx.db.connection(read_only=True) as conn:
                result = conn.execute("PRAGMA integrity_check").fetchone()
                integrity_status = result[0] if result else "unknown"

                if integrity_status != "ok":
                    findings.append(
                        Finding(
                            check_name=self.name,
                            severity=Severity.CRITICAL,
                            message=f"SQLite integrity check failed: {integrity_status}",
                            details={"integrity_status": integrity_status},
                            auto_fixed=False,
                        )
                    )
                else:
                    findings.append(
                        Finding(
                            check_name=self.name,
                            severity=Severity.INFO,
                            message="SQLite integrity check passed",
                            details={"integrity_status": "ok"},
                        )
                    )
        except Exception as exc:
            findings.append(
                Finding(
                    check_name=self.name,
                    severity=Severity.CRITICAL,
                    message=f"Could not run integrity check: {exc}",
                    details={"error": str(exc)},
                )
            )

        return findings

    def _check_schema_version(self, ctx: "FixContext") -> list[Finding]:
        """Check database schema version matches expected."""
        from batho.storage.engine import SCHEMA_VERSION

        findings = []

        try:
            with ctx.db.connection(read_only=True) as conn:
                row = conn.execute(
                    "SELECT value FROM db_meta WHERE key = 'schema_version'"
                ).fetchone()

                if row:
                    actual_version = row[0]
                    if actual_version != SCHEMA_VERSION:
                        findings.append(
                            Finding(
                                check_name=self.name,
                                severity=Severity.ERROR,
                                message=f"Schema version mismatch: expected {SCHEMA_VERSION}, got {actual_version}",
                                details={
                                    "expected": SCHEMA_VERSION,
                                    "actual": actual_version,
                                },
                            )
                        )
                    else:
                        findings.append(
                            Finding(
                                check_name=self.name,
                                severity=Severity.INFO,
                                message=f"Schema version matches: {actual_version}",
                                details={"version": actual_version},
                            )
                        )
                else:
                    findings.append(
                        Finding(
                            check_name=self.name,
                            severity=Severity.WARNING,
                            message="No schema version found in db_meta",
                            details={},
                        )
                    )
        except Exception as exc:
            findings.append(
                Finding(
                    check_name=self.name,
                    severity=Severity.ERROR,
                    message=f"Could not check schema version: {exc}",
                    details={"error": str(exc)},
                )
            )

        return findings

    def _check_foreign_keys(self, ctx: "FixContext") -> list[Finding]:
        """Check foreign key constraints."""
        findings = []

        try:
            with ctx.db.connection(read_only=True) as conn:
                result = conn.execute("PRAGMA foreign_key_check").fetchall()

                if result:
                    # Foreign key violations found
                    violations = [dict(row) for row in result]
                    findings.append(
                        Finding(
                            check_name=self.name,
                            severity=Severity.ERROR,
                            message=f"Found {len(violations)} foreign key violations",
                            details={"violations": violations},
                        )
                    )

                    # Attempt repair if not dry run
                    if not ctx.dry_run:
                        try:
                            with ctx.db.connection() as repair_conn:
                                for violation in violations:
                                    table = violation.get("table")
                                    rowid = violation.get("rowid")
                                    if table and rowid:
                                        # Delete orphaned row
                                        repair_conn.execute(
                                            f"DELETE FROM {table} WHERE rowid = ?",
                                            (rowid,),
                                        )
                                repair_conn.commit()

                            findings[-1].auto_fixed = True
                            findings[-1].fix_attempted = True
                            findings[-1].message += " (auto-fixed by deleting orphaned rows)"
                        except Exception as fix_exc:
                            findings[-1].fix_attempted = True
                            findings[-1].fix_error = str(fix_exc)
                else:
                    findings.append(
                        Finding(
                            check_name=self.name,
                            severity=Severity.INFO,
                            message="Foreign key constraints validated",
                            details={"violations": 0},
                        )
                    )
        except Exception as exc:
            findings.append(
                Finding(
                    check_name=self.name,
                    severity=Severity.WARNING,
                    message=f"Could not check foreign keys: {exc}",
                    details={"error": str(exc)},
                )
            )

        return findings

    def _check_pragmas(self, ctx: "FixContext") -> list[Finding]:
        """Check database pragma settings."""
        from batho.storage.engine import DEFAULT_PAGE_SIZE

        findings = []

        try:
            with ctx.db.connection(read_only=True) as conn:
                pragmas_to_check = [
                    ("journal_mode", "wal"),
                    ("foreign_keys", "1"),
                    ("page_size", str(DEFAULT_PAGE_SIZE)),
                ]

                for pragma_name, expected_value in pragmas_to_check:
                    result = conn.execute(f"PRAGMA {pragma_name}").fetchone()
                    actual_value = result[0] if result else None

                    if actual_value != expected_value:
                        findings.append(
                            Finding(
                                check_name=self.name,
                                severity=Severity.WARNING,
                                message=f"PRAGMA {pragma_name} is {actual_value}, expected {expected_value}",
                                details={
                                    "pragma": pragma_name,
                                    "expected": expected_value,
                                    "actual": actual_value,
                                },
                            )
                        )
                    else:
                        findings.append(
                            Finding(
                                check_name=self.name,
                                severity=Severity.INFO,
                                message=f"PRAGMA {pragma_name} = {actual_value}",
                                details={"pragma": pragma_name, "value": actual_value},
                            )
                        )
        except Exception as exc:
            findings.append(
                Finding(
                    check_name=self.name,
                    severity=Severity.WARNING,
                    message=f"Could not check pragmas: {exc}",
                    details={"error": str(exc)},
                )
            )

        return findings

    def _check_orphaned_rows(self, ctx: "FixContext") -> list[Finding]:
        """Check for orphaned rows in deep mode."""
        findings = []

        orphaned_checks = [
            # (table, column, parent_table, parent_column)
            (
                "graph_entities",
                "run_id",
                "index_runs",
                "run_id",
            ),
            (
                "graph_relationships",
                "run_id",
                "index_runs",
                "run_id",
            ),
            (
                "bsg_entries",
                "run_id",
                "index_runs",
                "run_id",
            ),
            ("context_outputs", "run_id", "index_runs", "run_id"),
            ("snapshots", "parent_id", "snapshots", "snapshot_id"),
        ]

        for table, column, parent_table, parent_column in orphaned_checks:
            try:
                with ctx.db.connection(read_only=True) as conn:
                    # Find orphaned rows
                    orphaned = conn.execute(
                        f"""SELECT {table}.{column} FROM {table}
                        LEFT JOIN {parent_table} ON {table}.{column} = {parent_table}.{parent_column}
                        WHERE {parent_table}.{parent_column} IS NULL AND {table}.{column} IS NOT NULL"""
                    ).fetchall()

                    if orphaned:
                        findings.append(
                            Finding(
                                check_name=self.name,
                                severity=Severity.WARNING,
                                message=f"Found {len(orphaned)} orphaned rows in {table}.{column}",
                                details={
                                    "table": table,
                                    "column": column,
                                    "orphaned_count": len(orphaned),
                                    "sample_orphans": [row[0] for row in orphaned[:5]],
                                },
                            )
                        )
            except Exception as exc:
                findings.append(
                    Finding(
                        check_name=self.name,
                        severity=Severity.WARNING,
                        message=f"Could not check orphaned rows in {table}: {exc}",
                        details={"table": table, "error": str(exc)},
                    )
                )

        return findings
