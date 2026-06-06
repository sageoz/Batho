"""Tests for the resolution cache module."""
import tempfile
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import pytest

from batho.modules.dependency.resolution_cache import ResolutionCache


class TestResolutionCache:
    """Tests for ResolutionCache class."""

    @pytest.fixture
    def temp_cache_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            yield Path(tmp)

    def test_init_creates_directories(self, temp_cache_dir):
        cache = ResolutionCache(temp_cache_dir)
        assert cache.dep_dir.exists()
        assert cache.cache_dir.exists()

    def test_put_and_get_symbols(self, temp_cache_dir):
        cache = ResolutionCache(temp_cache_dir)
        symbols = {"module1": ["func1", "func2"], "module2": ["class1"]}
        
        cache.put_symbols("mypackage", "1.0.0", "pip", symbols)
        retrieved = cache.get_symbols("mypackage", "1.0.0", "pip")
        
        assert retrieved == symbols

    def test_get_symbols_missing(self, temp_cache_dir):
        cache = ResolutionCache(temp_cache_dir)
        result = cache.get_symbols("nonexistent", "1.0.0", "pip")
        assert result is None

    def test_get_symbols_different_versions(self, temp_cache_dir):
        cache = ResolutionCache(temp_cache_dir)
        symbols_v1 = {"mod": ["func_v1"]}
        symbols_v2 = {"mod": ["func_v2"]}
        
        cache.put_symbols("pkg", "1.0.0", "pip", symbols_v1)
        cache.put_symbols("pkg", "2.0.0", "pip", symbols_v2)
        
        assert cache.get_symbols("pkg", "1.0.0", "pip") == symbols_v1
        assert cache.get_symbols("pkg", "2.0.0", "pip") == symbols_v2

    def test_get_symbols_different_managers(self, temp_cache_dir):
        cache = ResolutionCache(temp_cache_dir)
        pip_symbols = {"mod": ["pip_func"]}
        conda_symbols = {"mod": ["conda_func"]}
        
        cache.put_symbols("pkg", "1.0.0", "pip", pip_symbols)
        cache.put_symbols("pkg", "1.0.0", "conda", conda_symbols)
        
        assert cache.get_symbols("pkg", "1.0.0", "pip") == pip_symbols
        assert cache.get_symbols("pkg", "1.0.0", "conda") == conda_symbols

    def test_is_manifest_stale_new_file(self, temp_cache_dir):
        cache = ResolutionCache(temp_cache_dir)
        assert cache.is_manifest_stale("/path/to/new/file", "hash123")

    def test_mark_manifest_indexed(self, temp_cache_dir):
        cache = ResolutionCache(temp_cache_dir)
        cache.mark_manifest_indexed("/path/to/file", "hash123")
        
        assert not cache.is_manifest_stale("/path/to/file", "hash123")
        assert cache.is_manifest_stale("/path/to/file", "different_hash")

    def test_put_and_get_project_metadata(self, temp_cache_dir):
        cache = ResolutionCache(temp_cache_dir)
        metadata = {"manager": "pip", "name": "myproject", "version": "1.0.0", "source": ""}
        
        cache.put_project_metadata("/path/to/pyproject.toml", "hash123", metadata)
        retrieved = cache.get_project_metadata("/path/to/pyproject.toml", "hash123")
        
        assert retrieved == metadata

    def test_get_project_metadata_stale(self, temp_cache_dir):
        cache = ResolutionCache(temp_cache_dir)
        metadata = {"manager": "pip", "name": "myproject", "version": "1.0.0", "source": ""}
        
        cache.put_project_metadata("/path/to/pyproject.toml", "hash123", metadata)
        result = cache.get_project_metadata("/path/to/pyproject.toml", "different_hash")
        
        assert result is None

    def test_get_project_metadata_missing(self, temp_cache_dir):
        cache = ResolutionCache(temp_cache_dir)
        result = cache.get_project_metadata("/nonexistent/path", "hash")
        assert result is None

    def test_compute_pkg_hash_deterministic(self, temp_cache_dir):
        cache = ResolutionCache(temp_cache_dir)
        
        hash1 = cache._compute_pkg_hash("requests", "2.31.0", "pip")
        hash2 = cache._compute_pkg_hash("requests", "2.31.0", "pip")
        
        assert hash1 == hash2
        assert len(hash1) == 16  # First 16 chars of SHA256

    def test_compute_pkg_hash_different_inputs(self, temp_cache_dir):
        cache = ResolutionCache(temp_cache_dir)
        
        hash1 = cache._compute_pkg_hash("requests", "2.31.0", "pip")
        hash2 = cache._compute_pkg_hash("requests", "2.32.0", "pip")
        hash3 = cache._compute_pkg_hash("requests", "2.31.0", "conda")
        
        assert hash1 != hash2
        assert hash1 != hash3


class TestResolutionCacheThreadSafety:
    """Tests for thread safety of ResolutionCache."""

    @pytest.fixture
    def temp_cache_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            yield Path(tmp)

    def test_concurrent_put_symbols(self, temp_cache_dir):
        cache = ResolutionCache(temp_cache_dir)
        errors = []
        
        def put_symbols(i):
            try:
                symbols = {f"mod{i}": [f"func{i}"]}
                cache.put_symbols(f"pkg{i}", "1.0.0", "pip", symbols)
            except Exception as e:
                errors.append(e)
        
        with ThreadPoolExecutor(max_workers=10) as executor:
            for i in range(50):
                executor.submit(put_symbols, i)
        
        assert not errors
        
        # Verify all symbols were written
        for i in range(50):
            result = cache.get_symbols(f"pkg{i}", "1.0.0", "pip")
            assert result is not None
            assert f"mod{i}" in result

    def test_concurrent_manifest_indexed(self, temp_cache_dir):
        cache = ResolutionCache(temp_cache_dir)
        errors = []
        
        def mark_indexed(i):
            try:
                cache.mark_manifest_indexed(f"/path/file{i}.txt", f"hash{i}")
            except Exception as e:
                errors.append(e)
        
        with ThreadPoolExecutor(max_workers=10) as executor:
            for i in range(50):
                executor.submit(mark_indexed, i)
        
        assert not errors
        
        # Verify all were recorded
        for i in range(50):
            assert not cache.is_manifest_stale(f"/path/file{i}.txt", f"hash{i}")


class TestResolutionCacheMetadata:
    """Tests for metadata cache functionality."""

    @pytest.fixture
    def temp_cache_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            yield Path(tmp)

    def test_metadata_cache_lazy_load(self, temp_cache_dir):
        cache = ResolutionCache(temp_cache_dir)
        # Metadata cache should be empty before first access
        assert not cache._metadata_loaded
        
        # Access triggers load
        cache._load_metadata_cache()
        assert cache._metadata_loaded

    def test_metadata_cache_persists(self, temp_cache_dir):
        cache1 = ResolutionCache(temp_cache_dir)
        metadata = {"manager": "pip", "name": "proj", "version": "1.0.0", "source": ""}
        cache1.put_project_metadata("/path/to/file", "hash", metadata)
        
        # Create new cache instance pointing to same directory
        cache2 = ResolutionCache(temp_cache_dir)
        result = cache2.get_project_metadata("/path/to/file", "hash")
        
        assert result == metadata
