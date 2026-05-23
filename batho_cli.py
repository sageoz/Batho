"""Batho CLI entry point."""

from __future__ import annotations

import argparse
import sys


def _build_parser() -> argparse.ArgumentParser:
    """Construct the top-level argument parser with all subcommands."""
    parser = argparse.ArgumentParser(
        prog="batho",
        description="Batho — deterministic code intelligence engine",
    )
    subparsers = parser.add_subparsers(dest="command")

    # Register subcommands
    from batho.cli.build import register_build_parser

    register_build_parser(subparsers)

    # Future: register_patch_parser, register_doctor_parser, etc.

    return parser


def main() -> None:
    """CLI main entry point."""
    parser = _build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    if hasattr(args, "func"):
        exit_code = args.func(args)
        sys.exit(exit_code or 0)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
