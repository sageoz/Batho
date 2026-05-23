"""Graph data loading backed by the unified .batho SQLite database.

All graph data (entities + relationships) is stored in the graph_entities
and graph_relationships tables. No JSON files are read.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from batho.context.codegraph import InMemoryGraph
from batho.context.storage import get_artifact_registry
from batho.utils.logging import get_logger

LOGGER = get_logger(__name__, component="graph_cache")


def load_graph_payload(ctn_dir: Path, index_id: str) -> dict[str, Any] | None:
    """Load graph payload from the .batho database for the given run_id."""
    db = get_artifact_registry(ctn_dir)

    entities = db.query_entities(index_id, limit=999999)
    relationships = db.query_relationships(index_id, limit=999999)

    if not entities and not relationships:
        return None

    # Reconstruct the dict format expected by InMemoryGraph.from_dict()
    payload: dict[str, Any] = {
        "entities": [
            {
                "id": e.get("entity_id", ""),
                "type": e.get("entity_type", ""),
                "name": e.get("name", ""),
                "file": e.get("file_path", ""),
                "start_line": e.get("start_line", 0),
                "end_line": e.get("end_line", 0),
                "signature": e.get("signature"),
                "parent_id": e.get("parent_id"),
                "content_hash": e.get("content_hash", ""),
                "ast_node_type": e.get("ast_node_type"),
                "metadata": json.loads(e.get("metadata_json", "{}")),
            }
            for e in entities
        ],
        "relationships": [
            {
                "id": r.get("relationship_id", ""),
                "type": r.get("relationship_type", ""),
                "source_id": r.get("source_id", ""),
                "target_id": r.get("target_id", ""),
                "metadata": json.loads(r.get("metadata_json", "{}")),
            }
            for r in relationships
        ],
    }
    return payload


def load_cached_graph(ctn_dir: Path, index_id: str) -> InMemoryGraph | None:
    """Load InMemoryGraph from the .batho database for the given run_id."""
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
    """Return stats for graph data in the .batho database."""
    db = get_artifact_registry(ctn_dir)

    current_index_id = index_id
    if not current_index_id:
        current_index_id = db.get_latest_run_id()

    if not current_index_id:
        return {
            "current_index_id": "",
            "graph_exists": False,
            "graph_size_bytes": 0,
        }

    entity_count = db.get_entity_count(current_index_id)
    rel_count = db.get_relationship_count(current_index_id)
    graph_exists = entity_count > 0 or rel_count > 0

    return {
        "current_index_id": current_index_id,
        "graph_exists": graph_exists,
        "entity_count": entity_count,
        "relationship_count": rel_count,
    }
