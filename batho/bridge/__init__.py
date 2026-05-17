"""Batho bridge — access .ctn artifacts via registry, REST, and MCP."""

from __future__ import annotations

from batho.bridge.artifact_loader import (
    ArtifactContent,
    ArtifactLoader,
    ArtifactNotFoundError,
    ArtifactParseError,
    ChecksumMismatchError,
)
from batho.bridge.http_api import BridgeAPIHandler, create_bridge_server
from batho.bridge.mcp_server import create_mcp_server, run_mcp_sse, run_mcp_stdio
from batho.bridge.models import (
    ArtifactRecord,
    BridgeErrorResponse,
    BridgeResponse,
    IndexEntry,
    RegistryStats,
)
from batho.bridge.registry_client import ArtifactRegistryBridge

__version__ = "1.0.0"

__all__ = [
    "ArtifactContent",
    "ArtifactLoader",
    "ArtifactNotFoundError",
    "ArtifactParseError",
    "ArtifactRecord",
    "ArtifactRegistryBridge",
    "BridgeAPIHandler",
    "BridgeErrorResponse",
    "BridgeResponse",
    "ChecksumMismatchError",
    "IndexEntry",
    "RegistryStats",
    "create_bridge_server",
    "create_mcp_server",
    "run_mcp_sse",
    "run_mcp_stdio",
]
