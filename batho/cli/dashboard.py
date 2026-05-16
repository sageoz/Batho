"""CLI command helpers for ``batho dashboard`` subcommand.

Mirrors the structure of ``batho.bsg.plugins_cli``: a registration
helper (:func:`register_cli_subcommands`) plus one ``cmd_*`` handler.
"""

from __future__ import annotations

import argparse
import http.server
import os
import socket
import sys
import threading
import urllib.parse
import webbrowser
from importlib.resources import files as _pkg_files
from pathlib import Path
from typing import Any

import structlog

LOGGER = structlog.get_logger(__name__)

DEFAULT_PORT = 8765
DEFAULT_HOST = "127.0.0.1"
MAX_PORT_RETRIES = 10


def _find_ctn_dir(start_path: Path) -> Path | None:
    """Walk up from start_path to find the nearest ancestor with .ctn/."""
    current = start_path.resolve()
    while True:
        ctn_path = current / ".ctn"
        if ctn_path.is_dir():
            return ctn_path
        parent = current.parent
        if parent == current:
            break
        current = parent
    return None


def _find_workspace_root(ctn_path: Path) -> Path:
    """Return the workspace root (parent of .ctn/)."""
    return ctn_path.parent


def _find_dashboard_assets() -> Path | None:
    """Find the dashboard/ assets directory.

    Resolution order:
    1. ``BATHO_DASHBOARD_DIR`` environment variable (explicit override).
    2. The dev checkout living next to this file (``<repo>/batho/dashboard``).
       This lets contributors iterate without reinstalling the package.
    3. The packaged copy inside the installed ``batho`` distribution.
    """
    override = os.environ.get("BATHO_DASHBOARD_DIR")
    if override:
        candidate = Path(override).expanduser()
        if candidate.is_dir():
            return candidate

    # __file__ -> .../batho/cli/dashboard.py; dev dashboard sits at
    # .../batho/dashboard relative to the package root.
    here = Path(__file__).resolve()
    dev_candidate = here.parent.parent / "dashboard"
    if dev_candidate.is_dir() and (dev_candidate / "index.html").is_file():
        return dev_candidate

    try:
        packaged = Path(str(_pkg_files("batho").joinpath("dashboard")))
        if packaged.is_dir():
            return packaged
    except Exception:
        pass
    return None


def _is_port_available(host: str, port: int) -> bool:
    """Check if a port is available for binding."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(1)
            sock.bind((host, port))
            return True
    except OSError:
        return False


def _find_available_port(host: str, start_port: int) -> int | None:
    """Find an available port starting from start_port."""
    for offset in range(MAX_PORT_RETRIES):
        port = start_port + offset
        if _is_port_available(host, port):
            return port
    return None


class DualRootHandler(http.server.SimpleHTTPRequestHandler):
    """HTTP handler that serves from two root directories."""

    def __init__(self, *args, dashboard_dir: Path, ctn_dir: Path, **kwargs):
        self._dashboard_dir = dashboard_dir
        self._ctn_dir = ctn_dir
        self._bridge_api = None
        super().__init__(*args, **kwargs)

    def _get_bridge_api(self):
        from batho.bridge.http_api import BridgeAPIHandler
        if self._bridge_api is None:
            self._bridge_api = BridgeAPIHandler(self._ctn_dir)
        return self._bridge_api

    def translate_path(self, path: str) -> str:
        """Translate URL to filesystem path using dual-root logic."""
        if path.startswith("/dashboard/"):
            rel_path = path[len("/dashboard/"):]
            return str(self._dashboard_dir / rel_path)
        elif path.startswith("/.ctn/"):
            rel_path = path[len("/.ctn/"):]
            return str(self._ctn_dir / rel_path)
        elif path == "/dashboard" or path == "/dashboard/":
            return str(self._dashboard_dir / "index.html")
        elif path == "/" or path == "":
            return str(self._dashboard_dir / "index.html")
        else:
            return str(self._dashboard_dir / "index.html")

    def do_GET(self):
        """Handle GET requests."""
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path.startswith("/api/v1/bridge/"):
            query = urllib.parse.parse_qs(parsed.query)
            body, status, headers = self._get_bridge_api().dispatch(parsed.path, query)
            self.send_response(status)
            for key, value in headers.items():
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path not in ["/", "/dashboard", "/dashboard/"] and \
           not self.path.startswith("/dashboard/") and \
           not self.path.startswith("/.ctn/"):
            self.send_error(404, "Not Found")
            return
        super().do_GET()

    def do_OPTIONS(self):
        """Handle OPTIONS requests for CORS preflight."""
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path.startswith("/api/v1/bridge/"):
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()
            return
        self.send_error(405, "Method Not Allowed")

    def do_POST(self):
        """Reject POST requests."""
        self.send_error(405, "Method Not Allowed")

    def do_PUT(self):
        """Reject PUT requests."""
        self.send_error(405, "Method Not Allowed")

    def do_DELETE(self):
        """Reject DELETE requests."""
        self.send_error(405, "Method Not Allowed")

    def log_message(self, format, *args):
        """Log requests via structlog."""
        status = args[1] if len(args) > 1 else "-"
        LOGGER.info("dashboard_server", method=self.command, path=self.path, status=status)


def cmd_dashboard(args: argparse.Namespace) -> int:
    """Launch the Batho dashboard server."""
    root_arg = getattr(args, "root", None) or "."
    root_path = Path(root_arg).resolve()

    ctn_path = _find_ctn_dir(root_path)
    if not ctn_path:
        print(f"error: No .ctn/ directory found walking up from {root_path}")
        print("Run `batho index` from the repo root to populate .ctn/")
        return 1

    workspace_root = _find_workspace_root(ctn_path)
    dashboard_dir = _find_dashboard_assets()

    if not dashboard_dir or not dashboard_dir.exists():
        print("error: Dashboard assets not found in installation")
        print("Ensure batho is properly installed with dashboard assets")
        return 2

    port = getattr(args, "port", None) or DEFAULT_PORT
    host = getattr(args, "host", None) or DEFAULT_HOST

    if host == "0.0.0.0":
        print("warning: Binding to 0.0.0.0 exposes server to network")

    available_port = _find_available_port(host, port)
    if not available_port:
        print(f"error: Could not find available port in range [{port}, {port + MAX_PORT_RETRIES})")
        return 3

    open_browser = not getattr(args, "no_browser", False)
    open_route = getattr(args, "open_route", None) or "#/overview"

    handler = lambda *a, **kw: DualRootHandler(
        *a, dashboard_dir=dashboard_dir, ctn_dir=ctn_path, **kw
    )

    server = http.server.ThreadingHTTPServer((host, available_port), handler)

    print(f"🚀 Batho Dashboard")
    print(f"   Workspace: {workspace_root}")
    print(f"   CTN:       {ctn_path}")
    print(f"   URL:       http://{host}:{available_port}/")
    print(f"   Route:     {open_route}")
    print()
    print("Press Ctrl+C to stop")

    if open_browser:
        url = f"http://{host}:{available_port}/{open_route}"
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()
        return 0

    return 0


def register_cli_subcommands(dashboard_sub: argparse._SubParsersAction[Any]) -> None:
    """Attach ``dashboard`` parser to an existing subparser group."""

    dashboard_parser = dashboard_sub.add_parser(
        "dashboard",
        help="Launch the Batho Dashboard web interface",
    )
    dashboard_parser.add_argument(
        "--root",
        default=".",
        help="Path to repository root (walks up to find .ctn/)",
    )
    dashboard_parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"TCP port to bind (default: {DEFAULT_PORT})",
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
