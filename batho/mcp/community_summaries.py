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


def _one_line_description(community: dict[str, Any]) -> str:
    """T4 §5: one-line description from member file paths + top entities —
    replaces the persisted "N entities across M files. Key: ..." template."""
    top = [t for t in (community.get("top_entities") or []) if t][:3]
    dirs = sorted(
        {
            p.rsplit("/", 1)[0]
            for p in (community.get("file_paths") or [])
            if "/" in p
        }
    )
    dir_hint = dirs[0] if len(dirs) == 1 else (dirs[0] + "/…" if dirs else "")
    parts = []
    if dir_hint:
        parts.append(dir_hint)
    if top:
        parts.append("key: " + ", ".join(top))
    return " · ".join(parts) if parts else community.get("description", "")


def format_community_summary(community: dict[str, Any]) -> dict[str, Any]:
    """Format a single community row for inclusion in structured output.

    Display order (T16): llm_label ?? heuristic_label ?? name — persisted
    LLM labels win over the deterministic heuristic when present.
    """
    return {
        "id": community.get("community_id", 0),
        "name": (
            community.get("llm_label")
            or community.get("heuristic_label")
            or community.get("name", "Unnamed")
        ),
        "entity_count": community.get("entity_count", 0),
        "file_count": community.get("file_count", 0),
        "top_entities": community.get("top_entities", []),
        "description": _one_line_description(community),
        "file_paths": community.get("file_paths", []),
        "parent_id": community.get("parent_id"),
        "level": community.get("level") or 0,
    }


def format_communities_for_overview(
    communities: list[dict[str, Any]], top_n: int = 12
) -> list[dict[str, Any]]:
    """Format communities for the graph_overview structured output.

    Singleton communities stay in storage but are hidden from the overview.
    The top-N by entity count are rendered; the rest collapse into a trailing
    aggregate entry so the section stays small (<= ~400 tokens target).

    Only leaf rows are shown: interior (parent/domain) rows' entity_count
    includes their descendants' members, so flattening all levels would
    double-count entities in both the list and the aggregate. Leaf rows form
    a disjoint partition; parent_id links remain for drill-down.
    """
    has_children = {
        c.get("parent_id") for c in communities if c.get("parent_id") is not None
    }
    visible = sorted(
        (
            c
            for c in communities
            if not c.get("is_singleton", False)
            and c.get("entity_count", 0) >= 2
            and c.get("community_id") not in has_children
        ),
        key=lambda c: (-c.get("entity_count", 0), c.get("community_id", 0)),
    )
    shown = [format_community_summary(c) for c in visible[:top_n]]
    rest = visible[top_n:]
    if rest:
        shown.append(
            {
                "id": -1,
                "name": f"… {len(rest)} smaller communities",
                "entity_count": sum(c.get("entity_count", 0) for c in rest),
                "file_count": 0,
                "top_entities": [],
                "description": "",
                "file_paths": [],
                "is_aggregate": True,
            }
        )
    return shown
