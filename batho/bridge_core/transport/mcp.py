"""MCP Transport — FastMCP server for AI agent integration.

Provides the Model Context Protocol server with tools, resources, and prompts
for AI agents to query the Batho hypergraph.

This replaces the old BathoMCPServer from batho.bridge.mcp_server with
a simplified single-workspace implementation using bridge_core handlers.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

try:
    from mcp.server.fastmcp import FastMCP
    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False
    # Dummy class for when mcp is not installed
    class FastMCP:
        def __init__(self, name: str):
            pass
        def tool(self):
            return lambda f: f
        def resource(self, uri: str):
            return lambda f: f
        def prompt(self):
            return lambda f: f
        def run(self):
            pass

from batho.bridge_core.deps import WorkspaceDeps, load_workspace_deps, set_current_deps
from batho.bridge_core import handlers
from batho.utils.logging import get_logger

LOGGER = get_logger(__name__, component="bridge_core.mcp")


class BathoMCPServer:
    """FastMCP-based server for AI agent integration.
    
    This is the Phase 7 Oracle Gateway, simplified for single-workspace
    operation using bridge_core handlers.
    
    Usage:
        server = BathoMCPServer(deps)
        server.run_stdio()
    """
    
    def __init__(
        self,
        deps_or_cache: WorkspaceDeps | SnapshotCache,
        repo_root: Path | None = None,
        global_deps: Any = None
    ):
        """Initialize MCP server with workspace dependencies or snapshot cache.
        
        Args:
            deps_or_cache: WorkspaceDeps or SnapshotCache instance.
            repo_root: Optional repository root Path (required if SnapshotCache is passed).
            global_deps: Optional GlobalPlatformDeps instance.
        """
        if not MCP_AVAILABLE:
            raise ImportError(
                "mcp package not installed. "
                "Install with: pip install mcp"
            )
            
        self.mcp = FastMCP("Batho Oracle Nexus")
        
        from batho.bridge_core.deps import SnapshotCache, WorkspaceDeps
        from batho.storage.engine import get_database
        
        if isinstance(deps_or_cache, WorkspaceDeps):
            self.repo_root = Path(repo_root or deps_or_cache.repo_root).resolve()
            self.cache = SnapshotCache()
            if deps_or_cache.run_id:
                self.cache._cache[deps_or_cache.run_id] = deps_or_cache
            self.default_deps = deps_or_cache
        else:
            if repo_root is None:
                raise ValueError("repo_root is required when initializing with SnapshotCache")
            self.repo_root = Path(repo_root).resolve()
            self.cache = deps_or_cache
            self.default_deps = None
            
        # Initialize GlobalPlatformDeps if configured/resolved
        self.global_deps = global_deps
        if not self.global_deps:
            from batho.bridge_core.global_registry import resolve_global_db_path, GlobalPlatformDeps
            try:
                g_db_path = resolve_global_db_path(self.repo_root)
                if g_db_path:
                    self.global_deps = GlobalPlatformDeps(g_db_path)
            except Exception as e:
                LOGGER.warning("mcp_failed_to_initialize_global_deps", error=str(e))
            
        self.db = get_database(self.repo_root)
        
        # Load default/latest deps if not already set
        if self.default_deps is None:
            latest_run_id = self.db.get_latest_run_id()
            if latest_run_id:
                try:
                    self.default_deps = self.cache.get(self.repo_root, latest_run_id)
                except Exception as e:
                    LOGGER.warning("mcp_failed_to_load_default_deps", error=str(e))
                    
        # Set default contextvar
        if self.default_deps:
            set_current_deps(self.default_deps)
            
        self._register_tools()
        self._register_resources()
        self._register_prompts()

    def _resolve_deps(self, run_id: str | None = None, commit_sha: str | None = None) -> WorkspaceDeps:
        if not run_id and not commit_sha:
            if self.default_deps:
                return self.default_deps
            # Fallback to load latest
            latest_run_id = self.db.get_latest_run_id()
            if not latest_run_id:
                raise ValueError("No completed runs found in database")
            return self.cache.get(self.repo_root, latest_run_id)
            
        resolved_run_id = None
        if run_id:
            resolved_run_id = run_id
        else:
            from batho.bridge_core.deps import resolve_commit_to_run_id
            resolved_run_id = resolve_commit_to_run_id(self.db, commit_sha)
            if not resolved_run_id:
                raise ValueError(f"Commit SHA {commit_sha} could not be resolved to a completed run")
                
        return self.cache.get(self.repo_root, resolved_run_id)
    
    def _register_tools(self) -> None:
        """Register MCP tools for hypergraph queries."""
        
        @self.mcp.tool()
        async def hypergraph_neighborhood(
            node_id: str,
            radius: int = 1,
            include_metadata: bool = True,
            run_id: str | None = None,
            commit_sha: str | None = None
        ) -> str:
            """Get bidirectional neighborhood for any code entity.
            
            Returns neighborhood graph with center node, outbound/inbound edges,
            and coverage statistics for AI context windows.
            
            Args:
                node_id: Entity ID to center on
                radius: Neighborhood radius (1-3)
                include_metadata: Include entity metadata
                run_id: Optional snapshot run ID. If neither run_id nor commit_sha is provided, defaults to latest.
                commit_sha: Optional git commit hash to resolve to a run ID.
            """
            try:
                deps = self._resolve_deps(run_id, commit_sha)
                
                # Force in-memory search for structural queries / node_id resolution
                resolved_node_id = node_id
                if node_id not in deps.graph.entities:
                    results = deps.search_engine.search(node_id, use_sqlite_first=False)
                    if results:
                        resolved_node_id = results[0]["id"]
                
                from batho.bridge_core.deps import current_deps
                token = current_deps.set(deps)
                try:
                    result = handlers.handle_hypergraph_l3(deps, {
                        "node_id": resolved_node_id,
                        "radius": radius,
                    })
                    
                    if isinstance(result, dict):
                        if "metadata" not in result:
                            result["metadata"] = {}
                        if isinstance(result["metadata"], dict):
                            result["metadata"]["run_id"] = deps.run_id
                            result["metadata"]["git_commit"] = deps.git_commit
                            result["metadata"]["timestamp"] = deps.timestamp
                        if "data" in result and isinstance(result["data"], dict):
                            if "metadata" not in result["data"]:
                                result["data"]["metadata"] = {}
                            if isinstance(result["data"]["metadata"], dict):
                                result["data"]["metadata"]["run_id"] = deps.run_id
                                result["data"]["metadata"]["git_commit"] = deps.git_commit
                                result["data"]["metadata"]["timestamp"] = deps.timestamp
                            
                    return json.dumps(result.get("data", result))
                finally:
                    current_deps.reset(token)
            except Exception as e:
                LOGGER.error("mcp_neighborhood_error", error=str(e))
                return json.dumps({"error": str(e)})
        
        @self.mcp.tool()
        async def bsg_evaluate_policy(
            file_path: str | None = None,
            run_id: str | None = None,
            commit_sha: str | None = None
        ) -> str:
            """Evaluate code against deterministic BSG policies.
            
            Returns compliance score and policy violations.
            
            Args:
                file_path: Optional file to limit evaluation to
                run_id: Optional snapshot run ID. If neither run_id nor commit_sha is provided, defaults to latest.
                commit_sha: Optional git commit hash to resolve to a run ID.
            """
            try:
                deps = self._resolve_deps(run_id, commit_sha)
                from batho.bridge_core.deps import current_deps
                token = current_deps.set(deps)
                try:
                    result = handlers.handle_bsg_evaluate(deps, {
                        "file_path": file_path,
                    })
                    if isinstance(result, dict):
                        if "metadata" not in result:
                            result["metadata"] = {}
                        if isinstance(result["metadata"], dict):
                            result["metadata"]["run_id"] = deps.run_id
                            result["metadata"]["git_commit"] = deps.git_commit
                            result["metadata"]["timestamp"] = deps.timestamp
                        if "data" in result and isinstance(result["data"], dict):
                            if "metadata" not in result["data"]:
                                result["data"]["metadata"] = {}
                            if isinstance(result["data"]["metadata"], dict):
                                result["data"]["metadata"]["run_id"] = deps.run_id
                                result["data"]["metadata"]["git_commit"] = deps.git_commit
                                result["data"]["metadata"]["timestamp"] = deps.timestamp
                    return json.dumps(result.get("data", result))
                finally:
                    current_deps.reset(token)
            except Exception as e:
                LOGGER.error("mcp_policy_error", error=str(e))
                return json.dumps({"error": str(e)})
        
        @self.mcp.tool()
        async def hypergraph_context_for_llm(
            file_path: str,
            line_number: int,
            context_budget: int = 4000,
            run_id: str | None = None,
            commit_sha: str | None = None
        ) -> str:
            """Cure context amnesia: Fetch semantically connected entities within token budget.
            
            Optimized context extraction that respects LLM token limits while
            maximizing relevant code context from the hypergraph.
            
            Args:
                file_path: Path to file
                line_number: Line number in file
                context_budget: Token budget (default: 4000)
                run_id: Optional snapshot run ID. If neither run_id nor commit_sha is provided, defaults to latest.
                commit_sha: Optional git commit hash to resolve to a run ID.
            """
            try:
                deps = self._resolve_deps(run_id, commit_sha)
                from batho.bridge_core.deps import current_deps
                token = current_deps.set(deps)
                try:
                    # First get context at position
                    context_result = handlers.handle_context_at_position(deps, {
                        "file": file_path,
                        "line": line_number,
                    })
                    
                    if not context_result.get("ok"):
                        return json.dumps({
                            "error": context_result.get("error", "Failed to get context")
                        })
                    
                    context_data = context_result.get("data", {})
                    center_entity = context_data.get("enclosing_entity")
                    
                    if not center_entity:
                        return json.dumps({"error": "No entity found at cursor position"})
                    
                    # Use amnesia analyzer
                    amnesia_result = handlers.handle_context_amnesia(deps, {
                        "node_id": center_entity["id"],
                        "budget": context_budget,
                    })
                    
                    if isinstance(amnesia_result, dict):
                        if "metadata" not in amnesia_result:
                            amnesia_result["metadata"] = {}
                        if isinstance(amnesia_result["metadata"], dict):
                            amnesia_result["metadata"]["run_id"] = deps.run_id
                            amnesia_result["metadata"]["git_commit"] = deps.git_commit
                            amnesia_result["metadata"]["timestamp"] = deps.timestamp
                        if "data" in amnesia_result and isinstance(amnesia_result["data"], dict):
                            if "metadata" not in amnesia_result["data"]:
                                amnesia_result["data"]["metadata"] = {}
                            if isinstance(amnesia_result["data"]["metadata"], dict):
                                amnesia_result["data"]["metadata"]["run_id"] = deps.run_id
                                amnesia_result["data"]["metadata"]["git_commit"] = deps.git_commit
                                amnesia_result["data"]["metadata"]["timestamp"] = deps.timestamp
                            
                    return json.dumps(amnesia_result.get("data", amnesia_result))
                finally:
                    current_deps.reset(token)
            except Exception as e:
                LOGGER.error("mcp_context_error", error=str(e))
                return json.dumps({"error": str(e)})
        
        @self.mcp.tool()
        async def search_entities(
            query: str,
            kinds: str | None = None,
            limit: int = 50,
            run_id: str | None = None,
            commit_sha: str | None = None
        ) -> str:
            """Search for entities in the codebase.
            
            Fuzzy search over entity names and fully qualified names.
            
            Args:
                query: Search query string
                kinds: Comma-separated entity types (optional)
                limit: Max results (default: 50)
                run_id: Optional snapshot run ID. If neither run_id nor commit_sha is provided, defaults to latest.
                commit_sha: Optional git commit hash to resolve to a run ID.
            """
            try:
                deps = self._resolve_deps(run_id, commit_sha)
                from batho.bridge_core.deps import current_deps
                token = current_deps.set(deps)
                try:
                    params = {"q": query, "limit": limit}
                    if kinds:
                        params["kinds"] = kinds
                    
                    result = handlers.handle_search(deps, params)
                    if isinstance(result, dict):
                        if "metadata" not in result:
                            result["metadata"] = {}
                        if isinstance(result["metadata"], dict):
                            result["metadata"]["run_id"] = deps.run_id
                            result["metadata"]["git_commit"] = deps.git_commit
                            result["metadata"]["timestamp"] = deps.timestamp
                        if "data" in result and isinstance(result["data"], dict):
                            if "metadata" not in result["data"]:
                                result["data"]["metadata"] = {}
                            if isinstance(result["data"]["metadata"], dict):
                                result["data"]["metadata"]["run_id"] = deps.run_id
                                result["data"]["metadata"]["git_commit"] = deps.git_commit
                                result["data"]["metadata"]["timestamp"] = deps.timestamp
                    return json.dumps(result.get("data", result))
                finally:
                    current_deps.reset(token)
            except Exception as e:
                LOGGER.error("mcp_search_error", error=str(e))
                return json.dumps({"error": str(e)})
                
        @self.mcp.tool()
        async def search_fleet_symbols(
            query: str,
            symbol_type: str | None = None
        ) -> str:
            """Search for symbols across all registered repositories.
            
            Args:
                query: Search query string
                symbol_type: Optional type filter (e.g. FUNCTION, CLASS, INTERFACE, etc.)
            """
            if not self.global_deps:
                return json.dumps({"error": "Global registry is not configured/initialized."})
            
            from batho.bridge_core.deps import global_deps_var
            global_token = global_deps_var.set(self.global_deps)
            try:
                result = handlers.handle_global_search(None, {
                    "query": query,
                    "symbol_type": symbol_type
                })
                return json.dumps(result.get("data", result))
            except Exception as e:
                LOGGER.error("mcp_search_fleet_symbols_error", error=str(e))
                return json.dumps({"error": str(e)})
            finally:
                global_deps_var.reset(global_token)

        @self.mcp.tool()
        async def get_cross_repo_impact(
            repo_name: str,
            symbol_name: str
        ) -> str:
            """Get cross-repository impact analysis for a symbol change.
            
            Args:
                repo_name: The name of the target repository
                symbol_name: The name of the symbol to analyze
            """
            if not self.global_deps:
                return json.dumps({"error": "Global registry is not configured/initialized."})
            
            from batho.bridge_core.deps import global_deps_var
            global_token = global_deps_var.set(self.global_deps)
            try:
                db_conn = self.global_deps.global_db
                row = db_conn.execute(
                    "SELECT repo_id FROM workspaces WHERE repo_name = ?",
                    (repo_name,)
                ).fetchone()
                
                if not row:
                    return json.dumps({"error": f"Repository '{repo_name}' is not registered."})
                
                repo_id = row["repo_id"]
                result = handlers.handle_fleet_impact(None, {
                    "repo_id": repo_id,
                    "symbol_name": symbol_name
                })
                return json.dumps(result.get("data", result))
            except Exception as e:
                LOGGER.error("mcp_get_cross_repo_impact_error", error=str(e))
                return json.dumps({"error": str(e)})
            finally:
                global_deps_var.reset(global_token)

        @self.mcp.tool()
        async def list_fleet_workspaces() -> str:
            """List all registered workspaces in the fleet."""
            if not self.global_deps:
                return json.dumps({"error": "Global registry is not configured/initialized."})
            
            from batho.bridge_core.deps import global_deps_var
            global_token = global_deps_var.set(self.global_deps)
            try:
                result = handlers.handle_fleet_overview(None, {})
                return json.dumps(result.get("data", result))
            except Exception as e:
                LOGGER.error("mcp_list_fleet_workspaces_error", error=str(e))
                return json.dumps({"error": str(e)})
            finally:
                global_deps_var.reset(global_token)
    
    def _register_resources(self) -> None:
        """Register MCP resources for direct URI access."""
        
        @self.mcp.resource("batho://context/{file_path}/{line_number}")
        async def get_context_resource(file_path: str, line_number: str) -> str:
            """Direct URI access to code context at position."""
            try:
                decoded_path = file_path.replace('%2F', '/').replace('%20', ' ')
                result = handlers.handle_context_at_position(self.deps, {
                    "file": decoded_path,
                    "line": line_number,
                })
                return json.dumps(result.get("data", result))
            except Exception as e:
                LOGGER.error("mcp_resource_error", error=str(e))
                return json.dumps({"error": str(e)})
        
        @self.mcp.resource("batho://entity/{entity_id}")
        async def get_entity_resource(entity_id: str) -> str:
            """Direct URI access to entity by ID."""
            try:
                entity = self.deps.graph.get_entity(entity_id)
                if not entity:
                    return json.dumps({"error": "Entity not found"})
                
                return json.dumps({
                    "id": entity.id,
                    "name": entity.name,
                    "type": str(entity.type),
                    "fqn": entity.fqn,
                    "file": entity.file,
                    "line": entity.start_line,
                    "signature": entity.signature,
                })
            except Exception as e:
                LOGGER.error("mcp_entity_error", error=str(e))
                return json.dumps({"error": str(e)})
    
    def _register_prompts(self) -> None:
        """Register MCP prompts for orchestrator workflows."""
        
        @self.mcp.prompt()
        def analyze_code_context(file_path: str, line_number: int) -> str:
            """Prompt template for orchestrators."""
            return (
                f"Analyze {file_path}:{line_number} using `hypergraph_context_for_llm`. "
                f"Focus on inbound/outbound dependencies and critical misses."
            )
        
        @self.mcp.prompt()
        def review_bsg_policy() -> str:
            """Prompt for BSG policy review."""
            return (
                "Evaluate codebase against BSG policies using `bsg_evaluate_policy`. "
                "Identify violations and suggest fixes."
            )
    
    def run_stdio(self) -> None:
        """Run MCP server over stdio (standard input/output)."""
        LOGGER.info("mcp_stdio_starting")
        self.mcp.run()
    
    def run_sse(self, port: int = 8765) -> None:
        """Run MCP server over SSE (Server-Sent Events) HTTP.
        
        Note: FastMCP's SSE support depends on the mcp package version.
        This may fall back to stdio if SSE is not available.
        
        Args:
            port: HTTP port to listen on
        """
        LOGGER.info("mcp_sse_starting", port=port)
        try:
            # Try to use SSE transport if available
            import asyncio
            from mcp.server import Server
            from mcp.server.sse import SseServerTransport
            
            # This is a placeholder - actual SSE implementation
            # depends on mcp package capabilities
            LOGGER.warning("mcp_sse_not_implemented", 
                          message="SSE transport requires mcp>=1.0.0 with sse support")
            self.run_stdio()
        except ImportError:
            LOGGER.warning("mcp_sse_unavailable", fallback="stdio")
            self.run_stdio()


def run_mcp_stdio(repo_root: Path | None = None, global_db_path: Path | None = None) -> None:
    """Convenience function to run MCP server over stdio.
    
    This is the main entry point for MCP IDE integration.
    
    Args:
        repo_root: Path to repository root. If None, uses current directory.
        global_db_path: Optional path to global.batho database
    """
    if repo_root is None:
        repo_root = Path.cwd()
    
    repo_root = repo_root.resolve()
    
    LOGGER.info("mcp_initializing", repo_root=str(repo_root))
    
    # Create and run server
    from batho.bridge_core.deps import SnapshotCache
    from batho.bridge_core.global_registry import GlobalPlatformDeps
    cache = SnapshotCache()
    
    global_deps = None
    if global_db_path:
        try:
            global_deps = GlobalPlatformDeps(global_db_path)
        except Exception as e:
            LOGGER.warning("failed_to_initialize_global_deps_from_path", error=str(e))
            
    server = BathoMCPServer(cache, repo_root, global_deps=global_deps)
    server.run_stdio()


__all__ = [
    "BathoMCPServer",
    "run_mcp_stdio",
]
