"""Community detection via Leiden clustering.

Builds an igraph.Graph from InMemoryGraph relationships, runs Leiden
modularity partitioning, and produces Community summaries for MCP output.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from batho.modules.graph.builder.protocol import GraphBackend

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
    member_entity_ids: list[str] = field(default_factory=list)
    is_singleton: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "community_id": self.id,
            "name": self.name,
            "entity_count": self.entity_count,
            "file_count": self.file_count,
            "top_entities": self.top_entities,
            "description": self.description,
            "file_paths": self.file_paths,
            "member_entity_ids": self.member_entity_ids,
            "is_singleton": self.is_singleton,
        }


def _sample_graph_by_files(graph: "GraphBackend", sample_threshold: int) -> tuple[set[str], list[Any]]:
    """Sample graph by retaining whole files until entity count <= sample_threshold.

    Files are greedily kept in descending order of entity count, which preserves
    intra-file structure while capping memory use.

    Returns:
        A set of kept entity IDs and the filtered relationships.
    """
    from collections import defaultdict

    entities_by_file: dict[str, list[str]] = defaultdict(list)
    for eid, ent in graph.entities.items():
        entities_by_file[getattr(ent, "file", "")].append(eid)

    # Sort files by entity count descending; keep whole files until under threshold
    sorted_files = sorted(
        entities_by_file.items(),
        key=lambda item: len(item[1]),
        reverse=True,
    )
    kept_ids: set[str] = set()
    running_total = 0
    for _, eids in sorted_files:
        count = len(eids)
        if running_total + count > sample_threshold and kept_ids:
            break
        kept_ids.update(eids)
        running_total += count

    filtered_rels = [
        rel for rel in graph.relationships
        if rel.source_id in kept_ids and rel.target_id in kept_ids
    ]
    return kept_ids, filtered_rels


def detect_communities(graph: "GraphBackend", config: dict[str, Any] | None = None) -> list[Community]:
    """Detect communities in the code graph using Leiden clustering.

    Args:
        graph: Graph backend (InMemoryGraph or ArrowGraph) with entities and
            relationships.
        config: Optional community detection configuration with keys:
            enabled, skip_threshold, sample_threshold.

    Returns:
        List of Community objects sorted by entity count (descending).
    """
    if config is None:
        config = {}
    enabled = bool(config.get("enabled", True))
    skip_threshold = int(config.get("skip_threshold", 200_000))
    sample_threshold = int(config.get("sample_threshold", 100_000))

    if not enabled:
        LOGGER.info("community_detection_disabled_by_config")
        return []

    if not graph.entities or not graph.relationships:
        return []

    entity_count = len(graph.entities)
    if entity_count > skip_threshold:
        LOGGER.warning(
            "community_detection_skipped_large_graph",
            entity_count=entity_count,
            skip_threshold=skip_threshold,
        )
        return []

    relationships = graph.relationships
    sampled = False
    if entity_count > sample_threshold:
        LOGGER.info(
            "community_detection_sampling_graph",
            entity_count=entity_count,
            sample_threshold=sample_threshold,
        )
        kept_ids, relationships = _sample_graph_by_files(graph, sample_threshold)
        sampled = True
        LOGGER.info(
            "community_detection_sampled_graph",
            kept_entities=len(kept_ids),
            kept_relationships=len(relationships),
        )

    try:
        import igraph as ig
        import leidenalg
    except ImportError:
        LOGGER.warning("community_detection_deps_missing")
        return []

    if not sampled:
        entity_ids = list(graph.entities.keys())
    else:
        # Sampled graph: only kept entities participate
        entity_ids = sorted(
            {eid for rel in relationships for eid in (rel.source_id, rel.target_id)}
        )
        if not entity_ids:
            return []

    id_to_idx: dict[str, int] = {}
    idx_to_id: dict[int, str] = {}
    for i, eid in enumerate(entity_ids):
        id_to_idx[eid] = i
        idx_to_id[i] = eid

    edges: list[tuple[int, int]] = []
    for rel in relationships:
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
        if len(member_indices) < 1:
            continue

        member_ids = [idx_to_id[i] for i in member_indices]
        member_entities = [graph.entities[eid] for eid in member_ids if eid in graph.entities]
        is_singleton = len(member_indices) == 1

        file_set: set[str] = set()
        entity_names: list[str] = []
        for ent in member_entities:
            file_set.add(ent.file)
            entity_names.append(ent.name)

        degree_map: dict[str, int] = {}
        for eid in member_ids:
            try:
                degree_map[eid] = graph.degree_by_endpoint(eid)
            except Exception:
                degree_map[eid] = 0

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
            member_entity_ids=member_ids,
            is_singleton=is_singleton,
        ))

    communities.sort(key=lambda c: c.entity_count, reverse=True)
    LOGGER.info("community_detection_complete", communities=len(communities))
    return communities


def communities_to_rows(communities: list[Community]) -> list[dict[str, Any]]:
    """Convert Community objects to row dicts for IPC writing."""
    return [c.to_dict() for c in communities]
