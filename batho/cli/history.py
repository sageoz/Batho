"""CLI subcommand: batho history

List indexing runs, and query node-level changes across runs, entities, or files.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from batho.cli._utils import create_base_parser


def register_history_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the `history` subcommand on the given subparsers action."""
    parser = subparsers.add_parser(
        "history",
        parents=[create_base_parser()],
        help="List runs and query node-level change history",
        description="Lists recent indexing runs and tracks granular node evolution across runs, entities, or files.",
    )

    # Mutually exclusive group for targets; bare invocation lists recent runs.
    group = parser.add_mutually_exclusive_group(required=False)
    group.add_argument(
        "--run",
        type=str,
        help="All node changes in a specific patch run ID",
    )
    group.add_argument(
        "--entity",
        type=str,
        help="Full evolution history of one entity ID",
    )
    group.add_argument(
        "--file",
        type=str,
        help="All node changes in a file across runs (relative path)",
    )

    parser.add_argument(
        "--last",
        type=int,
        default=10,
        help="Max entries to show: runs in list mode, history entries with --entity, transitions with --file (default: 10; ignored with --run)",
    )
    parser.add_argument(
        "--since",
        type=str,
        help="Bounded history start run ID (only applicable with --entity)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Output in machine-readable JSON format",
    )

    parser.set_defaults(func=cmd_history)


def cmd_history(args: argparse.Namespace) -> int:
    """Execute the history subcommand."""
    from batho.modules.storage.arrow_bundle import get_bundle, resolve_bundle_dir

    if args.since and not args.entity:
        print("error: --since can only be used with --entity", file=sys.stderr)
        return 1

    root = Path(args.root or ".").resolve()
    bundle_dir = resolve_bundle_dir(root)

    if not (bundle_dir / "meta.json").exists():
        print(f"No artifact bundle found at {root}. Run: batho build --root {root}", file=sys.stderr)
        return 1

    try:
        db = get_bundle(root)
    except Exception as exc:
        print(f"error: Failed to open artifact bundle: {exc}", file=sys.stderr)
        return 1

    if args.run:
        return _handle_run_history(db, args.run, args.json)
    elif args.entity:
        return _handle_entity_history(db, args.entity, args.since, args.last, args.json)
    elif args.file:
        return _handle_file_history(db, args.file, args.last, args.json)

    return _handle_run_list(db, args.last, args.json)


def _run_type(run_uuid: str) -> str:
    """Derive run kind from the run_uuid prefix (patch_*, build_*, plugins_apply_*)."""
    if run_uuid.startswith("plugins_apply_"):
        return "plugins_apply"
    return run_uuid.split("_", 1)[0] if "_" in run_uuid else "unknown"


def _handle_run_list(db: Any, last: int, output_json: bool) -> int:
    """List the most recent runs, newest first."""
    runs = db._reader.get_all_runs()
    runs = sorted(runs, key=lambda r: r.get("started_at") or "", reverse=True)
    shown = runs[: max(last, 0)]

    if output_json:
        print(json.dumps({
            "runs": [
                {
                    "run_uuid": r.get("run_uuid", ""),
                    "run_type": _run_type(r.get("run_uuid", "")),
                    "started_at": r.get("started_at"),
                    "completed_at": r.get("completed_at"),
                    "status": r.get("status"),
                    "git_commit": r.get("git_commit"),
                    "git_branch": r.get("git_branch"),
                    "file_count": r.get("file_count"),
                    "entity_count": r.get("entity_count"),
                    "rel_count": r.get("rel_count"),
                    "duration_ms": r.get("duration_ms"),
                }
                for r in shown
            ],
            "total": len(runs),
            "limit": last,
        }, indent=2))
        return 0

    if not runs:
        print("No runs recorded in this artifact.")
        return 0

    for r in shown:
        ruid = r.get("run_uuid", "")
        commit = (r.get("git_commit") or "")[:8] or "-"
        print(
            f"{ruid}  {_run_type(ruid):<13}  {r.get('status', '?'):<9}  "
            f"{r.get('started_at') or '?'}  files={r.get('file_count', 0)}  "
            f"entities={r.get('entity_count', 0)}  {r.get('duration_ms') or 0}ms  "
            f"commit={commit}"
        )
    print(f"\nshowing {len(shown)} of {len(runs)} runs (--last N to adjust)")
    return 0


def _handle_run_history(db: Any, run_uuid: str, output_json: bool) -> int:
    """Fetch and display changes in a single run."""
    run_meta = db.get_run(run_uuid)
    if not run_meta:
        print(f"error: Run '{run_uuid}' not found.", file=sys.stderr)
        return 1

    changes = db.get_run_file_changelog(run_uuid)

    if output_json:
        print(json.dumps(changes, indent=2))
        return 0

    if not changes:
        print(f"No node changes in run {run_uuid}.")
        return 0

    by_kind = defaultdict(list)
    for c in changes:
        by_kind[c["change_kind"]].append(c)

    print(f"Run: {run_uuid} (base: {changes[0]['base_run_uuid'] if changes else 'None'})\n")

    kinds_to_show = [
        ("added", "Added nodes:"),
        ("removed", "Removed nodes:"),
        ("modified", "Modified nodes:"),
        ("renamed", "Renamed nodes:")
    ]

    has_output = False
    for kind, title in kinds_to_show:
        items = by_kind[kind]
        if items:
            has_output = True
            print(title)
            for item in sorted(items, key=lambda x: (x.get("file_path", ""), x["entity_name"])):
                name = item["entity_name"]
                type_str = item["entity_type"]
                file_path = item.get("file_path") or f"file_id:{item.get('file_id')}"
                entity_id = item["entity_id"]
                # changed_fields is stored as list[str] of field names —
                # old/new values are not persisted in the changelog schema.
                changed = item.get("changed_fields") or []
                suffix = (
                    f", fields: {', '.join(changed)}"
                    if kind in ("modified", "renamed") and changed
                    else ""
                )
                print(f"  - [{type_str}] {name} in {file_path} (ID: {entity_id}{suffix})")
            print()

    if not has_output:
        print("No node changes recorded for this run.")
    return 0


def _handle_entity_history(db: Any, entity_id: str, since_run_uuid: str | None, last: int, output_json: bool) -> int:
    """Fetch and display history of a single entity."""
    since_completed_at = None
    if since_run_uuid:
        since_run = db.get_run(since_run_uuid)
        if not since_run:
            print(f"error: Run '{since_run_uuid}' not found.", file=sys.stderr)
            return 1
        since_completed_at = since_run.get("completed_at")

    history = db.get_file_node_history(
        entity_id, limit=max(last, 0), since_completed_at=since_completed_at
    )

    if output_json:
        print(json.dumps(history, indent=2))
        return 0

    if not history:
        print(f"No history found for entity {entity_id}.")
        return 0

    first = history[0]
    name = first["entity_name"]
    type_str = first["entity_type"]
    file_path = first.get("file_path", "")

    print(f"Entity: {name}  [{type_str}]  {file_path}\n")

    for entry in history:
        base_uuid = entry["base_run_uuid"]
        run_uuid = entry["run_uuid"]
        kind = entry["change_kind"]
        changed = entry["changed_fields"]

        print(f"  {base_uuid}  →  {run_uuid}")
        fields = ", ".join(changed) if changed else ""
        if kind == "added":
            print("    [added]")
        elif kind == "removed":
            print("    [removed]")
        elif kind == "renamed":
            print(f"    [renamed]{f' fields: {fields}' if fields else ''}")
        elif kind == "modified":
            print(f"    [modified]{f' fields: {fields}' if fields else ''}")
        print()

    return 0


def _handle_file_history(db: Any, rel_path: str, last: int, output_json: bool) -> int:
    """Fetch and display changes in a file across runs."""
    results = db.get_file_changelog_raw(rel_path)

    if output_json:
        print(json.dumps(results, indent=2))
        return 0

    if not results:
        print(f"No node changes found for file {rel_path}.")
        return 0

    print(f"File: {rel_path}\n")

    by_transition = defaultdict(list)
    transition_order = []
    for item in results:
        t = (item["base_run_uuid"], item["run_uuid"])
        if t not in by_transition:
            transition_order.append(t)
        by_transition[t].append(item)

    for t in transition_order[: max(last, 0)]:
        base_uuid, run_uuid = t
        print(f"  {base_uuid}  →  {run_uuid}")
        for item in by_transition[t]:
            kind = item["change_kind"]
            name = item["entity_name"]
            type_str = item["entity_type"]
            entity_id = item["entity_id"]
            changed = item.get("changed_fields") or []
            fields = f" fields: {', '.join(changed)}" if changed else ""
            print(f"    [{kind}] {name} [{type_str}] (ID: {entity_id}{fields})")
        print()

    if len(transition_order) > max(last, 0):
        print(f"showing {max(last, 0)} of {len(transition_order)} transitions (--last N to adjust)")
    return 0
