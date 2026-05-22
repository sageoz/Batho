"""CLI command helpers for ``batho dashboard`` subcommand.

Mirrors the structure of ``batho.bsg.plugins_cli``: a registration
helper (:func:`register_cli_subcommands`) plus one ``cmd_*`` handler.
"""

from __future__ import annotations

import argparse
import http.server
import json
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
        """Translate URL to filesystem path using dual-root logic.
        Strips query parameters so cache-busting strings like ?v=2 work."""
        parsed = urllib.parse.urlparse(path)
        clean_path = parsed.path
        if clean_path.startswith("/dashboard/"):
            rel_path = clean_path[len("/dashboard/"):]
            return str(self._dashboard_dir / rel_path)
        elif clean_path.startswith("/.ctn/"):
            rel_path = clean_path[len("/.ctn/"):]
            return str(self._ctn_dir / rel_path)
        elif clean_path == "/dashboard" or clean_path == "/dashboard/":
            return str(self._dashboard_dir / "index.html")
        elif clean_path == "/" or clean_path == "":
            return str(self._dashboard_dir / "index.html")
        else:
            return str(self._dashboard_dir / "index.html")

    def end_headers(self):
        """Add cache-control for dashboard assets to prevent stale caches."""
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path.startswith("/dashboard/") or parsed.path.startswith("/.ctn/"):
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
        super().end_headers()

    def _handle_file_reconstruction(self, query: dict[str, list[str]]) -> None:
        """Handle GET /api/v1/bridge/file-reconstruction for the dashboard."""
        import json
        from pathlib import Path

        path_param = query.get("path", [""])[0]
        index_id = query.get("index_id", [""])[0]

        if not path_param or not index_id:
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": False, "error": {"message": "path and index_id required"}}).encode())
            return

        # Try storage view first (has raw_content), fall back to agent view
        bsg_path = self._ctn_dir / index_id / "bsg_storage_view.json"
        if not bsg_path.exists():
            LOGGER.info("Storage view not found, falling back to agent view", bsg_path=str(bsg_path))
            bsg_path = self._ctn_dir / index_id / "bsg.json"
        else:
            LOGGER.info("Using storage view", bsg_path=str(bsg_path))
        
        if not bsg_path.exists():
            self.send_response(404)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": False, "error": {"message": f"BSG not found: {bsg_path}"}}).encode())
            return

        try:
            bsg_data = json.loads(bsg_path.read_text(encoding="utf-8"))
            
            # Handle both storage view (file-based) and regular BSG (flat nodes) structures
            if "files" in bsg_data:
                # Storage view structure: { "files": [{ "file_path": "...", "entities": [...] }] }
                bsg_root = bsg_data.get("root", str(self._ctn_dir.parent))  # Default to project root
                relative_path = path_param
                if bsg_root and path_param.startswith(bsg_root):
                    relative_path = path_param[len(bsg_root):].lstrip("/")
                
                LOGGER.info("Path conversion", bsg_root=bsg_root, path_param=path_param, relative_path=relative_path)
                
                file_entities = []
                file_found = False
                for file_entry in bsg_data.get("files", []):
                    # Storage view uses relative paths in file_path field
                    entry_path = file_entry.get("file_path", "")
                    LOGGER.debug("Checking file entry", entry_path=entry_path, relative_path=relative_path, path_param=path_param, match=(entry_path == relative_path or entry_path == path_param))
                    if entry_path == relative_path or entry_path == path_param:
                        file_entities = file_entry.get("entities", [])
                        file_found = True
                        LOGGER.info("Found file in storage view", entry_path=entry_path, entity_count=len(file_entities))
                        break
                
                if not file_found:
                    LOGGER.warning("File not found in storage view", relative_path=relative_path, path_param=path_param, total_files=len(bsg_data.get("files", [])))
            else:
                # Regular BSG structure: { "nodes": [...] }
                nodes = bsg_data.get("nodes", bsg_data.get("entities", []))
                
                # BSG uses relative paths from the root, convert absolute path to relative
                bsg_root = bsg_data.get("root", "")
                relative_path = path_param
                if bsg_root and path_param.startswith(bsg_root):
                    relative_path = path_param[len(bsg_root):].lstrip("/")
                
                # Filter by path (try both relative and absolute)
                file_entities = [n for n in nodes if n.get("file") == relative_path or n.get("file") == path_param]
            if not file_entities:
                self.send_response(404)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"ok": False, "error": {"message": f"File not found in BSG: {path_param}"}}).encode())
                return

            # Sort by start_byte
            file_entities.sort(key=lambda x: x.get("start_byte", x.get("startByte", 0)))
            
            reconstructed_content = ""
            try:
                from batho.context.reconstructor import FileReconstructor
                from batho.context.schema import Entity
                reconstructor = FileReconstructor()
                
                # Convert JSON dicts to Entity objects
                entity_objects = [Entity.from_dict(e) for e in file_entities]
                result = reconstructor.reconstruct_file(file_path=path_param, entities=entity_objects)
                reconstructed_content = result.reconstructed_content
            except Exception as e:
                LOGGER.warning("FileReconstructor failed, falling back to simple concatenation", error=str(e))
                # Fallback to simple concatenation
                parts = []
                for e in file_entities:
                    if "raw_content" in e:
                        parts.append(e["raw_content"])
                    elif "raw_bytes" in e:
                        try:
                            raw_bytes_val = e["raw_bytes"]
                            if isinstance(raw_bytes_val, str) and raw_bytes_val:
                                parts.append(bytes.fromhex(raw_bytes_val).decode("utf-8"))
                            elif isinstance(raw_bytes_val, bytes):
                                parts.append(raw_bytes_val.decode("utf-8"))
                        except Exception:
                            pass
                reconstructed_content = "".join(parts)

            # Build response
            syntax_glue_count = sum(1 for e in file_entities if e.get("type", "").upper() == "SYNTAX_GLUE")
            response_data = {
                "ok": True,
                "data": {
                    "content": reconstructed_content,
                    "entities": file_entities,
                    "metadata": {
                        "entityCount": len(file_entities),
                        "hasSyntaxGlue": syntax_glue_count > 0,
                        "syntaxGlueCount": syntax_glue_count
                    }
                }
            }
            
            body = json.dumps(response_data).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)

        except Exception as exc:
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": False, "error": {"message": str(exc)}}).encode())


    def do_GET(self):
        """Handle GET requests."""
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path.startswith("/api/v1/"):
            query = urllib.parse.parse_qs(parsed.query)
            
            if parsed.path == "/api/v1/bridge/file-reconstruction":
                return self._handle_file_reconstruction(query)

            body, status, headers = self._get_bridge_api().dispatch(parsed.path, query)
            self.send_response(status)
            for key, value in headers.items():
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        clean_path = parsed.path
        if clean_path not in ["/", "/dashboard", "/dashboard/"] and \
           not clean_path.startswith("/dashboard/") and \
           not clean_path.startswith("/.ctn/"):
            self.send_error(404, "Not Found")
            return
        super().do_GET()

    def do_OPTIONS(self):
        """Handle OPTIONS requests for CORS preflight."""
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path.startswith("/api/v1/"):
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()
            return
        self.send_error(405, "Method Not Allowed")

    def do_POST(self):
        """Handle POST requests for API endpoints."""
        parsed = urllib.parse.urlparse(self.path)
        
        if parsed.path.startswith("/api/v1/workspaces"):
            try:
                content_length = int(self.headers.get('Content-Length', 0))
                post_data = self.rfile.read(content_length)
                body = json.loads(post_data.decode('utf-8')) if content_length > 0 else {}
            except (json.JSONDecodeError, UnicodeDecodeError):
                body = {}
            
            query = urllib.parse.parse_qs(parsed.query)
            body_response, status, headers = self._get_bridge_api().dispatch_post(parsed.path, query, body)
            
            self.send_response(status)
            self.send_header("Access-Control-Allow-Origin", "*")
            for key, value in headers.items():
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(body_response)))
            self.end_headers()
            self.wfile.write(body_response)
            return
        
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
    if getattr(args, "hub", False):
        print("Redirecting to `batho mcp serve --open-browser`...")
        from batho.cli.mcp import cmd_mcp_serve
        args.open_browser = True
        args.no_ui = False
        args.no_rest = False
        args.transport = "sse"  # Default for hub UI
        args.config = None
        return cmd_mcp_serve(args)

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
    dashboard_parser.add_argument(
        "--hub",
        action="store_true",
        help="Launch full Hub UI (multi-workspace) instead of single-workspace",
    )
    dashboard_parser.set_defaults(func=cmd_dashboard)


__all__ = [
    "cmd_dashboard",
    "register_cli_subcommands",
]
