"""
Metrics calculation utilities for repository analysis.
"""

import math
from collections import defaultdict, Counter
from typing import Dict, List, Set, Any, Tuple
from pathlib import Path

from batho_core.utils.logging import get_logger

logger = get_logger(__name__, component="granularity_metrics")


def calculate_coupling_score(graph: Dict[str, Any]) -> float:
    """
    Calculate coupling score based on inter-entity dependencies.
    
    Args:
        graph: Repository graph with entities and relationships
        
    Returns:
        Coupling score between 0 (low coupling) and 1 (high coupling)
    """
    entities = graph.get("entities", [])
    relationships = graph.get("relationships", [])
    
    if not entities:
        return 0.0
    
    # Count dependencies per entity
    dependency_counts = defaultdict(int)
    entity_ids = {e["id"] for e in entities}
    
    for rel in relationships:
        if rel.get("type") in ["IMPORTS", "DEPENDS_ON", "CALLS"]:
            source = rel.get("source")
            target = rel.get("target")
            if source in entity_ids and target in entity_ids:
                dependency_counts[source] += 1
    
    # Calculate average coupling
    if not entity_ids:
        return 0.0
    
    total_dependencies = sum(dependency_counts.values())
    max_possible = len(entities) * (len(entities) - 1)
    
    if max_possible == 0:
        return 0.0
    
    coupling = total_dependencies / max_possible
    return min(1.0, coupling)


def calculate_cohesion_score(graph: Dict[str, Any], repomap: Dict[str, Any]) -> float:
    """
    Calculate cohesion score based on functional grouping.
    
    Args:
        graph: Repository graph with entities and relationships
        repomap: Repository map with file structure
        
    Returns:
        Cohesion score between 0 (low cohesion) and 1 (high cohesion)
    """
    entities = graph.get("entities", [])
    
    if not entities:
        return 0.0
    
    # Group entities by directory/module
    directory_groups = defaultdict(list)
    for entity in entities:
        file_path = entity.get("file", "")
        if file_path:
            directory = str(Path(file_path).parent)
            directory_groups[directory].append(entity)
    
    # Calculate intra-directory relationships
    total_relationships = 0
    intra_directory_relationships = 0
    
    relationships = graph.get("relationships", [])
    entity_directories = {e["id"]: str(Path(e.get("file", "")).parent) for e in entities}
    
    for rel in relationships:
        if rel.get("type") in ["IMPORTS", "DEPENDS_ON", "CALLS"]:
            source = rel.get("source")
            target = rel.get("target")
            source_dir = entity_directories.get(source)
            target_dir = entity_directories.get(target)
            
            if source_dir and target_dir:
                total_relationships += 1
                if source_dir == target_dir:
                    intra_directory_relationships += 1
    
    if total_relationships == 0:
        return 0.5  # Neutral score when no relationships
    
    cohesion = intra_directory_relationships / total_relationships
    return cohesion


def detect_domain_boundaries(graph: Dict[str, Any], repomap: Dict[str, Any]) -> int:
    """
    Detect number of domains based on package structure and naming.
    
    Args:
        graph: Repository graph with entities
        repomap: Repository map with file structure
        
    Returns:
        Estimated number of domains
    """
    entities = graph.get("entities", [])
    
    # Extract top-level packages/directories
    packages = set()
    for entity in entities:
        file_path = entity.get("file", "")
        if file_path:
            parts = Path(file_path).parts
            if len(parts) > 1:
                packages.add(parts[0])
    
    # Look for domain indicators in names
    domain_keywords = {
        "user", "order", "payment", "product", "inventory", "shipping",
        "auth", "account", "profile", "notification", "analytics",
        "admin", "report", "search", "recommendation", "catalog"
    }
    
    domains = set(packages)
    for entity in entities:
        name = entity.get("name", "").lower()
        for keyword in domain_keywords:
            if keyword in name:
                domains.add(keyword)
    
    return len(domains)


def calculate_complexity_score(graph: Dict[str, Any], repomap: Dict[str, Any]) -> float:
    """
    Calculate overall complexity score based on multiple factors.
    
    Args:
        graph: Repository graph with entities and relationships
        repomap: Repository map with file structure
        
    Returns:
        Complexity score between 0 (simple) and 1 (complex)
    """
    entities = graph.get("entities", [])
    relationships = graph.get("relationships", [])
    
    # Base complexity from entity count
    entity_count = len(entities)
    relationship_count = len(relationships)
    
    # Normalize to 0-1 scale (using logarithmic scale)
    entity_complexity = min(1.0, math.log(entity_count + 1) / math.log(10000))
    relationship_complexity = min(1.0, math.log(relationship_count + 1) / math.log(50000))
    
    # Factor in different entity types
    entity_types = Counter(e.get("type", "").lower() for e in entities)
    type_diversity = len(entity_types) / 10  # Normalize to expected max of 10 types
    
    # Average file size complexity
    files = repomap.get("files", {})
    if files:
        # Check if files contains entity lists or metadata
        if isinstance(files, dict):
            first_value = next(iter(files.values())) if files else None
            if isinstance(first_value, list):
                # files contains entity lists, use default size
                avg_size = 1000
            else:
                # files contains metadata
                avg_size = sum(f.get("size", 0) for f in files.values()) / len(files)
        else:
            avg_size = 1000
        size_complexity = min(1.0, math.log(avg_size + 1) / math.log(10000))
    else:
        size_complexity = 0.0
    
    # Weighted combination
    complexity = (
        0.3 * entity_complexity +
        0.3 * relationship_complexity +
        0.2 * type_diversity +
        0.2 * size_complexity
    )
    
    return min(1.0, complexity)


def calculate_entity_importance(graph: Dict[str, Any]) -> Dict[str, float]:
    """
    Calculate importance score for each entity based on centrality.
    
    Args:
        graph: Repository graph with entities and relationships
        
    Returns:
        Dictionary mapping entity IDs to importance scores (0-1)
    """
    entities = graph.get("entities", [])
    relationships = graph.get("relationships", [])
    
    # Initialize scores
    importance = {e["id"]: 0.0 for e in entities}
    
    # Count incoming and outgoing relationships
    incoming = defaultdict(int)
    outgoing = defaultdict(int)
    
    for rel in relationships:
        if rel.get("type") in ["IMPORTS", "DEPENDS_ON", "CALLS", "USES"]:
            source = rel.get("source")
            target = rel.get("target")
            if source and target:
                outgoing[source] += 1
                incoming[target] += 1
    
    # Calculate importance based on relationship counts
    max_incoming = max(incoming.values()) if incoming else 1
    max_outgoing = max(outgoing.values()) if outgoing else 1
    
    for entity_id in importance:
        # Combine incoming and outgoing importance
        in_score = incoming[entity_id] / max_incoming
        out_score = outgoing[entity_id] / max_outgoing
        importance[entity_id] = (0.6 * in_score + 0.4 * out_score)
    
    return importance
