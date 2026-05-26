"""CLI command helpers for ``batho dashboard`` subcommand.

Uses the new dashboard_core for serving the UI and proxying to bridge.

This replaces the legacy DualRootHandler with a clean separation:
- dashboard_core: Static assets + API proxy
- bridge_core: Business logic and graph queries
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from batho.dashboard_core import serve_dashboard
from batho.utils.logging import get_logger
from batho.cli._utils import find_workspace_with_db

LOGGER = get_logger(__name__, component="cli.dashboard")

DEFAULT_PORT = 8766
DEFAULT_BRIDGE_PORT = 8765
DEFAULT_HOST = "127.0.0.1"


def cmd_dashboard(args: argparse.Namespace) -> int:
    """Launch the Batho dashboard server.
    
    Uses dashboard_core which provides:
    - Static asset serving
    - Transparent API proxy to bridge_core
    
    Args:
        args: Parsed CLI arguments
        
    Returns:
        Exit code (0 for success)
    """
    # Print ANSI startup banner
    print("\033[1;36m⟁ Initializing Batho Core Web App...\033[0m")
    print("\033[2mOptimized for zero-build, low-latency telemetry.\033[0m")

    root_arg = getattr(args, "root", None) or "."
    root_path = Path(root_arg).resolve()
    
    # Find workspace with artifact database
    workspace_path = find_workspace_with_db(root_path)
    
    if workspace_path is None:
        from batho.storage.engine import artifact_filename
        expected_db = artifact_filename(root_path)
        print(f"\033[91merror: No artifact database found at {root_path}\033[0m")
        print(f"Expected: {expected_db} or .batho/{expected_db}")
        print("Run 'batho build' from the repo root to create one")
        return 1
    
    # Use found workspace path
    root_path = workspace_path
    
    port = getattr(args, "port", None) or DEFAULT_PORT
    host = getattr(args, "host", None) or DEFAULT_HOST
    bridge_port = getattr(args, "bridge_port", None) or DEFAULT_BRIDGE_PORT
    
    if host == "0.0.0.0":
        print("\033[93mwarning: Binding to 0.0.0.0 exposes server to network\033[0m")
    
    no_browser = getattr(args, "no_browser", False)
    
    LOGGER.info(
        "dashboard_starting",
        root=str(root_path),
        dashboard_port=port,
        bridge_port=bridge_port,
    )
    
    try:
        serve_dashboard(
            repo_root=root_path,
            port=port,
            bridge_port=bridge_port,
            host=host,
            open_browser=not no_browser,
            no_browser=no_browser,
        )
        return 0
    except FileNotFoundError as e:
        print(f"\033[91merror: {e}\033[0m")
        return 1
    except RuntimeError as e:
        print(f"\033[91merror: {e}\033[0m")
        return 2
    except KeyboardInterrupt:
        print("\nDashboard server stopped")
        return 0
    except Exception as e:
        LOGGER.error("dashboard_error", error=str(e))
        print(f"\033[91merror: {e}\033[0m")
        return 3


def register_cli_subcommands(dashboard_sub: argparse._SubParsersAction[Any]) -> None:
    """Attach ``dashboard`` parser to an existing subparser group."""
    dashboard_parser = dashboard_sub.add_parser(
        "dashboard",
        help="Launch the Batho Dashboard web interface",
    )
    
    dashboard_parser.add_argument(
        "--root", "-r",
        default=".",
        help="Path to repository root (walks up to find .batho)",
    )
    dashboard_parser.add_argument(
        "--port", "-p",
        type=int,
        default=DEFAULT_PORT,
        help=f"Dashboard port (default: {DEFAULT_PORT})",
    )
    dashboard_parser.add_argument(
        "--bridge-port",
        type=int,
        default=DEFAULT_BRIDGE_PORT,
        help=f"Bridge server port (default: {DEFAULT_BRIDGE_PORT})",
    )
    dashboard_parser.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help=f"Bind address (default: {DEFAULT_HOST})",
    )
    dashboard_parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Skip opening the browser automatically",
    )
    dashboard_parser.add_argument(
        "--open-route",
        default="#/overview",
        help="Hash route to open after server starts",
    )
    
    dashboard_parser.set_defaults(func=cmd_dashboard)


__all__ = [
    "cmd_dashboard",
    "register_cli_subcommands",
]
