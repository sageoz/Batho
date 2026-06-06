"""Orchestrator for `batho load` — unpack a transport artifact ZIP into .batho/artifact/."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from batho.core.config import set_active_root
from batho.utils.logging import get_logger

LOGGER = get_logger(__name__, component="orchestrator.load")


@dataclass
class LoadOptions:
    root: Path
    artifact_path: Path
    force: bool = False
    rebuild_bsg: bool = True


@dataclass
class LoadResult:
    success: bool
    message: str = ""
    generation: int = 0
    tables_loaded: int = 0
    errors: list[str] = field(default_factory=list)


def run_load(options: LoadOptions) -> LoadResult:
    """Unpack a transport artifact ZIP into .batho/artifact/."""
    from batho.modules.storage.arrow_bundle import resolve_bundle_dir
    from batho.modules.storage.arrow_bundle.manager import BathoBundleManager

    root = options.root.resolve()
    if not root.exists() or not root.is_dir():
        return LoadResult(success=False, message=f"Repository root does not exist: {root}")

    artifact_path = options.artifact_path.resolve()
    if not artifact_path.exists():
        return LoadResult(success=False, message=f"Artifact file not found: {artifact_path}")

    set_active_root(root)
    bundle_dir = resolve_bundle_dir(root)
    meta_path = bundle_dir / "meta.json"

    if meta_path.exists() and not options.force:
        return LoadResult(
            success=False,
            message=(
                f"Artifact bundle already exists at {bundle_dir}. "
                "Use --force to overwrite."
            ),
        )

    if meta_path.exists() and options.force:
        import shutil
        LOGGER.info("load_clearing_existing_bundle", path=str(bundle_dir))
        shutil.rmtree(bundle_dir, ignore_errors=True)

    bundle_dir.mkdir(parents=True, exist_ok=True)
    manager = BathoBundleManager(bundle_dir)
    bsg_current_dir = root / ".batho" / "bsg" / "current"

    try:
        manifest = manager.unpack_artifact(
            artifact_path,
            bsg_target_dir=bsg_current_dir if options.rebuild_bsg else None,
        )
    except Exception as exc:
        LOGGER.error("load_unpack_failed", error=str(exc))
        return LoadResult(success=False, message=str(exc))

    generation = manifest.get("generation", 0)
    tables_loaded = len(manifest.get("active_files", {}))

    # --- Rebuild bsg/current/ ---
    # Fast path: ZIP contained bsg/ members — already extracted by unpack_artifact.
    # Fallback path: older ZIP without bsg/ — reconstruct from agent_views + rels_views.
    if options.rebuild_bsg:
        bsg_was_packed = bool(manifest.get("bsg_files"))
        if bsg_was_packed:
            _write_bsg_meta(bsg_current_dir, manifest)
            LOGGER.info("load_bsg_current_extracted", root=str(root))
        else:
            try:
                _reconstruct_bsg_current(root, bundle_dir, manifest)
                LOGGER.info("load_bsg_current_rebuilt", root=str(root))
            except Exception as exc:
                LOGGER.warning("load_bsg_current_rebuild_failed", error=str(exc))

    LOGGER.info(
        "load_complete",
        root=str(root),
        source=str(artifact_path),
        generation=generation,
        tables=tables_loaded,
    )
    return LoadResult(
        success=True,
        message=f"Loaded artifact into {bundle_dir} (generation {generation}, {tables_loaded} tables)",
        generation=generation,
        tables_loaded=tables_loaded,
    )


def _write_bsg_meta(bsg_current_dir: Path, manifest: dict[str, Any]) -> None:
    """Write meta.json into bsg/current/ after fast-path ZIP extraction."""
    import json as _json
    from batho.modules.storage.arrow_store.compaction import read_ipc
    from batho.modules.storage.arrow_store.schemas import SCHEMA_VERSION

    entities_path = bsg_current_dir / "entities.ipc"
    relationships_path = bsg_current_dir / "relationships.ipc"
    entity_count = 0
    rel_count = 0
    try:
        if entities_path.exists():
            entity_count = len(read_ipc(entities_path))
        if relationships_path.exists():
            rel_count = len(read_ipc(relationships_path))
    except Exception:
        pass

    meta = {
        "schema_version": SCHEMA_VERSION,
        "run_uuid": manifest.get("last_run_uuid") or "loaded",
        "run_internal_id": manifest.get("generation", 1),
        "entity_count": entity_count,
        "rel_count": rel_count,
        "dangling_count": 0,
    }
    (bsg_current_dir / "meta.json").write_text(_json.dumps(meta, indent=2))

    LOGGER.info(
        "load_bsg_current_written",
        current_dir=str(bsg_current_dir),
        entities=entity_count,
        rels=rel_count,
    )


def _reconstruct_bsg_current(root: Path, bundle_dir: Path, manifest: dict[str, Any]) -> None:
    """Fallback: reconstruct .batho/bsg/current/ from unpacked agent_views + rels_views IPC tables.

    Used when the ZIP was produced by an older batho version that did not
    include bsg/ members. Reads agent_views.ipc and rels_views.ipc, maps them
    into BsgScratchStore entity/rel tuples, and writes plain IPC Files:
    entity_dict.ipc, entities.ipc, relationships.ipc, dangling.ipc.
    """
    from batho.modules.storage.arrow_bundle.writer import read_ipc_table
    from batho.modules.storage.arrow_store.store import BsgScratchStore
    from batho.modules.storage.arrow_store.compaction import write_empty_dangling

    active = manifest.get("active_files", {})
    last_run_uuid = manifest.get("last_run_uuid") or "loaded"

    generation = manifest.get("generation", 1)

    # Resolve actual IPC paths from active_files
    def _ipc_path(logical: str) -> Path | None:
        stamped = active.get(logical)
        if not stamped:
            return None
        p = bundle_dir / stamped
        return p if p.exists() else None

    agent_path = _ipc_path("agent_views")
    rels_path = _ipc_path("rels_views")
    ft_path = _ipc_path("file_tracking")

    if agent_path is None and rels_path is None:
        LOGGER.warning("load_bsg_current_no_views", note="agent_views and rels_views missing — skipping")
        return

    # Build file_path lookup from file_tracking (file_id → file_path)
    file_id_to_path: dict[int, str] = {}
    if ft_path is not None:
        try:
            ft_tbl = read_ipc_table(ft_path)
            for row in ft_tbl.to_pylist():
                file_id_to_path[int(row["file_id"])] = str(row["file_path"])
        except Exception as exc:
            LOGGER.warning("load_bsg_file_tracking_read_failed", error=str(exc))

    batho_dir = root / ".batho"
    current_dir = batho_dir / "bsg" / "current"
    current_dir.mkdir(parents=True, exist_ok=True)

    store = BsgScratchStore(
        run_uuid=last_run_uuid,
        batho_dir=batho_dir,
        run_internal_id=generation,
    )

    # --- Populate entities from agent_views ---
    if agent_path is not None:
        try:
            ag_tbl = read_ipc_table(agent_path)
            entity_id_strs = ag_tbl.column("entity_id").to_pylist()
            # Allocate integer keys for all entity_id strings
            key_map = store.bulk_get_or_create_entity_keys(
                [str(eid) for eid in entity_id_strs if eid is not None]
            )

            entity_rows: list[tuple] = []
            for row in ag_tbl.to_pylist():
                eid = str(row.get("entity_id") or "")
                if not eid:
                    continue
                file_path = file_id_to_path.get(int(row.get("file_id") or 0), "")
                entity_rows.append((
                    key_map[eid],
                    generation,
                    str(row.get("name") or ""),
                    str(row.get("entity_type") or ""),
                    str(row.get("fqn") or ""),
                    file_path,
                    int(row.get("start_line") or 0),
                    str(row.get("signature") or ""),
                    bool(row.get("is_exported") or False),
                ))

            if entity_rows:
                store.append_entities(entity_rows)
        except Exception as exc:
            LOGGER.warning("load_bsg_agent_views_read_failed", error=str(exc))

    # --- Populate relationships from rels_views ---
    if rels_path is not None:
        try:
            rl_tbl = read_ipc_table(rels_path)
            all_ids = set()
            for row in rl_tbl.to_pylist():
                src = str(row.get("source_id") or "")
                tgt = str(row.get("target_id") or "")
                if src:
                    all_ids.add(src)
                if tgt:
                    all_ids.add(tgt)
            key_map = store.bulk_get_or_create_entity_keys(list(all_ids))

            rel_rows: list[tuple] = []
            for row in rl_tbl.to_pylist():
                src = str(row.get("source_id") or "")
                tgt = str(row.get("target_id") or "")
                if not src or not tgt:
                    continue
                rel_rows.append((
                    key_map.get(src, 0),
                    key_map.get(tgt, 0),
                    str(row.get("relation_type") or ""),
                    generation,
                    str(row.get("metadata_json") or "{}"),
                ))

            if rel_rows:
                store.append_relationships(rel_rows)
        except Exception as exc:
            LOGGER.warning("load_bsg_rels_views_read_failed", error=str(exc))

    # Write empty dangling (no cross-file resolution needed for a loaded bundle)
    write_empty_dangling(store.dangling_path)

    # Compact everything to disk
    store.compact()

    LOGGER.info(
        "load_bsg_current_written",
        current_dir=str(current_dir),
        entities=store.entity_count,
        rels=store.rel_count,
    )
