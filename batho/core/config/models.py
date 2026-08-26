"""Pydantic models for Batho v1.2.0 configuration."""

from __future__ import annotations

import logging
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


SCHEMA_VERSIONS: dict[str, str] = {
    "config": "batho-config.v1",
    "bsg": "bsg.v1",
}

DEFAULT_LOG_LEVEL = "ERROR"
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
    artifact_dir: str = Field(default=".batho/artifact")
    cache_dir: str = Field(default=".batho/cache")
    bsg_dir: str = Field(default=".batho/bsg")


class IndexerConfig(BaseModel):
    max_file_size_kb: int = Field(default=DEFAULT_MAX_FILE_SIZE_KB, ge=1)
    max_indexed_files: int = Field(default=DEFAULT_MAX_INDEXED_FILES, ge=1)
    max_workers: int = Field(default=DEFAULT_INDEX_WORKERS, ge=0)
    ignore_patterns: list[str] = Field(default_factory=list)
    ignore_files: list[str] | None = Field(default=None)
    default_patterns_file: str | None = Field(default=None)
    fail_on_warning: bool = Field(default=False)
    strict: bool = Field(default=False)


class GraphCycleDetectionConfig(BaseModel):
    enabled: bool = Field(default=True)
    fatal: bool = Field(default=False)


class GraphOrphanPruningConfig(BaseModel):
    enabled: bool = Field(default=True)
    keep_entry_points: bool = Field(default=True)
    keep_exports: bool = Field(default=True)


class GraphBackendConfig(BaseModel):
    """Graph storage backend selection and Arrow-specific tuning."""

    backend: str = Field(default="auto")  # "auto" | "in-memory" | "arrow"
    auto_threshold_files: int = Field(default=500, ge=1)
    auto_threshold_entities: int = Field(default=30_000, ge=1)
    arrow_staging_dir: str = Field(default=".batho/graph_staging")
    arrow_flush_rows: int = Field(default=5000, ge=100)
    arrow_flush_bytes_mb: float = Field(default=1.0, ge=0.1)
    # Reserved for future delta-overlay support (patch on Arrow); unused in Phase 1.
    arrow_recompact_delta_ratio: float = Field(default=0.10, ge=0.01, le=1.0)

    @field_validator("backend")
    @classmethod
    def _validate_backend(cls, v: str) -> str:
        if v not in ("auto", "in-memory", "arrow"):
            raise ValueError(
                "graph.backend.backend must be 'auto', 'in-memory', or 'arrow'"
            )
        return v


class GraphConfig(BaseModel):
    backend: GraphBackendConfig = Field(default_factory=GraphBackendConfig)
    cycle_detection: GraphCycleDetectionConfig = Field(
        default_factory=GraphCycleDetectionConfig
    )
    orphan_pruning: GraphOrphanPruningConfig = Field(
        default_factory=GraphOrphanPruningConfig
    )


class CommunityDetectionConfig(BaseModel):
    enabled: bool = Field(default=True)
    skip_threshold: int = Field(default=200_000, ge=1)
    sample_threshold: int = Field(default=100_000, ge=1)


class MemoryConfig(BaseModel):
    warning_threshold_mb: float = Field(default=800.0, ge=1.0)
    critical_threshold_mb: float = Field(default=1500.0, ge=1.0)
    rss_flush_threshold_mb: float = Field(default=1000.0, ge=1.0)
    max_per_worker_mb: float = Field(default=150.0, ge=1.0)


class FlagsConfig(BaseModel):
    fail_on_warning: bool = Field(default=False)
    strict: bool = Field(default=False)
    audit_log_enabled: bool = Field(default=True)


class McpToolsConfig(BaseModel):
    """Tool exposure controls for the MCP server.

    disabled: blocklist of tool names not registered on the MCP app.
              Default disables expensive administrative tools (build/export/load/gc)
              so the agent surface stays focused on retrieval + diagnostics.
              Set to [] to expose all 19 tools to the agent.
    enabled:  optional allowlist. If set, ONLY these tools are registered
              (disabled is ignored). None = no allowlist filtering.
    """
    disabled: list[str] = Field(
        default_factory=lambda: ["batho_build", "batho_export", "batho_load", "batho_gc"]
    )
    enabled: list[str] | None = Field(default=None)

    @field_validator("disabled", "enabled")
    @classmethod
    def _normalize_tool_names(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        return [name.strip() for name in v if name.strip()]


class McpConfig(BaseModel):
    """MCP server configuration."""
    enabled: bool = Field(default=True)
    tools: McpToolsConfig = Field(default_factory=McpToolsConfig)


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


class BsgCacheConfig(BaseModel):
    enabled: bool = Field(default=True)
    max_size_mb: int = Field(default=1024, ge=1)
    ttl_days: int = Field(default=30, ge=1)


class BsgSymbolResolutionConfig(BaseModel):
    enabled: bool = Field(default=True)
    fuzzy_matching: bool = Field(default=False)
    cache_symbols: bool = Field(default=True)
    prune_unresolved: bool = Field(default=True)
    max_unresolved_attempts: int = Field(default=10)
    unresolved_tracking: bool = Field(default=True)


class BsgParsingConfig(BaseModel):
    error_recovery: bool = Field(default=True)
    skip_comments: bool = Field(default=False)


class BsgBidirectionalConfig(BaseModel):
    enabled: bool = Field(default=True)
    include_gaps: bool = Field(default=True)
    verify_integrity: bool = Field(default=False)
    storage_view: bool = Field(default=False)


class BsgConfig(BaseModel):
    parallel: BsgParallelConfig = Field(default_factory=BsgParallelConfig)
    cache: BsgCacheConfig = Field(default_factory=BsgCacheConfig)
    symbol_resolution: BsgSymbolResolutionConfig = Field(
        default_factory=BsgSymbolResolutionConfig
    )
    parsing: BsgParsingConfig = Field(default_factory=BsgParsingConfig)
    bidirectional: BsgBidirectionalConfig = Field(
        default_factory=BsgBidirectionalConfig
    )


class PersistenceConfig(BaseModel):
    batch_size: int = Field(default=500, ge=1)
    batch_bytes_threshold: int = Field(default=15_728_640, ge=1)  # 15 MB


class DependencyIntrospectionConfig(BaseModel):
    enabled: bool = Field(default=True)
    mode: str = Field(default="shallow")   # "shallow" | "deep"
    venv_auto_detect: bool = Field(default=True)
    timeout_seconds: int = Field(default=5)
    full_scan: bool = Field(default=False)  # True = introspect all declared deps; False = popular-packages DB filter
    popular_packages_db_path: str | None = Field(default=None)  # Override bundled YAML; null = use default

class DependencyStdlibConfig(BaseModel):
    enabled: bool = Field(default=True)
    languages: list[str] = Field(default_factory=lambda: ["python", "javascript", "go", "rust"])

class DependencyCacheConfig(BaseModel):
    enabled: bool = Field(default=True)
    ttl_days: int = Field(default=90)
    # cache_dir is inherited from paths.cache_dir (unified cache directory)

class DependencyConfig(BaseModel):
    enabled: bool = Field(default=True)
    introspection: DependencyIntrospectionConfig = Field(
        default_factory=DependencyIntrospectionConfig
    )
    stdlib: DependencyStdlibConfig = Field(default_factory=DependencyStdlibConfig)
    cache: DependencyCacheConfig = Field(default_factory=DependencyCacheConfig)
    max_deps_per_manifest: int = Field(default=500, ge=1)


class ExtractionCacheConfig(BaseModel):
    enabled: bool = Field(default=True)
    ttl_days: int = Field(default=30)
    max_entries: int = Field(default=5000, ge=1)


class ExtractionConfig(BaseModel):
    cache: ExtractionCacheConfig = Field(default_factory=ExtractionCacheConfig)


class Config(BaseModel):
    schema_version: Literal["batho-config.v1"] = Field(default=SCHEMA_VERSIONS["config"])
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)
    indexer: IndexerConfig = Field(default_factory=IndexerConfig)
    graph: GraphConfig = Field(default_factory=GraphConfig)
    flags: FlagsConfig = Field(default_factory=FlagsConfig)
    mcp: McpConfig = Field(default_factory=McpConfig)
    rules: RulesConfig = Field(default_factory=RulesConfig)
    plugins: PluginsConfig = Field(default_factory=PluginsConfig)
    artifact_blobs: ArtifactBlobsConfig = Field(default_factory=ArtifactBlobsConfig)
    persistence: PersistenceConfig = Field(default_factory=PersistenceConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    bsg: BsgConfig = Field(default_factory=BsgConfig)
    dependency: DependencyConfig = Field(default_factory=DependencyConfig)
    extraction: ExtractionConfig = Field(default_factory=ExtractionConfig)
    community_detection: CommunityDetectionConfig = Field(
        default_factory=CommunityDetectionConfig
    )

    @field_validator("logging")
    @classmethod
    def _normalize_log_level(cls, v: LoggingConfig) -> LoggingConfig:
        v.level = v.level.upper()
        return v
