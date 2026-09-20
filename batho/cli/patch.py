"""CLI subcommand: batho patch

Thin argparse wrapper around batho.orchestrator.patch.run_patch().
"""

from __future__ import annotations

import argparse
import sys

from batho.cli._utils import create_base_parser


def register_patch_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the `patch` subcommand on the given subparsers action."""
    parser = subparsers.add_parser(
        "patch",
        parents=[create_base_parser()],
        help="Incremental patch of an existing artifact database",
        description=(
            "Detects changes natively using content hashing against the Arrow Bundle "
            "file_tracking table. Unlike previous versions, this does not use Git "
            "status for change detection, eliminating false positives from "
            "uncommitted files."
        ),
    )
    parser.add_argument(
        "--max-file-size-kb",
        type=int,
        default=None,
        help="Skip files exceeding this size in kilobytes during hash scan",
    )
    parser.add_argument(
        "--graph-backend",
        type=str,
        choices=["auto", "in-memory", "arrow"],
        default=None,
        help=(
            "Accepted for API symmetry with `build`. Patch always uses the "
            "in-memory graph backend internally; a warning is logged if a "
            "non-default backend is requested."
        ),
    )

    parser.add_argument(
        "--no-progress",
        action="store_true",
        default=False,
        help="Disable progress bars (also: BATHO_NO_PROGRESS=1)",
    )

    parser.set_defaults(func=cmd_patch)


def cmd_patch(args: argparse.Namespace) -> int:
    """Execute the patch command."""
    from batho.orchestrator.patch import PatchOptions, run_patch

    options = PatchOptions(
        root=args.root,
        verbose=args.verbose,
        max_file_size_kb=args.max_file_size_kb,
        graph_backend=args.graph_backend,
        no_progress=args.no_progress,
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
    from batho.utils.cli_output import CLIOutput

    cli_out = CLIOutput()
    cli_out.success(
        f"✓ patched in {result.duration_ms / 1000:.1f}s — "
        f"{result.changes_applied} changes "
        f"({result.added} added, {result.modified} modified, {result.deleted} deleted)"
    )
    if (
        result.nodes_added
        or result.nodes_removed
        or result.nodes_modified
        or result.nodes_renamed
    ):
        cli_out.info(
            f"  Nodes: {result.nodes_added} added, "
            f"{result.nodes_removed} removed, "
            f"{result.nodes_modified} modified, "
            f"{result.nodes_renamed} renamed"
        )
    return 0
