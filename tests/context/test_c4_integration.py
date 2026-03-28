"""
Integration tests for C4 generation with the new rule system.
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from batho_core.context.c4_generator import C4Generator


@pytest.fixture
def sample_ctn_data():
    """Create sample .ctn data for testing."""
    return {
        "graph": {
            "entities": [
                {
                    "id": "e1",
                    "name": "UserController",
                    "type": "class",
                    "file": "src/controllers/user_controller.py",
                    "start_line": 1,
                    "end_line": 50,
                    "signature": "class UserController:"
                },
                {
                    "id": "e2",
                    "name": "UserService",
                    "type": "class",
                    "file": "src/services/user_service.py",
                    "start_line": 1,
                    "end_line": 100,
                    "signature": "class UserService:"
                },
                {
                    "id": "e3",
                    "name": "UserModel",
                    "type": "class",
                    "file": "src/models/user_model.py",
                    "start_line": 1,
                    "end_line": 30,
                    "signature": "class UserModel:"
                },
                {
                    "id": "e4",
                    "name": "index",
                    "type": "function",
                    "file": "src/app.py",
                    "start_line": 10,
                    "end_line": 20,
                    "signature": "def index():"
                }
            ],
            "relationships": [
                {
                    "type": "IMPORTS",
                    "source": "e1",
                    "target": "flask"
                },
                {
                    "type": "IMPORTS",
                    "source": "e2",
                    "target": "sqlalchemy"
                },
                {
                    "type": "IMPORTS",
                    "source": "e3",
                    "target": "django.db"
                },
                {
                    "type": "IMPORTS",
                    "source": "e4",
                    "target": "requests"
                },
                {
                    "type": "CALLS",
                    "source": "e1",
                    "target": "e2"
                }
            ]
        },
        "repomap": {
            "files": {
                "src/controllers/user_controller.py": {"size": 100},
                "src/services/user_service.py": {"size": 200},
                "src/models/user_model.py": {"size": 150},
                "src/app.py": {"size": 300},
                "tests/test_user.py": {"size": 100},
                "README.md": {"size": 500},
                "requirements.txt": {"size": 50}
            }
        },
        "index": {
            "indexes": {
                "test123": {
                    "timestamp": "2024-01-01T00:00:00Z",
                    "entity_count": 4,
                    "relationship_count": 5,
                    "root": "src",
                    "stack": {
                        "languages": ["Python"],
                        "frameworks": ["Flask", "SQLAlchemy"],
                        "build_tools": ["pip"]
                    }
                }
            }
        }
    }


@pytest.fixture
def temp_ctn_dir(sample_ctn_data):
    """Create a temporary .ctn directory with sample data."""
    with tempfile.TemporaryDirectory() as tmpdir:
        ctn_dir = Path(tmpdir)
        versioned_dir = ctn_dir / "test123"
        versioned_dir.mkdir(parents=True)
        
        # Write files
        (versioned_dir / "graph.json").write_text(
            json.dumps(sample_ctn_data["graph"])
        )
        (versioned_dir / "repomap.json").write_text(
            json.dumps(sample_ctn_data["repomap"])
        )
        (ctn_dir / "index.json").write_text(
            json.dumps(sample_ctn_data["index"])
        )
        
        yield ctn_dir


@pytest.fixture
def temp_rules_dir():
    """Create a temporary rules directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        rules_dir = Path(tmpdir)
        
        # Create directory structure
        (rules_dir / "base").mkdir()
        (rules_dir / "languages").mkdir()
        (rules_dir / "dynamic").mkdir()
        
        # Create Python-specific rules
        python_rules = {
            "language": "python",
            "external_systems": [
                {
                    "name": "Python Database",
                    "description": "Python database detection",
                    "priority": 110,
                    "patterns": ["sqlalchemy", "django.db"],
                    "system_type": "Database",
                    "actor_name": "Database",
                    "actor_description": "Data storage system"
                },
                {
                    "name": "Python Web Framework",
                    "description": "Python web framework detection",
                    "priority": 105,
                    "patterns": ["flask", "django", "fastapi"],
                    "system_type": "WebServer",
                    "actor_name": "Web Server",
                    "actor_description": "Web application server"
                },
                {
                    "name": "Python HTTP Client",
                    "description": "Python HTTP client detection",
                    "priority": 95,
                    "patterns": ["requests", "httpx"],
                    "system_type": "ExternalAPI",
                    "actor_name": "External API",
                    "actor_description": "Third-party API service"
                }
            ],
            "containers": [
                {
                    "name": "Python Web App",
                    "description": "Python web application",
                    "priority": 110,
                    "framework_patterns": ["Flask", "Django", "FastAPI"],
                    "directory_patterns": ["src", "app", "web"],
                    "file_patterns": ["app.py", "main.py"],
                    "container_type": "Web Application",
                    "container_name": "Web App",
                    "technology": ["Python", "HTTP"]
                },
                {
                    "name": "Python Test Suite",
                    "description": "Python test suite",
                    "priority": 90,
                    "framework_patterns": ["pytest", "unittest"],
                    "directory_patterns": ["test", "tests"],
                    "container_type": "Test Suite",
                    "container_name": "Test Suite",
                    "technology": ["Python", "Testing"]
                }
            ],
            "components": [
                {
                    "name": "Python Controller",
                    "description": "Python controller components",
                    "entity_types": ["class"],
                    "importance_threshold": 0.3,
                    "max_per_file": 5,
                    "component_type": "Controller",
                    "name_patterns": ["*Controller"]
                },
                {
                    "name": "Python Service",
                    "description": "Python service components",
                    "entity_types": ["class"],
                    "importance_threshold": 0.3,
                    "max_per_file": 5,
                    "component_type": "Service",
                    "name_patterns": ["*Service"]
                },
                {
                    "name": "Python Model",
                    "description": "Python model components",
                    "entity_types": ["class"],
                    "importance_threshold": 0.2,
                    "max_per_file": 10,
                    "component_type": "Model",
                    "name_patterns": ["*Model"]
                }
            ]
        }
        
        (rules_dir / "languages" / "python.yaml").write_text(
            yaml.dump(python_rules)
        )
        
        # Create base rules (minimal)
        base_rules = {
            "external_systems": [],
            "containers": [],
            "components": []
        }
        
        for rule_type in ["external_systems", "containers", "components"]:
            (rules_dir / "base" / f"{rule_type}.yaml").write_text(
                yaml.dump({rule_type: base_rules[rule_type]})
            )
        
        yield rules_dir


class TestC4Integration:
    """Integration tests for C4 generation with new rule system."""
    
    def test_generate_c4_model_with_rules(self, temp_ctn_dir, temp_rules_dir):
        """Test complete C4 model generation with new rule system."""
        # Create generator with custom rules
        generator = C4Generator(temp_ctn_dir, "test123", rules_dir=temp_rules_dir)
        
        # Generate C4 model
        model = generator.generate_c4_model()
        
        # Verify model structure
        assert "model" in model
        assert "views" in model
        assert "documentation" in model
        assert "llm_extensions" in model
        assert "generation_metadata" in model
        
        # Verify generation metadata
        metadata = model["generation_metadata"]
        assert metadata["language"] == "python"
        assert metadata["rules_version"] == "1.0"
        assert metadata["dynamic_rules_enabled"] is True
        
        # Verify software systems
        systems = model["model"]["softwareSystems"]
        assert len(systems) > 0
        assert systems[0]["properties"]["language"] == "python"
        
        # Verify containers
        containers = model["model"]["containers"]
        assert len(containers) > 0
        
        # Should detect web application container
        web_containers = [c for c in containers if c["type"] == "Web Application"]
        assert len(web_containers) > 0
        assert web_containers[0]["properties"]["language"] == "python"
        
        # Should detect test suite container
        test_containers = [c for c in containers if c["type"] == "Test Suite"]
        assert len(test_containers) > 0
        
        # Verify components
        components = model["model"]["components"]
        assert len(components) > 0
        
        # Should detect controller component
        controller_components = [c for c in components if c["type"] == "Controller"]
        assert len(controller_components) > 0
        assert controller_components[0]["name"] == "UserController"
        
        # Should detect service component
        service_components = [c for c in components if c["type"] == "Service"]
        assert len(service_components) > 0
        assert service_components[0]["name"] == "UserService"
        
        # Should detect model component
        model_components = [c for c in components if c["type"] == "Model"]
        assert len(model_components) > 0
        assert model_components[0]["name"] == "UserModel"
    
    def test_language_detection(self, temp_ctn_dir, temp_rules_dir):
        """Test language detection functionality."""
        generator = C4Generator(temp_ctn_dir, "test123", rules_dir=temp_rules_dir)
        
        # Should detect Python
        assert generator.primary_language == "python"
    
    def test_external_system_detection(self, temp_ctn_dir, temp_rules_dir):
        """Test external system detection with rules."""
        generator = C4Generator(temp_ctn_dir, "test123", rules_dir=temp_rules_dir)
        
        # Analyze imports
        analysis = generator._analyze_imports()
        
        # Should detect database
        assert "Database" in analysis["external_actors"]
        
        # Should detect web server
        assert "WebServer" in analysis["external_actors"]
        
        # Should detect external API
        assert "ExternalAPI" in analysis["external_actors"]
        
        # Verify actor properties
        db_actor = analysis["external_actors"]["Database"]
        assert db_actor["name"] == "Database"
        assert db_actor["type"] == "Database"
    
    def test_container_detection_with_rules(self, temp_ctn_dir, temp_rules_dir):
        """Test container detection with rule engine."""
        generator = C4Generator(temp_ctn_dir, "test123", rules_dir=temp_rules_dir)
        
        containers = generator._generate_containers()
        
        # Should detect web application
        web_apps = [c for c in containers if c["type"] == "Web Application"]
        assert len(web_apps) > 0
        assert web_apps[0]["properties"]["rule"] == "Python Web App"
        
        # Should detect test suite
        test_suites = [c for c in containers if c["type"] == "Test Suite"]
        assert len(test_suites) > 0
        assert test_suites[0]["properties"]["rule"] == "Python Test Suite"
    
    def test_component_detection_with_rules(self, temp_ctn_dir, temp_rules_dir):
        """Test component detection with rule engine."""
        generator = C4Generator(temp_ctn_dir, "test123", rules_dir=temp_rules_dir)
        
        components = generator._generate_components()
        
        # Check each component has rule information
        for component in components:
            assert "rule" in component["properties"]
            assert "confidence" in component["properties"]
            assert "language" in component["properties"]
    
    def test_dynamic_rule_generation(self, temp_ctn_dir, temp_rules_dir):
        """Test dynamic rule generation."""
        generator = C4Generator(temp_ctn_dir, "test123", rules_dir=temp_rules_dir)
        
        # Check dynamic generator exists
        assert generator.rule_engine.dynamic_generator is not None
        
        # Dynamic rules should have been generated during initialization
        dynamic_rules = generator.rule_engine.dynamic_generator.get_dynamic_rules()
        assert isinstance(dynamic_rules, dict)
    
    def test_language_override(self, temp_ctn_dir, temp_rules_dir):
        """Test language override functionality."""
        generator = C4Generator(temp_ctn_dir, "test123", rules_dir=temp_rules_dir)
        
        # Override language
        generator.primary_language = "java"
        
        # Should use overridden language
        assert generator.primary_language == "java"
    
    def test_without_custom_rules(self, temp_ctn_dir):
        """Test C4 generation without custom rules (uses built-in)."""
        # Create generator without custom rules
        generator = C4Generator(temp_ctn_dir, "test123", rules_dir=None)
        
        # Should still generate a model
        model = generator.generate_c4_model()
        assert "model" in model
        assert "generation_metadata" in model
