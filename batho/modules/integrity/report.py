"""Report generation for batho fix command."""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .models import CheckReport, CheckStatus, Issue, RepairResult, Severity
from .engine import FixResult, FixSummary


@dataclass
class FixReport:
    """Complete report from batho fix execution."""

    started_at: str
    completed_at: str
    root: str
    bundle_dir: str
    mode: str
    summary: FixSummary
    check_results: list[CheckReport]
    repairs: list[RepairResult]
    findings_by_severity: dict[str, int] = field(default_factory=dict)

    def __post_init__(self):
        if not self.findings_by_severity:
            self.findings_by_severity = {
                "critical": self.summary.findings_critical,
                "error": self.summary.findings_error,
                "warning": self.summary.findings_warning,
                "info": self.summary.findings_info,
            }


class ReportGenerator:
    """Generate reports in multiple formats."""

    def __init__(self, format: str = "text"):
        self.format = format.lower()

    def generate(self, result: FixResult) -> str:
        """Generate report in specified format."""
        report = FixReport(
            started_at=result.started_at,
            completed_at=result.completed_at,
            root=result.root,
            bundle_dir=result.bundle_dir,
            mode=result.mode,
            summary=result.summary,
            check_results=result.check_results,
            repairs=result.repairs,
        )

        if self.format == "json":
            return self._generate_json(report)
        elif self.format == "csv":
            return self._generate_csv(report)
        else:
            return self._generate_text(report)

    def _generate_json(self, report: FixReport) -> str:
        """Generate JSON report."""
        data = {
            "started_at": report.started_at,
            "completed_at": report.completed_at,
            "root": report.root,
            "bundle_dir": report.bundle_dir,
            "mode": report.mode,
            "summary": {
                "checks_passed": report.summary.checks_passed,
                "checks_failed": report.summary.checks_failed,
                "checks_fixed": report.summary.checks_fixed,
                "checks_skipped": report.summary.checks_skipped,
                "findings": {
                    "critical": report.summary.findings_critical,
                    "error": report.summary.findings_error,
                    "warning": report.summary.findings_warning,
                    "info": report.summary.findings_info,
                },
                "repairs_attempted": report.summary.repairs_attempted,
                "repairs_successful": report.summary.repairs_successful,
                "duration_ms": report.summary.duration_ms,
                "exit_code": report.summary.exit_code,
            },
            "phases": [
                {
                    "phase": cr.phase,
                    "status": cr.status.value,
                    "duration_ms": cr.duration_ms,
                    "metrics": cr.metrics,
                    "issues": [
                        {
                            "type": issue.type,
                            "severity": issue.severity.value,
                            "table": issue.table,
                            "identifier": issue.identifier,
                            "description": issue.description,
                            "repair_strategy": issue.repair_strategy,
                        }
                        for issue in cr.issues
                    ],
                    "repairs": [
                        {
                            "type": rep.issue.type,
                            "success": rep.success,
                            "error": rep.error,
                            "rows_affected": rep.rows_affected,
                        }
                        for rep in cr.repairs
                    ],
                }
                for cr in report.check_results
            ],
        }
        return json.dumps(data, indent=2)

    def _generate_csv(self, report: FixReport) -> str:
        """Generate CSV report of findings."""
        output = io.StringIO()
        writer = csv.writer(output)

        # Header
        writer.writerow(
            ["timestamp", "check_name", "severity", "message", "auto_fixed", "details"]
        )

        # Findings / Issues
        for check_result in report.check_results:
            for issue in check_result.issues:
                if issue.severity != Severity.INFO:  # Skip info-level in CSV
                    repair_res = next((r for r in check_result.repairs if r.issue == issue), None)
                    auto_fixed = "yes" if (repair_res and repair_res.success) else "no"
                    details = {
                        "table": issue.table,
                        "identifier": issue.identifier,
                        "repair_strategy": issue.repair_strategy,
                    }
                    if repair_res and repair_res.error:
                        details["error"] = repair_res.error

                    writer.writerow(
                        [
                            report.completed_at,
                            issue.type,
                            issue.severity.value,
                            issue.description,
                            auto_fixed,
                            json.dumps(details),
                        ]
                    )

        return output.getvalue()

    def _generate_text(self, report: FixReport) -> str:
        """Generate human-readable text report."""
        lines = []

        # Header
        lines.append("🔍 Batho Fix Report")
        lines.append("━" * 50)
        lines.append(f"Database:    {report.bundle_dir}")
        lines.append(f"Mode:        {report.mode} {'(use --deep for full scan)' if report.mode == 'quick' else ''}")
        lines.append(f"Duration:    {self._format_duration(report.summary.duration_ms)}")
        lines.append("")

        # Summary
        lines.append(f"✅ Checks Passed:   {report.summary.checks_passed}/{report.summary.total_checks}")
        if report.summary.checks_fixed > 0:
            lines.append(f"🔧 Auto-Fixed:     {report.summary.checks_fixed} phases")
        if report.summary.checks_failed > 0:
            lines.append(f"❌ Checks Failed:   {report.summary.checks_failed}")
        if report.summary.total_findings > 0:
            lines.append(f"⚠️  Findings:       {report.summary.total_findings}")
        lines.append("")

        # Findings by severity
        if report.summary.total_findings > 0:
            lines.append("📊 Findings by Severity")
            lines.append("─" * 50)
            lines.append(f"  Critical: {report.summary.findings_critical}")
            lines.append(f"  Error:    {report.summary.findings_error}")
            lines.append(f"  Warning:  {report.summary.findings_warning}")
            lines.append(f"  Info:     {report.summary.findings_info}")
            lines.append("")

        # Repairs
        if report.summary.repairs_attempted > 0:
            lines.append("🔧 Repairs Made")
            lines.append("─" * 50)
            for check_result in report.check_results:
                for rep in check_result.repairs:
                    status = "✅" if rep.success else "⚠️"
                    err_msg = f" (Error: {rep.error})" if rep.error else ""
                    lines.append(f"  {status} [{check_result.phase}] Fixed {rep.issue.type}: {rep.issue.description}{err_msg}")
            lines.append("")

        # Failed/unfixed issues
        failed_issues = []
        for cr in report.check_results:
            for issue in cr.issues:
                if issue.severity in (Severity.CRITICAL, Severity.ERROR):
                    repair_res = next((r for r in cr.repairs if r.issue == issue), None)
                    if not repair_res or not repair_res.success:
                        failed_issues.append((cr.phase, issue, repair_res))

        if failed_issues:
            lines.append("❌ Unresolved Issues")
            lines.append("─" * 50)
            for phase, issue, repair_res in failed_issues[:10]:  # Show first 10
                emoji = "🔴" if issue.severity == Severity.CRITICAL else "orange"
                # Use standard bullet emojis
                emoji_symbol = "🔴" if emoji == "🔴" else "🟠"
                lines.append(f"  {emoji_symbol} [{phase}] {issue.description}")
                if repair_res and repair_res.error:
                    lines.append(f"      Fix error: {repair_res.error}")
            if len(failed_issues) > 10:
                lines.append(f"  ... and {len(failed_issues) - 10} more")
            lines.append("")

        # Footer
        exit_code = report.summary.exit_code
        if exit_code == 0:
            lines.append("✨ All checks passed or issues were fixed!")
        elif exit_code == 1:
            lines.append("⚠️  Some issues could not be automatically fixed. Manual intervention may be required.")
        else:
            lines.append("🚨 Critical issues found! Database integrity is compromised.")

        lines.append("")

        return "\n".join(lines)

    def _format_duration(self, ms: int) -> str:
        """Format duration in human-readable format."""
        if ms < 1000:
            return f"{ms}ms"
        elif ms < 60000:
            return f"{ms / 1000:.1f}s"
        else:
            minutes = ms // 60000
            seconds = (ms % 60000) / 1000
            return f"{minutes}m {seconds:.0f}s"


__all__ = [
    "FixReport",
    "ReportGenerator",
]
