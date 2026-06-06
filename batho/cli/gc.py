"""CLI subcommand: batho gc

Argparse wrapper around batho.orchestrator.gc.run_gc().
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from batho.cli._utils import create_base_parser


def register_gc_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the `gc` subcommand on the given subparsers action."""
    gc_parser = subparsers.add_parser(
        "gc",
        parents=[create_base_parser()],
        help="Garbage collection and database maintenance commands",
        description="Clean up old runs and orphaned Arrow IPC generations.",
    )
    
    gc_subparsers = gc_parser.add_subparsers(dest="gc_command", required=True)

    # gc run
    run_parser = gc_subparsers.add_parser(
        "run", 
        help="Delete specific run and all artifacts"
    )
    run_parser.add_argument(
        "run_uuid", 
        type=str, 
        help="UUID of the run to delete"
    )

    # gc runs
    runs_parser = gc_subparsers.add_parser(
        "runs", 
        help="Delete runs older than N days"
    )
    runs_parser.add_argument(
        "--older-than", 
        type=int, 
        required=True, 
        help="Delete runs older than N days"
    )

    # gc vacuum
    gc_subparsers.add_parser(
        "vacuum",
        help="Sweep orphaned Arrow IPC generations"
    )

    # gc orphans
    gc_subparsers.add_parser(
        "orphans",
        help="Remove stale IPC files not referenced by active generation"
    )

    # gc status
    gc_subparsers.add_parser(
        "status",
        help="Show storage stats (bundle size, generation, run count)"
    )

    gc_parser.set_defaults(func=cmd_gc)


def cmd_gc(args: argparse.Namespace) -> int:
    """Execute the gc command."""
    from batho.orchestrator.gc import GCOptions, run_gc

    options = GCOptions(
        root=args.root,
        command=args.gc_command,
        run_uuid=getattr(args, "run_uuid", None),
        older_than=getattr(args, "older_than", None),
        verbose=args.verbose,
    )

    result = run_gc(options)

    if not result["success"]:
        print(f"error: {result['message']}", file=sys.stderr)
        return 1

    print(result["message"])
    return 0
