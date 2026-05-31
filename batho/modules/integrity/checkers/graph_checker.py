"""Graph Sync Checker (Phase 4)."""

from __future__ import annotations

import time
from typing import Any
import sqlite3
import orjson
import zstandard as zstd

from ..models import CheckReport, CheckStatus, Issue, Severity
from ..repairers.graph_repairer import GraphRepairer


def _is_pseudo_target(target_id: str) -> bool:
    """Check if target_id is a special pseudo-target, not an entity reference."""
    pseudo_prefixes = (
        "external:",
        "file:",
        "anchor:",
        "image:",
        "import:",
        "stylesheet:",
        "resource:",
        "variable:",
    )
    return target_id.startswith(pseudo_prefixes)


class GraphSyncChecker:
    """Checker for hypergraph entity index synchronization and dangling references."""

    def __init__(self, db: Any, dry_run: bool = False, deep: bool = False):
        self.db = db
        self.dry_run = dry_run
        self.deep = deep
        self.dctx = zstd.ZstdDecompressor()
        self.repairer = GraphRepairer(db)

    def check_query_entities_sync(self, conn: sqlite3.Connection) -> list[Issue]:
        """Compare count/IDs in query_entities vs expanded bsg_agent_view blobs."""
        issues = []
        # Query all file artifacts
        rows = conn.execute(
            "SELECT fa.run_id, fa.file_id, sd.val, fa.bsg_agent_view "
            "FROM file_artifacts fa "
            "JOIN string_dict sd ON fa.file_id = sd.id"
        ).fetchall()

        from batho.modules.storage.sqlite_registry.engine import _expand_graph_payload

        for row in rows:
            run_id, file_id, file_path, agent_view_blob = row
            if not agent_view_blob:
                continue

            try:
                # Decompress and expand
                decompressed = self.dctx.decompress(agent_view_blob)
                minified = orjson.loads(decompressed)
                expanded = _expand_graph_payload(minified)
                blob_entities = expanded.get("entities", [])
                blob_entity_ids = {e.get("id") for e in blob_entities if e.get("id")}
            except Exception as e:
                # Handled by blob checker, but log/skip here
                continue

            # Query database query_entities
            db_entities = conn.execute(
                "SELECT ed.val AS entity_id FROM query_entities qe "
                "JOIN entity_dict ed ON qe.entity_key = ed.id "
                "WHERE qe.run_id = ? AND qe.file_path = ?",
                (run_id, file_path),
            ).fetchall()
            db_entity_ids = {r[0] for r in db_entities}

            if blob_entity_ids != db_entity_ids:
                issues.append(
                    Issue(
                        type="graph_index_desync",
                        severity=Severity.ERROR,
                        table="query_entities",
                        identifier={"run_id": run_id, "file_path": file_path},
                        description=f"Query entities index desync for '{file_path}' (run_id {run_id}). Blob has {len(blob_entity_ids)} entities, DB index has {len(db_entity_ids)}.",
                        repair_strategy="rebuild_query_entities",
                    )
                )
        return issues

    def check_dangling_references(self, conn: sqlite3.Connection) -> list[Issue]:
        """Find unresolved targets in dangling_references that now exist in query_entities."""
        issues = []
        query = """
            SELECT DISTINCT d.run_id
            FROM dangling_references d
            JOIN query_entities e ON d.unresolved_target_name = e.entity_name AND d.run_id = e.run_id
            WHERE e.entity_type != 'UNRESOLVED'
        """
        rows = conn.execute(query).fetchall()
        for row in rows:
            run_id = row[0]
            issues.append(
                Issue(
                    type="resolvable_dangling_reference",
                    severity=Severity.WARNING,
                    table="dangling_references",
                    identifier={"run_id": run_id},
                    description=f"Resolvable dangling references found for run_id {run_id}.",
                    repair_strategy="resolve_dangling",
                )
            )
        return issues

    def check_query_relationships(self, conn: sqlite3.Connection) -> list[Issue]:
        """Validate query_relationships referential integrity."""
        issues = []
        query = """
            SELECT ed_src.val AS source_id, ed_tgt.val AS target_id, r.relation_type, r.run_id
            FROM query_relationships r
            JOIN entity_dict ed_src ON r.source_key = ed_src.id
            JOIN entity_dict ed_tgt ON r.target_key = ed_tgt.id
            WHERE (ed_tgt.val NOT LIKE 'external:%'
                AND ed_tgt.val NOT LIKE 'file:%'
                AND ed_tgt.val NOT LIKE 'anchor:%'
                AND ed_tgt.val NOT LIKE 'image:%'
                AND ed_tgt.val NOT LIKE 'import:%'
                AND ed_tgt.val NOT LIKE 'stylesheet:%'
                AND ed_tgt.val NOT LIKE 'resource:%'
                AND ed_tgt.val NOT LIKE 'variable:%')
            AND (NOT EXISTS (
                SELECT 1 FROM query_entities e WHERE e.entity_key = r.source_key AND e.run_id = r.run_id
            ) OR NOT EXISTS (
                SELECT 1 FROM query_entities e WHERE e.entity_key = r.target_key AND e.run_id = r.run_id
            ))
        """
        rows = conn.execute(query).fetchall()
        for row in rows:
            src_id, tgt_id, rel_type, run_id = row
            if _is_pseudo_target(tgt_id) or _is_pseudo_target(src_id):
                continue
            issues.append(
                Issue(
                    type="invalid_relationship",
                    severity=Severity.ERROR,
                    table="query_relationships",
                    identifier={
                        "source_id": src_id,
                        "target_id": tgt_id,
                        "relation_type": rel_type,
                        "run_id": run_id,
                    },
                    description=f"Relationship '{rel_type}' references non-existent entity {src_id} or {tgt_id} in run_id {run_id}.",
                    repair_strategy="delete_invalid_relationship",
                )
            )
        return issues

    def run(self) -> CheckReport:
        """Run all Phase 4 checks and apply repairs if not dry_run."""
        start_time = time.time()
        issues = []
        tables_created = False

        try:
            self.db.ensure_query_tables_exist()
            tables_created = True
            
            run_uuid = self.db.get_latest_run_id()
            if run_uuid:
                run_internal_id = self.db.get_run_internal_id(run_uuid)
                if run_internal_id is not None:
                    with self.db.transaction() as conn:
                        conn.execute("DELETE FROM query_entities WHERE run_id = ?", (run_internal_id,))
                        conn.execute("DELETE FROM query_relationships WHERE run_id = ?", (run_internal_id,))
                        conn.execute("DELETE FROM dangling_references WHERE run_id = ?", (run_internal_id,))
                    self.db.populate_query_tables_for_unchanged_files(run_internal_id, run_internal_id, set())

            with self.db.connection() as conn:
                issues.extend(self.check_dangling_references(conn))
                issues.extend(self.check_query_relationships(conn))
                if self.deep:
                    issues.extend(self.check_query_entities_sync(conn))
        except Exception as e:
            issues.append(
                Issue(
                    type="graph_check_error",
                    severity=Severity.ERROR,
                    table="sqlite_master",
                    identifier={},
                    description=f"Error executing graph sync checks: {e}",
                )
            )
        finally:
            if tables_created:
                try:
                    self.db.cleanup_query_tables()
                except Exception:
                    pass

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
