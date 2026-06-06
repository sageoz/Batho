"""CLI subcommand: batho load

Unpack a transport artifact ZIP (.batho) into .batho/artifact/.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from batho.cli._utils import create_base_parser


def register_load_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the `load` subcommand."""
    parser = subparsers.add_parser(
        "load",
        parents=[create_base_parser()],
        help="Unpack a transport artifact_<dir>.batho ZIP into .batho/artifact/",
        description=(
            "Unpacks a zstd-compressed Arrow Bundle ZIP produced by `batho export --pack` "
            "into the repository's .batho/artifact/ directory."
        ),
    )
    parser.add_argument(
        "artifact",
        type=Path,
        help="Path to the artifact_<dir>.batho ZIP file",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Overwrite existing bundle if present",
    )
    parser.set_defaults(func=cmd_load)


def cmd_load(args: argparse.Namespace) -> int:
    """Execute the load command."""
    from batho.orchestrator.load import LoadOptions, run_load

    options = LoadOptions(
        root=args.root,
        artifact_path=args.artifact,
        force=args.force,
    )

    result = run_load(options)

    if not result.success:
        print(f"error: {result.message}", file=sys.stderr)
        return 1

    print(result.message)
    return 0
