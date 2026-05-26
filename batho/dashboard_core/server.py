"""Dashboard Server — Main HTTP server for dashboard UI.

Combines static asset serving with transparent API proxying to bridge_core.
"""

from __future__ import annotations

import socket
import threading
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Any
import urllib.parse

from batho.dashboard_core.assets import find_dashboard_assets, serve_asset, NO_CACHE_HEADERS
from batho.dashboard_core.proxy import BridgeProxy, proxy_api_request
from batho.utils.logging import get_logger

LOGGER = get_logger(__name__, component="dashboard_core.server")

DEFAULT_DASHBOARD_PORT = 8766
DEFAULT_BRIDGE_PORT = 8765


def is_port_available(host: str, port: int) -> bool:
    """Check if a port is available for binding."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.settimeout(1)
            sock.bind((host, port))
            return True
    except OSError:
        return False


def find_available_port(host: str, start_port: int, max_attempts: int = 10) -> int | None:
    """Find an available port starting from start_port."""
    for offset in range(max_attempts):
        port = start_port + offset
        if is_port_available(host, port):
            return port
    return None


class DashboardHTTPHandler(BaseHTTPRequestHandler):
    """HTTP handler for dashboard server.
    
    Routes:
        /             -> index.html
        /dashboard/*  -> Static assets (if path structure preserved)
        /.batho/*     -> .batho directory files
        /api/*        -> Proxy to bridge
        /healthz      -> Dashboard health check
    """
    
    # Set at server initialization
    assets_dir: Path | None = None
    workspace_dir: Path | None = None
    proxy: BridgeProxy | None = None
    
    def log_message(self, format: str, *args) -> None:
        """Override to use structlog."""
        LOGGER.info(
            "dashboard_request",
            method=self.command,
            path=self.path,
            status=args[1] if len(args) > 1 else "-",
        )
    
    def end_headers(self) -> None:
        """Add cache control headers."""
        parsed = urllib.parse.urlparse(self.path)
        
        # No cache for API and dynamic content
        if parsed.path.startswith("/api/") or parsed.path.startswith("/.batho/"):
            for key, value in NO_CACHE_HEADERS.items():
                self.send_header(key, value)
        
        super().end_headers()
    
    def do_GET(self) -> None:
        """Handle GET requests."""
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)
        query_params = {k: v[0] if len(v) == 1 else v for k, v in query.items()}
        
        # API proxy
        if path.startswith("/api/"):
            if self.proxy is None:
                self._send_error(503, "Bridge proxy not configured")
                return
            
            proxy_api_request(
                self,
                self.proxy,
                "GET",
                path,
                query_params=query_params
            )
            return
        
        # Health check
        if path in ("/healthz", "/readyz"):
            self._send_json_response({"status": "ok"})
            return
        
        # .batho directory files (try .batho/ subdirectory first, then root)
        if path.startswith("/.batho/") and self.workspace_dir:
            rel_path = path[len("/.batho/"):]
            
            # Special case: index.json - generate dynamically from database
            if rel_path == "index.json":
                self._handle_batho_index()
                return
            
            # Try .batho/ subdirectory first
            file_path = (self.workspace_dir / ".batho" / rel_path).resolve()
            
            # If not found, try root directory (for artifact database files)
            if not file_path.exists():
                file_path = (self.workspace_dir / rel_path).resolve()
            
            # Security: ensure path is within workspace
            if not str(file_path).startswith(str(self.workspace_dir)):
                self._send_error(403, "Access denied")
                return
            
            if file_path.exists() and file_path.is_file():
                if serve_asset(self, file_path, cache=False):
                    return
            
            self._send_error(404, "File not found")
            return
        
        # Static assets
        if self.assets_dir:
            # /dashboard/* -> serve from assets
            if path.startswith("/dashboard/"):
                rel_path = path[len("/dashboard/"):]
                asset_path = (self.assets_dir / rel_path).resolve()
            elif path == "/" or path == "/index.html":
                asset_path = (self.assets_dir / "index.html").resolve()
            else:
                # Try to serve from assets anyway (SPA routing)
                asset_path = (self.assets_dir / path.lstrip("/")).resolve()
            
            # Security: ensure path is within assets
            if str(asset_path).startswith(str(self.assets_dir)):
                if asset_path.exists() and asset_path.is_file():
                    if serve_asset(self, asset_path, cache=False):
                        return
                elif path != "/":
                    # SPA fallback: serve index.html for unknown routes
                    index_path = (self.assets_dir / "index.html").resolve()
                    if index_path.exists():
                        if serve_asset(self, index_path, cache=False):
                            return
            
            self._send_error(404, "Asset not found")
            return
        
        self._send_error(404, "Not found")
    
    def do_POST(self) -> None:
        """Handle POST requests (proxy to bridge)."""
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        
        if not path.startswith("/api/"):
            self._send_error(405, "Method not allowed")
            return
        
        if self.proxy is None:
            self._send_error(503, "Bridge proxy not configured")
            return
        
        # Parse body
        content_length = int(self.headers.get("Content-Length", 0))
        body = {}
        if content_length > 0:
            try:
                import json
                body_bytes = self.rfile.read(content_length)
                body = json.loads(body_bytes.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass
        
        proxy_api_request(self, self.proxy, "POST", path, body=body)
    
    def do_OPTIONS(self) -> None:
        """Handle CORS preflight."""
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
    
    def _send_json_response(self, data: dict, status: int = 200) -> None:
        """Send JSON response."""
        import json
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    
    def _send_error(self, status: int, message: str) -> None:
        """Send error response."""
        self._send_json_response({"ok": False, "error": message}, status=status)
    
    def _handle_batho_index(self) -> None:
        """Generate index.json dynamically from the artifact database."""
        import json
        from batho.storage.engine import get_database, artifact_filename
        
        try:
            db_name = artifact_filename(self.workspace_dir)
            db_path = self.workspace_dir / db_name
            
            if not db_path.exists():
                self._send_error(404, f"Database not found: {db_name}")
                return
            
            db = get_database(self.workspace_dir)
            
            latest_id = db.get_latest_run_id()
            runs = db.get_all_runs()
            
            index_data = {
                "current_index_id": latest_id,
                "indexes": [
                    {
                        "index_id": r.id,
                        "timestamp": r.timestamp,
                        "root": str(self.workspace_dir),
                        "file_count": r.file_count,
                        "entity_count": r.entity_count,
                        "relationship_count": r.relationship_count,
                        "repo_hash": r.repo_hash,
                        "staleness_score": r.staleness_score,
                    }
                    for r in runs
                ]
            }
            
            body = json.dumps(index_data).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.end_headers()
            self.wfile.write(body)
        except Exception as exc:
            LOGGER.error("batho_index_error", error=str(exc))
            self._send_error(500, f"Failed to generate index: {exc}")


class DashboardServer:
    """Dashboard HTTP server.
    
    Serves static dashboard assets and proxies API calls to bridge.
    
    Usage:
        server = DashboardServer(
            repo_root=Path("/path/to/repo"),
            bridge_port=8765,
            dashboard_port=8766
        )
        server.start(open_browser=True)
        server.serve_forever()
    """
    
    def __init__(
        self,
        repo_root: Path,
        bridge_port: int = DEFAULT_BRIDGE_PORT,
        dashboard_port: int = DEFAULT_DASHBOARD_PORT,
        host: str = "127.0.0.1"
    ):
        """Initialize dashboard server.
        
        Args:
            repo_root: Path to repository root
            bridge_port: Port of bridge_core HTTP server
            dashboard_port: Port for dashboard HTTP server
            host: Bind address
        """
        self.repo_root = Path(repo_root).resolve()
        self.bridge_port = bridge_port
        self.dashboard_port = dashboard_port
        self.host = host
        
        self._bridge_process = None
        self._http_server: HTTPServer | None = None
        self._running = False
    
    def _find_workspace_dir(self) -> Path:
        """Find workspace directory by looking for artifact database.
        
        Uses storage engine's artifact_filename() naming convention:
        artifact_<dirname>.batho
        
        Returns:
            Path to workspace directory containing the artifact database
        """
        from batho.storage.engine import artifact_filename
        
        # Check current repo_root
        db_name = artifact_filename(self.repo_root)
        if (self.repo_root / db_name).exists():
            return self.repo_root
        
        # Also check .batho/ subdirectory (legacy)
        if (self.repo_root / ".batho" / db_name).exists():
            return self.repo_root
        
        # Walk up looking for database
        current = self.repo_root
        while True:
            parent = current.parent
            if parent == current:
                break
            current = parent
            
            parent_db_name = artifact_filename(current)
            if (current / parent_db_name).exists():
                return current
            
            # Also check .batho/ subdirectory (legacy)
            if (current / ".batho" / parent_db_name).exists():
                return current
        
        return self.repo_root
    
    def start(
        self,
        open_browser: bool = False,
        browser_route: str = "#/overview",
        auto_start_bridge: bool = True
    ) -> None:
        """Start dashboard server.
        
        Args:
            open_browser: Whether to open browser automatically
            browser_route: Hash route to open (e.g., #/overview)
            auto_start_bridge: Whether to start bridge server if not running
        """
        workspace_dir = self._find_workspace_dir()
        
        # Find dashboard assets
        assets_dir = find_dashboard_assets()
        if not assets_dir:
            raise RuntimeError("Dashboard assets not found. Is batho properly installed?")
        
        # Check if bridge is running, start if needed (port is available for binding)
        bridge_port_free = is_port_available(self.host, self.bridge_port)
        
        if auto_start_bridge and bridge_port_free:
            LOGGER.info("starting_bridge_server", port=self.bridge_port)
            self._start_bridge_background()
        elif not bridge_port_free:
            LOGGER.info("bridge_server_already_running", port=self.bridge_port)
        
        # Find available dashboard port
        available_port = find_available_port(self.host, self.dashboard_port)
        if not available_port:
            raise RuntimeError(
                f"Could not find available port in range "
                f"[{self.dashboard_port}, {self.dashboard_port + 10}]"
            )
        
        self.dashboard_port = available_port
        
        # Create HTTP server
        proxy = BridgeProxy(f"http://{self.host}:{self.bridge_port}")
        
        def handler_factory(*args, **kwargs):
            handler = DashboardHTTPHandler(*args, **kwargs)
            return handler
        
        DashboardHTTPHandler.assets_dir = assets_dir
        DashboardHTTPHandler.workspace_dir = workspace_dir
        DashboardHTTPHandler.proxy = proxy
        
        self._http_server = HTTPServer((self.host, self.dashboard_port), handler_factory)
        self._running = True
        
        LOGGER.info(
            "dashboard_server_started",
            host=self.host,
            port=self.dashboard_port,
            workspace=str(workspace_dir),
        )
        
        print(f"🚀 Batho Dashboard")
        print(f"   Workspace: {workspace_dir}")
        print(f"   Bridge:    http://{self.host}:{self.bridge_port}/")
        print(f"   Dashboard: http://{self.host}:{self.dashboard_port}/")
        print(f"   Route:     {browser_route}")
        print()
        print("Press Ctrl+C to stop")
        
        # Open browser
        if open_browser:
            url = f"http://{self.host}:{self.dashboard_port}/{browser_route}"
            threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    
    def _start_bridge_background(self) -> None:
        """Start bridge server in background thread."""
        def run_bridge():
            try:
                from batho.bridge_core.server import serve
                serve(
                    repo_root=self.repo_root,
                    transport="http",
                    port=self.bridge_port,
                    host=self.host
                )
            except Exception as e:
                LOGGER.error("bridge_background_error", error=str(e))
        
        thread = threading.Thread(target=run_bridge, daemon=True)
        thread.start()
        
        # Wait a moment for bridge to start
        import time
        time.sleep(0.5)
    
    def serve_forever(self) -> None:
        """Run server until interrupted."""
        if not self._http_server:
            raise RuntimeError("Server not started. Call start() first.")
        
        try:
            self._http_server.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down...")
        finally:
            self.stop()
    
    def stop(self) -> None:
        """Stop the dashboard server."""
        self._running = False
        if self._http_server:
            self._http_server.shutdown()
            self._http_server.server_close()
            LOGGER.info("dashboard_server_stopped")


def serve_dashboard(
    repo_root: Path | None = None,
    port: int = DEFAULT_DASHBOARD_PORT,
    bridge_port: int = DEFAULT_BRIDGE_PORT,
    host: str = "127.0.0.1",
    open_browser: bool = True,
    no_browser: bool = False
) -> None:
    """High-level function to serve dashboard.
    
    Args:
        repo_root: Repository root. Uses cwd if None.
        port: Dashboard port
        bridge_port: Bridge server port
        host: Bind address
        open_browser: Whether to open browser
        no_browser: If True, override open_browser to False
    """
    if repo_root is None:
        repo_root = Path.cwd()
    
    should_open = open_browser and not no_browser
    
    server = DashboardServer(
        repo_root=repo_root,
        bridge_port=bridge_port,
        dashboard_port=port,
        host=host
    )
    server.start(open_browser=should_open)
    server.serve_forever()


# Import BridgeProxy at the end to avoid circular import
from batho.dashboard_core.proxy import BridgeProxy

__all__ = [
    "DashboardServer",
    "serve_dashboard",
    "DEFAULT_DASHBOARD_PORT",
    "DEFAULT_BRIDGE_PORT",
]
