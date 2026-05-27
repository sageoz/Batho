"""Graph Repairer."""

from __future__ import annotations

from typing import Any
import orjson
import zstandard as zstd

from ..models import Issue, RepairResult


class GraphRepairer:
    """Repairer for hypergraph synchronization and dangling reference issues."""

    def __init__(self, db: Any):
        self.db = db
        self.dctx = zstd.ZstdDecompressor()

    def repair(self, issue: Issue) -> RepairResult:
        """Dispatch to appropriate repair strategy."""
        if issue.repair_strategy == "rebuild_query_entities":
            return self.repair_desync(issue)
        elif issue.repair_strategy == "resolve_dangling":
            return self.repair_dangling(issue)
        elif issue.repair_strategy == "delete_invalid_relationship":
            return self.repair_invalid_relationship(issue)
        else:
            return RepairResult(
                issue=issue,
                success=False,
                error=f"Unknown or unhandled repair strategy: {issue.repair_strategy}",
            )

    def repair_desync(self, issue: Issue) -> RepairResult:
        """Rebuild query_entities from the agent view blob."""
        run_id = issue.identifier.get("run_id")
        file_path = issue.identifier.get("file_path")
        if run_id is None or file_path is None:
            return RepairResult(issue=issue, success=False, error="Missing run_id or file_path in identifier")

        from batho.storage.engine import _expand_graph_payload

        try:
            with self.db.transaction() as conn:
                # 1. Fetch the agent view blob
                row = conn.execute(
                    "SELECT bsg_agent_view FROM file_artifacts "
                    "WHERE run_id = ? AND file_id = (SELECT id FROM string_dict WHERE val = ?)",
                    (run_id, file_path),
                ).fetchone()

                if not row or not row[0]:
                    return RepairResult(issue=issue, success=False, error=f"No agent view blob found for '{file_path}'")

                # 2. Decompress and expand
                decompressed = self.dctx.decompress(row[0])
                minified = orjson.loads(decompressed)
                expanded = _expand_graph_payload(minified)
                entities = expanded.get("entities", [])

                # 3. Delete existing query_entities
                conn.execute(
                    "DELETE FROM query_entities WHERE run_id = ? AND file_path = ?",
                    (run_id, file_path),
                )

                # 4. Insert entities
                query_rows = []
                for e in entities:
                    ent_id = e.get("id")
                    ent_name = e.get("name")
                    ent_type = e.get("type") or e.get("entity_type")
                    ent_fqn = e.get("fqn")
                    line = e.get("start_line") or e.get("line") or 1
                    sig = e.get("signature")
                    is_exp = e.get("is_exported") or 0
                    if ent_id and ent_name and ent_type:
                        query_rows.append((
                            ent_id,
                            run_id,
                            ent_name,
                            ent_type,
                            ent_fqn,
                            file_path,
                            line,
                            sig,
                            is_exp,
                        ))

                if query_rows:
                    conn.executemany(
                        """INSERT OR REPLACE INTO query_entities(
                            entity_id, run_id, entity_name, entity_type, fqn, file_path, line_number, signature, is_exported
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        query_rows,
                    )
                conn.commit()

            return RepairResult(issue=issue, success=True, rows_affected=len(query_rows))
        except Exception as e:
            return RepairResult(issue=issue, success=False, error=str(e))

    def repair_dangling(self, issue: Issue) -> RepairResult:
        """Resolve dangling references in the database."""
        run_id = issue.identifier.get("run_id")
        if run_id is None:
            return RepairResult(issue=issue, success=False, error="Missing run_id in identifier")

        try:
            resolved_count = self.db.resolve_dangling_references(run_id)
            return RepairResult(issue=issue, success=True, rows_affected=resolved_count)
        except Exception as e:
            return RepairResult(issue=issue, success=False, error=str(e))

    def repair_invalid_relationship(self, issue: Issue) -> RepairResult:
        """Delete invalid relationship rows."""
        src_id = issue.identifier.get("source_id")
        tgt_id = issue.identifier.get("target_id")
        rel_type = issue.identifier.get("relation_type")
        run_id = issue.identifier.get("run_id")

        if any(v is None for v in (src_id, tgt_id, rel_type, run_id)):
            return RepairResult(issue=issue, success=False, error="Missing fields in relationship identifier")

        try:
            with self.db.connection() as conn:
                cursor = conn.execute(
                    "DELETE FROM query_relationships WHERE source_id = ? AND target_id = ? AND relation_type = ? AND run_id = ?",
                    (src_id, tgt_id, rel_type, run_id),
                )
                rows_deleted = cursor.rowcount
                conn.commit()
            return RepairResult(issue=issue, success=True, rows_affected=rows_deleted)
        except Exception as e:
            return RepairResult(issue=issue, success=False, error=str(e))
