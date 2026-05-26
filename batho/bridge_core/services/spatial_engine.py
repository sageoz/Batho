"""Spatial Engine - Backend layout computation and viewport culling.

Uses igraph for deterministic layout computation and dynamic quadtree
for efficient viewport-based geometry serving.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import Any, Literal

import igraph
import msgpack

from batho.context.codegraph import InMemoryGraph
from batho.utils.logging import get_logger

LOGGER = get_logger(__name__, component="bridge_core.services.spatial_engine")


@dataclass
class SpatialNode:
    """A node with spatial coordinates."""
    id: str
    x: float
    y: float
    size: float = 1.0
    node_type: str = "unknown"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SpatialEdge:
    """An edge with spatial endpoints."""
    source: str
    target: str
    weight: float = 1.0


@dataclass
class QuadtreeNode:
    """Dynamic quadtree node for spatial indexing."""
    x_min: float
    y_min: float
    x_max: float
    y_max: float
    depth: int
    max_depth: int = 8
    max_items: int = 16
    
    children: list["QuadtreeNode"] | None = None
    items: list[SpatialNode] = field(default_factory=list)
    
    def insert(self, node: SpatialNode) -> bool:
        """Insert a node into the quadtree."""
        if not self._contains(node.x, node.y):
            return False
        
        # If at max depth or not full, add directly
        if self.depth >= self.max_depth or len(self.items) < self.max_items:
            self.items.append(node)
            return True
        
        # Subdivide if needed
        if self.children is None:
            self._subdivide()
        
        # Try to insert into children
        for child in self.children:
            if child.insert(node):
                return True
        
        # Fallback: keep at this level
        self.items.append(node)
        return True
    
    def query(self, x_min: float, y_min: float, x_max: float, y_max: float) -> list[SpatialNode]:
        """Query nodes within bounding box."""
        results = []
        
        # Check if bounding boxes intersect
        if x_max < self.x_min or x_min > self.x_max or y_max < self.y_min or y_min > self.y_max:
            return results
        
        # Add items that fall within query bounds
        for item in self.items:
            if x_min <= item.x <= x_max and y_min <= item.y <= y_max:
                results.append(item)
        
        # Recurse into children
        if self.children:
            for child in self.children:
                results.extend(child.query(x_min, y_min, x_max, y_max))
        
        return results
    
    def get_all_nodes(self) -> list[SpatialNode]:
        """Get all nodes in this subtree."""
        results = list(self.items)
        if self.children:
            for child in self.children:
                results.extend(child.get_all_nodes())
        return results
    
    def _contains(self, x: float, y: float) -> bool:
        """Check if point is within this node's bounds."""
        return self.x_min <= x <= self.x_max and self.y_min <= y <= self.y_max
    
    def _subdivide(self) -> None:
        """Split into four quadrants."""
        x_mid = (self.x_min + self.x_max) / 2
        y_mid = (self.y_min + self.y_max) / 2
        
        self.children = [
            QuadtreeNode(self.x_min, self.y_min, x_mid, y_mid, self.depth + 1, self.max_depth, self.max_items),
            QuadtreeNode(x_mid, self.y_min, self.x_max, y_mid, self.depth + 1, self.max_depth, self.max_items),
            QuadtreeNode(self.x_min, y_mid, x_mid, self.y_max, self.depth + 1, self.max_depth, self.max_items),
            QuadtreeNode(x_mid, y_mid, self.x_max, self.y_max, self.depth + 1, self.max_depth, self.max_items),
        ]
        
        # Redistribute items
        items_to_redistribute = self.items
        self.items = []
        
        for item in items_to_redistribute:
            inserted = False
            for child in self.children:
                if child.insert(item):
                    inserted = True
                    break
            if not inserted:
                self.items.append(item)


class SpatialEngine:
    """Computes layouts and serves viewport-culled geometry.
    
    Uses igraph for layout computation and dynamic quadtree for
    efficient spatial queries.
    """
    
    def __init__(self, graph: InMemoryGraph):
        self.graph = graph
        self.nodes: dict[str, SpatialNode] = {}
        self.edges: list[SpatialEdge] = []
        self.quadtree: QuadtreeNode | None = None
        self.igraph_instance: igraph.Graph | None = None
        self._layout_cache: dict[str, tuple[list[SpatialNode], list[SpatialEdge]]] = {}
    
    def compute_layout(
        self,
        layer: Literal["L1", "L2", "L3"] = "L1",
        algorithm: Literal["kamada_kawai", "fruchterman_reingold", "lgl", "drl"] = "fruchterman_reingold",
        seed: int = 42,
        file_path: str | None = None,
    ) -> dict[str, Any]:
        """Compute deterministic layout using igraph.
        
        Args:
            layer: Which layer to layout (L1=file, L2=symbol, L3=neighborhood)
            algorithm: Layout algorithm to use
            seed: Random seed for determinism
            file_path: For L2 layer, scope layout to this file only
            
        Returns:
            Dict with layout stats and node count
        """
        # Cache hit: skip expensive igraph computation
        cache_key = (layer, algorithm, seed, file_path)
        if cache_key in self._layout_cache:
            cached_nodes, cached_edges = self._layout_cache[cache_key]
            self.nodes = {n.id: n for n in cached_nodes}
            self.edges = list(cached_edges)
            self._build_quadtree()
            LOGGER.info("layout_cache_hit", layer=layer, algorithm=algorithm, nodes=len(self.nodes))
            return {
                "ok": True,
                "layer": layer,
                "algorithm": algorithm,
                "node_count": len(self.nodes),
                "edge_count": len(self.edges),
                "latency_ms": 0.0,
                "bounds": self._get_bounds(),
                "cached": True,
            }

        start_time = time.time_ns()
        
        try:
            # Set random seed for deterministic layouts
            random.seed(seed)
            
            # Build igraph from codegraph
            self.igraph_instance = self._build_igraph(layer, file_path=file_path)
            
            if self.igraph_instance.vcount() == 0:
                return {"ok": False, "error": "No nodes to layout", "node_count": 0}
            
            # Select layout algorithm (seed param is for initial positions matrix, not RNG)
            if algorithm == "kamada_kawai":
                layout = self.igraph_instance.layout_kamada_kawai()
            elif algorithm == "fruchterman_reingold":
                layout = self.igraph_instance.layout_fruchterman_reingold()
            elif algorithm == "lgl":
                layout = self.igraph_instance.layout_lgl()
            elif algorithm == "drl":
                layout = self.igraph_instance.layout_drl()
            else:
                layout = self.igraph_instance.layout_kamada_kawai()
            
            # Convert to spatial nodes
            self.nodes = {}
            for i, vertex in enumerate(self.igraph_instance.vs):
                node_id = vertex["name"]
                x, y = layout[i]
                attrs = vertex.attributes()
                self.nodes[node_id] = SpatialNode(
                    id=node_id,
                    x=x,
                    y=y,
                    size=attrs.get("size", 1.0),
                    node_type=attrs.get("type", "unknown"),
                    metadata=attrs,
                )
            
            # Build spatial edges
            self.edges = []
            for edge in self.igraph_instance.es:
                source_id = self.igraph_instance.vs[edge.source]["name"]
                target_id = self.igraph_instance.vs[edge.target]["name"]
                edge_attrs = edge.attributes()
                self.edges.append(SpatialEdge(
                    source=source_id,
                    target=target_id,
                    weight=edge_attrs.get("weight", 1.0),
                ))
            
            # Build quadtree
            self._build_quadtree()
            
            latency_ms = (time.time_ns() - start_time) / 1e6
            
            # Store in cache for subsequent calls
            self._layout_cache[cache_key] = (list(self.nodes.values()), list(self.edges))

            LOGGER.info(
                "layout_computed",
                layer=layer,
                algorithm=algorithm,
                nodes=len(self.nodes),
                edges=len(self.edges),
                latency_ms=latency_ms,
            )
            
            return {
                "ok": True,
                "layer": layer,
                "algorithm": algorithm,
                "node_count": len(self.nodes),
                "edge_count": len(self.edges),
                "latency_ms": latency_ms,
                "bounds": self._get_bounds(),
                "cached": False,
            }
            
        except Exception as e:
            LOGGER.error("layout_computation_failed", error=str(e), layer=layer)
            return {"ok": False, "error": str(e), "node_count": 0}
    
    def get_viewport(
        self,
        x: float,
        y: float,
        width: float,
        height: float,
        zoom: float = 1.0,
        layer: Literal["L1", "L2", "L3"] = "L1",
    ) -> dict[str, Any]:
        """Get geometry for viewport bounding box.
        
        Args:
            x: Viewport center X
            y: Viewport center Y
            width: Viewport width
            height: Viewport height
            zoom: Zoom level (higher = more detail)
            layer: Which layer to query
            
        Returns:
            Dict with nodes and edges for the viewport
        """
        if not self.quadtree or not self.nodes:
            return {"ok": False, "error": "No layout computed", "nodes": [], "edges": []}
        
        start_time = time.time_ns()
        
        # Calculate query bounds
        x_min = x - width / 2
        x_max = x + width / 2
        y_min = y - height / 2
        y_max = y + height / 2
        
        # Query quadtree
        nodes_in_viewport = self.quadtree.query(x_min, y_min, x_max, y_max)
        
        # LOD: limit nodes at low zoom levels
        max_nodes = self._get_max_nodes_for_zoom(zoom)
        if len(nodes_in_viewport) > max_nodes:
            # Sort by importance (size/degree) and take top N
            nodes_in_viewport.sort(key=lambda n: n.size, reverse=True)
            nodes_in_viewport = nodes_in_viewport[:max_nodes]
        
        # Get node IDs for edge filtering
        node_ids = {n.id for n in nodes_in_viewport}
        
        # Filter edges to only those with both endpoints visible
        edges_in_viewport = [
            e for e in self.edges
            if e.source in node_ids and e.target in node_ids
        ]
        
        # LOD: simplify edges at low zoom
        max_edges = max_nodes * 2
        if len(edges_in_viewport) > max_edges:
            edges_in_viewport.sort(key=lambda e: e.weight, reverse=True)
            edges_in_viewport = edges_in_viewport[:max_edges]
        
        latency_ms = (time.time_ns() - start_time) / 1e6
        
        return {
            "ok": True,
            "nodes": nodes_in_viewport,
            "edges": edges_in_viewport,
            "bounds": {"x_min": x_min, "y_min": y_min, "x_max": x_max, "y_max": y_max},
            "zoom": zoom,
            "node_count": len(nodes_in_viewport),
            "edge_count": len(edges_in_viewport),
            "latency_ms": latency_ms,
        }
    
    def encode_viewport_binary(
        self,
        x: float,
        y: float,
        width: float,
        height: float,
        zoom: float = 1.0,
        layer: Literal["L1", "L2", "L3"] = "L1",
    ) -> bytes:
        """Encode viewport geometry as binary msgpack.
        
        Returns compact binary representation for efficient wire transfer.
        """
        viewport = self.get_viewport(x, y, width, height, zoom, layer)
        
        if not viewport.get("ok"):
            return msgpack.packb({"ok": False, "error": viewport.get("error", "unknown"), "n": [], "e": []})
        
        # Pack into compact binary format
        nodes_binary = []
        for node in viewport["nodes"]:
            nodes_binary.append({
                "i": node.id,  # id
                "x": float(node.x),  # x coordinate
                "y": float(node.y),  # y coordinate
                "s": float(node.size),  # size
                "t": node.node_type,  # type
            })
        
        edges_binary = []
        for edge in viewport["edges"]:
            edges_binary.append({
                "s": edge.source,  # source
                "t": edge.target,  # target
                "w": float(edge.weight),  # weight
            })
        
        data = {
            "ok": True,
            "b": viewport["bounds"],
            "z": zoom,
            "n": nodes_binary,
            "e": edges_binary,
            "c": viewport["node_count"],
        }
        
        return msgpack.packb(data, use_bin_type=True)
    
    def get_quadtree_metadata(self) -> dict[str, Any]:
        """Get quadtree structure metadata."""
        if not self.quadtree:
            return {"ok": False, "error": "No quadtree built"}
        
        def count_nodes(qt: QuadtreeNode) -> tuple[int, int]:
            """Return (total_items, total_nodes)."""
            items = len(qt.items)
            nodes = 1
            if qt.children:
                for child in qt.children:
                    child_items, child_nodes = count_nodes(child)
                    items += child_items
                    nodes += child_nodes
            return items, nodes
        
        items, nodes = count_nodes(self.quadtree)
        
        return {
            "ok": True,
            "depth": self.quadtree.max_depth,
            "bounds": {
                "x_min": self.quadtree.x_min,
                "y_min": self.quadtree.y_min,
                "x_max": self.quadtree.x_max,
                "y_max": self.quadtree.y_max,
            },
            "total_items": items,
            "tree_nodes": nodes,
        }
    
    def get_node_position(self, node_id: str) -> tuple[float, float] | None:
        """Get coordinates for a specific node."""
        if node_id in self.nodes:
            return (self.nodes[node_id].x, self.nodes[node_id].y)
        return None
    
    def _build_igraph(self, layer: Literal["L1", "L2", "L3"], file_path: str | None = None) -> igraph.Graph:
        """Build igraph from codegraph for specified layer."""
        g = igraph.Graph(directed=True)
        
        if layer == "L1":
            # File-level aggregated graph
            self._build_l1_graph(g)
        elif layer == "L2":
            # Intra-file symbol graph — scoped to file_path when provided
            self._build_l2_graph(g, file_path=file_path)
        else:
            # L3 or default: all entities
            self._build_full_graph(g)
        
        return g
    
    def _build_l1_graph(self, g: igraph.Graph) -> None:
        """Build file-level aggregated graph."""
        # Aggregate entities by file
        files: dict[str, dict] = {}
        for entity_id, entity in self.graph.entities.items():
            file_path = entity.file
            if file_path not in files:
                files[file_path] = {
                    "id": f"file:{file_path}",
                    "entities": [],
                    "languages": set(),
                }
            files[file_path]["entities"].append(entity_id)
            # Detect language
            ext = file_path.split(".")[-1].lower() if "." in file_path else ""
            lang_map = {
                "py": "python", "js": "javascript", "ts": "typescript",
                "go": "go", "rs": "rust", "java": "java",
            }
            if ext in lang_map:
                files[file_path]["languages"].add(lang_map[ext])
        
        # Add vertices
        vertex_ids = []
        for file_path, data in files.items():
            vid = g.add_vertex(
                name=data["id"],
                file=file_path,
                entity_count=len(data["entities"]),
                size=min(len(data["entities"]), 10),  # Cap size for visualization
                type="file",
                language=list(data["languages"])[0] if data["languages"] else "unknown",
            )
            vertex_ids.append(data["id"])
        
        # Build edges
        edges_added: set[tuple[str, str]] = set()
        for rel in self.graph.relationships:
            source_entity = self.graph.get_entity(rel.source_id)
            target_entity = self.graph.get_entity(rel.target_id)
            
            if not source_entity or not target_entity:
                continue
            
            source_file = f"file:{source_entity.file}"
            target_file = f"file:{target_entity.file}"
            
            # Skip self-loops
            if source_file == target_file:
                continue
            
            edge_key = (source_file, target_file)
            if edge_key not in edges_added:
                try:
                    g.add_edge(source_file, target_file, weight=1)
                    edges_added.add(edge_key)
                except Exception:
                    pass  # Vertex might not exist
    
    def _build_l2_graph(self, g: igraph.Graph, file_path: str | None = None) -> None:
        """Build intra-file symbol graph.
        
        When file_path is provided, only includes entities from that file and
        their intra-file edges (cross-file edges are excluded). This avoids
        loading the entire codegraph into igraph for large repos.
        """
        # Determine which entities to include
        if file_path:
            entities_iter = (
                (eid, e) for eid, e in self.graph.entities.items()
                if e.file == file_path
            )
        else:
            entities_iter = self.graph.entities.items()

        included_ids: set[str] = set()
        for entity_id, entity in entities_iter:
            g.add_vertex(
                name=entity_id,
                id=entity_id,
                file=entity.file,
                name_attr=entity.name,
                type=entity.type.value,
                size=1,
            )
            included_ids.add(entity_id)
        
        # Add only edges where both endpoints are in the included set
        for rel in self.graph.relationships:
            if rel.source_id not in included_ids or rel.target_id not in included_ids:
                continue
            try:
                g.add_edge(rel.source_id, rel.target_id, weight=1, type=rel.type.value)
            except Exception:
                pass
    
    def _build_full_graph(self, g: igraph.Graph) -> None:
        """Build full entity graph."""
        self._build_l2_graph(g)
    
    def _build_quadtree(self) -> None:
        """Build dynamic quadtree from spatial nodes."""
        if not self.nodes:
            self.quadtree = None
            return
        
        # Calculate bounds with padding
        bounds = self._get_bounds()
        padding = 0.1  # 10% padding
        x_range = bounds["x_max"] - bounds["x_min"]
        y_range = bounds["y_max"] - bounds["y_min"]
        
        x_min = bounds["x_min"] - x_range * padding
        x_max = bounds["x_max"] + x_range * padding
        y_min = bounds["y_min"] - y_range * padding
        y_max = bounds["y_max"] + y_range * padding
        
        # Create quadtree
        self.quadtree = QuadtreeNode(
            x_min=x_min,
            y_min=y_min,
            x_max=x_max,
            y_max=y_max,
            depth=0,
            max_depth=8,
            max_items=16,
        )
        
        # Insert all nodes
        for node in self.nodes.values():
            self.quadtree.insert(node)
        
        LOGGER.info(
            "quadtree_built",
            nodes=len(self.nodes),
            bounds=bounds,
        )
    
    def _get_bounds(self) -> dict[str, float]:
        """Get bounding box of all nodes."""
        if not self.nodes:
            return {"x_min": 0, "y_min": 0, "x_max": 1, "y_max": 1}
        
        xs = [n.x for n in self.nodes.values()]
        ys = [n.y for n in self.nodes.values()]
        
        return {
            "x_min": min(xs),
            "y_min": min(ys),
            "x_max": max(xs),
            "y_max": max(ys),
        }
    
    def _get_max_nodes_for_zoom(self, zoom: float) -> int:
        """Get maximum nodes to render based on zoom level."""
        # Higher zoom = more detail
        if zoom >= 2.0:
            return 10000
        elif zoom >= 1.0:
            return 5000
        elif zoom >= 0.5:
            return 2000
        elif zoom >= 0.25:
            return 1000
        else:
            return 500


__all__ = ["SpatialEngine", "SpatialNode", "SpatialEdge", "QuadtreeNode"]
