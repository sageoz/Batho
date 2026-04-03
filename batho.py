"""Batho Core CLI (indexing, stats, invalidate, webhook).

- Index: builds code graph and bsg, writes JSON/MD outputs without LLM or UniversalMemory.
- Stats: show current index metadata.
- Invalidate: clear file cache to force next full parse.
- Webhook Server: receive and process GitHub/GitLab webhook events.

Outputs (default):
- .ctn/<index_id>/graph.json       — Entities + relationships
- .ctn/<index_id>/bsg.json         — BSG structured data
- .ctn/<index_id>/architecture.md  — Hierarchical summary (optionally compressed)
- .ctn/index.json                  — Index metadata (current and history)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from batho_core.config import get_build_info, get_config_cached, reload_config
from batho_core.context.codegraph import CodeGraphIndexer, InMemoryGraph
from batho_core.context.languages.detector import default_detector
from batho_core.context.languages.registry import (
    get_extractor as registry_get_extractor,
)
from batho_core.context.bsg_map import BSGMap
from batho_core.context.stack_detector import detect_stack
from batho_core.time_machine import (
    generate_snapshot_id,
    create_snapshot,
    list_snapshots,
    load_snapshot,
    diff_snapshots,
    incremental_patch,
    list_snapshots,
    load_snapshot,
    webhook_stub,
    FileChangeTracker,
    FileChange,
    FileChangeType,
    FileChangeSummary,
    FileTrackingConfig,
    PatchOperation,
    compute_staleness,
)
from batho_core.webhook import WebhookServer, WebhookConfig
from batho_core.utils.file_io import read_file_bytes, write_atomically, _is_binary
from batho_core.utils.hash import compute_bytes_hash, compute_file_hash
from batho_core.utils.ignore import is_ignored, load_ignore_spec
from batho_core.utils.logging import configure_logging, get_logger

_read_file_content = read_file_bytes

LOGGER = get_logger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _generate_index_id() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"batho_{uuid.uuid4().hex}_{ts}"


def _ensure_ctn_dir(root: Path) -> Path:
    ctn_dir = root / get_config_cached()["paths"]["ctn_dir"]
    ctn_dir.mkdir(parents=True, exist_ok=True)
    return ctn_dir


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
    payload["schema_version"] = get_config_cached().get(
        "index_metadata_schema_version", "index-metadata.v1"
    )
    payload["_checksum"] = compute_bytes_hash(
        json.dumps(
            {k: v for k, v in payload.items() if k != "_checksum"}, sort_keys=True
        ).encode("utf-8")
    )
    write_atomically(index_path, payload, is_json=True)


def _write_json(path: Path, data: Any) -> None:
    """Write JSON data atomically."""
    write_atomically(path, data, is_json=True)


def _write_text(path: Path, content: str) -> None:
    """Write text content atomically."""
    write_atomically(path, content)


def _write_metrics(path: Path, payload: dict[str, Any]) -> None:
    """Write metrics data atomically as JSON."""
    write_atomically(path, payload, is_json=True)


def _estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text.encode("utf-8")) // 4)


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
    graph_path = ctn_dir / index_id / "graph.json"
    if not graph_path.exists():
        return None
    try:
        data = json.loads(graph_path.read_text(encoding="utf-8"))
        return InMemoryGraph.from_dict(data)
    except (json.JSONDecodeError, OSError):
        return None


def _strip_files(graph: InMemoryGraph, file_paths: Iterable[str]) -> None:
    targets = set(file_paths)
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
        _strip_files(graph, [filepath_str])
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
    from batho_core.utils.path_sanitizer import sanitize_diff_path, PathSecurityError
    
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
                parts = line.split(maxsplit=2)  # Limit splits to handle paths with spaces
                if len(parts) >= 2:
                    diff_path_str = parts[1]
            # Handle renamed files (old mode 100644 -> new mode 100644)
            elif line.startswith("rename from "):
                diff_path_str = line[12:]  # Remove "rename from " prefix
            elif line.startswith("rename to "):
                diff_path_str = line[10:]   # Remove "rename to " prefix
            # Handle similarity index lines
            elif line.startswith("similarity index ") or line.startswith("dissimilarity index "):
                continue  # Skip these lines
            # Handle binary file diffs
            elif "Binary files" in line and "differ" in line:
                # Extract paths from binary diff lines like "Binary files a/file and b/file differ"
                parts = line.split()
                if len(parts) >= 5 and parts[1].startswith("a/") and parts[3].startswith("b/"):
                    for i in [1, 3]:  # Both old and new paths
                        binary_path = parts[i][2:]  # Remove "a/" or "b/" prefix
                        if binary_path != "/dev/null":
                            try:
                                safe_path = sanitize_diff_path(binary_path, root)
                                if str(safe_path) not in seen_paths:
                                    paths.add(safe_path)
                                    seen_paths.add(str(safe_path))
                            except PathSecurityError:
                                LOGGER.warning("unsafe_binary_path_in_diff", diff_path=str(diff_path), line=line_num, path=binary_path)
                continue
            
            # Skip if we didn't find a valid path format
            if diff_path_str is None:
                continue
                
            # Additional validation
            if not diff_path_str or len(diff_path_str) > 1000:  # Reasonable length limit
                LOGGER.warning("invalid_diff_path_length", diff_path=str(diff_path), line=line_num, path=diff_path_str)
                continue
            
            # Skip /dev/null which represents deleted files
            if diff_path_str == "/dev/null" or diff_path_str == "dev/null":
                continue
            
            # Check for suspicious patterns before sanitization
            dangerous_patterns = [
                "..",  # Path traversal attempt
                "\0",  # Null bytes
                "~",   # Home directory expansion
                "$",   # Environment variable expansion
                "`",   # Command substitution
                "${",  # Environment variable expansion
                "$( ", # Command substitution
            ]
            
            if any(pattern in diff_path_str for pattern in dangerous_patterns):
                LOGGER.warning("dangerous_pattern_in_diff", diff_path=str(diff_path), line=line_num, path=diff_path_str)
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
                    LOGGER.warning("path_outside_root", diff_path=str(diff_path), line=line_num, path=diff_path_str)
                    continue
                
                # Check for extremely long paths after resolution
                if len(final_path_str) > 4096:  # Reasonable maximum path length
                    LOGGER.warning("path_too_long", diff_path=str(diff_path), line=line_num, path=final_path_str)
                    continue
                
                paths.add(safe_path)
                seen_paths.add(diff_path_str)
                
            except PathSecurityError as e:
                LOGGER.warning(
                    "unsafe_path_in_diff", 
                    diff_path=str(diff_path), 
                    line=line_num, 
                    path=diff_path_str,
                    error=str(e)
                )
                # Skip unsafe paths but continue processing others
                continue
                    
        except Exception as e:
            LOGGER.error("error_processing_diff_line", diff_path=str(diff_path), line=line_num, error=str(e))
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

    configure_logging(
        get_config_cached()["logging"]["level"], json_format=args.log_json
    )
    ctn_dir = _ensure_ctn_dir(root)

    cache_path = ctn_dir / "file_cache.json"
    indexer = CodeGraphIndexer(cache_path=str(cache_path), root=str(root))

    if args.force and cache_path.exists():
        cache_path.unlink()
        print("⚡ --force: cleared file cache")

    graph = indexer.build_graph(
        root=str(root),
        extensions=args.extensions,
        max_workers=args.max_workers,
        max_file_size_kb=args.max_file_size_kb,
        verbose=args.verbose,
    )

    if not graph.entities:
        print("⚠️  No entities extracted. Check source files and ignore patterns.")
        return 1

    bsg_map = BSGMap.build(graph, root=str(root))
    stack_info = detect_stack(root)
    token_input_estimate = bsg_map.estimate_tokens()

    index_id = _generate_index_id()
    versioned_dir = ctn_dir / index_id
    versioned_dir.mkdir(parents=True, exist_ok=True)

    context_dir = versioned_dir / "context"
    context_dir.mkdir(parents=True, exist_ok=True)

    with _ctn_lock(ctn_dir):
        # Outputs
        graph_path = (
            Path(args.output_json) if args.output_json else versioned_dir / "graph.json"
        )
        bsg_path = versioned_dir / "bsg.json"

        _write_json(graph_path, graph.to_dict())
        bsg_json = bsg_map.render_json()
        bsg_json["stack"] = stack_info
        _write_json(bsg_path, bsg_json)

        # Generate categorized markdown outputs
        timestamp = datetime.now(timezone.utc).isoformat()
        repo_name = root.name

        # overview.md - Full repository overview
        overview_content = bsg_map.render_overview(
            stack_info=stack_info,
            repo_name=repo_name,
            timestamp=timestamp,
        )
        _write_text(context_dir / "overview.md", overview_content)

        # architecture.md - Main codebase only (full entities)
        arch_content = bsg_map.render_category(
            "source", include_full_entities=True
        )
        _write_text(context_dir / "architecture.md", arch_content)

        # tests.md - Test files (summary format)
        tests_content = bsg_map.render_category(
            "tests", include_full_entities=False
        )
        _write_text(context_dir / "tests.md", tests_content)

        # docs.md - Uncategorized categories + Documentation files (summary format)
        uncategorized_content = bsg_map.render_uncategorized_categories(
            include_full_entities=False
        )
        docs_content = bsg_map.render_category(
            "docs", include_full_entities=False
        )
        
        # Combine uncategorized categories with docs
        combined_docs = uncategorized_content
        if combined_docs and docs_content.strip():
            combined_docs += "\n" + docs_content
        elif docs_content.strip():
            combined_docs = docs_content
            
        _write_text(context_dir / "docs.md", combined_docs)

        # config.md - Configuration files (summary format)
        config_content = bsg_map.render_category(
            "config", include_full_entities=False
        )
        _write_text(context_dir / "config.md", config_content)

        # Metadata
        metadata = _load_index_metadata(ctn_dir)
        prev_index_id = metadata.get("current_index_id")
        prev_entry = (
            metadata.get("indexes", {}).get(prev_index_id) if prev_index_id else None
        )
        repo_hash = _compute_repo_hash(root)
        stats = dict(indexer.stats)
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
                "architecture_md": str(
                    (context_dir / "architecture.md").relative_to(root)
                ),
                "tests_md": str((context_dir / "tests.md").relative_to(root)),
                "docs_md": str((context_dir / "docs.md").relative_to(root)),
                "config_md": str((context_dir / "config.md").relative_to(root)),
            },
            "stats": stats,
            "metrics": metrics,
            "build": get_build_info(),
            "schemas": get_config_cached().get("schemas", {}),
        }
        snapshot_id = None
        if args.snapshot:
            snapshot_id = create_snapshot(
                ctn_dir, root, graph, bsg_map, label=args.snapshot_label
            )
            entry["snapshot_id"] = snapshot_id
        metadata.setdefault("indexes", {})[index_id] = entry
        metadata["current_index_id"] = index_id
        _save_index_metadata(ctn_dir, metadata)

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
                _write_metrics(metrics_path_obj, metrics_payload)
            except OSError as exc:
                LOGGER.warning(
                    "metrics_write_failed", path=metrics_path, error=str(exc)
                )

    if stats.get("errors"):
        print(f"⚠️  Indexed with {stats['errors']} parse errors (partial success).")

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
    summary = {
        "loc_total": stats.get("loc_total") or metrics.get("loc_total"),
        "repo_size_bytes": stats.get("repo_size_bytes")
        or metrics.get("repo_size_bytes"),
        "compression_ratio": metrics.get("compression_ratio"),
        "cache_hit_rate": metrics.get("cache_hit_rate"),
    }
    print(
        json.dumps(
            {
                "summary": summary,
                "current": entry,
                "all_indexes": list(metadata.get("indexes", {}).keys()),
            },
            indent=2,
        )
    )
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


def _detect_file_changes(root: Path, files: list[Path], ctn_dir: Path, base_snapshot_id: str) -> list[FileChange]:
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
                changes.append(FileChange(
                    path=relative_path,
                    change_type=FileChangeType.DELETED,
                    old_hash=None,
                    new_hash=None,
                ))
        else:
            # File exists - check if it's new or modified
            relative_path = str(file_path.relative_to(root))
            current_hash = compute_file_hash(file_path)
            
            if relative_path in base_files:
                # File existed before - assume modified
                changes.append(FileChange(
                    path=relative_path,
                    change_type=FileChangeType.MODIFIED,
                    old_hash=None,  # Could be tracked if needed
                    new_hash=current_hash,
                    file_size=file_path.stat().st_size,
                    mtime=datetime.fromtimestamp(file_path.stat().st_mtime, timezone.utc),
                ))
            else:
                # New file
                changes.append(FileChange(
                    path=relative_path,
                    change_type=FileChangeType.ADDED,
                    old_hash=None,
                    new_hash=current_hash,
                    file_size=file_path.stat().st_size,
                    mtime=datetime.fromtimestamp(file_path.stat().st_mtime, timezone.utc),
                ))
    
    return changes


def _auto_detect_changes(root: Path, ctn_dir: Path, base_snapshot_id: str, max_file_size_kb: int) -> list[FileChange]:
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
            changes.append(FileChange(
                path=base_file,
                change_type=FileChangeType.DELETED,
                old_hash=None,
                new_hash=None,
            ))
    
    # Detect additions and modifications
    for current_file in current_files:
        full_path = root / current_file
        current_hash = compute_file_hash(full_path)
        
        if current_file in base_files:
            # File existed before - assume modified
            changes.append(FileChange(
                path=current_file,
                change_type=FileChangeType.MODIFIED,
                old_hash=None,
                new_hash=current_hash,
                file_size=full_path.stat().st_size,
                mtime=datetime.fromtimestamp(full_path.stat().st_mtime, timezone.utc),
            ))
        else:
            # New file
            changes.append(FileChange(
                path=current_file,
                change_type=FileChangeType.ADDED,
                old_hash=None,
                new_hash=current_hash,
                file_size=full_path.stat().st_size,
                mtime=datetime.fromtimestamp(full_path.stat().st_mtime, timezone.utc),
            ))
    
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

    cache_path = ctn_dir / "file_cache.json"
    indexer = CodeGraphIndexer(cache_path=str(cache_path), root=str(root))

    files: list[Path] = []

    if args.scan:
        hash_cache_path = ctn_dir / "file_hashes.json"
        tracker = FileChangeTracker(root)
        tracker.load(hash_cache_path)
        changes = tracker.scan_for_changes(max_file_size_kb=args.max_file_size_kb)
        deleted_paths = tracker.get_deleted_files(changes)
        if deleted_paths:
            _strip_files(graph, deleted_paths)
        files = tracker.get_changed_files(changes)
        if not files:
            print("No changes detected.")
            return 0
        tracker.save(hash_cache_path)
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

    if not files:
        print("No files to patch.")
        return 1

    if args.dry_run:
        print("Dry run mode - would apply changes to these files:")
        for f in files:
            print(f"  {f.relative_to(root)}")
        return 0

    patch_start = time.perf_counter()
    _reindex_files(root, files, indexer, graph)

    bsg_map = BSGMap.build(graph, root=str(root))
    versioned_dir = ctn_dir / current_id
    graph_path = versioned_dir / "graph.json"
    bsg_path = versioned_dir / "bsg.json"

    context_dir = versioned_dir / "context"
    context_dir.mkdir(parents=True, exist_ok=True)

    with _ctn_lock(ctn_dir):
        # Load metadata for stack info
        metadata = _load_index_metadata(ctn_dir)
        entry = metadata.get("indexes", {}).get(current_id, {})

        _write_json(graph_path, graph.to_dict())
        bsg_json = bsg_map.render_json()
        _write_json(bsg_path, bsg_json)

        # Generate categorized markdown outputs
        timestamp = datetime.now(timezone.utc).isoformat()
        repo_name = root.name

        # overview.md
        overview_content = bsg_map.render_overview(
            stack_info=entry.get("stack"),
            repo_name=repo_name,
            timestamp=timestamp,
        )
        _write_text(context_dir / "overview.md", overview_content)

        # architecture.md - Main codebase only
        arch_content = bsg_map.render_category(
            "source", include_full_entities=True
        )
        _write_text(context_dir / "architecture.md", arch_content)

        # tests.md
        tests_content = bsg_map.render_category(
            "tests", include_full_entities=False
        )
        _write_text(context_dir / "tests.md", tests_content)

        # docs.md - Uncategorized categories + Documentation files
        uncategorized_content = bsg_map.render_uncategorized_categories(
            include_full_entities=False
        )
        docs_content = bsg_map.render_category(
            "docs", include_full_entities=False
        )
        
        # Combine uncategorized categories with docs
        combined_docs = uncategorized_content
        if combined_docs and docs_content.strip():
            combined_docs += "\n" + docs_content
        elif docs_content.strip():
            combined_docs = docs_content
            
        _write_text(context_dir / "docs.md", combined_docs)

        # config.md
        config_content = bsg_map.render_category(
            "config", include_full_entities=False
        )
        _write_text(context_dir / "config.md", config_content)

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
        outputs["architecture_md"] = str(
            (context_dir / "architecture.md").relative_to(root)
        )
        outputs["tests_md"] = str((context_dir / "tests.md").relative_to(root))
        outputs["docs_md"] = str((context_dir / "docs.md").relative_to(root))
        outputs["config_md"] = str((context_dir / "config.md").relative_to(root))
        entry["schemas"] = dict(get_config_cached().get("schemas", {}))
        metadata.setdefault("indexes", {})[current_id] = entry
        _save_index_metadata(ctn_dir, metadata)

        snapshot_id = None
        if args.snapshot:
            snapshot_id = create_snapshot(ctn_dir, root, graph, bsg_map)
            entry["snapshot_id"] = snapshot_id
            metadata["indexes"][current_id] = entry
            _save_index_metadata(ctn_dir, metadata)

    summary = FileChangeSummary(
        total_changes=len(files),
        added=0,  # TODO: track these separately
        modified=len(files),
        deleted=0,
        unchanged=0,
        affected_files=[str(f.relative_to(root)) for f in files],
    )

    print(
        json.dumps(
            {
                "patched": summary.affected_files,
                "index_id": current_id,
                "summary": {
                    "total_changes": summary.total_changes,
                    "modified": summary.modified,
                },
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

    if args.scan:
        tracker = FileChangeTracker(root)
        hash_cache_path = ctn_dir / "file_hashes.json"
        tracker.load(hash_cache_path)
        changes = tracker.scan_for_changes(max_file_size_kb=args.max_file_size_kb)
        tracker.save(hash_cache_path)
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
            changes = _detect_file_changes(root, explicit_files, ctn_dir, args.base_snapshot)
        else:
            # Auto-detect changes by comparing current state with base snapshot
            changes = _auto_detect_changes(root, ctn_dir, args.base_snapshot, args.max_file_size_kb)
        
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
    result = incremental_patch(ctn_dir, args.base_snapshot, changes)

    if not result["success"]:
        error_msg = result.get("error", "Unknown error")
        LOGGER.error("incremental_patch_failed", 
                    error=error_msg, 
                    operation_id=result.get("operation_id"),
                    changes_count=len(changes))
        print(
            json.dumps(
                {"error": result["error"], "operation_id": result.get("operation_id")},
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
                "final_snapshot_id": final_snapshot_id
                if args.snapshot
                else result["new_snapshot_id"],
            },
            indent=2,
        )
    )
    return 0


def cmd_webhook(args: argparse.Namespace) -> int:
    try:
        payload = json.loads(args.payload)
    except json.JSONDecodeError:
        print("❌ Invalid JSON payload")
        return 1

    try:
        headers = json.loads(getattr(args, "headers", "{}") or "{}")
        if not isinstance(headers, dict):
            raise ValueError("headers must be a JSON object")
    except Exception:
        print("❌ Invalid headers JSON")
        return 1

    result = webhook_stub(payload, headers=headers)
    print(json.dumps(result, indent=2))
    return 0 if result.get("status") != "error" else 1


def cmd_webhook_server(args: argparse.Namespace) -> int:
    """Start webhook server for continuous processing."""
    config_path = Path("batho.yaml")
    if not config_path.exists():
        print("❌ Root config file not found: ./batho.yaml")
        return 1

    try:
        full_config = reload_config()
        config = WebhookConfig.from_dict(full_config.get("webhook") or {})
    except Exception as e:
        print(f"❌ Failed to load webhook config from ./batho.yaml: {e}")
        return 1
    
    # Validate repository configuration
    if not config.repository:
        print("❌ Repository not configured")
        return 1
    
    # Get repository path
    repo_path = Path(args.root or ".").resolve()
    if not repo_path.exists():
        print(f"❌ Repository path does not exist: {repo_path}")
        return 1
    
    print(f"🚀 Starting webhook server for {config.repository.name}")
    print(f"   Platform: {config.repository.platform}")
    print(
        f"   Endpoint: http://{config.server.host}:{config.server.port}{config.server.endpoint}"
    )
    print(
        f"   Health: http://{config.server.host}:{config.server.port}{config.server.health_endpoint}"
    )
    print(f"   Repository: {repo_path}")
    print()
    
    # Start server
    server = WebhookServer(config, repo_path)
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n🛑 Shutting down webhook server...")
        server.stop()
        print("✅ Server stopped")
    
    return 0


def cmd_invalidate(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    ctn_dir = _ensure_ctn_dir(root)
    cache_path = ctn_dir / "file_cache.json"
    if cache_path.exists():
        cache_path.unlink()
        print("✅ Cleared file cache")
    else:
        print("(cache already clear)")
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

    bsg_map = BSGMap.build(graph, root=str(root))

    # Render based on mode
    try:
        versioned_dir = ctn_dir / current_id
        
        if args.mode == "compressed":
            output, stats = bsg_map.render_compressed(budget=args.budget, fail_on_overflow=False)
            # Save compressed output with stats as JSON
            compressed_data = {
                "compressed_text": output,
                "stats": stats
            }
            output_path = versioned_dir / "bsg_compressed.json"
            _write_json(output_path, compressed_data)
            print(f"✅ Compressed bsg written to {output_path.relative_to(root)}")
            print(f"   Tokens used: {stats['tokens_used']}/{stats['budget']}")
            if stats['truncated_files'] > 0:
                print(f"   Truncated files: {stats['truncated_files']}")
        elif args.mode == "full":
            output = bsg_map.render_full()
            # Save full mode as JSON with text content
            full_data = {
                "full_text": output
            }
            output_path = versioned_dir / "bsg_full.json"
            _write_json(output_path, full_data)
            print(f"✅ Full bsg written to {output_path.relative_to(root)}")
        elif args.mode == "hierarchical":
            output = bsg_map.render_hierarchical()
            # Save hierarchical mode as JSON with text content
            hierarchical_data = {
                "hierarchical_text": output
            }
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


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="batho", description="Batho core CLI (index, stats, invalidate)"
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
    idx.add_argument("--output-json", default=None, help="Path for graph.json output")
    idx.add_argument(
        "--metrics-output", default=None, help="Write metrics JSON to path"
    )
    idx.add_argument(
        "--snapshot", action="store_true", help="Write a snapshot after indexing"
    )
    idx.add_argument("--snapshot-label", default=None, help="Optional snapshot label")
    idx.add_argument("--verbose", action="store_true", help="Verbose output")
    idx.add_argument(
        "--log-json",
        action="store_true",
        help="Emit logs in JSON instead of color console",
    )
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
    epilog="When snapshots are available, automatically uses true incremental patching for better performance. Use --force-index-patch to use traditional reindexing."
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
        "--force-index-patch", action="store_true", 
        help="Force traditional index-based patching instead of incremental"
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
    patches.add_argument("--format", choices=["json", "timeline"], default="json", help="Output format")
    patches.add_argument("--operation-type", help="Filter by operation type")
    patches.add_argument("--base-snapshot", help="Filter by base snapshot ID")
    patches.set_defaults(func=cmd_patches)

    patch_info = sub.add_parser("patch-info", help="Show detailed patch operation information")
    patch_info.add_argument("--root", required=True, help="Path to repo root")
    patch_info.add_argument("--patch-id", required=True, help="Patch operation ID")
    patch_info.add_argument("--format", choices=["json", "summary"], default="json", help="Output format")
    patch_info.set_defaults(func=cmd_patch_info)

    patch_chain = sub.add_parser("patch-chain", help="Show patch chain for a snapshot")
    patch_chain.add_argument("--root", required=True, help="Path to repo root")
    patch_chain.add_argument("--snapshot-id", required=True, help="Snapshot ID")
    patch_chain.add_argument("--full", action="store_true", help="Show full details")
    patch_chain.set_defaults(func=cmd_patch_chain)

    apply_patch = sub.add_parser("apply-patch", help="Apply patch from diff file or cherry-pick")
    apply_patch.add_argument("--root", required=True, help="Path to repo root")
    apply_patch.add_argument("--base-snapshot", required=True, help="Base snapshot ID")
    apply_patch.add_argument("--diff-file", help="Path to unified diff file")
    apply_patch.add_argument("--patch-id", help="Patch operation ID to cherry-pick")
    apply_patch.add_argument("--dry-run", action="store_true", help="Preview without applying")
    apply_patch.set_defaults(func=cmd_apply_patch)

    cherry_pick = sub.add_parser("cherry-pick", help="Cherry-pick patch to different base snapshot")
    cherry_pick.add_argument("--root", required=True, help="Path to repo root")
    cherry_pick.add_argument("--patch-id", required=True, help="Patch operation ID")
    cherry_pick.add_argument("--target-snapshot", required=True, help="Target snapshot ID")
    cherry_pick.add_argument("--dry-run", action="store_true", help="Preview without applying")
    cherry_pick.set_defaults(func=cmd_cherry_pick)

    wh = sub.add_parser("webhook", help="Validate webhook payload parsing")
    wh.add_argument("--payload", required=True, help="JSON payload string")
    wh.add_argument(
        "--headers",
        default="{}",
        help="Optional JSON headers (e.g. {'X-GitHub-Event':'push'})",
    )
    wh.set_defaults(func=cmd_webhook)

    inv = sub.add_parser("invalidate", help="Clear file cache")
    inv.add_argument("--root", required=True, help="Path to repo root")
    inv.set_defaults(func=cmd_invalidate)

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

    ws = sub.add_parser("webhook-server", help="Start webhook server using ./batho.yaml")
    ws.add_argument("--root", help="Path to repository root (default: current directory)")
    ws.set_defaults(func=cmd_webhook_server)

    return parser


# ---------------------------------------------------------------------------
# NEW: Patch Management CLI Commands (Phase 4)
# ---------------------------------------------------------------------------

def cmd_patches(args: argparse.Namespace) -> int:
    """List patch operations."""
    from batho_core.time_machine import list_patch_operations
    
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
            timeline.append({
                "operation_id": patch.operation_id,
                "timestamp": patch.timestamp.isoformat(),
                "operation_type": patch.operation_type,
                "base_snapshot_id": patch.base_snapshot_id,
                "new_snapshot_id": patch.new_snapshot_id,
                "metrics": patch.metrics,
                "patch_chain_length": len(patch.patch_chain),
            })
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
    from batho_core.time_machine import load_patch_operation
    
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
    from batho_core.time_machine import get_patches_for_snapshot
    
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
        print(json.dumps({
            "snapshot_id": args.snapshot_id,
            "patch_chain": chain_ids,
            "chain_length": len(chain_ids)
        }, indent=2))
    
    return 0


def cmd_apply_patch(args: argparse.Namespace) -> int:
    """Apply patch from diff file or cherry-pick."""
    from batho_core.time_machine import parse_unified_diff, load_patch_operation
    
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
            
            result = incremental_patch(ctn_dir, args.base_snapshot, changes)
            
            if result.get("success"):
                print(f"✅ Patch applied successfully")
                print(f"New snapshot: {result.get('new_snapshot_id')}")
                return 0
            else:
                print(f"❌ Patch application failed: {result.get('error')}")
                return 1
                
        except Exception as exc:
            print(f"❌ Error reading diff file: {exc}")
            return 1
    
    elif args.patch_id:
        # Cherry-pick existing patch
        from batho_core.time_machine import apply_deltas_to_snapshot
        
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
            print("❌ Cherry-pick failed")
            return 1
    
    else:
        print("❌ Must specify either --diff-file or --patch-id")
        return 1


def cmd_cherry_pick(args: argparse.Namespace) -> int:
    """Cherry-pick patch to different base snapshot."""
    from batho_core.time_machine import load_patch_operation, apply_deltas_to_snapshot
    
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
        print("❌ Cherry-pick failed")
        return 1


def extract_patch_deltas(operation) -> dict[str, Any]:
    """Extract reusable deltas from a patch operation."""
    return {
        'operation_id': operation.operation_id,
        'changes_applied': operation.changes_applied,
        'operation_type': operation.operation_type,
        'metrics': operation.metrics,
        'timestamp': operation.timestamp.isoformat(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
