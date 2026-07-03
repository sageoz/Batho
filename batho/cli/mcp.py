"""CLI subcommand: batho mcp

Thin argparse wrapper that starts the Batho MCP server.
"""

from __future__ import annotations

import argparse
import sys


def register_mcp_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the `mcp` subcommand on the given subparsers action."""
    parser = subparsers.add_parser(
        "mcp",
        help="Start the Batho MCP server (stdio transport)",
        description=(
            "Start the Batho MCP server on stdio. AI agents connect via "
            "Model Context Protocol to query the code graph. Requires a "
            "pre-built .batho artifact (run `batho build` first)."
        ),
    )
    parser.add_argument(
        "--root",
        default=None,
        help="Repository root containing .batho artifact. Defaults to current working directory.",
    )
    parser.set_defaults(func=cmd_mcp)


def cmd_mcp(args: argparse.Namespace) -> int:
    """Execute the mcp command — starts the MCP server."""
    import os

    from batho.mcp.server import run_server

    root = args.root or os.getcwd()
    run_server(root=root)
    return 0
