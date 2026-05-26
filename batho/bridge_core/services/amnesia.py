"""Context amnesia analyzer — LLM context limitation analysis.

Analyzes which nodes are within LLM context budget using optimized
O(V+E) graph traversal.
"""

from __future__ import annotations

import collections
from dataclasses import dataclass, field
from typing import Any

from batho.context.codegraph import InMemoryGraph
from batho.utils.logging import get_logger

LOGGER = get_logger(__name__, component="bridge_core.services.amnesia")


@dataclass
class AmnesiaAnalysis:
    center_node: str
    within_reach: list[dict] = field(default_factory=list)
    amnesia_zone: list[dict] = field(default_factory=list)
    critical_misses: list[dict] = field(default_factory=list)
    coverage_percent: float = 0.0


class ContextAmnesiaAnalyzer:
    """
    Analyzes LLM context limitations using optimized O(V+E) graph traversal.
    """
    CHARS_PER_TOKEN = 4
    
    def __init__(self, graph: InMemoryGraph):
        self.graph = graph
    
    def _get_full_neighborhood(self, start_node_id: str, max_radius: int = 3) -> list[str]:
        """
        Optimized Breadth-First Search for instant neighborhood extraction.
        
        Uses collections.deque for O(1) pops vs O(n) for list.pop(0).
        Time: O(V+E), Space: O(V)
        """
        visited = {start_node_id}
        queue = collections.deque([(start_node_id, 0)])
        
        while queue:
            current_id, depth = queue.popleft()
            if depth >= max_radius:
                continue
                
            for neighbor_id in self.graph.neighbors(current_id):
                if neighbor_id not in visited:
                    visited.add(neighbor_id)
                    queue.append((neighbor_id, depth + 1))
                    
        return list(visited)
    
    def analyze(self, center_node_id: str, context_limit: int = 4000) -> AmnesiaAnalysis:
        """Analyze which nodes are within LLM context budget."""
        # Get all nodes in radius
        all_neighbors = self._get_full_neighborhood(center_node_id, max_radius=3)
        
        within_reach = []
        amnesia_zone = []
        total_chars = 0
        budget_chars = context_limit * self.CHARS_PER_TOKEN
        
        for node_id in all_neighbors:
            entity = self.graph.get_entity(node_id)
            if not entity:
                continue
            
            # Estimate content size using robust fallback attributes
            content = getattr(entity, "raw_content", None) or getattr(entity, "source_text", None) or entity.name or ""
            node_chars = len(content)
            
            file_path = getattr(entity, "file_path", None) or getattr(entity, "file", "")
            entity_type_val = getattr(entity, "entity_type", None) or getattr(entity, "type", None)
            # convert enum to string if needed
            entity_type_str = str(entity_type_val) if entity_type_val else ""
            line = getattr(entity, "line", None) or getattr(entity, "start_line", 0)

            node_data = {
                "id": node_id,
                "name": entity.name,
                "type": entity_type_str,
                "file": file_path,
                "line": line,
            }
            
            if total_chars + node_chars <= budget_chars:
                within_reach.append(node_data)
                total_chars += node_chars
            else:
                amnesia_zone.append(node_data)
        
        # Identify critical dependencies that would be missed
        critical_misses = self._identify_critical_misses(center_node_id, amnesia_zone)
        
        coverage = len(within_reach) / len(all_neighbors) if all_neighbors else 0
        
        return AmnesiaAnalysis(
            center_node=center_node_id,
            within_reach=within_reach,
            amnesia_zone=amnesia_zone,
            critical_misses=critical_misses,
            coverage_percent=round(coverage * 100, 1)
        )
    
    def _identify_critical_misses(self, center_id: str, amnesia_nodes: list) -> list:
        """Identify high-impact nodes in the amnesia zone."""
        critical = []
        center = self.graph.get_entity(center_id)
        if not center:
            return critical
        
        center_file = getattr(center, "file_path", None) or getattr(center, "file", "")

        for node_data in amnesia_nodes:
            entity = self.graph.get_entity(node_data["id"])
            if not entity:
                continue
            
            entity_file = getattr(entity, "file_path", None) or getattr(entity, "file", "")
            # Critical if: cross-file import, public API, or error-prone
            is_cross_file = entity_file != center_file
            is_public = entity.name and not entity.name.startswith("_")
            
            if is_cross_file and is_public:
                node_data["reason"] = "Cross-file public API"
                critical.append(node_data)
        
        return critical[:10]  # Limit to top 10


__all__ = [
    "ContextAmnesiaAnalyzer",
    "AmnesiaAnalysis",
]
