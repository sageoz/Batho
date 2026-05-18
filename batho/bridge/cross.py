"""Cross-repo search and resolution helpers."""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from batho.bridge.artifact_cache import ArtifactCacheKey
from batho.bridge.cross_index import CrossRepoIndex, NodeRef
from batho.bridge.models import WorkspaceState
from batho.bridge.workspace_handle import WorkspaceHandle
from batho.bridge.workspace_manager import WorkspaceManager
from batho.utils.logging import get_logger

LOGGER = get_logger(__name__, component="bridge.cross")


@dataclass
class BsgLoadResult:
    data: dict
    nodes: list[NodeRef]
    file_path: str
    file_mtime_ns: int
    file_size: int
    checksum: str


async def cross_search_impl(
    manager: WorkspaceManager,
    *,
    query: str,
    workspace_ids: list[str] | None = None,
    tags: list[str] | None = None,
    kinds: list[str] | None = None,
    limit_per_ws: int = 25,
    merge_strategy: str = "score_desc",
    force_mount: bool = False,
) -> tuple[list[dict], dict]:
    """Search BSG across multiple workspaces."""
    start = time.perf_counter()

    handles, skipped = await _get_target_workspaces(
        manager,
        workspace_ids=workspace_ids,
        tags=tags,
        force_mount=force_mount,
    )

    if not handles:
        duration_ms = int((time.perf_counter() - start) * 1000)
        return [], {
            "workspaces_queried": [],
            "skipped": skipped,
            "duration_ms": duration_ms,
        }

    cross_index = manager.cross_index
    if not cross_index or not cross_index.enabled:
        duration_ms = int((time.perf_counter() - start) * 1000)
        return [], {
            "workspaces_queried": [h.workspace_id for h in handles],
            "skipped": skipped,
            "duration_ms": duration_ms,
            "warning": "cross_repo_disabled",
        }

    kind_filter = _normalize_kind_filter(kinds)

    async def search_workspace(handle: WorkspaceHandle) -> list[dict]:
        load_result = await _load_bsg(handle, manager)
        if load_result is None:
            return []

        await cross_index.ensure_workspace(
            handle.workspace_id,
            nodes=load_result.nodes,
            file_mtime_ns=load_result.file_mtime_ns,
            file_size=load_result.file_size,
        )

        scored = cross_index.search(
            handle.workspace_id,
            query=query,
            kinds=kind_filter,
            limit_per_ws=limit_per_ws,
            score_fn=_score_node,
        )
        return [_format_hit(handle.workspace_id, node, score) for node, score in scored]

    results = await _gather_workspace_tasks(handles, search_workspace)

    merged = _merge_hits(
        {handle.workspace_id: hits for handle, hits in zip(handles, results)},
        strategy=merge_strategy,
        limit_per_ws=limit_per_ws,
    )

    duration_ms = int((time.perf_counter() - start) * 1000)
    meta = {
        "workspaces_queried": [h.workspace_id for h in handles],
        "skipped": skipped,
        "duration_ms": duration_ms,
    }

    return merged, meta


async def cross_symbols_impl(
    manager: WorkspaceManager,
    *,
    name: str,
    workspace_ids: list[str] | None = None,
    tags: list[str] | None = None,
    kinds: list[str] | None = None,
) -> tuple[list[dict], dict]:
    """Locate a symbol across repos."""
    start = time.perf_counter()
    handles, skipped = await _get_target_workspaces(
        manager,
        workspace_ids=workspace_ids,
        tags=tags,
        force_mount=False,
    )

    cross_index = manager.cross_index
    if not handles or not cross_index or not cross_index.enabled:
        duration_ms = int((time.perf_counter() - start) * 1000)
        return [], {
            "workspaces_queried": [h.workspace_id for h in handles],
            "skipped": skipped,
            "duration_ms": duration_ms,
            "warning": "cross_repo_disabled" if not cross_index or not cross_index.enabled else None,
        }

    kind_filter = _normalize_kind_filter(kinds)

    async def find_symbol(handle: WorkspaceHandle) -> list[dict]:
        load_result = await _load_bsg(handle, manager)
        if load_result is None:
            return []

        await cross_index.ensure_workspace(
            handle.workspace_id,
            nodes=load_result.nodes,
            file_mtime_ns=load_result.file_mtime_ns,
            file_size=load_result.file_size,
        )

        matches = cross_index.symbols(
            handle.workspace_id,
            name=name,
            kinds=kind_filter,
        )
        relationships = _load_relationships(handle)

        hits = []
        for node in matches:
            rel = relationships.get(node.node_id, {"incoming": [], "outgoing": []})
            hits.append(
                {
                    "workspace_id": handle.workspace_id,
                    "node_id": node.node_id,
                    "name": node.name,
                    "fqn": node.fqn,
                    "type": node.kind,
                    "file": node.file,
                    "start_line": node.start_line,
                    "end_line": node.end_line,
                    "signature_excerpt": _signature_excerpt(node.signature),
                    "relationships": rel,
                }
            )
        return hits

    results = await _gather_workspace_tasks(handles, find_symbol)

    all_hits: list[dict] = []
    for hits in results:
        if hits:
            all_hits.extend(hits)

    duration_ms = int((time.perf_counter() - start) * 1000)
    meta = {
        "workspaces_queried": [h.workspace_id for h in handles],
        "skipped": skipped,
        "duration_ms": duration_ms,
    }

    return all_hits, meta


async def cross_dependencies_impl(
    manager: WorkspaceManager,
    *,
    package: str,
    workspace_ids: list[str] | None = None,
    tags: list[str] | None = None,
) -> tuple[list[dict], dict]:
    """Find which workspaces consume a package."""
    start = time.perf_counter()
    handles, skipped = await _get_target_workspaces(
        manager,
        workspace_ids=workspace_ids,
        tags=tags,
        force_mount=False,
    )

    query = package.strip().lower()
    if not query:
        return [], {
            "workspaces_queried": [h.workspace_id for h in handles],
            "skipped": skipped,
            "duration_ms": 0,
        }

    async def find_deps(handle: WorkspaceHandle) -> list[dict]:
        deps = _extract_stack_dependencies(handle)
        if not deps:
            deps = _extract_overview_dependencies(handle)

        matches = []
        for dep in deps:
            name = str(dep.get("package") or "").strip()
            if query not in name.lower():
                continue
            matches.append(
                {
                    "workspace_id": handle.workspace_id,
                    "package": name,
                    "version": dep.get("version"),
                    "declared_in": dep.get("declared_in"),
                    "used_in_files": dep.get("used_in_files", []),
                    "source": dep.get("source"),
                }
            )
        return matches

    results = await _gather_workspace_tasks(handles, find_deps)

    all_deps: list[dict] = []
    for matches in results:
        if matches:
            all_deps.extend(matches)

    duration_ms = int((time.perf_counter() - start) * 1000)
    meta = {
        "workspaces_queried": [h.workspace_id for h in handles],
        "skipped": skipped,
        "duration_ms": duration_ms,
    }

    return all_deps, meta


async def cross_workspaces_with_artifact_impl(
    manager: WorkspaceManager,
    *,
    artifact_type: str,
) -> tuple[list[dict], dict]:
    """Find workspaces that have a specific artifact type."""
    start = time.perf_counter()
    workspaces = list(manager.resident())

    results = []
    for handle in workspaces:
        try:
            types = handle.bridge.list_artifact_types()
            if artifact_type in types:
                results.append(
                    {
                        "workspace_id": handle.workspace_id,
                        "has_artifact": True,
                    }
                )
        except Exception:
            pass

    duration_ms = int((time.perf_counter() - start) * 1000)
    meta = {
        "workspaces_queried": [h.workspace_id for h in workspaces],
        "duration_ms": duration_ms,
    }

    return results, meta


def search_bsg_nodes(
    bsg_data: dict,
    *,
    query: str,
    kinds: list[str] | None = None,
    limit: int = 50,
) -> list[dict]:
    """Search BSG nodes inside a single workspace."""
    kind_filter = _normalize_kind_filter(kinds)
    nodes = _collect_bsg_nodes(bsg_data)
    results: list[tuple[NodeRef, float]] = []
    query_lower = query.lower().strip()
    if not query_lower:
        return []

    for node in nodes:
        if kind_filter and node.kind.lower() not in kind_filter:
            continue
        score = _score_node(query_lower, node)
        if score <= 0:
            continue
        results.append((node, score))

    results.sort(key=lambda item: (-item[1], len(item[0].name)))
    hits = [_format_hit("", node, score) for node, score in results[:limit]]
    for hit in hits:
        hit.pop("workspace_id", None)
    return hits


def merge_search_hits(
    results: dict[str, list[dict]],
    *,
    strategy: str = "score_desc",
    limit_per_ws: int = 25,
) -> list[dict]:
    """Merge search hits from multiple workspaces."""
    return _merge_hits(results, strategy=strategy, limit_per_ws=limit_per_ws)


async def warmup_cross_index(manager: WorkspaceManager, handles: list[WorkspaceHandle]) -> None:
    """Warm up cross-repo indexes for pinned workspaces."""
    cross_index = manager.cross_index
    if not cross_index or not cross_index.enabled:
        return

    async def warm(handle: WorkspaceHandle) -> None:
        result = await _load_bsg(handle, manager)
        if not result:
            return
        await cross_index.ensure_workspace(
            handle.workspace_id,
            nodes=result.nodes,
            file_mtime_ns=result.file_mtime_ns,
            file_size=result.file_size,
        )

    await _gather_workspace_tasks(handles, warm)


async def _get_target_workspaces(
    manager: WorkspaceManager,
    *,
    workspace_ids: list[str] | None,
    tags: list[str] | None,
    force_mount: bool,
) -> tuple[list[WorkspaceHandle], list[dict]]:
    handles: list[WorkspaceHandle] = []
    skipped: list[dict] = []

    tag_filter = {t.strip() for t in (tags or []) if t and t.strip()}

    def tag_match(handle: WorkspaceHandle) -> bool:
        if not tag_filter:
            return True
        return any(tag in handle.config.tags for tag in tag_filter)

    if workspace_ids:
        for ws_id in workspace_ids:
            handle = manager.get_handle(ws_id)
            if not handle:
                skipped.append({"workspace_id": ws_id, "reason": "not_found"})
                continue
            if not handle.config.enabled:
                skipped.append({"workspace_id": ws_id, "reason": "disabled"})
                continue
            if not tag_match(handle):
                skipped.append({"workspace_id": ws_id, "reason": "tag_mismatch"})
                continue
            if force_mount:
                try:
                    handle = await manager.resolve(ws_id)
                except Exception as exc:
                    skipped.append({"workspace_id": ws_id, "reason": "mount_failed", "error": str(exc)})
                    continue
            if not handle.is_ready:
                skipped.append({"workspace_id": ws_id, "reason": "not_resident"})
                continue
            if handle.state in (WorkspaceState.DEGRADED, WorkspaceState.FAILED):
                skipped.append({"workspace_id": ws_id, "reason": handle.state.value})
                continue
            handles.append(handle)
    else:
        for handle in manager.resident():
            if not handle.config.enabled:
                skipped.append({"workspace_id": handle.workspace_id, "reason": "disabled"})
                continue
            if not tag_match(handle):
                skipped.append({"workspace_id": handle.workspace_id, "reason": "tag_mismatch"})
                continue
            if handle.state in (WorkspaceState.DEGRADED, WorkspaceState.FAILED):
                skipped.append({"workspace_id": handle.workspace_id, "reason": handle.state.value})
                continue
            handles.append(handle)

    return handles, skipped


async def _gather_workspace_tasks(workspaces: list, func) -> list:
    """Gather results from workspaces with bounded concurrency."""
    cap = min(16, len(workspaces)) if workspaces else 1
    semaphore = asyncio.Semaphore(cap)

    async def bounded_func(handle):
        async with semaphore:
            if not handle.is_ready:
                return None
            return await func(handle)

    tasks = [bounded_func(h) for h in workspaces]
    return await asyncio.gather(*tasks, return_exceptions=False)


def _normalize_kind_filter(kinds: list[str] | None) -> set[str] | None:
    if not kinds:
        return None
    return {k.strip().lower() for k in kinds if k and k.strip()}


def _score_node(query_lower: str, node: NodeRef) -> float:
    name_lower = node.name.lower() if node.name else ""
    fqn_lower = node.fqn.lower() if node.fqn else ""
    signature_lower = node.signature.lower() if node.signature else ""

    if name_lower == query_lower:
        return 1.0

    if node.fqn:
        segments = [seg for seg in fqn_lower.split(".") if seg]
        if query_lower in segments:
            return 0.9

    if query_lower in name_lower:
        return 0.7

    if signature_lower and query_lower in signature_lower:
        return 0.4

    ratio = SequenceMatcher(None, query_lower, name_lower).ratio() if name_lower else 0.0
    return min(0.3, ratio * 0.3)


def _format_hit(workspace_id: str, node: NodeRef, score: float) -> dict:
    return {
        "workspace_id": workspace_id,
        "node_id": node.node_id,
        "name": node.name,
        "fqn": node.fqn,
        "type": node.kind,
        "file": node.file,
        "start_line": node.start_line,
        "end_line": node.end_line,
        "score": round(score, 4),
        "signature_excerpt": _signature_excerpt(node.signature),
    }


def _signature_excerpt(signature: str | None, max_len: int = 120) -> str:
    if not signature:
        return ""
    if len(signature) <= max_len:
        return signature
    return signature[: max_len - 3] + "..."


def _merge_hits(
    results: dict[str, list[dict]],
    *,
    strategy: str,
    limit_per_ws: int,
) -> list[dict]:
    all_hits: list[dict] = []
    for ws_id, hits in results.items():
        if not hits:
            continue
        for h in hits[:limit_per_ws]:
            h["workspace_id"] = ws_id
        all_hits.extend(hits[:limit_per_ws])

    if strategy == "round_robin":
        by_ws: dict[str, list[dict]] = {}
        for hit in all_hits:
            by_ws.setdefault(hit.get("workspace_id", ""), []).append(hit)
        merged = []
        while by_ws:
            for ws_id in list(by_ws.keys()):
                if by_ws[ws_id]:
                    merged.append(by_ws[ws_id].pop(0))
                else:
                    del by_ws[ws_id]
        return merged

    return sorted(all_hits, key=lambda h: -float(h.get("score", 0)))


async def _load_bsg(handle: WorkspaceHandle, manager: WorkspaceManager) -> BsgLoadResult | None:
    if not handle.loader:
        return None

    path, checksum = _resolve_bsg_path(handle)
    if not path:
        return None

    try:
        stat = path.stat()
    except OSError as exc:
        LOGGER.warning("bsg_stat_failed", workspace_id=handle.workspace_id, error=str(exc))
        return None

    key = ArtifactCacheKey(
        workspace_id=handle.workspace_id,
        artifact_type="bsg_json",
        file_path=str(path),
        file_mtime_ns=stat.st_mtime_ns,
        file_size=stat.st_size,
        checksum=checksum or "",
    )

    cache = manager.cache
    cached = cache.get(key)
    if cached is None:
        if cache.acquire_single_flight(key):
            try:
                cached = handle.loader.load_json("bsg_json")
                cache.put(key, cached, stat.st_size)
            except Exception as exc:
                LOGGER.warning("bsg_load_failed", workspace_id=handle.workspace_id, error=str(exc))
                return None
            finally:
                cache.release_single_flight(key)
        else:
            cache.wait_for_single_flight(key)
            cached = cache.get(key)

    if not isinstance(cached, dict):
        return None

    nodes = _collect_bsg_nodes(cached)
    if handle and manager:
        stats = cache.stats()
        handle.cache_bytes = stats.workspace_bytes.get(handle.workspace_id, 0)

    return BsgLoadResult(
        data=cached,
        nodes=nodes,
        file_path=str(path),
        file_mtime_ns=stat.st_mtime_ns,
        file_size=stat.st_size,
        checksum=checksum or "",
    )


def _resolve_bsg_path(handle: WorkspaceHandle) -> tuple[Path | None, str | None]:
    record = None
    if handle.bridge:
        records = handle.bridge.get_artifacts_by_type("bsg_json", limit=1)
        record = records[0] if records else None

    if record:
        path = Path(record.physical_path)
        if not path.exists():
            path = handle.ctn_dir / record.logical_path
        if path.exists():
            return path, record.checksum

    if handle.loader and hasattr(handle.loader, "resolve_path"):
        path = handle.loader.resolve_path("bsg_json")
        if path and path.exists():
            return path, None

    return None, None


def _collect_bsg_nodes(bsg_data: dict) -> list[NodeRef]:
    raw_nodes = bsg_data.get("nodes")
    if not isinstance(raw_nodes, list):
        raw_nodes = bsg_data.get("entities")

    nodes: list[NodeRef] = []
    if not isinstance(raw_nodes, list):
        return nodes

    for node in raw_nodes:
        if not isinstance(node, dict):
            continue
        node_id = str(node.get("id") or "")
        name = str(node.get("name") or "").strip()
        if not node_id and not name:
            continue
        kind = str(node.get("type") or node.get("kind") or "")
        file_path = str(node.get("file") or "")
        signature = str(node.get("signature") or "")
        start_line = _coerce_line(node.get("start_line") or node.get("startLine"))
        end_line = _coerce_line(node.get("end_line") or node.get("endLine"))
        if end_line and start_line and end_line < start_line:
            end_line = start_line
        fqn = _extract_fqn(node)
        node_id = node_id or f"{file_path}:{name}:{start_line}"
        nodes.append(
            NodeRef(
                node_id=node_id,
                name=name,
                fqn=fqn,
                kind=kind,
                file=file_path,
                start_line=start_line,
                end_line=end_line,
                signature=signature,
            )
        )

    return nodes


def _coerce_line(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _extract_fqn(node: dict[str, Any]) -> str:
    for key in ("fqn", "qualified_name", "bsg.fqn", "bsg.qualified_name"):
        value = node.get(key)
        if value:
            return str(value)
    metadata = node.get("metadata")
    if isinstance(metadata, dict):
        for key in ("fqn", "bsg.fqn", "qualified_name", "bsg.qualified_name"):
            value = metadata.get(key)
            if value:
                return str(value)
    return ""


def _load_relationships(handle: WorkspaceHandle) -> dict[str, dict[str, list[dict]]]:
    if not handle.loader:
        return {}
    try:
        graph = handle.loader.load_json("graph_json")
    except Exception:
        return {}

    relationships = graph.get("relationships")
    if not isinstance(relationships, list):
        return {}

    inbound: dict[str, list[dict]] = {}
    outbound: dict[str, list[dict]] = {}

    for rel in relationships:
        if not isinstance(rel, dict):
            continue
        source = str(rel.get("source_id") or "")
        target = str(rel.get("target_id") or "")
        rel_type = str(rel.get("type") or "")
        payload = {
            "source_id": source,
            "target_id": target,
            "type": rel_type,
        }
        if source:
            outbound.setdefault(source, []).append(payload)
        if target:
            inbound.setdefault(target, []).append(payload)

    combined: dict[str, dict[str, list[dict]]] = {}
    for node_id in set(list(inbound.keys()) + list(outbound.keys())):
        combined[node_id] = {
            "incoming": inbound.get(node_id, [])[:50],
            "outgoing": outbound.get(node_id, [])[:50],
        }

    return combined


def _extract_stack_dependencies(handle: WorkspaceHandle) -> list[dict[str, Any]]:
    if not handle.bridge:
        return []

    entry = handle.bridge.get_latest_index()
    if not entry:
        return []

    stack = entry.stack or {}
    deps = stack.get("dependencies") if isinstance(stack, dict) else None
    if not deps:
        return []

    results: list[dict[str, Any]] = []
    if isinstance(deps, dict):
        for name, meta in deps.items():
            meta_dict = meta if isinstance(meta, dict) else {}
            results.append(
                {
                    "package": name,
                    "version": meta_dict.get("version"),
                    "declared_in": meta_dict.get("declared_in"),
                    "used_in_files": meta_dict.get("used_in_files", []),
                    "source": "stack",
                }
            )
    elif isinstance(deps, list):
        for item in deps:
            if not isinstance(item, dict):
                continue
            name = item.get("name") or item.get("package") or item.get("dependency")
            if not name:
                continue
            results.append(
                {
                    "package": name,
                    "version": item.get("version"),
                    "declared_in": item.get("declared_in"),
                    "used_in_files": item.get("used_in_files", []),
                    "source": "stack",
                }
            )

    return results


def _extract_overview_dependencies(handle: WorkspaceHandle) -> list[dict[str, Any]]:
    if not handle.loader:
        return []

    try:
        overview = handle.loader.load_json("context_overview_json")
    except Exception:
        return []

    top = overview.get("top_dependencies")
    if not isinstance(top, list):
        return []

    results: list[dict[str, Any]] = []
    for item in top:
        if not isinstance(item, dict):
            continue
        name = item.get("dependency") or item.get("name")
        if not name:
            continue
        results.append(
            {
                "package": name,
                "version": None,
                "declared_in": None,
                "used_in_files": [],
                "source": "overview",
            }
        )

    return results


__all__ = [
    "cross_search_impl",
    "cross_symbols_impl",
    "cross_dependencies_impl",
    "cross_workspaces_with_artifact_impl",
    "merge_search_hits",
    "search_bsg_nodes",
    "warmup_cross_index",
]
