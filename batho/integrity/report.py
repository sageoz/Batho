"""Report generation for batho fix command."""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any

from .checks import CheckResult, Severity
from .engine import FixResult, FixSummary
from .repair import RepairRecord


@dataclass
class FixReport:
    """Complete report from batho fix execution."""

    started_at: str
    completed_at: str
    root: str
    db_path: str
    mode: str
    summary: FixSummary
    check_results: list[CheckResult]
    repairs: list[RepairRecord]
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
            db_path=result.db_path,
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
            "db_path": report.db_path,
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
            "checks": [
                {
                    "name": cr.check_name,
                    "status": cr.status.value,
                    "duration_ms": cr.duration_ms,
                    "metrics": cr.metrics,
                    "findings": [
                        {
                            "severity": f.severity.value,
                            "message": f.message,
                            "details": f.details,
                            "auto_fixed": f.auto_fixed,
                            "fix_attempted": f.fix_attempted,
                            "fix_error": f.fix_error,
                        }
                        for f in cr.findings
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

        # Findings
        for check_result in report.check_results:
            for finding in check_result.findings:
                if finding.severity != Severity.INFO:  # Skip info-level in CSV
                    writer.writerow(
                        [
                            report.completed_at,
                            finding.check_name,
                            finding.severity.value,
                            finding.message,
                            "yes" if finding.auto_fixed else "no",
                            json.dumps(finding.details),
                        ]
                    )

        return output.getvalue()

    def _generate_text(self, report: FixReport) -> str:
        """Generate human-readable text report."""
        lines = []

        # Header
        lines.append("🔍 Batho Fix Report")
        lines.append("━" * 50)
        lines.append(f"Database:    {report.db_path}")
        lines.append(f"Mode:        {report.mode} {'(use --deep for full scan)' if report.mode == 'quick' else ''}")
        lines.append(f"Duration:    {self._format_duration(report.summary.duration_ms)}")
        lines.append("")

        # Summary
        lines.append(f"✅ Checks Passed:   {report.summary.checks_passed}/{report.summary.total_checks}")
        if report.summary.checks_fixed > 0:
            lines.append(f"🔧 Auto-Fixed:     {report.summary.checks_fixed} issues")
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
                for finding in check_result.findings:
                    if finding.auto_fixed:
                        status = "✅" if finding.fix_error is None else "⚠️"
                        lines.append(f"  {status} {finding.message}")
            lines.append("")

        # Failed/unfixed issues
        failed_findings = [
            f
            for cr in report.check_results
            for f in cr.findings
            if f.severity in (Severity.CRITICAL, Severity.ERROR) and not f.auto_fixed
        ]

        if failed_findings:
            lines.append("❌ Unresolved Issues")
            lines.append("─" * 50)
            for finding in failed_findings[:10]:  # Show first 10
                emoji = "🔴" if finding.severity == Severity.CRITICAL else "🟠"
                lines.append(f"  {emoji} [{finding.check_name}] {finding.message}")
                if finding.fix_error:
                    lines.append(f"      Fix error: {finding.fix_error}")
            if len(failed_findings) > 10:
                lines.append(f"  ... and {len(failed_findings) - 10} more")
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
