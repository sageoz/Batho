"""MCP server for the Batho bridge using FastMCP."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "The 'mcp' package is required for the bridge MCP server. "
        "Install it with: pip install mcp>=1.0.0"
    ) from exc

from batho.bridge.artifact_loader import (
    ArtifactLoader,
    ArtifactNotFoundError,
    ArtifactParseError,
    ChecksumMismatchError,
)
from batho.bridge.constants import DEFAULT_MCP_SSE_PORT, KNOWN_ARTIFACT_TYPES
from batho.bridge.registry_client import ArtifactRegistryBridge
from batho.utils.logging import get_logger

LOGGER = get_logger(__name__, component="bridge")


def create_mcp_server(ctn_dir: Path) -> FastMCP:
    """Create and configure a FastMCP server bound to *ctn_dir*."""
    bridge = ArtifactRegistryBridge(ctn_dir)
    loader = ArtifactLoader(ctn_dir)
    mcp = FastMCP("batho-bridge")

    @mcp.tool()
    def bridge_list_indexes() -> str:
        """List all available index IDs and timestamps."""
        entries = bridge.list_indexes()
        result = [
            {"index_id": e.index_id, "timestamp": e.timestamp, "root": e.root}
            for e in entries
        ]
        return json.dumps(result, indent=2)

    @mcp.tool()
    def bridge_get_index(index_id: str) -> str:
        """Get metadata for a specific index."""
        entries = bridge.list_indexes()
        for entry in entries:
            if entry.index_id == index_id:
                return json.dumps(entry.model_dump(exclude_none=True), indent=2)
        return json.dumps({"error": f"Index not found: {index_id}"})

    @mcp.tool()
    def bridge_list_artifacts(index_id: str | None = None, artifact_type: str | None = None) -> str:
        """List artifact records, optionally filtered by type or index."""
        if artifact_type and artifact_type not in KNOWN_ARTIFACT_TYPES:
            return json.dumps(
                {
                    "error": f"Unknown artifact type: {artifact_type}",
                    "known_types": sorted(KNOWN_ARTIFACT_TYPES),
                }
            )

        if artifact_type:
            records = bridge.get_artifacts_by_type(artifact_type, limit=200)
        else:
            records = []
            for t in bridge.list_artifact_types()[:20]:
                records.extend(bridge.get_artifacts_by_type(t, limit=10))

        result = [r.model_dump(exclude_none=True) for r in records]
        return json.dumps(result, indent=2)

    @mcp.tool()
    def bridge_get_artifact(artifact_type: str, index_id: str | None = None) -> str:
        """Load and return full JSON content for an artifact type."""
        if artifact_type not in KNOWN_ARTIFACT_TYPES:
            return json.dumps(
                {
                    "error": f"Unknown artifact type: {artifact_type}",
                    "known_types": sorted(KNOWN_ARTIFACT_TYPES),
                }
            )

        try:
            data = loader.load_json(artifact_type, index_id=index_id)
        except ArtifactNotFoundError as exc:
            return json.dumps({"error": str(exc)})
        except ChecksumMismatchError as exc:
            return json.dumps({"error": str(exc), "warning": "checksum_mismatch"})
        except ArtifactParseError as exc:
            return json.dumps({"error": str(exc)})

        return json.dumps({"ok": True, "artifact_type": artifact_type, "data": data}, indent=2, default=str)

    @mcp.tool()
    def bridge_get_artifact_by_path(logical_path: str) -> str:
        """Load artifact content by its exact logical path."""
        record = bridge.get_artifact_by_logical_path(logical_path)
        if not record:
            return json.dumps({"error": f"No artifact at path: {logical_path}"})

        try:
            content = loader.load_artifact(record)
        except (ArtifactNotFoundError, ChecksumMismatchError, ArtifactParseError) as exc:
            return json.dumps({"error": str(exc)})

        return json.dumps(
            {
                "ok": True,
                "record": record.model_dump(exclude_none=True),
                "data": content.data,
                "resolved_path": content.resolved_path,
                "checksum_verified": content.checksum_verified,
            },
            indent=2,
            default=str,
        )

    @mcp.tool()
    def bridge_search_artifacts(query: str, artifact_type: str | None = None) -> str:
        """Fuzzy search artifacts by logical path."""
        records = bridge.search_artifacts(query, artifact_type=artifact_type)
        result = [r.model_dump(exclude_none=True) for r in records]
        return json.dumps(result, indent=2)

    @mcp.tool()
    def bridge_get_stats() -> str:
        """Return registry statistics."""
        stats = bridge.stats()
        return json.dumps(stats.model_dump(exclude_none=True), indent=2)

    return mcp


def run_mcp_stdio(ctn_dir: Path) -> None:
    """Run the MCP server over stdio (default for IDE integrations)."""
    mcp = create_mcp_server(ctn_dir)
    mcp.run(transport="stdio")


def run_mcp_sse(ctn_dir: Path, host: str = "127.0.0.1", port: int = DEFAULT_MCP_SSE_PORT) -> None:
    """Run the MCP server over SSE transport."""
    mcp = create_mcp_server(ctn_dir)
    LOGGER.info("mcp_sse_starting", host=host, port=port)
    mcp.run(transport="sse", host=host, port=port)


__all__ = [
    "create_mcp_server",
    "run_mcp_stdio",
    "run_mcp_sse",
]
