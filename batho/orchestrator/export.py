"""Orchestrator for `batho export` — pack artifact export with optional JSON views.

By default, loads the latest BSG artifact from the Arrow Bundle in .batho/artifact/
and produces a transportable ZIP (artifact_<dir>.batho). Set pack=False to export
one of several JSON views (storage, agent, overview, files, symbols, dependencies,
delta) with optional streaming for large repositories.
"""

from __future__ import annotations

import fnmatch
import json
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Literal

from batho.utils.logging import get_logger
from batho.core.config import set_active_root

LOGGER = get_logger(__name__, component="orchestrator.export")


# ---------------------------------------------------------------------------
# Public data types
# ---------------------------------------------------------------------------


@dataclass
class ExportOptions:
    """Configuration for an export run."""

    root: Path
    view: str = "storage"
    output: Path | None = None
    format: Literal["json", "pretty"] = "json"
    filter_pattern: str | None = None
    category: str = "all"
    index_id: str | None = None
    token_budget: int | None = None
    baseline_path: Path | None = None
    include_relationships: bool = False
    pack: bool = True


@dataclass
class ExportResult:
    """Outcome of an export run."""

    success: bool
    entity_count: int = 0
    file_count: int = 0
    output_path: Path | None = None
    stream_generator: Iterator[str] | None = None  # For streaming mode
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Valid view names
# ---------------------------------------------------------------------------

VALID_VIEWS = frozenset(
    ["storage", "agent", "overview", "files", "symbols", "dependencies", "delta", "rel"]
)

VALID_CATEGORIES = frozenset(["source", "test", "doc", "config", "infra", "all"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_bundle_dir(root: Path) -> Path | None:
    """Locate the Arrow bundle artifact dir for the given root."""
    from batho.modules.storage.arrow_bundle import resolve_bundle_dir

    bundle_dir = resolve_bundle_dir(root)
    if (bundle_dir / "meta.json").exists():
        return bundle_dir
    return None


def _load_bsg_map_from_bundle(
    bundle_dir: Path, run_id: str | None, root: Path
) -> "BSGMap | None":
    """Load and reconstruct a BSGMap from file artifacts in the Arrow Bundle."""
    from batho.modules.storage.arrow_bundle import get_bundle
    from batho.modules.compression.bsg_map import BSGMap
    from batho.core.schemas import Entity, EntityType, FileSnapshot, Relationship

    db = get_bundle(root)

    if run_id is None:
        run_id = db.get_latest_run_id()
    if run_id is None:
        return None

    run_internal_id = db.get_run_internal_id(run_id)
    if run_internal_id is None:
        return None

    artifacts = db.get_file_artifacts(run_internal_id, include_storage=True)
    if not artifacts:
        return None

    root = db.repo_root

    by_file: dict[str, list[Entity]] = {}
    relationships: list[Relationship] = []

    for artifact in artifacts:
        file_path = artifact["file_path"]
        abs_file_path = str((root / file_path).resolve())
        graph_data = artifact.get("graph")
        if graph_data and isinstance(graph_data, dict):
            entities_data = graph_data.get("entities", [])
            if isinstance(entities_data, list):
                # Set 'file' to abs_file_path for absolute-path-based entity ID computation
                for e in entities_data:
                    if isinstance(e, dict):
                        e["file"] = abs_file_path
                        if e.get("leading_whitespace") is None:
                            e["leading_whitespace"] = ""
                        if e.get("trailing_whitespace") is None:
                            e["trailing_whitespace"] = ""
                entities = [Entity.from_dict(e) for e in entities_data if isinstance(e, dict)]

                if entities:
                    by_file[file_path] = sorted(entities, key=lambda e: e.start_line)

            rels_data = graph_data.get("relationships", [])
            if isinstance(rels_data, list):
                for r in rels_data:
                    if isinstance(r, dict):
                        relationships.append(Relationship.from_dict(r))

    # Reconstruct dependencies
    entity_to_file: dict[str, str] = {}
    for f_path, ents in by_file.items():
        for e in ents:
            entity_to_file[e.id] = f_path

    dependencies: dict[str, set[str]] = {}
    for rel in relationships:
        if rel.type.name in ("IMPORTS", "CALLS", "USES"):
            source_file = entity_to_file.get(rel.source_id)
            if source_file:
                target_file = entity_to_file.get(rel.target_id)
                if not target_file:
                    target_file = rel.target_id

                if target_file.startswith("/"):
                    try:
                        target_file = Path(target_file).relative_to(root).as_posix()
                    except ValueError:
                        pass

                if source_file != target_file:
                    dependencies.setdefault(source_file, set()).add(target_file)

    sorted_deps = {
        path: sorted(list(deps)) for path, deps in dependencies.items()
    }

    # Load opaque snapshots from file_tracking for unindexed files
    opaque_snapshots: list[FileSnapshot] = []
    try:
        unindexed_files = db.get_unindexed_files_with_details()
        for file_info in unindexed_files:
            snap = FileSnapshot(
                file_path=file_info["file_path"],
                file_hash=file_info["content_hash"],
                file_size=file_info["size"],
                encoding=file_info["encoding"],
                entity_ids=[],
                gap_sections=[],
            )
            opaque_snapshots.append(snap)
    except Exception as exc:
        LOGGER.warning("export_opaque_snapshots_skipped", error=str(exc))

    instance = BSGMap(
        _root=str(root),
        _by_file=by_file,
        _dependencies=sorted_deps,
        _relationships=relationships,
        _opaque_snapshots={s.file_path: s for s in opaque_snapshots},
    )
    return instance


def _apply_filters(
    bsg_map: "BSGMap",
    pattern: str | None,
    category: str,
) -> "BSGMap":
    """Return a filtered BSGMap based on glob pattern and category."""
    from batho.modules.compression.bsg_map import BSGMap

    if pattern is None and category == "all":
        return bsg_map

    filtered: dict[str, list] = {}

    for file_path, entities in bsg_map._by_file.items():
        # Pattern filter
        if pattern is not None:
            if not fnmatch.fnmatch(file_path, pattern):
                continue

        # Category filter
        if category != "all":
            cat_upper = category.upper()
            file_cat = _resolve_file_category(file_path, entities)
            if file_cat != cat_upper:
                continue

        filtered[file_path] = entities

    return BSGMap(
        _root=bsg_map._root,
        _by_file=filtered,
        _dependencies={
            k: v for k, v in bsg_map._dependencies.items() if k in filtered
        },
        _relationships=bsg_map._relationships,
        _opaque_snapshots=bsg_map._opaque_snapshots,
    )


def _resolve_file_category(file_path: str, entities: list) -> str:
    """Derive a category string for a file from entity metadata or path heuristics."""
    # Check entity metadata first
    for entity in entities:
        metadata = entity.metadata or {}
        cat = str(metadata.get("bsg.category", "")).upper()
        if cat:
            return cat

    # Path heuristics
    fp = file_path.lower()
    if "test" in fp:
        return "TEST"
    if fp.endswith((".yaml", ".yml", ".toml", ".json", ".ini", ".cfg", ".env")):
        return "CONFIG"
    if "doc" in fp or fp.endswith((".md", ".rst", ".txt")):
        return "DOC"
    if any(fp.endswith(ext) for ext in (".dockerfile", ".tf", ".hcl", ".sh", ".bash")):
        return "INFRA"
    return "SOURCE"


def _generate_symbols_view(bsg_map: "BSGMap") -> dict:
    """Generate a flat symbol index view."""
    symbols = []
    for file_path in sorted(bsg_map._by_file.keys()):
        for entity in bsg_map._by_file[file_path]:
            symbols.append({
                "id": entity.id,
                "name": entity.name,
                "type": entity.type.name,
                "file": file_path,
                "line": entity.start_line,
                "signature": entity.signature,
            })

    return {
        "view_type": "symbols",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "symbol_count": len(symbols),
        "symbols": symbols,
    }


def _generate_dependencies_view(bsg_map: "BSGMap") -> dict:
    """Generate a dependency graph view."""
    deps_list = []
    for file_path in sorted(bsg_map._dependencies.keys()):
        targets = bsg_map._dependencies[file_path]
        if targets:
            deps_list.append({
                "file": file_path,
                "depends_on": sorted(targets),
                "dependency_count": len(targets),
            })

    # Build reverse-dependencies
    rdeps: dict[str, list[str]] = {}
    for file_path, targets in bsg_map._dependencies.items():
        for t in targets:
            rdeps.setdefault(t, []).append(file_path)

    return {
        "view_type": "dependencies",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "file_count": len(bsg_map._by_file),
        "dependency_edge_count": sum(len(v) for v in bsg_map._dependencies.values()),
        "dependencies": deps_list,
        "reverse_dependencies": [
            {"file": t, "required_by": sorted(sources)}
            for t, sources in sorted(rdeps.items())
        ],
    }


def _generate_delta_view(
    bsg_map: "BSGMap",
    baseline_path: Path,
) -> dict:
    """Load a baseline export JSON and compute the delta."""
    from batho.modules.compression.bsg_map import BSGMap

    # Enforce a 50 MB limit on baseline files to prevent memory exhaustion
    MAX_BASELINE_SIZE = 50 * 1024 * 1024
    try:
        file_size = baseline_path.stat().st_size
        if file_size > MAX_BASELINE_SIZE:
            raise ValueError(f"Baseline file size exceeds limit of 50 MB ({file_size} bytes)")
    except OSError as exc:
        raise ValueError(f"Cannot access baseline file {baseline_path}: {exc}") from exc

    try:
        raw = baseline_path.read_text(encoding="utf-8")
        baseline_data = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot load baseline from {baseline_path}: {exc}") from exc

    if not isinstance(baseline_data, dict):
        raise ValueError("Baseline JSON must be a dictionary object")

    baseline_map = BSGMap.from_dict(baseline_data)
    raw_delta = bsg_map.render_delta(previous=baseline_map)

    # Serialize entity lists in 'added'
    added_serialized = {
        fp: [e.to_dict(view="agent") for e in entities]
        for fp, entities in raw_delta.get("added", {}).items()
    }

    return {
        "view_type": "delta",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "delta_type": raw_delta.get("delta_type", "incremental"),
        "added": added_serialized,
        "modified": sorted(raw_delta.get("modified", [])),
        "removed": sorted(raw_delta.get("removed", [])),
        "unchanged": sorted(raw_delta.get("unchanged", [])),
        "stats": raw_delta.get("stats", {}),
    }


def _generate_relationships_view(bsg_map: "BSGMap") -> dict:
    """Generate a relationships view with dependencies and raw relationship blob."""
    relationships = []
    for rel in bsg_map._relationships:
        if hasattr(rel, "to_dict"):
            relationships.append(rel.to_dict())
        else:
            relationships.append(dict(rel))

    # Build dependencies list
    deps_list = []
    for file_path in sorted(bsg_map._dependencies.keys()):
        targets = bsg_map._dependencies[file_path]
        if targets:
            deps_list.append({
                "file": file_path,
                "depends_on": sorted(targets),
                "dependency_count": len(targets),
            })

    # Build reverse-dependencies
    rdeps: dict[str, list[str]] = {}
    for file_path, targets in bsg_map._dependencies.items():
        for t in targets:
            rdeps.setdefault(t, []).append(file_path)

    return {
        "view_type": "rel",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "relationship_count": len(relationships),
        "relationships": relationships,
        "file_count": len(bsg_map._by_file),
        "dependency_edge_count": sum(len(v) for v in bsg_map._dependencies.values()),
        "dependencies": deps_list,
        "reverse_dependencies": [
            {"file": t, "required_by": sorted(sources)}
            for t, sources in sorted(rdeps.items())
        ],
    }


def _serialize(data: dict, fmt: str) -> str:
    """Serialize a dict to a JSON string."""
    if fmt == "pretty":
        return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=True)
    return json.dumps(data, sort_keys=True, ensure_ascii=True)


def _write_output(content: str, output_path: Path) -> None:
    """Write string content to a file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------


def run_export(options: ExportOptions) -> ExportResult:
    """Execute the export command.

    By default produces a transport ZIP (artifact_<dir>.batho).
    Set options.pack=False to export a JSON view instead.

    Steps:
      1. Validate options.
      2. Locate artifact bundle in .batho/artifact/.
      3. Either pack the bundle into a ZIP, or load BSGMap for JSON export.
      4. Apply filters (glob pattern, category) for JSON mode.
      5. Route to streaming or batch export for JSON mode.
      6. Write output to file or stdout.
      7. Return ExportResult.
    """
    t0 = time.monotonic()
    root = options.root.resolve()
    
    if not root.exists():
        return ExportResult(
            success=False,
            errors=[f"Repository root does not exist: {root}"],
        )
    if not root.is_dir():
        return ExportResult(
            success=False,
            errors=[f"Repository root is not a directory: {root}"],
        )

    set_active_root(root)

    # --- Pack mode: produce transport ZIP and return early ---
    if options.pack:
        from batho.modules.storage.arrow_bundle.manager import BathoBundleManager
        from batho.modules.storage.arrow_bundle import resolve_bundle_dir

        bundle_dir = resolve_bundle_dir(root)
        if not (bundle_dir / "meta.json").exists():
            return ExportResult(
                success=False,
                errors=[f"No artifact bundle found at {root}. Run: batho build --root {root}"],
            )

        root_name = root.resolve().name
        sanitized = __import__("re").sub(r"[^a-z0-9_-]", "-", root_name.lower()).strip("-")
        default_zip = root / f"artifact_{sanitized}.batho"
        zip_path = options.output or default_zip

        try:
            manager = BathoBundleManager(bundle_dir)
            bsg_current_dir = options.root / ".batho" / "bsg" / "current"
            manager.export_artifact(zip_path, bsg_current_dir=bsg_current_dir)
        except Exception as exc:
            return ExportResult(success=False, errors=[f"Pack failed: {exc}"])

        LOGGER.info("export_pack_complete", dest=str(zip_path))
        return ExportResult(success=True, output_path=zip_path)

    output_path = options.output or (root / "batho_export.json")

    # --- Validate view ---
    view = options.view.lower()
    if view not in VALID_VIEWS:
        return ExportResult(
            success=False,
            errors=[
                f"Unknown view '{options.view}'. Valid: {sorted(VALID_VIEWS)}"
            ],
        )

    # --- Validate category ---
    category = options.category.lower()
    if category not in VALID_CATEGORIES:
        return ExportResult(
            success=False,
            errors=[
                f"Unknown category '{options.category}'. Valid: {sorted(VALID_CATEGORIES)}"
            ],
        )

    # --- Locate artifact bundle ---
    bundle_dir = _find_bundle_dir(root)
    if bundle_dir is None:
        return ExportResult(
            success=False,
            errors=[
                f"No artifact database found at {root}. "
                f"Run: batho build --root {root}"
            ],
        )

    LOGGER.info(
        "export_started",
        root=str(root),
        view=view,
        bundle_dir=str(bundle_dir),
    )

    # --- Load BSGMap ---
    try:
        bsg_map = _load_bsg_map_from_bundle(bundle_dir, options.index_id, root)
    except Exception as exc:
        LOGGER.error("export_load_failed", error=str(exc))
        return ExportResult(success=False, errors=[f"Failed to load BSG data: {exc}"])

    if bsg_map is None:
        return ExportResult(
            success=False,
            errors=["No BSG entries found. Run: batho build --root " + str(root)],
        )

    # --- Apply filters ---
    try:
        bsg_map = _apply_filters(bsg_map, options.filter_pattern, category)
    except Exception as exc:
        LOGGER.error("export_filter_failed", error=str(exc))
        return ExportResult(success=False, errors=[f"Filter error: {exc}"])

    file_count = len(bsg_map._by_file)
    entity_count = sum(len(v) for v in bsg_map._by_file.values())

    # --- Batch mode: generate view dict ---
    try:
        data = _generate_view(bsg_map, view, options)
    except ValueError as exc:
        return ExportResult(success=False, errors=[str(exc)])
    except Exception as exc:
        LOGGER.error("export_render_failed", view=view, error=str(exc))
        return ExportResult(success=False, errors=[f"Render error ({view}): {exc}"])

    # --- Serialize ---
    try:
        content = _serialize(data, options.format)
    except Exception as exc:
        return ExportResult(success=False, errors=[f"Serialization error: {exc}"])

    # --- Write output ---
    try:
        _write_output(content, output_path)
    except OSError as exc:
        return ExportResult(success=False, errors=[f"Write error: {exc}"])

    elapsed_ms = int((time.monotonic() - t0) * 1000)
    LOGGER.info(
        "export_complete",
        view=view,
        files=file_count,
        entities=entity_count,
        duration_ms=elapsed_ms,
        output=str(output_path),
    )

    return ExportResult(
        success=True,
        entity_count=entity_count,
        file_count=file_count,
        output_path=output_path,
    )


def _generate_view(bsg_map: "BSGMap", view: str, options: ExportOptions) -> dict:
    """Dispatch to the appropriate view generator."""
    from typing import Any

    data: dict[str, Any]

    if view == "storage":
        data = bsg_map.render_storage_view()

    elif view == "agent":
        view_dict, _stats = bsg_map.render_agent_view(
            token_budget=options.token_budget
        )
        data = view_dict

    elif view == "overview":
        data = bsg_map.render_overview_json()

    elif view == "files":
        data = bsg_map.render_files_json()

    elif view == "symbols":
        data = _generate_symbols_view(bsg_map)

    elif view == "dependencies":
        data = _generate_dependencies_view(bsg_map)

    elif view == "delta":
        if options.baseline_path is None:
            raise ValueError(
                "--baseline is required for the delta view. "
                "Provide the path to a previous export JSON."
            )
        data = _generate_delta_view(bsg_map, options.baseline_path)

    elif view == "rel":
        data = _generate_relationships_view(bsg_map)
        # Return early for rel view - --rel flag doesn't modify it
        return data

    else:
        raise ValueError(f"Unhandled view: {view}")

    # Inject relationships blob if --rel flag is set (except for 'rel' view itself)
    if options.include_relationships:
        relationships = []
        for rel in bsg_map._relationships:
            if hasattr(rel, "to_dict"):
                relationships.append(rel.to_dict())
            else:
                relationships.append(dict(rel))
        data["relationships"] = relationships
        data["relationship_count"] = len(relationships)

    return data
