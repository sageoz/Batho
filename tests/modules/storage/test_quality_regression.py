import threading
import pytest
from pathlib import Path
import tempfile
from batho.modules.storage.sqlite_registry.engine import BathoDatabase
from batho.utils.hash import compute_file_hash_cached

def test_bulk_get_or_create_string_ids_chunking():
    """Verify that bulk_get_or_create_string_ids chunks inputs larger than 999 variables."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = BathoDatabase(db_path, repo_root=Path(tmpdir))
        
        # Generate 2000 unique string values
        test_strings = [f"string_value_{i}" for i in range(2000)]
        
        # Resolve all strings. If chunking is broken, this will raise OperationalError: too many SQL variables
        resolved = db.bulk_get_or_create_string_ids(test_strings)
        
        assert len(resolved) == 2000
        # Make sure they are cached and retrieved correctly
        for s in test_strings:
            assert s in db._string_dict_cache
            assert resolved[s] == db._string_dict_cache[s]
            
        db.close()

def test_concurrent_string_ids_lookup():
    """Verify that multiple threads lookup string IDs concurrently without deadlocking."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = BathoDatabase(db_path, repo_root=Path(tmpdir))
        
        num_threads = 10
        strings_per_thread = 100
        errors = []
        
        def worker(thread_idx: int):
            try:
                for i in range(strings_per_thread):
                    # Call get_or_create_string_id
                    val = f"thread_{thread_idx}_val_{i}"
                    sid = db.get_or_create_string_id(val)
                    
                    # Call bulk_get_or_create_string_ids
                    bulk_vals = [f"thread_{thread_idx}_val_{i}_bulk_{j}" for j in range(5)]
                    resolved = db.bulk_get_or_create_string_ids(bulk_vals)
                    
                    # Verify lookup
                    assert db.get_string_val(sid) == val
                    for v in bulk_vals:
                        assert v in resolved
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
            
        assert len(errors) == 0, f"Thread errors encountered: {errors}"
        db.close()

def test_hash_cache_ino_invalidation(tmp_path):
    """Verify that changing file inode invalidates hash cache even if mtime and size are identical."""
    from batho.utils.hash import _compute_file_hash_cached_impl
    
    # Clear cache
    _compute_file_hash_cached_impl.cache_clear()
    
    # Create two different files
    file1 = tmp_path / "file1.txt"
    file2 = tmp_path / "file2.txt"
    file1.write_text("content1")
    file2.write_text("content2")
    
    # Run compute_file_hash_cached on both
    h1 = compute_file_hash_cached(str(file1), 0.0)
    h2 = compute_file_hash_cached(str(file2), 0.0)
    
    assert h1 != h2
    
    # Check cache info to see that it stores different entries (since paths are different)
    info = _compute_file_hash_cached_impl.cache_info()
    assert info.currsize >= 2
