"""Pydantic models for Batho v1.1.0 configuration."""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field, field_validator


SCHEMA_VERSIONS: dict[str, str] = {
    "config": "batho-config.v1",
    "graph": "graph.v1",
    "bsg": "bsg.v1",
    "snapshot": "snapshot.v1",
    "run_artifacts": "run-artifacts.v1",
    "file_artifacts": "file-artifacts.v1",
    "ignore_patterns": "ignore-patterns.v1",
}

DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_DB_PATH = "{root}"
DEFAULT_MAX_FILE_SIZE_KB = 500
DEFAULT_MAX_INDEXED_FILES = 200_000
DEFAULT_INDEX_WORKERS = 0

DEFAULT_RULES_BUILTIN_PLUGINS = (
    "bsg_core",
    "bsg_silent_failure_catcher",
    "bsg_dependency_blast_radius",
    "bsg_resource_leak_preventer",
    "bsg_nplus1_query_catcher",
    "bsg_iac_drift_sentinel",
    "bsg_schema_migration_enforcer",
    "bsg_api_contract_guardian",
    "bsg_hardcoded_secret_catcher",
    "bsg_auth_boundary_shield",
)


class LoggingConfig(BaseModel):
    level: str = Field(default=DEFAULT_LOG_LEVEL)
    json_format: bool | None = Field(default=None)
    quiet: bool = Field(default=False)
    file: str | None = Field(default=None)
    format: str = Field(default="%(message)s")

    @field_validator("quiet", mode="before")
    @classmethod
    def _normalize_quiet(cls, value: Any) -> bool:
        if value is None:
            return False
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    @property
    def std_level(self) -> int:
        name = (self.level or DEFAULT_LOG_LEVEL).upper()
        return {
            "DEBUG": logging.DEBUG,
            "INFO": logging.INFO,
            "WARNING": logging.WARNING,
            "ERROR": logging.ERROR,
            "CRITICAL": logging.CRITICAL,
        }.get(name, logging.INFO)

    @property
    def effective_level(self) -> int:
        if self.quiet:
            return logging.ERROR
        return self.std_level


class PathsConfig(BaseModel):
    db_path: str = Field(default=DEFAULT_DB_PATH)

    @field_validator("db_path", mode="before")
    @classmethod
    def _normalize_db_path(cls, value: Any) -> str:
        if isinstance(value, dict) and "root" in value:
            return "{root}"
        if value is None:
            return "{root}"
        if not isinstance(value, str):
            return str(value)
        return value



class IndexerConfig(BaseModel):
    max_file_size_kb: int = Field(default=DEFAULT_MAX_FILE_SIZE_KB, ge=1)
    max_indexed_files: int = Field(default=DEFAULT_MAX_INDEXED_FILES, ge=1)
    max_workers: int = Field(default=DEFAULT_INDEX_WORKERS, ge=0)
    max_files: int | None = Field(default=None, ge=1)
    ignore_patterns: list[str] = Field(default_factory=list)
    ignore_files: list[str] | None = Field(default=None)
    default_patterns_file: str | None = Field(default=None)
    fail_on_warning: bool = Field(default=False)
    strict: bool = Field(default=False)


class PatchConfig(BaseModel):
    timeout_seconds: int = Field(default=300)
    max_changes: int = Field(default=10_000)
    history_days: int = Field(default=90)
    max_count: int = Field(default=1_000)
    cleanup_on_startup: bool = Field(default=False)


class FlagsConfig(BaseModel):
    fail_on_warning: bool = Field(default=False)
    strict: bool = Field(default=False)
    audit_log_enabled: bool = Field(default=True)


class RulesConfig(BaseModel):
    enabled: bool = Field(default=True)
    auto_load_all_plugins: bool = Field(default=True)
    builtin_plugins: list[str] = Field(
        default_factory=lambda: list(DEFAULT_RULES_BUILTIN_PLUGINS)
    )
    disabled_rules: list[str] = Field(default_factory=list)
    custom_rules_path: str | None = Field(default=None)
    custom_rules_inline: list[dict[str, Any]] = Field(default_factory=list)
    strict_validation: bool = Field(default=False)
    cache_ttl: int = Field(default=3600, ge=0)
    fail_on_rule_error: bool = Field(default=False)


class PluginsConfig(BaseModel):
    overrides: dict[str, dict[str, dict[str, Any]]] = Field(default_factory=dict)


class FileArtifactBlobsConfig(BaseModel):
    bsg_agent_view: bool = Field(default=True)
    bsg_storage_view: bool = Field(default=True)
    bsg_rel_view: bool = Field(default=True)


class RunArtifactBlobsConfig(BaseModel):
    context_overview: bool = Field(default=True)
    telemetry_metrics: bool = Field(default=True)
    structural_metrics: bool = Field(default=True)
    security_audit: bool = Field(default=False)
    artifact_payload: bool = Field(default=True)
    delta_stats: bool = Field(default=True)


class ArtifactBlobsConfig(BaseModel):
    file_artifacts: FileArtifactBlobsConfig = Field(
        default_factory=FileArtifactBlobsConfig
    )
    run_artifacts: RunArtifactBlobsConfig = Field(
        default_factory=RunArtifactBlobsConfig
    )


class BsgParallelConfig(BaseModel):
    enabled: bool = Field(default=True)
    max_workers: int = Field(default=16, ge=1, le=32)
    chunk_size: int = Field(default=50, ge=1)


class BsgIgnoreConfig(BaseModel):
    enabled: bool = Field(default=True)


class BsgCacheConfig(BaseModel):
    enabled: bool = Field(default=True)
    max_size_mb: int = Field(default=1024, ge=1)
    ttl_days: int = Field(default=30, ge=1)


class BsgIncrementalConfig(BaseModel):
    enabled: bool = Field(default=True)
    auto_detect_git: bool = Field(default=True)


class BsgSymbolResolutionConfig(BaseModel):
    enabled: bool = Field(default=True)
    fuzzy_matching: bool = Field(default=False)
    cache_symbols: bool = Field(default=True)
    prune_unresolved: bool = Field(default=True)
    max_unresolved_attempts: int = Field(default=10)
    unresolved_tracking: bool = Field(default=True)


class BsgSerializationConfig(BaseModel):
    method: str = Field(default="streaming")
    compression: bool = Field(default=False)
    batch_size: int = Field(default=1000, ge=1)


class BsgParsingConfig(BaseModel):
    error_recovery: bool = Field(default=True)
    partial_parsing: bool = Field(default=False)
    max_file_size_mb: int = Field(default=10, ge=1)
    skip_comments: bool = Field(default=False)


class BsgQueryConfig(BaseModel):
    enabled: bool = Field(default=True)
    index_on_write: bool = Field(default=True)
    cache_enabled: bool = Field(default=True)
    cache_size: int = Field(default=256, ge=1)
    default_limit: int = Field(default=200, ge=1)
    query_timeout_ms: int = Field(default=5000, ge=1)


class BsgStorageRetentionConfig(BaseModel):
    enabled: bool = Field(default=True)
    snapshot_ttl_days: int = Field(default=90, ge=1)
    patch_ttl_days: int = Field(default=90, ge=1)
    metrics_ttl_days: int = Field(default=30, ge=1)
    context_ttl_days: int = Field(default=90, ge=1)
    max_snapshots: int = Field(default=500, ge=1)
    max_patches: int = Field(default=5000, ge=1)


class BsgStorageConfig(BaseModel):
    enabled: bool = Field(default=True)
    content_scope: str = Field(default="durable")
    track_content_ids: bool = Field(default=True)
    busy_timeout_ms: int = Field(default=5000, ge=100)
    page_size: int = Field(default=8192)
    auto_vacuum: str = Field(default="incremental")
    retention: BsgStorageRetentionConfig = Field(
        default_factory=BsgStorageRetentionConfig
    )

    @field_validator("content_scope")
    @classmethod
    def _validate_scope(cls, value: str) -> str:
        normalized = value.strip().lower()
        return normalized if normalized in {"durable", "all"} else "durable"

    @field_validator("auto_vacuum")
    @classmethod
    def _validate_auto_vacuum(cls, value: str) -> str:
        normalized = value.strip().lower()
        return normalized if normalized in {"none", "full", "incremental"} else "incremental"


class BsgBidirectionalConfig(BaseModel):
    enabled: bool = Field(default=True)
    include_gaps: bool = Field(default=True)
    verify_integrity: bool = Field(default=False)
    storage_view: bool = Field(default=False)


class BsgConfig(BaseModel):
    parallel: BsgParallelConfig = Field(default_factory=BsgParallelConfig)
    ignore: BsgIgnoreConfig = Field(default_factory=BsgIgnoreConfig)
    cache: BsgCacheConfig = Field(default_factory=BsgCacheConfig)
    incremental: BsgIncrementalConfig = Field(default_factory=BsgIncrementalConfig)
    symbol_resolution: BsgSymbolResolutionConfig = Field(
        default_factory=BsgSymbolResolutionConfig
    )
    serialization: BsgSerializationConfig = Field(
        default_factory=BsgSerializationConfig
    )
    parsing: BsgParsingConfig = Field(default_factory=BsgParsingConfig)
    query: BsgQueryConfig = Field(default_factory=BsgQueryConfig)
    storage: BsgStorageConfig = Field(default_factory=BsgStorageConfig)
    bidirectional: BsgBidirectionalConfig = Field(
        default_factory=BsgBidirectionalConfig
    )


class Config(BaseModel):
    schema_version: str = Field(default=SCHEMA_VERSIONS["config"])
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)
    indexer: IndexerConfig = Field(default_factory=IndexerConfig)
    patch: PatchConfig = Field(default_factory=PatchConfig)
    flags: FlagsConfig = Field(default_factory=FlagsConfig)
    rules: RulesConfig = Field(default_factory=RulesConfig)
    plugins: PluginsConfig = Field(default_factory=PluginsConfig)
    artifact_blobs: ArtifactBlobsConfig = Field(default_factory=ArtifactBlobsConfig)
    bsg: BsgConfig = Field(default_factory=BsgConfig)

    @field_validator("logging")
    @classmethod
    def _normalize_log_level(cls, v: LoggingConfig) -> LoggingConfig:
        v.level = v.level.upper()
        return v
