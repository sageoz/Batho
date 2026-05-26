"""MCP server CLI command — Oracle Gateway.

Provides the stdio MCP server for AI agent integration.

This uses bridge_core instead of the deprecated legacy bridge.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from batho.bridge_core.transport.mcp import run_mcp_stdio
from batho.utils.logging import get_logger
from batho.cli._utils import find_workspace_with_db

LOGGER = get_logger(__name__, component="cli.mcp")


def cmd_mcp_serve(args: argparse.Namespace) -> int:
    """Run Batho MCP server over stdio.
    
    This is the standard entry point for MCP IDE integration.
    
    Args:
        args: Parsed CLI arguments
        
    Returns:
        Exit code (0 for success)
    """
    root = Path(args.root).resolve() if args.root else Path.cwd()
    
    # Find workspace with artifact database
    workspace = find_workspace_with_db(root)
    if workspace is None:
        from batho.storage.engine import artifact_filename
        expected_db = artifact_filename(root)
        print(f"error: No artifact database found at {root}")
        print(f"Expected: {expected_db} or .batho/{expected_db}")
        print("Run 'batho build' first to create artifacts")
        return 1
    
    root = workspace
    
    LOGGER.info("mcp_serve_starting", root=str(root))
    
    try:
        run_mcp_stdio(repo_root=root)
        return 0
    except FileNotFoundError as e:
        print(f"error: {e}")
        return 1
    except ValueError as e:
        print(f"error: {e}")
        return 1
    except KeyboardInterrupt:
        print("\nMCP server stopped")
        return 0
    except Exception as e:
        LOGGER.error("mcp_serve_error", error=str(e))
        print(f"error: {e}")
        return 2


def register_cli_subcommands(mcp_sub: argparse._SubParsersAction[Any]) -> None:
    """Attach ``mcp`` parser to an existing subparser group."""
    mcp_parser = mcp_sub.add_parser(
        "mcp",
        help="Run Batho MCP server for AI agent integration",
    )
    
    mcp_parser.add_argument(
        "--root", "-r",
        default=".",
        help="Path to repository root (walks up to find .batho)",
    )
    
    mcp_parser.set_defaults(func=cmd_mcp_serve)


__all__ = ["cmd_mcp_serve", "register_cli_subcommands"]
