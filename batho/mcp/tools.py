"""Batho MCP tools — 19 tools for code-graph intelligence and repository lifecycle management."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Iterator
import dataclasses
import datetime
import json

from pathlib import Path
from typing import Any, TYPE_CHECKING

import pyarrow as pa
import pyarrow.compute as pc
from fastmcp import FastMCP, Context
from fastmcp.tools.tool import ToolResult
from mcp.types import TextContent, ToolAnnotations

from batho.modules.storage.arrow_bundle.reader import BathoBundleReader
from batho.modules.storage.arrow_bundle.bundle import BathoBundle
from batho.mcp.graph_builder import (
    build_dual_output, format_summary, estimate_tokens, truncate_to_budget,
)
from batho.mcp.community_summaries import load_communities, format_communities_for_overview
from batho.mcp.delta_reader import read_delta, format_delta_markdown, build_delta_structured
from batho.mcp.registry import RepoRegistry, RepoEntry
from batho.mcp.errors import _err, CLIENT_ERROR, EXTERNAL_ERROR
from batho.utils.path_sanitizer import sanitize_path, _canonicalize_untrusted_path, PathSecurityError

if TYPE_CHECKING:
    from batho.mcp.watcher import BathoWatcherEngine

import structlog

LOGGER = structlog.get_logger(__name__)


def _json_default(o: Any) -> Any:
    if isinstance(o, Path):
        return str(o)
    if isinstance(o, Iterator) and not isinstance(o, (str, bytes)):
        return None
    raise TypeError(f"Object of type {type(o).__name__} is not JSON serializable")


def _as_dict(obj: Any) -> dict:
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        data = {f.name: getattr(obj, f.name) for f in dataclasses.fields(obj)}
    elif isinstance(obj, dict):
        data = obj
    else:
        return {}
    try:
        return json.loads(json.dumps(data, default=_json_default))
    except (TypeError, ValueError):
        return {}


class _ReaderPool:
    """Manages BathoBundleReader instances keyed by repo name."""

    def __init__(self, registry: RepoRegistry | None = None) -> None:
        self._registry = registry
        self._readers: dict[str, BathoBundleReader] = {}
        self._root_readers: dict[str, BathoBundleReader] = {}

    def get_by_repo(self, repo_name: str) -> BathoBundleReader:
        """Get or create a reader for a named repo from the registry."""
        if repo_name in self._readers:
            return self._readers[repo_name]
        if not self._registry:
            raise ValueError(f"No registry configured. Cannot resolve repo '{repo_name}'.")
        entry = self._registry.get(repo_name)
        if not entry:
            available = [e.name for e in self._registry.list_all()]
            raise ValueError(
                f"Repo '{repo_name}' not found in registry. "
                f"Available repos: {available}"
            )
        reader = BathoBundleReader(entry.artifact_dir)
        self._readers[repo_name] = reader
        return reader

    def get_by_root(self, root_path: str) -> BathoBundleReader:
        """Get or create a reader for an explicit root path (backward compat)."""
        resolved = str(Path(root_path).resolve())
        if resolved not in self._root_readers:
            artifact_dir = Path(resolved) / ".batho" / "artifact"
            self._root_readers[resolved] = BathoBundleReader(artifact_dir)
        return self._root_readers[resolved]

    def invalidate(self, repo_name: str, root_path: str | None = None) -> None:
        """Remove a reader from the pool (e.g. after patch, build, load, or repo removal)."""
        self._readers.pop(repo_name, None)
        if self._registry:
            entry = self._registry.get(repo_name)
            if entry:
                self._root_readers.pop(str(Path(entry.path).resolve()), None)
        if root_path:
            self._root_readers.pop(str(Path(root_path).resolve()), None)


_pool: _ReaderPool | None = None


def invalidate_reader_pool(repo_name: str, root_path: str | None = None) -> None:
    """Public helper to invalidate a reader in the global reader pool."""
    global _pool
    if _pool:
        _pool.invalidate(repo_name, root_path=root_path)


def _get_reader(root_path: str) -> BathoBundleReader:
    """Get or create a reader for an explicit root path (backward compat helper)."""
    global _pool
    if _pool is None:
        _pool = _ReaderPool()
    return _pool.get_by_root(root_path)


def _check_artifact(root_path: str) -> str | None:
    """Check if root path has an artifact (backward compat helper)."""
    resolved = Path(root_path).resolve()
    artifact_dir = resolved / ".batho" / "artifact"
    if not artifact_dir.exists():
        return f"No Batho artifact found at {artifact_dir}."
    return None


def _repo_lock_path(root_path: str) -> Path:
    """Return the cross-process lock file path for a repo root."""
    return Path(root_path).resolve() / ".batho" / "batho.lock"


def _with_repo_lock(root_path: str, fn: Any) -> Any:
    """Run ``fn`` while holding the cross-process InterProcessLock for ``root_path``.

    This serializes mutating operations (gc/load/fix) against both manual tool
    calls and the watcher engine's auto-patch, preventing interleaved writes to
    the same artifact. ``run_build`` and ``run_patch`` acquire this lock
    internally, so callers should NOT wrap those two in this helper.
    """
    from batho.utils.file_io import InterProcessLock
    lock_path = _repo_lock_path(root_path)
    # Ensure the .batho directory exists so the lock file can be created. This
    # matters for batho_load, where the target repo may not yet have a .batho/
    # directory (load is what creates it).
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with InterProcessLock(lock_path):
        return fn()


def _resolve_repo(repo: str | None, default_root: str | None) -> tuple[str, BathoBundleReader]:
    """Resolve repo name to (repo_name, reader).

    Priority: explicit repo arg > registry default (first entry) > --root fallback.
    Returns (repo_name_or_root, reader).
    """
    global _pool
    if _pool is None:
        _pool = _ReaderPool()

    # Explicit repo name provided
    if repo:
        if _pool._registry and _pool._registry.get(repo):
            return repo, _pool.get_by_repo(repo)
        raise ValueError(
            f"Repo '{repo}' not found in registry. "
            f"Available: {[e.name for e in _pool._registry.list_all()] if _pool._registry else 'no registry'}"
        )

    # No repo arg — try registry default (first entry)
    if _pool._registry:
        entries = _pool._registry.list_all()
        if entries:
            return entries[0].name, _pool.get_by_repo(entries[0].name)

    # Fallback to --root (backward compat)
    if default_root:
        root = str(Path(default_root).resolve())
        return root, _pool.get_by_root(root)

    raise ValueError(
        "No repo specified and no registry entries found. "
        "Call list_repos to see registered repos or pass repo parameter."
    )


def _resolve_root_path(repo: str | None, default_root: str | None, registry: RepoRegistry | None) -> str:
    """Resolve repository filesystem root path securely.

    Resolution order (trust is anchored in the registry / --root CLI flag,
    never in untrusted client-supplied paths):
      1. ``repo`` matches a registered entry → that entry's validated path.
      2. ``repo`` omitted + registry has entries → first entry's path.
      3. ``repo`` omitted + ``default_root`` set (server --root flag) → that path.
      4. Otherwise → ValueError.

    Unregistered ``repo`` strings are rejected so an MCP client cannot target
    arbitrary filesystem locations.
    """
    try:
        if repo and registry:
            entry = registry.get(repo)
            if entry:
                return str(sanitize_path(entry.path, allow_absolute=True))
            raise ValueError(
                f"Repo '{repo}' is not registered in the MCP registry. "
                f"Registered repos: {[e.name for e in registry.list_all()]}"
            )
        if registry:
            entries = registry.list_all()
            if entries:
                return str(sanitize_path(entries[0].path, allow_absolute=True))
        if default_root:
            return str(sanitize_path(default_root, allow_absolute=True))
        raise ValueError("Cannot resolve repository root path.")
    except PathSecurityError as exc:
        raise ValueError(f"Invalid path: {exc}") from exc



def _check_artifact_for_repo(entry: RepoEntry) -> str | None:
    if not RepoRegistry.has_artifact(entry):
        return f"No Batho artifact found at {entry.artifact_dir} for repo '{entry.name}'."
    return None


def _file_paths_map(reader: BathoBundleReader) -> dict[int, str]:
    tracking = reader.get_all_file_tracking()
    return {tr.get("file_id", -1): fp for fp, tr in tracking.items() if "file_id" in tr}


def _manifest_gen(reader: BathoBundleReader) -> int:
    try:
        manifest = reader.get_manifest()
        return manifest.get("generation", 0)
    except Exception:
        return 0


def _resolve_entity_id(name_or_id: str, reader: BathoBundleReader) -> str | list[dict]:
    """Resolve an entity query to a concrete entity_id.

    Tries exact entity_id match first, then falls back to exact name match.
    Returns the entity_id string if uniquely resolved, or a list of candidate
    dicts (with entity_id, name, type, file) for disambiguation if multiple
    name matches exist. Returns an empty list if no match.
    """
    agent_table = reader._get_table("agent_views")
    if agent_table.num_rows == 0:
        return []

    # Try exact entity_id match first
    mask = pc.equal(agent_table.column("entity_id"), name_or_id)
    matched = agent_table.filter(mask)
    if matched.num_rows > 0:
        return name_or_id

    # Fall back to exact name match
    name_mask = pc.equal(agent_table.column("name"), name_or_id)
    name_matched = agent_table.filter(name_mask)
    if name_matched.num_rows == 0:
        return []
    if name_matched.num_rows == 1:
        return name_matched.to_pylist()[0].get("entity_id", "")

    # Multiple matches — return disambiguation list
    file_paths = _file_paths_map(reader)
    rows = name_matched.to_pylist()
    return [
        {
            "entity_id": r.get("entity_id", ""),
            "name": r.get("name", ""),
            "type": r.get("entity_type", ""),
            "file": file_paths.get(r.get("file_id", -1), ""),
        }
        for r in rows
    ]


def register_tools(
    app: FastMCP,
    default_root: str | None = None,
    registry: RepoRegistry | None = None,
    watcher: BathoWatcherEngine | None = None,
    disabled_tools: set[str] | None = None,
    enabled_tools: set[str] | None = None,
) -> None:
    """Register all Batho MCP tools on the FastMCP app.

    All 19 tools are registered via decorators, then disabled tools are removed
    from the app's tool registry so they disappear from ``tools/list``. This
    matches Sourcegraph's ``mcp.tools.disabled`` semantics and keeps the agent's
    tool surface focused on retrieval + diagnostics by default.

    Args:
        app: FastMCP application to register tools on.
        default_root: Fallback repository root when no registry entries exist.
        registry: Repo registry for multi-repo resolution.
        watcher: Optional watcher engine for staleness banners.
        disabled_tools: blocklist of tool names NOT to register. When None,
            defaults to the secure-by-default Tier-3 set
            (batho_build, batho_export, batho_load, batho_gc).
        enabled_tools: optional allowlist. If set, ONLY tools in this set are
            registered (disabled_tools is ignored). None = no allowlist filtering.
    """
    global _pool
    _pool = _ReaderPool(registry=registry)

    # Secure-by-default: if caller did not specify a filter, disable the
    # expensive/administrative Tier-3 tools so the agent surface stays
    # focused on retrieval + diagnostics.
    if disabled_tools is None and enabled_tools is None:
        disabled_tools = {"batho_build", "batho_export", "batho_load", "batho_gc"}
    disabled_tools = disabled_tools or set()

    # All 19 tool names — used to compute the removal set when an allowlist
    # is specified (remove everything NOT in the allowlist).
    _ALL_TOOL_NAMES = {
        "list_repos", "add_repo", "remove_repo",
        "graph_overview", "graph_query", "get_entity", "trace_path",
        "get_file_graph", "search_entities", "get_delta",
        "batho_status", "batho_list_runs", "batho_diff",
        "batho_build", "batho_patch", "batho_export",
        "batho_gc", "batho_fix", "batho_load",
    }

    def _tools_to_remove() -> set[str]:
        if enabled_tools is not None:
            # Allowlist mode: remove everything not in the allowlist
            return _ALL_TOOL_NAMES - enabled_tools
        return disabled_tools

    def _inject_banner(res: ToolResult, repo_name: str, file_path: str | None = None) -> ToolResult:
        if not watcher:
            return res
        banner = watcher.get_staleness_banner(repo_name, file_path=file_path)
        if not banner:
            return res
        if res.content and isinstance(res.content[0], TextContent):
            orig_text = res.content[0].text
            res.content[0] = TextContent(type="text", text=f"{banner}\n\n{orig_text}")
        if isinstance(res.structured_content, dict):
            meta = res.structured_content.setdefault("meta", {})
            if isinstance(meta, dict):
                meta["staleness_banner"] = banner
        return res

    # -------------------------------------------------------------------
    # Existing Tools (v1)
    # -------------------------------------------------------------------

    @app.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False, destructiveHint=False))
    def list_repos() -> ToolResult:
        """List all registered repositories in the Batho MCP registry.

        Use this to see available repos, their paths, entity counts, and artifact status.
        Do NOT call this repeatedly — call it once when starting or switching context.
        """
        if not registry:
            return _err("No registry configured. Start server with a registry or use --root.",
                         error_type=CLIENT_ERROR, hint="Start the server with 'batho mcp --root /path/to/repo' or register repos via add_repo.")
        entries = registry.list_all()
        if not entries:
            return _err("No repos registered.",
                         error_type=CLIENT_ERROR, hint="Call add_repo(name, path) to register a repo. The repo must have a .batho artifact (run 'batho build' first).")
        lines = ["## Registered Repos", ""]
        structured_repos = []
        for entry in entries:
            has_art = RepoRegistry.has_artifact(entry)
            status = "✓ ready" if has_art else "✗ no artifact"
            entity_count = 0
            if has_art:
                try:
                    r = _pool.get_by_repo(entry.name)
                    agent_table = r._get_table("agent_views")
                    entity_count = agent_table.num_rows
                except Exception:
                    pass
            lines.append(f"- **{entry.name}** — {entry.path} ({status}, {entity_count} entities, watch: {entry.watch})")
            structured_repos.append({
                "name": entry.name,
                "path": entry.path,
                "has_artifact": has_art,
                "entity_count": entity_count,
                "watch": entry.watch,
                "sync_state": entry.sync_state,
            })
        structured = {"repos": structured_repos, "total": len(structured_repos)}
        return ToolResult(content=[TextContent(type="text", text="\n".join(lines))], structured_content=structured)

    @app.tool(annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=False, destructiveHint=True))
    def add_repo(
        name: str,
        path: str,
        watch: bool = False,
        debounce_ms: int = 2000,
        max_file_size_kb: int | None = None,
    ) -> ToolResult:
        """Register a repository in the Batho MCP registry.

        The repo must have a .batho artifact (run 'batho build' first).
        Use this when you need to add a new repo to the MCP server at runtime.
        Do NOT use this for querying — use list_repos to see existing repos.

        Args:
            name: Unique name for the repo (e.g. 'myapp', 'frontend').
            path: Absolute filesystem path to the repo root.
            watch: If True, watcher engine will auto-patch this repo on file changes.
            debounce_ms: Debounce delay before auto-patch (100-60000 ms). Default: 2000.
            max_file_size_kb: Skip files larger than this during auto-patch.
        """
        if not registry:
            return _err("No registry configured. Cannot add repos.",
                         error_type=CLIENT_ERROR, hint="Start the server with 'batho mcp --root /path/to/repo' instead.")
        # Canonicalize the untrusted path (rejects percent-encoded traversal,
        # Unicode homoglyphs, URI schemes, null bytes) before resolving. The
        # path is operator-supplied and expected to be absolute, so
        # allow_absolute=True is permitted here.
        try:
            resolved = str(sanitize_path(path, allow_absolute=True))
        except PathSecurityError as exc:
            return _err(f"Invalid repo path: {exc}",
                         error_type=CLIENT_ERROR, hint="Provide a valid absolute filesystem path to the repo root.")
        artifact_dir = Path(resolved) / ".batho" / "artifact"
        if watch and not artifact_dir.exists():
            return _err(f"Cannot watch repo without an artifact at {artifact_dir}.",
                         error_type=CLIENT_ERROR, hint=f"Run 'batho build --root {resolved}' first to create the artifact.")
        if not artifact_dir.exists():
            return _err(f"No Batho artifact found at {artifact_dir}.",
                         error_type=EXTERNAL_ERROR, hint=f"Run 'batho build --root {resolved}' first to create the artifact.")
        entry = registry.add(name=name, path=resolved, watch=watch, debounce_ms=debounce_ms, max_file_size_kb=max_file_size_kb)
        _pool.invalidate(name)

        if watcher and watch:
            watcher.watch(entry)

        try:
            reader = _pool.get_by_repo(name)
            agent_table = reader._get_table("agent_views")
            entity_count = agent_table.num_rows
        except Exception:
            entity_count = 0
        watch_str = "✓ enabled" if watch else "✗ disabled"
        markdown = f"## Repo Registered\n\n- **{name}** — {resolved}\n- Entities: {entity_count}\n- Artifact: ✓ ready\n- Watch: {watch_str}"
        structured = {
            "name": name,
            "path": resolved,
            "watch": watch,
            "debounce_ms": entry.debounce_ms,
            "max_file_size_kb": max_file_size_kb,
            "entity_count": entity_count,
            "has_artifact": True,
        }
        return ToolResult(content=[TextContent(type="text", text=markdown)], structured_content=structured)

    @app.tool(annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=False, destructiveHint=True))
    def remove_repo(name: str) -> ToolResult:
        """Remove a repository from the Batho MCP registry.

        Use this when a repo is no longer needed. Does NOT delete the .batho artifact on disk.
        Do NOT use this to query repos — use list_repos instead.

        Args:
            name: Name of the repo to remove.
        """
        if not registry:
            return _err("No registry configured.",
                         error_type=CLIENT_ERROR, hint="Start the server with 'batho mcp --root /path/to/repo' instead.")
        if watcher:
            watcher.unwatch(name)
        removed = registry.remove(name)
        if not removed:
            return _err(f"Repo '{name}' not found in registry.",
                         error_type=CLIENT_ERROR, hint="Call list_repos to see available repos.")
        _pool.invalidate(name)
        markdown = f"## Repo Removed\n\n- **{name}** — removed from registry"
        structured = {"name": name, "removed": True}
        return ToolResult(content=[TextContent(type="text", text=markdown)], structured_content=structured)

    @app.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False, destructiveHint=False))
    def graph_overview(
        repo: str | None = None,
        response_format: str = "summary",
        max_tokens: int = 25000,
    ) -> ToolResult:
        """Get a high-level overview of the codebase graph.

        Returns entity counts, relationship breakdown, file list, and community summaries.
        Use this FIRST for any unfamiliar codebase — it provides context for all subsequent queries.
        Do NOT use graph_query or get_file_graph before calling this — always start here.
        Returns markdown summary (~200-500 tokens) and structured JSON with full stats.

        Args:
            repo: Name of the registered repo. If None, uses the default (first registered) repo.
            response_format: Output verbosity: 'summary' (default, ~200 tokens), 'concise', or 'detailed'.
            max_tokens: Maximum tokens for the content field. Default: 25000.
        """
        try:
            repo_name, reader = _resolve_repo(repo, default_root)
        except ValueError as e:
            return _err(str(e), error_type=CLIENT_ERROR, hint="Call list_repos to see available repos.")
        entry = registry.get(repo_name) if registry else None
        if entry:
            err = _check_artifact_for_repo(entry)
            if err:
                return _err(err, error_type=EXTERNAL_ERROR, hint="Run 'batho build' first to create the artifact.")
        root = str(Path(entry.path).resolve()) if entry else repo_name

        runs = reader.get_all_runs()
        if not runs:
            return _err("No runs found.",
                         error_type=EXTERNAL_ERROR, hint="Run 'batho build --root <path>' first to create the artifact.")
        latest = runs[-1]

        agent_table = reader._get_table("agent_views")
        rels_table = reader._get_table("rels_views")
        tracking = reader.get_all_file_tracking()

        entity_type_counts: dict[str, int] = {}
        if agent_table.num_rows > 0:
            etypes = agent_table.column("entity_type").to_pylist()
            for et in etypes:
                entity_type_counts[et] = entity_type_counts.get(et, 0) + 1

        rel_type_counts: dict[str, int] = {}
        if rels_table.num_rows > 0:
            rtypes = rels_table.column("relation_type").to_pylist()
            for rt in rtypes:
                rel_type_counts[rt] = rel_type_counts.get(rt, 0) + 1

        files_list = []
        entity_counts_by_file: dict[str, int] = {}
        if agent_table.num_rows > 0:
            file_ids = agent_table.column("file_id").to_pylist()
            fid_to_path = {tr.get("file_id"): fp for fp, tr in tracking.items()}
            for fid in file_ids:
                fp = fid_to_path.get(fid)
                if fp:
                    entity_counts_by_file[fp] = entity_counts_by_file.get(fp, 0) + 1
        for fp, tr in tracking.items():
            files_list.append({"path": fp, "entities": entity_counts_by_file.get(fp, 0), "indexed": tr.get("is_indexed", False)})
        files_list.sort(key=lambda x: x["path"])

        stats = {
            "total_entities": agent_table.num_rows,
            "total_relationships": rels_table.num_rows,
            "total_files": len(tracking),
            "entity_breakdown": entity_type_counts,
            "relationship_breakdown": rel_type_counts,
            "files": files_list,
            "run_id": latest.get("run_uuid"),
            "git_commit": latest.get("git_commit"),
            "artifact_generation": _manifest_gen(reader),
        }

        artifact_dir = Path(root).resolve() / ".batho" / "artifact"
        communities_raw = load_communities(artifact_dir)
        communities = format_communities_for_overview(communities_raw)

        markdown = format_summary(stats, communities)
        markdown, truncated = truncate_to_budget(markdown, max_tokens)
        if truncated:
            markdown += f"\n\n---\nTruncated to fit {max_tokens} token budget. Use graph_query with file_path filters for detailed per-file data."

        structured = {
            "overview": {
                "stats": stats,
                "communities": communities,
            },
            "meta": {
                "artifact_generation": stats["artifact_generation"],
                "tokens_used": estimate_tokens(markdown),
                "token_budget": max_tokens,
                "truncated": truncated,
            },
        }
        res = ToolResult(content=[TextContent(type="text", text=markdown)], structured_content=structured)
        return _inject_banner(res, repo_name)

    @app.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False, destructiveHint=False))
    def graph_query(
        repo: str | None = None,
        file_path: str | None = None,
        entity_types: list[str] | None = None,
        relation_types: list[str] | None = None,
        name_pattern: str | None = None,
        response_format: str = "concise",
        limit: int = 50,
        offset: int = 0,
        max_tokens: int = 25000,
    ) -> ToolResult:
        """Query the code graph with optional filters. Returns paginated nodes and edges.

        Use this for filtered graph traversal — by file, entity type, relation type, or name pattern.
        Do NOT use this for single-entity lookup — use get_entity instead.
        Do NOT use this for file-level analysis — use get_file_graph instead.
        Do NOT use this for name search — use search_entities instead.
        Use graph_overview first if you are unfamiliar with the codebase.

        Args:
            repo: Name of the registered repo. If None, uses the default repo.
            file_path: Filter to entities in a specific file (forward slashes).
            entity_types: Filter to specific entity types (e.g. ['FUNCTION', 'CLASS']).
            relation_types: Filter to specific relation types (e.g. ['CALLS', 'IMPORTS']).
            name_pattern: Regex pattern to match entity names.
            response_format: 'concise' (default, ~50 tokens/entity), 'detailed' (~150 tokens/entity).
            limit: Maximum entities to return. Default: 50.
            offset: Pagination offset. Default: 0.
            max_tokens: Maximum tokens for content field. Default: 25000.
        """
        try:
            repo_name, reader = _resolve_repo(repo, default_root)
        except ValueError as e:
            return _err(str(e), error_type=CLIENT_ERROR, hint="Call list_repos to see available repos.")

        agent_table = reader._get_table("agent_views")
        if agent_table.num_rows == 0:
            return _err("No entities found in artifact.",
                         error_type=EXTERNAL_ERROR, hint="Run 'batho build' to populate the artifact with entities.")

        table = agent_table

        if file_path:
            norm_fp = _canonicalize_untrusted_path(str(file_path))
            fid = reader.file_id_for_path(norm_fp)
            if fid is None:
                return _err(f"File not indexed: {norm_fp}",
                             error_type=CLIENT_ERROR, hint="Use graph_overview to see all indexed files, or graph_query without file_path to search across all files.")
            table = table.filter(pc.equal(table.column("file_id"), fid))

        if entity_types:
            masks = [pc.equal(table.column("entity_type"), et) for et in entity_types]
            combined = masks[0]
            for m in masks[1:]:
                combined = pc.or_(combined, m)
            table = table.filter(combined)

        if name_pattern:
            if len(name_pattern) > 200:
                return _err("name_pattern too long (max 200 chars).",
                             error_type=CLIENT_ERROR, hint="Use a shorter regex pattern.")
            try:
                table = table.filter(pc.match_substring_regex(table.column("name"), name_pattern))
            except Exception:
                table = table.filter(pc.match_substring(table.column("name"), name_pattern))

        total_nodes = table.num_rows
        rows = table.slice(offset, limit).to_pylist()

        rels_table = reader._get_table("rels_views")
        rels_rows: list[dict] = []
        if rels_table.num_rows > 0 and rows:
            entity_ids = {r.get("entity_id", "") for r in rows}
            file_ids = {r.get("file_id", -1) for r in rows}
            for fid in file_ids:
                fid_artifacts = reader.get_file_artifacts_by_id(fid)
                fid_rels = fid_artifacts.get("rels_view", []) if fid_artifacts else []
                if fid_rels:
                    rels_rows.extend(fid_rels)

            if relation_types:
                rels_rows = [r for r in rels_rows if r.get("relation_type") in relation_types]

            rels_rows = [r for r in rels_rows if r.get("source_id") in entity_ids or r.get("target_id") in entity_ids]

            seen_rels: set[tuple[str, str, str]] = set()
            deduped: list[dict] = []
            for r in rels_rows:
                key = (r.get("source_id", ""), r.get("target_id", ""), r.get("relation_type", ""))
                if key not in seen_rels:
                    seen_rels.add(key)
                    deduped.append(r)
            rels_rows = deduped

        file_paths = _file_paths_map(reader)
        gen = _manifest_gen(reader)

        markdown, structured = build_dual_output(
            rows, rels_rows, file_paths,
            response_format=response_format, max_tokens=max_tokens,
            offset=offset, limit=limit,
            total_nodes=total_nodes, total_edges=rels_table.num_rows,
            artifact_generation=gen,
        )
        res = ToolResult(content=[TextContent(type="text", text=markdown)], structured_content=structured)
        return _inject_banner(res, repo_name, file_path=file_path)

    @app.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False, destructiveHint=False))
    def get_entity(
        entity_id: str,
        repo: str | None = None,
        include_source: bool = False,
        response_format: str = "detailed",
    ) -> ToolResult:
        """Get detailed information about a single entity, including relationships and optionally source code.

        Use this after search_entities or graph_query to deep-dive a specific entity.
        Returns outgoing and incoming relationships (CALLS, IMPORTS, USES, etc.).
        Do NOT use this to search — use search_entities for name-based lookup.
        Do NOT use this for path tracing — use trace_path instead.

        Args:
            entity_id: Entity ID or display name from search_entities or graph_query results.
            repo: Name of the registered repo. If None, uses the default repo.
            include_source: If True, includes source code from storage_views. Default: False.
            response_format: 'detailed' (default), 'concise'.
        """
        try:
            repo_name, reader = _resolve_repo(repo, default_root)
        except ValueError as e:
            return _err(str(e), error_type=CLIENT_ERROR, hint="Call list_repos to see available repos.")

        agent_table = reader._get_table("agent_views")
        if agent_table.num_rows == 0:
            return _err("No entities found.",
                         error_type=EXTERNAL_ERROR, hint="Run 'batho build' to populate the artifact with entities.")

        mask = pc.equal(agent_table.column("entity_id"), entity_id)
        matched = agent_table.filter(mask)
        if matched.num_rows == 0:
            resolved = _resolve_entity_id(entity_id, reader)
            if isinstance(resolved, list):
                if len(resolved) == 0:
                    return _err(f"Entity not found: {entity_id}",
                                 error_type=CLIENT_ERROR, hint="Use search_entities to find the correct entity_id.")
                else:
                    candidates = "\n".join(
                        f"  - {c['name']} [{c['type']}] {c['file']} — `{c['entity_id']}`"
                        for c in resolved
                    )
                    return _err(
                        f"Multiple entities named '{entity_id}' found. Use one of these entity_ids:\n{candidates}",
                        error_type=CLIENT_ERROR,
                        hint="Pass the exact entity_id from the list above.",
                    )
            else:
                entity_id = resolved
                mask = pc.equal(agent_table.column("entity_id"), entity_id)
                matched = agent_table.filter(mask)
                if matched.num_rows == 0:
                    return _err(f"Entity not found: {entity_id}",
                                 error_type=CLIENT_ERROR, hint="Use search_entities to find the correct entity_id.")

        entity_row = matched.to_pylist()[0]
        file_paths = _file_paths_map(reader)

        rels_table = reader._get_table("rels_views")
        rels_rows: list[dict] = []
        if rels_table.num_rows > 0:
            src_mask = pc.equal(rels_table.column("source_id"), entity_id)
            tgt_mask = pc.equal(rels_table.column("target_id"), entity_id)
            combined = pc.or_(src_mask, tgt_mask)
            rels_rows = rels_table.filter(combined).to_pylist()

        storage_rows = None
        if include_source:
            storage_table = reader._get_table("storage_views")
            if storage_table.num_rows > 0:
                smask = pc.equal(storage_table.column("entity_id"), entity_id)
                storage_rows = storage_table.filter(smask).to_pylist()

        gen = _manifest_gen(reader)
        markdown, structured = build_dual_output(
            [entity_row], rels_rows, file_paths,
            storage_rows=storage_rows,
            response_format=response_format, max_tokens=25000,
            offset=0, limit=1,
            total_nodes=1, total_edges=len(rels_rows),
            artifact_generation=gen,
        )
        res = ToolResult(content=[TextContent(type="text", text=markdown)], structured_content=structured)
        entity_fp = file_paths.get(entity_row.get("file_id", -1))
        return _inject_banner(res, repo_name, file_path=entity_fp)

    @app.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False, destructiveHint=False))
    async def trace_path(
        source_entity_id: str,
        target_entity_id: str,
        repo: str | None = None,
        max_depth: int = 5,
        relation_types: list[str] | None = None,
        response_format: str = "concise",
        ctx: Context | None = None,
    ) -> ToolResult:
        """Find the shortest dependency path between two entities in the code graph using BFS.

        Use this to answer 'how does X reach Y?' or 'what is the call chain from A to B?'.
        Returns the shortest path with relation types at each hop.
        Do NOT use grep to trace call chains — this uses BFS on the pre-built graph.
        Use search_entities first to find entity_ids if you only have names.

        Args:
            source_entity_id: Entity ID or display name of the starting point.
            target_entity_id: Entity ID or display name of the destination.
            repo: Name of the registered repo. If None, uses the default repo.
            max_depth: Maximum BFS depth. Default: 5. Maximum: 20.
            relation_types: Filter to specific relation types (e.g. ['CALLS']).
            response_format: 'concise' (default), 'detailed'.
        """
        try:
            repo_name, reader = _resolve_repo(repo, default_root)
        except ValueError as e:
            return _err(str(e), error_type=CLIENT_ERROR, hint="Call list_repos to see available repos.")

        max_depth = min(max(max_depth, 1), 20)

        agent_table = reader._get_table("agent_views")
        for _field, _val in [("source", source_entity_id), ("target", target_entity_id)]:
            _mask = pc.equal(agent_table.column("entity_id"), _val)
            if agent_table.filter(_mask).num_rows > 0:
                continue
            resolved = _resolve_entity_id(_val, reader)
            if isinstance(resolved, list):
                if len(resolved) == 0:
                    return _err(f"Entity not found: {_val}",
                                 error_type=CLIENT_ERROR, hint="Use search_entities to find the correct entity_id.")
                else:
                    candidates = "\n".join(
                        f"  - {c['name']} [{c['type']}] {c['file']} — `{c['entity_id']}`"
                        for c in resolved
                    )
                    return _err(
                        f"Multiple entities named '{_val}' found. Use one of these entity_ids:\n{candidates}",
                        error_type=CLIENT_ERROR,
                        hint="Pass the exact entity_id from the list above.",
                    )
            else:
                if _field == "source":
                    source_entity_id = resolved
                else:
                    target_entity_id = resolved

        rels_table = reader._get_table("rels_views")
        if rels_table.num_rows == 0:
            return _err("No relationships found in artifact.",
                         error_type=EXTERNAL_ERROR, hint="Run 'batho build' to populate the artifact with relationships.")

        all_rels = rels_table.to_pylist()
        if relation_types:
            all_rels = [r for r in all_rels if r.get("relation_type") in relation_types]

        adjacency: dict[str, list[tuple[str, str]]] = {}
        for rel in all_rels:
            sid = rel.get("source_id", "")
            tid = rel.get("target_id", "")
            rt = rel.get("relation_type", "")
            adjacency.setdefault(sid, []).append((tid, rt))

        if source_entity_id not in adjacency and source_entity_id != target_entity_id:
            return _err(f"Source entity not found or has no outgoing edges: {source_entity_id}",
                         error_type=CLIENT_ERROR, hint="Use search_entities to find the correct entity_id, or check if the entity exists via get_entity.")

        from collections import deque
        queue: deque[list[tuple[str, str]]] = deque()
        visited: set[str] = {source_entity_id}
        queue.append([(source_entity_id, "")])

        path: list[tuple[str, str]] | None = None
        current_depth = 0
        while queue:
            current = queue.popleft()
            current_id = current[-1][0]
            current_depth = len(current) - 1
            if ctx and current_depth > 0 and current_depth % 5 == 0:
                await ctx.report_progress(current_depth, max_depth)
            if current_id == target_entity_id:
                path = current
                break
            if len(current) - 1 >= max_depth:
                continue
            for next_id, rt in adjacency.get(current_id, []):
                if next_id not in visited:
                    visited.add(next_id)
                    queue.append(current + [(next_id, rt)])

        if path is None:
            return _err(f"No path found from {source_entity_id} to {target_entity_id} within depth {max_depth}.",
                         error_type=CLIENT_ERROR, retryable=True, hint="Try increasing max_depth, or verify both entity_ids using search_entities.")

        name_by_id: dict[str, str] = {}
        if agent_table.num_rows > 0:
            for row in agent_table.to_pylist():
                name_by_id[row.get("entity_id", "")] = row.get("name", "")

        lines: list[str] = ["## Path Trace"]
        for i, (eid, rt) in enumerate(path):
            name = name_by_id.get(eid, eid)
            if i == 0:
                lines.append(f"  {name}")
            else:
                lines.append(f"  → [{rt}] {name}")
        lines.append(f"\nDepth: {len(path) - 1} hops")

        structured = {
            "path": [{"entity_id": eid, "relation_type": rt, "name": name_by_id.get(eid, eid)} for eid, rt in path],
            "depth": len(path) - 1,
            "meta": {"artifact_generation": _manifest_gen(reader)},
        }
        res = ToolResult(content=[TextContent(type="text", text="\n".join(lines))], structured_content=structured)
        return _inject_banner(res, repo_name)

    @app.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False, destructiveHint=False))
    def get_file_graph(
        file_path: str,
        repo: str | None = None,
        include_cross_file_refs: bool = True,
        response_format: str = "concise",
        max_tokens: int = 25000,
    ) -> ToolResult:
        """Get all entities and relationships within a single file.

        Optionally includes cross-file reference stubs (entities referenced from other files).
        Use this to understand a file's internal structure and external dependencies.
        Do NOT use read or grep — this returns all entities and relationships in one call.
        Do NOT use graph_query for file analysis — this is faster and more complete.

        Args:
            file_path: Path to the file (relative to repo root, forward slashes).
            repo: Name of the registered repo. If None, uses the default repo.
            include_cross_file_refs: If True (default), includes stub entities from cross-file references.
            response_format: 'concise' (default), 'detailed'.
            max_tokens: Maximum tokens for content field. Default: 25000.
        """
        try:
            repo_name, reader = _resolve_repo(repo, default_root)
        except ValueError as e:
            return _err(str(e), error_type=CLIENT_ERROR, hint="Call list_repos to see available repos.")

        norm_fp = _canonicalize_untrusted_path(str(file_path))
        fid = reader.file_id_for_path(norm_fp)
        if fid is None:
            return _err(f"File not indexed: {norm_fp}",
                         error_type=CLIENT_ERROR, hint="Use graph_overview to see all indexed files.")

        file_artifacts = reader.get_file_artifacts_by_id(fid, include_storage=True)
        agent_rows = file_artifacts.get("agent_view", []) if file_artifacts else []
        rels_rows = file_artifacts.get("rels_view", []) if file_artifacts else []
        storage_rows = file_artifacts.get("storage_view", []) if file_artifacts else []

        if include_cross_file_refs and rels_rows:
            agent_table = reader._get_table("agent_views")
            if agent_table.num_rows > 0:
                known_ids = {r.get("entity_id", "") for r in agent_rows}
                cross_ids = set()
                for rel in rels_rows:
                    sid = rel.get("source_id", "")
                    tid = rel.get("target_id", "")
                    if sid and sid not in known_ids:
                        cross_ids.add(sid)
                    if tid and tid not in known_ids:
                        cross_ids.add(tid)
                if cross_ids:
                    mask = pc.is_in(agent_table.column("entity_id"), value_set=pa.array(list(cross_ids)))
                    matched = agent_table.filter(mask)
                    if matched.num_rows > 0:
                        agent_rows.extend(matched.to_pylist())

        file_paths = _file_paths_map(reader)
        gen = _manifest_gen(reader)

        markdown, structured = build_dual_output(
            agent_rows, rels_rows, file_paths,
            storage_rows=storage_rows if response_format == "detailed" else None,
            response_format=response_format, max_tokens=max_tokens,
            offset=0, limit=len(agent_rows),
            total_nodes=len(agent_rows), total_edges=len(rels_rows),
            artifact_generation=gen,
        )
        res = ToolResult(content=[TextContent(type="text", text=markdown)], structured_content=structured)
        return _inject_banner(res, repo_name, file_path=norm_fp)

    @app.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False, destructiveHint=False))
    def search_entities(
        query: str,
        repo: str | None = None,
        entity_types: list[str] | None = None,
        limit: int = 25,
        response_format: str = "concise",
    ) -> ToolResult:
        """Search for entities by name using substring regex match.

        Returns matching entities with optional type filter and file locations.
        Each result includes the entity_id in backticks for use with get_entity or trace_path.
        Use this to find entity_ids for get_entity or trace_path.
        Do NOT use grep — this is faster and returns structured results with entity_ids.
        Do NOT use graph_query for name search — this is optimized for name matching.

        Args:
            query: Substring or regex pattern to match entity names.
            repo: Name of the registered repo. If None, uses the default repo.
            entity_types: Filter to specific types (e.g. ['FUNCTION', 'CLASS']).
            limit: Maximum results. Default: 25.
            response_format: 'concise' (default), 'detailed'.
        """
        try:
            repo_name, reader = _resolve_repo(repo, default_root)
        except ValueError as e:
            return _err(str(e), error_type=CLIENT_ERROR, hint="Call list_repos to see available repos.")

        agent_table = reader._get_table("agent_views")
        if agent_table.num_rows == 0:
            return _err("No entities found in artifact.",
                         error_type=EXTERNAL_ERROR, hint="Run 'batho build' to populate the artifact with entities.")

        if len(query) > 200:
            return _err("query too long (max 200 chars).",
                         error_type=CLIENT_ERROR, hint="Use a shorter search query.")
        try:
            mask = pc.match_substring_regex(agent_table.column("name"), query)
        except Exception:
            mask = pc.match_substring(agent_table.column("name"), query)
        table = agent_table.filter(mask)

        if entity_types:
            masks = [pc.equal(table.column("entity_type"), et) for et in entity_types]
            combined = masks[0]
            for m in masks[1:]:
                combined = pc.or_(combined, m)
            table = table.filter(combined)

        total = table.num_rows
        rows = table.to_pylist()[:limit]

        file_paths = _file_paths_map(reader)
        gen = _manifest_gen(reader)

        lines: list[str] = [f"## Search Results ({total} matches, showing {len(rows)})"]
        for row in rows:
            name = row.get("name", "")
            etype = row.get("entity_type", "")
            eid = row.get("entity_id", "")
            fp = file_paths.get(row.get("file_id", -1), "")
            lr = ""
            sl = row.get("start_line")
            el = row.get("end_line")
            if sl:
                lr = f"L{sl}" if not el or el == sl else f"L{sl}-{el}"
            lines.append(f"- {name} [{etype}] {fp}:{lr} — `{eid}`")

        structured = {
            "results": [build_node_dict_simple(r, file_paths) for r in rows],
            "meta": {"total_matches": total, "returned": len(rows), "artifact_generation": gen},
        }
        res = ToolResult(content=[TextContent(type="text", text="\n".join(lines))], structured_content=structured)
        return _inject_banner(res, repo_name)

    @app.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False, destructiveHint=False))
    def get_delta(
        repo: str | None = None,
        run_id: str | None = None,
        change_kind: str | None = None,
        file_path: str | None = None,
        limit: int = 100,
        offset: int = 0,
        response_format: str = "concise",
    ) -> ToolResult:
        """Get incremental changes from the latest patch run (or a specific run).

        Shows added/removed/modified/renamed nodes from 'batho patch'.
        Use this after running 'batho patch' to review what changed.
        Do NOT re-scan the entire codebase — this returns node-level changes only.
        The graph is already updated via MVCC — no server restart needed.

        Args:
            repo: Name of the registered repo. If None, uses the default repo.
            run_id: Specific patch run ID. If None, uses the latest completed run.
            change_kind: Filter to 'added', 'removed', 'modified', or 'renamed'. None = all.
            file_path: Filter to changes in a specific file.
            limit: Maximum changes to return. Default: 100.
            offset: Pagination offset. Default: 0.
            response_format: 'concise' (default), 'detailed'.
        """
        try:
            repo_name, reader = _resolve_repo(repo, default_root)
        except ValueError as e:
            return _err(str(e), error_type=CLIENT_ERROR, hint="Call list_repos to see available repos.")

        changes, delta_stats, run_info = read_delta(
            reader, run_id=run_id, change_kind=change_kind,
            file_path=file_path, limit=limit, offset=offset,
        )

        if not run_info and not changes:
            return _err("No patch runs found.",
                         error_type=EXTERNAL_ERROR, hint="Run 'batho patch --root <path>' first to create incremental changes.")

        markdown = format_delta_markdown(changes, delta_stats, run_info, response_format)
        structured = build_delta_structured(changes, delta_stats, run_info)
        res = ToolResult(content=[TextContent(type="text", text=markdown)], structured_content=structured)
        return _inject_banner(res, repo_name, file_path=file_path)

    # -------------------------------------------------------------------
    # Phase 1 New Tools
    # -------------------------------------------------------------------

    @app.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False, destructiveHint=False))
    def batho_status(repo: str | None = None) -> ToolResult:
        """Show artifact and watcher status for one or all repos.

        Args:
            repo: Name of the registered repo. If None, shows status for all repos.
        """
        entries: list[RepoEntry] = []
        if repo:
            e = registry.get(repo) if registry else None
            if not e and default_root:
                e = RepoEntry(name="default", path=default_root)
            if not e:
                return _err(f"Repo '{repo}' not found.", error_type=CLIENT_ERROR, hint="Call list_repos to see registered repos.")
            entries = [e]
        elif registry:
            entries = registry.list_all()
        elif default_root:
            entries = [RepoEntry(name="default", path=default_root)]

        if not entries:
            return _err("No repos registered or root specified.", error_type=CLIENT_ERROR, hint="Call add_repo to register a repository.")

        watcher_status = watcher.status() if watcher else {}
        results = []
        lines = ["## Batho System Status", ""]

        for entry in entries:
            has_art = RepoRegistry.has_artifact(entry)
            run_count = 0
            latest_run_uuid = None
            if has_art:
                try:
                    r = _pool.get_by_repo(entry.name) if registry and registry.get(entry.name) else _pool.get_by_root(entry.path)
                    runs = r.get_all_runs()
                    run_count = len(runs)
                    if runs:
                        latest_run_uuid = runs[-1].get("run_uuid")
                except Exception:
                    pass

            ws = watcher_status.get(entry.name, {})
            is_watching = ws.get("watching", entry.watch)
            sync_state = ws.get("sync_state", entry.sync_state)
            pending_files = ws.get("pending_files", [])
            last_synced = entry.last_synced

            status_icon = "✓" if sync_state == "idle" else ("⏳" if sync_state in ("pending", "patching") else "❌")
            lines.append(f"### {entry.name} ({status_icon} {sync_state})")
            lines.append(f"- Path: `{entry.path}`")
            lines.append(f"- Artifact: {'✓ present' if has_art else '✗ missing'} ({run_count} runs, latest: `{latest_run_uuid or 'N/A'}`)")
            lines.append(f"- Watcher: {'✓ active' if is_watching else '✗ inactive'} (debounce: {entry.debounce_ms}ms)")
            if pending_files:
                lines.append(f"- Pending files ({len(pending_files)}): {', '.join(pending_files[:5])}{'...' if len(pending_files) > 5 else ''}")
            if last_synced:
                lines.append(f"- Last synced: {last_synced}")
            lines.append("")

            results.append({
                "repo": entry.name,
                "path": entry.path,
                "has_artifact": has_art,
                "run_count": run_count,
                "latest_run_uuid": latest_run_uuid,
                "watching": is_watching,
                "sync_state": sync_state,
                "pending_sync_files": pending_files,
                "last_synced": last_synced,
                "debounce_ms": entry.debounce_ms,
            })

        structured = {"repos": results, "total": len(results)}
        return ToolResult(content=[TextContent(type="text", text="\n".join(lines).strip())], structured_content=structured)

    @app.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False, destructiveHint=False))
    def batho_list_runs(
        repo: str | None = None,
        limit: int = 20,
    ) -> ToolResult:
        """List patch/build run IDs for a repo.

        Args:
            repo: Name of the registered repo. If None, uses default repo.
            limit: Maximum runs to return. Default: 20.
        """
        try:
            repo_name, reader = _resolve_repo(repo, default_root)
        except ValueError as e:
            return _err(str(e), error_type=CLIENT_ERROR, hint="Call list_repos to see available repos.")

        runs = reader.get_all_runs()
        if not runs:
            return _err("No runs found in artifact.", error_type=EXTERNAL_ERROR, hint="Run 'batho build' first.")

        recent_runs = runs[-limit:][::-1]
        lines = [f"## Run History for `{repo_name}` ({len(runs)} total runs)", ""]
        structured_runs = []
        for r in recent_runs:
            ruid = r.get("run_uuid", "")
            rtype = r.get("run_type", "unknown")
            cat = r.get("created_at", "")
            commit = r.get("git_commit", "")
            lines.append(f"- `{ruid}` [{rtype}] {cat} (commit: {commit or 'N/A'})")
            structured_runs.append({
                "run_uuid": ruid,
                "run_type": rtype,
                "created_at": cat,
                "completed_at": r.get("completed_at"),
                "git_commit": commit,
            })

        structured = {"repo": repo_name, "runs": structured_runs, "total_runs": len(runs)}
        return ToolResult(content=[TextContent(type="text", text="\n".join(lines))], structured_content=structured)

    # -------------------------------------------------------------------
    # Phase 2 New Tools (Command-as-Tools)
    # -------------------------------------------------------------------


    @app.tool(annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=True, destructiveHint=True))
    async def batho_build(
        repo: str | None = None,
        full: bool = False,
        max_workers: int | None = None,
        max_file_size_kb: int | None = None,
        graph_backend: str | None = None,
    ) -> ToolResult:
        """Run a full index build for a repository.

        Creates a complete code graph in .batho/artifact/.
        Do NOT use this for routine file changes — use batho_patch for incremental updates.

        Args:
            repo: Name of the registered repo or root path. If None, uses default repo.
            full: Force a complete rebuild even if an artifact already exists.
            max_workers: Maximum worker threads for indexing.
            max_file_size_kb: Skip files larger than this size in KB.
            graph_backend: Graph engine backend ('networkx').
        """
        try:
            root_path = _resolve_root_path(repo, default_root, registry)
            repo_name = repo or (registry.list_all()[0].name if registry and registry.list_all() else "default")
        except ValueError as e:
            return _err(str(e), error_type=CLIENT_ERROR, hint="Specify a repo parameter or start server with --root.")

        from batho.orchestrator.build import run_build, BuildOptions

        try:
            options = BuildOptions(
                root=Path(root_path),
                force_full=full,
                max_workers=max_workers,
                max_file_size_kb=max_file_size_kb,
                graph_backend=graph_backend,
            )
            # run_build already acquires InterProcessLock internally on
            # <root>/.batho/batho.lock, so no outer lock is needed here.
            res = await asyncio.to_thread(run_build, options)
            _pool.invalidate(repo_name, root_path=root_path)
            res_dict = _as_dict(res)

            if not res_dict.get("success", False):
                msgs = res_dict.get("warnings") or ["Build failed"]
                return _err(f"Build failed: {'; '.join(msgs)}", error_type=EXTERNAL_ERROR)

            if "already_built" in res_dict.get("warnings", []):
                msg = f"Repository at `{root_path}` already has an artifact. Use `full=True` to force rebuild or `batho_patch` for incremental updates."
                return ToolResult(content=[TextContent(type="text", text=msg)], structured_content=res_dict)

            entity_count = res_dict.get("entity_count", 0)
            rel_count = res_dict.get("relationship_count", 0)
            run_id = res_dict.get("run_id", "")
            file_count = res_dict.get("file_count", 0)

            markdown = f"## Build Completed Successfully\n\n- Repo: `{repo_name}` (`{root_path}`)\n- Run ID: `{run_id}`\n- Entities: {entity_count}\n- Relationships: {rel_count}\n- Files indexed: {file_count}"
            structured = {
                "success": True,
                "repo": repo_name,
                "run_id": run_id,
                "entity_count": entity_count,
                "relationship_count": rel_count,
                "file_count": file_count,
                "duration_ms": res_dict.get("duration_ms", 0),
            }
            return ToolResult(content=[TextContent(type="text", text=markdown)], structured_content=structured)
        except Exception as exc:
            LOGGER.error("batho_build_failed", repo=repo_name, error=str(exc))
            return _err(f"Build failed: {exc}", error_type=EXTERNAL_ERROR, hint="Check permissions and repository integrity.")

    @app.tool(annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=True, destructiveHint=True))
    async def batho_patch(
        repo: str | None = None,
        max_file_size_kb: int | None = None,
        graph_backend: str | None = None,
    ) -> ToolResult:
        """Run an incremental patch on an existing artifact.

        Detects changes using content hashing. Use this after editing files to update the code graph.
        Do NOT use this on unbuilt repositories — run batho_build first.

        Note: If the watcher engine is running (default), it auto-patches on file
        changes. Only call this manually if the watcher is off (--no-watch) or
        to force a refresh. May block briefly if the watcher is mid-patch.

        Args:
            repo: Name of the registered repo or root path. If None, uses default repo.
            max_file_size_kb: Skip files larger than this size in KB.
            graph_backend: Graph engine backend.
        """
        try:
            root_path = _resolve_root_path(repo, default_root, registry)
            repo_name = repo or (registry.list_all()[0].name if registry and registry.list_all() else "default")
        except ValueError as e:
            return _err(str(e), error_type=CLIENT_ERROR, hint="Specify a repo parameter or start server with --root.")

        artifact_dir = Path(root_path) / ".batho" / "artifact"
        if not artifact_dir.exists():
            return _err(f"No artifact found at {artifact_dir}.", error_type=EXTERNAL_ERROR, hint="Run batho_build first to create the initial artifact.")

        LOGGER.info(
            "mcp_tool_invocation",
            tool="batho_patch",
            repo=repo_name,
            principal="mcp-client",
            timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        )

        from batho.orchestrator.patch import run_patch, PatchOptions

        try:
            options = PatchOptions(
                root=Path(root_path),
                max_file_size_kb=max_file_size_kb,
                graph_backend=graph_backend,
            )
            # run_patch already acquires InterProcessLock internally on
            # <root>/.batho/batho.lock, so no outer lock is needed here.
            res = await asyncio.to_thread(run_patch, options)
            _pool.invalidate(repo_name, root_path=root_path)
            res_dict = _as_dict(res)

            if not res_dict.get("success", False):
                msgs = res_dict.get("warnings") or ["Patch failed"]
                return _err(f"Patch failed: {'; '.join(msgs)}", error_type=EXTERNAL_ERROR)

            changes_applied = res_dict.get("changes_applied", 0)
            run_id = res_dict.get("run_id", "")

            if changes_applied == 0:
                markdown = f"## Patch Check\n\nNo changes detected in `{repo_name}`."
            else:
                added = res_dict.get("added", 0)
                modified = res_dict.get("modified", 0)
                deleted = res_dict.get("deleted", 0)
                markdown = f"## Patch Applied Successfully\n\n- Repo: `{repo_name}`\n- Run ID: `{run_id}`\n- Files changed: {changes_applied} (Added: {added}, Modified: {modified}, Deleted: {deleted})\n- Nodes: +{res_dict.get('nodes_added', 0)}, -{res_dict.get('nodes_removed', 0)}, ~{res_dict.get('nodes_modified', 0)}"

            structured = {
                "success": True,
                "repo": repo_name,
                "run_id": run_id,
                "changes_applied": changes_applied,
                "added": res_dict.get("added", 0),
                "modified": res_dict.get("modified", 0),
                "deleted": res_dict.get("deleted", 0),
                "nodes_added": res_dict.get("nodes_added", 0),
                "nodes_removed": res_dict.get("nodes_removed", 0),
                "nodes_modified": res_dict.get("nodes_modified", 0),
                "nodes_renamed": res_dict.get("nodes_renamed", 0),
                "duration_ms": res_dict.get("duration_ms", 0),
            }
            return ToolResult(content=[TextContent(type="text", text=markdown)], structured_content=structured)
        except Exception as exc:
            LOGGER.error("batho_patch_failed", repo=repo_name, error=str(exc))
            return _err(f"Patch failed: {exc}", error_type=EXTERNAL_ERROR, hint="Run batho_build if artifact is corrupted.")

    VALID_EXPORT_VIEWS = {"storage", "agent", "overview", "files", "symbols", "dependencies", "delta", "rel"}

    @app.tool(annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=True, destructiveHint=True))
    async def batho_export(
        repo: str | None = None,
        view: str = "storage",
        output: str | None = None,
        index_id: str | None = None,
        filter_pattern: str | None = None,
        category: str = "all",
        token_budget: int | None = None,
        json_mode: bool = True,
        include_relationships: bool = False,
    ) -> ToolResult:
        """Export a JSON view or Pack artifact from the code graph.

        Do NOT use this for single entity lookup — use get_entity or graph_query instead.

        Args:
            repo: Name of the registered repo or root path.
            view: View type to export ('storage', 'agent', 'overview', 'files', 'symbols', 'dependencies', 'delta', 'rel'). Default: 'storage'.
            output: Path to write the output JSON or ZIP file.
            index_id: Specific index ID.
            filter_pattern: Glob pattern to filter exported files/nodes.
            category: Node category filter.
            token_budget: Maximum tokens for inline export content.
            json_mode: If True (default), export JSON view. If False, export ZIP pack.
            include_relationships: Include relationships in JSON export.
        """
        if view.lower() not in VALID_EXPORT_VIEWS:
            return _err(f"Invalid view '{view}'. Must be one of {sorted(VALID_EXPORT_VIEWS)}.", error_type=CLIENT_ERROR)

        try:
            root_path = _resolve_root_path(repo, default_root, registry)
            repo_name = repo or (registry.list_all()[0].name if registry and registry.list_all() else "default")
        except ValueError as e:
            return _err(str(e), error_type=CLIENT_ERROR, hint="Specify a repo parameter or start server with --root.")

        from batho.orchestrator.export import run_export, ExportOptions

        try:
            out_path = sanitize_path(output, base_dir=root_path, allow_absolute=False) if output else None
        except PathSecurityError as exc:
            return _err(f"Output path rejected: {exc}", error_type=CLIENT_ERROR,
                        hint="Output must be a relative path under the repo root.")
        try:
            options = ExportOptions(
                root=Path(root_path),
                view=view,
                output=out_path,
                filter_pattern=filter_pattern,
                category=category,
                index_id=index_id,
                token_budget=token_budget,
                include_relationships=include_relationships,
                pack=not json_mode,
            )
            res = await asyncio.to_thread(run_export, options)
            res_dict = _as_dict(res)

            if not res_dict.get("success", False):
                errs = res_dict.get("errors", ["Unknown export error"])
                return _err(f"Export failed: {'; '.join(errs)}", error_type=EXTERNAL_ERROR)

            out_file = res_dict.get("output_path")
            target_file = str(out_file) if out_file else (str(out_path) if out_path else None)
            if json_mode and target_file and Path(target_file).exists():
                try:
                    target_path = Path(target_file)
                    file_size = target_path.stat().st_size
                    MAX_EXPORT_READ_BYTES = 1_000_000
                    if file_size > MAX_EXPORT_READ_BYTES:
                        toks = file_size // 4
                        if token_budget and toks > token_budget:
                            markdown = f"## Export Completed\n\nOutput saved to file `{target_file}` ({toks} tokens exceeds budget of {token_budget})."
                        else:
                            markdown = f"## Export Completed\n\nOutput saved to file `{target_file}` ({file_size} bytes). File is too large to return in the message ({MAX_EXPORT_READ_BYTES} byte cap)."
                        structured = {"success": True, "output_path": target_file, "file_size": file_size, "tokens": toks}
                        return ToolResult(content=[TextContent(type="text", text=markdown)], structured_content=structured)
                    content_text = target_path.read_text(encoding="utf-8")
                    toks = estimate_tokens(content_text)
                    if token_budget and toks > token_budget:
                        markdown = f"## Export Completed\n\nOutput saved to file `{target_file}` ({toks} tokens exceeds budget of {token_budget})."
                        structured = {"success": True, "output_path": target_file, "tokens": toks}
                    else:
                        markdown = f"## Export Result\n\n```json\n{content_text[:5000]}\n```" + ("\n...(content truncated for display)..." if len(content_text) > 5000 else "")
                        structured = {"success": True, "output_path": target_file, "data": res_dict}
                    return ToolResult(content=[TextContent(type="text", text=markdown)], structured_content=structured)
                except Exception:
                    pass

            markdown = f"## Export Completed\n\nArtifact saved to `{target_file or 'configured path'}`."
            structured = {"success": True, "output_path": target_file, "result": res_dict}
            return ToolResult(content=[TextContent(type="text", text=markdown)], structured_content=structured)
        except Exception as exc:
            LOGGER.error("batho_export_failed", repo=repo_name, error=str(exc))
            return _err(f"Export failed: {exc}", error_type=EXTERNAL_ERROR, hint="Check logs for details and retry.")

    @app.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False, destructiveHint=False))
    def batho_diff(
        repo: str | None = None,
        run_id: str | None = None,
        entity_id: str | None = None,
        file_path: str | None = None,
        since: str | None = None,
    ) -> ToolResult:
        """Query node-level changes across runs, entities, or files.

        Must provide exactly ONE of run_id, entity_id, or file_path.
        Do NOT use git diff for code-graph node changes — use this tool instead.

        Args:
            repo: Name of the registered repo.
            run_id: Fetch all file and node changes in a specific run.
            entity_id: Fetch historical changes for a single entity across runs.
            file_path: Fetch node changes for a specific file across runs.
            since: Run ID threshold when querying entity history (only with entity_id).
        """
        targets = [t for t in (run_id, entity_id, file_path) if t is not None]
        if len(targets) != 1:
            return _err("Must specify exactly ONE of run_id, entity_id, or file_path.", error_type=CLIENT_ERROR, hint="Provide exactly one target parameter.")
        if since and not entity_id:
            return _err("Parameter 'since' can only be used with 'entity_id'.", error_type=CLIENT_ERROR, hint="Remove 'since' or use it with 'entity_id'.")

        try:
            root_path = _resolve_root_path(repo, default_root, registry)
            repo_name = repo or (registry.list_all()[0].name if registry and registry.list_all() else "default")
        except ValueError as e:
            return _err(str(e), error_type=CLIENT_ERROR, hint="Call list_repos to see available repos.")

        if _pool:
            _pool.invalidate(repo_name, root_path=root_path)
        repo_name, reader = _resolve_repo(repo, default_root)
        reader.invalidate()

        db = BathoBundle(root_path)

        if run_id:
            run_meta = reader.get_run(run_id)
            if not run_meta:
                return _err(f"Run '{run_id}' not found.", error_type=CLIENT_ERROR)
            changes = db.get_run_file_changelog(run_id)
            lines = [f"## Diff for Run `{run_id}`", ""]
            if not changes:
                lines.append("No node changes recorded for this run.")
            else:
                by_kind = defaultdict(list)
                for c in changes:
                    by_kind[c.get("change_kind", "unknown")].append(c)
                for kind in ("added", "removed", "modified", "renamed"):
                    items = by_kind[kind]
                    if items:
                        lines.append(f"### {kind.capitalize()} ({len(items)})")
                        for item in sorted(items, key=lambda x: (x.get("file_path", ""), x.get("entity_name", ""))):
                            lines.append(f"- [{item.get('entity_type')}] **{item.get('entity_name')}** in `{item.get('file_path')}` (`{item.get('entity_id')}`)")
            structured = {"run_id": run_id, "changes": changes}

        elif entity_id:
            since_completed_at = None
            if since:
                srun = reader.get_run(since)
                if not srun:
                    return _err(f"Run '{since}' not found.", error_type=CLIENT_ERROR)
                since_completed_at = srun.get("completed_at")
            history = db.get_file_node_history(
                entity_id,
                since_completed_at=since_completed_at,
                since_run_uuid=since,
            )
            lines = [f"## History for Entity `{entity_id}`", ""]
            if not history:
                lines.append("No history found for entity.")
            else:
                for entry in history:
                    lines.append(f"- `{entry.get('base_run_uuid')}` → `{entry.get('run_uuid')}` [{entry.get('change_kind')}]")
            structured = {"entity_id": entity_id, "history": history}

        else:  # file_path
            norm_fp = _canonicalize_untrusted_path(str(file_path))
            results = db.get_file_changelog_raw(norm_fp)
            lines = [f"## Node Changes for File `{norm_fp}`", ""]
            if not results:
                lines.append("No node changes found for this file.")
            else:
                for item in results:
                    lines.append(f"- [{item.get('change_kind')}] **{item.get('entity_name')}** [{item.get('entity_type')}] (`{item.get('base_run_uuid')}` → `{item.get('run_uuid')}`)")
            structured = {"file_path": norm_fp, "changes": results}

        return ToolResult(content=[TextContent(type="text", text="\n".join(lines))], structured_content=structured)

    @app.tool(annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=False, destructiveHint=True))
    async def batho_gc(
        repo: str | None = None,
        subcommand: str = "status",
        run_uuid: str | None = None,
        older_than: int | None = None,
    ) -> ToolResult:
        """Run garbage collection and maintenance on an artifact database.

        Do NOT use this during active indexing operations.

        Args:
            repo: Name of the registered repo or root path.
            subcommand: GC action ('status', 'run', 'runs', 'vacuum', 'orphans'). Default: 'status'.
            run_uuid: Specific run UUID to prune (required if subcommand='run').
            older_than: Prune runs older than N days (required if subcommand='runs').
        """
        valid_subs = {"status", "run", "runs", "vacuum", "orphans"}
        if subcommand not in valid_subs:
            return _err(f"Invalid subcommand '{subcommand}'. Must be one of {sorted(valid_subs)}.", error_type=CLIENT_ERROR)

        if subcommand == "run" and not run_uuid:
            return _err("subcommand='run' requires run_uuid parameter.", error_type=CLIENT_ERROR)
        if subcommand == "runs" and older_than is None:
            return _err("subcommand='runs' requires older_than parameter.", error_type=CLIENT_ERROR)

        try:
            root_path = _resolve_root_path(repo, default_root, registry)
            repo_name = repo or (registry.list_all()[0].name if registry and registry.list_all() else "default")
        except ValueError as e:
            return _err(str(e), error_type=CLIENT_ERROR, hint="Specify a repo parameter or start server with --root.")

        from batho.orchestrator.gc import run_gc, GCOptions

        try:
            options = GCOptions(
                root=Path(root_path),
                command=subcommand,
                run_uuid=run_uuid,
                older_than=older_than,
            )
            res = await asyncio.to_thread(_with_repo_lock, root_path, lambda: run_gc(options))
            _pool.invalidate(repo_name, root_path=root_path)
            res_dict = _as_dict(res)

            msg = res_dict.get("message", f"GC {subcommand} completed successfully.")
            markdown = f"## Garbage Collection: `{subcommand}`\n\n{msg}"
            structured = {"success": res_dict.get("success", True), "subcommand": subcommand, "result": res_dict}
            return ToolResult(content=[TextContent(type="text", text=markdown)], structured_content=structured)
        except Exception as exc:
            LOGGER.error("batho_gc_failed", repo=repo_name, error=str(exc))
            return _err(f"GC failed: {exc}", error_type=EXTERNAL_ERROR, hint="Check logs for details and retry.")

    @app.tool(annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=False, destructiveHint=True))
    async def batho_fix(
        repo: str | None = None,
        deep: bool = False,
        dry_run: bool = False,
        target: str = "all",
        phase: int | None = None,
        parallel: bool = False,
    ) -> ToolResult:
        """Run integrity verification and repair on an artifact database.

        Do NOT run with dry_run=False unless issues have been verified.

        Args:
            repo: Name of the registered repo.
            deep: Perform deep table-level structural checks.
            dry_run: Inspect issues without modifying the database.
            target: Target checks ('all', 'bundle', 'state', 'blobs', 'graph'). Default: 'all'.
            phase: Repair phase filter (1-4).
            parallel: Run checks in parallel threads.
        """
        valid_targets = {"all", "bundle", "state", "blobs", "graph"}
        if target not in valid_targets:
            return _err(
                f"Invalid target '{target}'. Must be one of {sorted(valid_targets)}.",
                error_type=CLIENT_ERROR,
            )

        try:
            root_path = _resolve_root_path(repo, default_root, registry)
            repo_name = repo or (registry.list_all()[0].name if registry and registry.list_all() else "default")
        except ValueError as e:
            return _err(str(e), error_type=CLIENT_ERROR, hint="Specify a repo parameter or start server with --root.")

        artifact_dir = Path(root_path) / ".batho" / "artifact"
        if not artifact_dir.exists():
            return _err(f"No artifact bundle found at {artifact_dir}.", error_type=EXTERNAL_ERROR)

        LOGGER.info(
            "mcp_tool_invocation",
            tool="batho_fix",
            repo=repo_name,
            principal="mcp-client",
            timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        )

        from batho.modules.integrity.engine import FixEngine
        from batho.modules.integrity.report import ReportGenerator

        def _run_fix_inner():
            engine = FixEngine(
                root=Path(root_path),
                deep_mode=deep,
                dry_run=dry_run,
                target=target,
                phase=phase,
                parallel=parallel,
                verbose=False,
            )
            result = engine.run()
            rep_gen = ReportGenerator(format="markdown")
            markdown_report = rep_gen.generate(result)
            return result, markdown_report

        def _run_fix_locked():
            return _with_repo_lock(root_path, _run_fix_inner)

        try:
            result, markdown_report = await asyncio.to_thread(_run_fix_locked)
            _pool.invalidate(repo_name, root_path=root_path)

            summary = getattr(result, "summary", None)
            repairs = getattr(result, "repairs", []) or []
            structured = {
                "success": True,
                "repo": repo_name,
                "issues_found": getattr(summary, "total_findings", 0) if summary else 0,
                "repaired": getattr(summary, "repairs_successful", 0) if summary else 0,
                "repairs_attempted": getattr(summary, "repairs_attempted", 0) if summary else 0,
                "checks_passed": getattr(summary, "checks_passed", 0) if summary else 0,
                "checks_failed": getattr(summary, "checks_failed", 0) if summary else 0,
                "checks_fixed": getattr(summary, "checks_fixed", 0) if summary else 0,
                "checks_skipped": getattr(summary, "checks_skipped", 0) if summary else 0,
                "repairs_count": len(repairs),
                "dry_run": dry_run,
            }
            return ToolResult(content=[TextContent(type="text", text=markdown_report)], structured_content=structured)
        except Exception as exc:
            LOGGER.error("batho_fix_failed", repo=repo_name, error=str(exc))
            return _err(f"Fix failed: {exc}", error_type=EXTERNAL_ERROR, hint="Check logs for details and retry.")

    @app.tool(annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=False, destructiveHint=True))
    async def batho_load(
        artifact_path: str,
        repo: str | None = None,
        force: bool = False,
    ) -> ToolResult:
        """Unpack a transport artifact ZIP into .batho/artifact/.

        Do NOT use on non-zip files or corrupted archives.

        Args:
            artifact_path: Relative path to the input ZIP transport file, under the repo root.
            repo: Name of the registered repo to unpack into.
            force: Overwrite existing artifact without prompting.
        """
        try:
            root_path = _resolve_root_path(repo, default_root, registry)
            repo_name = repo or (registry.list_all()[0].name if registry and registry.list_all() else "default")
        except ValueError as e:
            return _err(str(e), error_type=CLIENT_ERROR, hint="Specify a repo parameter or start server with --root.")

        try:
            zip_file = sanitize_path(artifact_path, base_dir=root_path, allow_absolute=False)
        except PathSecurityError as exc:
            return _err(f"Artifact path rejected: {exc}", error_type=CLIENT_ERROR,
                        hint="artifact_path must be a relative path under the repo root.")
        if not zip_file.exists() or not zip_file.is_file():
            return _err(f"Artifact file not found: {artifact_path}", error_type=CLIENT_ERROR)

        from batho.orchestrator.load import run_load, LoadOptions

        try:
            options = LoadOptions(
                root=Path(root_path),
                artifact_path=zip_file,
                force=force,
            )
            res = await asyncio.to_thread(_with_repo_lock, root_path, lambda: run_load(options))
            _pool.invalidate(repo_name, root_path=root_path)
            res_dict = _as_dict(res)

            if not res_dict.get("success", False):
                errs = res_dict.get("errors") or [res_dict.get("message") or "Load failed"]
                return _err(f"Load failed: {'; '.join(errs)}", error_type=EXTERNAL_ERROR)

            gen = res_dict.get("generation", 0)
            tables_loaded = res_dict.get("tables_loaded", 0)

            markdown = f"## Artifact Loaded Successfully\n\n- Target repo: `{repo_name}`\n- Source ZIP: `{artifact_path}`\n- Generation: {gen}\n- Tables unpacked: {tables_loaded}"

            structured = {
                "success": True,
                "repo": repo_name,
                "generation": gen,
                "tables_loaded": tables_loaded,
            }
            return ToolResult(content=[TextContent(type="text", text=markdown)], structured_content=structured)
        except Exception as exc:
            LOGGER.error("batho_load_failed", repo=repo_name, error=str(exc))
            return _err(f"Load failed: {exc}", error_type=EXTERNAL_ERROR)

    # -------------------------------------------------------------------
    # Post-registration: remove disabled tools from the app so they
    # disappear from tools/list. This is done AFTER all decorators have
    # run (which register the tools) rather than conditionally wrapping
    # each function definition, to avoid re-indenting 19 multi-line bodies.
    # -------------------------------------------------------------------
    for tool_name in _tools_to_remove():
        try:
            app.local_provider.remove_tool(tool_name)
            LOGGER.info("mcp_tool_disabled", tool=tool_name)
        except Exception:
            # Tool may not exist if it was never registered; safe to skip.
            pass


def build_node_dict_simple(row: dict, file_paths: dict[int, str]) -> dict:

    return {
        "id": row.get("entity_id", ""),
        "name": row.get("name", ""),
        "type": row.get("entity_type", ""),
        "file": file_paths.get(row.get("file_id", -1), ""),
        "start_line": row.get("start_line"),
        "end_line": row.get("end_line"),
    }
