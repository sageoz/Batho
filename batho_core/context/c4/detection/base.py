"""
Base class for architectural pattern detectors.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Set
from pathlib import Path

from batho_core.utils.logging import get_logger


class DetectionResult:
    """Result of a pattern detection."""
    
    def __init__(
        self,
        pattern_type: str,
        confidence: float,
        entities: List[Dict[str, Any]],
        relationships: List[Dict[str, Any]],
        metadata: Optional[Dict[str, Any]] = None
    ):
        self.pattern_type = pattern_type
        self.confidence = confidence
        self.entities = entities
        self.relationships = relationships
        self.metadata = metadata or {}
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "pattern_type": self.pattern_type,
            "confidence": self.confidence,
            "entities": self.entities,
            "relationships": self.relationships,
            "metadata": self.metadata
        }


class PatternDetector(ABC):
    """Base class for all pattern detectors."""
    
    def __init__(self, name: str, min_confidence: float = 0.5):
        self.name = name
        self.min_confidence = min_confidence
        self.logger = get_logger(__name__, component=f"detector_{name}")
    
    @abstractmethod
    def detect(
        self,
        graph: Dict[str, Any],
        repomap: Dict[str, Any],
        rules: Optional[Dict[str, Any]] = None
    ) -> List[DetectionResult]:
        """
        Detect patterns in the given repository.
        
        Args:
            graph: Code graph data.
            repomap: Repository map data.
            rules: Optional rule data for reference.
            
        Returns:
            List of detection results.
        """
        pass
    
    def _find_files_by_pattern(
        self,
        repomap: Dict[str, Any],
        patterns: List[str],
        case_sensitive: bool = True
    ) -> List[str]:
        """Find files matching the given patterns."""
        matching_files = []
        
        for file_path in repomap.get("files", {}).keys():
            file_path_lower = file_path.lower() if not case_sensitive else file_path
            
            for pattern in patterns:
                pattern_lower = pattern.lower() if not case_sensitive else pattern
                
                if pattern_lower in file_path_lower:
                    matching_files.append(file_path)
                    break
        
        return matching_files
    
    def _find_imports_by_pattern(
        self,
        graph: Dict[str, Any],
        patterns: List[str],
        case_sensitive: bool = False
    ) -> List[Dict[str, Any]]:
        """Find imports matching the given patterns."""
        matching_imports = []
        
        for rel in graph.get("relationships", []):
            if rel.get("type") == "IMPORTS":
                target = rel.get("target", "")
                target_lower = target.lower() if not case_sensitive else target
                
                for pattern in patterns:
                    pattern_lower = pattern.lower() if not case_sensitive else pattern
                    
                    if pattern_lower in target_lower:
                        matching_imports.append(rel)
                        break
        
        return matching_imports
    
    def _find_entities_by_pattern(
        self,
        graph: Dict[str, Any],
        name_patterns: List[str],
        entity_types: Optional[List[str]] = None,
        case_sensitive: bool = False
    ) -> List[Dict[str, Any]]:
        """Find entities matching name patterns."""
        import fnmatch
        matching_entities = []
        
        for entity in graph.get("entities", []):
            # Filter by entity type if specified
            if entity_types and entity.get("type", "").lower() not in [t.lower() for t in entity_types]:
                continue
            
            name = entity.get("name", "")
            
            for pattern in name_patterns:
                # Use fnmatch for wildcard pattern matching
                if fnmatch.fnmatch(name if case_sensitive else name.lower(), 
                                 pattern if case_sensitive else pattern.lower()):
                    matching_entities.append(entity)
                    break
        
        return matching_entities
    
    def _calculate_confidence(
        self,
        indicators: List[bool],
        weights: Optional[List[float]] = None
    ) -> float:
        """Calculate confidence from boolean indicators."""
        if not indicators:
            return 0.0
        
        weights = weights or [1.0] * len(indicators)
        
        if len(indicators) != len(weights):
            raise ValueError("Indicators and weights must have same length")
        
        weighted_sum = sum(i * w for i, w in zip(indicators, weights))
        total_weight = sum(weights)
        
        return weighted_sum / total_weight if total_weight > 0 else 0.0
    
    def _group_entities_by_directory(
        self,
        entities: List[Dict[str, Any]]
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Group entities by their directory."""
        groups = {}
        
        for entity in entities:
            file_path = entity.get("file", "")
            directory = str(Path(file_path).parent)
            
            if directory not in groups:
                groups[directory] = []
            
            groups[directory].append(entity)
        
        return groups
    
    def _find_relationships_between_entities(
        self,
        graph: Dict[str, Any],
        source_entities: List[Dict[str, Any]],
        target_entities: List[Dict[str, Any]],
        relationship_types: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """Find relationships between two sets of entities."""
        source_ids = {e.get("id") for e in source_entities}
        target_ids = {e.get("id") for e in target_entities}
        
        matching_relationships = []
        
        for rel in graph.get("relationships", []):
            # Filter by relationship type if specified
            if relationship_types and rel.get("type") not in relationship_types:
                continue
            
            if (rel.get("source") in source_ids and 
                rel.get("target") in target_ids):
                matching_relationships.append(rel)
        
        return matching_relationships
