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
    parser.add_argument(
        "--no-watch",
        action="store_true",
        default=False,
        help="Do not start the watcher engine.",
    )
    parser.add_argument(
        "--enable-tool",
        action="append",
        default=[],
        metavar="TOOL_NAME",
        help=(
            "Enable a tool that is disabled by default (repeatable). "
            "Example: --enable-tool batho_build. "
            "Overrides the mcp.tools.disabled list from batho.yaml."
        ),
    )
    parser.set_defaults(func=cmd_mcp)


def cmd_mcp(args: argparse.Namespace) -> int:
    """Execute the mcp command — starts the MCP server."""
    import os
    from pathlib import Path

    from batho.core.config import get_config_with_root
    from batho.mcp.server import run_server

    root = args.root or os.getcwd()
    root_resolved = str(Path(root).resolve())

    # Compute the effective disabled set: start from config, then remove
    # any tools the user explicitly enabled via --enable-tool.
    cfg = get_config_with_root(Path(root_resolved))
    mcp_cfg = cfg.get("mcp", {})
    disabled = set(mcp_cfg.get("tools", {}).get("disabled", []))
    disabled -= set(args.enable_tool)

    run_server(root=root_resolved, watch=not args.no_watch, disabled_tools=disabled)
    return 0

