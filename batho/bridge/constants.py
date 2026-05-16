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

# Default logical path patterns relative to .ctn/ for each artifact type.
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

__all__ = [
    "KNOWN_ARTIFACT_TYPES",
    "DEFAULT_PATH_PATTERNS",
    "INDEX_SCOPED_TYPES",
    "ARTIFACT_RECORD_FIELDS",
    "DEFAULT_BRIDGE_HTTP_PORT",
    "DEFAULT_MCP_SSE_PORT",
    "DEFAULT_PAGE_LIMIT",
]
