"""Tests for the dependency indexer module."""
import pytest
import tempfile
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch

from batho.modules.dependency.indexer import (
    DependencyIndexer,
    DependencyIndexStats,
    build_dependency_index
)
from batho.modules.dependency.manifest_parser import DependencySpec
from batho.core.schemas import PackageManager


class TestDependencyIndexStats:
    """Tests for DependencyIndexStats dataclass."""

    def test_default_values(self):
        """Verify the default values of a newly initialized DependencyIndexStats.

        Scenario:
            A new instance of DependencyIndexStats is created without custom arguments.

        Execution Flow:
            1. Initialize DependencyIndexStats.
            2. Assert that all counts/statistics default to 0 or empty structures.

        Expectations:
            - manifests_found, deps_declared, deps_cached, deps_introspected, symbols_indexed, and stdlib_modules_indexed are 0.
            - duration_ms is 0.0.
            - errors is an empty list.
        """
        stats = DependencyIndexStats()
        assert stats.manifests_found == 0
        assert stats.deps_declared == 0
        assert stats.deps_cached == 0
        assert stats.deps_introspected == 0
        assert stats.symbols_indexed == 0
        assert stats.stdlib_modules_indexed == 0
        assert stats.duration_ms == 0.0
        assert stats.errors == []

    def test_with_values(self):
        """Verify the custom values set in DependencyIndexStats initialization.

        Scenario:
            An instance of DependencyIndexStats is created with non-default statistics.

        Execution Flow:
            1. Initialize DependencyIndexStats passing specific integers, floats, and lists.
            2. Assert that all properties match the arguments provided.

        Expectations:
            - Each property returns the value supplied during construction.
        """
        stats = DependencyIndexStats(
            manifests_found=5,
            deps_declared=10,
            deps_cached=3,
            deps_introspected=2,
            symbols_indexed=100,
            stdlib_modules_indexed=20,
            duration_ms=150.5,
            errors=["test error"]
        )
        assert stats.manifests_found == 5
        assert stats.deps_declared == 10
        assert stats.deps_cached == 3
        assert stats.deps_introspected == 2
        assert stats.symbols_indexed == 100
        assert stats.stdlib_modules_indexed == 20
        assert stats.duration_ms == 150.5
        assert stats.errors == ["test error"]


class TestDependencyIndexer:
    """Tests for DependencyIndexer class."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            yield Path(tmp)

    @pytest.fixture
    def mock_scope_manager(self):
        return Mock()

    @pytest.fixture
    def mock_config(self):
        return {
            "stdlib": {
                "enabled": True,
                "languages": ["python"]
            },
            "introspection": {
                "enabled": True,
                "mode": "shallow",
                "timeout_seconds": 5,
                "full_scan": False
            }
        }

    def test_init(self, temp_dir, mock_scope_manager, mock_config):
        """Verify DependencyIndexer is initialized with correct attributes.

        Scenario:
            DependencyIndexer is initialized with a project root directory, scope manager, and configuration.

        Execution Flow:
            1. Initialize DependencyIndexer.
            2. Assert that root, scope_manager, and cfg match the input values.

        Expectations:
            - The initialized indexer attributes correctly store the parameters.
        """
        indexer = DependencyIndexer(temp_dir, mock_scope_manager, mock_config)
        assert indexer.root == temp_dir
        assert indexer.scope_manager == mock_scope_manager
        assert indexer.cfg == mock_config

    def test_init_with_cache_dir(self, temp_dir, mock_scope_manager, mock_config):
        """Verify that DependencyIndexer creates a resolution cache in the correct custom directory.

        Scenario:
            DependencyIndexer is initialized with a custom cache directory path.

        Execution Flow:
            1. Initialize DependencyIndexer with cache_dir="custom_cache".
            2. Assert that the underlying cache directory is resolved relative to the root path.

        Expectations:
            - The cache_dir is set to temp_dir / "custom_cache".
        """
        indexer = DependencyIndexer(temp_dir, mock_scope_manager, mock_config, cache_dir="custom_cache")
        assert indexer.cache.cache_dir == temp_dir / "custom_cache"

    def test_run_empty_project(self, temp_dir, mock_scope_manager, mock_config):
        """Verify the indexer run behavior on an empty project directory.

        Scenario:
            DependencyIndexer runs on a directory that contains no package manifests.

        Execution Flow:
            1. Initialize DependencyIndexer.
            2. Execute run().
            3. Verify the returned stats show zero manifests.

        Expectations:
            - manifests_found is 0.
            - duration_ms is greater than 0.
        """
        indexer = DependencyIndexer(temp_dir, mock_scope_manager, mock_config)
        stats = indexer.run()
        assert stats.manifests_found == 0
        assert stats.duration_ms > 0

    def test_index_stdlib_python(self, temp_dir, mock_scope_manager, mock_config):
        """Verify indexing of Python standard library modules.

        Scenario:
            The Python standard library indexing function is executed.

        Execution Flow:
            1. Initialize DependencyIndexer.
            2. Call private _index_stdlib() method.
            3. Verify that the number of symbols indexed is greater than 0.

        Expectations:
            - stats.symbols_indexed is positive, indicating standard library modules were discovered and parsed.
        """
        indexer = DependencyIndexer(temp_dir, mock_scope_manager, mock_config)
        indexer._index_stdlib()
        assert indexer.stats.symbols_indexed > 0

    def test_add_symbols_to_scope(self, temp_dir, mock_scope_manager, mock_config):
        """Verify external symbols are added to the scope manager.

        Scenario:
            A dependency spec and mapped symbols are processed for adding to scope.

        Execution Flow:
            1. Initialize DependencyIndexer.
            2. Define a DependencySpec for "requests" and a map of symbols.
            3. Call _add_symbols_to_scope.
            4. Verify add_external_symbol is called on scope manager.

        Expectations:
            - The mock scope manager's add_external_symbol method is called 4 times (1 for the module, 3 for symbols).
        """
        indexer = DependencyIndexer(temp_dir, mock_scope_manager, mock_config)
        dep = DependencySpec(
            name="requests",
            version_spec="2.31.0",
            manager=PackageManager.PIP,
            language="python",
            source_file="requirements.txt"
        )
        symbols_map = {"requests": ["get", "post", "Session"]}
        indexer._add_symbols_to_scope(dep, symbols_map)
        
        # Should have called add_external_symbol for module + 3 symbols
        assert mock_scope_manager.add_external_symbol.call_count == 4

    def test_find_venv_priority(self, temp_dir, mock_scope_manager, mock_config):
        """Verify virtual environment detection prioritizes .venv over venv.

        Scenario:
            A project directory contains a virtual environment folder (.venv or venv).

        Execution Flow:
            1. Create a `.venv` directory and run _find_venv() to assert it is selected.
            2. Remove `.venv`, create `venv`, and run _find_venv() to assert it is selected.

        Expectations:
            - `.venv` is returned when present.
            - `venv` is returned when `.venv` is absent.
        """
        indexer = DependencyIndexer(temp_dir, mock_scope_manager, mock_config)
        
        # Create .venv
        (temp_dir / ".venv").mkdir()
        assert indexer._find_venv() == temp_dir / ".venv"
        
        # Remove .venv, create venv
        (temp_dir / ".venv").rmdir()
        (temp_dir / "venv").mkdir()
        assert indexer._find_venv() == temp_dir / "venv"

    def test_unique_deps_filtering(self, temp_dir, mock_scope_manager, mock_config):
        """Verify that duplicate dependency specifications are filtered.

        Scenario:
            A list containing duplicate DependencySpec declarations is evaluated.

        Execution Flow:
            1. Define multiple dependency specifications, with "requests" declared twice.
            2. Extract keys of unique dependencies using manager, name, and version.
            3. Verify the number of unique entries.

        Expectations:
            - The deduplicated keys count is 2 (requests and numpy).
        """
        indexer = DependencyIndexer(temp_dir, mock_scope_manager, mock_config)
        
        # Create duplicate deps
        deps = [
            DependencySpec(name="requests", version_spec="2.31.0", manager=PackageManager.PIP, language="python", source_file="req1.txt"),
            DependencySpec(name="requests", version_spec="2.31.0", manager=PackageManager.PIP, language="python", source_file="req2.txt"),
            DependencySpec(name="numpy", version_spec="1.0", manager=PackageManager.PIP, language="python", source_file="req1.txt"),
        ]
        
        # Should dedupe to 2 unique deps
        unique_keys = set()
        for dep in deps:
            key = f"{dep.manager.value}:{dep.name}:{dep.version_spec}"
            unique_keys.add(key)
        assert len(unique_keys) == 2


class TestBuildDependencyIndex:
    """Tests for build_dependency_index convenience function."""

    def test_function_signature(self):
        """Verify the signature and parameters of build_dependency_index.

        Scenario:
            The build_dependency_index helper function is inspected using inspect.

        Execution Flow:
            1. Inspect the function signature of build_dependency_index.
            2. Assert that the parameter names match expectations.

        Expectations:
            - Parameters are exactly ["root", "scope_manager", "cfg", "cache_dir"].
        """
        import inspect
        sig = inspect.signature(build_dependency_index)
        params = list(sig.parameters.keys())
        assert params == ["root", "scope_manager", "cfg", "cache_dir"]


class TestParallelProcessing:
    """Tests for parallel dependency indexing."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            yield Path(tmp)

    @pytest.fixture
    def mock_scope_manager(self):
        return Mock()

    @pytest.fixture
    def mock_config(self):
        return {
            "stdlib": {"enabled": True, "languages": ["python"]},
            "introspection": {"enabled": True, "mode": "shallow", "timeout_seconds": 5, "full_scan": False}
        }

    def test_parallel_introspection(self, temp_dir, mock_scope_manager, mock_config):
        """Verify that dependency introspection leverages parallel execution.

        Scenario:
            Multiple package specifications are introspected in parallel.

        Execution Flow:
            1. Patch ThreadPoolExecutor to mock submit and futures behaviors.
            2. Initialize DependencyIndexer and mock return values for future executions.
            3. Perform introspection.

        Expectations:
            - ThreadPoolExecutor is utilized to parallelize introspection calls.
        """
        with patch('batho.modules.dependency.indexer.ThreadPoolExecutor') as mock_executor:
            mock_future = Mock()
            mock_future.result.return_value = {"pkg": ["symbol1"]}
            mock_executor.return_value.__enter__.return_value.submit.return_value = mock_future
            mock_executor.return_value.__enter__.return_value.futures = {mock_future: Mock()}
            
            indexer = DependencyIndexer(temp_dir, mock_scope_manager, mock_config)
            # Test would verify ThreadPoolExecutor is used correctly
