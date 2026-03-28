"""
Repository analysis for adaptive granularity selection.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional
from pathlib import Path

from batho_core.utils.logging import get_logger
from .metrics import (
    calculate_coupling_score,
    calculate_cohesion_score,
    detect_domain_boundaries,
    calculate_complexity_score,
    calculate_entity_importance
)

logger = get_logger(__name__, component="granularity_analyzer")


@dataclass
class RepositoryMetrics:
    """Metrics describing repository characteristics."""
    entity_count: int = 0
    avg_file_size: float = 0.0
    coupling_score: float = 0.0  # 0-1 scale
    cohesion_score: float = 0.0  # 0-1 scale
    domain_count: int = 0
    complexity_score: float = 0.0
    size_category: str = "small"  # small/medium/large/massive
    entity_importance: Dict[str, float] = field(default_factory=dict)
    
    # Additional metrics for decision making
    file_count: int = 0
    relationship_count: int = 0
    max_file_size: int = 0
    package_count: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "entity_count": self.entity_count,
            "avg_file_size": self.avg_file_size,
            "coupling_score": self.coupling_score,
            "cohesion_score": self.cohesion_score,
            "domain_count": self.domain_count,
            "complexity_score": self.complexity_score,
            "size_category": self.size_category,
            "file_count": self.file_count,
            "relationship_count": self.relationship_count,
            "max_file_size": self.max_file_size,
            "package_count": self.package_count
        }


class RepositoryAnalyzer:
    """Analyzes repository characteristics for granularity decisions."""
    
    def __init__(self):
        self.logger = get_logger(self.__class__.__name__, component="granularity_analyzer")
    
    def analyze(
        self,
        graph: Dict[str, Any],
        repomap: Dict[str, Any],
        index_metadata: Optional[Dict[str, Any]] = None
    ) -> RepositoryMetrics:
        """
        Analyze repository and return comprehensive metrics.
        
        Args:
            graph: Repository graph with entities and relationships
            repomap: Repository map with file structure
            index_metadata: Additional metadata from index
            
        Returns:
            RepositoryMetrics with calculated values
        """
        self.logger.info("Starting repository analysis")
        
        # Basic counts
        entities = graph.get("entities", [])
        relationships = graph.get("relationships", [])
        files = repomap.get("files", {})
        
        metrics = RepositoryMetrics()
        metrics.entity_count = len(entities)
        metrics.relationship_count = len(relationships)
        metrics.file_count = len(files)
        
        # File size metrics
        if files:
            # files might be a dict of file paths to entity lists
            # or a dict of file paths to file metadata
            if isinstance(files, dict):
                # Check if values are lists (entities) or dicts (metadata)
                first_value = next(iter(files.values())) if files else None
                if isinstance(first_value, list):
                    # files contains entity lists, estimate sizes
                    metrics.avg_file_size = 1000  # Default estimate
                    metrics.max_file_size = 5000  # Default estimate
                else:
                    # files contains metadata
                    sizes = [f.get("size", 0) for f in files.values()]
                    if sizes:
                        metrics.avg_file_size = sum(sizes) / len(sizes)
                        metrics.max_file_size = max(sizes)
        
        # Calculate advanced metrics
        metrics.coupling_score = calculate_coupling_score(graph)
        metrics.cohesion_score = calculate_cohesion_score(graph, repomap)
        metrics.domain_count = detect_domain_boundaries(graph, repomap)
        metrics.complexity_score = calculate_complexity_score(graph, repomap)
        metrics.entity_importance = calculate_entity_importance(graph)
        
        # Package count
        packages = set()
        for entity in entities:
            file_path = entity.get("file", "")
            if file_path:
                parts = Path(file_path).parts
                if len(parts) > 1:
                    packages.add(parts[0])
        metrics.package_count = len(packages)
        
        # Determine size category
        metrics.size_category = self._categorize_size(metrics)
        
        self.logger.info(
            "Repository analysis complete",
            entity_count=metrics.entity_count,
            size_category=metrics.size_category,
            complexity=f"{metrics.complexity_score:.2f}"
        )
        
        return metrics
    
    def _categorize_size(self, metrics: RepositoryMetrics) -> str:
        """
        Categorize repository size based on multiple factors.
        
        Args:
            metrics: Repository metrics
            
        Returns:
            Size category: small, medium, large, or massive
        """
        # Primary factor: entity count
        entity_count = metrics.entity_count
        
        # Adjust based on complexity
        complexity_multiplier = 1.0 + metrics.complexity_score
        
        # Effective size considering complexity
        effective_size = entity_count * complexity_multiplier
        
        if effective_size < 100:
            return "small"
        elif effective_size < 1000:
            return "medium"
        elif effective_size < 10000:
            return "large"
        else:
            return "massive"
    
    def get_performance_targets(self, metrics: RepositoryMetrics) -> Dict[str, Any]:
        """
        Get performance targets based on repository size.
        
        Args:
            metrics: Repository metrics
            
        Returns:
            Dictionary with performance targets
        """
        targets = {
            "small": {"max_time": 1.0, "max_memory_mb": 100},
            "medium": {"max_time": 3.0, "max_memory_mb": 500},
            "large": {"max_time": 10.0, "max_memory_mb": 2000},
            "massive": {"max_time": 30.0, "max_memory_mb": 8000}
        }
        
        base_targets = targets[metrics.size_category]
        
        # Adjust based on complexity
        complexity_adjustment = 1.0 + (metrics.complexity_score * 0.5)
        
        return {
            "max_time_seconds": base_targets["max_time"] * complexity_adjustment,
            "max_memory_mb": base_targets["max_memory_mb"] * complexity_adjustment,
            "use_parallel_processing": metrics.entity_count > 1000,
            "use_streaming": metrics.entity_count > 10000,
            "cache_enabled": True
        }
