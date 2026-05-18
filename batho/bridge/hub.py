"""MCP hub with multi-workspace tool surface."""

from __future__ import annotations

import json
from typing import Any

from batho.bridge.constants import KNOWN_ARTIFACT_TYPES
from batho.bridge.cross import search_bsg_nodes
from batho.bridge.envelope import err, ok, to_json
from batho.bridge.file_outline import build_file_outline
from batho.bridge.file_service import build_file_content_response
from batho.bridge.workspace_handle import WorkspaceHandle
from batho.bridge.workspace_manager import WorkspaceManager
from batho.bridge.telemetry import get_collector
from batho.utils.logging import get_logger

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as exc:
    raise ImportError(
        "The 'mcp' package is required for the MCP hub. "
        "Install it with: pip install mcp>=1.0.0"
    ) from exc

LOGGER = get_logger(__name__, component="bridge.hub")


def _log_tool_call(tool_name: str, workspace_id: str | None, args: dict | None = None):
    """Log MCP tool call with structured fields."""
    import hashlib
    import time

    collector = get_collector()
    start_time = time.time()

    args_hash = "none"
    if args:
        args_str = json.dumps(args, sort_keys=True)
        args_hash = hashlib.md5(args_str.encode()).hexdigest()[:8]

    LOGGER.debug(
        "mcp_tool_call",
        tool=tool_name,
        workspace_id=workspace_id,
        args_hash=args_hash,
    )

    return start_time, collector


def _log_tool_result(
    tool_name: str,
    workspace_id: str | None,
    start_time: float,
    collector,
    status: str,
    error: str | None = None,
):
    """Log MCP tool result with latency and status."""
    import time

    latency_ms = (time.time() - start_time) * 1000

    collector.record_tool_call(tool_name, workspace_id, status)
    collector.record_tool_latency(tool_name, latency_ms / 1000)

    if error:
        LOGGER.info(
            "mcp_tool_complete",
            tool=tool_name,
            workspace_id=workspace_id,
            latency_ms=latency_ms,
            status=status,
            error=error,
        )
    else:
        LOGGER.debug(
            "mcp_tool_complete",
            tool=tool_name,
            workspace_id=workspace_id,
            latency_ms=latency_ms,
            status=status,
        )


def create_hub(manager: WorkspaceManager) -> FastMCP:
    """Create a FastMCP hub bound to a WorkspaceManager."""
    mcp = FastMCP("batho-hub")

    async def _resolve(workspace_id: str | None = None) -> WorkspaceHandle:
        """Resolve a workspace handle, raising on error."""
        handle = await manager.resolve(workspace_id)
        if not handle.is_ready:
            if handle.is_degraded:
                raise RuntimeError(f"Workspace {handle.workspace_id} is in degraded state")
            raise RuntimeError(f"Workspace {handle.workspace_id} is not ready")
        return handle

    # =========================================================================
    # Workspace introspection
    # =========================================================================

    @mcp.tool()
    async def workspace_list() -> str:
        """List all registered workspaces."""
        workspaces = manager.list()
        resident_ids = {h.workspace_id for h in manager.resident()}
        result = []
        for ws in workspaces:
            data = ws.model_dump()
            data["resident"] = ws.id in resident_ids
            result.append(data)
        return to_json(ok(result))

    @mcp.tool()
    async def workspace_health(workspace_id: str | None = None) -> str:
        """Get health status of all or specific workspace."""
        health_list = await manager.health_check(workspace_id)
        result = [h.model_dump() for h in health_list]
        return to_json(ok(result))

    @mcp.tool()
    async def workspace_stats(workspace_id: str | None = None) -> str:
        """Get registry statistics for a workspace."""
        try:
            handle = await _resolve(workspace_id)
            stats = handle.bridge.stats()
            return to_json(ok(stats.model_dump(), workspace_id=handle.workspace_id))
        except (RuntimeError, KeyError, ValueError) as exc:
            return to_json(err("workspace_error", str(exc)))

    # =========================================================================
    # Index / artifact tools
    # =========================================================================

    @mcp.tool()
    async def index_list(workspace_id: str | None = None) -> str:
        """List all available index IDs and timestamps."""
        try:
            handle = await _resolve(workspace_id)
            entries, current_index_id, persistence_model, schema_version = handle.bridge.list_indexes()
            result = {
                "current_index_id": current_index_id,
                "persistence_model": persistence_model,
                "schema_version": schema_version,
                "indexes": [
                    {
                        "index_id": e.index_id,
                        "timestamp": e.timestamp,
                        "root": e.root,
                        "file_count": e.file_count,
                        "entity_count": e.entity_count,
                    }
                    for e in entries
                ],
            }
            return to_json(ok(result, workspace_id=handle.workspace_id))
        except (RuntimeError, KeyError, ValueError) as exc:
            return to_json(err("workspace_error", str(exc)))

    @mcp.tool()
    async def index_get(index_id: str, workspace_id: str | None = None) -> str:
        """Get metadata for a specific index."""
        try:
            handle = await _resolve(workspace_id)
            entries, _, _, _ = handle.bridge.list_indexes()
            for entry in entries:
                if entry.index_id == index_id:
                    return to_json(ok(entry.model_dump(), workspace_id=handle.workspace_id))
            return to_json(err("artifact_not_found", f"Index not found: {index_id}"))
        except (RuntimeError, KeyError, ValueError) as exc:
            return to_json(err("workspace_error", str(exc)))

    @mcp.tool()
    async def artifact_list(
        artifact_type: str | None = None,
        limit: int | None = None,
        workspace_id: str | None = None,
    ) -> str:
        """List artifact records, optionally filtered by type."""
        try:
            handle = await _resolve(workspace_id)
            if artifact_type and artifact_type not in KNOWN_ARTIFACT_TYPES:
                return to_json(
                    err(
                        "unknown_artifact_type",
                        f"Unknown artifact type: {artifact_type}",
                        detail={"known_types": sorted(KNOWN_ARTIFACT_TYPES)},
                    )
                )

            if artifact_type:
                records = handle.bridge.get_artifacts_by_type(artifact_type, limit=limit or 200)
            else:
                records = []
                for t in handle.bridge.list_artifact_types()[:20]:
                    records.extend(handle.bridge.get_artifacts_by_type(t, limit=10))

            result = [r.model_dump(exclude_none=True) for r in records]
            return to_json(ok(result, workspace_id=handle.workspace_id))
        except (RuntimeError, KeyError, ValueError) as exc:
            return to_json(err("workspace_error", str(exc)))

    @mcp.tool()
    async def artifact_get(
        artifact_type: str,
        index_id: str | None = None,
        workspace_id: str | None = None,
    ) -> str:
        """Load and return full JSON content for an artifact type."""
        try:
            handle = await _resolve(workspace_id)
            if artifact_type not in KNOWN_ARTIFACT_TYPES:
                return to_json(
                    err(
                        "unknown_artifact_type",
                        f"Unknown artifact type: {artifact_type}",
                        detail={"known_types": sorted(KNOWN_ARTIFACT_TYPES)},
                    )
                )

            try:
                data = handle.loader.load_json(artifact_type, index_id=index_id)
            except Exception as exc:
                return to_json(err("artifact_not_found", str(exc)))

            return to_json(ok({"artifact_type": artifact_type, "data": data}, workspace_id=handle.workspace_id))
        except (RuntimeError, KeyError, ValueError) as exc:
            return to_json(err("workspace_error", str(exc)))

    @mcp.tool()
    async def artifact_get_by_path(logical_path: str, workspace_id: str | None = None) -> str:
        """Load artifact content by its exact logical path."""
        try:
            handle = await _resolve(workspace_id)
            record = handle.bridge.get_artifact_by_logical_path(logical_path)
            if not record:
                return to_json(err("artifact_not_found", f"No artifact at path: {logical_path}"))

            try:
                content = handle.loader.load_artifact(record)
            except Exception as exc:
                return to_json(err("artifact_parse_error", str(exc)))

            return to_json(
                ok(
                    {
                        "record": record.model_dump(exclude_none=True),
                        "data": content.data,
                        "resolved_path": str(content.resolved_path),
                        "checksum_verified": content.checksum_verified,
                    },
                    workspace_id=handle.workspace_id,
                )
            )
        except (RuntimeError, KeyError, ValueError) as exc:
            return to_json(err("workspace_error", str(exc)))

    @mcp.tool()
    async def artifact_search(
        query: str,
        artifact_type: str | None = None,
        workspace_id: str | None = None,
    ) -> str:
        """Fuzzy search artifacts by logical path."""
        try:
            handle = await _resolve(workspace_id)
            records = handle.bridge.search_artifacts(query, artifact_type=artifact_type)
            result = [r.model_dump(exclude_none=True) for r in records]
            return to_json(ok(result, workspace_id=handle.workspace_id))
        except (RuntimeError, KeyError, ValueError) as exc:
            return to_json(err("workspace_error", str(exc)))

    # =========================================================================
    # File / code tools
    # =========================================================================

    @mcp.tool()
    async def file_read(
        path: str,
        with_entities: bool = False,
        workspace_id: str | None = None,
    ) -> str:
        """Read file content with optional BSG entity overlay."""
        try:
            handle = await _resolve(workspace_id)

            if path.startswith("/") or ".." in path:
                return to_json(err("invalid_argument", "Path must be relative and not contain '..'"))

            try:
                content = build_file_content_response(
                    path,
                    root=handle.ctn_dir.parent,
                    include_entities=with_entities,
                )
            except FileNotFoundError:
                return to_json(err("artifact_not_found", f"File not found: {path}"))
            except Exception as exc:
                return to_json(err("internal_error", str(exc)))

            return to_json(ok(content, workspace_id=handle.workspace_id))
        except (RuntimeError, KeyError, ValueError) as exc:
            return to_json(err("workspace_error", str(exc)))

    @mcp.tool()
    async def file_list(
        prefix: str | None = None,
        limit: int | None = None,
        workspace_id: str | None = None,
    ) -> str:
        """List tracked files in the workspace."""
        try:
            handle = await _resolve(workspace_id)
            artifact_type = "source_file_entry"
            records = handle.bridge.get_artifacts_by_type(artifact_type, limit=limit or 1000)

            files = []
            for r in records:
                lp = r.logical_path
                if prefix is None or lp.startswith(prefix):
                    files.append({"logical_path": lp, "size_bytes": r.size_bytes})

            return to_json(ok(files, workspace_id=handle.workspace_id))
        except (RuntimeError, KeyError, ValueError) as exc:
            return to_json(err("workspace_error", str(exc)))

    @mcp.tool()
    async def file_outline(path: str, workspace_id: str | None = None) -> str:
        """Return a nested outline for a file based on BSG line ranges."""
        try:
            handle = await _resolve(workspace_id)
            if path.startswith("/") or ".." in path:
                return to_json(err("invalid_argument", "Path must be relative and not contain '..'"))
            try:
                bsg_data = handle.loader.load_json("bsg_json")
            except Exception as exc:
                return to_json(err("artifact_not_found", str(exc)))
            outline = build_file_outline(bsg_data, path)
            return to_json(ok(outline, workspace_id=handle.workspace_id))
        except (RuntimeError, KeyError, ValueError) as exc:
            return to_json(err("workspace_error", str(exc)))

    # =========================================================================
    # BSG / context tools
    # =========================================================================

    @mcp.tool()
    async def bsg_get(index_id: str | None = None, workspace_id: str | None = None) -> str:
        """Get BSG JSON artifact."""
        try:
            handle = await _resolve(workspace_id)
            try:
                data = handle.loader.load_json("bsg_json", index_id=index_id)
            except Exception as exc:
                return to_json(err("artifact_not_found", str(exc)))
            return to_json(ok(data, workspace_id=handle.workspace_id))
        except (RuntimeError, KeyError, ValueError) as exc:
            return to_json(err("workspace_error", str(exc)))

    @mcp.tool()
    async def bsg_search(
        query: str,
        kinds: str | None = None,
        limit: int = 50,
        workspace_id: str | None = None,
    ) -> str:
        """Search BSG nodes by name/fqn/signature."""
        try:
            handle = await _resolve(workspace_id)
            try:
                bsg_data = handle.loader.load_json("bsg_json")
            except Exception as exc:
                return to_json(err("artifact_not_found", str(exc)))

            kind_list = [k.strip() for k in kinds.split(",")] if kinds else None
            hits = search_bsg_nodes(bsg_data, query=query, kinds=kind_list, limit=limit)
            return to_json(ok(hits, workspace_id=handle.workspace_id))
        except (RuntimeError, KeyError, ValueError) as exc:
            return to_json(err("workspace_error", str(exc)))

    @mcp.tool()
    async def context_overview(
        index_id: str | None = None,
        workspace_id: str | None = None,
    ) -> str:
        """Get context overview JSON."""
        try:
            handle = await _resolve(workspace_id)
            try:
                data = handle.loader.load_json("context_overview_json", index_id=index_id)
            except Exception as exc:
                return to_json(err("artifact_not_found", str(exc)))
            return to_json(ok(data, workspace_id=handle.workspace_id))
        except (RuntimeError, KeyError, ValueError) as exc:
            return to_json(err("workspace_error", str(exc)))

    @mcp.tool()
    async def context_files(
        index_id: str | None = None,
        workspace_id: str | None = None,
    ) -> str:
        """Get context files JSON."""
        try:
            handle = await _resolve(workspace_id)
            try:
                data = handle.loader.load_json("context_files_json", index_id=index_id)
            except Exception as exc:
                return to_json(err("artifact_not_found", str(exc)))
            return to_json(ok(data, workspace_id=handle.workspace_id))
        except (RuntimeError, KeyError, ValueError) as exc:
            return to_json(err("workspace_error", str(exc)))

    @mcp.tool()
    async def graph_get(index_id: str | None = None, workspace_id: str | None = None) -> str:
        """Get graph JSON artifact."""
        try:
            handle = await _resolve(workspace_id)
            try:
                data = handle.loader.load_json("graph_json", index_id=index_id)
            except Exception as exc:
                return to_json(err("artifact_not_found", str(exc)))
            return to_json(ok(data, workspace_id=handle.workspace_id))
        except (RuntimeError, KeyError, ValueError) as exc:
            return to_json(err("workspace_error", str(exc)))

    # =========================================================================
    # Patches / snapshots (read-only)
    # =========================================================================

    @mcp.tool()
    async def patches_list(workspace_id: str | None = None) -> str:
        """List available patches."""
        try:
            handle = await _resolve(workspace_id)
            try:
                data = handle.loader.load_json("patches_index_json")
            except Exception as exc:
                return to_json(err("artifact_not_found", str(exc)))
            return to_json(ok(data, workspace_id=handle.workspace_id))
        except (RuntimeError, KeyError, ValueError) as exc:
            return to_json(err("workspace_error", str(exc)))

    @mcp.tool()
    async def patches_get(operation_id: str, workspace_id: str | None = None) -> str:
        """Get a specific patch by operation ID."""
        try:
            handle = await _resolve(workspace_id)
            try:
                data = handle.loader.load_json(f"patch_{operation_id}")
            except Exception as exc:
                return to_json(err("artifact_not_found", str(exc)))
            return to_json(ok(data, workspace_id=handle.workspace_id))
        except (RuntimeError, KeyError, ValueError) as exc:
            return to_json(err("workspace_error", str(exc)))

    @mcp.tool()
    async def snapshot_diff(
        base: str,
        new: str,
        workspace_id: str | None = None,
    ) -> str:
        """Compare two snapshots."""
        try:
            handle = await _resolve(workspace_id)
            try:
                base_data = handle.loader.load_json(f"snapshot_{base}")
                new_data = handle.loader.load_json(f"snapshot_{new}")
            except Exception as exc:
                return to_json(err("artifact_not_found", str(exc)))

            diff = _compute_diff(base_data, new_data)
            return to_json(ok(diff, workspace_id=handle.workspace_id))
        except (RuntimeError, KeyError, ValueError) as exc:
            return to_json(err("workspace_error", str(exc)))

    # =========================================================================
    # Cross-repo tools (placeholders - implemented in cross.py)
    # =========================================================================

    @mcp.tool()
    async def cross_search(
        query: str,
        workspace_ids: str | None = None,
        tags: str | None = None,
        kinds: str | None = None,
        limit_per_ws: int = 25,
        merge_strategy: str = "score_desc",
        force_mount: bool = False,
    ) -> str:
        """Search across multiple workspaces."""
        from batho.bridge.cross import cross_search_impl

        ws_ids = workspace_ids.split(",") if workspace_ids else None
        tag_list = tags.split(",") if tags else None
        result, meta = await cross_search_impl(
            manager,
            query=query,
            workspace_ids=ws_ids,
            tags=tag_list,
            kinds=kinds.split(",") if kinds else None,
            limit_per_ws=limit_per_ws,
            merge_strategy=merge_strategy,
            force_mount=force_mount,
        )
        return to_json(ok(result, meta=meta))

    @mcp.tool()
    async def cross_symbols(
        name: str,
        workspace_ids: str | None = None,
        tags: str | None = None,
        kinds: str | None = None,
    ) -> str:
        """Locate a symbol across repos."""
        from batho.bridge.cross import cross_symbols_impl

        ws_ids = workspace_ids.split(",") if workspace_ids else None
        tag_list = tags.split(",") if tags else None
        kind_list = kinds.split(",") if kinds else None
        result, meta = await cross_symbols_impl(
            manager,
            name=name,
            workspace_ids=ws_ids,
            tags=tag_list,
            kinds=kind_list,
        )
        return to_json(ok(result, meta=meta))

    @mcp.tool()
    async def cross_dependencies(
        package: str,
        workspace_ids: str | None = None,
        tags: str | None = None,
    ) -> str:
        """Find which workspaces consume a package."""
        from batho.bridge.cross import cross_dependencies_impl

        ws_ids = workspace_ids.split(",") if workspace_ids else None
        tag_list = tags.split(",") if tags else None
        result, meta = await cross_dependencies_impl(
            manager,
            package=package,
            workspace_ids=ws_ids,
            tags=tag_list,
        )
        return to_json(ok(result, meta=meta))

    @mcp.tool()
    async def cross_workspaces_with_artifact(artifact_type: str) -> str:
        """Find workspaces that have a specific artifact type."""
        from batho.bridge.cross import cross_workspaces_with_artifact_impl

        result, meta = await cross_workspaces_with_artifact_impl(manager, artifact_type=artifact_type)
        return to_json(ok(result, meta=meta))

    # =========================================================================
    # Resources (Discovery)
    # =========================================================================

    @mcp.resource("batho://workspace/{workspace_id}/index.json")
    async def get_workspace_index(workspace_id: str) -> str:
        """Return index.json content for a specific workspace."""
        try:
            handle = await _resolve(workspace_id)
            index = await handle.get_index()
            return json.dumps(index)
        except (RuntimeError, KeyError, ValueError) as exc:
            return json.dumps({"error": str(exc)})

    @mcp.resource("batho://workspaces/list")
    async def list_workspaces_resource() -> str:
        """List all registered workspaces with metadata."""
        try:
            workspaces = []
            from datetime import datetime

            for ws_config in manager.list():
                # We try to get a handle to get live stats, but don't force mount
                handle = manager.get(ws_config.id)
                last_time = None
                if handle and handle.last_index_time:
                    last_time = datetime.fromtimestamp(handle.last_index_time).isoformat()

                workspaces.append(
                    {
                        "id": ws_config.id,
                        "label": ws_config.label,
                        "enabled": ws_config.enabled,
                        "ctn_dir": str(ws_config.ctn_dir),
                        "artifact_count": handle.artifact_count if handle else 0,
                        "last_index_time": last_time,
                    }
                )
            return json.dumps(workspaces)
        except Exception as exc:
            return json.dumps({"error": str(exc)})

    # =========================================================================
    # Prompts (Affordances)
    # =========================================================================

    @mcp.prompt()
    def find_symbol(name: str, workspace_id: str | None = None) -> str:
        """Prompt to find a symbol across workspaces."""
        if workspace_id:
            return (
                f"Search for symbol '{name}' in workspace '{workspace_id}' "
                f"using bridge_search_artifacts with query='symbol:{name}*'"
            )
        return f"Search for symbol '{name}' across all workspaces using cross.search with query='{name}'"

    @mcp.prompt()
    def summarise_workspace(workspace_id: str) -> str:
        """Prompt to generate workspace overview."""
        return f"Use context.overview for workspace '{workspace_id}' to summarize the codebase structure and purpose"

    @mcp.prompt()
    def cross_repo_search(query: str, workspace_ids: list[str] | None = None) -> str:
        """Prompt for cross-repo search."""
        ws_filter = f"workspaces={','.join(workspace_ids)}" if workspace_ids else "all workspaces"
        return f"Search across {ws_filter} for '{query}' using cross.search"

    return mcp


def _search_bsg(
    bsg_data: dict,
    query: str,
    kind_filter: set[str] | None,
    limit: int,
) -> list[dict]:
    """In-memory fuzzy search over BSG nodes."""
    import re

    query_lower = query.lower()
    hits = []

    entities = bsg_data.get("entities", [])
    for entity in entities:
        name = entity.get("name", "")
        fqn = entity.get("fqn", "")
        signature = entity.get("signature", "")
        kind = entity.get("kind", "")

        if kind_filter and kind not in kind_filter:
            continue

        score = 0
        name_lower = name.lower()
        fqn_lower = fqn.lower()

        if name_lower == query_lower:
            score = 100
        elif name_lower.startswith(query_lower):
            score = 80
        elif query_lower in name_lower:
            score = 60
        elif fqn_lower == query_lower:
            score = 50
        elif query_lower in fqn_lower:
            score = 30
        elif signature and query_lower in signature.lower():
            score = 20

        if score > 0:
            hits.append({"score": score, "name": name, "fqn": fqn, "kind": kind, "signature": signature})

    hits.sort(key=lambda h: (-h["score"], len(h["name"])))
    return hits[:limit]


def _compute_diff(base: dict, new: dict) -> dict:
    """Compute a simple diff between two snapshots."""
    diff = {"added": [], "removed": [], "modified": []}

    base_files = set(base.get("files", {}).keys())
    new_files = set(new.get("files", {}).keys())

    diff["added"] = list(new_files - base_files)
    diff["removed"] = list(base_files - new_files)

    for f in base_files & new_files:
        if base["files"][f] != new["files"][f]:
            diff["modified"].append(f)

    return diff


async def run_hub_stdio(manager: WorkspaceManager) -> None:
    """Run the MCP hub over stdio."""
    await manager.astart()
    mcp = create_hub(manager)
    mcp.run(transport="stdio")


async def run_hub_sse(
    manager: WorkspaceManager,
    *,
    host: str = "127.0.0.1",
    port: int = 8770,
) -> None:
    """Run the MCP hub over SSE."""
    await manager.astart()
    mcp = create_hub(manager)
    LOGGER.info("mcp_hub_sse_starting", host=host, port=port)
    try:
        mcp.run(transport="sse", host=host, port=port)
    finally:
        await manager.stop()


async def run_hub_streamable_http(
    manager: WorkspaceManager,
    *,
    host: str = "127.0.0.1",
    port: int = 8770,
) -> None:
    """Run the MCP hub over streamable HTTP."""
    await manager.astart()
    mcp = create_hub(manager)
    LOGGER.info("mcp_hub_http_starting", host=host, port=port)
    try:
        mcp.run(transport="streamable-http", host=host, port=port)
    finally:
        await manager.stop()


__all__ = [
    "create_hub",
    "run_hub_stdio",
    "run_hub_sse",
    "run_hub_streamable_http",
]
