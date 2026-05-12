"""Batho Core CLI (indexing, stats, invalidate).

- Index: builds code graph and bsg, writes JSON/MD outputs without LLM or UniversalMemory.
- Stats: show current index metadata.
- Invalidate: clear file cache to force next full parse.

Outputs (default):
- .ctn/<index_id>/graph.json       — Entities + relationships
- .ctn/<index_id>/bsg.json         — BSG structured data
- .ctn/<index_id>/files.md         — All files by category (single source of truth)
- .ctn/index.json                  — Index metadata (current and history)
"""

from __future__ import annotations

import argparse
import builtins as _builtins
import json
import os
import sys
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import batho as batho_api
from batho.config import (
    get_build_info,
    get_config_cached,
    get_config_cached_for_root,
    get_default_batho_yaml_content,
    reload_config,
)
from batho.context.bsg_map import BSGMap
from batho.context.codegraph import CodeGraphIndexer, InMemoryGraph
from batho.context.graph_cache import get_cached_graph_stats, load_cached_graph
from batho.context.incremental import GitDiffEntry
from batho.context.languages.detector import default_detector
from batho.context.languages.registry import get_extractor as registry_get_extractor
from batho.context.query import QueryService
from batho.context.storage import (
    backfill_registry,
    cleanup_registry,
    get_registry_stats,
    rebuild_query_index,
    register_artifact,
    verify_registry,
)
from batho.hooks import (
    HookInstallError,
    HookPlanningError,
    HooksConfigError,
    configured_hook_names,
    enabled_hook_names,
    ensure_git_hooks_dir,
    ensure_hooks_config,
    execute_hook,
    hook_status,
    install_hooks,
    list_template_catalog,
    load_hooks_file,
    remove_hooks,
    resolve_hook_plan,
    resolve_hooks_settings,
    supported_git_hooks,
)
from batho.hooks.constants import BUILTIN_TEMPLATE_CATALOG
from batho.synthesizer import load_evolution_ledger, record_failure_rule
from batho.time_machine import (
    FileChange,
    FileChangeSummary,
    FileChangeTracker,
    FileChangeType,
    FileTrackingConfig,
    PatchOperation,
    compute_staleness,
    create_snapshot,
    diff_snapshots,
    generate_snapshot_id,
    list_snapshots,
    load_snapshot,
)
from batho.utils.cli_output import CLIOutput
from batho.utils.file_io import _is_binary, read_file_bytes, write_atomically
from batho.utils.hash import compute_bytes_hash, compute_file_hash
from batho.utils.ignore import is_ignored, load_ignore_spec
from batho.utils.logging import configure_logging, get_logger

# Re-export for CLI tests that import from batho_cli
__all__ = [
    "build_parser",
    "main",
    "_collect_repo_metrics",
    "_compute_repo_hash",
    "_load_current_graph",
    "_needs_metrics_backfill",
    "_strip_files",
    "_backfill_index_metrics",
    "_auto_detect_changes",
    "_cmd_patch_index_based",
    "_cmd_patch_snapshot_based",
    "_detect_file_changes",
    "_extract_change_paths",
    "_files_from_diff",
    "_git_diff_entries_to_file_changes",
    "_reindex_files",
    "cmd_apply_patch",
    "cmd_bsg",
    "cmd_cache_clear",
    "cmd_cache_invalidate",
    "cmd_cache_stats",
    "cmd_cherry_pick",
    "cmd_hooks_install",
    "cmd_hooks_list",
    "cmd_hooks_remove",
    "cmd_hooks_run",
    "cmd_hooks_status",
    "cmd_index",
    "cmd_patch_chain",
    "cmd_patch_info",
    "cmd_patches",
    "cmd_plugins_list",
    "cmd_plugins_validate",
    "cmd_query",
    "cmd_sync",
    "extract_patch_deltas",
]

_read_file_content = read_file_bytes

LOGGER = get_logger(__name__)
CLI_OUTPUT = CLIOutput()
_RUNTIME_LOGGING_INITIALIZED = False

_PERSISTENCE_MODEL_VERSION = "ctn-artifact-registry.v1"

_DEFAULT_GET_CHANGED_FILE_STATUS_SINCE = batho_api.get_changed_file_status_since
_DEFAULT_INCREMENTAL_PATCH = batho_api.incremental_patch

# Compatibility aliases for tests/plugins that monkeypatch module-level symbols.
get_changed_file_status_since = _DEFAULT_GET_CHANGED_FILE_STATUS_SINCE
incremental_patch = _DEFAULT_INCREMENTAL_PATCH


def _configure_cli_output(*, quiet: bool, json_mode: bool) -> None:
    CLI_OUTPUT.configure(quiet=quiet, json_mode=json_mode)


def _ensure_runtime_logging() -> None:
    """Configure process logging from config for direct command invocations."""

    global _RUNTIME_LOGGING_INITIALIZED

    if _RUNTIME_LOGGING_INITIALIZED:
        return

    cfg = get_config_cached()
    configure_logging(cfg.get("logging", {}))
    _RUNTIME_LOGGING_INITIALIZED = True


def print(
    *args: Any, sep: str = " ", end: str = "\n", file: Any = None, flush: bool = False
) -> None:
    """Route CLI user output through the CLIOutput abstraction."""

    message = sep.join(str(arg) for arg in args) if args else ""

    if file is not None:
        _builtins.print(message, end=end, file=file, flush=flush)
        return

    CLI_OUTPUT.write(message, end=end, flush=flush)


def _resolve_get_changed_file_status_since():
    candidate = globals().get("get_changed_file_status_since")
    if callable(candidate) and candidate is not _DEFAULT_GET_CHANGED_FILE_STATUS_SINCE:
        return candidate
    return batho_api.get_changed_file_status_since


def _resolve_incremental_patch():
    candidate = globals().get("incremental_patch")
    if callable(candidate) and candidate is not _DEFAULT_INCREMENTAL_PATCH:
        return candidate
    return batho_api.incremental_patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _generate_index_id() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"batho_{uuid.uuid4().hex}_{ts}"


def _ensure_ctn_dir(root: Path) -> Path:
    _ensure_runtime_logging()
    ctn_dir = root / get_config_cached()["paths"]["ctn_dir"]
    ctn_dir.mkdir(parents=True, exist_ok=True)
    return ctn_dir


def _ensure_local_dirs(ctn_dir: Path) -> dict[str, Path]:
    """Create .ctn/local/ subdirectories and return paths."""
    local = ctn_dir / "local"
    paths = {
        "cache": local / "cache",
        "sync": local / "sync",
        "metrics": local / "metrics",
        "state": local / "state",
    }
    for p in paths.values():
        p.mkdir(parents=True, exist_ok=True)
    return paths


def _get_serialization_config() -> dict[str, Any]:
    """Get BSG serialization config from cached config."""
    return get_config_cached().get("bsg", {}).get("serialization", {})


def _format_bytes(size_bytes: int) -> str:
    value = float(max(0, int(size_bytes)))
    units = ["B", "KB", "MB", "GB", "TB"]
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024.0
    return f"{int(size_bytes)} B"


def _extract_stack_info_from_bsg(graph: Any) -> dict[str, Any]:
    """
    Extract stack information from BSG metadata set by detection plugins.

    Optimized to process only file-level entities (MODULE, DOCUMENT) to avoid
    redundant extraction from multiple entities in the same file.

    Returns a dict with languages, frameworks, package_managers, and infra.
    """
    from batho.context.schema import EntityType

    languages: set[str] = set()
    frameworks: set[str] = set()
    package_managers: set[str] = set()
    infra: set[str] = set()

    # Track processed files to avoid redundant extraction
    processed_files: set[str] = set()

    # File-level entity types that typically hold stack detection metadata
    file_level_types = {EntityType.MODULE, EntityType.DOCUMENT, EntityType.ENTRY_POINT}

    for entity in graph.entities.values():
        # Skip if we've already processed this file
        if entity.file in processed_files:
            continue

        # Prefer file-level entities for stack metadata
        if entity.type not in file_level_types:
            continue

        metadata = entity.metadata or {}

        # Extract language
        lang = metadata.get("bsg.language")
        if lang:
            languages.add(str(lang))

        # Extract frameworks (can be a list)
        fw = metadata.get("bsg.frameworks")
        if isinstance(fw, list):
            frameworks.update(str(f) for f in fw)
        elif fw:
            frameworks.add(str(fw))

        # Extract package manager
        pm = metadata.get("bsg.package_manager")
        if pm:
            package_managers.add(str(pm))

        # Extract infrastructure (can be a list)
        inf = metadata.get("bsg.infra")
        if isinstance(inf, list):
            infra.update(str(i) for i in inf)
        elif inf:
            infra.add(str(inf))

        # Mark this file as processed
        processed_files.add(entity.file)

    return {
        "languages": sorted(languages),
        "frameworks": sorted(frameworks),
        "package_managers": sorted(package_managers),
        "infra": sorted(infra),
    }


def _extract_change_paths(changes: Iterable[Any]) -> list[str]:
    paths: list[str] = []
    seen: set[str] = set()

    for change in changes:
        path_value: str | None = None
        if isinstance(change, dict):
            raw_path = change.get("path")
            if raw_path:
                path_value = str(raw_path)
        else:
            raw_path = getattr(change, "path", None)
            if raw_path:
                path_value = str(raw_path)

        if not path_value:
            continue
        if path_value in seen:
            continue

        seen.add(path_value)
        paths.append(path_value)

    return sorted(paths)


def _git_diff_entries_to_file_changes(
    root: Path, entries: list[GitDiffEntry]
) -> list[FileChange]:
    """Convert git diff status entries to FileChange records for patching."""
    # Path-level status precedence ensures deterministic outcomes.
    status_rank = {"D": 3, "A": 2, "M": 1}
    chosen: dict[str, GitDiffEntry] = {}

    for entry in entries:
        rel_path = entry.path.strip()
        if not rel_path:
            continue

        existing = chosen.get(rel_path)
        if existing is None or status_rank.get(entry.status, 0) > status_rank.get(
            existing.status, 0
        ):
            chosen[rel_path] = entry

    changes: list[FileChange] = []
    for rel_path, entry in sorted(chosen.items()):
        abs_path = root / rel_path
        if entry.status == "D" or not abs_path.exists():
            changes.append(
                FileChange(
                    path=rel_path,
                    change_type=FileChangeType.DELETED,
                    old_hash=None,
                    new_hash=None,
                )
            )
            continue

        change_type = (
            FileChangeType.ADDED if entry.status == "A" else FileChangeType.MODIFIED
        )

        try:
            stat_info = abs_path.stat()
            changes.append(
                FileChange(
                    path=rel_path,
                    change_type=change_type,
                    old_hash=None,
                    new_hash=compute_file_hash(abs_path),
                    file_size=stat_info.st_size,
                    mtime=datetime.fromtimestamp(stat_info.st_mtime, timezone.utc),
                )
            )
        except OSError:
            # Skip unreadable files and let fallback/full rebuild handle anomalies.
            continue

    return changes


def _extract_bsg_quality_warnings(payload: dict[str, Any]) -> list[str]:
    """Return normalized quality warning strings from a bsg payload."""

    raw_warnings = payload.get("quality_warnings")
    if not isinstance(raw_warnings, list):
        return []

    warnings: list[str] = []
    for item in raw_warnings:
        text = str(item).strip()
        if text:
            warnings.append(text)
    return warnings


def _emit_bsg_quality_warnings(warnings: list[str], verbose: bool) -> None:
    """Emit a compact warning summary and optional sample lines."""

    if not warnings:
        return

    print(f"⚠️  BSG quality warnings: {len(warnings)}")
    if not verbose:
        return

    sample_size = 5
    for warning in warnings[:sample_size]:
        print(f"   - {warning}")
    if len(warnings) > sample_size:
        print(f"   - ... {len(warnings) - sample_size} more")


@contextmanager
def _ctn_lock(ctn_dir: Path):
    lock_path = ctn_dir / "ctn.lock"
    fd = None
    try:
        for _ in range(50):
            try:
                fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_RDWR)
                os.write(fd, str(os.getpid()).encode())
                break
            except FileExistsError:
                time.sleep(0.1)
        else:
            raise RuntimeError("Could not acquire .ctn lock")
        yield
    finally:
        if fd is not None:
            os.close(fd)
        try:
            lock_path.unlink()
        except OSError:
            pass


def _load_index_metadata(ctn_dir: Path) -> dict[str, Any]:
    index_path = ctn_dir / "index.json"
    if not index_path.exists():
        return {"current_index_id": "", "indexes": {}}
    try:
        data = json.loads(index_path.read_text(encoding="utf-8"))
        checksum = data.get("_checksum")
        if checksum:
            calc = compute_bytes_hash(
                json.dumps(
                    {k: v for k, v in data.items() if k != "_checksum"}, sort_keys=True
                ).encode("utf-8")
            )
            if calc != checksum:
                return {"current_index_id": "", "indexes": {}, "corrupted": True}
        return data
    except (json.JSONDecodeError, OSError):
        return {"current_index_id": "", "indexes": {}}


def _save_index_metadata(ctn_dir: Path, metadata: dict[str, Any]) -> None:
    index_path = ctn_dir / "index.json"
    payload = {**metadata}
    schema_version = get_config_cached().get(
        "index_metadata_schema_version", "index-metadata.v1"
    )
    payload.setdefault("persistence_model", _PERSISTENCE_MODEL_VERSION)
    payload["schema_version"] = schema_version
    payload["_checksum"] = compute_bytes_hash(
        json.dumps(
            {k: v for k, v in payload.items() if k != "_checksum"}, sort_keys=True
        ).encode("utf-8")
    )
    write_atomically(index_path, payload, is_json=True)
    register_artifact(
        ctn_dir,
        index_path,
        "index_metadata",
        producer="cli.index",
        schema_version=schema_version,
    )


def _load_interception_stats(ctn_dir: Path) -> dict[str, Any]:
    path = ctn_dir / "local" / "metrics" / "interception_stats.json"
    if not path.exists():
        return {"plugins": {}}

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"plugins": {}}

    if not isinstance(payload, dict):
        return {"plugins": {}}

    plugins = payload.get("plugins")
    if not isinstance(plugins, dict):
        return {"plugins": {}}

    return payload


def _build_interception_matrix(payload: dict[str, Any]) -> list[dict[str, Any]]:
    plugins = payload.get("plugins") if isinstance(payload, dict) else {}
    if not isinstance(plugins, dict):
        return []

    matrix: list[dict[str, Any]] = []
    for plugin_id, plugin_data in plugins.items():
        if not isinstance(plugin_data, dict):
            continue

        interceptions = int(plugin_data.get("interceptions", 0) or 0)
        name = str(plugin_data.get("name") or plugin_id)
        matrix.append(
            {
                "plugin_id": str(plugin_id),
                "name": name,
                "interceptions": interceptions,
            }
        )

    matrix.sort(key=lambda item: (-item["interceptions"], item["name"]))
    return matrix


def _load_recent_evolution_rules(ctn_dir: Path, limit: int = 5) -> list[dict[str, str]]:
    try:
        ledger = load_evolution_ledger(ctn_dir)
    except Exception:
        return []

    entries = ledger.get("entries") if isinstance(ledger, dict) else []
    if not isinstance(entries, list) or not entries:
        return []

    recent: list[dict[str, str]] = []
    for raw in entries[-max(1, limit) :]:
        if not isinstance(raw, dict):
            continue

        dont_rule = str(raw.get("dont_rule") or "").strip()
        if not dont_rule:
            continue

        recent.append(
            {
                "entry_id": str(raw.get("entry_id") or ""),
                "source": str(raw.get("source") or "unknown"),
                "timestamp": str(raw.get("timestamp") or ""),
                "dont_rule": dont_rule,
            }
        )

    return recent


def _is_path_under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _write_json(
    path: Path,
    data: Any,
    *,
    ctn_dir: Path | None = None,
    artifact_type: str | None = None,
    producer: str = "cli",
    metadata: dict[str, Any] | None = None,
    schema_version: str = "",
) -> None:
    """Write JSON data atomically."""
    write_atomically(path, data, is_json=True)
    if ctn_dir is not None and artifact_type:
        register_artifact(
            ctn_dir,
            path,
            artifact_type,
            producer=producer,
            metadata=metadata,
            schema_version=schema_version,
        )


def _write_json_chunks(
    path: Path,
    chunks: Iterable[str],
    *,
    ctn_dir: Path | None = None,
    artifact_type: str | None = None,
    producer: str = "cli",
    metadata: dict[str, Any] | None = None,
    schema_version: str = "",
) -> None:
    """Write pre-encoded JSON chunks atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        for chunk in chunks:
            handle.write(chunk)
    tmp_path.replace(path)
    if ctn_dir is not None and artifact_type:
        register_artifact(
            ctn_dir,
            path,
            artifact_type,
            producer=producer,
            metadata=metadata,
            schema_version=schema_version,
        )


def _write_text(
    path: Path,
    content: str,
    *,
    ctn_dir: Path | None = None,
    artifact_type: str | None = None,
    producer: str = "cli",
    metadata: dict[str, Any] | None = None,
    schema_version: str = "",
) -> None:
    """Write text content atomically."""
    write_atomically(path, content)
    if ctn_dir is not None and artifact_type:
        register_artifact(
            ctn_dir,
            path,
            artifact_type,
            producer=producer,
            metadata=metadata,
            schema_version=schema_version,
        )


def _write_metrics(
    path: Path,
    payload: dict[str, Any],
    *,
    ctn_dir: Path | None = None,
    artifact_type: str | None = None,
    producer: str = "cli",
    metadata: dict[str, Any] | None = None,
    schema_version: str = "",
) -> None:
    """Write metrics data atomically as JSON."""
    write_atomically(path, payload, is_json=True)
    if ctn_dir is not None and artifact_type:
        register_artifact(
            ctn_dir,
            path,
            artifact_type,
            producer=producer,
            metadata=metadata,
            schema_version=schema_version,
        )


def _estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text.encode("utf-8")) // 4)


def cmd_hooks_list(args: argparse.Namespace) -> int:
    root = Path(getattr(args, "root", ".") or ".").resolve()
    config_path, pointer_enabled = resolve_hooks_settings(root)
    payload: dict[str, Any] = {
        "root": str(root),
        "pointer_enabled": pointer_enabled,
        "config_path": str(config_path),
        "config_exists": config_path.exists(),
        "supported_git_hooks": supported_git_hooks(),
        "configured_hooks": [],
        "enabled_hooks": [],
        "template_catalog": {
            "builtin": sorted(BUILTIN_TEMPLATE_CATALOG.keys()),
            "custom": [],
        },
    }

    if config_path.exists():
        try:
            hooks_file = load_hooks_file(config_path)
            payload["configured_hooks"] = configured_hook_names(hooks_file)
            payload["enabled_hooks"] = enabled_hook_names(hooks_file)
            payload["template_catalog"] = list_template_catalog(hooks_file)
        except HooksConfigError as exc:
            payload["error"] = str(exc)
            print(json.dumps(payload, indent=2))
            return 1

    print(json.dumps(payload, indent=2))
    return 0


def cmd_hooks_status(args: argparse.Namespace) -> int:
    root = Path(getattr(args, "root", ".") or ".").resolve()
    config_path, pointer_enabled = resolve_hooks_settings(root)
    payload: dict[str, Any] = {
        "root": str(root),
        "pointer_enabled": pointer_enabled,
        "config_path": str(config_path),
        "config_exists": config_path.exists(),
    }

    try:
        hooks_dir = ensure_git_hooks_dir(root)
        payload["git_hooks_dir"] = str(hooks_dir)
    except HookInstallError as exc:
        payload["error"] = str(exc)
        print(json.dumps(payload, indent=2))
        return 1

    if not config_path.exists():
        payload["error"] = f"Hooks config not found: {config_path}"
        print(json.dumps(payload, indent=2))
        return 1

    try:
        hooks_file = load_hooks_file(config_path)
    except HooksConfigError as exc:
        payload["error"] = str(exc)
        print(json.dumps(payload, indent=2))
        return 1

    if args.hook:
        target_hooks = [args.hook]
    else:
        target_hooks = configured_hook_names(hooks_file)

    hooks_payload: list[dict[str, Any]] = []
    for hook_name in target_hooks:
        state = hook_status(root, hook_name)
        cfg = hooks_file.hooks.get(hook_name)
        state["configured"] = cfg is not None
        state["enabled"] = bool(cfg.enabled) if cfg else False
        hooks_payload.append(state)

    payload["hooks"] = hooks_payload
    print(json.dumps(payload, indent=2))
    return 0


def cmd_hooks_install(args: argparse.Namespace) -> int:
    if args.hook and args.all:
        print("❌ Cannot use both --hook and --all")
        return 1

    root = Path(getattr(args, "root", ".") or ".").resolve()
    try:
        ensure_git_hooks_dir(root)
    except HookInstallError as exc:
        print(f"❌ {exc}")
        return 1

    _config_path, pointer_enabled = resolve_hooks_settings(root)
    if not pointer_enabled:
        print("❌ Hooks pointer is disabled in batho.yaml")
        return 1

    config_path, bootstrapped = ensure_hooks_config(root, dry_run=bool(args.dry_run))

    try:
        hooks_file = load_hooks_file(config_path)
    except FileNotFoundError:
        if bootstrapped and bool(args.dry_run):
            print(
                json.dumps(
                    {
                        "root": str(root),
                        "config_path": str(config_path),
                        "bootstrapped": True,
                        "installed": [],
                        "unchanged": [],
                        "skipped": [],
                        "warnings": [
                            "Dry-run: starter hooks config would be created before install"
                        ],
                        "dry_run": True,
                    },
                    indent=2,
                )
            )
            return 0
        print(f"❌ Hooks config not found: {config_path}")
        return 1
    except HooksConfigError as exc:
        print(f"❌ {exc}")
        return 1

    targets = [args.hook] if args.hook else enabled_hook_names(hooks_file)
    if not targets:
        print(
            json.dumps(
                {
                    "root": str(root),
                    "config_path": str(config_path),
                    "bootstrapped": bootstrapped,
                    "installed": [],
                    "unchanged": [],
                    "skipped": [],
                    "warnings": ["No enabled hooks found in config"],
                    "dry_run": bool(args.dry_run),
                },
                indent=2,
            )
        )
        return 0

    try:
        result = install_hooks(
            root,
            targets,
            force=bool(args.force),
            dry_run=bool(args.dry_run),
            skip_unsupported=True,
        )
    except HookInstallError as exc:
        print(f"❌ {exc}")
        return 1

    payload = {
        "root": str(root),
        "config_path": str(config_path),
        "bootstrapped": bootstrapped,
        **result,
    }
    print(json.dumps(payload, indent=2))
    return 0


def cmd_hooks_remove(args: argparse.Namespace) -> int:
    if args.hook and args.all:
        print("❌ Cannot use both --hook and --all")
        return 1

    root = Path(getattr(args, "root", ".") or ".").resolve()
    try:
        ensure_git_hooks_dir(root)
    except HookInstallError as exc:
        print(f"❌ {exc}")
        return 1

    config_path, _pointer_enabled = resolve_hooks_settings(root)

    targets: list[str]
    if args.hook:
        targets = [args.hook]
    else:
        if not config_path.exists():
            print(f"❌ Hooks config not found: {config_path}")
            return 1
        try:
            hooks_file = load_hooks_file(config_path)
        except HooksConfigError as exc:
            print(f"❌ {exc}")
            return 1
        targets = (
            enabled_hook_names(hooks_file) if args.all or not args.hook else [args.hook]
        )

    result = remove_hooks(root, targets, dry_run=bool(args.dry_run))
    payload = {
        "root": str(root),
        "config_path": str(config_path),
        **result,
    }
    print(json.dumps(payload, indent=2))
    return 0


def cmd_hooks_run(args: argparse.Namespace) -> int:
    root = Path(getattr(args, "root", ".") or ".").resolve()
    config_path, pointer_enabled = resolve_hooks_settings(root)
    if not pointer_enabled:
        print("❌ Hooks pointer is disabled in batho.yaml")
        return 1
    if not config_path.exists():
        print(f"❌ Hooks config not found: {config_path}")
        return 1

    try:
        hooks_file = load_hooks_file(config_path)
        _hook, stages = resolve_hook_plan(hooks_file, args.hook)
    except (HooksConfigError, HookPlanningError) as exc:
        print(f"❌ {exc}")
        return 1

    try:
        result = execute_hook(
            hook_name=args.hook,
            root=root,
            stages=stages,
            shell=hooks_file.defaults.shell,
            dry_run=bool(args.dry_run),
            verbose=bool(args.verbose),
        )
    except Exception as exc:
        print(f"❌ {exc}")
        return 1

    payload = {
        "root": str(root),
        "config_path": str(config_path),
        "dry_run": bool(args.dry_run),
        **result.to_dict(),
    }
    print(json.dumps(payload, indent=2))
    return 0 if result.success else 1


def _collect_repo_metrics(
    root: Path, max_file_size_kb: int | None = None
) -> dict[str, Any]:
    ignore_spec = load_ignore_spec(root)
    file_count_total = 0
    repo_size_bytes = 0
    loc_total = 0
    text_files = 0
    skipped_files = 0
    for file_path in root.rglob("*"):
        if not file_path.is_file():
            continue
        if is_ignored(file_path, root, ignore_spec):
            continue
        file_count_total += 1
        try:
            repo_size_bytes += file_path.stat().st_size
        except OSError:
            continue
        content = _read_file_content(str(file_path), max_file_size_kb)
        if content is None:
            skipped_files += 1
            continue
        text_files += 1
        loc_total += content.count(b"\n") + (1 if content else 0)
    return {
        "file_count_total": file_count_total,
        "repo_size_bytes": repo_size_bytes,
        "loc_total": loc_total,
        "text_files_count": text_files,
        "skipped_files_count": skipped_files,
    }


def _needs_metrics_backfill(metadata: dict[str, Any]) -> bool:
    for entry in metadata.get("indexes", {}).values():
        if not isinstance(entry, dict):
            return True
        stats = entry.get("stats", {})
        metrics = entry.get("metrics", {})
        if not isinstance(stats, dict) or not isinstance(metrics, dict):
            return True
        if "loc_total" not in stats or "repo_size_bytes" not in stats:
            return True
        if "loc_total" not in metrics or "repo_size_bytes" not in metrics:
            return True
    return False


def _backfill_index_metrics(ctn_dir: Path, root: Path) -> bool:
    metadata = _load_index_metadata(ctn_dir)
    if not _needs_metrics_backfill(metadata):
        return False
    indexer_cfg = get_config_cached().get("indexer", {})
    repo_metrics = _collect_repo_metrics(root, indexer_cfg.get("max_file_size_kb"))
    updated = False
    for entry in metadata.get("indexes", {}).values():
        if not isinstance(entry, dict):
            continue
        stats = entry.get("stats", {}) if isinstance(entry.get("stats"), dict) else {}
        metrics = (
            entry.get("metrics", {}) if isinstance(entry.get("metrics"), dict) else {}
        )
        for key in (
            "loc_total",
            "repo_size_bytes",
            "file_count_total",
            "text_files_count",
            "skipped_files_count",
        ):
            if key not in stats:
                stats[key] = repo_metrics.get(key)
                updated = True
        for key, value in repo_metrics.items():
            if key not in metrics:
                metrics[key] = value
                updated = True
        entry["stats"] = stats
        entry["metrics"] = metrics
    if updated:
        _save_index_metadata(ctn_dir, metadata)
    return updated


def _compute_repo_hash(root: Path) -> str:
    ignore_spec = load_ignore_spec(root)
    blobs: list[bytes] = []
    for file_path in sorted(root.rglob("*")):
        if not file_path.is_file():
            continue
        if is_ignored(file_path, root, ignore_spec):
            continue
        content = _read_file_content(str(file_path))
        if content is None:
            continue
        blobs.append(content)
    return compute_bytes_hash(b"".join(blobs)) if blobs else ""


def _load_current_graph(ctn_dir: Path, index_id: str) -> InMemoryGraph | None:
    return load_cached_graph(ctn_dir, index_id)


def _try_reuse_persisted_graph(
    root: Path,
    ctn_dir: Path,
    max_file_size_kb: int | None,
    *,
    force_full: bool,
) -> tuple[InMemoryGraph, BSGMap, dict[str, Any]] | None:
    """Deprecated: Legacy file-hash based graph reuse. Always returns None.

    SQLite cache now handles incremental indexing through content hashing.
    """
    if force_full:
        return None

    cfg = get_config_cached()
    bsg_cfg = cfg.get("bsg", {}) if isinstance(cfg, dict) else {}
    storage_cfg = bsg_cfg.get("storage", {}) if isinstance(bsg_cfg, dict) else {}
    if not bool(storage_cfg.get("enabled", True)):
        return None

    metadata = _load_index_metadata(ctn_dir)
    current_index_id = str(metadata.get("current_index_id") or "").strip()
    if not current_index_id:
        return None

    # Legacy incremental indexing using file_hashes.json is deprecated
    # SQLite cache already provides incremental functionality through content hashing
    LOGGER.info(
        "index_cache_reuse_unavailable",
        reason="legacy_file_hash_cache_deprecated",
        message="SQLite cache handles incremental indexing through content hashing",
    )
    return None


def _strip_files(
    graph: InMemoryGraph,
    file_paths: Iterable[str],
    root: Path | None = None,
) -> None:
    targets: set[str] = set()
    root_resolved = root.resolve() if root else None

    for file_path in file_paths:
        raw = str(file_path)
        if not raw:
            continue
        targets.add(raw)
        targets.add(Path(raw).as_posix())

        candidate = Path(raw)
        if root_resolved is not None and not candidate.is_absolute():
            resolved = (root_resolved / candidate).resolve()
            targets.add(str(resolved))
            targets.add(resolved.as_posix())

        if root_resolved is not None and candidate.is_absolute():
            try:
                rel = candidate.resolve().relative_to(root_resolved)
                targets.add(rel.as_posix())
            except ValueError:
                pass

    remove_ids = {
        eid for eid, ent in list(graph.entities.items()) if ent.file in targets
    }
    graph.entities = {
        eid: ent for eid, ent in graph.entities.items() if ent.file not in targets
    }
    graph.relationships = [
        r
        for r in graph.relationships
        if r.source_id not in remove_ids
        and r.target_id not in remove_ids
        and r.source_id not in targets
    ]


def _reindex_files(
    root: Path, files: list[Path], indexer: CodeGraphIndexer, graph: InMemoryGraph
) -> None:
    ignore_spec = load_ignore_spec(root)
    for file_path in files:
        if not file_path.exists() or not file_path.is_file():
            continue
        if is_ignored(file_path, root, ignore_spec):
            continue
        content = _read_file_content(str(file_path))
        if content is None:
            continue
        extractor = default_detector.get_extractor(file_path, content)
        if extractor is None:
            extractor = registry_get_extractor(file_path.suffix.lower())
        if extractor is None:
            continue

        filepath_str = str(file_path)
        _strip_files(graph, [filepath_str], root=root)
        ents, rels = extractor.parse_file(filepath_str, content)
        for ent in ents:
            graph.add_entity(ent)
        for rel in rels:
            graph.add_relationship(rel)


def _files_from_diff(diff_path: Path, root: Path) -> list[Path]:
    """
    Extract file paths from a git diff with comprehensive security validation.

    Args:
        diff_path: Path to the git diff file
        root: Root directory of the repository

    Returns:
        List of sanitized file paths

    Raises:
        PathSecurityError: If any path in the diff is malicious
    """
    from batho.utils.path_sanitizer import PathSecurityError, sanitize_diff_path

    paths: set[Path] = set()
    try:
        text = diff_path.read_text(encoding="utf-8", errors="ignore")
    except OSError as e:
        LOGGER.error("failed_to_read_diff", diff_path=str(diff_path), error=str(e))
        return []

    # Track seen paths to detect duplicates and potential attacks
    seen_paths: set[str] = set()

    for line_num, line in enumerate(text.splitlines(), 1):
        try:
            line = line.strip()
            if not line:
                continue

            # Handle multiple git diff formats more comprehensively
            diff_path_str = None

            # Standard git diff formats
            if line.startswith("+++ b/") or line.startswith("--- a/"):
                parts = line.split(
                    maxsplit=2
                )  # Limit splits to handle paths with spaces
                if len(parts) >= 2:
                    diff_path_str = parts[1]
            # Handle renamed files (old mode 100644 -> new mode 100644)
            elif line.startswith("rename from "):
                diff_path_str = line[12:]  # Remove "rename from " prefix
            elif line.startswith("rename to "):
                diff_path_str = line[10:]  # Remove "rename to " prefix
            # Handle similarity index lines
            elif line.startswith("similarity index ") or line.startswith(
                "dissimilarity index "
            ):
                continue  # Skip these lines
            # Handle binary file diffs
            elif "Binary files" in line and "differ" in line:
                # Extract paths from binary diff lines like "Binary files a/file and b/file differ"
                parts = line.split()
                if (
                    len(parts) >= 5
                    and parts[1].startswith("a/")
                    and parts[3].startswith("b/")
                ):
                    for i in [1, 3]:  # Both old and new paths
                        binary_path = parts[i][2:]  # Remove "a/" or "b/" prefix
                        if binary_path != "/dev/null":
                            try:
                                safe_path = sanitize_diff_path(binary_path, root)
                                if str(safe_path) not in seen_paths:
                                    paths.add(safe_path)
                                    seen_paths.add(str(safe_path))
                            except PathSecurityError:
                                LOGGER.warning(
                                    "unsafe_binary_path_in_diff",
                                    diff_path=str(diff_path),
                                    line=line_num,
                                    path=binary_path,
                                )
                continue

            # Skip if we didn't find a valid path format
            if diff_path_str is None:
                continue

            # Additional validation
            if (
                not diff_path_str or len(diff_path_str) > 1000
            ):  # Reasonable length limit
                LOGGER.warning(
                    "invalid_diff_path_length",
                    diff_path=str(diff_path),
                    line=line_num,
                    path=diff_path_str,
                )
                continue

            # Skip /dev/null which represents deleted files
            if diff_path_str == "/dev/null" or diff_path_str == "dev/null":
                continue

            # Check for suspicious patterns before sanitization
            dangerous_patterns = [
                "..",  # Path traversal attempt
                "\0",  # Null bytes
                "~",  # Home directory expansion
                "$",  # Environment variable expansion
                "`",  # Command substitution
                "${",  # Environment variable expansion
                "$( ",  # Command substitution
            ]

            if any(pattern in diff_path_str for pattern in dangerous_patterns):
                LOGGER.warning(
                    "dangerous_pattern_in_diff",
                    diff_path=str(diff_path),
                    line=line_num,
                    path=diff_path_str,
                )
                continue

            # Skip if we've already processed this path (prevents duplicate processing)
            if diff_path_str in seen_paths:
                continue

            try:
                # Use secure path sanitization
                safe_path = sanitize_diff_path(diff_path_str, root)
                final_path_str = str(safe_path)

                # Final safety check - ensure the path is within the root
                try:
                    safe_path.relative_to(root)
                except ValueError:
                    LOGGER.warning(
                        "path_outside_root",
                        diff_path=str(diff_path),
                        line=line_num,
                        path=diff_path_str,
                    )
                    continue

                # Check for extremely long paths after resolution
                if len(final_path_str) > 4096:  # Reasonable maximum path length
                    LOGGER.warning(
                        "path_too_long",
                        diff_path=str(diff_path),
                        line=line_num,
                        path=final_path_str,
                    )
                    continue

                paths.add(safe_path)
                seen_paths.add(diff_path_str)

            except PathSecurityError as e:
                LOGGER.warning(
                    "unsafe_path_in_diff",
                    diff_path=str(diff_path),
                    line=line_num,
                    path=diff_path_str,
                    error=str(e),
                )
                # Skip unsafe paths but continue processing others
                continue

        except Exception as e:
            LOGGER.error(
                "error_processing_diff_line",
                diff_path=str(diff_path),
                line=line_num,
                error=str(e),
            )
            continue

    return sorted(paths)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_index(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    if not root.exists() or not root.is_dir():
        print(f"❌ Root does not exist or is not a directory: {root}")
        return 1

    cfg = get_config_cached()
    ctn_dir = _ensure_ctn_dir(root)
    local_dirs = _ensure_local_dirs(ctn_dir)

    cache_path = local_dirs["cache"] / "ast_cache.db"
    build_start = time.perf_counter()
    no_ast_cache = bool(getattr(args, "no_ast_cache", False))

    force_full = bool(getattr(args, "full", False)) or bool(args.force)
    requested_base_snapshot = getattr(args, "base_snapshot", None)

    bsg_cfg = cfg.get("bsg", {}) if isinstance(cfg, dict) else {}
    incremental_cfg = (
        bsg_cfg.get("incremental", {}) if isinstance(bsg_cfg, dict) else {}
    )
    incremental_enabled = bool(incremental_cfg.get("enabled", True)) and not force_full
    fallback_to_full = bool(incremental_cfg.get("fallback_to_full", True))

    indexer: CodeGraphIndexer | None = None
    graph: InMemoryGraph | None = None
    bsg_map: BSGMap | None = None
    incremental_stats: dict[str, Any] = {}

    if args.force and cache_path.exists():
        try:
            cache_path.unlink()
            print("⚡ --force: cleared file cache")
        except (PermissionError, OSError) as exc:
            LOGGER.warning(
                "force_cache_clear_failed",
                cache_path=str(cache_path),
                error=str(exc),
            )
            print(f"⚠️  Could not clear file cache (may be in use): {exc}")

    # Note: --force already cleared the per-project cache above

    if incremental_enabled:
        base_snapshot_id = requested_base_snapshot or _get_latest_snapshot(ctn_dir)
        if base_snapshot_id:
            base_snapshot = load_snapshot(ctn_dir, base_snapshot_id)
            if isinstance(base_snapshot, dict):
                diff_entries = _resolve_get_changed_file_status_since()(
                    base_snapshot_id,
                    root,
                    base_snapshot,
                )
                if diff_entries is not None:
                    if not diff_entries:
                        graph = InMemoryGraph.from_dict(base_snapshot.get("graph", {}))
                        bsg_map = BSGMap.build(
                            graph,
                            root=str(root),
                            serialization_config=_get_serialization_config(),
                        )
                        incremental_stats = {
                            "incremental": True,
                            "base_snapshot_id": base_snapshot_id,
                            "changes_applied": 0,
                            "files_candidates": 0,
                            "files_parsed": 0,
                            "files_cached": 0,
                            "files_skipped": 0,
                            "errors": 0,
                            "workers_used": 0,
                            "entity_count": len(graph.entities),
                            "relationship_count": len(graph.relationships),
                        }
                        LOGGER.info(
                            "index_incremental_reused_snapshot",
                            base_snapshot_id=base_snapshot_id,
                        )
                    else:
                        changes = _git_diff_entries_to_file_changes(root, diff_entries)
                        patch_result = _resolve_incremental_patch()(
                            ctn_dir,
                            base_snapshot_id,
                            changes,
                        )
                        if patch_result.get("success"):
                            patched_snapshot_id = str(
                                patch_result.get("new_snapshot_id") or ""
                            )
                            patched_snapshot = (
                                load_snapshot(ctn_dir, patched_snapshot_id)
                                if patched_snapshot_id
                                else None
                            )
                            if isinstance(patched_snapshot, dict):
                                graph = InMemoryGraph.from_dict(
                                    patched_snapshot.get("graph", {})
                                )
                                bsg_map = BSGMap.build(
                                    graph,
                                    root=str(root),
                                    serialization_config=_get_serialization_config(),
                                )
                                incremental_stats = {
                                    "incremental": True,
                                    "base_snapshot_id": base_snapshot_id,
                                    "patched_snapshot_id": patched_snapshot_id,
                                    "changes_applied": int(
                                        patch_result.get(
                                            "applied_changes", len(changes)
                                        )
                                    ),
                                    "files_candidates": len(changes),
                                    "files_parsed": len(changes),
                                    "files_cached": 0,
                                    "files_skipped": 0,
                                    "errors": 0,
                                    "workers_used": 0,
                                    "entity_count": len(graph.entities),
                                    "relationship_count": len(graph.relationships),
                                }
                                LOGGER.info(
                                    "index_incremental_patched",
                                    base_snapshot_id=base_snapshot_id,
                                    patched_snapshot_id=patched_snapshot_id,
                                    changes=len(changes),
                                )
                        else:
                            LOGGER.warning(
                                "index_incremental_patch_failed",
                                base_snapshot_id=base_snapshot_id,
                                error=str(patch_result.get("error") or "unknown"),
                            )
                else:
                    LOGGER.info(
                        "index_incremental_unavailable",
                        base_snapshot_id=base_snapshot_id,
                        reason="git_or_snapshot_commit_unavailable",
                    )

    if graph is None or bsg_map is None:
        reused = _try_reuse_persisted_graph(
            root,
            ctn_dir,
            args.max_file_size_kb,
            force_full=force_full,
        )
        if reused is not None:
            graph, bsg_map, reused_stats = reused
            incremental_stats = {**incremental_stats, **reused_stats}

    if graph is None or bsg_map is None:
        if incremental_enabled and not fallback_to_full:
            print(
                "❌ Incremental indexing unavailable and fallback_to_full is disabled."
            )
            return 1

        index_id = _generate_index_id()

        try:
            indexer = CodeGraphIndexer(cache_path=str(cache_path), root=str(root))
        except Exception as exc:
            if cache_path.exists() and "not a database" in str(exc).lower():
                try:
                    cache_path.unlink(missing_ok=True)
                except (PermissionError, OSError) as unlink_exc:
                    LOGGER.warning(
                        "index_cache_delete_failed",
                        cache_path=str(cache_path),
                        error=str(unlink_exc),
                    )
                LOGGER.warning(
                    "index_cache_recreated",
                    cache_path=str(cache_path),
                    reason="invalid_sqlite_cache",
                )
                indexer = CodeGraphIndexer(cache_path=str(cache_path), root=str(root))
            else:
                raise

        try:
            graph = indexer.build_graph(
                root=str(root),
                extensions=args.extensions,
                max_workers=args.max_workers,
                max_file_size_kb=args.max_file_size_kb,
                verbose=args.verbose,
                snapshot_id=index_id,
                ast_cache_enabled=(not no_ast_cache),
            )
            bsg_map = BSGMap.build(
                graph, root=str(root), serialization_config=_get_serialization_config()
            )
        finally:
            if indexer is not None:
                indexer.close()
    else:
        index_id = _generate_index_id()

    if not graph.entities:
        print("⚠️  No entities extracted. Check source files and ignore patterns.")
        return 1

    # Extract stack info from BSG metadata
    stack_info = _extract_stack_info_from_bsg(graph)
    token_input_estimate = bsg_map.estimate_tokens()
    versioned_dir = ctn_dir / index_id
    versioned_dir.mkdir(parents=True, exist_ok=True)

    context_dir = versioned_dir / "context"
    context_dir.mkdir(parents=True, exist_ok=True)
    quality_warnings: list[str] = []

    with _ctn_lock(ctn_dir):
        # Outputs
        graph_path = (
            Path(args.output_json) if args.output_json else versioned_dir / "graph.json"
        )
        bsg_path = versioned_dir / "bsg.json"

        _write_json(
            graph_path,
            graph.to_dict(),
            ctn_dir=ctn_dir,
            artifact_type="graph_json",
            producer="cli.index",
            metadata={"index_id": index_id},
            schema_version=get_config_cached().get("graph_schema_version", "graph.v1"),
        )
        index_build_ms = max(0, int((time.perf_counter() - build_start) * 1000))
        serialization_method = (
            cfg.get("bsg", {})
            .get("serialization", {})
            .get("method", "legacy")
            .strip()
            .lower()
        )
        if serialization_method == "streaming":
            _write_json_chunks(
                bsg_path,
                bsg_map.render_json_streaming(
                    build_ms=index_build_ms,
                    default_snapshot_id=index_id,
                    default_service_tag=root.name,
                    extra_fields={"stack": stack_info},
                ),
                ctn_dir=ctn_dir,
                artifact_type="bsg_json",
                producer="cli.index",
                metadata={"index_id": index_id, "serialization_method": "streaming"},
                schema_version=get_config_cached().get("bsg_schema_version", "bsg.v1"),
            )
            bsg_json = json.loads(bsg_path.read_text(encoding="utf-8"))
        else:
            bsg_json = bsg_map.render_json(
                build_ms=index_build_ms,
                default_snapshot_id=index_id,
                default_service_tag=root.name,
            )
            bsg_json["stack"] = stack_info
            _write_json(
                bsg_path,
                bsg_json,
                ctn_dir=ctn_dir,
                artifact_type="bsg_json",
                producer="cli.index",
                metadata={"index_id": index_id, "serialization_method": "legacy"},
                schema_version=get_config_cached().get("bsg_schema_version", "bsg.v1"),
            )

        quality_warnings = _extract_bsg_quality_warnings(bsg_json)

        query_cfg = cfg.get("bsg", {}).get("query", {})
        query_enabled = bool(query_cfg.get("enabled", True))
        query_index_on_write = bool(query_cfg.get("index_on_write", True))
        query_index_stats = {"entities_indexed": 0, "relationships_indexed": 0}
        if query_enabled and query_index_on_write:
            query_index_stats = rebuild_query_index(
                ctn_dir,
                index_id,
                graph.to_dict(),
            )

        # Generate categorized markdown outputs
        timestamp = datetime.now(timezone.utc).isoformat()
        repo_name = root.name
        evolution_rules = _load_recent_evolution_rules(ctn_dir)

        # overview.md - Full repository overview
        overview_content = bsg_map.render_overview(
            stack_info=stack_info,
            repo_name=repo_name,
            timestamp=timestamp,
            evolution_rules=evolution_rules,
        )
        _write_text(
            context_dir / "overview.md",
            overview_content,
            ctn_dir=ctn_dir,
            artifact_type="context_overview",
            producer="cli.index",
            metadata={"index_id": index_id},
        )

        # files.md - All files by category (single source of truth)
        files_content = bsg_map.render_files_md(
            repo_name=repo_name,
            timestamp=timestamp,
        )
        _write_text(
            context_dir / "files.md",
            files_content,
            ctn_dir=ctn_dir,
            artifact_type="context_files",
            producer="cli.index",
            metadata={"index_id": index_id},
        )

        # Metadata
        metadata = _load_index_metadata(ctn_dir)
        prev_index_id = metadata.get("current_index_id")
        prev_entry = (
            metadata.get("indexes", {}).get(prev_index_id) if prev_index_id else None
        )
        repo_hash = _compute_repo_hash(root)
        stats = dict(indexer.stats) if indexer is not None else dict(incremental_stats)
        cache_hit_rate = 0.0
        parsed = int(stats.get("files_parsed", 0))
        cached = int(stats.get("files_cached", 0))
        total_processed = parsed + cached
        if total_processed > 0:
            cache_hit_rate = round(cached / total_processed, 4)
        repo_metrics = _collect_repo_metrics(root, args.max_file_size_kb)
        stats.update(
            {
                "loc_total": repo_metrics.get("loc_total"),
                "repo_size_bytes": repo_metrics.get("repo_size_bytes"),
                "file_count_total": repo_metrics.get("file_count_total"),
                "text_files_count": repo_metrics.get("text_files_count"),
                "skipped_files_count": repo_metrics.get("skipped_files_count"),
                "bsg_quality_warnings": len(quality_warnings),
                "bsg_quality_warning_samples": quality_warnings[:5],
                "query_entities_indexed": int(
                    query_index_stats.get("entities_indexed", 0)
                ),
                "query_relationships_indexed": int(
                    query_index_stats.get("relationships_indexed", 0)
                ),
            }
        )
        metrics = {
            **repo_metrics,
            "token_input_estimate": token_input_estimate,
            "cache_hit_rate": cache_hit_rate,
        }
        entry = {
            "id": index_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "root": str(root),
            "file_count": len(bsg_map._by_file),
            "entity_count": bsg_map.entity_count,
            "relationship_count": len(graph.relationships),
            "repo_hash": repo_hash,
            "staleness_score": compute_staleness(prev_entry, repo_hash, stats),
            "stack": stack_info,
            "outputs": {
                "graph_json": str(graph_path.relative_to(root)),
                "bsg_json": str(bsg_path.relative_to(root)),
                "overview_md": str((context_dir / "overview.md").relative_to(root)),
                "files_md": str((context_dir / "files.md").relative_to(root)),
            },
            "stats": stats,
            "metrics": metrics,
            "build": get_build_info(),
            "schemas": get_config_cached().get("schemas", {}),
            "persistence": {
                "model": _PERSISTENCE_MODEL_VERSION,
                "query_index_on_write": bool(query_enabled and query_index_on_write),
                "mmap_enabled": bool(
                    cfg.get("bsg", {}).get("storage", {}).get("mmap_enabled", False)
                ),
            },
        }
        snapshot_id = None
        if args.snapshot:
            snapshot_id = create_snapshot(
                ctn_dir, root, graph, bsg_map, label=args.snapshot_label
            )
            entry["snapshot_id"] = snapshot_id
        metadata.setdefault("indexes", {})[index_id] = entry
        metadata["current_index_id"] = index_id
        metadata["persistence_model"] = _PERSISTENCE_MODEL_VERSION
        _save_index_metadata(ctn_dir, metadata)

        if cache_path.exists():
            register_artifact(
                ctn_dir,
                cache_path,
                "file_cache_sqlite",
                producer="cli.index",
                metadata={"index_id": index_id},
                schema_version=get_config_cached().get(
                    "file_cache_schema_version", "file-cache.v1"
                ),
            )

        metrics_path = args.metrics_output or get_config_cached().get(
            "indexer", {}
        ).get("metrics_output")
        if metrics_path:
            # Resolve relative paths against the indexed repo root
            metrics_path_obj = Path(metrics_path)
            if not metrics_path_obj.is_absolute():
                metrics_path_obj = root / metrics_path

            metrics_payload = {
                "index_id": index_id,
                "timestamp": entry["timestamp"],
                "root": str(root),
                "stats": stats,
                "stack": stack_info,
                "metrics": metrics,
            }
            try:
                metrics_artifact_type = (
                    "metrics_json"
                    if _is_path_under(metrics_path_obj, ctn_dir)
                    else None
                )
                _write_metrics(
                    metrics_path_obj,
                    metrics_payload,
                    ctn_dir=ctn_dir,
                    artifact_type=metrics_artifact_type,
                    producer="cli.index",
                    metadata={"index_id": index_id},
                )
            except OSError as exc:
                LOGGER.warning(
                    "metrics_write_failed", path=metrics_path, error=str(exc)
                )

    if stats.get("errors"):
        print(f"⚠️  Indexed with {stats['errors']} parse errors (partial success).")

    _emit_bsg_quality_warnings(quality_warnings, verbose=args.verbose)

    if args.verbose:
        print(f"✅ Indexed {root} → {index_id}")
        print(
            f"   Entities: {entry['entity_count']}, Relationships: {entry['relationship_count']}"
        )
        print(f"   Outputs: {entry['outputs']}")
        if stack_info:
            print(f"   Stack: {stack_info}")
        if snapshot_id:
            print(f"   Snapshot: {snapshot_id}")
    return 2 if stats.get("errors") else 0


def cmd_stats(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    ctn_dir = _ensure_ctn_dir(root)
    _backfill_index_metrics(ctn_dir, root)
    metadata = _load_index_metadata(ctn_dir)
    current_id = metadata.get("current_index_id")
    if not current_id:
        print("No index found.")
        return 0
    entry = metadata["indexes"].get(current_id, {})
    stats = entry.get("stats", {}) if isinstance(entry, dict) else {}
    metrics = entry.get("metrics", {}) if isinstance(entry, dict) else {}
    interception_payload = _load_interception_stats(ctn_dir)
    interception_matrix = _build_interception_matrix(interception_payload)
    summary = {
        "loc_total": stats.get("loc_total") or metrics.get("loc_total"),
        "repo_size_bytes": stats.get("repo_size_bytes")
        or metrics.get("repo_size_bytes"),
        "compression_ratio": metrics.get("compression_ratio"),
        "cache_hit_rate": metrics.get("cache_hit_rate"),
    }
    output = {
        "summary": summary,
        "current": entry,
        "all_indexes": list(metadata.get("indexes", {}).keys()),
        "interception_matrix": interception_matrix,
    }
    print(json.dumps(output, indent=2))

    if interception_matrix:
        print("\nInterception Matrix")
        for row in interception_matrix:
            print(f"{row['name']}: {row['interceptions']} Interceptions")

    return 0


def cmd_snapshots(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    ctn_dir = _ensure_ctn_dir(root)
    snaps = list_snapshots(ctn_dir)
    print(json.dumps(snaps, indent=2))
    return 0


def cmd_diff_snapshots(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    ctn_dir = _ensure_ctn_dir(root)
    a = load_snapshot(ctn_dir, args.snapshot_a)
    b = load_snapshot(ctn_dir, args.snapshot_b)
    if not a or not b:
        print("❌ snapshot not found")
        return 1
    print(json.dumps(diff_snapshots(a, b), indent=2))
    return 0


def _detect_file_changes(
    root: Path, files: list[Path], ctn_dir: Path, base_snapshot_id: str
) -> list[FileChange]:
    """Detect changes for explicitly provided files by comparing with base snapshot."""
    changes = []
    base_snapshot = load_snapshot(ctn_dir, base_snapshot_id)
    if not base_snapshot:
        LOGGER.warning("base_snapshot_not_found", snapshot_id=base_snapshot_id)
        return []

    # Get file hashes from base snapshot
    base_files = {}
    for entity in base_snapshot.get("graph", {}).get("entities", []):
        file_path = entity.get("file", "")
        if file_path:
            if file_path not in base_files:
                base_files[file_path] = set()
            base_files[file_path].add(entity.get("name", ""))

    for file_path in files:
        if not file_path.exists():
            # File was deleted
            relative_path = str(file_path.relative_to(root))
            if relative_path in base_files:
                changes.append(
                    FileChange(
                        path=relative_path,
                        change_type=FileChangeType.DELETED,
                        old_hash=None,
                        new_hash=None,
                    )
                )
        else:
            # File exists - check if it's new or modified
            relative_path = str(file_path.relative_to(root))
            current_hash = compute_file_hash(file_path)

            if relative_path in base_files:
                # File existed before - assume modified
                changes.append(
                    FileChange(
                        path=relative_path,
                        change_type=FileChangeType.MODIFIED,
                        old_hash=None,  # Could be tracked if needed
                        new_hash=current_hash,
                        file_size=file_path.stat().st_size,
                        mtime=datetime.fromtimestamp(
                            file_path.stat().st_mtime, timezone.utc
                        ),
                    )
                )
            else:
                # New file
                changes.append(
                    FileChange(
                        path=relative_path,
                        change_type=FileChangeType.ADDED,
                        old_hash=None,
                        new_hash=current_hash,
                        file_size=file_path.stat().st_size,
                        mtime=datetime.fromtimestamp(
                            file_path.stat().st_mtime, timezone.utc
                        ),
                    )
                )

    return changes


def _auto_detect_changes(
    root: Path, ctn_dir: Path, base_snapshot_id: str, max_file_size_kb: int
) -> list[FileChange]:
    """Auto-detect changes by comparing current filesystem with base snapshot."""
    changes = []
    base_snapshot = load_snapshot(ctn_dir, base_snapshot_id)
    if not base_snapshot:
        LOGGER.warning("base_snapshot_not_found", snapshot_id=base_snapshot_id)
        return []

    # Get files from base snapshot
    base_files = set()
    for entity in base_snapshot.get("graph", {}).get("entities", []):
        file_path = entity.get("file", "")
        if file_path:
            base_files.add(file_path)

    # Get current files (respecting ignore rules)
    ignore_spec = load_ignore_spec(root)
    current_files = set()

    for file_path in root.rglob("*"):
        if file_path.is_file() and not is_ignored(file_path, root, ignore_spec):
            # Skip files that are too large
            if file_path.stat().st_size > max_file_size_kb * 1024:
                continue

            # Skip binary files
            try:
                content = file_path.read_bytes()
                if _is_binary(content):
                    continue
            except (OSError, IOError):
                continue

            relative_path = str(file_path.relative_to(root))
            current_files.add(relative_path)

    # Detect deletions
    for base_file in base_files:
        if base_file not in current_files:
            changes.append(
                FileChange(
                    path=base_file,
                    change_type=FileChangeType.DELETED,
                    old_hash=None,
                    new_hash=None,
                )
            )

    # Detect additions and modifications
    for current_file in current_files:
        full_path = root / current_file
        current_hash = compute_file_hash(full_path)

        if current_file in base_files:
            # File existed before - assume modified
            changes.append(
                FileChange(
                    path=current_file,
                    change_type=FileChangeType.MODIFIED,
                    old_hash=None,
                    new_hash=current_hash,
                    file_size=full_path.stat().st_size,
                    mtime=datetime.fromtimestamp(
                        full_path.stat().st_mtime, timezone.utc
                    ),
                )
            )
        else:
            # New file
            changes.append(
                FileChange(
                    path=current_file,
                    change_type=FileChangeType.ADDED,
                    old_hash=None,
                    new_hash=current_hash,
                    file_size=full_path.stat().st_size,
                    mtime=datetime.fromtimestamp(
                        full_path.stat().st_mtime, timezone.utc
                    ),
                )
            )

    return changes


def _get_latest_snapshot(ctn_dir: Path) -> str | None:
    """Get the most recent snapshot ID from the snapshots directory."""
    snapshots_dir = ctn_dir / "snapshots"
    if not snapshots_dir.exists():
        return None

    snapshot_files = list(snapshots_dir.glob("batho_*.json"))
    if not snapshot_files:
        return None

    # Sort by modification time and get the latest
    latest_file = max(snapshot_files, key=lambda f: f.stat().st_mtime)
    snapshot_id = latest_file.stem  # Remove .json extension

    return snapshot_id


def cmd_patch(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    ctn_dir = _ensure_ctn_dir(root)

    # Check if using snapshot-based patching
    if args.base_snapshot:
        # Use snapshot-based incremental patching
        return _cmd_patch_snapshot_based(args, root, ctn_dir)
    elif args.force_index_patch:
        # Force traditional index-based patching
        return _cmd_patch_index_based(args, root, ctn_dir)
    else:
        # Try to use incremental patching if snapshots are available
        latest_snapshot = _get_latest_snapshot(ctn_dir)
        if latest_snapshot and not args.diff:
            # Auto-use snapshot-based incremental patching for better performance
            args.base_snapshot = latest_snapshot
            LOGGER.info("auto_using_snapshot_patch", snapshot_id=latest_snapshot)
            return _cmd_patch_snapshot_based(args, root, ctn_dir)
        else:
            # Fall back to traditional index-based patching
            return _cmd_patch_index_based(args, root, ctn_dir)


def _cmd_patch_index_based(args: argparse.Namespace, root: Path, ctn_dir: Path) -> int:
    """Traditional index-based patching for backward compatibility."""
    metadata = _load_index_metadata(ctn_dir)
    current_id = metadata.get("current_index_id")
    if not current_id:
        print("❌ no current index; run index first")
        return 1

    graph = _load_current_graph(ctn_dir, current_id)
    if graph is None:
        print("❌ current graph.json missing or invalid")
        return 1

    local_dirs = _ensure_local_dirs(ctn_dir)
    cache_path = local_dirs["cache"] / "ast_cache.db"
    indexer = CodeGraphIndexer(cache_path=str(cache_path), root=str(root))

    files: list[Path] = []
    added_count = 0
    modified_count = 0
    deleted_count = 0
    affected_files: list[str] = []
    existing_files = {Path(entity.file).resolve() for entity in graph.entities.values()}

    if args.scan:
        hash_cache_path = local_dirs["state"] / "file_hashes.json"
        tracker = FileChangeTracker(root)
        tracker.load(hash_cache_path)
        changes = tracker.scan_for_changes(max_file_size_kb=args.max_file_size_kb)
        deleted_paths = tracker.get_deleted_files(changes)
        if deleted_paths:
            _strip_files(graph, deleted_paths, root=root)
        files = tracker.get_changed_files(changes)
        added_count = sum(
            1 for change in changes if change.change_type == FileChangeType.ADDED
        )
        modified_count = sum(
            1 for change in changes if change.change_type == FileChangeType.MODIFIED
        )
        deleted_count = sum(
            1 for change in changes if change.change_type == FileChangeType.DELETED
        )
        affected_files = sorted({change.path for change in changes})
        if not files and deleted_count == 0:
            print("No changes detected.")
            indexer.close()
            return 0
        tracker.save(hash_cache_path)
        if hash_cache_path.exists():
            register_artifact(
                ctn_dir,
                hash_cache_path,
                "file_hashes_json",
                producer="cli.patch.index",
                metadata={"index_id": current_id},
            )
        print(f"Scanned: {len(files)} changed files, {len(deleted_paths)} deleted")
    else:
        if args.diff:
            files.extend(_files_from_diff(Path(args.diff), root))
        if args.files:
            files.extend(
                Path(f).resolve() if not Path(f).is_absolute() else Path(f)
                for f in args.files
            )
        files = sorted({f for f in files if f.exists()})
        added_count = sum(
            1 for file_path in files if file_path.resolve() not in existing_files
        )
        modified_count = max(0, len(files) - added_count)
        deleted_count = 0
        affected_files = sorted(
            {str(file_path.relative_to(root)) for file_path in files}
        )

    if not files:
        print("No files to patch.")
        indexer.close()
        return 1

    if args.dry_run:
        print("Dry run mode - would apply changes to these files:")
        for f in files:
            print(f"  {f.relative_to(root)}")
        indexer.close()
        return 0

    patch_start = time.perf_counter()
    _reindex_files(root, files, indexer, graph)

    bsg_map = BSGMap.build(
        graph, root=str(root), serialization_config=_get_serialization_config()
    )
    versioned_dir = ctn_dir / current_id
    graph_path = versioned_dir / "graph.json"
    bsg_path = versioned_dir / "bsg.json"

    context_dir = versioned_dir / "context"
    context_dir.mkdir(parents=True, exist_ok=True)
    quality_warnings: list[str] = []

    with _ctn_lock(ctn_dir):
        # Load metadata for stack info
        metadata = _load_index_metadata(ctn_dir)
        entry = metadata.get("indexes", {}).get(current_id, {})

        _write_json(
            graph_path,
            graph.to_dict(),
            ctn_dir=ctn_dir,
            artifact_type="graph_json",
            producer="cli.patch.index",
            metadata={"index_id": current_id},
            schema_version=get_config_cached().get("graph_schema_version", "graph.v1"),
        )
        patch_build_ms = max(0, int((time.perf_counter() - patch_start) * 1000))
        serialization_method = (
            get_config_cached()
            .get("bsg", {})
            .get("serialization", {})
            .get("method", "legacy")
            .strip()
            .lower()
        )
        if serialization_method == "streaming":
            _write_json_chunks(
                bsg_path,
                bsg_map.render_json_streaming(
                    build_ms=patch_build_ms,
                    default_snapshot_id=current_id,
                    default_service_tag=root.name,
                ),
                ctn_dir=ctn_dir,
                artifact_type="bsg_json",
                producer="cli.patch.index",
                metadata={"index_id": current_id, "serialization_method": "streaming"},
                schema_version=get_config_cached().get("bsg_schema_version", "bsg.v1"),
            )
            bsg_json = json.loads(bsg_path.read_text(encoding="utf-8"))
        else:
            bsg_json = bsg_map.render_json(
                build_ms=patch_build_ms,
                default_snapshot_id=current_id,
                default_service_tag=root.name,
            )
            _write_json(
                bsg_path,
                bsg_json,
                ctn_dir=ctn_dir,
                artifact_type="bsg_json",
                producer="cli.patch.index",
                metadata={"index_id": current_id, "serialization_method": "legacy"},
                schema_version=get_config_cached().get("bsg_schema_version", "bsg.v1"),
            )

        quality_warnings = _extract_bsg_quality_warnings(bsg_json)

        query_cfg = get_config_cached().get("bsg", {}).get("query", {})
        query_enabled = bool(query_cfg.get("enabled", True))
        query_index_on_write = bool(query_cfg.get("index_on_write", True))
        query_index_stats = {"entities_indexed": 0, "relationships_indexed": 0}
        if query_enabled and query_index_on_write:
            query_index_stats = rebuild_query_index(
                ctn_dir,
                current_id,
                graph.to_dict(),
            )

        # Generate categorized markdown outputs
        timestamp = datetime.now(timezone.utc).isoformat()
        repo_name = root.name
        evolution_rules = _load_recent_evolution_rules(ctn_dir)

        # overview.md
        overview_content = bsg_map.render_overview(
            stack_info=entry.get("stack"),
            repo_name=repo_name,
            timestamp=timestamp,
            evolution_rules=evolution_rules,
        )
        _write_text(
            context_dir / "overview.md",
            overview_content,
            ctn_dir=ctn_dir,
            artifact_type="context_overview",
            producer="cli.patch.index",
            metadata={"index_id": current_id},
        )

        # files.md - All files by category (single source of truth)
        files_content = bsg_map.render_files_md(
            repo_name=root.name,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        _write_text(
            context_dir / "files.md",
            files_content,
            ctn_dir=ctn_dir,
            artifact_type="context_files",
            producer="cli.patch.index",
            metadata={"index_id": current_id},
        )

        # Update metadata entry
        entry = metadata.get("indexes", {}).get(current_id, {})
        prev_stats = entry.get("stats", {}) if isinstance(entry, dict) else {}
        repo_hash = _compute_repo_hash(root)
        token_input_estimate = bsg_map.estimate_tokens()
        patch_elapsed = round(time.perf_counter() - patch_start, 4)
        patch_metrics = {
            "last_patch_latency_seconds": patch_elapsed,
            "last_patch_files": len(files),
            "token_input_estimate": token_input_estimate,
        }
        metrics = entry.get("metrics", {}) if isinstance(entry, dict) else {}
        if isinstance(metrics, dict):
            metrics.update({"last_patch": patch_metrics})
        merged_stats = dict(indexer.stats)
        for key in (
            "loc_total",
            "repo_size_bytes",
            "file_count_total",
            "text_files_count",
            "skipped_files_count",
        ):
            if key in prev_stats and key not in merged_stats:
                merged_stats[key] = prev_stats[key]
        merged_stats["bsg_quality_warnings"] = len(quality_warnings)
        merged_stats["bsg_quality_warning_samples"] = quality_warnings[:5]
        merged_stats["query_entities_indexed"] = int(
            query_index_stats.get("entities_indexed", 0)
        )
        merged_stats["query_relationships_indexed"] = int(
            query_index_stats.get("relationships_indexed", 0)
        )
        entry.update(
            {
                "entity_count": bsg_map.entity_count,
                "relationship_count": len(graph.relationships),
                "repo_hash": repo_hash,
                "staleness_score": compute_staleness(entry, repo_hash, indexer.stats),
                "stats": merged_stats,
                "metrics": metrics,
            }
        )
        outputs = entry.setdefault("outputs", {})
        outputs["bsg_json"] = str(bsg_path.relative_to(root))
        for stale_key in tuple(outputs.keys()):
            if stale_key.endswith("_json") and stale_key not in {
                "graph_json",
                "bsg_json",
            }:
                outputs.pop(stale_key, None)
        outputs["overview_md"] = str((context_dir / "overview.md").relative_to(root))
        outputs["files_md"] = str((context_dir / "files.md").relative_to(root))
        entry["schemas"] = dict(get_config_cached().get("schemas", {}))
        entry["persistence"] = {
            "model": _PERSISTENCE_MODEL_VERSION,
            "query_index_on_write": bool(query_enabled and query_index_on_write),
            "mmap_enabled": bool(
                get_config_cached()
                .get("bsg", {})
                .get("storage", {})
                .get("mmap_enabled", False)
            ),
        }
        metadata.setdefault("indexes", {})[current_id] = entry
        metadata["persistence_model"] = _PERSISTENCE_MODEL_VERSION
        _save_index_metadata(ctn_dir, metadata)

        if cache_path.exists():
            register_artifact(
                ctn_dir,
                cache_path,
                "file_cache_sqlite",
                producer="cli.patch.index",
                metadata={"index_id": current_id},
                schema_version=get_config_cached().get(
                    "file_cache_schema_version", "file-cache.v1"
                ),
            )

        snapshot_id = None
        if args.snapshot:
            snapshot_id = create_snapshot(ctn_dir, root, graph, bsg_map)
            entry["snapshot_id"] = snapshot_id
            metadata["indexes"][current_id] = entry
            _save_index_metadata(ctn_dir, metadata)

    _emit_bsg_quality_warnings(quality_warnings, verbose=False)

    summary = FileChangeSummary(
        total_changes=added_count + modified_count + deleted_count,
        added=added_count,
        modified=modified_count,
        deleted=deleted_count,
        unchanged=0,
        affected_files=affected_files,
    )

    indexer.close()

    print(
        json.dumps(
            {
                "patched": summary.affected_files,
                "index_id": current_id,
                "summary": {
                    "total_changes": summary.total_changes,
                    "added": summary.added,
                    "modified": summary.modified,
                    "deleted": summary.deleted,
                    "unchanged": summary.unchanged,
                },
                "bsg_quality_warning_count": len(quality_warnings),
                "bsg_quality_warnings": quality_warnings[:5],
                "snapshot_id": snapshot_id,
            },
            indent=2,
        )
    )
    return 0


def _cmd_patch_snapshot_based(
    args: argparse.Namespace, root: Path, ctn_dir: Path
) -> int:
    """Snapshot-based incremental patching using base snapshot."""
    # Collect changes from various sources
    changes: list[FileChange] = []
    local_dirs = _ensure_local_dirs(ctn_dir)

    if args.scan:
        tracker = FileChangeTracker(root)
        hash_cache_path = local_dirs["state"] / "file_hashes.json"
        tracker.load(hash_cache_path)

        base_snapshot = None
        if args.base_snapshot:
            base_snapshot = load_snapshot(ctn_dir, args.base_snapshot)
            if base_snapshot:
                base_file_hashes: dict[str, str] = {}
                for entity in base_snapshot.get("graph", {}).get("entities", []):
                    file_path = entity.get("file", "")
                    file_hash = entity.get("hash", "")
                    if file_path and file_hash:
                        base_file_hashes[file_path] = file_hash
                if not base_file_hashes:
                    LOGGER.warning(
                        "base_snapshot_missing_hashes",
                        base_snapshot_id=args.base_snapshot,
                        note="snapshot entities lack hash field; falling back to full scan",
                    )
                    base_snapshot = None
                else:
                    base_snapshot = {"file_hashes": base_file_hashes}

        changes = tracker.scan_for_changes(
            max_file_size_kb=args.max_file_size_kb, base_snapshot=base_snapshot
        )
        tracker.save(hash_cache_path)
        if hash_cache_path.exists():
            register_artifact(
                ctn_dir,
                hash_cache_path,
                "file_hashes_json",
                producer="cli.patch.snapshot",
                metadata={"base_snapshot_id": args.base_snapshot},
            )
        print(f"Scanned: {len(changes)} changes detected")
    else:
        # Process explicit file changes or auto-detect from current index
        explicit_files = []
        if args.diff:
            explicit_files.extend(_files_from_diff(Path(args.diff), root))
        if args.files:
            explicit_files.extend(
                Path(f).resolve() if not Path(f).is_absolute() else Path(f)
                for f in args.files
            )

        if explicit_files:
            # Use explicitly provided files
            explicit_files = sorted({f for f in explicit_files})
            changes = _detect_file_changes(
                root, explicit_files, ctn_dir, args.base_snapshot
            )
        else:
            # Auto-detect changes by comparing current state with base snapshot
            changes = _auto_detect_changes(
                root, ctn_dir, args.base_snapshot, args.max_file_size_kb
            )

        print(f"Detected: {len(changes)} changes")

    if not changes:
        print("No changes detected.")
        return 0

    # Create summary for reporting
    summary = FileChangeSummary(
        total_changes=len(changes),
        added=sum(1 for c in changes if c.change_type == FileChangeType.ADDED),
        modified=sum(1 for c in changes if c.change_type == FileChangeType.MODIFIED),
        deleted=sum(1 for c in changes if c.change_type == FileChangeType.DELETED),
        unchanged=0,
        affected_files=[c.path for c in changes],
    )

    if args.dry_run:
        print("Dry run mode - would apply changes:")
        print(f"  Added: {summary.added}")
        print(f"  Modified: {summary.modified}")
        print(f"  Deleted: {summary.deleted}")
        print(f"  Files: {', '.join(summary.affected_files)}")
        return 0

    # Apply incremental patch
    result = _resolve_incremental_patch()(ctn_dir, args.base_snapshot, changes)

    if not result["success"]:
        error_msg = result.get("error", "Unknown error")
        LOGGER.error(
            "incremental_patch_failed",
            error=error_msg,
            operation_id=result.get("operation_id"),
            changes_count=len(changes),
        )
        ledger_entry = record_failure_rule(
            ctn_dir=ctn_dir,
            source="cli.patch.snapshot",
            error_message=error_msg,
            changed_files=summary.affected_files,
            context={
                "base_snapshot_id": args.base_snapshot,
                "operation_id": result.get("operation_id"),
                "changes_count": len(changes),
            },
        )

        failure_payload = {
            "error": result["error"],
            "operation_id": result.get("operation_id"),
        }
        if ledger_entry.get("entry_id"):
            failure_payload["ledger_entry_id"] = ledger_entry.get("entry_id")
            failure_payload["dont_rule"] = ledger_entry.get("dont_rule")

        print(
            json.dumps(
                failure_payload,
                indent=2,
            )
        )
        return 1

    # Create additional snapshot if requested
    final_snapshot_id = result["new_snapshot_id"]
    if args.snapshot:
        # Load the newly created snapshot and create another one if needed
        base_snapshot = load_snapshot(ctn_dir, result["new_snapshot_id"])
        if base_snapshot:
            final_snapshot_id = create_snapshot(
                ctn_dir,
                root,
                InMemoryGraph.from_dict(base_snapshot["graph"]),
                BSGMap.from_dict(base_snapshot["bsg"]),
                label="Post-patch snapshot",
            )

    quality_warnings: list[str] = []
    quality_snapshot_id = (
        final_snapshot_id if args.snapshot else result.get("new_snapshot_id")
    )
    if quality_snapshot_id:
        quality_snapshot = load_snapshot(ctn_dir, str(quality_snapshot_id))
        if isinstance(quality_snapshot, dict):
            bsg_payload = quality_snapshot.get("bsg")
            if isinstance(bsg_payload, dict):
                quality_warnings = _extract_bsg_quality_warnings(bsg_payload)

    _emit_bsg_quality_warnings(quality_warnings, verbose=False)

    print(
        json.dumps(
            {
                "success": True,
                "new_snapshot_id": result["new_snapshot_id"],
                "operation_id": result["operation_id"],
                "applied_changes": result["applied_changes"],
                "base_snapshot_id": result["base_snapshot_id"],
                "summary": {
                    "total_changes": summary.total_changes,
                    "added": summary.added,
                    "modified": summary.modified,
                    "deleted": summary.deleted,
                },
                "bsg_quality_warning_count": len(quality_warnings),
                "bsg_quality_warnings": quality_warnings[:5],
                "final_snapshot_id": (
                    final_snapshot_id if args.snapshot else result["new_snapshot_id"]
                ),
            },
            indent=2,
        )
    )
    return 0


def cmd_invalidate(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    ctn_dir = _ensure_ctn_dir(root)
    local_dirs = _ensure_local_dirs(ctn_dir)
    cache_path = local_dirs["cache"] / "ast_cache.db"
    if cache_path.exists():
        try:
            cache_path.unlink()
            print("✅ Cleared AST cache")
        except (PermissionError, OSError) as exc:
            LOGGER.warning(
                "invalidate_cache_failed",
                cache_path=str(cache_path),
                error=str(exc),
            )
            print(f"⚠️  Could not clear file cache (may be in use): {exc}")
            return 1
    else:
        print("(cache already clear)")
    return 0


def cmd_cache_stats(args: argparse.Namespace) -> int:
    """Show AST cache statistics."""
    from batho.context.cache import ASTCache

    root = Path(args.root).resolve()
    ctn_dir = _ensure_ctn_dir(root)
    local_dirs = _ensure_local_dirs(ctn_dir)
    cache_path = local_dirs["cache"] / "ast_cache.db"

    cache = ASTCache(cache_path=cache_path)
    stats = cache.get_cache_stats()

    print("📊 AST Cache Statistics")
    print(f"  Cache path: {stats['cache_path']}")
    print(f"  Entry count: {stats['entry_count']}")
    print(f"  Total size: {stats['total_size_mb']} MB")
    print(f"  Oldest entry: {stats['oldest_entry']}")
    print(f"  Newest entry: {stats['newest_entry']}")
    return 0


def cmd_cache_invalidate(args: argparse.Namespace) -> int:
    """Invalidate cache entries by pattern."""
    from batho.context.cache import ASTCache

    root = Path(args.root).resolve()
    ctn_dir = _ensure_ctn_dir(root)
    local_dirs = _ensure_local_dirs(ctn_dir)
    cache_path = local_dirs["cache"] / "ast_cache.db"

    cache = ASTCache(cache_path=str(cache_path))
    pattern = args.pattern

    if pattern:
        cache.invalidate_cache(pattern=pattern)
        print(f"✅ Invalidated cache entries matching: {pattern}")
    else:
        cache.invalidate_cache(pattern=None)
        print("✅ Invalidated all cache entries")
    return 0


def cmd_cache_clear(args: argparse.Namespace) -> int:
    """Clear entire AST cache."""
    from batho.context.cache import ASTCache

    root = Path(args.root).resolve()
    ctn_dir = _ensure_ctn_dir(root)
    local_dirs = _ensure_local_dirs(ctn_dir)
    cache_path = local_dirs["cache"] / "ast_cache.db"

    cache = ASTCache(cache_path=str(cache_path))
    cache.invalidate_cache(pattern=None)
    print("✅ Cleared entire AST cache")
    return 0


def cmd_storage_backfill(args: argparse.Namespace) -> int:
    """Backfill artifact registry metadata from existing durable .ctn files."""
    root = Path(args.root).resolve()
    ctn_dir = _ensure_ctn_dir(root)
    run_id = f"backfill-{uuid.uuid4().hex[:12]}"
    result = backfill_registry(
        ctn_dir,
        producer="cli.storage.backfill",
        run_id=run_id,
    )
    print(json.dumps(result, indent=2))
    return 0


def cmd_storage_verify(args: argparse.Namespace) -> int:
    """Verify registry consistency and optionally repair metadata drift."""
    root = Path(args.root).resolve()
    ctn_dir = _ensure_ctn_dir(root)
    run_id = f"verify-{uuid.uuid4().hex[:12]}"
    result = verify_registry(
        ctn_dir,
        repair=bool(args.repair),
        run_id=run_id,
    )
    print(json.dumps(result, indent=2))
    return 0


def cmd_storage_cleanup(args: argparse.Namespace) -> int:
    """Apply storage retention policy with dry-run by default."""
    root = Path(args.root).resolve()
    ctn_dir = _ensure_ctn_dir(root)
    dry_run = not bool(args.apply)
    result = cleanup_registry(ctn_dir, dry_run=dry_run)
    print(json.dumps(result, indent=2))
    return 0


def cmd_storage_stats(args: argparse.Namespace) -> int:
    """Show storage registry and graph-cache statistics."""
    root = Path(args.root).resolve()
    ctn_dir = _ensure_ctn_dir(root)
    registry_stats = get_registry_stats(ctn_dir)
    graph_stats = get_cached_graph_stats(
        ctn_dir, index_id=getattr(args, "index_id", None)
    )
    payload = {
        "registry": registry_stats,
        "graph_cache": graph_stats,
    }
    print(json.dumps(payload, indent=2))
    return 0


def cmd_sync(args: argparse.Namespace) -> int:
    """Sync artifacts to configured cloud endpoint."""
    from batho.cloud_sync.config import CloudSyncConfig
    from batho.cloud_sync.uploader import CloudSyncUploader

    root = Path(args.root or ".").resolve()
    if not root.exists() or not root.is_dir():
        print(f"❌ Root does not exist or is not a directory: {root}")
        return 1

    ctn_dir = _ensure_ctn_dir(root)
    cfg = reload_config()
    cloud_payload = cfg.get("cloud_sync")
    cloud_data = cloud_payload if isinstance(cloud_payload, dict) else {}

    try:
        cloud_cfg = CloudSyncConfig.model_validate(cloud_data)
    except Exception as exc:
        print(f"❌ Invalid cloud_sync configuration: {exc}")
        return 1

    uploader = CloudSyncUploader(cloud_cfg)

    if bool(args.status):
        status_payload = uploader.get_sync_status(ctn_dir)
        project_id = status_payload.get("project_id") or root.name
        print(f"Sync Status for project '{project_id}':")
        print(f"  Pending: {int(status_payload.get('pending', 0))}")
        print(f"  Synced: {int(status_payload.get('synced', 0))}")
        print(f"  Failed: {int(status_payload.get('failed', 0))}")
        print(f"  Local only: {int(status_payload.get('local_only', 0))}")
        return 0

    requires_upload = not bool(args.dry_run)
    if requires_upload and not cloud_cfg.enabled:
        print(
            "❌ Cloud sync is disabled. Set cloud_sync.enabled=true in batho.yaml or BATHO_CLOUD_SYNC_ENABLED=1"
        )
        return 1
    if requires_upload and not cloud_cfg.endpoint:
        print("❌ cloud_sync.endpoint is required for sync uploads")
        return 1
    if requires_upload and not cloud_cfg.resolved_api_key():
        print("❌ cloud_sync.api_key is required for sync uploads")
        return 1

    artifact_types = [
        str(value).strip()
        for value in (args.artifact_types or [])
        if str(value).strip()
    ]

    def _progress(index: int, total: int, payload: dict[str, Any]) -> None:
        if not bool(args.verbose) or total <= 0:
            return
        pct = int((index / total) * 100)
        filled = min(20, int((index / total) * 20))
        bar = ("█" * filled) + ("░" * (20 - filled))
        artifact_id = str(payload.get("artifact_id") or "")
        print(f"[{bar}] {index}/{total} - {pct}% {artifact_id}")

    if bool(args.retry_failed):
        summary = uploader.retry_failed(
            ctn_dir,
            dry_run=bool(args.dry_run),
            progress_callback=_progress if bool(args.verbose) else None,
        )
    else:
        summary = uploader.sync_pending_artifacts(
            ctn_dir,
            dry_run=bool(args.dry_run),
            artifact_types=artifact_types or None,
            progress_callback=_progress if bool(args.verbose) else None,
        )

    if bool(args.dry_run):
        print(f"Found {summary.total} artifacts to sync:")
        for artifact_type in sorted(summary.by_type.keys()):
            bucket = summary.by_type[artifact_type]
            count = int(bucket.get("count", 0))
            size_bytes = int(bucket.get("size_bytes", 0))
            print(f"  - {count} {artifact_type} files ({_format_bytes(size_bytes)})")
        return 0

    if bool(args.retry_failed):
        print(f"Retrying failed artifact uploads to {cloud_cfg.endpoint}...")
    else:
        print(f"Syncing {summary.total} artifacts to {cloud_cfg.endpoint}...")

    if summary.total > 0 and not bool(args.verbose):
        print(f"[{'█' * 20}] {summary.total}/{summary.total} - 100%")

    print()
    print("Results:")
    print(f"  Uploaded: {summary.uploaded}")
    print(f"  Failed: {summary.failed}")
    print(f"  Duration: {summary.duration_seconds:.1f}s")

    if summary.failed > 0 and bool(args.verbose):
        for failure in summary.failures[:10]:
            artifact_id = str(failure.get("artifact_id") or "")
            error = str(failure.get("error") or "upload_failed")
            print(f"  - {artifact_id}: {error}")

    return 0 if summary.failed == 0 else 1


def cmd_storage_rebuild_indexes(args: argparse.Namespace) -> int:
    """Rebuild persisted query indexes for an existing graph artifact."""
    root = Path(args.root).resolve()
    ctn_dir = _ensure_ctn_dir(root)
    metadata = _load_index_metadata(ctn_dir)
    index_id = str(args.index_id or metadata.get("current_index_id") or "").strip()
    if not index_id:
        print("❌ No index found. Run 'batho index' first.")
        return 1

    graph = _load_current_graph(ctn_dir, index_id)
    if graph is None:
        print(f"❌ graph.json missing or invalid for index: {index_id}")
        return 1

    stats = rebuild_query_index(ctn_dir, index_id, graph.to_dict())
    print(
        json.dumps(
            {
                "index_id": index_id,
                "entities_indexed": int(stats.get("entities_indexed", 0)),
                "relationships_indexed": int(stats.get("relationships_indexed", 0)),
            },
            indent=2,
        )
    )
    return 0


def cmd_query(args: argparse.Namespace) -> int:
    """Query persisted graph indexes with automatic in-memory fallback."""
    root = Path(args.root).resolve()
    ctn_dir = _ensure_ctn_dir(root)

    cfg = get_config_cached()
    default_limit = (
        cfg.get("bsg", {}).get("query", {}).get("default_limit", 200)
        if isinstance(cfg, dict)
        else 200
    )
    limit = max(1, int(args.limit or default_limit))

    service = QueryService(ctn_dir, index_id=args.index_id)
    rebuild_stats: dict[str, int] | None = None
    if args.rebuild_index:
        rebuild_stats = service.rebuild_indexes()

    metadata = _load_index_metadata(ctn_dir)
    resolved_index_id = args.index_id or metadata.get("current_index_id")
    if not resolved_index_id:
        print("❌ No index found. Run 'batho index' first.")
        return 1

    if args.entity_type:
        rows = service.entities_by_type(args.entity_type, limit=limit)
        mode = "entities_by_type"
    elif args.file_path:
        rows = service.entities_by_file(args.file_path, limit=limit)
        mode = "entities_by_file"
    elif args.relationship_type:
        rows = service.relationships_by_type(args.relationship_type, limit=limit)
        mode = "relationships_by_type"
    else:
        print("❌ Provide one of --entity-type, --file-path, or --relationship-type.")
        return 1

    payload: dict[str, Any] = {
        "mode": mode,
        "index_id": resolved_index_id,
        "count": len(rows),
        "limit": limit,
        "rows": rows,
    }
    if rebuild_stats is not None:
        payload["rebuild_index"] = rebuild_stats

    print(json.dumps(payload, indent=2))
    return 0


def cmd_bsg(args: argparse.Namespace) -> int:
    """Render BSG in various formats."""
    root = Path(args.root).resolve()
    if not root.exists() or not root.is_dir():
        print(f"❌ Root does not exist or is not a directory: {root}")
        return 1

    ctn_dir = _ensure_ctn_dir(root)
    metadata = _load_index_metadata(ctn_dir)
    current_id = metadata.get("current_index_id")

    if not current_id:
        print("❌ No index found. Run 'batho index' first.")
        return 1

    graph = _load_current_graph(ctn_dir, current_id)
    if graph is None:
        print("❌ Current graph.json missing or invalid")
        return 1

    bsg_map = BSGMap.build(
        graph, root=str(root), serialization_config=_get_serialization_config()
    )

    # Render based on mode
    try:
        versioned_dir = ctn_dir / current_id

        if args.mode == "compressed":
            output, stats = bsg_map.render_compressed(
                budget=args.budget, fail_on_overflow=False
            )
            # Save compressed output with stats as JSON
            compressed_data = {"compressed_text": output, "stats": stats}
            output_path = versioned_dir / "bsg_compressed.json"
            _write_json(output_path, compressed_data)
            print(f"✅ Compressed bsg written to {output_path.relative_to(root)}")
            print(f"   Tokens used: {stats['tokens_used']}/{stats['budget']}")
            if stats["truncated_files"] > 0:
                print(f"   Truncated files: {stats['truncated_files']}")
        elif args.mode == "full":
            output = bsg_map.render_full()
            # Save full mode as JSON with text content
            full_data = {"full_text": output}
            output_path = versioned_dir / "bsg_full.json"
            _write_json(output_path, full_data)
            print(f"✅ Full bsg written to {output_path.relative_to(root)}")
        elif args.mode == "hierarchical":
            output = bsg_map.render_hierarchical()
            # Save hierarchical mode as JSON with text content
            hierarchical_data = {"hierarchical_text": output}
            output_path = versioned_dir / "bsg_hierarchical.json"
            _write_json(output_path, hierarchical_data)
            print(f"✅ Hierarchical bsg written to {output_path.relative_to(root)}")
        else:
            print(f"❌ Unknown mode: {args.mode}")
            return 1
    except Exception as e:
        print(f"❌ Error rendering bsg: {e}")
        return 1

    return 0


def cmd_plugins_list(args: argparse.Namespace) -> int:
    """List available BSG plugins and their status."""
    from batho.bsg import list_builtin_plugins, load_effective_rules

    root = Path(args.root).resolve()
    if not root.exists() or not root.is_dir():
        print(f"❌ Root does not exist or is not a directory: {root}")
        return 1

    _ensure_runtime_logging()
    cfg = get_config_cached_for_root(root)
    rules_cfg = cfg.get("bsg", {}).get("rules", {})

    # Get builtin plugins
    builtin_available = list_builtin_plugins()
    builtin_requested = rules_cfg.get("builtin_plugins", ["bsg_core"])
    if not isinstance(builtin_requested, list):
        builtin_requested = []

    # Load effective rules to get actual loaded state
    try:
        effective_rules, load_stats = load_effective_rules(
            rules_config=rules_cfg,
            root_path=root,
        )
    except Exception as exc:
        print(f"❌ Failed to load rules: {exc}")
        return 1

    # Build plugin info
    loaded_plugins: dict[str, dict[str, Any]] = {}
    for rule in effective_rules:
        plugin_name = rule.plugin
        if plugin_name not in loaded_plugins:
            loaded_plugins[plugin_name] = {
                "name": plugin_name,
                "enabled": True,
                "rule_count": 0,
                "source": (
                    "custom_inline"
                    if plugin_name == "custom_inline"
                    else "custom_file" if plugin_name == "custom_file" else "builtin"
                ),
            }
        loaded_plugins[plugin_name]["rule_count"] += 1

    # Custom rules info
    custom_inline_count = load_stats.get("custom_inline_count", 0)
    custom_file_count = load_stats.get("custom_file_count", 0)
    custom_file_path = rules_cfg.get("custom_rules_path")

    payload = {
        "builtin_plugins_available": sorted(builtin_available),
        "builtin_plugins_requested": sorted(builtin_requested),
        "custom_inline_rules": custom_inline_count,
        "custom_file": custom_file_path,
        "custom_file_rules": custom_file_count,
        "loaded_plugins": sorted(loaded_plugins.values(), key=lambda x: x["name"]),
        "stats": {
            "total_plugins": len(loaded_plugins),
            "total_rules": load_stats.get("rules_loaded", 0),
            "builtin_plugins_loaded": load_stats.get("builtin_plugins_loaded", 0),
            "rules_disabled": load_stats.get("rules_disabled", 0),
            "cache_hit": load_stats.get("cache_hit", False),
        },
        "load_stats": load_stats,
    }

    if bool(args.verbose):
        # Include full load stats in verbose mode
        payload["verbose_stats"] = load_stats

    print(json.dumps(payload, indent=2))
    return 0


def cmd_plugins_validate(args: argparse.Namespace) -> int:
    """Validate a BSG plugin YAML file."""
    from batho.bsg import validate_plugin_file

    plugin_path = Path(args.plugin_file).resolve()

    result = validate_plugin_file(plugin_path)

    print(json.dumps(result, indent=2))

    return 0 if result["valid"] else 1


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="batho", description="Batho core CLI (index, stats, invalidate)"
    )

    # Version flag
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {batho_api.__version__}",
    )

    # Global logging flags (apply before subcommands)
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        default=None,
        help="Override log level from batho.yaml",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Suppress all non-error output",
    )
    parser.add_argument(
        "--log-json",
        action="store_true",
        help="Force JSON log output",
    )
    parser.add_argument(
        "--log-file",
        default=None,
        help="Write logs to file",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    idx = sub.add_parser("index", help="Index a repository")
    idx.add_argument("--root", required=True, help="Path to repo root")
    idx.add_argument(
        "--extensions",
        nargs="*",
        default=None,
        help="File extensions to include (e.g., .py .ts)",
    )
    idx.add_argument(
        "--max-workers", type=int, default=0, help="Worker threads (0=auto)"
    )
    idx.add_argument(
        "--max-file-size-kb", type=int, default=None, help="Max file size KB"
    )
    idx.add_argument("--force", action="store_true", help="Clear cache before indexing")
    idx.add_argument(
        "--no-ast-cache",
        action="store_true",
        help="Bypass AST cache for this run",
    )
    idx.add_argument(
        "--full",
        action="store_true",
        help="Force full rebuild (disable incremental path)",
    )
    idx.add_argument(
        "--base-snapshot",
        default=None,
        help="Optional base snapshot ID for incremental indexing",
    )
    idx.add_argument("--output-json", default=None, help="Path for graph.json output")
    idx.add_argument(
        "--metrics-output", default=None, help="Write metrics JSON to path"
    )
    idx.add_argument(
        "--snapshot", action="store_true", help="Write a snapshot after indexing"
    )
    idx.add_argument("--snapshot-label", default=None, help="Optional snapshot label")
    idx.add_argument("--verbose", action="store_true", help="Verbose output")
    idx.set_defaults(func=cmd_index)

    st = sub.add_parser("stats", help="Show current index stats")
    st.add_argument("--root", required=True, help="Path to repo root")
    st.set_defaults(func=cmd_stats)

    snap = sub.add_parser("snapshots", help="List snapshots")
    snap.add_argument("--root", required=True, help="Path to repo root")
    snap.set_defaults(func=cmd_snapshots)

    diff = sub.add_parser("diff-snapshots", help="Diff two snapshots")
    diff.add_argument("--root", required=True, help="Path to repo root")
    diff.add_argument("--snapshot-a", dest="snapshot_a", required=True)
    diff.add_argument("--snapshot-b", dest="snapshot_b", required=True)
    diff.set_defaults(func=cmd_diff_snapshots)

    patch = sub.add_parser(
        "patch",
        help="Incremental patch for changed files or diff (auto-uses snapshots when available)",
        epilog="When snapshots are available, automatically uses true incremental patching for better performance. Use --force-index-patch to use traditional reindexing.",
    )
    patch.add_argument("--root", required=True, help="Path to repo root")
    patch.add_argument("--diff", help="Path to unified diff file")
    patch.add_argument(
        "--scan", action="store_true", help="Auto-detect changes via file hash scan"
    )
    patch.add_argument(
        "--base-snapshot", help="Base snapshot ID for incremental patching"
    )
    patch.add_argument(
        "--force-index-patch",
        action="store_true",
        help="Force traditional index-based patching instead of incremental",
    )
    patch.add_argument(
        "--snapshot", action="store_true", help="Create snapshot after patching"
    )
    patch.add_argument(
        "--dry-run", action="store_true", help="Preview changes without applying them"
    )
    patch.add_argument(
        "--max-file-size-kb",
        type=int,
        default=500,
        help="Maximum file size in KB (default: 500)",
    )
    patch.add_argument("files", nargs="*", help="Changed files (absolute or relative)")
    patch.set_defaults(func=cmd_patch)

    # NEW: Patch management commands
    patches = sub.add_parser("patches", help="List patch operations")
    patches.add_argument("--root", required=True, help="Path to repo root")
    patches.add_argument(
        "--format", choices=["json", "timeline"], default="json", help="Output format"
    )
    patches.add_argument("--operation-type", help="Filter by operation type")
    patches.add_argument("--base-snapshot", help="Filter by base snapshot ID")
    patches.set_defaults(func=cmd_patches)

    patch_info = sub.add_parser(
        "patch-info", help="Show detailed patch operation information"
    )
    patch_info.add_argument("--root", required=True, help="Path to repo root")
    patch_info.add_argument("--patch-id", required=True, help="Patch operation ID")
    patch_info.add_argument(
        "--format", choices=["json", "summary"], default="json", help="Output format"
    )
    patch_info.set_defaults(func=cmd_patch_info)

    patch_chain = sub.add_parser("patch-chain", help="Show patch chain for a snapshot")
    patch_chain.add_argument("--root", required=True, help="Path to repo root")
    patch_chain.add_argument("--snapshot-id", required=True, help="Snapshot ID")
    patch_chain.add_argument("--full", action="store_true", help="Show full details")
    patch_chain.set_defaults(func=cmd_patch_chain)

    apply_patch = sub.add_parser(
        "apply-patch", help="Apply patch from diff file or cherry-pick"
    )
    apply_patch.add_argument("--root", required=True, help="Path to repo root")
    apply_patch.add_argument("--base-snapshot", required=True, help="Base snapshot ID")
    apply_patch.add_argument("--diff-file", help="Path to unified diff file")
    apply_patch.add_argument("--patch-id", help="Patch operation ID to cherry-pick")
    apply_patch.add_argument(
        "--dry-run", action="store_true", help="Preview without applying"
    )
    apply_patch.set_defaults(func=cmd_apply_patch)

    cherry_pick = sub.add_parser(
        "cherry-pick", help="Cherry-pick patch to different base snapshot"
    )
    cherry_pick.add_argument("--root", required=True, help="Path to repo root")
    cherry_pick.add_argument("--patch-id", required=True, help="Patch operation ID")
    cherry_pick.add_argument(
        "--target-snapshot", required=True, help="Target snapshot ID"
    )
    cherry_pick.add_argument(
        "--dry-run", action="store_true", help="Preview without applying"
    )
    cherry_pick.set_defaults(func=cmd_cherry_pick)

    hooks = sub.add_parser("hooks", help="Manage git hooks from .batho/hooks.yaml")
    hooks_sub = hooks.add_subparsers(dest="hooks_command", required=True)

    hooks_list = hooks_sub.add_parser(
        "list", help="List supported/configured hooks and templates"
    )
    hooks_list.add_argument(
        "--root",
        default=".",
        help="Path to repository root (default: current directory)",
    )
    hooks_list.set_defaults(func=cmd_hooks_list)

    hooks_status = hooks_sub.add_parser("status", help="Show hooks installation status")
    hooks_status.add_argument("--hook", default=None, help="Optional hook name")
    hooks_status.add_argument(
        "--root",
        default=".",
        help="Path to repository root (default: current directory)",
    )
    hooks_status.set_defaults(func=cmd_hooks_status)

    hooks_install = hooks_sub.add_parser(
        "install", help="Install managed scripts into .git/hooks"
    )
    hooks_install.add_argument("--hook", default=None, help="Install one hook by name")
    hooks_install.add_argument(
        "--all",
        action="store_true",
        help="Install all enabled hooks from config",
    )
    hooks_install.add_argument(
        "--force",
        action="store_true",
        help="Overwrite unmanaged collisions",
    )
    hooks_install.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview install actions without writing files",
    )
    hooks_install.add_argument(
        "--root",
        default=".",
        help="Path to repository root (default: current directory)",
    )
    hooks_install.set_defaults(func=cmd_hooks_install)

    hooks_remove = hooks_sub.add_parser(
        "remove", help="Remove managed scripts from .git/hooks"
    )
    hooks_remove.add_argument("--hook", default=None, help="Remove one hook by name")
    hooks_remove.add_argument(
        "--all",
        action="store_true",
        help="Remove all enabled hooks from config",
    )
    hooks_remove.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview removals without deleting files",
    )
    hooks_remove.add_argument(
        "--root",
        default=".",
        help="Path to repository root (default: current directory)",
    )
    hooks_remove.set_defaults(func=cmd_hooks_remove)

    hooks_run = hooks_sub.add_parser("run", help="Execute hook stages by hook name")
    hooks_run.add_argument("--hook", required=True, help="Hook name to execute")
    hooks_run.add_argument(
        "--root",
        default=".",
        help="Path to repository root (default: current directory)",
    )
    hooks_run.add_argument(
        "--dry-run",
        action="store_true",
        help="Print execution plan without running commands",
    )
    hooks_run.add_argument(
        "--verbose",
        action="store_true",
        help="Print stage-level execution status",
    )
    hooks_run.set_defaults(func=cmd_hooks_run)

    sync = sub.add_parser("sync", help="Sync artifacts to cloud endpoint")
    sync.add_argument(
        "--root",
        default=".",
        help="Path to repository root (default: current directory)",
    )
    sync.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be synced without uploading",
    )
    sync.add_argument(
        "--type",
        dest="artifact_types",
        action="append",
        default=None,
        help="Filter by artifact types (can specify multiple times)",
    )
    sync.add_argument(
        "--status",
        action="store_true",
        help="Show sync status and exit",
    )
    sync.add_argument(
        "--retry-failed",
        action="store_true",
        help="Retry previously failed uploads",
    )
    sync.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show detailed upload progress",
    )
    sync.set_defaults(func=cmd_sync)

    inv = sub.add_parser("invalidate", help="Clear file cache")
    inv.add_argument("--root", required=True, help="Path to repo root")
    inv.set_defaults(func=cmd_invalidate)

    # Cache commands
    cache = sub.add_parser("cache", help="AST cache management")
    cache_sub = cache.add_subparsers(dest="cache_command", required=True)

    cache_stats = cache_sub.add_parser("stats", help="Show cache statistics")
    cache_stats.set_defaults(func=cmd_cache_stats)

    cache_inv = cache_sub.add_parser("invalidate", help="Invalidate cache entries")
    cache_inv.add_argument(
        "pattern", nargs="?", default=None, help="Glob pattern to match (optional)"
    )
    cache_inv.set_defaults(func=cmd_cache_invalidate)

    cache_clr = cache_sub.add_parser("clear", help="Clear entire cache")
    cache_clr.set_defaults(func=cmd_cache_clear)

    storage = sub.add_parser("storage", help="Artifact registry management")
    storage_sub = storage.add_subparsers(dest="storage_command", required=True)

    storage_backfill = storage_sub.add_parser(
        "backfill",
        help="Register existing durable .ctn artifacts in the SQLite registry",
    )
    storage_backfill.add_argument("--root", required=True, help="Path to repo root")
    storage_backfill.set_defaults(func=cmd_storage_backfill)

    storage_verify = storage_sub.add_parser(
        "verify",
        help="Verify registry consistency and optionally repair metadata drift",
    )
    storage_verify.add_argument("--root", required=True, help="Path to repo root")
    storage_verify.add_argument(
        "--repair",
        action="store_true",
        help="Repair unregistered/missing metadata from disk",
    )
    storage_verify.set_defaults(func=cmd_storage_verify)

    storage_cleanup = storage_sub.add_parser(
        "cleanup",
        help="Apply retention cleanup (dry-run by default)",
    )
    storage_cleanup.add_argument("--root", required=True, help="Path to repo root")
    storage_cleanup.add_argument(
        "--apply",
        action="store_true",
        help="Apply deletions (default prints dry-run candidates)",
    )
    storage_cleanup.set_defaults(func=cmd_storage_cleanup)

    storage_stats = storage_sub.add_parser(
        "stats",
        help="Show registry and persisted graph cache statistics",
    )
    storage_stats.add_argument("--root", required=True, help="Path to repo root")
    storage_stats.add_argument(
        "--index-id",
        default=None,
        help="Optional index id for graph cache stats",
    )
    storage_stats.set_defaults(func=cmd_storage_stats)

    storage_rebuild_indexes = storage_sub.add_parser(
        "rebuild-indexes",
        help="Rebuild persisted query indexes from graph.json",
    )
    storage_rebuild_indexes.add_argument(
        "--root", required=True, help="Path to repo root"
    )
    storage_rebuild_indexes.add_argument(
        "--index-id",
        default=None,
        help="Optional index id to rebuild (default: current index)",
    )
    storage_rebuild_indexes.set_defaults(func=cmd_storage_rebuild_indexes)

    query = sub.add_parser("query", help="Query persisted graph indexes")
    query.add_argument("--root", required=True, help="Path to repo root")
    query.add_argument("--index-id", default=None, help="Optional index id to query")
    query.add_argument("--entity-type", default=None, help="Filter by entity type")
    query.add_argument("--file-path", default=None, help="Filter entities by file path")
    query.add_argument(
        "--relationship-type",
        default=None,
        help="Filter by relationship type",
    )
    query.add_argument("--limit", type=int, default=None, help="Result limit")
    query.add_argument(
        "--rebuild-index",
        action="store_true",
        help="Rebuild query index from graph.json before lookup",
    )
    query.set_defaults(func=cmd_query)

    # BSG command
    bsg = sub.add_parser("bsg", help="Render BSG in various formats")
    bsg.add_argument("--root", required=True, help="Path to repo root")
    bsg.add_argument(
        "--mode",
        choices=["compressed", "full", "hierarchical"],
        default="compressed",
        help="Rendering mode (default: compressed)",
    )
    bsg.add_argument(
        "--budget",
        type=int,
        default=12000,
        help="Token budget for compressed mode (default: 12000)",
    )
    bsg.set_defaults(func=cmd_bsg)

    # Plugins command
    plugins = sub.add_parser("plugins", help="BSG plugin management")
    plugins_sub = plugins.add_subparsers(dest="plugins_command", required=True)

    plugins_list = plugins_sub.add_parser("list", help="List available BSG plugins")
    plugins_list.add_argument("--root", required=True, help="Path to repo root")
    plugins_list.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show detailed plugin information",
    )
    plugins_list.set_defaults(func=cmd_plugins_list)

    plugins_validate = plugins_sub.add_parser(
        "validate", help="Validate a BSG plugin YAML file"
    )
    plugins_validate.add_argument(
        "plugin_file", help="Path to plugin YAML file to validate"
    )
    plugins_validate.set_defaults(func=cmd_plugins_validate)

    # v2 engine: fixture runner, strict validation, trace/profile
    from batho.bsg.plugins_cli import register_cli_subcommands as _register_bsg_plugin_subcommands

    _register_bsg_plugin_subcommands(plugins_sub)

    # Dashboard: local static server with dual-root serving
    from batho.cli.dashboard import register_cli_subcommands as _register_dashboard_subcommands

    _register_dashboard_subcommands(sub)

    return parser


# ---------------------------------------------------------------------------
# NEW: Patch Management CLI Commands (Phase 4)
# ---------------------------------------------------------------------------


def cmd_patches(args: argparse.Namespace) -> int:
    """List patch operations."""
    from batho.time_machine import list_patch_operations

    root = Path(args.root).resolve()
    ctn_dir = _ensure_ctn_dir(root)

    filters = {}
    if args.operation_type:
        filters["operation_type"] = args.operation_type
    if args.base_snapshot:
        filters["base_snapshot_id"] = args.base_snapshot

    patches = list_patch_operations(ctn_dir, filters)

    if args.format == "timeline":
        # Output as detailed timeline
        timeline = []
        for patch in patches:
            timeline.append(
                {
                    "operation_id": patch.operation_id,
                    "timestamp": patch.timestamp.isoformat(),
                    "operation_type": patch.operation_type,
                    "base_snapshot_id": patch.base_snapshot_id,
                    "new_snapshot_id": patch.new_snapshot_id,
                    "metrics": patch.metrics,
                    "patch_chain_length": len(patch.patch_chain),
                }
            )
        print(json.dumps(timeline, indent=2))
    else:
        # Output as JSON list
        output = []
        for patch in patches:
            output.append(patch.serialize())
        print(json.dumps(output, indent=2))

    return 0


def cmd_patch_info(args: argparse.Namespace) -> int:
    """Show detailed patch operation information."""
    from batho.time_machine import load_patch_operation

    root = Path(args.root).resolve()
    ctn_dir = _ensure_ctn_dir(root)

    operation = load_patch_operation(ctn_dir, args.patch_id)
    if not operation:
        print(f"❌ Patch operation {args.patch_id} not found")
        return 1

    if args.format == "summary":
        # Output as human-readable summary
        print(f"Patch Operation: {operation.operation_id}")
        print(f"Type: {operation.operation_type}")
        print(f"Timestamp: {operation.timestamp.isoformat()}")
        print(f"Base Snapshot: {operation.base_snapshot_id}")
        print(f"New Snapshot: {operation.new_snapshot_id}")
        print(f"Changes Applied: {len(operation.changes_applied)}")
        print(f"Patch Chain Length: {len(operation.patch_chain)}")
        print(f"Metrics: {operation.metrics}")
        print(f"User Info: {operation.user_info}")
    else:
        # Output as full JSON
        print(json.dumps(operation.serialize(), indent=2))

    return 0


def cmd_patch_chain(args: argparse.Namespace) -> int:
    """Show patch chain for a snapshot."""
    from batho.time_machine import get_patches_for_snapshot

    root = Path(args.root).resolve()
    ctn_dir = _ensure_ctn_dir(root)

    # Get patches that led to this snapshot
    patches = get_patches_for_snapshot(ctn_dir, args.snapshot_id)

    if not patches:
        print(f"❌ No patches found for snapshot {args.snapshot_id}")
        return 1

    if args.full:
        # Show full details
        chain_data = []
        for patch in patches:
            chain_data.append(patch.serialize())
        print(json.dumps(chain_data, indent=2))
    else:
        # Show simple chain
        chain_ids = [p.operation_id for p in patches]
        print(
            json.dumps(
                {
                    "snapshot_id": args.snapshot_id,
                    "patch_chain": chain_ids,
                    "chain_length": len(chain_ids),
                },
                indent=2,
            )
        )

    return 0


def cmd_apply_patch(args: argparse.Namespace) -> int:
    """Apply patch from diff file or cherry-pick."""
    from batho.time_machine import load_patch_operation, parse_unified_diff

    root = Path(args.root).resolve()
    ctn_dir = _ensure_ctn_dir(root)

    if args.diff_file and args.patch_id:
        print("❌ Cannot specify both --diff-file and --patch-id")
        return 1

    if args.diff_file:
        # Apply patch from diff file
        diff_path = Path(args.diff_file)
        if not diff_path.exists():
            print(f"❌ Diff file {args.diff_file} not found")
            return 1

        try:
            diff_content = diff_path.read_text(encoding="utf-8")
            changes = parse_unified_diff(diff_content)

            if args.dry_run:
                print(f"🔍 Dry run: Would apply {len(changes)} changes")
                for change in changes:
                    print(f"  {change.change_type.value}: {change.path}")
                return 0

            result = _resolve_incremental_patch()(ctn_dir, args.base_snapshot, changes)

            if result.get("success"):
                print(f"✅ Patch applied successfully")
                print(f"New snapshot: {result.get('new_snapshot_id')}")
                return 0
            else:
                ledger_entry = record_failure_rule(
                    ctn_dir=ctn_dir,
                    source="cli.apply_patch",
                    error_message=str(
                        result.get("error") or "patch application failed"
                    ),
                    changed_files=_extract_change_paths(changes),
                    context={
                        "base_snapshot_id": args.base_snapshot,
                        "mode": "diff_file",
                        "diff_file": args.diff_file,
                    },
                )
                print(f"❌ Patch application failed: {result.get('error')}")
                if ledger_entry.get("entry_id"):
                    print(f"   Evolution Ledger: {ledger_entry.get('entry_id')}")
                    print(f"   Don't rule: {ledger_entry.get('dont_rule')}")
                return 1

        except Exception as exc:
            record_failure_rule(
                ctn_dir=ctn_dir,
                source="cli.apply_patch",
                error_message=str(exc),
                changed_files=[str(args.diff_file)],
                context={
                    "base_snapshot_id": args.base_snapshot,
                    "mode": "diff_file",
                },
            )
            print(f"❌ Error reading diff file: {exc}")
            return 1

    elif args.patch_id:
        # Cherry-pick existing patch
        from batho.time_machine import apply_deltas_to_snapshot

        operation = load_patch_operation(ctn_dir, args.patch_id)
        if not operation:
            print(f"❌ Patch operation {args.patch_id} not found")
            return 1

        if args.dry_run:
            print(f"🔍 Dry run: Would cherry-pick patch {args.patch_id}")
            print(f"Changes: {len(operation.changes_applied)}")
            return 0

        deltas = extract_patch_deltas(operation)
        new_snapshot_id = apply_deltas_to_snapshot(ctn_dir, args.base_snapshot, deltas)

        if new_snapshot_id:
            print(f"✅ Cherry-pick applied successfully")
            print(f"New snapshot: {new_snapshot_id}")
            return 0
        else:
            ledger_entry = record_failure_rule(
                ctn_dir=ctn_dir,
                source="cli.apply_patch",
                error_message="cherry-pick failed while applying patch deltas",
                changed_files=_extract_change_paths(operation.changes_applied),
                context={
                    "base_snapshot_id": args.base_snapshot,
                    "patch_id": args.patch_id,
                    "mode": "patch_id",
                },
            )
            print("❌ Cherry-pick failed")
            if ledger_entry.get("entry_id"):
                print(f"   Evolution Ledger: {ledger_entry.get('entry_id')}")
                print(f"   Don't rule: {ledger_entry.get('dont_rule')}")
            return 1

    else:
        print("❌ Must specify either --diff-file or --patch-id")
        return 1


def cmd_cherry_pick(args: argparse.Namespace) -> int:
    """Cherry-pick patch to different base snapshot."""
    from batho.time_machine import apply_deltas_to_snapshot, load_patch_operation

    root = Path(args.root).resolve()
    ctn_dir = _ensure_ctn_dir(root)

    operation = load_patch_operation(ctn_dir, args.patch_id)
    if not operation:
        print(f"❌ Patch operation {args.patch_id} not found")
        return 1

    if args.dry_run:
        print(f"🔍 Dry run: Would cherry-pick patch {args.patch_id}")
        print(f"From: {operation.base_snapshot_id}")
        print(f"To: {args.target_snapshot}")
        print(f"Changes: {len(operation.changes_applied)}")
        return 0

    deltas = extract_patch_deltas(operation)
    new_snapshot_id = apply_deltas_to_snapshot(ctn_dir, args.target_snapshot, deltas)

    if new_snapshot_id:
        print(f"✅ Cherry-pick applied successfully")
        print(f"New snapshot: {new_snapshot_id}")
        return 0
    else:
        ledger_entry = record_failure_rule(
            ctn_dir=ctn_dir,
            source="cli.cherry_pick",
            error_message="cherry-pick failed while applying patch deltas",
            changed_files=_extract_change_paths(operation.changes_applied),
            context={
                "target_snapshot": args.target_snapshot,
                "patch_id": args.patch_id,
            },
        )
        print("❌ Cherry-pick failed")
        if ledger_entry.get("entry_id"):
            print(f"   Evolution Ledger: {ledger_entry.get('entry_id')}")
            print(f"   Don't rule: {ledger_entry.get('dont_rule')}")
        return 1


def extract_patch_deltas(operation) -> dict[str, Any]:
    """Extract reusable deltas from a patch operation."""
    return {
        "operation_id": operation.operation_id,
        "changes_applied": operation.changes_applied,
        "operation_type": operation.operation_type,
        "metrics": operation.metrics,
        "timestamp": operation.timestamp.isoformat(),
    }


def main(argv: list[str] | None = None) -> int:
    global _RUNTIME_LOGGING_INITIALIZED

    parser = build_parser()
    args = parser.parse_args(argv)

    # Determine target root directory for config resolution
    # Most commands have a --root argument, default to current directory
    target_root = getattr(args, "root", None)
    if target_root:
        target_root = Path(target_root).resolve()
    else:
        target_root = Path.cwd().resolve()

    # Auto-create batho.yaml if missing when --root is explicitly provided
    root_arg_provided = getattr(args, "root", None) is not None
    config_path = target_root / "batho.yaml"
    if root_arg_provided and not config_path.exists():
        # Only prompt in interactive terminal (skip in tests/CI)
        if sys.stdin.isatty():
            print(f"No batho.yaml found in {target_root}")
            response = (
                input("Would you like to create a default batho.yaml? [Y/n]: ")
                .strip()
                .lower()
            )
            if response in ("", "y", "yes"):
                try:
                    config_path.write_text(get_default_batho_yaml_content())
                    print(f"Created {config_path}")
                except Exception as e:
                    print(f"Warning: Could not create config file: {e}")
            else:
                print("Continuing without config file...")
        else:
            # Non-interactive mode: just continue with defaults
            pass

    # Load config with proper root resolution
    cfg = get_config_cached_for_root(target_root)

    cli_level = getattr(args, "log_level", None)
    cli_quiet = bool(getattr(args, "quiet", False))
    cli_log_json = bool(getattr(args, "log_json", False))
    cli_log_file = getattr(args, "log_file", None)

    resolved_level = cli_level if cli_level is not None else cfg["logging"]["level"]
    resolved_json = True if cli_log_json else cfg["logging"].get("json_format")
    resolved_quiet = cli_quiet or bool(cfg["logging"].get("quiet", False))
    resolved_file = (
        cli_log_file if cli_log_file is not None else cfg["logging"].get("file")
    )

    # CLI flags override config/env (quiet flag wins over log level threshold)
    log_config = {
        "level": resolved_level,
        "json_format": resolved_json,
        "quiet": resolved_quiet,
        "file": resolved_file,
        "format": cfg["logging"].get("format", "%(message)s"),
    }

    # Configure logging globally ONCE
    configure_logging(log_config)
    _RUNTIME_LOGGING_INITIALIZED = True
    _configure_cli_output(quiet=resolved_quiet, json_mode=bool(resolved_json))

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
