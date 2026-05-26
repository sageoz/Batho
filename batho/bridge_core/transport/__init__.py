"""Bridge Core Transport — HTTP and MCP server implementations.

Provides two transport layers:
- HTTP: REST API for dashboard and external clients
- MCP: Model Context Protocol for AI agent integration
"""

from batho.bridge_core.transport.http import BridgeHTTPServer
from batho.bridge_core.transport.mcp import run_mcp_stdio, BathoMCPServer

__all__ = [
    "BridgeHTTPServer",
    "run_mcp_stdio",
    "BathoMCPServer",
]
