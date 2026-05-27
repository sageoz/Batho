"""Shared CLI utilities for batho CLI commands."""

from __future__ import annotations

import argparse
from pathlib import Path


def create_base_parser() -> argparse.ArgumentParser:
    """Create base parser with common arguments shared across all commands.

    Returns an ArgumentParser with --root and --verbose arguments.
    Use as parents=[create_base_parser()] when creating subcommand parsers.
    """
    parser = argparse.ArgumentParser(add_help=False)
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
    return parser


