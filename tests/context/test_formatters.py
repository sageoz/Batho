"""Tests for multi-format output formatters."""

import json
from pathlib import Path

from batho_core.context.c4.formatters import (
    get_format_registry,
    PlantUMLFormatter,
    MermaidFormatter,
    InteractiveHTMLFormatter,
    D2Formatter
)


class TestFormatRegistry:
    """Test the format registry functionality."""
    
    def test_registry_initialization(self):
        """Test that registry initializes with built-in formatters."""
        registry = get_format_registry()
        formats = registry.list_formats()
        
        assert len(formats) >= 4
        format_names = {f.name for f in formats}
        assert "plantuml" in format_names
        assert "mermaid" in format_names
        assert "interactive" in format_names
        assert "d2" in format_names
    
    def test_get_formatter(self):
        """Test getting formatters from registry."""
        registry = get_format_registry()
        
        plantuml = registry.get_formatter("plantuml")
        assert isinstance(plantuml, PlantUMLFormatter)
        
        mermaid = registry.get_formatter("mermaid")
        assert isinstance(mermaid, MermaidFormatter)
        
        interactive = registry.get_formatter("interactive")
        assert isinstance(interactive, InteractiveHTMLFormatter)
        
        d2 = registry.get_formatter("d2")
        assert isinstance(d2, D2Formatter)
    
    def test_formatter_capabilities(self):
        """Test that formatters report correct capabilities."""
        registry = get_format_registry()
        
        for fmt in registry.list_formats():
            formatter = registry.get_formatter(fmt.name)
            caps = formatter.get_capabilities()
            
            # All formatters should support basic views
            assert len(caps.supported_views) >= 3
            assert caps.supported_views is not None


class TestPlantUMLFormatter:
    """Test PlantUML formatter."""
    
    def test_basic_formatting(self):
        """Test basic PlantUML output generation."""
        formatter = PlantUMLFormatter()
        c4_model = self._create_test_model()
        
        output = formatter.format_model(c4_model)
        
        assert "@startuml" in output
        assert "@enduml" in output
        assert "Person(user" in output
        assert "System(system" in output
        assert "Rel(user, system" in output
    
    def test_theme_support(self):
        """Test theme support."""
        formatter = PlantUMLFormatter()
        formatter.set_theme("dark")
        
        c4_model = self._create_test_model()
        output = formatter.format_model(c4_model)
        
        assert "!include C4_Dark" in output
    
    def test_splitting_logic(self):
        """Test diagram splitting for large models."""
        formatter = PlantUMLFormatter()
        formatter.config.split_threshold = 5
        
        large_model = self._create_large_model()
        should_split = formatter.should_split(large_model)
        
        assert should_split is True
    
    def _create_test_model(self):
        """Create a simple test C4 model."""
        return {
            "name": "Test System",
            "description": "Test",
            "model": {
                "people": [{"id": "user", "name": "User", "description": "A user"}],
                "softwareSystems": [{"id": "system", "name": "System", "description": "The system"}],
                "containers": [],
                "components": []
            },
            "views": {
                "systemContext": [{
                    "actors": ["user"],
                    "systemId": "system"
                }]
            }
        }
    
    def _create_large_model(self):
        """Create a large model for testing splitting."""
        model = self._create_test_model()
        model["model"]["components"] = [
            {"id": f"comp_{i}", "name": f"Component {i}", "containerId": "container"}
            for i in range(10)
        ]
        return model


class TestMermaidFormatter:
    """Test Mermaid formatter."""
    
    def test_basic_formatting(self):
        """Test basic Mermaid output generation."""
        formatter = MermaidFormatter()
        c4_model = self._create_test_model()
        
        output = formatter.format_model(c4_model)
        
        assert "flowchart TD" in output
        assert "user[" in output
        assert "system[" in output
        assert "user --> system" in output
    
    def test_readme_formatting(self):
        """Test README-specific formatting."""
        formatter = MermaidFormatter()
        c4_model = self._create_test_model()
        
        output = formatter.format_for_readme(c4_model)
        
        assert "## Architecture Overview" in output
        assert "```mermaid" in output
    
    def _create_test_model(self):
        """Create a simple test C4 model."""
        return {
            "name": "Test System",
            "description": "Test",
            "model": {
                "people": [{"id": "user", "name": "User", "description": "A user"}],
                "softwareSystems": [{"id": "system", "name": "System", "description": "The system"}],
                "containers": [],
                "components": []
            },
            "views": {
                "systemContext": [{
                    "actors": ["user"],
                    "systemId": "system"
                }]
            }
        }


class TestInteractiveHTMLFormatter:
    """Test Interactive HTML formatter."""
    
    def test_basic_formatting(self):
        """Test basic HTML output generation."""
        formatter = InteractiveHTMLFormatter()
        c4_model = self._create_test_model()
        
        output = formatter.format_model(c4_model)
        
        assert "<!DOCTYPE html>" in output
        assert "const graphData =" in output
        assert "const config =" in output
        assert "d3.v7.min.js" in output
    
    def test_d3_conversion(self):
        """Test conversion to D3.js format."""
        formatter = InteractiveHTMLFormatter()
        c4_model = self._create_test_model()
        
        graph_data = formatter._convert_to_d3_format(c4_model)
        
        assert "nodes" in graph_data
        assert "links" in graph_data
        assert len(graph_data["nodes"]) > 0
        assert len(graph_data["links"]) > 0
    
    def _create_test_model(self):
        """Create a simple test C4 model."""
        return {
            "name": "Test System",
            "description": "Test",
            "model": {
                "people": [{"id": "user", "name": "User", "description": "A user"}],
                "softwareSystems": [{"id": "system", "name": "System", "description": "The system"}],
                "containers": [],
                "components": []
            },
            "views": {
                "systemContext": [{
                    "actors": ["user"],
                    "systemId": "system"
                }]
            }
        }


class TestD2Formatter:
    """Test D2 formatter."""
    
    def test_basic_formatting(self):
        """Test basic D2 output generation."""
        formatter = D2Formatter()
        c4_model = self._create_test_model()
        
        output = formatter.format_model(c4_model)
        
        assert "# C4 Architecture Diagram" in output
        assert "person: {" in output
        assert "system: {" in output
        assert "direction:" in output
    
    def test_tala_layout(self):
        """Test Tala layout optimization."""
        formatter = D2Formatter()
        c4_model = self._create_test_model()
        
        output = formatter.format_with_tala(c4_model)
        
        assert "Optimized with Tala" in output
    
    def _create_test_model(self):
        """Create a simple test C4 model."""
        return {
            "name": "Test System",
            "description": "Test",
            "model": {
                "people": [{"id": "user", "name": "User", "description": "A user"}],
                "softwareSystems": [{"id": "system", "name": "System", "description": "The system"}],
                "containers": [],
                "components": []
            },
            "views": {
                "systemContext": [{
                    "actors": ["user"],
                    "systemId": "system"
                }]
            }
        }
