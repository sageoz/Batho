"""Orchestrator for `batho export` — multi-view JSON export of BSG artifacts.

Loads the latest BSG artifact from the `artifact_<dirname>.batho` SQLite database and serializes
it into one of several JSON views (storage, agent, overview, files, symbols,
dependencies, delta) with optional streaming for large repositories.
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
    use_streaming: bool = False
    token_budget: int | None = None
    baseline_path: Path | None = None


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
    ["storage", "agent", "overview", "files", "symbols", "dependencies", "delta"]
)

VALID_CATEGORIES = frozenset(["source", "test", "doc", "config", "infra", "all"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_db_path(root: Path) -> Path | None:
    """Locate the artifact_<dirname>.batho database for the given root."""
    from batho.storage.engine import artifact_filename

    db_path = root / artifact_filename(root)
    if db_path.exists():
        return db_path
    return None


def _load_bsg_map_from_db(db_path: Path, run_id: str | None) -> "BSGMap | None":
    """Load and reconstruct a BSGMap from bsg_entries in the database."""
    from batho.storage.engine import BathoDatabase
    from batho.context.bsg_map import BSGMap
    from batho.context.schema import Entity, EntityType

    db = BathoDatabase(db_path, repo_root=db_path.parent)

    # Resolve run_id
    if run_id is None:
        run_id = db.get_latest_run_id()
    if run_id is None:
        return None

    entries = db.get_bsg_entries_for_run(run_id, view_type="agent")
    if not entries:
        return None

    root = db.repo_root

    by_file: dict[str, list[Entity]] = {}
    for entry in entries:
        file_path = entry["file_path"]
        try:
            entities_data: list[dict] = json.loads(entry["bsg_json"])
        except (json.JSONDecodeError, TypeError):
            continue
        entities = [Entity.from_dict(e) for e in entities_data if isinstance(e, dict)]
        if entities:
            by_file[file_path] = sorted(entities, key=lambda e: e.start_line)

    instance = BSGMap(
        _root=str(root),
        _by_file=by_file,
        _dependencies={},
        _relationships=[],
    )
    return instance


def _apply_filters(
    bsg_map: "BSGMap",
    pattern: str | None,
    category: str,
) -> "BSGMap":
    """Return a filtered BSGMap based on glob pattern and category."""
    from batho.context.bsg_map import BSGMap

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
    from batho.context.bsg_map import BSGMap

    try:
        raw = baseline_path.read_text(encoding="utf-8")
        baseline_data: dict = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot load baseline from {baseline_path}: {exc}") from exc

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


def _serialize(data: dict, fmt: str) -> str:
    """Serialize a dict to a JSON string."""
    if fmt == "pretty":
        return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=True)
    return json.dumps(data, sort_keys=True, ensure_ascii=True)


def _write_output(content: str, output_path: Path | None) -> None:
    """Write string content to a file or stdout."""
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(content, encoding="utf-8")
    else:
        sys.stdout.write(content)
        sys.stdout.write("\n")
        sys.stdout.flush()


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------


def run_export(options: ExportOptions) -> ExportResult:
    """Execute the export command.

    Steps:
      1. Validate options.
      2. Locate artifact_<dirname>.batho database.
      3. Load BSGMap from DB bsg_entries.
      4. Apply filters (glob pattern, category).
      5. Route to streaming or batch export.
      6. Write output to file or stdout.
      7. Return ExportResult.
    """
    t0 = time.monotonic()
    root = options.root.resolve()

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

    # --- Locate database ---
    db_path = _find_db_path(root)
    if db_path is None:
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
        db_path=str(db_path),
    )

    # --- Load BSGMap ---
    try:
        bsg_map = _load_bsg_map_from_db(db_path, options.index_id)
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

    # --- Streaming mode ---
    if options.use_streaming:
        from batho.bridge.bsg_exporter import BSGExporter

        exporter = BSGExporter()
        try:
            gen = exporter.export_streaming(bsg_map, view, options.format)
        except Exception as exc:
            return ExportResult(success=False, errors=[f"Streaming error: {exc}"])

        if options.output is not None:
            # Write streamed chunks to file
            try:
                options.output.parent.mkdir(parents=True, exist_ok=True)
                with options.output.open("w", encoding="utf-8") as fh:
                    for chunk in gen:
                        fh.write(chunk)
                    fh.write("\n")
            except OSError as exc:
                return ExportResult(
                    success=False, errors=[f"Write error: {exc}"]
                )
            LOGGER.info(
                "export_stream_complete",
                view=view,
                files=file_count,
                output=str(options.output),
            )
            return ExportResult(
                success=True,
                entity_count=entity_count,
                file_count=file_count,
                output_path=options.output,
            )
        else:
            # Return generator for caller to consume
            return ExportResult(
                success=True,
                entity_count=entity_count,
                file_count=file_count,
                stream_generator=gen,
            )

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
        _write_output(content, options.output)
    except OSError as exc:
        return ExportResult(success=False, errors=[f"Write error: {exc}"])

    elapsed_ms = int((time.monotonic() - t0) * 1000)
    LOGGER.info(
        "export_complete",
        view=view,
        files=file_count,
        entities=entity_count,
        duration_ms=elapsed_ms,
        output=str(options.output) if options.output else "stdout",
    )

    return ExportResult(
        success=True,
        entity_count=entity_count,
        file_count=file_count,
        output_path=options.output,
    )


def _generate_view(bsg_map: "BSGMap", view: str, options: ExportOptions) -> dict:
    """Dispatch to the appropriate view generator."""
    if view == "storage":
        return bsg_map.render_storage_view()

    if view == "agent":
        view_dict, _stats = bsg_map.render_agent_view(
            token_budget=options.token_budget
        )
        return view_dict

    if view == "overview":
        return bsg_map.render_overview_json()

    if view == "files":
        return bsg_map.render_files_json()

    if view == "symbols":
        return _generate_symbols_view(bsg_map)

    if view == "dependencies":
        return _generate_dependencies_view(bsg_map)

    if view == "delta":
        if options.baseline_path is None:
            raise ValueError(
                "--baseline is required for the delta view. "
                "Provide the path to a previous export JSON."
            )
        return _generate_delta_view(bsg_map, options.baseline_path)

    raise ValueError(f"Unhandled view: {view}")
