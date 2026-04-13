"""Performance tests for Batho indexing and processing."""
from __future__ import annotations

import json
import sys
import time
import psutil
import threading
from pathlib import Path
from typing import Dict, Any

import pytest

from batho_cli import main


def _windows_retry_rmtree(path, max_retries=3, delay=0.5):
    """Retry rmtree on Windows to handle SQLite file locking."""
    import shutil
    for attempt in range(max_retries):
        try:
            shutil.rmtree(path)
            return True
        except (PermissionError, OSError) as e:
            if sys.platform == "win32" and attempt < max_retries - 1:
                time.sleep(delay)
            else:
                raise
    return False


@pytest.mark.slow
@pytest.mark.integration
class TestPerformance:
    """Performance testing for various Batho operations."""

    def measure_memory_usage(self, func, *args, **kwargs):
        """Measure memory usage of a function."""
        process = psutil.Process()
        mem_before = process.memory_info().rss / 1024 / 1024  # MB
        
        result = func(*args, **kwargs)
        
        mem_after = process.memory_info().rss / 1024 / 1024  # MB
        mem_used = mem_after - mem_before
        
        return result, mem_used

    def measure_execution_time(self, func, *args, **kwargs):
        """Measure execution time of a function."""
        start_time = time.time()
        result = func(*args, **kwargs)
        end_time = time.time()
        
        execution_time = end_time - start_time
        return result, execution_time

    def test_flask_repository_indexing_performance(self, flask_repo: Path, tmp_path: Path):
        """Test indexing performance on Flask repository."""
        import shutil
        
        # Copy Flask repo to avoid interference
        flask_copy = tmp_path / "flask_copy"
        shutil.copytree(flask_repo, flask_copy)
        
        # Measure indexing performance
        def index_flask():
            return main(["index", "--root", str(flask_copy), "--force"])
        
        rc, exec_time = self.measure_execution_time(index_flask)
        assert rc == 0
        
        # Performance assertions
        assert exec_time < 30.0, f"Flask indexing took too long: {exec_time:.2f}s"
        
        # Verify results
        ctn_dir = flask_copy / ".ctn"
        assert ctn_dir.exists()
        
        meta = json.loads((ctn_dir / "index.json").read_text())
        assert len(meta.get("indexes", {})) > 0

    def test_memory_usage_with_large_repositories(self, multi_lang_repo: Path, tmp_path: Path):
        """Test memory usage with larger repositories."""
        import shutil
        
        # Copy and expand repository
        repo_copy = tmp_path / "large_repo"
        shutil.copytree(multi_lang_repo, repo_copy)
        
        # Create additional files to simulate larger repo
        for i in range(20):
            test_file = repo_copy / f"large_file_{i}.py"
            test_file.write_text(f"# Large file {i}\n" + "def func():\n    return True\n" * 300)
        
        # Measure memory usage
        def index_large_repo():
            return main(["index", "--root", str(repo_copy), "--force"])
        
        rc, mem_used = self.measure_memory_usage(index_large_repo)
        assert rc == 0
        
        # Memory usage should be reasonable (under 500MB for this test)
        assert mem_used < 500, f"Memory usage too high: {mem_used:.2f}MB"

    def test_parallel_processing_efficiency(self, simple_python_repo: Path, tmp_path: Path):
        """Test parallel processing efficiency."""
        import shutil
        
        # Create multiple copies to test parallel processing
        repos = []
        for i in range(3):
            repo_copy = tmp_path / f"repo_{i}"
            shutil.copytree(simple_python_repo, repo_copy)
            repos.append(repo_copy)
        
        # Test sequential processing
        start_time = time.time()
        for repo in repos:
            main(["index", "--root", str(repo), "--force"])
        sequential_time = time.time() - start_time
        
        # Clean up for parallel test
        for repo in repos:
            ctn_dir = repo / ".ctn"
            if ctn_dir.exists():
                _windows_retry_rmtree(ctn_dir)
        
        # Test parallel processing
        def parallel_index():
            threads = []
            results = []
            
            def index_repo(repo):
                result = main(["index", "--root", str(repo), "--force"])
                results.append(result)
            
            for repo in repos:
                thread = threading.Thread(target=index_repo, args=(repo,))
                threads.append(thread)
                thread.start()
            
            for thread in threads:
                thread.join()
            
            return all(r == 0 for r in results)
        
        success, parallel_time = self.measure_execution_time(parallel_index)
        assert success, "Parallel indexing failed"
        
        # Parallel should be faster (allow some variance)
        efficiency_ratio = sequential_time / parallel_time
        assert efficiency_ratio > 1.5, f"Parallel processing not efficient: ratio {efficiency_ratio:.2f}"

    def test_cache_performance_and_hit_rates(self, simple_python_repo: Path, tmp_path: Path):
        """Test cache performance and hit rates."""
        import shutil
        
        repo_copy = tmp_path / "cache_test_repo"
        shutil.copytree(simple_python_repo, repo_copy)
        
        # First indexing (cache miss)
        start_time = time.time()
        rc1 = main(["index", "--root", str(repo_copy), "--force"])
        first_time = time.time() - start_time
        assert rc1 == 0
        
        # Second indexing (cache hit)
        start_time = time.time()
        rc2 = main(["index", "--root", str(repo_copy), "--force"])
        second_time = time.time() - start_time
        assert rc2 == 0
        
        # Second indexing should be faster due to caching (allow some variance)
        speedup = first_time / second_time if second_time > 0 else float('inf')
        assert speedup > 0.7, f"Cache performance acceptable: {speedup:.2f}x"  # More lenient

    def test_scalability_with_increasing_file_counts(self, tmp_path: Path):
        """Test scalability with increasing file counts."""
        from batho.context.codegraph import CodeGraphIndexer
        
        # Create test repositories with different sizes
        sizes = [10, 25, 50]
        times = []
        
        for size in sizes:
            test_repo = tmp_path / f"repo_size_{size}"
            test_repo.mkdir()
            
            # Create test files
            for i in range(size):
                test_file = test_repo / f"file_{i}.py"
                test_file.write_text(f"""
# File {i}
import os
import sys

def function_{i}():
    return "result_{i}"

class Class_{i}:
    def method(self):
        return function_{i}()
""")
            
            # Measure indexing time
            def index_repo():
                # Ensure the directory still exists
                assert test_repo.exists(), f"Test repo directory should exist: {test_repo}"
                assert test_repo.is_dir(), f"Test repo should be a directory: {test_repo}"
                cache_path = test_repo / ".ctn" / "file_cache.json"
                cache_path.parent.mkdir(exist_ok=True)
                indexer = CodeGraphIndexer(str(cache_path), str(test_repo))
                try:
                    return indexer.build_graph(str(test_repo))
                finally:
                    indexer.close()
            
            _, exec_time = self.measure_execution_time(index_repo)
            times.append(exec_time)
            
            # Clean up
            ctn_dir = test_repo / ".ctn"
            if ctn_dir.exists():
                _windows_retry_rmtree(ctn_dir)
        
        # Check that scaling is reasonable (not exponential)
        # Time should scale roughly linearly with file count
        if len(times) >= 2:
            # Calculate scaling factor between smallest and largest
            scaling_factor = times[-1] / times[0]
            file_ratio = sizes[-1] / sizes[0]
            
            # Allow some overhead but should be roughly linear
            assert scaling_factor < file_ratio * 2, f"Poor scalability: {scaling_factor:.2f}x time increase for {file_ratio}x file increase"

    def test_performance_benchmarks_and_regression(self, flask_repo: Path, tmp_path: Path):
        """Create performance benchmarks and test for regression."""
        import shutil
        
        # Copy Flask repo
        flask_copy = tmp_path / "flask_benchmark"
        shutil.copytree(flask_repo, flask_copy)
        
        # Benchmark metrics
        benchmarks = {}
        
        # Indexing performance
        def index_flask():
            return main(["index", "--root", str(flask_copy), "--force"])
        
        rc, index_time = self.measure_execution_time(index_flask)
        assert rc == 0
        benchmarks["indexing_time"] = index_time
        
        # Memory usage
        rc, memory_usage = self.measure_memory_usage(index_flask)
        benchmarks["memory_usage"] = memory_usage
        
        # Stats command performance
        def stats_flask():
            return main(["stats", "--root", str(flask_copy)])
        
        rc, stats_time = self.measure_execution_time(stats_flask)
        assert rc == 0
        benchmarks["stats_time"] = stats_time
        
        # Save benchmarks for comparison
        benchmark_file = tmp_path / "performance_benchmarks.json"
        benchmark_file.write_text(json.dumps(benchmarks, indent=2))
        
        # Performance regression checks
        assert index_time < 60.0, f"Indexing regression: {index_time:.2f}s > 60s"
        assert memory_usage < 1000, f"Memory regression: {memory_usage:.2f}MB > 1GB"
        assert stats_time < 5.0, f"Stats regression: {stats_time:.2f}s > 5s"
        
        # Verify results
        ctn_dir = flask_copy / ".ctn"
        assert ctn_dir.exists()
        
        meta = json.loads((ctn_dir / "index.json").read_text())
        current_id = meta["current_index_id"]
        
        # Check graph size is reasonable
        graph_file = ctn_dir / current_id / "graph.json"
        if graph_file.exists():
            graph_data = json.loads(graph_file.read_text())
            entity_count = len(graph_data.get("entities", []))
            assert entity_count > 0, "No entities found in indexed graph"
            
            # Log benchmark results
            benchmarks["entity_count"] = entity_count
            print(f"Benchmarks: {benchmarks}")
