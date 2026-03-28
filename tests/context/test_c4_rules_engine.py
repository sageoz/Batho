"""
Tests for the C4 rule engine with YAML-based rules.
"""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from batho_core.context.c4_rules import C4RuleEngine


@pytest.fixture
def temp_rules_dir():
    """Create a temporary rules directory with test rules."""
    with tempfile.TemporaryDirectory() as tmpdir:
        rules_dir = Path(tmpdir)
        
        # Create directory structure
        (rules_dir / "base").mkdir()
        (rules_dir / "languages").mkdir()
        (rules_dir / "dynamic").mkdir()
        
        # Create minimal test rules
        external_systems = {
            "external_systems": [
                {
                    "name": "Database Rule",
                    "description": "Database detection",
                    "priority": 100,
                    "patterns": ["sqlalchemy", "django.db"],
                    "system_type": "Database",
                    "actor_name": "Database",
                    "actor_description": "Data storage"
                },
                {
                    "name": "API Rule",
                    "description": "API detection",
                    "priority": 90,
                    "patterns": ["requests", "httpx"],
                    "system_type": "ExternalAPI",
                    "actor_name": "External API",
                    "actor_description": "Third-party API"
                }
            ]
        }
        (rules_dir / "base" / "external_systems.yaml").write_text(
            f"external_systems: {external_systems['external_systems']}"
        )
        
        containers = {
            "containers": [
                {
                    "name": "Web App Rule",
                    "description": "Web app detection",
                    "priority": 100,
                    "framework_patterns": ["Flask", "Django"],
                    "directory_patterns": ["web", "app"],
                    "container_type": "Web Application",
                    "container_name": "Web App",
                    "technology": ["Python", "HTTP"]
                }
            ]
        }
        (rules_dir / "base" / "containers.yaml").write_text(
            f"containers: {containers['containers']}"
        )
        
        components = {
            "components": [
                {
                    "name": "Controller Rule",
                    "description": "Controller detection",
                    "entity_types": ["class"],
                    "importance_threshold": 0.5,
                    "max_per_file": 3,
                    "component_type": "Controller",
                    "name_patterns": ["*Controller"]
                }
            ]
        }
        (rules_dir / "base" / "components.yaml").write_text(
            f"components: {components['components']}"
        )
        
        yield rules_dir


@pytest.fixture
def rule_engine(temp_rules_dir):
    """Create a C4RuleEngine instance."""
    return C4RuleEngine(rules_dir=temp_rules_dir, enable_dynamic=False)


class TestC4RuleEngine:
    """Test cases for C4RuleEngine."""
    
    def test_initialization(self, temp_rules_dir):
        """Test rule engine initialization."""
        engine = C4RuleEngine(rules_dir=temp_rules_dir, enable_dynamic=False)
        assert engine.rule_loader is not None
        assert engine.dynamic_generator is None
    
    def test_initialization_with_dynamic(self, temp_rules_dir):
        """Test rule engine initialization with dynamic rules."""
        engine = C4RuleEngine(rules_dir=temp_rules_dir, enable_dynamic=True)
        assert engine.rule_loader is not None
        assert engine.dynamic_generator is not None
    
    def test_detect_language(self, rule_engine):
        """Test language detection."""
        # Create mock graph and repomap
        graph = {"relationships": []}
        repomap = {
            "files": {
                "app.py": {"size": 100},
                "models.py": {"size": 200},
                "utils.py": {"size": 150},
                "main.js": {"size": 100},
                "config.yaml": {"size": 50}
            }
        }
        
        language = rule_engine.detect_language(graph, repomap)
        assert language == "python"
    
    def test_detect_language_java(self, rule_engine):
        """Test language detection for Java."""
        graph = {"relationships": []}
        repomap = {
            "files": {
                "Main.java": {"size": 100},
                "Controller.java": {"size": 200},
                "Service.java": {"size": 150}
            }
        }
        
        language = rule_engine.detect_language(graph, repomap)
        assert language == "java"
    
    def test_detect_language_unknown(self, rule_engine):
        """Test language detection with unknown files."""
        graph = {"relationships": []}
        repomap = {
            "files": {
                "README": {"size": 100},
                "config": {"size": 50},
                "Makefile": {"size": 100}
            }
        }
        
        language = rule_engine.detect_language(graph, repomap)
        assert language is None
    
    def test_apply_external_system_rules(self, rule_engine):
        """Test applying external system rules."""
        imports = [
            "sqlalchemy",
            "django.db",
            "requests",
            "httpx",
            "some_other_lib"
        ]
        
        detected = rule_engine.apply_external_system_rules(imports)
        
        assert "Database" in detected
        assert "ExternalAPI" in detected
        assert detected["Database"]["actor_name"] == "Database"
        assert len(detected["Database"]["matches"]) == 2
        assert len(detected["ExternalAPI"]["matches"]) == 2
    
    def test_apply_external_system_rules_with_language(self, rule_engine):
        """Test applying external system rules with language filter."""
        imports = ["sqlalchemy", "django.db", "requests"]
        
        # Test without language
        detected = rule_engine.apply_external_system_rules(imports)
        assert "Database" in detected
        
        # Test with language (should get same result for this test)
        detected = rule_engine.apply_external_system_rules(imports, language="python")
        assert "Database" in detected
    
    def test_apply_container_rules(self, rule_engine):
        """Test applying container rules."""
        frameworks = ["Flask", "Django", "FastAPI"]
        directories = ["web", "app", "models", "api"]
        
        containers = rule_engine.apply_container_rules(frameworks, directories)
        
        assert len(containers) == 1
        assert containers[0]["type"] == "Web Application"
        assert containers[0]["name"] == "Web App"
        assert containers[0]["framework_match"] is True
        assert containers[0]["directory_match"] is True
        assert "Flask" in containers[0]["matched_frameworks"]
        assert "Django" in containers[0]["matched_frameworks"]
    
    def test_apply_container_rules_no_match(self, rule_engine):
        """Test applying container rules with no matches."""
        frameworks = ["UnknownFramework"]
        directories = ["unknown", "misc"]
        
        containers = rule_engine.apply_container_rules(frameworks, directories)
        
        assert len(containers) == 0
    
    def test_apply_component_rules(self, rule_engine):
        """Test applying component rules."""
        entities = [
            {
                "id": "entity1",
                "name": "UserController",
                "type": "class",
                "file": "web/controllers.py",
                "start_line": 1,
                "end_line": 50
            },
            {
                "id": "entity2",
                "name": "UserService",
                "type": "class",
                "file": "services/user_service.py",
                "start_line": 1,
                "end_line": 100
            },
            {
                "id": "entity3",
                "name": "low_importance",
                "type": "function",
                "file": "utils.py",
                "start_line": 1,
                "end_line": 10
            }
        ]
        
        importance_scores = {
            "entity1": 0.8,
            "entity2": 0.6,
            "entity3": 0.2
        }
        
        components = rule_engine.apply_component_rules(entities, importance_scores)
        
        # Should detect UserController as a Controller (high importance)
        controller_components = [c for c in components if c["type"] == "Controller"]
        assert len(controller_components) == 1
        assert controller_components[0]["entity"]["name"] == "UserController"
    
    def test_apply_component_rules_with_name_patterns(self, rule_engine):
        """Test applying component rules with name pattern matching."""
        # Add a rule with name patterns
        rule_engine.rule_loader.load_all_rules()
        existing_rules = rule_engine.rule_loader._loaded_rules
        if "base" not in existing_rules:
            existing_rules["base"] = {"components": [], "containers": [], "external_systems": []}
        if "components" not in existing_rules["base"]:
            existing_rules["base"]["components"] = []
        
        # Clear existing component rules and add only Service rule
        existing_rules["base"]["components"] = [{
            "name": "Service Rule",
            "entity_types": ["class"],
            "importance_threshold": 0.3,
            "max_per_file": 5,
            "component_type": "Service",
            "name_patterns": ["*Service"]
        }]
        
        entities = [
            {
                "id": "entity1",
                "name": "UserService",
                "type": "class",
                "file": "services/user_service.py",
                "start_line": 1,
                "end_line": 100
            },
            {
                "id": "entity2",
                "name": "NotAComponent",
                "type": "class",
                "file": "misc.py",
                "start_line": 1,
                "end_line": 50
            }
        ]
        
        importance_scores = {
            "entity1": 0.6,
            "entity2": 0.6
        }
        
        components = rule_engine.apply_component_rules(entities, importance_scores)
        
        service_components = [c for c in components if c["type"] == "Service"]
        assert len(service_components) == 1
        assert service_components[0]["entity"]["name"] == "UserService"
    
    def test_match_pattern(self, rule_engine):
        """Test pattern matching functionality."""
        # Test exact match
        assert rule_engine._match_pattern("UserService", "Service") is True
        
        # Test wildcard match
        assert rule_engine._match_pattern("UserController", "*Controller") is True
        assert rule_engine._match_pattern("UserRepository", "*Repository") is True
        
        # Test case insensitive
        assert rule_engine._match_pattern("userservice", "Service") is True
        
        # Test no match
        assert rule_engine._match_pattern("UserController", "*Service") is False
    
    def test_generate_dynamic_rules(self, rule_engine):
        """Test dynamic rule generation."""
        # Mock dynamic generator
        mock_generator = MagicMock()
        rule_engine.dynamic_generator = mock_generator
        
        graph = {"entities": [], "relationships": []}
        repomap = {"files": {}}
        
        rule_engine.generate_dynamic_rules(graph, repomap)
        
        # Should call analyze_repository on dynamic generator
        mock_generator.analyze_repository.assert_called_once()
        
        # Check arguments
        call_args = mock_generator.analyze_repository.call_args
        assert call_args[0][0] == graph
        assert call_args[0][1] == repomap
    
    def test_generate_dynamic_rules_disabled(self, rule_engine):
        """Test dynamic rule generation when disabled."""
        rule_engine.dynamic_generator = None
        
        graph = {"entities": [], "relationships": []}
        repomap = {"files": {}}
        
        # Should not raise any errors
        rule_engine.generate_dynamic_rules(graph, repomap)
