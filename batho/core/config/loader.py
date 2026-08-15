"""Logic to load, merge, and cache Batho configuration."""

from __future__ import annotations

import contextvars
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from .models import Config

logger = None


def _get_logger():
    global logger
    if logger is None:
        from batho.utils.logging import get_logger
        logger = get_logger(__name__)
    return logger


_active_root: contextvars.ContextVar[Path | None] = contextvars.ContextVar(
    "_active_root", default=None
)


def set_active_root(root: Path) -> None:
    _active_root.set(root.resolve())
    _get_config_cached_for_root.cache_clear()  # Bust cache on root switch


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


def _merge_config(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = {**base}
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_config(merged[key], value)
        else:
            merged[key] = value
    return merged


def _safe_get_nested(d: Any, keys: list[str], default: Any) -> Any:
    curr = d
    for k in keys:
        if isinstance(curr, dict):
            curr = curr.get(k)
        else:
            return default
    return default if curr is None else curr


def _safe_set_nested(d: dict[str, Any], keys: list[str], val: Any) -> None:
    curr = d
    for k in keys[:-1]:
        if k not in curr or not isinstance(curr[k], dict):
            curr[k] = {}
        curr = curr[k]
    curr[keys[-1]] = val


def get_config_with_root(root_dir: Path, auto_create: bool = False) -> dict[str, Any]:
    """Return validated config as a plain dict, loading batho.yaml from root_dir.

    If batho.yaml does not exist and auto_create is True, it is created with
    default configuration options. Otherwise, the default config is returned
    without writing to disk.
    """
    base_cfg: dict[str, Any] = Config().model_dump()

    cfg_path = root_dir / "batho.yaml"

    if not cfg_path.exists() and auto_create:
        try:
            cfg_path.write_text(
                yaml.safe_dump(base_cfg, default_flow_style=False, sort_keys=False),
                encoding="utf-8",
            )
            _get_logger().info("config_created_default", config_file=str(cfg_path))
        except OSError as exc:
            _get_logger().warning(
                "config_create_failed",
                config_file=str(cfg_path),
                error=str(exc),
            )

    if cfg_path.exists():
        try:
            file_cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
            base_cfg = _merge_config(base_cfg, file_cfg)
        except yaml.YAMLError as exc:
            _get_logger().error(
                "config_yaml_parse_error",
                config_file=cfg_path.name,
                error=str(exc),
            )
            raise RuntimeError(
                f"Failed to parse YAML configuration file {cfg_path.name}: {exc}"
            ) from exc
        except OSError as exc:
            _get_logger().error(
                "config_file_read_error",
                config_file=cfg_path.name,
                error=str(exc),
            )
            raise RuntimeError(
                f"Failed to read configuration file {cfg_path.name}: {exc}"
            ) from exc

    # Logging overrides
    _safe_set_nested(
        base_cfg,
        ["logging", "level"],
        _env("BATHO_LOG_LEVEL", _safe_get_nested(base_cfg, ["logging", "level"], "ERROR"))
        or _safe_get_nested(base_cfg, ["logging", "level"], "ERROR"),
    )
    _safe_set_nested(
        base_cfg,
        ["logging", "quiet"],
        _env_bool("BATHO_LOG_QUIET", _safe_get_nested(base_cfg, ["logging", "quiet"], False)),
    )
    env_log_json = os.getenv("BATHO_LOG_JSON")
    if env_log_json is not None:
        _safe_set_nested(
            base_cfg,
            ["logging", "json_format"],
            env_log_json.lower() in {"1", "true", "yes"},
        )
    env_log_file = _env("BATHO_LOG_FILE")
    if env_log_file is not None:
        _safe_set_nested(base_cfg, ["logging", "file"], env_log_file)

    # Paths overrides
    env_artifact_dir = _env("BATHO_ARTIFACT_DIR")
    if env_artifact_dir is not None:
        _safe_set_nested(base_cfg, ["paths", "artifact_dir"], env_artifact_dir)

    # Indexer overrides
    _safe_set_nested(
        base_cfg,
        ["indexer", "max_file_size_kb"],
        _env_int("BATHO_MAX_FILE_SIZE_KB", _safe_get_nested(base_cfg, ["indexer", "max_file_size_kb"], 500)),
    )
    _safe_set_nested(
        base_cfg,
        ["indexer", "max_indexed_files"],
        _env_int("BATHO_MAX_INDEXED_FILES", _safe_get_nested(base_cfg, ["indexer", "max_indexed_files"], 200_000)),
    )
    _safe_set_nested(
        base_cfg,
        ["indexer", "max_workers"],
        _env_int("BATHO_INDEX_WORKERS", _safe_get_nested(base_cfg, ["indexer", "max_workers"], 0)),
    )
    env_ignore_patterns = _env_list("BATHO_IGNORE_PATTERNS")
    if env_ignore_patterns is not None:
        _safe_set_nested(base_cfg, ["indexer", "ignore_patterns"], env_ignore_patterns)
    env_ignore_files = _env_list("BATHO_IGNORE_FILES")
    if env_ignore_files is not None:
        _safe_set_nested(base_cfg, ["indexer", "ignore_files"], env_ignore_files)
    env_default_patterns_file = _env("BATHO_DEFAULT_PATTERNS_FILE")
    if env_default_patterns_file is not None:
        _safe_set_nested(base_cfg, ["indexer", "default_patterns_file"], env_default_patterns_file)

    # Graph overrides
    _safe_set_nested(
        base_cfg,
        ["graph", "cycle_detection", "enabled"],
        _env_bool("BATHO_GRAPH_CYCLE_DETECTION_ENABLED", _safe_get_nested(base_cfg, ["graph", "cycle_detection", "enabled"], True)),
    )
    _safe_set_nested(
        base_cfg,
        ["graph", "cycle_detection", "fatal"],
        _env_bool("BATHO_GRAPH_CYCLE_DETECTION_FATAL", _safe_get_nested(base_cfg, ["graph", "cycle_detection", "fatal"], False)),
    )
    _safe_set_nested(
        base_cfg,
        ["graph", "orphan_pruning", "enabled"],
        _env_bool("BATHO_GRAPH_ORPHAN_PRUNING_ENABLED", _safe_get_nested(base_cfg, ["graph", "orphan_pruning", "enabled"], True)),
    )
    _safe_set_nested(
        base_cfg,
        ["graph", "orphan_pruning", "keep_entry_points"],
        _env_bool("BATHO_GRAPH_ORPHAN_PRUNING_KEEP_ENTRY_POINTS", _safe_get_nested(base_cfg, ["graph", "orphan_pruning", "keep_entry_points"], True)),
    )
    _safe_set_nested(
        base_cfg,
        ["graph", "orphan_pruning", "keep_exports"],
        _env_bool("BATHO_GRAPH_ORPHAN_PRUNING_KEEP_EXPORTS", _safe_get_nested(base_cfg, ["graph", "orphan_pruning", "keep_exports"], True)),
    )

    # Graph backend overrides
    env_graph_backend = _env("BATHO_GRAPH_BACKEND")
    if env_graph_backend is not None:
        if env_graph_backend in ("auto", "in-memory", "arrow"):
            _safe_set_nested(base_cfg, ["graph", "backend", "backend"], env_graph_backend)
        else:
            # An invalid env value must NOT reach Pydantic validation: a
            # ValidationError here triggers full batho.yaml regeneration,
            # discarding all user settings over a one-time typo.
            _get_logger().warning(
                "invalid_graph_backend_env_ignored",
                value=env_graph_backend,
                valid=["auto", "in-memory", "arrow"],
            )
    _safe_set_nested(
        base_cfg,
        ["graph", "backend", "auto_threshold_files"],
        _env_int("BATHO_GRAPH_AUTO_THRESHOLD_FILES", _safe_get_nested(base_cfg, ["graph", "backend", "auto_threshold_files"], 500)),
    )
    _safe_set_nested(
        base_cfg,
        ["graph", "backend", "auto_threshold_entities"],
        _env_int("BATHO_GRAPH_AUTO_THRESHOLD_ENTITIES", _safe_get_nested(base_cfg, ["graph", "backend", "auto_threshold_entities"], 30_000)),
    )
    env_arrow_staging_dir = _env("BATHO_GRAPH_ARROW_STAGING_DIR")
    if env_arrow_staging_dir is not None:
        _safe_set_nested(base_cfg, ["graph", "backend", "arrow_staging_dir"], env_arrow_staging_dir)
    _safe_set_nested(
        base_cfg,
        ["graph", "backend", "arrow_flush_rows"],
        _env_int("BATHO_GRAPH_ARROW_FLUSH_ROWS", _safe_get_nested(base_cfg, ["graph", "backend", "arrow_flush_rows"], 5000)),
    )
    _safe_set_nested(
        base_cfg,
        ["graph", "backend", "arrow_flush_bytes_mb"],
        _env_float("BATHO_GRAPH_ARROW_FLUSH_BYTES_MB", _safe_get_nested(base_cfg, ["graph", "backend", "arrow_flush_bytes_mb"], 1.0)),
    )
    _safe_set_nested(
        base_cfg,
        ["graph", "backend", "arrow_recompact_delta_ratio"],
        _env_float("BATHO_GRAPH_ARROW_RECOMPACT_DELTA_RATIO", _safe_get_nested(base_cfg, ["graph", "backend", "arrow_recompact_delta_ratio"], 0.10)),
    )

    # Flags overrides
    env_fail_on_warning = os.getenv("BATHO_FAIL_ON_WARNING")
    env_strict = os.getenv("BATHO_STRICT")
    if env_fail_on_warning is not None:
        val = env_fail_on_warning.lower() in {"1", "true", "yes"}
        _safe_set_nested(base_cfg, ["indexer", "fail_on_warning"], val)
        _safe_set_nested(base_cfg, ["flags", "fail_on_warning"], val)
    if env_strict is not None:
        val = env_strict.lower() in {"1", "true", "yes"}
        _safe_set_nested(base_cfg, ["indexer", "strict"], val)
        _safe_set_nested(base_cfg, ["flags", "strict"], val)
    _safe_set_nested(
        base_cfg,
        ["flags", "audit_log_enabled"],
        _env_bool("BATHO_AUDIT_LOG_ENABLED", _safe_get_nested(base_cfg, ["flags", "audit_log_enabled"], True)),
    )

    # Rules overrides
    _safe_set_nested(
        base_cfg,
        ["rules", "enabled"],
        _env_bool("BATHO_RULES_ENABLED", _safe_get_nested(base_cfg, ["rules", "enabled"], True)),
    )
    env_builtin_plugins = _env_list("BATHO_RULES_BUILTIN_PLUGINS")
    if env_builtin_plugins is not None:
        _safe_set_nested(base_cfg, ["rules", "builtin_plugins"], env_builtin_plugins)
    env_disabled_rules = _env_list("BATHO_RULES_DISABLED_RULES")
    if env_disabled_rules is not None:
        _safe_set_nested(base_cfg, ["rules", "disabled_rules"], env_disabled_rules)
    env_custom_rules_path = _env("BATHO_RULES_CUSTOM_RULES_PATH")
    if env_custom_rules_path is not None:
        _safe_set_nested(base_cfg, ["rules", "custom_rules_path"], env_custom_rules_path)
    _safe_set_nested(
        base_cfg,
        ["rules", "strict_validation"],
        _env_bool("BATHO_RULES_STRICT_VALIDATION", _safe_get_nested(base_cfg, ["rules", "strict_validation"], False)),
    )
    _safe_set_nested(
        base_cfg,
        ["rules", "fail_on_rule_error"],
        _env_bool("BATHO_RULES_FAIL_ON_RULE_ERROR", _safe_get_nested(base_cfg, ["rules", "fail_on_rule_error"], False)),
    )
    _safe_set_nested(
        base_cfg,
        ["rules", "cache_ttl"],
        _env_int("BATHO_RULES_CACHE_TTL", _safe_get_nested(base_cfg, ["rules", "cache_ttl"], 3600)),
    )

    # Artifact blobs overrides (per-blob fine-grained flags)
    _safe_set_nested(
        base_cfg,
        ["artifact_blobs", "file_artifacts", "bsg_agent_view"],
        _env_bool("BATHO_ARTIFACT_BLOBS_BSG_AGENT_VIEW", _safe_get_nested(base_cfg, ["artifact_blobs", "file_artifacts", "bsg_agent_view"], True)),
    )
    _safe_set_nested(
        base_cfg,
        ["artifact_blobs", "file_artifacts", "bsg_storage_view"],
        _env_bool("BATHO_ARTIFACT_BLOBS_BSG_STORAGE_VIEW", _safe_get_nested(base_cfg, ["artifact_blobs", "file_artifacts", "bsg_storage_view"], True)),
    )
    _safe_set_nested(
        base_cfg,
        ["artifact_blobs", "file_artifacts", "bsg_rel_view"],
        _env_bool("BATHO_ARTIFACT_BLOBS_BSG_REL_VIEW", _safe_get_nested(base_cfg, ["artifact_blobs", "file_artifacts", "bsg_rel_view"], True)),
    )
    _safe_set_nested(
        base_cfg,
        ["artifact_blobs", "run_artifacts", "context_overview"],
        _env_bool("BATHO_ARTIFACT_BLOBS_CONTEXT_OVERVIEW", _safe_get_nested(base_cfg, ["artifact_blobs", "run_artifacts", "context_overview"], True)),
    )
    _safe_set_nested(
        base_cfg,
        ["artifact_blobs", "run_artifacts", "telemetry_metrics"],
        _env_bool("BATHO_ARTIFACT_BLOBS_TELEMETRY_METRICS", _safe_get_nested(base_cfg, ["artifact_blobs", "run_artifacts", "telemetry_metrics"], True)),
    )
    _safe_set_nested(
        base_cfg,
        ["artifact_blobs", "run_artifacts", "structural_metrics"],
        _env_bool("BATHO_ARTIFACT_BLOBS_STRUCTURAL_METRICS", _safe_get_nested(base_cfg, ["artifact_blobs", "run_artifacts", "structural_metrics"], True)),
    )
    _safe_set_nested(
        base_cfg,
        ["artifact_blobs", "run_artifacts", "security_audit"],
        _env_bool("BATHO_ARTIFACT_BLOBS_SECURITY_AUDIT", _safe_get_nested(base_cfg, ["artifact_blobs", "run_artifacts", "security_audit"], False)),
    )
    _safe_set_nested(
        base_cfg,
        ["artifact_blobs", "run_artifacts", "artifact_payload"],
        _env_bool("BATHO_ARTIFACT_BLOBS_ARTIFACT_PAYLOAD", _safe_get_nested(base_cfg, ["artifact_blobs", "run_artifacts", "artifact_payload"], True)),
    )
    _safe_set_nested(
        base_cfg,
        ["artifact_blobs", "run_artifacts", "delta_stats"],
        _env_bool("BATHO_ARTIFACT_BLOBS_DELTA_STATS", _safe_get_nested(base_cfg, ["artifact_blobs", "run_artifacts", "delta_stats"], True)),
    )

    # Memory overrides
    _safe_set_nested(
        base_cfg,
        ["memory", "warning_threshold_mb"],
        _env_float("BATHO_MEMORY_WARNING_THRESHOLD_MB", _safe_get_nested(base_cfg, ["memory", "warning_threshold_mb"], 800.0)),
    )
    _safe_set_nested(
        base_cfg,
        ["memory", "critical_threshold_mb"],
        _env_float("BATHO_MEMORY_CRITICAL_THRESHOLD_MB", _safe_get_nested(base_cfg, ["memory", "critical_threshold_mb"], 1500.0)),
    )
    _safe_set_nested(
        base_cfg,
        ["memory", "rss_flush_threshold_mb"],
        _env_float("BATHO_MEMORY_RSS_FLUSH_THRESHOLD_MB", _safe_get_nested(base_cfg, ["memory", "rss_flush_threshold_mb"], 1000.0)),
    )
    _safe_set_nested(
        base_cfg,
        ["memory", "max_per_worker_mb"],
        _env_float("BATHO_MEMORY_MAX_PER_WORKER_MB", _safe_get_nested(base_cfg, ["memory", "max_per_worker_mb"], 150.0)),
    )

    # Community detection overrides
    _safe_set_nested(
        base_cfg,
        ["community_detection", "enabled"],
        _env_bool("BATHO_COMMUNITY_DETECTION_ENABLED", _safe_get_nested(base_cfg, ["community_detection", "enabled"], True)),
    )
    _safe_set_nested(
        base_cfg,
        ["community_detection", "skip_threshold"],
        _env_int("BATHO_COMMUNITY_DETECTION_SKIP_THRESHOLD", _safe_get_nested(base_cfg, ["community_detection", "skip_threshold"], 200_000)),
    )
    _safe_set_nested(
        base_cfg,
        ["community_detection", "sample_threshold"],
        _env_int("BATHO_COMMUNITY_DETECTION_SAMPLE_THRESHOLD", _safe_get_nested(base_cfg, ["community_detection", "sample_threshold"], 100_000)),
    )

    # MCP overrides
    _safe_set_nested(
        base_cfg,
        ["mcp", "enabled"],
        _env_bool("BATHO_MCP_ENABLED", _safe_get_nested(base_cfg, ["mcp", "enabled"], True)),
    )
    env_mcp_tools_disabled = _env_list("BATHO_MCP_TOOLS_DISABLED")
    if env_mcp_tools_disabled is not None:
        _safe_set_nested(base_cfg, ["mcp", "tools", "disabled"], env_mcp_tools_disabled)
    env_mcp_tools_enabled = _env_list("BATHO_MCP_TOOLS_ENABLED")
    if env_mcp_tools_enabled is not None:
        _safe_set_nested(base_cfg, ["mcp", "tools", "enabled"], env_mcp_tools_enabled)

    # BSG overrides
    _safe_set_nested(
        base_cfg,
        ["bsg", "parallel", "enabled"],
        _env_bool("BATHO_BSG_PARALLEL_ENABLED", _safe_get_nested(base_cfg, ["bsg", "parallel", "enabled"], True)),
    )
    _safe_set_nested(
        base_cfg,
        ["bsg", "parallel", "max_workers"],
        _env_int("BATHO_BSG_MAX_WORKERS", _safe_get_nested(base_cfg, ["bsg", "parallel", "max_workers"], 16)),
    )
    _safe_set_nested(
        base_cfg,
        ["bsg", "parallel", "chunk_size"],
        _env_int("BATHO_BSG_CHUNK_SIZE", _safe_get_nested(base_cfg, ["bsg", "parallel", "chunk_size"], 50)),
    )
    _safe_set_nested(
        base_cfg,
        ["bsg", "cache", "enabled"],
        _env_bool("BATHO_BSG_CACHE_ENABLED", _safe_get_nested(base_cfg, ["bsg", "cache", "enabled"], True)),
    )
    _safe_set_nested(
        base_cfg,
        ["bsg", "cache", "max_size_mb"],
        _env_int("BATHO_BSG_CACHE_MAX_SIZE_MB", _safe_get_nested(base_cfg, ["bsg", "cache", "max_size_mb"], 1024)),
    )
    _safe_set_nested(
        base_cfg,
        ["bsg", "cache", "ttl_days"],
        _env_int("BATHO_BSG_CACHE_TTL_DAYS", _safe_get_nested(base_cfg, ["bsg", "cache", "ttl_days"], 30)),
    )
    _safe_set_nested(
        base_cfg,
        ["bsg", "symbol_resolution", "enabled"],
        _env_bool("BATHO_BSG_SYMBOL_RESOLUTION_ENABLED", _safe_get_nested(base_cfg, ["bsg", "symbol_resolution", "enabled"], True)),
    )
    _safe_set_nested(
        base_cfg,
        ["bsg", "symbol_resolution", "fuzzy_matching"],
        _env_bool("BATHO_BSG_SYMBOL_RESOLUTION_FUZZY", _safe_get_nested(base_cfg, ["bsg", "symbol_resolution", "fuzzy_matching"], False)),
    )
    _safe_set_nested(
        base_cfg,
        ["bsg", "symbol_resolution", "cache_symbols"],
        _env_bool("BATHO_BSG_SYMBOL_RESOLUTION_CACHE_SYMBOLS", _safe_get_nested(base_cfg, ["bsg", "symbol_resolution", "cache_symbols"], True)),
    )
    _safe_set_nested(
        base_cfg,
        ["bsg", "parsing", "error_recovery"],
        _env_bool("BATHO_BSG_PARSING_ERROR_RECOVERY", _safe_get_nested(base_cfg, ["bsg", "parsing", "error_recovery"], True)),
    )
    _safe_set_nested(
        base_cfg,
        ["bsg", "parsing", "skip_comments"],
        _env_bool("BATHO_BSG_PARSING_SKIP_COMMENTS", _safe_get_nested(base_cfg, ["bsg", "parsing", "skip_comments"], False)),
    )
    _safe_set_nested(
        base_cfg,
        ["bsg", "bidirectional", "enabled"],
        _env_bool("BATHO_BSG_BIDIRECTIONAL_ENABLED", _safe_get_nested(base_cfg, ["bsg", "bidirectional", "enabled"], True)),
    )
    _safe_set_nested(
        base_cfg,
        ["bsg", "bidirectional", "include_gaps"],
        _env_bool("BATHO_BSG_BIDIRECTIONAL_INCLUDE_GAPS", _safe_get_nested(base_cfg, ["bsg", "bidirectional", "include_gaps"], True)),
    )
    _safe_set_nested(
        base_cfg,
        ["bsg", "bidirectional", "verify_integrity"],
        _env_bool("BATHO_BSG_BIDIRECTIONAL_VERIFY_INTEGRITY", _safe_get_nested(base_cfg, ["bsg", "bidirectional", "verify_integrity"], False)),
    )
    _safe_set_nested(
        base_cfg,
        ["bsg", "bidirectional", "storage_view"],
        _env_bool("BATHO_BSG_BIDIRECTIONAL_STORAGE_VIEW", _safe_get_nested(base_cfg, ["bsg", "bidirectional", "storage_view"], False)),
    )

    try:
        cfg = Config.model_validate(base_cfg)
    except ValidationError as exc:
        _get_logger().warning(
            "config_validation_failed_regenerating",
            config_file=cfg_path.name,
            error=str(exc),
        )
        # No backward compatibility: regenerate with current defaults
        try:
            cfg = Config()
            if cfg_path.exists():
                try:
                    # Back up the invalid config file to prevent silent data destruction
                    backup_path = cfg_path.with_suffix(".yaml.bak")
                    import shutil
                    shutil.copyfile(cfg_path, backup_path)
                    _get_logger().warning(
                        "config_validation_failed_backup_created",
                        config_file=str(cfg_path),
                        backup_file=str(backup_path),
                    )
                    cfg_path.write_text(
                        yaml.safe_dump(cfg.model_dump(), default_flow_style=False, sort_keys=False),
                        encoding="utf-8",
                    )
                    _get_logger().info("config_regenerated", config_file=str(cfg_path))
                except OSError as write_exc:
                    _get_logger().warning(
                        "config_regenerate_failed",
                        config_file=str(cfg_path),
                        error=str(write_exc),
                    )
        except ValidationError:
            cfg = Config.model_construct()

    cfg_dict = cfg.model_dump()
    cfg_dict["logging"]["level"] = cfg.logging.std_level

    # Sanitize and validate paths configuration to prevent traversal attacks
    paths = cfg_dict.setdefault("paths", {})
    from batho.utils.path_sanitizer import PathSecurityError
    for path_key in ("artifact_dir", "cache_dir", "bsg_dir"):
        val = paths.get(path_key)
        if val:
            p = Path(val)
            if not p.is_absolute():
                p = root_dir / p
            resolved = p.resolve()
            try:
                resolved.relative_to(root_dir)
            except ValueError:
                raise PathSecurityError(f"Unsafe config path {path_key} escaping repository root: {val}")
            paths[path_key] = str(resolved)

    return cfg_dict


@lru_cache(maxsize=None)
def _get_config_cached_for_root(root_dir: Path, auto_create: bool = False) -> dict[str, Any]:
    return get_config_with_root(root_dir, auto_create=auto_create)


def get_config_cached(auto_create: bool = False) -> dict[str, Any]:
    return _get_config_cached_for_root(get_active_root(), auto_create)


def reload_config() -> dict[str, Any]:
    _get_config_cached_for_root.cache_clear()
    return get_config_cached()
