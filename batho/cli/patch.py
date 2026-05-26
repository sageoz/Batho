"""CLI subcommand: batho patch

Thin argparse wrapper around batho.orchestrator.patch.run_patch().
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def register_patch_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the `patch` subcommand on the given subparsers action."""
    parser = subparsers.add_parser(
        "patch",
        help="Incremental patch of an existing artifact database",
        description=(
            "Detects changes natively using content hashing against the SQLite "
            "file_tracking table. Unlike previous versions, this does not use Git "
            "status for change detection, eliminating false positives from "
            "uncommitted files."
        ),
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("."),
        help="Repository root directory (default: current directory)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        default=False,
        help="Enable verbose debug logging",
    )
    parser.add_argument(
        "--max-file-size-kb",
        type=int,
        default=None,
        help="Skip files exceeding this size in kilobytes during hash scan",
    )

    parser.set_defaults(func=cmd_patch)


def cmd_patch(args: argparse.Namespace) -> int:
    """Execute the patch command."""
    from batho.orchestrator.patch import PatchOptions, run_patch

    options = PatchOptions(
        root=args.root,
        verbose=args.verbose,
        max_file_size_kb=args.max_file_size_kb,
    )

    result = run_patch(options)

    if not result.success:
        for w in result.warnings:
            if "No artifact database found" in w or "No baseline snapshot" in w:
                print(w, file=sys.stderr)
            else:
                print(f"error: {w}", file=sys.stderr)
        return 1

    if result.warnings and any("No changes detected" in w for w in result.warnings):
        for w in result.warnings:
            print(w)
        return 0

    # Success summary
    print(
        f"Patched {args.root.resolve()}: "
        f"{result.changes_applied} changes ("
        f"{result.added} added, "
        f"{result.modified} modified, "
        f"{result.deleted} deleted) "
        f"in {result.duration_ms}ms"
    )
    if (result.nodes_added or result.nodes_removed or result.nodes_modified or result.nodes_renamed):
        print(
            f"  Nodes: {result.nodes_added} added, "
            f"{result.nodes_removed} removed, "
            f"{result.nodes_modified} modified, "
            f"{result.nodes_renamed} renamed"
        )
    return 0
