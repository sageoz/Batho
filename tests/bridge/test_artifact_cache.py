"""Tests for ArtifactCache."""

from __future__ import annotations

import pytest

from batho.bridge.artifact_cache import ArtifactCache, ArtifactCacheKey, CacheStats


class TestArtifactCache:
    """Test ArtifactCache functionality."""

    def test_put_and_get(self):
        """Putting and getting cache entries works."""
        cache = ArtifactCache(max_total_bytes=1000, max_per_workspace_bytes=500)
        key = ArtifactCacheKey(
            workspace_id="ws1",
            artifact_type="graph_json",
            file_path="/test/graph.json",
            file_mtime_ns=123456789,
            file_size=100,
            checksum="abc123",
        )
        cache.put(key, {"nodes": []}, 100)
        result = cache.get(key)
        assert result == {"nodes": []}

    def test_cache_miss(self):
        """Cache miss returns None."""
        cache = ArtifactCache(max_total_bytes=1000, max_per_workspace_bytes=500)
        key = ArtifactCacheKey(
            workspace_id="ws1",
            artifact_type="graph_json",
            file_path="/test/graph.json",
            file_mtime_ns=123456789,
            file_size=100,
            checksum="abc123",
        )
        result = cache.get(key)
        assert result is None

    def test_lru_eviction(self):
        """LRU eviction works when cache is full."""
        cache = ArtifactCache(max_total_bytes=200, max_per_workspace_bytes=200)
        key1 = ArtifactCacheKey(
            workspace_id="ws1",
            artifact_type="graph_json",
            file_path="/test/graph1.json",
            file_mtime_ns=123456789,
            file_size=100,
            checksum="abc123",
        )
        key2 = ArtifactCacheKey(
            workspace_id="ws1",
            artifact_type="graph_json",
            file_path="/test/graph2.json",
            file_mtime_ns=123456790,
            file_size=100,
            checksum="def456",
        )
        key3 = ArtifactCacheKey(
            workspace_id="ws1",
            artifact_type="graph_json",
            file_path="/test/graph3.json",
            file_mtime_ns=123456791,
            file_size=100,
            checksum="ghi789",
        )
        cache.put(key1, {"data": "1"}, 100)
        cache.put(key2, {"data": "2"}, 100)
        cache.put(key3, {"data": "3"}, 100)
        assert cache.get(key1) is None
        assert cache.get(key2) == {"data": "2"}
        assert cache.get(key3) == {"data": "3"}

    def test_invalidate_workspace(self):
        """Invalidating workspace removes all its entries."""
        cache = ArtifactCache(max_total_bytes=1000, max_per_workspace_bytes=500)
        key1 = ArtifactCacheKey(
            workspace_id="ws1",
            artifact_type="graph_json",
            file_path="/test/graph1.json",
            file_mtime_ns=123456789,
            file_size=100,
            checksum="abc123",
        )
        key2 = ArtifactCacheKey(
            workspace_id="ws2",
            artifact_type="graph_json",
            file_path="/test/graph2.json",
            file_mtime_ns=123456790,
            file_size=100,
            checksum="def456",
        )
        cache.put(key1, {"data": "1"}, 100)
        cache.put(key2, {"data": "2"}, 100)
        count = cache.invalidate_workspace("ws1")
        assert count == 1
        assert cache.get(key1) is None
        assert cache.get(key2) == {"data": "2"}

    def test_stats(self):
        """Stats track cache operations."""
        cache = ArtifactCache(max_total_bytes=1000, max_per_workspace_bytes=500)
        key = ArtifactCacheKey(
            workspace_id="ws1",
            artifact_type="graph_json",
            file_path="/test/graph.json",
            file_mtime_ns=123456789,
            file_size=100,
            checksum="abc123",
        )
        cache.get(key)
        cache.put(key, {"data": "test"}, 100)
        cache.get(key)
        stats = cache.stats()
        assert stats.misses == 1
        assert stats.hits == 1
        assert stats.total_entries == 1

    def test_single_flight(self):
        """Single-flight prevents duplicate loads."""
        cache = ArtifactCache(max_total_bytes=1000, max_per_workspace_bytes=500)
        key = ArtifactCacheKey(
            workspace_id="ws1",
            artifact_type="graph_json",
            file_path="/test/graph.json",
            file_mtime_ns=123456789,
            file_size=100,
            checksum="abc123",
        )
        assert cache.acquire_single_flight(key) is True
        assert cache.acquire_single_flight(key) is False
        cache.release_single_flight(key)
        assert cache.acquire_single_flight(key) is True
