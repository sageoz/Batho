"""Arrow Bundle health checker — replaces SQLiteHealthChecker."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from batho.utils.logging import get_logger
from ..models import CheckReport, CheckStatus, Issue, RepairResult, Severity

LOGGER = get_logger(__name__, component="integrity.bundle_checker")


class BundleHealthChecker:
    """Verifies structural integrity of the Arrow Bundle artifact directory."""

    def __init__(self, bundle: Any, dry_run: bool = False) -> None:
        self.bundle = bundle
        self.dry_run = dry_run

    def run(self) -> CheckReport:
        issues: list[Issue] = []
        repairs: list[RepairResult] = []

        artifact_dir: Path = self.bundle.artifact_dir
        manager = self.bundle._manager

        # 1. meta.json present and parseable
        manifest = manager.load_manifest()
        if not manifest.get("active_files"):
            issues.append(Issue(
                type="missing_active_files",
                severity=Severity.CRITICAL,
                description="meta.json has no active_files entries. Bundle may be empty or corrupt.",
                auto_fixable=False,
            ))

        # 2. All active IPC files exist
        active = manifest.get("active_files", {})
        missing = [name for name, fname in active.items()
                   if not (artifact_dir / fname).exists()]
        for name in missing:
            issues.append(Issue(
                type="missing_ipc_file",
                severity=Severity.CRITICAL,
                description=f"Active IPC file for table '{name}' is missing from {artifact_dir}",
                auto_fixable=False,
            ))

        # 3. Schema version match
        from batho.modules.storage.arrow_bundle.schemas import BUNDLE_SCHEMA_VERSION
        schema_ver = manifest.get("schema_version", "")
        if schema_ver != BUNDLE_SCHEMA_VERSION:
            issues.append(Issue(
                type="schema_version_mismatch",
                severity=Severity.ERROR,
                description=(
                    f"Bundle schema version {schema_ver!r} does not match "
                    f"expected {BUNDLE_SCHEMA_VERSION!r}. Rebuild with: batho build --full"
                ),
                auto_fixable=False,
            ))

        # 4. IPC files are valid Arrow IPC (quick header check)
        import pyarrow.ipc as ipc
        for name, fname in active.items():
            p = artifact_dir / fname
            if not p.exists():
                continue
            try:
                with open(str(p), "rb") as f:
                    ipc.open_file(f)
            except Exception as exc:
                issues.append(Issue(
                    type="corrupt_ipc_file",
                    severity=Severity.CRITICAL,
                    description=f"IPC file '{fname}' for table '{name}' is corrupt: {exc}",
                    auto_fixable=False,
                ))

        # 5. GC: report orphaned files
        ipc_files = {p.name for p in artifact_dir.glob("*.ipc")}
        active_names = set(active.values())
        orphans = ipc_files - active_names
        if orphans:
            if not self.dry_run:
                deleted = manager.garbage_collect()
                repairs.append(RepairResult(
                    issue=Issue(
                        type="orphaned_ipc_files",
                        severity=Severity.WARNING,
                        description=f"{len(orphans)} orphaned IPC file(s) found",
                        auto_fixable=True,
                    ),
                    success=True,
                    rows_affected=deleted,
                ))
            else:
                issues.append(Issue(
                    type="orphaned_ipc_files",
                    severity=Severity.WARNING,
                    description=f"{len(orphans)} orphaned IPC file(s) found (dry-run; use `batho gc vacuum`)",
                    auto_fixable=True,
                ))

        if issues:
            critical = any(i.severity == Severity.CRITICAL for i in issues)
            status = CheckStatus.FAILED if critical else CheckStatus.PASSED
        else:
            status = CheckStatus.PASSED

        return CheckReport(
            phase="bundle",
            status=status,
            issues=issues,
            repairs=repairs,
        )
