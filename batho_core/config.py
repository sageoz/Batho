"""
Typed configuration and build info helpers for Batho core.

Features
- Pydantic-validated config with sane defaults.
- Optional config file override (JSON/YAML/TOML) via ``BATHO_CONFIG_FILE``.
- Env-variable overrides kept for compatibility.
- Strict/fail-on-warning flags for regulated environments.
- Schema identifiers for persisted artifacts.
"""

from __future__ import annotations

import importlib.metadata
import logging
import os
import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator

DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_CTN_DIR = ".ctn"
DEFAULT_MAX_FILE_SIZE_KB = 500
DEFAULT_MAX_INDEXED_FILES = 200000  # allow large repos
DEFAULT_INDEX_WORKERS = 0  # auto
DEFAULT_REPOMAP_BUDGET_TOKENS = 12000
DEFAULT_REPOMAP_BUDGET_RATIO = 0.8
DEFAULT_REPOMAP_BUDGET_MIN_TOKENS = 4000
DEFAULT_REPOMAP_BUDGET_MAX_TOKENS = 40000
DEFAULT_IGNORE_FILES: list[str] | None = None
DEFAULT_METRICS_OUTPUT: str | None = ".ctn/metrics.json"
DEFAULT_CONFIG_FILE_ENV = "BATHO_CONFIG_FILE"

GRAPH_SCHEMA_VERSION = "graph.v1"
REPOMAP_SCHEMA_VERSION = "repomap.v1"
SNAPSHOT_SCHEMA_VERSION = "snapshot.v1"
INDEX_METADATA_SCHEMA_VERSION = "index-metadata.v1"
FILE_CACHE_SCHEMA_VERSION = "file-cache.v1"


class LoggingConfig(BaseModel):
    level: str = Field(default=DEFAULT_LOG_LEVEL)
    json_format: Optional[bool] = Field(
        default=None, description="Force JSON logs when True, console when False"
    )

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


class PathsConfig(BaseModel):
    ctn_dir: str = Field(default=DEFAULT_CTN_DIR)


class IndexerConfig(BaseModel):
    max_file_size_kb: int = Field(default=DEFAULT_MAX_FILE_SIZE_KB, ge=1)
    max_indexed_files: int = Field(default=DEFAULT_MAX_INDEXED_FILES, ge=1)
    max_workers: int = Field(default=DEFAULT_INDEX_WORKERS, ge=0)
    max_files: Optional[int] = Field(
        default=None, ge=1, description="Hard cap on files processed in a run"
    )
    repomap_budget_tokens: int = Field(default=DEFAULT_REPOMAP_BUDGET_TOKENS, ge=0)
    repomap_budget_ratio: float = Field(default=DEFAULT_REPOMAP_BUDGET_RATIO, ge=0.0, le=1.0)
    repomap_budget_min_tokens: int = Field(default=DEFAULT_REPOMAP_BUDGET_MIN_TOKENS, ge=0)
    repomap_budget_max_tokens: int = Field(default=DEFAULT_REPOMAP_BUDGET_MAX_TOKENS, ge=0)
    ignore_patterns: list[str] = Field(default_factory=list, description="Extra ignore patterns")
    ignore_files: list[str] | None = Field(
        default=DEFAULT_IGNORE_FILES,
        description="Ignore file names to load (None uses defaults)",
    )
    metrics_output: str | None = Field(
        default=DEFAULT_METRICS_OUTPUT,
        description="Optional path to write metrics JSON",
    )
    fail_on_warning: bool = Field(default=False)
    strict: bool = Field(default=False, description="Strict mode: treat parse warnings as errors")


class FlagsConfig(BaseModel):
    fail_on_warning: bool = Field(default=False)
    strict: bool = Field(default=False)


class Config(BaseModel):
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)
    indexer: IndexerConfig = Field(default_factory=IndexerConfig)
    flags: FlagsConfig = Field(default_factory=FlagsConfig)

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
    if path.suffix.lower() == ".json":
        import json

        return json.loads(path.read_text(encoding="utf-8"))
    if path.suffix.lower() == ".toml":
        return tomllib.loads(path.read_text(encoding="utf-8"))
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


def get_config(config_file: str | None = None) -> Dict[str, Any]:
    """Return validated config as a plain dict (backward compatible)."""

    base_cfg: Dict[str, Any] = {
        "logging": {"level": DEFAULT_LOG_LEVEL, "json_format": None},
        "paths": {"ctn_dir": DEFAULT_CTN_DIR},
        "indexer": {
            "max_file_size_kb": DEFAULT_MAX_FILE_SIZE_KB,
            "max_indexed_files": DEFAULT_MAX_INDEXED_FILES,
            "max_workers": DEFAULT_INDEX_WORKERS,
            "max_files": None,
            "repomap_budget_tokens": DEFAULT_REPOMAP_BUDGET_TOKENS,
            "repomap_budget_ratio": DEFAULT_REPOMAP_BUDGET_RATIO,
            "repomap_budget_min_tokens": DEFAULT_REPOMAP_BUDGET_MIN_TOKENS,
            "repomap_budget_max_tokens": DEFAULT_REPOMAP_BUDGET_MAX_TOKENS,
            "ignore_patterns": [],  # Will be merged with actual patterns in ignore.py
            "ignore_files": DEFAULT_IGNORE_FILES,
            "metrics_output": DEFAULT_METRICS_OUTPUT,
            "fail_on_warning": False,
            "strict": False,
        },
        "flags": {"fail_on_warning": False, "strict": False},
        "schemas": {
            "graph": GRAPH_SCHEMA_VERSION,
            "repomap": REPOMAP_SCHEMA_VERSION,
            "snapshot": SNAPSHOT_SCHEMA_VERSION,
            "index_metadata": INDEX_METADATA_SCHEMA_VERSION,
            "file_cache": FILE_CACHE_SCHEMA_VERSION,
        },
    }

    # Config file override
    cfg_path_env = _env(DEFAULT_CONFIG_FILE_ENV)
    cfg_path = Path(config_file or cfg_path_env) if (config_file or cfg_path_env) else None
    if cfg_path:
        try:
            file_cfg = _load_config_file(cfg_path)
            base_cfg = _merge_config(base_cfg, file_cfg)
        except Exception:
            pass  # fall back to defaults + env overrides

    # Env overrides (compatible with previous behavior)
    base_cfg["logging"]["level"] = (
        _env("BATHO_LOG_LEVEL", base_cfg["logging"]["level"]) or base_cfg["logging"]["level"]
    )
    base_cfg["paths"]["ctn_dir"] = (
        _env("BATHO_CTN_DIR", base_cfg["paths"]["ctn_dir"]) or base_cfg["paths"]["ctn_dir"]
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
    base_cfg["indexer"]["repomap_budget_tokens"] = _env_int(
        "BATHO_REPOMAP_BUDGET_TOKENS", base_cfg["indexer"]["repomap_budget_tokens"]
    )
    base_cfg["indexer"]["repomap_budget_ratio"] = _env_float(
        "BATHO_REPOMAP_BUDGET_RATIO", base_cfg["indexer"]["repomap_budget_ratio"]
    )
    base_cfg["indexer"]["repomap_budget_min_tokens"] = _env_int(
        "BATHO_REPOMAP_BUDGET_MIN_TOKENS", base_cfg["indexer"]["repomap_budget_min_tokens"]
    )
    base_cfg["indexer"]["repomap_budget_max_tokens"] = _env_int(
        "BATHO_REPOMAP_BUDGET_MAX_TOKENS", base_cfg["indexer"]["repomap_budget_max_tokens"]
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

    # Strict/fail-on-warning flags can be set at either indexer.* or flags.* (keep compatibility)
    env_fail_on_warning = os.getenv("BATHO_FAIL_ON_WARNING")
    env_strict = os.getenv("BATHO_STRICT")
    if env_fail_on_warning is not None:
        base_cfg["indexer"]["fail_on_warning"] = env_fail_on_warning.lower() in {"1", "true", "yes"}
    if env_strict is not None:
        base_cfg["indexer"]["strict"] = env_strict.lower() in {"1", "true", "yes"}
    base_cfg["flags"]["fail_on_warning"] = base_cfg["indexer"].get("fail_on_warning", False)
    base_cfg["flags"]["strict"] = base_cfg["indexer"].get("strict", False)

    try:
        cfg = Config.model_validate(base_cfg)
    except ValidationError:
        cfg = Config()  # fall back to safe defaults

    cfg_dict = cfg.model_dump()
    cfg_dict["logging"]["level"] = cfg.logging.std_level
    # Provide flat schema helpers for legacy callers
    schemas = cfg_dict.get("schemas", {})
    cfg_dict["graph_schema_version"] = schemas.get("graph", GRAPH_SCHEMA_VERSION)
    cfg_dict["repomap_schema_version"] = schemas.get("repomap", REPOMAP_SCHEMA_VERSION)
    cfg_dict["snapshot_schema_version"] = schemas.get("snapshot", SNAPSHOT_SCHEMA_VERSION)
    cfg_dict["index_metadata_schema_version"] = schemas.get(
        "index_metadata", INDEX_METADATA_SCHEMA_VERSION
    )
    cfg_dict["file_cache_schema_version"] = schemas.get("file_cache", FILE_CACHE_SCHEMA_VERSION)
    return cfg_dict


@lru_cache(maxsize=None)
def get_config_cached(config_file: str | None = None) -> Dict[str, Any]:
    return get_config(config_file=config_file)


def reload_config(config_file: str | None = None) -> Dict[str, Any]:
    get_config_cached.cache_clear()
    return get_config_cached(config_file=config_file)
