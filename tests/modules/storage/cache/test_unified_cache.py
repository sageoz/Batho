"""Unit tests for Batho's unified storage cache.

This module validates the correctness of the unified cache mechanism, ensuring that
snapshots are successfully stored, retrieved, capped at the maximum item threshold (1000 items),
and properly evicted using a Least Recently Used (LRU) policy.
"""

from __future__ import annotations

import pytest
from batho.modules.storage.cache.unified_cache import BathoCache
from batho.core.schemas import FileSnapshot


def test_unified_cache_lru_eviction():
    """Verify that unified cache snapshots are capped at 1000 items and follow LRU eviction.

    Scenario:
        We populate the unified cache with 1005 items, which exceeds the max capacity of 1000.
        The cache must evict the first 5 elements (oldest, least recently used) to enforce the limit,
        while preserving the most recently inserted 1000 items.

    Execution Flow:
        1. Initialize `BathoCache`.
        2. In a loop, insert 1005 file snapshot objects (`file_0.py` to `file_1004.py`) into the cache.
        3. Retrieve cache stats and verify that the current snapshot count is exactly 1000.
        4. Attempt to fetch each of the first 5 inserted items (`file_0.py` to `file_4.py`) and assert they are None (evicted).
        5. Fetch `file_5.py` and assert that it is successfully retrieved (not evicted).

    Expectations:
        - The cache never exceeds the hard limit of 1000 items.
        - Oldest, unaccessed elements are evicted first when the limit is breached.
        - Retrieval of active items functions normally.
    """
    cache = BathoCache()

    # Insert 1005 snapshots (limit is 1000)
    for i in range(1005):
        snap = FileSnapshot(file_path=f"file_{i}.py", file_hash=f"hash_{i}")
        cache.set_file_snapshot(snap)

    # Check stats - snapshot count should be strictly capped at 1000
    stats = cache.get_stats()
    assert stats["snapshot_count"] == 1000

    # The first 5 files should be evicted (file_0 to file_4)
    for i in range(5):
        assert cache.get_file_snapshot(f"file_{i}.py") is None

    # file_5 should be present and retrieveable
    assert cache.get_file_snapshot("file_5.py") is not None
