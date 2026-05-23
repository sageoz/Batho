"""HTTP API handler for the Batho dashboard bridge endpoints."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from batho.bridge.envelope import err, ok
from batho.utils.logging import get_logger

LOGGER = get_logger(__name__, component="bridge.http_api")


class BridgeAPIHandler:
    """HTTP API handler for dashboard bridge endpoints."""

    def __init__(self, ctn_dir: Path):
        self._ctn_dir = ctn_dir
        self._index = None

    def _load_index(self) -> dict | None:
        """Load index metadata from the .batho database."""
        if self._index is not None:
            return self._index
        try:
            from batho.context.storage import get_artifact_registry
            db = get_artifact_registry(self._ctn_dir)
            run_id = db.get_latest_run_id()
            if not run_id:
                return None
            self._index = {
                "current_index_id": run_id,
                "schema_version": "batho-db.v1",
                "indexes": {run_id: {"created_at": "", "artifact_count": 0}},
            }
            return self._index
        except Exception as e:
            LOGGER.warning("failed_to_load_index", error=str(e))
        return None

    def dispatch(self, path: str, query: dict[str, list[str]]) -> tuple[bytes, int, dict[str, str]]:
        """Dispatch an API request to the appropriate handler."""
        if path.startswith("/api/v1/bridge/"):
            path = path[len("/api/v1/bridge/"):]
        elif path.startswith("/api/v1/"):
            path = path[len("/api/v1/"):]

        try:
            if path == "indexes":
                return self._handle_indexes(query)
            elif path.startswith("artifacts/bsg_json"):
                return self._handle_bsg_json(path, query)
            elif path.startswith("artifacts/context_overview_json"):
                return self._handle_context_overview_json(path, query)
            elif path.startswith("artifacts/context_files_json"):
                return self._handle_context_files_json(path, query)
            elif path == "patches":
                return self._handle_patches(query)
            elif path.startswith("patches/"):
                return self._handle_patch(path, query)
            elif path.startswith("snapshots/diff"):
                return self._handle_snapshots_diff(path, query)
            elif path == "artifacts/metrics_json":
                return self._handle_metrics_json(query)
            elif path.startswith("file-content"):
                return self._handle_file_content(path, query)
            elif path == "config":
                return self._handle_config(query)
            elif path.startswith("config/"):
                return self._handle_config_sub(path, query)
            elif path == "workspaces":
                return self._handle_workspaces(query)
            elif path.startswith("workspaces/"):
                return self._handle_workspace(path, query)
            elif path.startswith("agents/"):
                return self._handle_agents(path, query)
            elif path == "admin/discover":
                return self._handle_admin_discover(query)
            elif path.startswith("fs/"):
                return self._handle_fs(path, query)
            elif path in ["healthz", "readyz", "metrics"]:
                return self._handle_health(path)
            else:
                return self._not_found(path)
        except Exception as e:
            LOGGER.error("api_error", path=path, error=str(e))
            body = json.dumps(err("internal_error", str(e)))
            return body.encode(), 500, {"Content-Type": "application/json"}

    def dispatch_post(self, path: str, query: dict[str, list[str]], body: dict[str, Any]) -> tuple[bytes, int, dict[str, str]]:
        """Dispatch a POST request to the appropriate handler."""
        if path.startswith("/api/v1/bridge/"):
            path = path[len("/api/v1/bridge/"):]
        elif path.startswith("/api/v1/"):
            path = path[len("/api/v1/"):]

        try:
            if path == "workspaces":
                return self._handle_create_workspace(body)
            elif path.startswith("workspaces/"):
                return self._handle_workspace_action(path, body)
            elif path == "reconstruct":
                return self._handle_reconstruct(body)
            else:
                return self._not_found(path)
        except Exception as e:
            LOGGER.error("api_post_error", path=path, error=str(e))
            response = json.dumps(err("internal_error", str(e)))
            return response.encode(), 500, {"Content-Type": "application/json"}

    def _ok(self, data: Any) -> tuple[bytes, int, dict[str, str]]:
        """Create a successful response."""
        body = json.dumps(ok(data))
        return body.encode(), 200, {"Content-Type": "application/json"}

    def _not_found(self, path: str) -> tuple[bytes, int, dict[str, str]]:
        """Create a not found response."""
        body = json.dumps(err("not_found", f"Endpoint not found: {path}"))
        return body.encode(), 404, {"Content-Type": "application/json"}

    def _handle_indexes(self, query: dict[str, list[str]]) -> tuple[bytes, int, dict[str, str]]:
        """Handle /indexes endpoint."""
        index = self._load_index()
        if not index:
            return self._ok({"indexes": [], "current_index_id": None})

        indexes = []
        for idx_id, idx_data in (index.get("indexes") or {}).items():
            indexes.append({
                "id": idx_id,
                "created_at": idx_data.get("created_at"),
                "artifact_count": idx_data.get("artifact_count", 0),
            })

        current = index.get("current_index_id")
        return self._ok({
            "indexes": indexes,
            "current_index_id": current,
            "schema_version": index.get("schema_version", "1.0"),
        })

    def _handle_bsg_json(self, path: str, query: dict[str, list[str]]) -> tuple[bytes, int, dict[str, str]]:
        """Handle /artifacts/bsg_json endpoint."""
        index_id = query.get("index_id", [None])[0]
        try:
            from batho.context.storage import get_artifact_registry
            db = get_artifact_registry(self._ctn_dir)
            run_id = index_id or db.get_latest_run_id()
            if run_id:
                entries = db.get_bsg_entries_for_run(run_id)
                return self._ok({"entries": entries})
        except Exception as e:
            LOGGER.warning("failed_to_load_bsg", error=str(e))
        return self._ok({"entities": []})

    def _handle_context_overview_json(self, path: str, query: dict[str, list[str]]) -> tuple[bytes, int, dict[str, str]]:
        """Handle /artifacts/context_overview_json endpoint."""
        index_id = query.get("index_id", [None])[0]
        try:
            from batho.context.storage import get_artifact_registry
            db = get_artifact_registry(self._ctn_dir)
            run_id = index_id or db.get_latest_run_id()
            if run_id:
                output = db.get_context_output(run_id, "overview")
                if output:
                    return self._ok(json.loads(output))
        except Exception as e:
            LOGGER.warning("failed_to_load_overview", error=str(e))
        return self._ok({"file_distribution": [], "total_entities": 0})

    def _handle_context_files_json(self, path: str, query: dict[str, list[str]]) -> tuple[bytes, int, dict[str, str]]:
        """Handle /artifacts/context_files_json endpoint."""
        index_id = query.get("index_id", [None])[0]
        try:
            from batho.context.storage import get_artifact_registry
            db = get_artifact_registry(self._ctn_dir)
            run_id = index_id or db.get_latest_run_id()
            if run_id:
                output = db.get_context_output(run_id, "files")
                if output:
                    return self._ok(json.loads(output))
        except Exception as e:
            LOGGER.warning("failed_to_load_files", error=str(e))
        return self._ok({"categories": []})

    def _handle_patches(self, query: dict[str, list[str]]) -> tuple[bytes, int, dict[str, str]]:
        """Handle /patches endpoint."""
        try:
            from batho.time_machine import list_patch_operations
            ops = list_patch_operations(self._ctn_dir)
            patches = [
                {
                    "id": op.operation_id,
                    "created_at": op.timestamp.isoformat(),
                    "operation_type": op.operation_type,
                    "status": "completed",
                }
                for op in ops
            ]
        except Exception:
            patches = []
        return self._ok({"patches": patches, "schema_version": "1.0"})

    def _handle_patch(self, path: str, query: dict[str, list[str]]) -> tuple[bytes, int, dict[str, str]]:
        """Handle /patches/{operationId} endpoint."""
        patch_id = path.split("/")[-1]
        try:
            from batho.time_machine import load_patch_operation
            op = load_patch_operation(self._ctn_dir, patch_id)
            if op:
                return self._ok(op.serialize())
        except Exception as e:
            return self._ok({"error": str(e)})
        return self._ok({"error": "Patch not found"})

    def _handle_snapshots_diff(self, path: str, query: dict[str, list[str]]) -> tuple[bytes, int, dict[str, str]]:
        """Handle /snapshots/diff endpoint."""
        base = query.get("base", [None])[0]
        new = query.get("new", [None])[0]

        if not base or not new:
            return self._ok({"error": "Missing base or new parameter"})

        try:
            from batho.time_machine import load_snapshot, diff_snapshots
            base_data = load_snapshot(self._ctn_dir, base)
            new_data = load_snapshot(self._ctn_dir, new)
            if not base_data or not new_data:
                return self._ok({"error": "Snapshot not found"})
            diff = diff_snapshots(base_data, new_data)
            return self._ok({"base": base_data.get("stats"), "new": new_data.get("stats"), "diff": diff})
        except Exception as e:
            return self._ok({"error": str(e)})

    def _handle_metrics_json(self, query: dict[str, list[str]]) -> tuple[bytes, int, dict[str, str]]:
        """Handle /artifacts/metrics_json endpoint."""
        index_id = query.get("index_id", [None])[0]
        try:
            from batho.context.storage import get_artifact_registry
            db = get_artifact_registry(self._ctn_dir)
            run_id = index_id or db.get_latest_run_id()
            if run_id:
                output = db.get_context_output(run_id, "metrics")
                if output:
                    return self._ok(json.loads(output))
        except Exception as e:
            LOGGER.warning("failed_to_load_metrics", error=str(e))
        return self._ok({"metrics": {}})

    def _handle_file_content(self, path: str, query: dict[str, list[str]]) -> tuple[bytes, int, dict[str, str]]:
        """Handle /file-content endpoint."""
        file_path = query.get("path", [None])[0]
        if not file_path:
            return self._ok({"error": "Missing path parameter"})

        full_path = (self._ctn_dir / file_path.lstrip("/")).resolve()
        if full_path.exists() and full_path.is_file():
            try:
                content = full_path.read_text()
                return self._ok({
                    "path": file_path,
                    "content": content,
                    "size": len(content),
                })
            except Exception as e:
                return self._ok({"error": str(e)})

        return self._ok({"error": "File not found"})

    def _handle_config(self, query: dict[str, list[str]]) -> tuple[bytes, int, dict[str, str]]:
        """Handle /config endpoint."""
        return self._ok({
            "server": {"host": "127.0.0.1", "port": 8765, "transport": "sse"},
            "residency": {"enabled": True, "max_workspaces": 10},
            "concurrency": {"max_concurrent_requests": 50},
            "discovery": {"auto_discover": True, "scan_on_startup": True},
        })

    def _handle_config_sub(self, path: str, query: dict[str, list[str]]) -> tuple[bytes, int, dict[str, str]]:
        """Handle /config/* sub-endpoints."""
        sub = path.split("/")[-1]
        if sub == "server":
            return self._ok({"host": "127.0.0.1", "port": 8765, "transport": "sse"})
        elif sub == "residency":
            return self._ok({"enabled": True, "max_workspaces": 10})
        elif sub == "concurrency":
            return self._ok({"max_concurrent_requests": 50})
        elif sub == "discovery":
            return self._ok({"auto_discover": True, "scan_on_startup": True})
        return self._not_found(path)

    def _handle_workspaces(self, query: dict[str, list[str]]) -> tuple[bytes, int, dict[str, str]]:
        """Handle /workspaces endpoint."""
        return self._ok([])

    def _handle_workspace(self, path: str, query: dict[str, list[str]]) -> tuple[bytes, int, dict[str, str]]:
        """Handle /workspaces/{id} endpoint."""
        parts = path.split("/")
        if len(parts) >= 2:
            ws_id = parts[1]
            return self._ok({"id": ws_id, "error": "Workspace not found"})
        return self._not_found(path)

    def _handle_create_workspace(self, body: dict[str, Any]) -> tuple[bytes, int, dict[str, str]]:
        """Handle POST /workspaces to create a new workspace."""
        ws_id = body.get("id")
        ctn_dir = body.get("ctn_dir")
        label = body.get("label", "")
        tags = body.get("tags", [])
        pinned = body.get("pinned", False)
        
        if not ctn_dir:
            return self._ok({"error": "ctn_dir is required"})
        
        if not ws_id:
            ws_id = re.sub(r'[^a-z0-9-]', '-', ctn_dir.split("/")[-1].lower())
        
        LOGGER.info("create_workspace", id=ws_id, ctn_dir=ctn_dir, label=label, tags=tags, pinned=pinned)
        
        return self._ok({
            "id": ws_id,
            "ctn_dir": ctn_dir,
            "label": label,
            "tags": tags,
            "pinned": pinned,
            "resident": pinned,
            "status": "active"
        })

    def _handle_workspace_action(self, path: str, body: dict[str, Any]) -> tuple[bytes, int, dict[str, str]]:
        """Handle POST /workspaces/{id} for workspace actions."""
        parts = path.split("/")
        if len(parts) >= 2:
            ws_id = parts[1]
            action = body.get("action", "update")
            
            LOGGER.info("workspace_action", id=ws_id, action=action)
            
            return self._ok({"id": ws_id, "action": action, "status": "ok"})
        
        return self._not_found(path)

    def _handle_reconstruct(self, body: dict[str, Any]) -> tuple[bytes, int, dict[str, str]]:
        """Handle POST /reconstruct — reconstruct a file from BSG entities."""
        from batho.context.reconstructor import FileReconstructor, ReconstructionError, IntegrityError

        file_path = body.get("file_path", "")
        if not file_path:
            body_resp = json.dumps(err("invalid_request", "file_path is required"))
            return body_resp.encode(), 400, {"Content-Type": "application/json"}

        index = self._load_index()
        if not index:
            body_resp = json.dumps(err("no_index", "No index found"))
            return body_resp.encode(), 404, {"Content-Type": "application/json"}

        current_id = index.get("current_index_id")
        if not current_id:
            body_resp = json.dumps(err("no_index", "No current index"))
            return body_resp.encode(), 404, {"Content-Type": "application/json"}

        # Load graph JSON
        graph_path = self._ctn_dir / current_id / "graph.json"
        if not graph_path.exists():
            body_resp = json.dumps(err("graph_not_found", "graph.json not found"))
            return body_resp.encode(), 404, {"Content-Type": "application/json"}

        try:
            import json as _json
            graph_data = _json.loads(graph_path.read_text())
            from batho.context.codegraph import InMemoryGraph

            graph = InMemoryGraph.from_dict(graph_data)

            # Enrich entities with raw_content and raw_bytes from storage view if available
            storage_view_path = self._ctn_dir / current_id / "bsg_storage_view.json"
            if storage_view_path.exists():
                try:
                    storage_view_data = _json.loads(storage_view_path.read_text(encoding="utf-8"))
                    graph.enrich_from_storage_view(storage_view_data)
                except Exception as exc:
                    LOGGER.warning("storage_view_load_failed_http_api", error=str(exc))

            entities = list(graph.entities_by_file(file_path))
            if not entities:
                body_resp = json.dumps(err("no_entities", f"No entities for: {file_path}"))
                return body_resp.encode(), 404, {"Content-Type": "application/json"}

            reconstructor = FileReconstructor()
            result = reconstructor.reconstruct_file(
                file_path=file_path,
                entities=entities,
            )
            body_resp = json.dumps(ok(result.model_dump()))
            return body_resp.encode(), 200, {"Content-Type": "application/json"}
        except (ReconstructionError, IntegrityError) as exc:
            body_resp = json.dumps(err("reconstruct_error", str(exc)))
            return body_resp.encode(), 422, {"Content-Type": "application/json"}
        except Exception as exc:
            body_resp = json.dumps(err("internal_error", str(exc)))
            return body_resp.encode(), 500, {"Content-Type": "application/json"}

    def _handle_agents(self, path: str, query: dict[str, list[str]]) -> tuple[bytes, int, dict[str, str]]:
        """Handle /agents/* endpoints."""
        if path.startswith("agents/snippets/"):
            agent = path.split("/")[-1]
            return self._ok({"agent": agent, "snippets": []})
        return self._not_found(path)

    def _handle_admin_discover(self, query: dict[str, list[str]]) -> tuple[bytes, int, dict[str, str]]:
        """Handle /admin/discover endpoint."""
        return self._ok({"discovered": [], "message": "Discovery not available"})

    def _handle_fs(self, path: str, query: dict[str, list[str]]) -> tuple[bytes, int, dict[str, str]]:
        """Handle /fs/* endpoints."""
        if path.startswith("fs/browse"):
            at_path = query.get("at", [None])[0]
            if not at_path:
                at_path = str(Path.home())
            
            try:
                abs_path = Path(at_path).expanduser().resolve()
                if not abs_path.exists():
                    return self._ok({"path": at_path, "entries": [], "error": "Path does not exist"})
                if not abs_path.is_dir():
                    return self._ok({"path": at_path, "entries": [], "error": "Path is not a directory"})
                
                entries = []
                try:
                    for name in sorted(os.listdir(abs_path)):
                        try:
                            entry_path = abs_path / name
                            is_dir = entry_path.is_dir()
                            entries.append({
                                "name": name,
                                "path": str(entry_path),
                                "is_dir": is_dir,
                                "is_batho": name == ".batho" and not is_dir
                            })
                        except PermissionError:
                            continue
                except PermissionError:
                    return self._ok({"path": at_path, "entries": [], "error": "Permission denied"})
                
                return self._ok({"path": str(abs_path), "entries": entries})
            except Exception as e:
                LOGGER.warning("fs_browse_error", path=at_path, error=str(e))
                return self._ok({"path": at_path, "entries": [], "error": str(e)})
        return self._not_found(path)

    def _handle_health(self, path: str) -> tuple[bytes, int, dict[str, str]]:
        """Handle health check endpoints."""
        if path == "healthz":
            return self._ok({"status": "ok"})
        elif path == "readyz":
            return self._ok({"status": "ready"})
        elif path == "metrics":
            return self._ok({"requests_total": 0, "errors_total": 0})
        return self._not_found(path)
