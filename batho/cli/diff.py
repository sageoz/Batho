from __future__ import annotations

import argparse
import json
import orjson
import sys
from pathlib import Path
from typing import Any

def register_diff_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the `diff` subcommand on the given subparsers action."""
    parser = subparsers.add_parser(
        "diff",
        help="Query node-level changes across runs, entities, or files",
        description="Tracks granular node evolution and prints node-level diff history.",
    )
    
    # Mutually exclusive group for targets
    group = parser.add_mutually_exclusive_group(required=True)
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
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("."),
        help="Repository root directory (default: current directory)",
    )
    
    parser.set_defaults(func=cmd_diff)


def cmd_diff(args: argparse.Namespace) -> int:
    """Execute the diff subcommand."""
    from batho.storage.engine import get_database, artifact_filename
    
    if args.since and not args.entity:
        print("error: --since can only be used with --entity", file=sys.stderr)
        return 1
        
    root = Path(args.root or ".").resolve()
    db_path = root / artifact_filename(root)
    
    if not db_path.exists():
        print(f"No artifact database found at {root}. Run: batho build --root {root}", file=sys.stderr)
        return 1
        
    try:
        db = get_database(root)
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
        
    if args.run:
        return _handle_run_diff(db, args.run, args.json)
    elif args.entity:
        return _handle_entity_diff(db, args.entity, args.since, args.json)
    elif args.file:
        return _handle_file_diff(db, args.file, args.json)
        
    return 0


def _handle_run_diff(db: Any, run_uuid: str, output_json: bool) -> int:
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
        
    from collections import defaultdict
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
            for item in sorted(items, key=lambda x: (x["file_path"], x["entity_name"])):
                name = item["entity_name"]
                type_str = item["entity_type"]
                file_path = item["file_path"]
                entity_id = item["entity_id"]
                if kind == "renamed":
                    old_id = item["changed_fields"].get("old_id", "unknown")
                    print(f"  - [{type_str}] {name} in {file_path} (ID: {entity_id}, old ID: {old_id})")
                elif kind == "modified":
                    print(f"  - [{type_str}] {name} in {file_path} (ID: {entity_id})")
                    changed = item["changed_fields"]
                    max_k_len = max(len(k) for k in changed.keys()) if changed else 0
                    for k, (old_val, new_val) in sorted(changed.items()):
                        print(f"    {k:<{max_k_len + 1}} {old_val} → {new_val}")
                else:
                    print(f"  - [{type_str}] {name} in {file_path} (ID: {entity_id})")
            print()
            
    if not has_output:
        print("No node changes recorded for this run.")
    return 0


def _handle_entity_diff(db: Any, entity_id: str, since_run_uuid: str | None, output_json: bool) -> int:
    """Fetch and display history of a single entity."""
    since_completed_at = None
    if since_run_uuid:
        since_run = db.get_run(since_run_uuid)
        if not since_run:
            print(f"error: Run '{since_run_uuid}' not found.", file=sys.stderr)
            return 1
        since_completed_at = since_run.get("completed_at")
        
    history = db.get_file_node_history(entity_id)
    
    if since_completed_at:
        filtered_history = []
        for entry in history:
            entry_run = db.get_run(entry["run_uuid"])
            if entry_run and entry_run.get("completed_at") and entry_run.get("completed_at") >= since_completed_at:
                filtered_history.append(entry)
        history = filtered_history
        
    if output_json:
        print(json.dumps(history, indent=2))
        return 0
        
    if not history:
        print(f"No history found for entity {entity_id}.")
        return 0
        
    first = history[0]
    name = first["entity_name"]
    type_str = first["entity_type"]
    file_path = first["file_path"]
    
    print(f"Entity: {name}  [{type_str}]  {file_path}\n")
    
    for entry in history:
        base_uuid = entry["base_run_uuid"]
        run_uuid = entry["run_uuid"]
        kind = entry["change_kind"]
        changed = entry["changed_fields"]
        
        print(f"  {base_uuid}  →  {run_uuid}")
        if kind == "added":
            print("    [added]")
        elif kind == "removed":
            print("    [removed]")
        elif kind == "renamed":
            old_id = changed.get("old_id", "unknown")
            print(f"    [renamed] old ID: {old_id}")
        elif kind == "modified":
            max_k_len = max(len(k) for k in changed.keys()) if changed else 0
            for k, (old_val, new_val) in sorted(changed.items()):
                print(f"    {k:<{max_k_len + 1}} {old_val} → {new_val}")
        print()
        
    return 0


def _handle_file_diff(db: Any, rel_path: str, output_json: bool) -> int:
    """Fetch and display changes in a file across runs."""
    sql = """
        SELECT fc.run_id, fc.base_run_id, fc.node_changes,
               r.run_uuid, base_r.run_uuid AS base_run_uuid
        FROM file_changelog fc
        JOIN string_dict file_dict ON fc.file_id = file_dict.id
        JOIN index_runs r ON fc.run_id = r.id
        JOIN index_runs base_r ON fc.base_run_id = base_r.id
        WHERE file_dict.val = ?
        ORDER BY r.completed_at ASC, fc.run_id ASC
    """

    results = []
    with db.connection(read_only=True) as conn:
        rows = conn.execute(sql, (rel_path,)).fetchall()
        for row in rows:
            blob = row["node_changes"]
            if not blob:
                continue
            changes = orjson.loads(db._dctx.decompress(blob))
            for entry in changes:
                results.append({
                    "run_id": row["run_id"],
                    "base_run_id": row["base_run_id"],
                    "run_uuid": row["run_uuid"],
                    "base_run_uuid": row["base_run_uuid"],
                    "entity_id": entry["entity_id"],
                    "entity_name": entry["entity_name"],
                    "entity_type": entry["entity_type"],
                    "change_kind": entry["change_kind"],
                    "changed_fields": entry["changed_fields"],
                    "old_hash": entry["old_hash"],
                    "new_hash": entry["new_hash"],
                })
            
    if output_json:
        print(json.dumps(results, indent=2))
        return 0
        
    if not results:
        print(f"No node changes found for file {rel_path}.")
        return 0
        
    print(f"File: {rel_path}\n")
    
    from collections import defaultdict
    by_transition = defaultdict(list)
    transition_order = []
    for item in results:
        t = (item["base_run_uuid"], item["run_uuid"])
        if t not in by_transition:
            transition_order.append(t)
        by_transition[t].append(item)
        
    for t in transition_order:
        base_uuid, run_uuid = t
        print(f"  {base_uuid}  →  {run_uuid}")
        for item in by_transition[t]:
            kind = item["change_kind"]
            name = item["entity_name"]
            type_str = item["entity_type"]
            entity_id = item["entity_id"]
            changed = item["changed_fields"]
            
            if kind == "added":
                print(f"    [added] {name} [{type_str}] (ID: {entity_id})")
            elif kind == "removed":
                print(f"    [removed] {name} [{type_str}] (ID: {entity_id})")
            elif kind == "renamed":
                old_id = changed.get("old_id", "unknown")
                print(f"    [renamed] {name} [{type_str}] (ID: {entity_id}, old ID: {old_id})")
            elif kind == "modified":
                print(f"    [modified] {name} [{type_str}] (ID: {entity_id})")
                max_k_len = max(len(k) for k in changed.keys()) if changed else 0
                for k, (old_val, new_val) in sorted(changed.items()):
                    print(f"      {k:<{max_k_len + 1}} {old_val} → {new_val}")
        print()
        
    return 0
