"""Tests for the popular packages database module."""
import tempfile
from pathlib import Path

import pytest
import yaml

from batho.modules.dependency.popular_packages import PopularPackagesDB


class TestPopularPackagesDB:
    """Tests for PopularPackagesDB class."""

    def setup_method(self):
        """Reset singleton before each test."""
        PopularPackagesDB._instance = None
        PopularPackagesDB._data = {}
        PopularPackagesDB._package_sets = {}

    @pytest.fixture
    def sample_db_content(self):
        return {
            "languages": {
                "python": {
                    "packages": [
                        {"name": "requests"},
                        {"name": "numpy"},
                        {"name": "pandas"},
                    ],
                    "symbol_indexing": "bundled_tables_only"
                },
                "javascript": {
                    "packages": [
                        {"name": "express"},
                        {"name": "lodash"},
                    ],
                    "symbol_indexing": {
                        "default_strategy": "introspection"
                    }
                }
            }
        }

    @pytest.fixture
    def temp_db_file(self, sample_db_content):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml.dump(sample_db_content, f)
            yield Path(f.name)
        Path(f.name).unlink(missing_ok=True)

    def test_singleton_pattern(self, temp_db_file):
        """Test that PopularPackagesDB uses singleton pattern."""
        db1 = PopularPackagesDB(temp_db_file)
        db2 = PopularPackagesDB(temp_db_file)
        assert db1 is db2

    def test_load_yaml_data(self, temp_db_file):
        db = PopularPackagesDB(temp_db_file)
        assert "languages" in db._data
        assert "python" in db._data["languages"]

    def test_get_language_config(self, temp_db_file):
        db = PopularPackagesDB(temp_db_file)
        config = db.get_language_config("python")
        assert config is not None
        assert "packages" in config

    def test_get_language_config_case_insensitive(self, temp_db_file):
        db = PopularPackagesDB(temp_db_file)
        config = db.get_language_config("PYTHON")
        assert config is not None

    def test_get_packages(self, temp_db_file):
        db = PopularPackagesDB(temp_db_file)
        packages = db.get_packages("python")
        assert len(packages) == 3
        assert packages[0]["name"] == "requests"

    def test_get_packages_with_limit(self, temp_db_file):
        db = PopularPackagesDB(temp_db_file)
        packages = db.get_packages("python", limit=2)
        assert len(packages) == 2

    def test_get_packages_unknown_language(self, temp_db_file):
        db = PopularPackagesDB(temp_db_file)
        packages = db.get_packages("unknown")
        assert packages == []

    def test_should_introspect_full_scan(self, temp_db_file):
        db = PopularPackagesDB(temp_db_file)
        # With full_scan=True, should always return True
        assert db.should_introspect("python", "unknown-package", full_scan=True)

    def test_should_introspect_popular_package(self, temp_db_file):
        db = PopularPackagesDB(temp_db_file)
        # requests is in the popular packages
        assert db.should_introspect("python", "requests", full_scan=False)

    def test_should_introspect_unpopular_package(self, temp_db_file):
        db = PopularPackagesDB(temp_db_file)
        # unknown-package is not in the popular packages
        assert not db.should_introspect("python", "unknown-package", full_scan=False)

    def test_should_introspect_unknown_language(self, temp_db_file):
        db = PopularPackagesDB(temp_db_file)
        # Unknown language should return False
        assert not db.should_introspect("unknown", "some-package", full_scan=False)

    def test_should_introspect_o1_performance(self, temp_db_file):
        """Test that should_introspect uses O(1) set lookup."""
        db = PopularPackagesDB(temp_db_file)
        
        # Build package sets should exist
        assert "python" in db._package_sets
        assert "javascript" in db._package_sets
        
        # Sets should contain the package names
        assert "requests" in db._package_sets["python"]
        assert "numpy" in db._package_sets["python"]
        assert "express" in db._package_sets["javascript"]

    def test_get_symbol_indexing_strategy_simple(self, temp_db_file):
        db = PopularPackagesDB(temp_db_file)
        strategy = db.get_symbol_indexing_strategy("python")
        assert strategy == "bundled_tables_only"

    def test_get_symbol_indexing_strategy_nested(self, temp_db_file):
        db = PopularPackagesDB(temp_db_file)
        strategy = db.get_symbol_indexing_strategy("javascript")
        assert strategy == "introspection"

    def test_get_symbol_indexing_strategy_unknown(self, temp_db_file):
        db = PopularPackagesDB(temp_db_file)
        strategy = db.get_symbol_indexing_strategy("unknown")
        assert strategy == "bundled_tables_only"


class TestPopularPackagesDBEdgeCases:
    """Tests for edge cases."""

    def setup_method(self):
        """Reset singleton before each test."""
        PopularPackagesDB._instance = None
        PopularPackagesDB._data = {}
        PopularPackagesDB._package_sets = {}

    def test_missing_db_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            nonexistent = Path(tmp) / "nonexistent.yaml"
            db = PopularPackagesDB(nonexistent)
            assert db._data == {}

    def test_empty_packages_list(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml.dump({"languages": {"python": {"packages": []}}}, f)
            db_path = Path(f.name)
        
        try:
            PopularPackagesDB._instance = None  # Reset singleton
            db = PopularPackagesDB(db_path)
            assert not db.should_introspect("python", "any-package", full_scan=False)
        finally:
            db_path.unlink(missing_ok=True)
