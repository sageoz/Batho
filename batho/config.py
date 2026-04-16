"""
Typed configuration and build info helpers for Batho core.

Features
- Pydantic-validated config with sane defaults.
- Single root config file ``./batho.yaml`` as the source of truth.
- Env-variable overrides kept for compatibility.
- Strict/fail-on-warning flags for regulated environments.
- Schema identifiers for persisted artifacts.
"""

from __future__ import annotations

import importlib.metadata
import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator

from batho.cloud_sync.config import CloudSyncConfig

DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_CTN_DIR = ".ctn"
DEFAULT_MAX_FILE_SIZE_KB = 500
DEFAULT_MAX_INDEXED_FILES = 200000  # allow large repos
DEFAULT_INDEX_WORKERS = 0  # auto
DEFAULT_IGNORE_FILES: list[str] | None = None
DEFAULT_METRICS_OUTPUT: str | None = ".ctn/metrics.json"
DEFAULT_ROOT_CONFIG_FILE = "batho.yaml"
DEFAULT_RULES_ENABLED = True
DEFAULT_RULES_INTERCEPTOR_PLUGINS = (
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
DEFAULT_RULES_BUILTIN_PLUGINS = ("bsg_core",) + DEFAULT_RULES_INTERCEPTOR_PLUGINS
DEFAULT_RULES_CACHE_TTL = 3600
DEFAULT_PATCH_TIMEOUT_SECONDS = 300  # 5 minutes
DEFAULT_MAX_PATCH_CHANGES = 10000  # Max changes in a single patch
DEFAULT_PATCH_HISTORY_DAYS = 90  # Retention policy for patches
DEFAULT_PATCH_COUNT = 1000  # Alternative retention limit
DEFAULT_STORAGE_REGISTRY_PATH = ".ctn/artifact_registry.db"
DEFAULT_STORAGE_RETENTION_SNAPSHOT_DAYS = 90
DEFAULT_STORAGE_RETENTION_PATCH_DAYS = 90
DEFAULT_STORAGE_RETENTION_METRICS_DAYS = 30
DEFAULT_STORAGE_RETENTION_CONTEXT_DAYS = 90
DEFAULT_STORAGE_RETENTION_MAX_SNAPSHOTS = 500
DEFAULT_STORAGE_RETENTION_MAX_PATCHES = 5000

GRAPH_SCHEMA_VERSION = "graph.v1"
BSG_SCHEMA_VERSION = "bsg.v1"
SNAPSHOT_SCHEMA_VERSION = "snapshot.v1"
INDEX_METADATA_SCHEMA_VERSION = "index-metadata.v1"
FILE_CACHE_SCHEMA_VERSION = "file-cache.v1"


class LoggingConfig(BaseModel):
    level: str = Field(default=DEFAULT_LOG_LEVEL)
    json_format: Optional[bool] = Field(
        default=None, description="Force JSON logs when True, console when False"
    )
    quiet: bool = Field(default=False, description="Suppress all non-error output")
    file: Optional[str] = Field(default=None, description="Optional log file path")
    format: str = Field(default="%(message)s", description="Log format string")

    @field_validator("quiet", mode="before")
    @classmethod
    def _normalize_quiet(cls, value: Any) -> bool:  # noqa: B902
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
    ctn_dir: str = Field(default=DEFAULT_CTN_DIR)


class IndexerConfig(BaseModel):
    max_file_size_kb: int = Field(default=DEFAULT_MAX_FILE_SIZE_KB, ge=1)
    max_indexed_files: int = Field(default=DEFAULT_MAX_INDEXED_FILES, ge=1)
    max_workers: int = Field(default=DEFAULT_INDEX_WORKERS, ge=0)
    max_files: Optional[int] = Field(
        default=None, ge=1, description="Hard cap on files processed in a run"
    )
    ignore_patterns: list[str] = Field(
        default_factory=list, description="Extra ignore patterns"
    )
    ignore_files: list[str] | None = Field(
        default=DEFAULT_IGNORE_FILES,
        description="Ignore file names to load (None uses defaults)",
    )
    metrics_output: str | None = Field(
        default=DEFAULT_METRICS_OUTPUT,
        description="Optional path to write metrics JSON",
    )
    fail_on_warning: bool = Field(default=False)
    strict: bool = Field(
        default=False, description="Strict mode: treat parse warnings as errors"
    )


class FlagsConfig(BaseModel):
    fail_on_warning: bool = Field(default=False)
    strict: bool = Field(default=False)
    audit_log_enabled: bool = Field(
        default=True, description="Enable patch operation audit logging"
    )


class RulesConfig(BaseModel):
    enabled: bool = Field(default=DEFAULT_RULES_ENABLED)
    builtin_plugins: list[str] = Field(
        default_factory=lambda: list(DEFAULT_RULES_BUILTIN_PLUGINS)
    )
    disabled_rules: list[str] = Field(default_factory=list)
    custom_rules_path: str | None = Field(default=None)
    custom_rules_inline: list[dict[str, Any]] = Field(default_factory=list)
    strict_validation: bool = Field(default=False)
    cache_ttl: int = Field(default=DEFAULT_RULES_CACHE_TTL, ge=0)
    fail_on_rule_error: bool = Field(default=False)


class PluginsConfig(BaseModel):
    overrides: dict[str, dict[str, dict[str, Any]]] = Field(default_factory=dict)


class HooksConfig(BaseModel):
    enabled: bool = Field(default=True)
    include: bool = Field(default=True)


class BsgParallelConfig(BaseModel):
    enabled: bool = Field(default=True)
    max_workers: int = Field(default=16, ge=1, le=32)
    chunk_size: int = Field(default=50, ge=1)


class BsgIgnoreConfig(BaseModel):
    enabled: bool = Field(default=True)
    file: str = Field(default=".bathoignore")


class BsgCacheConfig(BaseModel):
    enabled: bool = Field(default=True)
    path: str = Field(default="~/.batho/ast_cache.db")
    max_size_mb: int = Field(default=1024, ge=1)
    ttl_days: int = Field(default=30, ge=1)


class BsgIncrementalConfig(BaseModel):
    enabled: bool = Field(default=True)
    fallback_to_full: bool = Field(default=True)
    auto_detect_git: bool = Field(default=True)


class BsgSymbolResolutionConfig(BaseModel):
    enabled: bool = Field(default=True)
    fuzzy_matching: bool = Field(default=False)
    cache_symbols: bool = Field(default=True)


class BsgSerializationConfig(BaseModel):
    method: str = Field(default="legacy")
    compression: bool = Field(default=False)
    batch_size: int = Field(default=1000, ge=1)

    @field_validator("method")
    @classmethod
    def _validate_method(cls, value: str) -> str:  # noqa: B902
        normalized = value.strip().lower()
        if normalized not in {"legacy", "streaming"}:
            return "legacy"
        return normalized


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
    snapshot_ttl_days: int = Field(
        default=DEFAULT_STORAGE_RETENTION_SNAPSHOT_DAYS, ge=1
    )
    patch_ttl_days: int = Field(default=DEFAULT_STORAGE_RETENTION_PATCH_DAYS, ge=1)
    metrics_ttl_days: int = Field(default=DEFAULT_STORAGE_RETENTION_METRICS_DAYS, ge=1)
    context_ttl_days: int = Field(default=DEFAULT_STORAGE_RETENTION_CONTEXT_DAYS, ge=1)
    max_snapshots: int = Field(default=DEFAULT_STORAGE_RETENTION_MAX_SNAPSHOTS, ge=1)
    max_patches: int = Field(default=DEFAULT_STORAGE_RETENTION_MAX_PATCHES, ge=1)


class BsgStorageConfig(BaseModel):
    enabled: bool = Field(default=True)
    backend: str = Field(default="sqlite")
    registry_path: str = Field(default=DEFAULT_STORAGE_REGISTRY_PATH)
    content_scope: str = Field(default="durable")
    strict_compatibility: bool = Field(default=True)
    cloud_sync_ready: bool = Field(default=True)
    track_content_ids: bool = Field(default=True)
    mmap_enabled: bool = Field(default=False)
    mmap_min_size_mb: int = Field(default=8, ge=1)
    retention: BsgStorageRetentionConfig = Field(
        default_factory=BsgStorageRetentionConfig
    )

    @field_validator("backend")
    @classmethod
    def _validate_backend(cls, value: str) -> str:  # noqa: B902
        normalized = value.strip().lower()
        if normalized not in {"sqlite"}:
            return "sqlite"
        return normalized

    @field_validator("content_scope")
    @classmethod
    def _validate_scope(cls, value: str) -> str:  # noqa: B902
        normalized = value.strip().lower()
        if normalized not in {"durable", "all"}:
            return "durable"
        return normalized


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


class Config(BaseModel):
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)
    indexer: IndexerConfig = Field(default_factory=IndexerConfig)
    patch: dict = Field(default_factory=dict)
    flags: FlagsConfig = Field(default_factory=FlagsConfig)
    rules: RulesConfig = Field(default_factory=RulesConfig)
    plugins: PluginsConfig = Field(default_factory=PluginsConfig)
    hooks: HooksConfig = Field(default_factory=HooksConfig)
    schemas: dict = Field(default_factory=dict)
    cloud_sync: CloudSyncConfig = Field(default_factory=CloudSyncConfig)
    bsg: BsgConfig = Field(default_factory=BsgConfig)

    @field_validator("logging")
    @classmethod
    def _normalize_log_level(cls, v: LoggingConfig) -> LoggingConfig:  # noqa: B902
        v.level = v.level.upper()
        return v


def _env(name: str, default: Optional[str] = None) -> Optional[str]:
    val = os.getenv(name, default)
    return val if val else default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (ValueError, TypeError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (ValueError, TypeError):
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


def _env_list(name: str) -> list[str] | None:
    raw = os.getenv(name)
    if raw is None:
        return None
    raw = raw.strip()
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def _load_config_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(path)
    if path.suffix.lower() in {".yaml", ".yml"}:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    raise ValueError(f"Unsupported config file format: {path.suffix}")


def _merge_config(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    merged = {**base}
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_config(merged[key], value)
        else:
            merged[key] = value
    return merged


def get_log_level() -> int:
    return get_config_cached()["logging"]["level"]


def get_build_info() -> dict[str, str]:
    """Expose package version/build info for CLI and metadata."""

    try:
        version = importlib.metadata.version("batho")
    except importlib.metadata.PackageNotFoundError:
        version = _env("BATHO_VERSION", "0.1.0") or "0.1.0"
    build = _env("BATHO_BUILD", "") or ""
    return {"version": version, "build": build}


def get_config() -> Dict[str, Any]:
    """Return validated config as a plain dict with batho.yaml resolved from cwd."""
    return get_config_with_root(Path.cwd())


def get_log_level() -> int:
    return get_config_cached()["logging"]["level"]


def get_build_info() -> dict[str, str]:
    """Expose package version/build info for CLI and metadata."""

    try:
        version = importlib.metadata.version("batho")
    except importlib.metadata.PackageNotFoundError:
        version = _env("BATHO_VERSION", "0.1.0") or "0.1.0"
    build = _env("BATHO_BUILD", "") or ""
    return {"version": version, "build": build}


@lru_cache(maxsize=None)
def get_config_cached() -> Dict[str, Any]:
    """Get config with batho.yaml resolved relative to current working directory."""
    return get_config_with_root(Path.cwd())


@lru_cache(maxsize=None)
def get_config_cached_for_root(root_dir: Path) -> Dict[str, Any]:
    """Get config with batho.yaml resolved relative to target root directory."""
    return get_config_with_root(root_dir)


def get_config_with_root(root_dir: Path) -> Dict[str, Any]:
    """Return validated config as a plain dict with batho.yaml resolved from root_dir."""

    base_cfg: Dict[str, Any] = {
        "logging": {
            "level": DEFAULT_LOG_LEVEL,
            "json_format": None,
            "quiet": False,
            "file": None,
            "format": "%(message)s",
        },
        "paths": {"ctn_dir": DEFAULT_CTN_DIR},
        "indexer": {
            "max_file_size_kb": DEFAULT_MAX_FILE_SIZE_KB,
            "max_indexed_files": DEFAULT_MAX_INDEXED_FILES,
            "max_workers": DEFAULT_INDEX_WORKERS,
            "max_files": None,
            "ignore_patterns": [],
            "ignore_files": DEFAULT_IGNORE_FILES,
            "metrics_output": DEFAULT_METRICS_OUTPUT,
            "fail_on_warning": False,
            "strict": False,
        },
        "patch": {
            "timeout_seconds": DEFAULT_PATCH_TIMEOUT_SECONDS,
            "max_changes": DEFAULT_MAX_PATCH_CHANGES,
            "audit_log_path": ".ctn/patch_audit.log",
            "history_days": DEFAULT_PATCH_HISTORY_DAYS,
            "max_count": DEFAULT_PATCH_COUNT,
            "cleanup_on_startup": False,
        },
        "flags": {"fail_on_warning": False, "strict": False, "audit_log_enabled": True},
        "rules": {
            "enabled": DEFAULT_RULES_ENABLED,
            "builtin_plugins": list(DEFAULT_RULES_BUILTIN_PLUGINS),
            "disabled_rules": [],
            "custom_rules_path": None,
            "custom_rules_inline": [],
            "strict_validation": False,
            "cache_ttl": DEFAULT_RULES_CACHE_TTL,
            "fail_on_rule_error": False,
        },
        "plugins": {
            "overrides": {},
        },
        "hooks": {
            "enabled": True,
            "include": True,
        },
        "schemas": {
            "graph": GRAPH_SCHEMA_VERSION,
            "bsg": BSG_SCHEMA_VERSION,
            "snapshot": SNAPSHOT_SCHEMA_VERSION,
            "index_metadata": INDEX_METADATA_SCHEMA_VERSION,
            "file_cache": FILE_CACHE_SCHEMA_VERSION,
        },
        "cloud_sync": {
            "enabled": False,
            "endpoint": "",
            "api_key": "",
            "organization_id": "",
            "project_id": "",
            "timeout_seconds": 300,
            "max_retries": 3,
            "batch_size": 10,
        },
        "bsg": {
            "parallel": {
                "enabled": True,
                "max_workers": 16,
                "chunk_size": 50,
            },
            "ignore": {
                "enabled": True,
                "file": ".bathoignore",
            },
            "cache": {
                "enabled": True,
                "path": "~/.batho/ast_cache.db",
                "max_size_mb": 1024,
                "ttl_days": 30,
            },
            "incremental": {
                "enabled": True,
                "fallback_to_full": True,
                "auto_detect_git": True,
            },
            "symbol_resolution": {
                "enabled": True,
                "fuzzy_matching": False,
                "cache_symbols": True,
            },
            "serialization": {
                "method": "legacy",
                "compression": False,
                "batch_size": 1000,
            },
            "parsing": {
                "error_recovery": True,
                "partial_parsing": False,
                "max_file_size_mb": 10,
                "skip_comments": False,
            },
            "query": {
                "enabled": True,
                "index_on_write": True,
                "cache_enabled": True,
                "cache_size": 256,
                "default_limit": 200,
                "query_timeout_ms": 5000,
            },
            "storage": {
                "enabled": True,
                "backend": "sqlite",
                "registry_path": DEFAULT_STORAGE_REGISTRY_PATH,
                "content_scope": "durable",
                "strict_compatibility": True,
                "cloud_sync_ready": True,
                "track_content_ids": True,
                "mmap_enabled": False,
                "mmap_min_size_mb": 8,
                "retention": {
                    "enabled": True,
                    "snapshot_ttl_days": DEFAULT_STORAGE_RETENTION_SNAPSHOT_DAYS,
                    "patch_ttl_days": DEFAULT_STORAGE_RETENTION_PATCH_DAYS,
                    "metrics_ttl_days": DEFAULT_STORAGE_RETENTION_METRICS_DAYS,
                    "context_ttl_days": DEFAULT_STORAGE_RETENTION_CONTEXT_DAYS,
                    "max_snapshots": DEFAULT_STORAGE_RETENTION_MAX_SNAPSHOTS,
                    "max_patches": DEFAULT_STORAGE_RETENTION_MAX_PATCHES,
                },
            },
        },
    }

    # Root config override from ./batho.yaml only
    cfg_path = Path(DEFAULT_ROOT_CONFIG_FILE)
    if cfg_path:
        try:
            file_cfg = _load_config_file(cfg_path)
            base_cfg = _merge_config(base_cfg, file_cfg)
        except Exception:
            pass  # fall back to defaults + env overrides

    # Env overrides (compatible with previous behavior)
    base_cfg["logging"]["level"] = (
        _env("BATHO_LOG_LEVEL", base_cfg["logging"]["level"])
        or base_cfg["logging"]["level"]
    )
    base_cfg["logging"]["quiet"] = _env_bool(
        "BATHO_LOG_QUIET", base_cfg["logging"].get("quiet", False)
    )
    env_log_json = os.getenv("BATHO_LOG_JSON")
    if env_log_json is not None:
        base_cfg["logging"]["json_format"] = env_log_json.lower() in {
            "1",
            "true",
            "yes",
        }
    env_log_file = _env("BATHO_LOG_FILE")
    if env_log_file is not None:
        base_cfg["logging"]["file"] = env_log_file
    base_cfg["paths"]["ctn_dir"] = (
        _env("BATHO_CTN_DIR", base_cfg["paths"]["ctn_dir"])
        or base_cfg["paths"]["ctn_dir"]
    )
    base_cfg["indexer"]["max_file_size_kb"] = _env_int(
        "BATHO_MAX_FILE_SIZE_KB", base_cfg["indexer"]["max_file_size_kb"]
    )
    base_cfg["indexer"]["max_indexed_files"] = _env_int(
        "BATHO_MAX_INDEXED_FILES", base_cfg["indexer"]["max_indexed_files"]
    )
    base_cfg["indexer"]["max_workers"] = _env_int(
        "BATHO_INDEX_WORKERS", base_cfg["indexer"]["max_workers"]
    )
    env_ignore_patterns = _env_list("BATHO_IGNORE_PATTERNS")
    if env_ignore_patterns is not None:
        base_cfg["indexer"]["ignore_patterns"] = env_ignore_patterns
    env_ignore_files = _env_list("BATHO_IGNORE_FILES")
    if env_ignore_files is not None:
        base_cfg["indexer"]["ignore_files"] = env_ignore_files
    env_metrics_output = _env("BATHO_METRICS_OUTPUT")
    if env_metrics_output is not None:
        base_cfg["indexer"]["metrics_output"] = env_metrics_output

    # Rules overrides
    base_cfg["rules"]["enabled"] = _env_bool(
        "BATHO_RULES_ENABLED", base_cfg["rules"]["enabled"]
    )
    env_builtin_plugins = _env_list("BATHO_RULES_BUILTIN_PLUGINS")
    if env_builtin_plugins is not None:
        base_cfg["rules"]["builtin_plugins"] = env_builtin_plugins
    env_disabled_rules = _env_list("BATHO_RULES_DISABLED_RULES")
    if env_disabled_rules is not None:
        base_cfg["rules"]["disabled_rules"] = env_disabled_rules
    env_custom_rules_path = _env("BATHO_RULES_CUSTOM_RULES_PATH")
    if env_custom_rules_path is not None:
        base_cfg["rules"]["custom_rules_path"] = env_custom_rules_path
    base_cfg["rules"]["strict_validation"] = _env_bool(
        "BATHO_RULES_STRICT_VALIDATION", base_cfg["rules"]["strict_validation"]
    )
    base_cfg["rules"]["fail_on_rule_error"] = _env_bool(
        "BATHO_RULES_FAIL_ON_RULE_ERROR", base_cfg["rules"]["fail_on_rule_error"]
    )
    base_cfg["rules"]["cache_ttl"] = _env_int(
        "BATHO_RULES_CACHE_TTL", base_cfg["rules"]["cache_ttl"]
    )

    # Strict/fail-on-warning flags can be set at either indexer.* or flags.* (keep compatibility)
    env_fail_on_warning = os.getenv("BATHO_FAIL_ON_WARNING")
    env_strict = os.getenv("BATHO_STRICT")
    if env_fail_on_warning is not None:
        base_cfg["indexer"]["fail_on_warning"] = env_fail_on_warning.lower() in {
            "1",
            "true",
            "yes",
        }
    if env_strict is not None:
        base_cfg["indexer"]["strict"] = env_strict.lower() in {"1", "true", "yes"}
    base_cfg["flags"]["fail_on_warning"] = base_cfg["indexer"].get(
        "fail_on_warning", False
    )
    base_cfg["flags"]["strict"] = base_cfg["indexer"].get("strict", False)
    base_cfg["flags"]["audit_log_enabled"] = _env(
        "BATHO_AUDIT_LOG_ENABLED", "true"
    ).lower() in {"1", "true", "yes"}
    base_cfg["patch"]["timeout_seconds"] = _env_int(
        "BATHO_PATCH_TIMEOUT_SECONDS", base_cfg["patch"]["timeout_seconds"]
    )
    base_cfg["patch"]["max_changes"] = _env_int(
        "BATHO_MAX_PATCH_CHANGES", base_cfg["patch"]["max_changes"]
    )
    base_cfg["patch"]["history_days"] = _env_int(
        "BATHO_PATCH_HISTORY_DAYS", base_cfg["patch"]["history_days"]
    )
    base_cfg["patch"]["max_count"] = _env_int(
        "BATHO_PATCH_COUNT", base_cfg["patch"]["max_count"]
    )
    base_cfg["patch"]["cleanup_on_startup"] = _env(
        "BATHO_PATCH_CLEANUP_ON_STARTUP", "false"
    ).lower() in {"1", "true", "yes"}
    env_audit_log_path = _env("BATHO_PATCH_AUDIT_LOG_PATH")
    if env_audit_log_path:
        base_cfg["patch"]["audit_log_path"] = env_audit_log_path

    # Cloud sync configuration environment variables
    base_cfg["cloud_sync"]["enabled"] = _env_bool(
        "BATHO_CLOUD_SYNC_ENABLED", base_cfg["cloud_sync"]["enabled"]
    )
    env_cloud_endpoint = _env("BATHO_CLOUD_ENDPOINT")
    if env_cloud_endpoint is not None:
        base_cfg["cloud_sync"]["endpoint"] = env_cloud_endpoint
    env_cloud_api_key = _env("BATHO_CLOUD_API_KEY")
    if env_cloud_api_key is not None:
        base_cfg["cloud_sync"]["api_key"] = env_cloud_api_key
    env_cloud_org_id = _env("BATHO_CLOUD_ORG_ID")
    if env_cloud_org_id is not None:
        base_cfg["cloud_sync"]["organization_id"] = env_cloud_org_id
    env_cloud_project_id = _env("BATHO_CLOUD_PROJECT_ID")
    if env_cloud_project_id is not None:
        base_cfg["cloud_sync"]["project_id"] = env_cloud_project_id
    base_cfg["cloud_sync"]["timeout_seconds"] = _env_int(
        "BATHO_CLOUD_TIMEOUT_SECONDS", base_cfg["cloud_sync"]["timeout_seconds"]
    )
    base_cfg["cloud_sync"]["max_retries"] = _env_int(
        "BATHO_CLOUD_MAX_RETRIES", base_cfg["cloud_sync"]["max_retries"]
    )
    base_cfg["cloud_sync"]["batch_size"] = _env_int(
        "BATHO_CLOUD_BATCH_SIZE", base_cfg["cloud_sync"]["batch_size"]
    )

    # BSG configuration environment variables
    base_cfg["bsg"]["parallel"]["enabled"] = _env_bool(
        "BATHO_BSG_PARALLEL_ENABLED", base_cfg["bsg"]["parallel"]["enabled"]
    )
    base_cfg["bsg"]["parallel"]["max_workers"] = _env_int(
        "BATHO_BSG_MAX_WORKERS", base_cfg["bsg"]["parallel"]["max_workers"]
    )
    base_cfg["bsg"]["parallel"]["chunk_size"] = _env_int(
        "BATHO_BSG_CHUNK_SIZE", base_cfg["bsg"]["parallel"]["chunk_size"]
    )
    base_cfg["bsg"]["ignore"]["enabled"] = _env_bool(
        "BATHO_BSG_IGNORE_ENABLED", base_cfg["bsg"]["ignore"]["enabled"]
    )
    env_bathoignore_file = _env("BATHO_BSG_IGNORE_FILE")
    if env_bathoignore_file:
        base_cfg["bsg"]["ignore"]["file"] = env_bathoignore_file
    base_cfg["bsg"]["cache"]["enabled"] = _env_bool(
        "BATHO_BSG_CACHE_ENABLED", base_cfg["bsg"]["cache"]["enabled"]
    )
    env_cache_path = _env("BATHO_BSG_CACHE_PATH")
    if env_cache_path:
        base_cfg["bsg"]["cache"]["path"] = env_cache_path
    base_cfg["bsg"]["cache"]["max_size_mb"] = _env_int(
        "BATHO_BSG_CACHE_MAX_SIZE_MB", base_cfg["bsg"]["cache"]["max_size_mb"]
    )
    base_cfg["bsg"]["cache"]["ttl_days"] = _env_int(
        "BATHO_BSG_CACHE_TTL_DAYS", base_cfg["bsg"]["cache"]["ttl_days"]
    )
    base_cfg["bsg"]["incremental"]["enabled"] = _env_bool(
        "BATHO_BSG_INCREMENTAL_ENABLED",
        base_cfg["bsg"]["incremental"]["enabled"],
    )
    base_cfg["bsg"]["incremental"]["fallback_to_full"] = _env_bool(
        "BATHO_BSG_INCREMENTAL_FALLBACK_TO_FULL",
        base_cfg["bsg"]["incremental"]["fallback_to_full"],
    )
    base_cfg["bsg"]["incremental"]["auto_detect_git"] = _env_bool(
        "BATHO_BSG_INCREMENTAL_AUTO_DETECT_GIT",
        base_cfg["bsg"]["incremental"]["auto_detect_git"],
    )
    base_cfg["bsg"]["symbol_resolution"]["enabled"] = _env_bool(
        "BATHO_BSG_SYMBOL_RESOLUTION_ENABLED",
        base_cfg["bsg"]["symbol_resolution"]["enabled"],
    )
    base_cfg["bsg"]["symbol_resolution"]["fuzzy_matching"] = _env_bool(
        "BATHO_BSG_SYMBOL_RESOLUTION_FUZZY",
        base_cfg["bsg"]["symbol_resolution"]["fuzzy_matching"],
    )
    base_cfg["bsg"]["symbol_resolution"]["cache_symbols"] = _env_bool(
        "BATHO_BSG_SYMBOL_RESOLUTION_CACHE_SYMBOLS",
        base_cfg["bsg"]["symbol_resolution"]["cache_symbols"],
    )
    env_serialization_method = _env("BATHO_BSG_SERIALIZATION_METHOD")
    if env_serialization_method:
        base_cfg["bsg"]["serialization"]["method"] = env_serialization_method
    base_cfg["bsg"]["serialization"]["compression"] = _env_bool(
        "BATHO_BSG_SERIALIZATION_COMPRESSION",
        base_cfg["bsg"]["serialization"]["compression"],
    )
    base_cfg["bsg"]["serialization"]["batch_size"] = _env_int(
        "BATHO_BSG_SERIALIZATION_BATCH_SIZE",
        base_cfg["bsg"]["serialization"]["batch_size"],
    )
    base_cfg["bsg"]["parsing"]["error_recovery"] = _env_bool(
        "BATHO_BSG_PARSING_ERROR_RECOVERY",
        base_cfg["bsg"]["parsing"]["error_recovery"],
    )
    base_cfg["bsg"]["parsing"]["partial_parsing"] = _env_bool(
        "BATHO_BSG_PARSING_PARTIAL",
        base_cfg["bsg"]["parsing"]["partial_parsing"],
    )
    base_cfg["bsg"]["parsing"]["max_file_size_mb"] = _env_int(
        "BATHO_BSG_PARSING_MAX_FILE_SIZE_MB",
        base_cfg["bsg"]["parsing"]["max_file_size_mb"],
    )
    base_cfg["bsg"]["parsing"]["skip_comments"] = _env_bool(
        "BATHO_BSG_PARSING_SKIP_COMMENTS",
        base_cfg["bsg"]["parsing"]["skip_comments"],
    )
    base_cfg["bsg"]["query"]["enabled"] = _env_bool(
        "BATHO_BSG_QUERY_ENABLED",
        base_cfg["bsg"]["query"]["enabled"],
    )
    base_cfg["bsg"]["query"]["index_on_write"] = _env_bool(
        "BATHO_BSG_QUERY_INDEX_ON_WRITE",
        base_cfg["bsg"]["query"]["index_on_write"],
    )
    base_cfg["bsg"]["query"]["cache_enabled"] = _env_bool(
        "BATHO_BSG_QUERY_CACHE_ENABLED",
        base_cfg["bsg"]["query"]["cache_enabled"],
    )
    base_cfg["bsg"]["query"]["cache_size"] = _env_int(
        "BATHO_BSG_QUERY_CACHE_SIZE",
        base_cfg["bsg"]["query"]["cache_size"],
    )
    base_cfg["bsg"]["query"]["default_limit"] = _env_int(
        "BATHO_BSG_QUERY_DEFAULT_LIMIT",
        base_cfg["bsg"]["query"]["default_limit"],
    )
    base_cfg["bsg"]["query"]["query_timeout_ms"] = _env_int(
        "BATHO_BSG_QUERY_TIMEOUT_MS",
        base_cfg["bsg"]["query"]["query_timeout_ms"],
    )
    base_cfg["bsg"]["storage"]["enabled"] = _env_bool(
        "BATHO_BSG_STORAGE_ENABLED",
        base_cfg["bsg"]["storage"]["enabled"],
    )
    env_storage_backend = _env("BATHO_BSG_STORAGE_BACKEND")
    if env_storage_backend:
        base_cfg["bsg"]["storage"]["backend"] = env_storage_backend
    env_storage_registry_path = _env("BATHO_BSG_STORAGE_REGISTRY_PATH")
    if env_storage_registry_path:
        base_cfg["bsg"]["storage"]["registry_path"] = env_storage_registry_path
    env_storage_scope = _env("BATHO_BSG_STORAGE_CONTENT_SCOPE")
    if env_storage_scope:
        base_cfg["bsg"]["storage"]["content_scope"] = env_storage_scope
    base_cfg["bsg"]["storage"]["strict_compatibility"] = _env_bool(
        "BATHO_BSG_STORAGE_STRICT_COMPATIBILITY",
        base_cfg["bsg"]["storage"]["strict_compatibility"],
    )
    base_cfg["bsg"]["storage"]["cloud_sync_ready"] = _env_bool(
        "BATHO_BSG_STORAGE_CLOUD_SYNC_READY",
        base_cfg["bsg"]["storage"]["cloud_sync_ready"],
    )
    base_cfg["bsg"]["storage"]["track_content_ids"] = _env_bool(
        "BATHO_BSG_STORAGE_TRACK_CONTENT_IDS",
        base_cfg["bsg"]["storage"]["track_content_ids"],
    )
    base_cfg["bsg"]["storage"]["mmap_enabled"] = _env_bool(
        "BATHO_BSG_STORAGE_MMAP_ENABLED",
        base_cfg["bsg"]["storage"]["mmap_enabled"],
    )
    base_cfg["bsg"]["storage"]["mmap_min_size_mb"] = _env_int(
        "BATHO_BSG_STORAGE_MMAP_MIN_SIZE_MB",
        base_cfg["bsg"]["storage"]["mmap_min_size_mb"],
    )
    base_cfg["bsg"]["storage"]["retention"]["enabled"] = _env_bool(
        "BATHO_BSG_STORAGE_RETENTION_ENABLED",
        base_cfg["bsg"]["storage"]["retention"]["enabled"],
    )
    base_cfg["bsg"]["storage"]["retention"]["snapshot_ttl_days"] = _env_int(
        "BATHO_BSG_STORAGE_RETENTION_SNAPSHOT_TTL_DAYS",
        base_cfg["bsg"]["storage"]["retention"]["snapshot_ttl_days"],
    )
    base_cfg["bsg"]["storage"]["retention"]["patch_ttl_days"] = _env_int(
        "BATHO_BSG_STORAGE_RETENTION_PATCH_TTL_DAYS",
        base_cfg["bsg"]["storage"]["retention"]["patch_ttl_days"],
    )
    base_cfg["bsg"]["storage"]["retention"]["metrics_ttl_days"] = _env_int(
        "BATHO_BSG_STORAGE_RETENTION_METRICS_TTL_DAYS",
        base_cfg["bsg"]["storage"]["retention"]["metrics_ttl_days"],
    )
    base_cfg["bsg"]["storage"]["retention"]["context_ttl_days"] = _env_int(
        "BATHO_BSG_STORAGE_RETENTION_CONTEXT_TTL_DAYS",
        base_cfg["bsg"]["storage"]["retention"]["context_ttl_days"],
    )
    base_cfg["bsg"]["storage"]["retention"]["max_snapshots"] = _env_int(
        "BATHO_BSG_STORAGE_RETENTION_MAX_SNAPSHOTS",
        base_cfg["bsg"]["storage"]["retention"]["max_snapshots"],
    )
    base_cfg["bsg"]["storage"]["retention"]["max_patches"] = _env_int(
        "BATHO_BSG_STORAGE_RETENTION_MAX_PATCHES",
        base_cfg["bsg"]["storage"]["retention"]["max_patches"],
    )

    try:
        cfg = Config.model_validate(base_cfg)
    except ValidationError:
        cfg = Config()  # fall back to safe defaults

    cfg_dict = cfg.model_dump()
    cfg_dict["logging"]["level"] = cfg.logging.std_level
    # Provide flat schema helpers for legacy callers
    schemas = cfg_dict.get("schemas", {})
    cfg_dict["graph_schema_version"] = schemas.get("graph", GRAPH_SCHEMA_VERSION)
    cfg_dict["bsg_schema_version"] = schemas.get("bsg", BSG_SCHEMA_VERSION)
    cfg_dict["snapshot_schema_version"] = schemas.get(
        "snapshot", SNAPSHOT_SCHEMA_VERSION
    )
    cfg_dict["index_metadata_schema_version"] = schemas.get(
        "index_metadata", INDEX_METADATA_SCHEMA_VERSION
    )
    cfg_dict["file_cache_schema_version"] = schemas.get(
        "file_cache", FILE_CACHE_SCHEMA_VERSION
    )
    return cfg_dict


@lru_cache(maxsize=None)
def get_config_cached() -> Dict[str, Any]:
    """Get config with batho.yaml resolved relative to current working directory."""
    return get_config_with_root(Path.cwd())


@lru_cache(maxsize=None)
def get_config_cached_for_root(root_dir: Path) -> Dict[str, Any]:
    """Get config with batho.yaml resolved relative to target root directory."""
    return get_config_with_root(root_dir)


def reload_config() -> Dict[str, Any]:
    get_config_cached.cache_clear()
    get_config_cached_for_root.cache_clear()
    return get_config_cached()


def get_default_batho_yaml_content() -> str:
    """Return default batho.yaml content for auto-creation."""
    return """# Batho configuration
# Auto-generated default config. Edit as needed for your project.

logging:
  level: INFO
  json_format: null
  quiet: false
  file: null
  format: "%(message)s"

paths:
  ctn_dir: .ctn

indexer:
  max_file_size_kb: 500
  max_indexed_files: 200000
  max_workers: 0
  max_files: null
  ignore_patterns: []
  ignore_files: null
  metrics_output: .ctn/metrics.json
  fail_on_warning: false
  strict: false

patch:
  timeout_seconds: 300
  max_changes: 10000
  audit_log_path: .ctn/patch_audit.log
  history_days: 90
  max_count: 1000
  cleanup_on_startup: false

flags:
  fail_on_warning: false
  strict: false
  audit_log_enabled: true

rules:
  enabled: false
  builtin_plugins:
    - bsg_core
    - bsg_silent_failure_catcher
    - bsg_dependency_blast_radius
    - bsg_resource_leak_preventer
    - bsg_nplus1_query_catcher
    - bsg_iac_drift_sentinel
    - bsg_schema_migration_enforcer
    - bsg_api_contract_guardian
    - bsg_hardcoded_secret_catcher
    - bsg_auth_boundary_shield
  disabled_rules: []
  custom_rules_path: null
  custom_rules_inline: []
  strict_validation: false
  cache_ttl: 3600
  fail_on_rule_error: false

plugins:
  overrides: {}

schemas:
  graph: graph.v1
  bsg: bsg.v1
  snapshot: snapshot.v1
  index_metadata: index-metadata.v1
  file_cache: file-cache.v1

cloud_sync:
  enabled: false
  endpoint: ""
  api_key: ""
  organization_id: ""
  project_id: ""
  timeout_seconds: 300
  max_retries: 3
  batch_size: 10

bsg:
  parallel:
    enabled: true
    max_workers: 16
    chunk_size: 50
  ignore:
    enabled: true
    file: .bathoignore
  cache:
    enabled: true
    path: ~/.batho/ast_cache.db
    max_size_mb: 1024
    ttl_days: 30
  incremental:
    enabled: true
    fallback_to_full: true
    auto_detect_git: true
  symbol_resolution:
    enabled: true
    fuzzy_matching: false
    cache_symbols: true
  serialization:
    method: legacy
    compression: false
    batch_size: 1000
  parsing:
    error_recovery: true
    partial_parsing: false
    max_file_size_mb: 10
    skip_comments: false
  query:
    enabled: true
    index_on_write: true
    cache_enabled: true
    cache_size: 256
    default_limit: 200
    query_timeout_ms: 5000
  storage:
    enabled: true
    backend: sqlite
    registry_path: .ctn/artifact_registry.db
    content_scope: durable
    strict_compatibility: true
    cloud_sync_ready: true
    track_content_ids: true
    mmap_enabled: false
    mmap_min_size_mb: 8
    retention:
      enabled: true
      snapshot_ttl_days: 90
      patch_ttl_days: 90
      metrics_ttl_days: 30
      context_ttl_days: 90
      max_snapshots: 500
      max_patches: 5000
"""
