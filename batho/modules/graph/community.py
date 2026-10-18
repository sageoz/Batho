"""Community detection via greedy modularity clustering.

Builds a networkx.Graph from InMemoryGraph relationships, runs greedy
modularity community detection, and produces Community summaries for MCP output.

Uses networkx (BSD-3-Clause) instead of leidenalg (GPL-3.0) / python-igraph
(GPL-2.0) to maintain Apache-2.0 license compatibility.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import structlog

from batho.core.schemas import EntityType, RelationshipType, entity_is_quarantined

if TYPE_CHECKING:
    from batho.modules.graph.builder.protocol import GraphBackend

LOGGER = structlog.get_logger(__name__)

# T4/T5 boundary: only structural edge kinds feed community detection.
# Annotation edges (RATIONALE_FOR) and any future inferred/heuristic relation
# type must not shape communities — they annotate the graph, they are not
# structure. Default-deny: new relation kinds are excluded until added here.
_CLUSTERING_RELATIONS: frozenset[RelationshipType] = frozenset(
    {
        RelationshipType.CALLS,
        RelationshipType.IMPORTS,
        RelationshipType.CONTAINS,
        RelationshipType.INHERITS,
        RelationshipType.IMPLEMENTS,
        RelationshipType.READS,
        RelationshipType.WRITES,
    }
)

# T4 §2 defaults — duplicated from CommunityDetectionConfig so community.py
# works when callers pass a partial dict. A weight of 0 excludes the kind
# from clustering input (CONTAINS encodes file layout, not coupling).
_DEFAULT_EDGE_WEIGHTS: dict[str, float] = {
    "CALLS": 3.0,
    "INHERITS": 3.0,
    "IMPLEMENTS": 3.0,
    "IMPORTS": 2.0,
    "READS": 1.0,
    "WRITES": 1.0,
    "CONTAINS": 0.0,
}

_DEFAULT_GENERIC_DIR_BLOCKLIST: tuple[str, ...] = (
    "src", "lib", "app", "core", "utils",
    "common", "shared", "helpers", "test", "tests",
)


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
    # NOTE (schema-compat name): despite the field name, `is_singleton` means
    # "below community_detection.min_community_entities AND unmergeable into a
    # neighbor" — i.e. a flagged small community kept as-is. It does NOT mean
    # "exactly 1 member": a 2-member community can have is_singleton=True when
    # min_community_entities is 3. The persisted communities.ipc column name is
    # unchanged to avoid schema churn; consumers must read it as
    # "small/unmergeable", not "single-member".
    is_singleton: bool = False
    # T4: deterministic heuristic label (dir-dominant / c-TF-IDF / common
    # affix / hub / fallback). Separate from `name` so a future LLM pass can
    # upgrade it without schema churn.
    heuristic_label: str = ""
    # T15: hierarchy — parent_id points at the containing community row
    # (None = top-level); level 0 = top, +1 per split depth, +1 more under
    # a domain-grouping tier.
    parent_id: int | None = None
    level: int = 0
    # T16: optional post-build labels (persisted columns; populated by
    # `batho communities label`, never by detection).
    llm_label: str = ""
    label_source: str = ""
    label_input_hash: str = ""
    label_model: str = ""

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
            "heuristic_label": self.heuristic_label,
            "parent_id": self.parent_id,
            "level": self.level,
            "llm_label": self.llm_label or None,
            "label_source": self.label_source or None,
            "label_input_hash": self.label_input_hash or None,
            "label_model": self.label_model or None,
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
        if rel.type in _CLUSTERING_RELATIONS
        and rel.source_id in kept_ids
        and rel.target_id in kept_ids
    ]
    return kept_ids, filtered_rels


def detect_communities(graph: "GraphBackend", config: dict[str, Any] | None = None) -> list[Community]:
    """Detect communities in the code graph using greedy modularity clustering.

    Args:
        graph: Graph backend (InMemoryGraph or ArrowGraph) with entities and
            relationships.
        config: Optional community detection configuration with keys:
            enabled, skip_threshold, sample_threshold.

    Returns:
        List of Community objects in construction order (partition × node
        order); callers that want a ranked view re-sort by entity_count.
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

    # T2-quarantine: `unresolved:` reference stubs are not real symbols —
    # excluding them keeps communities named after first-party code instead
    # of external packages/lockfile fragments, and prevents ghost-dominated
    # singletons. T3 extends the same exclusion to plugin-flagged entities
    # (metadata bsg.noise / bsg.quarantined — generated artifacts, vendored
    # trees, ghost externals). EXTERNAL_SYMBOL entities are pure reference
    # targets (stdlib/third-party) — never community members. At build they
    # carry `file=""` so they were incidentally unattachable isolates, but
    # artifact-rehydrated graphs (patch/plugins_apply) restore a real file
    # path that made them dir-attachable — the type check excludes them on
    # every path. Relationships touching any excluded class are dropped.
    entity_ids_all = {
        eid
        for eid, ent in graph.entities.items()
        if not entity_is_quarantined(eid, getattr(ent, "metadata", None))
        and getattr(ent, "type", None) != EntityType.EXTERNAL_SYMBOL
    }
    if not entity_ids_all:
        return []

    entity_count = len(entity_ids_all)
    if entity_count > skip_threshold:
        LOGGER.warning(
            "community_detection_skipped_large_graph",
            entity_count=entity_count,
            skip_threshold=skip_threshold,
        )
        return []

    kept_ids = entity_ids_all
    if entity_count > sample_threshold:
        LOGGER.info(
            "community_detection_sampling_graph",
            entity_count=entity_count,
            sample_threshold=sample_threshold,
        )
        # _sample_graph_by_files already restricts to _CLUSTERING_RELATIONS
        # with both endpoints kept; intersecting kept_ids with entity_ids_all
        # plus the endpoint re-check below applies the same `unresolved:` stub
        # filter as the non-sampled whitelist — so graph.relationships is
        # scanned exactly once in this branch (ff5104f331c0).
        kept_ids, whitelisted = _sample_graph_by_files(graph, sample_threshold)
        kept_ids &= entity_ids_all
        whitelisted = [
            rel for rel in whitelisted
            if rel.source_id in kept_ids and rel.target_id in kept_ids
        ]
        LOGGER.info(
            "community_detection_sampled_graph",
            kept_entities=len(kept_ids),
            kept_relationships=len(whitelisted),
        )
    else:
        whitelisted = [
            rel for rel in graph.relationships
            if rel.type in _CLUSTERING_RELATIONS
            and rel.source_id in entity_ids_all
            and rel.target_id in entity_ids_all
        ]

    try:
        import networkx as nx
    except ImportError:
        LOGGER.warning("community_detection_deps_missing")
        return []

    # ------------------------------------------------------------------
    # T15: partition into domain groups (optional L0 tier) or run flat.
    # Each partition runs the shared structural pipeline; results carry a
    # node tree (parents + children) instead of a flattened list.
    # ------------------------------------------------------------------
    domain_grouping = bool(config.get("domain_grouping", False))
    partitions: list[tuple[str | None, set[str], list[Any]]] = []
    if domain_grouping:
        groups: dict[str, list[str]] = {}
        for eid in sorted(kept_ids):
            groups.setdefault(_domain_key(graph.entities.get(eid)), []).append(eid)
        for tag in sorted(groups):
            gset = set(groups[tag])
            grels = [
                r for r in whitelisted
                if r.source_id in gset and r.target_id in gset
            ]
            partitions.append((tag, gset, grels))
    else:
        partitions.append((None, kept_ids, whitelisted))

    communities: list[Community] = []
    next_id = 0
    degree_lookup: dict[str, int] = {}
    for domain_tag, group_ids, group_rels in partitions:
        result = _cluster_partition(group_ids, group_rels, config, graph, nx)
        if result is None:
            result = _ClusterResult.empty(group_ids)
        adjacency = result.adjacency
        for eid, nbrs in adjacency.items():
            degree_lookup[eid] = len(nbrs)

        domain_comm_id: int | None = None
        level_shift = 0
        if domain_tag is not None:
            # L0 domain row: members = every entity attributed to a leaf
            # inside this partition. When the partition had no effective
            # clustering edges, `result` is None → attribute the whole group
            # to the domain row so its entities stay covered and no
            # zero-member row is persisted (COM-01).
            domain_members = sorted(
                result.leaf_of_member if result.leaf_of_member else group_ids
            )
            domain_comm_id = next_id
            next_id += 1
            communities.append(
                _build_community(
                    domain_comm_id,
                    domain_members,
                    graph,
                    adjacency,
                    level=0,
                    parent_id=None,
                    min_size=int(config.get("min_community_entities", 3)),
                    name_override=domain_tag,
                )
            )
            level_shift = 1

        # Emit the partition's node tree in BFS order. Interior nodes →
        # parent rows; surviving leaves → community rows. Merged-away
        # leaves produce no row (their members live under the parent).
        node_row_id: dict[int, int] = {}
        children_map = _children_map(result.nodes)
        for idx, (members, depth, parent_idx) in enumerate(result.nodes):
            has_children = idx in children_map
            final_idx = result.leaf_final.get(idx)
            if not has_children and final_idx is None:
                continue  # leaf merged into a sibling's final set — no row
            row_members = (
                sorted(result.final_sets[final_idx])
                if final_idx is not None
                else sorted(
                    eid
                    for eid, leaf in result.leaf_of_member.items()
                    if leaf in _descendant_leaves(children_map, idx)
                )
            )
            comm_id = next_id
            next_id += 1
            node_row_id[idx] = comm_id
            parent_comm_id = (
                node_row_id.get(parent_idx)
                if parent_idx is not None
                else domain_comm_id
            )
            communities.append(
                _build_community(
                    comm_id,
                    row_members,
                    graph,
                    adjacency,
                    level=depth + level_shift,
                    parent_id=parent_comm_id,
                    min_size=int(config.get("min_community_entities", 3)),
                )
            )

    # T4 §4 deterministic heuristic labels (separate from `name` so a future
    # LLM pass can upgrade without schema churn).
    from batho.modules.graph.community_labels import label_communities

    blocklist = config.get("generic_dir_blocklist")
    if blocklist is None:
        blocklist = list(_DEFAULT_GENERIC_DIR_BLOCKLIST)
    label_communities(
        communities,
        graph.entities,
        lambda eid: degree_lookup.get(eid, 0),
        set(str(d).lower() for d in blocklist),
    )

    LOGGER.info(
        "community_detection_complete",
        communities=len(communities),
        domain_grouping=domain_grouping,
        partitions=len(partitions),
    )
    return communities


_DOMAIN_KEY_PRIORITY = ("bsg.domain", "bsg.service_tag", "bsg.category")


def _domain_key(ent: Any) -> str:
    """Dominant domain tag for an entity (T15 L0 tier).

    Priority: bsg.domain → bsg.service_tag → bsg.category. List values vote
    lexicographically-first (deterministic); untagged → "(untagged)".
    """
    md = getattr(ent, "metadata", None) or {}
    for key in _DOMAIN_KEY_PRIORITY:
        v = md.get(key)
        if isinstance(v, (list, tuple)):
            if v:
                return str(sorted(str(x) for x in v)[0])
        elif v:
            return str(v)
    return "(untagged)"


def _children_map(nodes: list[tuple[set, int, "int | None"]]) -> dict[int, list[int]]:
    """parent_idx -> [child_idx] for a node list — built once per partition."""
    children: dict[int, list[int]] = {}
    for i, (_, _, p) in enumerate(nodes):
        if p is not None:
            children.setdefault(p, []).append(i)
    return children


def _descendant_leaves(children: dict[int, list[int]], idx: int) -> set[int]:
    """All leaf-node indices under (and including) node idx."""
    leaves: set[int] = set()
    stack = [idx]
    while stack:
        cur = stack.pop()
        kids = children.get(cur)
        if not kids:
            leaves.add(cur)
        else:
            stack.extend(kids)
    return leaves


@dataclass
class _ClusterResult:
    """Result of structural clustering over one partition (T15).

    nodes: node tree in construction order — (members, depth, parent_idx).
        Interior nodes are split parents; leaves are the unit communities.
    final_sets: surviving community member-sets post-merge/attach.
    leaf_final: leaf node idx -> final_sets idx it owns (survived).
    leaf_of_member: eid -> leaf node idx it is attributed to (original leaf
        for clustered members; owning leaf of the absorbing set for merged
        smalls / attached isolates+superhubs).
    """
    nodes: list[tuple[set[str], int, "int | None"]]
    final_sets: list[set[str]]
    leaf_final: dict[int, int]
    leaf_of_member: dict[str, int]
    adjacency: dict[str, dict[str, float]]
    cluster_id_set: set[str]

    @classmethod
    def empty(cls, group_ids: set[str]) -> "_ClusterResult":
        return cls(
            nodes=[],
            final_sets=[],
            leaf_final={},
            leaf_of_member={},
            adjacency={},
            cluster_id_set=set(),
        )


def _cluster_partition(
    kept_ids: set[str],
    whitelisted: list[Any],
    config: dict[str, Any],
    graph: "GraphBackend",
    nx: Any,
) -> "_ClusterResult | None":
    """Structural clustering over one partition of the entity set.

    Weighted edges → super-hub exclusion → greedy modularity → recursive
    oversize split (recorded as a node tree, T15) → small-comm merge →
    isolate/superhub attachment. Returns None when the partition has no
    clusterable edges (callers decide whether to emit a bare domain row).
    """
    # ------------------------------------------------------------------
    # T4 §2: weighted input. Edge weight =
    #   community_detection.edge_weights[kind] × call-site multiplicity × confidence.
    # Multiplicity and confidence fold into the per-pair sum: N duplicate
    # CALLS edges between a pair accumulate N × kind_weight × confidence.
    # Kinds with weight 0 (CONTAINS by default) are excluded from the input.
    # ------------------------------------------------------------------
    edge_weights = dict(_DEFAULT_EDGE_WEIGHTS)
    cfg_weights = config.get("edge_weights")
    if isinstance(cfg_weights, dict):
        edge_weights.update(
            {str(k).upper(): float(v) for k, v in cfg_weights.items()}
        )

    pair_weight: dict[tuple[str, str], float] = {}
    adjacency: dict[str, dict[str, float]] = {}
    for rel in whitelisted:
        kind_w = edge_weights.get(rel.type.name, 0.0)
        if kind_w <= 0:
            continue
        a, b = rel.source_id, rel.target_id
        if a == b:
            continue
        _conf = getattr(rel, "confidence", None)
        conf = 1.0 if _conf is None else float(_conf)
        if conf <= 0:
            continue  # explicit zero-confidence edge — no clustering weight
        key = (a, b) if a < b else (b, a)
        pair_weight[key] = pair_weight.get(key, 0.0) + kind_w * conf
        adjacency.setdefault(a, {})[b] = adjacency.get(a, {}).get(b, 0.0) + kind_w * conf
        adjacency.setdefault(b, {})[a] = adjacency.get(b, {}).get(a, 0.0) + kind_w * conf

    # §1 input stats — measured on the effective (weight>0) input so the
    # isolate count reflects what clustering actually sees.
    connected_ids = set(adjacency)
    isolate_ids = sorted(eid for eid in kept_ids if eid not in connected_ids)
    comp_sizes = _component_sizes(connected_ids, adjacency)
    LOGGER.info(
        "community_input_stats",
        input_entities=len(kept_ids),
        input_edges=len(pair_weight),
        isolates=len(isolate_ids),
        components=len(comp_sizes),
        component_size_histogram=_size_histogram(comp_sizes),
    )

    # §2 super-hub exclusion: drop god-nodes above the degree percentile
    # before detection; they are reattached post-hoc by max shared weight.
    superhub_pct = float(config.get("superhub_degree_percentile", 99.0))
    degrees = sorted(len(adjacency[eid]) for eid in connected_ids)
    cutoff_idx = min(len(degrees) - 1, int((superhub_pct / 100.0) * len(degrees)))
    degree_cutoff = degrees[max(cutoff_idx, 0)] if degrees else 0
    superhubs = sorted(
        eid for eid in connected_ids
        if len(adjacency[eid]) > degree_cutoff and degree_cutoff > 0
    )
    superhub_set = set(superhubs)
    cluster_ids = sorted(connected_ids - superhub_set)
    cluster_id_set = set(cluster_ids)
    if not cluster_ids:
        return None

    nx_graph = nx.Graph()
    nx_graph.add_nodes_from(cluster_ids)
    nx_graph.add_weighted_edges_from(
        (a, b, w)
        for (a, b), w in pair_weight.items()
        if a in cluster_id_set and b in cluster_id_set
    )
    if nx_graph.number_of_edges() == 0:
        return None

    try:
        communities_sets = [
            set(c)
            for c in nx.community.greedy_modularity_communities(
                nx_graph, weight="weight"
            )
        ]
    except Exception as exc:
        LOGGER.warning("community_detection_failed", error=str(exc))
        return None

    # ------------------------------------------------------------------
    # T4 §3 post-processing (all on the sampled clustering input).
    # ------------------------------------------------------------------
    min_size = int(config.get("min_community_entities", 3))
    max_fraction = float(config.get("max_community_fraction", 0.25))
    split_cap = max(1, int(max_fraction * len(cluster_ids)))

    # T15: record the split tree — each node is (members, depth, parent_idx);
    # interior nodes later emit parent community rows.
    nodes: list[tuple[set[str], int, "int | None"]] = []

    def _split_recursive(members: set[str], depth: int, parent_idx: "int | None") -> int:
        node_idx = len(nodes)
        nodes.append((members, depth, parent_idx))
        if len(members) <= split_cap or depth >= 2:
            return node_idx
        sub = nx_graph.subgraph(sorted(members))
        try:
            parts = [
                set(c)
                for c in nx.community.greedy_modularity_communities(
                    sub, weight="weight"
                )
            ]
        except Exception:
            return node_idx
        if len(parts) <= 1:
            return node_idx
        for part in sorted(parts, key=lambda s: (-len(s), sorted(s)[0])):
            _split_recursive(part, depth + 1, node_idx)
        return node_idx

    for comm in sorted(communities_sets, key=lambda s: (-len(s), sorted(s)[0])):
        _split_recursive(set(comm), 0, None)

    # Leaf nodes are the flat communities the merge/attach passes operate on
    # (identical to the old split_sets, just ordered by node index).
    children_map = _children_map(nodes)
    leaf_indices = [i for i in range(len(nodes)) if i not in children_map]
    split_sets = [nodes[i][0] for i in leaf_indices]
    split_leaf = leaf_indices  # split_sets[i] -> leaf node idx

    # Merge small communities into the neighbor with max shared edge weight;
    # unmergeable ones become flagged singletons. Shared weight between a
    # small comm and each candidate target is accumulated per member via the
    # adjacency map (O(Σ degree) per comm) — scanning all pair_weight entries
    # per pair would be O(S × F × E), which hangs near sample_threshold.
    large = [c for c in split_sets if len(c) >= min_size]
    large_leaf = [split_leaf[i] for i, c in enumerate(split_sets) if len(c) >= min_size]
    small = sorted((c for c in split_sets if len(c) < min_size), key=len)
    small_leaf = sorted(
        (split_leaf[i] for i, c in enumerate(split_sets) if len(c) < min_size),
        key=lambda i: len(nodes[i][0]),
    )
    # Copy the sets — `final_sets[i] |= comm` / `.add(eid)` must not mutate
    # the leaf node's member set in `nodes` (COM-04: the aliasing made
    # attribution order-dependent across subtrees).
    final_sets: list[set[str]] = [set(c) for c in large]
    owner_leaf: dict[int, int] = {k: leaf for k, leaf in enumerate(large_leaf)}

    # member_of maps entity → final_sets index. Built once over the large
    # seeds and maintained as small comms merge in, so it also serves the
    # isolate/superhub attachment policy below.
    member_of: dict[str, int] = {}
    for i, members in enumerate(final_sets):
        for eid in members:
            member_of[eid] = i

    singletons: list[set[str]] = []
    singleton_leaf: list[int] = []
    # Communities >= min_size stay; smaller ones merge into the strongest
    # neighbor or become flagged singletons.
    for comm, leaf_i in zip(small, small_leaf):
        # Neighbors inside `comm` or in not-yet-merged small comms have no
        # member_of entry — matching the old pairwise scan, where only edges
        # between comm and a target set counted.
        weights: dict[int, float] = {}
        for m in comm:
            for nbr, w in adjacency.get(m, {}).items():
                idx = member_of.get(nbr)
                if idx is not None:
                    weights[idx] = weights.get(idx, 0.0) + w
        if weights:
            # Highest shared weight wins; ties resolve to the lowest index,
            # identical to the previous first-strictly-greater scan order.
            best_idx = max(weights.items(), key=lambda kv: (kv[1], -kv[0]))[0]
            final_sets[best_idx] |= comm
            for eid in comm:
                member_of[eid] = best_idx
        else:
            singletons.append(comm)
            singleton_leaf.append(leaf_i)
    singleton_base = len(final_sets)
    final_sets.extend(set(s) for s in singletons)
    for offset in range(len(singletons)):
        owner_leaf[singleton_base + offset] = singleton_leaf[offset]
    # Singletons are still communities — register their members so the
    # isolate/superhub attachment policy below can see them. Without this an
    # isolate whose file-mates all sit in an unmergeable singleton is dropped,
    # and a superhub whose strongest neighbor is a singleton member attaches
    # to a weaker neighbor instead.
    for offset, members in enumerate(singletons):
        for eid in members:
            member_of[eid] = singleton_base + offset

    # §2 isolate policy: attach each isolate to its containing file's majority
    # community, else the dominant community of the file's parent directory.
    # Super-hubs reattach to the neighbor with maximum shared edge weight.

    ent_file = {eid: getattr(graph.entities.get(eid), "file", "") or "" for eid in kept_ids}
    file_members: dict[str, list[str]] = {}
    dir_members: dict[str, list[str]] = {}
    for eid, fpath in ent_file.items():
        if fpath:
            file_members.setdefault(fpath, []).append(eid)
            dir_members.setdefault(fpath.rsplit("/", 1)[0], []).append(eid)

    def _attach_to_majority(candidates: list[str]) -> int | None:
        counts: dict[int, int] = {}
        for cid in candidates:
            idx = member_of.get(cid)
            if idx is not None:
                counts[idx] = counts.get(idx, 0) + 1
        if not counts:
            return None
        return max(counts.items(), key=lambda kv: (kv[1], -kv[0]))[0]

    for eid in isolate_ids:
        fpath = ent_file.get(eid, "")
        idx = _attach_to_majority(file_members.get(fpath, []))
        if idx is None and fpath:
            idx = _attach_to_majority(
                dir_members.get(fpath.rsplit("/", 1)[0], [])
            )
        if idx is not None:
            final_sets[idx].add(eid)
            member_of[eid] = idx

    for eid in superhubs:
        best_idx, best_w = -1, 0.0
        for nbr, w in adjacency.get(eid, {}).items():
            idx = member_of.get(nbr)
            if idx is not None and w > best_w:
                best_w, best_idx = w, idx
        if best_idx >= 0:
            final_sets[best_idx].add(eid)
            member_of[eid] = best_idx

    # §3 connectivity check: each final community must be internally connected
    # within the clustered subgraph (clustered members only — attachments may
    # legitimately hang off by file/dir affinity).
    disconnected = 0
    for members in final_sets:
        clustered_members = members & cluster_id_set
        if len(clustered_members) > 1 and not _is_connected(
            clustered_members, adjacency
        ):
            disconnected += 1
    if disconnected:
        LOGGER.warning(
            "community_disconnected", count=disconnected, total=len(final_sets)
        )

    # ------------------------------------------------------------------
    # Leaf attribution: eid -> leaf node idx (original leaf for clustered
    # members; owning leaf of the absorbing set for merges/attachments).
    # ------------------------------------------------------------------
    leaf_final = owner_leaf  # final_idx -> leaf idx (invert below)
    final_owner_leaf = dict(owner_leaf)  # final idx -> leaf node idx
    leaf_to_final = {leaf: fi for fi, leaf in final_owner_leaf.items()}
    # COM-04: attribute every tracked member through member_of — the owning
    # leaf of the *absorbing* final set — instead of per-leaf scans over the
    # (previously aliased) node member sets. A small leaf that merged into a
    # leaf under a different subtree now attributes to the absorber, not to
    # whichever node iterated last.
    leaf_of_member: dict[str, int] = {
        eid: final_owner_leaf[fi] for eid, fi in member_of.items()
    }

    return _ClusterResult(
        nodes=nodes,
        final_sets=final_sets,
        leaf_final=leaf_to_final,
        leaf_of_member=leaf_of_member,
        adjacency=adjacency,
        cluster_id_set=cluster_id_set,
    )


def _build_community(
    comm_id: int,
    member_ids: list[str],
    graph: "GraphBackend",
    adjacency: dict[str, dict[str, float]],
    *,
    level: int,
    parent_id: "int | None",
    min_size: int,
    name_override: str | None = None,
) -> Community:
    """Build one Community row (leaf, split-parent, or domain tier)."""
    member_ids = sorted(member_ids)
    member_entities = [
        graph.entities[eid] for eid in member_ids if eid in graph.entities
    ]
    is_singleton = len(member_ids) < min_size

    file_set: set[str] = set()
    for ent in member_entities:
        file_set.add(ent.file)

    degree_map: dict[str, int] = {}
    for eid in member_ids:
        try:
            degree_map[eid] = graph.degree_by_endpoint(eid)
        except Exception:
            degree_map[eid] = len(adjacency.get(eid, {}))

    top_sorted = sorted(
        member_ids,
        key=lambda e: (-degree_map.get(e, 0), e),
    )
    top_names = [
        graph.entities[eid].name
        for eid in top_sorted[:10]
        if eid in graph.entities
    ]

    comm_name = name_override or (top_names[0] if top_names else f"Community {comm_id}")
    description = f"{len(member_entities)} entities across {len(file_set)} files. "
    description += f"Key: {', '.join(top_names[:5])}"

    return Community(
        id=comm_id,
        name=comm_name,
        entity_count=len(member_entities),
        file_count=len(file_set),
        top_entities=top_names,
        description=description,
        file_paths=sorted(file_set),
        member_entity_ids=member_ids,
        is_singleton=is_singleton,
        parent_id=parent_id,
        level=level,
    )


def _component_sizes(
    node_ids: set[str], adjacency: dict[str, dict[str, float]]
) -> list[int]:
    """Connected-component sizes over the weighted adjacency (BFS)."""
    seen: set[str] = set()
    sizes: list[int] = []
    for start in sorted(node_ids):
        if start in seen:
            continue
        stack = [start]
        seen.add(start)
        size = 0
        while stack:
            node = stack.pop()
            size += 1
            for nbr in adjacency.get(node, {}):
                if nbr not in seen:
                    seen.add(nbr)
                    stack.append(nbr)
        sizes.append(size)
    return sizes


def _size_histogram(sizes: list[int]) -> dict[str, int]:
    buckets = {"1": 0, "2-3": 0, "4-10": 0, "11-100": 0, ">100": 0}
    for s in sizes:
        if s == 1:
            buckets["1"] += 1
        elif s <= 3:
            buckets["2-3"] += 1
        elif s <= 10:
            buckets["4-10"] += 1
        elif s <= 100:
            buckets["11-100"] += 1
        else:
            buckets[">100"] += 1
    return buckets


def _is_connected(
    members: set[str], adjacency: dict[str, dict[str, float]]
) -> bool:
    """True when the member set forms one component over whitelisted edges."""
    start = next(iter(members))
    seen = {start}
    stack = [start]
    while stack:
        node = stack.pop()
        for nbr in adjacency.get(node, {}):
            if nbr in members and nbr not in seen:
                seen.add(nbr)
                stack.append(nbr)
    return seen == members


def communities_to_rows(communities: list[Community]) -> list[dict[str, Any]]:
    """Convert Community objects to row dicts for IPC writing."""
    return [c.to_dict() for c in communities]
