"""
PlantUML formatter for C4 models.
"""

from typing import Any, Dict, List, Optional
from pathlib import Path

from batho_core.utils.logging import get_logger
from .base import BaseFormatter, FormatCapabilities, ViewType, FormatConfig

logger = get_logger(__name__, component="plantuml_formatter")


class PlantUMLFormatter(BaseFormatter):
    """Formats C4 models as PlantUML diagrams."""
    
    # Class attributes for plugin registration
    FORMATTER_NAME = "plantuml"
    FORMATTER_DESCRIPTION = "PlantUML diagram format"
    FILE_EXTENSION = "puml"
    MIME_TYPE = "text/plain"
    
    def __init__(self, config: Optional[FormatConfig] = None):
        super().__init__(config)
        self.split_threshold = self.config.split_threshold or 50
    
    def get_capabilities(self) -> FormatCapabilities:
        """Get PlantUML formatter capabilities."""
        return FormatCapabilities(
            supported_views={ViewType.CONTEXT, ViewType.CONTAINER, ViewType.COMPONENT},
            supports_splitting=True,
            supports_themes=True,
            supports_interactivity=False,
            supports_export=False,
            max_recommended_size=100
        )
    
    def format_model(self, c4_model: Dict[str, Any]) -> str:
        """Format C4 model as PlantUML."""
        if self.should_split(c4_model):
            return self._format_split_model(c4_model)
        else:
            return self._format_single_model(c4_model)
    
    def _format_single_model(self, c4_model: Dict[str, Any]) -> str:
        """Format as a single PlantUML diagram."""
        lines = []
        
        # Header
        lines.extend(self._get_header())
        
        # Add people
        people = c4_model.get("model", {}).get("people", [])
        if people:
            lines.append("\n!define PERSONS")
            for person in people:
                lines.append(self._format_person(person))
        
        # Add systems
        systems = c4_model.get("model", {}).get("softwareSystems", [])
        if systems:
            lines.append("\n!define SYSTEMS")
            for system in systems:
                lines.append(self._format_system(system))
        
        # Add containers
        containers = c4_model.get("model", {}).get("containers", [])
        if containers:
            lines.append("\n!define CONTAINERS")
            for container in containers:
                lines.append(self._format_container(container))
        
        # Add components
        components = c4_model.get("model", {}).get("components", [])
        if components:
            lines.append("\n!define COMPONENTS")
            for component in components:
                lines.append(self._format_component(component))
        
        # Add relationships
        lines.append("\n!define RELATIONSHIPS")
        views = c4_model.get("views", {})
        
        # Context view relationships
        context_views = views.get("systemContext", [])
        if context_views:
            # Extract relationships from the first context view
            context_view = context_views[0] if context_views else {}
            # Generate relationships based on actors and system
            actors = context_view.get("actors", [])
            system_id = context_view.get("systemId", "system")
            for actor in actors:
                lines.append(f'Rel({actor}, {system_id}, "Uses")')
        
        # Container view relationships
        container_views = views.get("container", [])
        if container_views:
            container_view = container_views[0] if container_views else {}
            containers = container_view.get("containers", [])
            for container in containers:
                lines.append(f'Rel(user, {container}, "Uses")')
        
        # Component view relationships
        component_views = views.get("component", [])
        if component_views:
            for comp_view in component_views:
                components = comp_view.get("components", [])
                for comp in components:
                    lines.append(f'Rel(user, {comp}, "Interacts with")')
        
        # Footer
        lines.append("@enduml")
        
        return "\n".join(lines)
    
    def _format_split_model(self, c4_model: Dict[str, Any]) -> str:
        """Format as multiple PlantUML diagrams."""
        diagrams = []
        
        # Context diagram
        context_diagram = self._format_context_view(c4_model)
        diagrams.append(("SystemContext", context_diagram))
        
        # Container diagrams (one per system)
        systems = c4_model.get("model", {}).get("softwareSystems", [])
        for system in systems:
            container_diagram = self._format_container_view(c4_model, system["id"])
            diagrams.append((f"Containers_{system['id']}", container_diagram))
        
        # Component diagrams (split if needed)
        containers = c4_model.get("model", {}).get("containers", [])
        if len(containers) > self.split_threshold:
            # Group containers by system
            system_containers = {}
            for container in containers:
                system_id = container.get("systemId", "default")
                if system_id not in system_containers:
                    system_containers[system_id] = []
                system_containers[system_id].append(container)
            
            for system_id, sys_containers in system_containers.items():
                if len(sys_containers) > self.split_threshold:
                    # Split further
                    for i in range(0, len(sys_containers), self.split_threshold):
                        batch = sys_containers[i:i + self.split_threshold]
                        component_diagram = self._format_components_batch(
                            c4_model, batch, f"{system_id}_batch_{i//self.split_threshold + 1}"
                        )
                        diagrams.append((f"Components_{system_id}_part_{i//self.split_threshold + 1}", component_diagram))
                else:
                    component_diagram = self._format_container_components(c4_model, system_id)
                    diagrams.append((f"Components_{system_id}", component_diagram))
        else:
            # Single component diagram
            component_diagram = self._format_component_view(c4_model)
            diagrams.append(("Components", component_diagram))
        
        # Combine all diagrams
        result = []
        for name, diagram in diagrams:
            result.append(f"!define {name}")
            result.append(diagram)
            result.append("")
        
        return "\n".join(result)
    
    def _get_header(self) -> List[str]:
        """Get PlantUML header with theme includes."""
        lines = ["@startuml"]
        
        # Add C4 PlantUML includes
        lines.extend([
            "!include C4_Context",
            "!include C4_Container",
            "!include C4_Component"
        ])
        
        # Add theme
        theme = self.get_theme()
        if theme == "dark":
            lines.append("!include C4_Dark")
        elif theme == "light":
            lines.append("!include C4_Light")
        
        # Add sprites if enabled
        if self.config.custom_options and self.config.custom_options.get("include_sprites", True):
            lines.append("!include sprites/aws")
            lines.append("!include sprites/azure")
            lines.append("!include sprites/gcp")
        
        # Add title
        lines.append("title C4 Architecture Diagram")
        
        return lines
    
    def _format_person(self, person: Dict[str, Any]) -> str:
        """Format a person entity."""
        name = person.get("name", "Unknown")
        description = person.get("description", "")
        return f'Person({person["id"]}, "{name}", "{description}")'
    
    def _format_system(self, system: Dict[str, Any]) -> str:
        """Format a software system."""
        name = system.get("name", "Unknown")
        description = system.get("description", "")
        technology = system.get("technology", [])
        
        tech_str = f" [{', '.join(technology)}]" if technology else ""
        return f'System({system["id"]}, "{name}", "{description}"{tech_str})'
    
    def _format_container(self, container: Dict[str, Any]) -> str:
        """Format a container."""
        name = container.get("name", "Unknown")
        description = container.get("description", "")
        technology = container.get("technology", [])
        system_id = container.get("systemId", "")
        
        tech_str = f" [{', '.join(technology)}]" if technology else ""
        return f'Container({system_id}, {container["id"]}, "{name}", "{description}"{tech_str})'
    
    def _format_component(self, component: Dict[str, Any]) -> str:
        """Format a component."""
        name = component.get("name", "Unknown")
        description = component.get("description", "")
        technology = component.get("technology", [])
        container_id = component.get("containerId", "")
        
        tech_str = f" [{', '.join(technology)}]" if technology else ""
        return f'Component({container_id}, {component["id"]}, "{name}", "{description}"{tech_str})'
    
    def _format_relationship(self, relationship: Dict[str, Any]) -> str:
        """Format a relationship."""
        source = relationship.get("source", "")
        target = relationship.get("target", "")
        description = relationship.get("description", "")
        technology = relationship.get("technology", "")
        
        tech_str = f" [{technology}]" if technology else ""
        return f'Rel({source}, {target}, "{description}"{tech_str})'
    
    def _format_context_view(self, c4_model: Dict[str, Any]) -> str:
        """Format the system context view."""
        lines = []
        
        # Add people
        for person in c4_model.get("model", {}).get("people", []):
            lines.append(self._format_person(person))
        
        # Add systems
        for system in c4_model.get("model", {}).get("softwareSystems", []):
            lines.append(self._format_system(system))
        
        # Add relationships
        context_view = c4_model.get("views", {}).get("systemContext", {})
        for rel in context_view.get("relationships", []):
            lines.append(self._format_relationship(rel))
        
        return "\n".join(lines)
    
    def _format_container_view(self, c4_model: Dict[str, Any], system_id: str) -> str:
        """Format containers for a specific system."""
        lines = []
        
        # Add system
        systems = c4_model.get("model", {}).get("softwareSystems", [])
        for system in systems:
            if system["id"] == system_id:
                lines.append(self._format_system(system))
                break
        
        # Add external systems if any
        for system in systems:
            if system["id"] != system_id:
                lines.append(f'ExternalSystem({system["id"]}, "{system.get("name", "Unknown")}", "")')
        
        # Add containers for this system
        containers = c4_model.get("model", {}).get("containers", [])
        for container in containers:
            if container.get("systemId") == system_id:
                lines.append(self._format_container(container))
        
        # Add relationships
        container_view = c4_model.get("views", {}).get("container", {})
        for rel in container_view.get("relationships", []):
            lines.append(self._format_relationship(rel))
        
        return "\n".join(lines)
    
    def _format_component_view(self, c4_model: Dict[str, Any]) -> str:
        """Format all components."""
        lines = []
        
        # Add containers
        for container in c4_model.get("model", {}).get("containers", []):
            lines.append(self._format_container(container))
        
        # Add components
        for component in c4_model.get("model", {}).get("components", []):
            lines.append(self._format_component(component))
        
        # Add relationships
        component_view = c4_model.get("views", {}).get("component", {})
        for rel in component_view.get("relationships", []):
            lines.append(self._format_relationship(rel))
        
        return "\n".join(lines)
    
    def _format_container_components(self, c4_model: Dict[str, Any], system_id: str) -> str:
        """Format components for all containers in a system."""
        lines = []
        
        # Add containers for this system
        containers = c4_model.get("model", {}).get("containers", [])
        for container in containers:
            if container.get("systemId") == system_id:
                lines.append(self._format_container(container))
        
        # Add components in these containers
        components = c4_model.get("model", {}).get("components", [])
        for component in components:
            container_id = component.get("containerId")
            if container_id:
                # Check if this container belongs to the system
                for container in containers:
                    if (container["id"] == container_id and 
                        container.get("systemId") == system_id):
                        lines.append(self._format_component(component))
                        break
        
        # Add relationships
        component_view = c4_model.get("views", {}).get("component", {})
        for rel in component_view.get("relationships", []):
            lines.append(self._format_relationship(rel))
        
        return "\n".join(lines)
    
    def _format_components_batch(
        self, 
        c4_model: Dict[str, Any], 
        containers: List[Dict[str, Any]], 
        batch_name: str
    ) -> str:
        """Format a batch of components."""
        lines = []
        
        # Add containers in this batch
        for container in containers:
            lines.append(self._format_container(container))
        
        # Add components in these containers
        container_ids = {c["id"] for c in containers}
        components = c4_model.get("model", {}).get("components", [])
        for component in components:
            if component.get("containerId") in container_ids:
                lines.append(self._format_component(component))
        
        # Add relationships
        component_view = c4_model.get("views", {}).get("component", {})
        for rel in component_view.get("relationships", []):
            lines.append(self._format_relationship(rel))
        
        return "\n".join(lines)
