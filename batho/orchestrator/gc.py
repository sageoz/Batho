"""Orchestrator for `batho gc` — garbage collection and bundle maintenance.

Deletes specific runs/artifacts, prunes runs older than N days, vacuums
orphaned Arrow IPC generations, and provides status reports.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from batho.core.config import set_active_root
from batho.modules.storage.arrow_bundle import get_bundle, resolve_bundle_dir
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
    bundle_dir = resolve_bundle_dir(root)
    if not (bundle_dir / "meta.json").exists():
        return {"success": False, "message": f"No artifact bundle found at {root}."}

    db = get_bundle(root)

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

        threshold_date = datetime.now(timezone.utc) - timedelta(days=options.older_than)
        threshold_str = threshold_date.isoformat()

        all_runs = db._reader.get_all_runs()
        old_uuids = [
            r["run_uuid"] for r in all_runs
            if r.get("started_at", "") < threshold_str
        ]

        if not old_uuids:
            return {"success": True, "message": f"No runs found older than {options.older_than} days."}

        for run_uuid in old_uuids:
            db.delete_run(run_uuid)

        return {
            "success": True,
            "message": f"Successfully deleted {len(old_uuids)} runs older than {options.older_than} days: {', '.join(old_uuids)}.",
        }

    elif options.command == "vacuum":
        deleted = db.garbage_collect()
        return {"success": True, "message": f"GC complete — {deleted} orphaned IPC generation(s) removed."}

    elif options.command == "orphans":
        deleted = db.garbage_collect()
        return {"success": True, "message": f"Orphan sweep complete — {deleted} stale IPC file(s) removed."}

    elif options.command == "status":
        stats = db.get_stats()
        tables = stats.get("tables", {})
        total_mb = sum(t.get("size_bytes", 0) for t in tables.values()) / (1024 * 1024)
        runs_count = tables.get("runs", {}).get("rows", 0)
        tracking_count = tables.get("file_tracking", {}).get("rows", 0)
        artifacts_count = tables.get("run_artifacts", {}).get("rows", 0)
        msg = (
            f"Storage Status for {bundle_dir.name}:\n"
            f"  Total artifact size: {total_mb:.2f} MB\n"
            f"  Arrow generation:    {stats.get('generation', 0)}\n"
            f"  Total runs:          {runs_count}\n"
            f"  File tracking:       {tracking_count}\n"
            f"  Run artifacts:       {artifacts_count}\n"
            f"  Last run:            {stats.get('last_run_uuid', 'none')}"
        )
        return {"success": True, "message": msg}

    else:
        return {"success": False, "message": f"Unknown gc command: {options.command}"}
