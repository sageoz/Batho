"""Bridge Core Server — Unified HTTP and MCP server.

Provides a single entry point for starting either HTTP REST API
or MCP (stdio or SSE) servers.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from batho.bridge_core.transport.http import BridgeHTTPServer, run_http_server
from batho.bridge_core.transport.mcp import BathoMCPServer, run_mcp_stdio
from batho.utils.logging import get_logger

LOGGER = get_logger(__name__, component="bridge_core.server")


class BridgeServer:
    """Unified server supporting HTTP and MCP transports.
    
    This is the main entry point for bridge_core. It can start
    either an HTTP REST API server or an MCP server (stdio or SSE).
    
    Usage:
        # HTTP mode (for dashboard, external clients)
        server = BridgeServer(Path("/path/to/repo"))
        server.start_http(port=8765)
        server.serve_forever()
        
        # MCP stdio mode (for IDE integration)
        server = BridgeServer(Path("/path/to/repo"))
        server.start_mcp_stdio()
        
        # MCP SSE mode (for HTTP-based MCP)
        server = BridgeServer(Path("/path/to/repo"))
        server.start_mcp_sse(port=8765)
    """
    
    def __init__(self, repo_root: Path, global_db_path: Path | None = None):
        """Initialize server with repository path.
        
        Args:
            repo_root: Path to repository root (where .batho/ lives)
            global_db_path: Optional path to global.batho database
        """
        self.repo_root = Path(repo_root).resolve()
        self.global_db_path = global_db_path
        self._http_server: BridgeHTTPServer | None = None
        self._mcp_server: BathoMCPServer | None = None
    
    def start_http(
        self,
        port: int = 8765,
        host: str = "127.0.0.1",
        open_browser: bool = False
    ) -> None:
        """Start HTTP REST API server.
        
        Args:
            port: TCP port to listen on
            host: Bind address (127.0.0.1 for local only)
            open_browser: Whether to open browser (not implemented for HTTP mode)
        """
        LOGGER.info("starting_http_server", port=port, host=host)
        
        self._http_server = BridgeHTTPServer(
            self.repo_root,
            port=port,
            host=host,
            global_db_path=self.global_db_path
        )
        self._http_server.start()
        
        if open_browser:
            # HTTP server doesn't auto-open browser
            LOGGER.info("open_browser_not_supported", transport="http")
    
    def start_mcp_stdio(self) -> None:
        """Start MCP server over stdio.
        
        This is the standard mode for IDE integration (Cursor, Claude Desktop, etc.)
        """
        LOGGER.info("starting_mcp_stdio")
        run_mcp_stdio(self.repo_root, global_db_path=self.global_db_path)
    
    def start_mcp_sse(self, port: int = 8765) -> None:
        """Start MCP server over SSE (Server-Sent Events).
        
        Note: This requires mcp>=1.0.0 with SSE support.
        Falls back to stdio if SSE is not available.
        
        Args:
            port: HTTP port for SSE endpoint
        """
        LOGGER.info("starting_mcp_sse", port=port)
        
        # For now, we need to load deps and create server manually
        # since run_mcp_stdio doesn't support SSE
        from batho.bridge_core.deps import load_workspace_deps
        
        deps = load_workspace_deps(self.repo_root)
        
        global_deps = None
        from batho.bridge_core.global_registry import resolve_global_db_path, GlobalPlatformDeps
        g_db_path = self.global_db_path or resolve_global_db_path(self.repo_root)
        if g_db_path:
            try:
                global_deps = GlobalPlatformDeps(g_db_path)
            except Exception as e:
                LOGGER.warning("failed_to_initialize_global_deps_mcp_sse", error=str(e))
                
        mcp_server = BathoMCPServer(deps, global_deps=global_deps)
        mcp_server.run_sse(port=port)
    
    def serve_forever(self) -> None:
        """Run HTTP server until interrupted.
        
        Only works if start_http() was called.
        """
        if self._http_server is None:
            raise RuntimeError("HTTP server not started. Call start_http() first.")
        
        self._http_server.serve_forever()
    
    def stop(self) -> None:
        """Stop the running server."""
        if self._http_server:
            self._http_server.stop()
            self._http_server = None
        
        self._mcp_server = None


def serve(
    repo_root: Path | None = None,
    transport: Literal["http", "stdio", "sse"] = "stdio",
    port: int = 8765,
    host: str = "127.0.0.1",
    global_db_path: Path | None = None
) -> None:
    """High-level serve function.
    
    Convenience function to start a bridge server with minimal configuration.
    
    Args:
        repo_root: Repository root path. Uses cwd if None.
        transport: Transport type (http, stdio, sse)
        port: Port for HTTP/SSE modes
        host: Bind address for HTTP mode
        global_db_path: Optional path to global.batho database
    """
    if repo_root is None:
        repo_root = Path.cwd()
    
    server = BridgeServer(repo_root, global_db_path=global_db_path)
    
    if transport == "http":
        server.start_http(port=port, host=host)
        server.serve_forever()
    elif transport == "stdio":
        server.start_mcp_stdio()
    elif transport == "sse":
        server.start_mcp_sse(port=port)
    else:
        raise ValueError(f"Unknown transport: {transport}")


__all__ = [
    "BridgeServer",
    "serve",
]
