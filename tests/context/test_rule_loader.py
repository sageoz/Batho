"""
Tests for the C4 rule loader system.
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
import yaml

from batho_core.context.c4.rules.loader import RuleLoader
from batho_core.context.c4.rules.cache import RuleCache


@pytest.fixture
def temp_rules_dir():
    """Create a temporary rules directory with test rules."""
    with tempfile.TemporaryDirectory() as tmpdir:
        rules_dir = Path(tmpdir)
        
        # Create directory structure
        (rules_dir / "base").mkdir()
        (rules_dir / "languages").mkdir()
        (rules_dir / "dynamic").mkdir()
        
        # Create base external systems rule
        external_systems = {
            "external_systems": [
                {
                    "name": "Test Database",
                    "description": "Test database rule",
                    "priority": 100,
                    "patterns": ["test_db", "test_sql"],
                    "system_type": "Database",
                    "actor_name": "Test DB",
                    "actor_description": "Test database system"
                }
            ]
        }
        (rules_dir / "base" / "external_systems.yaml").write_text(
            yaml.dump(external_systems)
        )
        
        # Create base containers rule
        containers = {
            "containers": [
                {
                    "name": "Test Web App",
                    "description": "Test web application",
                    "priority": 100,
                    "framework_patterns": ["TestFramework"],
                    "directory_patterns": ["web"],
                    "container_type": "Web Application",
                    "container_name": "Test Web App",
                    "technology": ["Test"]
                }
            ]
        }
        (rules_dir / "base" / "containers.yaml").write_text(
            yaml.dump(containers)
        )
        
        # Create base components rule
        components = {
            "components": [
                {
                    "name": "Test Controller",
                    "description": "Test controller rule",
                    "entity_types": ["class"],
                    "importance_threshold": 0.5,
                    "max_per_file": 3,
                    "component_type": "Controller"
                }
            ]
        }
        (rules_dir / "base" / "components.yaml").write_text(
            yaml.dump(components)
        )
        
        # Create Python-specific rules
        python_rules = {
            "language": "python",
            "external_systems": [
                {
                    "name": "Python Database",
                    "description": "Python-specific database",
                    "priority": 110,
                    "patterns": ["django.db", "sqlalchemy"],
                    "system_type": "Database",
                    "actor_name": "Python DB",
                    "actor_description": "Python database"
                }
            ]
        }
        (rules_dir / "languages" / "python.yaml").write_text(
            yaml.dump(python_rules)
        )
        
        yield rules_dir


@pytest.fixture
def rule_loader(temp_rules_dir):
    """Create a rule loader instance."""
    return RuleLoader(temp_rules_dir)


class TestRuleLoader:
    """Test cases for RuleLoader."""
    
    def test_load_all_rules(self, rule_loader):
        """Test loading all rules."""
        rules = rule_loader.load_all_rules()
        
        assert "base" in rules
        assert "languages" in rules
        assert "dynamic" in rules
        assert "python" in rules["languages"]
        
        # Check base rules
        assert len(rules["base"]["external_systems"]) == 1
        assert rules["base"]["external_systems"][0]["name"] == "Test Database"
        
        # Check language rules
        assert len(rules["languages"]["python"]["external_systems"]) == 2  # Base + Python
    
    def test_get_external_system_rules(self, rule_loader):
        """Test getting external system rules."""
        # Test without language filter
        rules = rule_loader.get_external_system_rules()
        assert len(rules) == 1
        assert rules[0]["name"] == "Test Database"
        
        # Test with language filter
        rules = rule_loader.get_external_system_rules(language="python")
        assert len(rules) == 2  # Should merge base and Python rules
        names = [r["name"] for r in rules]
        assert "Test Database" in names
        assert "Python Database" in names
    
    def test_get_container_rules(self, rule_loader):
        """Test getting container rules."""
        rules = rule_loader.get_container_rules()
        assert len(rules) == 1
        assert rules[0]["name"] == "Test Web App"
    
    def test_get_component_rules(self, rule_loader):
        """Test getting component rules."""
        rules = rule_loader.get_component_rules()
        assert len(rules) == 1
        assert rules[0]["name"] == "Test Controller"
    
    def test_caching(self, rule_loader):
        """Test rule caching functionality."""
        # Load rules first time
        rules1 = rule_loader.load_all_rules()
        
        # Load rules second time (should use cache)
        rules2 = rule_loader.load_all_rules()
        
        assert rules1 is rules2  # Should be the same object (cached)
        
        # Force reload
        rules3 = rule_loader.load_all_rules(force_reload=True)
        assert rules1 is not rules3  # Should be a new object
    
    def test_invalid_yaml_file(self, temp_rules_dir):
        """Test handling of invalid YAML files."""
        # Create invalid YAML file
        (temp_rules_dir / "base" / "invalid.yaml").write_text("invalid: yaml: content:")
        
        loader = RuleLoader(temp_rules_dir)
        # Should not raise exception, just skip invalid file
        rules = loader.load_all_rules()
        assert "base" in rules
    
    def test_missing_rules_directory(self):
        """Test handling of missing rules directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            non_existent = Path(tmpdir) / "non_existent"
            loader = RuleLoader(non_existent)
            
            # Should create empty rules structure
            rules = loader.load_all_rules()
            assert rules == {
                "version": "1.0",
                "base": {"external_systems": [], "containers": [], "components": []},
                "languages": {},
                "enhanced": {
                    "microservices": {},
                    "event_driven": {},
                    "cloud_native": {},
                    "data_patterns": {}
                },
                "dynamic": {"external_systems": [], "containers": [], "components": []},
                "loaded_at": ""
            }


class TestRuleCache:
    """Test cases for RuleCache."""
    
    def test_cache_operations(self):
        """Test basic cache operations."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir)
            cache = RuleCache(cache_dir=cache_dir)
            
            # Test set and get
            cache.set("test_key", {"data": "test"})
            result = cache.get("test_key")
            assert result == {"data": "test"}
            
            # Test cache miss
            result = cache.get("non_existent")
            assert result is None
    
    def test_cache_ttl(self):
        """Test cache TTL functionality."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir)
            cache = RuleCache(cache_dir=cache_dir, default_ttl=0.1)  # 0.1 second TTL
            
            cache.set("test_key", {"data": "test"})
            
            # Should be available immediately
            result = cache.get("test_key")
            assert result == {"data": "test"}
            
            # Wait for expiry
            import time
            time.sleep(0.2)
            
            # Should be expired
            result = cache.get("test_key")
            assert result is None
    
    def test_file_change_detection(self):
        """Test cache invalidation on file changes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir)
            cache = RuleCache(cache_dir=cache_dir)
            
            test_file = cache_dir / "test.txt"
            test_file.write_text("version1")
            
            # Cache with file
            cache.set("test_key", {"data": "test"}, file_path=test_file)
            result = cache.get("test_key", file_path=test_file)
            assert result == {"data": "test"}
            
            # Change file
            test_file.write_text("version2")
            
            # Cache should be invalidated
            result = cache.get("test_key", file_path=test_file)
            assert result is None
    
    def test_persistent_cache(self):
        """Test persistent cache storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir)
            cache1 = RuleCache(cache_dir=cache_dir)
            
            cache1.set("test_key", {"data": "persistent"})
            
            # Create new cache instance (should load from disk)
            cache2 = RuleCache(cache_dir=cache_dir)
            result = cache2.get("test_key")
            assert result == {"data": "persistent"}
