"""CLI argument parsing for batho fix command."""

from __future__ import annotations

import argparse
from pathlib import Path

from batho.cli._utils import create_base_parser


def register_fix_parser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    """Register the `fix` subcommand."""
    parser = subparsers.add_parser(
        "fix",
        parents=[create_base_parser()],
        help="Verify and repair artifact database integrity",
        description=(
            "Comprehensive integrity check and automatic repair for the Batho artifact database. "
            "Detects corruption, validates data structures, and repairs issues where possible. "
        ),
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Check only, do not perform any repairs",
    )

    parser.add_argument(
        "--deep",
        action="store_true",
        help="Decompress and validate every blob (slow)",
    )

    parser.add_argument(
        "--target",
        choices=["db", "state", "blobs", "graph", "all"],
        default="all",
        help="Target checker (default: all)",
    )

    parser.add_argument(
        "--phase",
        type=int,
        choices=[1, 2, 3, 4],
        help="Run specific phase (1-4)",
    )

    parser.add_argument(
        "--parallel",
        action="store_true",
        help="Run independent checks in parallel",
    )


    parser.add_argument(
        "--format",
        choices=["text", "json", "csv"],
        default="text",
        help="Report output format (default: text)",
    )

    parser.add_argument(
        "--output",
        type=Path,
        help="Write report to file instead of stdout",
    )

    return parser
