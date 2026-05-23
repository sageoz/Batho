"""Index run and entity/relationship integrity check."""

from __future__ import annotations

import time

from . import CheckResult, CheckStatus, Finding, IntegrityCheck, Severity


class IndexIntegrityCheck(IntegrityCheck):
    """Check index runs, entities, and relationships."""

    name = "index"
    description = "Validate index runs, entity consistency, and relationship integrity"

    def supports_quick_mode(self) -> bool:
        return True

    def run(self, ctx: "FixContext") -> CheckResult:
        """Execute index integrity checks."""
        from ..engine import FixContext

        start_time = time.time()
        findings = []

        runs = ctx.get_index_runs()
        if not runs:
            findings.append(
                Finding(
                    check_name=self.name,
                    severity=Severity.WARNING,
                    message="No index runs found in database",
                    details={},
                )
            )
            duration_ms = int((time.time() - start_time) * 1000)
            return CheckResult(
                check_name=self.name,
                status=CheckStatus.PASSED,
                duration_ms=duration_ms,
                findings=findings,
                metrics={"runs_checked": 0},
            )

        # Check 1: Run status and metadata
        run_findings = self._check_runs(ctx, runs)
        findings.extend(run_findings)

        # Check 2: Entity integrity
        entity_findings = self._check_entities(ctx, runs)
        findings.extend(entity_findings)

        # Check 3: Relationship integrity
        rel_findings = self._check_relationships(ctx, runs)
        findings.extend(rel_findings)

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
                "runs_checked": len(runs),
                "errors_found": error_count,
                "auto_fixed": fixed_count,
            },
        )

    def _check_runs(self, ctx: "FixContext", runs: list) -> list[Finding]:
        """Check index run metadata."""
        findings = []

        # Check for runs stuck in 'running' status (likely crashed)
        stuck_runs = [r for r in runs if r.get("status") == "running"]
        if stuck_runs:
            stuck_count = len(stuck_runs)
            findings.append(
                Finding(
                    check_name=self.name,
                    severity=Severity.WARNING,
                    message=f"Found {stuck_count} runs stuck in 'running' status",
                    details={
                        "stuck_count": stuck_count,
                        "run_ids": [r["run_id"] for r in stuck_runs[:5]],
                    },
                )
            )

            # Auto-fix: mark as failed
            if not ctx.dry_run:
                try:
                    with ctx.db.connection() as conn:
                        for run in stuck_runs:
                            conn.execute(
                                """UPDATE index_runs
                                SET status = 'failed', error_message = 'Marked failed by fix command'
                                WHERE run_id = ?""",
                                (run["run_id"],),
                            )
                        conn.commit()

                    findings[-1].auto_fixed = True
                    findings[-1].fix_attempted = True
                    findings[-1].message += " (marked as failed)"
                except Exception as fix_exc:
                    findings[-1].fix_attempted = True
                    findings[-1].fix_error = str(fix_exc)

        # Check for failed runs
        failed_runs = [r for r in runs if r.get("status") == "failed"]
        if failed_runs:
            findings.append(
                Finding(
                    check_name=self.name,
                    severity=Severity.INFO,
                    message=f"Found {len(failed_runs)} failed runs (may need cleanup)",
                    details={
                        "failed_count": len(failed_runs),
                        "run_ids": [r["run_id"] for r in failed_runs[:5]],
                    },
                )
            )

        # Check entity counts match
        for run in runs:
            if run.get("status") != "completed":
                continue

            run_id = run["run_id"]
            reported_entity_count = run.get("entity_count", 0)
            reported_rel_count = run.get("rel_count", 0)

            try:
                with ctx.db.connection(read_only=True) as conn:
                    actual_entity_count = conn.execute(
                        "SELECT COUNT(*) FROM graph_entities WHERE run_id = ?",
                        (run_id,),
                    ).fetchone()[0]

                    actual_rel_count = conn.execute(
                        "SELECT COUNT(*) FROM graph_relationships WHERE run_id = ?",
                        (run_id,),
                    ).fetchone()[0]

                    if actual_entity_count != reported_entity_count:
                        findings.append(
                            Finding(
                                check_name=self.name,
                                severity=Severity.WARNING,
                                message=f"Run {run_id}: entity count mismatch",
                                details={
                                    "run_id": run_id,
                                    "reported": reported_entity_count,
                                    "actual": actual_entity_count,
                                },
                            )
                        )

                    if actual_rel_count != reported_rel_count:
                        findings.append(
                            Finding(
                                check_name=self.name,
                                severity=Severity.WARNING,
                                message=f"Run {run_id}: relationship count mismatch",
                                details={
                                    "run_id": run_id,
                                    "reported": reported_rel_count,
                                    "actual": actual_rel_count,
                                },
                            )
                        )
            except Exception as exc:
                findings.append(
                    Finding(
                        check_name=self.name,
                        severity=Severity.WARNING,
                        message=f"Could not verify counts for run {run_id}: {exc}",
                        details={"run_id": run_id, "error": str(exc)},
                    )
                )

        if not any(f.severity in (Severity.ERROR, Severity.CRITICAL) for f in findings):
            findings.append(
                Finding(
                    check_name=self.name,
                    severity=Severity.INFO,
                    message="Index run metadata validated",
                    details={"runs_checked": len(runs)},
                )
            )

        return findings

    def _check_entities(self, ctx: "FixContext", runs: list) -> list[Finding]:
        """Check entity consistency."""
        findings = []

        # Check latest run in quick mode, all runs in deep mode
        runs_to_check = runs if ctx.deep_mode else runs[:1]

        for run in runs_to_check:
            run_id = run["run_id"]

            try:
                with ctx.db.connection(read_only=True) as conn:
                    # Check for entities with invalid line numbers
                    invalid_lines = conn.execute(
                        """SELECT COUNT(*) FROM graph_entities
                        WHERE run_id = ? AND start_line > end_line""",
                        (run_id,),
                    ).fetchone()[0]

                    if invalid_lines > 0:
                        findings.append(
                            Finding(
                                check_name=self.name,
                                severity=Severity.ERROR,
                                message=f"Run {run_id}: {invalid_lines} entities have invalid line numbers",
                                details={"run_id": run_id, "invalid_count": invalid_lines},
                            )
                        )

                    # Check for circular parent references (deep mode only)
                    if ctx.deep_mode:
                        circular = self._detect_circular_parents(conn, run_id)
                        if circular:
                            findings.append(
                                Finding(
                                    check_name=self.name,
                                    severity=Severity.ERROR,
                                    message=f"Run {run_id}: {len(circular)} circular parent references detected",
                                    details={"run_id": run_id, "circular_count": len(circular)},
                                )
                            )

                    # Check entity ID uniqueness within run
                    dups = conn.execute(
                        """SELECT entity_id, COUNT(*) as cnt
                        FROM graph_entities
                        WHERE run_id = ?
                        GROUP BY entity_id
                        HAVING cnt > 1""",
                        (run_id,),
                    ).fetchall()

                    if dups:
                        findings.append(
                            Finding(
                                check_name=self.name,
                                severity=Severity.ERROR,
                                message=f"Run {run_id}: {len(dups)} duplicate entity IDs",
                                details={
                                    "run_id": run_id,
                                    "duplicate_count": len(dups),
                                    "sample_ids": [d[0] for d in dups[:5]],
                                },
                            )
                        )

            except Exception as exc:
                findings.append(
                    Finding(
                        check_name=self.name,
                        severity=Severity.WARNING,
                        message=f"Could not check entities for run {run_id}: {exc}",
                        details={"run_id": run_id, "error": str(exc)},
                    )
                )

        if not any(f.severity in (Severity.ERROR, Severity.CRITICAL) for f in findings):
            findings.append(
                Finding(
                    check_name=self.name,
                    severity=Severity.INFO,
                    message="Entity integrity validated",
                    details={"runs_checked": len(runs_to_check)},
                )
            )

        return findings

    def _check_relationships(self, ctx: "FixContext", runs: list) -> list[Finding]:
        """Check relationship consistency."""
        findings = []

        runs_to_check = runs if ctx.deep_mode else runs[:1]

        for run in runs_to_check:
            run_id = run["run_id"]

            try:
                with ctx.db.connection(read_only=True) as conn:
                    # Find dangling relationships (source doesn't exist)
                    dangling_source = conn.execute(
                        """SELECT COUNT(*) FROM graph_relationships r
                        WHERE r.run_id = ? AND r.source_id NOT IN
                        (SELECT entity_id FROM graph_entities WHERE run_id = ?)""",
                        (run_id, run_id),
                    ).fetchone()[0]

                    # Find dangling relationships (target doesn't exist)
                    dangling_target = conn.execute(
                        """SELECT COUNT(*) FROM graph_relationships r
                        WHERE r.run_id = ? AND r.target_id NOT IN
                        (SELECT entity_id FROM graph_entities WHERE run_id = ?)""",
                        (run_id, run_id),
                    ).fetchone()[0]

                    total_dangling = dangling_source + dangling_target

                    if total_dangling > 0:
                        findings.append(
                            Finding(
                                check_name=self.name,
                                severity=Severity.ERROR,
                                message=f"Run {run_id}: {total_dangling} dangling relationships",
                                details={
                                    "run_id": run_id,
                                    "dangling_source": dangling_source,
                                    "dangling_target": dangling_target,
                                },
                            )
                        )

                        # Auto-fix: delete dangling relationships
                        if not ctx.dry_run:
                            try:
                                conn.execute(
                                    """DELETE FROM graph_relationships
                                    WHERE run_id = ? AND source_id NOT IN
                                    (SELECT entity_id FROM graph_entities WHERE run_id = ?)""",
                                    (run_id, run_id),
                                )
                                conn.execute(
                                    """DELETE FROM graph_relationships
                                    WHERE run_id = ? AND target_id NOT IN
                                    (SELECT entity_id FROM graph_entities WHERE run_id = ?)""",
                                    (run_id, run_id),
                                )
                                conn.commit()

                                findings[-1].auto_fixed = True
                                findings[-1].fix_attempted = True
                                findings[-1].message += " (dangling relationships deleted)"
                            except Exception as fix_exc:
                                findings[-1].fix_attempted = True
                                findings[-1].fix_error = str(fix_exc)

            except Exception as exc:
                findings.append(
                    Finding(
                        check_name=self.name,
                        severity=Severity.WARNING,
                        message=f"Could not check relationships for run {run_id}: {exc}",
                        details={"run_id": run_id, "error": str(exc)},
                    )
                )

        if not any(f.severity in (Severity.ERROR, Severity.CRITICAL) for f in findings):
            findings.append(
                Finding(
                    check_name=self.name,
                    severity=Severity.INFO,
                    message="Relationship integrity validated",
                    details={"runs_checked": len(runs_to_check)},
                )
            )

        return findings

    def _detect_circular_parents(self, conn, run_id: str) -> list:
        """Detect circular parent_id references."""
        circular = []

        try:
            # Get all entities with parents
            rows = conn.execute(
                "SELECT entity_id, parent_id FROM graph_entities WHERE run_id = ? AND parent_id IS NOT NULL",
                (run_id,),
            ).fetchall()

            parent_map = {r["entity_id"]: r["parent_id"] for r in rows}

            for entity_id, parent_id in parent_map.items():
                visited = {entity_id}
                current = parent_id

                while current:
                    if current in visited:
                        circular.append({"entity_id": entity_id, "cycle": list(visited)})
                        break
                    visited.add(current)
                    current = parent_map.get(current)

        except Exception:
            pass

        return circular
