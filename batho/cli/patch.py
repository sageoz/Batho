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
            "Detects changes since the last build/patch and applies incremental "
            "graph updates, refreshing all DB artifacts."
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
    parser.add_argument(
        "--mode",
        type=str,
        choices=["commit", "staged", "modified", "auto"],
        default="auto",
        help=(
            "Change detection mode: commit (committed changes vs snapshot), "
            "staged (git add), modified (working dir), "
            "auto (staged+modified, default)"
        ),
    )
    parser.set_defaults(func=cmd_patch)


def cmd_patch(args: argparse.Namespace) -> int:
    """Execute the patch command."""
    from batho.orchestrator.patch import PatchOptions, run_patch
    from batho.context.incremental import PatchMode

    options = PatchOptions(
        root=args.root,
        verbose=args.verbose,
        max_file_size_kb=args.max_file_size_kb,
        mode=PatchMode(args.mode),
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
    return 0
