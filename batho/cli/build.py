"""CLI subcommand: batho build

Thin argparse wrapper around batho.orchestrator.build.run_build().
"""

from __future__ import annotations

import argparse
import sys

from batho.cli._utils import create_base_parser


def register_build_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the `build` subcommand on the given subparsers action."""
    parser = subparsers.add_parser(
        "build",
        parents=[create_base_parser()],
        help="Full index build for a repository (creates artifact_<dirname>.batho database)",
        description=(
            "Build a complete code graph, BSG map, and baseline snapshot for a "
            "repository. If the artifact database already exists, exits with guidance to use "
            "`batho patch` for incremental updates."
        ),
    )
    parser.add_argument(
        "--full",
        action="store_true",
        default=False,
        help="Force full rebuild (deletes existing database and rebuilds from scratch)",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=None,
        help="Max parallel workers for parsing (default: CPU count)",
    )
    parser.add_argument(
        "--max-file-size-kb",
        type=int,
        default=None,
        help="Skip files exceeding this size in kilobytes",
    )
    parser.set_defaults(func=cmd_build)


def cmd_build(args: argparse.Namespace) -> int:
    """Execute the build command."""
    from batho.orchestrator.build import BuildOptions, run_build

    options = BuildOptions(
        root=args.root,
        force_full=args.full,
        verbose=args.verbose,
        max_workers=args.max_workers,
        max_file_size_kb=args.max_file_size_kb,
    )

    result = run_build(options)

    # Handle "already built" case
    if result.warnings and "already_built" in result.warnings:
        # Print the user-facing message (second warning entry)
        for w in result.warnings:
            if w != "already_built":
                print(w)
        return 0

    if not result.success:
        for w in result.warnings:
            print(f"error: {w}", file=sys.stderr)
        return 1

    # Success summary
    print(
        f"Built {args.root.resolve()}: "
        f"{result.entity_count} entities, "
        f"{result.relationship_count} relationships, "
        f"{result.file_count} files "
        f"in {result.duration_ms}ms"
    )
    return 0
