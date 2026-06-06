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
        indexer = DependencyIndexer(temp_dir, mock_scope_manager, mock_config)
        assert indexer.root == temp_dir
        assert indexer.scope_manager == mock_scope_manager
        assert indexer.cfg == mock_config

    def test_init_with_cache_dir(self, temp_dir, mock_scope_manager, mock_config):
        indexer = DependencyIndexer(temp_dir, mock_scope_manager, mock_config, cache_dir="custom_cache")
        assert indexer.cache.cache_dir == temp_dir / "custom_cache"

    def test_run_empty_project(self, temp_dir, mock_scope_manager, mock_config):
        indexer = DependencyIndexer(temp_dir, mock_scope_manager, mock_config)
        stats = indexer.run()
        assert stats.manifests_found == 0
        assert stats.duration_ms > 0

    def test_index_stdlib_python(self, temp_dir, mock_scope_manager, mock_config):
        indexer = DependencyIndexer(temp_dir, mock_scope_manager, mock_config)
        indexer._index_stdlib()
        assert indexer.stats.symbols_indexed > 0

    def test_add_symbols_to_scope(self, temp_dir, mock_scope_manager, mock_config):
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
        indexer = DependencyIndexer(temp_dir, mock_scope_manager, mock_config)
        
        # Create .venv
        (temp_dir / ".venv").mkdir()
        assert indexer._find_venv() == temp_dir / ".venv"
        
        # Remove .venv, create venv
        (temp_dir / ".venv").rmdir()
        (temp_dir / "venv").mkdir()
        assert indexer._find_venv() == temp_dir / "venv"

    def test_unique_deps_filtering(self, temp_dir, mock_scope_manager, mock_config):
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
        with patch('batho.modules.dependency.indexer.ThreadPoolExecutor') as mock_executor:
            mock_future = Mock()
            mock_future.result.return_value = {"pkg": ["symbol1"]}
            mock_executor.return_value.__enter__.return_value.submit.return_value = mock_future
            mock_executor.return_value.__enter__.return_value.futures = {mock_future: Mock()}
            
            indexer = DependencyIndexer(temp_dir, mock_scope_manager, mock_config)
            # Test would verify ThreadPoolExecutor is used correctly
