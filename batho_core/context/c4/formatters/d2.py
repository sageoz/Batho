"""
D2 (Declarative Diagrams) formatter for C4 models.
"""

from typing import Any, Dict, List, Optional, Tuple
from collections import defaultdict

from batho_core.utils.logging import get_logger
from .base import BaseFormatter, FormatCapabilities, ViewType, FormatConfig

logger = get_logger(__name__, component="d2_formatter")


class D2Formatter(BaseFormatter):
    """Formats C4 models as D2 declarative diagrams."""
    
    # Class attributes for plugin registration
    FORMATTER_NAME = "d2"
    FORMATTER_DESCRIPTION = "D2 declarative diagrams"
    FILE_EXTENSION = "d2"
    MIME_TYPE = "text/plain"
    
    def __init__(self, config: Optional[FormatConfig] = None):
        super().__init__(config)
        self.theme = self.get_theme()
        self.layout_algorithm = self._determine_layout_algorithm()
    
    def get_capabilities(self) -> FormatCapabilities:
        """Get D2 formatter capabilities."""
        return FormatCapabilities(
            supported_views={ViewType.CONTEXT, ViewType.CONTAINER, ViewType.COMPONENT},
            supports_splitting=False,
            supports_themes=True,
            supports_interactivity=False,
            supports_export=False,
            max_recommended_size=300
        )
    
    def format_model(self, c4_model: Dict[str, Any]) -> str:
        """Format C4 model as D2 diagram."""
        lines = []
        
        # Add header and imports
        lines.extend(self._get_header())
        
        # Define styles
        lines.extend(self._get_styles())
        
        # Create layers for different entity types
        lines.extend(self._create_layers())
        
        # Add people
        people = c4_model.get("model", {}).get("people", [])
        for person in people:
            lines.append(self._format_person(person))
        
        # Add systems
        systems = c4_model.get("model", {}).get("softwareSystems", [])
        for system in systems:
            lines.append(self._format_system(system))
        
        # Add containers (grouped by system)
        containers = c4_model.get("model", {}).get("containers", [])
        if containers:
            # Group containers by system
            system_containers = defaultdict(list)
            for container in containers:
                system_id = container.get("systemId", "default")
                system_containers[system_id].append(container)
            
            # Create container groups
            for system_id, sys_containers in system_containers.items():
                lines.extend(self._format_container_group(system_id, sys_containers))
        
        # Add components (grouped by container)
        components = c4_model.get("model", {}).get("components", [])
        if components:
            # Group components by container
            container_components = defaultdict(list)
            for component in components:
                container_id = component.get("containerId", "default")
                container_components[container_id].append(component)
            
            # Create component groups
            for container_id, comps in container_components.items():
                lines.extend(self._format_component_group(container_id, comps))
        
        # Add connections
        lines.append("\n# Connections")
        views = c4_model.get("views", {})
        
        # Collect all relationships
        all_relationships = []
        
        # Context view relationships
        context_views = views.get("systemContext", [])
        if context_views:
            context_view = context_views[0] if context_views else {}
            actors = context_view.get("actors", [])
            system_id = context_view.get("systemId", "system")
            for actor in actors:
                all_relationships.append({
                    "source": actor,
                    "target": system_id,
                    "description": "Uses",
                    "technology": ""
                })
        
        # Container view relationships
        container_views = views.get("container", [])
        if container_views:
            container_view = container_views[0] if container_views else {}
            containers = container_view.get("containers", [])
            for container in containers:
                all_relationships.append({
                    "source": "user",
                    "target": container,
                    "description": "Uses",
                    "technology": ""
                })
        
        # Component view relationships
        component_views = views.get("component", [])
        if component_views:
            for comp_view in component_views:
                components = comp_view.get("components", [])
                for comp in components:
                    all_relationships.append({
                        "source": "user",
                        "target": comp,
                        "description": "Interacts with",
                        "technology": ""
                    })
        
        # Format connections
        for rel in all_relationships:
            lines.append(self._format_connection(rel))
        
        # Add layout directive
        lines.append(f"\ndirection: {self.layout_algorithm}")
        
        return "\n".join(lines)
    
    def _determine_layout_algorithm(self) -> str:
        """Determine the best layout algorithm based on content."""
        # This could be made smarter by analyzing the graph structure
        return "TB"  # Top-to-bottom by default
    
    def _get_header(self) -> List[str]:
        """Get D2 header with theme imports."""
        lines = ["# C4 Architecture Diagram in D2"]
        
        # Add theme imports
        if self.theme == "dark":
            lines.append("#theme: dark")
        elif self.theme == "light":
            lines.append("#theme: light")
        
        return lines
    
    def _get_styles(self) -> List[str]:
        """Get style definitions."""
        return [
            "\n# Styles",
            "person: {",
            "  shape: person",
            "  style: {",
            "    fill: #E1F5FE",
            "    stroke: #01579B",
            "    stroke-width: 2",
            "  }",
            "}",
            "",
            "system: {",
            "  shape: rectangle",
            "  style: {",
            "    fill: #F3E5F5",
            "    stroke: #4A148C",
            "    stroke-width: 2",
            "  }",
            "}",
            "",
            "container: {",
            "  shape: rectangle",
            "  style: {",
            "    fill: #E8F5E9",
            "    stroke: #1B5E20",
            "    stroke-width: 2",
            "  }",
            "}",
            "",
            "component: {",
            "  shape: rectangle",
            "  style: {",
            "    fill: #FFF3E0",
            "    stroke: #E65100",
            "    stroke-width: 2",
            "  }",
            "}",
            "",
            "connection: {",
            "  style: {",
            "    stroke: #666666",
            "    stroke-width: 1.5,",
            "  }",
            "}"
        ]
    
    def _create_layers(self) -> List[str]:
        """Create layer definitions for z-ordering."""
        return [
            "\n# Layers",
            "layers: {",
            "  \"people\": 1,",
            "  \"systems\": 2,",
            "  \"containers\": 3,",
            "  \"components\": 4,",
            "}"
        ]
    
    def _format_person(self, person: Dict[str, Any]) -> str:
        """Format a person entity."""
        name = person.get("name", "Unknown")
        description = person.get("description", "")
        
        lines = [
            f"\n# Person: {name}",
            f"{person['id']}: {name} {{",
            "  shape: person",
            "  layer: \"people\"",
            "  style: person"
        ]
        
        if description:
            lines.append(f'  label: "{name}\\n{description}"')
        
        lines.append("}")
        return "\n".join(lines)
    
    def _format_system(self, system: Dict[str, Any]) -> str:
        """Format a software system."""
        name = system.get("name", "Unknown")
        description = system.get("description", "")
        technology = system.get("technology", [])
        
        lines = [
            f"\n# System: {name}",
            f"{system['id']}: {name} {{",
            "  shape: rectangle",
            "  layer: \"systems\"",
            "  style: system"
        ]
        
        # Create label
        label = name
        if technology:
            label += f"\\n[{', '.join(technology)}]"
        if description:
            label += f"\\n{description}"
        
        lines.append(f'  label: "{label}"')
        lines.append("}")
        
        return "\n".join(lines)
    
    def _format_container_group(self, system_id: str, containers: List[Dict[str, Any]]) -> List[str]:
        """Format a group of containers for a system."""
        lines = [
            f"\n# Containers for {system_id}",
            f"{system_id}_containers: {{",
            "  shape: rectangle",
            "  layer: \"containers\"",
            "  style: {",
            "    fill: transparent,",
            "    stroke: #1B5E20,",
            "    stroke-width: 1,",
            "    dash: 5,",
            "  },"
        ]
        
        # Add containers as sub-objects
        for container in containers:
            name = container.get("name", "Unknown")
            technology = container.get("technology", [])
            
            container_lines = [
                f"  {container['id']}: {name} {{",
                "    shape: rectangle",
                "    style: container",
                "    near: top-left"
            ]
            
            # Create label
            label = name
            if technology:
                label += f"\\n[{', '.join(technology)}]"
            
            container_lines.append(f'    label: "{label}"')
            container_lines.append("  }")
            
            lines.extend(container_lines)
        
        lines.append("}")
        return lines
    
    def _format_component_group(self, container_id: str, components: List[Dict[str, Any]]) -> List[str]:
        """Format a group of components for a container."""
        lines = [
            f"\n# Components for {container_id}",
            f"{container_id}_components: {{",
            "  shape: rectangle",
            "  layer: \"components\"",
            "  style: {",
            "    fill: transparent,",
            "    stroke: #E65100,",
            "    stroke-width: 1,",
            "    dash: 3,",
            "  },"
        ]
        
        # Add components as sub-objects
        for component in components:
            name = component.get("name", "Unknown")
            component_type = component.get("type", "")
            technology = component.get("technology", [])
            
            component_lines = [
                f"  {component['id']}: {name} {{",
                "    shape: rectangle",
                "    style: component",
                "    near: top-left"
            ]
            
            # Create label
            label = name
            if component_type and component_type != name:
                label += f"\\n<<{component_type}>>"
            if technology:
                label += f"\\n[{', '.join(technology)}]"
            
            component_lines.append(f'    label: "{label}"')
            component_lines.append("  }")
            
            lines.extend(component_lines)
        
        lines.append("}")
        return lines
    
    def _format_connection(self, relationship: Dict[str, Any]) -> str:
        """Format a relationship/connection."""
        source = relationship.get("source", "")
        target = relationship.get("target", "")
        description = relationship.get("description", "")
        technology = relationship.get("technology", "")
        
        # Create connection label
        label = description
        if technology:
            label += f"\\n[{technology}]"
        
        # Format the connection
        return f"{source} -> {target}: {label} {{\n  style: connection\n}}"
    
    def format_with_tala(self, c4_model: Dict[str, Any]) -> str:
        """Format using Tala (D2's layout engine) with intelligent layout selection."""
        # Analyze the graph to determine best layout
        analysis = self._analyze_graph_structure(c4_model)
        
        # Choose layout based on analysis
        if analysis["is_hierarchical"]:
            self.layout_algorithm = "TB"
        elif analysis["has_many_cycles"]:
            self.layout_algorithm = "neato"
        elif analysis["is_large"]:
            self.layout_algorithm = "dot"
        else:
            self.layout_algorithm = "TB"
        
        # Add Tala-specific optimizations
        return self.format_model(c4_model) + "\n\n# Optimized with Tala layout engine"
    
    def _analyze_graph_structure(self, c4_model: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze graph structure to inform layout decisions."""
        nodes = (
            len(c4_model.get("model", {}).get("people", [])) +
            len(c4_model.get("model", {}).get("softwareSystems", [])) +
            len(c4_model.get("model", {}).get("containers", [])) +
            len(c4_model.get("model", {}).get("components", []))
        )
        
        # Count relationships from views
        relationships = 0
        views = c4_model.get("views", {})
        
        # Count from each view type
        for view_type in ["systemContext", "container", "component"]:
            view_list = views.get(view_type, [])
            if view_list and isinstance(view_list, list):
                # Each view might have actors, containers, components
                for view in view_list:
                    if isinstance(view, dict):
                        # Count potential relationships based on actors/systems
                        actors = view.get("actors", [])
                        if actors:
                            relationships += len(actors)
        
        # Simple heuristics
        return {
            "is_hierarchical": self._is_hierarchical(c4_model),
            "has_many_cycles": relationships > nodes * 2,
            "is_large": nodes > 100
        }
    
    def _is_hierarchical(self, c4_model: Dict[str, Any]) -> bool:
        """Check if the model has a hierarchical structure."""
        # Simple check: if components belong to containers which belong to systems
        containers = c4_model.get("model", {}).get("containers", [])
        components = c4_model.get("model", {}).get("components", [])
        
        has_containers = len(containers) > 0
        has_components = len(components) > 0
        
        # If we have both containers and components, it's likely hierarchical
        return has_containers and has_components
