"""Batho Core CLI (indexing, stats, invalidate).

- Index: builds code graph, repomap, writes JSON/MD outputs without LLM or UniversalMemory.
- Stats: show current index metadata.
- Invalidate: clear file cache to force next full parse.

Outputs (default):
- .ctn/<index_id>/graph.json       — Entities + relationships
- .ctn/<index_id>/repomap.json     — RepoMap structured data
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

from batho_core.config import get_build_info, get_config_cached
from batho_core.context.categorizer import FileCategory
from batho_core.context.codegraph import CodeGraphIndexer, InMemoryGraph
from batho_core.context.languages.detector import default_detector
from batho_core.context.languages.registry import (
    get_extractor as registry_get_extractor,
)
from batho_core.context.repomap import RepoMap
from batho_core.context.c4_generator import C4Generator
from batho_core.context.c4_structurizr import StructurizrFormatter
from batho_core.context.stack_detector import detect_stack
from batho_core.time_machine import (
    compute_staleness,
    create_snapshot,
    diff_snapshots,
    list_snapshots,
    load_snapshot,
    webhook_stub,
)
from batho_core.utils.file_io import read_file_bytes, write_atomically
from batho_core.utils.hash import compute_bytes_hash
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
        json.dumps({k: v for k, v in payload.items() if k != "_checksum"}, sort_keys=True).encode(
            "utf-8"
        )
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


def _collect_repo_metrics(root: Path, max_file_size_kb: int | None = None) -> dict[str, Any]:
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
        metrics = entry.get("metrics", {}) if isinstance(entry.get("metrics"), dict) else {}
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
    remove_ids = {eid for eid, ent in list(graph.entities.items()) if ent.file in targets}
    graph.entities = {eid: ent for eid, ent in graph.entities.items() if ent.file not in targets}
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
    paths: set[Path] = set()
    try:
        text = diff_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    for line in text.splitlines():
        if line.startswith("+++ b/") or line.startswith("--- a/"):
            parts = line.split()
            if len(parts) < 2:
                continue
            p = parts[1].replace("b/", "").replace("a/", "")
            if p == "/dev/null":
                continue
            paths.add(root / p)
    return sorted(paths)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_index(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    if not root.exists() or not root.is_dir():
        print(f"❌ Root does not exist or is not a directory: {root}")
        return 1

    configure_logging(get_config_cached()["logging"]["level"], json_format=args.log_json)
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

    repomap = RepoMap.build(graph, root=str(root))
    stack_info = detect_stack(root)
    token_input_estimate = repomap.estimate_tokens()

    index_id = _generate_index_id()
    versioned_dir = ctn_dir / index_id
    versioned_dir.mkdir(parents=True, exist_ok=True)

    context_dir = versioned_dir / "context"
    context_dir.mkdir(parents=True, exist_ok=True)

    with _ctn_lock(ctn_dir):
        # Outputs
        graph_path = Path(args.output_json) if args.output_json else versioned_dir / "graph.json"
        repomap_path = versioned_dir / "repomap.json"

        _write_json(graph_path, graph.to_dict())
        repomap_json = repomap.render_json()
        repomap_json["stack"] = stack_info
        _write_json(repomap_path, repomap_json)

        # Generate categorized markdown outputs
        timestamp = datetime.now(timezone.utc).isoformat()
        repo_name = root.name

        # overview.md - Full repository overview
        overview_content = repomap.render_overview(
            stack_info=stack_info,
            repo_name=repo_name,
            timestamp=timestamp,
        )
        _write_text(context_dir / "overview.md", overview_content)

        # architecture.md - Main codebase only (full entities)
        arch_content = repomap.render_category(FileCategory.SOURCE, include_full_entities=True)
        _write_text(context_dir / "architecture.md", arch_content)

        # tests.md - Test files (summary format)
        tests_content = repomap.render_category(FileCategory.TESTS, include_full_entities=False)
        _write_text(context_dir / "tests.md", tests_content)

        # docs.md - Documentation files (summary format)
        docs_content = repomap.render_category(FileCategory.DOCS, include_full_entities=False)
        _write_text(context_dir / "docs.md", docs_content)

        # config.md - Configuration files (summary format)
        config_content = repomap.render_category(FileCategory.CONFIG, include_full_entities=False)
        _write_text(context_dir / "config.md", config_content)

        # Metadata
        metadata = _load_index_metadata(ctn_dir)
        prev_index_id = metadata.get("current_index_id")
        prev_entry = metadata.get("indexes", {}).get(prev_index_id) if prev_index_id else None
        repo_hash = _compute_repo_hash(root)
        stats = dict(indexer.stats)
        cache_hit_rate = 0.0
        parsed = int(stats.get("files_parsed", 0))
        cached = int(stats.get("files_cached", 0))
        if parsed > 0:
            cache_hit_rate = round(cached / parsed, 4)
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
            "file_count": len(repomap._by_file),
            "entity_count": repomap.entity_count,
            "relationship_count": len(graph.relationships),
            "repo_hash": repo_hash,
            "staleness_score": compute_staleness(prev_entry, repo_hash, stats),
            "stack": stack_info,
            "outputs": {
                "graph_json": str(graph_path.relative_to(root)),
                "repomap_json": str(repomap_path.relative_to(root)),
                "overview_md": str((context_dir / "overview.md").relative_to(root)),
                "architecture_md": str((context_dir / "architecture.md").relative_to(root)),
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
            snapshot_id = create_snapshot(ctn_dir, root, graph, repomap, label=args.snapshot_label)
            entry["snapshot_id"] = snapshot_id
        metadata.setdefault("indexes", {})[index_id] = entry
        metadata["current_index_id"] = index_id
        _save_index_metadata(ctn_dir, metadata)

        metrics_path = args.metrics_output or get_config_cached().get("indexer", {}).get(
            "metrics_output"
        )
        if metrics_path:
            metrics_payload = {
                "index_id": index_id,
                "timestamp": entry["timestamp"],
                "root": str(root),
                "stats": stats,
                "stack": stack_info,
                "metrics": metrics,
            }
            try:
                _write_metrics(Path(metrics_path), metrics_payload)
            except OSError as exc:
                LOGGER.warning("metrics_write_failed", path=metrics_path, error=str(exc))
        
        # Generate C4 model if not disabled
        if not args.no_c4:
            try:
                if args.verbose:
                    print("🏗️  Generating C4 model...")
                
                generator = C4Generator(ctn_dir, index_id)
                c4_model = generator.generate_c4_model()
                
                # Format as Structurizr JSON
                formatter = StructurizrFormatter(
                    workspace_name=c4_model["name"],
                    workspace_description=c4_model["description"]
                )
                
                # Add all model elements
                for person in c4_model["model"]["people"]:
                    formatter.add_person(person)
                
                for system in c4_model["model"]["softwareSystems"]:
                    formatter.add_software_system(system)
                
                for container in c4_model["model"]["containers"]:
                    formatter.add_container(container)
                
                for component in c4_model["model"]["components"]:
                    formatter.add_component(component)
                
                # Add views
                for view in c4_model["views"]["systemContext"]:
                    formatter.add_system_context_view(view)
                
                for view in c4_model["views"]["container"]:
                    formatter.add_container_view(view)
                
                for view in c4_model["views"]["component"]:
                    formatter.add_component_view(view)
                
                # Add LLM extensions
                formatter.add_llm_extensions(c4_model["llm_extensions"])
                
                # Add styling
                formatter.add_styling()
                
                # Write C4 model
                c4_path = versioned_dir / "c4-model.json"
                formatter.save_to_file(str(c4_path))
                
                # Update entry with C4 output
                entry["outputs"]["c4_model"] = str(c4_path.relative_to(root))
                metadata["indexes"][index_id] = entry
                _save_index_metadata(ctn_dir, metadata)
                
                if args.verbose:
                    print(f"   C4 model: {c4_path.relative_to(root)}")
                    print(f"   Systems: {len(c4_model['model']['softwareSystems'])}")
                    print(f"   Containers: {len(c4_model['model']['containers'])}")
                    print(f"   Components: {len(c4_model['model']['components'])}")
                
            except Exception as e:
                LOGGER.warning("c4_generation_failed", error=str(e))
                if args.verbose:
                    print(f"⚠️  C4 generation failed: {e}")

    if stats.get("errors"):
        print(f"⚠️  Indexed with {stats['errors']} parse errors (partial success).")

    if args.verbose:
        print(f"✅ Indexed {root} → {index_id}")
        print(f"   Entities: {entry['entity_count']}, Relationships: {entry['relationship_count']}")
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
        "repo_size_bytes": stats.get("repo_size_bytes") or metrics.get("repo_size_bytes"),
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


def cmd_patch(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    ctn_dir = _ensure_ctn_dir(root)
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
    if args.diff:
        files.extend(_files_from_diff(Path(args.diff), root))
    if args.files:
        files.extend(
            Path(f).resolve() if not Path(f).is_absolute() else Path(f) for f in args.files
        )
    files = sorted({f for f in files if f.exists()})

    patch_start = time.perf_counter()
    _reindex_files(root, files, indexer, graph)

    repomap = RepoMap.build(graph, root=str(root))
    versioned_dir = ctn_dir / current_id
    graph_path = versioned_dir / "graph.json"
    repomap_path = versioned_dir / "repomap.json"

    context_dir = versioned_dir / "context"
    context_dir.mkdir(parents=True, exist_ok=True)

    with _ctn_lock(ctn_dir):
        # Load metadata for stack info
        metadata = _load_index_metadata(ctn_dir)
        entry = metadata.get("indexes", {}).get(current_id, {})
        
        _write_json(graph_path, graph.to_dict())
        repomap_json = repomap.render_json()
        _write_json(repomap_path, repomap_json)

        # Generate categorized markdown outputs
        timestamp = datetime.now(timezone.utc).isoformat()
        repo_name = root.name

        # overview.md
        overview_content = repomap.render_overview(
            stack_info=entry.get("stack"),
            repo_name=repo_name,
            timestamp=timestamp,
        )
        _write_text(context_dir / "overview.md", overview_content)

        # architecture.md - Main codebase only
        arch_content = repomap.render_category(FileCategory.SOURCE, include_full_entities=True)
        _write_text(context_dir / "architecture.md", arch_content)

        # tests.md
        tests_content = repomap.render_category(FileCategory.TESTS, include_full_entities=False)
        _write_text(context_dir / "tests.md", tests_content)

        # docs.md
        docs_content = repomap.render_category(FileCategory.DOCS, include_full_entities=False)
        _write_text(context_dir / "docs.md", docs_content)

        # config.md
        config_content = repomap.render_category(FileCategory.CONFIG, include_full_entities=False)
        _write_text(context_dir / "config.md", config_content)

        # Update metadata entry
        entry = metadata.get("indexes", {}).get(current_id, {})
        prev_stats = entry.get("stats", {}) if isinstance(entry, dict) else {}
        repo_hash = _compute_repo_hash(root)
        token_input_estimate = repomap.estimate_tokens()
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
                "entity_count": repomap.entity_count,
                "relationship_count": len(graph.relationships),
                "repo_hash": repo_hash,
                "staleness_score": compute_staleness(entry, repo_hash, indexer.stats),
                "stats": merged_stats,
                "metrics": metrics,
            }
        )
        entry.setdefault("outputs", {})["overview_md"] = str(
            (context_dir / "overview.md").relative_to(root)
        )
        entry.setdefault("outputs", {})["architecture_md"] = str(
            (context_dir / "architecture.md").relative_to(root)
        )
        entry.setdefault("outputs", {})["tests_md"] = str(
            (context_dir / "tests.md").relative_to(root)
        )
        entry.setdefault("outputs", {})["docs_md"] = str(
            (context_dir / "docs.md").relative_to(root)
        )
        entry.setdefault("outputs", {})["config_md"] = str(
            (context_dir / "config.md").relative_to(root)
        )
        entry.setdefault("schemas", get_config_cached().get("schemas", {}))
        metadata.setdefault("indexes", {})[current_id] = entry
        _save_index_metadata(ctn_dir, metadata)

    print(json.dumps({"patched": [str(f) for f in files], "index_id": current_id}, indent=2))
    return 0


def cmd_webhook(args: argparse.Namespace) -> int:
    try:
        payload = json.loads(args.payload)
    except json.JSONDecodeError:
        print("❌ Invalid JSON payload")
        return 1
    result = webhook_stub(payload)
    print(json.dumps(result, indent=2))
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


def cmd_c4(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    if not root.exists() or not root.is_dir():
        print(f"❌ Root does not exist or is not a directory: {root}")
        return 1

    configure_logging(get_config_cached()["logging"]["level"], json_format=args.log_json)
    ctn_dir = _ensure_ctn_dir(root)
    
    # Load current index
    metadata = _load_index_metadata(ctn_dir)
    current_id = metadata.get("current_index_id")
    
    if not current_id:
        print("❌ No index found. Run 'batho index' first.")
        return 1
    
    try:
        # Generate C4 model with new rule system options
        generator = C4Generator(
            ctn_dir, 
            current_id, 
            rules_dir=getattr(args, 'rules_dir', None)
        )
        
        # Override language detection if specified
        if getattr(args, 'language', None):
            generator.primary_language = args.language
            # Regenerate dynamic rules with overridden language
            if not getattr(args, 'no_dynamic_rules', False):
                generator.rule_engine.generate_dynamic_rules(generator.graph, generator.repomap)
        
        # Apply granularity override if specified
        if getattr(args, 'granularity', None):
            from batho_core.context.c4.granularity.engine import GranularityLevel
            override_level = GranularityLevel(args.granularity)
            generator.granularity_decision = generator.granularity_engine.decide_granularity(
                generator.repository_metrics,
                override=override_level
            )
            print(f"🎯 Applied granularity override: {args.granularity}")
        
        # Apply grouping strategy if specified
        if getattr(args, 'grouping_strategy', None):
            from batho_core.context.c4.granularity.grouping import GroupingStrategy
            strategy = GroupingStrategy(args.grouping_strategy)
            generator.granularity_decision.settings["grouping_strategy"] = strategy.value
            generator.granularity_decision.settings["group_components"] = True
            print(f"📦 Applied grouping strategy: {args.grouping_strategy}")
        
        # Apply importance threshold if specified
        if getattr(args, 'importance_threshold', None) and args.importance_threshold > 0:
            generator.granularity_decision.settings["importance_threshold"] = args.importance_threshold
            generator.granularity_decision.settings["filter_by_importance"] = True
            print(f"⭐ Applied importance threshold: {args.importance_threshold}")
        
        # Apply max components limit if specified
        if getattr(args, 'max_components', None):
            generator.granularity_decision.settings["max_components"] = args.max_components
            print(f"🔢 Applied max components limit: {args.max_components}")
        
        # Configure pattern detectors
        enable_detectors = getattr(args, 'enable_detectors', None)
        disable_detectors = getattr(args, 'disable_detectors', None)
        
        if enable_detectors or disable_detectors:
            # Re-run detection with specific detectors
            all_rules = generator.rule_engine.rule_loader.load_all_rules()
            generator._detection_results = generator.detector_registry.detect_all(
                generator.graph,
                generator.repomap,
                all_rules,
                detector_names=enable_detectors
            )
        
        c4_model = generator.generate_c4_model()
        
        # Determine output format and formatter
        output_format = getattr(args, 'output_format', 'json')
        
        if output_format == 'json':
            # Use Structurizr JSON formatter
            from batho_core.context.c4_structurizr import StructurizrFormatter
            formatter = StructurizrFormatter(
                workspace_name=c4_model["name"],
                workspace_description=c4_model["description"]
            )
            
            # Add all model elements
            for person in c4_model["model"]["people"]:
                formatter.add_person(person)
            
            for system in c4_model["model"]["softwareSystems"]:
                formatter.add_software_system(system)
            
            for container in c4_model["model"]["containers"]:
                formatter.add_container(container)
            
            for component in c4_model["model"]["components"]:
                formatter.add_component(component)
            
            # Add views
            for view in c4_model["views"]["systemContext"]:
                formatter.add_system_context_view(view)
            
            for view in c4_model["views"]["container"]:
                formatter.add_container_view(view)
            
            for view in c4_model["views"]["component"]:
                formatter.add_component_view(view)
            
            # Add LLM extensions
            formatter.add_llm_extensions(c4_model["llm_extensions"])
            
            # Add styling
            formatter.add_styling()
            
            # Get formatted output
            output_content = formatter.to_json()
            
        else:
            # Use new format registry
            from batho_core.context.c4.formatters import get_format_registry
            from batho_core.context.c4.formatters.base import FormatConfig
            
            registry = get_format_registry()
            
            # Build formatter configuration
            config = {
                "theme": getattr(args, 'theme', None),
                "split_threshold": getattr(args, 'split_threshold', None),
                "include_relationships": True,
                "include_descriptions": True,
                "custom_options": {}
            }
            
            # Add format-specific options
            if output_format == 'plantuml':
                config["custom_options"]["include_sprites"] = True
            elif output_format == 'interactive':
                config["custom_options"]["default_zoom"] = 0.8
                config["custom_options"]["show_minimap"] = True
                config["custom_options"]["enable_search"] = True
            elif output_format == 'mermaid':
                config["custom_options"]["collapsible"] = True
            
            # Get formatter and format model
            formatter = registry.get_formatter(output_format, config)
            output_content = formatter.format_model(c4_model)
        
        # Determine output path
        if args.output:
            output_path = Path(args.output)
        else:
            # Default based on format
            format_extensions = {
                'json': 'json',
                'plantuml': 'puml',
                'mermaid': 'mmd',
                'interactive': 'html',
                'd2': 'd2'
            }
            ext = format_extensions.get(output_format, 'txt')
            output_path = ctn_dir / current_id / f"c4-model.{ext}"
        
        # Write output
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(output_content, encoding='utf-8')
        
        # Update index metadata
        with _ctn_lock(ctn_dir):
            entry = metadata.get("indexes", {}).get(current_id, {})
            entry.setdefault("outputs", {})[f"c4_model_{output_format}"] = str(output_path.relative_to(root))
            metadata.setdefault("indexes", {})[current_id] = entry
            _save_index_metadata(ctn_dir, metadata)
        
        print(f"✅ Generated C4 model ({output_format}): {output_path}")
        if output_format == 'json':
            print(f"   Systems: {len(c4_model['model']['softwareSystems'])}")
            print(f"   Containers: {len(c4_model['model']['containers'])}")
            print(f"   Components: {len(c4_model['model']['components'])}")
        
        return 0
        
    except FileNotFoundError as e:
        print(f"❌ {e}")
        print("   Make sure the index artifacts exist in .ctn directory")
        return 1
    except Exception as e:
        print(f"❌ Failed to generate C4 model: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1


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
        "--extensions", nargs="*", default=None, help="File extensions to include (e.g., .py .ts)"
    )
    idx.add_argument("--max-workers", type=int, default=0, help="Worker threads (0=auto)")
    idx.add_argument("--max-file-size-kb", type=int, default=None, help="Max file size KB")
    idx.add_argument("--force", action="store_true", help="Clear cache before indexing")
    idx.add_argument("--output-json", default=None, help="Path for graph.json output")
    idx.add_argument("--metrics-output", default=None, help="Write metrics JSON to path")
    idx.add_argument("--snapshot", action="store_true", help="Write a snapshot after indexing")
    idx.add_argument("--snapshot-label", default=None, help="Optional snapshot label")
    idx.add_argument("--verbose", action="store_true", help="Verbose output")
    idx.add_argument(
        "--log-json", action="store_true", help="Emit logs in JSON instead of color console"
    )
    idx.add_argument("--no-c4", action="store_true", help="Skip C4 model generation")
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

    patch = sub.add_parser("patch", help="Incremental patch for changed files or diff")
    patch.add_argument("--root", required=True, help="Path to repo root")
    patch.add_argument("--diff", help="Path to unified diff file")
    patch.add_argument("files", nargs="*", help="Changed files (absolute or relative)")
    patch.set_defaults(func=cmd_patch)

    wh = sub.add_parser("webhook", help="Webhook stub for push/PR events")
    wh.add_argument("--payload", required=True, help="JSON payload string")
    wh.set_defaults(func=cmd_webhook)

    inv = sub.add_parser("invalidate", help="Clear file cache")
    inv.add_argument("--root", required=True, help="Path to repo root")
    inv.set_defaults(func=cmd_invalidate)

    c4 = sub.add_parser("c4", help="Generate C4 architecture diagrams")
    c4.add_argument("--root", required=True, help="Path to repo root")
    c4.add_argument("--verbose", action="store_true", help="Verbose output")
    c4.add_argument(
        "--log-json", action="store_true", help="Emit logs in JSON instead of color console"
    )
    c4.add_argument(
        "--rules-dir", type=Path, help="Custom rules directory (default: built-in rules)"
    )
    c4.add_argument(
        "--language", 
        help="Override language detection (e.g., python, java, javascript, typescript, go)"
    )
    c4.add_argument(
        "--no-dynamic-rules", 
        action="store_true", 
        help="Disable dynamic rule generation"
    )
    c4.add_argument(
        "--enable-detectors",
        nargs="*",
        choices=["microservices", "event_driven", "cloud_native", "data_patterns"],
        help="Enable specific pattern detectors (default: all)"
    )
    c4.add_argument(
        "--disable-detectors",
        nargs="*",
        choices=["microservices", "event_driven", "cloud_native", "data_patterns"],
        help="Disable specific pattern detectors"
    )
    c4.add_argument(
        "--granularity",
        choices=["fine", "medium", "coarse", "adaptive"],
        help="Override granularity selection (default: adaptive based on repo size)"
    )
    c4.add_argument(
        "--grouping-strategy",
        choices=["domain", "functional", "data_flow", "team", "hybrid"],
        help="Component grouping strategy for medium/adaptive granularity"
    )
    c4.add_argument(
        "--importance-threshold",
        type=float,
        default=0.0,
        help="Minimum importance threshold for components (0.0-1.0)"
    )
    c4.add_argument(
        "--max-components",
        type=int,
        help="Maximum number of components to include"
    )
    c4.add_argument(
        "--output-format",
        choices=["json", "plantuml", "mermaid", "interactive", "d2"],
        default="json",
        help="Output format for C4 model (default: json)"
    )
    c4.add_argument(
        "--output",
        help="Output file path (default: stdout or .c4/{format}/model.{ext})"
    )
    c4.add_argument(
        "--theme",
        help="Theme for supported formats (light, dark, github)"
    )
    c4.add_argument(
        "--split-threshold",
        type=int,
        help="Component threshold for diagram splitting (PlantUML only)"
    )
    c4.set_defaults(func=cmd_c4)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
