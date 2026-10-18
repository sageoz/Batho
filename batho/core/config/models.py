"""Pydantic models for Batho v1.2.0 configuration."""

from __future__ import annotations

import logging
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


SCHEMA_VERSIONS: dict[str, str] = {
    "config": "batho-config.v1",
    "bsg": "bsg.v1",
}

DEFAULT_LOG_LEVEL = "ERROR"
DEFAULT_MAX_FILE_SIZE_KB = 500
DEFAULT_MAX_INDEXED_FILES = 200_000
DEFAULT_INDEX_WORKERS = 0

# Canonical §16.3 catalog stems (SDK core pack). The pre-relocation bsg_*
# names still resolve via _PLUGIN_ALIASES with a DeprecationWarning (F5).
DEFAULT_RULES_BUILTIN_PLUGINS = (
    "graph_foundation",
    "classification",
    "manifests",
    "cicd",
    "cloud_providers",
    "test_frameworks",
    "token_optimization",
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


class ProgressConfig(BaseModel):
    """Progress display for long-running commands (`batho build` / `batho patch`)."""
    enabled: bool = Field(default=True)
    style: Literal["progress", "classic"] = Field(default="progress")
    mininterval_s: float = Field(default=0.2, ge=0)
    show_after_s: float = Field(default=2.0, ge=0)
    keepalive_s: float = Field(default=60.0, ge=0)


class PathsConfig(BaseModel):
    artifact_dir: str = Field(default=".batho/artifact")
    cache_dir: str = Field(default=".batho/cache")
    bsg_dir: str = Field(default=".batho/bsg")


class IndexerConfig(BaseModel):
    max_file_size_kb: int = Field(default=DEFAULT_MAX_FILE_SIZE_KB, ge=1)
    # Oversize files: "skip" (legacy, drop from the graph) or "outline"
    # (default, index files between max_file_size_kb and
    # oversize_outline_max_kb so their definitions stay visible).
    oversize_mode: Literal["skip", "outline"] = Field(default="outline")
    oversize_outline_max_kb: int = Field(default=4096, ge=1)
    max_indexed_files: int = Field(default=DEFAULT_MAX_INDEXED_FILES, ge=1)
    max_workers: int = Field(default=DEFAULT_INDEX_WORKERS, ge=0)
    ignore_patterns: list[str] = Field(default_factory=list)
    ignore_files: list[str] | None = Field(default=None)
    default_patterns_file: str | None = Field(default=None)
    ignore_defaults: bool = Field(default=True)
    package_roots: list[str] = Field(default_factory=list)
    fail_on_warning: bool = Field(default=False)
    strict: bool = Field(default=False)
    # True = SHA-256 every tracked file on every patch; False enables the
    # mtime/inode/size fast-path in IncrementalEngine.scan_changes.
    strict_hashing: bool = Field(default=False)
    # Cap on file_changelog rows retained per file across patch runs.
    file_changelog_max_runs: int = Field(default=100, ge=1)


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


class CommunityLLMConfig(BaseModel):
    """T16: `batho communities label` — optional post-build LLM labeling."""
    enabled: bool = Field(default=False)
    provider: str = Field(default="anthropic")
    model: str = Field(default="claude-haiku-4-5-20251001")
    # Cap on card content (~200 tokens ≈ ~800 chars target).
    max_card_tokens: int = Field(default=200, ge=50)


class CommunityDetectionConfig(BaseModel):
    enabled: bool = Field(default=True)
    skip_threshold: int = Field(default=200_000, ge=1)
    sample_threshold: int = Field(default=100_000, ge=1)
    # T4: per-kind edge weights for clustering input; a weight of 0 excludes
    # the kind entirely (CONTAINS encodes file layout, not coupling).
    # Combined with call-site multiplicity × edge confidence per pair.
    edge_weights: dict[str, float] = Field(
        default_factory=lambda: {
            "CALLS": 3.0,
            "INHERITS": 3.0,
            "IMPLEMENTS": 3.0,
            "IMPORTS": 2.0,
            "READS": 1.0,
            "WRITES": 1.0,
            "CONTAINS": 0.0,
        }
    )
    # Communities smaller than this merge into their strongest neighbor;
    # unmergeable ones are flagged is_singleton and hidden from overview.
    min_community_entities: int = Field(default=3, ge=1)
    # A community larger than this fraction of clustered entities is split by
    # a recursive clustering pass on its induced subgraph (depth cap 2).
    max_community_fraction: float = Field(default=0.25, gt=0, le=1.0)
    # Entities above this degree percentile are dropped before detection
    # (god-nodes like utils/loggers) and reattached to the neighboring
    # community with maximum shared edge weight.
    superhub_degree_percentile: float = Field(default=99.0, ge=50.0, le=100.0)
    # Directory names too generic to label a community (labeling tier 1).
    generic_dir_blocklist: list[str] = Field(
        default_factory=lambda: [
            "src", "lib", "app", "core", "utils", "common",
            "shared", "helpers", "test", "tests",
        ]
    )
    # graph_overview shows the top-N communities by entity count.
    overview_top_n: int = Field(default=12, ge=1)
    # T15: optional L0 domain tier — entities are pre-grouped by dominant
    # bsg.* metadata (bsg.domain → bsg.service_tag → bsg.category priority,
    # untagged → "(untagged)") and structural clustering runs within each
    # domain group, producing domain → community → sub-community trees.
    domain_grouping: bool = Field(default=False)
    # T16: optional post-build LLM labeler (`batho communities label`).
    # Disabled by default — never runs in the query path; labels persist to
    # communities.ipc so later reads are deterministic and LLM-free.
    llm: CommunityLLMConfig = Field(default_factory=lambda: CommunityLLMConfig())


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
              None = unset — the server resolves mcp.toolsets or its
              secure-by-default set (batho_build, batho_export, batho_load,
              batho_gc). Set to [] to expose all 20 tools to the agent.
    enabled:  optional allowlist. If set, ONLY these tools are registered
              (disabled is ignored). None = no allowlist filtering.
    """
    disabled: list[str] | None = Field(default=None)
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
    # Named tool groups resolved to a disabled set by the MCP server
    # (batho/mcp/server.py). Only consulted when tools.disabled /
    # tools.enabled are both unset. true = enable the group,
    # false = disable it. None = section absent (secure defaults).
    toolsets: dict[str, bool] | None = Field(default=None)


class RulesConfig(BaseModel):
    enabled: bool = Field(default=True)
    auto_load_all_plugins: bool = Field(default=True)
    builtin_plugins: list[str] = Field(
        default_factory=lambda: list(DEFAULT_RULES_BUILTIN_PLUGINS)
    )
    disabled_rules: list[str] = Field(default_factory=list)
    custom_rules_path: str | None = Field(default=None)
    custom_rules_dir: str | None = Field(default=".batho/plugins")
    custom_rules_inline: list[dict[str, Any]] = Field(default_factory=list)
    strict_validation: bool = Field(default=False)
    cache_ttl: int = Field(default=3600, ge=0)
    fail_on_rule_error: bool = Field(default=False)


class PluginCoreConfig(BaseModel):
    """Foundation-pack policy (``plugins.core``, spec §8.2)."""

    model_config = ConfigDict(extra="forbid")

    required: bool = Field(
        default=True,
        description="Build fails (with guidance) if the core pack is missing/invalid.",
    )


class PluginExternalConfig(BaseModel):
    """External-pack gating (``plugins.external``, spec §8.2)."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(
        default=False,
        description="Master switch for the optional external pack (opt-in).",
    )
    select: list[str] = Field(
        default_factory=list,
        description="Per-plugin allowlist; empty = load every external plugin.",
    )


class PluginTelemetryConfig(BaseModel):
    """Plugin telemetry policy (``plugins.telemetry``, spec §8.2)."""

    model_config = ConfigDict(extra="forbid")

    hooks_metadata: bool = Field(
        default=False,
        description="When true, stamp bsg.hooks provenance on entities (debug).",
    )


class PluginHostConfig(BaseModel):
    """PluginHost dispatch policy (``plugins.host``, spec §8.2)."""

    model_config = ConfigDict(extra="forbid")

    dispatch_order: Literal["priority_then_id"] = Field(
        default="priority_then_id",
        description=(
            "Reserved. Hooks always dispatch priority-desc then plugin_id-asc; "
            "the key exists to reject alternative orderings up front (extra='forbid')."
        ),
    )


class PluginsConfig(BaseModel):
    """Plugin-host configuration (``plugins.*``, spec §8.2) plus the legacy
    rule-engine ``overrides`` fold (read by ``effective_rules_config``)."""

    model_config = ConfigDict(extra="forbid")

    overrides: dict[str, dict[str, dict[str, Any]]] = Field(default_factory=dict)
    core: PluginCoreConfig = Field(default_factory=PluginCoreConfig)
    external: PluginExternalConfig = Field(default_factory=PluginExternalConfig)
    fingerprint_in_cache: bool = Field(
        default=True,
        description="Include the plugin fingerprint in the AST cache key (§9).",
    )
    reextract_on_drift: bool = Field(
        default=True,
        description="Escalate patch to full-repo re-extraction when the plugin fingerprint drifts from the last run (§9).",
    )
    telemetry: PluginTelemetryConfig = Field(default_factory=PluginTelemetryConfig)
    host: PluginHostConfig = Field(default_factory=PluginHostConfig)


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
    rule_stats: bool = Field(default=True)
    enrich_profile: bool = Field(default=True)
    enrich_score: bool = Field(default=True)


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
    prune_unresolved: bool = Field(default=True)


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
    # Skip introspection for deps whose environment (venv, node_modules,
    # vendor/, user package store, ...) cannot be found — no fallback
    # {name: [name]} stubs, no cache pollution. When false, missing envs fall
    # back to best-effort introspection with toolchain defaults.
    skip_missing_env: bool = Field(default=True)
    # Per-manager overrides, e.g. {gem: false} disables gem introspection.
    # Keys are PackageManager values ("pip", "npm", "cargo", ...); unknown
    # keys log a warning and are ignored. null = all managers enabled.
    managers: dict[str, bool] | None = Field(default=None)

class DependencyStdlibConfig(BaseModel):
    enabled: bool = Field(default=True)
    # None = auto-detect from project manifests at index time. An explicit
    # list (config file) overrides detection — needed for polyglot repos
    # whose manifests don't cover every language they use.
    languages: list[str] | None = Field(default=None)

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


class WorkspaceConfig(BaseModel):
    """Workspace manifest scoping (multi-repo-identity T6).

    ``manifest_dirs``: allowlist ``[dir, ...]`` or ``{allow: [...], deny: [...]}``
    of repo-relative dir prefixes; deny wins. null = every discovered manifest.
    """
    manifest_dirs: list[str] | dict[str, list[str]] | None = Field(default=None)


class PackageOverrideConfig(BaseModel):
    """Explicit ``project.package`` identity override (multi-repo-identity T6)."""
    manager: str = Field(default="pip")
    name: str
    version: str = Field(default="0.0.0")


class ProjectConfig(BaseModel):
    """Project-level overrides; consumed by ManifestParser._workspace_config."""
    package: PackageOverrideConfig | None = Field(default=None)


class ExtractionConfig(BaseModel):
    cache: ExtractionCacheConfig = Field(default_factory=ExtractionCacheConfig)
    # T02: Opt-in entity extraction flags. CONSTRUCTOR and ENUM_MEMBER are
    # extracted by default (low entity-count impact). PARAMETER and
    # TYPE_PARAMETER are opt-in to avoid entity count inflation.
    extract_parameters: bool = Field(default=False)
    extract_type_parameters: bool = Field(default=False)
    # T5 rationale layer: comment markers that promote a standalone comment to
    # a first-class COMMENT_BLOCK entity with a RATIONALE_FOR edge. An
    # explicit empty list disables the marker layer entirely; null/unset
    # keeps the defaults.
    rationale_markers: list[str] = Field(
        default_factory=lambda: ["WHY:", "NOTE:"]
    )
    rationale_markers_case_sensitive: bool = Field(default=True)


class WatchConfig(BaseModel):
    """File-watcher / auto-patch tuning for the MCP watcher engine.

    ``mode``: ``auto`` enables the git sentinel layer when the repo resolves a
    git dir (falls back to file events otherwise); ``fs`` = file events only;
    ``off`` = track state for staleness banners but never auto-patch.
    """

    mode: Literal["auto", "fs", "off"] = Field(default="auto")
    max_staleness_ms: int = Field(default=60_000)
    flush_threshold: int = Field(default=300)
    git_settle_ms: int = Field(default=300)
    vcs_op_hold_ms: int = Field(default=30_000)

    @field_validator("mode", mode="before")
    @classmethod
    def _normalize_mode(cls, value: Any) -> str:
        if value not in {"auto", "fs", "off"}:
            raise ValueError("watch.mode must be 'auto', 'fs', or 'off'")
        return value

    @field_validator("max_staleness_ms")
    @classmethod
    def _clamp_staleness(cls, value: int) -> int:
        return max(5_000, min(600_000, int(value)))

    @field_validator("flush_threshold")
    @classmethod
    def _clamp_threshold(cls, value: int) -> int:
        return max(10, min(100_000, int(value)))

    @field_validator("git_settle_ms")
    @classmethod
    def _clamp_settle(cls, value: int) -> int:
        return max(50, min(5_000, int(value)))

    @field_validator("vcs_op_hold_ms")
    @classmethod
    def _clamp_hold(cls, value: int) -> int:
        return max(1_000, min(300_000, int(value)))


class SkillsConfig(BaseModel):
    """Agent skill-pack management (``batho skills`` + auto-sync on ``batho mcp``)."""

    auto_install: bool = Field(default=True)


class Config(BaseModel):
    schema_version: Literal["batho-config.v1"] = Field(default=SCHEMA_VERSIONS["config"])
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    progress: ProgressConfig = Field(default_factory=ProgressConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)
    indexer: IndexerConfig = Field(default_factory=IndexerConfig)
    watch: WatchConfig = Field(default_factory=WatchConfig)
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
    workspace: WorkspaceConfig | None = Field(default=None)
    project: ProjectConfig | None = Field(default=None)
    community_detection: CommunityDetectionConfig = Field(
        default_factory=CommunityDetectionConfig
    )
    skills: SkillsConfig = Field(default_factory=SkillsConfig)

    @field_validator("logging")
    @classmethod
    def _normalize_log_level(cls, v: LoggingConfig) -> LoggingConfig:
        v.level = v.level.upper()
        return v
