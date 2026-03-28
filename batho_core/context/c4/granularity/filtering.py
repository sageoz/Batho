"""
View filtering engine for generating focused C4 views.
"""

from enum import Enum
from typing import Dict, List, Any, Optional, Set, Tuple
from dataclasses import dataclass
from collections import defaultdict

from batho_core.utils.logging import get_logger
from .analyzer import RepositoryMetrics

logger = get_logger(__name__, component="granularity_filtering")


class FilterLevel(Enum):
    """Levels of view filtering."""
    OVERVIEW = "overview"       # High-level overview only
    IMPORTANT = "important"     # Important components only
    STANDARD = "standard"       # Balanced view
    DETAILED = "detailed"       # Most components included
    COMPREHENSIVE = "comprehensive"  # Everything included


@dataclass
class ViewFilter:
    """Filter configuration for a specific view."""
    name: str
    description: str
    filter_level: FilterLevel
    importance_threshold: float
    max_components: Optional[int]
    include_relationships: bool
    relationship_threshold: float
    focus_domains: Optional[List[str]]
    metadata: Dict[str, Any]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "name": self.name,
            "description": self.description,
            "filterLevel": self.filter_level.value,
            "importanceThreshold": self.importance_threshold,
            "maxComponents": self.max_components,
            "includeRelationships": self.include_relationships,
            "relationshipThreshold": self.relationship_threshold,
            "focusDomains": self.focus_domains,
            "metadata": self.metadata
        }


class ViewFilteringEngine:
    """Generates filtered views of C4 models."""
    
    def __init__(self):
        self.logger = get_logger(self.__class__.__name__, component="granularity_filtering")
        self.custom_filters: List[ViewFilter] = []
    
    def add_custom_filter(self, filter_config: ViewFilter) -> None:
        """Add a custom view filter."""
        self.custom_filters.append(filter_config)
        self.logger.info("Added custom view filter", filter_name=filter_config.name)
    
    def generate_filters(
        self,
        metrics: RepositoryMetrics,
        components: List[Dict[str, Any]],
        containers: List[Dict[str, Any]],
        domains: Optional[List[str]] = None
    ) -> List[ViewFilter]:
        """
        Generate appropriate view filters based on repository characteristics.
        
        Args:
            metrics: Repository metrics
            components: List of all components
            containers: List of all containers
            domains: List of detected domains
            
        Returns:
            List of ViewFilter objects
        """
        filters = []
        
        # Always generate overview filter
        filters.append(self._create_overview_filter(metrics))
        
        # Generate domain-specific filters if multiple domains
        if domains and len(domains) > 1:
            for domain in domains:
                filters.append(self._create_domain_filter(domain, metrics))
        
        # Generate importance-based filters
        if metrics.entity_count > 100:
            filters.append(self._create_important_filter(metrics))
        
        # Generate progressive disclosure filters for large repos
        if metrics.entity_count > 1000:
            filters.append(self._create_progressive_filters(metrics))
        
        # Add custom filters
        filters.extend(self.custom_filters)
        
        self.logger.info(
            "Generated view filters",
            filter_count=len(filters),
            repository_size=metrics.size_category
        )
        
        return filters
    
    def _create_overview_filter(self, metrics: RepositoryMetrics) -> ViewFilter:
        """Create high-level overview filter."""
        return ViewFilter(
            name="overview",
            description="High-level overview of the system",
            filter_level=FilterLevel.OVERVIEW,
            importance_threshold=0.7,
            max_components=50,
            include_relationships=True,
            relationship_threshold=0.8,
            focus_domains=None,
            metadata={
                "purpose": "executive",
                "target_audience": "stakeholders",
                "max_complexity": "low"
            }
        )
    
    def _create_domain_filter(self, domain: str, metrics: RepositoryMetrics) -> ViewFilter:
        """Create filter focused on specific domain."""
        return ViewFilter(
            name=f"domain-{domain}",
            description=f"View focused on {domain} domain",
            filter_level=FilterLevel.STANDARD,
            importance_threshold=0.3,
            max_components=100 if metrics.size_category == "massive" else None,
            include_relationships=True,
            relationship_threshold=0.4,
            focus_domains=[domain],
            metadata={
                "purpose": "domain_analysis",
                "target_audience": "domain_experts",
                "domain": domain
            }
        )
    
    def _create_important_filter(self, metrics: RepositoryMetrics) -> ViewFilter:
        """Create filter showing only important components."""
        threshold = 0.5 if metrics.complexity_score > 0.7 else 0.4
        
        return ViewFilter(
            name="important",
            description="View showing only important components",
            filter_level=FilterLevel.IMPORTANT,
            importance_threshold=threshold,
            max_components=200,
            include_relationships=True,
            relationship_threshold=0.6,
            focus_domains=None,
            metadata={
                "purpose": "focus",
                "target_audience": "developers",
                "threshold_type": "importance"
            }
        )
    
    def _create_progressive_filters(self, metrics: RepositoryMetrics) -> ViewFilter:
        """Create progressive disclosure filters."""
        return ViewFilter(
            name="progressive",
            description="Progressive disclosure view with layered details",
            filter_level=FilterLevel.DETAILED,
            importance_threshold=0.2,
            max_components=500,
            include_relationships=True,
            relationship_threshold=0.3,
            focus_domains=None,
            metadata={
                "purpose": "exploration",
                "target_audience": "architects",
                "progressive_levels": 3
            }
        )
    
    def apply_filter(
        self,
        c4_model: Dict[str, Any],
        filter_config: ViewFilter,
        entity_importance: Dict[str, float]
    ) -> Dict[str, Any]:
        """
        Apply filter to C4 model to create focused view.
        
        Args:
            c4_model: Complete C4 model
            filter_config: Filter configuration
            entity_importance: Importance scores for entities
            
        Returns:
            Filtered C4 model view
        """
        self.logger.info(
            "Applying view filter",
            filter_name=filter_config.name,
            threshold=filter_config.importance_threshold
        )
        
        # Start with base model structure
        filtered_model = {
            "name": f"{c4_model['name']} - {filter_config.name}",
            "description": filter_config.description,
            "model": {
                "people": c4_model["model"]["people"],
                "softwareSystems": c4_model["model"]["softwareSystems"],
                "containers": self._filter_containers(
                    c4_model["model"]["containers"],
                    filter_config,
                    entity_importance
                ),
                "components": self._filter_components(
                    c4_model["model"]["components"],
                    filter_config,
                    entity_importance
                )
            },
            "views": self._generate_filtered_views(
                c4_model,
                filter_config,
                entity_importance
            ),
            "filter_metadata": filter_config.to_dict()
        }
        
        return filtered_model
    
    def _filter_containers(
        self,
        containers: List[Dict[str, Any]],
        filter_config: ViewFilter,
        entity_importance: Dict[str, float]
    ) -> List[Dict[str, Any]]:
        """Filter containers based on configuration."""
        if filter_config.filter_level == FilterLevel.OVERVIEW:
            # Keep all containers for overview
            return containers
        
        # For other filters, keep all containers but mark importance
        filtered = []
        for container in containers:
            container_copy = container.copy()
            container_copy["importance"] = entity_importance.get(container["id"], 0.5)
            filtered.append(container_copy)
        
        return filtered
    
    def _filter_components(
        self,
        components: List[Dict[str, Any]],
        filter_config: ViewFilter,
        entity_importance: Dict[str, float]
    ) -> List[Dict[str, Any]]:
        """Filter components based on importance and other criteria."""
        filtered = []
        
        for component in components:
            importance = entity_importance.get(component["id"], 0.0)
            
            # Check importance threshold
            if importance < filter_config.importance_threshold:
                continue
            
            # Check domain focus
            if filter_config.focus_domains:
                component_domain = self._extract_component_domain(component)
                if component_domain not in filter_config.focus_domains:
                    continue
            
            # Add importance to component
            component_copy = component.copy()
            component_copy["importance"] = importance
            filtered.append(component_copy)
        
        # Apply max component limit
        if filter_config.max_components and len(filtered) > filter_config.max_components:
            # Sort by importance and keep top N
            filtered.sort(key=lambda c: c["importance"], reverse=True)
            filtered = filtered[:filter_config.max_components]
        
        return filtered
    
    def _extract_component_domain(self, component: Dict[str, Any]) -> str:
        """Extract domain from component properties."""
        file_path = component.get("properties", {}).get("file", "")
        if file_path:
            parts = file_path.split("/")
            if len(parts) > 1:
                return parts[0]
        return "default"
    
    def _generate_filtered_views(
        self,
        c4_model: Dict[str, Any],
        filter_config: ViewFilter,
        entity_importance: Dict[str, float]
    ) -> Dict[str, Any]:
        """Generate filtered views based on configuration."""
        views = {
            "systemContext": self._filter_context_view(
                c4_model.get("views", {}).get("systemContext", {}),
                filter_config
            ),
            "container": self._filter_container_view(
                c4_model.get("views", {}).get("container", {}),
                filter_config,
                entity_importance
            )
        }
        
        # Add component view if components are included
        if filter_config.filter_level in [FilterLevel.STANDARD, FilterLevel.DETAILED, FilterLevel.COMPREHENSIVE]:
            views["component"] = self._filter_component_view(
                c4_model.get("views", {}).get("component", {}),
                filter_config,
                entity_importance
            )
        
        return views
    
    def _filter_context_view(
        self,
        context_view: Dict[str, Any],
        filter_config: ViewFilter
    ) -> Dict[str, Any]:
        """Filter system context view."""
        # Context view usually doesn't need filtering
        return context_view
    
    def _filter_container_view(
        self,
        container_view: Dict[str, Any],
        filter_config: ViewFilter,
        entity_importance: Dict[str, float]
    ) -> Dict[str, Any]:
        """Filter container view."""
        if not container_view:
            return {}
        
        filtered_view = container_view.copy()
        
        # Filter relationships if needed
        if filter_config.include_relationships and "relationships" in filtered_view:
            filtered_relationships = []
            
            for rel in filtered_view["relationships"]:
                # Apply relationship threshold
                if filter_config.relationship_threshold > 0:
                    source_importance = entity_importance.get(rel.get("source", ""), 0)
                    target_importance = entity_importance.get(rel.get("target", ""), 0)
                    avg_importance = (source_importance + target_importance) / 2
                    
                    if avg_importance < filter_config.relationship_threshold:
                        continue
                
                filtered_relationships.append(rel)
            
            filtered_view["relationships"] = filtered_relationships
        
        return filtered_view
    
    def _filter_component_view(
        self,
        component_view: Dict[str, Any],
        filter_config: ViewFilter,
        entity_importance: Dict[str, float]
    ) -> Dict[str, Any]:
        """Filter component view."""
        if not component_view:
            return {}
        
        filtered_view = component_view.copy()
        
        # Filter relationships based on importance
        if "relationships" in filtered_view:
            filtered_relationships = []
            
            for rel in filtered_view["relationships"]:
                source_importance = entity_importance.get(rel.get("source", ""), 0)
                target_importance = entity_importance.get(rel.get("target", ""), 0)
                
                # Keep relationships involving important components
                if (source_importance >= filter_config.importance_threshold or
                    target_importance >= filter_config.importance_threshold):
                    
                    # Apply relationship threshold
                    if filter_config.relationship_threshold > 0:
                        avg_importance = (source_importance + target_importance) / 2
                        if avg_importance < filter_config.relationship_threshold:
                            continue
                    
                    filtered_relationships.append(rel)
            
            filtered_view["relationships"] = filtered_relationships
        
        return filtered_view
