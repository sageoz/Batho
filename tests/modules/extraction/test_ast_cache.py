"""Unit tests for Batho's AST extraction cache.

This module validates that the AST Cache system can:
1. Correctly clean up older cache entries based on a threshold number of days.
2. Stale content hash entries are automatically purged when file content changes.
3. Manifest operations are properly synchronized and thread-safe using a locking mechanism.
"""

from __future__ import annotations

import os
import time
import threading
import pytest
from pathlib import Path

from batho.modules.extraction.ast_cache import AstCache
from batho.core.schemas import Entity, Relationship, RelationshipType, EntityType


def test_ast_cache_clear_older_than_days(tmp_path: Path):
    """Verify that AstCache.clear(older_than_days) selectively deletes old entries and updates the manifest.

    Scenario:
        The cache has one old entry (mtime set back 10 days) and one fresh entry.
        Calling `clear(older_than_days=5)` should delete the old entry's msgpack file,
        keep the fresh entry, and remove the old entry's reference from the manifest.

    Execution Flow:
        1. Initialize `AstCache` with `tmp_path`.
        2. Set AST for `foo.py` with content hash "hash1".
        3. Assert that the cache file exists on disk.
        4. Artificially backdate the mtime of `foo.py`'s cache file to 10 days ago.
        5. Set AST for `bar.py` with content hash "hash2" (representing a fresh entry).
        6. Assert both files exist.
        7. Invoke `cache.clear(older_than_days=5)`.
        8. Assert that the returned deleted count is 1.
        9. Assert that the old file is deleted and the fresh file remains.
        10. Load the manifest and assert that "foo.py" is removed while "bar.py" is still present.

    Expectations:
        - Only cache files older than the specified threshold are garbage-collected.
        - Manifest is kept in sync with the actual files remaining on disk.
    """
    cache = AstCache(tmp_path)
    
    # Write a cache entry
    cache.set_ast(
        file_path="foo.py",
        content_hash="hash1",
        variant="v1",
        entities=[],
        relationships=[],
        mtime=1.0,
        size=10
    )
    
    key1 = cache._compute_key("foo.py", "hash1", "v1")
    file1 = cache.ast_dir / f"{key1}.msgpack"
    assert file1.exists()

    # Backdate file1 st_mtime to 10 days ago (10 * 24 * 3600 seconds)
    ten_days_ago = time.time() - (10 * 86400)
    os.utime(file1, (ten_days_ago, ten_days_ago))

    # Write a fresh cache entry
    cache.set_ast(
        file_path="bar.py",
        content_hash="hash2",
        variant="v1",
        entities=[],
        relationships=[],
        mtime=2.0,
        size=20
    )
    
    key2 = cache._compute_key("bar.py", "hash2", "v1")
    file2 = cache.ast_dir / f"{key2}.msgpack"
    assert file2.exists()

    # Clear entries older than 5 days
    deleted_count = cache.clear(older_than_days=5)
    assert deleted_count == 1
    
    assert not file1.exists()
    assert file2.exists()
    
    manifest = cache._load_manifest_for_gc()
    assert "foo.py" not in manifest
    assert "bar.py" in manifest


def test_ast_cache_stale_purging(tmp_path: Path):
    """Verify that older content_hash entries are deleted from disk/manifest when a file's content changes.

    Scenario:
        We write an AST cache entry for a file. Later, the file's content changes (new content hash).
        Writing the new AST entry should automatically purge the old content hash's cache file and
        manifest records to prevent unbounded disk growth.

    Execution Flow:
        1. Initialize `AstCache`.
        2. Set AST for `src/main.py` under "content_hash_1".
        3. Verify that the cache file and manifest entry exist.
        4. Set AST for `src/main.py` under a new hash "content_hash_2".
        5. Verify that the old cache file is deleted, the new cache file is created,
           and the manifest is updated to reference only the new key.

    Expectations:
        - Outdated cache entries for the same file path are deleted on new writes.
        - Manifest references are cleaned up.
    """
    ast_cache = AstCache(tmp_path)

    file_path = "src/main.py"
    entities = [Entity(type=EntityType.FUNCTION, name="func1", file=file_path, start_line=1, end_line=5)]
    rels = [Relationship(source_id="e1", target_id="e2", type=RelationshipType.CALLS)]

    # Write variant 1 under content_hash_1
    ast_cache.set_ast(
        file_path=file_path,
        content_hash="content_hash_1",
        variant="v1",
        entities=entities,
        relationships=rels,
        mtime=1234.56,
        size=100
    )

    # Verify files exist on disk
    key1 = ast_cache._compute_key(file_path, "content_hash_1", "v1")
    file1 = ast_cache.ast_dir / f"{key1}.msgpack"
    assert file1.exists()

    manifest = ast_cache._load_manifest_for_gc()
    assert file_path in manifest
    assert key1 in manifest[file_path]

    # Write a new variant under content_hash_2 (content has changed)
    ast_cache.set_ast(
        file_path=file_path,
        content_hash="content_hash_2",
        variant="v1",
        entities=entities,
        relationships=rels,
        mtime=1234.57,
        size=105
    )

    # Verify that file1 is deleted and file2 exists
    key2 = ast_cache._compute_key(file_path, "content_hash_2", "v1")
    file2 = ast_cache.ast_dir / f"{key2}.msgpack"
    
    assert not file1.exists()
    assert file2.exists()

    manifest = ast_cache._load_manifest_for_gc()
    assert key1 not in manifest[file_path]
    assert key2 in manifest[file_path]


def test_ast_cache_manifest_locking(tmp_path: Path):
    """Test that the manifest locking context manager serializes concurrent access.

    Scenario:
        Multiple threads attempt to write to/access the AST cache manifest at the same time.
        The internal manifest lock must serialize these operations, ensuring that the start
        and end operations of a thread are never interleaved by another thread.

    Execution Flow:
        1. Define a worker function that acquires `ast_cache._lock_manifest()`, appends a start tag
           to a list, sleeps briefly, and then appends an end tag.
        2. Spin up 3 concurrent threads running this worker.
        3. Join all threads.
        4. Validate that the logged results list consists of paired contiguous start/end tags from
           the same thread (e.g., [T1-start, T1-end, T2-start, T2-end, ...]).

    Expectations:
        - Thread safety: manifest operations are fully serialized.
        - No race conditions or dirty interleavings occur during concurrent access.
    """
    ast_cache = AstCache(tmp_path)
    
    results = []
    
    def worker(worker_id):
        with ast_cache._lock_manifest():
            results.append(f"{worker_id}-start")
            time.sleep(0.05)
            results.append(f"{worker_id}-end")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # The start and end tags must not be interleaved because of the lock
    for i in range(0, len(results), 2):
        start = results[i]
        end = results[i+1]
        assert start.split("-")[0] == end.split("-")[0]
        assert "start" in start
        assert "end" in end
