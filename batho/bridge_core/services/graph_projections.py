"""Graph Projection Engine - Server-side graph projections for dashboard."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from batho.context.codegraph import InMemoryGraph
from batho.context.schema import Entity, Relationship, RelationshipType
from batho.utils.logging import get_logger

LOGGER = get_logger(__name__, component="bridge_core.services.graph_projections")


@dataclass
class GraphNode:
    """A node in the projection."""
    id: str
    label: str
    type: str
    file: str
    line: int
    metrics: dict[str, Any] = field(default_factory=dict)


@dataclass
class GraphEdge:
    """An edge in the projection."""
    source: str
    target: str
    type: str
    weight: int = 1


class GraphProjectionEngine:
    """
    Creates graph projections for dashboard hypergraph views.
    
    L1: File-level aggregated graph
    L2: Intra-file symbol graph
    L3: Node neighborhood with bidirectional emphasis
    
    Coordinates:
        When spatial_engine is provided, includes (x, y) coordinates
        computed deterministically via igraph for WebGL rendering.
    """
    
    def __init__(self, graph: InMemoryGraph, spatial_engine: Any | None = None):
        self.graph = graph
        self.spatial_engine = spatial_engine
        self._l1_cache: dict | None = None
        self._l2_cache: dict[str, dict] = {}
    
    def build_level1(self, filters: dict[str, Any] | None = None) -> dict[str, Any]:
        """
        L1: File-level aggregated graph.
        
        Returns: {
            nodes: [{id, file, language, entity_count, metrics}],
            edges: [{source, target, weight, types}],
            stats: {total_files, total_edges, filtered}
        }
        """
        # Cache hit — unfiltered result is cached after first build
        if self._l1_cache is not None and not filters:
            return self._l1_cache

        start_time = time.time_ns()

        # Single pass: build files aggregation AND entity→file index simultaneously
        files: dict[str, dict] = {}
        entity_file: dict[str, str] = {}
        for entity_id, entity in self.graph.entities.items():
            file_path = entity.file
            entity_file[entity_id] = file_path
            if file_path not in files:
                files[file_path] = {
                    "id": f"file:{file_path}",
                    "file": file_path,
                    "entities": [],
                    "languages": set(),
                    "metrics": {},
                }
            files[file_path]["entities"].append(entity_id)
            lang = self._detect_language(file_path)
            if lang:
                files[file_path]["languages"].add(lang)

        # Build aggregated edges between files
        edges: dict[tuple[str, str], dict] = {}
        for rel in self.graph.relationships:
            source_file = entity_file.get(rel.source_id)
            target_file = entity_file.get(rel.target_id)

            if not source_file or not target_file or source_file == target_file:
                continue

            rel_type = rel.type.value if hasattr(rel.type, 'value') else str(rel.type)
            edge_key = (source_file, target_file)
            if edge_key not in edges:
                edges[edge_key] = {
                    "source": f"file:{source_file}",
                    "target": f"file:{target_file}",
                    "weight": 1,
                    "types": {rel_type: 1},
                }
            else:
                edges[edge_key]["weight"] += 1
                edges[edge_key]["types"][rel_type] = edges[edge_key]["types"].get(rel_type, 0) + 1
        
        # Apply filters
        filtered_files = dict(files)
        if filters:
            if "languages" in filters:
                filtered_files = {
                    f: data for f, data in filtered_files.items()
                    if any(lang in filters["languages"] for lang in data["languages"])
                }
            if "path" in filters:
                path_filter = filters["path"]
                filtered_files = {
                    f: data for f, data in filtered_files.items()
                    if path_filter in f
                }
        
        # Build response
        nodes = []
        for f, data in filtered_files.items():
            node = {
                "id": data["id"],
                "file": data["file"],
                "language": list(data["languages"])[0] if data["languages"] else "unknown",
                "entity_count": len(data["entities"]),
                "metrics": {"complexity": len(data["entities"])},  # Simplified metric
            }
            
            # Add coordinates from spatial engine if available
            if self.spatial_engine and data["id"] in self.spatial_engine.nodes:
                spatial_node = self.spatial_engine.nodes[data["id"]]
                node["x"] = spatial_node.x
                node["y"] = spatial_node.y
            
            nodes.append(node)
        
        edge_list = list(edges.values())
        
        latency_ms = (time.time_ns() - start_time) / 1e6
        
        result = {
            "nodes": nodes,
            "edges": edge_list,
            "stats": {
                "total_files": len(nodes),
                "total_edges": len(edge_list),
                "filtered": filters is not None,
                "latency_ms": latency_ms,
            }
        }
        
        # Only cache the unfiltered result — a filtered call must not poison the slot
        if not filters:
            self._l1_cache = result
        return result
    
    def build_level2(self, file_path: str, budget: int = 2000) -> dict[str, Any]:
        """
        L2: Intra-file symbol graph.
        
        Returns all entities in file + internal edges.
        Respects node budget with pagination info.
        
        Returns: {
            nodes: [{id, name, type, line, signature}],
            edges: [{source, target, type}],
            pagination: {total, limit, has_more}
        }
        """
        # Cache hit — skip recomputation for the same file
        if file_path in self._l2_cache:
            return self._l2_cache[file_path]

        start_time = time.time_ns()
        
        # Get entities for this file
        entities = self.graph.entities_by_file(file_path)
        total_entities = len(entities)
        
        # Apply budget limit
        if total_entities > budget:
            entities = entities[:budget]
            has_more = True
        else:
            has_more = False
        
        # Build nodes
        entity_ids = {e.id for e in entities}
        nodes = [
            {
                "id": e.id,
                "name": e.name,
                "type": e.type.value,
                "line": e.start_line,
                "signature": e.signature,
            }
            for e in entities
        ]
        
        # Build internal edges using adjacency index — O(K local edges) not O(R global)
        edges = []
        for eid in entity_ids:
            for target_id in self.graph.neighbors(eid, direction="out"):
                if target_id in entity_ids:
                    edges.append({
                        "source": eid,
                        "target": target_id,
                        "type": self._get_relationship_type(eid, target_id),
                    })
        
        latency_ms = (time.time_ns() - start_time) / 1e6
        
        result = {
            "nodes": nodes,
            "edges": edges,
            "file": file_path,
            "pagination": {
                "total": total_entities,
                "limit": budget,
                "has_more": has_more,
            },
            "latency_ms": latency_ms,
        }
        
        self._l2_cache[file_path] = result
        return result
    
    def build_level3(self, node_id: str, radius: int = 1) -> dict[str, Any]:
        """
        L3: Node neighborhood with bidirectional emphasis.
        
        Emphasizes bidirectional nature:
        - "calls": Outbound edges (this node calls others)
        - "called_by": Inbound edges (others call this node)
        - "bidirectional": Both directions
        
        Returns: {
            center: {id, name, type, file, line, signature},
            outbound: [{node, edge_type}],  # Calls
            inbound: [{node, edge_type}],   # Called By
            bidirectional: [{node, edge_out, edge_in}],  # Mutual
            all_neighbors: [node_ids],  # For Cytoscape
            latency_ms: float
        }
        """
        start_time = time.time_ns()
        
        center = self.graph.get_entity(node_id)
        if not center:
            return {"error": "Node not found", "center_id": node_id}
        
        # Get neighbors by direction
        outbound_ids = self.graph.neighbors(node_id, direction="out")
        inbound_ids = self.graph.neighbors(node_id, direction="in")
        
        # Build bidirectional set
        bidirectional_ids = set(outbound_ids) & set(inbound_ids)
        
        # Collect node data
        def make_node_data(eid: str) -> dict | None:
            entity = self.graph.get_entity(eid)
            if not entity:
                return None
            return {
                "id": eid,
                "name": entity.name,
                "type": entity.type.value,
                "file": entity.file,
                "line": entity.start_line,
            }
        
        outbound = [
            {"node": node, "edge_type": self._get_relationship_type(node_id, nid)}
            for nid in outbound_ids
            if (node := make_node_data(nid))
        ]
        
        inbound = [
            {"node": node, "edge_type": self._get_relationship_type(nid, node_id)}
            for nid in inbound_ids
            if (node := make_node_data(nid))
        ]
        
        bidirectional = [
            {
                "node": make_node_data(nid),
                "edge_out": self._get_relationship_type(node_id, nid),
                "edge_in": self._get_relationship_type(nid, node_id),
            }
            for nid in bidirectional_ids
            if make_node_data(nid)
        ]
        
        # All neighbors for canvas renderer
        all_neighbor_ids = list(set(outbound_ids) | set(inbound_ids))

        # ── Bidirectional Integrity Score (BIS) ─────────────────────────
        # BIS = (|bidirectional| / |all_neighbors|) × 100, clamped 0–100.
        # A node with 100% bidirectional edges is maximally "integral";
        # a node with only unidirectional imports scores low.
        total_neighbors = len(all_neighbor_ids)
        if total_neighbors > 0:
            bis_score = round((len(bidirectional_ids) / total_neighbors) * 100, 1)
        else:
            bis_score = 100.0  # isolated node — no broken edges

        # Attach per-node bis contribution (simplified: bidir neighbours score high)
        def _make_scored_node(nid: str) -> dict | None:
            nd = make_node_data(nid)
            if nd is None:
                return None
            nd["bis_score"] = 100.0 if nid in bidirectional_ids else 0.0
            return nd

        all_nodes = [n for nid in all_neighbor_ids if (n := _make_scored_node(nid))]

        latency_ms = (time.time_ns() - start_time) / 1e6

        return {
            "center": {
                "id": center.id,
                "name": center.name,
                "type": center.type.value,
                "file": center.file,
                "line": center.start_line,
                "signature": center.signature,
            },
            "outbound": outbound,
            "inbound": inbound,
            "bidirectional": bidirectional,
            "all_neighbors": all_neighbor_ids,
            "nodes": all_nodes,
            "bis_score": bis_score,
            "radius": radius,
            "latency_ms": latency_ms,
        }
    
    def get_context_at_position(self, file_path: str, line_number: int) -> dict[str, Any]:
        """
        Get context for specific cursor position.
        Used by panel mode quick context.
        
        Returns: {
            file: str,
            line: int,
            enclosing_entity: {id, name, type},
            parent_scope: {id, name} | None,
            immediate_deps: [{name, type, direction}],
        }
        """
        entities = self.graph.entities_by_file(file_path)
        
        # Find entity containing this line
        enclosing = None
        for entity in entities:
            if entity.start_line <= line_number <= entity.end_line:
                if enclosing is None or (entity.end_line - entity.start_line) < (enclosing.end_line - enclosing.start_line):
                    enclosing = entity
        
        if not enclosing:
            return {"file": file_path, "line": line_number, "enclosing_entity": None}
        
        # Get parent scope
        parent = None
        if enclosing.parent_id:
            parent_entity = self.graph.get_entity(enclosing.parent_id)
            if parent_entity:
                parent = {"id": parent_entity.id, "name": parent_entity.name}
        
        # Get immediate dependencies
        deps = []
        for nid in self.graph.neighbors(enclosing.id, direction="out")[:5]:
            entity = self.graph.get_entity(nid)
            if entity:
                deps.append({"name": entity.name, "type": entity.type.value, "direction": "out"})
        for nid in self.graph.neighbors(enclosing.id, direction="in")[:5]:
            entity = self.graph.get_entity(nid)
            if entity:
                deps.append({"name": entity.name, "type": entity.type.value, "direction": "in"})
        
        return {
            "file": file_path,
            "line": line_number,
            "enclosing_entity": {
                "id": enclosing.id,
                "name": enclosing.name,
                "type": enclosing.type.value,
            },
            "parent_scope": parent,
            "immediate_deps": deps,
        }
    
    def optimize_context_for_budget(
        self,
        file_path: str,
        line_number: int,
        context_budget: int,  # Estimated tokens
    ) -> dict[str, Any]:
        """
        AI-optimized context extraction within token budget.
        
        Returns: {
            context_entities: [{id, name, type, relevance_score}],
            total_tokens_estimate: int,
            coverage_radius: int,
            missing_dependencies: [{name, reason}],
        }
        """
        # Implementation for context optimization
        # This would calculate token estimates and select most relevant entities
        context = self.get_context_at_position(file_path, line_number)
        
        return {
            "context_entities": [context.get("enclosing_entity")] if context.get("enclosing_entity") else [],
            "total_tokens_estimate": 100,  # Placeholder
            "coverage_radius": 1,
            "missing_dependencies": [],
        }
    
    def _detect_language(self, file_path: str) -> str:
        """Detect programming language from file extension."""
        ext = file_path.split(".")[-1].lower() if "." in file_path else ""
        lang_map = {
            "py": "python",
            "js": "javascript",
            "ts": "typescript",
            "jsx": "jsx",
            "tsx": "tsx",
            "go": "go",
            "rs": "rust",
            "java": "java",
            "cpp": "cpp",
            "c": "c",
            "h": "c",
            "rb": "ruby",
        }
        return lang_map.get(ext, "unknown")
    
    def _get_relationship_type(self, source_id: str, target_id: str) -> str:
        """O(1) relationship lookup using lazy-built edge type cache."""
        if getattr(self, '_edge_type_cache', None) is None:
            self._edge_type_cache: dict[tuple[str, str], str] = {
                (rel.source_id, rel.target_id): rel.type.value if hasattr(rel.type, 'value') else str(rel.type)
                for rel in self.graph.relationships
            }
        return self._edge_type_cache.get((source_id, target_id), "unknown")


__all__ = ["GraphProjectionEngine", "GraphNode", "GraphEdge"]
