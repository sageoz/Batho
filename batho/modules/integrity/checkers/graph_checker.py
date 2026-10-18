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
            agent_entities = artifact.get("graph", {}).get("entities", [])
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

    def _check_duplicate_entity_ids(self) -> list[Issue]:
        """Detect entity_id rows duplicated in agent_views (one id, many rows)."""
        issues: list[Issue] = []
        try:
            agent = self.db._reader._get_table("agent_views")
            if (
                not isinstance(getattr(agent, "num_rows", None), int)
                or agent.num_rows == 0
            ):
                return issues
            import pyarrow.compute as pc

            counts = pc.value_counts(agent.column("entity_id"))
            values = counts.field("values").to_pylist()
            n = counts.field("counts").to_pylist()
            dups = [(v, c) for v, c in zip(values, n) if c > 1]
            if dups:
                issues.append(
                    Issue(
                        type="DUP_ENTITY_ID",
                        severity=Severity.ERROR,
                        table="agent_views",
                        identifier={
                            "duplicate_ids": len(dups),
                            "worst": max(c for _, c in dups),
                        },
                        description=(
                            f"{len(dups)} entity_id values appear more than once "
                            f"in agent_views ({sum(c - 1 for _, c in dups)} surplus rows)."
                        ),
                        repair_strategy=None,
                    )
                )
        except Exception as e:
            issues.append(
                Issue(
                    type="graph_check_error",
                    severity=Severity.ERROR,
                    table="agent_views",
                    identifier={},
                    description=f"Error checking duplicate entity ids: {e}",
                )
            )
        return issues

    def _check_stub_target_stub(self) -> list[Issue]:
        """Detect stubs whose persisted resolved_target_id is a stub or itself."""
        issues: list[Issue] = []
        try:
            agent = self.db._reader._get_table("agent_views")
            if (
                not isinstance(getattr(agent, "num_rows", None), int)
                or agent.num_rows == 0
                or "metadata_json" not in agent.schema.names
            ):
                return issues
            import json
            import pyarrow.compute as pc

            meta_col = agent.column("metadata_json")
            candidates = agent.filter(
                pc.and_(
                    pc.is_valid(meta_col),
                    pc.starts_with(agent.column("entity_id"), "unresolved:"),
                    pc.match_substring_regex(meta_col, '"resolved_target_id"'),
                )
            )
            stub_self = 0
            stub_stub = 0
            for eid, meta_str in zip(
                candidates.column("entity_id").to_pylist(),
                candidates.column("metadata_json").to_pylist(),
            ):
                try:
                    meta = json.loads(meta_str)
                except (ValueError, TypeError):
                    continue
                target = meta.get("resolved_target_id")
                if not target:
                    continue
                if target == eid:
                    stub_self += 1
                elif target.startswith("unresolved:"):
                    stub_stub += 1
            if stub_self or stub_stub:
                issues.append(
                    Issue(
                        type="STUB_TARGET_STUB",
                        severity=Severity.ERROR,
                        table="agent_views",
                        identifier={"self": stub_self, "stub": stub_stub},
                        description=(
                            f"{stub_stub} stubs resolve to another stub and "
                            f"{stub_self} resolve to themselves — the symbol "
                            f"table accepted contextual stubs as targets."
                        ),
                        repair_strategy=None,
                    )
                )
        except Exception as e:
            issues.append(
                Issue(
                    type="graph_check_error",
                    severity=Severity.ERROR,
                    table="agent_views",
                    identifier={},
                    description=f"Error checking stub resolution targets: {e}",
                )
            )
        return issues

    def run(self) -> CheckReport:
        """Run all Phase 4 checks against the Arrow current/ store."""
        start_time = time.time()
        issues = []

        # Bundle-level resolution-quality checks (independent of BSG store)
        issues.extend(self._check_duplicate_entity_ids())
        issues.extend(self._check_stub_target_stub())

        try:
            from batho.modules.storage.arrow_store.store import BsgScratchStore
            from batho.modules.storage.arrow_store.compaction import read_ipc

            from batho.core.config.loader import _get_config_cached_for_root
            from pathlib import Path

            cfg = _get_config_cached_for_root(self.db._repo_root)
            bsg_dir_val = cfg.get("paths", {}).get("bsg_dir", ".batho/bsg")

            bsg_dir = Path(bsg_dir_val)
            if not bsg_dir.is_absolute():
                bsg_dir = self.db._repo_root / bsg_dir

            current_dir = bsg_dir.resolve() / "current"

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
