"""Reads file_changelog + delta_stats for the get_delta MCP tool.

Uses existing BathoBundleReader methods to read changelog and run artifacts.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from batho.modules.storage.arrow_bundle.reader import BathoBundleReader


def find_latest_patch_run(reader: BathoBundleReader) -> str | None:
    """Find the latest patch run UUID by scanning the runs table."""
    runs = reader.get_all_runs()
    if not runs:
        return None
    patch_runs = [r for r in runs if r.get("run_uuid", "").startswith("patch_")]
    if patch_runs:
        return patch_runs[-1].get("run_uuid")
    return runs[-1].get("run_uuid") if runs else None


def read_delta(
    reader: BathoBundleReader,
    run_id: str | None = None,
    change_kind: str | None = None,
    file_path: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any] | None]:
    """Read delta changes, delta stats, and patch run info.

    Returns:
        Tuple of (changes_list, delta_stats_dict, patch_run_info_dict).
    """
    if run_id is None:
        run_id = find_latest_patch_run(reader)
        if run_id is None:
            return [], {}, None

    changes = reader.get_file_changelog_raw(since_run_uuid=run_id)

    if change_kind:
        changes = [c for c in changes if c.get("change_kind") == change_kind]

    if file_path:
        file_path = str(file_path).replace("\\", "/")
        fid = reader.file_id_for_path(file_path)
        if fid is not None:
            changes = [c for c in changes if c.get("file_id") == fid]
        else:
            changes = []

    total = len(changes)
    changes = changes[offset:offset + limit]

    delta_stats: dict[str, Any] = {}
    run_info: dict[str, Any] | None = None
    artifacts = reader.get_run_artifacts(run_id)
    if artifacts:
        ds_json = artifacts.get("delta_stats_json")
        if ds_json:
            try:
                delta_stats = json.loads(ds_json)
            except Exception:
                pass
        run_info = {
            "run_uuid": run_id,
            "created_at": artifacts.get("created_at"),
        }

    run_record = reader.get_run(run_id)
    if run_record:
        if run_info is None:
            run_info = {"run_uuid": run_id}
        run_info["git_commit"] = run_record.get("git_commit")
        run_info["git_branch"] = run_record.get("git_branch")
        run_info["started_at"] = run_record.get("started_at")
        run_info["completed_at"] = run_record.get("completed_at")
        run_info["duration_ms"] = run_record.get("duration_ms")

    delta_stats["_total_changes"] = total
    delta_stats["_offset"] = offset
    delta_stats["_limit"] = limit
    delta_stats["_returned"] = len(changes)

    return changes, delta_stats, run_info


def format_delta_markdown(
    changes: list[dict[str, Any]],
    delta_stats: dict[str, Any],
    run_info: dict[str, Any] | None,
    response_format: str = "concise",
) -> str:
    """Format delta changes as markdown for the content field."""
    lines: list[str] = []

    if run_info:
        lines.append("## Patch Run")
        lines.append(f"- Run: {run_info.get('run_uuid', 'unknown')}")
        if run_info.get("git_commit"):
            lines.append(f"- Git: {run_info.get('git_commit')}")
        if run_info.get("duration_ms") is not None:
            lines.append(f"- Duration: {run_info.get('duration_ms')}ms")
        lines.append("")

    lines.append("## Delta Summary")
    for key in ["nodes_added", "nodes_removed", "nodes_modified", "nodes_renamed",
                "files_changed", "files_added", "files_deleted", "churn_pct"]:
        val = delta_stats.get(key)
        if val is not None:
            label = key.replace("_", " ").title()
            lines.append(f"- {label}: {val}")
    lines.append("")

    if not changes:
        lines.append("No changes found matching the criteria.")
        return "\n".join(lines)

    by_kind: dict[str, list[dict]] = {}
    for c in changes:
        kind = c.get("change_kind", "unknown")
        by_kind.setdefault(kind, []).append(c)

    lines.append(f"## Changes ({len(changes)} shown)")
    for kind in ["added", "removed", "modified", "renamed"]:
        items = by_kind.get(kind, [])
        if not items:
            continue
        lines.append(f"### {kind.title()} ({len(items)})")
        for item in items:
            name = item.get("entity_name", "")
            etype = item.get("entity_type", "")
            eid = item.get("entity_id", "")
            if response_format == "detailed":
                lines.append(f"  - {name} [{etype}] id={eid}")
                changed_fields = item.get("changed_fields", [])
                if changed_fields:
                    lines.append(f"    Changed: {', '.join(changed_fields)}")
                old_h = item.get("old_hash")
                new_h = item.get("new_hash")
                if old_h or new_h:
                    lines.append(f"    Hash: {old_h or '?'} → {new_h or '?'}")
            else:
                lines.append(f"  - {name} [{etype}]")
        lines.append("")

    return "\n".join(lines)


def build_delta_structured(
    changes: list[dict[str, Any]],
    delta_stats: dict[str, Any],
    run_info: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build structured JSON for the get_delta tool."""
    return {
        "changes": changes,
        "delta_stats": delta_stats,
        "run_info": run_info,
    }
