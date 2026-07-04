"""Batho CLI entry point."""

from __future__ import annotations

import argparse
import sys

from batho import __version__
from batho.core.config.loader import get_config_cached
from batho.utils.logging import configure_logging_from_dict


def _build_parser() -> argparse.ArgumentParser:
    """Construct the top-level argument parser with all subcommands."""
    parser = argparse.ArgumentParser(
        prog="batho",
        description="Batho — deterministic code intelligence engine",
    )
    parser.add_argument(
        "--version", action="version", version=f"batho {__version__}"
    )
    subparsers = parser.add_subparsers(dest="command")

    # Register subcommands
    from batho.cli.build import register_build_parser
    from batho.cli.patch import register_patch_parser
    from batho.cli.fix import register_fix_parser
    from batho.cli.export import register_export_parser
    from batho.cli.diff import register_diff_parser
    from batho.cli.gc import register_gc_parser
    from batho.cli.load import register_load_parser
    from batho.cli.mcp import register_mcp_parser

    register_build_parser(subparsers)
    register_patch_parser(subparsers)
    register_export_parser(subparsers)
    register_fix_parser(subparsers)
    register_diff_parser(subparsers)
    register_gc_parser(subparsers)
    register_load_parser(subparsers)
    register_mcp_parser(subparsers)

    return parser


def main() -> None:
    """CLI main entry point."""
    import gc
    gc.set_threshold(50000, 50, 50)
    configure_logging_from_dict(get_config_cached()["logging"])
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
