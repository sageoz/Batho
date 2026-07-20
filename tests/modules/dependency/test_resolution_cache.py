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
        """Verify that initializing ResolutionCache creates the necessary folders.

        Scenario:
            ResolutionCache is initialized with a directory path.

        Execution Flow:
            1. Initialize ResolutionCache using `temp_cache_dir`.
            2. Check that the dependency directory and cache directory exist on disk.

        Expectations:
            - Both `cache.dep_dir` and `cache.cache_dir` exist.
        """
        cache = ResolutionCache(temp_cache_dir)
        assert cache.dep_dir.exists()
        assert cache.cache_dir.exists()

    def test_put_and_get_symbols(self, temp_cache_dir):
        """Verify symbols can be successfully stored and retrieved from the cache.

        Scenario:
            A package's symbols map is added to the cache and then retrieved.

        Execution Flow:
            1. Call `put_symbols` with a symbol mapping dictionary.
            2. Invoke `get_symbols` for the same package, version, and manager.
            3. Assert that the retrieved symbols match the stored ones.

        Expectations:
            - The retrieved symbol dictionary matches the input symbols.
        """
        cache = ResolutionCache(temp_cache_dir)
        symbols = {"module1": ["func1", "func2"], "module2": ["class1"]}
        
        cache.put_symbols("mypackage", "1.0.0", "pip", symbols)
        retrieved = cache.get_symbols("mypackage", "1.0.0", "pip")
        
        assert retrieved == symbols

    def test_get_symbols_missing(self, temp_cache_dir):
        """Verify get_symbols returns None for a non-cached package.

        Scenario:
            A package which has not been cached is requested.

        Execution Flow:
            1. Invoke `get_symbols` with a nonexistent package name.
            2. Assert that the returned value is None.

        Expectations:
            - Resolves to None.
        """
        cache = ResolutionCache(temp_cache_dir)
        result = cache.get_symbols("nonexistent", "1.0.0", "pip")
        assert result is None

    def test_get_symbols_different_versions(self, temp_cache_dir):
        """Verify symbols are isolated and retrieved by specific package versions.

        Scenario:
            Different versions of the same package are stored in the cache.

        Execution Flow:
            1. Save symbols for package v1.0.0.
            2. Save distinct symbols for package v2.0.0.
            3. Retrieve and assert symbols separately for both versions.

        Expectations:
            - Symbols for v1.0.0 and v2.0.0 are stored and returned independently.
        """
        cache = ResolutionCache(temp_cache_dir)
        symbols_v1 = {"mod": ["func_v1"]}
        symbols_v2 = {"mod": ["func_v2"]}
        
        cache.put_symbols("pkg", "1.0.0", "pip", symbols_v1)
        cache.put_symbols("pkg", "2.0.0", "pip", symbols_v2)
        
        assert cache.get_symbols("pkg", "1.0.0", "pip") == symbols_v1
        assert cache.get_symbols("pkg", "2.0.0", "pip") == symbols_v2

    def test_get_symbols_different_managers(self, temp_cache_dir):
        """Verify symbols are isolated by package managers.

        Scenario:
            The same package and version is cached via different package managers (pip and conda).

        Execution Flow:
            1. Cache pip-specific symbols.
            2. Cache conda-specific symbols.
            3. Retrieve and assert symbols for each manager independently.

        Expectations:
            - Stored symbols are isolated by manager.
        """
        cache = ResolutionCache(temp_cache_dir)
        pip_symbols = {"mod": ["pip_func"]}
        conda_symbols = {"mod": ["conda_func"]}
        
        cache.put_symbols("pkg", "1.0.0", "pip", pip_symbols)
        cache.put_symbols("pkg", "1.0.0", "conda", conda_symbols)
        
        assert cache.get_symbols("pkg", "1.0.0", "pip") == pip_symbols
        assert cache.get_symbols("pkg", "1.0.0", "conda") == conda_symbols

    def test_is_manifest_stale_new_file(self, temp_cache_dir):
        """Verify that a newly introduced manifest file is considered stale.

        Scenario:
            An index staleness check is performed on a new manifest path.

        Execution Flow:
            1. Call `is_manifest_stale` with a new filepath and hash.
            2. Assert that the return value is True.

        Expectations:
            - Returns True.
        """
        cache = ResolutionCache(temp_cache_dir)
        assert cache.is_manifest_stale("/path/to/new/file", "hash123")

    def test_mark_manifest_indexed(self, temp_cache_dir):
        """Verify marking a manifest file as indexed makes it not stale until modified.

        Scenario:
            A manifest file is indexed and subsequent staleness is checked.

        Execution Flow:
            1. Call `mark_manifest_indexed` with a file path and hash.
            2. Check staleness with the same hash.
            3. Check staleness with a different hash.

        Expectations:
            - returns False for the same hash (not stale).
            - returns True for a different hash (stale).
        """
        cache = ResolutionCache(temp_cache_dir)
        cache.mark_manifest_indexed("/path/to/file", "hash123")
        
        assert not cache.is_manifest_stale("/path/to/file", "hash123")
        assert cache.is_manifest_stale("/path/to/file", "different_hash")

    def test_put_and_get_project_metadata(self, temp_cache_dir):
        """Verify storing and retrieving project metadata by filepath and hash.

        Scenario:
            Metadata for a project config file is cached and retrieved.

        Execution Flow:
            1. Store project metadata with `put_project_metadata`.
            2. Retrieve metadata with `get_project_metadata`.
            3. Assert that retrieved values match the stored dict.

        Expectations:
            - Stored metadata is returned successfully.
        """
        cache = ResolutionCache(temp_cache_dir)
        metadata = {"manager": "pip", "name": "myproject", "version": "1.0.0", "source": ""}
        
        cache.put_project_metadata("/path/to/pyproject.toml", "hash123", metadata)
        retrieved = cache.get_project_metadata("/path/to/pyproject.toml", "hash123")
        
        assert retrieved == metadata

    def test_get_project_metadata_stale(self, temp_cache_dir):
        """Verify that querying project metadata with a modified hash returns None.

        Scenario:
            Metadata is cached for a file hash but later queried using a new hash.

        Execution Flow:
            1. Save metadata for a file path with 'hash123'.
            2. Query metadata for the file path with 'different_hash'.
            3. Assert the result is None.

        Expectations:
            - Stale metadata queries return None.
        """
        cache = ResolutionCache(temp_cache_dir)
        metadata = {"manager": "pip", "name": "myproject", "version": "1.0.0", "source": ""}
        
        cache.put_project_metadata("/path/to/pyproject.toml", "hash123", metadata)
        result = cache.get_project_metadata("/path/to/pyproject.toml", "different_hash")
        
        assert result is None

    def test_get_project_metadata_missing(self, temp_cache_dir):
        """Verify retrieving missing project metadata returns None.

        Scenario:
            Metadata is requested for a file path that was never cached.

        Execution Flow:
            1. Query `get_project_metadata` on a nonexistent path.
            2. Assert the result is None.

        Expectations:
            - Returns None.
        """
        cache = ResolutionCache(temp_cache_dir)
        result = cache.get_project_metadata("/nonexistent/path", "hash")
        assert result is None

    def test_compute_pkg_hash_deterministic(self, temp_cache_dir):
        """Verify that package hash computation is deterministic and of correct length.

        Scenario:
            A package hash is computed multiple times for the same input.

        Execution Flow:
            1. Compute hashes for identical inputs.
            2. Assert that both hashes are identical and have length 16.

        Expectations:
            - Deterministic hash output.
            - Length of the computed hash is exactly 16.
        """
        cache = ResolutionCache(temp_cache_dir)
        
        hash1 = cache._compute_pkg_hash("requests", "2.31.0", "pip")
        hash2 = cache._compute_pkg_hash("requests", "2.31.0", "pip")
        
        assert hash1 == hash2
        assert len(hash1) == 16  # First 16 chars of SHA256

    def test_compute_pkg_hash_different_inputs(self, temp_cache_dir):
        """Verify that package hash changes when inputs vary.

        Scenario:
            Package hashes are computed with different names, versions, or managers.

        Execution Flow:
            1. Compute hash for requests-2.31.0-pip.
            2. Compute hash for requests-2.32.0-pip.
            3. Compute hash for requests-2.31.0-conda.
            4. Assert that the hashes are distinct.

        Expectations:
            - Varying inputs produce unique hash digests.
        """
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
        """Verify thread safety when writing symbols concurrently.

        Scenario:
            Multiple threads concurrently call `put_symbols` on the cache.

        Execution Flow:
            1. Spin up a ThreadPoolExecutor with 10 workers.
            2. Submit 50 concurrent put tasks.
            3. Assert that no exceptions/errors were raised.
            4. Verify all 50 entries were successfully written.

        Expectations:
            - Thread-safe storage without corruption or locks.
            - All cached symbols are retrieved successfully.
        """
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
        """Verify thread safety when concurrently marking manifests as indexed.

        Scenario:
            Multiple threads concurrently call `mark_manifest_indexed`.

        Execution Flow:
            1. Spin up a ThreadPoolExecutor.
            2. Submit 50 concurrent marking operations.
            3. Verify that all indexing records are stored and correct.

        Expectations:
            - No exceptions are thrown.
            - All manifests are accurately recorded as indexed.
        """
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
        """Verify that the metadata cache is loaded lazily on demand.

        Scenario:
            A new ResolutionCache is initialized and metadata loading is tested.

        Execution Flow:
            1. Initialize ResolutionCache.
            2. Assert that metadata_loaded is False.
            3. Invoke `_load_metadata_cache()`.
            4. Assert that metadata_loaded is True.

        Expectations:
            - Metadata is not loaded automatically during instantiation.
            - Calling the load function successfully updates load state.
        """
        cache = ResolutionCache(temp_cache_dir)
        # Metadata cache should be empty before first access
        assert not cache._metadata_loaded
        
        # Access triggers load
        cache._load_metadata_cache()
        assert cache._metadata_loaded

    def test_metadata_cache_persists(self, temp_cache_dir):
        """Verify that cached project metadata persists across different ResolutionCache instances.

        Scenario:
            Metadata is cached in one instance and accessed via a second instance.

        Execution Flow:
            1. Write project metadata using `cache1`.
            2. Instantiate `cache2` referencing the same cache directory.
            3. Query and assert metadata from `cache2`.

        Expectations:
            - Metadata is persisted to disk and reloadable.
        """
        cache1 = ResolutionCache(temp_cache_dir)
        metadata = {"manager": "pip", "name": "proj", "version": "1.0.0", "source": ""}
        cache1.put_project_metadata("/path/to/file", "hash", metadata)
        
        # Create new cache instance pointing to same directory
        cache2 = ResolutionCache(temp_cache_dir)
        result = cache2.get_project_metadata("/path/to/file", "hash")
        
        assert result == metadata


class TestResolutionCacheAtomicWrites:
    """Tests for atomic write behavior in ResolutionCache."""

    @pytest.fixture
    def temp_cache_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            yield Path(tmp)

    def test_put_symbols_atomic_overwrite(self, temp_cache_dir):
        """Verify that put_symbols writes atomically — overwriting an existing cache file doesn't corrupt it.

        Scenario:
            A cache file exists for a package. put_symbols is called again for the same
            package with updated symbols. The file should be atomically replaced.

        Execution Flow:
            1. Write symbols for a package.
            2. Read them back to verify.
            3. Overwrite with different symbols.
            4. Read again — should get the new symbols, not corrupted data.

        Expectations:
            - The file is not corrupted after overwrite.
            - The new symbols are returned.
        """
        cache = ResolutionCache(temp_cache_dir)
        symbols_v1 = {"mod": ["func_v1"]}
        symbols_v2 = {"mod": ["func_v2"]}

        cache.put_symbols("pkg", "1.0.0", "pip", symbols_v1)
        assert cache.get_symbols("pkg", "1.0.0", "pip") == symbols_v1

        cache.put_symbols("pkg", "1.0.0", "pip", symbols_v2)
        assert cache.get_symbols("pkg", "1.0.0", "pip") == symbols_v2

    def test_save_index_atomic(self, temp_cache_dir):
        """Verify that _save_index writes atomically — the index file is valid after save.

        Scenario:
            The manifest index is saved and reloaded. The data should be consistent.

        Execution Flow:
            1. Mark several manifests as indexed.
            2. Create a new ResolutionCache pointing to the same directory.
            3. Verify the manifest index was loaded correctly.

        Expectations:
            - The index file is valid and loadable after atomic save.
        """
        cache1 = ResolutionCache(temp_cache_dir)
        cache1.mark_manifest_indexed("/path/to/file1", "hash1")
        cache1.mark_manifest_indexed("/path/to/file2", "hash2")

        # New instance should load the saved index
        cache2 = ResolutionCache(temp_cache_dir)
        assert not cache2.is_manifest_stale("/path/to/file1", "hash1")
        assert not cache2.is_manifest_stale("/path/to/file2", "hash2")
        assert cache2.is_manifest_stale("/path/to/file1", "wrong_hash")
