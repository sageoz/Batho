"""Arrow-backed _compute_run_metrics — replaces 8 SQL queries with in-process column ops."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pyarrow as pa
import pyarrow.compute as pc

if TYPE_CHECKING:
    from .store import BsgScratchStore


def compute_run_metrics(store: "BsgScratchStore", db: Any, root: Path) -> dict:
    """Compute all run metrics from the compacted Arrow files + db.file_artifacts.

    Returns a dict with keys: context_overview, structural_metrics, artifact_payload.
    Mirrors the output contract of the original _compute_run_metrics() in build.py.
    """
    from .compaction import read_ipc

    ent_path = store.entities_path
    rel_path = store.relationships_path

    if ent_path.exists():
        ent_tbl = read_ipc(ent_path)
    else:
        ent_tbl = pa.table(
            {
                "entity_key": pa.array([], type=pa.int64()),
                "run_id": pa.array([], type=pa.int32()),
                "entity_name": pa.array([], type=pa.dictionary(pa.int32(), pa.utf8())),
                "entity_type": pa.array([], type=pa.dictionary(pa.int16(), pa.utf8())),
                "fqn": pa.array([], type=pa.large_utf8()),
                "file_path": pa.array([], type=pa.dictionary(pa.int32(), pa.utf8())),
                "line_number": pa.array([], type=pa.int32()),
                "signature": pa.array([], type=pa.large_utf8()),
                "is_exported": pa.array([], type=pa.bool_()),
            }
        )

    if rel_path.exists():
        rel_tbl = read_ipc(rel_path)
    else:
        rel_tbl = pa.table(
            {
                "source_key": pa.array([], type=pa.int64()),
                "target_key": pa.array([], type=pa.int64()),
                "relation_type": pa.array([], type=pa.dictionary(pa.int16(), pa.utf8())),
                "run_id": pa.array([], type=pa.int32()),
                "metadata_json": pa.array([], type=pa.utf8()),
            }
        )

    total_entities = len(ent_tbl)
    total_relationships = len(rel_tbl)

    # --- File paths from db.file_artifacts (Arrow Bundle) ---
    file_paths: list[str] = []
    try:
        with db.connection(read_only=True) as conn:
            rows = conn.execute(
                "SELECT val FROM string_dict WHERE id IN (SELECT file_id FROM file_artifacts WHERE run_id = ?)",
                (store.run_internal_id,),
            ).fetchall()
            file_paths = [r["val"] for r in rows]
    except Exception:
        if total_entities > 0:
            file_paths = ent_tbl.column("file_path").cast(pa.utf8()).to_pylist()
            file_paths = list(set(fp for fp in file_paths if fp))
    total_files = len(file_paths)

    # --- Entity type distribution ---
    entity_types: dict[str, int] = {}
    if total_entities > 0:
        et_col = ent_tbl.column("entity_type").cast(pa.utf8())
        agg = ent_tbl.group_by("entity_type").aggregate([("entity_key", "count")])
        for i in range(len(agg)):
            etype = str(agg.column("entity_type")[i].as_py())
            count = int(agg.column("entity_key_count")[i].as_py())
            entity_types[etype] = count

    # --- File distribution: top 100 files by entity count ---
    file_distribution: list[dict] = []
    if total_entities > 0:
        fd_agg = ent_tbl.group_by("file_path").aggregate([("entity_key", "count")])
        sort_idx = pc.sort_indices(fd_agg, sort_keys=[("entity_key_count", "descending")])
        fd_sorted = fd_agg.take(sort_idx).slice(0, 100)
        for i in range(len(fd_sorted)):
            file_distribution.append(
                {
                    "file_path": str(fd_sorted.column("file_path")[i].as_py()),
                    "entity_count": int(fd_sorted.column("entity_key_count")[i].as_py()),
                }
            )

    # --- File categories by extension ---
    by_ext: dict[str, list[str]] = defaultdict(list)
    for fp in file_paths:
        ext = Path(fp).suffix.lower() or "(no extension)"
        by_ext[ext].append(fp)
    categories = [
        {"extension": ext, "files": sorted(files), "count": len(files)}
        for ext, files in sorted(by_ext.items(), key=lambda x: -len(x[1]))
    ]

    # --- Top coupled files ---
    top_coupled: list[dict] = []
    if total_relationships > 0 and total_entities > 0:
        try:
            ent_key_col = ent_tbl.column("entity_key").cast(pa.int64())
            ent_fp_col = ent_tbl.column("file_path").cast(pa.utf8())
            key_to_fp: dict[int, str] = {}
            for k, fp in zip(ent_key_col.to_pylist(), ent_fp_col.to_pylist()):
                if k is not None and fp is not None:
                    key_to_fp[k] = fp

            src_keys = rel_tbl.column("source_key").to_pylist()
            tgt_keys = rel_tbl.column("target_key").to_pylist()
            coupling_counter: dict[str, int] = defaultdict(int)
            for src_k, tgt_k in zip(src_keys, tgt_keys):
                src_fp = key_to_fp.get(src_k)
                tgt_fp = key_to_fp.get(tgt_k)
                if src_fp and tgt_fp and src_fp != tgt_fp:
                    coupling_counter[src_fp] += 1
                    coupling_counter[tgt_fp] += 1

            top_coupled = [
                {"file_path": fp, "coupling": c}
                for fp, c in sorted(coupling_counter.items(), key=lambda x: -x[1])[:50]
            ]
        except Exception:
            top_coupled = []

    # --- Top 200 entities ---
    top_entities: list[dict] = []
    if total_entities > 0:
        try:
            fqn_col = ent_tbl.column("fqn").cast(pa.utf8())
            name_col = ent_tbl.column("entity_name").cast(pa.utf8())
            coalesce_col = pa.array(
                [
                    f if f else n
                    for f, n in zip(fqn_col.to_pylist(), name_col.to_pylist())
                ],
                type=pa.utf8(),
            )
            sort_idx = pc.sort_indices(pa.chunked_array([coalesce_col]))
            te_sorted = ent_tbl.take(sort_idx).slice(0, 200)
            for i in range(len(te_sorted)):
                top_entities.append(
                    {
                        "name": str(te_sorted.column("entity_name")[i].as_py() or ""),
                        "type": str(te_sorted.column("entity_type")[i].as_py() or ""),
                        "fqn": te_sorted.column("fqn")[i].as_py(),
                        "file": str(te_sorted.column("file_path")[i].as_py() or ""),
                        "start_line": int(te_sorted.column("line_number")[i].as_py() or 0),
                    }
                )
        except Exception:
            top_entities = []

    # --- Relationship count per source file ---
    rel_count_per_file: dict[str, int] = {}
    if total_relationships > 0 and total_entities > 0:
        try:
            src_keys = rel_tbl.column("source_key").to_pylist()
            per_file_counter: dict[str, int] = defaultdict(int)
            for src_k in src_keys:
                fp = key_to_fp.get(src_k) if "key_to_fp" in dir() else None
                if fp:
                    per_file_counter[fp] += 1
            rel_count_per_file = dict(per_file_counter)
        except Exception:
            rel_count_per_file = {}

    context_overview = {
        "total_entities": total_entities,
        "total_relationships": total_relationships,
        "total_files": total_files,
        "entity_types": entity_types,
        "file_distribution": file_distribution,
        "categories": categories,
    }

    structural_metrics = {
        "entity_type_distribution": entity_types,
        "top_coupled_files": top_coupled,
    }

    artifact_payload = {
        "entities": top_entities,
        "rel_count_per_file": rel_count_per_file,
    }

    return {
        "context_overview": context_overview,
        "structural_metrics": structural_metrics,
        "artifact_payload": artifact_payload,
    }
