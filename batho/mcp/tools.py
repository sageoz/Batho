"""Batho MCP tools — 10 tools for code-graph intelligence."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.compute as pc
from fastmcp import FastMCP, Context
from fastmcp.tools.tool import ToolResult
from mcp.types import TextContent, ToolAnnotations

from batho.modules.storage.arrow_bundle.reader import BathoBundleReader
from batho.mcp.graph_builder import (
    build_dual_output, format_summary, estimate_tokens,
)
from batho.mcp.community_summaries import load_communities, format_communities_for_overview
from batho.mcp.delta_reader import read_delta, format_delta_markdown, build_delta_structured
from batho.mcp.registry import RepoRegistry, RepoEntry
from batho.mcp.errors import _err, CLIENT_ERROR, EXTERNAL_ERROR

import structlog

LOGGER = structlog.get_logger(__name__)


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

    def invalidate(self, repo_name: str) -> None:
        """Remove a reader from the pool (e.g. after repo removal)."""
        self._readers.pop(repo_name, None)


_pool: _ReaderPool | None = None


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
        "Use add_repo to register a repo, or start with `batho mcp --root /path/to/repo`."
    )


def _check_artifact_by_root(root_path: str) -> str | None:
    artifact_dir = Path(root_path).resolve() / ".batho" / "artifact"
    if not artifact_dir.exists():
        return f"No Batho artifact found at {artifact_dir}. Run `batho build` first."
    return None


def _check_artifact_for_repo(entry: RepoEntry) -> str | None:
    if not RepoRegistry.has_artifact(entry):
        return f"No Batho artifact found at {entry.artifact_dir}. Run `batho build` first."
    return None


# Backward-compatible aliases for tests
def _get_reader(root_path: str) -> BathoBundleReader:
    """Backward compat: get reader by root path."""
    global _pool
    if _pool is None:
        _pool = _ReaderPool()
    return _pool.get_by_root(root_path)


def _check_artifact(root_path: str) -> str | None:
    """Backward compat: check artifact by root path."""
    return _check_artifact_by_root(root_path)


def _file_paths_map(reader: BathoBundleReader) -> dict[int, str]:
    tracking = reader.get_all_file_tracking()
    return {v.get("file_id", -1): k for k, v in tracking.items()}


def _manifest_gen(reader: BathoBundleReader) -> int:
    try:
        manifest = reader._manager.load_manifest()
        return manifest.get("generation", 0)
    except Exception:
        return 0


def register_tools(
    app: FastMCP,
    default_root: str | None = None,
    registry: RepoRegistry | None = None,
) -> None:
    global _pool
    _pool = _ReaderPool(registry=registry)

    @app.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False, destructiveHint=False))
    def list_repos() -> ToolResult:
        """List all registered Batho repos and their artifact status.

        Returns a markdown list of repos with their path, artifact status, and entity count.
        Use this FIRST to discover which repos are available before calling other tools.
        Do NOT use this for querying repo contents — use graph_overview instead.
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
            lines.append(f"- **{entry.name}** — {entry.path} ({status}, {entity_count} entities)")
            structured_repos.append({
                "name": entry.name,
                "path": entry.path,
                "has_artifact": has_art,
                "entity_count": entity_count,
            })
        structured = {"repos": structured_repos, "total": len(structured_repos)}
        return ToolResult(content=[TextContent(type="text", text="\n".join(lines))], structured_content=structured)

    @app.tool(annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=False, destructiveHint=True))
    def add_repo(name: str, path: str) -> ToolResult:
        """Register a repository in the Batho MCP registry.

        The repo must have a .batho artifact (run 'batho build' first).
        Use this when you need to add a new repo to the MCP server at runtime.
        Do NOT use this for querying — use list_repos to see existing repos.

        Args:
            name: Unique name for the repo (e.g. 'myapp', 'frontend').
            path: Absolute filesystem path to the repo root.
        """
        if not registry:
            return _err("No registry configured. Cannot add repos.",
                         error_type=CLIENT_ERROR, hint="Start the server with 'batho mcp --root /path/to/repo' instead.")
        resolved = str(Path(path).resolve())
        artifact_dir = Path(resolved) / ".batho" / "artifact"
        if not artifact_dir.exists():
            return _err(f"No Batho artifact found at {artifact_dir}.",
                         error_type=EXTERNAL_ERROR, hint=f"Run 'batho build --root {resolved}' first to create the artifact.")
        entry = registry.add(name=name, path=resolved)
        _pool.invalidate(name)
        try:
            reader = _pool.get_by_repo(name)
            agent_table = reader._get_table("agent_views")
            entity_count = agent_table.num_rows
        except Exception:
            entity_count = 0
        markdown = f"## Repo Registered\n\n- **{name}** — {resolved}\n- Entities: {entity_count}\n- Artifact: ✓ ready"
        structured = {"name": name, "path": resolved, "entity_count": entity_count, "has_artifact": True}
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
        from batho.mcp.graph_builder import truncate_to_budget
        markdown, truncated = truncate_to_budget(markdown, max_tokens)
        if truncated:
            markdown += f"\n\n---\nTruncated to fit {max_tokens} token budget."

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
        return ToolResult(content=[TextContent(type="text", text=markdown)], structured_content=structured)

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
            file_path = str(file_path).replace("\\", "/")
            fid = reader.file_id_for_path(file_path)
            if fid is None:
                return _err(f"File not indexed: {file_path}",
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
        rows = table.to_pylist()
        rows = rows[offset:offset + limit]

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

        file_paths = _file_paths_map(reader)
        gen = _manifest_gen(reader)

        markdown, structured = build_dual_output(
            rows, rels_rows, file_paths,
            response_format=response_format, max_tokens=max_tokens,
            offset=offset, limit=limit,
            total_nodes=total_nodes, total_edges=rels_table.num_rows,
            artifact_generation=gen,
        )
        return ToolResult(content=[TextContent(type="text", text=markdown)], structured_content=structured)

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
            entity_id: The entity ID from search_entities or graph_query results.
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
        return ToolResult(content=[TextContent(type="text", text=markdown)], structured_content=structured)

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
            source_entity_id: Entity ID of the starting point.
            target_entity_id: Entity ID of the destination.
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

        agent_table = reader._get_table("agent_views")
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
        return ToolResult(content=[TextContent(type="text", text="\n".join(lines))], structured_content=structured)

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

        file_path = str(file_path).replace("\\", "/")
        fid = reader.file_id_for_path(file_path)
        if fid is None:
            return _err(f"File not indexed: {file_path}",
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
        return ToolResult(content=[TextContent(type="text", text=markdown)], structured_content=structured)

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
            fp = file_paths.get(row.get("file_id", -1), "")
            lr = ""
            sl = row.get("start_line")
            el = row.get("end_line")
            if sl:
                lr = f"L{sl}" if not el or el == sl else f"L{sl}-{el}"
            lines.append(f"- {name} [{etype}] {fp}:{lr}")

        structured = {
            "results": [build_node_dict_simple(r, file_paths) for r in rows],
            "meta": {"total_matches": total, "returned": len(rows), "artifact_generation": gen},
        }
        return ToolResult(content=[TextContent(type="text", text="\n".join(lines))], structured_content=structured)

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
        return ToolResult(content=[TextContent(type="text", text=markdown)], structured_content=structured)


def build_node_dict_simple(row: dict, file_paths: dict[int, str]) -> dict:
    return {
        "id": row.get("entity_id", ""),
        "name": row.get("name", ""),
        "type": row.get("entity_type", ""),
        "file": file_paths.get(row.get("file_id", -1), ""),
        "start_line": row.get("start_line"),
        "end_line": row.get("end_line"),
    }
