"""
Tests for the dynamic rule generator.
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from batho_core.context.c4.rules.dynamic.rule_generator import DynamicRuleGenerator


@pytest.fixture
def temp_dynamic_dir():
    """Create a temporary directory for dynamic rules."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def dynamic_generator(temp_dynamic_dir):
    """Create a DynamicRuleGenerator instance."""
    return DynamicRuleGenerator(temp_dynamic_dir)


class TestDynamicRuleGenerator:
    """Test cases for DynamicRuleGenerator."""
    
    def test_initialization(self, temp_dynamic_dir):
        """Test generator initialization."""
        generator = DynamicRuleGenerator(temp_dynamic_dir)
        
        assert generator.dynamic_dir == temp_dynamic_dir
        assert generator.patterns_file == temp_dynamic_dir / "detected_patterns.json"
        assert generator.min_occurrences == 3
        assert generator.confidence_threshold == 0.6
    
    def test_analyze_repository(self, dynamic_generator):
        """Test repository analysis."""
        # Create test graph and repomap
        graph = {
            "relationships": [
                {"type": "IMPORTS", "target": "sqlalchemy"},
                {"type": "IMPORTS", "target": "sqlalchemy"},
                {"type": "IMPORTS", "target": "sqlalchemy"},
                {"type": "IMPORTS", "target": "requests"},
                {"type": "IMPORTS", "target": "requests"},
                {"type": "IMPORTS", "target": "requests"},
                {"type": "IMPORTS", "target": "django.db"}
            ],
            "entities": [
                {
                    "id": "e1",
                    "name": "UserController",
                    "type": "class",
                    "file": "controllers/user_controller.py"
                },
                {
                    "id": "e2",
                    "name": "UserService",
                    "type": "class",
                    "file": "services/user_service.py"
                }
            ]
        }
        
        repomap = {
            "files": {
                "controllers/user_controller.py": {"size": 100},
                "services/user_service.py": {"size": 200},
                "models/user_model.py": {"size": 150},
                "web/app.py": {"size": 300}
            }
        }
        
        # Analyze repository
        rules = dynamic_generator.analyze_repository(graph, repomap, "python")
        
        assert "external_systems" in rules
        assert "containers" in rules
        assert "components" in rules
        assert rules["language"] == "python"
        
        # Should detect database from sqlalchemy patterns
        db_rules = [r for r in rules["external_systems"] if r["system_type"] == "Database"]
        assert len(db_rules) > 0
        
        # Should detect API from requests patterns
        api_rules = [r for r in rules["external_systems"] if r["system_type"] == "ExternalAPI"]
        assert len(api_rules) > 0
    
    def test_analyze_import_patterns(self, dynamic_generator):
        """Test import pattern analysis."""
        graph = {
            "relationships": [
                {"type": "IMPORTS", "target": "sqlalchemy"},
                {"type": "IMPORTS", "target": "sqlalchemy"},
                {"type": "IMPORTS", "target": "sqlalchemy"},
                {"type": "IMPORTS", "target": "requests"},
                {"type": "IMPORTS", "target": "requests"},
                {"type": "IMPORTS", "target": "requests"},
                {"type": "IMPORTS", "target": "custom_lib"}
            ]
        }
        
        result = dynamic_generator._analyze_import_patterns(graph, "python")
        
        assert "external_systems" in result
        
        # Should detect database (sqlalchemy appears 3 times)
        db_rules = [r for r in result["external_systems"] if r["system_type"] == "Database"]
        assert len(db_rules) > 0
        
        # Should detect API (requests appears 3 times)
        api_rules = [r for r in result["external_systems"] if r["system_type"] == "ExternalAPI"]
        assert len(api_rules) > 0
        
        # Should not detect custom_lib (only appears once, below threshold)
        custom_rules = [r for r in result["external_systems"] if "custom_lib" in str(r)]
        assert len(custom_rules) == 0
    
    def test_analyze_naming_conventions(self, dynamic_generator):
        """Test naming convention analysis."""
        graph = {
            "entities": [
                {"id": "e1", "name": "UserController", "type": "class"},
                {"id": "e2", "name": "AdminController", "type": "class"},
                {"id": "e3", "name": "ProductController", "type": "class"},
                {"id": "e4", "name": "UserService", "type": "class"},
                {"id": "e5", "name": "ProductService", "type": "class"},
                {"id": "e6", "name": "OrderService", "type": "class"},
                {"id": "e7", "name": "UserRepository", "type": "class"},
                {"id": "e8", "name": "ProductRepository", "type": "class"},
                {"id": "e9", "name": "OrderRepository", "type": "class"},
                {"id": "e10", "name": "MiscClass", "type": "class"}
            ]
        }
        
        result = dynamic_generator._analyze_naming_conventions(graph, "python")
        
        assert "components" in result
        
        # Should detect Controller pattern (appears 3 times)
        controller_rules = [r for r in result["components"] if r["component_type"] == "Controller"]
        assert len(controller_rules) > 0
        
        # Should detect Service pattern (appears 3 times)
        service_rules = [r for r in result["components"] if r["component_type"] == "Service"]
        assert len(service_rules) > 0
        
        # Should detect Repository pattern (appears 3 times)
        repo_rules = [r for r in result["components"] if r["component_type"] == "Repository"]
        assert len(repo_rules) > 0
    
    def test_analyze_directory_structure(self, dynamic_generator):
        """Test directory structure analysis."""
        repomap = {
            "files": {
                # Multiple controller directories to meet min_occurrences
                "controllers/user_controller.py": {"size": 100},
                "controllers/admin_controller.py": {"size": 100},
                "api/controllers/product_controller.py": {"size": 100},
                "v1/controllers/order_controller.py": {"size": 100},
                # Multiple service directories
                "services/user_service.py": {"size": 200},
                "services/product_service.py": {"size": 200},
                "business/services/order_service.py": {"size": 200},
                "core/services/payment_service.py": {"size": 200},
                "models/user_model.py": {"size": 150},
                "utils/helper.py": {"size": 50}
            }
        }
        
        result = dynamic_generator._analyze_directory_structure(repomap, "python")
        
        assert "containers" in result
        
        # Should detect controllers pattern (3+ directories with 'controller')
        controller_rules = [r for r in result["containers"] if r["container_type"] == "Controller"]
        assert len(controller_rules) > 0
        
        # Should detect services pattern (3+ directories with 'service')
        service_rules = [r for r in result["containers"] if r["container_type"] == "Service"]
        assert len(service_rules) > 0
    
    def test_group_imports_by_system(self, dynamic_generator):
        """Test grouping imports by system."""
        imports = [
            "sqlalchemy",
            "django.db",
            "requests",
            "httpx",
            "redis",
            "celery",
            "custom_lib"
        ]
        
        groups = dynamic_generator._group_imports_by_system(imports, "python")
        
        assert "Database" in groups
        assert "HTTP Client" in groups
        assert "Message Queue" in groups
        
        # Check database group
        assert "sqlalchemy" in groups["Database"]
        assert "django.db" in groups["Database"]
        
        # Check HTTP client group
        assert "requests" in groups["HTTP Client"]
        assert "httpx" in groups["HTTP Client"]
    
    def test_extract_suffixes(self, dynamic_generator):
        """Test suffix extraction from names."""
        names = [
            "UserController",
            "AdminController",
            "UserService",
            "ProductService",
            "UserRepository",
            "ProductRepository",
            "Helper"
        ]
        
        suffixes = dynamic_generator._extract_suffixes(names)
        
        assert suffixes["Controller"] == 2
        assert suffixes["Service"] == 2
        assert suffixes["Repository"] == 2
        assert suffixes["Helper"] == 1
    
    def test_infer_component_type_from_suffix(self, dynamic_generator):
        """Test component type inference from suffix."""
        assert dynamic_generator._infer_component_type_from_suffix("Controller") == "Controller"
        assert dynamic_generator._infer_component_type_from_suffix("Service") == "Service"
        assert dynamic_generator._infer_component_type_from_suffix("Repository") == "Repository"
        assert dynamic_generator._infer_component_type_from_suffix("Model") == "Model"
        assert dynamic_generator._infer_component_type_from_suffix("Unknown") is None
    
    def test_calculate_import_confidence(self, dynamic_generator):
        """Test import confidence calculation."""
        system_imports = ["sqlalchemy", "django.db", "psycopg"]
        import_counter = {
            "sqlalchemy": 10,
            "django.db": 8,
            "psycopg": 5,
            "other": 20
        }
        total_imports = 100
        
        confidence = dynamic_generator._calculate_import_confidence(
            system_imports, import_counter, total_imports
        )
        
        assert 0 <= confidence <= 1
        assert confidence > 0  # Should have some confidence
    
    def test_save_and_load_patterns(self, dynamic_generator):
        """Test saving and loading patterns."""
        # Save some patterns
        patterns = {
            "external_systems": [
                {
                    "id": "test-rule",
                    "name": "Test Rule",
                    "patterns": ["test_pattern"],
                    "usage_count": 5
                }
            ]
        }
        
        dynamic_generator._save_patterns(patterns)
        
        # Load patterns
        loaded = dynamic_generator.patterns
        
        assert "external_systems" in loaded
        assert len(loaded["external_systems"]) == 1
        assert loaded["external_systems"][0]["id"] == "test-rule"
    
    def test_clear_patterns(self, dynamic_generator):
        """Test clearing patterns."""
        # Save some patterns first
        patterns = {"external_systems": []}
        dynamic_generator._save_patterns(patterns)
        
        # Clear patterns
        dynamic_generator.clear_patterns()
        
        # Check they're cleared
        assert dynamic_generator.patterns == {}
        assert not dynamic_generator.patterns_file.exists()
    
    def test_get_dynamic_rules(self, dynamic_generator):
        """Test getting dynamic rules."""
        # Should return empty initially
        rules = dynamic_generator.get_dynamic_rules()
        assert rules == {}
        
        # Save some patterns
        patterns = {"external_systems": [{"id": "test"}]}
        dynamic_generator.patterns = patterns
        
        # Should return saved patterns
        rules = dynamic_generator.get_dynamic_rules()
        assert rules == patterns
