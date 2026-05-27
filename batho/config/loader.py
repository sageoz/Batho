"""Logic to load, merge, and cache Batho configuration."""

from __future__ import annotations

import contextvars
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from .models import Config, DEFAULT_DB_PATH


_active_root: contextvars.ContextVar[Path | None] = contextvars.ContextVar(
    "_active_root", default=None
)


def set_active_root(root: Path) -> None:
    _active_root.set(root.resolve())
    _get_config_cached_for_root.cache_clear()


def get_active_root() -> Path:
    return _active_root.get() or Path.cwd()


def _env(name: str, default: str | None = None) -> str | None:
    val = os.getenv(name, default)
    return val if val else default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
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


def _merge_config(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = {**base}
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_config(merged[key], value)
        else:
            merged[key] = value
    return merged


def get_config_with_root(root_dir: Path) -> dict[str, Any]:
    """Return validated config as a plain dict, loading batho.yaml from root_dir."""
    base_cfg: dict[str, Any] = Config().model_dump()

    cfg_path = root_dir / "batho.yaml"
    if cfg_path.exists():
        try:
            file_cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
            base_cfg = _merge_config(base_cfg, file_cfg)
        except (yaml.YAMLError, OSError):
            pass

    # Logging overrides
    base_cfg["logging"]["level"] = (
        _env("BATHO_LOG_LEVEL", base_cfg["logging"]["level"])
        or base_cfg["logging"]["level"]
    )
    base_cfg["logging"]["quiet"] = _env_bool(
        "BATHO_LOG_QUIET", base_cfg["logging"].get("quiet", False)
    )
    env_log_json = os.getenv("BATHO_LOG_JSON")
    if env_log_json is not None:
        base_cfg["logging"]["json_format"] = env_log_json.lower() in {"1", "true", "yes"}
    env_log_file = _env("BATHO_LOG_FILE")
    if env_log_file is not None:
        base_cfg["logging"]["file"] = env_log_file

    # Paths overrides
    base_cfg["paths"]["db_path"] = (
        _env("BATHO_DB_PATH", base_cfg["paths"]["db_path"])
        or base_cfg["paths"]["db_path"]
    )

    # Indexer overrides
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
    env_default_patterns_file = _env("BATHO_DEFAULT_PATTERNS_FILE")
    if env_default_patterns_file is not None:
        base_cfg["indexer"]["default_patterns_file"] = env_default_patterns_file

    # Patch overrides
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
    base_cfg["patch"]["cleanup_on_startup"] = _env_bool(
        "BATHO_PATCH_CLEANUP_ON_STARTUP", base_cfg["patch"]["cleanup_on_startup"]
    )

    # Flags overrides
    env_fail_on_warning = os.getenv("BATHO_FAIL_ON_WARNING")
    env_strict = os.getenv("BATHO_STRICT")
    if env_fail_on_warning is not None:
        val = env_fail_on_warning.lower() in {"1", "true", "yes"}
        base_cfg["indexer"]["fail_on_warning"] = val
        base_cfg["flags"]["fail_on_warning"] = val
    if env_strict is not None:
        val = env_strict.lower() in {"1", "true", "yes"}
        base_cfg["indexer"]["strict"] = val
        base_cfg["flags"]["strict"] = val
    base_cfg["flags"]["audit_log_enabled"] = _env_bool(
        "BATHO_AUDIT_LOG_ENABLED", base_cfg["flags"].get("audit_log_enabled", True)
    )

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

    # Artifact blobs overrides (per-blob fine-grained flags)
    ab = base_cfg["artifact_blobs"]
    ab["file_artifacts"]["bsg_agent_view"] = _env_bool(
        "BATHO_ARTIFACT_BLOBS_BSG_AGENT_VIEW",
        ab["file_artifacts"]["bsg_agent_view"],
    )
    ab["file_artifacts"]["bsg_storage_view"] = _env_bool(
        "BATHO_ARTIFACT_BLOBS_BSG_STORAGE_VIEW",
        ab["file_artifacts"]["bsg_storage_view"],
    )
    ab["file_artifacts"]["bsg_rel_view"] = _env_bool(
        "BATHO_ARTIFACT_BLOBS_BSG_REL_VIEW",
        ab["file_artifacts"]["bsg_rel_view"],
    )
    ab["run_artifacts"]["context_overview"] = _env_bool(
        "BATHO_ARTIFACT_BLOBS_CONTEXT_OVERVIEW",
        ab["run_artifacts"]["context_overview"],
    )
    ab["run_artifacts"]["telemetry_metrics"] = _env_bool(
        "BATHO_ARTIFACT_BLOBS_TELEMETRY_METRICS",
        ab["run_artifacts"]["telemetry_metrics"],
    )
    ab["run_artifacts"]["structural_metrics"] = _env_bool(
        "BATHO_ARTIFACT_BLOBS_STRUCTURAL_METRICS",
        ab["run_artifacts"]["structural_metrics"],
    )
    ab["run_artifacts"]["security_audit"] = _env_bool(
        "BATHO_ARTIFACT_BLOBS_SECURITY_AUDIT",
        ab["run_artifacts"]["security_audit"],
    )
    ab["run_artifacts"]["artifact_payload"] = _env_bool(
        "BATHO_ARTIFACT_BLOBS_ARTIFACT_PAYLOAD",
        ab["run_artifacts"]["artifact_payload"],
    )
    ab["run_artifacts"]["delta_stats"] = _env_bool(
        "BATHO_ARTIFACT_BLOBS_DELTA_STATS",
        ab["run_artifacts"]["delta_stats"],
    )

    # BSG overrides
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
    base_cfg["bsg"]["cache"]["enabled"] = _env_bool(
        "BATHO_BSG_CACHE_ENABLED", base_cfg["bsg"]["cache"]["enabled"]
    )
    base_cfg["bsg"]["cache"]["max_size_mb"] = _env_int(
        "BATHO_BSG_CACHE_MAX_SIZE_MB", base_cfg["bsg"]["cache"]["max_size_mb"]
    )
    base_cfg["bsg"]["cache"]["ttl_days"] = _env_int(
        "BATHO_BSG_CACHE_TTL_DAYS", base_cfg["bsg"]["cache"]["ttl_days"]
    )
    base_cfg["bsg"]["incremental"]["enabled"] = _env_bool(
        "BATHO_BSG_INCREMENTAL_ENABLED", base_cfg["bsg"]["incremental"]["enabled"]
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
        "BATHO_BSG_QUERY_ENABLED", base_cfg["bsg"]["query"]["enabled"]
    )
    base_cfg["bsg"]["query"]["index_on_write"] = _env_bool(
        "BATHO_BSG_QUERY_INDEX_ON_WRITE", base_cfg["bsg"]["query"]["index_on_write"]
    )
    base_cfg["bsg"]["query"]["cache_enabled"] = _env_bool(
        "BATHO_BSG_QUERY_CACHE_ENABLED", base_cfg["bsg"]["query"]["cache_enabled"]
    )
    base_cfg["bsg"]["query"]["cache_size"] = _env_int(
        "BATHO_BSG_QUERY_CACHE_SIZE", base_cfg["bsg"]["query"]["cache_size"]
    )
    base_cfg["bsg"]["query"]["default_limit"] = _env_int(
        "BATHO_BSG_QUERY_DEFAULT_LIMIT", base_cfg["bsg"]["query"]["default_limit"]
    )
    base_cfg["bsg"]["query"]["query_timeout_ms"] = _env_int(
        "BATHO_BSG_QUERY_TIMEOUT_MS", base_cfg["bsg"]["query"]["query_timeout_ms"]
    )
    base_cfg["bsg"]["storage"]["enabled"] = _env_bool(
        "BATHO_BSG_STORAGE_ENABLED", base_cfg["bsg"]["storage"]["enabled"]
    )
    env_storage_scope = _env("BATHO_BSG_STORAGE_CONTENT_SCOPE")
    if env_storage_scope:
        base_cfg["bsg"]["storage"]["content_scope"] = env_storage_scope
    base_cfg["bsg"]["storage"]["track_content_ids"] = _env_bool(
        "BATHO_BSG_STORAGE_TRACK_CONTENT_IDS",
        base_cfg["bsg"]["storage"]["track_content_ids"],
    )
    base_cfg["bsg"]["storage"]["busy_timeout_ms"] = _env_int(
        "BATHO_STORAGE_BUSY_TIMEOUT_MS",
        base_cfg["bsg"]["storage"]["busy_timeout_ms"],
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
    base_cfg["bsg"]["bidirectional"]["enabled"] = _env_bool(
        "BATHO_BSG_BIDIRECTIONAL_ENABLED",
        base_cfg["bsg"]["bidirectional"]["enabled"],
    )
    base_cfg["bsg"]["bidirectional"]["include_gaps"] = _env_bool(
        "BATHO_BSG_BIDIRECTIONAL_INCLUDE_GAPS",
        base_cfg["bsg"]["bidirectional"]["include_gaps"],
    )
    base_cfg["bsg"]["bidirectional"]["verify_integrity"] = _env_bool(
        "BATHO_BSG_BIDIRECTIONAL_VERIFY_INTEGRITY",
        base_cfg["bsg"]["bidirectional"]["verify_integrity"],
    )
    base_cfg["bsg"]["bidirectional"]["storage_view"] = _env_bool(
        "BATHO_BSG_BIDIRECTIONAL_STORAGE_VIEW",
        base_cfg["bsg"]["bidirectional"]["storage_view"],
    )

    try:
        cfg = Config.model_validate(base_cfg)
    except ValidationError:
        cfg = Config()

    cfg_dict = cfg.model_dump()
    cfg_dict["logging"]["level"] = cfg.logging.std_level
    return cfg_dict


@lru_cache(maxsize=None)
def _get_config_cached_for_root(root_dir: Path) -> dict[str, Any]:
    return get_config_with_root(root_dir)


def get_config_cached() -> dict[str, Any]:
    return _get_config_cached_for_root(get_active_root())


def reload_config() -> dict[str, Any]:
    _get_config_cached_for_root.cache_clear()
    return get_config_cached()


