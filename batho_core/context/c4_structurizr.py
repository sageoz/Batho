"""
Structurizr JSON Formatting for C4 Models.

Converts C4 model data into Structurizr-compatible JSON format with extensions.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List


class StructurizrFormatter:
    """Formats C4 models as Structurizr-compatible JSON."""
    
    def __init__(self, workspace_name: str, workspace_description: str):
        self.workspace = {
            "name": workspace_name,
            "description": workspace_description,
            "version": "1.0.0",
            "revision": datetime.now(timezone.utc).isoformat(),
            "model": {
                "people": [],
                "softwareSystems": [],
                "containers": [],
                "components": []
            },
            "views": {
                "systemLandscapeViews": [],
                "systemContextViews": [],
                "containerViews": [],
                "componentViews": [],
                "dynamicViews": [],
                "deploymentViews": [],
                "filteredViews": []
            },
            "documentation": {
                "sections": [],
                "decisions": [],
                "images": []
            },
            "configuration": {
                "branding": {},
                "styles": {},
                "themes": {}
            }
        }
    
    def add_person(self, person: Dict[str, Any]) -> None:
        """Add a person (actor) to the model."""
        structurizr_person = {
            "id": person["id"],
            "name": person["name"],
            "description": person.get("description", ""),
            "tags": self._generate_tags(person, "Person"),
            "properties": person.get("properties", {}),
            "url": "",
            "location": "Unspecified"
        }
        self.workspace["model"]["people"].append(structurizr_person)
    
    def add_software_system(self, system: Dict[str, Any]) -> None:
        """Add a software system to the model."""
        structurizr_system = {
            "id": system["id"],
            "name": system["name"],
            "description": system.get("description", ""),
            "tags": self._generate_tags(system, "Software System"),
            "properties": system.get("properties", {}),
            "url": "",
            "location": "Unspecified"
        }
        self.workspace["model"]["softwareSystems"].append(structurizr_system)
    
    def add_container(self, container: Dict[str, Any]) -> None:
        """Add a container to the model."""
        structurizr_container = {
            "id": container["id"],
            "name": container["name"],
            "description": container.get("description", ""),
            "tags": self._generate_tags(container, "Container"),
            "properties": container.get("properties", {}),
            "url": "",
            "technology": container.get("technology", []),
            "configuration": {},
            "systemId": container.get("systemId", "")
        }
        self.workspace["model"]["containers"].append(structurizr_container)
    
    def add_component(self, component: Dict[str, Any]) -> None:
        """Add a component to the model."""
        structurizr_component = {
            "id": component["id"],
            "name": component["name"],
            "description": component.get("description", ""),
            "tags": self._generate_tags(component, "Component"),
            "properties": component.get("properties", {}),
            "url": "",
            "technology": component.get("technology", []),
            "configuration": {},
            "containerId": component.get("containerId", "")
        }
        self.workspace["model"]["components"].append(structurizr_component)
    
    def add_system_context_view(self, view: Dict[str, Any]) -> None:
        """Add a system context view."""
        structurizr_view = {
            "key": view.get("key", "system-context"),
            "description": view.get("description", ""),
            "title": view.get("name", "System Context"),
            "softwareSystemId": view.get("systemId", ""),
            "viewType": "SystemContext",
            "elements": [],
            "relationships": [],
            "animations": [],
            "paperSize": "A4",
            "automaticLayout": True,
            "elements": self._format_view_elements(
                view.get("actors", []), 
                [view.get("systemId", "")]
            )
        }
        
        # Add relationships
        if view.get("actors"):
            for actor_id in view.get("actors", []):
                structurizr_view["relationships"].append({
                    "sourceId": actor_id,
                    "destinationId": view.get("systemId", ""),
                    "description": "Uses",
                    "technology": "",
                    "tags": ["Relationship"]
                })
        
        self.workspace["views"]["systemContextViews"].append(structurizr_view)
    
    def add_container_view(self, view: Dict[str, Any]) -> None:
        """Add a container view."""
        structurizr_view = {
            "key": view.get("key", "containers"),
            "description": view.get("description", ""),
            "title": view.get("name", "Container View"),
            "softwareSystemId": view.get("systemId", ""),
            "viewType": "Container",
            "elements": self._format_view_elements(
                view.get("containers", []),
                []
            ),
            "relationships": [],
            "animations": [],
            "paperSize": "A4",
            "automaticLayout": True
        }
        
        self.workspace["views"]["containerViews"].append(structurizr_view)
    
    def add_component_view(self, view: Dict[str, Any]) -> None:
        """Add a component view."""
        structurizr_view = {
            "key": view.get("key", f"components-{view.get('containerId', '')}"),
            "description": view.get("description", ""),
            "title": view.get("name", "Component View"),
            "containerId": view.get("containerId", ""),
            "viewType": "Component",
            "elements": self._format_view_elements(
                view.get("components", []),
                []
            ),
            "relationships": [],
            "animations": [],
            "paperSize": "A4",
            "automaticLayout": True
        }
        
        self.workspace["views"]["componentViews"].append(structurizr_view)
    
    def add_llm_extensions(self, extensions: Dict[str, Any]) -> None:
        """Add LLM-friendly extensions to the workspace."""
        # Add as custom properties to the workspace
        self.workspace["properties"] = {
            "llm_extensions": extensions,
            "generated_by": "batho-c4",
            "schema_version": "c4-extensions-v1"
        }
        
        # Add documentation sections for LLM context
        for section_name, section_content in extensions.items():
            if isinstance(section_content, list) and section_content:
                self.workspace["documentation"]["sections"].append({
                    "id": f"llm-{section_name.lower().replace('_', '-')}",
                    "title": f"LLM: {section_name.replace('_', ' ').title()}",
                    "content": self._format_markdown_content(section_name, section_content),
                    "format": "Markdown",
                    "order": 1000  # LLM sections at the end
                })
    
    def _generate_tags(self, element: Dict[str, Any], element_type: str) -> List[str]:
        """Generate tags for an element."""
        tags = [element_type]
        
        # Add type-specific tags
        if element_type == "Person":
            tags.append("Actor")
        elif element_type == "Software System":
            tags.append("System")
        elif element_type == "Container":
            tags.append(element.get("type", "").replace(" ", ""))
        elif element_type == "Component":
            tags.append(element.get("type", ""))
        
        # Add technology tags
        technology = element.get("technology", [])
        if isinstance(technology, list):
            tags.extend([tech.replace(" ", "") for tech in technology])
        
        # Add property-based tags
        properties = element.get("properties", {})
        if properties.get("systemType"):
            tags.append(properties["systemType"].replace(" ", ""))
        
        return list(set(tags))  # Remove duplicates
    
    def _format_view_elements(self, element_ids: List[str], additional_ids: List[str]) -> List[Dict[str, Any]]:
        """Format elements for a view."""
        elements = []
        
        for element_id in element_ids + additional_ids:
            if element_id:
                elements.append({
                    "id": element_id,
                    "x": 0,  # Will be auto-laid out
                    "y": 0
                })
        
        return elements
    
    def _format_markdown_content(self, section_name: str, content: Any) -> str:
        """Format content as markdown for documentation."""
        if isinstance(content, list):
            lines = [f"# {section_name.replace('_', ' ').title()}\n"]
            
            for item in content[:50]:  # Limit to 50 items
                if isinstance(item, dict):
                    if "name" in item:
                        lines.append(f"## {item['name']}")
                    if "description" in item:
                        lines.append(item["description"])
                    if "location" in item:
                        lines.append(f"*Location: {item['location']}*")
                    if "type" in item:
                        lines.append(f"*Type: {item['type']}*")
                    lines.append("")
                else:
                    lines.append(f"- {item}")
            
            return "\n".join(lines)
        
        return str(content)
    
    def add_relationships(self, relationships: List[Dict[str, Any]]) -> None:
        """Add relationships to the model."""
        # Note: Structurizr relationships are typically defined within views
        # This method can be used to store relationship metadata
        self.workspace["properties"]["relationships"] = relationships
    
    def add_styling(self) -> None:
        """Add default styling for different element types."""
        styles = {
            "elements": [
                {
                    "tag": "Person",
                    "shape": "Person",
                    "icon": "assets/images/person.png",
                    "color": "#ffffff",
                    "stroke": "#9A9A9A",
                    "fontSize": 24,
                    "metadata": False,
                    "description": False
                },
                {
                    "tag": "Software System",
                    "shape": "Box",
                    "icon": "assets/images/software-system.png",
                    "color": "#438DD5",
                    "stroke": "#2E5C8A",
                    "fontSize": 24,
                    "metadata": False,
                    "description": False
                },
                {
                    "tag": "Container",
                    "shape": "Box",
                    "icon": "assets/images/container.png",
                    "color": "#85BBEF",
                    "stroke": "#4A86A8",
                    "fontSize": 20,
                    "metadata": False,
                    "description": False
                },
                {
                    "tag": "Component",
                    "shape": "Box",
                    "icon": "assets/images/component.png",
                    "color": "#B4B4B4",
                    "stroke": "#666666",
                    "fontSize": 16,
                    "metadata": False,
                    "description": False
                },
                {
                    "tag": "WebApplication",
                    "shape": "Box",
                    "color": "#08427B",
                    "stroke": "#053061",
                    "fontSize": 20
                },
                {
                    "tag": "Database",
                    "shape": "Cylinder",
                    "color": "#08427B",
                    "stroke": "#053061",
                    "fontSize": 20
                },
                {
                    "tag": "API Service",
                    "shape": "Box",
                    "color": "#999999",
                    "stroke": "#666666",
                    "fontSize": 20
                }
            ],
            "relationships": [
                {
                    "tag": "Relationship",
                    "routing": "Direct",
                    "fontSize": 12,
                    "width": 1,
                    "dashed": False,
                    "color": "#707070",
                    "position": 50
                },
                {
                    "tag": "Async",
                    "routing": "Direct",
                    "fontSize": 12,
                    "width": 2,
                    "dashed": True,
                    "color": "#707070",
                    "position": 50
                }
            ]
        }
        
        self.workspace["configuration"]["styles"] = styles
    
    def to_dict(self) -> Dict[str, Any]:
        """Return the complete Structurizr workspace as a dictionary."""
        return self.workspace
    
    def to_json(self, indent: int = 2) -> str:
        """Return the complete Structurizr workspace as JSON."""
        return json.dumps(self.workspace, indent=indent, ensure_ascii=False)
    
    def save_to_file(self, file_path: str) -> None:
        """Save the Structurizr workspace to a file."""
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(self.to_json())
    
    def validate(self) -> List[str]:
        """Validate the Structurizr workspace and return any errors."""
        errors = []
        
        # Check required fields
        if not self.workspace["name"]:
            errors.append("Workspace name is required")
        
        if not self.workspace["model"]["softwareSystems"]:
            errors.append("At least one software system is required")
        
        # Check reference integrity
        system_ids = {s["id"] for s in self.workspace["model"]["softwareSystems"]}
        container_ids = {c["id"] for c in self.workspace["model"]["containers"]}
        component_ids = {c["id"] for c in self.workspace["model"]["components"]}
        
        # Check container system references
        for container in self.workspace["model"]["containers"]:
            if container.get("systemId") not in system_ids:
                errors.append(f"Container {container['id']} references non-existent system {container.get('systemId')}")
        
        # Check component container references
        for component in self.workspace["model"]["components"]:
            if component.get("containerId") not in container_ids:
                errors.append(f"Component {component['id']} references non-existent container {component.get('containerId')}")
        
        # Check view references
        for view in self.workspace["views"]["systemContextViews"]:
            if view.get("softwareSystemId") not in system_ids:
                errors.append(f"System context view references non-existent system {view.get('softwareSystemId')}")
        
        for view in self.workspace["views"]["containerViews"]:
            if view.get("softwareSystemId") not in system_ids:
                errors.append(f"Container view references non-existent system {view.get('softwareSystemId')}")
        
        for view in self.workspace["views"]["componentViews"]:
            if view.get("containerId") not in container_ids:
                errors.append(f"Component view references non-existent container {view.get('containerId')}")
        
        return errors
