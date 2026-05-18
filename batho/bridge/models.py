"""Pydantic models for the Batho bridge API."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class ArtifactRecord(BaseModel):
    """A single artifact as returned by the registry."""

    artifact_id: str
    artifact_type: str
    logical_path: str
    physical_path: str
    checksum: str = ""
    size_bytes: int = 0
    schema_version: str = ""
    producer: str = ""
    run_id: str = ""
    sync_status: str = "local_only"
    cloud_content_id: str | None = None
    last_sync_at: str | None = None
    sync_error: str | None = None
    retry_count: int = 0
    retention_class: str = "default"
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""


class IndexEntry(BaseModel):
    """A single index entry from .ctn/index.json."""

    index_id: str
    timestamp: str
    root: str
    file_count: int = 0
    entity_count: int = 0
    relationship_count: int = 0
    repo_hash: str = ""
    staleness_score: float = 1.0
    stack: dict[str, Any] = Field(default_factory=dict)
    outputs: dict[str, str] = Field(default_factory=dict)
    stats: dict[str, Any] = Field(default_factory=dict)
    metrics: dict[str, Any] = Field(default_factory=dict)
    build: dict[str, Any] = Field(default_factory=dict)
    schemas: dict[str, Any] = Field(default_factory=dict)
    persistence: dict[str, Any] = Field(default_factory=dict)
    snapshot_id: str = ""


class IndexListResponse(BaseModel):
    """Response envelope for the indexes list endpoint."""

    ok: bool = True
    data: list[IndexEntry] = Field(default_factory=list)
    current_index_id: str = ""
    persistence_model: str | None = None
    schema_version: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


class BridgeResponse(BaseModel):
    """Unified envelope for all bridge HTTP responses."""

    ok: bool = True
    data: Any = None
    meta: dict[str, Any] = Field(default_factory=dict)


class BridgeErrorResponse(BaseModel):
    """Error envelope for bridge HTTP responses."""

    ok: bool = False
    error: dict[str, Any] = Field(default_factory=dict)


class RegistryStats(BaseModel):
    """Registry statistics."""

    enabled: bool = False
    registry_path: str = ""
    backend: str = "sqlite"
    artifact_count: int = 0
    deleted_artifact_count: int = 0
    content_blob_count: int = 0
    artifact_types: dict[str, int] = Field(default_factory=dict)
    sync_status: dict[str, int] = Field(default_factory=dict)
    db_size_bytes: int = 0


class WorkspaceConfig(BaseModel):
    """Configuration for a single workspace."""

    id: str
    label: str = ""
    ctn_dir: str
    enabled: bool = True
    pinned: bool = False
    tags: list[str] = Field(default_factory=list)
    default_index_id: str | None = None
    read_only: bool = True
    description: str = ""
    source: Literal["manual", "auto-discovered", "project-override"] = "manual"


class ServerConfig(BaseModel):
    """Hub server configuration."""

    bind: str = "127.0.0.1"
    http_port: int = 8770
    rest_port: int = 8771
    default_workspace: str | None = None
    worker_threads: int = 8


class ResidencyConfig(BaseModel):
    """Workspace residency and caching configuration."""

    max_resident_workspaces: int = 32
    idle_evict_seconds: int = 600
    max_total_cache_bytes: int = 1 << 30
    max_per_workspace_cache_bytes: int = 1 << 27
    prefetch_default_workspace: bool = True


class ConcurrencyConfig(BaseModel):
    """Concurrency limits configuration."""

    global_inflight_limit: int = 256
    per_workspace_inflight_limit: int = 16
    request_timeout_seconds: int = 30


class DiscoveryConfig(BaseModel):
    """Workspace discovery configuration."""

    ctn_dir_globs: list[str] = Field(default_factory=list)
    watch: bool = True
    ignore_ids: list[str] = Field(default_factory=list)


class CrossRepoConfig(BaseModel):
    """Cross-repo indexing configuration."""

    enabled: bool = True
    max_results_per_workspace: int = 25
    merge_strategy: Literal["score_desc", "round_robin"] = "score_desc"
    rebuild_on_mtime_change: bool = True
    background_warmup: bool = True


class HubConfig(BaseModel):
    """Root configuration for the MCP hub."""

    schema_version: int = 1
    server: ServerConfig = Field(default_factory=ServerConfig)
    residency: ResidencyConfig = Field(default_factory=ResidencyConfig)
    concurrency: ConcurrencyConfig = Field(default_factory=ConcurrencyConfig)
    discovery: DiscoveryConfig = Field(default_factory=DiscoveryConfig)
    workspaces: list[WorkspaceConfig] = Field(default_factory=list)
    cross_repo: CrossRepoConfig = Field(default_factory=CrossRepoConfig)


class WorkspaceState(str, Enum):
    """Workspace lifecycle state."""

    REGISTERED = "registered"
    MOUNTING = "mounting"
    READY = "ready"
    DEGRADED = "degraded"
    UNMOUNTING = "unmounting"
    EVICTED = "evicted"
    FAILED = "failed"


class WorkspaceHealth(BaseModel):
    """Health status for a workspace."""

    id: str
    state: Literal["registered", "mounting", "ready", "degraded", "unmounting", "evicted", "failed"]
    ok: bool
    ctn_exists: bool
    registry_enabled: bool
    last_index_id: str | None = None
    artifact_count: int = 0
    resident: bool = False
    last_used_at: str | None = None
    cache_bytes: int = 0
    inflight: int = 0
    last_error: str | None = None
    checked_at: str


class HubConfigDiff(BaseModel):
    """Diff between two hub configurations."""

    added: list[WorkspaceConfig] = Field(default_factory=list)
    removed: list[str] = Field(default_factory=list)
    updated: list[WorkspaceConfig] = Field(default_factory=list)
    server_changed: bool = False
    residency_changed: bool = False
    discovery_changed: bool = False


__all__ = [
    "ArtifactRecord",
    "IndexEntry",
    "IndexListResponse",
    "BridgeResponse",
    "BridgeErrorResponse",
    "RegistryStats",
    "WorkspaceConfig",
    "ServerConfig",
    "ResidencyConfig",
    "ConcurrencyConfig",
    "DiscoveryConfig",
    "CrossRepoConfig",
    "HubConfig",
    "WorkspaceState",
    "WorkspaceHealth",
    "HubConfigDiff",
]
