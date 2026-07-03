"""Community detection via Leiden clustering.

Builds an igraph.Graph from InMemoryGraph relationships, runs Leiden
modularity partitioning, and produces Community summaries for MCP output.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import structlog

LOGGER = structlog.get_logger(__name__)


@dataclass
class Community:
    """A detected community of code entities."""
    id: int
    name: str
    entity_count: int
    file_count: int
    top_entities: list[str] = field(default_factory=list)
    description: str = ""
    file_paths: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "community_id": self.id,
            "name": self.name,
            "entity_count": self.entity_count,
            "file_count": self.file_count,
            "top_entities": self.top_entities,
            "description": self.description,
            "file_paths": self.file_paths,
        }


def detect_communities(graph: Any) -> list[Community]:
    """Detect communities in the code graph using Leiden clustering.

    Args:
        graph: InMemoryGraph with entities and relationships.

    Returns:
        List of Community objects sorted by entity count (descending).
    """
    if not graph.entities or not graph.relationships:
        return []

    try:
        import igraph as ig
        import leidenalg
    except ImportError:
        LOGGER.warning("community_detection_deps_missing")
        return []

    entity_ids = list(graph.entities.keys())
    id_to_idx: dict[str, int] = {}
    idx_to_id: dict[int, str] = {}
    for i, eid in enumerate(entity_ids):
        id_to_idx[eid] = i
        idx_to_id[i] = eid

    edges: list[tuple[int, int]] = []
    for rel in graph.relationships:
        src_idx = id_to_idx.get(rel.source_id)
        tgt_idx = id_to_idx.get(rel.target_id)
        if src_idx is not None and tgt_idx is not None and src_idx != tgt_idx:
            edges.append((src_idx, tgt_idx))

    if not edges:
        return []

    ig_graph = ig.Graph(n=len(entity_ids), edges=edges, directed=True)

    try:
        partition = leidenalg.find_partition(
            ig_graph,
            leidenalg.ModularityVertexPartition,
        )
    except Exception as exc:
        LOGGER.warning("community_detection_failed", error=str(exc))
        return []

    communities: list[Community] = []
    for comm_idx, member_indices in enumerate(partition):
        if len(member_indices) < 2:
            continue

        member_ids = [idx_to_id[i] for i in member_indices]
        member_entities = [graph.entities[eid] for eid in member_ids if eid in graph.entities]

        file_set: set[str] = set()
        entity_names: list[str] = []
        for ent in member_entities:
            file_set.add(ent.file)
            entity_names.append(ent.name)

        degree_map: dict[str, int] = {}
        for eid in member_ids:
            degree_map[eid] = len(graph._rels_by_endpoint.get(eid, []))

        top_sorted = sorted(member_ids, key=lambda e: degree_map.get(e, 0), reverse=True)
        top_names = [graph.entities[eid].name for eid in top_sorted[:10] if eid in graph.entities]

        comm_name = top_names[0] if top_names else f"Community {comm_idx}"
        description = f"{len(member_entities)} entities across {len(file_set)} files. "
        description += f"Key: {', '.join(top_names[:5])}"

        communities.append(Community(
            id=comm_idx,
            name=comm_name,
            entity_count=len(member_entities),
            file_count=len(file_set),
            top_entities=top_names,
            description=description,
            file_paths=sorted(file_set),
        ))

    communities.sort(key=lambda c: c.entity_count, reverse=True)
    LOGGER.info("community_detection_complete", communities=len(communities))
    return communities


def communities_to_rows(communities: list[Community]) -> list[dict[str, Any]]:
    """Convert Community objects to row dicts for IPC writing."""
    return [c.to_dict() for c in communities]
