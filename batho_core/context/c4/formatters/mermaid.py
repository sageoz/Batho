"""
Mermaid formatter for C4 models.
"""

from typing import Any, Dict, List, Optional
import re

from batho_core.utils.logging import get_logger
from .base import BaseFormatter, FormatCapabilities, ViewType, FormatConfig

logger = get_logger(__name__, component="mermaid_formatter")


class MermaidFormatter(BaseFormatter):
    """Formats C4 models as Mermaid diagrams."""

    # Class attributes for plugin registration
    FORMATTER_NAME = "mermaid"
    FORMATTER_DESCRIPTION = "Mermaid diagram format for Markdown"
    FILE_EXTENSION = "mmd"
    MIME_TYPE = "text/plain"

    def __init__(self, config: Optional[FormatConfig] = None):
        super().__init__(config)
        self.theme = self.get_theme()
        self.collapsible = self.config.custom_options.get("collapsible", True)

    def get_capabilities(self) -> FormatCapabilities:
        """Get Mermaid formatter capabilities."""
        return FormatCapabilities(
            supported_views={ViewType.CONTEXT, ViewType.CONTAINER, ViewType.COMPONENT},
            supports_splitting=False,
            supports_themes=True,
            supports_interactivity=True,
            supports_export=False,
            max_recommended_size=200,
        )

    def format_model(self, c4_model: Dict[str, Any]) -> str:
        """Format C4 model as Mermaid."""
        # Start with flowchart TD for top-down layout
        lines = ["flowchart TD"]

        # Add theme configuration
        if self.theme:
            lines.extend(self._get_theme_config())

        # Add CSS classes for styling
        lines.extend(self._get_css_classes())

        # Add people
        people = c4_model.get("model", {}).get("people", [])
        if people:
            for person in people:
                lines.append(self._format_person(person))
        else:
            # Add default user node
            lines.append('user["User"]:::person')

        # Add systems
        systems = c4_model.get("model", {}).get("softwareSystems", [])
        for system in systems:
            lines.append(self._format_system(system))

        # Add containers
        containers = c4_model.get("model", {}).get("containers", [])
        if containers:
            lines.append("\nsubgraph Containers")
            for container in containers:
                lines.append(f"  {self._format_container(container)}")
            lines.append("end")

        # Add components (with subgraphs for containers)
        components = c4_model.get("model", {}).get("components", [])
        if components:
            lines.append("\nsubgraph Components")

            # Group components by container
            container_groups = {}
            for component in components:
                container_id = component.get("containerId", "default")
                if container_id not in container_groups:
                    container_groups[container_id] = []
                container_groups[container_id].append(component)

            # Create subgraphs for each container
            for container_id, comps in container_groups.items():
                if self.collapsible and len(comps) > 5:
                    lines.append(f"  subgraph {container_id}[{container_id}]")
                    for component in comps:
                        lines.append(f"    {self._format_component(component)}")
                    lines.append("  end")
                else:
                    for component in comps:
                        lines.append(f"  {self._format_component(component)}")

            lines.append("end")

        # Add relationships
        lines.append("\n%% Relationships")
        views = c4_model.get("views", {})

        # Collect all relationships from all views
        all_relationships = []

        # Context view relationships
        context_views = views.get("systemContext", [])
        if context_views:
            context_view = context_views[0] if context_views else {}
            actors = context_view.get("actors", [])
            system_id = context_view.get("systemId", "system")
            for actor in actors:
                all_relationships.append(
                    {
                        "source": actor,
                        "target": system_id,
                        "description": "Uses",
                        "technology": "",
                    }
                )

        # Container view relationships
        container_views = views.get("containerViews", [])
        if container_views:
            container_view = container_views[0] if container_views else {}
            elements = container_view.get("elements", [])
            for element in elements:
                container_id = element.get("id", "")
                if container_id:
                    all_relationships.append(
                        {
                            "source": "user",
                            "target": container_id,
                            "description": "Uses",
                            "technology": "",
                        }
                    )
        else:
            # Fallback: generate relationships for all containers if no views exist
            containers = c4_model.get("model", {}).get("containers", [])
            for container in containers:
                container_id = container.get("id", "")
                if container_id:
                    all_relationships.append(
                        {
                            "source": "user",
                            "target": container_id,
                            "description": "Uses",
                            "technology": "",
                        }
                    )

        # Component view relationships
        component_views = views.get("componentViews", [])
        if component_views:
            for comp_view in component_views:
                elements = comp_view.get("elements", [])
                for element in elements:
                    comp_id = element.get("id", "")
                    if comp_id:
                        all_relationships.append(
                            {
                                "source": "user",
                                "target": comp_id,
                                "description": "Interacts with",
                                "technology": "",
                            }
                        )

        # Format relationships
        for rel in all_relationships:
            lines.append(self._format_relationship(rel))

        # Add legend
        lines.extend(self._get_legend())

        return "\n".join(lines)

    def _get_theme_config(self) -> List[str]:
        """Get Mermaid theme configuration."""
        lines = []

        if self.theme == "dark":
            lines.extend(
                [
                    "%%{init: {'theme': 'dark', 'themeVariables': {",
                    "  'primaryColor': '#404040',",
                    "  'primaryTextColor': '#fff',",
                    "  'primaryBorderColor': '#fff',",
                    "  'lineColor': '#666',",
                    "  'sectionBkgColor': '#404040',",
                    "  'altSectionBkgColor': '#333',",
                    "  'gridColor': '#666'",
                    "}}}%%",
                ]
            )
        elif self.theme == "github":
            lines.extend(
                [
                    "%%{init: {'theme': 'base', 'themeVariables': {",
                    "  'primaryColor': '#f6f8fa',",
                    "  'primaryTextColor': '#24292f',",
                    "  'primaryBorderColor': '#d0d7de',",
                    "  'lineColor': '#656d76',",
                    "  'sectionBkgColor': '#f6f8fa',",
                    "  'altSectionBkgColor': '#ffffff',",
                    "  'gridColor': '#e1e4e8'",
                    "}}}%%",
                ]
            )

        return lines

    def _get_css_classes(self) -> List[str]:
        """Get CSS class definitions."""
        return [
            "classDef person fill:#E1F5FE,stroke:#01579B,stroke-width:2px",
            "classDef system fill:#F3E5F5,stroke:#4A148C,stroke-width:2px",
            "classDef container fill:#E8F5E9,stroke:#1B5E20,stroke-width:2px",
            "classDef component fill:#FFF3E0,stroke:#E65100,stroke-width:2px",
            "classDef external fill:#FFEBEE,stroke:#B71C1C,stroke-width:2px",
        ]

    def _format_person(self, person: Dict[str, Any]) -> str:
        """Format a person entity."""
        name = self._sanitize_label(person.get("name", "Unknown"))
        person_id = person.get("id", "person")
        return f'{person_id}["{name}"]:::person'

    def _format_system(self, system: Dict[str, Any]) -> str:
        """Format a software system."""
        name = self._sanitize_label(system.get("name", "Unknown"))
        system_id = system.get("id", "system")
        return f'{system_id}["{name}"]:::system'

    def _format_container(self, container: Dict[str, Any]) -> str:
        """Format a container."""
        name = self._sanitize_label(container.get("name", "Unknown"))
        container_id = container.get("id", "container")
        technology = container.get("technology", [])

        label = name
        if technology:
            label += f"<br/><small>[{', '.join(technology)}]</small>"

        return f'{container_id}["{label}"]:::container'

    def _format_component(self, component: Dict[str, Any]) -> str:
        """Format a component."""
        name = self._sanitize_label(component.get("name", "Unknown"))
        component_id = component.get("id", "component")
        component_type = component.get("type", "")

        label = name
        if component_type and component_type != name:
            label += f"<br/><small>&lt;&lt;{component_type}&gt;&gt;</small>"

        return f'{component_id}["{label}"]:::component'

    def _format_relationship(self, relationship: Dict[str, Any]) -> str:
        """Format a relationship."""
        source = relationship.get("source", "")
        target = relationship.get("target", "")
        description = relationship.get("description", "")
        technology = relationship.get("technology", "")

        # Don't sanitize IDs - keep them consistent with node definitions
        # source = source.replace("-", "_").replace(".", "_")
        # target = target.replace("-", "_").replace(".", "_")

        # Format description
        label = description
        if technology:
            label += f"<br/><small>[{technology}]</small>"

        # Add link style
        link_style = ""
        if technology:
            link_style = " -.-> "
        else:
            link_style = " --> "

        return f"{source}{link_style}{target}"

    def _get_legend(self) -> List[str]:
        """Get legend for the diagram."""
        return [
            "\n%% Legend",
            "subgraph Legend",
            "  direction LR",
            "  P[Person]:::person",
            "  S[System]:::system",
            "  C[Container]:::container",
            "  CO[Component]:::component",
            "end",
        ]

    def _sanitize_label(self, label: str) -> str:
        """Sanitize label for Mermaid."""
        # Escape special characters
        label = label.replace('"', '\\"')

        # Truncate very long labels
        if len(label) > 50:
            label = label[:47] + "..."

        return label

    def format_for_readme(self, c4_model: Dict[str, Any]) -> str:
        """Format specifically for README embedding."""
        mermaid_code = self.format_model(c4_model)

        # Wrap in README-friendly format
        return f"""## Architecture Overview

```mermaid
{mermaid_code}
```

*This diagram was generated using Batho C4 model generator*"""

    def format_github_actions(self, c4_model: Dict[str, Any]) -> str:
        """Format for GitHub Actions workflow."""
        mermaid_code = self.format_model(c4_model)

        # Create a GitHub Actions step that updates README
        return f"""- name: Update Architecture Diagram
  run: |
    cat > README.md << 'EOF'
    # Architecture

    ```mermaid
    {mermaid_code}
    ```

    EOF
  git add README.md
  git config --local user.email "action@github.com"
  git config --local user.name "GitHub Action"
  git commit -m "Update architecture diagram" || exit 0
  git push"""
