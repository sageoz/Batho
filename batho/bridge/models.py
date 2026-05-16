"""Pydantic models for the Batho bridge API."""

from __future__ import annotations

from datetime import datetime
from typing import Any

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


__all__ = [
    "ArtifactRecord",
    "IndexEntry",
    "IndexListResponse",
    "BridgeResponse",
    "BridgeErrorResponse",
    "RegistryStats",
]
