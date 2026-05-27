"""Orchestrator for `batho gc` — garbage collection and database maintenance.

Deletes specific runs/artifacts, prunes runs older than N days, vacuums,
and provides status reports on SQLite database size and counts.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from batho.core.config import set_active_root
from batho.modules.storage.sqlite_registry.engine import get_database, resolve_db_path
from batho.utils.logging import get_logger

LOGGER = get_logger(__name__, component="orchestrator.gc")


@dataclass
class GCOptions:
    root: Path
    command: str
    run_uuid: str | None = None
    older_than: int | None = None
    verbose: bool = False


def run_gc(options: GCOptions) -> dict[str, Any]:
    root = options.root.resolve()
    if not root.exists():
        return {"success": False, "message": f"Repository root does not exist: {root}"}
    if not root.is_dir():
        return {"success": False, "message": f"Repository root is not a directory: {root}"}

    set_active_root(root)
    db_path = resolve_db_path(root)
    if not db_path.exists():
        return {"success": False, "message": f"No artifact database found at {root}."}

    db = get_database(root)

    if options.command == "run":
        if not options.run_uuid:
            return {"success": False, "message": "Missing run_uuid"}

        run = db.get_run(options.run_uuid)
        if not run:
            return {"success": False, "message": f"Run not found: {options.run_uuid}"}

        db.delete_run(options.run_uuid)
        return {"success": True, "message": f"Successfully deleted run {options.run_uuid}."}

    elif options.command == "runs":
        if options.older_than is None or options.older_than < 0:
            return {"success": False, "message": "Invalid older-than threshold"}

        # started_at in index_runs is ISO 8601 string, e.g. 2026-05-26T18:15:22.123456
        threshold_date = datetime.now(timezone.utc) - timedelta(days=options.older_than)
        threshold_str = threshold_date.isoformat()

        with db.connection() as conn:
            rows = conn.execute(
                "SELECT run_uuid FROM index_runs WHERE started_at < ?",
                (threshold_str,),
            ).fetchall()

            run_uuids = [row["run_uuid"] for row in rows]

        if not run_uuids:
            return {"success": True, "message": f"No runs found older than {options.older_than} days."}

        for run_uuid in run_uuids:
            db.delete_run(run_uuid)

        return {
            "success": True,
            "message": f"Successfully deleted {len(run_uuids)} runs older than {options.older_than} days: {', '.join(run_uuids)}.",
        }

    elif options.command == "vacuum":
        db.full_vacuum()
        return {"success": True, "message": "Database vacuum completed successfully."}

    elif options.command == "status":
        stats = db.get_stats()
        db_size_mb = stats.get("file_size_bytes", 0) / (1024 * 1024)
        msg = (
            f"Storage Status for {db_path.name}:\n"
            f"  Database size: {db_size_mb:.2f} MB\n"
            f"  Total runs: {stats.get('index_runs_count', 0)}\n"
            f"  File artifacts: {stats.get('file_artifacts_count', 0)}\n"
            f"  File tracking entries: {stats.get('file_tracking_count', 0)}\n"
            f"  Run artifacts: {stats.get('run_artifacts_count', 0)}\n"
            f"  Query entities: {stats.get('query_entities_count', 0)}"
        )
        return {"success": True, "message": msg}

    else:
        return {"success": False, "message": f"Unknown gc command: {options.command}"}
