"""Graph data loading backed by the unified .batho SQLite database (v2.0).

All graph data is stored as zlib-compressed blobs in file_artifacts.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from batho.modules.graph.builder.codegraph import InMemoryGraph
from batho.modules.storage.sqlite_registry.engine import get_database
from batho.utils.logging import get_logger

LOGGER = get_logger(__name__, component="graph_cache")


def load_graph_payload(ctn_dir: Path, run_uuid: str) -> dict[str, Any] | None:
    """Load merged graph payload from compressed blobs for a run."""
    db = get_database(ctn_dir)
    run_internal_id = db.get_run_internal_id(run_uuid)
    if run_internal_id is None:
        return None

    artifacts = db.get_file_artifacts(run_internal_id)
    if not artifacts:
        # Run exists but has no file artifacts (e.g., repo with no indexable files).
        # Return an empty payload instead of None so callers can distinguish this
        # from "run UUID not found" (which returns None above).
        return {"entities": [], "relationships": []}

    all_entities: list[dict[str, Any]] = []
    all_relationships: list[dict[str, Any]] = []
    for artifact in artifacts:
        graph = artifact.get("graph", {})
        file_path = artifact.get("file_path", "")
        for e in graph.get("entities", []):
            e_copy = dict(e)
            if "file" not in e_copy:
                e_copy["file"] = file_path
            all_entities.append(e_copy)
        all_relationships.extend(graph.get("relationships", []))

    return {"entities": all_entities, "relationships": all_relationships}


def load_cached_graph(ctn_dir: Path, index_id: str) -> InMemoryGraph | None:
    """Load InMemoryGraph from compressed blobs for the given run_uuid."""
    payload = load_graph_payload(ctn_dir, index_id)
    if payload is None:
        return None

    try:
        return InMemoryGraph.from_dict(payload)
    except Exception as exc:
        LOGGER.warning(
            "graph_cache_deserialize_failed",
            index_id=index_id,
            error=str(exc),
        )
        return None


def get_cached_graph_stats(
    ctn_dir: Path, index_id: str | None = None
) -> dict[str, Any]:
    """Return stats for graph data stored in compressed blobs."""
    db = get_database(ctn_dir)

    current_index_id = index_id or db.get_latest_run_id()
    if not current_index_id:
        return {"current_index_id": "", "graph_exists": False, "graph_size_bytes": 0}

    run_internal_id = db.get_run_internal_id(current_index_id)
    if run_internal_id is None:
        return {"current_index_id": current_index_id, "graph_exists": False}

    with db.connection(read_only=True) as conn:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM file_artifacts WHERE run_id = ?",
            (run_internal_id,),
        ).fetchone()
        file_count = row["cnt"] if row else 0

    run_meta = db.get_run(current_index_id) or {}
    return {
        "current_index_id": current_index_id,
        "graph_exists": file_count > 0,
        "file_count": file_count,
        "entity_count": run_meta.get("entity_count", 0),
        "relationship_count": run_meta.get("rel_count", 0),
    }
