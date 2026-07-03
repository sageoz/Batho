"""Community summary loading and formatting.

Reads `communities.ipc` from the artifact directory (if present) and
formats community summaries for inclusion in graph_overview output.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.ipc as ipc

import structlog

LOGGER = structlog.get_logger(__name__)


def load_communities(artifact_dir: Path) -> list[dict[str, Any]]:
    """Load communities from `communities.ipc` in the artifact directory.

    Returns an empty list if the file does not exist (graceful fallback).
    """
    communities_path = artifact_dir / "communities.ipc"
    if not communities_path.exists():
        return []

    try:
        with pa.memory_map(str(communities_path), "r") as mmap:
            with ipc.open_file(mmap) as reader:
                table = reader.read_all()
        if table.num_rows == 0:
            return []
        return table.to_pylist()
    except Exception as exc:
        LOGGER.warning("community_load_failed", error=str(exc))
        return []


def format_community_summary(community: dict[str, Any]) -> dict[str, Any]:
    """Format a single community row for inclusion in structured output."""
    return {
        "id": community.get("community_id", 0),
        "name": community.get("name", "Unnamed"),
        "entity_count": community.get("entity_count", 0),
        "file_count": community.get("file_count", 0),
        "top_entities": community.get("top_entities", []),
        "description": community.get("description", ""),
        "file_paths": community.get("file_paths", []),
    }


def format_communities_for_overview(communities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Format all communities for the graph_overview structured output."""
    return [format_community_summary(c) for c in communities]
