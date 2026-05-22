"""REST API router for the MCP hub."""

from __future__ import annotations

import asyncio
import json
import mimetypes
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import parse_qs, urlparse

from batho.bridge.constants import DEFAULT_HUB_REST_PORT, KNOWN_ARTIFACT_TYPES
from batho.bridge.cross import (
    cross_dependencies_impl,
    cross_search_impl,
    cross_symbols_impl,
    cross_workspaces_with_artifact_impl,
    search_bsg_nodes,
)
from batho.bridge.envelope import err, ok, to_json
from batho.bridge.file_outline import build_file_outline
from batho.bridge.file_service import build_file_content_response
from batho.bridge.fs_browse import browse_directory
from batho.bridge.snippets import generate_agent_snippet
from batho.bridge.workspace_manager import WorkspaceManager
from batho.bridge.workspace_registry import WorkspaceRegistry
from batho.bridge.telemetry import get_collector
from batho.utils.logging import get_logger

LOGGER = get_logger(__name__, component="bridge.http")


class ServerOrClassProperty:
    """Descriptor that resolves attributes from HTTPServer instance for thread isolation.
    
    Falls back to instance attribute if set directly (for testing compatibility).
    Falls back to class attribute if server attribute is not available.
    This ensures each HTTPServer instance has its own configuration for strict thread isolation.
    """
    
    def __init__(self, name: str):
        self.name = name
    
    def __get__(self, instance, owner):
        if instance is None:
            # Class access: fall back to class attribute for compatibility
            return getattr(owner, f'_{self.name}', None)

        # Instance access: try to get from server instance first
        if hasattr(instance, 'server') and instance.server is not None:
            return getattr(instance.server, self.name, None)

        # Fallback to instance attribute (for testing compatibility)
        if hasattr(instance, f'_{self.name}'):
            return getattr(instance, f'_{self.name}')

        # Fallback to class attribute
        return getattr(owner, f'_{self.name}', None)
    
    def __set__(self, instance, value):
        # Set on the instance's server if available
        if hasattr(instance, 'server') and instance.server is not None:
            setattr(instance.server, self.name, value)
        else:
            # Fallback: set as instance attribute (for testing compatibility)
            setattr(instance, f'_{self.name}', value)


class HubHTTPHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the hub REST API."""

    # Use descriptors for dynamic resolution from server instance
    manager: WorkspaceManager = ServerOrClassProperty('manager')
    registry: WorkspaceRegistry = ServerOrClassProperty('registry')
    default_workspace: str | None = ServerOrClassProperty('default_workspace')
    dashboard_dir: Path | None = ServerOrClassProperty('dashboard_dir')

    def log_message(self, format, *args):
        LOGGER.debug("http_request", method=self.command, path=self.path)

    def send_json(self, data: dict, status: int = 200, headers: dict | None = None):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        if headers:
            for k, v in headers.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(to_json(data).encode("utf-8"))

    def _check_origin(self) -> bool:
        """Validate Origin header for mutating requests."""
        origin = self.headers.get("Origin")
        if not origin:
            # Allow requests without Origin (e.g. CLI, direct curl)
            return True

        host = self.headers.get("Host")
        parsed_origin = urlparse(origin)
        
        # If origin matches our host, it's safe
        if parsed_origin.netloc == host:
            return True
            
        # Also allow localhost by default
        if parsed_origin.hostname in ("localhost", "127.0.0.1"):
            return True

        LOGGER.warning("cross_origin_mutation_rejected", origin=origin, host=host)
        self.send_json(err("forbidden", "Cross-origin mutation rejected"), status=403)
        return False

    def get_workspace_id(self, path: str) -> tuple[str | None, str]:
        """Extract workspace ID from path or use default."""
        parsed = urlparse(path)
        parts = parsed.path.strip("/").split("/")

        if len(parts) >= 2 and parts[0] == "workspaces":
            return parts[1], f"/{'/'.join(parts[2:])}"

        if len(parts) >= 1 and parts[0] == "bridge":
            return self.default_workspace, f"/{'/'.join(parts[1:])}"

        return None, path

    def _run_coro(self, coro, timeout: float = 30.0) -> Any:
        """Run a coroutine on the manager's event loop from this HTTP thread."""
        if not self.manager.ready:
            raise RuntimeError("Manager is not ready yet, please wait")

        loop = self.manager.loop
        if not loop:
            raise RuntimeError("Manager event loop not initialized")

        future = asyncio.run_coroutine_threadsafe(coro, loop)
        try:
            return future.result(timeout)
        except asyncio.CancelledError:
            raise TimeoutError(f"Operation cancelled after {timeout}s")

    def _resolve_workspace(self, ws_id: str) -> tuple[Any, bool]:
        """Resolve a workspace handle with proper error handling.

        Returns:
            tuple of (handle or None, success_bool)
            success_bool can be True, False, or "not_ready" string
        """
        try:
            handle = self._run_coro(self.manager.resolve(ws_id))
            if not handle or not handle.is_ready:
                return None, False
            return handle, True
        except RuntimeError as exc:
            if "not ready" in str(exc).lower():
                LOGGER.warning("manager_not_ready", workspace_id=ws_id)
                return None, "not_ready"
            LOGGER.error("workspace_resolve_failed", workspace_id=ws_id, error=str(exc))
            return None, False
        except Exception as exc:
            LOGGER.error("workspace_resolve_failed", workspace_id=ws_id, error=str(exc))
            return None, False

    def _check_workspace_ready(self, ok) -> bool:
        """Check if workspace is ready, sending error response if not."""
        if ok == "not_ready":
            self.send_json(err("service_unavailable", "Hub is still starting, please retry"), status=503)
            return False
        if not ok:
            self.send_json(err("workspace_not_ready", "Workspace is not ready"), status=503)
            return False
        return True

    def do_GET(self):
        try:
            parsed = urlparse(self.path)
            path = parsed.path.strip("/")

            if path == "healthz" or path == "api/v1/healthz":
                return self.handle_healthz()

            if path == "readyz" or path == "api/v1/readyz":
                return self.handle_readyz()

            if path == "metrics" or path == "api/v1/metrics":
                return self.handle_metrics(parsed.query)

            if path.startswith("api/v1/"):
                return self.handle_api_v1(path, parsed.query, "GET")

            ws_id, remaining = self.get_workspace_id(self.path)
            remaining = remaining.strip("/")

            # Check if this is a bridge API route
            is_bridge = ws_id is not None or path.startswith("bridge/") or path.startswith("workspaces/") or path.startswith("cross/")

            if is_bridge:
                if not path.startswith("cross/"):
                    if not ws_id and self.default_workspace:
                        self.send_json(
                            err("workspace_not_found", "No workspace specified and no default configured"),
                            status=400,
                            headers={"X-Batho-Deprecation": "route=/api/v1/bridge; sunset=phase-6"},
                        )
                        return

                if path == "workspaces" or path == "":
                    return self.handle_list_workspaces()

                if path.startswith("cross/"):
                    return self.handle_cross(ws_id, remaining, parsed.query)

                if remaining.startswith("health"):
                    return self.handle_workspace_health(ws_id)

                if remaining.startswith("stats"):
                    return self.handle_workspace_stats(ws_id)

                if remaining.startswith("indexes"):
                    return self.handle_indexes(ws_id, remaining, parsed.query)

                if remaining.startswith("artifacts"):
                    return self.handle_artifacts(ws_id, remaining, parsed.query)

                if remaining.startswith("file-content"):
                    return self.handle_file_content(ws_id, parsed.query)

                if remaining.startswith("files"):
                    return self.handle_files(ws_id, parsed.query)

                if remaining.startswith("bsg"):
                    return self.handle_bsg(ws_id, remaining, parsed.query)

                if remaining.startswith("context/"):
                    return self.handle_context(ws_id, remaining)

                if remaining == "graph":
                    return self.handle_graph(ws_id, parsed.query)

                if remaining.startswith("patches"):
                    return self.handle_patches(ws_id, remaining, parsed.query)

                if remaining.startswith("snapshots/"):
                    return self.handle_snapshots(ws_id, remaining, parsed.query)

            # Fallback to static file serving if dashboard_dir is set
            if self.dashboard_dir:
                return self.handle_static_file(parsed.path)

            self.send_json(err("invalid_argument", f"Unknown path: {path}"), status=404)

        except Exception as exc:
            LOGGER.error("http_error", error=str(exc))
            self.send_json(err("internal_error", str(exc)), status=500)

    def handle_static_file(self, path: str):
        """Serve static files from dashboard_dir."""
        if not self.dashboard_dir:
            return self.send_json(err("not_found", "Static assets not configured"), status=404)

        # Normalize path
        if path == "/" or not path:
            path = "/index.html"

        # Remove leading slash for Path joining
        rel_path = path.lstrip("/")
        file_path = (self.dashboard_dir / rel_path).resolve()

        # Security check: ensure path is within dashboard_dir using relative_to
        try:
            file_path = file_path.resolve()
            dashboard_resolved = self.dashboard_dir.resolve()
            file_path.relative_to(dashboard_resolved)
        except ValueError:
            return self.send_json(err("forbidden", "Access denied"), status=403)

        # SPA fallback: if file doesn't exist but looks like a route, serve index.html
        if not file_path.exists() or not file_path.is_file():
            if "." not in path.split("/")[-1]:
                file_path = self.dashboard_dir / "index.html"
            else:
                return self.send_json(err("not_found", f"File not found: {path}"), status=404)

        try:
            content_type, _ = mimetypes.guess_type(str(file_path))
            if not content_type:
                content_type = "application/octet-stream"

            with open(file_path, "rb") as f:
                content = f.read()

            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(content)
        except Exception as exc:
            LOGGER.error("static_file_error", path=path, error=str(exc))
            self.send_json(err("internal_error", str(exc)), status=500)

    def do_PUT(self):
        if not self._check_origin():
            return
        try:
            parsed = urlparse(self.path)
            path = parsed.path.strip("/")

            if path.startswith("api/v1/"):
                content_length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
                return self.handle_api_v1(path, parsed.query, "PUT", body)

            self.send_json(err("invalid_argument", f"Unknown path: {path}"), status=404)

        except Exception as exc:
            LOGGER.error("http_error", error=str(exc))
            self.send_json(err("internal_error", str(exc)), status=500)

    def do_PATCH(self):
        if not self._check_origin():
            return
        try:
            parsed = urlparse(self.path)
            path = parsed.path.strip("/")

            if path.startswith("api/v1/"):
                content_length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
                return self.handle_api_v1(path, parsed.query, "PATCH", body)

            self.send_json(err("invalid_argument", f"Unknown path: {path}"), status=404)

        except Exception as exc:
            LOGGER.error("http_error", error=str(exc))
            self.send_json(err("internal_error", str(exc)), status=500)

    def do_POST(self):
        if not self._check_origin():
            return
        try:
            parsed = urlparse(self.path)
            path = parsed.path.strip("/")

            if path.startswith("api/v1/"):
                content_length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
                return self.handle_api_v1(path, parsed.query, "POST", body)

            self.send_json(err("invalid_argument", f"Unknown path: {path}"), status=404)

        except Exception as exc:
            LOGGER.error("http_error", error=str(exc))
            self.send_json(err("internal_error", str(exc)), status=500)

    def do_DELETE(self):
        if not self._check_origin():
            return
        try:
            parsed = urlparse(self.path)
            path = parsed.path.strip("/")

            if path.startswith("api/v1/"):
                return self.handle_api_v1(path, parsed.query, "DELETE")

            self.send_json(err("invalid_argument", f"Unknown path: {path}"), status=404)

        except Exception as exc:
            LOGGER.error("http_error", error=str(exc))
            self.send_json(err("internal_error", str(exc)), status=500)

    def handle_api_v1(self, path: str, query: str, method: str, body: str = "{}"):
        """Handle all /api/v1/* endpoints."""
        params = parse_qs(query)
        path_parts = path.split("/")[2:]  # Strip "api/v1/"

        try:
            data = json.loads(body) if body else {}
        except json.JSONDecodeError:
            return self.send_json(err("invalid_argument", "Invalid JSON body"), status=400)

        # Config endpoints
        if path_parts == ["config"]:
            if method == "GET":
                return self.handle_get_config()
            if method == "PUT":
                return self.handle_put_config(data)

        if len(path_parts) >= 2 and path_parts[0] == "config":
            subpath = "/".join(path_parts[1:])
            if subpath == "server" and method == "GET":
                return self.handle_get_server_config()
            if subpath == "server" and method == "PATCH":
                return self.handle_patch_server_config(data)
            if subpath == "residency" and method == "GET":
                return self.handle_get_residency_config()
            if subpath == "residency" and method == "PATCH":
                return self.handle_patch_residency_config(data)
            if subpath == "concurrency" and method == "GET":
                return self.handle_get_concurrency_config()
            if subpath == "concurrency" and method == "PATCH":
                return self.handle_patch_concurrency_config(data)
            if subpath == "discovery" and method == "GET":
                return self.handle_get_discovery_config()
            if subpath == "discovery" and method == "PATCH":
                return self.handle_patch_discovery_config(data)

        # Workspaces endpoints
        if path_parts == ["workspaces"]:
            if method == "GET":
                return self.handle_list_workspaces_api()
            if method == "POST":
                return self.handle_create_workspace(data)

        if len(path_parts) >= 2 and path_parts[0] == "workspaces":
            ws_id = path_parts[1]
            remaining = path_parts[2:] if len(path_parts) > 2 else []

            if method == "GET" and not remaining:
                return self.handle_get_workspace(ws_id)
            if method == "PATCH" and not remaining:
                return self.handle_patch_workspace(ws_id, data)
            if method == "DELETE" and not remaining:
                return self.handle_delete_workspace(ws_id)
            if len(remaining) == 1 and remaining[0] == "reindex-hint" and method == "POST":
                return self.handle_workspace_reindex_hint(ws_id)
            if len(remaining) == 1 and remaining[0] == "mount" and method == "POST":
                return self.handle_workspace_mount(ws_id)
            if len(remaining) == 1 and remaining[0] == "unmount" and method == "POST":
                return self.handle_workspace_unmount(ws_id)
            if len(remaining) == 1 and remaining[0] == "refresh" and method == "POST":
                return self.handle_workspace_refresh(ws_id)
            if (
                method == "GET"
                and remaining
                and remaining[0] == "files"
                and remaining[-1] == "outline"
            ):
                file_path = "/".join(remaining[1:-1])
                return self.handle_file_outline(ws_id, file_path)

        # Cross-repo endpoints
        if len(path_parts) >= 2 and path_parts[0] == "cross" and method == "GET":
            if path_parts[1] == "search":
                return self.handle_cross_search_api(params)
            if path_parts[1] == "symbols":
                return self.handle_cross_symbols_api(params)
            if path_parts[1] == "dependencies":
                return self.handle_cross_dependencies_api(params)
            if path_parts[1] == "index" and len(path_parts) > 2 and path_parts[2] == "stats":
                return self.handle_cross_index_stats_api()

        # Agent snippets
        if len(path_parts) >= 3 and path_parts[0] == "agents" and path_parts[1] == "snippets":
            agent = path_parts[2]
            if method == "GET":
                return self.handle_agent_snippet(agent)

        # Admin endpoints
        if len(path_parts) >= 2 and path_parts[0] == "admin":
            if path_parts[1] == "discover" and method == "POST":
                return self.handle_admin_discover()

        # FS browse
        if path_parts == ["fs", "browse"]:
            if method == "GET":
                at = params.get("at", [None])[0]
                return self.handle_fs_browse(at)

        self.send_json(err("invalid_argument", f"Unknown API path: {path}"), status=404)

    # Config handlers
    def handle_get_config(self):
        config = self.registry.load()
        return self.send_json(ok(config.model_dump(exclude_none=True)))

    def handle_put_config(self, data: dict):
        from batho.bridge.models import HubConfig
        try:
            config = HubConfig.model_validate(data)
            self.registry.save(config)
            return self.send_json(ok(config.model_dump(exclude_none=True)))
        except Exception as exc:
            return self.send_json(err("invalid_argument", str(exc)), status=400)

    def handle_get_server_config(self):
        config = self.registry.load()
        return self.send_json(ok(config.server.model_dump()))

    def handle_patch_server_config(self, data: dict):
        from batho.bridge.models import ServerConfig
        config = self.registry.load()
        try:
            updated = ServerConfig.model_validate({**config.server.model_dump(), **data})
            config.server = updated
            self.registry.save(config)
            return self.send_json(ok(config.server.model_dump()))
        except Exception as exc:
            return self.send_json(err("invalid_argument", str(exc)), status=400)

    def handle_get_residency_config(self):
        config = self.registry.load()
        return self.send_json(ok(config.residency.model_dump()))

    def handle_patch_residency_config(self, data: dict):
        from batho.bridge.models import ResidencyConfig
        config = self.registry.load()
        try:
            updated = ResidencyConfig.model_validate({**config.residency.model_dump(), **data})
            config.residency = updated
            self.registry.save(config)
            return self.send_json(ok(config.residency.model_dump()))
        except Exception as exc:
            return self.send_json(err("invalid_argument", str(exc)), status=400)

    def handle_get_concurrency_config(self):
        config = self.registry.load()
        return self.send_json(ok(config.concurrency.model_dump()))

    def handle_patch_concurrency_config(self, data: dict):
        from batho.bridge.models import ConcurrencyConfig
        config = self.registry.load()
        try:
            updated = ConcurrencyConfig.model_validate({**config.concurrency.model_dump(), **data})
            config.concurrency = updated
            self.registry.save(config)
            return self.send_json(ok(config.concurrency.model_dump()))
        except Exception as exc:
            return self.send_json(err("invalid_argument", str(exc)), status=400)

    def handle_get_discovery_config(self):
        config = self.registry.load()
        return self.send_json(ok(config.discovery.model_dump()))

    def handle_patch_discovery_config(self, data: dict):
        from batho.bridge.models import DiscoveryConfig
        config = self.registry.load()
        try:
            updated = DiscoveryConfig.model_validate({**config.discovery.model_dump(), **data})
            config.discovery = updated
            self.registry.save(config)
            return self.send_json(ok(config.discovery.model_dump()))
        except Exception as exc:
            return self.send_json(err("invalid_argument", str(exc)), status=400)

    # Workspaces handlers
    def handle_list_workspaces_api(self):
        config = self.registry.load()
        resident_ids = {h.workspace_id for h in self.manager.resident()}

        result = []
        for ws in config.workspaces:
            data = ws.model_dump()
            data["resident"] = ws.id in resident_ids
            result.append(data)
        return self.send_json(ok(result))

    def handle_create_workspace(self, data: dict):
        from batho.bridge.models import WorkspaceConfig
        try:
            ws = WorkspaceConfig.model_validate(data)
            self.registry.add(ws)
            return self.send_json(ok(ws.model_dump()), status=201)
        except Exception as exc:
            return self.send_json(err("invalid_argument", str(exc)), status=400)

    def handle_get_workspace(self, ws_id: str):
        ws = self.registry.get(ws_id)
        if not ws:
            return self.send_json(err("workspace_not_found", f"Workspace not found: {ws_id}"), status=404)
        return self.send_json(ok(ws.model_dump()))

    def handle_patch_workspace(self, ws_id: str, data: dict):
        try:
            self.registry.update(ws_id, **data)
            ws = self.registry.get(ws_id)
            return self.send_json(ok(ws.model_dump()))
        except Exception as exc:
            return self.send_json(err("invalid_argument", str(exc)), status=400)

    def handle_delete_workspace(self, ws_id: str):
        try:
            self.registry.remove(ws_id)
            return self.send_json(ok({"deleted": ws_id}))
        except Exception as exc:
            return self.send_json(err("invalid_argument", str(exc)), status=400)

    def handle_workspace_reindex_hint(self, ws_id: str):
        return self.send_json(ok({"workspace_id": ws_id, "hint": "marked_stale"}))

    def handle_workspace_mount(self, ws_id: str):
        try:
            self._run_coro(self.manager.mount(ws_id))
            return self.send_json(ok({"workspace_id": ws_id, "mounted": True}))
        except Exception as exc:
            return self.send_json(err("internal_error", str(exc)), status=500)

    def handle_workspace_unmount(self, ws_id: str):
        try:
            self._run_coro(self.manager.unmount(ws_id, reason="api_unmount"))
            return self.send_json(ok({"workspace_id": ws_id, "unmounted": True}))
        except Exception as exc:
            return self.send_json(err("internal_error", str(exc)), status=500)

    def handle_workspace_refresh(self, ws_id: str):
        try:
            self._run_coro(self.manager.refresh(ws_id))
            return self.send_json(ok({"workspace_id": ws_id, "refreshed": True}))
        except Exception as exc:
            return self.send_json(err("internal_error", str(exc)), status=500)

    def handle_agent_snippet(self, agent: str):
        config = self.registry.load()
        snippet = generate_agent_snippet(agent, config)
        if snippet is None:
            return self.send_json(err("invalid_argument", f"Unknown agent: {agent}"), status=404)
        return self.send_json(ok({"agent": agent, "snippet": snippet}))

    def handle_admin_discover(self):
        config = self.registry.load()
        if not config.discovery.ctn_dir_globs:
            return self.send_json(err("invalid_argument", "No ctn_dir_globs configured"), status=400)

        from batho.bridge.workspace_discovery import WorkspaceDiscovery
        discovery = WorkspaceDiscovery(self.registry, config.discovery)
        diff = discovery.scan()

        return self.send_json(ok({
            "added": [ws.model_dump() for ws in diff.added],
            "removed": diff.removed,
            "updated": [ws.model_dump() for ws in diff.updated],
        }))

    def handle_fs_browse(self, at: str | None):
        import os
        from pathlib import Path

        root = os.path.expanduser(at) if at else os.path.expanduser("~")
        try:
            entries = browse_directory(root)
            return self.send_json(ok({"path": root, "entries": entries}))
        except Exception as exc:
            return self.send_json(err("invalid_argument", str(exc)), status=400)

    def handle_healthz(self):
        self.send_json(ok({"status": "ok"}))

    def handle_readyz(self):
        self.send_json(ok({"status": "ready"}))

    def handle_metrics(self, query: str):
        params = parse_qs(query)
        fmt = params.get("format", ["text"])[0]

        collector = get_collector()

        resident = list(self.manager.resident())
        collector.set_workspace_state("_total", "ready")
        for ws in self.manager.list():
            state = "ready"
            for r in resident:
                if r.workspace_id == ws.id:
                    state = "ready"
                    break
            else:
                state = "registered"
            collector.set_workspace_state(ws.id, state)

        if hasattr(self.manager, "cache") and self.manager.cache:
            for ws_id in [ws.id for ws in self.manager.list()]:
                cache_size = self.manager.cache.workspace_size(ws_id) if hasattr(self.manager.cache, "workspace_size") else 0
                collector.set_cache_bytes(ws_id, cache_size)

        if self.manager.cross_index:
            stats = self.manager.cross_index.stats() if hasattr(self.manager.cross_index, "stats") else {}
            collector.set_cross_index_stats(
                stats.get("bytes", 0),
                stats.get("workspaces", 0)
            )

        data = {
            "resident_workspaces": len(resident),
            "registered_workspaces": len(self.manager.list()),
        }

        if fmt == "json":
            self.send_json(ok(data))
        else:
            metrics = collector.generate_prometheus()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4")
            self.end_headers()
            self.wfile.write(metrics.encode("utf-8"))

    def handle_list_workspaces(self):
        workspaces = self.manager.list()
        resident_ids = {h.workspace_id for h in self.manager.resident()}
        result = []
        for ws in workspaces:
            data = ws.model_dump()
            data["resident"] = ws.id in resident_ids
            result.append(data)
        self.send_json(ok(result))

    def handle_cross(self, ws_id, remaining, query):
        params = parse_qs(query)

        def dispatch():
            if remaining == "search":
                q = params.get("q", [""])[0]
                ws_ids = params.get("workspaces", [None])[0]
                ws_ids = ws_ids.split(",") if ws_ids else None
                tags = params.get("tags", [None])[0]
                tag_list = tags.split(",") if tags else None
                kinds = params.get("kinds", [None])[0]
                limit = int(params.get("limit", [25])[0])
                merge_strategy = params.get("merge_strategy", ["score_desc"])[0]
                force_mount = params.get("force_mount", ["false"])[0] == "true"
                result, meta = self._run_coro(
                    cross_search_impl(
                        self.manager,
                        query=q,
                        workspace_ids=ws_ids,
                        tags=tag_list,
                        kinds=kinds.split(",") if kinds else None,
                        limit_per_ws=limit,
                        merge_strategy=merge_strategy,
                        force_mount=force_mount,
                    )
                )
                self.send_json(ok(result, meta=meta))

            elif remaining == "symbols":
                name = params.get("name", [""])[0]
                ws_ids = params.get("workspaces", [None])[0]
                ws_ids = ws_ids.split(",") if ws_ids else None
                tags = params.get("tags", [None])[0]
                tag_list = tags.split(",") if tags else None
                kinds = params.get("kinds", [None])[0]
                kind_list = kinds.split(",") if kinds else None
                result, meta = self._run_coro(
                    cross_symbols_impl(
                        self.manager,
                        name=name,
                        workspace_ids=ws_ids,
                        tags=tag_list,
                        kinds=kind_list,
                    )
                )
                self.send_json(ok(result, meta=meta))

            elif remaining == "dependencies":
                package = params.get("package", [""])[0]
                ws_ids = params.get("workspaces", [None])[0]
                ws_ids = ws_ids.split(",") if ws_ids else None
                tags = params.get("tags", [None])[0]
                tag_list = tags.split(",") if tags else None
                result, meta = self._run_coro(
                    cross_dependencies_impl(
                        self.manager,
                        package=package,
                        workspace_ids=ws_ids,
                        tags=tag_list,
                    )
                )
                self.send_json(ok(result, meta=meta))

            elif remaining == "workspaces-with-artifact":
                artifact_type = params.get("artifact_type", [""])[0]
                result, meta = self._run_coro(
                    cross_workspaces_with_artifact_impl(self.manager, artifact_type=artifact_type)
                )
                self.send_json(ok(result, meta=meta))

            else:
                self.send_json(err("invalid_argument", f"Unknown cross endpoint: {remaining}"), status=404)

        dispatch()

    def handle_cross_search_api(self, params: dict[str, list[str]]):
        q = params.get("q", [""])[0]
        ws_ids = params.get("workspaces", [None])[0]
        ws_ids = ws_ids.split(",") if ws_ids else None
        tags = params.get("tags", [None])[0]
        tag_list = tags.split(",") if tags else None
        kinds = params.get("kinds", [None])[0]
        limit = int(params.get("limit_per_ws", [params.get("limit", [25])[0]])[0])
        merge_strategy = params.get("merge_strategy", ["score_desc"])[0]
        force_mount = params.get("force_mount", ["false"])[0] == "true"

        result, meta = self._run_coro(
            cross_search_impl(
                self.manager,
                query=q,
                workspace_ids=ws_ids,
                tags=tag_list,
                kinds=kinds.split(",") if kinds else None,
                limit_per_ws=limit,
                merge_strategy=merge_strategy,
                force_mount=force_mount,
            )
        )
        self.send_json(ok(result, meta=meta))

    def handle_cross_symbols_api(self, params: dict[str, list[str]]):
        name = params.get("name", [""])[0]
        ws_ids = params.get("workspaces", [None])[0]
        ws_ids = ws_ids.split(",") if ws_ids else None
        tags = params.get("tags", [None])[0]
        tag_list = tags.split(",") if tags else None
        kinds = params.get("kinds", [None])[0]
        kind_list = kinds.split(",") if kinds else None

        result, meta = self._run_coro(
            cross_symbols_impl(
                self.manager,
                name=name,
                workspace_ids=ws_ids,
                tags=tag_list,
                kinds=kind_list,
            )
        )
        self.send_json(ok(result, meta=meta))

    def handle_cross_dependencies_api(self, params: dict[str, list[str]]):
        package = params.get("package", [""])[0]
        ws_ids = params.get("workspaces", [None])[0]
        ws_ids = ws_ids.split(",") if ws_ids else None
        tags = params.get("tags", [None])[0]
        tag_list = tags.split(",") if tags else None

        result, meta = self._run_coro(
            cross_dependencies_impl(
                self.manager,
                package=package,
                workspace_ids=ws_ids,
                tags=tag_list,
            )
        )
        self.send_json(ok(result, meta=meta))

    def handle_cross_index_stats_api(self):
        index = self.manager.cross_index
        if not index:
            return self.send_json(ok({"enabled": False, "stats": {}}))
        stats = index.stats()
        payload = {
            "enabled": True,
            "stats": stats.__dict__,
        }
        self.send_json(ok(payload))

    def handle_file_outline(self, ws_id: str, file_path: str):
        handle, ok = self._resolve_workspace(ws_id)
        if not self._check_workspace_ready(ok):
            return
        if not file_path or file_path.startswith("/") or ".." in file_path:
            return self.send_json(err("invalid_argument", "Invalid path"), status=400)
        try:
            bsg_data = handle.loader.load_json("bsg_json")
        except Exception as exc:
            return self.send_json(err("artifact_not_found", str(exc)), status=404)
        outline = build_file_outline(bsg_data, file_path)
        self.send_json(ok(outline, workspace_id=ws_id))

    def handle_workspace_health(self, ws_id: str):
        health_list = self._run_coro(self.manager.health_check(ws_id))
        result = [h.model_dump() for h in health_list]
        self.send_json(ok(result, workspace_id=ws_id))

    def handle_workspace_stats(self, ws_id: str):
        handle, ok = self._resolve_workspace(ws_id)
        if not self._check_workspace_ready(ok):
            return
        stats = handle.bridge.stats()
        self.send_json(ok(stats.model_dump(), workspace_id=ws_id))

    def handle_indexes(self, ws_id: str, remaining: str, query: str):
        handle, ok = self._resolve_workspace(ws_id)
        if not self._check_workspace_ready(ok):
            return

        parts = remaining.split("/")
        if len(parts) == 1 or (len(parts) == 2 and not parts[1]):
            entries, current_index_id, persistence_model, schema_version = handle.bridge.list_indexes()
            result = {
                "current_index_id": current_index_id,
                "persistence_model": persistence_model,
                "schema_version": schema_version,
                "indexes": [{"index_id": e.index_id, "timestamp": e.timestamp, "root": e.root} for e in entries],
            }
            self.send_json(ok(result, workspace_id=ws_id))
        else:
            index_id = parts[1]
            entries, _, _, _ = handle.bridge.list_indexes()
            for entry in entries:
                if entry.index_id == index_id:
                    return self.send_json(ok(entry.model_dump(), workspace_id=ws_id))
            self.send_json(err("artifact_not_found", f"Index not found: {index_id}"), status=404)

    def handle_artifacts(self, ws_id: str, remaining: str, query: str):
        handle, ok = self._resolve_workspace(ws_id)
        if not self._check_workspace_ready(ok):
            return

        params = parse_qs(query)
        artifact_type = params.get("type", [None])[0]
        limit = int(params.get("limit", [200])[0])

        parts = remaining.split("/")
        if len(parts) == 1 or ":search" in remaining:
            if artifact_type and artifact_type not in KNOWN_ARTIFACT_TYPES:
                return self.send_json(err("unknown_artifact_type", f"Unknown: {artifact_type}"), status=400)

            if artifact_type:
                records = handle.bridge.get_artifacts_by_type(artifact_type, limit=limit)
            else:
                records = []
                for t in handle.bridge.list_artifact_types()[:20]:
                    records.extend(handle.bridge.get_artifacts_by_type(t, limit=10))

            result = [r.model_dump(exclude_none=True) for r in records]
            self.send_json(ok(result, workspace_id=ws_id))
        else:
            at = parts[1]
            if at not in KNOWN_ARTIFACT_TYPES:
                return self.send_json(err("unknown_artifact_type", f"Unknown: {at}"), status=400)

            try:
                data = handle.loader.load_json(at)
            except Exception as exc:
                return self.send_json(err("artifact_not_found", str(exc)), status=404)

            self.send_json(ok({"artifact_type": at, "data": data}, workspace_id=ws_id))

    def handle_file_content(self, ws_id: str, query: str):
        handle, ok = self._resolve_workspace(ws_id)
        if not self._check_workspace_ready(ok):
            return

        params = parse_qs(query)
        path = params.get("path", [""])[0]
        with_entities = params.get("with_entities", ["false"])[0] == "true"

        if not path or path.startswith("/") or ".." in path:
            return self.send_json(err("invalid_argument", "Invalid path"), status=400)

        try:
            content = build_file_content_response(
                path,
                root=handle.ctn_dir.parent,
                include_entities=with_entities,
            )
        except FileNotFoundError:
            return self.send_json(err("artifact_not_found", f"File not found: {path}"), status=404)
        except Exception as exc:
            return self.send_json(err("internal_error", str(exc)), status=500)

        self.send_json(ok(content, workspace_id=ws_id))

    def handle_files(self, ws_id: str, query: str):
        handle, ok = self._resolve_workspace(ws_id)
        if not self._check_workspace_ready(ok):
            return

        params = parse_qs(query)
        prefix = params.get("prefix", [None])[0]
        limit = int(params.get("limit", [1000])[0])

        artifact_type = "source_file_entry"
        records = handle.bridge.get_artifacts_by_type(artifact_type, limit=limit)

        files = []
        for r in records:
            lp = r.logical_path
            if prefix is None or lp.startswith(prefix):
                files.append({"logical_path": lp, "size_bytes": r.size_bytes})

        self.send_json(ok(files, workspace_id=ws_id))

    def handle_bsg(self, ws_id: str, remaining: str, query: str):
        handle, ok = self._resolve_workspace(ws_id)
        if not self._check_workspace_ready(ok):
            return

        params = parse_qs(query)
        index_id = params.get("index_id", [None])[0]

        if "/search" in remaining:
            q = params.get("q", [""])[0]
            kinds = params.get("kinds", [None])[0]
            limit = int(params.get("limit", [50])[0])

            try:
                bsg_data = handle.loader.load_json("bsg_json", index_id=index_id)
            except Exception as exc:
                return self.send_json(err("artifact_not_found", str(exc)), status=404)

            kind_list = kinds.split(",") if kinds else None
            hits = search_bsg_nodes(bsg_data, query=q, kinds=kind_list, limit=limit)
            self.send_json(ok(hits, workspace_id=ws_id))
        else:
            try:
                data = handle.loader.load_json("bsg_json", index_id=index_id)
            except Exception as exc:
                return self.send_json(err("artifact_not_found", str(exc)), status=404)
            self.send_json(ok(data, workspace_id=ws_id))

    def handle_context(self, ws_id: str, remaining: str):
        handle, ok = self._resolve_workspace(ws_id)
        if not self._check_workspace_ready(ok):
            return

        parts = remaining.split("/")
        ctx_type = parts[1] if len(parts) > 1 else None

        artifact = "context_overview_json" if ctx_type == "overview" else "context_files_json"

        try:
            data = handle.loader.load_json(artifact)
        except Exception as exc:
            return self.send_json(err("artifact_not_found", str(exc)), status=404)

        self.send_json(ok(data, workspace_id=ws_id))

    def handle_graph(self, ws_id: str, query: str):
        handle, ok = self._resolve_workspace(ws_id)
        if not self._check_workspace_ready(ok):
            return

        params = parse_qs(query)
        index_id = params.get("index_id", [None])[0]

        try:
            data = handle.loader.load_json("graph_json", index_id=index_id)
        except Exception as exc:
            return self.send_json(err("artifact_not_found", str(exc)), status=404)

        self.send_json(ok(data, workspace_id=ws_id))

    def handle_patches(self, ws_id: str, remaining: str, query: str):
        handle, ok = self._resolve_workspace(ws_id)
        if not self._check_workspace_ready(ok):
            return

        parts = remaining.split("/")
        if len(parts) == 1:
            try:
                data = handle.loader.load_json("patches_index_json")
            except Exception as exc:
                return self.send_json(err("artifact_not_found", str(exc)), status=404)
            self.send_json(ok(data, workspace_id=ws_id))
        else:
            op_id = parts[1]
            try:
                data = handle.loader.load_json(f"patch_{op_id}")
            except Exception as exc:
                return self.send_json(err("artifact_not_found", str(exc)), status=404)
            self.send_json(ok(data, workspace_id=ws_id))

    def handle_snapshots(self, ws_id: str, remaining: str, query: str):
        handle, ok = self._resolve_workspace(ws_id)
        if not self._check_workspace_ready(ok):
            return

        params = parse_qs(query)
        base = params.get("base", [""])[0]
        new = params.get("new", [""])[0]

        if not base or not new:
            return self.send_json(err("invalid_argument", "base and new parameters required"), status=400)

        try:
            base_data = handle.loader.load_json(f"snapshot_{base}")
            new_data = handle.loader.load_json(f"snapshot_{new}")
        except Exception as exc:
            return self.send_json(err("artifact_not_found", str(exc)), status=404)

        from batho.bridge.hub import _compute_diff

        diff = _compute_diff(base_data, new_data)
        self.send_json(ok(diff, workspace_id=ws_id))


def create_hub_server(
    manager: WorkspaceManager,
    *,
    host: str = "127.0.0.1",
    port: int = DEFAULT_HUB_REST_PORT,
    default_workspace: str | None = None,
    registry: WorkspaceRegistry | None = None,
    dashboard_dir: Path | None = None,
) -> HTTPServer:
    """Create and configure the hub HTTP server."""

    class ConfiguredHandler(HubHTTPHandler):
        pass

    server = HTTPServer((host, port), ConfiguredHandler)
    # Set configuration attributes on HTTPServer instance for thread isolation
    server.manager = manager
    server.default_workspace = default_workspace
    server.registry = registry
    server.dashboard_dir = dashboard_dir
    LOGGER.info("hub_http_server_created", host=host, port=port)
    return server


__all__ = [
    "HubHTTPHandler",
    "create_hub_server",
]
