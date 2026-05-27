"""SQLite Health Checker (Phase 1)."""

from __future__ import annotations

import time
from typing import Any
import sqlite3

from ..models import CheckReport, CheckStatus, Issue, Severity
from ..repairers.sqlite_repairer import SQLiteRepairer


class SQLiteHealthChecker:
    """Checker for database file health and SQLite settings."""

    def __init__(self, db: Any, dry_run: bool = False):
        self.db = db
        self.dry_run = dry_run
        self.repairer = SQLiteRepairer(db)

    def check_pragmas(self, conn: sqlite3.Connection) -> list[Issue]:
        """Verify key PRAGMA settings are correct."""
        issues = []
        # Check foreign keys
        fk = conn.execute("PRAGMA foreign_keys").fetchone()
        if not fk or fk[0] != 1:
            issues.append(
                Issue(
                    type="invalid_pragma_fk",
                    severity=Severity.ERROR,
                    table="db_meta",
                    identifier={},
                    description="PRAGMA foreign_keys is not enabled.",
                    repair_strategy="enable_foreign_keys",
                )
            )
        return issues

    def check_integrity(self, conn: sqlite3.Connection) -> list[Issue]:
        """Run PRAGMA integrity_check."""
        issues = []
        try:
            rows = conn.execute("PRAGMA integrity_check").fetchall()
            if not rows or rows[0][0].lower() != "ok":
                errors = [r[0] for r in rows]
                issues.append(
                    Issue(
                        type="database_corruption",
                        severity=Severity.CRITICAL,
                        table="sqlite_master",
                        identifier={},
                        description=f"PRAGMA integrity_check failed: {'; '.join(errors[:5])}",
                        repair_strategy="dump_and_restore",
                    )
                )
        except Exception as e:
            issues.append(
                Issue(
                    type="database_corruption",
                    severity=Severity.CRITICAL,
                    table="sqlite_master",
                    identifier={},
                    description=f"PRAGMA integrity_check query failed: {e}",
                    repair_strategy="dump_and_restore",
                )
            )
        return issues

    def check_foreign_keys(self, conn: sqlite3.Connection) -> list[Issue]:
        """Run PRAGMA foreign_key_check."""
        issues = []
        try:
            rows = conn.execute("PRAGMA foreign_key_check").fetchall()
            for row in rows:
                table, rowid, parent, fkid = row
                issues.append(
                    Issue(
                        type="foreign_key_violation",
                        severity=Severity.ERROR,
                        table=table,
                        identifier={"rowid": rowid},
                        description=f"Foreign key violation in table {table} (rowid {rowid}) referencing {parent}",
                        repair_strategy="rebuild_or_cleanup",
                    )
                )
        except Exception as e:
            issues.append(
                Issue(
                    type="foreign_key_check_failed",
                    severity=Severity.ERROR,
                    table="sqlite_master",
                    identifier={},
                    description=f"PRAGMA foreign_key_check query failed: {e}",
                )
            )
        return issues

    def check_schema_version(self, conn: sqlite3.Connection) -> list[Issue]:
        """Verify the database schema version."""
        from batho.storage.engine import SCHEMA_VERSION
        issues = []
        try:
            row = conn.execute("SELECT value FROM db_meta WHERE key = 'schema_version'").fetchone()
            if not row:
                issues.append(
                    Issue(
                        type="schema_mismatch",
                        severity=Severity.CRITICAL,
                        table="db_meta",
                        identifier={"key": "schema_version"},
                        description="Schema version missing from db_meta.",
                        repair_strategy="recommend_rebuild",
                    )
                )
            elif row[0] != SCHEMA_VERSION:
                issues.append(
                    Issue(
                        type="schema_mismatch",
                        severity=Severity.CRITICAL,
                        table="db_meta",
                        identifier={"key": "schema_version"},
                        description=f"Schema version mismatch. Found {row[0]}, expected {SCHEMA_VERSION}.",
                        repair_strategy="recommend_rebuild",
                    )
                )
        except sqlite3.OperationalError:
            issues.append(
                Issue(
                    type="schema_mismatch",
                    severity=Severity.CRITICAL,
                    table="db_meta",
                    identifier={},
                    description="db_meta table missing. Schema mismatch.",
                    repair_strategy="recommend_rebuild",
                )
            )
        return issues

    def run(self) -> CheckReport:
        """Run all Phase 1 checks and apply repairs if not dry_run."""
        start_time = time.time()
        issues = []

        try:
            with self.db.connection() as conn:
                issues.extend(self.check_schema_version(conn))
                issues.extend(self.check_pragmas(conn))
                issues.extend(self.check_integrity(conn))
                issues.extend(self.check_foreign_keys(conn))
        except Exception as e:
            issues.append(
                Issue(
                    type="db_connection_error",
                    severity=Severity.CRITICAL,
                    table="sqlite_master",
                    identifier={},
                    description=f"Failed to connect to database: {e}",
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
            phase="db",
            status=status,
            issues=issues,
            repairs=repairs,
            duration_ms=duration_ms,
            metrics={"issues_count": len(issues), "repairs_count": len(repairs)},
        )
