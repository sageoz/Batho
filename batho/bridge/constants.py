"""Artifact type constants and path mappings for the Batho bridge."""

from __future__ import annotations

# Artifact types that the bridge can load as JSON
KNOWN_ARTIFACT_TYPES: set[str] = {
    "interception_stats_json",
    "graph_json",
    "bsg_json",
    "context_overview_json",
    "context_files_json",
    "snapshot_json",
    "index_metadata",
    "metrics_json",
    "file_hashes_json",
    "patches_index",
    "patch_detail",
}

# Default logical path patterns relative to repo root for each artifact type.
# The {index_id} placeholder is resolved from the current index.
DEFAULT_PATH_PATTERNS: dict[str, str] = {
    "interception_stats_json": "local/metrics/interception_stats.json",
    "graph_json": "{index_id}/graph.json",
    "bsg_json": "{index_id}/bsg.json",
    "context_overview_json": "{index_id}/context/json/overview.json",
    "context_files_json": "{index_id}/context/json/files.json",
    "snapshot_json": "snapshots/{name}.json",
    "index_metadata": "index.json",
    "metrics_json": "local/metrics/metrics.json",
    "file_hashes_json": "local/state/file_hashes.json",
    "patches_index": "patches/index.json",
    "patch_detail": "patches/patch_{operation_id}.json",
}

# Artifact types that require an index_id for path resolution
INDEX_SCOPED_TYPES: set[str] = {
    "graph_json",
    "bsg_json",
    "context_overview_json",
    "context_files_json",
}

# Registry column names exposed by the bridge API
ARTIFACT_RECORD_FIELDS: tuple[str, ...] = (
    "artifact_id",
    "content_id",
    "artifact_type",
    "logical_path",
    "physical_path",
    "checksum",
    "size_bytes",
    "schema_version",
    "producer",
    "run_id",
    "sync_status",
    "cloud_content_id",
    "last_sync_at",
    "sync_error",
    "retry_count",
    "retention_class",
    "metadata",
    "created_at",
    "updated_at",
)

DEFAULT_BRIDGE_HTTP_PORT = 8766
DEFAULT_MCP_SSE_PORT = 8767
DEFAULT_PAGE_LIMIT = 200

DEFAULT_HUB_HTTP_PORT = 8770
DEFAULT_HUB_REST_PORT = 8771
DEFAULT_USER_CONFIG_PATH = "~/.batho/mcp.yaml"
PROJECT_CONFIG_FILENAME = ".batho/mcp.yaml"
WORKSPACE_ID_REGEX = r"^[a-z0-9][a-z0-9_-]{0,62}$"

DEFAULT_MAX_RESIDENT_WORKSPACES = 32
DEFAULT_IDLE_EVICT_SECONDS = 600
DEFAULT_MAX_TOTAL_CACHE_BYTES = 1 << 30
DEFAULT_MAX_PER_WORKSPACE_CACHE_BYTES = 1 << 27
DEFAULT_GLOBAL_INFLIGHT = 256
DEFAULT_PER_WORKSPACE_INFLIGHT = 16
DEFAULT_REQUEST_TIMEOUT = 30
DEFAULT_CONNECTION_POOL_SIZE = 4
MOUNT_BACKOFF_SECONDS = (1, 5, 30, 30, 30)

__all__ = [
    "KNOWN_ARTIFACT_TYPES",
    "DEFAULT_PATH_PATTERNS",
    "INDEX_SCOPED_TYPES",
    "ARTIFACT_RECORD_FIELDS",
    "DEFAULT_BRIDGE_HTTP_PORT",
    "DEFAULT_MCP_SSE_PORT",
    "DEFAULT_PAGE_LIMIT",
    "DEFAULT_HUB_HTTP_PORT",
    "DEFAULT_HUB_REST_PORT",
    "DEFAULT_USER_CONFIG_PATH",
    "PROJECT_CONFIG_FILENAME",
    "WORKSPACE_ID_REGEX",
    "DEFAULT_MAX_RESIDENT_WORKSPACES",
    "DEFAULT_IDLE_EVICT_SECONDS",
    "DEFAULT_MAX_TOTAL_CACHE_BYTES",
    "DEFAULT_MAX_PER_WORKSPACE_CACHE_BYTES",
    "DEFAULT_GLOBAL_INFLIGHT",
    "DEFAULT_PER_WORKSPACE_INFLIGHT",
    "DEFAULT_REQUEST_TIMEOUT",
    "DEFAULT_CONNECTION_POOL_SIZE",
    "MOUNT_BACKOFF_SECONDS",
]
