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
        help="Full index build for a repository (creates Arrow Bundle in .batho/artifact/)",
        description=(
            "Build a complete code graph, BSG map, and baseline snapshot for a "
            "repository. If the artifact bundle already exists, exits with guidance to use "
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
    parser.add_argument(
        "--graph-backend",
        type=str,
        choices=["auto", "in-memory", "arrow"],
        default=None,
        help=(
            "Graph storage backend: 'auto' (default, threshold-based), "
            "'in-memory', or 'arrow' (columnar, memory-mapped). "
            "Overrides graph.backend.backend in batho.yaml."
        ),
    )
    parser.add_argument(
        "--no-progress",
        action="store_true",
        default=False,
        help="Disable progress bars (also: BATHO_NO_PROGRESS=1)",
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
        graph_backend=args.graph_backend,
        no_progress=args.no_progress,
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
    from batho.utils.cli_output import CLIOutput

    cli_out = CLIOutput()
    cli_out.success(
        f"✓ built in {result.duration_ms / 1000:.1f}s — "
        f"{result.file_count} files · "
        f"{result.entity_count} entities · "
        f"{result.relationship_count} relationships"
    )
    return 0
