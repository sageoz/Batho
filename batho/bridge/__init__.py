"""Batho bridge — access .ctn artifacts via registry, REST, and MCP."""

from __future__ import annotations

from batho.bridge.artifact_cache import ArtifactCache, ArtifactCacheKey, CacheStats
from batho.bridge.artifact_loader import (
    ArtifactContent,
    ArtifactLoader,
    ArtifactNotFoundError,
    ArtifactParseError,
    ChecksumMismatchError,
)
from batho.bridge.connection_pool import ConnectionPool, ConnectionPoolExhausted
from batho.bridge.cross import (
    cross_dependencies_impl,
    cross_search_impl,
    cross_symbols_impl,
    cross_workspaces_with_artifact_impl,
    merge_search_hits,
)
from batho.bridge.envelope import err, ok, to_json, tool_envelope
from batho.bridge.hub import (
    create_hub,
    run_hub_sse,
    run_hub_stdio,
    run_hub_streamable_http,
)
from batho.bridge.hub_http import HubHTTPHandler, create_hub_server
from batho.bridge.models import (
    ArtifactRecord,
    BridgeErrorResponse,
    BridgeResponse,
    ConcurrencyConfig,
    CrossRepoConfig,
    DiscoveryConfig,
    HubConfig,
    HubConfigDiff,
    IndexEntry,
    RegistryStats,
    ResidencyConfig,
    ServerConfig,
    WorkspaceConfig,
    WorkspaceHealth,
    WorkspaceState,
)
from batho.bridge.registry_client import ArtifactRegistryBridge
from batho.bridge.workspace_discovery import WorkspaceDiscovery
from batho.bridge.workspace_handle import WorkspaceHandle
from batho.bridge.workspace_manager import WorkspaceManager
from batho.bridge.workspace_registry import WorkspaceRegistry, Watcher

__version__ = "1.0.0"

__all__ = [
    "ArtifactCache",
    "ArtifactCacheKey",
    "ArtifactContent",
    "ArtifactLoader",
    "ArtifactNotFoundError",
    "ArtifactParseError",
    "ArtifactRecord",
    "ArtifactRegistryBridge",
    "BridgeErrorResponse",
    "BridgeResponse",
    "ChecksumMismatchError",
    "ConcurrencyConfig",
    "ConnectionPool",
    "ConnectionPoolExhausted",
    "CrossRepoConfig",
    "cross_dependencies_impl",
    "cross_search_impl",
    "cross_symbols_impl",
    "cross_workspaces_with_artifact_impl",
    "DiscoveryConfig",
    "err",
    "HubConfig",
    "HubConfigDiff",
    "HubHTTPHandler",
    "IndexEntry",
    "merge_search_hits",
    "ok",
    "RegistryStats",
    "ResidencyConfig",
    "ServerConfig",
    "to_json",
    "tool_envelope",
    "WorkspaceConfig",
    "WorkspaceDiscovery",
    "WorkspaceHandle",
    "WorkspaceHealth",
    "WorkspaceManager",
    "WorkspaceRegistry",
    "WorkspaceState",
    "Watcher",
    "create_hub",
    "create_hub_server",
    "run_hub_sse",
    "run_hub_stdio",
    "run_hub_streamable_http",
]
