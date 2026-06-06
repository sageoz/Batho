"""Graph Sync Checker (Phase 4)."""

from __future__ import annotations

import time
from typing import Any
from ..models import CheckReport, CheckStatus, Issue, Severity
from ..repairers.graph_repairer import GraphRepairer


class GraphSyncChecker:
    """Checker for hypergraph entity index synchronization and dangling references."""

    def __init__(self, db: Any, dry_run: bool = False, deep: bool = False):
        self.db = db
        self.dry_run = dry_run
        self.deep = deep
        self.repairer = GraphRepairer(db)

    def _check_arrow_entity_sync(self, store: Any, read_ipc: Any) -> list[Issue]:
        """Deep check: compare BSG scratch-store entities against bundle agent_view rows."""
        issues = []
        from batho.modules.storage.arrow_bundle.helpers import _expand_graph_payload

        if not store.entities_path.exists():
            return issues

        ent_tbl = read_ipc(store.entities_path)
        arrow_by_file: dict[str, set[str]] = {}
        fp_col = ent_tbl.column("file_path").to_pylist()
        key_col = ent_tbl.column("entity_key").to_pylist()
        for fp, key in zip(fp_col, key_col):
            val = store.get_entity_val(key)
            if fp and val:
                arrow_by_file.setdefault(fp, set()).add(val)

        run_id = self.db.get_latest_run_id()
        if not run_id:
            return issues
        run_internal_id = self.db.get_run_internal_id(run_id)
        if run_internal_id is None:
            return issues

        artifacts = self.db.get_file_artifacts(run_internal_id, include_storage=False)
        for artifact in (artifacts or []):
            fp = artifact.get("file_path", "")
            agent_entities = artifact.get("agent_view_data", {}).get("entities", [])
            blob_ids = {e.get("id") for e in agent_entities if e.get("id")}
            arrow_ids = arrow_by_file.get(fp, set())
            if blob_ids != arrow_ids:
                issues.append(Issue(
                    type="graph_index_desync",
                    severity=Severity.ERROR,
                    table="agent_views.ipc",
                    identifier={"file_path": fp},
                    description=(
                        f"Arrow entity sync mismatch for '{fp}': "
                        f"bundle has {len(blob_ids)}, BSG store has {len(arrow_ids)}."
                    ),
                    repair_strategy=None,
                ))
        return issues

    def run(self) -> CheckReport:
        """Run all Phase 4 checks against the Arrow current/ store."""
        start_time = time.time()
        issues = []

        try:
            from batho.modules.storage.arrow_store.store import BsgScratchStore
            from batho.modules.storage.arrow_store.compaction import read_ipc

            current_dir = self.db._repo_root / ".batho" / "bsg" / "current"
            if not current_dir.exists():
                pass  # No store yet — nothing to check
            else:
                store = BsgScratchStore.from_run_dir(current_dir, run_internal_id=0)

                # Check dangling references in Arrow store
                if store.dangling_path.exists():
                    dan_tbl = read_ipc(store.dangling_path)
                    if len(dan_tbl) > 0:
                        issues.append(
                            Issue(
                                type="resolvable_dangling_reference",
                                severity=Severity.WARNING,
                                table="dangling_references",
                                identifier={"run_id": store.run_internal_id},
                                description=f"{len(dan_tbl)} unresolved dangling references in Arrow store.",
                                repair_strategy="resolve_dangling",
                            )
                        )

                if self.deep:
                    issues.extend(self._check_arrow_entity_sync(store, read_ipc))

        except Exception as e:
            issues.append(
                Issue(
                    type="graph_check_error",
                    severity=Severity.ERROR,
                    table="arrow_bundle",
                    identifier={},
                    description=f"Error executing graph sync checks: {e}",
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
            phase="graph",
            status=status,
            issues=issues,
            repairs=repairs,
            duration_ms=duration_ms,
            metrics={"issues_count": len(issues), "repairs_count": len(repairs)},
        )
