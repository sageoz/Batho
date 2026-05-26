"""HTTP Transport — REST API server.

Provides HTTP endpoints for dashboard and external clients.
This is a pure transport layer with no business logic.
"""

from __future__ import annotations

import json
import threading
import urllib.parse
from http.server import HTTPServer, ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Any

from batho.bridge_core.deps import WorkspaceDeps, load_workspace_deps, SnapshotCache
from batho.bridge_core import handlers
from batho.storage.engine import get_database
from batho.utils.logging import get_logger

LOGGER = get_logger(__name__, component="bridge_core.http")


class BridgeHTTPHandler(BaseHTTPRequestHandler):
    """HTTP request handler for bridge API.
    
    This handler routes all requests to the pure function handlers
    in bridge_core.handlers. It has no business logic.
    
    Routes:
        GET  /api/v2/* -> Handler functions
        POST /api/v2/* -> Handler functions
        GET  /healthz, /readyz, /metrics -> Health handlers
    """
    
    def log_message(self, format: str, *args) -> None:
        """Override to use structlog instead of stderr."""
        LOGGER.info(
            "http_request",
            method=self.command,
            path=self.path,
            status=args[1] if len(args) > 1 else "-",
        )
    
    def _send_json_response(
        self,
        data: dict,
        status: int = 200,
        extra_headers: dict[str, str] | None = None
    ) -> None:
        """Send JSON response with CORS headers."""
        body = json.dumps(data, ensure_ascii=True, sort_keys=True).encode("utf-8")
        
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        
        if extra_headers:
            for key, value in extra_headers.items():
                self.send_header(key, value)
        
        self.end_headers()
        self.wfile.write(body)
    
    def _send_error(self, status: int, message: str) -> None:
        """Send error response."""
        self._send_json_response(
            {"ok": False, "error": message, "data": {}},
            status=status
        )
    
    def _parse_query_params(self, query_string: str) -> dict[str, Any]:
        """Parse URL query string into dict."""
        parsed = urllib.parse.parse_qs(query_string, keep_blank_values=True)
        # Convert single-item lists to scalars
        return {
            k: v[0] if len(v) == 1 else v
            for k, v in parsed.items()
        }
    
    def _parse_body(self) -> dict[str, Any]:
        """Parse request body as JSON."""
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length == 0:
            return {}
        
        try:
            body_bytes = self.rfile.read(content_length)
            body_str = body_bytes.decode("utf-8")
            return json.loads(body_str) if body_str else {}
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            LOGGER.warning("body_parse_error", error=str(e))
            return {}
    
    def do_OPTIONS(self) -> None:
        """Handle CORS preflight requests."""
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
    
    def _handle_request_with_deps(self, method: str, path: str, params: dict[str, Any]) -> None:
        run_id = params.get("run_id")
        commit_sha = params.get("commit_sha")
        
        if isinstance(run_id, list):
            run_id = run_id[0] if run_id else None
        if isinstance(commit_sha, list):
            commit_sha = commit_sha[0] if commit_sha else None
            
        # Set global deps context var if server has it
        from batho.bridge_core.deps import global_deps_var
        global_token = None
        if hasattr(self.server, "global_deps") and self.server.global_deps:
            global_token = global_deps_var.set(self.server.global_deps)
            
        try:
            # Route fleet endpoints directly
            if path in ("/api/v1/fleet/overview", "/api/v1/search/global", "/api/v1/fleet/impact"):
                try:
                    result = handlers.dispatch(method, path, None, params)
                    self._send_json_response(result)
                except KeyError as e:
                    LOGGER.warning("endpoint_not_found", path=path, error=str(e))
                    self._send_error(404, f"Endpoint not found: {path}")
                except Exception as e:
                    LOGGER.error("handler_error", error=str(e), path=path)
                    self._send_error(500, str(e))
                return

            db = get_database(self.server.repo_root)
            resolved_run_id = None
            
            if run_id:
                resolved_run_id = run_id
            elif commit_sha:
                from batho.bridge_core.deps import resolve_commit_to_run_id
                resolved_run_id = resolve_commit_to_run_id(db, commit_sha)
                if not resolved_run_id:
                    self._send_error(400, f"Commit SHA '{commit_sha}' could not be resolved to a completed run")
                    return
            else:
                resolved_run_id = db.get_latest_run_id()
                if not resolved_run_id:
                    self._send_error(400, "No completed runs found in database")
                    return
                    
            # Get from cache
            deps = self.server.snapshot_cache.get(self.server.repo_root, resolved_run_id)
            
            # Set context var
            from batho.bridge_core.deps import current_deps
            token = current_deps.set(deps)
            try:
                result = handlers.dispatch(method, path, deps, params)

                # After layout is recomputed, invalidate L1 projection cache so
                # the next /hypergraph/level1 response embeds fresh x/y coordinates.
                if (method == "POST"
                        and path == "/api/v2/spatial/layout"
                        and isinstance(result, dict)
                        and result.get("ok")
                        and hasattr(deps, "projections")):
                    deps.projections._l1_cache = None

                # Inject metadata into result
                if isinstance(result, dict):
                    if "metadata" not in result:
                        result["metadata"] = {}
                    if isinstance(result["metadata"], dict):
                        result["metadata"]["run_id"] = deps.run_id
                        result["metadata"]["git_commit"] = deps.git_commit
                        result["metadata"]["timestamp"] = deps.timestamp
                        
                    # Also inject into result["data"] if it exists and is a dict
                    if "data" in result and isinstance(result["data"], dict):
                        if "metadata" not in result["data"]:
                            result["data"]["metadata"] = {}
                        if isinstance(result["data"]["metadata"], dict):
                            result["data"]["metadata"]["run_id"] = deps.run_id
                            result["data"]["metadata"]["git_commit"] = deps.git_commit
                            result["data"]["metadata"]["timestamp"] = deps.timestamp
                            
                self._send_json_response(result)
            except KeyError as e:
                LOGGER.warning("endpoint_not_found", path=path, error=str(e))
                self._send_error(404, f"Endpoint not found: {path}")
            except Exception as e:
                LOGGER.error("handler_error", error=str(e), path=path)
                self._send_error(500, str(e))
            finally:
                current_deps.reset(token)
                
        except Exception as e:
            LOGGER.error("http_handler_error", error=str(e), path=path)
            self._send_error(500, str(e))
        finally:
            if global_token:
                global_deps_var.reset(global_token)

    def do_GET(self) -> None:
        """Handle GET requests."""
        if not hasattr(self.server, "snapshot_cache") or self.server.snapshot_cache is None:
            self._send_error(500, "Server not initialized")
            return
            
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query_params = self._parse_query_params(parsed.query)
        
        # Binary viewport endpoint (special handling)
        if path == "/api/v2/spatial/viewport.bin":
            self._handle_binary_viewport(query_params)
            return
        
        # SSE agent event stream
        if path == "/api/v2/events/stream":
            self._handle_sse_stream(query_params)
            return
        
        # Green telemetry stats (no workspace deps needed)
        if path == "/api/v2/telemetry/stats":
            self._handle_telemetry_stats()
            return
        
        # Health endpoints
        if path in ("/healthz", "/readyz", "/metrics"):
            self._handle_request_with_deps("GET", path, query_params)
            return
            
        # API endpoints
        if not path.startswith("/api/"):
            self._send_error(404, f"Not found: {path}")
            return
            
        self._handle_request_with_deps("GET", path, query_params)
    
    def _handle_binary_viewport(self, params: dict) -> None:
        """Handle binary viewport request with msgpack response."""
        from batho.bridge_core.deps import current_deps, get_database
        from batho.bridge_core.handlers.spatial import handle_spatial_viewport_binary
        
        try:
            db = get_database(self.server.repo_root)
            run_id = params.get("run_id")
            if isinstance(run_id, list):
                run_id = run_id[0] if run_id else None
            resolved_run_id = run_id or db.get_latest_run_id()
            if not resolved_run_id:
                self._send_error(400, "No completed runs found in database")
                return
            deps = self.server.snapshot_cache.get(self.server.repo_root, resolved_run_id)
            token = current_deps.set(deps)
            try:
                binary_data = handle_spatial_viewport_binary(deps, params)
                
                # Send binary response
                self.send_response(200)
                self.send_header("Content-Type", "application/msgpack")
                self.send_header("Content-Length", str(len(binary_data)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(binary_data)
            finally:
                current_deps.reset(token)
        except Exception as e:
            LOGGER.error("binary_viewport_error", error=str(e))
            self._send_error(500, str(e))
    
    def _handle_sse_stream(self, params: dict) -> None:
        """Handle GET /api/v2/events/stream — Server-Sent Events."""
        from batho.bridge_core.services.event_bus import get_event_bus
        bus = get_event_bus()
        timeout = float(params.get("timeout", 60))

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        try:
            for event in bus.subscribe(timeout=timeout):
                if event is None:
                    self.wfile.write(b": keep-alive\n\n")
                else:
                    self.wfile.write(event.to_sse_line())
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            LOGGER.warning("sse_stream_error", error=str(e))

    def _handle_telemetry_stats(self) -> None:
        """Handle GET /api/v2/telemetry/stats."""
        try:
            if hasattr(self.server, "snapshot_cache") and self.server.snapshot_cache:
                from batho.storage.engine import get_database
                db = get_database(self.server.repo_root)
                run_id = db.get_latest_run_id()
                if run_id:
                    deps = self.server.snapshot_cache.get(self.server.repo_root, run_id)
                    if hasattr(deps, "telemetry") and deps.telemetry:
                        stats = deps.telemetry.get_stats()
                        self._send_json_response({"ok": True, "data": stats})
                        return
            self._send_json_response({"ok": True, "data": {
                "total_requests": 0, "avg_duration_ms": 0.0,
                "avg_cpu_ms": 0.0, "peak_memory_mb": 0.0,
                "recent_requests": [], "carbon_estimate_mg": 0.0,
            }})
        except Exception as e:
            self._send_error(500, str(e))

    def do_POST(self) -> None:
        """Handle POST requests."""
        if not hasattr(self.server, "snapshot_cache") or self.server.snapshot_cache is None:
            self._send_error(500, "Server not initialized")
            return
        
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        body_params = self._parse_body()
        
        # Merge query params with body (body takes precedence)
        query_params = self._parse_query_params(parsed.query)
        params = {**query_params, **body_params}
        
        if not path.startswith("/api/"):
            self._send_error(404, f"Not found: {path}")
            return
        
        self._handle_request_with_deps("POST", path, params)


class BridgeHTTPServer:
    """HTTP server for bridge API.
    
    Wraps Python's HTTPServer with workspace dependency injection.
    
    Usage:
        server = BridgeHTTPServer(repo_root, port=8765)
        server.start()
        # ... run until shutdown ...
        server.stop()
    """
    
    def __init__(
        self,
        repo_root: Path,
        port: int = 8765,
        host: str = "127.0.0.1",
        global_db_path: Path | None = None
    ):
        """Initialize HTTP server.
        
        Args:
            repo_root: Path to repository root
            port: TCP port to listen on
            host: Bind address (127.0.0.1 for local, 0.0.0.0 for network)
            global_db_path: Optional path to global.batho database
        """
        self.repo_root = Path(repo_root).resolve()
        self.port = port
        self.host = host
        self.deps: WorkspaceDeps | None = None
        self.server: HTTPServer | None = None
        self._running = False
        self.snapshot_cache = SnapshotCache()
        
        # Initialize GlobalPlatformDeps if configured/resolved
        self.global_deps = None
        from batho.bridge_core.global_registry import resolve_global_db_path, GlobalPlatformDeps
        if not global_db_path:
            try:
                global_db_path = resolve_global_db_path(self.repo_root)
            except Exception:
                pass
        
        if global_db_path:
            try:
                self.global_deps = GlobalPlatformDeps(global_db_path)
            except Exception as e:
                LOGGER.warning("failed_to_initialize_global_deps", error=str(e))
                self.global_deps = None
    
    def start(self) -> None:
        """Start the HTTP server.
        
        Loads workspace dependencies and starts listening for requests.
        """
        # Load latest workspace dependencies for server initialization display
        LOGGER.info("http_loading_workspace", repo_root=str(self.repo_root))
        self.deps = load_workspace_deps(self.repo_root)
        
        # Initialize default snapshot in cache
        if self.deps and self.deps.run_id:
            self.snapshot_cache._cache[self.deps.run_id] = self.deps
        
        # Create server
        def handler_factory(*args, **kwargs):
            handler = BridgeHTTPHandler(*args, **kwargs)
            return handler
        
        self.server = ThreadingHTTPServer((self.host, self.port), handler_factory)
        self.server.snapshot_cache = self.snapshot_cache
        self.server.repo_root = self.repo_root
        self.server.global_deps = self.global_deps

        # Pre-warm L1 cache + spatial layout in background so first request is instant
        def _prewarm() -> None:
            try:
                self.deps.spatial.compute_layout(layer="L1")
                self.deps.projections.build_level1()
                LOGGER.info("prewarm_complete", component="bridge_core.http")
            except Exception as e:
                LOGGER.warning("prewarm_failed", error=str(e))

        threading.Thread(target=_prewarm, daemon=True, name="batho-prewarm").start()

        self._running = True
        
        LOGGER.info(
            "http_server_started",
            host=self.host,
            port=self.port,
            entities=len(self.deps.graph.entities),
        )
        
        print(f"🚀 Batho Bridge HTTP Server")
        print(f"   Workspace: {self.repo_root}")
        print(f"   URL:       http://{self.host}:{self.port}/")
        print(f"   Entities:  {len(self.deps.graph.entities):,}")
        print()
        print("Press Ctrl+C to stop")
    
    def serve_forever(self) -> None:
        """Run server until interrupted."""
        if not self.server:
            raise RuntimeError("Server not started. Call start() first.")
        
        try:
            self.server.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down...")
        finally:
            self.stop()
    
    def stop(self) -> None:
        """Stop the HTTP server."""
        self._running = False
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            LOGGER.info("http_server_stopped")


def run_http_server(
    repo_root: Path | None = None,
    port: int = 8765,
    host: str = "127.0.0.1",
    global_db_path: Path | None = None
) -> None:
    """Convenience function to run HTTP server.
    
    This blocks until interrupted with Ctrl+C.
    
    Args:
        repo_root: Path to repository root. Uses cwd if None.
        port: TCP port to listen on
        host: Bind address
        global_db_path: Optional path to global.batho database
    """
    if repo_root is None:
        repo_root = Path.cwd()
    
    server = BridgeHTTPServer(repo_root, port=port, host=host, global_db_path=global_db_path)
    server.start()
    server.serve_forever()


__all__ = [
    "BridgeHTTPHandler",
    "BridgeHTTPServer",
    "run_http_server",
]
