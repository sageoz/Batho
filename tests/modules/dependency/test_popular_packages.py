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
        """Verify that PopularPackagesDB follows the singleton pattern.

        Scenario:
            Multiple instantiations of PopularPackagesDB are requested.

        Execution Flow:
            1. Construct two PopularPackagesDB instances pointing to the same file path.
            2. Assert that both instances refer to the exact same object in memory.

        Expectations:
            - db1 and db2 are the identical object instance.
        """
        db1 = PopularPackagesDB(temp_db_file)
        db2 = PopularPackagesDB(temp_db_file)
        assert db1 is db2

    def test_load_yaml_data(self, temp_db_file):
        """Verify PopularPackagesDB correctly loads yaml configuration file data.

        Scenario:
            PopularPackagesDB is initialized with a path to a valid YAML file.

        Execution Flow:
            1. Initialize the database object.
            2. Verify the raw parsed YAML content is loaded into the private attribute `_data`.

        Expectations:
            - The loaded dictionary contains the "languages" key.
            - "python" configuration is nested under "languages".
        """
        db = PopularPackagesDB(temp_db_file)
        assert "languages" in db._data
        assert "python" in db._data["languages"]

    def test_get_language_config(self, temp_db_file):
        """Verify retrieval of configuration map for a supported language.

        Scenario:
            Language configuration for Python is requested.

        Execution Flow:
            1. Call get_language_config() with "python".
            2. Validate the structure of the returned dictionary.

        Expectations:
            - The returned config is not None.
            - The config dictionary contains the "packages" list.
        """
        db = PopularPackagesDB(temp_db_file)
        config = db.get_language_config("python")
        assert config is not None
        assert "packages" in config

    def test_get_language_config_case_insensitive(self, temp_db_file):
        """Verify language config retrieval ignores case sensitivity.

        Scenario:
            Language configuration for "PYTHON" is requested.

        Execution Flow:
            1. Call get_language_config() using uppercase "PYTHON".
            2. Assert that the configuration is found and returned.

        Expectations:
            - Returns a valid config dictionary instead of None.
        """
        db = PopularPackagesDB(temp_db_file)
        config = db.get_language_config("PYTHON")
        assert config is not None

    def test_get_packages(self, temp_db_file):
        """Verify package list retrieval for a supported language.

        Scenario:
            All packages for Python are queried from the database.

        Execution Flow:
            1. Call get_packages() with "python".
            2. Validate length and first package name.

        Expectations:
            - Returns exactly 3 package definitions.
            - The first package name is "requests".
        """
        db = PopularPackagesDB(temp_db_file)
        packages = db.get_packages("python")
        assert len(packages) == 3
        assert packages[0]["name"] == "requests"

    def test_get_packages_with_limit(self, temp_db_file):
        """Verify limiting package count returned by get_packages.

        Scenario:
            Packages for python are queried with a limit of 2.

        Execution Flow:
            1. Call get_packages() with language="python" and limit=2.
            2. Assert the length of the returned list.

        Expectations:
            - Returns a list containing exactly 2 packages.
        """
        db = PopularPackagesDB(temp_db_file)
        packages = db.get_packages("python", limit=2)
        assert len(packages) == 2

    def test_get_packages_unknown_language(self, temp_db_file):
        """Verify get_packages returns an empty list for unsupported languages.

        Scenario:
            Packages are queried for an unregistered language.

        Execution Flow:
            1. Call get_packages() with "unknown".
            2. Assert that the output list is empty.

        Expectations:
            - Returns an empty list.
        """
        db = PopularPackagesDB(temp_db_file)
        packages = db.get_packages("unknown")
        assert packages == []

    def test_should_introspect_full_scan(self, temp_db_file):
        """Verify introspection is allowed for any package when full_scan is enabled.

        Scenario:
            An introspection check is run for an unknown package with full_scan enabled.

        Execution Flow:
            1. Call should_introspect() with full_scan=True.
            2. Assert that the return value is True.

        Expectations:
            - Introspection is allowed (returns True).
        """
        db = PopularPackagesDB(temp_db_file)
        # With full_scan=True, should always return True
        assert db.should_introspect("python", "unknown-package", full_scan=True)

    def test_should_introspect_popular_package(self, temp_db_file):
        """Verify introspection is allowed for a known popular package.

        Scenario:
            An introspection check is run for "requests" with full_scan disabled.

        Execution Flow:
            1. Call should_introspect() for "requests" with full_scan=False.
            2. Assert that the return value is True.

        Expectations:
            - Introspection is allowed because the package is in the popular package list.
        """
        db = PopularPackagesDB(temp_db_file)
        # requests is in the popular packages
        assert db.should_introspect("python", "requests", full_scan=False)

    def test_should_introspect_unpopular_package(self, temp_db_file):
        """Verify introspection is blocked for a package not in the popular package set.

        Scenario:
            An introspection check is run for an unknown package with full_scan disabled.

        Execution Flow:
            1. Call should_introspect() for "unknown-package" with full_scan=False.
            2. Assert that the return value is False.

        Expectations:
            - Introspection is blocked (returns False).
        """
        db = PopularPackagesDB(temp_db_file)
        # unknown-package is not in the popular packages
        assert not db.should_introspect("python", "unknown-package", full_scan=False)

    def test_should_introspect_unknown_language(self, temp_db_file):
        """Verify introspection is blocked for unknown languages.

        Scenario:
            An introspection check is run for a package under an unsupported language.

        Execution Flow:
            1. Call should_introspect() with language="unknown".
            2. Assert that the return value is False.

        Expectations:
            - Introspection is blocked (returns False).
        """
        db = PopularPackagesDB(temp_db_file)
        # Unknown language should return False
        assert not db.should_introspect("unknown", "some-package", full_scan=False)

    def test_should_introspect_o1_performance(self, temp_db_file):
        """Verify that popular package sets are indexed to ensure O(1) membership lookups.

        Scenario:
            The internal `_package_sets` dictionary is inspected.

        Execution Flow:
            1. Initialize PopularPackagesDB.
            2. Assert that python and javascript sets exist.
            3. Check that package names are present in these sets.

        Expectations:
            - Lookups are set-based ensuring efficient constant time search.
        """
        db = PopularPackagesDB(temp_db_file)
        
        # Build package sets should exist
        assert "python" in db._package_sets
        assert "javascript" in db._package_sets
        
        # Sets should contain the package names
        assert "requests" in db._package_sets["python"]
        assert "numpy" in db._package_sets["python"]
        assert "express" in db._package_sets["javascript"]

    def test_get_symbol_indexing_strategy_simple(self, temp_db_file):
        """Verify symbol indexing strategy lookup for a simple configuration.

        Scenario:
            The indexing strategy for Python is requested.

        Execution Flow:
            1. Call get_symbol_indexing_strategy() with "python".
            2. Assert that the returned strategy matches "bundled_tables_only".

        Expectations:
            - Python strategy evaluates to "bundled_tables_only".
        """
        db = PopularPackagesDB(temp_db_file)
        strategy = db.get_symbol_indexing_strategy("python")
        assert strategy == "bundled_tables_only"

    def test_get_symbol_indexing_strategy_nested(self, temp_db_file):
        """Verify symbol indexing strategy lookup for a nested configuration map.

        Scenario:
            The indexing strategy for Javascript is requested.

        Execution Flow:
            1. Call get_symbol_indexing_strategy() with "javascript".
            2. Assert that the nested default strategy "introspection" is resolved.

        Expectations:
            - Javascript strategy evaluates to "introspection".
        """
        db = PopularPackagesDB(temp_db_file)
        strategy = db.get_symbol_indexing_strategy("javascript")
        assert strategy == "introspection"

    def test_get_symbol_indexing_strategy_unknown(self, temp_db_file):
        """Verify default fallback strategy for unknown languages.

        Scenario:
            The indexing strategy for an unsupported language is requested.

        Execution Flow:
            1. Call get_symbol_indexing_strategy() with "unknown".
            2. Assert that the default fallback strategy is returned.

        Expectations:
            - Resolves to "bundled_tables_only".
        """
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
        """Verify database initialization gracefully handles a missing YAML file.

        Scenario:
            The database points to a non-existent YAML file path.

        Execution Flow:
            1. Create a reference path for a non-existent file.
            2. Instantiate PopularPackagesDB with the nonexistent path.
            3. Verify the initialized dataset is empty.

        Expectations:
            - Database initializes successfully.
            - `_data` is an empty dictionary.
        """
        with tempfile.TemporaryDirectory() as tmp:
            nonexistent = Path(tmp) / "nonexistent.yaml"
            db = PopularPackagesDB(nonexistent)
            assert db._data == {}

    def test_empty_packages_list(self):
        """Verify database behavior when the package list in YAML is empty.

        Scenario:
            A database is configured with an empty list of packages for python.

        Execution Flow:
            1. Dump YAML containing an empty package list for python.
            2. Instantiate PopularPackagesDB.
            3. Call should_introspect() and assert it returns False.

        Expectations:
            - `should_introspect` evaluates to False because the package set is empty.
        """
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml.dump({"languages": {"python": {"packages": []}}}, f)
            db_path = Path(f.name)
        
        try:
            PopularPackagesDB._instance = None  # Reset singleton
            db = PopularPackagesDB(db_path)
            assert not db.should_introspect("python", "any-package", full_scan=False)
        finally:
            db_path.unlink(missing_ok=True)
